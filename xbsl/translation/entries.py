"""The dictionary as a TABLE: entries with their place, gaps with theirs, edits back to disk.

A translation dictionary of a real project runs to thousands of lines across several files.
Editing that by hand is where mistakes come from - a key typed twice, a value quoted wrong, a
gap missed - so an editor gets a table instead: what is translated, what is not, where each
name occurs, and one place to type the missing value. This module is the engine side of that
table: it reads the entries WITH their file and line (so a row can jump to its source), pairs
them with the gaps the translator reports, and writes new values back into a dictionary file
without disturbing the rest.

Writing lives here rather than in the editor on purpose: the format (quoting, the
`tokens`/`phrases` split, the scoped `<Owner>.<Name>` key) is the engine's business, and one
implementation keeps the panel, the quick fix and any script honest.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path

from xbsl import i18n
from xbsl.translation import dictionary as dictionary_module

try:
    import yaml
except ImportError:  # pragma: no cover
    yaml = None

MESSAGES = {
    "translate.entries.no-dictionary": {
        "ru": "словарь перевода не найден рядом с проектом",
        "en": "no translation dictionary next to the project",
    },
}
i18n.register(MESSAGES)

#: The file new entries land in when the caller names none.
DEFAULT_TARGET = "090-manual.yaml"

#: A key line of a dictionary section: the indent, the key (quoted or bare), the value.
_ENTRY_RE = re.compile(
    r"^(?P<indent>[ \t]+)"
    r"(?:(?P<q>['\"])(?P<quoted>.*?)(?P=q)|(?P<plain>[^\s:#][^:]*?))"
    r":[ \t]*(?P<value>.*?)[ \t]*$"
)
#: The head of a section. A comment may sit on that line - yaml allows it, so a dictionary
#: written that way loads and translates; a reader that refused it would show an empty table
#: over a full file, and the writer would then add a key that is already there.
_SECTION_RE = re.compile(r"^(tokens|phrases):[ \t]*(?:#.*)?$")

#: Suffixes of the platform's INTERNAL names. The compiler dictionary carries a few of them
#: (the metadata class behind a built-in attribute is `CodeAttrMd`), and offering such a name
#: as a translation would be worse than offering nothing: it looks authoritative and is wrong.
_INTERNAL_SUFFIXES = ("Md", "Metadata", "Descriptor", "G5Enum", "Cmpt", "Impl")


def _suggestion(name: str) -> str:
    """The platform spelling worth offering for a name, or an empty string."""
    from xbsl.translation import platform_map

    for candidate in (platform_map.ident_english(name), platform_map.member_english(name)):
        if candidate and not candidate.endswith(_INTERNAL_SUFFIXES):
            return candidate
    return ""


#: Values yaml would read as something other than a string.
_RESERVED_SCALARS = frozenset({
    "true", "false", "null", "yes", "no", "on", "off",
    "True", "False", "Null", "Yes", "No", "On", "Off", "~", "",
})
_BARE_SCALAR_RE = re.compile(r"^[^\W\d][\w.]*$", re.UNICODE)


@dataclass
class Entry:
    """One dictionary line, ready to be shown as a table row."""

    key: str
    value: str
    kind: str            # 'token' | 'phrase'
    file: str            # the dictionary file the entry lives in
    line: int            # 1-based
    scope: str = ""      # the owner of a qualified key (`<Owner>.<Name>`), empty for a plain one

    def as_dict(self) -> dict:
        return {
            "key": self.key, "value": self.value, "kind": self.kind,
            "file": self.file, "line": self.line, "scope": self.scope,
        }


@dataclass
class Gap:
    """A name or a comment line the dictionary does not cover yet."""

    key: str
    kind: str                       # 'token' | 'phrase'
    count: int = 0
    places: list[tuple[str, int]] = field(default_factory=list)
    #: What the platform would spell it, when it knows the word - the value to offer first.
    suggestion: str = ""
    #: True when the name is a resource FILE (the stem of an icon and the like).
    resource: bool = False

    def as_dict(self) -> dict:
        return {
            "key": self.key, "kind": self.kind, "count": self.count,
            "places": [{"file": f, "line": ln} for f, ln in self.places],
            "suggestion": self.suggestion, "resource": self.resource,
        }


def read_entries(dictionary_path: Path) -> list[Entry]:
    """Every entry of the dictionary, with the file and line it stands on."""
    files = (
        sorted(p for p in dictionary_path.rglob("*.yaml") if p.is_file())
        if dictionary_path.is_dir() else [dictionary_path]
    )
    out: list[Entry] = []
    for file in files:
        try:
            text = file.read_text(encoding="utf-8-sig")
        except OSError:
            continue
        section = ""
        for number, raw in enumerate(text.splitlines(), 1):
            header = _SECTION_RE.match(raw)
            if header:
                section = header.group(1)
                continue
            if raw and not raw[0].isspace():
                section = ""  # any top-level key closes the section
                continue
            if not section or not raw.strip() or raw.lstrip().startswith("#"):
                continue
            m = _ENTRY_RE.match(raw)
            if m is None:
                continue
            key = m.group("quoted") if m.group("quoted") is not None else (m.group("plain") or "")
            if not key:
                continue
            scope = key.partition(".")[0] if (section == "tokens" and "." in key) else ""
            out.append(Entry(
                key=key, value=_unquote(m.group("value")),
                kind="token" if section == "tokens" else "phrase",
                file=str(file), line=number, scope=scope,
            ))
    return out


def _unquote(value: str) -> str:
    """The scalar as yaml would read it (the writer only ever emits plain or JSON quoting)."""
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
        if value[0] == '"':
            try:
                return json.loads(value)
            except ValueError:
                return value[1:-1]
        return value[1:-1].replace("''", "'")
    return value


def gaps_of_project(root: Path, dictionary) -> list[Gap]:
    """What the translator leaves behind on this project, ready for the table.

    The suggestion is the PLATFORM's own spelling where it has one: most gaps of a real
    project are words the platform also knows, and the right value is usually exactly that
    spelling - the project simply named its own thing the same way.
    """
    from xbsl.translation import project as project_module

    report = project_module.translate_project(root, dictionary, None)
    out: list[Gap] = []
    for name, info in report.merged_missing_tokens().items():
        out.append(Gap(
            key=name, kind="token", count=int(info.get("count") or 0),
            places=_places(report, name, "token"),
            suggestion=_suggestion(name),
            resource=bool(info.get("resource")),
        ))
    for text, info in report.merged_missing_phrases().items():
        out.append(Gap(
            key=text, kind="phrase", count=int(info.get("count") or 0),
            places=_places(report, text, "phrase"),
        ))
    out.sort(key=lambda gap: (-gap.count, gap.key))
    return out


def _places(report, key: str, kind: str, limit: int = 20) -> list[tuple[str, int]]:
    """Where the gap occurs: (file, line) pairs, capped so one row stays small."""
    places: list[tuple[str, int]] = []
    for rel, file_report in sorted(report.files.items()):
        table = file_report.missing_tokens if kind == "token" else file_report.missing_phrases
        for line, _col in table.get(key, ()):
            places.append((rel, line))
            if len(places) >= limit:
                return places
    return places


def write_entries(dictionary_path: Path, edits: list[dict], target: str = DEFAULT_TARGET) -> dict:
    """Apply the edits to disk and report what happened (the CLI and MCP path)."""
    plan = plan_entries(dictionary_path, edits, target)
    for path, text in plan["files"].items():
        file = Path(path)
        file.parent.mkdir(parents=True, exist_ok=True)
        file.write_text(text, encoding="utf-8", newline="")
    return {key: plan[key] for key in ("changed", "added", "removed")}


def plan_entries(dictionary_path: Path, edits: list[dict], target: str = DEFAULT_TARGET) -> dict:
    """Compute the dictionary files AFTER the edits, without touching the disk.

    An edit is `{key, value, kind}`. An emptied value REMOVES the entry: a half-filled stub
    is not a translation, and leaving it would claim coverage the project does not have.

    The result is `{files: {path: the full new text}, changed, added, removed}`. Texts rather
    than writes are what an editor needs: the language server never writes to disk, so the
    client applies the result as a workspace edit and the user keeps undo.
    """
    known = {(entry.kind, entry.key): entry for entry in read_entries(dictionary_path)}
    by_file: dict[Path, list[tuple[Entry, dict]]] = {}
    fresh: list[dict] = []
    for edit in edits:
        key = str(edit.get("key") or "")
        kind = str(edit.get("kind") or "token")
        if not key:
            continue
        entry = known.get((kind, key))
        if entry is None:
            fresh.append({"key": key, "kind": kind, "value": str(edit.get("value") or "")})
        else:
            by_file.setdefault(Path(entry.file), []).append((entry, edit))

    changed = removed = 0
    files: dict[str, str] = {}
    for file, items in by_file.items():
        lines = file.read_text(encoding="utf-8-sig").splitlines(keepends=True)
        # Last line first: an earlier removal would shift the ones after it.
        for entry, edit in sorted(items, key=lambda pair: -pair[0].line):
            index = entry.line - 1
            if index >= len(lines):
                continue
            value = str(edit.get("value") or "")
            if not value:
                del lines[index]
                removed += 1
                continue
            indent = re.match(r"^[ \t]*", lines[index]).group(0)
            newline = "\r\n" if lines[index].endswith("\r\n") else "\n"
            lines[index] = f"{indent}{scalar(entry.key)}: {scalar(value)}{newline}"
            changed += 1
        files[str(file)] = "".join(lines)

    added = 0
    if fresh:
        target_file, new_text, added = _plan_new(dictionary_path, fresh, target)
        if added:
            files[str(target_file)] = new_text
    return {"files": files, "changed": changed, "added": added, "removed": removed}


def scalar(text: str) -> str:
    """One yaml scalar: a plain word stays plain, everything else is quoted."""
    if _BARE_SCALAR_RE.match(text) and text not in _RESERVED_SCALARS:
        return text
    return json.dumps(text, ensure_ascii=False)


def _plan_new(dictionary_path: Path, edits: list[dict], target: str) -> tuple[Path, str, int]:
    """(the target file, its full text with the new entries, how many were added)."""
    file = dictionary_path / target if dictionary_path.is_dir() else dictionary_path
    tokens = {e["key"]: e["value"] for e in edits if e["kind"] == "token" and e["value"]}
    phrases = {e["key"]: e["value"] for e in edits if e["kind"] == "phrase" and e["value"]}
    if not tokens and not phrases:
        return file, "", 0
    if file.exists():
        text = file.read_text(encoding="utf-8-sig")
    else:
        text = (
            "version: 1\n"
            "language: en\n"
            "\n"
            "# Записи, добавленные из редактора: панель словаря перевода и быстрые исправления.\n"
        )
    text = _merge_section(text, "tokens", tokens)
    text = _merge_section(text, "phrases", phrases)
    return file, text, len(tokens) + len(phrases)


#: The indent new entries get when the section has none to copy.
_DEFAULT_INDENT = "    "


def _merge_section(text: str, section: str, pairs: dict[str, str]) -> str:
    """Append the pairs at the END of the section, creating the section when absent.

    The indent is COPIED from the entries already there, not fixed: a file written with two
    spaces is valid yaml, and appending four-space entries under a two-space key nests them
    inside the previous entry - the dictionary stops parsing at the next load.
    """
    if not pairs:
        return text
    if not text.endswith("\n"):
        text += "\n"
    marker = f"{section}:"
    if text.startswith(marker):
        start = 0
    else:
        found = text.find(f"\n{marker}")
        if found == -1:
            return text + marker + "\n" + _entries(pairs, _DEFAULT_INDENT)
        start = found + 1
    # Past the head line itself: a comment may live there, and it is not an entry.
    head = text.find("\n", start)
    offset = (head + 1 - start) if head != -1 else len(text) - start
    indent = ""
    for line in text[start + offset:].splitlines(keepends=True):
        if line.strip() and not line[0].isspace():
            break
        m = _ENTRY_RE.match(line.rstrip("\n"))
        if m and not indent:
            indent = m.group("indent")
        offset += len(line)
    return text[:start + offset] + _entries(pairs, indent or _DEFAULT_INDENT) + text[start + offset:]


def _entries(pairs: dict[str, str], indent: str) -> str:
    return "".join(f"{indent}{scalar(k)}: {scalar(v)}\n" for k, v in sorted(pairs.items()))


def discover(root: Path) -> Path | None:
    """The dictionary that serves this project, or None."""
    return dictionary_module.discover(root)
