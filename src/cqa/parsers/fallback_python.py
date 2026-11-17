"""AST-based fallback parser used when the Node parser is unavailable.

The fallback exists so ``cqa`` remains useful in a bare Python environment. It
is intentionally conservative:

* Python uses the standard library ``ast`` module (accurate).
* JavaScript/TypeScript use a masked-source heuristic (comments and strings are
  blanked before call/function extraction).

It returns the same facts shape as the TypeScript parser and never raises past a
single file. The Node parser remains the production path.
"""

from __future__ import annotations

import ast
import re
from bisect import bisect_right
from typing import Literal

from ..logging import get_logger
from ..models import (
    AnalysisError,
    CallFact,
    FileFacts,
    FunctionFact,
    ImportFact,
    LiteralFact,
    ParsedFile,
    ParserFile,
)
from .protocol import ParserOutcome

LOGGER = get_logger("parsers.fallback")
PARSER_VERSION = "python-fallback-1"

ArgsKind = Literal["empty", "literal", "dynamic", "mixed"]

JS_KEYWORDS = {
    "if",
    "for",
    "while",
    "switch",
    "catch",
    "function",
    "return",
    "typeof",
    "new",
    "delete",
    "void",
    "in",
    "of",
    "do",
    "else",
    "try",
    "throw",
    "await",
    "yield",
    "super",
    "import",
    "require",
}

CALL_RE = re.compile(
    r"([A-Za-z_$][\w$]*(?:\s*\.\s*[A-Za-z_$][\w$]*)*)\s*\("
)
IMPORT_FROM_RE = re.compile(
    r"^\s*import\s+(?P<clause>.+?)\s+from\s+['\"](?P<source>[^'\"]+)['\"]", re.MULTILINE
)
IMPORT_SIDE_EFFECT_RE = re.compile(r"^\s*import\s+['\"](?P<source>[^'\"]+)['\"]", re.MULTILINE)
REQUIRE_RE = re.compile(
    r"(?:const|let|var)\s+(?P<clause>[^=]+?)=\s*require\(\s*['\"](?P<source>[^'\"]+)['\"]\s*\)"
)
FUNCTION_RE = re.compile(r"\bfunction\s+([A-Za-z_$][\w$]*)\s*\(")
ARROW_RE = re.compile(
    r"\b(?:const|let|var)\s+([A-Za-z_$][\w$]*)\s*=\s*(?:async\s*)?(?:\([^)]*\)|[A-Za-z_$][\w$]*)\s*=>"
)
METHOD_RE = re.compile(
    r"^\s*(?:public|private|protected|static|async\s+)*([A-Za-z_$][\w$]*)\s*\([^)]*\)\s*\{",
    re.MULTILINE,
)
BRANCH_RE = re.compile(r"\b(?:if|for|while|case|catch)\b|&&|\|\||\?\?|\?(?![.?])")


# ---------------------------------------------------------------------------
# Python AST extraction
# ---------------------------------------------------------------------------


def _dotted_name(node: ast.AST) -> str | None:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        base = _dotted_name(node.value)
        return f"{base}.{node.attr}" if base else node.attr
    return None


def _is_literal_node(node: ast.AST) -> bool:
    if isinstance(node, ast.Constant):
        return isinstance(node.value, (str, int, float, bool)) or node.value is None
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.USub, ast.UAdd)):
        return isinstance(node.operand, ast.Constant)
    if isinstance(node, (ast.List, ast.Tuple, ast.Set, ast.Dict)):
        values = (
            node.elts
            if isinstance(node, (ast.List, ast.Tuple, ast.Set))
            else [value for value in node.values if value is not None]
        )
        return all(_is_literal_node(value) for value in values)
    return False


def _args_kind(call: ast.Call) -> ArgsKind:
    args: list[ast.AST] = list(call.args)
    args.extend(keyword.value for keyword in call.keywords)
    if not args:
        return "empty"
    if any(isinstance(arg, ast.Starred) for arg in call.args):
        return "dynamic"
    literal = sum(1 for arg in args if _is_literal_node(arg))
    if literal == len(args):
        return "literal"
    if literal:
        return "mixed"
    return "dynamic"


class _ComplexityVisitor(ast.NodeVisitor):
    """Cyclomatic complexity, not descending into nested functions/classes."""

    def __init__(self) -> None:
        self.score = 1

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:  # noqa: N802
        return

    visit_AsyncFunctionDef = visit_FunctionDef  # type: ignore[assignment]
    visit_Lambda = visit_FunctionDef  # type: ignore[assignment]
    visit_ClassDef = visit_FunctionDef  # type: ignore[assignment]

    def visit_If(self, node: ast.If) -> None:  # noqa: N802
        self.score += 1
        self.generic_visit(node)

    visit_IfExp = visit_If  # type: ignore[assignment]
    visit_For = visit_If  # type: ignore[assignment]
    visit_AsyncFor = visit_If  # type: ignore[assignment]
    visit_While = visit_If  # type: ignore[assignment]
    visit_ExceptHandler = visit_If  # type: ignore[assignment]
    visit_Assert = visit_If  # type: ignore[assignment]
    visit_With = visit_If  # type: ignore[assignment]
    visit_AsyncWith = visit_If  # type: ignore[assignment]

    def visit_BoolOp(self, node: ast.BoolOp) -> None:  # noqa: N802
        self.score += max(0, len(node.values) - 1)
        self.generic_visit(node)

    def visit_comprehension(self, node: ast.comprehension) -> None:  # noqa: N802
        self.score += 1 + len(node.ifs)
        self.generic_visit(node)

    def visit_Match(self, node: ast.Match) -> None:  # noqa: N802
        self.score += max(0, len(node.cases) - 1)
        self.generic_visit(node)


def _function_complexity(node: ast.FunctionDef | ast.AsyncFunctionDef) -> int:
    visitor = _ComplexityVisitor()
    for statement in node.body:
        visitor.visit(statement)
    return visitor.score


def _python_facts(source: str) -> FileFacts:
    tree = ast.parse(source)
    imports: list[ImportFact] = []
    calls: list[CallFact] = []
    literals: list[LiteralFact] = []
    functions: list[FunctionFact] = []

    class Visitor(ast.NodeVisitor):
        def visit_Import(self, node: ast.Import) -> None:  # noqa: N802
            for alias in node.names:
                imports.append(
                    ImportFact.model_validate(
                        {
                            "from": alias.name,
                            "names": [alias.asname or alias.name.split(".")[-1]],
                            "line": node.lineno,
                        }
                    )
                )
            self.generic_visit(node)

        def visit_ImportFrom(self, node: ast.ImportFrom) -> None:  # noqa: N802
            module = "." * (node.level or 0) + (node.module or "")
            names = [alias.asname or alias.name for alias in node.names if alias.name != "*"]
            imports.append(
                ImportFact.model_validate(
                    {"from": module, "names": names or ["*"], "line": node.lineno}
                )
            )
            self.generic_visit(node)

        def visit_Call(self, node: ast.Call) -> None:  # noqa: N802
            callee = _dotted_name(node.func)
            if callee:
                calls.append(
                    CallFact(
                        callee=callee,
                        line=node.lineno,
                        col=node.col_offset + 1,
                        args_kind=_args_kind(node),
                    )
                )
            self.generic_visit(node)

        def visit_Constant(self, node: ast.Constant) -> None:  # noqa: N802
            if isinstance(node.value, str):
                literals.append(
                    LiteralFact(
                        value=node.value[:120],
                        line=node.lineno,
                        col=node.col_offset + 1,
                        kind="string",
                    )
                )
            self.generic_visit(node)

        def visit_JoinedStr(self, node: ast.JoinedStr) -> None:  # noqa: N802
            parts: list[str] = []
            for value in node.values:
                if isinstance(value, ast.Constant) and isinstance(value.value, str):
                    parts.append(value.value)
                elif isinstance(value, ast.FormattedValue):
                    parts.append("{}")
            literals.append(
                LiteralFact(
                    value="".join(parts)[:120],
                    line=node.lineno,
                    col=node.col_offset + 1,
                    kind="template",
                )
            )
            self.generic_visit(node)

        def visit_FunctionDef(self, node: ast.FunctionDef) -> None:  # noqa: N802
            functions.append(
                FunctionFact(
                    name=node.name, line=node.lineno, complexity=_function_complexity(node)
                )
            )
            self.generic_visit(node)

        visit_AsyncFunctionDef = visit_FunctionDef  # type: ignore[assignment]

    Visitor().visit(tree)
    return FileFacts(imports=imports, calls=calls, literals=literals, functions=functions)


# ---------------------------------------------------------------------------
# JavaScript / TypeScript heuristic extraction
# ---------------------------------------------------------------------------


class _Token:
    __slots__ = ("start", "end", "kind", "value")

    def __init__(self, start: int, end: int, kind: str, value: str) -> None:
        self.start = start
        self.end = end
        self.kind = kind
        self.value = value


def _scan_js(source: str) -> tuple[str, list[_Token]]:
    """Return a masked source (strings/comments blanked) and string tokens."""

    chars = list(source)
    tokens: list[_Token] = []
    index = 0
    length = len(source)
    while index < length:
        char = source[index]
        nxt = source[index + 1] if index + 1 < length else ""

        if char == "/" and nxt == "/":
            end = source.find("\n", index)
            end = length if end == -1 else end
            for pos in range(index, end):
                chars[pos] = " "
            index = end
            continue
        if char == "/" and nxt == "*":
            end = source.find("*/", index + 2)
            end = length if end == -1 else end + 2
            for pos in range(index, end):
                if chars[pos] != "\n":
                    chars[pos] = " "
            index = end
            continue
        if char in {"'", '"', "`"}:
            quote = char
            start = index
            index += 1
            value_chars: list[str] = []
            while index < length:
                current = source[index]
                if current == "\\" and index + 1 < length:
                    value_chars.append(source[index + 1])
                    index += 2
                    continue
                if current == quote:
                    index += 1
                    break
                value_chars.append(current)
                index += 1
            end = index
            kind = "template" if quote == "`" else "string"
            tokens.append(_Token(start, end, kind, "".join(value_chars)))
            for pos in range(start, end):
                if chars[pos] != "\n":
                    chars[pos] = " "
            continue
        index += 1
    return "".join(chars), tokens


def _line_starts(source: str) -> list[int]:
    starts = [0]
    for match in re.finditer("\n", source):
        starts.append(match.end())
    return starts


def _line_col(starts: list[int], index: int) -> tuple[int, int]:
    line_index = bisect_right(starts, index) - 1
    return line_index + 1, index - starts[line_index] + 1


def _matching_brace(masked: str, open_index: int) -> int:
    depth = 0
    for index in range(open_index, len(masked)):
        char = masked[index]
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return index
    return len(masked) - 1


def _js_literal_segment(
    masked: str, start: int, end: int, strings: list[_Token]
) -> ArgsKind | None:
    """Classify one JS argument; ``None`` means the segment is blank."""

    text = masked[start:end].strip()
    segment_strings = [token for token in strings if token.start >= start and token.end <= end]
    if not text and not segment_strings:
        return None
    if text.startswith("*") or text.startswith("..."):
        return "dynamic"

    # Strings are blanked in ``masked``; only their captured spans survive.
    if segment_strings:
        if any(token.kind == "template" and "${" in token.value for token in segment_strings):
            return "dynamic"
        return "literal" if not re.search(r"[A-Za-z_$]", text) else "dynamic"

    without_keywords = re.sub(r"\b(?:true|false|null|undefined)\b", "", text)
    if re.search(r"[A-Za-z_$]", without_keywords):
        return "dynamic"
    return "literal"


def _js_args_kind(
    masked: str, open_index: int, strings: list[_Token]
) -> tuple[ArgsKind, int]:
    """Return (args_kind, end_index) for the call whose ``(`` is at open_index."""

    depth = 1
    index = open_index + 1
    while index < len(masked) and depth:
        char = masked[index]
        if char == "(":
            depth += 1
        elif char == ")":
            depth -= 1
        index += 1
    end = index - 1

    kinds: list[ArgsKind] = []
    depth = 0
    segment_start = open_index + 1
    for position in range(open_index + 1, end):
        char = masked[position]
        if char in "([{":
            depth += 1
        elif char in ")]}":
            depth = max(0, depth - 1)
        elif char == "," and depth == 0:
            kind = _js_literal_segment(masked, segment_start, position, strings)
            if kind is not None:
                kinds.append(kind)
            segment_start = position + 1
    last = _js_literal_segment(masked, segment_start, end, strings)
    if last is not None:
        kinds.append(last)

    if not kinds:
        return "empty", end
    if all(kind == "literal" for kind in kinds):
        return "literal", end
    if all(kind == "dynamic" for kind in kinds):
        return "dynamic", end
    return "mixed", end


def _parse_import_names(clause: str) -> list[str]:
    names: list[str] = []
    cleaned = clause.replace("{", " ").replace("}", " ")
    for part in cleaned.split(","):
        candidate = part.strip().split(" as ")[0].strip()
        if not candidate or candidate == "*":
            continue
        candidate = candidate.split(".")[0].strip()
        if re.fullmatch(r"[A-Za-z_$][\w$]*", candidate):
            names.append(candidate)
    return names


def _js_facts(source: str) -> FileFacts:
    masked, string_tokens = _scan_js(source)
    starts = _line_starts(source)

    imports: list[ImportFact] = []
    # Imports are detected on the original source because module specifiers are
    # string literals (and therefore blanked in the masked copy). Regexes are
    # line/statement anchored to keep comment false positives rare.
    for match in IMPORT_FROM_RE.finditer(source):
        line, _ = _line_col(starts, match.start())
        imports.append(
            ImportFact.model_validate(
                {
                    "from": match.group("source"),
                    "names": _parse_import_names(match.group("clause")),
                    "line": line,
                }
            )
        )
    for match in IMPORT_SIDE_EFFECT_RE.finditer(source):
        line, _ = _line_col(starts, match.start())
        imports.append(
            ImportFact.model_validate({"from": match.group("source"), "names": [], "line": line})
        )
    for match in REQUIRE_RE.finditer(source):
        line, _ = _line_col(starts, match.start())
        imports.append(
            ImportFact.model_validate(
                {
                    "from": match.group("source"),
                    "names": _parse_import_names(match.group("clause")),
                    "line": line,
                }
            )
        )

    calls: list[CallFact] = []
    for match in CALL_RE.finditer(masked):
        callee = re.sub(r"\s+", "", match.group(1))
        if not callee or callee.split(".")[-1] in JS_KEYWORDS:
            continue
        open_index = match.end() - 1
        args_kind, _ = _js_args_kind(masked, open_index, string_tokens)
        line, col = _line_col(starts, match.start(1))
        calls.append(CallFact(callee=callee, line=line, col=col, args_kind=args_kind))

    literals: list[LiteralFact] = []
    for token in string_tokens:
        line, col = _line_col(starts, token.start)
        literals.append(
            LiteralFact(value=token.value[:120], line=line, col=col, kind=token.kind)  # type: ignore[arg-type]
        )

    functions: list[FunctionFact] = []
    for name, match in [
        (match.group(1), match) for match in FUNCTION_RE.finditer(masked)
    ]:
        line, _ = _line_col(starts, match.start())
        brace = masked.find("{", match.end())
        body_end = _matching_brace(masked, brace) if brace != -1 else match.end()
        complexity = 1 + len(BRANCH_RE.findall(masked[match.end() : body_end]))
        functions.append(FunctionFact(name=name, line=line, complexity=complexity))

    for match in ARROW_RE.finditer(masked):
        name = match.group(1)
        line, _ = _line_col(starts, match.start())
        brace = masked.find("{", match.end())
        if brace != -1 and masked[match.end() : brace].strip() == "":
            body_end = _matching_brace(masked, brace)
            complexity = 1 + len(BRANCH_RE.findall(masked[brace:body_end]))
        else:
            semicolon = masked.find(";", match.end())
            body_end = semicolon if semicolon != -1 else match.end()
            complexity = 1 + len(BRANCH_RE.findall(masked[match.end() : body_end]))
        functions.append(FunctionFact(name=name, line=line, complexity=complexity))

    for match in METHOD_RE.finditer(masked):
        name = match.group(1)
        if name in JS_KEYWORDS or name in {"constructor"}:
            continue
        line, _ = _line_col(starts, match.start())
        brace = match.end() - 1
        body_end = _matching_brace(masked, brace)
        complexity = 1 + len(BRANCH_RE.findall(masked[brace:body_end]))
        functions.append(FunctionFact(name=name, line=line, complexity=complexity))

    return FileFacts(imports=imports, calls=calls, literals=literals, functions=functions)


class FallbackParser:
    """Pure-Python parser implementing :class:`ParserPort`."""

    parser_version = PARSER_VERSION

    def parse(self, files: list[ParserFile]) -> ParserOutcome:
        outcome = ParserOutcome(parser_version=self.parser_version)
        for file in files:
            source = file.content or ""
            try:
                facts = _python_facts(source) if file.language == "python" else _js_facts(source)
                outcome.files.append(
                    ParsedFile(path=file.path, language=file.language, facts=facts, source=source)
                )
            except (SyntaxError, ValueError, TypeError, RecursionError) as exc:
                outcome.errors.append(
                    AnalysisError(
                        path=file.path,
                        message=f"{type(exc).__name__}: {exc}",
                        kind="parse",
                    )
                )
                outcome.files.append(
                    ParsedFile(
                        path=file.path,
                        language=file.language,
                        facts=FileFacts(),
                        source=source,
                    )
                )
            except Exception as exc:  # never abort a batch for one file
                LOGGER.debug("fallback parser failed on %s: %s", file.path, exc)
                outcome.errors.append(
                    AnalysisError(path=file.path, message=str(exc), kind="internal")
                )
                outcome.files.append(
                    ParsedFile(
                        path=file.path,
                        language=file.language,
                        facts=FileFacts(),
                        source=source,
                    )
                )
        return outcome
