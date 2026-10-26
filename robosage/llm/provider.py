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

    def generate_stream(
        self,
        prompt: str,
        system_prompt: Optional[str] = None,
        history: Optional[List[ChatMessage]] = None,
    ):
        """Default stream implementation falls back to generate()."""
        resp = self.generate(prompt=prompt, system_prompt=system_prompt, history=history)
        yield resp.content


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


_MODEL_CACHE: Dict[str, Any] = {"models": [], "timestamp": 0.0, "checked": False}


def get_installed_ollama_models(host: str = "http://127.0.0.1:11434", force_refresh: bool = False) -> List[str]:
    """Queries Ollama for list of locally installed model names with 5s caching."""
    import time
    now = time.time()
    if not force_refresh and _MODEL_CACHE["checked"] and (now - _MODEL_CACHE["timestamp"] < 5.0):
        return _MODEL_CACHE["models"]

    try:
        req = urllib.request.Request(f"{host.rstrip('/')}/api/tags", method="GET")
        with urllib.request.urlopen(req, timeout=1.5) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            models = [m.get("name", "") for m in data.get("models", []) if m.get("name")]
            _MODEL_CACHE["models"] = models
            _MODEL_CACHE["timestamp"] = now
            _MODEL_CACHE["checked"] = True
            return models
    except Exception:
        _MODEL_CACHE["models"] = []
        _MODEL_CACHE["timestamp"] = now
        _MODEL_CACHE["checked"] = True
        return []


def resolve_turbo_model(host: str = "http://127.0.0.1:11434") -> Optional[str]:
    """Finds the fastest lightweight model (0.5b, 1b, 1.5b, 3b) for 20+ tok/s output."""
    installed = get_installed_ollama_models(host)
    for pattern in [":0.5b", "0.5b", ":1b", "1b", "1.5b", "3b"]:
        for m in installed:
            if pattern in m.lower():
                return m
    return None


def resolve_best_local_model(host: str = "http://127.0.0.1:11434", requested: Optional[str] = None) -> str:
    """Finds best matching model in Ollama, prioritizing Qwen Coder or Turbo Fast."""
    installed = get_installed_ollama_models(host)
    if not installed:
        return requested if (requested and requested.lower() not in ("auto", "qwen", "qwen-coder", "qwencoder", "local", "turbo", "fast")) else "qwen2.5-coder:latest"

    # Explicit turbo / speed request
    if requested and requested.lower() in ("turbo", "fast", "speed", "turbo-fast"):
        turbo = resolve_turbo_model(host)
        if turbo:
            return turbo

    # If requested model was explicitly specified, use/match it
    if requested and requested.lower() not in ("auto", "qwen", "qwen-coder", "qwencoder", "local", "turbo", "fast"):
        for m in installed:
            if m.lower() == requested.lower() or m.lower().startswith(requested.lower() + ":"):
                return m
        return requested

    # Priority 1: Any model with BOTH 'qwen' and 'coder' in its name (e.g. qwen2.5-coder, qwen-coder, qwen2.5-coder:7b)
    for m in installed:
        m_low = m.lower()
        if "qwen" in m_low and "coder" in m_low:
            return m

    # Priority 2: Any Qwen model (e.g. qwen2.5, qwen2, qwen)
    for m in installed:
        if "qwen" in m.lower():
            return m

    # Priority 3: Any Coder model (e.g. deepseek-coder, codellama)
    for m in installed:
        if "coder" in m.lower():
            return m

    return installed[0]


def warm_up_local_model(host: str = "http://127.0.0.1:11434", model: Optional[str] = None) -> bool:
    """
    Preloads local Qwen Coder model into unified GPU/RAM with keep_alive: 24h.
    This eliminates cold-start model weight loading timeouts when the user chats.
    """
    try:
        target_model = resolve_best_local_model(host, model)
        url = f"{host.rstrip('/')}/api/generate"
        payload = {
            "model": target_model,
            "keep_alive": "24h",
            "prompt": "",
        }
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            url,
            data=data,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=120) as resp:
            return resp.status == 200
    except Exception:
        return False


class OllamaProvider(BaseLLMProvider):
    """Local Ollama Provider with auto-discovery of Qwen Coder and installed models."""

    def __init__(self, host: str = "http://127.0.0.1:11434", model: Optional[str] = None):
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
            "keep_alive": "24h",
        }

        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            url,
            data=data,
            headers={"Content-Type": "application/json"},
            method="POST",
        )

        try:
            with urllib.request.urlopen(req, timeout=180) as resp:
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
                installed = get_installed_ollama_models(self.host, force_refresh=True)
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
        except (TimeoutError, urllib.error.URLError) as e:
            is_timeout = isinstance(e, TimeoutError) or "timed out" in str(e).lower()
            if is_timeout:
                raise RuntimeError(
                    f"Ollama inference timed out after 180s on model '{self.model}'. "
                    f"The model may be loading weights from disk. Please retry in a few seconds."
                )
            reason = getattr(e, 'reason', e)
            raise RuntimeError(
                f"Could not connect to Ollama server at {self.host} ({reason}). "
                f"Make sure Ollama is running (`ollama serve`)."
            )


class QwenProvider(BaseLLMProvider):
    """
    Local Qwen Coder Provider for Robotics & Code Improvement.
    Auto-detects installed Qwen Coder models (e.g. qwen2.5-coder, qwen-coder, qwen2.5-coder:7b)
    via Ollama or local OpenAI-compatible endpoints (LM Studio, vLLM).
    """

    def __init__(
        self,
        endpoint: Optional[str] = None,
        model: Optional[str] = None,
    ):
        self.endpoint = (endpoint or os.environ.get("QWEN_ENDPOINT", "http://127.0.0.1:11434")).rstrip("/")
        self.model = resolve_best_local_model(self.endpoint, model or os.environ.get("QWEN_MODEL"))

    def generate_stream(
        self,
        prompt: str,
        system_prompt: Optional[str] = None,
        history: Optional[List[ChatMessage]] = None,
    ):
        """Streams response tokens from local Qwen Coder in real-time."""
        from robosage.agent.prompts import QWEN_ROBOTICS_CODE_IMPROVER_PROMPT
        effective_sys = system_prompt or QWEN_ROBOTICS_CODE_IMPROVER_PROMPT

        is_openai_compat = "/v1" in self.endpoint or ":1234" in self.endpoint or ":8000" in self.endpoint
        if is_openai_compat:
            resp = self.generate(prompt, system_prompt=system_prompt, history=history)
            yield resp.content
            return

        url = f"{self.endpoint}/api/chat"
        messages = [{"role": "system", "content": effective_sys}]
        if history:
            for msg in history[-6:]:
                messages.append({"role": msg.role, "content": msg.content})
        messages.append({"role": "user", "content": prompt})

        cpu_threads = min(os.cpu_count() or 4, 8)
        payload = {
            "model": self.model,
            "messages": messages,
            "stream": True,
            "keep_alive": "24h",
            "options": {
                "num_thread": cpu_threads,
                "num_ctx": 2048,
                "num_predict": 1024,
                "temperature": 0.4,
                "top_k": 40,
                "top_p": 0.9,
                "repeat_penalty": 1.18,
                "repeat_last_n": 128,
                "presence_penalty": 0.2,
            }
        }
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"}, method="POST")

        try:
            with urllib.request.urlopen(req, timeout=180) as resp:
                for line in resp:
                    if line:
                        try:
                            chunk = json.loads(line.decode("utf-8"))
                            token = chunk.get("message", {}).get("content", "")
                            if token:
                                yield token
                        except Exception:
                            continue
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            reason = getattr(e, 'reason', e)
            raise RuntimeError(
                f"Could not connect to Qwen at {self.endpoint} ({reason}). "
                f"Ensure Ollama is running (`ollama serve`)."
            )

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
                with urllib.request.urlopen(req, timeout=180) as resp:
                    result = json.loads(resp.read().decode("utf-8"))
                    text = result["choices"][0]["message"]["content"]
                    return LLMResponse(content=text, provider=f"Qwen Coder ({self.model})", model=self.model)
            except Exception as e:
                raise RuntimeError(f"Qwen Local Server Error: {e}")

        else:
            # Default to Ollama API
            url = f"{self.endpoint}/api/chat"
            messages = [{"role": "system", "content": effective_sys}]
            if history:
                for msg in history[-6:]:
                    messages.append({"role": msg.role, "content": msg.content})
            messages.append({"role": "user", "content": prompt})

            cpu_threads = min(os.cpu_count() or 4, 8)
            payload = {
                "model": self.model,
                "messages": messages,
                "stream": False,
                "keep_alive": "24h",
                "options": {
                    "num_thread": cpu_threads,
                    "num_ctx": 2048,
                    "num_predict": 1024,
                    "temperature": 0.4,
                    "top_k": 40,
                    "top_p": 0.9,
                    "repeat_penalty": 1.18,
                    "repeat_last_n": 128,
                    "presence_penalty": 0.2,
                }
            }
            data = json.dumps(payload).encode("utf-8")
            req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"}, method="POST")

            try:
                with urllib.request.urlopen(req, timeout=180) as resp:
                    result = json.loads(resp.read().decode("utf-8"))
                    text = result["message"]["content"]
                    return LLMResponse(content=text, provider=f"Qwen Coder ({self.model})", model=self.model)
            except urllib.error.HTTPError as e:
                err_body = e.read().decode("utf-8", errors="ignore")
                try:
                    err_json = json.loads(err_body)
                    err_msg = err_json.get("error", err_body)
                except Exception:
                    err_msg = err_body

                # If 404 model not found, auto-switch to installed model and retry
                if (e.code == 404 or "not found" in err_msg.lower()) and not _retried:
                    installed = get_installed_ollama_models(self.endpoint, force_refresh=True)
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
            except (TimeoutError, urllib.error.URLError) as e:
                is_timeout = isinstance(e, TimeoutError) or "timed out" in str(e).lower()
                if is_timeout:
                    # Trigger background warm-up
                    import threading
                    threading.Thread(target=warm_up_local_model, args=(self.endpoint, self.model), daemon=True).start()
                    raise RuntimeError(
                        f"Local Qwen Coder model inference timed out. "
                        f"Ollama is warming up and loading the '{self.model}' weights into unified memory (24h keep-alive enabled). "
                        f"Please click Send again in a moment — inference will run fast once cached!"
                    )
                reason = getattr(e, 'reason', e)
                raise RuntimeError(
                    f"Could not connect to Qwen at {self.endpoint} ({reason}). "
                    f"Ensure Ollama is running (`ollama serve`)."
                )

    def improve_code(self, code: str, focus: str = "all") -> str:
        """Specialized robotics code refactoring pipeline powered by Qwen Coder."""
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
                "**AOUL Robotics Assistant (Offline Mode):**\n\n"
                f"Received request regarding: '{prompt[:100]}...'\n\n"
                "I am running in offline rule-based diagnostic mode for AOUL (Actuator, Orientation, Undefined-behavior, Locator). You can configure a cloud or local LLM at any time by setting:\n"
                "- `export GEMINI_API_KEY='your_key'`\n"
                "- `export OPENAI_API_KEY='your_key'`\n"
                "- `export ANTHROPIC_API_KEY='your_key'`\n"
                "- Or connect local Qwen Coder (`ollama run qwen2.5-coder`)."
            )

        return LLMResponse(content=response, provider="AOUL Heuristic Engine (Offline)", model="robotics-rules-v1")


def get_llm_provider(
    provider_name: Optional[str] = None,
    api_key: Optional[str] = None,
    model: Optional[str] = None,
    endpoint: Optional[str] = None,
) -> BaseLLMProvider:
    """Factory to create appropriate LLM provider with automatic fallback detection."""
    name = (provider_name or os.environ.get("AOUL_LLM_PROVIDER", os.environ.get("ROBOSAGE_LLM_PROVIDER", "auto"))).lower()

    # 0. Offline Heuristic Engine
    if name in ("offline", "heuristic", "builtin", "rule", "rules"):
        return OfflineRoboticsProvider()

    # 1. Cactus Needle 3 Edge Agent
    if name in ("cactus", "needle", "needle3", "cactus-needle", "cactus-needle-3") or (model and "needle" in str(model).lower()):
        from robosage.llm.needle_provider import CactusNeedleProvider
        return CactusNeedleProvider(model=model or "cactus-needle-3")

    # 2. Direct Qwen Coder / Local selection
    if name in ("qwen", "qwen-coder", "qwencoder", "ollama", "local"):
        return QwenProvider(endpoint=endpoint, model=model)

    if name == "gemini" or (name == "auto" and os.environ.get("GEMINI_API_KEY")):
        return GeminiProvider(api_key=api_key, model=model or "gemini-1.5-flash")

    if name == "openai" or (name == "auto" and os.environ.get("OPENAI_API_KEY")):
        return OpenAIProvider(api_key=api_key, model=model or "gpt-4o-mini")

    if name == "anthropic" or (name == "auto" and os.environ.get("ANTHROPIC_API_KEY")):
        return AnthropicProvider(api_key=api_key, model=model or "claude-3-5-sonnet-20241022")

    # If auto, check if local Qwen/Ollama server is responding
    if name == "auto":
        # Check Ollama on port 11434
        try:
            req = urllib.request.Request("http://127.0.0.1:11434/api/tags", method="GET")
            with urllib.request.urlopen(req, timeout=2.5) as resp:
                if resp.status == 200:
                    return QwenProvider(endpoint="http://127.0.0.1:11434", model=model)
        except Exception:
            pass

        # Check LM Studio on port 1234
        try:
            req = urllib.request.Request("http://127.0.0.1:1234/v1/models", method="GET")
            with urllib.request.urlopen(req, timeout=2.5) as resp:
                if resp.status == 200:
                    return QwenProvider(endpoint="http://127.0.0.1:1234/v1", model=model)
        except Exception:
            pass

    # Default to QwenProvider if Ollama models are installed, else offline engine
    installed = get_installed_ollama_models(endpoint or "http://127.0.0.1:11434")
    if installed:
        return QwenProvider(endpoint=endpoint, model=model)

    return OfflineRoboticsProvider()
