"""Integration test for the Node bridge. Skipped when the parser is not built."""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from cqa.models import ParserFile
from cqa.parsers.node_bridge import NodeParser

REPO_ROOT = Path(__file__).resolve().parents[3]
PARSER = REPO_ROOT / "packages" / "parser-cli" / "dist" / "main.js"

pytestmark = pytest.mark.skipif(
    not PARSER.is_file() or shutil.which("node") is None,
    reason="parser-cli is not built or Node is unavailable (run npm run build)",
)


def test_node_parser_returns_facts_and_versions() -> None:
    parser = NodeParser([shutil.which("node") or "node", str(PARSER)], timeout_s=30, jobs=2)
    source = (
        "import { exec } from 'child_process';\n"
        "const key = 'AKIAIOSFODNN7EXAMPLE';\n"
        "export function run(command) {\n"
        "  child_process.exec(command);\n"
        "  if (command) { return eval(command); }\n"
        "  return key;\n"
        "}\n"
    )
    outcome = parser.parse(
        [ParserFile(path="sample.ts", language="typescript", content=source)]
    )
    assert outcome.errors == []
    assert len(outcome.files) == 1
    facts = outcome.files[0].facts
    assert any(item.from_ == "child_process" for item in facts.imports)
    assert any(call.callee.endswith("exec") for call in facts.calls)
    assert any(call.callee == "eval" for call in facts.calls)
    assert any(literal.value.startswith("AKIA") for literal in facts.literals)
    assert any(function.complexity >= 2 for function in facts.functions)
    assert outcome.parser_version


def test_node_parser_isolates_bad_files(tmp_path: Path) -> None:
    parser = NodeParser([shutil.which("node") or "node", str(PARSER)], timeout_s=30, jobs=1)
    outcome = parser.parse(
        [
            ParserFile(path="good.py", language="python", content="x = 1\n"),
            ParserFile(path=str(tmp_path / "missing.py"), language="python"),
        ]
    )
    assert len(outcome.files) == 2
    assert outcome.errors
    assert any(error.path.endswith("missing.py") for error in outcome.errors)
