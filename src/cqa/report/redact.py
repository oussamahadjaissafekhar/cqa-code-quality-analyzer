"""Redaction helpers for human-facing and SARIF output.

JSON artifacts may include a bounded snippet for tooling. Markdown, tables, and
SARIF must never print secret material, so secret-rule findings are replaced by
a constant marker.
"""

from __future__ import annotations

from ..models import Finding

REDACTED = "[REDACTED]"
MAX_DISPLAY_SNIPPET = 160


def is_secret_finding(finding: Finding) -> bool:
    return finding.rule_id.startswith("secrets.")


def display_snippet(finding: Finding) -> str | None:
    if is_secret_finding(finding):
        return REDACTED
    snippet = (finding.snippet or "").strip()
    if not snippet:
        return None
    if len(snippet) > MAX_DISPLAY_SNIPPET:
        return snippet[:MAX_DISPLAY_SNIPPET] + "..."
    return snippet
