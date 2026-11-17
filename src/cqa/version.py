"""Version metadata for the CLI, schema, and TypeScript parser.

Keeping these values in one place makes ``cqa version`` and the JSON reports
consistent. The parser version is read from the workspace package metadata when
available so the bridge and the CLI cannot silently drift apart.
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Literal

TOOL_VERSION = "0.1.0"
PARSER_VERSION_FALLBACK = "0.1.0"
SCHEMA_VERSION: Literal[1] = 1


@lru_cache(maxsize=1)
def parser_version() -> str:
    """Return the parser-cli version, falling back to the tool version.

    Resolution order:
    1. ``CQA_PARSER_VERSION`` environment override (used by the Docker image).
    2. ``packages/parser-cli/package.json`` in a source checkout.
    3. The bundled fallback constant.
    """

    import os

    override = os.environ.get("CQA_PARSER_VERSION")
    if override:
        return override

    candidate = Path(__file__).resolve().parents[2] / "packages" / "parser-cli" / "package.json"
    try:
        payload = json.loads(candidate.read_text(encoding="utf-8"))
        version = payload.get("version")
        if isinstance(version, str) and version:
            return version
    except (OSError, ValueError):
        pass
    return PARSER_VERSION_FALLBACK


def version_info() -> dict[str, object]:
    """Machine-readable version block used by ``cqa version --format json``."""

    return {
        "name": "cqa",
        "version": TOOL_VERSION,
        "parser_version": parser_version(),
        "schema_version": SCHEMA_VERSION,
    }
