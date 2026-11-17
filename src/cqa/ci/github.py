"""GitHub Actions adapters.

v1 never talks to the GitHub REST API. It only reads ``GITHUB_*`` environment
variables, appends Markdown to the step summary file, and resolves paths against
``GITHUB_WORKSPACE``.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class GitHubContext:
    actions: bool
    step_summary: Path | None
    workspace: Path | None
    is_ci: bool


def detect_github(env: Mapping[str, str] | None = None) -> GitHubContext:
    values = env if env is not None else os.environ
    actions = values.get("GITHUB_ACTIONS", "").lower() == "true"
    summary_value = values.get("GITHUB_STEP_SUMMARY")
    workspace_value = values.get("GITHUB_WORKSPACE")
    return GitHubContext(
        actions=actions,
        step_summary=Path(summary_value) if summary_value else None,
        workspace=Path(workspace_value) if workspace_value else None,
        is_ci=values.get("CI", "").lower() == "true",
    )


def append_step_summary(markdown: str, context: GitHubContext) -> bool:
    """Append ``markdown`` to ``$GITHUB_STEP_SUMMARY``. Best-effort."""

    if context.step_summary is None:
        return False
    try:
        with context.step_summary.open("a", encoding="utf-8") as handle:
            handle.write(markdown)
            if not markdown.endswith("\n"):
                handle.write("\n")
        return True
    except OSError:
        return False


def resolve_workspace_path(path: Path, context: GitHubContext) -> Path:
    if path.is_absolute() or context.workspace is None:
        return path
    return context.workspace / path
