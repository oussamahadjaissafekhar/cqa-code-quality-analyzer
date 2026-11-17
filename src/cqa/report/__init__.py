"""Report generators.

Reports consume :class:`cqa.models.AnalysisResult` only. They never import the
parser, discovery, or security engine, which keeps output formats independent of
analysis internals.
"""

from __future__ import annotations

from ..models import AnalysisResult
from .github_annotations import render_github_annotations
from .json_report import render_json
from .markdown_report import render_markdown
from .sarif_report import render_sarif
from .table_report import render_table

FORMATS = ("json", "sarif", "markdown", "github", "table")


def render_result(
    result: AnalysisResult,
    fmt: str,
    *,
    pretty: bool = False,
) -> str:
    """Render ``result`` in ``fmt``. Unknown formats raise ``ValueError``."""

    if fmt == "json":
        return render_json(result, pretty=pretty)
    if fmt == "sarif":
        return render_sarif(result)
    if fmt == "markdown":
        return render_markdown(result)
    if fmt == "github":
        return render_github_annotations(result)
    if fmt == "table":
        return render_table(result)
    raise ValueError(f"unknown report format: {fmt}")


__all__ = [
    "FORMATS",
    "render_github_annotations",
    "render_json",
    "render_markdown",
    "render_result",
    "render_sarif",
    "render_table",
]
