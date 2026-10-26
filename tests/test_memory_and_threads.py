"""Unit tests for Robotics Memory Layer, Conversation Threads, and Repetition Loop Buster."""

import unittest
from unittest.mock import MagicMock

from aoul.agent.core import AgentSession, deduplicate_repeating_sentences
from aoul.agent.memory import ConversationManager, ConversationThread, RoboticsMemoryLayer
from aoul.llm.provider import OfflineRoboticsProvider


class TestMemoryAndThreads(unittest.TestCase):

    def test_deduplicate_repeating_sentences(self):
        # Case 1: Simple repeated sentences
        repeated = (
            "The robot has an E-Stop zero velocity command on shutdown. "
            "The robot has an E-Stop zero velocity command on shutdown. "
            "The robot has an E-Stop zero velocity command on shutdown. "
            "Watchdog timer is also configured."
        )
        cleaned = deduplicate_repeating_sentences(repeated)
        self.assertEqual(
            cleaned.strip(),
            "The robot has an E-Stop zero velocity command on shutdown. Watchdog timer is also configured."
        )

        # Case 2: Short text should be unchanged
        short = "Safe cmd_vel."
        self.assertEqual(deduplicate_repeating_sentences(short), short)

        # Case 3: Diverse non-repeating sentences preserved
        diverse = "Sensor stream is active. LiDAR reports 20 Hz. Wheel odometry is nominal."
        self.assertEqual(deduplicate_repeating_sentences(diverse), diverse)

    def test_memory_layer_auto_extraction(self):
        mem = RoboticsMemoryLayer()

        user_msg = "My robot is a 4-wheel differential drive rover using ROS 2 Jazzy and CycloneDDS on /cmd_vel."
        mem.extract_from_text(user_msg)

        self.assertEqual(mem.robot_profile.platform_type, "Differential Drive")
        self.assertIn("Jazzy", mem.robot_profile.ros_distro)
        self.assertEqual(mem.robot_profile.rmw_implementation, "rmw_cyclonedds_cpp")
        self.assertTrue(any("/cmd_vel" in act for act in mem.robot_profile.actuators))

    def test_memory_layer_parameter_extraction(self):
        mem = RoboticsMemoryLayer()
        text = "Setting max_linear_velocity = 2.5 m/s and watchdog_timeout = 0.25s for navigation."
        mem.extract_from_text(text)

        self.assertIn("max_linear_velocity", mem.working_parameters)
        self.assertEqual(mem.working_parameters["max_linear_velocity"], "2.5 m/s")
        self.assertIn("watchdog_timeout", mem.working_parameters)
        self.assertEqual(mem.working_parameters["watchdog_timeout"], "0.25s")

    def test_memory_layer_prompt_injection(self):
        mem = RoboticsMemoryLayer()
        mem.record_issue("Missing E-Stop in runaway_node.py", "CRITICAL", "runaway_node.py", "Add on_shutdown hook")
        prompt = mem.get_system_memory_context()

        self.assertIn("[AOUL Working Memory Layer]", prompt)
        self.assertIn("Differential Drive", prompt)
        self.assertIn("Missing E-Stop", prompt)

    def test_conversation_thread_lifecycle(self):
        thread = ConversationThread(id="test_thread_1", title="New Conversation")

        # First message dynamically names the thread
        thread.add_message("user", "How do I configure LiDAR QoS SensorDataQoS profile in ROS 2?")
        self.assertNotEqual(thread.title, "New Conversation")
        self.assertIn("LiDAR", thread.title)

        thread.add_message("assistant", "Use rclpy.qos.qos_profile_sensor_data.")
        self.assertEqual(len(thread.messages), 2)

        # Context retrieval
        llm_msgs = thread.get_messages_for_llm(max_recent=4)
        self.assertEqual(len(llm_msgs), 2)

    def test_conversation_manager_crud(self):
        mgr = ConversationManager()

        # Create thread
        t1 = mgr.create_thread("Thread 1: QoS RxO")
        self.assertEqual(mgr.active_thread_id, t1.id)

        # Create another thread
        t2 = mgr.create_thread("Thread 2: TF2 Extrapolation")
        self.assertEqual(mgr.active_thread_id, t2.id)

        # List threads
        threads = mgr.list_threads()
        self.assertTrue(len(threads) >= 2)

        # Switch back to t1
        switched = mgr.switch_thread(t1.id)
        self.assertEqual(mgr.active_thread_id, t1.id)
        self.assertEqual(switched.title, "Thread 1: QoS RxO")

        # Rename thread
        mgr.rename_thread(t1.id, "Renamed QoS Thread")
        self.assertEqual(mgr.threads[t1.id].title, "Renamed QoS Thread")

        # Add turn
        mgr.add_turn(t1.id, "My robot uses Ackermann Steering", "Ackermann kinematics noted.")
        self.assertEqual(mgr.memory_layer.robot_profile.platform_type, "Ackermann Steering")
        self.assertEqual(len(mgr.threads[t1.id].messages), 2)

        # Clear thread
        mgr.clear_thread(t1.id)
        self.assertEqual(len(mgr.threads[t1.id].messages), 0)

        # Delete thread
        mgr.delete_thread(t1.id)
        self.assertNotIn(t1.id, mgr.threads)

    def test_agent_session_multi_turn_continuation(self):
        provider = OfflineRoboticsProvider()
        session = AgentSession(provider=provider)

        # Turn 1
        rep1 = session.step("We are testing ROS 2 Humble robot with cyclone dds.")
        self.assertIn("Humble", session.conversation_manager.memory_layer.robot_profile.ros_distro)
        self.assertEqual(len(session.conversation_history), 2)

        # Turn 2 in same thread continues context
        rep2 = session.step("What QoS profile should we use?")
        self.assertEqual(len(session.conversation_history), 4)

        # Verify thread holds all 4 messages
        active_t = session.conversation_manager.threads[session.conversation_manager.active_thread_id]
        self.assertEqual(len(active_t.messages), 4)


if __name__ == "__main__":
    unittest.main()
