"""
OASIS SARIF (Static Analysis Results Interchange Format) v2.1.0 Exporter.
Integrates AOUL safety audit findings into GitHub Code Scanning, GitLab Security,
and Space ROS CI/CD compliance gates.
"""

from typing import Any, Dict, List
import json


class SarifExporter:
    """Exports AOUL static analysis findings into standardized SARIF v2.1.0 JSON."""

    SCHEMA_URI = "https://raw.githubusercontent.com/oasis-tcs/sarif-spec/master/Schemata/sarif-schema-2.1.0.json"
    VERSION = "2.1.0"
    TOOL_NAME = "AOUL Robotics Safety Auditor"
    TOOL_VERSION = "2.0.0"

    @classmethod
    def convert_findings_to_sarif(
        cls,
        findings: List[Dict[str, Any]],
        target_file: str = "src/robot_node.py",
    ) -> Dict[str, Any]:
        rules: Dict[str, Dict[str, Any]] = {}
        results: List[Dict[str, Any]] = []

        for f in findings:
            rule_id = f.get("loophole_type", "ROBOTICS_SAFETY_HAZARD")
            severity_str = f.get("severity", "WARNING").upper()

            # Map AOUL severity to SARIF level
            sarif_level = (
                "error" if severity_str in ("CRITICAL", "HIGH")
                else "warning" if severity_str in ("MEDIUM", "WARNING")
                else "note"
            )

            # Register rule if not already present
            if rule_id not in rules:
                rules[rule_id] = {
                    "id": rule_id,
                    "name": f.get("title", rule_id),
                    "shortDescription": {"text": f.get("title", rule_id)},
                    "fullDescription": {
                        "text": f"{f.get('description', '')}\nHazard: {f.get('impact', '')}\nFix: {f.get('recommended_fix', '')}"
                    },
                    "defaultConfiguration": {"level": sarif_level},
                    "properties": {
                        "tags": ["robotics", "ros2", "safety-critical", "concurrency"],
                        "precision": "high",
                    },
                }

            line_number = int(f.get("line_number") or 1)

            results.append({
                "ruleId": rule_id,
                "level": sarif_level,
                "message": {
                    "text": f"{f.get('title')}: {f.get('description')}\nImpact: {f.get('impact')}\nRecommended Fix: {f.get('recommended_fix')}"
                },
                "locations": [
                    {
                        "physicalLocation": {
                            "artifactLocation": {"uri": target_file},
                            "region": {
                                "startLine": max(1, line_number),
                                "startColumn": 1,
                            },
                        }
                    }
                ],
            })

        sarif_document = {
            "$schema": cls.SCHEMA_URI,
            "version": cls.VERSION,
            "runs": [
                {
                    "tool": {
                        "driver": {
                            "name": cls.TOOL_NAME,
                            "version": cls.TOOL_VERSION,
                            "informationUri": "https://github.com/aoul-robotics/aoul",
                            "rules": list(rules.values()),
                        }
                    },
                    "results": results,
                }
            ],
        }

        return sarif_document

    @classmethod
    def to_json_str(cls, findings: List[Dict[str, Any]], target_file: str = "src/robot_node.py") -> str:
        doc = cls.convert_findings_to_sarif(findings, target_file)
        return json.dumps(doc, indent=2)
