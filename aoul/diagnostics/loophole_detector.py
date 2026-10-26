"""
Robotics Loophole & Safety Vulnerability Detector ("RoboAudit").
Performs static AST analysis (for Python/rclpy) and structural regex analysis (for C++/rclcpp)
to catch hidden deadlocks, missing E-Stops, sensor dropouts, unhandled NaNs, and race conditions.
"""

import ast
from dataclasses import dataclass, field
from enum import Enum
import os
from pathlib import Path
import re
from typing import Any, Dict, List, Optional


class LoopholeSeverity(str, Enum):
    CRITICAL = "CRITICAL"   # Can cause physical robot crash or hardware damage (e.g. Runaway robot, deadlock)
    HIGH = "HIGH"           # Can crash the node during runtime (e.g. Unprotected TF exception)
    MEDIUM = "MEDIUM"       # Behavioral glitch, stale sensor data, rate overrun
    LOW = "LOW"             # Anti-pattern or sub-optimal performance


class LoopholeType(str, Enum):
    MISSING_ESTOP_ON_SHUTDOWN = "MISSING_ESTOP_ON_SHUTDOWN"
    SYNCHRONOUS_SERVICE_DEADLOCK = "SYNCHRONOUS_SERVICE_DEADLOCK"
    MISSING_SENSOR_WATCHDOG = "MISSING_SENSOR_WATCHDOG"
    UNPROTECTED_TF_LOOKUP = "UNPROTECTED_TF_LOOKUP"
    UNCHECKED_NAN_INF = "UNCHECKED_NAN_INF"
    RACE_CONDITION_UNPROTECTED_STATE = "RACE_CONDITION_UNPROTECTED_STATE"
    BLOCKING_SLEEP_IN_CALLBACK = "BLOCKING_SLEEP_IN_CALLBACK"
    DEFAULT_QOS_ON_HIGH_RATE_SENSOR = "DEFAULT_QOS_ON_HIGH_RATE_SENSOR"
    HARDCODED_TOPIC_OR_FRAME = "HARDCODED_TOPIC_OR_FRAME"


@dataclass
class LoopholeFinding:
    severity: LoopholeSeverity
    loophole_type: LoopholeType
    file_path: str
    line_number: Optional[int]
    title: str
    description: str
    impact: str
    recommended_fix: str
    sample_patch: Optional[str] = None


class LoopholeDetector:
    """Audits robotics source files for safety, reliability, and concurrency pitfalls."""

    def audit_file(self, file_path: str) -> List[LoopholeFinding]:
        path = Path(file_path)
        if not path.is_file():
            return []

        ext = path.suffix.lower()
        if ext == ".py":
            return self._audit_python_file(file_path)
        elif ext in (".cpp", ".hpp", ".cc", ".h"):
            return self._audit_cpp_file(file_path)
        return []

    def audit_directory(self, dir_path: str) -> List[LoopholeFinding]:
        results: List[LoopholeFinding] = []
        path = Path(dir_path)
        for root, _, files in os.walk(path):
            # Skip build and install directories
            if any(part in ("build", "install", "log", ".git", "__pycache__", ".venv") for part in Path(root).parts):
                continue
            for file in files:
                ext = Path(file).suffix.lower()
                if ext in (".py", ".cpp", ".hpp", ".cc", ".h"):
                    full_path = os.path.join(root, file)
                    results.extend(self.audit_file(full_path))
        return results

    # ==========================================
    # Python AST Analysis
    # ==========================================
    def _audit_python_file(self, file_path: str) -> List[LoopholeFinding]:
        findings: List[LoopholeFinding] = []
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                content = f.read()
        except Exception:
            return findings

        try:
            tree = ast.parse(content, filename=file_path)
        except SyntaxError as e:
            findings.append(
                LoopholeFinding(
                    severity=LoopholeSeverity.HIGH,
                    loophole_type=LoopholeType.SYNCHRONOUS_SERVICE_DEADLOCK,
                    file_path=file_path,
                    line_number=e.lineno,
                    title="Syntax Error in Python Node",
                    description=f"File contains a syntax error: {e.msg}",
                    impact="Node will fail to launch.",
                    recommended_fix="Fix the syntax error at indicated line.",
                )
            )
            return findings

        # Run individual AST visitors & inspectors
        findings.extend(self._check_estop_on_shutdown(tree, content, file_path))
        findings.extend(self._check_service_call_deadlock(tree, content, file_path))
        findings.extend(self._check_unprotected_tf_lookup(tree, content, file_path))
        findings.extend(self._check_blocking_sleep(tree, content, file_path))
        findings.extend(self._check_sensor_watchdog(tree, content, file_path))
        findings.extend(self._check_nan_inf_handling(tree, content, file_path))
        findings.extend(self._check_multithread_state_mutation(tree, content, file_path))
        findings.extend(self._check_qos_antipattern(tree, content, file_path))

        return findings

    def _check_estop_on_shutdown(self, tree: ast.AST, content: str, file_path: str) -> List[LoopholeFinding]:
        """Detects if a node publishes Twist/cmd_vel but lacks a shutdown/cleanup hook sending zero velocity."""
        publishes_cmd_vel = False

        # Look for Twist publisher or topic named 'cmd_vel'
        if "cmd_vel" in content or "Twist" in content:
            publishes_cmd_vel = True

        if not publishes_cmd_vel:
            return []

        code_only = "\n".join(line.split("#")[0] for line in content.splitlines())

        # Check for actual zero velocity stopping indicators
        # Note: avoid matching numbers like 0.5 or 0.8
        zero_vel_pattern = re.compile(r"linear\.x\s*=\s*0(?:\.0*)?(?!\d|\.)")
        has_zero_vel_assign = bool(zero_vel_pattern.search(code_only))

        shutdown_indicators = [
            "on_shutdown",
            "stop_robot",
            "emergency_stop",
            "stop_motors",
            "publish_zero",
        ]
        has_shutdown_stop = has_zero_vel_assign or any(ind in code_only for ind in shutdown_indicators)

        if not has_shutdown_stop:
            return [
                LoopholeFinding(
                    severity=LoopholeSeverity.CRITICAL,
                    loophole_type=LoopholeType.MISSING_ESTOP_ON_SHUTDOWN,
                    file_path=file_path,
                    line_number=1,
                    title="Missing E-Stop / Zero-Velocity on Shutdown",
                    description="Node publishes velocity commands (Twist/cmd_vel) but lacks a shutdown callback or cleanup block to publish zero velocity.",
                    impact="If the node is terminated, killed, or crashes, the robot may keep moving at the last commanded velocity (Runaway Robot hazard!).",
                    recommended_fix="Register an `on_shutdown` hook or use a try...finally block in main() to publish a zero Twist message when exiting.",
                    sample_patch="""# In your Node class:
def stop_robot(self):
    stop_msg = Twist()
    self.cmd_vel_pub.publish(stop_msg)
    self.get_logger().info('Emergency stop zero-velocity sent.')

# In your node initialization or main():
rclpy.get_default_context().on_shutdown(node.stop_robot)
# Or in main():
try:
    rclpy.spin(node)
finally:
    node.stop_robot()
    node.destroy_node()
    rclpy.shutdown()""",
                )
            ]
        return []

    def _check_service_call_deadlock(self, tree: ast.AST, content: str, file_path: str) -> List[LoopholeFinding]:
        """Detects synchronous call() or future.result() inside callback methods."""
        findings = []

        class SynchronousCallVisitor(ast.NodeVisitor):
            def __init__(self):
                self.in_node_method = False
                self.deadlocks = []

            def visit_ClassDef(self, node: ast.ClassDef):
                # Check methods inside Node classes
                self.generic_visit(node)

            def visit_FunctionDef(self, node: ast.FunctionDef):
                prev = self.in_node_method
                self.in_node_method = True
                self.generic_visit(node)
                self.in_node_method = prev

            def visit_Call(self, node: ast.Call):
                if self.in_node_method:
                    func_str = ast.unparse(node.func) if hasattr(ast, "unparse") else ""
                    # Check for synchronous .call() or spin_until_future_complete
                    if func_str.endswith(".call") or "spin_until_future_complete" in func_str:
                        self.deadlocks.append((node.lineno, func_str))
                    # Check for future.result() without async await
                    elif func_str.endswith(".result"):
                        self.deadlocks.append((node.lineno, func_str))
                self.generic_visit(node)

        visitor = SynchronousCallVisitor()
        visitor.visit(tree)

        for lineno, call_name in visitor.deadlocks:
            findings.append(
                LoopholeFinding(
                    severity=LoopholeSeverity.CRITICAL,
                    loophole_type=LoopholeType.SYNCHRONOUS_SERVICE_DEADLOCK,
                    file_path=file_path,
                    line_number=lineno,
                    title="Synchronous Service Call in Callback (Deadlock Hazard)",
                    description=f"Calling synchronous `{call_name}()` inside a ROS 2 callback blocks the single-threaded executor, preventing the response from ever being processed.",
                    impact="Node will freeze indefinitely (100% CPU deadlock or hanging process).",
                    recommended_fix="Use `client.call_async(request)` with `future.add_done_callback(...)`, or use a MultiThreadedExecutor with ReentrantCallbackGroup.",
                    sample_patch="""# Non-blocking async service call:
future = self.client.call_async(request)
future.add_done_callback(self._service_response_callback)

def _service_response_callback(self, future):
    try:
        response = future.result()
        self.get_logger().info(f'Result: {response}')
    except Exception as e:
        self.get_logger().error(f'Service call failed: {e}')""",
                )
            )
        return findings

    def _check_unprotected_tf_lookup(self, tree: ast.AST, content: str, file_path: str) -> List[LoopholeFinding]:
        """Detects lookup_transform without try-except handling."""
        findings = []

        class TFVisitor(ast.NodeVisitor):
            def __init__(self):
                self.in_try = False
                self.unprotected_lookups = []

            def visit_Try(self, node: ast.Try):
                prev = self.in_try
                self.in_try = True
                self.generic_visit(node)
                self.in_try = prev

            def visit_Call(self, node: ast.Call):
                func_str = ast.unparse(node.func) if hasattr(ast, "unparse") else ""
                if "lookup_transform" in func_str:
                    if not self.in_try:
                        self.unprotected_lookups.append(node.lineno)
                self.generic_visit(node)

        visitor = TFVisitor()
        visitor.visit(tree)

        for lineno in visitor.unprotected_lookups:
            findings.append(
                LoopholeFinding(
                    severity=LoopholeSeverity.HIGH,
                    loophole_type=LoopholeType.UNPROTECTED_TF_LOOKUP,
                    file_path=file_path,
                    line_number=lineno,
                    title="Unprotected TF2 lookup_transform Call",
                    description="`lookup_transform` is called without a surrounding try...except block.",
                    impact="When transforms are briefly delayed, missing, or extrapolating, tf2 raises TransformException, crashing your node instantly.",
                    recommended_fix="Wrap `lookup_transform` in a `try...except (TransformException, ConnectivityException, ExtrapolationException)` block.",
                    sample_patch="""from tf2_ros import TransformException

try:
    t = self.tf_buffer.lookup_transform(
        target_frame,
        source_frame,
        rclpy.time.Time(),
        timeout=rclpy.duration.Duration(seconds=0.05)
    )
except TransformException as ex:
    self.get_logger().warn(f'Could not transform {source_frame} to {target_frame}: {ex}')
    return""",
                )
            )
        return findings

    def _check_blocking_sleep(self, tree: ast.AST, content: str, file_path: str) -> List[LoopholeFinding]:
        """Flags time.sleep() inside ROS nodes."""
        findings = []

        class SleepVisitor(ast.NodeVisitor):
            def __init__(self):
                self.sleep_calls = []

            def visit_Call(self, node: ast.Call):
                func_str = ast.unparse(node.func) if hasattr(ast, "unparse") else ""
                if func_str in ("time.sleep", "sleep"):
                    self.sleep_calls.append(node.lineno)
                self.generic_visit(node)

        visitor = SleepVisitor()
        visitor.visit(tree)

        for lineno in visitor.sleep_calls:
            findings.append(
                LoopholeFinding(
                    severity=LoopholeSeverity.MEDIUM,
                    loophole_type=LoopholeType.BLOCKING_SLEEP_IN_CALLBACK,
                    file_path=file_path,
                    line_number=lineno,
                    title="Blocking time.sleep() Detected in ROS Node",
                    description="Using standard `time.sleep()` freezes the executor thread and ignores simulation time (`use_sim_time=True`).",
                    impact="Causes missed deadlines, sensor buffer overflow, and desynchronization with Gazebo/Isaac Sim clock.",
                    recommended_fix="Use a ROS timer (`create_timer()`) or `rate = node.create_rate(hz); rate.sleep()` instead.",
                )
            )
        return findings

    def _check_sensor_watchdog(self, tree: ast.AST, content: str, file_path: str) -> List[LoopholeFinding]:
        """Checks if sensor subscriptions (e.g. LaserScan, PointCloud2, Imu) are verified for freshness/watchdog."""
        # Strip comments so comments don't count as code
        code_only = "\n".join(line.split("#")[0] for line in content.splitlines())

        has_sensor_sub = any(s in code_only for s in ("LaserScan", "Image", "Imu", "PointCloud2", "/scan", "/camera"))
        publishes_cmd = "cmd_vel" in code_only or "Twist" in code_only

        if has_sensor_sub and publishes_cmd:
            # Check if there is any watchdog or timestamp validation
            has_watchdog = any(w in code_only for w in ("last_scan_time", "last_msg_time", "watchdog", "timeout", "now() - ", "time() - "))
            if not has_watchdog:
                return [
                    LoopholeFinding(
                        severity=LoopholeSeverity.HIGH,
                        loophole_type=LoopholeType.MISSING_SENSOR_WATCHDOG,
                        file_path=file_path,
                        line_number=1,
                        title="Missing Sensor Timeout / Watchdog",
                        description="Node subscribes to sensor streams and drives actuators, but does not verify sensor timestamp freshness or timeout.",
                        impact="If the sensor driver crashes or disconnects, the node will either operate on frozen stale data or fail to trigger safe stopping.",
                        recommended_fix="Implement a watchdog timer that resets motors to zero if no new sensor message arrives within a defined threshold (e.g. 0.5s).",
                        sample_patch="""# In constructor:
self.last_sensor_time = self.get_clock().now()
self.watchdog_timer = self.create_timer(0.2, self._check_watchdog)

def sensor_callback(self, msg):
    self.last_sensor_time = self.get_clock().now()
    # Process data...

def _check_watchdog(self):
    elapsed = (self.get_clock().now() - self.last_sensor_time).nanoseconds / 1e9
    if elapsed > 0.5:
        self.get_logger().error(f'Sensor timeout ({elapsed:.2f}s)! Stopping.')
        self.stop_robot()""",
                    )
                ]
        return []

    def _check_nan_inf_handling(self, tree: ast.AST, content: str, file_path: str) -> List[LoopholeFinding]:
        """Detects math operations on sensor ranges or arrays without isnan/isinf checks."""
        has_scan = "ranges" in content and "LaserScan" in content
        checks_nan = "isnan" in content or "isinf" in content or "isfinite" in content

        if has_scan and not checks_nan:
            return [
                LoopholeFinding(
                    severity=LoopholeSeverity.MEDIUM,
                    loophole_type=LoopholeType.UNCHECKED_NAN_INF,
                    file_path=file_path,
                    line_number=1,
                    title="Unchecked NaN / Inf in Sensor Range Processing",
                    description="LaserScan `ranges` are manipulated without `math.isnan()` or `math.isinf()` filtering.",
                    impact="LiDARs report `inf` for out-of-range beams and `nan` for specular/absorbed returns. These propagate into navigation planners and velocity controllers, causing NaN errors.",
                    recommended_fix="Filter out non-finite readings using `[r for r in msg.ranges if math.isfinite(r) and msg.range_min <= r <= msg.range_max]`.",
                )
            ]
        return []

    def _check_multithread_state_mutation(self, tree: ast.AST, content: str, file_path: str) -> List[LoopholeFinding]:
        """Detects MultiThreadedExecutor or ReentrantCallbackGroup without threading.Lock."""
        has_mt = "MultiThreadedExecutor" in content or "ReentrantCallbackGroup" in content
        has_lock = "Lock()" in content or "threading.Lock" in content or "mutex" in content

        if has_mt and not has_lock:
            return [
                LoopholeFinding(
                    severity=LoopholeSeverity.HIGH,
                    loophole_type=LoopholeType.RACE_CONDITION_UNPROTECTED_STATE,
                    file_path=file_path,
                    line_number=1,
                    title="MultiThreadedExecutor without Mutex Lock (Race Condition Hazard)",
                    description="Node uses `MultiThreadedExecutor` or `ReentrantCallbackGroup`, but does not declare or use a `threading.Lock`.",
                    impact="Concurrent callback executions on shared attributes (e.g. `self.current_pose`, `self.target`) will cause data corruption, tearing, and non-deterministic behavior.",
                    recommended_fix="Protect shared state access with `with self.lock:` using `import threading; self.lock = threading.Lock()`.",
                )
            ]
        return []

    def _check_qos_antipattern(self, tree: ast.AST, content: str, file_path: str) -> List[LoopholeFinding]:
        """Detects subscription to high-rate sensor topics with default reliable QoS."""
        findings = []
        if ("create_subscription" in content) and ("/scan" in content or "LaserScan" in content):
            if "qos_profile_sensor_data" not in content and "SensorDataQoS" not in content and "BEST_EFFORT" not in content:
                findings.append(
                    LoopholeFinding(
                        severity=LoopholeSeverity.MEDIUM,
                        loophole_type=LoopholeType.DEFAULT_QOS_ON_HIGH_RATE_SENSOR,
                        file_path=file_path,
                        line_number=1,
                        title="Subscribing to LiDAR/Sensor with Default Reliable QoS",
                        description="Subscribing to `/scan` or sensor messages without using `qos_profile_sensor_data` (BEST_EFFORT).",
                        impact="Most LiDAR and sensor drivers publish with Best Effort QoS. If this subscriber requests Reliable QoS, DDS will refuse to deliver any messages!",
                        recommended_fix="Pass `rclpy.qos.qos_profile_sensor_data` as the QoS argument in `create_subscription`.",
                    )
                )
        return findings

    # ==========================================
    # C++ Structural Pattern Analysis
    # ==========================================
    def _audit_cpp_file(self, file_path: str) -> List[LoopholeFinding]:
        findings: List[LoopholeFinding] = []
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                content = f.read()
        except Exception:
            return findings

        # 1. Unchecked TF lookup
        if "lookupTransform" in content and "tf2::TransformException" not in content:
            findings.append(
                LoopholeFinding(
                    severity=LoopholeSeverity.HIGH,
                    loophole_type=LoopholeType.UNPROTECTED_TF_LOOKUP,
                    file_path=file_path,
                    line_number=None,
                    title="C++ Unprotected lookupTransform Call",
                    description="`tf_buffer_->lookupTransform` is used without catching `tf2::TransformException`.",
                    impact="If the transform is missing or extrapolates, an unhandled exception will terminate the C++ process.",
                    recommended_fix="Wrap lookup in `try { ... } catch (const tf2::TransformException & ex) { RCLCPP_WARN(...); return; }`.",
                )
            )

        # 2. Multi-threaded callback without std::mutex
        if "ReentrantCallbackGroup" in content and "std::mutex" not in content:
            findings.append(
                LoopholeFinding(
                    severity=LoopholeSeverity.HIGH,
                    loophole_type=LoopholeType.RACE_CONDITION_UNPROTECTED_STATE,
                    file_path=file_path,
                    line_number=None,
                    title="C++ Reentrant Callback without std::mutex",
                    description="Node uses `ReentrantCallbackGroup` but does not include `std::mutex` or `std::lock_guard`.",
                    impact="Race condition and memory corruption across threads.",
                    recommended_fix="Add `mutable std::mutex mutex_;` and guard shared variables with `std::lock_guard<std::mutex> lock(mutex_);`.",
                )
            )

        # 3. Raw pointer dereference of shared message pointer without null check
        if re.search(r"void\s+\w+\(const\s+[\w:]+::SharedPtr\s+(\w+)\)\s*\{(?!\s*if\s*\(!?\1)", content):
            findings.append(
                LoopholeFinding(
                    severity=LoopholeSeverity.MEDIUM,
                    loophole_type=LoopholeType.UNCHECKED_NAN_INF,
                    file_path=file_path,
                    line_number=None,
                    title="Potential Nullptr Dereference on ROS 2 Message Pointer",
                    description="Callback receives `SharedPtr msg` and dereferences it without checking `if (!msg)`.",
                    impact="If a null or corrupted message is delivered by the middleware, node crashes with SIGSEGV.",
                    recommended_fix="Add `if (!msg) { return; }` at the start of callback.",
                )
            )

        return findings
