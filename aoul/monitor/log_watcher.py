"""
Real-Time ROS 2 Log Watcher and Stream Monitor.
Monitors live log files or stdin stream, detects crashes, QoS mismatches, and TF glitches,
and surfaces instant triage alerts in real time.
"""

from dataclasses import dataclass
import os
from pathlib import Path
import sys
import time
from typing import Callable, Generator, List, Optional

from aoul.diagnostics.log_analyzer import LogIncident, ROS2LogAnalyzer


class LogWatcher:
    """Tails and monitors ROS 2 log streams for live error triage."""

    def __init__(self, incident_callback: Optional[Callable[[LogIncident], None]] = None):
        self.analyzer = ROS2LogAnalyzer()
        self.incident_callback = incident_callback or self._default_alert

    def _default_alert(self, incident: LogIncident):
        print(f"\n🚨 [AOUL ALERT] [{incident.severity.value}] {incident.category.value}")
        print(f"Summary: {incident.summary}")
        print(f"Root Cause: {incident.root_cause}")
        if incident.remediation_steps:
            print("Actionable Fix:")
            for s in incident.remediation_steps:
                print(f"  ➜ {s}")
        if incident.code_fix:
            print("\nSuggested Code:")
            print(incident.code_fix)
        print("-" * 60)

    def watch_stream(self, stream=sys.stdin):
        """Continuously reads from a piped input stream (e.g. ros2 launch ... | aoul watch)."""
        buffer = []
        last_flush = time.time()

        for line in iter(stream.readline, ""):
            sys.stdout.write(line)
            sys.stdout.flush()

            line_str = line.strip()
            if any(kw in line_str for kw in ("ERROR", "FATAL", "Incompatible QoS", "extrapolation", "SIGSEGV", "Traceback")):
                buffer.append(line_str)

            # Flush and analyze every 0.5s if errors accumulated
            if buffer and (time.time() - last_flush > 0.5 or len(buffer) > 5):
                text_block = "\n".join(buffer)
                incidents = self.analyzer.analyze_text(text_block)
                for inc in incidents:
                    self.incident_callback(inc)
                buffer.clear()
                last_flush = time.time()

    def watch_file(self, file_path: str, poll_interval_sec: float = 0.5):
        """Tails an active log file like `tail -f` and triages errors as they are appended."""
        path = Path(file_path).expanduser().resolve()
        if not path.exists():
            raise FileNotFoundError(f"Log file '{file_path}' does not exist.")

        with open(path, "r", encoding="utf-8", errors="ignore") as f:
            # Go to end of file
            f.seek(0, os.SEEK_END)
            buffer = []

            while True:
                line = f.readline()
                if line:
                    line_str = line.strip()
                    if any(kw in line_str for kw in ("ERROR", "FATAL", "Incompatible QoS", "extrapolation", "SIGSEGV", "Traceback")):
                        buffer.append(line_str)
                        if len(buffer) >= 3 or "SIGSEGV" in line_str or "Traceback" in line_str:
                            text_block = "\n".join(buffer)
                            incidents = self.analyzer.analyze_text(text_block)
                            for inc in incidents:
                                self.incident_callback(inc)
                            buffer.clear()
                else:
                    if buffer:
                        text_block = "\n".join(buffer)
                        incidents = self.analyzer.analyze_text(text_block)
                        for inc in incidents:
                            self.incident_callback(inc)
                        buffer.clear()
                    time.sleep(poll_interval_sec)

    @staticmethod
    def find_latest_ros_log_dir() -> Optional[str]:
        """Locates ~/.ros/log/latest or most recent log directory."""
        ros_log_root = Path.home() / ".ros" / "log"
        if not ros_log_root.exists():
            return None

        latest_symlink = ros_log_root / "latest"
        if latest_symlink.exists():
            return str(latest_symlink)

        # Look for most recent timestamped subfolder
        dirs = [d for d in ros_log_root.iterdir() if d.is_dir()]
        if dirs:
            latest = max(dirs, key=os.path.getmtime)
            return str(latest)
        return None
