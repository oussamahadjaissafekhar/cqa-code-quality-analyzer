"""Quality policy: scoring, complexity findings, and the CI gate."""

from __future__ import annotations

from cqa.config import Config, RuleOverride, RulesConfig
from cqa.models import (
    ALL_SEVERITIES,
    FileFacts,
    Finding,
    FunctionFact,
    ParsedFile,
    Severity,
    Summary,
    fingerprint,
)
from cqa.quality.metrics import build_summary, complexity_findings
from cqa.quality.thresholds import (
    COMPLEXITY_HIGH,
    COMPLEXITY_WARN,
    compute_score,
    exceeds_count_limits,
    gate_failed,
    severity_counts,
)
from cqa.security.severity import findings_failing, is_at_or_above, worst_severity


def finding(severity: Severity, rule_id: str = "test.rule") -> Finding:
    return Finding(
        rule_id=rule_id,
        severity=severity,
        message="message",
        path="src/a.py",
        start_line=1,
        start_col=1,
        end_line=1,
        end_col=2,
        fingerprint=fingerprint(rule_id, "src/a.py", 1, "x"),
    )


def parsed(complexity: int, name: str = "f") -> ParsedFile:
    return ParsedFile(
        path="src/a.py",
        language="python",
        facts=FileFacts(functions=[FunctionFact(name=name, line=1, complexity=complexity)]),
        source=f"def {name}():\n    pass\n",
    )


def test_severity_helpers() -> None:
    findings = [
        finding(Severity.CRITICAL),
        finding(Severity.HIGH),
        finding(Severity.LOW),
    ]
    assert severity_counts(findings) == {
        "critical": 1,
        "high": 1,
        "medium": 0,
        "low": 1,
        "info": 0,
    }
    assert is_at_or_above(Severity.CRITICAL, "high") is True
    assert is_at_or_above(Severity.MEDIUM, "high") is False
    assert is_at_or_above(Severity.CRITICAL, "never") is False
    assert is_at_or_above(Severity.CRITICAL, "bogus") is False
    assert [item.severity for item in findings_failing(findings, "high")] == [
        Severity.CRITICAL,
        Severity.HIGH,
    ]
    assert worst_severity([]) is None
    assert worst_severity(findings) is Severity.CRITICAL


def test_compute_score_weights_and_clamps() -> None:
    assert compute_score([]) == 100
    assert compute_score([finding(Severity.CRITICAL)]) == 75
    assert compute_score([finding(Severity.HIGH)]) == 90
    assert compute_score([finding(Severity.MEDIUM)]) == 97
    assert compute_score([finding(Severity.LOW)]) == 99
    assert compute_score([finding(Severity.INFO)]) == 100
    assert compute_score([finding(Severity.CRITICAL)] * 5) == 0


def test_exceeds_count_limits() -> None:
    counts = {"critical": 1, "high": 2}
    assert exceeds_count_limits(counts, [(Severity.HIGH, 2)]) is False
    assert exceeds_count_limits(counts, [(Severity.HIGH, 1)]) is True
    assert exceeds_count_limits(counts, [(Severity.CRITICAL, None)]) is False
    assert exceeds_count_limits({}, [(Severity.CRITICAL, 0)]) is False


def test_gate_uses_severity_threshold_and_count_limits() -> None:
    high = [finding(Severity.HIGH)]
    assert gate_failed(high, "high") is True
    assert gate_failed(high, "critical") is False
    assert gate_failed(high, "never") is False
    assert gate_failed([], "info") is False

    assert gate_failed([], "high", counts={"high": 2}, limits=[(Severity.HIGH, 1)]) is True
    assert gate_failed([], "high", counts={"high": 1}, limits=[(Severity.HIGH, 1)]) is False
    assert gate_failed([], "high", counts={"high": 2}, limits=None) is False


def test_build_summary_mirrors_findings() -> None:
    config = Config(schema_version=1)
    findings = [finding(Severity.CRITICAL), finding(Severity.LOW)]
    summary = build_summary(findings, files_scanned=7, config=config, fail_on="high")

    assert isinstance(summary, Summary)
    assert summary.files_scanned == 7
    assert summary.findings == 2
    assert summary.by_severity["critical"] == 1
    assert summary.by_severity["low"] == 1
    assert summary.by_severity["info"] == 0
    assert summary.score == 74
    assert summary.truncated is False
    assert summary.failed is True


def test_build_summary_honours_count_limits() -> None:
    config = Config(schema_version=1)
    config.thresholds.max_medium = 1
    findings = [finding(Severity.MEDIUM), finding(Severity.MEDIUM)]
    summary = build_summary(findings, files_scanned=1, config=config, fail_on="critical")
    assert summary.failed is True


def test_complexity_thresholds_and_severities() -> None:
    config = Config(schema_version=1)
    assert complexity_findings([parsed(COMPLEXITY_WARN)], config) == []

    warn = complexity_findings([parsed(COMPLEXITY_WARN + 1)], config)
    assert len(warn) == 1
    assert warn[0].rule_id == "quality.complexity"
    assert warn[0].severity is Severity.LOW
    assert f"threshold {COMPLEXITY_WARN}" in warn[0].message

    high = complexity_findings([parsed(COMPLEXITY_HIGH)], config)
    assert high[0].severity is Severity.MEDIUM


def test_complexity_finding_location_snippet_and_fingerprint() -> None:
    config = Config(schema_version=1)
    result = complexity_findings([parsed(COMPLEXITY_WARN + 1, "handle")], config)[0]
    assert result.path == "src/a.py"
    assert (result.start_line, result.start_col, result.end_line, result.end_col) == (1, 1, 1, 2)
    assert result.snippet == "def handle():"
    assert result.fingerprint.startswith("cqa:v1:")
    assert "handle()" in result.message


def test_complexity_findings_respect_rule_selection_and_overrides() -> None:
    base = Config(schema_version=1)
    files = [parsed(COMPLEXITY_WARN + 1)]

    assert complexity_findings(files, base, allow={"sec.eval"}) == []
    assert len(complexity_findings(files, base, allow={"quality.complexity"})) == 1
    assert complexity_findings(files, base, disabled={"quality.complexity"}) == []

    disabled = Config(
        schema_version=1,
        rules=RulesConfig(disable=["quality.complexity"]),
    )
    assert complexity_findings(files, disabled) == []

    override = Config(
        schema_version=1,
        rules=RulesConfig(
            overrides={"quality.complexity": RuleOverride(severity=Severity.HIGH)}
        ),
    )
    result = complexity_findings(files, override)
    assert result[0].severity is Severity.HIGH

    off = Config(
        schema_version=1,
        rules=RulesConfig(overrides={"quality.complexity": RuleOverride(enabled=False)}),
    )
    assert complexity_findings(files, off) == []


def test_summary_defaults_cover_every_severity() -> None:
    summary = Summary()
    assert set(summary.by_severity) == {severity.value for severity in ALL_SEVERITIES}
    assert summary.score == 100
    assert summary.failed is False
