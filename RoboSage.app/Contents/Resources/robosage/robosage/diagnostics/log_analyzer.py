"""
ROS 2 Log Analyzer & Crash Triage Engine.
Parses ROS 2 console logs, rosout streams, RMW DDS warnings, and C++ backtraces.
Classifies error categories, extracts context, and provides automated remedies.
"""

from dataclasses import dataclass, field
from enum import Enum
import re
from typing import Dict, List, Optional

from robosage.diagnostics.qos_checker import (
    DurabilityPolicy,
    QoSCheckResult,
    QoSProfile,
    ReliabilityPolicy,
    check_qos_compatibility,
)
from robosage.diagnostics.tf_diagnostics import TFDiagnosis, TFDiagnostics


class LogSeverity(str, Enum):
    FATAL = "FATAL"
    ERROR = "ERROR"
    WARN = "WARN"
    INFO = "INFO"
    DEBUG = "DEBUG"
    UNKNOWN = "UNKNOWN"


class RoboticsErrorCategory(str, Enum):
    QOS_MISMATCH = "QOS_MISMATCH"
    TF_ERROR = "TF_ERROR"
    EXECUTOR_DEADLOCK = "EXECUTOR_DEADLOCK"
    RATE_STARVATION = "RATE_STARVATION"
    SEGMENTATION_FAULT = "SEGMENTATION_FAULT"
    UNHANDLED_EXCEPTION = "UNHANDLED_EXCEPTION"
    NAV2_NAVIGATION_FAILURE = "NAV2_NAVIGATION_FAILURE"
    MISSING_NODE_OR_TOPIC = "MISSING_NODE_OR_TOPIC"
    PARAMETER_ERROR = "PARAMETER_ERROR"
    DDS_MIDDLEWARE = "DDS_MIDDLEWARE"
    LIFECYCLE_FAILURE = "LIFECYCLE_FAILURE"
    GENERAL = "GENERAL"


@dataclass
class LogIncident:
    severity: LogSeverity
    category: RoboticsErrorCategory
    raw_message: str
    node_name: Optional[str] = None
    topic_or_frame: Optional[str] = None
    file_path: Optional[str] = None
    line_number: Optional[int] = None
    summary: str = ""
    root_cause: str = ""
    remediation_steps: List[str] = field(default_factory=list)
    code_fix: Optional[str] = None


class ROS2LogAnalyzer:
    """Parses and triages ROS 2 log messages, crashes, and runtime errors."""

    # Matches standard ROS 2 console log pattern:
    # [SEVERITY] [timestamp] [node_name]: message
    # e.g.: [ERROR] [1729252800.123456789] [nav2_controller]: Failed to make progress
    LOG_LINE_PATTERN = re.compile(
        r"\[(FATAL|ERROR|WARN|INFO|DEBUG)\]\s+\[([\d\.]+)\]\s+\[([\w\-_/\.]+)?\]:\s*(.*)",
        re.IGNORECASE,
    )

    # QoS Incompatibility pattern:
    # Incompatible QoS settings on topic '/cmd_vel'
    # or New publisher discovered on topic '/cmd_vel', offering incompatible QoS
    QOS_MISMATCH_PATTERN = re.compile(
        r"(?:Incompatible QoS|incompatible QoS|offering incompatible QoS).*topic\s+'?([/\w\-_]+)'?",
        re.IGNORECASE,
    )

    # Deadlock / SingleThreadedExecutor lockup
    DEADLOCK_PATTERN = re.compile(
        r"(?:deadlock|Waiting for service.*never returned|call_async.*never completed|Executor blocking)",
        re.IGNORECASE,
    )

    # Missed deadline or rate starvation
    STARVATION_PATTERN = re.compile(
        r"(?:missed deadline|callback took longer than period|Rate starvation|scheduling delay high)",
        re.IGNORECASE,
    )

    # Segmentation fault / C++ crash
    SIGSEGV_PATTERN = re.compile(
        r"(?:Segmentation fault|SIGSEGV|signal 11|Process finished with exit code -11|core dumped)",
        re.IGNORECASE,
    )

    # Python Traceback
    PYTHON_TRACEBACK_PATTERN = re.compile(
        r'File "([^"]+)", line (\d+), in (\w+)\n\s*(.*)\n(?:.*Error|Exception):\s*(.*)',
        re.DOTALL,
    )

    # Nav2 Costmap / planner failures
    NAV2_PATTERN = re.compile(
        r"(?:Nav2|Costmap2D|planner_server|controller_server|Failed to make progress|Cannot clear costmap|No valid trajectory)",
        re.IGNORECASE,
    )

    # Lifecycle transitions
    LIFECYCLE_PATTERN = re.compile(
        r"(?:Failed to change state for node|Transition.*failed|on_configure.*failed)",
        re.IGNORECASE,
    )

    def analyze_text(self, text: str) -> List[LogIncident]:
        """Analyzes a multi-line log string or error output."""
        incidents: List[LogIncident] = []
        lines = text.strip().split("\n")

        # 1. First check if there is an overarching Python Traceback
        if "Traceback (most recent call last):" in text:
            tb_incident = self._parse_python_traceback(text)
            if tb_incident:
                incidents.append(tb_incident)

        # 2. Check for Segmentation fault
        if self.SIGSEGV_PATTERN.search(text):
            incidents.append(self._parse_sigsegv(text))

        # 3. Line-by-line inspection
        for line in lines:
            line_str = line.strip()
            if not line_str:
                continue

            # Check if this line is a TF diagnostic
            tf_diag = TFDiagnostics.diagnose_message(line_str)
            if tf_diag:
                incidents.append(
                    LogIncident(
                        severity=LogSeverity.WARN if tf_diag.error_type == tf_diag.error_type.TF_OLD_DATA else LogSeverity.ERROR,
                        category=RoboticsErrorCategory.TF_ERROR,
                        raw_message=line_str,
                        topic_or_frame=tf_diag.source_frame or tf_diag.target_frame,
                        summary=tf_diag.summary,
                        root_cause=tf_diag.root_cause,
                        remediation_steps=tf_diag.remediation_steps,
                        code_fix=tf_diag.code_example,
                    )
                )
                continue

            # Check QoS mismatch
            qos_match = self.QOS_MISMATCH_PATTERN.search(line_str)
            if qos_match:
                topic = qos_match.group(1)
                incidents.append(self._parse_qos_incident(line_str, topic))
                continue

            # Check for Rate / Executor Starvation
            if self.STARVATION_PATTERN.search(line_str):
                incidents.append(
                    LogIncident(
                        severity=LogSeverity.WARN,
                        category=RoboticsErrorCategory.RATE_STARVATION,
                        raw_message=line_str,
                        summary="Real-time control rate starvation or callback overrun detected",
                        root_cause=(
                            "A timer callback or subscription handler is doing heavy computation (e.g. image processing, "
                            "synchronous I/O, or sleeping) inside the main executor thread, missing its cycle deadline."
                        ),
                        remediation_steps=[
                            "Offload heavy compute to a background worker thread or custom callback group.",
                            "Use MultiThreadedExecutor with ReentrantCallbackGroup for concurrent callbacks.",
                            "Avoid time.sleep() or blocking calls inside ROS 2 callbacks.",
                        ],
                    )
                )
                continue

            # Check for Nav2 failures
            if self.NAV2_PATTERN.search(line_str) and ("error" in line_str.lower() or "fail" in line_str.lower()):
                incidents.append(
                    LogIncident(
                        severity=LogSeverity.ERROR,
                        category=RoboticsErrorCategory.NAV2_NAVIGATION_FAILURE,
                        raw_message=line_str,
                        summary=f"Nav2 navigation/controller error: {line_str[:80]}...",
                        root_cause=(
                            "The robot failed to generate or track a valid trajectory. Typical causes: "
                            "obstacle inflation zone trapping robot, odom drift causing localization jump, "
                            "or controller goal tolerance unreachable."
                        ),
                        remediation_steps=[
                            "Check costmap inflation radius (`inflation_radius` vs `robot_radius`).",
                            "Verify TF frame `map` -> `odom` is steady and not jumping.",
                            "Ensure `xy_goal_tolerance` and `yaw_goal_tolerance` are appropriate for the drive base.",
                        ],
                    )
                )
                continue

        # If no incidents were categorized but text contains ERROR / FATAL lines, create general incident
        if not incidents:
            for line in lines:
                m = self.LOG_LINE_PATTERN.search(line)
                if m:
                    sev, ts, node, msg = m.groups()
                    if sev.upper() in ("ERROR", "FATAL"):
                        incidents.append(
                            LogIncident(
                                severity=LogSeverity(sev.upper()),
                                category=RoboticsErrorCategory.GENERAL,
                                raw_message=line,
                                node_name=node,
                                summary=f"Error in node [{node}]: {msg}",
                                root_cause="Generic ROS 2 node error or unhandled condition.",
                                remediation_steps=["Inspect node source code around failure point", "Check topic connections using `ros2 node info`"],
                            )
                        )

        return incidents

    def _parse_python_traceback(self, text: str) -> Optional[LogIncident]:
        matches = list(re.finditer(r'File "([^"]+)", line (\d+), in (\w+)\n\s*(.*?)\n([A-Za-z_][A-Za-z0-9_]*Error|Exception):\s*(.*)', text))
        if matches:
            last = matches[-1]
            file_path, line_no, func, code_line, err_type, err_msg = (
                last.group(1),
                int(last.group(2)),
                last.group(3),
                last.group(4),
                last.group(5),
                last.group(6),
            )
            return LogIncident(
                severity=LogSeverity.FATAL,
                category=RoboticsErrorCategory.UNHANDLED_EXCEPTION,
                raw_message=f"{err_type}: {err_msg}",
                file_path=file_path,
                line_number=line_no,
                summary=f"Python unhandled {err_type} at {file_path}:{line_no} in `{func}`",
                root_cause=f"{err_type}: {err_msg} in line: `{code_line.strip()}`",
                remediation_steps=[
                    f"Check value assignments and null/None guards at line {line_no}.",
                    f"Wrap code block in appropriate try...except clause with fallback defaults.",
                ],
            )
        return None

    def _parse_sigsegv(self, text: str) -> LogIncident:
        return LogIncident(
            severity=LogSeverity.FATAL,
            category=RoboticsErrorCategory.SEGMENTATION_FAULT,
            raw_message="Process terminated with Segmentation Fault (SIGSEGV)",
            summary="C++ ROS 2 Node crashed due to illegal memory access (SIGSEGV)",
            root_cause=(
                "Common causes in ROS 2 C++ nodes:\n"
                "1. Dereferencing a nullptr message shared_ptr (e.g. `msg->header` when msg is null).\n"
                "2. Race condition on shared pointer or buffer across multi-threaded callbacks.\n"
                "3. Use-after-free or double free in custom hardware interfaces or OpenCV image pointers.\n"
                "4. Uninitialized publisher, subscriber, or TF buffer pointer."
            ),
            remediation_steps=[
                "Run node with gdb: `ros2 run --prefix 'gdb -ex run --args' <package> <node>` to get exact backtrace.",
                "Check all shared pointer usages for `if (ptr != nullptr)` before accessing.",
                "Ensure publishers and subscribers are initialized in the constructor before timers fire.",
                "Compile with AddressSanitizer: `-DCMAKE_CXX_FLAGS='-fsanitize=address'` in colcon build.",
            ],
            code_fix="""// Safe pointer pattern in rclcpp:
void topic_callback(const sensor_msgs::msg::LaserScan::SharedPtr msg) {
  if (!msg) {
    RCLCPP_WARN(this->get_logger(), "Received null message pointer, dropping.");
    return;
  }
  // Process msg safely...
}""",
        )

    def _parse_qos_incident(self, line: str, topic: Optional[str]) -> LogIncident:
        # Determine if reliability or durability is mentioned
        is_reliability = "reliability" in line.lower()
        is_durability = "durability" in line.lower()

        if is_reliability:
            summary = f"QoS Incompatibility on topic '{topic}': Reliability Mismatch"
            cause = "The subscriber expects RELIABLE delivery, but the publisher is publishing with BEST_EFFORT (common with sensors like LiDAR/Camera)."
            fix = f"""# For Python (rclpy):
from rclpy.qos import qos_profile_sensor_data

self.subscription = self.create_subscription(
    TopicType,
    '{topic or "/topic"}',
    self.callback,
    qos_profile_sensor_data  # Uses Best Effort + Small History
)

// For C++ (rclcpp):
auto sub = this->create_subscription<TopicType>(
    "{topic or "/topic"}",
    rclcpp::SensorDataQoS(),
    std::bind(&Node::callback, this, std::placeholders::_1)
);"""
        elif is_durability:
            summary = f"QoS Incompatibility on topic '{topic}': Durability Mismatch"
            cause = "The subscriber requested TRANSIENT_LOCAL (latched), but the publisher is VOLATILE, or vice versa."
            fix = f"""# Latched / Transient Local configuration:
from rclpy.qos import QoSProfile, DurabilityPolicy, ReliabilityPolicy

custom_qos = QoSProfile(
    reliability=ReliabilityPolicy.RELIABLE,
    durability=DurabilityPolicy.TRANSIENT_LOCAL,
    depth=1
)
self.create_subscription(TopicType, '{topic or "/topic"}', self.callback, custom_qos)"""
        else:
            summary = f"QoS Incompatibility on topic '{topic}'"
            cause = "DDS Publisher and Subscriber Quality of Service settings do not match RxO requirements."
            fix = "Match the QoS profiles on both nodes using standard presets (`rclcpp::SensorDataQoS()` or `rclcpp::SystemDefaultsQoS()`)."

        return LogIncident(
            severity=LogSeverity.ERROR,
            category=RoboticsErrorCategory.QOS_MISMATCH,
            raw_message=line,
            topic_or_frame=topic,
            summary=summary,
            root_cause=cause,
            remediation_steps=[
                "Check publisher and subscriber QoS settings with: `ros2 topic info -v " + (topic or "<topic>") + "`",
                "Ensure subscriber reliability does not exceed publisher reliability.",
                "Ensure subscriber durability does not exceed publisher durability.",
            ],
            code_fix=fix,
        )
