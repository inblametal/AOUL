"""
Local, offline Speech-to-Text Transcriber for robotics lab benches.
Supports:
1. whisper.cpp (high-performance C++ edge inference via whisper-cli)
2. Python openai-whisper / faster-whisper
3. Fallback to Web Speech API / On-Device macOS Dictation
"""

from dataclasses import dataclass
import os
import shutil
import subprocess
import sys
import tempfile
import time
from typing import Any, Dict, List, Optional


@dataclass
class VoiceEngineStatus:
    whisper_cpp_available: bool
    whisper_cpp_binary: Optional[str]
    whisper_model_path: Optional[str]
    python_whisper_available: bool
    active_engine: str
    wake_word: str = "AOUL"
    supported_models: List[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "whisper_cpp_available": self.whisper_cpp_available,
            "whisper_cpp_binary": self.whisper_cpp_binary,
            "whisper_model_path": self.whisper_model_path,
            "python_whisper_available": self.python_whisper_available,
            "active_engine": self.active_engine,
            "wake_word": self.wake_word,
            "supported_models": self.supported_models or ["tiny.en (75MB)", "base.en (142MB)", "small.en (466MB)"],
        }


class VoiceTranscriber:
    """
    Orchestrates local speech-to-text inference for hands-free lab operation.
    """

    def __init__(self, custom_binary: Optional[str] = None, custom_model: Optional[str] = None):
        self.custom_binary = custom_binary or os.environ.get("WHISPER_CPP_BIN")
        self.custom_model = custom_model or os.environ.get("WHISPER_MODEL_PATH")
        self._python_whisper_model = None

    def find_whisper_cpp_binary(self) -> Optional[str]:
        """Locates compiled whisper.cpp executable on system."""
        if self.custom_binary and os.path.isfile(self.custom_binary) and os.access(self.custom_binary, os.X_OK):
            return self.custom_binary

        candidates = [
            shutil.which("whisper-cli"),
            shutil.which("whisper-cpp"),
            shutil.which("main"),
            os.path.expanduser("~/.local/bin/whisper-cli"),
            os.path.expanduser("~/whisper.cpp/build/bin/whisper-cli"),
            os.path.expanduser("~/whisper.cpp/main"),
            "/usr/local/bin/whisper-cli",
            "/opt/homebrew/bin/whisper-cli",
        ]
        for c in candidates:
            if c and os.path.isfile(c) and os.access(c, os.X_OK):
                return c
        return None

    def find_whisper_model(self) -> Optional[str]:
        """Locates downloaded GGML / GGUF whisper model weights."""
        if self.custom_model and os.path.isfile(self.custom_model):
            return self.custom_model

        model_candidates = [
            "ggml-tiny.en.bin",
            "ggml-base.en.bin",
            "ggml-small.en.bin",
            "ggml-tiny.bin",
            "ggml-base.bin",
        ]
        search_dirs = [
            os.path.expanduser("~/.cache/whisper.cpp"),
            os.path.expanduser("~/whisper.cpp/models"),
            "/usr/local/share/whisper.cpp",
            os.path.abspath("models"),
        ]

        for s_dir in search_dirs:
            if os.path.isdir(s_dir):
                for m in model_candidates:
                    p = os.path.join(s_dir, m)
                    if os.path.isfile(p):
                        return p
        return None

    def has_python_whisper(self) -> bool:
        """Checks if python whisper package is importable."""
        try:
            import whisper  # noqa: F401
            return True
        except ImportError:
            return False

    def get_status(self) -> VoiceEngineStatus:
        binary = self.find_whisper_cpp_binary()
        model = self.find_whisper_model()
        py_whisper = self.has_python_whisper()

        if binary and model:
            active = "whisper.cpp (Edge C++ Native)"
        elif py_whisper:
            active = "Python Whisper (Torch)"
        else:
            active = "Web Speech API (macOS Offline Dictation)"

        return VoiceEngineStatus(
            whisper_cpp_available=bool(binary and model),
            whisper_cpp_binary=binary,
            whisper_model_path=model,
            python_whisper_available=py_whisper,
            active_engine=active,
            wake_word="AOUL",
            supported_models=["tiny.en (75MB)", "base.en (142MB)", "small.en (466MB)"],
        )

    def transcribe_audio_file(self, audio_path: str) -> Dict[str, Any]:
        """Transcribes local WAV/audio file using whisper.cpp or python fallback."""
        if not os.path.isfile(audio_path):
            return {"error": f"Audio file not found: {audio_path}", "text": ""}

        status = self.get_status()
        t0 = time.time()

        # 1. High-speed whisper.cpp
        if status.whisper_cpp_available and status.whisper_cpp_binary and status.whisper_model_path:
            cmd = [
                status.whisper_cpp_binary,
                "-m", status.whisper_model_path,
                "-f", audio_path,
                "-nt",  # no timestamps
                "--no-prints",
            ]
            try:
                proc = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
                dur = time.time() - t0
                if proc.returncode == 0:
                    text = proc.stdout.strip()
                    return {
                        "text": text,
                        "engine": "whisper.cpp",
                        "duration_sec": round(dur, 2),
                        "model": os.path.basename(status.whisper_model_path),
                    }
            except Exception as e:
                pass

        # 2. Python Whisper fallback
        if status.python_whisper_available:
            try:
                import whisper
                if self._python_whisper_model is None:
                    self._python_whisper_model = whisper.load_model("tiny.en")
                result = self._python_whisper_model.transcribe(audio_path)
                dur = time.time() - t0
                return {
                    "text": result.get("text", "").strip(),
                    "engine": "python-whisper",
                    "duration_sec": round(dur, 2),
                    "model": "tiny.en",
                }
            except Exception as e:
                pass

        # 3. Inform caller to rely on client-side native SpeechRecognition
        return {
            "text": "",
            "engine": "web-speech-fallback",
            "message": "Local whisper.cpp not yet compiled. Use browser Web Speech API or run scripts/setup_whisper_cpp.sh.",
        }

    def transcribe_audio_bytes(self, audio_bytes: bytes, filename: str = "audio.wav") -> Dict[str, Any]:
        """Saves temporary audio buffer and executes transcription."""
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
            f.write(audio_bytes)
            tmp_path = f.name

        try:
            return self.transcribe_audio_file(tmp_path)
        finally:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)


_GLOBAL_TRANSCRIBER: Optional[VoiceTranscriber] = None


def get_voice_transcriber() -> VoiceTranscriber:
    global _GLOBAL_TRANSCRIBER
    if _GLOBAL_TRANSCRIBER is None:
        _GLOBAL_TRANSCRIBER = VoiceTranscriber()
    return _GLOBAL_TRANSCRIBER
