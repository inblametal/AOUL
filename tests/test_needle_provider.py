"""Unit tests for Cactus Needle 3 Edge Agent Provider."""

import unittest
from unittest.mock import MagicMock, patch

from robosage.llm.needle_provider import CactusNeedleProvider, _build_needle_tools
from robosage.llm.provider import get_llm_provider


class TestCactusNeedleProvider(unittest.TestCase):

    def test_provider_instantiation(self):
        provider = CactusNeedleProvider(model="cactus-needle-3")
        self.assertEqual(provider.model, "cactus-needle-3")

    def test_get_llm_provider_routing(self):
        p1 = get_llm_provider("cactus")
        self.assertIsInstance(p1, CactusNeedleProvider)

        p2 = get_llm_provider("needle3")
        self.assertIsInstance(p2, CactusNeedleProvider)

        p3 = get_llm_provider("cactus-needle")
        self.assertIsInstance(p3, CactusNeedleProvider)

        p4 = get_llm_provider(model="cactus-needle-3")
        self.assertIsInstance(p4, CactusNeedleProvider)

    def test_build_needle_tools(self):
        tools = _build_needle_tools()
        self.assertTrue(len(tools) >= 5)
        tool_names = [t.__name__ for t in tools]
        self.assertIn("trigger_estop", tool_names)
        self.assertIn("set_robot_velocity", tool_names)
        self.assertIn("check_qos_compatibility_tool", tool_names)
        self.assertIn("audit_robotics_code_tool", tool_names)
        self.assertIn("triage_ros_log_tool", tool_names)

    def test_trigger_estop_tool_execution(self):
        tools = _build_needle_tools()
        estop_fn = next(t for t in tools if t.__name__ == "trigger_estop")
        res = estop_fn("Obstacle detected within 0.2m")
        self.assertEqual(res["status"], "ESTOP_ENGAGED")
        self.assertEqual(res["cmd_vel_linear"], 0.0)
        self.assertEqual(res["cmd_vel_angular"], 0.0)
        self.assertEqual(res["reason"], "Obstacle detected within 0.2m")
        self.assertEqual(res["brakes"], "LOCKED")

    def test_set_velocity_safety_clamp(self):
        tools = _build_needle_tools()
        vel_fn = next(t for t in tools if t.__name__ == "set_robot_velocity")
        # Over limits: 5.0 linear, 10.0 angular
        res = vel_fn(linear_x=5.0, angular_z=10.0)
        self.assertEqual(res["status"], "VELOCITY_COMMAND_SENT")
        self.assertEqual(res["linear_x"], 1.0)
        self.assertEqual(res["angular_z"], 1.5)
        self.assertTrue(res["safety_clamped"])

    def test_check_qos_tool_execution(self):
        tools = _build_needle_tools()
        qos_fn = next(t for t in tools if t.__name__ == "check_qos_compatibility_tool")
        res = qos_fn(pub_reliability="BEST_EFFORT", sub_reliability="RELIABLE")
        self.assertFalse(res["is_compatible"])
        self.assertTrue(len(res["issues"]) > 0)

    @patch("robosage.llm.needle_provider.needle.Needle")
    def test_generate_with_tool_results(self, mock_needle_cls):
        mock_instance = MagicMock()
        mock_needle_cls.return_value = mock_instance
        mock_instance.run.return_value = {
            "type": "respond",
            "success": True,
            "reasoning": "Collision risk -> triggered emergency stop.",
            "confidence": 0.95,
            "peak_ram_mb": 108.5,
            "prefill_tps": 22.0,
            "results": [{"status": "ESTOP_ENGAGED", "reason": "wall nearby"}],
        }

        provider = CactusNeedleProvider()
        resp = provider.generate("Emergency brake now!")

        self.assertIn("Cactus Needle 3", resp.provider)
        self.assertIn("ESTOP_ENGAGED", resp.content)
        self.assertIn("108.5 MB", resp.content)
        self.assertIn("95.0%", resp.content)

    @patch("robosage.llm.needle_provider.needle.Needle")
    def test_generate_stream(self, mock_needle_cls):
        mock_instance = MagicMock()
        mock_needle_cls.return_value = mock_instance
        mock_instance.run.return_value = {
            "type": "respond",
            "success": True,
            "reasoning": "Triggering e-stop",
            "confidence": 0.99,
            "peak_ram_mb": 110.0,
            "results": [{"status": "ESTOP_ENGAGED"}],
        }

        provider = CactusNeedleProvider()
        chunks = list(provider.generate_stream("Emergency brake!"))
        full_text = "".join(chunks)
        self.assertIn("ESTOP_ENGAGED", full_text)


if __name__ == "__main__":
    unittest.main()
