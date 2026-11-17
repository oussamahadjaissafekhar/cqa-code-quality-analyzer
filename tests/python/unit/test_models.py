"""Model invariants and small shared helpers."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest
from pydantic import ValidationError

from cqa.models import (
    AnalysisError,
    CallFact,
    Finding,
    FunctionFact,
    ImportFact,
    ParsedFile,
    ParserFile,
    ParserRequest,
    Severity,
    fingerprint,
    sort_findings,
    utc_now_iso,
)
from cqa.version import parser_version, version_info


def finding(severity: Severity, path: str = "a.py", line: int = 1, rule_id: str = "r") -> Finding:
    return Finding(
        rule_id=rule_id,
        severity=severity,
        message="m",
        path=path,
        start_line=line,
        start_col=1,
        end_line=line,
        end_col=2,
        fingerprint=fingerprint(rule_id, path, line, "p"),
    )


def test_fingerprint_is_stable_and_secret_free() -> None:
    first = fingerprint("sec.eval", "a.py", 3, "eval")
    assert first == fingerprint("sec.eval", "a.py", 3, "eval")
    assert first.startswith("cqa:v1:")
    assert len(first) == len("cqa:v1:") + 16
    assert first != fingerprint("sec.eval", "b.py", 3, "eval")
    assert first != fingerprint("sec.eval", "a.py", 4, "eval")
    assert first != fingerprint("sec.eval", "a.py", 3, "exec")


def test_utc_now_iso_handles_aware_and_naive_clocks() -> None:
    aware = datetime(2020, 5, 4, 3, 2, 1, tzinfo=timezone.utc)
    assert utc_now_iso(aware) == "2020-05-04T03:02:01Z"

    naive = datetime(2020, 5, 4, 3, 2, 1)
    assert utc_now_iso(naive) == "2020-05-04T03:02:01Z"

    assert utc_now_iso().endswith("Z")


def test_sort_findings_is_deterministic() -> None:
    findings = [
        finding(Severity.LOW, "b.py", 2, "b"),
        finding(Severity.CRITICAL, "z.py", 9, "z"),
        finding(Severity.HIGH, "a.py", 5, "h"),
        finding(Severity.CRITICAL, "a.py", 2, "c"),
    ]
    ordered = [(item.severity, item.path, item.start_line) for item in sort_findings(findings)]
    assert ordered == [
        (Severity.CRITICAL, "a.py", 2),
        (Severity.CRITICAL, "z.py", 9),
        (Severity.HIGH, "a.py", 5),
        (Severity.LOW, "b.py", 2),
    ]


def test_parsed_file_line_text_boundaries() -> None:
    parsed = ParsedFile(
        path="a.py",
        language="python",
        facts={"imports": [], "calls": [], "literals": [], "functions": []},
        source="first\r\nsecond\r\n",
    )
    assert parsed.line_text(1) == "first"
    assert parsed.line_text(2) == "second"
    assert parsed.line_text(0) == ""
    assert parsed.line_text(3) == ""
    assert parsed.line_text(99) == ""

    no_source = ParsedFile(
        path="b.py",
        language="python",
        facts={"imports": [], "calls": [], "literals": [], "functions": []},
    )
    assert no_source.line_text(1) == ""


def test_contract_models_reject_invalid_or_unknown_fields() -> None:
    with pytest.raises(ValidationError):
        Finding(
            rule_id="r",
            severity=Severity.HIGH,
            message="m",
            path="a.py",
            start_line=0,
            start_col=1,
            end_line=1,
            end_col=1,
            fingerprint="f",
        )

    with pytest.raises(ValidationError):
        CallFact(callee="eval", line=1, col=1, args_kind="sometimes")  # type: ignore[arg-type]

    with pytest.raises(ValidationError):
        FunctionFact(name="f", line=1, complexity=0)

    with pytest.raises(ValidationError):
        ParserFile(path="a.py", language="ruby", content="")  # type: ignore[arg-type]

    with pytest.raises(ValidationError):
        AnalysisError(path="a.py", message="m", extra="nope")  # type: ignore[call-arg]


def test_parser_contract_defaults_and_aliases() -> None:
    request = ParserRequest()
    assert request.schema_version == 1
    assert request.jobs == 1
    assert request.files == []

    with pytest.raises(ValidationError):
        ParserRequest(jobs=0)

    imported = ImportFact.model_validate({"from": "os", "names": ["os"], "line": 1})
    assert imported.from_ == "os"
    assert imported.model_dump(by_alias=True)["from"] == "os"


def test_version_info_and_environment_override(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    payload = version_info()
    assert payload["name"] == "cqa"
    assert payload["schema_version"] == 1
    assert isinstance(payload["parser_version"], str)

    monkeypatch.setenv("CQA_PARSER_VERSION", "9.9.9")
    parser_version.cache_clear()
    try:
        assert parser_version() == "9.9.9"
        assert version_info()["parser_version"] == "9.9.9"
    finally:
        parser_version.cache_clear()


def test_parser_version_falls_back_when_package_metadata_is_unreadable(
    monkeypatch,
) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.delenv("CQA_PARSER_VERSION", raising=False)
    parser_version.cache_clear()

    def fail(self, *args, **kwargs):  # type: ignore[no-untyped-def]
        raise OSError("not readable")

    monkeypatch.setattr(Path, "read_text", fail)
    try:
        assert parser_version() == "0.1.0"
    finally:
        parser_version.cache_clear()
