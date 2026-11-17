"""Report branches not covered by the main report suite."""

from __future__ import annotations

from cqa.models import (
    ALL_SEVERITIES,
    AnalysisError,
    AnalysisResult,
    Summary,
    ToolInfo,
)
from cqa.report import render_result
from cqa.report.markdown_report import MAX_ERRORS, render_markdown
from cqa.report.redact import MAX_DISPLAY_SNIPPET, display_snippet
from cqa.report.table_report import render_table


def result(errors: list[AnalysisError] | None = None) -> AnalysisResult:
    counts = {severity.value: 0 for severity in ALL_SEVERITIES}
    return AnalysisResult(
        tool=ToolInfo(version="0.1.0", parser_version="0.1.0"),
        generated_at="1970-01-01T00:00:00Z",
        root=".",
        summary=Summary(files_scanned=0, findings=0, by_severity=counts, score=100),
        findings=[],
        errors=errors or [],
    )


def test_table_handles_no_findings_errors_and_truncation() -> None:
    empty = render_table(result())
    assert "No findings." in empty

    analysis = result(
        [
            AnalysisError(path="a.py", message="bad syntax", kind="parse"),
            AnalysisError(path="b.ts", message="unreadable", kind="io"),
        ]
    )
    analysis.summary.truncated = True
    analysis.summary.findings = 42
    text = render_table(analysis)
    assert "2 parser/IO error(s)" in text
    assert "a.py: parse: bad syntax" in text
    assert "b.ts: io: unreadable" in text
    assert "Output truncated" in text


def test_markdown_limits_rendered_errors() -> None:
    errors = [
        AnalysisError(path=f"f{index}.py", message=f"error {index}", kind="parse")
        for index in range(MAX_ERRORS + 2)
    ]
    text = render_markdown(result(errors))
    assert "### Parser / IO errors" in text
    assert "`f0.py`" in text
    assert f"- … {len(errors) - MAX_ERRORS} more error(s)" in text


def test_display_snippet_is_bounded_and_redacts_secrets() -> None:
    from cqa.models import Finding, Severity

    long = Finding(
        rule_id="sec.eval",
        severity=Severity.HIGH,
        message="m",
        path="a.py",
        start_line=1,
        start_col=1,
        end_line=1,
        end_col=2,
        fingerprint="f",
        snippet="x" * (MAX_DISPLAY_SNIPPET + 20),
    )
    assert display_snippet(long) == "x" * MAX_DISPLAY_SNIPPET + "..."

    secret = long.model_copy(update={"rule_id": "secrets.hardcoded", "snippet": "secret"})
    assert display_snippet(secret) == "[REDACTED]"

    blank = long.model_copy(update={"snippet": "   "})
    assert display_snippet(blank) is None


def test_render_result_dispatch_remains_total() -> None:
    for fmt in ("json", "sarif", "markdown", "github", "table"):
        rendered = render_result(result(), fmt)
        assert isinstance(rendered, str)
    assert render_result(result(), "github") == ""
