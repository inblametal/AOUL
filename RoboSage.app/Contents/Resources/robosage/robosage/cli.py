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


def main():
    parser = argparse.ArgumentParser(
        prog="robosage",
        description="RoboSage: AI Robotics Assistant, Safety Auditor & Diagnostic Copilot",
    )
    subparsers = parser.add_subparsers(dest="command", help="Subcommand to run")

    # chat
    p_chat = subparsers.add_parser("chat", help="Start interactive pair programming with AI robotics assistant")
    p_chat.add_argument("--provider", help="LLM Provider: gemini, openai, anthropic, ollama, or auto")
    p_chat.add_argument("--api-key", help="API key for cloud provider")
    p_chat.add_argument("--model", help="Model name (e.g. gemini-1.5-flash, gpt-4o, llama3)")

    # audit
    p_audit = subparsers.add_parser("audit", help="Run loophole and safety audit on ROS 2 package or code")
    p_audit.add_argument("path", nargs="?", default=".", help="Path to file or directory to audit (default: .)")

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
    }

    handler = dispatch.get(args.command)
    if handler:
        handler(args)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
