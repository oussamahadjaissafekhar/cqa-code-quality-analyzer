"""Filesystem discovery: gitignore-aware, deterministic, symlink-safe.

The walker is deliberately dependency-free. It implements the subset of
``.gitignore`` needed for source discovery and uses the same glob dialect as the
CLI/config (``**``, ``*``, ``?``, ``{a,b}``).

Security rule: symlinks are never followed. This guarantees the analysis root
cannot be escaped via a link, even when the link target is outside the repo.
"""

from __future__ import annotations

import os
import re
import sys
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import TextIO

from ..logging import get_logger

LOGGER = get_logger("fs.discover")

LANGUAGE_BY_SUFFIX: dict[str, str] = {
    ".py": "python",
    ".pyi": "python",
    ".ts": "typescript",
    ".tsx": "typescript",
    ".mts": "typescript",
    ".cts": "typescript",
    ".js": "javascript",
    ".jsx": "javascript",
    ".mjs": "javascript",
    ".cjs": "javascript",
}


@dataclass(frozen=True)
class SourceFile:
    """One discovered source file. ``path`` is always POSIX and root-relative."""

    path: str
    absolute: Path
    language: str


@dataclass(frozen=True)
class DiscoverOptions:
    include: tuple[str, ...] = ()
    exclude: tuple[str, ...] = ()
    use_gitignore: bool = True
    languages: tuple[str, ...] = ("python", "typescript", "javascript")
    explicit_files: tuple[str, ...] = field(default_factory=tuple)


# ---------------------------------------------------------------------------
# Glob handling
# ---------------------------------------------------------------------------


def expand_braces(pattern: str) -> list[str]:
    """Expand the first ``{a,b}`` group recursively (source-glob style)."""

    start = pattern.find("{")
    if start == -1:
        return [pattern]
    depth = 0
    end = -1
    for index in range(start, len(pattern)):
        char = pattern[index]
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                end = index
                break
    if end == -1:
        return [pattern]

    prefix, body, suffix = pattern[:start], pattern[start + 1 : end], pattern[end + 1 :]
    options: list[str] = []
    current = ""
    depth = 0
    for char in body + ",":
        if char == "," and depth == 0:
            options.append(current)
            current = ""
            continue
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
        current += char

    expanded: list[str] = []
    for option in options:
        expanded.extend(expand_braces(f"{prefix}{option}{suffix}"))
    return expanded


def glob_to_regex(pattern: str) -> re.Pattern[str]:
    """Translate a git-style glob to an anchored, POSIX-path regex."""

    pattern = pattern.replace("\\", "/")
    while pattern.startswith("./"):
        pattern = pattern[2:]
    out: list[str] = []
    index = 0
    length = len(pattern)
    while index < length:
        char = pattern[index]
        if char == "*":
            if index + 1 < length and pattern[index + 1] == "*":
                index += 2
                if index < length and pattern[index] == "/":
                    index += 1
                    out.append("(?:.*/)?")
                else:
                    out.append(".*")
                continue
            out.append("[^/]*")
        elif char == "?":
            out.append("[^/]")
        elif char == "[":
            close = pattern.find("]", index + 1)
            if close == -1:
                out.append(r"\[")
            else:
                body = pattern[index + 1 : close]
                if body.startswith("!"):
                    body = "^" + body[1:]
                out.append(f"[{body}]")
                index = close
        else:
            out.append(re.escape(char))
        index += 1
    return re.compile("^" + "".join(out) + "$")


class GlobSet:
    """Compiled include/exclude globs with brace expansion."""

    def __init__(self, patterns: Iterable[str]) -> None:
        self.patterns = list(patterns)
        compiled: list[re.Pattern[str]] = []
        for pattern in self.patterns:
            for expanded in expand_braces(pattern):
                compiled.append(glob_to_regex(expanded))
        self._compiled = compiled

    def matches(self, path: str) -> bool:
        return any(regex.match(path) for regex in self._compiled)

    def matches_directory(self, path: str) -> bool:
        """Match a directory against patterns that target its contents."""

        if not path:
            return False
        if self.matches(path) or self.matches(f"{path}/"):
            return True
        for pattern in self.patterns:
            trimmed = pattern.replace("\\", "/").rstrip("/")
            if trimmed.endswith("/**"):
                trimmed = trimmed[: -len("/**")]
            if not trimmed or not any(char in trimmed for char in "*?[{"):
                continue
            if GlobSet([trimmed]).matches(path):
                return True
        return False

    def __bool__(self) -> bool:
        return bool(self._compiled)


# ---------------------------------------------------------------------------
# gitignore
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class GitIgnoreRule:
    base: str
    pattern: str
    negated: bool
    directory_only: bool
    regex: re.Pattern[str]


def _parse_gitignore_line(line: str) -> tuple[str, bool, bool] | None:
    """Return ``(pattern, negated, directory_only)`` or None for a no-op line."""

    stripped = line.rstrip("\r\n")
    if not stripped or stripped.lstrip().startswith("#"):
        return None
    # Git treats trailing unescaped spaces as insignificant.
    stripped = stripped.rstrip()
    if not stripped:
        return None

    negated = False
    if stripped.startswith("!"):
        negated = True
        stripped = stripped[1:]
    elif stripped.startswith(r"\!"):
        stripped = stripped[1:]
    if stripped.startswith(r"\#"):
        stripped = stripped[1:]

    directory_only = stripped.endswith("/")
    if directory_only:
        stripped = stripped[:-1]
    if not stripped:
        return None
    return stripped, negated, directory_only


def _compile_gitignore_rule(base: str, line: str) -> GitIgnoreRule | None:
    parsed = _parse_gitignore_line(line)
    if parsed is None:
        return None
    pattern, negated, directory_only = parsed

    anchored = pattern.startswith("/")
    if anchored:
        pattern = pattern[1:]
    # A slash anywhere but the end means the pattern is relative to the base.
    anchored = anchored or "/" in pattern

    body = glob_to_regex(pattern).pattern
    # Strip the anchors added by glob_to_regex so we can compose with base.
    body = body[1:-1]
    if anchored:
        prefix = re.escape(base) + "/" if base else ""
        regex = re.compile("^" + prefix + body + "$")
    else:
        prefix = re.escape(base) + "/" if base else ""
        regex = re.compile("^(?:" + prefix + ")?(?:.*/)?" + body + "$")
    return GitIgnoreRule(base, pattern, negated, directory_only, regex)


class GitIgnore:
    """Reads a directory's ``.gitignore`` and returns scoped rules.

    Rules are immutable and returned to the walker instead of accumulated on a
    shared object: sibling directories must not inherit each other's patterns.
    """

    @staticmethod
    def load_directory(directory: Path, base: str) -> list[GitIgnoreRule]:
        path = directory / ".gitignore"
        if not path.is_file():
            return []
        try:
            lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError as exc:
            LOGGER.debug("cannot read %s: %s", path, exc)
            return []
        rules: list[GitIgnoreRule] = []
        for line in lines:
            rule = _compile_gitignore_rule(base, line)
            if rule is not None:
                rules.append(rule)
        return rules


def _parent_paths(rel_path: str) -> list[str]:
    parts = PurePosixPath(rel_path).parts
    return ["/".join(parts[:index]) for index in range(1, len(parts))]


# ---------------------------------------------------------------------------
# Walker
# ---------------------------------------------------------------------------


def _language_for(path: Path) -> str | None:
    return LANGUAGE_BY_SUFFIX.get(path.suffix.lower())


def discover_files(root: Path, options: DiscoverOptions) -> list[SourceFile]:
    """Discover source files under ``root``.

    ``root`` may be a file or directory. Missing paths raise ``FileNotFoundError``
    (mapped to exit code 3 by the CLI). Unreadable subdirectories are skipped with
    a warning rather than aborting the whole analysis.
    """

    root = root.expanduser()
    if not root.exists():
        raise FileNotFoundError(str(root))

    allowed_languages = set(options.languages)
    include = GlobSet(options.include)
    exclude = GlobSet(options.exclude)
    found: list[SourceFile] = []

    if root.is_file():
        resolved = root.resolve()
        language = _language_for(resolved)
        if language in allowed_languages and (not include or include.matches(resolved.name)):
            found.append(SourceFile(resolved.name, resolved, language))
        return found

    root = root.resolve()

    if options.explicit_files:
        for raw in options.explicit_files:
            candidate = Path(raw)
            if not candidate.is_absolute():
                candidate = root / candidate
            try:
                resolved = candidate.resolve()
                rel = resolved.relative_to(root).as_posix()
            except (OSError, ValueError):
                LOGGER.warning("skipping path outside analysis root: %s", raw)
                continue
            if not resolved.is_file() or resolved.is_symlink():
                continue
            language = _language_for(resolved)
            if language not in allowed_languages:
                continue
            if (include and not include.matches(rel)) or exclude.matches(rel):
                continue
            found.append(SourceFile(rel, resolved, language))
        return sorted(found, key=lambda item: item.path)

    def walk(directory: Path, base: str, inherited: list[GitIgnoreRule]) -> None:
        if options.use_gitignore:
            rules = inherited + GitIgnore.load_directory(directory, base)
        else:
            rules = inherited

        try:
            entries = sorted(os.scandir(directory), key=lambda entry: entry.name)
        except OSError as exc:
            LOGGER.warning("cannot read directory %s: %s", directory, exc)
            return

        for entry in entries:
            rel = f"{base}/{entry.name}" if base else entry.name
            try:
                is_symlink = entry.is_symlink()
                is_dir = entry.is_dir(follow_symlinks=False)
                is_file = entry.is_file(follow_symlinks=False)
            except OSError as exc:
                LOGGER.debug("cannot stat %s: %s", entry.path, exc)
                continue

            # Never follow symlinks: guarantees we stay inside the analysis root.
            if is_symlink:
                continue

            if is_dir:
                if exclude.matches_directory(rel):
                    continue
                if rules and _ignored_by(rules, rel, is_dir=True):
                    continue
                walk(Path(entry.path), rel, rules)
                continue

            if not is_file:
                continue
            if exclude.matches(rel):
                continue
            if rules and _ignored_by(rules, rel, is_dir=False):
                continue
            language = _language_for(Path(entry.name))
            if language not in allowed_languages:
                continue
            if include and not include.matches(rel):
                continue
            found.append(SourceFile(rel, Path(entry.path), language))

    walk(root, "", [])
    return sorted(found, key=lambda item: item.path)


def _ignored_by(rules: list[GitIgnoreRule], rel_path: str, is_dir: bool) -> bool:
    """Apply rules in order; negation wins only when it is the last match."""

    ignored = False
    for rule in rules:
        if rule.directory_only and not is_dir:
            parent_match = any(rule.regex.match(parent) for parent in _parent_paths(rel_path))
            if not parent_match:
                continue
        if rule.regex.match(rel_path):
            ignored = not rule.negated
    return ignored


def read_stdin_files(stream: TextIO | None = None) -> list[str]:
    """Read a NUL-separated path list (falls back to newline separation).

    Used by ``cqa analyze --stdin-files`` for CI incremental runs:
    ``git diff --name-only -z | cqa analyze --stdin-files``.
    """

    source = stream or sys.stdin
    data = source.read()
    raw_items = data.split("\x00") if "\x00" in data else data.splitlines()
    return [item.strip().strip('"') for item in raw_items if item.strip()]
