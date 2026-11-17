"""Parser adapters: Node bridge (production) and AST fallback (optional)."""

from .fallback_python import FallbackParser
from .node_bridge import NodeParser, create_parser, resolve_parser_command
from .protocol import ParserOutcome, ParserPort

__all__ = [
    "FallbackParser",
    "NodeParser",
    "ParserOutcome",
    "ParserPort",
    "create_parser",
    "resolve_parser_command",
]
