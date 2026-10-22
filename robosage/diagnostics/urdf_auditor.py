"""
URDF & Physics Integrity Auditor.
Statically analyzes Robot Description XML (URDF/Xacro) for physical impossibilities,
negative or zero diagonal moments of inertia, triangle inequality violations,
missing collision geometries, and invalid joint limits.
"""

from dataclasses import dataclass
import math
from typing import Any, Dict, List, Optional
import xml.etree.ElementTree as ET


@dataclass
class UrdfFinding:
    severity: str  # "CRITICAL", "HIGH", "WARNING", "INFO"
    title: str
    element_type: str  # "link", "joint", "material", "robot"
    element_name: str
    description: str
    physics_impact: str
    recommended_fix: str
    line_number: Optional[int] = None


class UrdfAuditor:
    """Performs static physical and simulation audits on URDF robot descriptions."""

    @classmethod
    def audit_urdf_text(cls, xml_content: str) -> Dict[str, Any]:
        findings: List[UrdfFinding] = []
        links_data: List[Dict[str, Any]] = []
        joints_data: List[Dict[str, Any]] = []

        try:
            root = ET.fromstring(xml_content.strip())
        except Exception as e:
            return {
                "valid": False,
                "error": f"Malformed URDF XML: {e}",
                "robot_name": "unknown",
                "findings": [
                    {
                        "severity": "CRITICAL",
                        "title": "URDF XML Syntax Error",
                        "element_type": "robot",
                        "element_name": "root",
                        "description": str(e),
                        "physics_impact": "Parser cannot load model; robot cannot be spawned into Gazebo or MoveIt.",
                        "recommended_fix": "Fix XML syntax errors and unclosed tags.",
                    }
                ],
                "stats": {"links": 0, "joints": 0, "total_mass_kg": 0.0},
            }

        robot_name = root.attrib.get("name", "robot")
        total_mass = 0.0

        # Step 1: Inspect Links
        link_names = set()
        for link in root.findall("link"):
            name = link.attrib.get("name", "unnamed_link")
            link_names.add(name)

            mass_val = 0.0
            inertial = link.find("inertial")
            visual = link.find("visual")
            collision = link.find("collision")

            # Check Mass
            if inertial is not None:
                mass_elem = inertial.find("mass")
                if mass_elem is not None:
                    try:
                        mass_val = float(mass_elem.attrib.get("value", 0.0))
                    except ValueError:
                        mass_val = 0.0

                if mass_val < 0.0:
                    findings.append(UrdfFinding(
                        severity="CRITICAL",
                        title=f"Negative Mass on Link '{name}'",
                        element_type="link",
                        element_name=name,
                        description=f"Link '{name}' specifies a negative mass ({mass_val} kg).",
                        physics_impact="Physics engines (ODE, Bullet, PhysX) will produce NaN forces and crash the simulation instantly.",
                        recommended_fix="Set mass to a positive value > 0.0.",
                    ))
                elif mass_val == 0.0 and (visual is not None or collision is not None):
                    # Zero mass is fine for world/base_footprint, but hazardous if dynamic
                    if name not in ("world", "base_footprint", "map", "odom"):
                        findings.append(UrdfFinding(
                            severity="WARNING",
                            title=f"Zero Mass Dynamic Link '{name}'",
                            element_type="link",
                            element_name=name,
                            description=f"Link '{name}' has geometry but zero mass.",
                            physics_impact="May be treated as a static obstacle or merged unexpectedly by physics solvers.",
                            recommended_fix="Assign realistic mass > 0.001 kg if this link moves.",
                        ))

                total_mass += max(0.0, mass_val)

                # Check Inertia Tensor
                inertia_elem = inertial.find("inertia")
                if inertia_elem is not None:
                    try:
                        ixx = float(inertia_elem.attrib.get("ixx", 0.0))
                        iyy = float(inertia_elem.attrib.get("iyy", 0.0))
                        izz = float(inertia_elem.attrib.get("izz", 0.0))
                        ixy = float(inertia_elem.attrib.get("ixy", 0.0))
                        ixz = float(inertia_elem.attrib.get("ixz", 0.0))
                        iyz = float(inertia_elem.attrib.get("iyz", 0.0))

                        # Check 1: Diagonal moments must be strictly positive for non-zero mass
                        if mass_val > 0.0 and (ixx <= 0.0 or iyy <= 0.0 or izz <= 0.0):
                            findings.append(UrdfFinding(
                                severity="CRITICAL",
                                title=f"Non-Positive Diagonal Moment of Inertia on '{name}'",
                                element_type="link",
                                element_name=name,
                                description=f"Diagonal inertia components must be positive: ixx={ixx}, iyy={iyy}, izz={izz}.",
                                physics_impact="Rotational equations of motion cannot be solved; causes simulation explosions (exploding robot effect).",
                                recommended_fix="Ensure ixx, iyy, izz > 0. Use formulas for cylinder, box, or sphere moments.",
                            ))

                        # Check 2: Triangle Inequality for Physical Realizability:
                        # For any real physical body: Ixx + Iyy >= Izz, Iyy + Izz >= Ixx, Ixx + Izz >= Iyy
                        if mass_val > 0.0 and ixx > 0.0 and iyy > 0.0 and izz > 0.0:
                            eps = 1e-7
                            if (ixx + iyy < izz - eps) or (iyy + izz < ixx - eps) or (ixx + izz < iyy - eps):
                                findings.append(UrdfFinding(
                                    severity="HIGH",
                                    title=f"Triangle Inequality Violation in Inertia Tensor on '{name}'",
                                    element_type="link",
                                    element_name=name,
                                    description=(
                                        f"Inertia components violate physical triangle inequality: "
                                        f"ixx={ixx:.4f}, iyy={iyy:.4f}, izz={izz:.4f}. "
                                        f"(Ixx+Iyy must be >= Izz, Iyy+Izz >= Ixx, Ixx+Izz >= Iyy)."
                                    ),
                                    physics_impact="Physically impossible mass distribution. Can cause unstable oscillations during fast rotations or control loops.",
                                    recommended_fix="Recompute the principal moments of inertia using CAD or proper bounding box formulas.",
                                ))

                    except ValueError:
                        findings.append(UrdfFinding(
                            severity="CRITICAL",
                            title=f"Invalid Non-Numeric Inertia on Link '{name}'",
                            element_type="link",
                            element_name=name,
                            description="Inertia attributes must be valid floating point numbers.",
                            physics_impact="URDF parser fails.",
                            recommended_fix="Provide valid floating-point numbers.",
                        ))

            # Check Missing Collision Geometry
            if visual is not None and collision is None:
                if name not in ("world", "base_footprint", "map", "odom"):
                    findings.append(UrdfFinding(
                        severity="WARNING",
                        title=f"Missing Collision Geometry on Link '{name}'",
                        element_type="link",
                        element_name=name,
                        description=f"Link '{name}' has visual rendering but lacks a `<collision>` element.",
                        physics_impact="The robot will visually exist but will pass through objects without colliding in simulation.",
                        recommended_fix="Add `<collision>` with simplified box, cylinder, or mesh geometry.",
                    ))

            links_data.append({
                "name": name,
                "mass_kg": round(mass_val, 4),
                "has_visual": visual is not None,
                "has_collision": collision is not None,
                "has_inertial": inertial is not None,
            })

        # Step 2: Inspect Joints
        child_links = set()
        for joint in root.findall("joint"):
            j_name = joint.attrib.get("name", "unnamed_joint")
            j_type = joint.attrib.get("type", "fixed")

            parent = joint.find("parent")
            child = joint.find("child")
            p_name = parent.attrib.get("link", "") if parent is not None else ""
            c_name = child.attrib.get("link", "") if child is not None else ""

            if c_name:
                child_links.add(c_name)

            # Check parent/child link existence
            if p_name and p_name not in link_names:
                findings.append(UrdfFinding(
                    severity="CRITICAL",
                    title=f"Non-Existent Parent Link '{p_name}' in Joint '{j_name}'",
                    element_type="joint",
                    element_name=j_name,
                    description=f"Joint specifies parent='{p_name}', but no link named '{p_name}' is declared.",
                    physics_impact="URDF graph broken; tf2 / robot_state_publisher fails to construct transform tree.",
                    recommended_fix=f"Declare link '{p_name}' or fix spelling.",
                ))

            if c_name and c_name not in link_names:
                findings.append(UrdfFinding(
                    severity="CRITICAL",
                    title=f"Non-Existent Child Link '{c_name}' in Joint '{j_name}'",
                    element_type="joint",
                    element_name=j_name,
                    description=f"Joint specifies child='{c_name}', but no link named '{c_name}' is declared.",
                    physics_impact="URDF graph broken; kinematic chain disconnected.",
                    recommended_fix=f"Declare link '{c_name}' or fix spelling.",
                ))

            # Check Joint Limits for Revolute & Prismatic
            limit = joint.find("limit")
            if j_type in ("revolute", "prismatic"):
                if limit is None:
                    findings.append(UrdfFinding(
                        severity="CRITICAL",
                        title=f"Missing `<limit>` on {j_type.title()} Joint '{j_name}'",
                        element_type="joint",
                        element_name=j_name,
                        description=f"Joint '{j_name}' is of type '{j_type}' but does not declare a `<limit>` tag.",
                        physics_impact="Robot controllers and MoveIt trajectory planners cannot plan without limits.",
                        recommended_fix="Specify `<limit lower='...' upper='...' effort='...' velocity='...'/>`.",
                    ))
                else:
                    effort = limit.attrib.get("effort")
                    velocity = limit.attrib.get("velocity")
                    lower = limit.attrib.get("lower")
                    upper = limit.attrib.get("upper")

                    if effort is None or float(effort or 0) <= 0:
                        findings.append(UrdfFinding(
                            severity="HIGH",
                            title=f"Missing or Zero Effort Limit on Joint '{j_name}'",
                            element_type="joint",
                            element_name=j_name,
                            description=f"Effort limit is '{effort}'. Joint cannot produce torque.",
                            physics_impact="Simulated motors cannot apply effort to overcome gravity or friction.",
                            recommended_fix="Set effort to maximum motor torque (e.g. effort='30.0').",
                        ))

                    if velocity is None or float(velocity or 0) <= 0:
                        findings.append(UrdfFinding(
                            severity="HIGH",
                            title=f"Missing or Zero Velocity Limit on Joint '{j_name}'",
                            element_type="joint",
                            element_name=j_name,
                            description=f"Velocity limit is '{velocity}'. Joint cannot rotate.",
                            physics_impact="Trajectory generators will clamp commanded velocity to 0.",
                            recommended_fix="Set velocity to realistic actuator max velocity (e.g. velocity='2.5').",
                        ))

                    if lower is not None and upper is not None:
                        try:
                            l_val = float(lower)
                            u_val = float(upper)
                            if l_val >= u_val:
                                findings.append(UrdfFinding(
                                    severity="CRITICAL",
                                    title=f"Inverted Joint Limits on '{j_name}' (lower >= upper)",
                                    element_type="joint",
                                    element_name=j_name,
                                    description=f"Joint limit lower ({l_val}) >= upper ({u_val}).",
                                    physics_impact="Joint is completely locked or MoveIt inverse kinematics fails.",
                                    recommended_fix="Ensure lower limit is strictly less than upper limit.",
                                ))
                        except ValueError:
                            pass

            joints_data.append({
                "name": j_name,
                "type": j_type,
                "parent": p_name,
                "child": c_name,
                "has_limit": limit is not None,
            })

        # Step 3: Check Kinematic Root Link
        root_candidates = link_names - child_links
        if len(root_candidates) == 0 and len(link_names) > 0:
            findings.append(UrdfFinding(
                severity="CRITICAL",
                title="Cyclic Kinematic Tree Detected",
                element_type="robot",
                element_name=robot_name,
                description="Every link is the child of another joint; no root link exists (kinematic cycle).",
                physics_impact="URDF supports only Directed Tree graphs without kinematic loops (closed chains must use transmission tags).",
                recommended_fix="Ensure exactly one base link (e.g. 'base_link') has no parent joint.",
            ))
        elif len(root_candidates) > 1:
            findings.append(UrdfFinding(
                severity="WARNING",
                title=f"Multiple Root Links Detected: {', '.join(sorted(root_candidates))}",
                element_type="robot",
                element_name=robot_name,
                description="Multiple disconnected link trees found in the same robot description.",
                physics_impact="Forms disconnected TF trees unless connected by a joint.",
                recommended_fix="Connect disconnected roots to 'base_link' or 'world' via fixed joints.",
            ))

        serialized_findings = [
            {
                "severity": f.severity,
                "title": f.title,
                "element_type": f.element_type,
                "element_name": f.element_name,
                "description": f.description,
                "physics_impact": f.physics_impact,
                "recommended_fix": f.recommended_fix,
            }
            for f in findings
        ]

        return {
            "valid": True,
            "robot_name": robot_name,
            "total_findings": len(serialized_findings),
            "findings": serialized_findings,
            "stats": {
                "links": len(links_data),
                "joints": len(joints_data),
                "total_mass_kg": round(total_mass, 3),
                "root_link": list(root_candidates)[0] if root_candidates else "none",
            },
            "links": links_data,
            "joints": joints_data,
        }

    @classmethod
    def get_sample_urdfs(cls) -> Dict[str, Any]:
        """Provides verified sample URDFs for nominal and faulty test scenarios."""
        return {
            "nominal_arm": {
                "title": "Nominal 3-DOF Arm (Valid Physical Inertias & Limits)",
                "urdf": """<robot name="nominal_arm">
  <link name="base_link">
    <inertial>
      <mass value="5.0"/>
      <inertia ixx="0.05" ixy="0" ixz="0" iyy="0.05" iyz="0" izz="0.08"/>
    </inertial>
    <visual>
      <geometry><cylinder radius="0.15" length="0.2"/></geometry>
    </visual>
    <collision>
      <geometry><cylinder radius="0.15" length="0.2"/></geometry>
    </collision>
  </link>

  <link name="link1">
    <inertial>
      <mass value="2.5"/>
      <inertia ixx="0.08" ixy="0" ixz="0" iyy="0.08" iyz="0" izz="0.02"/>
    </inertial>
    <visual>
      <geometry><cylinder radius="0.06" length="0.5"/></geometry>
      <origin xyz="0 0 0.25" rpy="0 0 0"/>
    </visual>
    <collision>
      <geometry><cylinder radius="0.06" length="0.5"/></geometry>
      <origin xyz="0 0 0.25" rpy="0 0 0"/>
    </collision>
  </link>

  <joint name="joint1" type="revolute">
    <parent link="base_link"/>
    <child link="link1"/>
    <origin xyz="0 0 0.2" rpy="0 0 0"/>
    <axis xyz="0 0 1"/>
    <limit lower="-3.14" upper="3.14" effort="30.0" velocity="2.5"/>
  </joint>
</robot>"""
            },
            "faulty_inertias_amr": {
                "title": "Faulty Mobile Robot (Exploding Inertia, Inverted Limits & Missing Collision)",
                "urdf": """<robot name="hazardous_amr">
  <link name="base_link">
    <inertial>
      <mass value="15.0"/>
      <!-- Critical Loophole: Negative and Zero Diagonal Inertia -->
      <inertia ixx="-0.5" ixy="0" ixz="0" iyy="0.0" iyz="0" izz="1.2"/>
    </inertial>
    <visual>
      <geometry><box size="0.6 0.4 0.2"/></geometry>
    </visual>
    <!-- Warning Loophole: Missing Collision Geometry on Dynamic Chassis -->
  </link>

  <link name="wheel_left">
    <inertial>
      <mass value="1.5"/>
      <!-- Critical Loophole: Triangle Inequality Violation (0.01 + 0.01 < 0.5) -->
      <inertia ixx="0.01" ixy="0" ixz="0" iyy="0.01" iyz="0" izz="0.5"/>
    </inertial>
    <visual>
      <geometry><cylinder radius="0.1" length="0.05"/></geometry>
    </visual>
  </link>

  <joint name="wheel_left_joint" type="revolute">
    <parent link="base_link"/>
    <child link="wheel_left"/>
    <!-- Critical Loophole: Inverted joint limits (lower > upper) & 0 effort -->
    <limit lower="3.14" upper="-3.14" effort="0.0" velocity="0.0"/>
  </joint>
</robot>"""
            }
        }
