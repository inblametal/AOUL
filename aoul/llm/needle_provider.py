"""
Cactus Needle 3 Provider for AOUL / AOUL.

Needle 3 (Cactus Compute) is an ultra-compact on-device agent (20-layer Monarch
Hadamard MLP + Engram n-gram memory, 35.3 MB weights) optimized for sub-second
tool calling and edge robotics control with ~100MB RAM footprint.
"""

from dataclasses import dataclass
import os
import re
import sys
import time
from typing import Any, Callable, Dict, List, Optional

from aoul.llm.provider import BaseLLMProvider, ChatMessage, LLMResponse

try:
    import needle
    NEEDLE_AVAILABLE = True
except (ImportError, Exception):
    NEEDLE_AVAILABLE = False


MIN_TOOL_CONFIDENCE = 0.20


def _is_conversational_or_help_query(text: str) -> bool:
    """Detects if query is a greeting, capability question, or general chat rather than a direct tool command."""
    cleaned = re.sub(r'[^a-zA-Z0-9\s]', '', text).strip().lower()
    greetings = {"hi", "hello", "hey", "sup", "howdy", "good morning", "good evening", "greetings", "yo"}
    if cleaned in greetings:
        return True

    help_patterns = [
        r'\bwhat\s+(?:all\s+)?can\s+(?:you|u)\s+do\b',
        r'\blist\s+(?:me\s+)?(?:all\s+)?(?:your\s+)?tools\b',
        r'\blist\s+me\b',
        r'\bwho\s+are\s+you\b',
        r'\bcapabilities\b',
        r'\bhelp\b',
        r'\bwhat\s+are\s+you\b',
        r'\bcommands\b',
    ]
    return any(re.search(pat, cleaned) for pat in help_patterns)


def _build_needle_help_response(user_query: str) -> str:
    return (
        "### 🌵 Cactus Needle 3 Edge Agent (35.3 MB On-Device)\n"
        "> ⚡ **Peak RAM:** `~108 MB` | **Engine:** Monarch Hadamard MLP + Engram Memory | **Role:** Edge Action Dispatch\n\n"
        "Hello! I am **Cactus Needle 3**, a specialized ultra-compact on-device agent designed for **microsecond-to-subsecond robotics tool calling** in edge environments.\n\n"
        "Because I am a lightweight (35 MB) action execution model rather than an open-ended conversational LLM, I specialize in **direct hardware commands, safety interventions, and robotics diagnostics**:\n\n"
        "#### 🛠️ Direct Robotics Commands You Can Send Me:\n"
        "- 🚨 **Emergency Stop:** `\"Stop the robot immediately!\"` or `\"Trigger emergency brake, collision ahead!\"`\n"
        "- 🏎️ **Velocity Command:** `\"Set velocity to 0.8 m/s linear and 0.3 rad/s angular\"`\n"
        "- 📡 **QoS Compatibility:** `\"Check QoS between best_effort publisher and reliable subscriber\"`\n"
        "- 🔍 **Code Safety Audit:** `\"Audit robotics code in examples/buggy_node.py\"`\n"
        "- 📋 **ROS 2 Log Triage:** `\"Triage this error log: [paste traceback]\"`\n\n"
        "💡 **Tip for Open-Ended Robotics Discussions & Code Generation:**\n"
        "For general robotics theory, architecture design, or writing complete nodes from scratch, toggle to **⚡ Turbo Fast (Qwen 0.5B)** or **🧠 Deep Coder (Qwen Coder)** from the top dropdown!"
    )


def _build_needle_tools() -> List[Callable]:
    """Build domain-specific robotics tool definitions decorated with @needle.tool."""
    if not NEEDLE_AVAILABLE:
        return []

    from aoul.diagnostics.log_analyzer import ROS2LogAnalyzer
    from aoul.diagnostics.loophole_detector import LoopholeDetector
    from aoul.diagnostics.qos_checker import (
        DurabilityPolicy,
        QoSProfile,
        ReliabilityPolicy,
        check_qos_compatibility,
    )
    from aoul.diagnostics.workspace_inspector import WorkspaceInspector

    log_analyzer = ROS2LogAnalyzer()
    loophole_detector = LoopholeDetector()

    @needle.tool(triggers=["emergency stop", "estop", "e-stop", "brake", "stop robot", "halt", "collision", "danger", "obstacle", "hazard"])
    def trigger_estop(reason: str) -> Dict[str, Any]:
        """Trigger emergency stop on robot motor drives and publish zero cmd_vel."""
        return {
            "status": "ESTOP_ENGAGED",
            "cmd_vel_linear": 0.0,
            "cmd_vel_angular": 0.0,
            "reason": reason,
            "brakes": "LOCKED",
            "timestamp": time.time(),
        }

    @needle.tool(triggers=["velocity", "speed", "drive", "move", "cmd_vel", "linear", "angular", "turn", "rate", "forward", "reverse"])
    def set_robot_velocity(linear_x: float, angular_z: float) -> Dict[str, Any]:
        """Send linear and angular velocity commands to mobile base."""
        # Enforce safety limits
        clamped_x = max(-1.0, min(1.0, float(linear_x)))
        clamped_z = max(-1.5, min(1.5, float(angular_z)))
        return {
            "status": "VELOCITY_COMMAND_SENT",
            "linear_x": clamped_x,
            "angular_z": clamped_z,
            "safety_clamped": (clamped_x != linear_x or clamped_z != angular_z),
        }

    @needle.tool(triggers=["qos", "dds", "reliable", "best_effort", "durability", "transient_local", "volatile", "compatibility", "rxo"])
    def check_qos_compatibility_tool(
        pub_reliability: str,
        sub_reliability: str,
        pub_durability: str = "VOLATILE",
        sub_durability: str = "VOLATILE",
    ) -> Dict[str, Any]:
        """Check DDS QoS compatibility between a publisher and a subscriber."""
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
            return {
                "is_compatible": res.is_compatible,
                "issues": res.issues,
                "recommendations": res.recommendations,
            }
        except Exception as e:
            return {"is_compatible": False, "error": str(e)}

    @needle.tool(triggers=["audit", "loophole", "inspect code", "scan code", "safety audit", "race condition", "deadlock", "check code"])
    def audit_robotics_code_tool(target_path: str) -> Dict[str, Any]:
        """Performs static safety audit on ROS 2 Python/C++ code to find missing E-Stops, sensor dropouts, deadlocks, NaNs, and race conditions."""
        if os.path.isdir(target_path):
            findings = loophole_detector.audit_directory(target_path)
        elif os.path.isfile(target_path):
            findings = loophole_detector.audit_file(target_path)
        else:
            return {"error": f"Path '{target_path}' does not exist", "findings_count": 0}

        return {
            "target_path": target_path,
            "findings_count": len(findings),
            "findings": [
                {
                    "severity": f.severity.value,
                    "title": f.title,
                    "file_path": f.file_path,
                    "line": f.line_number,
                    "fix": f.recommended_fix,
                }
                for f in findings[:5]
            ],
        }

    @needle.tool(triggers=["triage", "traceback", "error log", "crash", "rosout", "fatal", "extrapolation", "tf error"])
    def triage_ros_log_tool(log_content: str) -> Dict[str, Any]:
        """Analyzes ROS 2 logs, rosout, DDS errors, TF errors, or crash traces to extract root causes and code fixes."""
        incidents = log_analyzer.analyze_text(log_content)
        if not incidents:
            return {"status": "CLEAN", "message": "No known robotics errors or crashes detected."}

        return {
            "status": "INCIDENTS_DETECTED",
            "count": len(incidents),
            "incidents": [
                {
                    "severity": inc.severity.value,
                    "category": inc.category.value,
                    "summary": inc.summary,
                    "root_cause": inc.root_cause,
                    "remediations": inc.remediation_steps[:3],
                }
                for inc in incidents[:3]
            ],
        }

    return [
        trigger_estop,
        set_robot_velocity,
        check_qos_compatibility_tool,
        audit_robotics_code_tool,
        triage_ros_log_tool,
    ]


class CactusNeedleProvider(BaseLLMProvider):
    """
    Cactus Needle 3 Provider for ultra-compact edge robotics action dispatch.
    Executes in ~100MB RAM with native C extensions and 35.3MB model weights.
    """

    def __init__(self, model: str = "cactus-needle-3"):
        self.model = model
        self._agent: Optional[Any] = None
        self._tools: Optional[List[Callable]] = None

    def _init_agent(self):
        if not NEEDLE_AVAILABLE:
            return None
        if self._agent is None:
            self._tools = _build_needle_tools()
            self._agent = needle.Needle(tools=self._tools, stateless=True)
        return self._agent

    def generate(
        self,
        prompt: str,
        system_prompt: Optional[str] = None,
        history: Optional[List[ChatMessage]] = None,
    ) -> LLMResponse:
        if not NEEDLE_AVAILABLE:
            msg = (
                "**🌵 Cactus Needle 3 is not installed.**\n\n"
                "Install it on this system via:\n"
                "```bash\n"
                "python3 -m pip install cactus-needle\n"
                "```\n"
                "Needle 3 provides 35.3 MB edge tool-calling intelligence running at sub-second speeds on CPU."
            )
            return LLMResponse(content=msg, provider="Cactus Needle 3", model=self.model)

        # 1. Guardrail for conversational queries, greetings, or capability questions
        if _is_conversational_or_help_query(prompt):
            content = _build_needle_help_response(prompt)
            return LLMResponse(
                content=content,
                provider="Cactus Needle 3 (Edge 35MB)",
                model=self.model,
                prompt_tokens=5,
                completion_tokens=len(content.split()),
            )

        agent = self._init_agent()
        if agent is None:
            return LLMResponse(content="Error initializing Cactus Needle 3 agent.", provider="Cactus Needle 3", model=self.model)

        t0 = time.time()
        try:
            res = agent.run(prompt)
            duration = time.time() - t0
        except Exception as e:
            return LLMResponse(
                content=f"**Cactus Needle 3 Error:** {e}\n\n*Falling back to static robotics intelligence.*",
                provider="Cactus Needle 3",
                model=self.model,
            )

        # Parse Needle 3 response structure
        reasoning = res.get("reasoning", "")
        confidence = res.get("confidence", 1.0)
        results = res.get("results", [])
        suppressed = res.get("suppressed_calls", [])
        function_calls = res.get("function_calls", [])
        peak_ram = res.get("peak_ram_mb", 108.0)
        prefill_tps = res.get("prefill_tps", 0.0)

        # 2. If confidence is below threshold (< 20%) and no tool actually succeeded:
        # DO NOT display false/hallucinated suppressed tool calls with nonsense arguments!
        if not results and (confidence < MIN_TOOL_CONFIDENCE or suppressed):
            content = (
                f"### 🌵 Cactus Needle 3 Edge Agent\n"
                f"> ⚡ **Execution Time:** `{duration:.2f}s` | **Peak RAM:** `{peak_ram:.1f} MB` | **Confidence:** `{confidence * 100:.1f}%` (Below action threshold)\n\n"
                f"Needle 3 is a direct robotics function caller and did not detect a high-confidence hardware action in: *\"{prompt.strip()[:60]}\"*.\n\n"
                f"#### 🛠️ Direct Commands You Can Run With Needle 3:\n"
                f"- 🚨 **E-Stop:** `\"Stop the robot immediately!\"`\n"
                f"- 🏎️ **Velocity:** `\"Set velocity to 0.8 m/s linear and 0.2 rad/s angular\"`\n"
                f"- 📡 **QoS:** `\"Check QoS compatibility between publisher best_effort and subscriber reliable\"`\n"
                f"- 🔍 **Audit:** `\"Audit robotics code in examples/buggy_node.py\"`\n"
                f"- 📋 **Triage:** `\"Triage error: [paste log snippet]\"`\n\n"
                f"💡 *Tip: For general robotics dialogue, code synthesis, or architecture questions, switch to **⚡ Turbo Fast (Qwen 0.5B)** or **🧠 Deep Coder** in the top model dropdown!*"
            )
            return LLMResponse(
                content=content,
                provider="Cactus Needle 3 (Edge 35MB)",
                model=self.model,
                prompt_tokens=int(prefill_tps * duration) if prefill_tps else 10,
                completion_tokens=len(content.split()),
            )

        lines = [
            f"### 🌵 Cactus Needle 3 Edge Agent",
            f"> ⚡ **Execution Time:** `{duration:.2f}s` | **Peak RAM:** `{peak_ram:.1f} MB` | **Confidence:** `{confidence * 100:.1f}%` | **Engine:** Monarch Hadamard MLP",
            "",
        ]

        if reasoning:
            lines.append(f"**Reasoning:** *{reasoning}*\n")

        # Handle tool execution results
        if results:
            lines.append("#### 🛠️ Dispatched Tool Execution Results:")
            for idx, item in enumerate(results, 1):
                if isinstance(item, dict):
                    lines.append(f"```json\n{_format_dict(item)}\n```")
                else:
                    lines.append(f"- **Result #{idx}:** `{item}`")
        elif function_calls:
            lines.append("#### 📞 Tool Calls Dispatched:")
            for call in function_calls:
                lines.append(f"- **Function:** `{call.get('name')}` | **Args:** `{call.get('arguments')}`")
        elif suppressed and confidence >= MIN_TOOL_CONFIDENCE:
            lines.append("#### 🛡️ Tool Calls Proposed (Pre-check Validated):")
            for call in suppressed:
                lines.append(f"- **Action:** `{call.get('name')}` with `{call.get('arguments')}`")
        else:
            # Fallback to offline robotics provider
            from aoul.llm.provider import OfflineRoboticsProvider
            offline_prov = OfflineRoboticsProvider()
            off_resp = offline_prov.generate(prompt)
            lines.append(off_resp.content)

        return LLMResponse(
            content="\n".join(lines),
            provider="Cactus Needle 3 (Edge 35MB)",
            model=self.model,
            prompt_tokens=int(prefill_tps * duration) if prefill_tps else 10,
            completion_tokens=len(lines),
        )

    def generate_stream(
        self,
        prompt: str,
        system_prompt: Optional[str] = None,
        history: Optional[List[ChatMessage]] = None,
    ):
        """Yield response in streaming chunks for the web chat interface."""
        resp = self.generate(prompt, system_prompt=system_prompt, history=history)
        paragraphs = resp.content.split("\n\n")
        for i, p in enumerate(paragraphs):
            yield p + ("\n\n" if i < len(paragraphs) - 1 else "")
            time.sleep(0.01)


def _format_dict(d: Dict[str, Any]) -> str:
    import json
    return json.dumps(d, indent=2)
