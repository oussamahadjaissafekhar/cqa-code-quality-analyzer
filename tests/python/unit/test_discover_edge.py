"""Discovery edge cases: glob syntax, gitignore corners, explicit file filters."""

from __future__ import annotations

from pathlib import Path

from cqa.fs.discover import (
    DiscoverOptions,
    GlobSet,
    _parse_gitignore_line,
    discover_files,
    expand_braces,
    glob_to_regex,
)


def touch(path: Path, content: str = "x = 1\n") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


def test_glob_translation_corners() -> None:
    assert glob_to_regex("./src/*.py").match("src/app.py")
    assert glob_to_regex("src/?.py").match("src/a.py")
    assert not glob_to_regex("src/?.py").match("src/ab.py")
    assert glob_to_regex("src/[ab].py").match("src/a.py")
    assert not glob_to_regex("src/[ab].py").match("src/c.py")
    assert glob_to_regex("src/[!a].py").match("src/b.py")
    assert not glob_to_regex("src/[!a].py").match("src/a.py")
    # Unclosed character classes and braces are treated literally, never raise.
    assert glob_to_regex("src/[.py").match("src/[.py")
    assert expand_braces("a/{b") == ["a/{b"]
    assert expand_braces("plain.py") == ["plain.py"]


def test_globset_directory_matching() -> None:
    assert GlobSet(["**/node_modules/**"]).matches_directory("node_modules")
    assert GlobSet(["**/node_modules/**"]).matches_directory("src/node_modules")
    assert GlobSet(["vendor/"]).matches_directory("vendor")
    assert not GlobSet(["**/*.py"]).matches_directory("src")
    assert not GlobSet([]).matches_directory("")
    assert bool(GlobSet([])) is False
    assert bool(GlobSet(["*.py"])) is True


def test_gitignore_line_parsing_corners() -> None:
    assert _parse_gitignore_line("") is None
    assert _parse_gitignore_line("   ") is None
    assert _parse_gitignore_line("# comment") is None
    assert _parse_gitignore_line("!keep.py") == ("keep.py", True, False)
    assert _parse_gitignore_line("build/") == ("build", False, True)
    assert _parse_gitignore_line(r"\!literal.py") == ("!literal.py", False, False)
    assert _parse_gitignore_line(r"\#hash.py") == ("#hash.py", False, False)


def test_gitignore_anchoring_negation_and_nested_patterns(tmp_path: Path) -> None:
    touch(
        tmp_path / ".gitignore",
        "/root.py\ngenerated/*.py\n!generated/keep.py\nnested/ignored.py\n",
    )
    for name in (
        "root.py",
        "sub/root.py",
        "generated/drop.py",
        "generated/keep.py",
        "nested/ignored.py",
        "nested/ok.py",
    ):
        touch(tmp_path / name)

    files = discover_files(tmp_path, DiscoverOptions())
    assert [item.path for item in files] == [
        "generated/keep.py",
        "nested/ok.py",
        "sub/root.py",
    ]


def test_unreadable_gitignore_is_ignored(tmp_path: Path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    touch(tmp_path / ".gitignore", "a.py\n")
    touch(tmp_path / "a.py")

    def fail(self, *args, **kwargs):  # type: ignore[no-untyped-def]
        raise OSError("not readable")

    monkeypatch.setattr(Path, "read_text", fail)
    assert [item.path for item in discover_files(tmp_path, DiscoverOptions())] == ["a.py"]


def test_unreadable_directory_is_skipped(tmp_path: Path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    touch(tmp_path / "a.py")

    def fail(*args, **kwargs):  # type: ignore[no-untyped-def]
        raise OSError("not readable")

    monkeypatch.setattr("cqa.fs.discover.os.scandir", fail)
    assert discover_files(tmp_path, DiscoverOptions()) == []


def test_explicit_files_filter_non_files_unknown_languages_and_excludes(
    tmp_path: Path,
) -> None:
    touch(tmp_path / "a.py")
    touch(tmp_path / "notes.txt")
    touch(tmp_path / "skip.py")
    (tmp_path / "directory").mkdir()

    files = discover_files(
        tmp_path,
        DiscoverOptions(
            explicit_files=("a.py", "notes.txt", "skip.py", "missing.py", "directory"),
            exclude=("**/skip.py",),
        ),
    )
    assert [item.path for item in files] == ["a.py"]


def test_explicit_files_honour_include_patterns(tmp_path: Path) -> None:
    touch(tmp_path / "a.py")
    touch(tmp_path / "b.ts")
    files = discover_files(
        tmp_path,
        DiscoverOptions(explicit_files=("a.py", "b.ts"), include=("**/*.ts",)),
    )
    assert [item.path for item in files] == ["b.ts"]


def test_walk_include_and_exclude_filters(tmp_path: Path) -> None:
    touch(tmp_path / "src" / "a.py")
    touch(tmp_path / "src" / "b.ts")
    touch(tmp_path / "src" / "notes.txt")
    files = discover_files(
        tmp_path,
        DiscoverOptions(include=("src/**/*.py",), exclude=("**/ignored.py",)),
    )
    assert [item.path for item in files] == ["src/a.py"]


def test_missing_explicit_file_is_not_an_error(tmp_path: Path) -> None:
    assert discover_files(
        tmp_path, DiscoverOptions(explicit_files=("missing.py",))
    ) == []
