"""
RoboSage Web Application Server.
Provides a zero-dependency, high-performance local REST & UI server
using Python's built-in http.server module.
"""

try:
    from http.server import ThreadingHTTPServer as ServerClass
except ImportError:
    from http.server import HTTPServer as ServerClass
from http.server import SimpleHTTPRequestHandler
import json
import os
from pathlib import Path
import sys
from typing import Any, Dict, Optional
import urllib.parse

from robosage.agent.core import AgentSession
from robosage.diagnostics.bag_inspector import RosbagInspector
from robosage.diagnostics.behavior_tree_analyzer import BehaviorTreeAnalyzer
from robosage.diagnostics.log_analyzer import ROS2LogAnalyzer
from robosage.diagnostics.loophole_detector import LoopholeDetector
from robosage.diagnostics.power_thermal import PowerThermalEngine
from robosage.diagnostics.qos_checker import (
    DurabilityPolicy,
    QoSProfile,
    ReliabilityPolicy,
    check_qos_compatibility,
)
from robosage.diagnostics.safety_shield import SafetyShieldEngine
from robosage.diagnostics.sarif_exporter import SarifExporter
from robosage.diagnostics.urdf_auditor import UrdfAuditor
from robosage.diagnostics.workspace_inspector import WorkspaceInspector
from robosage.llm.provider import get_llm_provider
from robosage.templates.generator import TemplateGenerator

WEB_DIR = Path(__file__).parent / "web"
EXAMPLES_DIR = Path(__file__).parent.parent / "examples"


class RoboSageRequestHandler(SimpleHTTPRequestHandler):
    """Custom request handler dispatching REST APIs and serving UI assets."""
    disable_nagle_algorithm = True
    protocol_version = "HTTP/1.1"

    def setup(self):
        super().setup()
        self.directory = str(WEB_DIR)
        if not hasattr(self.server, "agent_session"):
            self.server.llm_provider = get_llm_provider(provider_name="qwen")
            self.server.agent_session = AgentSession(provider=self.server.llm_provider)
            self.server.log_analyzer = ROS2LogAnalyzer()
            self.server.loophole_detector = LoopholeDetector()

    def end_headers(self):
        """Prevent WKWebView and browsers from aggressively caching dynamic assets."""
        if not getattr(self, "_custom_cache_set", False):
            self.send_header("Cache-Control", "no-cache, no-store, must-revalidate")
            self.send_header("Pragma", "no-cache")
            self.send_header("Expires", "0")
        super().end_headers()

    def do_OPTIONS(self):
        """Handle CORS pre-flight requests."""
        self.send_response(200)
        self._send_cors_headers()
        self.end_headers()

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path

        if path in ("", "/"):
            self._serve_index_html()
            return

        if path == "/api/doctor":
            self._handle_doctor()
            return

        if path == "/api/threads":
            self._handle_get_threads()
            return

        if path == "/api/memory":
            self._handle_get_memory()
            return

        if path == "/api/local-models":
            self._handle_local_models()
            return

        if path == "/api/examples":
            self._handle_examples()
            return

        if path == "/api/sample-data":
            self._handle_sample_data()
            return

        if path == "/api/graph-topology":
            self._handle_graph_topology()
            return

        if path == "/favicon.ico":
            self.send_response(204)
            self.end_headers()
            return

        # Fallback to standard static file handling from WEB_DIR
        super().do_GET()

    def do_POST(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path

        try:
            content_length = int(self.headers.get("Content-Length", 0))
            body_bytes = self.rfile.read(content_length)
            body = json.loads(body_bytes.decode("utf-8")) if body_bytes else {}
        except Exception as e:
            self._send_json({"error": f"Invalid JSON payload: {e}"}, status=400)
            return

        if path == "/api/chat":
            self._handle_chat(body)
        elif path == "/api/threads":
            self._handle_post_threads(body)
        elif path == "/api/memory":
            self._handle_post_memory(body)
        elif path == "/api/audit":
            self._handle_audit(body)
        elif path == "/api/triage":
            self._handle_triage(body)
        elif path == "/api/check-qos":
            self._handle_check_qos(body)
        elif path == "/api/generate":
            self._handle_generate(body)
        elif path == "/api/refactor":
            self._handle_refactor(body)
        elif path == "/api/save-file":
            self._handle_save_file(body)
        elif path == "/api/bag-analyze":
            self._handle_bag_analyze(body)
        elif path == "/api/bt-analyze":
            self._handle_bt_analyze(body)
        elif path == "/api/safety-shield":
            self._handle_safety_shield(body)
        elif path == "/api/export-sarif":
            self._handle_export_sarif(body)
        elif path == "/api/batch-analyze":
            self._handle_batch_analyze(body)
        elif path == "/api/urdf-audit":
            self._handle_urdf_audit(body)
        elif path == "/api/power-calc":
            self._handle_power_calc(body)
        else:
            self._send_json({"error": f"Endpoint '{path}' not found."}, status=404)

    # -------------------------------------------------------------
    # API Handlers
    # -------------------------------------------------------------
    def _handle_get_threads(self):
        session = getattr(self.server, "agent_session", None)
        if not session:
            self._send_json({"threads": [], "active_thread_id": "default_thread"})
            return
        self._send_json({
            "threads": session.conversation_manager.list_threads(),
            "active_thread_id": session.conversation_manager.active_thread_id,
        })

    def _handle_post_threads(self, body: Dict[str, Any]):
        session = getattr(self.server, "agent_session", None)
        if not session:
            self._send_json({"error": "No active session"}, status=500)
            return

        action = body.get("action", "list")
        mgr = session.conversation_manager

        if action == "create":
            title = body.get("title", "New Conversation")
            thread = mgr.create_thread(title)
            self._send_json({"thread": thread.to_dict(), "active_thread_id": thread.id, "threads": mgr.list_threads()})
        elif action == "switch":
            thread_id = body.get("thread_id")
            thread = mgr.switch_thread(thread_id)
            if thread:
                self._send_json({"thread": thread.to_dict(), "active_thread_id": thread.id, "threads": mgr.list_threads()})
            else:
                self._send_json({"error": "Thread not found"}, status=404)
        elif action == "get":
            thread_id = body.get("thread_id") or mgr.active_thread_id
            thread = mgr.threads.get(thread_id)
            if thread:
                self._send_json({"thread": thread.to_dict(), "active_thread_id": thread.id})
            else:
                self._send_json({"error": "Thread not found"}, status=404)
        elif action == "rename":
            thread_id = body.get("thread_id")
            new_title = body.get("title", "Untitled")
            success = mgr.rename_thread(thread_id, new_title)
            self._send_json({"success": success, "threads": mgr.list_threads()})
        elif action == "delete":
            thread_id = body.get("thread_id")
            success = mgr.delete_thread(thread_id)
            self._send_json({"success": success, "threads": mgr.list_threads(), "active_thread_id": mgr.active_thread_id})
        elif action == "clear":
            thread_id = body.get("thread_id") or mgr.active_thread_id
            success = mgr.clear_thread(thread_id)
            self._send_json({"success": success, "active_thread_id": mgr.active_thread_id})
        else:
            self._send_json({"threads": mgr.list_threads(), "active_thread_id": mgr.active_thread_id})

    def _handle_get_memory(self):
        session = getattr(self.server, "agent_session", None)
        if not session:
            from robosage.agent.memory import RoboticsMemoryLayer
            self._send_json(RoboticsMemoryLayer().to_dict())
            return
        self._send_json(session.conversation_manager.memory_layer.to_dict())

    def _handle_post_memory(self, body: Dict[str, Any]):
        session = getattr(self.server, "agent_session", None)
        if not session:
            self._send_json({"error": "No active session"}, status=500)
            return

        mem = session.conversation_manager.memory_layer
        action = body.get("action", "update")

        if action == "update":
            mem.update_from_dict(body.get("data", {}))
            self._send_json({"success": True, "memory": mem.to_dict()})
        elif action == "add_param":
            k = str(body.get("key", "")).strip()
            v = str(body.get("value", "")).strip()
            if k:
                mem.working_parameters[k] = v
            self._send_json({"success": True, "memory": mem.to_dict()})
        elif action == "delete_param":
            k = str(body.get("key", "")).strip()
            if k in mem.working_parameters:
                del mem.working_parameters[k]
            self._send_json({"success": True, "memory": mem.to_dict()})
        elif action == "reset":
            from robosage.agent.memory import RoboticsMemoryLayer
            session.conversation_manager.memory_layer = RoboticsMemoryLayer()
            self._send_json({"success": True, "memory": session.conversation_manager.memory_layer.to_dict()})
        else:
            self._send_json({"error": f"Unknown memory action '{action}'"}, status=400)

    def _handle_chat(self, body: Dict[str, Any]):
        try:
            message = body.get("message", "").strip()
            provider_name = body.get("provider") or "qwen"
            api_key = body.get("api_key")
            model = body.get("model")
            thread_id = body.get("thread_id")
            stream = bool(body.get("stream", False))

            if not message:
                self._send_json({"error": "Empty message."}, status=400)
                return

            # Maintain session singleton with dynamic provider updates so conversation continuation is preserved
            session = getattr(self.server, "agent_session", None)
            if session is None:
                provider = get_llm_provider(provider_name=provider_name, api_key=api_key, model=model)
                session = AgentSession(provider=provider)
                self.server.agent_session = session
            elif provider_name or api_key or model:
                try:
                    session.provider = get_llm_provider(provider_name=provider_name, api_key=api_key, model=model)
                except Exception:
                    pass

            target_thread = session.conversation_manager.get_or_create_thread(thread_id)

            if stream:
                self.close_connection = True
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream; charset=utf-8")
                self.send_header("Cache-Control", "no-cache, no-store, must-revalidate, no-transform")
                self.send_header("Connection", "close")
                self.send_header("X-Accel-Buffering", "no")
                self._send_cors_headers()
                self._custom_cache_set = True
                self.end_headers()

                # Immediate heartbeat so WebKit connects instantly with 0ms latency
                try:
                    self.wfile.write(b": heartbeat\n\n")
                    self.wfile.flush()
                    for chunk in session.step_stream(message, thread_id=target_thread.id):
                        data = json.dumps(chunk)
                        self.wfile.write(f"data: {data}\n\n".encode("utf-8"))
                        self.wfile.flush()
                    self.wfile.write(b"data: [DONE]\n\n")
                    self.wfile.flush()
                except (BrokenPipeError, ConnectionResetError, OSError):
                    pass
                return

            reply = session.step(message, thread_id=target_thread.id)
            model_name = getattr(session.provider, "model", None)
            provider_label = (
                f"Qwen Coder ({model_name})"
                if "qwen" in session.provider.__class__.__name__.lower()
                else session.provider.__class__.__name__
            )
            self._send_json({
                "reply": reply,
                "provider": provider_label,
                "thread_id": target_thread.id,
                "thread_title": target_thread.title,
                "turn_count": len(target_thread.messages),
                "memory_summary": session.conversation_manager.memory_layer.robot_profile.platform_type,
                "model": model_name,
                "history_length": len(session.conversation_history),
            })
        except Exception as e:
            try:
                self._send_json({"error": f"Chat engine error: {str(e)}"}, status=500)
            except Exception:
                pass

    def _handle_audit(self, body: Dict[str, Any]):
        code = body.get("code")
        file_path = body.get("file_path")

        detector: LoopholeDetector = self.server.loophole_detector

        if file_path and os.path.exists(file_path):
            if os.path.isdir(file_path):
                findings = detector.audit_directory(file_path)
            else:
                findings = detector.audit_file(file_path)
        elif code:
            # Write temporary file in scratch or inspect directly
            import tempfile
            with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False) as tf:
                tf.write(code)
                temp_name = tf.name
            try:
                findings = detector.audit_file(temp_name)
                # Remap temp file path to "<pasted_code>"
                for f in findings:
                    f.file_path = "pasted_buffer.py"
            finally:
                if os.path.exists(temp_name):
                    os.remove(temp_name)
        else:
            self._send_json({"error": "Provide either 'code' or 'file_path'."}, status=400)
            return

        serialized = [
            {
                "severity": f.severity.value,
                "loophole_type": f.loophole_type.value,
                "file_path": f.file_path,
                "line_number": f.line_number,
                "title": f.title,
                "description": f.description,
                "impact": f.impact,
                "recommended_fix": f.recommended_fix,
                "sample_patch": f.sample_patch,
            }
            for f in findings
        ]

        self._send_json({
            "count": len(serialized),
            "findings": serialized,
        })

    def _handle_triage(self, body: Dict[str, Any]):
        log_content = body.get("log_content", "").strip()
        if not log_content:
            self._send_json({"error": "No log content provided."}, status=400)
            return

        analyzer: ROS2LogAnalyzer = self.server.log_analyzer
        incidents = analyzer.analyze_text(log_content)

        serialized = [
            {
                "severity": inc.severity.value,
                "category": inc.category.value,
                "summary": inc.summary,
                "root_cause": inc.root_cause,
                "remediation_steps": inc.remediation_steps,
                "code_fix": inc.code_fix,
                "topic_or_frame": inc.topic_or_frame,
                "file_path": inc.file_path,
                "line_number": inc.line_number,
            }
            for inc in incidents
        ]

        self._send_json({
            "count": len(serialized),
            "incidents": serialized,
        })

    def _handle_check_qos(self, body: Dict[str, Any]):
        try:
            pub_q = QoSProfile(
                reliability=ReliabilityPolicy(body.get("pub_reliability", "RELIABLE").upper()),
                durability=DurabilityPolicy(body.get("pub_durability", "VOLATILE").upper()),
            )
            sub_q = QoSProfile(
                reliability=ReliabilityPolicy(body.get("sub_reliability", "RELIABLE").upper()),
                durability=DurabilityPolicy(body.get("sub_durability", "VOLATILE").upper()),
            )
            res = check_qos_compatibility(pub_q, sub_q)

            self._send_json({
                "is_compatible": res.is_compatible,
                "status": "COMPATIBLE" if res.is_compatible else "INCOMPATIBLE",
                "issues": res.issues,
                "recommendations": res.recommendations,
                "details": res.details,
            })
        except Exception as e:
            self._send_json({"error": f"Failed to check QoS: {e}"}, status=400)

    def _handle_doctor(self):
        report = WorkspaceInspector.inspect()
        provider = self.server.llm_provider
        self._send_json({
            "ros_distro": report.ros_distro,
            "ros_domain_id": report.ros_domain_id,
            "rmw_implementation": report.rmw_implementation,
            "colcon_available": report.colcon_available,
            "ros2_cli_available": report.ros2_cli_available,
            "workspace_root": report.workspace_root,
            "packages_found": report.packages_found,
            "warnings": report.warnings,
            "recommendations": report.recommendations,
            "active_provider": provider.__class__.__name__,
        })

    def _handle_local_models(self):
        import platform
        import threading
        from robosage.llm.provider import (
            get_installed_ollama_models,
            resolve_best_local_model,
            resolve_turbo_model,
            warm_up_local_model,
        )
        endpoint = os.environ.get("QWEN_ENDPOINT", "http://127.0.0.1:11434")
        installed = get_installed_ollama_models(endpoint)
        best = resolve_best_local_model(endpoint) if installed else "qwen2.5-coder:latest"
        turbo = resolve_turbo_model(endpoint) if installed else None

        # Detect Intel Mac or CPU-constrained machines where 7B+ models swap heavily
        is_cpu_constrained = (sys.platform == "darwin" and platform.machine() in ("x86_64", "i386")) or (os.cpu_count() or 4) <= 4
        default_model = (turbo or best) if is_cpu_constrained else best

        # Pre-warm local models in background so user's first prompt executes with 0ms cold-start
        if installed:
            threading.Thread(target=warm_up_local_model, args=(endpoint, default_model), daemon=True).start()
            if turbo and turbo != default_model:
                threading.Thread(target=warm_up_local_model, args=(endpoint, turbo), daemon=True).start()

        # Detect Cactus Needle 3 availability
        try:
            import needle
            cactus_available = True
        except Exception:
            cactus_available = False

        self._send_json({
            "ollama_online": len(installed) > 0,
            "installed_models": installed,
            "best_model": best,
            "turbo_model": turbo,
            "default_model": default_model,
            "is_cpu_constrained": is_cpu_constrained,
            "cactus_needle_available": cactus_available,
            "endpoint": endpoint,
        })

    def _handle_generate(self, body: Dict[str, Any]):
        template_type = body.get("template_type", "diff_drive").lower()
        node_name = body.get("node_name", f"safe_{template_type}_node")

        generators = {
            "diff_drive": TemplateGenerator.safe_diff_drive,
            "tf_listener": TemplateGenerator.tf_listener,
            "multithreaded": TemplateGenerator.multithreaded_safe_node,
        }

        if template_type not in generators:
            self._send_json({"error": f"Invalid template type: {template_type}"}, status=400)
            return

        code = generators[template_type](node_name=node_name)
        self._send_json({
            "template_type": template_type,
            "node_name": node_name,
            "code": code,
        })

    def _handle_refactor(self, body: Dict[str, Any]):
        from robosage.llm.provider import QwenProvider
        code = body.get("code", "").strip()
        focus = body.get("focus", "all")
        model = body.get("model")
        endpoint = body.get("endpoint")

        if not code:
            self._send_json({"error": "No code provided to improve."}, status=400)
            return

        qwen = QwenProvider(endpoint=endpoint, model=model)
        try:
            improved = qwen.improve_code(code, focus=focus)
            self._send_json({
                "improved_code": improved,
                "model": qwen.model,
                "provider": f"Qwen Coder ({qwen.model})",
            })
        except Exception as e:
            # If Qwen server connection fails, provide offline improvement guidance
            fallback_prompt = (
                f"⚠️ Could not reach local Qwen Coder at {qwen.endpoint} ({e}).\n\n"
                f"To start local Qwen Coder, run: `ollama run qwen2.5-coder` or open your local model runner.\n\n"
                f"**Static Robotics Safety Recommendations for your code:**\n"
                f"1. Ensure zero-velocity Twist(0,0,0) is commanded before node shutdown.\n"
                f"2. Wrap all `tf_buffer.lookup_transform` calls in `try...except TransformException`.\n"
                f"3. Do not invoke `client.call()` synchronously inside timer/subscription callbacks.\n"
                f"4. Add a watchdog check to halt motors if incoming sensor data is older than 0.5s.\n"
                f"5. Filter `math.isnan()` and `math.isinf()` from laser ranges."
            )
            self._send_json({
                "improved_code": fallback_prompt,
                "model": "offline-fallback",
                "provider": "RoboSage Heuristic Fallback",
                "warning": str(e),
            })

    def _handle_save_file(self, body: Dict[str, Any]):
        path_str = body.get("path")
        content = body.get("content")
        if not path_str or content is None:
            self._send_json({"error": "Path and content required."}, status=400)
            return

        try:
            target = Path(path_str).resolve()
            target.parent.mkdir(parents=True, exist_ok=True)
            with open(target, "w", encoding="utf-8") as f:
                f.write(content)
            self._send_json({"success": True, "saved_path": str(target)})
        except Exception as e:
            self._send_json({"error": f"Failed to save file: {e}"}, status=500)

    def _handle_examples(self):
        buggy_code = ""
        crash_log = ""

        buggy_path = EXAMPLES_DIR / "buggy_node.py"
        if buggy_path.exists():
            with open(buggy_path, "r", encoding="utf-8") as f:
                buggy_code = f.read()

        crash_path = EXAMPLES_DIR / "sample_ros2_crash.log"
        if crash_path.exists():
            with open(crash_path, "r", encoding="utf-8") as f:
                crash_log = f.read()

        self._send_json({
            "buggy_code": buggy_code,
            "crash_log": crash_log,
        })

    def _handle_sample_data(self):
        self._send_json({
            "flight_bags": RosbagInspector.get_sample_flight_bags(),
            "behavior_trees": BehaviorTreeAnalyzer.get_sample_trees(),
            "urdf_models": UrdfAuditor.get_sample_urdfs(),
            "motor_presets": {
                "direct_drive_amr": {
                    "torque_nm": 3.2,
                    "speed_rad_s": 12.5,
                    "motor_resistance_ohms": 0.85,
                    "torque_constant_kt": 0.12,
                    "battery_voltage": 24.0,
                    "battery_capacity_ah": 15.0,
                    "ambient_temp_c": 25.0
                },
                "high_torque_manipulator": {
                    "torque_nm": 18.5,
                    "speed_rad_s": 2.8,
                    "motor_resistance_ohms": 1.45,
                    "torque_constant_kt": 0.28,
                    "battery_voltage": 48.0,
                    "battery_capacity_ah": 20.0,
                    "ambient_temp_c": 28.0
                },
                "drone_bldc_motor": {
                    "torque_nm": 0.45,
                    "speed_rad_s": 85.0,
                    "motor_resistance_ohms": 0.18,
                    "torque_constant_kt": 0.035,
                    "battery_voltage": 14.8,
                    "battery_capacity_ah": 5.0,
                    "ambient_temp_c": 22.0
                }
            },
            "safety_shield_presets": {
                "amr_warehouse": {
                    "max_linear_vel": 1.2,
                    "max_angular_vel": 1.5,
                    "max_linear_accel": 1.0,
                    "min_safe_dist": 0.40,
                    "latency": 0.05,
                },
                "heavy_payload_agv": {
                    "max_linear_vel": 0.6,
                    "max_angular_vel": 0.8,
                    "max_linear_accel": 0.4,
                    "min_safe_dist": 0.80,
                    "latency": 0.08,
                },
                "high_speed_drone": {
                    "max_linear_vel": 4.0,
                    "max_angular_vel": 3.0,
                    "max_linear_accel": 2.5,
                    "min_safe_dist": 1.20,
                    "latency": 0.03,
                }
            }
        })

    def _handle_graph_topology(self):
        """Returns visual computation graph node-topic-QoS topology."""
        self._send_json({
            "nodes": [
                {"id": "laser_driver", "label": "/laser_driver", "type": "hardware", "x": 80, "y": 80},
                {"id": "amcl", "label": "/amcl_localization", "type": "algorithm", "x": 300, "y": 80},
                {"id": "bt_navigator", "label": "/bt_navigator", "type": "control", "x": 520, "y": 140},
                {"id": "safety_shield", "label": "/safety_shield_node", "type": "safety", "x": 520, "y": 280},
                {"id": "motor_driver", "label": "/motor_controller", "type": "hardware", "x": 760, "y": 280},
                {"id": "legacy_logger", "label": "/legacy_cloud_logger", "type": "telemetry", "x": 300, "y": 240},
            ],
            "topics": [
                {"id": "t_scan", "name": "/scan", "type": "sensor_msgs/msg/LaserScan"},
                {"id": "t_pose", "name": "/amcl_pose", "type": "geometry_msgs/msg/PoseWithCovarianceStamped"},
                {"id": "t_cmd_raw", "name": "/cmd_vel_raw", "type": "geometry_msgs/msg/Twist"},
                {"id": "t_cmd_safe", "name": "/cmd_vel", "type": "geometry_msgs/msg/Twist"},
                {"id": "t_odom", "name": "/odom", "type": "nav_msgs/msg/Odometry"},
            ],
            "edges": [
                {"from": "laser_driver", "to": "t_scan", "role": "pub", "qos": "BEST_EFFORT / VOLATILE", "status": "NOMINAL"},
                {"from": "t_scan", "to": "amcl", "role": "sub", "qos": "BEST_EFFORT / VOLATILE", "status": "NOMINAL"},
                {"from": "t_scan", "to": "safety_shield", "role": "sub", "qos": "BEST_EFFORT / VOLATILE", "status": "NOMINAL"},
                {"from": "t_scan", "to": "legacy_logger", "role": "sub", "qos": "RELIABLE / TRANSIENT_LOCAL", "status": "INCOMPATIBLE", "issue": "Subscriber requested RELIABLE QoS but publisher offers BEST_EFFORT."},
                {"from": "amcl", "to": "t_pose", "role": "pub", "qos": "RELIABLE / VOLATILE", "status": "NOMINAL"},
                {"from": "t_pose", "to": "bt_navigator", "role": "sub", "qos": "RELIABLE / VOLATILE", "status": "NOMINAL"},
                {"from": "bt_navigator", "to": "t_cmd_raw", "role": "pub", "qos": "RELIABLE / VOLATILE", "status": "NOMINAL"},
                {"from": "t_cmd_raw", "to": "safety_shield", "role": "sub", "qos": "RELIABLE / VOLATILE", "status": "NOMINAL"},
                {"from": "safety_shield", "to": "t_cmd_safe", "role": "pub", "qos": "RELIABLE / VOLATILE", "status": "NOMINAL"},
                {"from": "t_cmd_safe", "to": "motor_driver", "role": "sub", "qos": "RELIABLE / VOLATILE", "status": "NOMINAL"},
                {"from": "motor_driver", "to": "t_odom", "role": "pub", "qos": "RELIABLE / VOLATILE", "status": "NOMINAL"},
                {"from": "t_odom", "to": "amcl", "role": "sub", "qos": "RELIABLE / VOLATILE", "status": "NOMINAL"},
            ]
        })

    def _handle_urdf_audit(self, body: Dict[str, Any]):
        urdf_xml = body.get("urdf", "").strip()
        if not urdf_xml:
            self._send_json({"error": "No URDF XML provided."}, status=400)
            return
        report = UrdfAuditor.audit_urdf_text(urdf_xml)
        self._send_json(report)

    def _handle_power_calc(self, body: Dict[str, Any]):
        try:
            torque = float(body.get("torque_nm", 2.5))
            speed = float(body.get("speed_rad_s", 10.0))
            duration = float(body.get("duration_min", 15.0))
            resistance = float(body.get("motor_resistance_ohms", 0.85))
            kt = float(body.get("torque_constant_kt", 0.12))
            v_bat = float(body.get("battery_voltage", 24.0))
            ah_bat = float(body.get("battery_capacity_ah", 15.0))
            t_amb = float(body.get("ambient_temp_c", 25.0))

            res = PowerThermalEngine.calculate_motor_and_power(
                torque_nm=torque,
                speed_rad_s=speed,
                run_duration_min=duration,
                motor_resistance_ohms=resistance,
                torque_constant_kt=kt,
                battery_voltage=v_bat,
                battery_capacity_ah=ah_bat,
                ambient_temp_c=t_amb,
            )
            self._send_json(res)
        except Exception as e:
            self._send_json({"error": f"Failed to compute motor thermal envelope: {e}"}, status=400)

    def _handle_bag_analyze(self, body: Dict[str, Any]):
        try:
            report = RosbagInspector.analyze_flight_bag(body)
            self._send_json(report)
        except Exception as e:
            self._send_json({"error": f"Failed to analyze flight telemetry: {e}"}, status=400)

    def _handle_bt_analyze(self, body: Dict[str, Any]):
        xml_content = body.get("xml", "").strip()
        if not xml_content:
            self._send_json({"error": "No Behavior Tree XML provided."}, status=400)
            return
        result = BehaviorTreeAnalyzer.parse_and_audit_xml(xml_content)
        self._send_json(result)

    def _handle_safety_shield(self, body: Dict[str, Any]):
        action = body.get("action", "calculate")
        if action == "generate_cpp":
            code = SafetyShieldEngine.generate_cpp_shield_node(body.get("node_name", "safety_shield_node"))
            self._send_json({"code": code, "language": "cpp"})
        elif action == "generate_python":
            code = SafetyShieldEngine.generate_python_shield_node(body.get("node_name", "safety_shield_node"))
            self._send_json({"code": code, "language": "python"})
        else:
            v_cmd = float(body.get("linear_vel", 1.0))
            w_cmd = float(body.get("angular_vel", 0.0))
            dist = float(body.get("obstacle_dist", 1.5))
            v_max = float(body.get("max_linear_vel", 1.0))
            w_max = float(body.get("max_angular_vel", 1.5))
            a_max = float(body.get("max_linear_accel", 0.8))
            d_safe = float(body.get("min_safe_dist", 0.35))
            latency = float(body.get("latency", 0.05))

            envelope = SafetyShieldEngine.calculate_envelope(
                commanded_linear_vel=v_cmd,
                commanded_angular_vel=w_cmd,
                current_distance_to_obstacle=dist,
                max_linear_vel=v_max,
                max_angular_vel=w_max,
                max_linear_accel=a_max,
                min_safe_distance=d_safe,
                latency_seconds=latency,
            )
            self._send_json(envelope)

    def _handle_export_sarif(self, body: Dict[str, Any]):
        findings = body.get("findings", [])
        target_file = body.get("target_file", "src/robot_node.py")
        sarif_doc = SarifExporter.convert_findings_to_sarif(findings, target_file)
        self._send_json(sarif_doc)

    def _handle_batch_analyze(self, body: Dict[str, Any]):
        """Accepts a list of bag or BT payloads and returns a combined report.
        Expected body format:
        {
            "tasks": [
                {"type": "bag", "payload": {...}},
                {"type": "bt", "payload": "<xml>...</xml>"}
            ]
        }
        """
        tasks = body.get("tasks", [])
        reports = []
        for t in tasks:
            ttype = t.get("type")
            payload = t.get("payload")
            if ttype == "bag":
                try:
                    reports.append({"type": "bag", "report": RosbagInspector.analyze_flight_bag(payload)})
                except Exception as e:
                    reports.append({"type": "bag", "error": str(e)})
            elif ttype == "bt":
                try:
                    reports.append({"type": "bt", "report": BehaviorTreeAnalyzer.parse_and_audit_xml(payload)})
                except Exception as e:
                    reports.append({"type": "bt", "error": str(e)})
            else:
                reports.append({"type": ttype, "error": "Unsupported task type"})
        self._send_json({"batch_reports": reports})

    def _serve_index_html(self):
        index_file = WEB_DIR / "index.html"
        if not index_file.exists():
            self._send_json({"error": "UI index.html not found."}, status=404)
            return

        with open(index_file, "rb") as f:
            content = f.read()

        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(content)))
        self._send_cors_headers()
        self.end_headers()
        self.wfile.write(content)

    def _send_json(self, data: Any, status: int = 200):
        body = json.dumps(data, indent=2).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self._send_cors_headers()
        self.end_headers()
        self.wfile.write(body)

    def _send_cors_headers(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization")

    def log_message(self, format, *args):
        """Clean single-line logging for server requests."""
        try:
            msg = format % args
        except Exception:
            msg = " ".join(str(a) for a in args)
        sys.stderr.write(f"[{self.log_date_time_string()}] {msg}\n")


def start_server(host: str = "127.0.0.1", port: int = 8765, max_port_attempts: int = 25):
    """Starts the AOUL application HTTP server with auto-port conflict recovery."""
    import threading
    from robosage.llm.provider import warm_up_local_model

    httpd = None
    actual_port = port
    for p in range(port, port + max_port_attempts):
        try:
            server_address = (host, p)
            httpd = ServerClass(server_address, RoboSageRequestHandler)
            actual_port = p
            break
        except OSError:
            continue

    if httpd is None:
        server_address = (host, 0)
        httpd = ServerClass(server_address, RoboSageRequestHandler)
        actual_port = httpd.server_port

    httpd.bound_port = actual_port
    # Default to local Qwen Coder model
    httpd.llm_provider = get_llm_provider(provider_name="qwen")
    httpd.agent_session = AgentSession(provider=httpd.llm_provider)
    httpd.log_analyzer = ROS2LogAnalyzer()
    httpd.loophole_detector = LoopholeDetector()

    # Pre-warm local Qwen Coder in background thread
    threading.Thread(target=warm_up_local_model, daemon=True).start()

    print(f"🚀 AOUL Application Server running at http://{host}:{actual_port}/")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\n🛑 AOUL server stopped.")
    finally:
        httpd.server_close()
