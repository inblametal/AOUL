"""
ROS 2 Quality of Service (QoS) Compatibility & Policy Validator.
Provides strict compatibility checks between Publishers and Subscribers
based on DDS specification and ROS 2 design guidelines.
"""

from dataclasses import dataclass
from enum import Enum
from typing import Dict, List, Optional, Tuple


class ReliabilityPolicy(str, Enum):
    RELIABLE = "RELIABLE"
    BEST_EFFORT = "BEST_EFFORT"
    UNKNOWN = "UNKNOWN"


class DurabilityPolicy(str, Enum):
    TRANSIENT_LOCAL = "TRANSIENT_LOCAL"
    VOLATILE = "VOLATILE"
    UNKNOWN = "UNKNOWN"


class LivelinessPolicy(str, Enum):
    AUTOMATIC = "AUTOMATIC"
    MANUAL_BY_TOPIC = "MANUAL_BY_TOPIC"
    UNKNOWN = "UNKNOWN"


@dataclass
class QoSProfile:
    reliability: ReliabilityPolicy = ReliabilityPolicy.RELIABLE
    durability: DurabilityPolicy = DurabilityPolicy.VOLATILE
    history_depth: int = 10
    liveliness: LivelinessPolicy = LivelinessPolicy.AUTOMATIC
    deadline_sec: Optional[float] = None
    lifespan_sec: Optional[float] = None

    @classmethod
    def from_dict(cls, data: dict) -> "QoSProfile":
        rel = ReliabilityPolicy(data.get("reliability", "RELIABLE").upper())
        dur = DurabilityPolicy(data.get("durability", "VOLATILE").upper())
        liv = LivelinessPolicy(data.get("liveliness", "AUTOMATIC").upper())
        return cls(
            reliability=rel,
            durability=dur,
            history_depth=int(data.get("history_depth", 10)),
            liveliness=liv,
            deadline_sec=data.get("deadline_sec"),
            lifespan_sec=data.get("lifespan_sec"),
        )

    @classmethod
    def sensor_data_preset(cls) -> "QoSProfile":
        """Equivalent to rclcpp::SensorDataQoS() / qos_profile_sensor_data."""
        return cls(
            reliability=ReliabilityPolicy.BEST_EFFORT,
            durability=DurabilityPolicy.VOLATILE,
            history_depth=5,
        )

    @classmethod
    def default_preset(cls) -> "QoSProfile":
        """Equivalent to default reliable QoS."""
        return cls(
            reliability=ReliabilityPolicy.RELIABLE,
            durability=DurabilityPolicy.VOLATILE,
            history_depth=10,
        )

    @classmethod
    def latched_preset(cls) -> "QoSProfile":
        """Equivalent to ROS 1 latched topic (e.g. /map, /robot_description)."""
        return cls(
            reliability=ReliabilityPolicy.RELIABLE,
            durability=DurabilityPolicy.TRANSIENT_LOCAL,
            history_depth=1,
        )


@dataclass
class QoSCheckResult:
    is_compatible: bool
    issues: List[str]
    recommendations: List[str]
    details: Dict[str, str]


def check_qos_compatibility(publisher_qos: QoSProfile, subscription_qos: QoSProfile) -> QoSCheckResult:
    """
    Checks compatibility according to ROS 2 Request vs Offered (RxO) rules:
    - Reliability: Offered must be >= Requested. (RELIABLE >= BEST_EFFORT)
      -> If Sub requests RELIABLE, Pub MUST offer RELIABLE.
      -> If Pub offers BEST_EFFORT and Sub requests RELIABLE: INCOMPATIBLE!
    - Durability: Offered must be >= Requested. (TRANSIENT_LOCAL >= VOLATILE)
      -> If Sub requests TRANSIENT_LOCAL, Pub MUST offer TRANSIENT_LOCAL.
    - Deadline: Offered deadline <= Requested deadline.
    - Liveliness: Offered liveliness >= Requested liveliness.
    """
    issues = []
    recommendations = []
    details = {}

    # 1. Reliability check
    if subscription_qos.reliability == ReliabilityPolicy.RELIABLE and publisher_qos.reliability == ReliabilityPolicy.BEST_EFFORT:
        issues.append(
            "Reliability Mismatch: Subscription requested RELIABLE, but Publisher offers BEST_EFFORT."
        )
        recommendations.append(
            "Change subscription QoS to 'rclpy.qos.qos_profile_sensor_data' or set reliability to BEST_EFFORT, "
            "OR change publisher to RELIABLE if packet loss is unacceptable."
        )
        details["reliability"] = "INCOMPATIBLE (Offered BEST_EFFORT < Requested RELIABLE)"
    else:
        details["reliability"] = "COMPATIBLE"

    # 2. Durability check
    if subscription_qos.durability == DurabilityPolicy.TRANSIENT_LOCAL and publisher_qos.durability == DurabilityPolicy.VOLATILE:
        issues.append(
            "Durability Mismatch: Subscription requested TRANSIENT_LOCAL (latched), but Publisher offers VOLATILE."
        )
        recommendations.append(
            "Configure publisher durability to TRANSIENT_LOCAL if late-joining subscribers need the last message "
            "(e.g., /map, /tf_static, /robot_description)."
        )
        details["durability"] = "INCOMPATIBLE (Offered VOLATILE < Requested TRANSIENT_LOCAL)"
    elif publisher_qos.durability == DurabilityPolicy.TRANSIENT_LOCAL and subscription_qos.durability == DurabilityPolicy.VOLATILE:
        # Not strictly broken by DDS, but Sub won't receive past latched message!
        issues.append(
            "Durability Sub-optimal: Publisher offers TRANSIENT_LOCAL (latched), but Subscription requested VOLATILE. "
            "Late-joining subscriber will NOT receive previously published messages until a new one is sent."
        )
        recommendations.append(
            "Set subscription durability to TRANSIENT_LOCAL to receive the last published message immediately on connect."
        )
        details["durability"] = "SUBOPTIMAL (Late subscriber miss)"
    else:
        details["durability"] = "COMPATIBLE"

    # 3. Deadline check
    if subscription_qos.deadline_sec is not None and publisher_qos.deadline_sec is not None:
        if publisher_qos.deadline_sec > subscription_qos.deadline_sec:
            issues.append(
                f"Deadline Incompatibility: Publisher deadline ({publisher_qos.deadline_sec}s) > "
                f"Subscription deadline ({subscription_qos.deadline_sec}s)."
            )
            recommendations.append("Ensure publisher can publish at least as fast as subscription expects.")
            details["deadline"] = "INCOMPATIBLE"
        else:
            details["deadline"] = "COMPATIBLE"

    is_compatible = not any("INCOMPATIBLE" in status for status in details.values())
    return QoSCheckResult(
        is_compatible=is_compatible,
        issues=issues,
        recommendations=recommendations,
        details=details,
    )
