"""Edge-case coverage for the pure-Python fallback parser."""

from __future__ import annotations

from cqa.models import ParserFile
from cqa.parsers.fallback_python import PARSER_VERSION, FallbackParser


def parse_one(language: str, source: str, path: str = "sample"):
    outcome = FallbackParser().parse([ParserFile(path=path, language=language, content=source)])
    assert len(outcome.files) == 1
    return outcome.files[0], outcome.errors


def test_empty_batch_returns_empty_outcome() -> None:
    outcome = FallbackParser().parse([])
    assert outcome.files == []
    assert outcome.errors == []
    assert outcome.parser_version == PARSER_VERSION


def test_empty_and_whitespace_files_are_valid() -> None:
    for source in ("", "   \n\t\r\n", "# only a comment\n"):
        file, errors = parse_one("python", source)
        assert errors == []
        assert file.facts.imports == []
        assert file.facts.calls == []
        assert file.facts.literals == []
        assert file.facts.functions == []


def test_missing_content_is_treated_as_empty() -> None:
    outcome = FallbackParser().parse(
        [ParserFile(path="empty.py", language="python", content=None)]
    )
    assert outcome.errors == []
    assert outcome.files[0].facts == outcome.files[0].facts.__class__()
    assert outcome.files[0].source == ""


def test_malformed_python_is_isolated_per_file() -> None:
    outcome = FallbackParser().parse(
        [
            ParserFile(path="broken.py", language="python", content="def broken(:\n    pass\n"),
            ParserFile(path="fine.py", language="python", content="eval(user)\n"),
        ]
    )

    assert [file.path for file in outcome.files] == ["broken.py", "fine.py"]
    assert [error.path for error in outcome.errors] == ["broken.py"]
    assert outcome.errors[0].kind == "parse"
    assert "SyntaxError" in outcome.errors[0].message
    # The broken file still yields an empty, schema-valid fact set.
    assert outcome.files[0].facts.calls == []
    # The following file is unaffected.
    assert outcome.files[1].facts.calls[0].callee == "eval"
    assert outcome.files[1].source == "eval(user)\n"


def test_python_argument_classification() -> None:
    source = (
        "eval()\n"
        "eval('literal')\n"
        "eval(user)\n"
        "call('literal', user)\n"
        "call(*args)\n"
        "call(1, 2, -3, True, None)\n"
        "call(**kwargs)\n"
        "query(sql='SELECT 1')\n"
    )
    file, errors = parse_one("python", source)
    assert errors == []

    kinds = [(call.callee, call.args_kind) for call in file.facts.calls]
    assert kinds == [
        ("eval", "empty"),
        ("eval", "literal"),
        ("eval", "dynamic"),
        ("call", "mixed"),
        ("call", "dynamic"),
        ("call", "literal"),
        ("call", "dynamic"),
        ("query", "literal"),
    ]


def test_python_imports_and_literals() -> None:
    source = (
        "import os, sys as system\n"
        "from . import local\n"
        "from ..pkg import thing as alias\n"
        "from mod import *\n"
        'plain = "value"\n'
        'formatted = f"hello {name}"\n'
        "raw = b'bytes'\n"
    )
    file, errors = parse_one("python", source)
    assert errors == []

    imports = {(item.from_, tuple(item.names), item.line) for item in file.facts.imports}
    assert imports == {
        ("os", ("os",), 1),
        ("sys", ("system",), 1),
        (".", ("local",), 2),
        ("..pkg", ("alias",), 3),
        ("mod", ("*",), 4),
    }

    literals = {(item.value, item.kind) for item in file.facts.literals}
    assert ("value", "string") in literals
    assert ("hello {}", "template") in literals
    # Bytes constants are intentionally not string literals.
    assert all(item.value != "bytes" for item in file.facts.literals)


def test_python_complexity_does_not_descend_into_nested_functions() -> None:
    source = (
        "def outer(a, b):\n"
        "    if a:\n"
        "        return a and b\n"
        "    def inner(c):\n"
        "        if c:\n"
        "            return 1\n"
        "        return 0\n"
        "    return inner(a)\n"
        "\n"
        "async def worker(items):\n"
        "    for item in items:\n"
        "        while item:\n"
        "            item -= 1\n"
    )
    file, errors = parse_one("python", source)
    assert errors == []
    functions = {item.name: item.complexity for item in file.facts.functions}
    # outer: 1 + if + boolean operator = 3 (nested def is not counted).
    assert functions["outer"] == 3
    assert functions["inner"] == 2
    assert functions["worker"] == 3


def test_javascript_empty_comment_and_malformed_sources() -> None:
    for source in ("", "   \n", "// comment\n/* block */\n", "/* never closed\nconst x = 1;\n"):
        file, errors = parse_one("javascript", source, "sample.js")
        assert errors == []
        assert file.facts.calls == []


def test_javascript_unterminated_string_does_not_raise() -> None:
    file, errors = parse_one("javascript", "const value = 'unterminated\n", "broken.js")
    assert errors == []
    assert any(item.value.startswith("unterminated") for item in file.facts.literals)


def test_javascript_calls_are_masked_and_classified() -> None:
    source = (
        "const text = \"eval(user)\";\n"
        "eval();\n"
        "eval('literal');\n"
        "eval(user);\n"
        "eval('literal', user);\n"
        "if (user) { child_process.exec(user); }\n"
    )
    file, errors = parse_one("javascript", source, "app.js")
    assert errors == []

    calls = [(call.callee, call.args_kind) for call in file.facts.calls]
    assert calls == [
        ("eval", "empty"),
        ("eval", "literal"),
        ("eval", "dynamic"),
        ("eval", "mixed"),
        ("child_process.exec", "dynamic"),
    ]


def test_javascript_imports_require_and_functions() -> None:
    source = (
        "import { exec } from 'child_process';\n"
        "import fs from 'fs';\n"
        "import 'side-effect';\n"
        "const legacy = require('legacy');\n"
        "export function declared(a) { if (a) { return 1; } return 0; }\n"
        "const arrow = (a) => { if (a) { return 1; } return 0; };\n"
        "class Box {\n"
        "  method(a) { for (;;) { break; } }\n"
        "}\n"
    )
    file, errors = parse_one("javascript", source, "app.js")
    assert errors == []

    imports = {(item.from_, tuple(item.names)) for item in file.facts.imports}
    assert ("child_process", ("exec",)) in imports
    assert ("fs", ("fs",)) in imports
    assert ("side-effect", ()) in imports
    assert ("legacy", ("legacy",)) in imports

    names = {item.name for item in file.facts.functions}
    assert {"declared", "arrow", "method"} <= names
    assert all(item.complexity >= 2 for item in file.facts.functions)


def test_typescript_uses_the_javascript_heuristics() -> None:
    file, errors = parse_one("typescript", "export const f = (v: string) => eval(v);\n", "a.ts")
    assert errors == []
    assert any(call.callee == "eval" for call in file.facts.calls)


def test_container_literals_are_classified_as_literal() -> None:
    file, errors = parse_one(
        "python", "call([1, 2], (3, 4), {5, 6}, {'a': 1}, [])\n"
    )
    assert errors == []
    assert file.facts.calls[0].args_kind == "literal"


def test_python_comprehension_and_match_complexity() -> None:
    source = (
        "def comp(xs):\n"
        "    return [x for x in xs if x > 0]\n"
        "\n"
        "def matcher(value):\n"
        "    match value:\n"
        "        case 1:\n"
        "            return 'one'\n"
        "        case 2:\n"
        "            return 'two'\n"
        "        case _:\n"
        "            return 'many'\n"
    )
    file, errors = parse_one("python", source)
    assert errors == []
    functions = {item.name: item.complexity for item in file.facts.functions}
    assert functions["comp"] == 3  # 1 + comprehension + if filter
    assert functions["matcher"] == 3  # 1 + (3 cases - 1)


def test_unexpected_parser_failure_is_isolated(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    def explode(source):  # type: ignore[no-untyped-def]
        raise RuntimeError("unexpected parser failure")

    monkeypatch.setattr("cqa.parsers.fallback_python._python_facts", explode)
    outcome = FallbackParser().parse(
        [ParserFile(path="a.py", language="python", content="x = 1\n")]
    )
    assert outcome.files[0].facts.calls == []
    assert outcome.errors[0].kind == "internal"
    assert "unexpected parser failure" in outcome.errors[0].message
