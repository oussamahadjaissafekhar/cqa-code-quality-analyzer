"""Node bridge unit tests (no real subprocess or Node.js required)."""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from cqa.exit_codes import CqaError, ParserError, ParserTimeout
from cqa.models import ParserFile
from cqa.parsers import node_bridge
from cqa.parsers.fallback_python import FallbackParser
from cqa.parsers.node_bridge import NodeParser, create_parser, resolve_parser_command


def parser_file(path: str = "a.py", content: str = "eval(x)\n") -> ParserFile:
    return ParserFile(path=path, language="python", content=content)


def response_payload(*, files=None, errors=None) -> dict:
    return {
        "schema_version": 1,
        "files": files
        if files is not None
        else [
            {
                "path": "a.py",
                "language": "python",
                "ok": True,
                "facts": {
                    "imports": [],
                    "calls": [
                        {"callee": "eval", "line": 1, "col": 1, "args_kind": "dynamic"}
                    ],
                    "literals": [],
                    "functions": [],
                },
            }
        ],
        "errors": errors or [],
    }


def fake_completed(stdout: str, *, returncode: int = 0, stderr: str = "") -> subprocess.CompletedProcess:
    return subprocess.CompletedProcess(["parser"], returncode, stdout=stdout, stderr=stderr)


# ---------------------------------------------------------------------------
# Resolution
# ---------------------------------------------------------------------------


def test_explicit_missing_binary_is_a_parser_error(tmp_path: Path) -> None:
    with pytest.raises(ParserError, match="parser binary not found"):
        resolve_parser_command(str(tmp_path / "missing.js"))


def test_explicit_script_requires_node(tmp_path: Path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    script = tmp_path / "parser.js"
    script.write_text("// parser\n", encoding="utf-8")
    monkeypatch.setattr(shutil, "which", lambda name: None)
    with pytest.raises(ParserError, match="Node.js was not found"):
        resolve_parser_command(str(script))


def test_explicit_script_uses_node_and_preserves_path(tmp_path: Path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    script = tmp_path / "parser.js"
    script.write_text("// parser\n", encoding="utf-8")
    monkeypatch.setattr(shutil, "which", lambda name: "node")
    assert resolve_parser_command(str(script)) == ["node", str(script)]


def test_explicit_native_binary_is_used_directly(tmp_path: Path) -> None:
    binary = tmp_path / "parser.exe"
    binary.write_bytes(b"")
    assert resolve_parser_command(str(binary)) == [str(binary)]


def test_environment_override(monkeypatch, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    binary = tmp_path / "parser-bin"
    binary.write_bytes(b"")
    monkeypatch.setenv("CQA_PARSER_BIN", str(binary))
    assert resolve_parser_command(None) == [str(binary)]


def test_no_candidates_returns_none(tmp_path: Path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.delenv("CQA_PARSER_BIN", raising=False)
    monkeypatch.setattr(node_bridge, "_cwd_parser_candidate", lambda: tmp_path / "a.js")
    monkeypatch.setattr(node_bridge, "_repo_parser_candidate", lambda: tmp_path / "b.js")
    monkeypatch.setattr(node_bridge.Path, "is_file", lambda self: False)
    assert resolve_parser_command(None) is None


def test_create_parser_falls_back_or_fails_closed(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setattr(node_bridge, "resolve_parser_command", lambda explicit: None)

    fallback = create_parser(None, timeout_s=1, jobs=1)
    assert isinstance(fallback, FallbackParser)

    with pytest.raises(CqaError, match="fallback is disabled"):
        create_parser(None, timeout_s=1, jobs=1, allow_fallback=False)


def test_create_parser_returns_a_node_parser_when_resolved(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setattr(node_bridge, "resolve_parser_command", lambda explicit: ["node", "x.js"])
    parser = create_parser(None, timeout_s=3, jobs=2)
    assert isinstance(parser, NodeParser)
    assert parser.command == ["node", "x.js"]


def test_discovered_parser_without_node_is_ignored(tmp_path: Path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.delenv("CQA_PARSER_BIN", raising=False)
    script = tmp_path / "main.js"
    script.write_text("// parser\n", encoding="utf-8")
    monkeypatch.setattr(node_bridge, "_cwd_parser_candidate", lambda: script)
    monkeypatch.setattr(node_bridge, "_repo_parser_candidate", lambda: script)
    monkeypatch.setattr(shutil, "which", lambda name: None)

    assert resolve_parser_command(None) is None


def test_candidate_helpers_point_into_the_checkout() -> None:
    assert node_bridge._cwd_parser_candidate().name == "main.js"
    assert node_bridge._repo_parser_candidate().name == "main.js"
    assert node_bridge._repo_parser_candidate().parts[-3:] == (
        "parser-cli",
        "dist",
        "main.js",
    )


# ---------------------------------------------------------------------------
# parse()
# ---------------------------------------------------------------------------


def test_parse_success_sends_content_and_maps_results(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    captured: dict = {}

    def fake_run(command, **kwargs):  # type: ignore[no-untyped-def]
        captured["command"] = command
        captured["kwargs"] = kwargs
        return fake_completed(json.dumps(response_payload()))

    monkeypatch.setattr(node_bridge.subprocess, "run", fake_run)
    parser = NodeParser(["node", "parser.js"], timeout_s=7, jobs=0)
    outcome = parser.parse([parser_file()])

    assert captured["command"] == ["node", "parser.js"]
    assert captured["kwargs"]["timeout"] == 7
    assert captured["kwargs"]["shell"] is False
    request = json.loads(captured["kwargs"]["input"])
    assert request["schema_version"] == 1
    assert request["jobs"] == 1  # clamped to a positive worker count
    assert request["files"] == [
        {"path": "a.py", "language": "python", "content": "eval(x)\n"}
    ]

    assert outcome.errors == []
    assert outcome.parser_version == parser.parser_version
    assert outcome.files[0].path == "a.py"
    assert outcome.files[0].source == "eval(x)\n"
    assert outcome.files[0].facts.calls[0].callee == "eval"


def test_parse_nonzero_exit_includes_stderr_tail(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setattr(
        node_bridge.subprocess,
        "run",
        lambda *args, **kwargs: fake_completed("", returncode=9, stderr="boom"),
    )
    with pytest.raises(ParserError, match="code 9: boom"):
        NodeParser(["parser"], timeout_s=1, jobs=1).parse([parser_file()])


def test_parse_timeout_maps_to_timeout_error(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    def timeout(*args, **kwargs):  # type: ignore[no-untyped-def]
        raise subprocess.TimeoutExpired(cmd="parser", timeout=2)

    monkeypatch.setattr(node_bridge.subprocess, "run", timeout)
    with pytest.raises(ParserTimeout, match="2s timeout"):
        NodeParser(["parser"], timeout_s=2, jobs=1).parse([parser_file()])


def test_parse_os_error_is_a_parser_error(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    def fail(*args, **kwargs):  # type: ignore[no-untyped-def]
        raise OSError("cannot execute")

    monkeypatch.setattr(node_bridge.subprocess, "run", fail)
    with pytest.raises(ParserError, match="cannot start parser"):
        NodeParser(["parser"], timeout_s=1, jobs=1).parse([parser_file()])


def test_parse_invalid_json_and_schema_are_parser_errors(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setattr(
        node_bridge.subprocess, "run", lambda *args, **kwargs: fake_completed("not json")
    )
    with pytest.raises(ParserError, match="invalid parser response"):
        NodeParser(["parser"], timeout_s=1, jobs=1).parse([parser_file()])

    bad_schema = {"schema_version": 2, "files": [], "errors": []}
    monkeypatch.setattr(
        node_bridge.subprocess,
        "run",
        lambda *args, **kwargs: fake_completed(json.dumps(bad_schema)),
    )
    with pytest.raises(ParserError, match="failed validation"):
        NodeParser(["parser"], timeout_s=1, jobs=1).parse([parser_file()])


def test_missing_result_becomes_internal_error_with_empty_facts(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setattr(
        node_bridge.subprocess,
        "run",
        lambda *args, **kwargs: fake_completed(json.dumps(response_payload(files=[]))),
    )
    outcome = NodeParser(["parser"], timeout_s=1, jobs=1).parse([parser_file("gone.py")])
    assert outcome.files[0].path == "gone.py"
    assert outcome.files[0].facts.calls == []
    assert outcome.errors[0].kind == "internal"
    assert "did not return a result" in outcome.errors[0].message


def test_failed_file_result_becomes_parse_error(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    payload = response_payload(
        files=[
            {
                "path": "a.py",
                "language": "python",
                "ok": False,
                "error": "SyntaxError: bad input",
                "facts": {"imports": [], "calls": [], "literals": [], "functions": []},
            }
        ]
    )
    monkeypatch.setattr(
        node_bridge.subprocess, "run", lambda *args, **kwargs: fake_completed(json.dumps(payload))
    )
    outcome = NodeParser(["parser"], timeout_s=1, jobs=1).parse([parser_file()])
    assert outcome.errors[0].kind == "parse"
    assert "SyntaxError" in outcome.errors[0].message
    assert outcome.files[0].facts.calls == []


def test_response_level_errors_are_preserved(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    payload = response_payload(
        errors=[{"path": "b.py", "message": "unreadable", "kind": "io"}]
    )
    monkeypatch.setattr(
        node_bridge.subprocess, "run", lambda *args, **kwargs: fake_completed(json.dumps(payload))
    )
    outcome = NodeParser(["parser"], timeout_s=1, jobs=1).parse([parser_file()])
    assert [error.path for error in outcome.errors] == ["b.py"]
    assert outcome.errors[0].kind == "io"
