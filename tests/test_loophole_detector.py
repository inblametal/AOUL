"""Tests for RoboAudit Loophole Detector."""

import os
import unittest
from robosage.diagnostics.loophole_detector import (
    LoopholeDetector,
    LoopholeSeverity,
    LoopholeType,
)


class TestLoopholeDetector(unittest.TestCase):

    def setUp(self):
        self.detector = LoopholeDetector()
        self.example_dir = os.path.abspath(
            os.path.join(os.path.dirname(__file__), "..", "examples")
        )

    def test_audit_buggy_node(self):
        buggy_file = os.path.join(self.example_dir, "buggy_node.py")
        findings = self.detector.audit_file(buggy_file)

        types_found = {f.loophole_type for f in findings}

        # Verify all key loopholes were successfully caught
        self.assertIn(LoopholeType.MISSING_ESTOP_ON_SHUTDOWN, types_found)
        self.assertIn(LoopholeType.SYNCHRONOUS_SERVICE_DEADLOCK, types_found)
        self.assertIn(LoopholeType.UNPROTECTED_TF_LOOKUP, types_found)
        self.assertIn(LoopholeType.BLOCKING_SLEEP_IN_CALLBACK, types_found)
        self.assertIn(LoopholeType.MISSING_SENSOR_WATCHDOG, types_found)
        self.assertIn(LoopholeType.UNCHECKED_NAN_INF, types_found)
        self.assertIn(LoopholeType.DEFAULT_QOS_ON_HIGH_RATE_SENSOR, types_found)

        # Check severity of critical hazards
        critical_findings = [f for f in findings if f.severity == LoopholeSeverity.CRITICAL]
        self.assertTrue(len(critical_findings) >= 2)  # E-stop and deadlock


if __name__ == "__main__":
    unittest.main()
