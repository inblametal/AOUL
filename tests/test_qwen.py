"""Unit tests for local Qwen robotics code improver provider."""

import json
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


    def test_resolve_best_local_model_priority(self):
        from robosage.llm.provider import resolve_best_local_model
        with patch("robosage.llm.provider.get_installed_ollama_models") as mock_tags:
            # Case 1: Has qwen2.5-coder
            mock_tags.return_value = ["llama3:latest", "qwen2.5-coder:7b", "mistral:latest"]
            self.assertEqual(resolve_best_local_model(), "qwen2.5-coder:7b")

            # Case 2: Has generic qwen2.5
            mock_tags.return_value = ["llama3:latest", "qwen2.5:latest"]
            self.assertEqual(resolve_best_local_model(), "qwen2.5:latest")

            # Case 3: Has any qwen tag
            mock_tags.return_value = ["qwen:7b", "deepseek-coder:6.7b"]
            self.assertEqual(resolve_best_local_model(), "qwen:7b")

            # Case 4: No qwen, falls back to first
            mock_tags.return_value = ["codellama:7b", "phi3:latest"]
            self.assertEqual(resolve_best_local_model(), "codellama:7b")

    @patch("urllib.request.urlopen")
    def test_qwen_404_self_healing_retry(self, mock_urlopen):
        import urllib.error
        from robosage.llm.provider import QwenProvider

        def fake_urlopen(req, *args, **kwargs):
            url = req.full_url if hasattr(req, 'full_url') else str(req)
            m = MagicMock()
            if "/api/tags" in url:
                m.read.return_value = b'{"models": [{"name": "qwen2.5:latest"}]}'
            elif "/api/chat" in url:
                payload = json.loads(req.data.decode('utf-8'))
                if payload.get("model") == "nonexistent_model":
                    raise urllib.error.HTTPError(
                        url=url, code=404, msg="Not Found", hdrs={},
                        fp=MagicMock(read=lambda: b'{"error": "model nonexistent_model not found"}')
                    )
                m.read.return_value = b'{"message": {"content": "Self-healed response"}}'
            return MagicMock(__enter__=lambda s: m)

        mock_urlopen.side_effect = fake_urlopen

        qwen = QwenProvider(model="nonexistent_model")
        resp = qwen.generate("hello robot")
        self.assertEqual(resp.content, "Self-healed response")
        self.assertEqual(qwen.model, "qwen2.5:latest")


if __name__ == "__main__":
    unittest.main()
