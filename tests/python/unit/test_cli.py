from __future__ import annotations

import io
import json
from pathlib import Path

import pytest

from cqa.cli import main


@pytest.fixture(autouse=True)
def use_fallback(monkeypatch, fallback_parser):
    """CLI tests must not depend on a built Node parser."""
    monkeypatch.setattr("cqa.app.create_parser", lambda *args, **kwargs: fallback_parser)


def test_help_lists_commands(capsys) -> None:  # type: ignore[no-untyped-def]
    assert main(["--help"]) == 0
    output = capsys.readouterr().out
    for command in ("analyze", "rules", "init", "version"):
        assert command in output


def test_version_flag(capsys) -> None:  # type: ignore[no-untyped-def]
    assert main(["--version"]) == 0
    assert "cqa 0.1.0" in capsys.readouterr().out


def test_version_json(capsys) -> None:  # type: ignore[no-untyped-def]
    assert main(["version", "--format", "json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["name"] == "cqa"
    assert payload["schema_version"] == 1
    assert "parser_version" in payload


def test_rules_json(capsys) -> None:  # type: ignore[no-untyped-def]
    assert main(["rules", "--format", "json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    rules = {item["id"]: item for item in payload["rules"]}
    assert rules["sec.eval"]["severity"] == "high"
    assert rules["secrets.hardcoded"]["severity"] == "critical"
    assert rules["quality.complexity"]["enabled"] is True


def test_analyze_json_and_exit_code(capsys, sample_repo: Path) -> None:  # type: ignore[no-untyped-def]
    code = main(
        [
            "analyze",
            str(sample_repo),
            "--format",
            "json",
            "--no-cache",
            "--fail-on",
            "high",
        ]
    )
    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert code == 1
    assert payload["summary"]["failed"] is True
    assert payload["tool"]["name"] == "cqa"
    assert payload["root"].endswith("tests/python/fixtures/repos/sample")


def test_analyze_fail_on_never(capsys, sample_repo: Path) -> None:  # type: ignore[no-untyped-def]
    assert (
        main(
            [
                "analyze",
                str(sample_repo),
                "--no-cache",
                "--fail-on",
                "never",
            ]
        )
        == 0
    )
    capsys.readouterr()


def test_env_fail_on_overrides_config(capsys, sample_repo: Path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setenv("CQA_FAIL_ON", "never")
    assert main(["analyze", str(sample_repo), "--no-cache"]) == 0
    capsys.readouterr()


def test_config_fail_on_used_when_flag_absent(capsys, sample_repo: Path, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    config = tmp_path / "cqa.toml"
    config.write_text(
        'schema_version = 1\n\n[thresholds]\nfail_on = "never"\n\n[report]\nsarif = false\n',
        encoding="utf-8",
    )
    assert main(["--config", str(config), "analyze", str(sample_repo), "--no-cache"]) == 0
    capsys.readouterr()


def test_analyze_output_and_sarif_files(capsys, sample_repo: Path, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    output = tmp_path / "out" / "cqa-results.json"
    sarif = tmp_path / "cqa.sarif"
    code = main(
        [
            "analyze",
            str(sample_repo),
            "--no-cache",
            "--fail-on",
            "never",
            "--output",
            str(output),
            "--sarif",
            str(sarif),
        ]
    )
    assert code == 0
    assert json.loads(output.read_text(encoding="utf-8"))["schema_version"] == 1
    assert json.loads(sarif.read_text(encoding="utf-8"))["version"] == "2.1.0"
    assert capsys.readouterr().out == ""


def test_max_findings_flag(capsys, sample_repo: Path) -> None:  # type: ignore[no-untyped-def]
    assert (
        main(
            [
                "analyze",
                str(sample_repo),
                "--no-cache",
                "--max-findings",
                "1",
                "--fail-on",
                "never",
            ]
        )
        == 0
    )
    payload = json.loads(capsys.readouterr().out)
    assert len(payload["findings"]) == 1
    assert payload["summary"]["findings"] > 1
    assert payload["summary"]["truncated"] is True


def test_markdown_redacts_secrets(capsys, sample_repo: Path) -> None:  # type: ignore[no-untyped-def]
    assert (
        main(
            [
                "analyze",
                str(sample_repo),
                "--format",
                "markdown",
                "--no-cache",
                "--fail-on",
                "never",
            ]
        )
        == 0
    )
    output = capsys.readouterr().out
    assert "CQA analysis" in output
    assert "sk-live-1234567890abcdef" not in output
    assert "[REDACTED]" in output


def test_github_format(capsys, sample_repo: Path) -> None:  # type: ignore[no-untyped-def]
    assert (
        main(
            [
                "analyze",
                str(sample_repo),
                "--format",
                "github",
                "--no-cache",
                "--fail-on",
                "never",
            ]
        )
        == 0
    )
    assert capsys.readouterr().out.startswith("::")


def test_table_falls_back_without_tty(capsys, sample_repo: Path) -> None:  # type: ignore[no-untyped-def]
    assert (
        main(
            [
                "analyze",
                str(sample_repo),
                "--format",
                "table",
                "--no-cache",
                "--fail-on",
                "never",
            ]
        )
        == 0
    )
    captured = capsys.readouterr()
    assert "falling back to JSON" in captured.err
    assert json.loads(captured.out)["schema_version"] == 1


def test_rules_allow_list_cli(capsys, sample_repo: Path) -> None:  # type: ignore[no-untyped-def]
    assert (
        main(
            [
                "analyze",
                str(sample_repo),
                "--rules",
                "sec.eval",
                "--no-cache",
                "--fail-on",
                "never",
            ]
        )
        == 0
    )
    payload = json.loads(capsys.readouterr().out)
    assert {finding["rule_id"] for finding in payload["findings"]} == {"sec.eval"}


def test_languages_cli(capsys, sample_repo: Path) -> None:  # type: ignore[no-untyped-def]
    assert (
        main(
            [
                "analyze",
                str(sample_repo),
                "--languages",
                "python",
                "--no-cache",
                "--fail-on",
                "never",
            ]
        )
        == 0
    )
    payload = json.loads(capsys.readouterr().out)
    assert payload["summary"]["files_scanned"] == 1


def test_stdin_files(capsys, sample_repo: Path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setattr("sys.stdin", io.StringIO("vulnerable.py\x00"))
    assert (
        main(
            [
                "analyze",
                str(sample_repo),
                "--stdin-files",
                "--no-cache",
                "--fail-on",
                "never",
            ]
        )
        == 0
    )
    payload = json.loads(capsys.readouterr().out)
    assert {finding["path"] for finding in payload["findings"]} == {"vulnerable.py"}


def test_missing_path_exit_3(capsys, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    assert main(["analyze", str(tmp_path / "missing"), "--no-cache"]) == 3
    assert "path not found" in capsys.readouterr().err


def test_bad_config_exit_2(capsys, tmp_path: Path, sample_repo: Path) -> None:  # type: ignore[no-untyped-def]
    config = tmp_path / "bad.toml"
    config.write_text("schema_version = 1\n\n[discover]\nmagic = true\n", encoding="utf-8")
    assert main(["--config", str(config), "analyze", str(sample_repo)]) == 2
    assert "invalid config" in capsys.readouterr().err


def test_init_and_force(capsys, tmp_path: Path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.chdir(tmp_path)
    assert main(["init"]) == 0
    assert (tmp_path / "cqa.toml").is_file()
    assert main(["init"]) == 2
    assert main(["init", "--force"]) == 0
    capsys.readouterr()


def test_pretty_json_with_verbose(capsys, sample_repo: Path) -> None:  # type: ignore[no-untyped-def]
    assert (
        main(
            [
                "-v",
                "analyze",
                str(sample_repo),
                "--no-cache",
                "--fail-on",
                "never",
            ]
        )
        == 0
    )
    output = capsys.readouterr().out
    assert '\n  "' in output
