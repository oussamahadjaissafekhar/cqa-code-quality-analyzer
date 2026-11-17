"""Artifact writing with predictable error mapping (exit code 3 on failure)."""

from __future__ import annotations

from pathlib import Path

from ..exit_codes import IoError


def write_artifact(path: Path, content: str) -> Path:
    """Write text, creating parent directories. Raise :class:`IoError` on failure."""

    try:
        if path.parent and not path.parent.exists():
            path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8", newline="\n")
    except OSError as exc:
        raise IoError(f"cannot write {path}: {exc}") from exc
    return path
