"""
Unit tests for the Voice-Activated Hands-Free Lab Copilot subsystem.
"""

import os
import unittest
from unittest.mock import MagicMock, patch
from aoul.voice.transcriber import VoiceTranscriber, VoiceEngineStatus, get_voice_transcriber


class TestVoiceSubsystem(unittest.TestCase):
    def setUp(self):
        self.transcriber = VoiceTranscriber()

    def test_voice_engine_status_to_dict(self):
        status = VoiceEngineStatus(
            whisper_cpp_available=False,
            whisper_cpp_binary=None,
            whisper_model_path=None,
            python_whisper_available=False,
            active_engine="Web Speech API (macOS Offline Dictation)",
            wake_word="AOUL",
        )
        d = status.to_dict()
        self.assertEqual(d["wake_word"], "AOUL")
        self.assertEqual(d["whisper_cpp_available"], False)
        self.assertIn("tiny.en (75MB)", d["supported_models"])

    def test_get_status(self):
        status = self.transcriber.get_status()
        self.assertIsInstance(status, VoiceEngineStatus)
        self.assertIn(status.wake_word, ["AOUL", "Hey AOUL"])
        self.assertIsInstance(status.active_engine, str)

    def test_transcribe_nonexistent_file(self):
        res = self.transcriber.transcribe_audio_file("/path/to/nonexistent/audio_file.wav")
        self.assertIn("error", res)
        self.assertEqual(res["text"], "")

    def test_transcribe_audio_bytes_fallback(self):
        # Even with raw dummy bytes, it should gracefully return fallback or transcribe
        dummy_wav = b"RIFF\x24\x00\x00\x00WAVEfmt \x10\x00\x00\x00\x01\x00\x01\x00D\xac\x00\x00\x88X\x01\x00\x02\x00\x10\x00data\x00\x00\x00\x00"
        res = self.transcriber.transcribe_audio_bytes(dummy_wav)
        self.assertIsInstance(res, dict)
        self.assertTrue("text" in res or "error" in res or "engine" in res)

    @patch("subprocess.run")
    def test_whisper_cpp_mock_execution(self, mock_run):
        mock_run.return_value = MagicMock(return_code=0, stdout="AOUL emergency stop", returncode=0)
        custom_t = VoiceTranscriber(custom_binary="/bin/echo", custom_model="/dev/null")
        with patch.object(os.path, "isfile", return_value=True), \
             patch.object(os, "access", return_value=True):
            res = custom_t.transcribe_audio_file("/tmp/fake.wav")
            self.assertEqual(res.get("engine"), "whisper.cpp")
            self.assertEqual(res.get("text"), "AOUL emergency stop")

    def test_get_voice_transcriber_singleton(self):
        t1 = get_voice_transcriber()
        t2 = get_voice_transcriber()
        self.assertIs(t1, t2)


if __name__ == "__main__":
    unittest.main()
