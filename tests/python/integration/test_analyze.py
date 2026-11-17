from __future__ import annotations

import json
from pathlib import Path

import pytest

from cqa.app import AnalyzeOptions, run_analyze
from cqa.config import Config
from cqa.exit_codes import IoError, UsageError
from cqa.models import Severity


def test_pipeline_end_to_end(sample_repo: Path, fallback_parser, frozen_clock) -> None:
    result = run_analyze(
        AnalyzeOptions(
            path=str(sample_repo),
            fail_on="high",
            no_cache=True,
            clock=frozen_clock,
        ),
        parser=fallback_parser,
    )

    assert result.generated_at == "1970-01-01T00:00:00Z"
    assert result.summary.files_scanned == 2
    assert {finding.path for finding in result.findings} == {"vulnerable.py"}
    assert all(not finding.path.startswith("ignored") for finding in result.findings)
    assert result.summary.failed is True

    rule_ids = {finding.rule_id for finding in result.findings}
    assert {"secrets.hardcoded", "secrets.aws_key", "sec.eval", "sec.sql_concat"} <= rule_ids
    assert result.summary.findings == len(result.findings)

    # Sorted: severity desc, path asc, line asc, rule_id asc.
    order = {
        Severity.CRITICAL: 0,
        Severity.HIGH: 1,
        Severity.MEDIUM: 2,
        Severity.LOW: 3,
        Severity.INFO: 4,
    }
    keys = [
        (order[finding.severity], finding.path, finding.start_line, finding.rule_id)
        for finding in result.findings
    ]
    assert keys == sorted(keys)


def test_fail_on_never_does_not_fail(sample_repo: Path, fallback_parser, frozen_clock) -> None:
    result = run_analyze(
        AnalyzeOptions(
            path=str(sample_repo),
            fail_on="never",
            no_cache=True,
            clock=frozen_clock,
        ),
        parser=fallback_parser,
    )
    assert result.findings
    assert result.summary.failed is False


def test_max_findings_truncates_list_but_not_counts(
    sample_repo: Path, fallback_parser, frozen_clock
) -> None:
    result = run_analyze(
        AnalyzeOptions(
            path=str(sample_repo),
            no_cache=True,
            max_findings=2,
            clock=frozen_clock,
        ),
        parser=fallback_parser,
    )
    assert len(result.findings) == 2
    assert result.summary.findings > 2
    assert result.summary.truncated is True


def test_language_filter(sample_repo: Path, fallback_parser, frozen_clock) -> None:
    result = run_analyze(
        AnalyzeOptions(
            path=str(sample_repo),
            languages="python",
            no_cache=True,
            clock=frozen_clock,
        ),
        parser=fallback_parser,
    )
    assert result.summary.files_scanned == 1
    assert {finding.path for finding in result.findings} == {"vulnerable.py"}


def test_rule_allow_list(sample_repo: Path, fallback_parser, frozen_clock) -> None:
    result = run_analyze(
        AnalyzeOptions(
            path=str(sample_repo),
            rules="sec.eval",
            no_cache=True,
            clock=frozen_clock,
        ),
        parser=fallback_parser,
    )
    assert result.findings
    assert {finding.rule_id for finding in result.findings} == {"sec.eval"}


def test_baseline_suppresses_and_updates(
    sample_repo: Path, fallback_parser, frozen_clock, tmp_path: Path
) -> None:
    baseline = tmp_path / "baseline.json"
    first = run_analyze(
        AnalyzeOptions(
            path=str(sample_repo),
            no_cache=True,
            baseline=str(baseline),
            update_baseline=True,
            clock=frozen_clock,
        ),
        parser=fallback_parser,
    )
    assert first.findings
    assert baseline.is_file()
    payload = json.loads(baseline.read_text(encoding="utf-8"))
    assert payload["schema_version"] == 1
    assert len(payload["fingerprints"]) == first.summary.findings

    second = run_analyze(
        AnalyzeOptions(
            path=str(sample_repo),
            no_cache=True,
            baseline=str(baseline),
            clock=frozen_clock,
        ),
        parser=fallback_parser,
    )
    assert second.findings == []
    assert second.summary.findings == 0
    assert second.summary.failed is False


def test_baseline_accepts_analysis_result_shape(
    sample_repo: Path, fallback_parser, frozen_clock, tmp_path: Path
) -> None:
    first = run_analyze(
        AnalyzeOptions(path=str(sample_repo), no_cache=True, clock=frozen_clock),
        parser=fallback_parser,
    )
    baseline = tmp_path / "baseline.json"
    baseline.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "findings": [{"fingerprint": finding.fingerprint} for finding in first.findings],
            }
        ),
        encoding="utf-8",
    )
    second = run_analyze(
        AnalyzeOptions(
            path=str(sample_repo),
            no_cache=True,
            baseline=str(baseline),
            clock=frozen_clock,
        ),
        parser=fallback_parser,
    )
    assert second.findings == []


def test_update_baseline_requires_path(sample_repo: Path) -> None:
    with pytest.raises(UsageError):
        run_analyze(AnalyzeOptions(path=str(sample_repo), update_baseline=True))


def test_missing_path_is_io_error(tmp_path: Path) -> None:
    with pytest.raises(IoError):
        run_analyze(AnalyzeOptions(path=str(tmp_path / "missing"), no_cache=True))


def test_parser_cache_avoids_second_parse(
    sample_repo: Path, fallback_parser, frozen_clock, tmp_path: Path
) -> None:
    class BombParser:
        parser_version = "python-fallback-1"

        def parse(self, files):  # type: ignore[no-untyped-def]
            raise AssertionError("parser must not be called on a warm cache")

    cache_dir = tmp_path / "cache"
    options = AnalyzeOptions(
        path=str(sample_repo),
        cache_dir=str(cache_dir),
        clock=frozen_clock,
    )
    first = run_analyze(options, parser=fallback_parser)
    assert any(cache_dir.glob("*.json"))
    second = run_analyze(options, parser=BombParser())
    assert second.summary.findings == first.summary.findings
    assert second.findings == first.findings


def test_invalid_utf8_becomes_parse_error_and_info_finding(
    tmp_path: Path, fallback_parser, frozen_clock
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "bad.py").write_bytes(b"\xff\xfe\x00bad")
    (repo / "ok.py").write_text("x = 1\n", encoding="utf-8")

    result = run_analyze(
        AnalyzeOptions(path=str(repo), no_cache=True, clock=frozen_clock),
        parser=fallback_parser,
    )
    assert result.summary.files_scanned == 2
    assert any(error.path == "bad.py" and error.kind == "parse" for error in result.errors)
    parse_findings = [item for item in result.findings if item.rule_id == "parser.error"]
    assert len(parse_findings) == 1
    assert parse_findings[0].severity is Severity.INFO


def test_rules_override_from_config(
    sample_repo: Path, fallback_parser, frozen_clock
) -> None:
    from cqa.config import RuleOverride, RulesConfig

    config = Config(
        schema_version=1,
        rules=RulesConfig(
            overrides={"secrets.hardcoded": RuleOverride(severity=Severity.LOW)}
        ),
    )
    result = run_analyze(
        AnalyzeOptions(path=str(sample_repo), no_cache=True, clock=frozen_clock),
        config=config,
        parser=fallback_parser,
    )
    secrets = [item for item in result.findings if item.rule_id == "secrets.hardcoded"]
    assert secrets
    assert all(item.severity is Severity.LOW for item in secrets)


def test_score_is_clamped_and_weighted(fallback_parser, frozen_clock, tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "crit.py").write_text('API_KEY = "sk-live-1234567890abcdef"\n', encoding="utf-8")
    result = run_analyze(
        AnalyzeOptions(path=str(repo), no_cache=True, clock=frozen_clock),
        parser=fallback_parser,
    )
    assert 0 <= result.summary.score <= 100
    assert result.summary.score == 75  # one critical -> -25
