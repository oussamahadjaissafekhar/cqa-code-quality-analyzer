from __future__ import annotations

import json

import pytest

from cqa.models import (
    ALL_SEVERITIES,
    AnalysisError,
    AnalysisResult,
    Finding,
    Severity,
    Summary,
    ToolInfo,
    fingerprint,
)
from cqa.report import render_result
from cqa.report.github_annotations import render_github_annotations
from cqa.report.json_report import render_json
from cqa.report.markdown_report import render_markdown
from cqa.report.sarif_report import render_sarif
from cqa.report.table_report import render_table


def finding(
    rule_id: str = "sec.eval",
    severity: Severity = Severity.HIGH,
    path: str = "src/app.ts",
    line: int = 12,
    snippet: str = "eval(user)",
    message: str = "Use of eval() is unsafe",
) -> Finding:
    return Finding(
        rule_id=rule_id,
        severity=severity,
        message=message,
        path=path,
        start_line=line,
        start_col=3,
        end_line=line,
        end_col=7,
        fingerprint=fingerprint(rule_id, path, line, "eval"),
        snippet=snippet,
        help_uri=f"https://cqa.local/rules/{rule_id}",
    )


def result(findings: list[Finding] | None = None) -> AnalysisResult:
    items = findings or [finding()]
    counts = {severity.value: 0 for severity in ALL_SEVERITIES}
    for item in items:
        counts[item.severity.value] += 1
    return AnalysisResult(
        tool=ToolInfo(version="0.1.0", parser_version="0.1.0"),
        generated_at="1970-01-01T00:00:00Z",
        root=".",
        summary=Summary(
            files_scanned=1,
            findings=len(items),
            by_severity=counts,
            score=90,
            truncated=False,
            failed=True,
        ),
        findings=items,
        errors=[],
    )


def test_json_is_sorted_and_byte_stable() -> None:
    first = render_json(result())
    second = render_json(result())
    assert first == second
    assert first.endswith("\n")
    payload = json.loads(first)
    assert payload["tool"]["name"] == "cqa"
    # Sorted keys: errors precedes findings in the compact document.
    assert first.index('"errors"') < first.index('"findings"')
    assert "eval(user)" in first


def test_json_pretty_and_compact_differ_only_in_whitespace() -> None:
    compact = render_json(result(), pretty=False)
    pretty = render_json(result(), pretty=True)
    assert json.loads(compact) == json.loads(pretty)
    assert compact.count("\n") == 1
    assert pretty.count("\n") > 1


def test_sarif_mapping() -> None:
    payload = json.loads(render_sarif(result()))
    assert payload["version"] == "2.1.0"
    run = payload["runs"][0]
    assert run["tool"]["driver"]["name"] == "cqa"
    sarif_result = run["results"][0]
    assert sarif_result["ruleId"] == "sec.eval"
    assert sarif_result["level"] == "error"
    assert sarif_result["partialFingerprints"]["cqa/v1"].startswith("cqa:v1:")
    region = sarif_result["locations"][0]["physicalLocation"]["region"]
    assert region["startLine"] == 12
    assert region["startColumn"] == 3


def test_sarif_levels() -> None:
    from cqa.report.sarif_report import LEVEL_BY_SEVERITY

    assert LEVEL_BY_SEVERITY[Severity.CRITICAL] == "error"
    assert LEVEL_BY_SEVERITY[Severity.HIGH] == "error"
    assert LEVEL_BY_SEVERITY[Severity.MEDIUM] == "warning"
    assert LEVEL_BY_SEVERITY[Severity.LOW] == "note"
    assert LEVEL_BY_SEVERITY[Severity.INFO] == "note"


def test_secret_redaction_in_human_formats_and_sarif() -> None:
    secret = finding(
        rule_id="secrets.hardcoded",
        severity=Severity.CRITICAL,
        snippet='API_KEY = "sk-live-very-secret-value"',
        message="Possible hardcoded credential",
    )
    markdown = render_markdown(result([secret]))
    table = render_table(result([secret]))
    sarif = render_sarif(result([secret]))
    assert "sk-live-very-secret-value" not in markdown
    assert "[REDACTED]" in markdown
    assert "sk-live-very-secret-value" not in table
    assert "[REDACTED]" in table
    assert "sk-live-very-secret-value" not in sarif
    assert "[REDACTED]" in sarif
    # JSON is allowed a bounded snippet for tooling.
    assert "sk-live-very-secret-value" in render_json(result([secret]))


def test_markdown_contains_summary_and_truncation_note() -> None:
    analysis = result()
    analysis.summary.truncated = True
    text = render_markdown(analysis)
    assert "## CQA analysis" in text
    assert "| critical |" in text
    assert "truncated" in text.lower()


def test_github_annotations_escape_workflow_commands() -> None:
    item = finding(message="bad % newline\nvalue, colon: here", path="src/a:b.ts")
    text = render_github_annotations(result([item]))
    assert text.startswith("::error ")
    assert "file=src/a%3Ab.ts" in text
    assert "%25" in text
    assert "%0A" in text
    assert "title=sec.eval" in text
    assert text.endswith("\n")


def test_table_fallback_content() -> None:
    text = render_table(result())
    assert "CQA 0.1.0" in text
    assert "sec.eval" in text
    assert "src/app.ts:12:3" in text


def test_render_result_dispatch() -> None:
    assert render_result(result(), "json").startswith("{")
    assert "version" in render_result(result(), "sarif")
    assert "CQA analysis" in render_result(result(), "markdown")
    assert render_result(result(), "github").startswith("::")
    assert "SEVERITY" in render_result(result(), "table")
    with pytest.raises(ValueError):
        render_result(result(), "xml")


def test_errors_are_rendered() -> None:
    analysis = result()
    analysis.errors = [AnalysisError(path="bad.py", message="bad syntax", kind="parse")]
    assert "bad.py" in render_markdown(analysis)
    assert "bad syntax" in render_github_annotations(analysis)
