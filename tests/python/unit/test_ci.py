"""GitHub Actions adapters and artifact error mapping."""

from __future__ import annotations

from pathlib import Path

import pytest

from cqa.ci.artifacts import write_artifact
from cqa.ci.github import (
    GitHubContext,
    append_step_summary,
    detect_github,
    resolve_workspace_path,
)
from cqa.exit_codes import IoError


def test_detect_github_empty_env_does_not_fall_back_to_os_environ(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    monkeypatch.setenv("CI", "true")
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", "leak.md")

    context = detect_github({})
    assert context == GitHubContext(
        actions=False, step_summary=None, workspace=None, is_ci=False
    )


def test_detect_github_reads_environment_flags() -> None:
    context = detect_github(
        {
            "GITHUB_ACTIONS": "TRUE",
            "CI": "true",
            "GITHUB_STEP_SUMMARY": "summary.md",
            "GITHUB_WORKSPACE": "workspace",
        }
    )
    assert context.actions is True
    assert context.is_ci is True
    assert context.step_summary == Path("summary.md")
    assert context.workspace == Path("workspace")


def test_detect_github_ignores_non_true_values() -> None:
    context = detect_github({"GITHUB_ACTIONS": "yes", "CI": "1"})
    assert context.actions is False
    assert context.is_ci is False


def test_detect_github_defaults_to_process_environment(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    assert detect_github().actions is True


def test_append_step_summary_noop_without_a_file() -> None:
    assert append_step_summary("text", detect_github({})) is False


def test_append_step_summary_adds_a_single_trailing_newline(tmp_path: Path) -> None:
    summary = tmp_path / "summary.md"
    context = detect_github({"GITHUB_STEP_SUMMARY": str(summary)})

    assert append_step_summary("first", context) is True
    assert append_step_summary("second\n", context) is True
    assert summary.read_text(encoding="utf-8") == "first\nsecond\n"


def test_append_step_summary_swallows_os_errors(tmp_path: Path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    context = detect_github({"GITHUB_STEP_SUMMARY": str(tmp_path / "summary.md")})

    def fail(*args, **kwargs):  # type: ignore[no-untyped-def]
        raise OSError("read-only")

    monkeypatch.setattr(Path, "open", fail)
    assert append_step_summary("text", context) is False


def test_resolve_workspace_path() -> None:
    workspace = detect_github({"GITHUB_WORKSPACE": "ws"})
    assert resolve_workspace_path(Path("report.json"), workspace) == Path("ws/report.json")

    absolute = Path.cwd() / "absolute.json"
    assert resolve_workspace_path(absolute, workspace) == absolute

    no_workspace = detect_github({})
    assert resolve_workspace_path(Path("report.json"), no_workspace) == Path("report.json")


def test_write_artifact_creates_parents_and_normalizes_content(tmp_path: Path) -> None:
    target = tmp_path / "nested" / "deep" / "report.json"
    written = write_artifact(target, "line\n")
    assert written == target
    assert target.read_text(encoding="utf-8") == "line\n"


def test_write_artifact_maps_os_errors_to_io_error(tmp_path: Path) -> None:
    with pytest.raises(IoError, match="cannot write"):
        write_artifact(tmp_path, "content")  # a directory is not writable

    blocker = tmp_path / "blocker"
    blocker.write_text("not a directory", encoding="utf-8")
    with pytest.raises(IoError, match="cannot write"):
        write_artifact(blocker / "child.json", "content")
