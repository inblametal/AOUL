"""
RoboSage Web Application Server.
Provides a zero-dependency, high-performance local REST & UI server
using Python's built-in http.server module.
"""

from http.server import HTTPServer, SimpleHTTPRequestHandler
import json
import os
from pathlib import Path
import sys
from typing import Any, Dict, Optional
import urllib.parse

from robosage.agent.core import AgentSession
from robosage.diagnostics.log_analyzer import ROS2LogAnalyzer
from robosage.diagnostics.loophole_detector import LoopholeDetector
from robosage.diagnostics.qos_checker import (
    DurabilityPolicy,
    QoSProfile,
    ReliabilityPolicy,
    check_qos_compatibility,
)
from robosage.diagnostics.workspace_inspector import WorkspaceInspector
from robosage.llm.provider import get_llm_provider
from robosage.templates.generator import TemplateGenerator

WEB_DIR = Path(__file__).parent / "web"
EXAMPLES_DIR = Path(__file__).parent.parent / "examples"


class RoboSageRequestHandler(SimpleHTTPRequestHandler):
    """Custom request handler dispatching REST APIs and serving UI assets."""

    def __init__(self, *args, **kwargs):
        # Initializing singletons on the server instance
        if not hasattr(self.server, "agent_session"):
            self.server.llm_provider = get_llm_provider()
            self.server.agent_session = AgentSession(provider=self.server.llm_provider)
            self.server.log_analyzer = ROS2LogAnalyzer()
            self.server.loophole_detector = LoopholeDetector()
        super().__init__(*args, directory=str(WEB_DIR), **kwargs)

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

        if path == "/api/examples":
            self._handle_examples()
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
        elif path == "/api/audit":
            self._handle_audit(body)
        elif path == "/api/triage":
            self._handle_triage(body)
        elif path == "/api/check-qos":
            self._handle_check_qos(body)
        elif path == "/api/generate":
            self._handle_generate(body)
        elif path == "/api/save-file":
            self._handle_save_file(body)
        else:
            self._send_json({"error": f"Endpoint '{path}' not found."}, status=404)

    # -------------------------------------------------------------
    # API Handlers
    # -------------------------------------------------------------
    def _handle_chat(self, body: Dict[str, Any]):
        message = body.get("message", "").strip()
        provider_name = body.get("provider")
        api_key = body.get("api_key")
        model = body.get("model")

        if not message:
            self._send_json({"error": "Empty message."}, status=400)
            return

        # If user changed provider or credentials, re-instantiate session
        if provider_name or api_key or model:
            provider = get_llm_provider(provider_name=provider_name, api_key=api_key, model=model)
            session = AgentSession(provider=provider)
        else:
            session = self.server.agent_session

        reply = session.step(message)
        self._send_json({
            "reply": reply,
            "provider": session.provider.__class__.__name__,
            "history_length": len(session.conversation_history),
        })

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
        sys.stderr.write(f"[{self.log_date_time_string()}] {args[0]} {args[1]} {args[2]}\n")


def start_server(host: str = "127.0.0.1", port: int = 8765):
    """Starts the RoboSage application HTTP server."""
    server_address = (host, port)
    httpd = HTTPServer(server_address, RoboSageRequestHandler)
    print(f"🚀 RoboSage Application Server running at http://{host}:{port}/")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\n🛑 RoboSage server stopped.")
    finally:
        httpd.server_close()
