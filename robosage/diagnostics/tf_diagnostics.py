"""
ROS 2 Transform (TF2) Tree Diagnostics & Anomaly Detector.
Detects common TF2 issues such as extrapolation errors, clock skew,
missing intermediate frames, and buffer timeouts.
"""

from dataclasses import dataclass, field
from enum import Enum
import re
from typing import List, Optional


class TFErrorType(str, Enum):
    EXTRAPOLATION_FUTURE = "EXTRAPOLATION_FUTURE"
    EXTRAPOLATION_PAST = "EXTRAPOLATION_PAST"
    FRAME_MISSING = "FRAME_MISSING"
    TF_OLD_DATA = "TF_OLD_DATA"
    CYCLE_DETECTED = "CYCLE_DETECTED"
    UNPROTECTED_LOOKUP = "UNPROTECTED_LOOKUP"
    CLOCK_SKEW = "CLOCK_SKEW"
    UNKNOWN = "UNKNOWN"


@dataclass
class TFDiagnosis:
    error_type: TFErrorType
    source_frame: Optional[str]
    target_frame: Optional[str]
    delta_seconds: Optional[float]
    summary: str
    root_cause: str
    remediation_steps: List[str]
    code_example: Optional[str] = None


class TFDiagnostics:
    """Parses TF2 error strings and logs to identify root causes and specific fixes."""

    # Patterns for ROS 2 tf2 errors
    # e.g.: Lookup would require extrapolation into the future. Requested time 1729252800.100000 but the latest data is at time 1729252800.050000, when looking up transform from frame [base_link] to frame [odom]
    FUTURE_PATTERN = re.compile(
        r"extrapolation into the future.*Requested time\s+([\d\.]+).*latest data is at time\s+([\d\.]+).*from frame\s+\[?([\w\-_]+)\]?\s+to frame\s+\[?([\w\-_]+)\]?",
        re.IGNORECASE,
    )

    # e.g.: Lookup would require extrapolation into the past. Requested time 1729252800.010000 but the earliest data is at time 1729252800.050000
    PAST_PATTERN = re.compile(
        r"extrapolation into the past.*Requested time\s+([\d\.]+).*earliest data is at time\s+([\d\.]+).*from frame\s+\[?([\w\-_]+)\]?\s+to frame\s+\[?([\w\-_]+)\]?",
        re.IGNORECASE,
    )

    # e.g.: "base_footprint" passed to lookupTransform argument target_frame does not exist
    # or Frame [base_footprint] does not exist
    MISSING_FRAME_PATTERN = re.compile(
        r"(?:Frame\s+\[?([\w\-_]+)\]?\s+does not exist|\"?([\w\-_]+)\"?\s+passed to lookupTransform.*does not exist)",
        re.IGNORECASE,
    )

    # e.g.: TF_OLD_DATA ignoring data from the past for frame base_link
    OLD_DATA_PATTERN = re.compile(
        r"TF_OLD_DATA.*frame\s+\[?([\w\-_]+)\]?",
        re.IGNORECASE,
    )

    @classmethod
    def diagnose_message(cls, message: str) -> Optional[TFDiagnosis]:
        # 1. Extrapolation into the future
        m = cls.FUTURE_PATTERN.search(message)
        if m:
            req_time, latest_time, src, tgt = float(m.group(1)), float(m.group(2)), m.group(3), m.group(4)
            delta = req_time - latest_time
            return TFDiagnosis(
                error_type=TFErrorType.EXTRAPOLATION_FUTURE,
                source_frame=src,
                target_frame=tgt,
                delta_seconds=delta,
                summary=f"TF extrapolation into future by {delta*1000:.1f}ms between '{src}' and '{tgt}'",
                root_cause=(
                    f"A transform lookup was requested at t={req_time:.4f}, but the broadcaster has only published "
                    f"transforms up to t={latest_time:.4f}. This frequently happens when: (1) sensor header stamp is ahead "
                    f"of odom/base_link TF broadcast, (2) lookup called with Time(0) vs specific timestamp, or (3) sim time (use_sim_time) skew."
                ),
                remediation_steps=[
                    "If using a specific timestamp, wrap lookup in `lookup_transform(..., timeout=rclpy.duration.Duration(seconds=0.05))` to allow buffer to populate.",
                    "If the latest available transform is sufficient, use `rclpy.time.Time()` (equivalent to Time(0)) to request the latest transform.",
                    "Verify both nodes have identical `use_sim_time` parameter values.",
                    "Check broadcaster publishing frequency; ensure it publishes at least 20-50 Hz.",
                ],
                code_example="""# Recommended TF lookup pattern:
from tf2_ros import TransformException
import rclpy.duration

try:
    transform = self.tf_buffer.lookup_transform(
        target_frame='odom',
        source_frame='base_link',
        time=rclpy.time.Time(), # or sensor_header.stamp
        timeout=rclpy.duration.Duration(seconds=0.05) # Wait up to 50ms for buffer
    )
except TransformException as ex:
    self.get_logger().warn(f'Could not transform: {ex}')
    return
""",
            )

        # 2. Extrapolation into past
        m = cls.PAST_PATTERN.search(message)
        if m:
            req_time, earliest_time, src, tgt = float(m.group(1)), float(m.group(2)), m.group(3), m.group(4)
            delta = earliest_time - req_time
            return TFDiagnosis(
                error_type=TFErrorType.EXTRAPOLATION_PAST,
                source_frame=src,
                target_frame=tgt,
                delta_seconds=delta,
                summary=f"TF buffer expired: requested time is {delta*1000:.1f}ms older than buffer history",
                root_cause=(
                    "The transform buffer cache duration (default 10.0 seconds) does not hold data that far back, "
                    "or sensor data processing is heavily delayed/backlogged."
                ),
                remediation_steps=[
                    "Increase TF Buffer cache duration: `Buffer(cache_time=Duration(seconds=30.0))`.",
                    "Profile node callback duration to see if high compute latency is delaying processing of older messages.",
                ],
            )

        # 3. Missing frame
        m = cls.MISSING_FRAME_PATTERN.search(message)
        if m:
            frame = m.group(1) or m.group(2)
            return TFDiagnosis(
                error_type=TFErrorType.FRAME_MISSING,
                source_frame=frame,
                target_frame=None,
                delta_seconds=None,
                summary=f"TF Frame '{frame}' does not exist in the transform tree",
                root_cause=(
                    f"No active broadcaster is publishing frame '{frame}', or `robot_state_publisher` has not loaded the URDF, "
                    f"or a prefix mismatch occurred (e.g., 'base_link' vs 'robot_1/base_link')."
                ),
                remediation_steps=[
                    f"Run `ros2 run tf2_tools view_frames` to generate and inspect frames.pdf.",
                    f"Check if the broadcaster node for '{frame}' (e.g. odometry, robot_state_publisher) is running without crashing.",
                    "Verify frame naming in parameters and launch files for leading slashes (e.g., use 'base_link', not '/base_link' in ROS 2).",
                ],
            )

        # 4. Old data warning
        m = cls.OLD_DATA_PATTERN.search(message)
        if m:
            frame = m.group(1)
            return TFDiagnosis(
                error_type=TFErrorType.TF_OLD_DATA,
                source_frame=frame,
                target_frame=None,
                delta_seconds=None,
                summary=f"TF_OLD_DATA warning for frame '{frame}'",
                root_cause=(
                    "Transforms are being published with timestamps that go backward or repeat, or simulation was reset "
                    "without resetting the ROS 2 node/tf_buffer."
                ),
                remediation_steps=[
                    "When restarting Gazebo/Isaac Sim, restart the ROS nodes or reset their TF buffers.",
                    "Ensure monotonic timestamping on published TransformStamped messages.",
                ],
            )

        return None
