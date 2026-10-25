"""
Robotics Memory Layer and Conversation Continuation Manager for AOUL Copilot.

Provides:
1. RoboticsMemoryLayer: Persistent structured working memory for robot profile,
   discovered safety loopholes, active parameters, and domain constraints.
2. ConversationThread: Individual conversational thread with multi-turn history.
3. ConversationManager: Session manager for multiple conversation tabs/threads,
   continuation summaries, and memory layer orchestration.
"""

from dataclasses import asdict, dataclass, field
import json
import os
import re
import time
from typing import Any, Dict, List, Optional
import uuid

from robosage.llm.provider import ChatMessage


@dataclass
class RobotProfile:
    name: str = "Autonomous Ground Platform"
    platform_type: str = "Differential Drive (2WD)"
    ros_distro: str = "ROS 2 Humble / Jazzy"
    rmw_implementation: str = "rmw_cyclonedds_cpp"
    sensors: List[str] = field(default_factory=lambda: ["2D LiDAR (/scan)", "IMU (/imu/data)", "Wheel Odometry (/odom)"])
    actuators: List[str] = field(default_factory=lambda: ["Base Motor Drives (/cmd_vel)", "Emergency Brake Relay"])

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class RoboticsMemoryLayer:
    """
    Structured working memory holding long-term facts, robot specifications,
    and discovered issues across the multi-turn session.
    """
    robot_profile: RobotProfile = field(default_factory=RobotProfile)
    working_parameters: Dict[str, str] = field(default_factory=lambda: {
        "max_linear_velocity": "1.2 m/s",
        "max_angular_velocity": "1.5 rad/s",
        "watchdog_timeout_sec": "0.5s",
        "estop_zero_cmd_vel": "True",
        "qos_sensor_profile": "BEST_EFFORT / SensorDataQoS",
    })
    safety_constraints: List[str] = field(default_factory=lambda: [
        "Enforce zero-velocity publishing on shutdown / SIGINT",
        "Filter NaN/Inf on incoming sensor streams before math calculations",
        "Use asynchronous service calls to avoid SingleThreadedExecutor deadlocks",
    ])
    discovered_issues: List[Dict[str, Any]] = field(default_factory=list)
    custom_notes: List[str] = field(default_factory=list)

    def extract_from_text(self, user_text: str, assistant_reply: str = ""):
        """Heuristically extracts robotics platform facts and parameters from conversational turns."""
        combined = f"{user_text}\n{assistant_reply}"
        lower = combined.lower()

        # 1. ROS Distro extraction
        for distro in ["jazzy", "humble", "iron", "foxy", "galactic", "noetic", "rolling"]:
            if distro in lower:
                self.robot_profile.ros_distro = f"ROS 2 {distro.capitalize()}" if distro != "noetic" else "ROS 1 Noetic"
                break

        # 2. RMW extraction
        if "cyclone" in lower:
            self.robot_profile.rmw_implementation = "rmw_cyclonedds_cpp"
        elif "fastdds" in lower or "fastrtps" in lower:
            self.robot_profile.rmw_implementation = "rmw_fastrtps_cpp"
        elif "zenoh" in lower:
            self.robot_profile.rmw_implementation = "rmw_zenoh_cpp"

        # 3. Platform type extraction
        if "diff drive" in lower or "differential drive" in lower:
            self.robot_profile.platform_type = "Differential Drive"
        elif "ackermann" in lower or "car-like" in lower or "steer" in lower:
            self.robot_profile.platform_type = "Ackermann Steering"
        elif "mecanum" in lower or "omni" in lower:
            self.robot_profile.platform_type = "Omnidirectional (Mecanum)"
        elif "arm" in lower or "manipulator" in lower or "dof" in lower:
            self.robot_profile.platform_type = "Robotic Manipulator / Arm"
        elif "quadruped" in lower or "legged" in lower:
            self.robot_profile.platform_type = "Legged / Quadruped"

        # 4. Parameters extraction (e.g. "speed = 2.0", "velocity: 1.5", "timeout 0.3")
        param_patterns = [
            r'(max(?:imum)?_?(?:linear_)?velocity|speed)\s*[:=]\s*([0-9.]+\s*(?:m/s)?)',
            r'(max(?:imum)?_?angular_velocity|turn_rate)\s*[:=]\s*([0-9.]+\s*(?:rad/s)?)',
            r'(watchdog_?timeout|timeout)\s*[:=]\s*([0-9.]+\s*s?)',
            r'(wheel_?(?:radius|diameter))\s*[:=]\s*([0-9.]+\s*(?:m|cm)?)',
        ]
        for pat in param_patterns:
            m = re.search(pat, combined, re.IGNORECASE)
            if m:
                key = m.group(1).lower().replace(" ", "_")
                val = m.group(2).strip()
                self.working_parameters[key] = val

        # 5. Sensor / Actuator topic detection
        topics = re.findall(r'(/[\w/-]+)', combined)
        for t in topics:
            if any(t.startswith(p) for p in ["/cmd_vel", "/motor", "/drive", "/joint_traj"]):
                if t not in self.robot_profile.actuators:
                    self.robot_profile.actuators.append(f"Actuator topic ({t})")
            elif any(t.startswith(p) for p in ["/scan", "/imu", "/odom", "/camera", "/pointcloud", "/tf"]):
                if t not in self.robot_profile.sensors:
                    self.robot_profile.sensors.append(f"Sensor topic ({t})")

    def record_issue(self, title: str, severity: str, file_path: str = "", fix: str = ""):
        """Records a detected safety loophole or runtime diagnostic issue."""
        for item in self.discovered_issues:
            if item.get("title") == title:
                return
        self.discovered_issues.append({
            "title": title,
            "severity": severity,
            "file_path": file_path,
            "fix": fix,
            "timestamp": time.time(),
        })

    def get_system_memory_context(self) -> str:
        """Produces a compact, structured Markdown prompt injection of working memory."""
        lines = [
            "### [AOUL Working Memory Layer]",
            f"- **Active Platform:** {self.robot_profile.name} ({self.robot_profile.platform_type})",
            f"- **ROS & Middleware:** {self.robot_profile.ros_distro} | {self.robot_profile.rmw_implementation}",
        ]
        if self.working_parameters:
            param_str = ", ".join(f"`{k}: {v}`" for k, v in list(self.working_parameters.items())[:5])
            lines.append(f"- **Key Parameters:** {param_str}")
        if self.discovered_issues:
            recent_issues = ", ".join(f"`{i.get('title')}`" for i in self.discovered_issues[-3:])
            lines.append(f"- **Active Discovered Issues:** {recent_issues}")
        if self.safety_constraints:
            constraints_str = "; ".join(self.safety_constraints[:3])
            lines.append(f"- **Safety Invariants:** {constraints_str}")

        return "\n".join(lines)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "robot_profile": self.robot_profile.to_dict(),
            "working_parameters": self.working_parameters,
            "safety_constraints": self.safety_constraints,
            "discovered_issues": self.discovered_issues,
            "custom_notes": self.custom_notes,
        }

    def update_from_dict(self, data: Dict[str, Any]):
        if "robot_profile" in data:
            rp = data["robot_profile"]
            self.robot_profile.name = rp.get("name", self.robot_profile.name)
            self.robot_profile.platform_type = rp.get("platform_type", self.robot_profile.platform_type)
            self.robot_profile.ros_distro = rp.get("ros_distro", self.robot_profile.ros_distro)
            self.robot_profile.rmw_implementation = rp.get("rmw_implementation", self.robot_profile.rmw_implementation)
            if "sensors" in rp and isinstance(rp["sensors"], list):
                self.robot_profile.sensors = rp["sensors"]
            if "actuators" in rp and isinstance(rp["actuators"], list):
                self.robot_profile.actuators = rp["actuators"]
        if "working_parameters" in data and isinstance(data["working_parameters"], dict):
            self.working_parameters.update(data["working_parameters"])
        if "safety_constraints" in data and isinstance(data["safety_constraints"], list):
            self.safety_constraints = data["safety_constraints"]
        if "custom_notes" in data and isinstance(data["custom_notes"], list):
            self.custom_notes = data["custom_notes"]


@dataclass
class ConversationThread:
    """A distinct conversational session thread in the AI Copilot."""
    id: str
    title: str = "New Conversation"
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    messages: List[ChatMessage] = field(default_factory=list)
    continuation_summary: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    def add_message(self, role: str, content: str):
        self.messages.append(ChatMessage(role=role, content=content))
        self.updated_at = time.time()
        # Auto-generate dynamic thread title from first user message
        if self.title in ("New Conversation", "New Chat", "") and role == "user":
            clean = re.sub(r'[\r\n]+', ' ', content).strip()
            # Truncate to a snappy ~30 character title
            if len(clean) > 35:
                words = clean.split()
                clean = " ".join(words[:5]) + "..."
            self.title = clean[:38] if clean else "Robotics Chat"

    def get_messages_for_llm(self, max_recent: int = 8) -> List[ChatMessage]:
        """
        Returns messages tailored for LLM context window.
        If conversation is long, prepends the continuation summary.
        """
        if len(self.messages) <= max_recent:
            return list(self.messages)

        recent = self.messages[-max_recent:]
        if self.continuation_summary:
            summary_msg = ChatMessage(
                role="system",
                content=f"[Conversation History Continuation Summary]:\n{self.continuation_summary}"
            )
            return [summary_msg] + recent
        return recent

    def update_summary_if_needed(self):
        """Builds a running conversation continuation summary if thread length grows."""
        if len(self.messages) > 10 and not self.continuation_summary:
            # Condense older messages
            older_turns = self.messages[:-6]
            bullet_points = []
            for m in older_turns:
                snippet = m.content.strip().split("\n")[0][:100]
                bullet_points.append(f"- {m.role.capitalize()}: {snippet}")
            self.continuation_summary = "\n".join(bullet_points[:6])

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "title": self.title,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "turn_count": len(self.messages),
            "continuation_summary": self.continuation_summary,
            "messages": [{"role": m.role, "content": m.content} for m in self.messages],
        }


class ConversationManager:
    """
    Orchestrates conversation threads and active working memory.
    Ensures persistent multi-turn continuation and easy thread switching.
    """
    def __init__(self):
        self.threads: Dict[str, ConversationThread] = {}
        self.active_thread_id: str = "default_thread"
        self.memory_layer: RoboticsMemoryLayer = RoboticsMemoryLayer()
        # Initialize default thread
        self.get_or_create_thread(self.active_thread_id, title="Main Robotics Session")

    def get_or_create_thread(self, thread_id: Optional[str] = None, title: Optional[str] = None) -> ConversationThread:
        if not thread_id:
            thread_id = f"thread_{int(time.time())}_{uuid.uuid4().hex[:6]}"
        if thread_id not in self.threads:
            self.threads[thread_id] = ConversationThread(
                id=thread_id,
                title=title or "New Conversation",
            )
        return self.threads[thread_id]

    def create_thread(self, title: str = "New Conversation") -> ConversationThread:
        new_id = f"thread_{int(time.time())}_{uuid.uuid4().hex[:6]}"
        thread = ConversationThread(id=new_id, title=title)
        self.threads[new_id] = thread
        self.active_thread_id = new_id
        return thread

    def switch_thread(self, thread_id: str) -> Optional[ConversationThread]:
        if thread_id in self.threads:
            self.active_thread_id = thread_id
            return self.threads[thread_id]
        return None

    def rename_thread(self, thread_id: str, new_title: str) -> bool:
        if thread_id in self.threads:
            self.threads[thread_id].title = new_title.strip() or "Untitled"
            return True
        return False

    def delete_thread(self, thread_id: str) -> bool:
        if thread_id in self.threads:
            del self.threads[thread_id]
            if self.active_thread_id == thread_id:
                if self.threads:
                    self.active_thread_id = next(iter(self.threads.keys()))
                else:
                    self.create_thread("Main Robotics Session")
            return True
        return False

    def clear_thread(self, thread_id: str) -> bool:
        if thread_id in self.threads:
            self.threads[thread_id].messages.clear()
            self.threads[thread_id].continuation_summary = None
            self.threads[thread_id].updated_at = time.time()
            return True
        return False

    def list_threads(self) -> List[Dict[str, Any]]:
        result = []
        for tid, t in sorted(self.threads.items(), key=lambda kv: kv[1].updated_at, reverse=True):
            last_msg = t.messages[-1].content[:60] if t.messages else "No messages yet"
            result.append({
                "id": tid,
                "title": t.title,
                "created_at": t.created_at,
                "updated_at": t.updated_at,
                "turn_count": len(t.messages),
                "is_active": (tid == self.active_thread_id),
                "preview": last_msg,
            })
        return result

    def add_turn(self, thread_id: str, user_text: str, assistant_reply: str):
        thread = self.get_or_create_thread(thread_id)
        thread.add_message("user", user_text)
        thread.add_message("assistant", assistant_reply)
        thread.update_summary_if_needed()
        self.active_thread_id = thread_id
        # Update shared working memory layer
        self.memory_layer.extract_from_text(user_text, assistant_reply)
