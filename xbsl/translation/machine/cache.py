"""What the service already answered, kept whether or not a human accepted the suggestion.

The RAW answer is stored, not the finished identifier: shaping rules and the term list change,
and re-paying for the same sentence because a rule changed would be absurd. The file is JSON on
purpose - the dictionary loader collects `*.yaml` recursively, so a yaml here would be read as a
dictionary plan and a duplicate key would refuse the whole load.
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Sequence


def fingerprint(glossary: Sequence[tuple[str, str]]) -> str:
    """A short hash of the term list in canonical form; empty when there is no glossary."""
    if not glossary:
        return ""
    pairs = sorted((source_term.strip().casefold(), target_term.strip()) for source_term, target_term in glossary)
    text = "\n".join(f"{source_term}={target_term}" for source_term, target_term in pairs)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:12]


class Cache:
    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self.hits = 0
        self.misses = 0
        self._data: dict[str, str] = {}
        self._load_safely()

    def _load_safely(self) -> None:
        """Load cache from file, forgiving all errors: corrupted, truncated, wrong type, missing."""
        if not self.path.exists():
            return
        try:
            text = self.path.read_text(encoding="utf-8")
            if not text:
                return
            data = json.loads(text)
            if isinstance(data, dict):
                self._data = data
        except (OSError, json.JSONDecodeError, UnicodeDecodeError):
            pass

    @staticmethod
    def _key(provider: str, source: str, target: str, fp: str, text: str) -> str:
        return "\u0000".join((provider, source, target, fp, text))

    def get(self, provider: str, source: str, target: str, fp: str, text: str) -> str | None:
        value = self._data.get(self._key(provider, source, target, fp, text))
        if value is None:
            self.misses += 1
        else:
            self.hits += 1
        return value

    def put(self, provider: str, source: str, target: str, fp: str, text: str,
            translation: str) -> None:
        self._data[self._key(provider, source, target, fp, text)] = translation

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        text = json.dumps(self._data, ensure_ascii=False, indent=1, sort_keys=True)
        # Write atomically via a temporary file and os.replace.
        tmp_file = self.path.with_suffix(self.path.suffix + ".tmp")
        try:
            tmp_file.write_text(text + "\n", encoding="utf-8", newline="")
            os.replace(tmp_file, self.path)
        except Exception:
            # Clean up the temporary file if anything goes wrong.
            try:
                tmp_file.unlink()
            except OSError:
                pass
            raise
