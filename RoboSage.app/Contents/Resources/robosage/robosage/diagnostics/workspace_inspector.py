"""
ROS 2 Environment & Workspace Diagnostic Inspector.
Inspects ROS_DISTRO, RMW_IMPLEMENTATION, colcon workspace structure,
and checks ROS 2 environment consistency.
"""

from dataclasses import dataclass, field
import os
from pathlib import Path
import shutil
import subprocess
from typing import Dict, List, Optional


@dataclass
class ROS2EnvironmentReport:
    ros_distro: Optional[str]
    ros_domain_id: str
    rmw_implementation: Optional[str]
    colcon_available: bool
    ros2_cli_available: bool
    workspace_root: Optional[str]
    packages_found: List[str]
    warnings: List[str]
    recommendations: List[str]


class WorkspaceInspector:
    """Inspects the local system and workspace for ROS 2 configuration issues."""

    @classmethod
    def inspect(cls, target_path: Optional[str] = None) -> ROS2EnvironmentReport:
        ros_distro = os.environ.get("ROS_DISTRO")
        ros_domain_id = os.environ.get("ROS_DOMAIN_ID", "0 (default)")
        rmw = os.environ.get("RMW_IMPLEMENTATION")

        colcon_avail = shutil.which("colcon") is not None
        ros2_avail = shutil.which("ros2") is not None

        # Search for workspace root (look for src/ directory and package.xml)
        search_dir = Path(target_path or os.getcwd()).resolve()
        ws_root = None
        packages = []

        curr = search_dir
        while curr != curr.parent:
            if (curr / "src").is_dir() and ((curr / "build").is_dir() or (curr / "install").is_dir() or (curr / "src").glob("*/package.xml")):
                ws_root = str(curr)
                break
            curr = curr.parent

        if not ws_root and (search_dir / "src").is_dir():
            ws_root = str(search_dir)

        # Find packages in workspace or current dir
        root_to_scan = Path(ws_root) if ws_root else search_dir
        for p in root_to_scan.glob("**/package.xml"):
            # skip build/install
            if not any(part in ("build", "install", ".venv") for part in p.parts):
                packages.append(p.parent.name)

        warnings = []
        recommendations = []

        if not ros_distro:
            warnings.append("No active ROS 2 environment detected in current shell (`ROS_DISTRO` is unset).")
            recommendations.append("Source your ROS 2 installation (e.g. `source /opt/ros/humble/setup.bash` or local install).")

        if not colcon_avail:
            warnings.append("`colcon` build tool was not found in PATH.")
            recommendations.append("Install colcon via `pip install -U colcon-common-extensions` or distro apt package.")

        if rmw is None:
            recommendations.append("Default RMW is active. For high-frequency sensor streams, consider `rmw_cyclonedds_cpp`.")

        return ROS2EnvironmentReport(
            ros_distro=ros_distro,
            ros_domain_id=ros_domain_id,
            rmw_implementation=rmw,
            colcon_available=colcon_avail,
            ros2_cli_available=ros2_avail,
            workspace_root=ws_root,
            packages_found=packages,
            warnings=warnings,
            recommendations=recommendations,
        )
