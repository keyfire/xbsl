"""The dictionary as a TABLE: entries with their place, gaps with theirs, edits back to disk.

A translation dictionary of a real project runs to thousands of lines across several files.
Editing that by hand is where mistakes come from - a key typed twice, a value quoted wrong, a
gap missed - so an editor gets a table instead: what is translated, what is not, where each
name occurs, and one place to type the missing value. This module is the engine side of that
table: it reads the entries WITH their file and line (so a row can jump to its source), pairs
them with the gaps the translator reports, and writes new values back into a dictionary file
without disturbing the rest.

Writing lives here rather than in the editor on purpose: the format (quoting, the
`tokens`/`phrases`/`literals` split, the scoped `<Owner>.<Name>` key) is the engine's
business, and one implementation keeps the panel, the quick fix and any script honest.
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
    "translate.unknown-kind": {
        "ru": "неизвестный вид записи \"{kind}\"; ожидается один из: {allowed}",
        "en": "unknown entry kind \"{kind}\"; expected one of: {allowed}",
    },
    "translate.entries.edits-not-list": {
        "ru": "в файле правок ожидается список [{{key, value, kind}}]",
        "en": "the edits file must carry a list [{{key, value, kind}}]",
    },
    "translate.entries.edits-empty": {
        "ru": "в файле правок не найдено ни одной записи: нужны секции"
              " tokens/phrases/literals формата словаря либо список JSON",
        "en": "no entries found in the edits file: it needs tokens/phrases/literals"
              " sections in the dictionary format, or a JSON list",
    },
    "translate.page.truncated": {
        "ru": "показаны не все строки, осталось ещё {remaining}:"
              " следующая страница – offset={next_offset}, limit=0 отдаёт список целиком.",
        "en": "not every row is shown, {remaining} more to go:"
              " the next page is offset={next_offset}, limit=0 answers with the whole list.",
    },
    "translate.page.gaps-file": {
        "ru": " Весь остаток разом – заготовкой словаря в файл:"
              " xbsl translate <root> --missing <файл>.",
        "en": " The whole remainder at once - as a dictionary stub in a file:"
              " xbsl translate <root> --missing <file>.",
    },
    "translate.unused.textual": {
        "ru": "чтение сирот текстовое: ключ считается живым, пока его текст встречается в"
              " исходниках, какими они лежат сейчас. Поэтому список без отбора описывает"
              " ВЕСЬ накопленный словарь, а не вашу правку, и годится на просмотр, а не на"
              " снятие целиком. Сироты одной правки – {option}: ключи, которые встречались"
              " только в строках, снятых этой правкой.",
        "en": "the orphan reading is textual: a key counts as live while its text occurs in"
              " the sources as they stand. So a list without a filter describes the WHOLE"
              " accumulated dictionary rather than your change - a list to read through, not"
              " one to prune wholesale. The orphans of one change are {option}: the keys that"
              " only ever occurred in the lines that change took out.",
    },
    "translate.since.no-git": {
        "ru": "git не найден: режим сирот правки читает снятые строки по git diff",
        "en": "git was not found: the change-orphans mode reads the removed lines from"
              " git diff",
    },
    "translate.since.not-a-repo": {
        "ru": "каталог {path} не в репозитории git: снятые строки взять неоткуда",
        "en": "the directory {path} is not inside a git repository: there is nowhere to"
              " read the removed lines from",
    },
    "translate.since.unknown-rev": {
        "ru": "git не знает ревизии \"{rev}\": ожидается ветка, коммит или диапазон A..B",
        "en": "git does not know the revision \"{rev}\": a branch, a commit or a range A..B"
              " is expected",
    },
    "translate.since.diff-failed": {
        "ru": "git diff по \"{rev}\" не выполнен: {error}",
        "en": "git diff over \"{rev}\" failed: {error}",
    },
}
i18n.register(MESSAGES)

#: The file new entries land in when the caller names none.
DEFAULT_TARGET = "090-manual.yaml"

#: A key line of a dictionary section: the indent, the key (quoted or bare), the value.
#: A quoted key may carry a quote of its own - a comment line that cites something is an
#: ordinary key here - so the escape is part of the pattern; stopping at the first inner quote
#: would drop the whole entry, and the writer would then add the key a second time.
#:
#: A BARE key ends where yaml ends it: at a colon followed by a space or by the end of the
#: line, never at just any colon. A key holding `::` is ordinary in this data - a platform
#: form is cited as a `Std::Jobs::Interface::JobsForm` path - and reading the key as
#: "everything up to the first colon" tore such an entry in two: the key stopped mid-word and
#: the rest of it was stored as part of the translation. The damage was silent, because both
#: halves are valid strings; it surfaced as one phrase going missing from the coverage.
_ENTRY_RE = re.compile(
    r"^(?P<indent>[ \t]+)"
    r"(?:\"(?P<dq>(?:[^\"\\]|\\.)*)\"|'(?P<sq>(?:[^']|'')*)'"
    r"|(?P<plain>[^\s:#](?:[^:]|:(?![ \t]|$))*?))"
    r":(?=[ \t]|$)[ \t]*(?P<value>.*?)[ \t]*$"
)
#: The head of a section. A comment may sit on that line - yaml allows it, so a dictionary
#: written that way loads and translates; a reader that refused it would show an empty table
#: over a full file, and the writer would then add a key that is already there.
_SECTION_RE = re.compile(r"^(tokens|phrases|literals):[ \t]*(?:#.*)?$")

#: The EXPLICIT key form of yaml - `? <key>` on one line, `: <value>` on the next. A dumper
#: writes a long key that way on its own (PyYAML does it past 128 characters), so a dictionary
#: file may carry it without anyone choosing it: the live dictionary of the site holds two
#: literals in this shape. Read as ordinary lines they matched nothing, and the entries were
#: invisible to every reader - the table, the orphan pass and the writer alike, which would
#: then ADD a key that is already there.
_EXPLICIT_KEY_RE = re.compile(
    r"^(?P<indent>[ \t]+)\?[ \t]+"
    r"(?:\"(?P<dq>(?:[^\"\\]|\\.)*)\"|'(?P<sq>(?:[^']|'')*)'|(?P<plain>\S.*?))[ \t]*$"
)
_EXPLICIT_VALUE_RE = re.compile(r"^[ \t]+:[ \t]*(?P<value>.*?)[ \t]*$")

#: The section a row of each kind lives in - the table speaks of kinds, the file of sections.
SECTION_OF_KIND = {"token": "tokens", "phrase": "phrases", "literal": "literals"}
KIND_OF_SECTION = {section: kind for kind, section in SECTION_OF_KIND.items()}
#: The kinds a caller may name, in the order the documentation lists them.
KINDS = tuple(SECTION_OF_KIND)


def kind_refusal(kind: str, *, allow_any: bool = True) -> str:
    """Why this `kind` cannot be honored, or an empty string when it can.

    A misspelled kind used to be answered, not refused: the readers filter by `kind == row.kind`,
    so `phrases` (the SECTION name, plural) matched nothing and the answer came back with an
    empty list - indistinguishable from "the dictionary covers everything". A run that trusted
    it left the gaps unfilled, and the strict pass found them after the merge.
    """
    allowed = (("any",) + KINDS) if allow_any else KINDS
    if kind in allowed:
        return ""
    return i18n.t("translate.unknown-kind", kind=kind, allowed=", ".join(allowed))

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
    kind: str            # 'token' | 'phrase' | 'literal'
    file: str            # the dictionary file the entry lives in
    line: int            # 1-based
    scope: str = ""      # the owner of a qualified key (`<Owner>.<Name>`), empty for a plain one
    #: How many physical lines the entry occupies from `line` on. One for an ordinary
    #: `key: value`, two for the explicit form (`? key` / `: value`) - the writer replaces
    #: and removes the whole span, or half of an explicit entry would be left behind.
    span: int = 1

    def as_dict(self) -> dict:
        return {
            "key": self.key, "value": self.value, "kind": self.kind,
            "file": self.file, "line": self.line, "scope": self.scope,
        }


@dataclass
class Gap:
    """A name, a comment line or a string literal the dictionary does not cover yet."""

    key: str
    kind: str                       # 'token' | 'phrase' | 'literal'
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


def page_of(rows: list, limit: int, offset: int = 0, *, gaps: bool = False
            ) -> tuple[list, dict]:
    """One page of `rows`, plus the fields that say what the page LEFT OUT.

    A page used to arrive as `total: 72` beside exactly fifty rows and nothing else. The shape
    reads as a complete answer, and a dictionary built from one was short by twenty-two
    entries - found by the strict pass after the merge, when the batch was long written. So
    the cut is stated rather than implied: `truncated`, how many rows are left, and the two
    ways to get them (the next `offset`, or `limit=0` for the lot).
    """
    page = rows[offset:offset + limit] if limit else rows[offset:]
    seen = offset + len(page)
    remaining = len(rows) - seen
    fields = {"total": len(rows), "shown": len(page), "offset": offset,
              "truncated": remaining > 0}
    if remaining > 0:
        hint = i18n.t("translate.page.truncated", remaining=remaining, next_offset=seen)
        fields["remaining"] = remaining
        fields["hint"] = (hint + i18n.t("translate.page.gaps-file")) if gaps else hint
    return page, fields


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
        rows = text.splitlines()
        skip_to = 0
        for number, raw in enumerate(rows, 1):
            if number < skip_to:
                continue
            header = _SECTION_RE.match(raw)
            if header:
                section = header.group(1)
                continue
            if raw and not raw[0].isspace():
                section = ""  # any top-level key closes the section
                continue
            if not section or not raw.strip() or raw.lstrip().startswith("#"):
                continue
            explicit = _EXPLICIT_KEY_RE.match(raw)
            if explicit is not None:
                value_line = rows[number] if number < len(rows) else ""
                paired = _EXPLICIT_VALUE_RE.match(value_line)
                if paired is None:
                    continue  # a key without its value line is not an entry yet
                key = _key_of(explicit)
                if key:
                    out.append(_entry(key, _unquote(paired.group("value")),
                                      section, file, number, span=2))
                skip_to = number + 2
                continue
            m = _ENTRY_RE.match(raw)
            if m is None:
                continue
            key = _key_of(m)
            if not key:
                continue
            out.append(_entry(key, _unquote(m.group("value")), section, file, number))
    return out


def _entry(key: str, value: str, section: str, file: Path, line: int, span: int = 1) -> Entry:
    scope = key.partition(".")[0] if (section == "tokens" and "." in key) else ""
    return Entry(key=key, value=value, kind=KIND_OF_SECTION[section],
                 file=str(file), line=line, scope=scope, span=span)


def _key_of(m: re.Match) -> str:
    """The key of an entry line, decoded - the same string the caller asks the writer about."""
    if m.group("dq") is not None:
        return _unquote(f'"{m.group("dq")}"')
    if m.group("sq") is not None:
        return m.group("sq").replace("''", "'")
    return m.group("plain") or ""


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


#: A name as the language writes it: letters of either alphabet, digits and the underscore.
_WORD_RE = re.compile(r"[A-Za-zА-Яа-яЁё_][A-Za-zА-Яа-яЁё_0-9]*")
#: The body of a double-quoted literal, escaping kept as the source writes it.
_LITERAL_RE = re.compile(r'"((?:[^"\\]|\\.)*)"')


def _comment_bodies(path: Path, text: str) -> set[str]:
    """Every comment payload of one file, spelled the way the TRANSLATOR keys a phrase.

    The suffix decides the reading; the text is what the file holds. `_comment_bodies_of`
    does the work, so the same reading serves a file on disk and the lines a diff took out.

    The two readings have to agree character for character or a LIVE pair reads as an orphan -
    the one mistake `--prune` would act on. So this is not an imitation: a module is taken
    through the lexer and its comment tokens through `code.comment_payloads`, the very
    function the translating pass calls, block comments and `///` decoration included. A
    private regex of this module did neither, and answered a doc comment with a slash glued
    to the text.

    A resource - a stylesheet, a script, a page, a drawing - is read by `resourcefile`, the
    module the translating pass itself reads it with, for the same reason.

    A yaml file is read by its own pattern from EVERY `#` on the line, without the "inside a
    scalar" test the translator makes: the extra bodies that yields cost nothing (an entry
    stays in place), while a missed one costs a translation. The same reading serves a module
    the lexer cannot take - such a file translates to nothing anyway, so anything it yields
    is a bonus in the safe direction.
    """
    if path.suffix in (".xbsl", ".xbql"):
        from xbsl import engine

        try:
            text = engine.load(path).text
        except Exception:  # unreadable through the loader - the raw text still reads
            pass
    return _comment_bodies_of(path.suffix, text)


def _comment_bodies_of(suffix: str, text: str) -> set[str]:
    """The same reading over TEXT alone: what a diff hands over has no file behind it.

    A fragment is not a module - a removed block may open a comment it never closes - so the
    lexer is given the text and its refusal is expected, not exceptional: the marker reading
    takes over. Both directions of that error are harmless here, because the caller only ever
    INTERSECTS this set with the orphans of the whole project.
    """
    from xbsl.translation import code as code_module
    from xbsl.translation import resourcefile as resource_module
    from xbsl.translation import yamlfile as yaml_module

    if suffix == ".yaml":
        return _marked_bodies(text, "#", yaml_module._COMMENT_TEXT_RE)
    if suffix.lower() in resource_module.SUFFIXES:
        return {payload for _start, _end, payload in
                resource_module.resource_payloads(suffix, text)}
    if suffix not in (".xbsl", ".xbql"):
        return set()  # json carries keys and data, never a comment
    from xbsl import lexer

    try:
        tokens = lexer.tokenize(text)
    except Exception:  # a module the translating pass cannot read either
        return _marked_bodies(text, "//", code_module._LINE_COMMENT_RE)
    return {
        payload
        for token in tokens if token.kind == "COMMENT"
        for _offset, _index, payload in code_module.comment_payloads(token)
    }


def _marked_bodies(text: str, marker: str, pattern: re.Pattern) -> set[str]:
    """Payloads read straight off the lines, from every marker position on each."""
    out: set[str] = set()
    for raw in text.splitlines():
        line = raw.rstrip("\r\n")
        at = line.find(marker)
        while at != -1:
            found = pattern.match(line[at:])
            if found:
                out.add(found.group(2))
            at = line.find(marker, at + 1)
    return out


def _surfaces(root: Path, dictionary) -> tuple[set[str], set[str], set[str]]:
    """(names, comment lines, literal bodies) the project's sources carry, as written.

    Read textually rather than taken from a translation pass: the pass records the gaps it
    left, not the entries it applied, and teaching every one of its eleven writing sites to
    report the entry it used would put the answer at the mercy of the one site somebody
    forgets. The direction of the error matters more than its size here - a textual reading
    can call an orphan "used" (a name that also occurs in prose), and that only leaves an
    entry in place; it cannot call a LIVE entry an orphan, which is the mistake that would
    delete a translation the project still needs.
    """
    from xbsl.translation import project as project_module
    from xbsl.translation import resourcefile as resource_module

    names: set[str] = set()
    lines: set[str] = set()
    literals: set[str] = set()
    for path in project_module._iter_files(root, dictionary):
        # The PATH is translated too - every folder and file name goes through the same token
        # plane - so a name that only ever stands in a path is used. A resource referenced by
        # its file name alone (an icon next to the yaml that names it) is exactly that case.
        for part in path.relative_to(root).parts:
            names.update(_WORD_RE.findall(part))
        resource = path.suffix.lower() in resource_module.SUFFIXES
        if not resource and path.suffix not in (".yaml", ".xbsl", ".xbql", ".json"):
            continue
        try:
            text = path.read_text(encoding="utf-8-sig")
        except (OSError, UnicodeDecodeError):
            continue
        if not resource:
            # A stylesheet or a script is read for its PROSE alone. Its words are English
            # code, and feeding them in would answer for a name no source declares any more.
            names.update(_WORD_RE.findall(text))
            literals.update(_LITERAL_RE.findall(text))
        lines.update(_comment_bodies(path, text))
    return names, lines, literals


@dataclass
class Removal:
    """The surfaces a CHANGE took out of the sources, and what the diff behind them was.

    A project that has lived a while carries thousands of orphans - a dictionary of thirty
    thousand entries answered with three thousand of them - and every one is somebody's old
    deletion. The list is a review list, not a worklist, and the orphans of the change at hand
    are what a task actually has to clean up. Those are the entries whose key went missing
    from the project AND stood on a line this change removed.
    """

    #: What the diff was taken against, as git resolved it (a commit, or the range as given).
    base: str
    #: How many files the diff names - zero means the change removed nothing readable.
    files: int
    names: set[str] = field(default_factory=set)
    lines: set[str] = field(default_factory=set)
    literals: set[str] = field(default_factory=set)


def removed_surfaces(root: Path, since: str) -> Removal:
    """Names, comment lines and literal bodies that `since` .. the sources on disk removed.

    `since` is a branch or a commit - then the diff runs from where the branch parted from
    HEAD to the WORKING TREE, so work not committed yet counts as part of the change - or a
    range `A..B`, handed to git as written, which is how a change already merged is examined.

    Raises ValueError naming what failed: no git, not a repository, an unknown revision.
    """
    since = (since or "").strip()
    code, top, error = _git(root, "rev-parse", "--show-toplevel")
    if code != 0:
        raise ValueError(i18n.t("translate.since.not-a-repo", path=root))
    toplevel = Path(top.strip())
    if ".." in since:
        spec = since
    else:
        code, _out, _error = _git(root, "rev-parse", "--verify", "--quiet", f"{since}^{{commit}}")
        if code != 0:
            raise ValueError(i18n.t("translate.since.unknown-rev", rev=since))
        # The merge base, not the tip: a base branch that has moved on since the fork would
        # otherwise report ITS new lines as lines this change removed.
        code, merged, _error = _git(root, "merge-base", since, "HEAD")
        spec = merged.strip() or since
    code, diff, error = _git(
        root, "diff", "--unified=0", "--no-color", "--no-ext-diff", "--find-renames",
        spec, "--", ".",
    )
    if code != 0:
        raise ValueError(i18n.t("translate.since.diff-failed", rev=since, error=error.strip()))
    return _removal_of_diff(toplevel, spec, diff)


def _git(root: Path, *args: str) -> tuple[int, str, str]:
    """One git call under `root`: (exit code, stdout, stderr), both decoded as UTF-8.

    The output is decoded here rather than by the subprocess machinery because the sources
    are UTF-8 whatever the console codepage is, and a Windows shell would hand back mojibake
    for every Cyrillic name in the diff. `core.quotepath=false` is the same point for the
    PATHS: without it git escapes every non-Latin file name into octal.
    """
    import subprocess

    try:
        done = subprocess.run(
            ["git", "-c", "core.quotepath=false", *args],
            cwd=str(root), capture_output=True, timeout=300,
        )
    except FileNotFoundError:
        raise ValueError(i18n.t("translate.since.no-git")) from None
    return (done.returncode,
            done.stdout.decode("utf-8", "replace"),
            done.stderr.decode("utf-8", "replace"))


def _removal_of_diff(toplevel: Path, base: str, diff: str) -> Removal:
    """Read a unified diff for what it TOOK OUT, file by file.

    The file headers are read only outside a hunk. Inside one, a removed line that begins
    with `--` arrives as `--- ...` and is a line of source, not a header - reading it as a
    header would attribute the rest of the hunk to nothing.
    """
    removed: dict[str, list[str]] = {}
    seen: set[str] = set()
    path = ""
    in_hunk = False
    for raw in diff.splitlines():
        if raw.startswith("diff --git "):
            path, in_hunk = "", False
        elif raw.startswith("@@"):
            in_hunk = True
        elif not in_hunk and raw.startswith("--- "):
            name = raw[4:].strip()
            path = "" if name == "/dev/null" else name[2:] if name[:2] == "a/" else name
            if path:
                seen.add(path)
        elif in_hunk and path and raw.startswith("-"):
            removed.setdefault(path, []).append(raw[1:])
    from xbsl.translation import resourcefile as resource_module

    out = Removal(base=base, files=len(seen))
    for rel, body in removed.items():
        suffix = Path(rel).suffix
        resource = suffix.lower() in resource_module.SUFFIXES
        if not resource and suffix not in (".yaml", ".xbsl", ".xbql", ".json"):
            continue
        text = "\n".join(body)
        if not resource:
            out.names.update(_WORD_RE.findall(text))
            out.literals.update(_LITERAL_RE.findall(text))
        out.lines.update(_comment_bodies_of(suffix, text))
    for rel in seen:
        # A file that is gone took its PATH with it, and a path is a place a name may live -
        # the icon named by its file name alone is exactly that. A rename is the same event
        # seen from the old side.
        if not (toplevel / rel).exists():
            for part in Path(rel).parts:
                out.names.update(_WORD_RE.findall(part))
    return out


def unused_entries(root: Path, dictionary_path: Path, dictionary=None,
                   removed: Removal | None = None) -> list[Entry]:
    """Dictionary entries whose key the project no longer carries anywhere.

    Deleting code leaves its names and comment lines behind in the dictionary, and nothing
    said so: `--strict` judges what is NOT covered, and the entries table shows where a pair
    is declared, not whether anything uses it. One task left 43 of them, found only by a
    throwaway script.

    With `removed` the answer narrows to the orphans of ONE change: an entry is listed only
    when what went missing from the project is what that change took out. The narrowing is an
    intersection, never a shortcut - an entry the project still carries is not an orphan of
    anybody's change - so a diff read too generously cannot cost a translation.
    """
    names, lines, literals = _surfaces(root, dictionary)
    out: list[Entry] = []
    for entry in read_entries(dictionary_path):
        gone: list[str] = []
        if entry.kind == "phrase":
            gone = [] if entry.key in lines else [entry.key]
            missing = removed.lines if removed else None
        elif entry.kind == "literal":
            gone = [] if entry.key in literals else [entry.key]
            missing = removed.literals if removed else None
        else:
            # A qualified key (`<Owner>.<Name>`) gives one word to one owner, and the sources
            # spell the two halves apart: judging the dotted text as a name would call every
            # such entry an orphan. Both halves must still be there - an entry qualified by a
            # type the project no longer declares has nothing left to qualify.
            gone = [part for part in entry.key.split(".") if part not in names]
            missing = removed.names if removed else None
        if not gone:
            continue
        # The half that is gone is what the change must answer for: an entry orphaned because
        # its OWNER was deleted belongs to the change that deleted the owner, whatever else
        # the key still spells.
        if missing is not None and not all(part in missing for part in gone):
            continue
        out.append(entry)
    return out


def echoed_entries(root: Path, dictionary_path: Path, dictionary=None,
                   report=None) -> list[Entry]:
    """Dictionary entries the PLATFORM answers itself - the pass comes out the same without them.

    The opposite question to `unused_entries`: there a key the project no longer carries, here
    one it carries where the platform's own tables spell the very same word. Such an entry is
    invisible by construction - nothing is missing, nothing collides, the tree builds - and
    that is what makes it worth naming: while it stands, whatever the platform data or this
    engine fails to answer stays hidden behind it. The languages of a project were exactly
    that: one pair `Русский: Russian` in a live dictionary, and the half-translated enumeration
    behind it was found by a test on an empty dictionary, never by the project.

    The verdict comes from the PASS, not from a second reading of the tables: an entry is
    listed only when every place it answered would have been answered the same way without it
    (see Resolver.echoes), which is the same evidence the shadow report rests on - there the
    platform overrules the entry, here it repeats it. An entry the project never used is not
    listed at all: that is the orphan question, and it has its own answer.
    """
    from xbsl.translation import project as project_module

    if report is None:
        report = project_module.translate_project(root, dictionary, None)
    echoed = report.echoed
    return [entry for entry in read_entries(dictionary_path) if entry.key in echoed]


def gaps_of_project(root: Path, dictionary) -> list[Gap]:
    """What the translator leaves behind on this project, ready for the table."""
    from xbsl.translation import project as project_module

    return gaps_of_report(project_module.translate_project(root, dictionary, None))


def gaps_of_report(report) -> list[Gap]:
    """The same list out of a pass ALREADY made - the table mode reads one report twice.

    The suggestion is the PLATFORM's own spelling where it has one: most gaps of a real
    project are words the platform also knows, and the right value is usually exactly that
    spelling - the project simply named its own thing the same way.
    """
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
    # A literal carries no suggestion: the platform tables spell NAMES, and what stands
    # between the quotes is as often a sentence, where a table answer would be a guess.
    for text, info in report.merged_missing_literals().items():
        out.append(Gap(
            key=text, kind="literal", count=int(info.get("count") or 0),
            places=_places(report, text, "literal"),
        ))
    out.sort(key=lambda gap: (-gap.count, gap.key))
    return out


def _places(report, key: str, kind: str, limit: int = 20) -> list[tuple[str, int]]:
    """Where the gap occurs: (file, line) pairs, capped so one row stays small."""
    places: list[tuple[str, int]] = []
    for rel, file_report in sorted(report.files.items()):
        table = {
            "token": file_report.missing_tokens,
            "phrase": file_report.missing_phrases,
            "literal": file_report.missing_literals,
        }[kind]
        for line, _col in table.get(key, ()):
            places.append((rel, line))
            if len(places) >= limit:
                return places
    return places


def read_edits_file(path: Path) -> list[dict]:
    """Edits out of a file: the dictionary's own yaml format, or the JSON list.

    A batch of a real task runs to hundreds of entries, and that much inline JSON with
    Cyrillic and literal escaping is where mistakes come from - so a batch is authored the
    way the dictionary itself is written: `tokens`/`phrases`/`literals` sections, the same
    quoting (the entry reader is shared with the dictionary, escaping included), an empty
    value removes the entry. The JSON shape - `[{key, value, kind}]` or `{"edits": [...]}` -
    stays accepted: it is what scripts already produce for `--set`.

    Raises ValueError when neither shape yields entries: a silently empty batch would read
    as "nothing to change" over a file that simply had its sections misspelled.
    """
    text = path.read_text(encoding="utf-8-sig")
    if text.lstrip().startswith(("[", "{")):
        data = json.loads(text)
        edits = data.get("edits") if isinstance(data, dict) else data
        if not isinstance(edits, list):
            raise ValueError(i18n.t("translate.entries.edits-not-list"))
        return [dict(item) for item in edits if isinstance(item, dict)]
    entries = read_entries(path)
    if not entries:
        raise ValueError(i18n.t("translate.entries.edits-empty"))
    return [{"key": e.key, "value": e.value, "kind": e.kind} for e in entries]


def write_entries(dictionary_path: Path, edits: list[dict], target: str = DEFAULT_TARGET,
                  comment: str = "") -> dict:
    """Apply the edits to disk and report what happened (the CLI and MCP path)."""
    plan = plan_entries(dictionary_path, edits, target, comment)
    for path, text in plan["files"].items():
        file = Path(path)
        file.parent.mkdir(parents=True, exist_ok=True)
        file.write_text(text, encoding="utf-8", newline="")
    return {key: plan[key]
            for key in ("changed", "added", "removed", "rewritten", "refused", "collisions")}


def plan_entries(dictionary_path: Path, edits: list[dict], target: str = DEFAULT_TARGET,
                 comment: str = "") -> dict:
    """Compute the dictionary files AFTER the edits, without touching the disk.

    An edit is `{key, value, kind}`. An emptied value REMOVES the entry: a half-filled stub
    is not a translation, and leaving it would claim coverage the project does not have.

    `comment` is the head line a NEWLY created file gets. The caller knows what the batch is
    for, the writer does not: a file written from the MCP tool used to arrive announcing that
    it came from the editor panel, and the line was corrected by hand afterwards.

    The result is `{files: {path: the full new text}, changed, added, removed}`. Texts rather
    than writes are what an editor needs: the language server never writes to disk, so the
    client applies the result as a workspace edit and the user keeps undo.
    """
    known = {(entry.kind, entry.key): entry for entry in read_entries(dictionary_path)}
    by_file: dict[Path, list[tuple[Entry, dict]]] = {}
    fresh: list[dict] = []
    refused: list[dict] = []
    for edit in edits:
        key = str(edit.get("key") or "")
        kind = str(edit.get("kind") or "token")
        if not key:
            continue
        # A misspelled kind used to be written: the entry landed in a section named after it,
        # or the plan crashed on the unknown section. Refused here, where the value is in hand.
        reason = kind_refusal(kind, allow_any=False)
        if not reason and kind == "literal":
            reason = _literal_edit_refusal(key, str(edit.get("value") or ""))
        if reason:
            # Written now, refused at the next load - and the author would be a day away from
            # the entry by then. The same check answers here, while the value is still in hand.
            refused.append({"key": key, "kind": kind, "reason": reason})
            continue
        entry = known.get((kind, key))
        if entry is None:
            fresh.append({"key": key, "kind": kind, "value": str(edit.get("value") or "")})
        else:
            by_file.setdefault(Path(entry.file), []).append((entry, edit))

    changed = removed = 0
    # What exactly was overwritten. A bare count told the author that two existing entries got
    # a new value and left them to find WHICH by diffing the dictionary; one of the two turned
    # out to be a name that merely coincided with a new one, rewritten silently.
    rewritten: list[dict] = []
    files: dict[str, str] = {}
    for file, items in by_file.items():
        lines = file.read_text(encoding="utf-8-sig").splitlines(keepends=True)
        # Last line first: an earlier removal would shift the ones after it.
        for entry, edit in sorted(items, key=lambda pair: -pair[0].line):
            index = entry.line - 1
            if index >= len(lines):
                continue
            # The explicit form (`? key` / `: value`) occupies two lines, and both go: half
            # of it left behind is a stray mapping key the next load refuses.
            span = min(max(entry.span, 1), len(lines) - index)
            value = str(edit.get("value") or "")
            if not value:
                del lines[index:index + span]
                removed += 1
                continue
            indent = re.match(r"^[ \t]*", lines[index]).group(0)
            newline = "\r\n" if lines[index].endswith("\r\n") else "\n"
            lines[index:index + span] = [f"{indent}{scalar(entry.key)}: {scalar(value)}{newline}"]
            changed += 1
            if value != entry.value:
                rewritten.append({
                    "key": entry.key, "kind": entry.kind,
                    "was": entry.value, "now": value,
                    "file": str(file), "line": entry.line,
                })
        files[str(file)] = "".join(lines)

    added = 0
    if fresh:
        target_file, new_text, added = _plan_new(dictionary_path, fresh, target, comment,
                                                 planned=files)
        if added:
            files[str(target_file)] = new_text
    # `changed` stays a COUNT: the reports print it as a number. The names live beside it,
    # the way collisions do.
    return {"files": files, "changed": changed, "added": added, "removed": removed,
            "rewritten": sorted(rewritten, key=lambda row: (row["file"], row["line"])),
            "refused": refused, "collisions": _value_collisions(known, edits)}


def _value_collisions(known: dict, edits: list[dict]) -> list[dict]:
    """Edits whose value is ALREADY taken by another key of the same scope and plane.

    Two names translated into one word are a build breaker: the platform refuses a repeated
    name, and the translator reports it only when the whole project is passed through. Here
    the same answer costs one lookup, at the moment a person types the word - and it is a
    WARNING, not a refusal: a qualified key is exactly how one word is deliberately given to
    two owners.
    """
    by_value: dict[tuple[str, str, str], list[str]] = {}
    for (kind, key), entry in known.items():
        if kind != "token" or not entry.value:
            continue
        by_value.setdefault((kind, entry.scope, entry.value), []).append(key)
    out: list[dict] = []
    for edit in edits:
        key = str(edit.get("key") or "")
        value = str(edit.get("value") or "")
        kind = str(edit.get("kind") or "token")
        if not key or not value or kind != "token":
            continue
        scope = key.rsplit(".", 1)[0] if "." in key else ""
        taken = [name for name in by_value.get((kind, scope, value), ()) if name != key]
        if taken:
            out.append({"key": key, "value": value, "taken": sorted(taken)})
    return out


def _literal_edit_refusal(key: str, value: str) -> str:
    """Why this literal edit cannot be written; "" when it can.

    Both sides obey one convention - the text between the quotes as the source writes it - so
    both are checked against it. An emptied value REMOVES the entry and is not a body at all.
    """
    reason = dictionary_module.literal_body_error(key)
    if reason:
        return reason
    return dictionary_module.literal_body_error(value) if value else ""


def scalar(text: str) -> str:
    """One yaml scalar: a plain word stays plain, everything else is quoted."""
    if _BARE_SCALAR_RE.match(text) and text not in _RESERVED_SCALARS:
        return text
    return json.dumps(text, ensure_ascii=False)


#: The head line a new dictionary file gets when the caller names none. It says what the file
#: is rather than who wrote it: every surface writes such files, and a fixed provenance line
#: was wrong about all of them but one.
DEFAULT_COMMENT = "Записи словаря перевода."


def _plan_new(dictionary_path: Path, edits: list[dict], target: str,
              comment: str = "", planned: dict[str, str] | None = None
              ) -> tuple[Path, str, int]:
    """(the target file, its full text with the new entries, how many were added).

    `planned` holds the texts the same batch has already computed for the files it corrects
    and empties. The target may be one of them - then the new entries go on top of THAT text
    rather than the one on disk, which still carries the entries the batch has just removed.
    """
    file = dictionary_path / target if dictionary_path.is_dir() else dictionary_path
    sections = {
        section: {e["key"]: e["value"] for e in edits if e["kind"] == kind and e["value"]}
        for kind, section in SECTION_OF_KIND.items()
    }
    if not any(sections.values()):
        return file, "", 0
    if planned and str(file) in planned:
        text = planned[str(file)]
    elif file.exists():
        text = file.read_text(encoding="utf-8-sig")
    else:
        head = " ".join((comment or DEFAULT_COMMENT).split())
        text = (
            "version: 1\n"
            "language: en\n"
            "\n"
            f"# {head}\n"
        )
    for section, pairs in sections.items():
        text = _merge_section(text, section, pairs)
    return file, text, sum(len(pairs) for pairs in sections.values())


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
