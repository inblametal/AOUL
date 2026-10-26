"""
Rosbag2 & MCAP Flight Telemetry Inspector.
Performs deterministic time-series jitter analysis, dropped sensor frame detection,
and timestamp divergence diagnosis for recorded mission data.
"""

from dataclasses import dataclass, field
import math
from typing import Any, Dict, List, Optional


@dataclass
class TopicStats:
    topic_name: str
    message_type: str
    message_count: int
    expected_hz: float
    observed_hz: float
    jitter_std_dev_ms: float
    min_delta_ms: float
    max_delta_ms: float
    dropped_frames_estimate: int
    health_status: str  # "HEALTHY", "WARNING", "CRITICAL"
    anomalies: List[str] = field(default_factory=list)


class RosbagInspector:
    """Analyzes recorded flight bags (MCAP / SQLite3) for timing jitter and packet drops."""

    @staticmethod
    def analyze_topic_timestamps(
        topic_name: str,
        message_type: str,
        timestamps_sec: List[float],
        expected_hz: Optional[float] = None,
    ) -> TopicStats:
        if len(timestamps_sec) < 2:
            return TopicStats(
                topic_name=topic_name,
                message_type=message_type,
                message_count=len(timestamps_sec),
                expected_hz=expected_hz or 0.0,
                observed_hz=0.0,
                jitter_std_dev_ms=0.0,
                min_delta_ms=0.0,
                max_delta_ms=0.0,
                dropped_frames_estimate=0,
                health_status="CRITICAL",
                anomalies=["Insufficient message samples to compute frequency (need at least 2)."],
            )

        # Sort timestamps
        ts = sorted(timestamps_sec)
        deltas = [ts[i] - ts[i - 1] for i in range(1, len(ts))]
        deltas_ms = [d * 1000.0 for d in deltas]

        total_duration = ts[-1] - ts[0]
        observed_hz = (len(ts) - 1) / total_duration if total_duration > 0 else 0.0

        target_hz = expected_hz or observed_hz
        expected_period_ms = (1000.0 / target_hz) if target_hz > 0 else 0.0

        mean_delta_ms = sum(deltas_ms) / len(deltas_ms)
        variance = sum((d - mean_delta_ms) ** 2 for d in deltas_ms) / len(deltas_ms)
        std_dev_ms = math.sqrt(variance)

        min_delta_ms = min(deltas_ms)
        max_delta_ms = max(deltas_ms)

        anomalies = []
        dropped_count = 0

        # Check for dropped frames (> 1.8x expected period)
        if expected_period_ms > 0:
            for d in deltas_ms:
                if d > (1.8 * expected_period_ms):
                    dropped = round(d / expected_period_ms) - 1
                    dropped_count += max(1, dropped)

        if dropped_count > 0:
            anomalies.append(f"Detected ~{dropped_count} dropped sensor frame(s) with inter-packet gaps exceeding 1.8x nominal period.")

        # Check for jitter threshold (> 35% of period)
        if expected_period_ms > 0 and (std_dev_ms > (0.35 * expected_period_ms)):
            anomalies.append(f"Severe publication jitter (std dev: {std_dev_ms:.1f}ms vs nominal {expected_period_ms:.1f}ms).")

        # Check for clock jumps / negative timestamps
        negative_deltas = [d for d in deltas if d < 0]
        if negative_deltas:
            anomalies.append("Out-of-order timestamp anomalies detected (clock backwards jump).")

        health = "HEALTHY"
        if dropped_count > 5 or std_dev_ms > 50.0:
            health = "CRITICAL"
        elif dropped_count > 0 or std_dev_ms > 15.0:
            health = "WARNING"

        return TopicStats(
            topic_name=topic_name,
            message_type=message_type,
            message_count=len(timestamps_sec),
            expected_hz=round(target_hz, 1),
            observed_hz=round(observed_hz, 1),
            jitter_std_dev_ms=round(std_dev_ms, 2),
            min_delta_ms=round(min_delta_ms, 1),
            max_delta_ms=round(max_delta_ms, 1),
            dropped_frames_estimate=dropped_count,
            health_status=health,
            anomalies=anomalies,
        )

    @classmethod
    def analyze_flight_bag(cls, bag_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Analyzes a multi-topic flight bag dataset.
        Format:
        {
          "duration_sec": 12.5,
          "topics": [
             {"name": "/scan", "type": "sensor_msgs/msg/LaserScan", "expected_hz": 20.0, "timestamps": [0.0, 0.05, ...]},
             ...
          ]
        }
        """
        topic_reports = []
        critical_count = 0
        warning_count = 0
        total_messages = 0

        topics = bag_data.get("topics", [])
        for t in topics:
            stats = cls.analyze_topic_timestamps(
                topic_name=t.get("name", "/unknown"),
                message_type=t.get("type", "std_msgs/msg/Header"),
                timestamps_sec=t.get("timestamps", []),
                expected_hz=t.get("expected_hz"),
            )
            total_messages += stats.message_count
            if stats.health_status == "CRITICAL":
                critical_count += 1
            elif stats.health_status == "WARNING":
                warning_count += 1

            topic_reports.append({
                "topic": stats.topic_name,
                "type": stats.message_type,
                "count": stats.message_count,
                "expected_hz": stats.expected_hz,
                "observed_hz": stats.observed_hz,
                "jitter_ms": stats.jitter_std_dev_ms,
                "min_gap_ms": stats.min_delta_ms,
                "max_gap_ms": stats.max_delta_ms,
                "dropped_frames": stats.dropped_frames_estimate,
                "status": stats.health_status,
                "anomalies": stats.anomalies,
            })

        overall_status = "HEALTHY"
        if critical_count > 0:
            overall_status = "CRITICAL"
        elif warning_count > 0:
            overall_status = "WARNING"

        return {
            "overall_status": overall_status,
            "total_topics": len(topic_reports),
            "total_messages": total_messages,
            "critical_topics": critical_count,
            "warning_topics": warning_count,
            "topics": topic_reports,
        }

    @classmethod
    def get_sample_flight_bags(cls) -> Dict[str, Any]:
        """Provides pre-packaged simulation and flight datasets for live interactive testing."""
        # Sample 1: Healthy AMR Run
        clean_timestamps = [i * 0.05 for i in range(100)]  # 20 Hz (50ms interval)
        odom_timestamps = [i * 0.02 for i in range(250)]   # 50 Hz (20ms interval)

        # Sample 2: Degraded Run with LiDAR dropout
        degraded_lidar = []
        curr = 0.0
        for i in range(60):
            if 20 <= i <= 25:
                curr += 0.35  # Massive sensor dropout
            else:
                curr += 0.05
            degraded_lidar.append(curr)

        return {
            "clean_amr_run": {
                "title": "Nominal AMR Navigation Mission (Clean Telemetry)",
                "topics": [
                    {"name": "/scan", "type": "sensor_msgs/msg/LaserScan", "expected_hz": 20.0, "timestamps": clean_timestamps},
                    {"name": "/odom", "type": "nav_msgs/msg/Odometry", "expected_hz": 50.0, "timestamps": odom_timestamps},
                ]
            },
            "degraded_sensor_dropout": {
                "title": "Degraded LiDAR Dropout & Controller Jitter Flight",
                "topics": [
                    {"name": "/scan", "type": "sensor_msgs/msg/LaserScan", "expected_hz": 20.0, "timestamps": degraded_lidar},
                    {"name": "/odom", "type": "nav_msgs/msg/Odometry", "expected_hz": 50.0, "timestamps": odom_timestamps},
                ]
            }
        }
