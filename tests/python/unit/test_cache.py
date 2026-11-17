"""Behavioral tests for the content-addressed parser fact cache."""

from __future__ import annotations

import json
from pathlib import Path

from cqa.fs.cache import EXTRACTOR_REVISION, FactCache
from cqa.models import CallFact, FileFacts


def facts(callee: str = "eval") -> FileFacts:
    return FileFacts(calls=[CallFact(callee=callee, line=1, col=1, args_kind="dynamic")])


def test_memory_roundtrip_and_miss(tmp_path: Path) -> None:
    cache = FactCache(tmp_path / "cache", parser_version="p1")
    assert cache.get("a.py", "python", "eval(x)\n") is None

    value = facts()
    cache.put("a.py", "python", "eval(x)\n", value)
    assert cache.get("a.py", "python", "eval(x)\n") is value
    # Any key component change is a miss.
    assert cache.get("b.py", "python", "eval(x)\n") is None
    assert cache.get("a.py", "typescript", "eval(x)\n") is None
    assert cache.get("a.py", "python", "eval(y)\n") is None


def test_disk_persistence_and_deterministic_payload(tmp_path: Path) -> None:
    directory = tmp_path / "cache"
    cache = FactCache(directory, parser_version="p1")
    value = facts("run")
    cache.put("src/a.py", "python", "run(x)\n", value)

    entries = list(directory.glob("*.json"))
    assert len(entries) == 1
    text = entries[0].read_text(encoding="utf-8")
    assert text.endswith("\n")
    payload = json.loads(text)
    assert payload["calls"][0]["callee"] == "run"

    # A new process (new in-memory map) reads the same facts from disk.
    second = FactCache(directory, parser_version="p1")
    loaded = second.get("src/a.py", "python", "run(x)\n")
    assert loaded is not None
    assert loaded.calls[0].callee == "run"


def test_parser_version_and_extractor_revision_participate_in_the_key(tmp_path: Path) -> None:
    first = FactCache(tmp_path / "cache", parser_version="p1")
    key = first._key("a.py", "python", "x = 1\n")
    assert EXTRACTOR_REVISION in ("1",)
    assert key != FactCache(tmp_path / "cache", parser_version="p2")._key(
        "a.py", "python", "x = 1\n"
    )
    assert key == FactCache(tmp_path / "cache", parser_version="p1")._key(
        "a.py", "python", "x = 1\n"
    )


def test_corrupt_or_malformed_entries_are_cache_misses(tmp_path: Path) -> None:
    directory = tmp_path / "cache"
    cache = FactCache(directory, parser_version="p1")
    source = "eval(x)\n"
    cache.put("a.py", "python", source, facts())
    entry = directory / f"{cache._key('a.py', 'python', source)}.json"

    entry.write_text("{ not json", encoding="utf-8")
    assert FactCache(directory, parser_version="p1").get("a.py", "python", source) is None

    entry.write_text(json.dumps({"calls": [{"callee": "eval"}]}), encoding="utf-8")
    assert FactCache(directory, parser_version="p1").get("a.py", "python", source) is None


def test_disabled_cache_never_touches_disk(tmp_path: Path) -> None:
    directory = tmp_path / "cache"
    cache = FactCache(directory, parser_version="p1", enabled=False)
    cache.put("a.py", "python", "eval(x)\n", facts())
    assert cache.get("a.py", "python", "eval(x)\n") is None
    assert not directory.exists()


def test_write_failures_are_best_effort(tmp_path: Path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    cache = FactCache(tmp_path / "cache", parser_version="p1")

    def fail(*args, **kwargs):  # type: ignore[no-untyped-def]
        raise OSError("disk full")

    monkeypatch.setattr(Path, "mkdir", fail)
    cache.put("a.py", "python", "eval(x)\n", facts())  # must not raise
    # The in-memory layer still serves the entry.
    assert cache.get("a.py", "python", "eval(x)\n") is not None
