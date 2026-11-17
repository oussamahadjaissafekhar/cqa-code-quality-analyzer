"""Quality metrics: complexity findings and the 0-100 summary score.

The engine never mutates parser facts. Complexity is a metric over the
``functions`` facts; the result is converted to a normal :class:`Finding` so the
gate, reports, baselines, and SARIF all treat it uniformly.
"""

from __future__ import annotations

from ..config import Config
from ..models import (
    Finding,
    ParsedFile,
    Severity,
    Summary,
    fingerprint,
)
from .thresholds import (
    COMPLEXITY_HIGH,
    COMPLEXITY_WARN,
    compute_score,
    gate_failed,
    severity_counts,
)

RULE_ID = "quality.complexity"
HELP_URI = f"https://cqa.local/rules/{RULE_ID}"


def complexity_findings(
    files: list[ParsedFile],
    config: Config,
    *,
    allow: set[str] | None = None,
    disabled: set[str] | None = None,
) -> list[Finding]:
    """Emit ``quality.complexity`` findings for functions over the threshold."""

    disabled_ids = set(config.rules.disable)
    override = config.rules.overrides.get(RULE_ID)
    if (allow is not None and RULE_ID not in allow) or RULE_ID in disabled_ids:
        return []
    if disabled and RULE_ID in disabled:
        return []
    if override and override.enabled is False:
        return []

    severity_override = override.severity if override and override.severity else None
    findings: list[Finding] = []

    for file in files:
        for function in file.facts.functions:
            if function.complexity <= COMPLEXITY_WARN:
                continue
            severity = severity_override or (
                Severity.MEDIUM if function.complexity >= COMPLEXITY_HIGH else Severity.LOW
            )
            findings.append(
                Finding(
                    rule_id=RULE_ID,
                    severity=severity,
                    message=(
                        f"Function {function.name}() has cyclomatic complexity "
                        f"{function.complexity} (threshold {COMPLEXITY_WARN})"
                    ),
                    path=file.path,
                    start_line=function.line,
                    start_col=1,
                    end_line=function.line,
                    end_col=2,
                    fingerprint=fingerprint(
                        RULE_ID, file.path, function.line, f"{function.name}:{function.complexity}"
                    ),
                    snippet=file.line_text(function.line).strip() or None,
                    help_uri=HELP_URI,
                )
            )
    return findings


def build_summary(
    findings: list[Finding],
    files_scanned: int,
    config: Config,
    fail_on: str,
) -> Summary:
    """Compute counts, score, and the gate decision over *all* findings."""

    counts = severity_counts(findings)
    thresholds = config.thresholds
    limits = [(severity, thresholds.max_for(severity)) for severity in Severity]
    failed = gate_failed(findings, fail_on, counts=counts, limits=limits)
    return Summary(
        files_scanned=files_scanned,
        findings=len(findings),
        by_severity=counts,
        score=compute_score(findings),
        truncated=False,
        failed=failed,
    )


__all__ = [
    "COMPLEXITY_HIGH",
    "COMPLEXITY_WARN",
    "complexity_findings",
    "build_summary",
    "compute_score",
    "severity_counts",
]
