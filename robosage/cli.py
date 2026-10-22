"""
RoboSage CLI: The AI Robotics Assistant & Diagnostic Copilot.
Provides interactive chat, loophole auditing, log triage, real-time monitoring,
and safe node scaffolding.
"""

import argparse
import os
from pathlib import Path
import sys
from typing import List, Optional

from robosage.agent.core import AgentSession
from robosage.diagnostics.log_analyzer import ROS2LogAnalyzer
from robosage.diagnostics.loophole_detector import LoopholeDetector, LoopholeSeverity
from robosage.diagnostics.qos_checker import (
    DurabilityPolicy,
    QoSProfile,
    ReliabilityPolicy,
    check_qos_compatibility,
)
from robosage.diagnostics.workspace_inspector import WorkspaceInspector
from robosage.llm.provider import get_llm_provider
from robosage.monitor.log_watcher import LogWatcher
from robosage.templates.generator import TemplateGenerator

# ANSI color formatting for terminal
class Colors:
    CYAN = "\033[96m"
    GREEN = "\033[92m"
    YELLOW = "\033[93m"
    RED = "\033[91m"
    BOLD = "\033[1m"
    UNDERLINE = "\033[4m"
    RESET = "\033[0m"
    MAGENTA = "\033[95m"


def print_banner():
    banner = f"""
{Colors.CYAN}{Colors.BOLD}╔═══════════════════════════════════════════════════════════════════╗
║   🤖  ROBOSAGE : AI Senior Robotics Assistant & Safety Auditor    ║
║         ROS 2 Diagnostics • Concurrency • Loophole Fuzzer         ║
╚═══════════════════════════════════════════════════════════════════╝{Colors.RESET}
"""
    print(banner)


def cmd_chat(args):
    """Starts an interactive pair-programming session with the robotics agent."""
    print_banner()
    provider = get_llm_provider(
        provider_name=args.provider,
        api_key=args.api_key,
        model=args.model,
    )
    session = AgentSession(provider=provider)

    print(f"{Colors.GREEN}Active Provider:{Colors.RESET} {provider.__class__.__name__}")
    print(f"{Colors.YELLOW}Type your robotics question, paste error logs, or provide a file path to audit.")
    print(f"Commands: 'reset' to clear history, 'exit' or 'quit' to end session.{Colors.RESET}\n")

    while True:
        try:
            user_input = input(f"{Colors.BOLD}{Colors.CYAN}RoboEngineer ➜ {Colors.RESET}").strip()
            if not user_input:
                continue

            if user_input.lower() in ("exit", "quit", "q"):
                print(f"\n{Colors.GREEN}Shutting down RoboSage session. Keep your robots safe!{Colors.RESET}")
                break

            if user_input.lower() == "reset":
                session.reset()
                print(f"{Colors.YELLOW}Session conversation history cleared.{Colors.RESET}\n")
                continue

            print(f"\n{Colors.MAGENTA}Thinking...{Colors.RESET}")
            reply = session.step(user_input)
            print(f"\n{Colors.BOLD}{Colors.GREEN}RoboSage ➜{Colors.RESET}\n{reply}\n")

        except (KeyboardInterrupt, EOFError):
            print(f"\n{Colors.GREEN}Session terminated.{Colors.RESET}")
            break


def cmd_audit(args):
    """Audits source code or directory for safety loopholes and edge cases."""
    print_banner()
    target_path = os.path.abspath(args.path)
    print(f"🔍 {Colors.BOLD}Scanning target for robotics loopholes:{Colors.RESET} {target_path}\n")

    detector = LoopholeDetector()
    if os.path.isdir(target_path):
        findings = detector.audit_directory(target_path)
    elif os.path.isfile(target_path):
        findings = detector.audit_file(target_path)
    else:
        print(f"{Colors.RED}Error: Path '{target_path}' does not exist.{Colors.RESET}")
        sys.exit(1)

    if not findings:
        print(f"{Colors.GREEN}✅ Audit Passed: No safety loopholes, deadlocks, or unprotected sensor calls found!{Colors.RESET}\n")
        return

    # Sort findings by severity: CRITICAL > HIGH > MEDIUM > LOW
    severity_order = {
        LoopholeSeverity.CRITICAL: 0,
        LoopholeSeverity.HIGH: 1,
        LoopholeSeverity.MEDIUM: 2,
        LoopholeSeverity.LOW: 3,
    }
    findings.sort(key=lambda x: severity_order.get(x.severity, 99))

    print(f"{Colors.RED}{Colors.BOLD}Found {len(findings)} potential safety loophole(s):{Colors.RESET}\n")
    for idx, f in enumerate(findings, 1):
        color = Colors.RED if f.severity in (LoopholeSeverity.CRITICAL, LoopholeSeverity.HIGH) else Colors.YELLOW
        line_info = f":{f.line_number}" if f.line_number else ""
        rel_path = os.path.relpath(f.file_path, os.getcwd()) if f.file_path.startswith(os.getcwd()) else f.file_path

        print(f"{color}[{idx}] [{f.severity.value}] {f.title}{Colors.RESET}")
        print(f"    {Colors.BOLD}Location:{Colors.RESET}    {rel_path}{line_info}")
        print(f"    {Colors.BOLD}Loophole:{Colors.RESET}    {f.description}")
        print(f"    {Colors.BOLD}Hazard:{Colors.RESET}      {Colors.RED}{f.impact}{Colors.RESET}")
        print(f"    {Colors.BOLD}Remediation:{Colors.RESET} {f.recommended_fix}")
        if f.sample_patch:
            print(f"\n    {Colors.CYAN}{Colors.BOLD}Recommended Code Patch:{Colors.RESET}")
            indented = "\n".join("    " + line for line in f.sample_patch.split("\n"))
            print(f"{indented}")
        print("-" * 70)

    if getattr(args, "sarif", None):
        from robosage.diagnostics.sarif_exporter import SarifExporter
        dict_findings = [
            {
                "loophole_type": f.loophole_type.value,
                "severity": f.severity.value,
                "title": f.title,
                "description": f.description,
                "impact": f.impact,
                "recommended_fix": f.recommended_fix,
                "line_number": f.line_number,
                "file_path": f.file_path,
            }
            for f in findings
        ]
        sarif_content = SarifExporter.to_json_str(dict_findings, target_file=target_path)
        sarif_path = Path(args.sarif).resolve()
        sarif_path.parent.mkdir(parents=True, exist_ok=True)
        with open(sarif_path, "w", encoding="utf-8") as sf:
            sf.write(sarif_content)
        print(f"\n{Colors.GREEN}🛡️ OASIS SARIF v2.1.0 report exported to:{Colors.RESET} {sarif_path}")


def cmd_triage(args):
    """Diagnoses a ROS 2 log file, terminal output, or stack trace."""
    print_banner()
    analyzer = ROS2LogAnalyzer()

    # Read from file or argument string
    if os.path.isfile(args.target):
        with open(args.target, "r", encoding="utf-8", errors="ignore") as f:
            content = f.read()
        print(f"📋 Ingested log file: {args.target}")
    else:
        content = args.target

    incidents = analyzer.analyze_text(content)
    if not incidents:
        print(f"{Colors.YELLOW}No explicit ROS 2 crashes, QoS mismatches, or TF anomalies detected in log.{Colors.RESET}")
        return

    print(f"{Colors.BOLD}{Colors.RED}Triaged {len(incidents)} Incident(s):{Colors.RESET}\n")
    for i, inc in enumerate(incidents, 1):
        color = Colors.RED if inc.severity.value in ("FATAL", "ERROR") else Colors.YELLOW
        print(f"{color}Incident #{i}: [{inc.severity.value}] {inc.category.value}{Colors.RESET}")
        print(f"{Colors.BOLD}Summary:{Colors.RESET}    {inc.summary}")
        print(f"{Colors.BOLD}Root Cause:{Colors.RESET} {inc.root_cause}")
        if inc.remediation_steps:
            print(f"{Colors.BOLD}Action Plan:{Colors.RESET}")
            for step in inc.remediation_steps:
                print(f"  ➜ {step}")
        if inc.code_fix:
            print(f"\n{Colors.CYAN}{Colors.BOLD}Fix Snippet:{Colors.RESET}")
            print(inc.code_fix)
        print("=" * 70)


def cmd_watch(args):
    """Starts live log watcher on standard input or latest ROS log file."""
    print_banner()
    watcher = LogWatcher()

    if not sys.stdin.isatty():
        print(f"{Colors.GREEN}Listening to piped ROS 2 output stream in real-time...{Colors.RESET}")
        watcher.watch_stream(sys.stdin)
    else:
        log_path = args.path
        if not log_path:
            latest = LogWatcher.find_latest_ros_log_dir()
            if latest:
                # Look for launch.log or rosout.log
                cand = os.path.join(latest, "launch.log")
                log_path = cand if os.path.exists(cand) else latest
            else:
                print(f"{Colors.RED}No active ~/.ros/log found and no log file specified.{Colors.RESET}")
                print("Usage: robosage watch /path/to/logfile.log OR ros2 launch ... | robosage watch")
                sys.exit(1)

        print(f"{Colors.GREEN}Tailing live log file:{Colors.RESET} {log_path}")
        print(f"{Colors.YELLOW}Press Ctrl+C to stop watcher.{Colors.RESET}\n")
        try:
            watcher.watch_file(log_path)
        except KeyboardInterrupt:
            print(f"\n{Colors.GREEN}Watcher stopped.{Colors.RESET}")


def cmd_generate(args):
    """Scaffolds safe, boilerplate ROS 2 node templates."""
    print_banner()
    templates = {
        "diff_drive": TemplateGenerator.safe_diff_drive,
        "tf_listener": TemplateGenerator.tf_listener,
        "multithreaded": TemplateGenerator.multithreaded_safe_node,
    }

    t_type = args.template.lower()
    if t_type not in templates:
        print(f"{Colors.RED}Unknown template '{t_type}'. Available: {', '.join(templates.keys())}{Colors.RESET}")
        sys.exit(1)

    node_name = args.name or f"safe_{t_type}_node"
    code = templates[t_type](node_name=node_name)

    if args.output:
        out_path = Path(args.output)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        with open(out_path, "w", encoding="utf-8") as f:
            f.write(code)
        print(f"{Colors.GREEN}✅ Successfully generated safe template '{t_type}' at:{Colors.RESET} {out_path}")
    else:
        print(code)


def cmd_improve(args):
    """Uses local Qwen to refactor and optimize robotics code."""
    print_banner()
    from robosage.llm.provider import QwenProvider

    target_path = os.path.abspath(args.path)
    if not os.path.isfile(target_path):
        print(f"{Colors.RED}File '{target_path}' not found.{Colors.RESET}")
        sys.exit(1)

    with open(target_path, "r", encoding="utf-8") as f:
        code = f.read()

    print(f"🤖 {Colors.BOLD}Analyzing and optimizing robotics code with Qwen...{Colors.RESET}")
    print(f"Target: {target_path}")
    print(f"Focus:  {args.focus.upper()}\n")

    qwen = QwenProvider(model=args.model, endpoint=args.endpoint)
    try:
        improved = qwen.improve_code(code, focus=args.focus)
        if args.output:
            out_p = os.path.abspath(args.output)
            with open(out_p, "w", encoding="utf-8") as f:
                f.write(improved)
            print(f"{Colors.GREEN}✅ Successfully saved improved code to: {out_p}{Colors.RESET}")
        else:
            print(f"{Colors.CYAN}{Colors.BOLD}--- QWEN IMPROVED ROBOTICS CODE ---{Colors.RESET}\n")
            print(improved)
    except Exception as e:
        print(f"{Colors.YELLOW}Notice: Could not connect to local Qwen server ({e}).{Colors.RESET}")
        print("Tip: Start Qwen using `ollama run qwen2.5-coder` or your local model runner.\n")
        print("Running static loophole scan instead:")
        from robosage.diagnostics.loophole_detector import LoopholeDetector
        d = LoopholeDetector()
        findings = d.audit_file(target_path)
        for f in findings:
            print(f"  • [{f.severity.value}] {f.title}: {f.recommended_fix}")


def cmd_check_qos(args):
    """Validates DDS QoS compatibility."""
    print_banner()
    try:
        pub_q = QoSProfile(
            reliability=ReliabilityPolicy(args.pub_reliability.upper()),
            durability=DurabilityPolicy(args.pub_durability.upper()),
        )
        sub_q = QoSProfile(
            reliability=ReliabilityPolicy(args.sub_reliability.upper()),
            durability=DurabilityPolicy(args.sub_durability.upper()),
        )
        res = check_qos_compatibility(pub_q, sub_q)

        status_color = Colors.GREEN if res.is_compatible else Colors.RED
        status_text = "COMPATIBLE" if res.is_compatible else "INCOMPATIBLE"
        print(f"QoS Evaluation: {status_color}{Colors.BOLD}{status_text}{Colors.RESET}\n")

        print(f"{Colors.BOLD}Publisher Offered:{Colors.RESET}   Reliability={pub_q.reliability.value}, Durability={pub_q.durability.value}")
        print(f"{Colors.BOLD}Subscriber Request:{Colors.RESET}  Reliability={sub_q.reliability.value}, Durability={sub_q.durability.value}\n")

        if res.issues:
            print(f"{Colors.RED}{Colors.BOLD}Issues Detected:{Colors.RESET}")
            for issue in res.issues:
                print(f"  ❌ {issue}")
        if res.recommendations:
            print(f"\n{Colors.CYAN}{Colors.BOLD}Remediation:{Colors.RESET}")
            for rec in res.recommendations:
                print(f"  ➜ {rec}")

    except Exception as e:
        print(f"{Colors.RED}Error validating QoS: {e}{Colors.RESET}")


def cmd_doctor(args):
    """Inspects the local robotics environment, ROS 2 configuration, and LLM backend."""
    print_banner()
    print(f"{Colors.BOLD}🩺 RoboSage Environment Health Check:{Colors.RESET}\n")

    report = WorkspaceInspector.inspect()
    print(f"  • ROS Distro:          {report.ros_distro or f'{Colors.RED}Not Sourced{Colors.RESET}'}")
    print(f"  • ROS Domain ID:       {report.ros_domain_id}")
    print(f"  • RMW Implementation:  {report.rmw_implementation or 'Default (FastRTPS/Cyclone)'}")
    print(f"  • Colcon Build Tool:   {'Found' if report.colcon_available else f'{Colors.YELLOW}Missing in PATH{Colors.RESET}'}")
    print(f"  • ROS 2 CLI:           {'Found' if report.ros2_cli_available else f'{Colors.YELLOW}Missing in PATH{Colors.RESET}'}")
    print(f"  • Workspace Root:      {report.workspace_root or 'None'}")
    print(f"  • Packages Located:    {len(report.packages_found)}")

    # Check LLM provider
    provider = get_llm_provider()
    print(f"\n  • AI Backend:          {Colors.GREEN}{provider.__class__.__name__}{Colors.RESET}")

    if report.warnings:
        print(f"\n{Colors.YELLOW}{Colors.BOLD}Warnings:{Colors.RESET}")
        for w in report.warnings:
            print(f"  ⚠️  {w}")

    if report.recommendations:
        print(f"\n{Colors.CYAN}{Colors.BOLD}Recommendations:{Colors.RESET}")
        for r in report.recommendations:
            print(f"  ➜  {r}")


def cmd_bag(args):
    """Analyzes a flight telemetry log or sample dataset."""
    print_banner()
    from robosage.diagnostics.bag_inspector import RosbagInspector
    import json

    target = args.target
    if target in ("clean", "nominal"):
        bag = RosbagInspector.get_sample_flight_bags()["clean_amr_run"]
    elif target in ("degraded", "faulty", "dropout"):
        bag = RosbagInspector.get_sample_flight_bags()["degraded_sensor_dropout"]
    elif os.path.isfile(target):
        with open(target, "r", encoding="utf-8") as f:
            bag = json.load(f)
    else:
        print(f"{Colors.RED}Target '{target}' not found. Use 'nominal', 'degraded', or a valid JSON flight telemetry file.{Colors.RESET}")
        sys.exit(1)

    report = RosbagInspector.analyze_flight_bag(bag)
    status_color = Colors.GREEN if report["overall_status"] == "HEALTHY" else Colors.RED
    print(f"✈️  Telemetry Status: {status_color}{Colors.BOLD}{report['overall_status']}{Colors.RESET}")
    print(f"Total Topics: {report['total_topics']} | Total Packets: {report['total_messages']}\n")

    for t in report["topics"]:
        col = Colors.GREEN if t["status"] == "HEALTHY" else Colors.RED
        print(f"{col}[{t['status']}] Topic: {t['topic']} ({t['type']}){Colors.RESET}")
        print(f"   Expected: {t['expected_hz']} Hz | Observed: {t['observed_hz']} Hz | Jitter StdDev: {t['jitter_ms']} ms")
        print(f"   Delta Min/Max: {t['min_gap_ms']}ms / {t['max_gap_ms']}ms | Dropped Frames: {t['dropped_frames']}")
        for a in t["anomalies"]:
            print(f"   ⚠️  {Colors.YELLOW}{a}{Colors.RESET}")
        print("-" * 60)


def cmd_bt(args):
    """Parses and audits a BehaviorTree.CPP XML file."""
    print_banner()
    from robosage.diagnostics.behavior_tree_analyzer import BehaviorTreeAnalyzer

    target = args.target
    if target in ("nominal", "nav2"):
        xml_content = BehaviorTreeAnalyzer.get_sample_trees()["nav2_nominal"]["xml"]
    elif target in ("faulty", "hazard"):
        xml_content = BehaviorTreeAnalyzer.get_sample_trees()["faulty_tree"]["xml"]
    elif os.path.isfile(target):
        with open(target, "r", encoding="utf-8") as f:
            xml_content = f.read()
    else:
        print(f"{Colors.RED}File '{target}' not found. Use 'nominal', 'faulty', or a valid XML file path.{Colors.RESET}")
        sys.exit(1)

    res = BehaviorTreeAnalyzer.parse_and_audit_xml(xml_content)
    if not res["valid"]:
        print(f"{Colors.RED}Tree Invalid: {res['error']}{Colors.RESET}")
        return

    print(f"{Colors.BOLD}🌲 Behavior Tree Structure Audited:{Colors.RESET}")
    stats = res["stats"]
    print(f"Nodes: {stats['nodes']} | Actions: {stats['actions']} | Controls: {stats['controls']} | Blackboard Keys: {stats['blackboard_keys']}\n")

    if not res["findings"]:
        print(f"{Colors.GREEN}✅ Behavior Tree is robust: No blackboard race conditions or infinite retry traps.{Colors.RESET}")
    else:
        print(f"{Colors.RED}{Colors.BOLD}Found {len(res['findings'])} Tree Safety Finding(s):{Colors.RESET}")
        for f in res["findings"]:
            col = Colors.RED if f["severity"] == "CRITICAL" else Colors.YELLOW
            print(f"{col}[{f['severity']}] {f['title']}{Colors.RESET}")
            print(f"   Description: {f['description']}")
            print(f"   Impact:      {f['impact']}")
            print(f"   Fix:         {f['fix']}")
            print("-" * 60)


def cmd_shield(args):
    """Calculates dynamic stopping envelope and generates safety shield middleware."""
    print_banner()
    from robosage.diagnostics.safety_shield import SafetyShieldEngine

    if args.generate:
        lang = args.generate.lower()
        if lang in ("cpp", "c++"):
            code = SafetyShieldEngine.generate_cpp_shield_node(args.name or "safety_shield_node")
        else:
            code = SafetyShieldEngine.generate_python_shield_node(args.name or "safety_shield_node")
        print(f"{Colors.GREEN}🛡️ Generated AOUL Deterministic Safety Shield Node ({lang.upper()}):{Colors.RESET}\n")
        print(code)
        return

    res = SafetyShieldEngine.calculate_envelope(
        commanded_linear_vel=args.vel,
        commanded_angular_vel=0.0,
        current_distance_to_obstacle=args.dist,
        max_linear_vel=args.max_vel,
        max_linear_accel=args.max_accel,
        min_safe_distance=args.safe_dist,
    )
    col = Colors.RED if res["is_clamped"] else Colors.GREEN
    print(f"{Colors.BOLD}🛡️ Safety Shield Envelope Evaluation:{Colors.RESET}")
    print(f"Status:             {col}{'CLAMPED / INTERVENING' if res['is_clamped'] else 'SAFE / PASS-THROUGH'}{Colors.RESET}")
    print(f"Commanded Vel:      {res['commanded_linear_vel']} m/s")
    print(f"Safe Clamped Vel:   {res['safe_linear_vel']} m/s")
    print(f"Obstacle Distance:  {res['obstacle_distance']} m")
    print(f"Stopping Distance:  {res['stopping_distance_required']} m")
    print(f"Safety Margin:      {res['safety_margin_m']} m")
    print(f"Intervention Info:  {col}{res['intervention_reason']}{Colors.RESET}")


def cmd_wizard(args):
    """Interactive wizard to set up AOUL project configuration (themes, model, optional modules)."""
    print_banner()
    print(f"{Colors.CYAN}🛠️  AOUL Developer Wizard{Colors.RESET}\n")
    theme = input("Select theme (cyber/amber/matrix/indigo/crimson/light) [cyber]: ").strip() or "cyber"
    model = input("Default LLM model (qwen2.5-coder/ollama/gemini) [qwen2.5-coder]: ").strip() or "qwen2.5-coder"
    enable_pkg = input("Enable optional packages (diagnostics, ci, packaging) [y]/n: ").strip().lower()
    enable_pkg = enable_pkg != 'n'
    config = {
        "theme": theme,
        "model": model,
        "optional_modules": {
            "diagnostics": enable_pkg,
            "ci": enable_pkg,
            "packaging": enable_pkg,
        }
    }
    import json, os
    cfg_path = os.path.join(os.getcwd(), "aoul_config.json")
    with open(cfg_path, "w", encoding="utf-8") as f:
        json.dump(config, f, indent=2)
    print(f"{Colors.GREEN}✅ Configuration saved to {cfg_path}{Colors.RESET}\n")
    print("You can now run the optional modules:")
    if enable_pkg:
        print(f"  • {Colors.CYAN}robosage cli ci   {Colors.RESET}- generate CI workflow")
        print(f"  • {Colors.CYAN}robosage cli package {Colors.RESET}- build distributable packages")
    print("Happy hacking! 🎉")

def cmd_ci(args):
    """Generate a starter GitHub Actions CI workflow that runs AOUL diagnostics and SARIF upload."""
    print_banner()
    workflow = {
        "name": "AOUL CI",
        "on": {"push": {"branches": ["main"]}, "pull_request": {"branches": ["main"]}},
        "jobs": {
            "build": {
                "runs-on": "ubuntu-latest",
                "steps": [
                    {"uses": "actions/checkout@v4"},
                    {"name": "Set up Python", "uses": "actions/setup-python@v5", "with": {"python-version": "3.11"}},
                    {"name": "Install dependencies", "run": "pip install -r requirements.txt"},
                    {"name": "Run diagnostics", "run": "python -m robosage.cli audit --sarif /tmp/aoul.sarif ."},
                    {"name": "Upload SARIF", "uses": "github/codeql-action/upload-sarif@v2", "with": {"sarif_file": "/tmp/aoul.sarif"}}
                ]
            }
        }
    }
    import yaml, os
    out_path = os.path.join(os.getcwd(), ".github", "workflows", "aoul-ci.yml")
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        yaml.safe_dump(workflow, f, sort_keys=False)
    print(f"{Colors.GREEN}✅ CI workflow written to {out_path}{Colors.RESET}")
    print("Commit the file and push to enable automated diagnostics.")

def cmd_package(args):
    """Build distributable packages (wheel, sdist, optional exe) for AOUL.
    Uses `build` and optional `pyinstaller` for Windows exe.
    """
    print_banner()
    print(f"{Colors.CYAN}📦  Building Python packages...{Colors.RESET}")
    try:
        import build
    except ImportError:
        import subprocess, sys
        print(f"{Colors.YELLOW}Installing build tool...{Colors.RESET}")
        subprocess.check_call([sys.executable, "-m", "pip", "install", "build"])
        import build
    import subprocess, sys
    subprocess.check_call([sys.executable, "-m", "build", "--sdist", "--wheel", "."])
    print(f"{Colors.GREEN}✅ Packages created in ./dist{Colors.RESET}")
    if getattr(args, 'exe', False):
        print(f"{Colors.CYAN}🔧  Building Windows exe...{Colors.RESET}")
        subprocess.check_call([sys.executable, "-m", "pip", "install", "pyinstaller"])
        subprocess.check_call([sys.executable, "-m", "PyInstaller", "--onefile", "robosage/__main__.py", "-n", "AOUL.exe"])
        print(f"{Colors.GREEN}✅ Windows exe created in ./dist{Colors.RESET}")
    if getattr(args, 'dmg', False):
        print(f"{Colors.CYAN}🔧  Building macOS dmg (requires external script)...{Colors.RESET}")
        print(f"{Colors.YELLOW}⚠️  Dmg creation not automated in sandbox. Use build_dmg.sh manually.{Colors.RESET}")


def cmd_urdf(args):
    """Audits a URDF robot model for physical impossibilities and simulation loopholes."""
    print_banner()
    from robosage.diagnostics.urdf_auditor import UrdfAuditor
    target = args.path
    if target in ("nominal", "arm"):
        content = UrdfAuditor.get_sample_urdfs()["nominal_arm"]["urdf"]
    elif target in ("faulty", "hazardous"):
        content = UrdfAuditor.get_sample_urdfs()["faulty_inertias_amr"]["urdf"]
    elif os.path.isfile(target):
        with open(target, "r", encoding="utf-8") as f:
            content = f.read()
    else:
        print(f"{Colors.RED}Target '{target}' not found. Use 'nominal', 'faulty', or a valid URDF file path.{Colors.RESET}")
        sys.exit(1)

    res = UrdfAuditor.audit_urdf_text(content)
    if not res["valid"]:
        print(f"{Colors.RED}URDF Invalid: {res['error']}{Colors.RESET}")
        return

    print(f"🤖 {Colors.BOLD}Robot Model Audited:{Colors.RESET} {res['robot_name']}")
    stats = res["stats"]
    print(f"Links: {stats['links']} | Joints: {stats['joints']} | Total Mass: {stats['total_mass_kg']} kg | Root Link: {stats['root_link']}\n")

    if not res["findings"]:
        print(f"{Colors.GREEN}✅ URDF Physics Clean: No negative inertias, triangle inequality violations, or missing collision tags found.{Colors.RESET}")
    else:
        print(f"{Colors.RED}{Colors.BOLD}Found {len(res['findings'])} URDF Physics Finding(s):{Colors.RESET}")
        for f in res["findings"]:
            col = Colors.RED if f["severity"] == "CRITICAL" else Colors.YELLOW
            print(f"{col}[{f['severity']}] [{f['element_type'].upper()}: {f['element_name']}] {f['title']}{Colors.RESET}")
            print(f"   Loophole:    {f['description']}")
            print(f"   Hazard:      {Colors.RED}{f['physics_impact']}{Colors.RESET}")
            print(f"   Fix:         {f['recommended_fix']}")
            print("-" * 65)


def cmd_power(args):
    """Calculates motor thermal saturation, Joule losses, and battery discharge."""
    print_banner()
    from robosage.diagnostics.power_thermal import PowerThermalEngine
    res = PowerThermalEngine.calculate_motor_and_power(
        torque_nm=args.torque,
        speed_rad_s=args.speed,
        run_duration_min=args.duration,
        motor_resistance_ohms=args.resistance,
        torque_constant_kt=args.kt,
        battery_voltage=args.voltage,
        battery_capacity_ah=args.capacity,
    )
    col = Colors.GREEN if res["thermal_status"] == "NOMINAL" else Colors.YELLOW if res["thermal_status"] == "WARNING_OVERHEAT" else Colors.RED
    print(f"⚡ {Colors.BOLD}Actuator Thermal & Battery Power Envelope:{Colors.RESET}")
    print(f"Thermal State:       {col}{res['thermal_status']}{Colors.RESET}")
    print(f"Transient Temp:      {col}{res['transient_temp_c']} °C{Colors.RESET} (after {args.duration} min)")
    print(f"Steady-State Temp:   {res['steady_state_temp_c']} °C (Rated Max: {res['max_rated_temp_c']} °C)")
    print(f"Motor Current:       {res['current_a']} A")
    print(f"Joule Heat Loss:     {res['joule_loss_w']} W | Mech Power: {res['mech_power_w']} W")
    print(f"Total System Power:  {res['total_system_power_w']} W")
    print(f"Max Safe Duty Cycle: {res['safe_duty_cycle_pct']} %")
    print(f"Battery Runtime:     {Colors.CYAN}{res['battery_runtime_hours']} hours{Colors.RESET} ({res['battery_energy_wh']} Wh capacity)\n")
    for a in res["advisories"]:
        print(f"  • {col}{a}{Colors.RESET}")


def main():
    parser = argparse.ArgumentParser(
        prog="robosage",
        description="AOUL: AI Senior Robotics Assistant, Safety Auditor & Diagnostic Copilot",
    )
    subparsers = parser.add_subparsers(dest="command", help="Subcommand to run")

    # chat
    p_chat = subparsers.add_parser("chat", help="Start interactive pair programming with AI robotics assistant")
    p_chat.add_argument("--provider", help="LLM Provider: gemini, openai, anthropic, ollama, or auto")
    p_chat.add_argument("--api-key", help="API key for cloud provider")
    p_chat.add_argument("--model", help="Model name (e.g. gemini-1.5-flash, gpt-4o, llama3)")

    # wizard (developer experience)
    p_wizard = subparsers.add_parser("wizard", help="Interactive setup wizard for AOUL configuration")

    # ci (integration)
    p_ci = subparsers.add_parser("ci", help="Generate CI workflow for AOUL diagnostics")

    # package (packaging)
    p_pkg = subparsers.add_parser("package", help="Build distributable packages (wheel, sdist, optional exe/dmg)")
    p_pkg.add_argument("--exe", action="store_true", help="Also build Windows exe using PyInstaller")
    p_pkg.add_argument("--dmg", action="store_true", help="Create macOS dmg (requires external script)")

    # urdf (Physics & Inertia Auditor)
    p_urdf = subparsers.add_parser("urdf", help="Audit URDF robot model for physics loopholes & invalid inertias")
    p_urdf.add_argument("path", nargs="?", default="nominal", help="Path to URDF file or preset: 'nominal', 'faulty'")

    # power (Motor Thermal & Battery Envelope)
    p_power = subparsers.add_parser("power", help="Simulate motor Joule heating and battery discharge runtime")
    p_power.add_argument("--torque", type=float, default=2.5, help="Actuator torque (Nm)")
    p_power.add_argument("--speed", type=float, default=10.0, help="Actuator speed (rad/s)")
    p_power.add_argument("--duration", type=float, default=15.0, help="Run duration (minutes)")
    p_power.add_argument("--resistance", type=float, default=0.85, help="Winding resistance (Ohms)")
    p_power.add_argument("--kt", type=float, default=0.12, help="Torque constant Kt (Nm/A)")
    p_power.add_argument("--voltage", type=float, default=24.0, help="Battery voltage (V)")
    p_power.add_argument("--capacity", type=float, default=15.0, help="Battery capacity (Ah)")

    # audit
    p_audit = subparsers.add_parser("audit", help="Run loophole and safety audit on ROS 2 package or code")
    p_audit.add_argument("path", nargs="?", default=".", help="Path to file or directory to audit (default: .)")
    p_audit.add_argument("--sarif", help="Export audit findings to OASIS SARIF v2.1.0 JSON format for GitHub / CI")

    # bag (Flight Telemetry Inspector)
    p_bag = subparsers.add_parser("bag", help="Inspect and triage Rosbag2/MCAP flight telemetry jitter & packet drops")
    p_bag.add_argument("target", nargs="?", default="nominal", help="Path to telemetry JSON or preset: 'nominal', 'degraded'")

    # bt (Nav2 Behavior Tree Auditor)
    p_bt = subparsers.add_parser("bt", help="Visualize and audit Nav2 BehaviorTree.CPP v4 XML trees")
    p_bt.add_argument("target", nargs="?", default="nominal", help="Path to BehaviorTree XML or preset: 'nominal', 'faulty'")

    # shield (Safety Shield Middleware)
    p_shield = subparsers.add_parser("shield", help="Evaluate dynamic stopping envelope or scaffold safe shield node")
    p_shield.add_argument("--dist", type=float, default=1.5, help="Obstacle distance (meters)")
    p_shield.add_argument("--vel", type=float, default=1.0, help="Commanded linear velocity (m/s)")
    p_shield.add_argument("--max-vel", type=float, default=1.0, help="Maximum linear velocity limit (m/s)")
    p_shield.add_argument("--max-accel", type=float, default=0.8, help="Maximum linear deceleration (m/s^2)")
    p_shield.add_argument("--safe-dist", type=float, default=0.35, help="Minimum safe buffer distance (meters)")
    p_shield.add_argument("--generate", choices=["cpp", "python"], help="Generate verified production node code")
    p_shield.add_argument("--name", default="safety_shield_node", help="Node name for generation")

    # improve (Qwen Robotics Code Optimizer)
    p_improve = subparsers.add_parser("improve", help="Optimize & refactor robotics code using local Qwen")
    p_improve.add_argument("path", help="Path to Python or C++ robotics file to improve")
    p_improve.add_argument("--focus", default="all", choices=["all", "safety", "concurrency", "performance"], help="Optimization focus area")
    p_improve.add_argument("--model", help="Qwen model name (default: auto-detected or qwen2.5-coder)")
    p_improve.add_argument("--endpoint", help="Qwen endpoint (default: http://localhost:11434)")
    p_improve.add_argument("--output", "-o", help="File path to save the improved code")

    # triage
    p_triage = subparsers.add_parser("triage", help="Triage a ROS 2 log file, crash output, or traceback")
    p_triage.add_argument("target", help="Log file path or error message text")

    # watch
    p_watch = subparsers.add_parser("watch", help="Monitor live ROS 2 logs or piped console stream")
    p_watch.add_argument("path", nargs="?", help="Path to log file (default: ~/.ros/log/latest)")

    # generate
    p_gen = subparsers.add_parser("generate", help="Scaffold safe ROS 2 node templates")
    p_gen.add_argument("template", choices=["diff_drive", "tf_listener", "multithreaded"], help="Template type")
    p_gen.add_argument("--name", help="Name of the node")
    p_gen.add_argument("--output", "-o", help="Output file path")

    # check-qos
    p_qos = subparsers.add_parser("check-qos", help="Check DDS QoS compatibility between pub and sub")
    p_qos.add_argument("pub_reliability", choices=["reliable", "best_effort"])
    p_qos.add_argument("pub_durability", choices=["volatile", "transient_local"])
    p_qos.add_argument("sub_reliability", choices=["reliable", "best_effort"])
    p_qos.add_argument("sub_durability", choices=["volatile", "transient_local"])

    # doctor
    subparsers.add_parser("doctor", help="Check system ROS 2 environment and LLM configuration")

    args = parser.parse_args()
    if not args.command:
        parser.print_help()
        sys.exit(0)

    dispatch = {
        "chat": cmd_chat,
        "audit": cmd_audit,
        "improve": cmd_improve,
        "triage": cmd_triage,
        "watch": cmd_watch,
        "generate": cmd_generate,
        "check-qos": cmd_check_qos,
        "doctor": cmd_doctor,
        "bag": cmd_bag,
        "bt": cmd_bt,
        "shield": cmd_shield,
        "urdf": cmd_urdf,
        "power": cmd_power,
        "wizard": cmd_wizard,
        "ci": cmd_ci,
        "package": cmd_package,
    }

    handler = dispatch.get(args.command)
    if handler:
        handler(args)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
