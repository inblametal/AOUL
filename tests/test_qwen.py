"""Unit tests for local Qwen robotics code improver provider."""

import unittest
from unittest.mock import MagicMock, patch
from robosage.llm.provider import QwenProvider, get_llm_provider


class TestQwenProvider(unittest.TestCase):

    def test_qwen_provider_instantiation(self):
        qwen = QwenProvider(model="qwen2.5-coder:7b", endpoint="http://localhost:11434")
        self.assertEqual(qwen.model, "qwen2.5-coder:7b")
        self.assertEqual(qwen.endpoint, "http://localhost:11434")

    def test_get_llm_provider_qwen(self):
        p = get_llm_provider("qwen", model="qwen2.5-coder")
        self.assertIsInstance(p, QwenProvider)
        self.assertEqual(p.model, "qwen2.5-coder")

    @patch("urllib.request.urlopen")
    def test_qwen_generate_mock(self, mock_urlopen):
        # Mocking Ollama response
        mock_resp = MagicMock()
        mock_resp.read.return_value = b'{"message": {"content": "Qwen optimized robotics code"}}'
        mock_urlopen.return_value.__enter__.return_value = mock_resp

        qwen = QwenProvider(model="qwen2.5-coder")
        resp = qwen.generate("Refactor this node")
        self.assertIn("Qwen", resp.provider)
        self.assertEqual(resp.content, "Qwen optimized robotics code")

    @patch("urllib.request.urlopen")
    def test_qwen_improve_code_mock(self, mock_urlopen):
        mock_resp = MagicMock()
        mock_resp.read.return_value = b'{"message": {"content": "1. Added E-Stop on shutdown\\n2. Fixed NaN values in LaserScan"}}'
        mock_urlopen.return_value.__enter__.return_value = mock_resp

        qwen = QwenProvider(model="qwen2.5-coder")
        result = qwen.improve_code("cmd_vel = Twist()", focus="safety")
        self.assertIn("E-Stop", result)


if __name__ == "__main__":
    unittest.main()
