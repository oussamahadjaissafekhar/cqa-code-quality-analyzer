"""CLI argument validation and exit-code mapping edge cases."""

from __future__ import annotations

import json
import runpy
import sys
from pathlib import Path

import click
import pytest

from cqa.app import AnalyzeOptions
from cqa.ci.github import GitHubContext, detect_github
from cqa.cli import _emit_reports, main
from cqa.exit_codes import IoError, ParserError, ParserTimeout, UsageError
from cqa.models import AnalysisResult, Summary, ToolInfo
from cqa.version import TOOL_VERSION


def result(failed: bool = False) -> AnalysisResult:
    return AnalysisResult(
        tool=ToolInfo(version=TOOL_VERSION, parser_version="test"),
        generated_at="1970-01-01T00:00:00Z",
        root=".",
        summary=Summary(failed=failed),
    )


@pytest.fixture(autouse=True)
def isolated_cwd(tmp_path: Path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.chdir(tmp_path)


def test_missing_option_values_are_usage_errors(capsys) -> None:  # type: ignore[no-untyped-def]
    for argv in (
        ["analyze", "--fail-on"],
        ["analyze", "--output"],
        ["analyze", "--baseline"],
        ["rules", "--format"],
    ):
        assert main(argv) == 2
        assert "requires an argument" in capsys.readouterr().err


def test_invalid_choices_and_ranges_are_usage_errors(capsys) -> None:  # type: ignore[no-untyped-def]
    for argv in (
        ["analyze", "--fail-on", "sometimes"],
        ["analyze", "--format", "xml"],
        ["analyze", "--jobs=-1"],
        ["analyze", "--timeout-s", "0"],
        ["version", "--format", "xml"],
        ["unknown-command"],
    ):
        assert main(argv) == 2
        assert capsys.readouterr().err


def test_update_baseline_without_baseline_is_a_usage_error(capsys) -> None:  # type: ignore[no-untyped-def]
    assert main(["analyze", "--update-baseline"]) == 2
    assert "--update-baseline requires --baseline" in capsys.readouterr().err


def test_invalid_language_is_a_usage_error(tmp_path: Path, capsys) -> None:  # type: ignore[no-untyped-def]
    assert main(["analyze", str(tmp_path), "--languages", "ruby"]) == 2
    assert "unsupported language" in capsys.readouterr().err


def test_missing_path_is_io_error(tmp_path: Path, capsys) -> None:  # type: ignore[no-untyped-def]
    assert main(["analyze", str(tmp_path / "missing")]) == 3
    assert "path not found" in capsys.readouterr().err


def test_missing_explicit_parser_is_a_parser_error(tmp_path: Path, capsys) -> None:  # type: ignore[no-untyped-def]
    assert (
        main(
            [
                "analyze",
                str(tmp_path),
                "--parser-bin",
                str(tmp_path / "missing-parser.js"),
                "--no-cache",
            ]
        )
        == 4
    )
    assert "parser binary not found" in capsys.readouterr().err


@pytest.mark.parametrize(
    ("error", "expected"),
    [
        (ParserError("bad parser"), 4),
        (ParserTimeout("slow parser"), 5),
        (IoError("missing file"), 3),
        (UsageError("bad option"), 2),
    ],
)
def test_cqa_errors_map_to_documented_exit_codes(
    monkeypatch, capsys, error, expected  # type: ignore[no-untyped-def]
) -> None:
    def fail(*args, **kwargs):  # type: ignore[no-untyped-def]
        raise error

    monkeypatch.setattr("cqa.cli.run_analyze", fail)
    assert main(["analyze", "."]) == expected
    assert error.message in capsys.readouterr().err


def test_interrupt_and_abort_map_to_130(monkeypatch, capsys) -> None:  # type: ignore[no-untyped-def]
    def abort(*args, **kwargs):  # type: ignore[no-untyped-def]
        raise click.Abort()

    monkeypatch.setattr("cqa.cli.run_analyze", abort)
    assert main(["analyze", "."]) == 130
    assert "aborted" in capsys.readouterr().err


def test_keyboard_interrupt_outside_click_maps_to_130(monkeypatch, capsys) -> None:  # type: ignore[no-untyped-def]
    def interrupt(*args, **kwargs):  # type: ignore[no-untyped-def]
        raise KeyboardInterrupt

    # Click converts interrupts raised by the command; interrupts from its own
    # machinery reach the outer handler.
    monkeypatch.setattr("cqa.cli.cli.main", interrupt)
    assert main([]) == 130
    assert "interrupted" in capsys.readouterr().err


def test_click_exit_code_is_preserved(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    def exit_early(*args, **kwargs):  # type: ignore[no-untyped-def]
        raise click.exceptions.Exit(7)

    monkeypatch.setattr("cqa.cli.cli.main", exit_early)
    assert main([]) == 7


def test_broken_pipe_and_unexpected_errors(monkeypatch, capsys) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setattr("cqa.cli.run_analyze", lambda *args, **kwargs: result())
    monkeypatch.setattr(
        "cqa.cli._emit_reports", lambda *args, **kwargs: (_ for _ in ()).throw(BrokenPipeError())
    )
    assert main(["analyze", "."]) == 0

    def explode(*args, **kwargs):  # type: ignore[no-untyped-def]
        raise RuntimeError("unexpected")

    monkeypatch.setattr("cqa.cli.run_analyze", explode)
    assert main(["analyze", "."]) == 4
    assert "internal error: unexpected" in capsys.readouterr().err


def test_findings_gate_maps_to_exit_1(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setattr("cqa.cli.run_analyze", lambda *args, **kwargs: result(failed=True))
    monkeypatch.setattr("cqa.cli._emit_reports", lambda *args, **kwargs: None)
    assert main(["analyze", "."]) == 1


def test_rules_table_and_json(capsys) -> None:  # type: ignore[no-untyped-def]
    assert main(["rules"]) == 0
    table = capsys.readouterr().out
    assert "ID" in table and "SEVERITY" in table and "quality.complexity" in table

    assert main(["rules", "--format", "json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["schema_version"] == 1
    assert {rule["id"] for rule in payload["rules"]} >= {"sec.eval", "quality.complexity"}


def test_init_refuses_overwrite_without_force(capsys) -> None:  # type: ignore[no-untyped-def]
    assert main(["init"]) == 0
    target = Path.cwd() / "cqa.toml"
    assert target.is_file()
    first = target.read_text(encoding="utf-8")
    assert "schema_version" in first

    assert main(["init"]) == 2
    assert "already exists" in capsys.readouterr().err

    target.write_text("overwritten", encoding="utf-8")
    assert main(["init", "--force"]) == 0
    assert target.read_text(encoding="utf-8") == first


def test_version_table(capsys) -> None:  # type: ignore[no-untyped-def]
    assert main(["version"]) == 0
    assert capsys.readouterr().out.startswith("cqa 0.1.0")


def test_python_m_cqa_entrypoint(monkeypatch, capsys) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setattr(sys, "argv", ["cqa", "--version"])
    with pytest.raises(SystemExit) as excinfo:
        runpy.run_module("cqa", run_name="__main__")
    assert excinfo.value.code == 0
    assert "cqa 0.1.0" in capsys.readouterr().out


def test_table_format_falls_back_to_json_off_a_tty(
    monkeypatch, capsys, tmp_path: Path
) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setattr("cqa.cli.run_analyze", lambda *args, **kwargs: result())
    assert main(["analyze", ".", "--format", "table"]) == 0
    captured = capsys.readouterr()
    assert "table format requires a TTY" in captured.err
    assert json.loads(captured.out)["schema_version"] == 1


def test_report_sarif_config_writes_extra_artifact(monkeypatch, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    (tmp_path / "cqa.toml").write_text("schema_version = 1\n[report]\nsarif = true\n", encoding="utf-8")
    monkeypatch.setattr("cqa.cli.run_analyze", lambda *args, **kwargs: result())
    monkeypatch.setattr("cqa.cli.detect_github", lambda: detect_github({}))

    assert main(["analyze", "."]) == 0
    assert (tmp_path / "cqa.sarif").is_file()


def test_emit_reports_writes_output_sarif_and_step_summary(
    monkeypatch, capsys, tmp_path: Path
) -> None:  # type: ignore[no-untyped-def]
    summary = tmp_path / "step-summary.md"
    monkeypatch.setattr(
        "cqa.cli.detect_github",
        lambda: GitHubContext(
            actions=True, step_summary=summary, workspace=None, is_ci=True
        ),
    )
    output = tmp_path / "report.md"
    sarif = tmp_path / "report.sarif"
    options = AnalyzeOptions(format="markdown", output=str(output), sarif=str(sarif))

    _emit_reports(result(), options, verbose=0)

    assert "## CQA analysis" in output.read_text(encoding="utf-8")
    assert json.loads(sarif.read_text(encoding="utf-8"))["version"] == "2.1.0"
    assert summary.read_text(encoding="utf-8").startswith("## CQA analysis")
    # Workflow commands are only printed to stdout when the report goes to a file.
    assert capsys.readouterr().out == ""


def test_detect_github_is_used_by_emit_reports(monkeypatch, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    context = detect_github()
    assert context.actions is True

    output = tmp_path / "report.json"
    options = AnalyzeOptions(format="json", output=str(output))
    _emit_reports(result(), options, verbose=0)
    assert output.is_file()
