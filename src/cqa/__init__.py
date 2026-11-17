"""Code Quality Analyzer (cqa).

Python owns orchestration, configuration, scoring, reporting, and exit codes.
TypeScript owns syntax parsing and emits facts over a JSON IPC bridge.
"""

from .version import SCHEMA_VERSION, TOOL_VERSION

__all__ = ["SCHEMA_VERSION", "TOOL_VERSION"]
__version__ = TOOL_VERSION
