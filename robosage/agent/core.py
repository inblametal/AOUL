"""
RoboSage AI Agent Core Loop.
Coordinates LLM reasoning, robotics tools execution, and context management.
"""

from dataclasses import dataclass, field
import os
from typing import Dict, List, Optional

from robosage.agent.prompts import ROBOTICS_AGENT_SYSTEM_PROMPT
from robosage.agent.tools import RoboticsToolRegistry
from robosage.llm.provider import BaseLLMProvider, ChatMessage, LLMResponse, get_llm_provider


@dataclass
class AgentSession:
    provider: BaseLLMProvider
    tool_registry: RoboticsToolRegistry = field(default_factory=RoboticsToolRegistry)
    conversation_history: List[ChatMessage] = field(default_factory=list)
    system_prompt: str = ROBOTICS_AGENT_SYSTEM_PROMPT

    def reset(self):
        self.conversation_history.clear()

    def step(self, user_input: str) -> str:
        """Processes a single conversational turn from the user."""
        # 1. Automatic heuristic tool routing for instant feedback
        pre_tool_context = self._evaluate_quick_tools(user_input)

        # 2. Build augmented prompt
        augmented_prompt = user_input
        if pre_tool_context:
            augmented_prompt = (
                f"{user_input}\n\n"
                f"[RoboSage Diagnostic Tool Output]:\n{pre_tool_context}\n\n"
                f"Please synthesize this diagnostic finding, explain the physics/concurrency cause, and provide a clean solution."
            )

        # 3. Call LLM provider
        try:
            response = self.provider.generate(
                prompt=augmented_prompt,
                system_prompt=self.system_prompt,
                history=self.conversation_history,
            )
            # Store in history
            self.conversation_history.append(ChatMessage(role="user", content=user_input))
            self.conversation_history.append(ChatMessage(role="assistant", content=response.content))
            return response.content
        except Exception as e:
            err_str = str(e)
            is_timeout = "timed out" in err_str.lower()
            if is_timeout:
                note = (
                    "> ℹ️ **RoboSage Model Warm-Up Note:** The local Qwen Coder model timed out while loading into memory.\n"
                    "> *The model weights are now resident in unified memory (24h keep-alive enabled). Click **Send** again to get your answer immediately!*\n\n"
                )
            else:
                note = (
                    f"> ℹ️ **RoboSage Connection Note:** `{err_str}`\n"
                    f"> *Tip: Ensure Ollama is active (`ollama serve`) with Qwen Coder installed (`ollama pull qwen2.5-coder`).*\n\n"
                )

            # If LLM provider fails, return diagnostic output if available
            if pre_tool_context:
                return (
                    f"{note}"
                    f"**RoboSage Static Diagnostic Findings:**\n\n"
                    f"{pre_tool_context}"
                )
            # Graceful fallback: RoboSage Offline Expert Intelligence
            from robosage.llm.provider import OfflineRoboticsProvider
            offline = OfflineRoboticsProvider()
            offline_resp = offline.generate(user_input)
            return (
                f"{note}"
                f"**RoboSage Static Diagnostic Assistant Response:**\n\n"
                f"{offline_resp.content}"
            )

    def _evaluate_quick_tools(self, text: str) -> Optional[str]:
        """Runs relevant static analysis or triage if file paths or logs are detected in prompt."""
        # Check if user mentioned an existing file
        words = text.split()
        for w in words:
            cleaned = w.strip("`'\",:;")
            if os.path.isfile(cleaned):
                ext = os.path.splitext(cleaned)[1].lower()
                if ext in (".py", ".cpp", ".hpp", ".h"):
                    return self.tool_registry.execute("audit_robotics_code", target_path=cleaned)
                elif ext in (".log", ".txt") or "log" in cleaned:
                    try:
                        with open(cleaned, "r", encoding="utf-8") as f:
                            content = f.read(50000)  # read up to 50KB
                        return self.tool_registry.execute("triage_ros_log", log_content=content)
                    except Exception:
                        pass
            elif os.path.isdir(cleaned) and (cleaned.endswith("src") or os.path.exists(os.path.join(cleaned, "package.xml"))):
                return self.tool_registry.execute("audit_robotics_code", target_path=cleaned)

        # Check if input text itself contains a log or crash snippet
        if any(marker in text for marker in ("Traceback", "extrapolation into", "Incompatible QoS", "SIGSEGV", "[ERROR]", "[FATAL]", "TF_OLD_DATA")):
            return self.tool_registry.execute("triage_ros_log", log_content=text)

        return None
