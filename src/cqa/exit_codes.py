"""Process exit codes and the exception hierarchy that maps onto them.

CI treats ``1`` as a quality gate and ``2``-``5`` as infrastructure failures, so
the mapping must never depend on Click's or Python's default exit codes.
"""

from __future__ import annotations

from enum import IntEnum


class ExitCode(IntEnum):
    OK = 0
    FINDINGS = 1
    USAGE = 2
    IO = 3
    PARSER = 4
    TIMEOUT = 5
    SIGINT = 130


class CqaError(Exception):
    """Base class for expected, user-facing failures.

    The CLI catches these, prints ``message`` without a traceback, and exits with
    ``exit_code``. Unexpected exceptions keep their traceback under ``--verbose``.
    """

    exit_code: ExitCode = ExitCode.USAGE

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


class UsageError(CqaError):
    """Invalid arguments or invalid configuration."""

    exit_code = ExitCode.USAGE


class IoError(CqaError):
    """Missing path, permission problem, or failed write."""

    exit_code = ExitCode.IO


class ParserError(CqaError):
    """The parser subprocess crashed or returned an unusable response."""

    exit_code = ExitCode.PARSER


class ParserTimeout(CqaError):
    """The parser subprocess exceeded its hard timeout."""

    exit_code = ExitCode.TIMEOUT


class Interrupted(CqaError):
    """SIGINT / keyboard interrupt."""

    exit_code = ExitCode.SIGINT
