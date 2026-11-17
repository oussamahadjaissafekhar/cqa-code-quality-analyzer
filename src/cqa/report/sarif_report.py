"""SARIF 2.1.0 output for GitHub code scanning.

Mapping (spec §5.4):
* ``ruleId`` <- ``finding.rule_id``
* ``level`` <- critical/high = error, medium = warning, low/info = note
* ``partialFingerprints["cqa/v1"]`` <- finding fingerprint
"""

from __future__ import annotations

import json

from ..models import AnalysisResult, Finding, Severity

SARIF_SCHEMA = "https://json.schemastore.org/sarif-2.1.0.json"
LEVEL_BY_SEVERITY = {
    Severity.CRITICAL: "error",
    Severity.HIGH: "error",
    Severity.MEDIUM: "warning",
    Severity.LOW: "note",
    Severity.INFO: "note",
}


def _rule_descriptor(rule_id: str, help_uri: str | None) -> dict[str, object]:
    descriptor: dict[str, object] = {
        "id": rule_id,
        "name": rule_id,
        "shortDescription": {"text": rule_id},
    }
    if help_uri:
        descriptor["helpUri"] = help_uri
    return descriptor


def _result(finding: Finding) -> dict[str, object]:
    from .redact import display_snippet

    region: dict[str, object] = {
        "startLine": finding.start_line,
        "startColumn": finding.start_col,
        "endLine": finding.end_line,
        "endColumn": finding.end_col,
    }
    result: dict[str, object] = {
        "ruleId": finding.rule_id,
        "level": LEVEL_BY_SEVERITY[finding.severity],
        "message": {"text": finding.message},
        "locations": [
            {
                "physicalLocation": {
                    "artifactLocation": {"uri": finding.path},
                    "region": region,
                }
            }
        ],
        "partialFingerprints": {"cqa/v1": finding.fingerprint},
        "properties": {
            "severity": finding.severity.value,
            "fingerprint": finding.fingerprint,
        },
    }
    snippet = display_snippet(finding)
    if snippet:
        region["snippet"] = {"text": snippet}
    return result


def render_sarif(result: AnalysisResult) -> str:
    rules: dict[str, dict[str, object]] = {}
    for finding in result.findings:
        rules.setdefault(finding.rule_id, _rule_descriptor(finding.rule_id, finding.help_uri))

    payload = {
        "$schema": SARIF_SCHEMA,
        "version": "2.1.0",
        "runs": [
            {
                "tool": {
                    "driver": {
                        "name": "cqa",
                        "informationUri": "https://github.com/cqa/cqa",
                        "version": result.tool.version,
                        "rules": [rules[key] for key in sorted(rules)],
                    }
                },
                "results": [_result(finding) for finding in result.findings],
            }
        ],
    }
    return json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
