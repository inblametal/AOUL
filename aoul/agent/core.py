"""
AOUL AI Agent Core Loop.
Coordinates LLM reasoning, robotics tools execution, memory layer, and conversation continuation.
"""

from dataclasses import dataclass, field
import os
import re
from typing import Dict, List, Optional

from aoul.agent.memory import ConversationManager, RoboticsMemoryLayer
from aoul.agent.prompts import ROBOTICS_AGENT_SYSTEM_PROMPT, ROBOTICS_FAST_CHAT_PROMPT
from aoul.agent.tools import RoboticsToolRegistry
from aoul.llm.provider import BaseLLMProvider, ChatMessage, LLMResponse, get_llm_provider


def deduplicate_repeating_sentences(text: str) -> str:
    """
    Detects and truncates degenerative repeating sentence loops produced by small LLMs.
    If the same sentence repeats consecutively or >2 times in a short window, cuts off the repetition.
    """
    if not text or len(text) < 40:
        return text

    parts = re.split(r'((?<=[.!?\n])\s+)', text)
    cleaned = []
    seen = []
    i = 0
    while i < len(parts):
        chunk = parts[i]
        norm = re.sub(r'\s+', ' ', chunk).strip().lower()
        if len(norm) > 15:
            if seen and norm == seen[-1]:
                # Skip duplicate and any trailing separator
                i += 2 if (i + 1 < len(parts) and re.match(r'^\s+$', parts[i + 1])) else 1
                continue
            seen.append(norm)
        cleaned.append(chunk)
        i += 1
    return "".join(cleaned)


@dataclass
class AgentSession:
    provider: BaseLLMProvider
    tool_registry: RoboticsToolRegistry = field(default_factory=RoboticsToolRegistry)
    conversation_history: List[ChatMessage] = field(default_factory=list)
    system_prompt: str = ROBOTICS_AGENT_SYSTEM_PROMPT
    conversation_manager: ConversationManager = field(default_factory=ConversationManager)

    def reset(self):
        """Clears active thread messages and temporary conversation history."""
        self.conversation_history.clear()
        if self.conversation_manager.active_thread_id in self.conversation_manager.threads:
            self.conversation_manager.clear_thread(self.conversation_manager.active_thread_id)

    def step(self, user_input: str, thread_id: Optional[str] = None) -> str:
        """Processes a single conversational turn from the user with full memory & continuation."""
        thread = self.conversation_manager.get_or_create_thread(thread_id or self.conversation_manager.active_thread_id)

        # 1. Automatic heuristic tool routing for instant feedback
        pre_tool_context = self._evaluate_quick_tools(user_input)

        # 2. Build augmented prompt with memory layer context
        memory_context = self.conversation_manager.memory_layer.get_system_memory_context()
        augmented_prompt = user_input
        if pre_tool_context:
            augmented_prompt = (
                f"{user_input}\n\n"
                f"[AOUL Diagnostic Tool Output]:\n{pre_tool_context}\n\n"
                f"Please synthesize this diagnostic finding, explain the physics/concurrency cause, and provide a clean solution."
            )

        # 3. Call LLM provider with optimized fast prompt for conversational turns
        is_short_turn = len(user_input.strip()) < 120 and not pre_tool_context and "refactor" not in user_input.lower()
        base_sys = ROBOTICS_FAST_CHAT_PROMPT if (is_short_turn and self.system_prompt == ROBOTICS_AGENT_SYSTEM_PROMPT) else self.system_prompt
        effective_sys = f"{base_sys}\n\n{memory_context}"

        history_for_llm = thread.get_messages_for_llm()
        if not history_for_llm and self.conversation_history:
            history_for_llm = self.conversation_history[-6:]

        try:
            response = self.provider.generate(
                prompt=augmented_prompt,
                system_prompt=effective_sys,
                history=history_for_llm,
            )
            cleaned_content = deduplicate_repeating_sentences(response.content)

            # Store in thread and manager
            self.conversation_manager.add_turn(thread.id, user_input, cleaned_content)
            self.conversation_history = list(thread.messages)
            return cleaned_content
        except Exception as e:
            err_str = str(e)
            is_timeout = "timed out" in err_str.lower()
            if is_timeout:
                note = (
                    "> ℹ️ **AOUL Model Warm-Up Note:** The local Qwen Coder model timed out while loading into memory.\n"
                    "> *The model weights are now resident in unified memory (24h keep-alive enabled). Click **Send** again to get your answer immediately!*\n\n"
                )
            else:
                note = (
                    f"> ℹ️ **AOUL Connection Note:** `{err_str}`\n"
                    f"> *Tip: Ensure Ollama is active (`ollama serve`) with Qwen Coder installed (`ollama pull qwen2.5-coder`).*\n\n"
                )

            # If LLM provider fails, return diagnostic output if available
            if pre_tool_context:
                fallback_text = (
                    f"{note}"
                    f"**AOUL Static Diagnostic Findings:**\n\n"
                    f"{pre_tool_context}"
                )
            else:
                # Graceful fallback: AOUL Offline Expert Intelligence
                from aoul.llm.provider import OfflineRoboticsProvider
                offline = OfflineRoboticsProvider()
                offline_resp = offline.generate(user_input)
                fallback_text = (
                    f"{note}"
                    f"**AOUL Static Diagnostic Assistant Response:**\n\n"
                    f"{offline_resp.content}"
                )

            self.conversation_manager.add_turn(thread.id, user_input, fallback_text)
            self.conversation_history = list(thread.messages)
            return fallback_text

    def step_stream(self, user_input: str, thread_id: Optional[str] = None):
        """Processes a single conversational turn from the user, yielding streaming chunks as tokens arrive."""
        thread = self.conversation_manager.get_or_create_thread(thread_id or self.conversation_manager.active_thread_id)
        pre_tool_context = self._evaluate_quick_tools(user_input)

        memory_context = self.conversation_manager.memory_layer.get_system_memory_context()
        augmented_prompt = user_input
        if pre_tool_context:
            augmented_prompt = (
                f"{user_input}\n\n"
                f"[AOUL Diagnostic Tool Output]:\n{pre_tool_context}\n\n"
                f"Please synthesize this diagnostic finding, explain the physics/concurrency cause, and provide a clean solution."
            )

        full_reply = []
        model_name = getattr(self.provider, "model", "Qwen Coder")
        is_short_turn = len(user_input.strip()) < 120 and not pre_tool_context and "refactor" not in user_input.lower()
        base_sys = ROBOTICS_FAST_CHAT_PROMPT if (is_short_turn and self.system_prompt == ROBOTICS_AGENT_SYSTEM_PROMPT) else self.system_prompt
        effective_sys = f"{base_sys}\n\n{memory_context}"

        history_for_llm = thread.get_messages_for_llm()
        if not history_for_llm and self.conversation_history:
            history_for_llm = self.conversation_history[-6:]

        stream_buffer = ""
        loop_broken = False

        try:
            if hasattr(self.provider, "generate_stream"):
                for token in self.provider.generate_stream(
                    prompt=augmented_prompt,
                    system_prompt=effective_sys,
                    history=history_for_llm,
                ):
                    full_reply.append(token)
                    stream_buffer += token

                    # Live sentence repetition detection to prevent repeating bug
                    if any(p in token for p in [".", "!", "?", "\n"]):
                        sentences = [s.strip() for s in re.split(r'[.!?\n]+', stream_buffer) if len(s.strip()) > 15]
                        if len(sentences) >= 2 and sentences[-1].lower() == sentences[-2].lower():
                            loop_broken = True
                            break

                    yield {
                        "type": "token",
                        "token": token,
                        "model": model_name,
                        "thread_id": thread.id,
                        "thread_title": thread.title,
                    }
            else:
                resp = self.provider.generate(
                    prompt=augmented_prompt,
                    system_prompt=effective_sys,
                    history=history_for_llm,
                )
                full_reply.append(resp.content)
                yield {
                    "type": "token",
                    "token": resp.content,
                    "model": model_name,
                    "thread_id": thread.id,
                    "thread_title": thread.title,
                }

            raw_content = "".join(full_reply)
            content = deduplicate_repeating_sentences(raw_content)

            self.conversation_manager.add_turn(thread.id, user_input, content)
            self.conversation_history = list(thread.messages)
            yield {
                "type": "done",
                "reply": content,
                "model": model_name,
                "thread_id": thread.id,
                "thread_title": thread.title,
                "memory_summary": self.conversation_manager.memory_layer.robot_profile.platform_type,
            }

        except Exception as e:
            err_str = str(e)
            is_timeout = "timed out" in err_str.lower()
            if is_timeout:
                note = (
                    "> ℹ️ **AOUL Model Warm-Up Note:** The local Qwen Coder model timed out while loading into memory.\n"
                    "> *The model weights are now resident in unified memory (24h keep-alive enabled). Click **Send** again to get your answer immediately!*\n\n"
                )
            else:
                note = (
                    f"> ℹ️ **AOUL Connection Note:** `{err_str}`\n"
                    f"> *Tip: Ensure Ollama is active (`ollama serve`) with Qwen Coder installed (`ollama pull qwen2.5-coder`).*\n\n"
                )

            if pre_tool_context:
                fallback_text = (
                    f"{note}"
                    f"**AOUL Static Diagnostic Findings:**\n\n"
                    f"{pre_tool_context}"
                )
            else:
                from aoul.llm.provider import OfflineRoboticsProvider
                offline = OfflineRoboticsProvider()
                offline_resp = offline.generate(user_input)
                fallback_text = (
                    f"{note}"
                    f"**AOUL Static Diagnostic Assistant Response:**\n\n"
                    f"{offline_resp.content}"
                )

            self.conversation_manager.add_turn(thread.id, user_input, fallback_text)
            self.conversation_history = list(thread.messages)
            yield {
                "type": "token",
                "token": fallback_text,
                "model": "Offline Heuristics",
                "thread_id": thread.id,
                "thread_title": thread.title,
            }
            yield {
                "type": "done",
                "reply": fallback_text,
                "model": "Offline Heuristics",
                "thread_id": thread.id,
                "thread_title": thread.title,
            }

    def _evaluate_quick_tools(self, text: str) -> Optional[str]:
        """Runs relevant static analysis or triage if file paths or logs are detected in prompt."""
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

        if any(marker in text for marker in ("Traceback", "extrapolation into", "Incompatible QoS", "SIGSEGV", "[ERROR]", "[FATAL]", "TF_OLD_DATA")):
            return self.tool_registry.execute("triage_ros_log", log_content=text)

        return None
