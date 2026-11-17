"""Severity helpers shared by the engine, threshold gate, and reports."""

from __future__ import annotations

from ..models import SEVERITY_ORDER, Finding, Severity

FAIL_THRESHOLDS = ("critical", "high", "medium", "low", "info", "never")


def is_at_or_above(severity: Severity, threshold: str) -> bool:
    """Return True when ``severity`` is at least as urgent as ``threshold``."""

    if threshold == "never":
        return False
    try:
        boundary = Severity(threshold)
    except ValueError:
        return False
    return SEVERITY_ORDER[severity] <= SEVERITY_ORDER[boundary]


def findings_failing(findings: list[Finding], threshold: str) -> list[Finding]:
    return [finding for finding in findings if is_at_or_above(finding.severity, threshold)]


def worst_severity(findings: list[Finding]) -> Severity | None:
    if not findings:
        return None
    return min(findings, key=lambda finding: SEVERITY_ORDER[finding.severity]).severity
