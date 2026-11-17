"""Bridge to the TypeScript parser CLI.

Contract: one JSON ``ParserRequest`` on stdin, one JSON ``ParserResponse`` on
stdout. No shell is ever used (argument lists only), stderr is forwarded at
DEBUG, and the hard timeout maps to exit code 5.

Binary resolution (spec §5.1):
1. ``--parser-bin``
2. ``CQA_PARSER_BIN``
3. ``packages/parser-cli/dist/main.js`` in a source checkout
4. ``/opt/cqa/parser-cli.js`` in the container image

If none exists and the caller allows a fallback, the AST fallback parser is used
with a warning. An explicitly requested binary that is missing is always a
parser error (exit 4).
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

from ..exit_codes import CqaError, ParserError, ParserTimeout
from ..logging import get_logger
from ..models import AnalysisError, ParsedFile, ParserFile, ParserRequest, ParserResponse
from ..version import parser_version
from .fallback_python import FallbackParser
from .protocol import ParserOutcome, ParserPort

LOGGER = get_logger("parsers.bridge")
PARSER_SCRIPT_SUFFIXES = {".js", ".cjs", ".mjs"}


def _repo_parser_candidate() -> Path:
    # src/cqa/parsers/node_bridge.py -> repository root
    return Path(__file__).resolve().parents[3] / "packages" / "parser-cli" / "dist" / "main.js"


def _cwd_parser_candidate() -> Path:
    return Path.cwd() / "packages" / "parser-cli" / "dist" / "main.js"


def _resolve_command(path: Path) -> list[str]:
    """Turn a parser path into an argv list without invoking a shell."""

    if path.suffix.lower() in PARSER_SCRIPT_SUFFIXES:
        node = shutil.which("node")
        if node is None:
            raise ParserError(
                "Node.js was not found on PATH; install Node 20+ or pass a parser binary"
            )
        return [node, str(path)]
    return [str(path)]


def resolve_parser_command(explicit: str | None = None) -> list[str] | None:
    """Resolve the parser argv, or None when no bundled parser is available."""

    requested = explicit or os.environ.get("CQA_PARSER_BIN")
    if requested:
        path = Path(requested).expanduser()
        if not path.is_file():
            raise ParserError(f"parser binary not found: {path}")
        return _resolve_command(path)

    for candidate in (
        _cwd_parser_candidate(),
        _repo_parser_candidate(),
        Path("/opt/cqa/parser-cli.js"),
    ):
        if candidate.is_file():
            try:
                return _resolve_command(candidate)
            except ParserError:
                LOGGER.warning("parser %s found but Node is unavailable", candidate)
                return None
    return None


class NodeParser:
    """Subprocess-backed parser implementing :class:`ParserPort`."""

    def __init__(self, command: list[str], timeout_s: int, jobs: int) -> None:
        self.command = command
        self.timeout_s = timeout_s
        self.jobs = max(1, jobs)
        self.parser_version = parser_version()

    def parse(self, files: list[ParserFile]) -> ParserOutcome:
        request = ParserRequest(
            schema_version=1,
            jobs=self.jobs,
            files=files,
        )
        payload = request.model_dump(mode="json", by_alias=True, exclude_none=True)
        try:
            completed = subprocess.run(
                self.command,
                input=json.dumps(payload),
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=self.timeout_s,
                check=False,
                shell=False,
            )
        except subprocess.TimeoutExpired as exc:
            raise ParserTimeout(
                f"parser exceeded the {self.timeout_s}s timeout"
            ) from exc
        except OSError as exc:
            raise ParserError(f"cannot start parser: {exc}") from exc

        if completed.stderr.strip():
            LOGGER.debug("parser stderr: %s", completed.stderr.strip())

        if completed.returncode != 0:
            tail = (completed.stderr or completed.stdout).strip()[-2000:]
            raise ParserError(
                f"parser exited with code {completed.returncode}"
                + (f": {tail}" if tail else "")
            )

        try:
            payload_response = json.loads(completed.stdout)
        except json.JSONDecodeError as exc:
            raise ParserError(f"invalid parser response: {exc}") from exc
        try:
            response = ParserResponse.model_validate(payload_response)
        except Exception as exc:  # pydantic validation details are useful in logs
            raise ParserError(f"parser response failed validation: {exc}") from exc

        return self._to_outcome(files, response)

    def _to_outcome(self, requested: list[ParserFile], response: ParserResponse) -> ParserOutcome:
        by_path = {item.path: item for item in response.files}
        outcome = ParserOutcome(
            errors=list(response.errors),
            parser_version=self.parser_version,
        )
        for file in requested:
            item = by_path.get(file.path)
            if item is None:
                outcome.errors.append(
                    AnalysisError(
                        path=file.path,
                        message="parser did not return a result for this file",
                        kind="internal",
                    )
                )
                outcome.files.append(
                    ParsedFile(
                        path=file.path,
                        language=file.language,
                        facts=_empty_facts(),
                        source=file.content,
                    )
                )
                continue
            if not item.ok:
                outcome.errors.append(
                    AnalysisError(
                        path=file.path,
                        message=item.error or "parser reported a failure",
                        kind="parse",
                    )
                )
            outcome.files.append(
                ParsedFile(
                    path=file.path,
                    language=file.language,
                    facts=item.facts,
                    source=file.content,
                )
            )
        return outcome


def _empty_facts():
    from ..models import FileFacts

    return FileFacts()


def create_parser(
    explicit_bin: str | None,
    timeout_s: int,
    jobs: int,
    *,
    allow_fallback: bool = True,
) -> ParserPort:
    """Build the Node bridge, or the pure-Python fallback when appropriate."""

    command = resolve_parser_command(explicit_bin)
    if command is not None:
        return NodeParser(command, timeout_s=timeout_s, jobs=jobs)
    if allow_fallback:
        LOGGER.warning(
            "parser-cli not found (run `npm install && npm run build`); "
            "using the Python fallback parser"
        )
        return FallbackParser()
    raise CqaError("parser-cli not found and fallback is disabled")
