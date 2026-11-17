"""CI adapters (GitHub Actions in v1)."""

from .artifacts import write_artifact
from .github import GitHubContext, append_step_summary, detect_github, resolve_workspace_path

__all__ = [
    "GitHubContext",
    "append_step_summary",
    "detect_github",
    "resolve_workspace_path",
    "write_artifact",
]
