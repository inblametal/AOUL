"""
BehaviorTree.CPP v4 & Nav2 Autonomous Mission Visualizer & Safety Auditor.
Inspects Behavior Tree XMLs for blackboard key collisions, missing recovery fallbacks,
and infinite retry storms.
"""

from typing import Any, Dict, List, Optional
import xml.etree.ElementTree as ET


class BehaviorTreeAnalyzer:
    """Parses and audits BehaviorTree.CPP v4 XML trees."""

    CONTROL_NODES = {
        "Sequence", "Fallback", "ReactiveSequence", "ReactiveFallback",
        "Parallel", "IfThenElse", "Inverter", "RetryUntilSuccessful",
        "KeepRunningUntilFailure", "Repeat",
    }

    @classmethod
    def parse_and_audit_xml(cls, xml_content: str) -> Dict[str, Any]:
        findings = []
        node_count = 0
        control_node_count = 0
        action_node_count = 0
        blackboard_writes: Dict[str, List[str]] = {}
        blackboard_reads: Dict[str, List[str]] = {}

        try:
            root = ET.fromstring(xml_content.strip())
        except Exception as e:
            return {
                "valid": False,
                "error": f"Malformed Behavior Tree XML: {e}",
                "tree_json": None,
                "findings": [
                    {
                        "severity": "CRITICAL",
                        "title": "XML Parse Failure",
                        "description": str(e),
                        "impact": "Nav2 tree executor cannot load malformed XML.",
                        "fix": "Ensure all tags are properly closed and formatted."
                    }
                ],
                "stats": {"nodes": 0, "actions": 0, "controls": 0}
            }

        # Find main BehaviorTree definition
        bt_elem = root.find("BehaviorTree") if root.tag == "root" else root
        if bt_elem is None:
            # Check for direct tree
            bt_elem = root

        def traverse_node(elem: ET.Element, depth: int = 0) -> Dict[str, Any]:
            nonlocal node_count, control_node_count, action_node_count
            node_count += 1

            tag = elem.tag
            name = elem.attrib.get("name") or elem.attrib.get("ID") or tag
            node_type = "CONTROL" if tag in cls.CONTROL_NODES else "ACTION"

            if node_type == "CONTROL":
                control_node_count += 1
            else:
                action_node_count += 1

            # Track blackboard port usage
            for attr, val in elem.attrib.items():
                if val.startswith("{") and val.endswith("}"):
                    key = val[1:-1]
                    # Guess write if attribute name implies output
                    is_output = any(kw in attr.lower() for kw in ("out", "output", "result", "path", "goal"))
                    if is_output:
                        blackboard_writes.setdefault(key, []).append(f"{name} ({attr})")
                    else:
                        blackboard_reads.setdefault(key, []).append(f"{name} ({attr})")

            children = []
            for child in elem:
                if child.tag not in ("Metadata", "TreeNodesModel"):
                    children.append(traverse_node(child, depth + 1))

            return {
                "tag": tag,
                "name": name,
                "type": node_type,
                "depth": depth,
                "attributes": dict(elem.attrib),
                "children": children,
            }

        tree_json = traverse_node(bt_elem)

        # Audit Rule 1: Blackboard Write Conflicts / Race conditions
        for key, writers in blackboard_writes.items():
            if len(writers) > 1:
                findings.append({
                    "severity": "HIGH",
                    "title": f"Blackboard Port Write Contention on '{{{key}}}'",
                    "description": f"Multiple nodes write to blackboard key '{{{key}}}': {', '.join(writers)}.",
                    "impact": "Race condition if nodes execute concurrently or in parallel sequences.",
                    "fix": "Ensure blackboard keys have unique names or use atomic sub-trees.",
                })

        # Audit Rule 2: Root Fallback Completeness
        if tree_json.get("children"):
            top_node = tree_json["children"][0] if tree_json["tag"] in ("root", "BehaviorTree") else tree_json
            if top_node.get("tag") not in ("Fallback", "ReactiveFallback"):
                findings.append({
                    "severity": "MEDIUM",
                    "title": "Missing Top-Level Recovery Fallback",
                    "description": f"Root node is '{top_node.get('tag')}' instead of a 'Fallback' / 'RecoveryNode'.",
                    "impact": "If an action fails, the entire mission aborts immediately without triggering recovery behaviors (e.g. SpinRecovery, WaitRecovery).",
                    "fix": "Wrap main navigation sequences inside a Fallback or RecoveryNode."
                })

        # Audit Rule 3: Unbounded Retry Loops
        for elem in bt_elem.iter():
            if elem.tag == "RetryUntilSuccessful":
                num_attempts = elem.attrib.get("num_attempts", "-1")
                if num_attempts in ("-1", "0", ""):
                    findings.append({
                        "severity": "CRITICAL",
                        "title": "Infinite Retry Loop Trap",
                        "description": f"Node '{elem.attrib.get('name', 'Retry')}' has num_attempts='{num_attempts}'.",
                        "impact": "If hardware is stalled or path is blocked, robot will spin/retry infinitely without aborting or triggering E-Stop.",
                        "fix": "Set a bounded retry limit (e.g. num_attempts='3')."
                    })

        return {
            "valid": True,
            "tree_json": tree_json,
            "findings": findings,
            "stats": {
                "nodes": node_count,
                "actions": action_node_count,
                "controls": control_node_count,
                "blackboard_keys": len(set(list(blackboard_writes.keys()) + list(blackboard_reads.keys())))
            }
        }

    @classmethod
    def get_sample_trees(cls) -> Dict[str, Any]:
        """Provides preloaded Behavior Tree XML samples."""
        return {
            "nav2_nominal": {
                "title": "Nav2 Standard NavigateToPose with Recovery Tree",
                "xml": """<root main_tree_to_execute="MainTree">
  <BehaviorTree ID="MainTree">
    <RecoveryNode number_of_retries="6" name="NavigateRecovery">
      <PipelineSequence name="NavigateWithReplanning">
        <RateController hz="1.0">
          <ComputePathToPose goal="{goal}" path="{path}" planner_id="GridBased"/>
        </RateController>
        <FollowPath path="{path}" controller_id="FollowPath"/>
      </PipelineSequence>
      <ReactiveFallback name="RecoveryFallback">
        <GoalUpdated/>
        <RoundRobin name="RecoveryActions">
          <ClearEntireCostmap name="ClearLocalCostmap" service_name="local_costmap/clear_entirely"/>
          <Spin spin_dist="1.57" name="SpinRecovery"/>
          <Wait wait_duration="5" name="WaitRecovery"/>
          <BackUp backup_dist="0.3" backup_speed="0.1" name="BackupRecovery"/>
        </RoundRobin>
      </ReactiveFallback>
    </RecoveryNode>
  </BehaviorTree>
</root>"""
            },
            "faulty_tree": {
                "title": "Hazardous Tree (Blackboard Race Condition & Infinite Retry)",
                "xml": """<root main_tree_to_execute="MainTree">
  <BehaviorTree ID="MainTree">
    <Sequence name="UnprotectedMission">
      <Parallel threshold="2">
        <ComputePathToPose goal="{target}" path="{shared_path}"/>
        <OptimizeTrajectory input_path="{shared_path}" output_path="{shared_path}"/>
      </Parallel>
      <RetryUntilSuccessful num_attempts="-1" name="InfiniteSpin">
        <Spin spin_dist="3.14"/>
      </RetryUntilSuccessful>
      <FollowPath path="{shared_path}"/>
    </Sequence>
  </BehaviorTree>
</root>"""
            }
        }
