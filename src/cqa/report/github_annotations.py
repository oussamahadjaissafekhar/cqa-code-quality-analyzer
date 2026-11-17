"""GitHub Actions workflow commands (annotations).

Only escaped fields are printed. Snippets are intentionally omitted so secret
material never reaches workflow logs.
"""

from __future__ import annotations

from ..models import AnalysisResult, Severity

LEVEL_BY_SEVERITY = {
    Severity.CRITICAL: "error",
    Severity.HIGH: "error",
    Severity.MEDIUM: "warning",
    Severity.LOW: "notice",
    Severity.INFO: "notice",
}


def _escape_data(value: str) -> str:
    return value.replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")


def _escape_property(value: str) -> str:
    return _escape_data(value).replace(":", "%3A").replace(",", "%2C")


def render_github_annotations(result: AnalysisResult) -> str:
    lines: list[str] = []
    for finding in result.findings:
        level = LEVEL_BY_SEVERITY[finding.severity]
        properties = (
            f"file={_escape_property(finding.path)},"
            f"line={finding.start_line},"
            f"col={finding.start_col},"
            f"endLine={finding.end_line},"
            f"endColumn={finding.end_col},"
            f"title={_escape_property(finding.rule_id)}"
        )
        message = f"{finding.message} ({finding.rule_id})"
        if finding.help_uri:
            message += f" - {finding.help_uri}"
        lines.append(f"::{level} {properties}::{_escape_data(message)}")

    for error in result.errors:
        lines.append(
            f"::warning file={_escape_property(error.path)}::"
            f"{_escape_data(f'cqa {error.kind} error: {error.message}')}"
        )
    return "\n".join(lines) + ("\n" if lines else "")
