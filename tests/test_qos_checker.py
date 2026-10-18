"""Tests for QoS compatibility validator."""

import unittest
from robosage.diagnostics.qos_checker import (
    DurabilityPolicy,
    QoSProfile,
    ReliabilityPolicy,
    check_qos_compatibility,
)


class TestQoSChecker(unittest.TestCase):

    def test_compatible_default_profiles(self):
        pub = QoSProfile.default_preset()
        sub = QoSProfile.default_preset()
        res = check_qos_compatibility(pub, sub)
        self.assertTrue(res.is_compatible)
        self.assertEqual(len(res.issues), 0)

    def test_incompatible_reliability_mismatch(self):
        # Pub offers Best Effort, Sub requests Reliable
        pub = QoSProfile(reliability=ReliabilityPolicy.BEST_EFFORT)
        sub = QoSProfile(reliability=ReliabilityPolicy.RELIABLE)
        res = check_qos_compatibility(pub, sub)
        self.assertFalse(res.is_compatible)
        self.assertTrue(any("Reliability Mismatch" in issue for issue in res.issues))

    def test_compatible_sensor_profile(self):
        # Pub offers Best Effort, Sub requests Best Effort
        pub = QoSProfile.sensor_data_preset()
        sub = QoSProfile.sensor_data_preset()
        res = check_qos_compatibility(pub, sub)
        self.assertTrue(res.is_compatible)

    def test_incompatible_durability_mismatch(self):
        # Pub offers Volatile, Sub requests Transient Local
        pub = QoSProfile(durability=DurabilityPolicy.VOLATILE)
        sub = QoSProfile(durability=DurabilityPolicy.TRANSIENT_LOCAL)
        res = check_qos_compatibility(pub, sub)
        self.assertFalse(res.is_compatible)
        self.assertTrue(any("Durability Mismatch" in issue for issue in res.issues))


if __name__ == "__main__":
    unittest.main()
