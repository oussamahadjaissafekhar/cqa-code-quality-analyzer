"""Quality policy: score weights, complexity limits, and the CI gate."""

from __future__ import annotations

from ..models import ALL_SEVERITIES, SEVERITY_WEIGHTS, Finding, Severity
from ..security.severity import is_at_or_above

# Cyclomatic complexity thresholds for ``quality.complexity``.
COMPLEXITY_WARN = 10
COMPLEXITY_HIGH = 20

DEFAULT_FAIL_ON = "high"


def severity_counts(findings: list[Finding]) -> dict[str, int]:
    counts = {severity.value: 0 for severity in ALL_SEVERITIES}
    for finding in findings:
        counts[finding.severity.value] += 1
    return counts


def compute_score(findings: list[Finding]) -> int:
    """100 minus weighted severity counts, clamped to ``[0, 100]``."""

    deductions = sum(SEVERITY_WEIGHTS[finding.severity] for finding in findings)
    return max(0, min(100, 100 - deductions))


def exceeds_count_limits(
    counts: dict[str, int], limits: list[tuple[Severity, int | None]]
) -> bool:
    for severity, limit in limits:
        if limit is not None and counts.get(severity.value, 0) > limit:
            return True
    return False


def gate_failed(
    findings: list[Finding],
    fail_on: str,
    *,
    counts: dict[str, int] | None = None,
    limits: list[tuple[Severity, int | None]] | None = None,
) -> bool:
    """Decide whether CI should fail.

    A run fails when any finding is at/above ``fail_on`` or a configured count
    limit (``max_high`` etc.) is exceeded.
    """

    if any(is_at_or_above(finding.severity, fail_on) for finding in findings):
        return True
    return bool(counts is not None and limits and exceeds_count_limits(counts, limits))
