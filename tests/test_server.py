"""Unit tests for RoboSage Web Server handlers and REST API dispatch."""

import io
import json
import unittest
from unittest.mock import MagicMock

from robosage.server import RoboSageRequestHandler


class DummyServer:
    pass


class TestServerHandlers(unittest.TestCase):

    def setUp(self):
        self.server = DummyServer()

    def _create_handler(self, path: str, method: str = "GET", body: dict = None):
        handler = RoboSageRequestHandler.__new__(RoboSageRequestHandler)
        handler.server = self.server
        handler.path = path
        handler.command = method
        handler.headers = {"Content-Length": str(len(json.dumps(body))) if body else "0"}
        handler.rfile = io.BytesIO(json.dumps(body).encode("utf-8") if body else b"")
        handler.wfile = io.BytesIO()
        handler.send_response = MagicMock()
        handler.send_header = MagicMock()
        handler.end_headers = MagicMock()

        # Initialize singletons if needed
        if not hasattr(handler.server, "agent_session"):
            from robosage.agent.core import AgentSession
            from robosage.diagnostics.log_analyzer import ROS2LogAnalyzer
            from robosage.diagnostics.loophole_detector import LoopholeDetector
            from robosage.llm.provider import OfflineRoboticsProvider
            handler.server.llm_provider = OfflineRoboticsProvider()
            handler.server.agent_session = AgentSession(provider=handler.server.llm_provider)
            handler.server.log_analyzer = ROS2LogAnalyzer()
            handler.server.loophole_detector = LoopholeDetector()

        return handler

    def test_api_doctor_handler(self):
        handler = self._create_handler("/api/doctor", method="GET")
        handler._handle_doctor()
        response_bytes = handler.wfile.getvalue()
        data = json.loads(response_bytes.decode("utf-8"))
        self.assertIn("active_provider", data)
        self.assertIn("ros_domain_id", data)

    def test_api_check_qos_handler(self):
        body = {
            "pub_reliability": "BEST_EFFORT",
            "pub_durability": "VOLATILE",
            "sub_reliability": "RELIABLE",
            "sub_durability": "VOLATILE",
        }
        handler = self._create_handler("/api/check-qos", method="POST", body=body)
        handler._handle_check_qos(body)
        response_bytes = handler.wfile.getvalue()
        data = json.loads(response_bytes.decode("utf-8"))
        self.assertFalse(data["is_compatible"])
        self.assertEqual(data["status"], "INCOMPATIBLE")

    def test_api_audit_handler(self):
        code = """
import rclpy
from rclpy.node import Node
from geometry_msgs.msg import Twist

class RunawayRobot(Node):
    def __init__(self):
        super().__init__('runaway')
        self.pub = self.create_publisher(Twist, 'cmd_vel', 10)
"""
        body = {"code": code}
        handler = self._create_handler("/api/audit", method="POST", body=body)
        handler._handle_audit(body)
        response_bytes = handler.wfile.getvalue()
        data = json.loads(response_bytes.decode("utf-8"))
        self.assertTrue(data["count"] >= 1)
        self.assertEqual(data["findings"][0]["loophole_type"], "MISSING_ESTOP_ON_SHUTDOWN")

    def test_api_triage_handler(self):
        log = "Lookup would require extrapolation into the future. Requested time 1729252800.100000 but the latest data is at time 1729252800.050000, when looking up transform from frame [base_link] to frame [odom]"
        body = {"log_content": log}
        handler = self._create_handler("/api/triage", method="POST", body=body)
        handler._handle_triage(body)
        response_bytes = handler.wfile.getvalue()
        data = json.loads(response_bytes.decode("utf-8"))
        self.assertEqual(data["count"], 1)
        self.assertEqual(data["incidents"][0]["category"], "TF_ERROR")

    def test_api_generate_handler(self):
        body = {"template_type": "diff_drive", "node_name": "custom_drive"}
        handler = self._create_handler("/api/generate", method="POST", body=body)
        handler._handle_generate(body)
        response_bytes = handler.wfile.getvalue()
        data = json.loads(response_bytes.decode("utf-8"))
        self.assertIn("custom_drive", data["code"])

    def test_api_chat_handler_non_streaming(self):
        body = {"message": "Explain ROS 2 QoS", "provider": "offline", "stream": False}
        handler = self._create_handler("/api/chat", method="POST", body=body)
        handler._handle_chat(body)
        response_bytes = handler.wfile.getvalue()
        data = json.loads(response_bytes.decode("utf-8"))
        self.assertIn("reply", data)
        self.assertIn("QoS", data["reply"])
        self.assertIn("provider", data)

    def test_api_chat_handler_streaming(self):
        body = {"message": "Explain TF transforms", "provider": "offline", "stream": True}
        handler = self._create_handler("/api/chat", method="POST", body=body)
        handler._handle_chat(body)
        self.assertTrue(getattr(handler, "close_connection", False))
        stream_output = handler.wfile.getvalue().decode("utf-8")
        self.assertIn(": heartbeat\n\n", stream_output)
        self.assertIn("data: [DONE]\n\n", stream_output)
        self.assertIn("transform", stream_output.lower())

    def test_api_local_models_handler(self):
        handler = self._create_handler("/api/local-models", method="GET")
        handler._handle_local_models()
        response_bytes = handler.wfile.getvalue()
        data = json.loads(response_bytes.decode("utf-8"))
        self.assertIn("cactus_needle_available", data)
        self.assertIn("installed_models", data)
        self.assertIn("is_cpu_constrained", data)

    def test_api_threads_get_and_post(self):
        # 1. GET threads
        handler = self._create_handler("/api/threads", method="GET")
        handler._handle_get_threads()
        data = json.loads(handler.wfile.getvalue().decode("utf-8"))
        self.assertIn("threads", data)
        self.assertIn("active_thread_id", data)

        # 2. POST create thread
        body = {"action": "create", "title": "Safety E-Stop Verification"}
        handler2 = self._create_handler("/api/threads", method="POST", body=body)
        handler2._handle_post_threads(body)
        data2 = json.loads(handler2.wfile.getvalue().decode("utf-8"))
        self.assertIn("thread", data2)
        self.assertEqual(data2["thread"]["title"], "Safety E-Stop Verification")

    def test_api_memory_get_and_post(self):
        # 1. GET memory
        handler = self._create_handler("/api/memory", method="GET")
        handler._handle_get_memory()
        data = json.loads(handler.wfile.getvalue().decode("utf-8"))
        self.assertIn("robot_profile", data)
        self.assertIn("working_parameters", data)

        # 2. POST add_param
        body = {"action": "add_param", "key": "wheel_base", "value": "0.55m"}
        handler2 = self._create_handler("/api/memory", method="POST", body=body)
        handler2._handle_post_memory(body)
        data2 = json.loads(handler2.wfile.getvalue().decode("utf-8"))
        self.assertTrue(data2["success"])
        self.assertEqual(data2["memory"]["working_parameters"]["wheel_base"], "0.55m")

    def test_api_chat_handler_empty_message(self):
        body = {"message": "", "stream": False}
        handler = self._create_handler("/api/chat", method="POST", body=body)
        handler._handle_chat(body)
        handler.send_response.assert_called_with(400)

    def test_api_voice_status(self):
        handler = self._create_handler("/api/voice-status", method="GET")
        handler._handle_voice_status()
        data = json.loads(handler.wfile.getvalue().decode("utf-8"))
        self.assertIn("wake_word", data)
        self.assertIn("active_engine", data)
        self.assertIn("supported_models", data)

    def test_api_voice_transcribe(self):
        import base64
        dummy_wav = b"RIFF\x24\x00\x00\x00WAVEfmt \x10\x00\x00\x00\x01\x00\x01\x00D\xac\x00\x00\x88X\x01\x00\x02\x00\x10\x00data\x00\x00\x00\x00"
        b64 = base64.b64encode(dummy_wav).decode("ascii")
        body = {"audio": f"data:audio/wav;base64,{b64}"}
        handler = self._create_handler("/api/voice-transcribe", method="POST", body=body)
        handler._handle_voice_transcribe(body, b"")
        data = json.loads(handler.wfile.getvalue().decode("utf-8"))
        self.assertTrue("text" in data or "engine" in data or "error" in data)


if __name__ == "__main__":
    unittest.main()
