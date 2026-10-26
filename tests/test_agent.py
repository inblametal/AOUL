"""Tests for Agent Core & Tool Registry."""

import unittest
from aoul.agent.core import AgentSession
from aoul.agent.tools import RoboticsToolRegistry
from aoul.llm.provider import OfflineRoboticsProvider


class TestAgent(unittest.TestCase):

    def setUp(self):
        self.provider = OfflineRoboticsProvider()
        self.session = AgentSession(provider=self.provider)

    def test_offline_agent_step(self):
        reply = self.session.step("How do I avoid QoS incompatibility in ROS 2?")
        self.assertIn("QoS", reply)
        self.assertIn("Reliability", reply)
        self.assertEqual(len(self.session.conversation_history), 2)

    def test_tool_registry_execution(self):
        reg = RoboticsToolRegistry()
        tools = reg.list_tools()
        self.assertTrue(len(tools) >= 4)

        # Execute check_qos tool
        res = reg.execute(
            "check_qos_compatibility",
            pub_reliability="BEST_EFFORT",
            pub_durability="VOLATILE",
            sub_reliability="RELIABLE",
            sub_durability="VOLATILE",
        )
        self.assertIn("INCOMPATIBLE", res)


if __name__ == "__main__":
    unittest.main()
