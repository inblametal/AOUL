"""Tests for TF2 diagnostics."""

import unittest
from robosage.diagnostics.tf_diagnostics import TFDiagnostics, TFErrorType


class TestTFDiagnostics(unittest.TestCase):

    def test_extrapolation_into_future(self):
        log_line = (
            "Lookup would require extrapolation into the future. Requested time 1729252800.100000 "
            "but the latest data is at time 1729252800.050000, when looking up transform from frame [base_link] to frame [odom]"
        )
        diag = TFDiagnostics.diagnose_message(log_line)
        self.assertIsNotNone(diag)
        self.assertEqual(diag.error_type, TFErrorType.EXTRAPOLATION_FUTURE)
        self.assertEqual(diag.source_frame, "base_link")
        self.assertEqual(diag.target_frame, "odom")
        self.assertAlmostEqual(diag.delta_seconds, 0.05)
        self.assertIn("timeout", diag.code_example)

    def test_missing_frame(self):
        log_line = 'Frame [camera_depth_optical_frame] does not exist'
        diag = TFDiagnostics.diagnose_message(log_line)
        self.assertIsNotNone(diag)
        self.assertEqual(diag.error_type, TFErrorType.FRAME_MISSING)
        self.assertEqual(diag.source_frame, "camera_depth_optical_frame")

    def test_old_data(self):
        log_line = "TF_OLD_DATA ignoring data from the past for frame base_link"
        diag = TFDiagnostics.diagnose_message(log_line)
        self.assertIsNotNone(diag)
        self.assertEqual(diag.error_type, TFErrorType.TF_OLD_DATA)


if __name__ == "__main__":
    unittest.main()
