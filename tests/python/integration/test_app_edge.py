"""Pipeline edge cases: empty inputs, malformed code, and invalid options."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from cqa.app import AnalyzeOptions, run_analyze
from cqa.exit_codes import IoError, UsageError
from cqa.models import Severity


def analyze(path: Path, parser, clock, **overrides):  # type: ignore[no-untyped-def]
    options = AnalyzeOptions(
        path=str(path),
        no_cache=True,
        clock=clock,
        **overrides,
    )
    return run_analyze(options, parser=parser)


def test_empty_directory_produces_a_passing_result(
    tmp_path: Path, fallback_parser, frozen_clock
) -> None:
    repo = tmp_path / "empty"
    repo.mkdir()

    result = analyze(repo, fallback_parser, frozen_clock)
    assert result.summary.files_scanned == 0
    assert result.summary.findings == 0
    assert result.summary.score == 100
    assert result.summary.failed is False
    assert result.findings == []
    assert result.errors == []
    assert result.generated_at == "1970-01-01T00:00:00Z"


def test_empty_source_files_are_scanned_without_findings(
    tmp_path: Path, fallback_parser, frozen_clock
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    for name in ("empty.py", "empty.ts", "empty.js"):
        (repo / name).write_text("", encoding="utf-8")

    result = analyze(repo, fallback_parser, frozen_clock)
    assert result.summary.files_scanned == 3
    assert [finding for finding in result.findings if finding.rule_id != "parser.error"] == []
    assert result.errors == []
    assert result.summary.failed is False


def test_malformed_python_is_reported_but_does_not_abort(
    tmp_path: Path, fallback_parser, frozen_clock
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "broken.py").write_text("def broken(:\n    pass\n", encoding="utf-8")
    (repo / "ok.py").write_text("eval(user)\n", encoding="utf-8")

    result = analyze(repo, fallback_parser, frozen_clock, fail_on="critical")
    assert result.summary.files_scanned == 2
    assert any(error.path == "broken.py" and error.kind == "parse" for error in result.errors)

    parser_findings = [item for item in result.findings if item.rule_id == "parser.error"]
    assert len(parser_findings) == 1
    assert parser_findings[0].severity is Severity.INFO
    assert parser_findings[0].path == "broken.py"

    # The healthy file still produced its security finding.
    assert any(item.rule_id == "sec.eval" and item.path == "ok.py" for item in result.findings)
    # Info findings never trip the default gate.
    assert result.summary.failed is False


def test_invalid_language_and_fail_on_are_usage_errors(
    tmp_path: Path, fallback_parser, frozen_clock
) -> None:
    with pytest.raises(UsageError, match="unsupported language"):
        analyze(tmp_path, fallback_parser, frozen_clock, languages="ruby")

    with pytest.raises(UsageError, match="unsupported language"):
        analyze(tmp_path, fallback_parser, frozen_clock, languages="python,ruby")

    with pytest.raises(UsageError, match="invalid fail-on"):
        analyze(tmp_path, fallback_parser, frozen_clock, fail_on="sometimes")


def test_jobs_zero_falls_back_to_available_cpus(
    tmp_path: Path, fallback_parser, frozen_clock
) -> None:
    result = analyze(tmp_path, fallback_parser, frozen_clock, jobs=0)
    assert result.summary.files_scanned == 0


def test_single_file_target_and_unsupported_extension(
    tmp_path: Path, fallback_parser, frozen_clock
) -> None:
    source = tmp_path / "one.py"
    source.write_text("eval(user)\n", encoding="utf-8")
    result = analyze(source, fallback_parser, frozen_clock)
    assert result.summary.files_scanned == 1
    assert result.root == tmp_path.resolve().as_posix()

    notes = tmp_path / "notes.txt"
    notes.write_text("eval(user)\n", encoding="utf-8")
    ignored = analyze(notes, fallback_parser, frozen_clock)
    assert ignored.summary.files_scanned == 0
    assert ignored.findings == []


def test_explicit_stdin_file_list_limits_discovery(
    tmp_path: Path, fallback_parser, frozen_clock, monkeypatch
) -> None:  # type: ignore[no-untyped-def]
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "a.py").write_text("eval(user)\n", encoding="utf-8")
    (repo / "b.py").write_text("exec(user)\n", encoding="utf-8")
    monkeypatch.setattr("cqa.app.read_stdin_files", lambda: ("a.py",))

    result = analyze(repo, fallback_parser, frozen_clock, stdin_files=True)
    assert result.summary.files_scanned == 1
    assert {finding.path for finding in result.findings} == {"a.py"}


def test_unreadable_source_becomes_an_io_error(
    tmp_path: Path, fallback_parser, frozen_clock, monkeypatch
) -> None:  # type: ignore[no-untyped-def]
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "denied.py").write_text("eval(user)\n", encoding="utf-8")

    def denied(self):  # type: ignore[no-untyped-def]
        raise OSError("permission denied")

    monkeypatch.setattr(Path, "read_bytes", denied)
    result = analyze(repo, fallback_parser, frozen_clock)

    assert result.summary.files_scanned == 1
    assert result.summary.findings == 0
    assert [(error.path, error.kind) for error in result.errors] == [("denied.py", "io")]
    # IO errors are not promoted to parser.error info findings.
    assert all(item.rule_id != "parser.error" for item in result.findings)


def test_baseline_errors_are_mapped(
    tmp_path: Path, fallback_parser, frozen_clock
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "a.py").write_text("x = 1\n", encoding="utf-8")

    with pytest.raises(IoError, match="baseline not found"):
        analyze(repo, fallback_parser, frozen_clock, baseline=str(tmp_path / "missing.json"))

    invalid_json = tmp_path / "invalid.json"
    invalid_json.write_text("{ not json", encoding="utf-8")
    with pytest.raises(UsageError, match="invalid baseline"):
        analyze(repo, fallback_parser, frozen_clock, baseline=str(invalid_json))

    wrong_shape = tmp_path / "wrong.json"
    wrong_shape.write_text(json.dumps(["not", "a", "mapping"]), encoding="utf-8")
    with pytest.raises(UsageError, match="expected findings"):
        analyze(repo, fallback_parser, frozen_clock, baseline=str(wrong_shape))

    loose = tmp_path / "loose.json"
    loose.write_text(json.dumps({"fingerprints": [1, "cqa:v1:deadbeef"]}), encoding="utf-8")
    result = analyze(repo, fallback_parser, frozen_clock, baseline=str(loose))
    assert result.errors == []


def test_baseline_update_unions_old_and_new_fingerprints(
    sample_repo: Path, fallback_parser, frozen_clock, tmp_path: Path
) -> None:
    baseline = tmp_path / "baseline.json"
    baseline.write_text(
        json.dumps({"schema_version": 1, "fingerprints": ["cqa:v1:oldfingerprint"]}),
        encoding="utf-8",
    )

    updated = analyze(
        sample_repo, fallback_parser, frozen_clock, baseline=str(baseline), update_baseline=True
    )
    assert updated.findings  # the unknown old entry does not suppress anything

    payload = json.loads(baseline.read_text(encoding="utf-8"))
    assert "cqa:v1:oldfingerprint" in payload["fingerprints"]
    assert len(payload["fingerprints"]) == updated.summary.findings + 1

    accepted = analyze(sample_repo, fallback_parser, frozen_clock, baseline=str(baseline))
    assert accepted.findings == []
    assert accepted.summary.failed is False
