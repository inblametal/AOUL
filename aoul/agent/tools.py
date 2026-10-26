"""
Tool definitions and registry for the AOUL Agent.
Exposes diagnostics, code audits, and scaffolding to the agent loop.
"""

from dataclasses import dataclass
import json
from typing import Any, Callable, Dict, List, Optional

from aoul.diagnostics.log_analyzer import ROS2LogAnalyzer
from aoul.diagnostics.loophole_detector import LoopholeDetector
from aoul.diagnostics.qos_checker import (
    DurabilityPolicy,
    QoSProfile,
    ReliabilityPolicy,
    check_qos_compatibility,
)
from aoul.diagnostics.workspace_inspector import WorkspaceInspector


@dataclass
class Tool:
    name: str
    description: str
    func: Callable[..., Any]
    parameters: Dict[str, Any]


class RoboticsToolRegistry:
    """Registry of domain-specific robotics tools for the AI agent."""

    def __init__(self):
        self.log_analyzer = ROS2LogAnalyzer()
        self.loophole_detector = LoopholeDetector()
        self._tools: Dict[str, Tool] = {}
        self._register_default_tools()

    def register(self, tool: Tool):
        self._tools[tool.name] = tool

    def get(self, name: str) -> Optional[Tool]:
        return self._tools.get(name)

    def list_tools(self) -> List[Tool]:
        return list(self._tools.values())

    def execute(self, tool_name: str, **kwargs) -> Any:
        tool = self.get(tool_name)
        if not tool:
            return f"Error: Tool '{tool_name}' not found."
        try:
            return tool.func(**kwargs)
        except Exception as e:
            return f"Error executing tool '{tool_name}': {e}"

    def _register_default_tools(self):
        # 1. Triage log
        def triage_log_fn(log_content: str) -> str:
            incidents = self.log_analyzer.analyze_text(log_content)
            if not incidents:
                return "No known robotics errors or crashes detected in the provided log."
            results = []
            for i, inc in enumerate(incidents, 1):
                res = f"Incident #{i}: [{inc.severity.value}] {inc.category.value}\n"
                res += f"Summary: {inc.summary}\n"
                res += f"Root Cause: {inc.root_cause}\n"
                if inc.remediation_steps:
                    res += "Remediation Steps:\n" + "\n".join(f"  - {s}" for s in inc.remediation_steps) + "\n"
                if inc.code_fix:
                    res += f"Suggested Code Fix:\n```python\n{inc.code_fix}\n```\n"
                results.append(res)
            return "\n".join(results)

        self.register(
            Tool(
                name="triage_ros_log",
                description="Analyzes ROS 2 logs, rosout, DDS errors, TF errors, or crash traces to extract root causes and code fixes.",
                func=triage_log_fn,
                parameters={
                    "type": "object",
                    "properties": {
                        "log_content": {"type": "string", "description": "The raw log or traceback text"}
                    },
                    "required": ["log_content"],
                },
            )
        )

        # 2. Audit file/dir for loopholes
        def audit_code_fn(target_path: str) -> str:
            import os
            if os.path.isdir(target_path):
                findings = self.loophole_detector.audit_directory(target_path)
            elif os.path.isfile(target_path):
                findings = self.loophole_detector.audit_file(target_path)
            else:
                return f"Path '{target_path}' does not exist."

            if not findings:
                return f"No safety loopholes or deadlocks detected in '{target_path}'. Code follows safe robotics patterns."

            results = [f"Found {len(findings)} potential safety loophole(s) in '{target_path}':\n"]
            for i, f in enumerate(findings, 1):
                res = f"[{i}] [{f.severity.value}] {f.title} ({f.file_path}" + (f":{f.line_number}" if f.line_number else "") + ")\n"
                res += f"    Description: {f.description}\n"
                res += f"    Hazard/Impact: {f.impact}\n"
                res += f"    Fix: {f.recommended_fix}\n"
                if f.sample_patch:
                    res += f"    Code Patch:\n{f.sample_patch}\n"
                results.append(res)
            return "\n".join(results)

        self.register(
            Tool(
                name="audit_robotics_code",
                description="Performs static safety audit on ROS 2 Python/C++ code to find missing E-Stops, sensor dropouts, deadlocks, NaNs, and race conditions.",
                func=audit_code_fn,
                parameters={
                    "type": "object",
                    "properties": {
                        "target_path": {"type": "string", "description": "Path to file or directory to audit"}
                    },
                    "required": ["target_path"],
                },
            )
        )

        # 3. Check QoS compatibility
        def check_qos_fn(pub_reliability: str, pub_durability: str, sub_reliability: str, sub_durability: str) -> str:
            try:
                pub_q = QoSProfile(
                    reliability=ReliabilityPolicy(pub_reliability.upper()),
                    durability=DurabilityPolicy(pub_durability.upper()),
                )
                sub_q = QoSProfile(
                    reliability=ReliabilityPolicy(sub_reliability.upper()),
                    durability=DurabilityPolicy(sub_durability.upper()),
                )
                res = check_qos_compatibility(pub_q, sub_q)
                status = "COMPATIBLE" if res.is_compatible else "INCOMPATIBLE"
                out = f"QoS Status: {status}\n"
                if res.issues:
                    out += "Issues:\n" + "\n".join(f"- {i}" for i in res.issues) + "\n"
                if res.recommendations:
                    out += "Recommendations:\n" + "\n".join(f"- {r}" for r in res.recommendations)
                return out
            except Exception as e:
                return f"Error checking QoS: {e}"

        self.register(
            Tool(
                name="check_qos_compatibility",
                description="Validates DDS QoS compatibility between a publisher and a subscriber.",
                func=check_qos_fn,
                parameters={
                    "type": "object",
                    "properties": {
                        "pub_reliability": {"type": "string", "enum": ["RELIABLE", "BEST_EFFORT"]},
                        "pub_durability": {"type": "string", "enum": ["VOLATILE", "TRANSIENT_LOCAL"]},
                        "sub_reliability": {"type": "string", "enum": ["RELIABLE", "BEST_EFFORT"]},
                        "sub_durability": {"type": "string", "enum": ["VOLATILE", "TRANSIENT_LOCAL"]},
                    },
                    "required": ["pub_reliability", "pub_durability", "sub_reliability", "sub_durability"],
                },
            )
        )

        # 4. Inspect ROS 2 environment
        def inspect_env_fn(workspace_path: Optional[str] = None) -> str:
            rep = WorkspaceInspector.inspect(workspace_path)
            lines = [
                f"ROS 2 Distro: {rep.ros_distro or 'Not detected (environment not sourced)'}",
                f"Domain ID: {rep.ros_domain_id}",
                f"RMW Implementation: {rep.rmw_implementation or 'Default (FastRTPS/CycloneDDS)'}",
                f"Colcon Available: {rep.colcon_available}",
                f"ROS 2 CLI Available: {rep.ros2_cli_available}",
                f"Workspace Root: {rep.workspace_root or 'None'}",
                f"Packages Found ({len(rep.packages_found)}): {', '.join(rep.packages_found) if rep.packages_found else 'None'}",
            ]
            if rep.warnings:
                lines.append("\nWarnings:\n" + "\n".join(f"  - {w}" for w in rep.warnings))
            if rep.recommendations:
                lines.append("\nRecommendations:\n" + "\n".join(f"  - {r}" for r in rep.recommendations))
            return "\n".join(lines)

        self.register(
            Tool(
                name="inspect_ros_environment",
                description="Checks local ROS 2 installation, environment variables, and active workspace packages.",
                func=inspect_env_fn,
                parameters={
                    "type": "object",
                    "properties": {
                        "workspace_path": {"type": "string", "description": "Optional path to workspace"}
                    },
                },
            )
        )
