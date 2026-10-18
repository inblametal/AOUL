"""
Multi-Provider LLM Client for RoboSage.
Supports:
1. Google Gemini (REST API / google-genai)
2. OpenAI (REST API / openai SDK / Groq / DeepSeek)
3. Anthropic Claude (REST API / anthropic SDK)
4. Local Ollama (REST API for air-gapped robot use)
5. Offline Rule-Based Fallback (Works 100% offline with zero API keys)
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
import json
import os
import urllib.error
import urllib.request
from typing import Any, Dict, List, Optional


@dataclass
class ChatMessage:
    role: str  # "system", "user", "assistant"
    content: str


@dataclass
class LLMResponse:
    content: str
    provider: str
    model: str
    prompt_tokens: Optional[int] = None
    completion_tokens: Optional[int] = None


class BaseLLMProvider(ABC):
    """Abstract base class for all LLM providers."""

    @abstractmethod
    def generate(
        self,
        prompt: str,
        system_prompt: Optional[str] = None,
        history: Optional[List[ChatMessage]] = None,
    ) -> LLMResponse:
        pass


class GeminiProvider(BaseLLMProvider):
    """Google Gemini Provider using standard HTTP REST API."""

    def __init__(self, api_key: Optional[str] = None, model: str = "gemini-1.5-flash"):
        self.api_key = api_key or os.environ.get("GEMINI_API_KEY")
        self.model = model

    def generate(
        self,
        prompt: str,
        system_prompt: Optional[str] = None,
        history: Optional[List[ChatMessage]] = None,
    ) -> LLMResponse:
        if not self.api_key:
            raise ValueError("GEMINI_API_KEY is not set.")

        url = f"https://generativelanguage.googleapis.com/v1beta/models/{self.model}:generateContent?key={self.api_key}"

        contents = []
        if history:
            for msg in history:
                role = "user" if msg.role == "user" else "model"
                contents.append({"role": role, "parts": [{"text": msg.content}]})

        contents.append({"role": "user", "parts": [{"text": prompt}]})

        payload: Dict[str, Any] = {"contents": contents}
        if system_prompt:
            payload["systemInstruction"] = {"parts": [{"text": system_prompt}]}

        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            url,
            data=data,
            headers={"Content-Type": "application/json"},
            method="POST",
        )

        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                result = json.loads(resp.read().decode("utf-8"))
                text = result["candidates"][0]["content"]["parts"][0]["text"]
                return LLMResponse(content=text, provider="Gemini", model=self.model)
        except urllib.error.HTTPError as e:
            err_body = e.read().decode("utf-8", errors="ignore")
            raise RuntimeError(f"Gemini API Error ({e.code}): {err_body}")


class OpenAIProvider(BaseLLMProvider):
    """OpenAI / OpenAI-compatible provider (supports custom base_url for Ollama/vLLM/Groq)."""

    def __init__(
        self,
        api_key: Optional[str] = None,
        base_url: str = "https://api.openai.com/v1",
        model: str = "gpt-4o-mini",
    ):
        self.api_key = api_key or os.environ.get("OPENAI_API_KEY", "")
        self.base_url = base_url.rstrip("/")
        self.model = model

    def generate(
        self,
        prompt: str,
        system_prompt: Optional[str] = None,
        history: Optional[List[ChatMessage]] = None,
    ) -> LLMResponse:
        url = f"{self.base_url}/chat/completions"

        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        if history:
            for msg in history:
                messages.append({"role": msg.role, "content": msg.content})
        messages.append({"role": "user", "content": prompt})

        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": 0.2,
        }

        data = json.dumps(payload).encode("utf-8")
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

        req = urllib.request.Request(url, data=data, headers=headers, method="POST")

        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                result = json.loads(resp.read().decode("utf-8"))
                text = result["choices"][0]["message"]["content"]
                return LLMResponse(content=text, provider="OpenAI", model=self.model)
        except urllib.error.HTTPError as e:
            err_body = e.read().decode("utf-8", errors="ignore")
            raise RuntimeError(f"OpenAI-compatible API Error ({e.code}): {err_body}")


class AnthropicProvider(BaseLLMProvider):
    """Anthropic Claude Provider using standard HTTP REST API."""

    def __init__(self, api_key: Optional[str] = None, model: str = "claude-3-5-sonnet-20241022"):
        self.api_key = api_key or os.environ.get("ANTHROPIC_API_KEY")
        self.model = model

    def generate(
        self,
        prompt: str,
        system_prompt: Optional[str] = None,
        history: Optional[List[ChatMessage]] = None,
    ) -> LLMResponse:
        if not self.api_key:
            raise ValueError("ANTHROPIC_API_KEY is not set.")

        url = "https://api.anthropic.com/v1/messages"

        messages = []
        if history:
            for msg in history:
                if msg.role != "system":
                    messages.append({"role": msg.role, "content": msg.content})
        messages.append({"role": "user", "content": prompt})

        payload: Dict[str, Any] = {
            "model": self.model,
            "max_tokens": 4096,
            "messages": messages,
        }
        if system_prompt:
            payload["system"] = system_prompt

        data = json.dumps(payload).encode("utf-8")
        headers = {
            "Content-Type": "application/json",
            "x-api-key": self.api_key,
            "anthropic-version": "2023-06-01",
        }

        req = urllib.request.Request(url, data=data, headers=headers, method="POST")

        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                result = json.loads(resp.read().decode("utf-8"))
                text = result["content"][0]["text"]
                return LLMResponse(content=text, provider="Anthropic", model=self.model)
        except urllib.error.HTTPError as e:
            err_body = e.read().decode("utf-8", errors="ignore")
            raise RuntimeError(f"Anthropic API Error ({e.code}): {err_body}")


def get_installed_ollama_models(host: str = "http://localhost:11434") -> List[str]:
    """Queries Ollama for list of locally installed model names."""
    try:
        req = urllib.request.Request(f"{host}/api/tags", method="GET")
        with urllib.request.urlopen(req, timeout=1.2) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            return [m.get("name", "") for m in data.get("models", []) if m.get("name")]
    except Exception:
        return []


def resolve_best_local_model(host: str = "http://localhost:11434", requested: Optional[str] = None) -> str:
    """Finds best matching model in Ollama, prioritizing Qwen."""
    installed = get_installed_ollama_models(host)
    if not installed:
        return requested or "qwen2.5-coder:latest"

    # If requested model matches an installed model, use it
    if requested and requested not in ("auto", "qwen", "local"):
        for m in installed:
            if m.lower() == requested.lower() or m.lower().startswith(requested.lower() + ":"):
                return m

    # Priority 1: Qwen 2.5 Coder
    for m in installed:
        if "qwen2.5-coder" in m.lower():
            return m
    # Priority 2: Qwen 2.5
    for m in installed:
        if "qwen2.5" in m.lower():
            return m
    # Priority 3: Any Qwen
    for m in installed:
        if "qwen" in m.lower():
            return m
    # Priority 4: Any Coder model
    for m in installed:
        if "coder" in m.lower():
            return m

    return installed[0]


class OllamaProvider(BaseLLMProvider):
    """Local Ollama Provider with auto-discovery of Qwen and installed models."""

    def __init__(self, host: str = "http://localhost:11434", model: Optional[str] = None):
        self.host = host.rstrip("/")
        self.model = resolve_best_local_model(self.host, model)

    def generate(
        self,
        prompt: str,
        system_prompt: Optional[str] = None,
        history: Optional[List[ChatMessage]] = None,
        _retried: bool = False,
    ) -> LLMResponse:
        url = f"{self.host}/api/chat"

        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        if history:
            for msg in history:
                messages.append({"role": msg.role, "content": msg.content})
        messages.append({"role": "user", "content": prompt})

        payload = {
            "model": self.model,
            "messages": messages,
            "stream": False,
        }

        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            url,
            data=data,
            headers={"Content-Type": "application/json"},
            method="POST",
        )

        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                result = json.loads(resp.read().decode("utf-8"))
                text = result["message"]["content"]
                return LLMResponse(content=text, provider=f"Ollama ({self.model})", model=self.model)
        except urllib.error.HTTPError as e:
            err_body = e.read().decode("utf-8", errors="ignore")
            try:
                err_json = json.loads(err_body)
                err_msg = err_json.get("error", err_body)
            except Exception:
                err_msg = err_body

            # Self-healing: if 404 model not found, auto-discover installed models and retry
            if (e.code == 404 or "not found" in err_msg.lower()) and not _retried:
                installed = get_installed_ollama_models(self.host)
                if installed:
                    best = resolve_best_local_model(self.host)
                    target = best if best != self.model else installed[0]
                    if target != self.model:
                        self.model = target
                        return self.generate(prompt, system_prompt=system_prompt, history=history, _retried=True)
                raise RuntimeError(
                    f"Model '{self.model}' not found in Ollama. "
                    f"Installed models: {installed or 'none'}. Run: `ollama pull qwen2.5-coder`."
                )

            raise RuntimeError(f"Ollama Error ({e.code}): {err_msg}")
        except urllib.error.URLError as e:
            reason = getattr(e, 'reason', e)
            raise RuntimeError(
                f"Could not connect to Ollama server at {self.host} ({reason}). "
                f"Make sure Ollama is running (`ollama serve`)."
            )


class QwenProvider(BaseLLMProvider):
    """
    Local Qwen Provider for Robotics & Code Improvement.
    Auto-detects installed Qwen models (e.g. qwen2.5-coder, qwen2.5, qwen2)
    via Ollama or local OpenAI-compatible endpoints (LM Studio, vLLM).
    """

    def __init__(
        self,
        endpoint: Optional[str] = None,
        model: Optional[str] = None,
    ):
        self.endpoint = (endpoint or os.environ.get("QWEN_ENDPOINT", "http://localhost:11434")).rstrip("/")
        self.model = resolve_best_local_model(self.endpoint, model or os.environ.get("QWEN_MODEL"))

    def generate(
        self,
        prompt: str,
        system_prompt: Optional[str] = None,
        history: Optional[List[ChatMessage]] = None,
        _retried: bool = False,
    ) -> LLMResponse:
        from robosage.agent.prompts import QWEN_ROBOTICS_CODE_IMPROVER_PROMPT
        effective_sys = system_prompt or QWEN_ROBOTICS_CODE_IMPROVER_PROMPT

        # Check if endpoint is OpenAI-compatible (/v1, :1234, :8000)
        is_openai_compat = "/v1" in self.endpoint or ":1234" in self.endpoint or ":8000" in self.endpoint

        if is_openai_compat:
            url = f"{self.endpoint}/chat/completions" if "/v1" in self.endpoint else f"{self.endpoint}/v1/chat/completions"
            messages = [{"role": "system", "content": effective_sys}]
            if history:
                for msg in history:
                    messages.append({"role": msg.role, "content": msg.content})
            messages.append({"role": "user", "content": prompt})

            payload = {"model": self.model, "messages": messages, "temperature": 0.2}
            data = json.dumps(payload).encode("utf-8")
            req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"}, method="POST")

            try:
                with urllib.request.urlopen(req, timeout=60) as resp:
                    result = json.loads(resp.read().decode("utf-8"))
                    text = result["choices"][0]["message"]["content"]
                    return LLMResponse(content=text, provider=f"Qwen ({self.model})", model=self.model)
            except Exception as e:
                raise RuntimeError(f"Qwen Local Server Error: {e}")

        else:
            # Default to Ollama API
            url = f"{self.endpoint}/api/chat"
            messages = [{"role": "system", "content": effective_sys}]
            if history:
                for msg in history:
                    messages.append({"role": msg.role, "content": msg.content})
            messages.append({"role": "user", "content": prompt})

            payload = {"model": self.model, "messages": messages, "stream": False}
            data = json.dumps(payload).encode("utf-8")
            req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"}, method="POST")

            try:
                with urllib.request.urlopen(req, timeout=60) as resp:
                    result = json.loads(resp.read().decode("utf-8"))
                    text = result["message"]["content"]
                    return LLMResponse(content=text, provider=f"Qwen ({self.model})", model=self.model)
            except urllib.error.HTTPError as e:
                err_body = e.read().decode("utf-8", errors="ignore")
                try:
                    err_json = json.loads(err_body)
                    err_msg = err_json.get("error", err_body)
                except Exception:
                    err_msg = err_body

                # If 404 model not found, auto-switch to installed model and retry
                if (e.code == 404 or "not found" in err_msg.lower()) and not _retried:
                    installed = get_installed_ollama_models(self.endpoint)
                    if installed:
                        best = resolve_best_local_model(self.endpoint)
                        target = best if best != self.model else installed[0]
                        if target != self.model:
                            self.model = target
                            return self.generate(prompt, system_prompt=system_prompt, history=history, _retried=True)
                    raise RuntimeError(
                        f"Model '{self.model}' not found in Ollama. "
                        f"Installed models: {installed or 'none'}. Run: `ollama pull qwen2.5-coder`."
                    )

                raise RuntimeError(f"Qwen Ollama Error ({e.code}): {err_msg}")
            except urllib.error.URLError as e:
                reason = getattr(e, 'reason', e)
                raise RuntimeError(
                    f"Could not connect to Qwen at {self.endpoint} ({reason}). "
                    f"Ensure Ollama is running (`ollama serve`)."
                )

    def improve_code(self, code: str, focus: str = "all") -> str:
        """Specialized robotics code refactoring pipeline."""
        prompt = (
            f"Please inspect, audit, refactor, and improve the following ROS 2 robotics code.\n"
            f"Focus area: {focus.upper()}\n\n"
            f"```\n{code}\n```\n\n"
            f"Apply production-grade robotics standards:\n"
            f"- Failsafe E-Stop on shutdown for cmd_vel/Twist publishers\n"
            f"- Watchdog timer for sensor streams\n"
            f"- Filter NaNs/Infs on sensor ranges\n"
            f"- Prevent SingleThreadedExecutor service deadlocks (use async)\n"
            f"- Use proper QoS (SensorDataQoS for sensors)\n"
            f"- Wrap shared state in mutex locks if multi-threaded\n"
            f"- Output the complete improved code and bulleted improvements."
        )
        resp = self.generate(prompt)
        return resp.content


class OfflineRoboticsProvider(BaseLLMProvider):
    """
    Zero-network offline diagnostic intelligence.
    Provides expert ROS 2 reasoning and advice when no API key or Ollama instance is configured.
    """

    def generate(
        self,
        prompt: str,
        system_prompt: Optional[str] = None,
        history: Optional[List[ChatMessage]] = None,
    ) -> LLMResponse:
        p_lower = prompt.lower()

        if "qos" in p_lower:
            response = (
                "**ROS 2 Quality of Service (QoS) Diagnostics:**\n\n"
                "In ROS 2, DDS enforces Request vs. Offered (RxO) rules:\n"
                "- **Reliability:** A Subscriber requesting `RELIABLE` will **not** receive messages from a Publisher offering `BEST_EFFORT`. (E.g. LiDAR drivers publishing best-effort will not connect to a default reliable subscriber).\n"
                "- **Durability:** A Subscriber requesting `TRANSIENT_LOCAL` (latched topics like `/map`, `/tf_static`) requires the publisher to also offer `TRANSIENT_LOCAL`.\n\n"
                "**Solution:** Use `rclpy.qos.qos_profile_sensor_data` (Python) or `rclcpp::SensorDataQoS()` (C++) for sensor topics."
            )
        elif "tf" in p_lower or "transform" in p_lower:
            response = (
                "**ROS 2 TF2 Transform Troubleshooting:**\n\n"
                "Common causes for TF failures:\n"
                "1. **Extrapolation into the future:** Broadcaster has slight timestamp delay compared to sensor msg header. Use `lookup_transform(..., timeout=Duration(seconds=0.05))` or request latest transform with `Time()`.\n"
                "2. **Missing Frame:** The publisher for that frame (e.g. `robot_state_publisher` or `ekf_node`) is not running or crashing.\n"
                "3. **use_sim_time Mismatch:** One node is using simulation clock (`use_sim_time:=true`) while another uses system time."
            )
        elif "deadlock" in p_lower or "executor" in p_lower:
            response = (
                "**ROS 2 Executor Deadlock Prevention:**\n\n"
                "Calling `client.call()` or awaiting a future synchronously inside a timer or subscription callback locks the single-threaded executor!\n"
                "**Fixes:**\n"
                "1. Use `client.call_async()` with `future.add_done_callback(cb)`.\n"
                "2. Use `MultiThreadedExecutor` with a `ReentrantCallbackGroup` and protect mutable class variables with `threading.Lock()`."
            )
        elif "audit" in p_lower or "loophole" in p_lower:
            response = (
                "**Robotics Safety Audit Guide:**\n\n"
                "Key loopholes to watch out for in production robots:\n"
                "1. **Missing E-Stop on Shutdown:** Nodes publishing `/cmd_vel` must register an `on_shutdown` hook to publish a zero velocity Twist.\n"
                "2. **Sensor Watchdogs:** Implement timeout checks so the robot halts if the camera or LiDAR stream freezes.\n"
                "3. **Unchecked NaNs:** Sensors report NaN/Inf on beam drops. Filter with `math.isfinite()` before publishing to controllers."
            )
        else:
            response = (
                "**RoboSage Robotics Assistant (Offline Mode):**\n\n"
                f"Received request regarding: '{prompt[:100]}...'\n\n"
                "I am running in offline rule-based diagnostic mode. You can configure a cloud or local LLM at any time by setting:\n"
                "- `export GEMINI_API_KEY='your_key'`\n"
                "- `export OPENAI_API_KEY='your_key'`\n"
                "- `export ANTHROPIC_API_KEY='your_key'`\n"
                "- Or connect local Qwen (`ollama run qwen2.5-coder`)."
            )

        return LLMResponse(content=response, provider="RoboSage Heuristic Engine (Offline)", model="robotics-rules-v1")


def get_llm_provider(
    provider_name: Optional[str] = None,
    api_key: Optional[str] = None,
    model: Optional[str] = None,
    endpoint: Optional[str] = None,
) -> BaseLLMProvider:
    """Factory to create appropriate LLM provider with automatic fallback detection."""
    name = (provider_name or os.environ.get("ROBOSAGE_LLM_PROVIDER", "auto")).lower()

    # 1. Direct Qwen selection
    if name == "qwen":
        return QwenProvider(endpoint=endpoint, model=model)

    if name == "gemini" or (name == "auto" and os.environ.get("GEMINI_API_KEY")):
        return GeminiProvider(api_key=api_key, model=model or "gemini-1.5-flash")

    if name == "openai" or (name == "auto" and os.environ.get("OPENAI_API_KEY")):
        return OpenAIProvider(api_key=api_key, model=model or "gpt-4o-mini")

    if name == "anthropic" or (name == "auto" and os.environ.get("ANTHROPIC_API_KEY")):
        return AnthropicProvider(api_key=api_key, model=model or "claude-3-5-sonnet-20241022")

    if name in ("ollama", "local"):
        return QwenProvider(endpoint=endpoint, model=model)

    # If auto, check if local Qwen/Ollama server is responding
    if name == "auto":
        # Check Ollama on port 11434
        try:
            req = urllib.request.Request("http://localhost:11434/api/tags", method="GET")
            with urllib.request.urlopen(req, timeout=0.8) as resp:
                if resp.status == 200:
                    return QwenProvider(endpoint="http://localhost:11434", model=model)
        except Exception:
            pass

        # Check LM Studio on port 1234
        try:
            req = urllib.request.Request("http://localhost:1234/v1/models", method="GET")
            with urllib.request.urlopen(req, timeout=0.8) as resp:
                if resp.status == 200:
                    return QwenProvider(endpoint="http://localhost:1234/v1", model=model)
        except Exception:
            pass

    # Default to offline robotics engine
    return OfflineRoboticsProvider()
