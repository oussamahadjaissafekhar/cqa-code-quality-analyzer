from __future__ import annotations

import io
from pathlib import Path

import pytest

from cqa.fs.discover import (
    DiscoverOptions,
    discover_files,
    expand_braces,
    glob_to_regex,
    read_stdin_files,
)


def touch(path: Path, content: str = "x = 1\n") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


def test_expand_braces() -> None:
    assert expand_braces("**/*.{py,ts}") == ["**/*.py", "**/*.ts"]
    assert expand_braces("a/{b,c/{d,e}}.py") == ["a/b.py", "a/c/d.py", "a/c/e.py"]


def test_glob_semantics() -> None:
    regex = glob_to_regex("**/node_modules/**")
    assert regex.match("node_modules/pkg/a.js")
    assert regex.match("src/node_modules/pkg/a.js")
    assert not regex.match("src/app.js")
    assert glob_to_regex("src/*.py").match("src/app.py")
    assert not glob_to_regex("src/*.py").match("src/nested/app.py")


def test_discovery_basic_and_sorted(tmp_path: Path) -> None:
    touch(tmp_path / "b.py")
    touch(tmp_path / "a.ts")
    touch(tmp_path / "nested" / "c.js")
    touch(tmp_path / "notes.txt")

    files = discover_files(
        tmp_path,
        DiscoverOptions(
            include=("**/*.{py,ts,js}",),
            languages=("python", "typescript", "javascript"),
        ),
    )
    assert [item.path for item in files] == ["a.ts", "b.py", "nested/c.js"]
    assert {item.language for item in files} == {"python", "typescript", "javascript"}


def test_language_filter(tmp_path: Path) -> None:
    touch(tmp_path / "a.py")
    touch(tmp_path / "b.ts")
    files = discover_files(tmp_path, DiscoverOptions(languages=("python",)))
    assert [item.path for item in files] == ["a.py"]


def test_gitignore_applies_to_files_and_directories(tmp_path: Path) -> None:
    touch(tmp_path / ".gitignore", "ignored.py\nbuild/\n!keep.py\n")
    touch(tmp_path / "ignored.py")
    touch(tmp_path / "keep.py")
    touch(tmp_path / "ok.py")
    touch(tmp_path / "build" / "generated.py")
    touch(tmp_path / "nested" / ".gitignore", "skip.ts\n")
    touch(tmp_path / "nested" / "skip.ts")
    touch(tmp_path / "nested" / "use.ts")

    files = discover_files(tmp_path, DiscoverOptions())
    assert [item.path for item in files] == ["keep.py", "nested/use.ts", "ok.py"]


def test_no_gitignore(tmp_path: Path) -> None:
    touch(tmp_path / ".gitignore", "ignored.py\n")
    touch(tmp_path / "ignored.py")
    files = discover_files(tmp_path, DiscoverOptions(use_gitignore=False))
    assert [item.path for item in files] == ["ignored.py"]


def test_config_excludes_and_node_modules(tmp_path: Path) -> None:
    touch(tmp_path / "app.ts")
    touch(tmp_path / "node_modules" / "pkg" / "index.js")
    touch(tmp_path / "dist" / "bundle.js")
    files = discover_files(
        tmp_path,
        DiscoverOptions(exclude=("**/node_modules/**", "**/dist/**")),
    )
    assert [item.path for item in files] == ["app.ts"]


def test_explicit_files_stay_inside_root(tmp_path: Path) -> None:
    touch(tmp_path / "a.py")
    touch(tmp_path / "b.py")
    outside = touch(tmp_path.parent / "outside.py")
    files = discover_files(
        tmp_path,
        DiscoverOptions(explicit_files=("a.py", "b.py", str(outside), "../outside.py")),
    )
    assert [item.path for item in files] == ["a.py", "b.py"]


def test_missing_root_raises(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        discover_files(tmp_path / "missing", DiscoverOptions())


def test_root_file_input(tmp_path: Path) -> None:
    target = touch(tmp_path / "one.py")
    files = discover_files(target, DiscoverOptions())
    assert [(item.path, item.language) for item in files] == [("one.py", "python")]


def test_symlinks_are_not_followed(tmp_path: Path) -> None:
    touch(tmp_path / "real.py")
    link = tmp_path / "link.py"
    try:
        link.symlink_to(tmp_path / "real.py")
    except (OSError, NotImplementedError):
        pytest.skip("symlink creation not permitted on this platform")
    files = discover_files(tmp_path, DiscoverOptions())
    assert [item.path for item in files] == ["real.py"]


def test_read_stdin_files_nul_and_newline() -> None:
    assert read_stdin_files(io.StringIO("a.py\x00dir/b.ts\x00")) == ["a.py", "dir/b.ts"]
    assert read_stdin_files(io.StringIO('a.py\n"b.ts"\n')) == ["a.py", "b.ts"]
