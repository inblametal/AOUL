"""
Unit tests for AOUL Advanced Research Capabilities:
1. OASIS SARIF v2.1.0 Exporter
2. Rosbag2 & Flight Telemetry Inspector
3. Nav2 & BehaviorTree.CPP Safety Auditor
4. Safety Shield Deterministic Runtime Middleware
"""

import unittest
from aoul.diagnostics.sarif_exporter import SarifExporter
from aoul.diagnostics.bag_inspector import RosbagInspector
from aoul.diagnostics.behavior_tree_analyzer import BehaviorTreeAnalyzer
from aoul.diagnostics.safety_shield import SafetyShieldEngine


class TestAdvancedFeatures(unittest.TestCase):

    def test_sarif_export(self):
        sample_findings = [
            {
                "loophole_type": "MISSING_ESTOP_ON_SHUTDOWN",
                "severity": "CRITICAL",
                "title": "Missing E-Stop on Shutdown",
                "description": "Node does not publish zero velocity on shutdown.",
                "impact": "Runaway robot hazard.",
                "recommended_fix": "Add try...finally block in main()",
                "line_number": 42,
            }
        ]
        doc = SarifExporter.convert_findings_to_sarif(sample_findings, "src/safe_node.py")
        self.assertEqual(doc["version"], "2.1.0")
        self.assertEqual(len(doc["runs"]), 1)
        self.assertEqual(len(doc["runs"][0]["results"]), 1)
        res = doc["runs"][0]["results"][0]
        self.assertEqual(res["ruleId"], "MISSING_ESTOP_ON_SHUTDOWN")
        self.assertEqual(res["level"], "error")
        self.assertEqual(res["locations"][0]["physicalLocation"]["region"]["startLine"], 42)

    def test_rosbag_inspector_nominal(self):
        # 20 Hz nominal timestamps (50ms interval)
        ts = [i * 0.05 for i in range(100)]
        stats = RosbagInspector.analyze_topic_timestamps("/scan", "sensor_msgs/msg/LaserScan", ts, expected_hz=20.0)
        self.assertEqual(stats.health_status, "HEALTHY")
        self.assertEqual(stats.dropped_frames_estimate, 0)
        self.assertAlmostEqual(stats.observed_hz, 20.0, places=1)

    def test_rosbag_inspector_dropout_and_jitter(self):
        # Timestamps with simulated 400ms sensor dropout
        ts = [0.0, 0.05, 0.10, 0.50, 0.55, 0.60]
        stats = RosbagInspector.analyze_topic_timestamps("/scan", "sensor_msgs/msg/LaserScan", ts, expected_hz=20.0)
        self.assertIn(stats.health_status, ("WARNING", "CRITICAL"))
        self.assertGreater(stats.dropped_frames_estimate, 0)

    def test_behavior_tree_analyzer_nominal(self):
        trees = BehaviorTreeAnalyzer.get_sample_trees()
        nom = trees["nav2_nominal"]["xml"]
        res = BehaviorTreeAnalyzer.parse_and_audit_xml(nom)
        self.assertTrue(res["valid"])
        self.assertGreater(res["stats"]["nodes"], 5)
        self.assertIsNotNone(res["tree_json"])

    def test_behavior_tree_analyzer_faults(self):
        trees = BehaviorTreeAnalyzer.get_sample_trees()
        faulty = trees["faulty_tree"]["xml"]
        res = BehaviorTreeAnalyzer.parse_and_audit_xml(faulty)
        self.assertTrue(res["valid"])
        finding_titles = [f["title"] for f in res["findings"]]
        # Should detect infinite retry trap
        self.assertTrue(any("Infinite Retry" in t for t in finding_titles))

    def test_safety_shield_envelope_safe(self):
        # Obstacle far away (2.5m), commanded velocity 1.0 m/s
        env = SafetyShieldEngine.calculate_envelope(
            commanded_linear_vel=1.0,
            commanded_angular_vel=0.0,
            current_distance_to_obstacle=2.5,
            max_linear_vel=1.0,
            max_linear_accel=0.8,
            min_safe_distance=0.35,
        )
        self.assertFalse(env["is_clamped"])
        self.assertEqual(env["safe_linear_vel"], 1.0)

    def test_safety_shield_envelope_clamped(self):
        # Obstacle close (0.5m), commanded velocity 1.5 m/s
        env = SafetyShieldEngine.calculate_envelope(
            commanded_linear_vel=1.5,
            commanded_angular_vel=0.0,
            current_distance_to_obstacle=0.5,
            max_linear_vel=1.5,
            max_linear_accel=0.8,
            min_safe_distance=0.35,
        )
        self.assertTrue(env["is_clamped"])
        self.assertLess(env["safe_linear_vel"], 1.5)

    def test_safety_shield_emergency_stop(self):
        # Obstacle inside buffer (0.2m < 0.35m safe distance)
        env = SafetyShieldEngine.calculate_envelope(
            commanded_linear_vel=1.0,
            commanded_angular_vel=0.0,
            current_distance_to_obstacle=0.2,
            max_linear_vel=1.0,
            max_linear_accel=0.8,
            min_safe_distance=0.35,
        )
        self.assertTrue(env["is_clamped"])
        self.assertEqual(env["safe_linear_vel"], 0.0)

    def test_safety_shield_code_generation(self):
        cpp_code = SafetyShieldEngine.generate_cpp_shield_node("custom_shield_node")
        self.assertIn("custom_shield_node", cpp_code)
        self.assertIn("rclcpp::Node", cpp_code)

        py_code = SafetyShieldEngine.generate_python_shield_node("custom_shield_node")
        self.assertIn("custom_shield_node", py_code)
        self.assertIn("rclpy.node", py_code)


if __name__ == "__main__":
    unittest.main()
