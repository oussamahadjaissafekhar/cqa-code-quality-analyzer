"""Content-addressed cache for parser facts (v1 optional feature).

Cache keys include the language, parser version, an extractor revision, and a
SHA-256 of the exact source bytes. A stale cache therefore cannot change rule
results; it only lets unchanged files skip the parser bridge.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from ..logging import get_logger
from ..models import FileFacts

LOGGER = get_logger("fs.cache")
EXTRACTOR_REVISION = "1"


class FactCache:
    def __init__(self, directory: Path, parser_version: str, enabled: bool = True) -> None:
        self.directory = directory
        self.parser_version = parser_version
        self.enabled = enabled
        self._mem: dict[str, FileFacts] = {}

    def _key(self, path: str, language: str, content: str) -> str:
        material = "\x00".join(
            [
                self.parser_version,
                EXTRACTOR_REVISION,
                language,
                path,
                content,
            ]
        )
        return hashlib.sha256(material.encode("utf-8", errors="replace")).hexdigest()

    def get(self, path: str, language: str, content: str) -> FileFacts | None:
        if not self.enabled:
            return None
        key = self._key(path, language, content)
        cached = self._mem.get(key)
        if cached is not None:
            return cached

        file_path = self.directory / f"{key}.json"
        try:
            payload = json.loads(file_path.read_text(encoding="utf-8"))
            facts = FileFacts.model_validate(payload)
        except Exception:  # cache is best-effort: a corrupt entry is a miss
            return None
        self._mem[key] = facts
        return facts

    def put(self, path: str, language: str, content: str, facts: FileFacts) -> None:
        if not self.enabled:
            return
        key = self._key(path, language, content)
        self._mem[key] = facts
        try:
            self.directory.mkdir(parents=True, exist_ok=True)
            # Compact deterministic JSON keeps cache dirs small and debuggable.
            text = json.dumps(facts.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))
            (self.directory / f"{key}.json").write_text(text + "\n", encoding="utf-8")
        except OSError as exc:
            LOGGER.debug("cache write failed: %s", exc)
