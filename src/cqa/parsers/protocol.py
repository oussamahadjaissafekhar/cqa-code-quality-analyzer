"""Parser port: the seam between Python orchestration and syntax parsing.

Implementations must isolate per-file failures and return facts only. They may
not compute severities, read configuration, or format reports.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol

from ..models import AnalysisError, ParsedFile, ParserFile


@dataclass
class ParserOutcome:
    files: list[ParsedFile] = field(default_factory=list)
    errors: list[AnalysisError] = field(default_factory=list)
    parser_version: str = "unknown"


class ParserPort(Protocol):
    parser_version: str

    def parse(self, files: list[ParserFile]) -> ParserOutcome: ...
