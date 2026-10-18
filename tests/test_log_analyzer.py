"""Tests for ROS 2 log analyzer & crash triage."""

import unittest
from robosage.diagnostics.log_analyzer import (
    LogSeverity,
    RoboticsErrorCategory,
    ROS2LogAnalyzer,
)


class TestLogAnalyzer(unittest.TestCase):

    def setUp(self):
        self.analyzer = ROS2LogAnalyzer()

    def test_parse_qos_incompatibility(self):
        log = "New publisher discovered on topic '/scan', offering incompatible QoS. Incompatible QoS settings on topic '/scan': Reliability requested: RELIABLE, offered: BEST_EFFORT"
        incidents = self.analyzer.analyze_text(log)
        self.assertEqual(len(incidents), 1)
        inc = incidents[0]
        self.assertEqual(inc.category, RoboticsErrorCategory.QOS_MISMATCH)
        self.assertEqual(inc.topic_or_frame, "/scan")
        self.assertIn("qos_profile_sensor_data", inc.code_fix)

    def test_parse_python_traceback(self):
        tb = """
Traceback (most recent call last):
  File "/workspace/src/my_robot/vision_node.py", line 42, in process_image
    depth_val = depth_image[center_y, center_x]
IndexError: index 480 is out of bounds for axis 0 with size 480
"""
        incidents = self.analyzer.analyze_text(tb)
        self.assertEqual(len(incidents), 1)
        inc = incidents[0]
        self.assertEqual(inc.category, RoboticsErrorCategory.UNHANDLED_EXCEPTION)
        self.assertEqual(inc.line_number, 42)
        self.assertIn("vision_node.py", inc.file_path)

    def test_parse_sigsegv(self):
        log = "[ERROR] [1729252800.123] [manipulator_ik]: Process finished with exit code -11 (SIGSEGV)"
        incidents = self.analyzer.analyze_text(log)
        self.assertTrue(any(i.category == RoboticsErrorCategory.SEGMENTATION_FAULT for i in incidents))


if __name__ == "__main__":
    unittest.main()
