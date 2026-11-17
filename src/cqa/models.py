"""Pydantic models mirroring ``contracts/*.schema.json`` (schema v1).

These are the *only* shapes that cross module boundaries:

* parsers emit :class:`ParserResponse` / :class:`ParsedFile`
* rules consume :class:`FileFacts` and emit :class:`Finding`
* reports consume :class:`AnalysisResult`

Imports intentionally stay inside the standard library and pydantic so this
module has no dependency on discovery, parsing, or rendering.
"""

from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from enum import Enum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class Severity(str, Enum):
    """Finding severity, ordered from most to least urgent."""

    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    INFO = "info"


SEVERITY_ORDER: dict[Severity, int] = {
    Severity.CRITICAL: 0,
    Severity.HIGH: 1,
    Severity.MEDIUM: 2,
    Severity.LOW: 3,
    Severity.INFO: 4,
}

SEVERITY_WEIGHTS: dict[Severity, int] = {
    Severity.CRITICAL: 25,
    Severity.HIGH: 10,
    Severity.MEDIUM: 3,
    Severity.LOW: 1,
    Severity.INFO: 0,
}

ALL_SEVERITIES: tuple[Severity, ...] = (
    Severity.CRITICAL,
    Severity.HIGH,
    Severity.MEDIUM,
    Severity.LOW,
    Severity.INFO,
)

Language = Literal["python", "typescript", "javascript"]


class StrictModel(BaseModel):
    """Contract models reject unknown keys to prevent silent drift."""

    model_config = ConfigDict(extra="forbid")


class Finding(StrictModel):
    """A rule verdict anchored to a 1-based source location."""

    schema_version: Literal[1] = 1
    rule_id: str
    severity: Severity
    message: str
    path: str
    start_line: int = Field(ge=1)
    start_col: int = Field(ge=1)
    end_line: int = Field(ge=1)
    end_col: int = Field(ge=1)
    fingerprint: str
    snippet: str | None = None
    help_uri: str | None = None


class AnalysisError(StrictModel):
    """A per-file failure that did not abort the run."""

    path: str
    message: str
    kind: Literal["parse", "io", "internal"] = "internal"


class ToolInfo(StrictModel):
    name: Literal["cqa"] = "cqa"
    version: str
    parser_version: str


class Summary(StrictModel):
    files_scanned: int = 0
    findings: int = 0
    by_severity: dict[str, int] = Field(
        default_factory=lambda: {severity.value: 0 for severity in ALL_SEVERITIES}
    )
    score: int = 100
    truncated: bool = False
    failed: bool = False


class AnalysisResult(StrictModel):
    """Canonical output of ``cqa analyze`` (``analysis-result.schema.json``)."""

    schema_version: Literal[1] = 1
    tool: ToolInfo
    generated_at: str
    root: str
    summary: Summary = Field(default_factory=Summary)
    findings: list[Finding] = Field(default_factory=list)
    errors: list[AnalysisError] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Parser IPC contracts
# ---------------------------------------------------------------------------


class ImportFact(StrictModel):
    from_: str = Field(alias="from")
    names: list[str] = Field(default_factory=list)
    line: int = Field(ge=1)

    model_config = ConfigDict(extra="forbid", populate_by_name=True)


class CallFact(StrictModel):
    callee: str
    line: int = Field(ge=1)
    col: int = Field(ge=1)
    args_kind: Literal["empty", "literal", "dynamic", "mixed"] = "dynamic"


class LiteralFact(StrictModel):
    value: str
    line: int = Field(ge=1)
    col: int = Field(ge=1)
    kind: Literal["string", "template", "number", "boolean"] = "string"


class FunctionFact(StrictModel):
    name: str
    line: int = Field(ge=1)
    complexity: int = Field(ge=1)


class FileFacts(StrictModel):
    imports: list[ImportFact] = Field(default_factory=list)
    calls: list[CallFact] = Field(default_factory=list)
    literals: list[LiteralFact] = Field(default_factory=list)
    functions: list[FunctionFact] = Field(default_factory=list)


class ParserFile(StrictModel):
    """A file handed to the parser. ``content`` avoids parser-side path access."""

    path: str
    language: Language
    content: str | None = None


class ParserFileResult(StrictModel):
    path: str
    language: str
    ok: bool = True
    facts: FileFacts = Field(default_factory=FileFacts)
    error: str | None = None


class ParserRequest(StrictModel):
    schema_version: Literal[1] = 1
    jobs: int = Field(default=1, ge=1)
    files: list[ParserFile] = Field(default_factory=list)


class ParserResponse(StrictModel):
    schema_version: Literal[1] = 1
    files: list[ParserFileResult] = Field(default_factory=list)
    errors: list[AnalysisError] = Field(default_factory=list)


class ParsedFile(StrictModel):
    """Internal join of parser facts with the source needed by rules."""

    path: str
    language: str
    facts: FileFacts
    source: str | None = None

    def line_text(self, line: int) -> str:
        """Return a single source line (1-based), or an empty string."""

        if not self.source or line < 1:
            return ""
        lines = self.source.splitlines()
        if line > len(lines):
            return ""
        return lines[line - 1]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def utc_now_iso(clock: datetime | None = None) -> str:
    """Return an ISO-8601 UTC timestamp with a trailing ``Z``."""

    value = clock or datetime.now(timezone.utc)
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def fingerprint(rule_id: str, path: str, start_line: int, pattern: str) -> str:
    """Stable, secret-free fingerprint.

    Spec v1 decision: hash ``rule_id + path + start_line + pattern`` rather than
    raw source text. This avoids leaking secrets into artifacts/baselines and
    keeps fingerprints stable when surrounding code moves.
    """

    material = f"cqa:v1|{rule_id}|{path}|{start_line}|{pattern}"
    digest = hashlib.sha256(material.encode("utf-8")).hexdigest()[:16]
    return f"cqa:v1:{digest}"


def sort_findings(findings: list[Finding]) -> list[Finding]:
    """Sort by severity desc, path asc, line asc, rule_id asc (deterministic)."""

    return sorted(
        findings,
        key=lambda finding: (
            SEVERITY_ORDER[finding.severity],
            finding.path,
            finding.start_line,
            finding.start_col,
            finding.rule_id,
        ),
    )
