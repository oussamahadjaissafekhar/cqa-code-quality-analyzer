"""TTY-friendly aligned table. Falls back to JSON when stdout is not a TTY."""

from __future__ import annotations

from ..models import AnalysisResult
from .redact import display_snippet

MAX_MESSAGE = 80


def _truncate(value: str, width: int) -> str:
    return value if len(value) <= width else value[: max(0, width - 3)] + "..."


def render_table(result: AnalysisResult) -> str:
    summary = result.summary
    lines = [
        f"CQA {result.tool.version}  score={summary.score}/100  "
        f"files={summary.files_scanned}  findings={summary.findings}  "
        f"status={'FAILED' if summary.failed else 'PASSED'}",
        "",
    ]

    if not result.findings:
        lines.append("No findings.")
    else:
        headers = ("SEVERITY", "RULE", "LOCATION", "MESSAGE")
        rows: list[tuple[str, str, str, str]] = []
        for finding in result.findings:
            location = f"{finding.path}:{finding.start_line}:{finding.start_col}"
            message = finding.message
            snippet = display_snippet(finding)
            if snippet:
                message += f"  [{snippet}]"
            rows.append(
                (
                    finding.severity.value.upper(),
                    finding.rule_id,
                    location,
                    _truncate(message, MAX_MESSAGE),
                )
            )

        widths = [len(header) for header in headers]
        for row in rows:
            for index, cell in enumerate(row):
                widths[index] = min(60, max(widths[index], len(cell)))

        def fmt(cells: tuple[str, str, str, str]) -> str:
            return "  ".join(
                _truncate(cell, widths[index]).ljust(widths[index])
                for index, cell in enumerate(cells)
            ).rstrip()

        lines.append(fmt(headers))
        lines.append("  ".join("-" * width for width in widths))
        lines.extend(fmt(row) for row in rows)

    if result.errors:
        lines.append("")
        lines.append(f"{len(result.errors)} parser/IO error(s):")
        for error in result.errors[:10]:
            lines.append(f"  {error.path}: {error.kind}: {error.message}")

    if summary.truncated:
        lines.append("")
        lines.append(
            f"Output truncated; {summary.findings} findings counted in total."
        )
    return "\n".join(lines) + "\n"
