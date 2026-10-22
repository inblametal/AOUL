"""
Unit tests for URDF Physics Auditor and Motor Thermal & Battery Simulator.
"""

import unittest
from robosage.diagnostics.urdf_auditor import UrdfAuditor
from robosage.diagnostics.power_thermal import PowerThermalEngine


class TestUrdfAndPower(unittest.TestCase):

    def test_urdf_auditor_nominal(self):
        samples = UrdfAuditor.get_sample_urdfs()
        nom = samples["nominal_arm"]["urdf"]
        res = UrdfAuditor.audit_urdf_text(nom)
        self.assertTrue(res["valid"])
        self.assertEqual(res["robot_name"], "nominal_arm")
        self.assertEqual(res["stats"]["links"], 2)
        self.assertEqual(res["stats"]["joints"], 1)
        self.assertAlmostEqual(res["stats"]["total_mass_kg"], 7.5, places=2)
        # Should have 0 critical findings
        criticals = [f for f in res["findings"] if f["severity"] == "CRITICAL"]
        self.assertEqual(len(criticals), 0)

    def test_urdf_auditor_faulty_inertias_and_limits(self):
        samples = UrdfAuditor.get_sample_urdfs()
        faulty = samples["faulty_inertias_amr"]["urdf"]
        res = UrdfAuditor.audit_urdf_text(faulty)
        self.assertTrue(res["valid"])
        titles = [f["title"] for f in res["findings"]]
        # Detects negative/zero inertia
        self.assertTrue(any("Non-Positive Diagonal Moment" in t for t in titles))
        # Detects triangle inequality violation
        self.assertTrue(any("Triangle Inequality Violation" in t for t in titles))
        # Detects missing collision geometry
        self.assertTrue(any("Missing Collision Geometry" in t for t in titles))
        # Detects inverted limits
        self.assertTrue(any("Inverted Joint Limits" in t for t in titles))

    def test_power_thermal_nominal(self):
        res = PowerThermalEngine.calculate_motor_and_power(
            torque_nm=0.4,
            speed_rad_s=10.0,
            run_duration_min=10.0,
            motor_resistance_ohms=0.85,
            torque_constant_kt=0.12,
            battery_voltage=24.0,
            battery_capacity_ah=15.0,
        )
        self.assertEqual(res["thermal_status"], "NOMINAL")
        self.assertGreater(res["battery_runtime_hours"], 1.0)
        self.assertEqual(res["safe_duty_cycle_pct"], 100.0)

    def test_power_thermal_overheat(self):
        # High torque causing massive copper heating
        res = PowerThermalEngine.calculate_motor_and_power(
            torque_nm=8.0,
            speed_rad_s=15.0,
            run_duration_min=30.0,
            motor_resistance_ohms=1.2,
            torque_constant_kt=0.12,
            max_winding_temp_c=90.0,
        )
        self.assertIn(res["thermal_status"], ("WARNING_OVERHEAT", "CRITICAL_BURN"))
        self.assertLess(res["safe_duty_cycle_pct"], 50.0)


if __name__ == "__main__":
    unittest.main()
