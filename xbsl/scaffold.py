"""1C:Element metadata scaffolding: creating objects, fields, routes, forms and projects.

This module is the single source of templates and yaml/xbsl edits for every surface
of the toolkit: the meta_* MCP tools (mcp_server.py), the custom xbsl/meta* LSP
requests (lsp.py) and the CLI subcommands (cli.py). The VS Code extension is a thin
client of these surfaces and has no write logic of its own.

Layers:
    - pure text functions: inserting a section item (insert_item_edit and friends),
      templates of new objects and forms - no file system, covered by unit tests;
    - project discovery: a lightweight textual scan (projects, subsystems, objects,
      attributes) - same parsing conventions as the indexer, but without building
      a full index;
    - operations (op_*): collect changes into a ScaffoldResult {files to create + full
      new texts of edited files}, write NOTHING - applying is left to the caller:
      MCP/CLI write to disk (apply_result), the editor applies via WorkspaceEdit;
    - applying: apply_result saves with the newlines and BOM of the source file.

Yaml parsing here is textual (by section headers and indentation), not via PyYAML:
edits must be pinpoint insertions into the existing text, not a reformatting of the
document; a parser does not provide insertion positions.
"""

from __future__ import annotations

import re
import uuid as _uuid
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

from xbsl import dataset, engine, fixer, metamodel, terms

PROJECT_FILE = "Проект.yaml"
SUBSYSTEM_FILE = "Подсистема.yaml"

_WORD = "A-Za-zА-Яа-яЁё0-9_"  # identifier character class (for regex word boundaries)
_IDENTIFIER = re.compile(r"^[A-Za-zА-Яа-яЁё_][A-Za-zА-Яа-яЁё0-9_]*$")
_KIND_RE = re.compile(r"^ВидЭлемента:\s*(\S+)", re.M)
# The same key in the English spelling the platform declares for it.
_KIND_EN_RE = re.compile(r"^ElementKind:\s*(\S+)", re.M)
_LINE_INDENT = re.compile(r"^[ \t]*")


class ScaffoldError(RuntimeError):
    """Scaffolding operation error; the text is shown to the user as is."""


# --- bilingual yaml keys ----------------------------------------------------------------
#
# Sources may be written in either language: `ElementKind: Catalog` is the very same object as
# `ВидЭлемента: Справочник`, and the section `Attributes` is `Реквизиты` (demo-en/ is such a
# project, and it compiles). So everything below READS both spellings and WRITES the one the
# file around it uses, while the tables of this module stay keyed by the Russian names.


@lru_cache(maxsize=None)
def key_forms(name: str) -> tuple[str, ...]:
    """Both spellings of a yaml key, Russian first; just the Russian one when unpaired.

    The English spelling comes from the metamodel, where the platform declares it, and from
    nowhere else: `Реквизиты` is `Attributes` there, the compact term dictionary has no English
    for it at all, and a hand-made table would be a guess. An ambiguous name (the metamodel
    classes disagree) yields the Russian spelling alone - a false negative beats inventing a key.
    Without the data every key degrades to Russian, exactly as the tool worked before.
    """
    english = metamodel.english_name(name)
    return (name, english) if english and english != name else (name,)


@lru_cache(maxsize=None)
def field_forms(name: str) -> tuple[str, ...]:
    """Both spellings of a standard attribute name (`Наименование` is `Name`, `Дата` is `Date`).

    A standard attribute is not a yaml key but a member of the object, and members are named
    in the compiler dictionary rather than in the metamodel classes - hence the second source.
    """
    english = metamodel.english_name(name) or terms.common_english(name)
    return (name, english) if english and english != name else (name,)


@lru_cache(maxsize=None)
def _key_re(name: str) -> re.Pattern:
    """`^Ключ: значение` in either spelling of the key."""
    return re.compile(rf"^(?:{'|'.join(re.escape(f) for f in key_forms(name))}):\s*(\S+)", re.M)


dataset.register_reset(key_forms.cache_clear)
dataset.register_reset(field_forms.cache_clear)
dataset.register_reset(_key_re.cache_clear)

# Keys of section items that the scaffolding reads (see section_items). Listed one by one, and
# only where the platform itself names the pair: a wholesale reverse map would have to guess -
# `Name` is both `Имя` and `Наименование` depending on the class.
_ITEM_KEYS = ("Ид", "Имя", "Тип", "Шаблон", "ПолеРодителя", "Поставщик", "Версия")


@lru_cache(maxsize=1)
def _russian_item_keys() -> dict[str, str]:
    """{English spelling of an item key: the Russian one} - to read items under one set of keys."""
    return {forms[-1]: forms[0] for name in _ITEM_KEYS if len(forms := key_forms(name)) > 1}


dataset.register_reset(_russian_item_keys.cache_clear)


def element_kind(text: str) -> str | None:
    """The element kind of an object yaml as the metamodel names it, or None - not an object.

    Both the key and the value are bilingual, and the answer is always the Russian spelling:
    every table of this module (KIND_SECTIONS, ACCESS_KIND_RIGHTS, KIND_SPECS) is keyed by it.
    """
    m = _key_re("ВидЭлемента").search(text)
    return metamodel.canonical_kind(m.group(1)) if m else None


def element_name(text: str, default: str = "") -> str:
    """The value of the `Имя`/`Name` key of an element yaml, or the default."""
    m = _key_re("Имя").search(text)
    return m.group(1) if m else default


def yaml_language(text: str, directory: Path | None = None) -> str:
    """The language a yaml file spells its KEYS in: "ru" or "en".

    Decided by the file itself - it declares its element kind in one spelling or the other -
    and for a file that declares no kind (a project descriptor, a subsystem) by the project
    around it. Never by a setting: what the tool writes must look like the files next to it.
    """
    if _KIND_EN_RE.search(text):
        return "en"
    if _KIND_RE.search(text):
        return "ru"
    return project_language(directory) if directory is not None else "ru"


def spelled_key(name: str, lang: str) -> str:
    """A yaml key in the given language (the Russian one when the platform declares no pair)."""
    return key_forms(name)[-1] if lang == "en" else name


def spelled_property(name: str, lang: str) -> str:
    """A key of a form template: a metadata key, otherwise a component property.

    Two sources on purpose. A metadata key is declared by the metamodel classes, and there a
    guess is dangerous. A form is built of COMPONENTS, and their properties are members - named
    in the compiler dictionary, the same source the standard attributes come from. That the
    dictionary is right here is not a hope: the English demo project (which compiles) spells
    exactly these keys - `Content`, `MainCommand`, `WidthInColumns`.
    """
    if lang != "en":
        return name
    spelled = key_forms(name)[-1]
    return spelled if spelled != name else (terms.common_english(name) or name)


_LINE_KEY_RE = re.compile(rf"^([ \t]*(?:-[ \t]*)?)([{_WORD}]+):(.*)$")


def spelled_lines(lines: list[str], lang: str) -> list[str]:
    """Template lines with their KEYS in the given language; values are left as they are.

    A value is the author's data (a name, a type, a version) and the platform accepts a Russian
    one inside an English project - the keys are what has to match the file.
    """
    if lang != "en":
        return list(lines)
    out = []
    for line in lines:
        m = _LINE_KEY_RE.match(line)
        out.append(f"{m.group(1)}{spelled_key(m.group(2), lang)}:{m.group(3)}" if m else line)
    return out


# --- what the tool WRITES, in the language of the project ---------------------------------
#
# Reading both spellings was only half the job. A form generated into an English project used
# to arrive with Russian keys, Russian type names and a file called `TasksФормаСписка.yaml` -
# a Russian island in an English project, exactly what the reading side was fixed to avoid.
#
# Three kinds of words meet in a generated file, and each has its own source:
#   - KEYS and platform TYPE names belong to the platform - taken from its own data
#     (the metamodel and the term dictionaries), never from a hand-written table;
#   - the AUTHOR's names (the object, its attributes, its tabular parts) are not touched at
#     all: `Goods` stays `Goods` even when a platform type happens to be spelled the same;
#   - the words the TOOL invents (route handler names, the row-data structure of a list form)
#     have no platform pair, so they are listed below in both languages. That is the tool's
#     own vocabulary, and choosing it is legitimate - the same way `new-project` names things.

_TOKEN_RE = re.compile(rf"[{_WORD}]+")


def spelled_type(value: str, lang: str, keep: frozenset[str] = frozenset()) -> str:
    """Platform names inside a VALUE in the given language; `keep` is never translated.

    Token by token, because a value is a type expression rather than a word:
    `ФормаОбъекта<Goods.Объект>` has a platform type, an author's object and a platform facet
    in one line. A token the platform knows no English for stays as it is, and the author's
    names arrive in `keep` - so an object named like a platform type keeps its own name.
    """
    if lang != "en" or not value:
        return value

    def replace(match: re.Match) -> str:
        token = match.group(0)
        if token in keep:
            return token
        return terms.common_english(token) or terms.english(token, "types") or token

    return _TOKEN_RE.sub(replace, value)


def spelled_template(lines: list[str], lang: str, keep: frozenset[str] = frozenset()) -> list[str]:
    """Template lines fully in the given language: keys, and platform names in the values."""
    if lang != "en":
        return list(lines)
    out = []
    for line in lines:
        m = _LINE_KEY_RE.match(line)
        if not m:
            out.append(spelled_type(line, lang, keep) if line.lstrip().startswith("- ") else line)
            continue
        key = m.group(2) if m.group(2) in keep else spelled_property(m.group(2), lang)
        out.append(f"{m.group(1)}{key}:{spelled_type(m.group(3), lang, keep)}")
    return out


#: Form kinds the scaffolding produces - the suffix of the element name and of the file name.
FORM_SUFFIXES = ("ФормаОбъекта", "ФормаСписка", "ФормаОтчета")


def localize_form_text(text: str, info: dict, lang: str) -> str:
    """A generated form yaml in the language of the project it goes into.

    The generators build the Russian template (one shape, one place to read) and this pass
    puts it into the project's language: keys and platform names by the platform's own data,
    the composite `<Object><FormKind>` name by the same rule as the file name, and the two
    words the tool invents by its own vocabulary. Author names are protected.
    """
    if lang != "en":
        return text
    keep = author_names(info)
    out = "\n".join(spelled_template(text.split("\n"), lang, keep))
    obj = info.get("name", "")
    for suffix in FORM_SUFFIXES:
        english = form_suffix(suffix, lang)
        if english != suffix:
            out = out.replace(f"{obj}{suffix}", f"{obj}{english}")
    for russian, english in TOOL_WORDS_EN.items():
        out = out.replace(russian, english)
    return out


_CYRILLIC_RE = re.compile(r"[А-Яа-яЁё]")


def untranslated_words(text: str, keep: frozenset[str] = frozenset()) -> list[str]:
    """Russian words left in a text meant to be English - what the data could not name.

    Not every Russian word in a generated English file is a defect of the tool: the value
    lists of the INTERFACE enumerations (`ШиринаВКолонках: Одинарная`) exist in English in the
    platform, but the extracted data spells them in Russian only - the type is `WidthInColumns`
    while its values stay `Одинарная`. Guessing an English value would be inventing platform
    vocabulary, so the value is left as it is and the caller is told which ones - a note beats
    both a silent Russian island and a made-up word.
    """
    found = []
    for token in _TOKEN_RE.findall(text):
        if token in keep or token in found or not _CYRILLIC_RE.search(token):
            continue
        found.append(token)
    return found


def form_suffix(suffix: str, lang: str) -> str:
    """`ФормаСписка` / `ListForm` - the suffix of a form's name and of its file name.

    The convention `<Object><FormKind>` is the platform's own (the kinds are its type names),
    so the English project gets the English spelling of the very same convention.
    """
    if lang != "en":
        return suffix
    return terms.common_english(suffix) or terms.english(suffix, "types") or suffix


#: The tool's own words - the names it invents, which the platform never spells. Listed in
#: both languages because there is nowhere to look them up: a Russian name inside an English
#: project would be the tool's own Russian island, and inventing an English one on the fly
#: would give a different name on every code path.
TOOL_WORDS_EN = {
    "ДанныеСтрокиСписка": "ListRowData",
    "СтрокаСписка": "ListRow",
}


def tool_word(name: str, lang: str) -> str:
    """A word the tool invented, in the given language."""
    return TOOL_WORDS_EN.get(name, name) if lang == "en" else name


def author_names(info: dict) -> frozenset[str]:
    """Names that belong to the project and must survive translation untouched."""
    names = {info.get("name", ""), info.get("namespace", "")}
    for field in info.get("fields") or ():
        names.add(field.get("name", ""))
    for tabular in info.get("tabulars") or ():
        names.add(tabular.get("name", ""))
        for field in tabular.get("fields") or ():
            names.add(field.get("name", ""))
    return frozenset(name for name in names if name)


def _check_identifier(name: str, что: str) -> str:
    name = name.strip()
    if not _IDENTIFIER.match(name):
        raise ScaffoldError(
            f"Недопустимое имя {что}: '{name}' (нужен идентификатор: буквы, цифры, подчёркивание)"
        )
    return name


def new_uuid() -> str:
    return str(_uuid.uuid4())


# --- text edits ------------------------------------------------------------------------


@dataclass(frozen=True)
class TextEdit:
    start: int
    end: int
    new_text: str


def apply_edit(text: str, edit: TextEdit) -> str:
    return text[: edit.start] + edit.new_text + text[edit.end :]


def _line_end(text: str, offset: int) -> int:
    nl = text.find("\n", offset)
    return len(text) if nl == -1 else nl


def _detect_indent(body_slice: str, header_indent: int) -> tuple[str, str]:
    """Section item indents from the first existing "-" in the body; otherwise from the header."""
    m = re.search(r"^([ \t]*)-[ \t]*\r?\n([ \t]*)\S", body_slice, re.M)
    if m:
        return m.group(1), m.group(2)
    return " " * (header_indent + 4), " " * (header_indent + 8)


def _section_bounds(text: str, section: str, top_level: bool = False) -> tuple[int, int, int] | None:
    """(header indent, end of header line, end of body) of the section, or None.

    The body ends at the end of the last non-blank line indented deeper than the header.
    top_level=True - match only an unindented header: otherwise a NESTED section with the
    same name (`Реквизиты` inside a tabular part) would be taken for the object section.
    Calls on a block slice (tabular part attributes, Разрешения inside КонтрольДоступа)
    search at any indent.

    The section is looked up under both spellings of its name: `Attributes:` is the same
    section as `Реквизиты:` and callers name it the Russian way.
    """
    indent_pattern = "()" if top_level else "([ \t]*)"
    header = None
    for spelling in key_forms(section):
        header = re.search(rf"^{indent_pattern}{re.escape(spelling)}:[ \t]*\r?$", text, re.M)
        if header is not None:
            break
    if header is None:
        return None
    header_indent = len(header.group(1))
    header_line_end = _line_end(text, header.start())
    body_end = header_line_end
    pos = header_line_end
    while pos < len(text):
        line_start = pos + 1
        line_end = _line_end(text, line_start)
        line = text[line_start:line_end]
        blank = line.strip() == ""
        indent = len(_LINE_INDENT.match(line).group(0))
        if not blank and indent <= header_indent:
            break
        if not blank:
            body_end = line_end
        pos = line_end
    return header_indent, header_line_end, body_end


def insert_item_edit(text: str, section: str, item_lines: list[str], nl: str = "\n",
                     top_level: bool = False, lang: str = "ru") -> TextEdit:
    """Pinpoint insertion of a new item (a set of field lines) at the end of a section.

    If the section is missing, it is appended at the end of the file. top_level=True -
    only an unindented section (otherwise an object attribute would land in a nested
    tabular part section). A port of insertItemEdit from the VS Code extension
    (metadataCore.ts) with one difference: the newline is passed as a parameter so the
    edit does not mix styles in CRLF files.

    The section is named the Russian way by the caller and found under either spelling;
    lang is the spelling to CREATE it in when it is not there yet.
    """

    def body(item: str, fld: str) -> str:
        return f"{item}-{nl}" + nl.join(f"{fld}{line}" for line in item_lines)

    bounds = _section_bounds(text, section, top_level)
    if bounds is None:
        tail = "" if (not text or text.endswith("\n")) else nl
        new = f"{tail}{spelled_key(section, lang)}:{nl}{body('    ', '        ')}{nl}"
        return TextEdit(len(text), len(text), new)

    header_indent, header_line_end, body_end = bounds
    item, fld = _detect_indent(text[header_line_end:body_end], header_indent)
    insert_at = body_end
    return TextEdit(insert_at, insert_at, f"{nl}{body(item, fld)}")


def insert_nested_item_edit(
    text: str, block_offset: int, section: str, item_lines: list[str], nl: str = "\n",
    lang: str = "ru",
) -> TextEdit:
    """Insert an item into a nested section of an item block (e.g. tabular part Реквизиты).

    block_offset is the offset of the block's first key (see find_section_item_offset).
    The block ends before the first non-blank line indented less than the block's fields.
    A port of insertTabularAttrEdit. lang - see insert_item_edit.
    """
    line_start = text.rfind("\n", 0, block_offset) + 1
    field_indent = block_offset - line_start
    block_end = len(text)
    pos = _line_end(text, block_offset)
    while pos < len(text):
        ls = pos + 1
        le = _line_end(text, ls)
        line = text[ls:le]
        if line.strip() != "" and len(_LINE_INDENT.match(line).group(0)) < field_indent:
            block_end = ls
            break
        pos = le
    block = text[block_offset:block_end]
    for spelling in key_forms(section):
        if re.search(rf"^[ \t]{{{field_indent}}}{re.escape(spelling)}:[ \t]*\r?$", block, re.M):
            sub = insert_item_edit(block, spelling, item_lines, nl)
            return TextEdit(block_offset + sub.start, block_offset + sub.end, sub.new_text)
    # No nested section - append it at the end of the block content.
    head = " " * field_indent
    item = " " * (field_indent + 4)
    fld = " " * (field_indent + 8)
    content_end = 0
    p = 0
    while p < len(block):
        e = block.find("\n", p)
        end = len(block) if e == -1 else e
        if block[p:end].strip() != "":
            content_end = end
        if e == -1:
            break
        p = e + 1
    body = nl.join(f"{fld}{line}" for line in item_lines)
    new = f"{nl}{head}{spelled_key(section, lang)}:{nl}{item}-{nl}{body}"
    return TextEdit(block_offset + content_end, block_offset + content_end, new)


def section_items(text: str, section: str, top_level: bool = False) -> list[dict[str, str]]:
    """Scalar fields of section items (for duplicate checks and overview).

    An item is a block after "-" at the minimal indent of the section body; nested item
    sections (tabular part Реквизиты, template Методы) do not make it into the dict,
    their fields are indented deeper than the item fields. top_level=True - only the
    object-level section, unindented (see _section_bounds).

    The keys the scaffolding reads come back under their Russian spelling whatever the file
    writes (`Name: Steps` reads as `Имя`), so callers have one set of keys to know; the rest
    of the keys are returned as written.
    """
    russian = _russian_item_keys()
    bounds = _section_bounds(text, section, top_level)
    if bounds is None:
        return []
    _, header_line_end, body_end = bounds
    body = text[header_line_end:body_end]
    m = re.search(r"^([ \t]*)-", body, re.M)
    if m is None:
        return []
    item_indent = len(m.group(1))
    items: list[dict[str, str]] = []
    current: dict[str, str] | None = None
    field_indent: int | None = None
    for line in body.split("\n"):
        stripped = line.strip()
        if not stripped:
            continue
        indent = len(_LINE_INDENT.match(line).group(0))
        if indent == item_indent and stripped.startswith("-"):
            if current is not None:
                items.append(current)
            current = {}
            field_indent = None
            rest = stripped[1:].strip()
            if rest and ":" in rest:  # inline form "- Имя: X"
                k, _, v = rest.partition(":")
                key = k.strip()
                current[russian.get(key, key)] = v.strip()
            continue
        if current is None:
            continue
        if field_indent is None and indent > item_indent and ":" in stripped:
            field_indent = indent
        if indent == field_indent and ":" in stripped and not stripped.startswith("-"):
            k, _, v = stripped.partition(":")
            v = v.strip()
            if v:
                key = k.strip()
                current[russian.get(key, key)] = v
    if current is not None:
        items.append(current)
    return items


def find_section_item_offset(text: str, section: str, name: str,
                             top_level: bool = True) -> int | None:
    """Offset of the first key of the section item with Имя == name (for nested inserts).

    Searched in the object-level section (unindented): callers address ТабличныеЧасти
    and ШаблоныUrl. The name key is read in either spelling (`Имя:` or `Name:`).
    """
    name_keys = tuple(f"{form}:" for form in key_forms("Имя"))
    bounds = _section_bounds(text, section, top_level)
    if bounds is None:
        return None
    _, header_line_end, body_end = bounds
    body = text[header_line_end:body_end]
    m = re.search(r"^([ \t]*)-", body, re.M)
    if m is None:
        return None
    item_indent = len(m.group(1))
    pos = 0
    current_start: int | None = None
    current_named = False
    for raw in body.split("\n"):
        line_len = len(raw) + 1
        stripped = raw.strip()
        indent = len(_LINE_INDENT.match(raw).group(0))
        if stripped.startswith("-") and indent == item_indent:
            current_start = None
            current_named = False
        elif stripped and current_start is None and indent > item_indent:
            current_start = header_line_end + pos + indent
        key = next((k for k in name_keys if stripped.startswith(k)), None)
        if key is not None and current_start is not None and not current_named:
            value = stripped[len(key):].strip()
            if value == name:
                return current_start
            current_named = True
        pos += line_len
    return None


def top_level_key_span(text: str, key: str) -> tuple[int, int] | None:
    """(start of the key line, end of body) of a top-level key with nested content."""
    m = None
    for spelling in key_forms(key):
        m = re.search(rf"^{re.escape(spelling)}:[ \t]*\r?$", text, re.M)
        if m is not None:
            break
    if m is None:
        return None
    bounds = _section_bounds(text, key)
    if bounds is None:
        return None
    _, _, body_end = bounds
    return m.start(), body_end


# --- templates of new objects -----------------------------------------------------------


# The header keys of any object, in the spelling the metamodel states for each of them. A project
# written in English gets an English header: the file the tool writes must look like the files
# around it, not like a Russian island in an English project.
_HEADER_KEYS = ("ВидЭлемента", "Ид", "Имя", "ОбластьВидимости")


def project_language(directory: Path) -> str:
    """The language the project around `directory` writes its metadata in: "ru" or "en".

    Decided by the sources themselves - the first yaml that declares an element kind wins - and
    not by a setting: the tool has to match what is already there. Russian is the answer when
    nothing is found, which is what the tool has always written.
    """
    root = directory
    for candidate in (directory, *directory.parents):
        if (candidate / PROJECT_FILE).exists():
            root = candidate
            break
    russian = english = 0
    for path in sorted(root.rglob("*.yaml")):
        try:
            head = path.read_text(encoding="utf-8-sig", errors="replace")[:4096]
        except OSError:  # pragma: no cover - unreadable file, nothing to learn from it
            continue
        # By MAJORITY, not by the first hit: one file of the other spelling (a leftover, a
        # fragment copied from elsewhere) must not flip the language of the whole project.
        if _KIND_RE.search(head):
            russian += 1
        elif _KIND_EN_RE.search(head):
            english += 1
    return "en" if english > russian else "ru"


def _spelled(name: str, lang: str, section: str = "") -> str:
    """A metadata VALUE in the project's language, falling back to the Russian one.

    Values (a kind, an enumeration value) live in the term dictionary; the KEYS around them
    are spelled by spelled_key, which asks the metamodel - the two dictionaries name different
    things and disagree where they overlap (`Поставщик` is the property `Vendor`, but the
    compiler's word for the same root is `Provider`).
    """
    if lang != "en":
        return name
    english = None
    if section:
        english = terms.english(name, section)
    return english or terms.common_english(name) or name


def new_object_yaml(
    kind: str, uid: str, name: str, scope: str, extra_lines: list[str], lang: str = "ru",
) -> str:
    keys = [spelled_key(k, lang) for k in _HEADER_KEYS]
    values = [_spelled(kind, lang, "types"), uid, name, _spelled(scope, lang, "enums")]
    lines = [f"{k}: {v}" for k, v in zip(keys, values)]
    return "\n".join(lines + spelled_lines(list(extra_lines), lang)) + "\n"


def _expand_extra(lines: tuple[str, ...], name: str) -> list[str]:
    """Substitute the name and a unique Ид for every {uuid} occurrence in object template lines."""
    out = []
    for line in lines:
        while "{uuid}" in line:
            line = line.replace("{uuid}", new_uuid(), 1)
        out.append(line.format(name=name) if "{name}" in line else line)
    return out


@dataclass(frozen=True)
class KindSpec:
    # The visibility default is the platform's: "Стандартно элемент виден только внутри
    # своей подсистемы (ВПодсистеме)... Если хочется использовать в других подсистемах –
    # нужно установить ВПроекте" ("Модульная разработка" documentation). The tool does not
    # widen visibility on the developer's behalf: wider - via an explicit scope parameter.
    scope: str = "ВПодсистеме"
    module: bool = False  # create a paired module file
    module_suffix: str = ".xbsl"  # for ВиртуальнаяТаблица the paired file is a .xbql query
    module_stub: str = ""  # module template ({name}); empty - a comment with the name
    extra: tuple[str, ...] = ()  # extra template lines (may contain {name})
    # The kind requires data from the caller (Отчет - source and layout): there is nothing
    # to offer for it in the "create" menu, so it is excluded from the parameterless
    # showcase (bare_kinds).
    needs_args: bool = False
    # What is left to fill in by hand: the platform will not supply it, and the generator
    # does not make it up.
    note: str = ""


# Module stubs: the handler without which an element of the kind is useless. Signatures
# are taken verbatim from the documentation (verified against working code where it exists).
_STUB_HANDLER = """\
@Обработчик
метод Обработчик()
    // TODO: действия команды
;
"""
_STUB_JOB = """\
@Обработчик
метод Обработчик()
    // TODO: логика запланированного задания
;
"""
_STUB_CLIENT_PARAMS = """\
@Обработчик
метод ВычислитьПараметрыРаботыКлиента()
    // TODO: вычислить значения параметров (выполняется на сервере при открытии приложения)
;
"""
# Action privilege: the element name is substituted into the generic parameters;
# КлючДоступа.Объект is the literal base type of keys (confirmed by the working
# ПравоМодератора.xbsl).
_STUB_ACTION_PRIVILEGE = """\
@Обработчик
метод ВычислитьРазрешенияДоступа(Права: ЧитаемыйМассив<{name}.Объект>):
        ЧитаемоеСоответствие<{name}.Объект, ЧитаемаяКоллекция<КлючДоступа.Объект>>
    // TODO: вернуть соответствие "экземпляр права -> ключи доступа, которым оно выдано"
    возврат {{:}}
;
"""
_STUB_SELF_REGISTRATION = """\
@Обработчик
метод ПослеПодключения()
    // TODO: действия после подключения пользователя (выполняется на сервере)
;
"""
# Access key: the mandatory handler matches key instances to the users who hold them
# (the signature is verbatim from the "manage-access-control" documentation;
# Пользователи.Ссылка is a facet of the system type - valid in any project).
_STUB_ACCESS_KEY = """\
@Обработчик
метод ПроверитьНаличиеКлючейДоступа(
        Ключи: ЧитаемыйМассив<{name}.Объект>,
        ПользователиДляПроверки: ЧитаемыйМассив<Пользователи.Ссылка>
    ): ЧитаемоеСоответствие<{name}.Объект, ЧитаемыйМассив<Пользователи.Ссылка>>
    // TODO: вернуть соответствие "экземпляр ключа -> пользователи, у которых он есть"
    возврат {{:}}
;
"""
# Command with a component: the component the command acts on is этот.Компонент
# (the "КомандаСКомпонентом" documentation example is a form-closing command).
_STUB_COMPONENT_COMMAND = """\
@Обработчик
метод Обработчик()
    // TODO: действие над компонентом, напр. знч Форма = этот.Компонент; Форма.Закрыть()
;
"""
_STUB_SERVICE_CONTRACT = """\
// Контракт состоит из абстрактных методов; реализуют их элементы проекта,
// которые объявляют этот контракт в НастройкиТипа.Контракты. Например:
// абстрактный метод Рассчитать(Параметр: Строка): Число
"""

# Creatable object kinds. The full list of kinds is Стд::Отражение::ВидЭлементаПроекта;
# here are those that make sense to create as files. Deliberately not included:
# ПанельОтчетов and ПроцессИнтеграции (their content is drawn in the designer, the process
# also has node coordinates; unavailable in the cloud), КлиентSoapСервиса (useless without
# a WSDL loaded from the IDE).
# Mandatory starter fields: without them the object does not compile, and the platform
# will not supply them. Документ - the Дата attribute ("Обязан присутствовать всегда.
# Если реквизит отсутствует – выдается ошибка"), a standard one, hence without Ид.
# РегистрСведений - a non-empty list of dimensions ("Список измерений не может быть
# пустым"); a dimension cannot be an unbounded Строка, hence МаксимальнаяДлина.
# РегистрНакопления - a non-empty list of resources ("Список ресурсов не может быть
# пустым"); the mandatory Регистратор attribute is added by hand (its type is a union of
# references to registrar documents, which do not exist yet at creation time).
_DOC_EXTRA = (
    "Реквизиты:",
    "    -",
    "        Имя: Дата",
    "        Тип: ДатаВремя",
)
_INFO_REGISTER_EXTRA = (
    "Измерения:",
    "    -",
    "        Ид: {uuid}",
    "        Имя: Измерение1",
    "        Тип: Строка",
    "        МаксимальнаяДлина: 50",
)
_ACC_REGISTER_EXTRA = (
    "Ресурсы:",
    "    -",
    "        Ид: {uuid}",
    "        Имя: Ресурс1",
    "        Тип: Число",
)
_ACC_REGISTER_NOTE = (
    "Регистр накопления требует стандартный реквизит Регистратор – добавьте его "
    "(Тип: объединение ссылок на документы-регистраторы, напр. Накладная.Ссылка|?), "
    "иначе регистр не компилируется"
)

KIND_SPECS: dict[str, KindSpec] = {
    "Справочник": KindSpec(),
    "Документ": KindSpec(extra=_DOC_EXTRA),
    "Перечисление": KindSpec(),
    "Структура": KindSpec(extra=("Окружение: КлиентИСервер",)),
    "ХранимаяСтруктура": KindSpec(),
    "РегистрСведений": KindSpec(extra=_INFO_REGISTER_EXTRA),
    "РегистрНакопления": KindSpec(extra=_ACC_REGISTER_EXTRA, note=_ACC_REGISTER_NOTE),
    "ПланОбмена": KindSpec(),
    "НаборКонстант": KindSpec(),
    "ХранилищеНастроек": KindSpec(),
    # The paired file is NOT a module but a .xbql query: "наличие файла и запроса в нем
    # обязательно". The IDE creates it empty - we do the same and state the requirement
    # in notes.
    "ВиртуальнаяТаблица": KindSpec(
        module=True, module_suffix=".xbql", module_stub="\n",
        note="Запрос виртуальной таблицы обязателен: заполните парный .xbql "
             "(пустой файл – невалидный элемент) и объявите в Параметры все параметры запроса",
    ),
    "Обработка": KindSpec(
        module=True,
        module_stub="// На каждую операцию из секции Операции нужен метод-обработчик с "
                    "тем же именем:\n// @Обработчик\n// метод РассчитатьВсе()\n// ;\n",
        note="Обработка без операций бесполезна: добавьте Операции и одноимённые "
             "@Обработчик-методы в модуль (иначе ошибка \"Обязательный обработчик не определен\")",
    ),
    "ЗапланированноеЗадание": KindSpec(
        module=True, module_stub=_STUB_JOB,
        note="Расписание не задано – ПредопределенноеЗадание может быть только НеСоздавать",
    ),
    "СобытиеЖурналаСобытий": KindSpec(
        extra=("ВидСобытия: Информация", "ШаблонПредставления: {name}"),
        note="Для ВидСобытия: Ошибка нужен ещё ХарактерОшибки, для Операция – "
             "ШаблонПредставленияНачала, ШаблонПредставленияКонца и ШаблонПредставленияОшибки",
    ),
    # The module is mandatory: the platform expects the ВычислитьПараметрыРаботыКлиента
    # handler in it, without which the parameters are not computed ("ПараметрыРаботыКлиента"
    # documentation).
    "ПараметрыРаботыКлиента": KindSpec(module=True, module_stub=_STUB_CLIENT_PARAMS),
    "ОбщийМодуль": KindSpec(module=True, extra=("Окружение: Сервер",)),
    "HttpСервис": KindSpec(module=True, extra=("КорневойUrl: /{name}",)),
    # SoapСервис is created by the _new_soap_service generator (intercepted in
    # op_new_object before the generic path), like HttpСервис - the spec exists only so
    # the kind counts as creatable.
    "SoapСервис": KindSpec(module=True),
    "ГлобальноеКлиентскоеСобытие": KindSpec(),
    "ФрагментКомандногоИнтерфейса": KindSpec(),
    # `Форма.Содержимое` is typed `ШаблонФормы?`, so a Группа cannot sit there directly -
    # the server rejects the build with `Значение типа "Группа" не может быть присвоено в
    # "ШаблонФормы?"`. The template wrapper is what real forms carry.
    "КомпонентИнтерфейса": KindSpec(
        extra=(
            "Наследует:",
            "    Тип: Форма",
            "    Содержимое:",
            "        Тип: ПроизвольныйШаблонФормы",
            "        Содержимое:",
            "            Тип: Группа",
            "            Компоновка: Вертикальная",
        ),
    ),
    "КлючДоступа": KindSpec(module=True, module_stub=_STUB_ACCESS_KEY),
    "ЛокализованныеСтроки": KindSpec(),
    "Отчет": KindSpec(needs_args=True),
    # Privileges: an ON-ELEMENT privilege has no module ("Не имеет модуля" - it is an
    # enumeration), an ON-ACTION privilege's module computes permissions on the server.
    "ПравоНаЭлемент": KindSpec(),
    "ПравоНаДействие": KindSpec(module=True, module_stub=_STUB_ACTION_PRIVILEGE),
    # Contracts: a module is needed only for abstract methods, so we do not create one for
    # type and entity contracts (properties only) - such contracts have no modules.
    "КонтрактСервиса": KindSpec(module=True, module_stub=_STUB_SERVICE_CONTRACT),
    "КонтрактТипа": KindSpec(),
    "КонтрактСущности": KindSpec(
        note="ТаблицыКонтракта по умолчанию Недоступны – с ним контракт не виден в запросах; "
             "нужны таблицы – добавьте ТаблицыКонтракта: Доступны",
    ),
    # Commands: the navigation command's behavior is fully declarative (ТипФормы), for the
    # rest the point is the module handler (executed on the client).
    "НавигационнаяКоманда": KindSpec(
        extra=("Представление: {name}",),
        note="Задайте ТипФормы – форму, которую открывает команда; без неё команда ничего не делает",
    ),
    "ОбычнаяКоманда": KindSpec(
        module=True, module_stub=_STUB_HANDLER, extra=("Представление: {name}",),
    ),
    "ПереключаемаяКоманда": KindSpec(
        module=True, module_stub=_STUB_HANDLER,
        extra=("ПредставлениеАктивного: {name}", "ПредставлениеНеактивного: {name}"),
        note="Задайте пару представлений (активное/неактивное) и Активна – это смысл вида",
    ),
    # The property is named ТипКомпонента, as in all YAML examples of the documentation;
    # the "Компонент" variant from the property list was tested by deployment and is
    # rejected by the compiler ("Неизвестное свойство"). In the module the command's
    # component is available as этот.Компонент.
    "КомандаСКомпонентом": KindSpec(
        module=True, module_stub=_STUB_COMPONENT_COMMAND,
        extra=("Представление: {name}", "ТипКомпонента: Форма"),
        note="ТипКомпонента: Форма – заглушка; укажите тип компонента, над которым "
             "выполняется команда, и используйте его в модуле через этот.Компонент",
    ),
    "ЦветоваяСхемаОтчета": KindSpec(
        extra=("Представление: {name}",),
        note="Заполните Цвета (Массив<АбсолютныйЦвет>, напр. RGB(009E73)); "
             "ЦветаТемнойТемы необязательны – без них берутся Цвета",
    ),
    "ПараметрСамостоятельнойРегистрацииПользователя": KindSpec(
        module=True, module_stub=_STUB_SELF_REGISTRATION,
        note="Обработчик ПослеПодключения обязателен; параметр работает в связке с "
             "КомпонентСамостоятельнойРегистрации и свойством проекта "
             "КлиентскоеПриложениеСамостоятельнойРегистрации",
    ),
}


def bare_kinds() -> list[str]:
    """Kinds creatable from a name alone - they can be shown in a "create" menu as is."""
    return sorted(k for k, spec in KIND_SPECS.items() if not spec.needs_args)

# Extendable sections: the yaml section + the lines of a new item.
_WITH_TYPE = ("Ид: {uuid}", "Имя: {name}", "Тип: {type}")
_SECTION_SPECS: dict[str, dict] = {
    "реквизит": {"section": "Реквизиты", "lines": _WITH_TYPE},
    "измерение": {"section": "Измерения", "lines": _WITH_TYPE},
    "ресурс": {"section": "Ресурсы", "lines": _WITH_TYPE},
    "значение": {"section": "Элементы", "lines": ("Ид: {uuid}", "Имя: {name}")},
    "параметр": {"section": "Параметры", "lines": ("Имя: {name}", "Тип: {type}")},
    "поле": {"section": "Поля", "lines": ("Имя: {name}", "Тип: {type}")},
    "константа": {"section": "Константы", "lines": _WITH_TYPE},
    "свойство": {"section": "Свойства", "lines": ("Имя: {name}", "Тип: {type}")},
    # Data processor operation: the name goes into yaml, and a same-named @Обработчик
    # method is appended to the module (without it the platform raises "Обязательный
    # обработчик не определен" - see op_add_field).
    "операция": {"section": "Операции", "lines": ("Имя: {name}",)},
    # Index of an object or tabular part: a name + a list of fields. The starter field is
    # a placeholder (the Поля list cannot be empty); real attributes are filled in later,
    # so a reminder goes into notes.
    "индекс": {"section": "Индексы", "lines": ("Имя: {name}", "Поля:", "    - Реквизит1")},
    # Report query parameter: a name + a type (the ПараметрыЗапроса section, read by object_info).
    "параметр-запроса": {"section": "ПараметрыЗапроса", "lines": ("Имя: {name}", "Тип: {type}")},
    "табличная-часть": {
        "section": "ТабличныеЧасти",
        # A tabular part with one starter attribute (an empty one is usually useless).
        "lines": (
            "Ид: {uuid}",
            "Имя: {name}",
            "Реквизиты:",
            "    -",
            "        Ид: {uuid2}",
            "        Имя: Реквизит1",
            "        Тип: Строка",
        ),
    },
}

# Mapping sections "Ключ: Значение" (not a list of items with "-"): ЛокализованныеСтроки.
# quote - wrap the value in quotes (templates may contain spaces and %0/$0 substitutions).
_MAPPING_SPECS: dict[str, dict] = {
    "строка": {"section": "Строки", "quote": False},
    "шаблон": {"section": "Шаблоны", "quote": True},
}

# Object kind -> which sections of it are extendable.
KIND_SECTIONS: dict[str, tuple[str, ...]] = {
    # Tabular parts - only on reference entities ("Табличная часть" documentation:
    # Справочник, Документ, ПланОбмена, ХранилищеНастроек, КонтрактСущности).
    # Indexes - on objects with stored data (documentation: a set of primary/additional
    # fields over which a DB index is created).
    "Справочник": ("реквизит", "табличная-часть", "индекс"),
    "Документ": ("реквизит", "табличная-часть", "индекс"),
    "ПланОбмена": ("реквизит", "табличная-часть", "индекс"),
    "ХранилищеНастроек": ("реквизит", "табличная-часть"),
    "РегистрСведений": ("измерение", "ресурс", "реквизит", "индекс"),
    "РегистрНакопления": ("измерение", "ресурс", "реквизит", "индекс"),
    "НаборКонстант": ("константа",),
    "Обработка": ("реквизит", "операция"),
    "Отчет": ("параметр-запроса",),
    "ЛокализованныеСтроки": ("строка", "шаблон"),
    "Перечисление": ("значение",),
    "ПараметрыРаботыКлиента": ("параметр",),
    "ГлобальноеКлиентскоеСобытие": ("параметр",),
    "ЗапланированноеЗадание": ("параметр",),
    "ВиртуальнаяТаблица": ("параметр",),
    "Структура": ("поле",),
    "ХранимаяСтруктура": ("поле",),
    "ПараметрСамостоятельнойРегистрацииПользователя": ("поле",),
    "КлючДоступа": ("параметр",),
    "ПравоНаДействие": ("параметр",),
    "ПравоНаЭлемент": ("значение",),  # the Элементы section: actions of the privilege
    "КонтрактТипа": ("свойство",),
    "КонтрактСущности": ("свойство", "табличная-часть"),
    "СобытиеЖурналаСобытий": ("свойство",),
}

# Line sets that differ from the kind's common ones: for ХранимаяСтруктура fields and
# КлючДоступа parameters the documentation describes an Ид - it keeps the data binding
# across renames (a plain Структура and ПараметрыРаботыКлиента have no Ид in their sets).
_KIND_SECTION_LINES: dict[tuple[str, str], tuple[str, ...]] = {
    ("ХранимаяСтруктура", "поле"): _WITH_TYPE,
    ("КлючДоступа", "параметр"): _WITH_TYPE,
    ("ПравоНаДействие", "параметр"): _WITH_TYPE,
    ("ЗапланированноеЗадание", "параметр"): _WITH_TYPE,
    ("КонтрактСущности", "свойство"): _WITH_TYPE,
}

FIELD_KINDS = tuple(_SECTION_SPECS)


# --- project discovery ------------------------------------------------------------------


def _read(path: Path) -> str:
    return engine.load(path).text


@dataclass
class ObjectHit:
    kind: str
    name: str
    path: Path  # the object's yaml
    subsystem: str | None
    namespace: str  # vendor::project::subsystem
    text: str = field(repr=False, default="")


def find_projects(root: Path) -> list[dict]:
    """Projects under the root: [{vendor, name, dir, subsystems: [names]}], hidden directories skipped."""
    out = []
    for project_yaml in sorted(root.rglob(PROJECT_FILE)):
        rel = project_yaml.relative_to(root)
        if any(part.startswith(".") for part in rel.parts):
            continue
        text = _read(project_yaml)
        project_dir = project_yaml.parent
        vendor = _vendor_of(text, project_dir.parent.name)
        name = element_name(text, project_dir.name)
        subsystems = sorted(
            p.parent.name for p in project_dir.rglob(SUBSYSTEM_FILE)
            if not any(part.startswith(".") for part in p.relative_to(project_dir).parts)
        )
        out.append({
            "vendor": vendor, "name": name, "dir": project_dir, "subsystems": subsystems,
            "libraries": project_libraries(text),
        })
    return out


def _vendor_of(text: str, default: str) -> str:
    """The `Поставщик`/`Vendor` of a project descriptor, or the default."""
    m = _key_re("Поставщик").search(text)
    return m.group(1) if m else default


def _iter_objects(root: Path):
    for yaml_path in engine.find_sources(root, "*.yaml"):
        if yaml_path.name in (PROJECT_FILE, SUBSYSTEM_FILE):
            continue
        text = _read(yaml_path)
        kind = element_kind(text)
        if kind is None:
            continue
        yield yaml_path, kind, element_name(text, yaml_path.stem), text


def _namespace_of(yaml_path: Path, root: Path) -> tuple[str | None, str]:
    """(subsystem name, vendor::project::subsystem) for an object file."""
    subsystem = yaml_path.parent.name if (yaml_path.parent / SUBSYSTEM_FILE).is_file() else None
    project_dir = yaml_path.parent
    while project_dir != project_dir.parent:
        if (project_dir / PROJECT_FILE).is_file():
            break
        if project_dir == root:
            break
        project_dir = project_dir.parent
    vendor = project = ""
    project_yaml = project_dir / PROJECT_FILE
    if project_yaml.is_file():
        text = _read(project_yaml)
        vendor = _vendor_of(text, project_dir.parent.name)
        project = element_name(text, project_dir.name)
    parts = [p for p in (vendor, project, subsystem) if p]
    return subsystem, "::".join(parts)


def find_object(root: Path, name: str) -> ObjectHit:
    """An object by name; multiple namesakes or none at all - an error listing the candidates."""
    hits = []
    for yaml_path, kind, obj_name, text in _iter_objects(root):
        if obj_name == name:
            subsystem, namespace = _namespace_of(yaml_path, root)
            hits.append(ObjectHit(kind, obj_name, yaml_path, subsystem, namespace, text))
    if not hits:
        raise ScaffoldError(f"Объект '{name}' не найден под {root}")
    if len(hits) > 1:
        paths = "; ".join(str(h.path) for h in hits)
        raise ScaffoldError(f"Имя '{name}' неоднозначно: {paths} – укажите файл объекта явно")
    return hits[0]


# Types with a default value: ПолеВвода<Тип> accepts them as is. For ПолеВвода
# "параметр типа должен иметь значение по умолчанию ИЛИ Неопределено в составе типов"
# (stdlib ПолеВвода) - references and enumerations without ПоУмолчанию have no default
# and need a '?'.
PRIMITIVE_TYPES = {
    "Строка", "Число", "Булево", "Дата", "ДатаВремя", "Время", "УникальныйИдентификатор",
    "Момент", "Длительность", "Ууид",
}

# Standard (platform-predefined) attributes: they may be absent from yaml, yet forms need
# them. Only those that exist without an explicit declaration: Справочник - Наименование;
# Документ - Дата ("Обязан присутствовать всегда"). The document Номер is NOT supplied: it
# is optional ("Если не задан, то номер отсутствует"), and a phantom form column would be
# an error.
_STANDARD_FIELDS = {
    "Справочник": [{"name": "Наименование", "type": "Строка"}],
    "Документ": [{"name": "Дата", "type": "ДатаВремя"}],
}

# Kinds that have object and list forms (child types of ФормаОбъекта / ФормаСписка in
# stdlib). Registers and a constant set have no object form - list only.
OBJECT_FORM_KINDS = ("Справочник", "Документ", "ПланОбмена", "ХранилищеНастроек")
LIST_FORM_KINDS = OBJECT_FORM_KINDS + (
    "РегистрСведений", "РегистрНакопления", "НаборКонстант",
)
# Register data lives in Измерения and Ресурсы, not only in Реквизиты: a list must
# show all of them.
_REGISTER_FIELD_SECTIONS = ("Измерения", "Ресурсы", "Реквизиты")

# Accumulation register kind: Остатки (the default) stores both balances and turnovers;
# Обороты - changes only. A balance register record has a ВидЗаписи (Приход/Расход) - a
# turnover one does not ("Свойства элемента проекта РегистрНакопления" documentation and
# the design example).
BALANCE_REGISTER = "Остатки"

# Permission computation handlers: level 1 - for the project element as a whole, level 2 -
# for individual objects (RLS). Written in the object module <Имя>.xbsl.
ACCESS_HANDLER_LEVEL1 = "ВычислитьРазрешенияДоступа"
ACCESS_HANDLER_LEVEL2 = "ВычислитьРазрешенияДоступаДляОбъектов"


def object_info(root: Path, name: str | None = None, yaml_path: Path | None = None,
                reader=None) -> dict:
    """Object summary for form generation and overview.

    Fields are completed with the kind's standard attributes (Наименование / Номер+Дата,
    for registers - Период / Регистратор / ВидЗаписи) when absent from yaml: forms are
    built from the full list. Besides the composition it returns what is needed to write
    the object's code: access control and the presence of permission handlers, the
    register kind and whether movements need a ВидЗаписи.
    """
    if yaml_path is not None:
        yaml_path = Path(yaml_path)
        if not yaml_path.is_file():
            raise ScaffoldError(f"Файл не найден: {yaml_path}")
        text = _read(yaml_path)
        kind = element_kind(text)
        if kind is None:
            raise ScaffoldError(f"В {yaml_path} нет ВидЭлемента – это не объект конфигурации")
        subsystem, namespace = _namespace_of(yaml_path, root)
        hit = ObjectHit(
            kind, element_name(text, yaml_path.stem), yaml_path, subsystem, namespace, text,
        )
    else:
        hit = find_object(root, name or "")
        text = hit.text

    # A register's data is its Измерения and Ресурсы; attributes only complement them.
    register = _register_info(hit.kind, text)
    sections = (
        _REGISTER_FIELD_SECTIONS if hit.kind.startswith("Регистр") else ("Реквизиты",)
    )
    fields = [
        {"name": item.get("Имя", "?"), "type": item.get("Тип", "")}
        for section in sections
        for item in section_items(text, section, top_level=True)
    ]
    declared = {f["name"] for f in fields}
    standard_source = register.get("standard_fields") or _STANDARD_FIELDS.get(hit.kind, [])
    # A standard attribute the object declares itself is not added a second time - in either
    # spelling: an English catalog declares `Name`, and that IS `Наименование`.
    standard = [
        f for f in standard_source if not declared.intersection(field_forms(f["name"]))
    ]
    fields = standard + fields

    tabulars = [
        {
            "name": item.get("Имя", "?"),
            "fields": _tabular_fields(text, item.get("Имя", "")),
        }
        for item in section_items(text, "ТабличныеЧасти", top_level=True)
    ]
    hierarchies = [
        {"name": h.get("Имя", ""), "field": h.get("ПолеРодителя", "")}
        for h in section_items(text, "ДополнительныеИерархии", top_level=True)
    ]
    # The value is bilingual as well: `Иерархический: Истина` is `Hierarchical: True`.
    hierarchical = _key_re("Иерархический").search(text)
    is_hierarchical = bool(
        hierarchical and _enum_value(hierarchical.group(1)) == "Истина"
    )

    stem = hit.path.stem
    if hit.kind == "Отчет":
        existing_forms = {"ФормаОтчета": _existing(hit.path.parent, f"{stem}ФормаОтчета.yaml")}
        layout = "report"
    else:
        existing_forms = {
            "ФормаОбъекта": _existing(hit.path.parent, f"{stem}ФормаОбъекта.yaml"),
            "ФормаСписка": _existing(hit.path.parent, f"{stem}ФормаСписка.yaml"),
        }
        layout = _suggest_layout(len(fields), len(tabulars))

    return {
        "path": str(hit.path),
        "kind": hit.kind,
        "name": hit.name,
        "subsystem": hit.subsystem,
        "namespace": hit.namespace,
        # None - no КонтрольДоступа section: the platform applies РазрешеноАдминистраторам.
        "access": access_info(text),
        "access_rights": list(ACCESS_KIND_RIGHTS.get(hit.kind, ())),
        # Permission computation handlers in the object module: needed with
        # РазрешенияВычисляются (level 1) and РазрешенияВычисляютсяДляКаждогоОбъекта
        # (levels 1 and 2).
        "access_handlers": _access_handlers(hit.path, reader),
        # Registers only: the kind (Остатки/Обороты), the periodicity and whether a
        # movement needs a ВидЗаписи. For other kinds - null.
        "register": register or None,
        "fields": fields,
        "tabulars": tabulars,
        "suggested_layout": layout,
        "existing_forms": existing_forms,
        "is_hierarchical": is_hierarchical,
        "additional_hierarchies": hierarchies,
        "report_params": [
            {"name": p.get("Имя", "?"), "type": p.get("Тип", "")}
            for p in section_items(text, "ПараметрыЗапроса", top_level=True)
        ],
        "sections": {
            kind: [i.get("Имя", "?") for i in section_items(text, _SECTION_SPECS[kind]["section"], top_level=True)]
            for kind in KIND_SECTIONS.get(hit.kind, ())
        },
    }


def _enum_value(value: str) -> str:
    """An enumeration value as the platform names it in Russian (`Turnovers` -> `Обороты`).

    A property of a bilingual project carries a bilingual value; the tool compares against the
    Russian names, so an English one is translated back by the term pairs - and an unknown word
    is returned as it stands rather than guessed at.
    """
    if not value.isascii():
        return value
    return terms.russian(value, "enums") or terms.common_russian(value) or value


def _register_info(kind: str, text: str) -> dict:
    """{register_kind, needs_record_type, standard_fields} of a register; empty for other kinds.

    needs_record_type - whether movements need a ВидЗаписи (Приход/Расход): only a balance
    (Остатки) accumulation register has it.
    """
    if not kind.startswith("Регистр"):
        return {}
    if kind == "РегистрНакопления":
        found = _key_re("ВидРегистра").search(text)
        register_kind = _enum_value(found.group(1)) if found else BALANCE_REGISTER
        balance = register_kind == BALANCE_REGISTER
        standard = [{"name": "Период", "type": "ДатаВремя"}, {"name": "Регистратор", "type": ""}]
        if balance:
            standard.append({"name": "ВидЗаписи", "type": ""})
        return {
            "register_kind": register_kind,
            "needs_record_type": balance,
            "standard_fields": standard,
        }
    found = _key_re("Периодичность").search(text)
    periodicity = _enum_value(found.group(1)) if found else "Непериодический"
    return {
        "register_kind": None,  # an information register has no kind - it has periodicity
        "periodicity": periodicity,
        "needs_record_type": False,
        "standard_fields": (
            [{"name": "Период", "type": "ДатаВремя"}] if periodicity != "Непериодический" else []
        ),
    }


def _access_handlers(yaml_path: Path, reader=None) -> dict:
    """Whether the object module has permission computation handlers (levels 1 and 2).

    The object module is <Имя>.xbsl; <Имя>.Объект.xbsl is meant for write events, these
    handlers are not written there.
    """
    module = yaml_path.with_suffix(".xbsl")
    if not module.is_file():
        return {"module": None, "level1": False, "level2": False}
    text = (reader or _read)(module)
    declared = set(re.findall(r"^\s*метод\s+([A-Za-zА-Яа-яЁё0-9_]+)", text, re.M))
    return {
        "module": module.name,
        "level1": ACCESS_HANDLER_LEVEL1 in declared,
        "level2": ACCESS_HANDLER_LEVEL2 in declared,
    }


def _tabular_fields(text: str, tc_name: str) -> list[dict]:
    """Tabular part attributes: they live in a nested section of its block, not at the top."""
    if not tc_name:
        return []
    offset = find_section_item_offset(text, "ТабличныеЧасти", tc_name)
    if offset is None:
        return []
    block = _block_at(text, offset)
    return [
        {"name": item.get("Имя", "?"), "type": item.get("Тип", "")}
        for item in section_items(block, "Реквизиты")
    ]


def _existing(directory: Path, filename: str) -> str | None:
    return filename if (directory / filename).is_file() else None


def _suggest_layout(field_count: int, tc_count: int) -> str:
    if tc_count == 0:
        return "simple"
    if tc_count == 1 and field_count >= 5:
        return "panels"
    return "tabs"


def project_info(root: Path) -> dict:
    """Overview of the sources under the root: projects, subsystems and objects by kind."""
    projects = find_projects(root)
    objects = []
    for yaml_path, kind, name, text in _iter_objects(root):
        subsystem, namespace = _namespace_of(yaml_path, root)
        entry = {
            "kind": kind, "name": name, "path": str(yaml_path),
            "subsystem": subsystem, "namespace": namespace,
        }
        if kind in ACCESS_KIND_RIGHTS:
            # Project-wide rights summary: the method for ПоУмолчанию (None - no section,
            # so РазрешеноАдминистраторам applies) and the methods of individual rights.
            access = access_info(text)
            entry["access_default"] = access["default"] if access else None
            entry["access_permissions"] = access["permissions"] if access else {}
        objects.append(entry)
    return {
        "projects": [
            {**p, "dir": str(p["dir"])} for p in projects
        ],
        "objects": sorted(objects, key=lambda o: (o["kind"], o["name"])),
        "creatable_kinds": sorted(KIND_SPECS),
        "field_kinds": {kind: list(sections) for kind, sections in KIND_SECTIONS.items()},
        "access_methods": list(ACCESS_METHODS),
        "access_kind_rights": {k: list(v) for k, v in ACCESS_KIND_RIGHTS.items()},
    }


# --- operation result and applying ------------------------------------------------------


@dataclass
class FileChange:
    path: Path
    content: str  # the full new text of the file
    created: bool  # True - a new file, False - an edit of an existing one
    cursor: tuple[int, int] | None = None  # (line, column) of the point of interest, 0-based


@dataclass(frozen=True)
class FileRename:
    old_path: Path
    new_path: Path

    @property
    def case_only(self) -> bool:
        """The two names differ only by letter case: `Товары.yaml` -> `товары.yaml`.

        This is the one rename whose target legitimately "already exists": a
        case-insensitive filesystem (Windows, macOS by default) addresses one and the same
        file under both spellings, so the existence check must not read it as a clash with
        a foreign file. The test is textual on purpose - it states the class of the rename
        and answers the same on every filesystem.
        """
        old, new = str(self.old_path), str(self.new_path)
        return old != new and old.casefold() == new.casefold()


# Suffix of the intermediate name of a two-step rename (see _rename_file). Deliberately
# not .yaml/.xbsl: should a process be killed between the steps, what is left behind is
# not picked up as a source by engine.find_sources.
_RENAME_TEMP_SUFFIX = ".xbsl-rename-tmp"


def _one_file_under_both_names(rename: FileRename) -> bool:
    """A case-only rename on a case-insensitive filesystem: both names are one file.

    On a case-sensitive filesystem the new name is simply free, so this is False and the
    rename is an ordinary one. A path that cannot be stat'ed also answers False - nothing
    then proves the two names are one file, and the safe reading is a foreign file.
    """
    if not rename.case_only or not rename.new_path.exists():
        return False
    try:
        return rename.old_path.samefile(rename.new_path)
    except OSError:
        return False


def _rename_clashes(rename: FileRename) -> bool:
    """The target name is taken by ANOTHER file - the rename would destroy it."""
    return rename.new_path.exists() and not _one_file_under_both_names(rename)


def _free_temp_path(path: Path) -> Path:
    """A name next to `path` that is free under any casing - for the intermediate step."""
    candidate = path.with_name(path.name + _RENAME_TEMP_SUFFIX)
    n = 0
    while candidate.exists():
        n += 1
        candidate = path.with_name(f"{path.name}{_RENAME_TEMP_SUFFIX}{n}")
    return candidate


def _rename_file(rename: FileRename) -> None:
    """Rename one file; a case-only rename goes through a temporary name.

    On a case-insensitive filesystem the old and the new name are the same file, and a
    single-step rename between them is not guaranteed: it is a no-op or an error depending
    on the filesystem (network shares and mounted volumes differ from a local NTFS).
    Two steps through a free name work everywhere and leave nothing behind - a failure of
    the second step undoes the first. The branch is on the observable fact "the target
    exists and it is the same file", not on the operating system: on a case-sensitive
    filesystem the target simply does not exist, the plain single rename runs and no
    temporary name ever appears.

    Called after _rename_clashes has cleared the rename - a target held by a foreign file
    is an error, not a case to handle here.
    """
    if _one_file_under_both_names(rename):
        temp = _free_temp_path(rename.old_path)
        rename.old_path.rename(temp)
        try:
            temp.rename(rename.new_path)
        except OSError:
            temp.rename(rename.old_path)
            raise
    else:
        rename.old_path.rename(rename.new_path)


@dataclass
class ScaffoldResult:
    changes: list[FileChange] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)  # warnings, manual steps
    renames: list[FileRename] = field(default_factory=list)  # file renames (before edits)

    def as_dict(self, content: bool = True) -> dict:
        files = []
        for c in self.changes:
            entry = {"path": str(c.path), "created": c.created}
            if content:
                entry["content"] = c.content
            entry["cursor"] = (
                {"line": c.cursor[0], "character": c.cursor[1]} if c.cursor else None
            )
            files.append(entry)
        return {
            "renames": [
                {"from": str(r.old_path), "to": str(r.new_path)} for r in self.renames
            ],
            "files": files,
            "notes": self.notes,
        }


def apply_result(result: ScaffoldResult) -> list[str]:
    """Write the changes to disk; returns the paths of the written files.

    File renames run before writing the edits: edits of renamed files reference the new
    paths. Editing an existing file preserves its BOM (the encoding is detected by
    engine.load); newlines are chosen by the operation itself when generating the text.
    A rename that only changes letter case is applied in two steps (see _rename_file).
    """
    for rename in result.renames:
        if _rename_clashes(rename):
            raise ScaffoldError(f"Файл уже существует: {rename.new_path}")
        rename.new_path.parent.mkdir(parents=True, exist_ok=True)
        _rename_file(rename)
    written = []
    for change in result.changes:
        change.path.parent.mkdir(parents=True, exist_ok=True)
        if change.created or not change.path.exists():
            change.path.write_bytes(change.content.encode("utf-8"))
        else:
            source = engine.load(change.path)
            change.path.write_bytes(fixer.encode(source, change.content))
        written.append(str(change.path))
    return written


def _cursor_at(text: str, offset: int) -> tuple[int, int]:
    line = text.count("\n", 0, offset)
    return line, offset - (text.rfind("\n", 0, offset) + 1)


def _dominant_nl(text: str) -> str:
    return fixer._dominant_newline(text) if text else "\n"


# Reading the file to edit. reader: Callable[[Path], str]; the LSP supplies a reader that
# first checks the editor's open buffers: an edit must start from the text with unsaved
# changes, otherwise applying the full new text would wipe them out.
def _load_for_edit(yaml_path: Path, reader=None) -> tuple[str, str]:
    if not yaml_path.is_file():
        raise ScaffoldError(f"Файл не найден: {yaml_path}")
    text = (reader or _read)(yaml_path)
    return text, _dominant_nl(text)


# --- operations: object, field, subsystem, project ---------------------------------------


@lru_cache(maxsize=1)
def _kind_by_english() -> dict[str, str]:
    """{English name of an element kind: the Russian one the scaffolding works in}.

    The platform is bilingual and a project may be written in either language, so the tool
    accepts both spellings of a kind. The pairs come from the term dictionary (documentation
    plus the compiler meta objects), never from a translation; without the data the map is
    empty and only the Russian spellings are accepted, as before.
    """
    pairs: dict[str, str] = {}
    for name, section in (("terms.json", "types"), ("terms_full.json", "common")):
        try:
            data = dataset.load_json(name)
        except (dataset.DatasetError, KeyError, ValueError):
            continue
        for russian, english in (data.get(section) or {}).items():
            if russian in KIND_SPECS:
                pairs.setdefault(english.casefold(), russian)
    return pairs


def resolve_kind(kind: str) -> str:
    """The Russian spelling of an element kind, whichever language it was given in."""
    if kind in KIND_SPECS:
        return kind
    return _kind_by_english().get(kind.casefold(), kind)


def op_new_object(
    directory: Path,
    kind: str,
    name: str,
    *,
    scope: str | None = None,
    environment: str | None = None,
    access: str | None = None,
    routes: str | None = None,
    report: dict | None = None,
) -> ScaffoldResult:
    """Create a configuration object: Имя.yaml (+ Имя.xbsl for kinds with a module).

    environment - Окружение for ОбщийМодуль/Структура; access - the access control method
    (for HttpСервис written to Разрешения.Вызов, for data objects to
    Разрешения.ПоУмолчанию; individual rights are set by op_set_access); routes -
    HttpСервис routes ("GET /, POST /, GET /{id}"); report - the report source and layout.
    """
    kind = resolve_kind(kind)
    spec = KIND_SPECS.get(kind)
    if spec is None:
        raise ScaffoldError(
            f"Вид '{kind}' не поддерживается; доступны: {', '.join(sorted(KIND_SPECS))}"
        )
    name = _check_identifier(name, "объекта")
    directory = Path(directory)
    yaml_path = directory / f"{name}.yaml"
    if yaml_path.exists():
        raise ScaffoldError(f"Файл уже существует: {yaml_path}")

    if access and kind not in ACCESS_KIND_RIGHTS:
        raise ScaffoldError(
            f"Вид {kind} не поддерживает управление доступом – параметр access неприменим; "
            "поддерживают: " + ", ".join(sorted(ACCESS_KIND_RIGHTS))
        )
    if access and access not in ACCESS_METHODS:
        raise ScaffoldError(
            f"Недопустимый способ контроля доступа '{access}'; доступны: " + ", ".join(ACCESS_METHODS)
        )

    result = ScaffoldResult()
    if access in ("РазрешенияВычисляются", _PER_OBJECT):
        result.notes.append(
            f"{access}: разрешения нужно вычислить самому – напишите обработчик "
            "ВычислитьРазрешенияДоступа" + (
                " и ВычислитьРазрешенияДоступаДляОбъектов (+ РасчетРазрешенийПо)"
                if access == _PER_OBJECT else ""
            ) + " в модуле объекта"
        )
    if kind == "HttpСервис":
        return _new_http_service(yaml_path, name, access, routes or "GET /", result, scope)
    if kind == "SoapСервис":
        return _new_soap_service(yaml_path, name, access, result, scope)
    if kind == "Отчет":
        return _new_report(yaml_path, name, report or {}, result, scope)

    extra = _expand_extra(spec.extra, name)
    if environment:
        extra = [line for line in extra if not line.startswith("Окружение:")]
        extra.append(f"Окружение: {environment}")
    if access:
        # Разрешения is mandatory: КонтрольДоступа is a set of "Право: СпособКонтроляДоступа"
        # entries inside Разрешения (see ACCESS_KIND_RIGHTS and the "Контроль прав доступа"
        # documentation).
        extra += ["КонтрольДоступа:", f"    {_PERMISSIONS_KEY}:",
                  f"        {ACCESS_DEFAULT_RIGHT}: {access}"]
    content = new_object_yaml(
        kind, new_uuid(), name, scope or spec.scope, extra, project_language(directory),
    )
    result.changes.append(FileChange(yaml_path, content, created=True))
    if spec.module:
        stub = spec.module_stub.format(name=name) if spec.module_stub else f"// {name}\n"
        result.changes.append(
            FileChange(yaml_path.with_suffix(spec.module_suffix), stub, created=True)
        )
    if spec.note:
        result.notes.append(spec.note)
    return result


def op_add_field(
    yaml_path: Path,
    field_kind: str,
    name: str,
    *,
    type_: str = "Строка",
    tabular: str | None = None,
    reader=None,
) -> ScaffoldResult:
    """Add a section item to an object: an attribute, dimension, resource, enumeration
    value, parameter, structure field or tabular part; tabular - the tabular part name
    when adding an attribute into it.
    """
    yaml_path = Path(yaml_path)
    name = _check_identifier(name, "элемента")
    text, nl = _load_for_edit(yaml_path, reader)
    kind = element_kind(text) or "?"
    # The item is written in the spelling of the file it goes into: a Russian island inside
    # an English object compiles, but the next reader has to know both to find anything.
    lang = yaml_language(text, yaml_path.parent)

    if tabular:
        if field_kind != "реквизит":
            raise ScaffoldError("В табличную часть добавляются только реквизиты")
        offset = find_section_item_offset(text, "ТабличныеЧасти", tabular)
        if offset is None:
            raise ScaffoldError(f"Табличная часть '{tabular}' не найдена в {yaml_path.name}")
        lines = spelled_lines(
            [f"Ид: {new_uuid()}", f"Имя: {name}", f"Тип: {type_}"], lang
        )
        edit = insert_nested_item_edit(text, offset, "Реквизиты", lines, nl, lang)
        new_text = apply_edit(text, edit)
        cursor = _cursor_at(new_text, edit.start + len(edit.new_text))
        return ScaffoldResult([FileChange(yaml_path, new_text, created=False, cursor=cursor)])

    map_spec = _MAPPING_SPECS.get(field_kind)
    if map_spec is not None:
        return _add_mapping_entry(yaml_path, text, nl, kind, field_kind, map_spec, name, type_)

    spec = _SECTION_SPECS.get(field_kind)
    if spec is None:
        raise ScaffoldError(
            f"Неизвестный вид элемента '{field_kind}'; доступны: {', '.join(FIELD_KINDS)}"
        )
    allowed = KIND_SECTIONS.get(kind)
    if allowed is None:
        # A kind with no extendable sections (ОбщийМодуль, HttpСервис, КомпонентИнтерфейса
        # etc.): the check used to let such a kind through and silently append a foreign
        # section to it.
        raise ScaffoldError(
            f"У вида {kind} нет пополняемых секций; они есть у: " + ", ".join(sorted(KIND_SECTIONS))
        )
    if field_kind not in allowed:
        raise ScaffoldError(
            f"У вида {kind} нет секции для '{field_kind}'; доступны: {', '.join(allowed)}"
        )
    existing = {i.get("Имя") for i in section_items(text, spec["section"], top_level=True)}
    if name in existing:
        raise ScaffoldError(f"'{name}' уже есть в секции {spec['section']} файла {yaml_path.name}")
    template = _KIND_SECTION_LINES.get((kind, field_kind), spec["lines"])
    lines = spelled_lines([
        line.format(uuid=new_uuid(), uuid2=new_uuid(), name=name, type=type_)
        for line in template
    ], lang)
    edit = insert_item_edit(text, spec["section"], lines, nl, top_level=True, lang=lang)
    new_text = apply_edit(text, edit)
    cursor = _cursor_at(new_text, edit.start + len(edit.new_text))
    result = ScaffoldResult([FileChange(yaml_path, new_text, created=False, cursor=cursor)])
    if field_kind == "операция":
        _add_operation_handler(yaml_path, name, result, reader)
    if field_kind == "индекс":
        result.notes.append(
            f"Индекс {name} создан с полем-заглушкой Реквизит1 – замените Поля на реальные "
            "реквизиты, по которым нужен индекс"
        )
    return result


def _add_mapping_entry(
    yaml_path: Path, text: str, nl: str, kind: str, field_kind: str,
    map_spec: dict, key: str, value: str,
) -> ScaffoldResult:
    """Add a "Ключ: Значение" pair to a mapping section (Строки/Шаблоны of localized strings).

    The format is from the "Локализация" documentation: the Строки and Шаблоны sections
    are key-to-value mappings, not item lists. The default value equals the key (as in
    Мероприятия: Мероприятия); template values are quoted.
    """
    allowed = KIND_SECTIONS.get(kind)
    if allowed is None or field_kind not in allowed:
        avail = ", ".join(allowed) if allowed else "нет"
        raise ScaffoldError(f"У вида {kind} нет секции для '{field_kind}'; доступны: {avail}")
    section = map_spec["section"]
    raw_value = value if value and value != "Строка" else key
    entry_value = f'"{raw_value}"' if map_spec["quote"] else raw_value

    bounds = _section_bounds(text, section, top_level=True)
    if bounds is not None:
        _, header_line_end, body_end = bounds
        body = text[header_line_end:body_end]
        if re.search(rf"^[ \t]+{re.escape(key)}:", body, re.M):
            raise ScaffoldError(f"Ключ '{key}' уже есть в секции {section} файла {yaml_path.name}")
        new_text = text[:body_end] + f"{nl}    {key}: {entry_value}" + text[body_end:]
    else:
        tail = "" if (not text or text.endswith("\n")) else nl
        header = spelled_key(section, yaml_language(text, yaml_path.parent))
        new_text = text + f"{tail}{header}:{nl}    {key}: {entry_value}{nl}"
    cursor = _cursor_at(new_text, new_text.index(f"{key}: {entry_value}"))
    return ScaffoldResult([FileChange(yaml_path, new_text, created=False, cursor=cursor)])


def _add_operation_handler(yaml_path: Path, operation: str, result: ScaffoldResult, reader) -> None:
    """Append the operation's @Обработчик method to the processor module (unless present).

    Every operation must have a same-named method annotated with @Обработчик, otherwise
    the platform raises "Обязательный обработчик <Имя> не определен" (the "Обработка"
    documentation).
    """
    module_path = yaml_path.with_suffix(".xbsl")
    module_text = (reader or _read)(module_path) if module_path.exists() else ""
    if re.search(rf"^метод\s+{re.escape(operation)}\b", module_text, re.M):
        return
    nl = _dominant_nl(module_text) if module_text else "\n"
    handler = f"@Обработчик{nl}метод {operation}(){nl}    // TODO: логика операции{nl};{nl}"
    if module_text and not module_text.endswith(("\n", "\r")):
        module_text += nl
    new_text = (module_text + nl if module_text else "") + handler
    result.changes.append(FileChange(module_path, new_text, created=not module_path.exists()))
    result.notes.append(f"В модуль дописан @Обработчик-метод операции {operation}")


def op_add_subsystem(
    parent_dir: Path,
    name: str,
    *,
    representation: str | None = None,
    auto_interface: bool = True,
    uses: list[str] | None = None,
) -> ScaffoldResult:
    """Create a subsystem: a folder + Подсистема.yaml (blocks assembled from the parameters)."""
    name = _check_identifier(name, "подсистемы")
    parent_dir = Path(parent_dir)
    yaml_path = parent_dir / name / SUBSYSTEM_FILE
    if yaml_path.exists():
        raise ScaffoldError(f"Файл уже существует: {yaml_path}")
    lang = project_language(parent_dir)
    lines: list[str] = []
    if uses:
        lines.append("Использование:")
        lines += [f"    - {u}" for u in uses]
    # The Интерфейс block is always written: the platform default is Истина, so disabling
    # the auto-interface exists only as an explicit ВключатьВАвтоИнтерфейс: Ложь entry.
    lines.append("Интерфейс:")
    flag = "Истина" if auto_interface else "Ложь"
    lines.append(f"    ВключатьВАвтоИнтерфейс: {_spelled(flag, lang, 'enums')}")
    if representation:
        lines.append(f"    Представление: {representation}")
    content = "\n".join(spelled_lines(lines, lang)) + "\n"
    return ScaffoldResult([FileChange(yaml_path, content, created=True)])


_PROJECT_MODULE_STUB = """\
// @НастройкаПриложения(Ид = "НастройкаПриложения", Номер = 1)
// метод НастройкаПриложения(НоваяВерсия: Версия)
// TODO Раскомментируйте метод и вставьте код обработчика. Метод с таким Ид будет выполнен только один раз!
// ;

// @ОбновлениеПроекта(Ид = "КонвертацияДанных", Номер = 1)
// метод КонвертацияДанных(ИсходнаяВерсия: Версия, ЦелеваяВерсия: Версия)
// TODO Раскомментируйте метод и вставьте код обработчика. Метод с таким Ид будет выполнен только один раз!
// ;
"""


def op_new_project(
    root: Path,
    vendor: str,
    name: str,
    *,
    representation: str | None = None,
    # Three numbers A.B.C - semantic versioning per the project property standard
    # (the linter's own project/version rule complains about "1.0").
    version: str = "1.0.0",
    compatibility: str = "9.0",
    subsystem: str = "Основное",
    library: bool = False,
) -> ScaffoldResult:
    """Create a project from scratch: Проект.yaml + Проект.xbsl + the first subsystem."""
    vendor = _check_identifier(vendor, "поставщика")
    name = _check_identifier(name, "проекта")
    subsystem = _check_identifier(subsystem, "подсистемы")
    project_dir = Path(root) / vendor / name
    if (project_dir / PROJECT_FILE).exists():
        raise ScaffoldError(f"Проект уже существует: {project_dir / PROJECT_FILE}")
    lines = [f"Ид: {new_uuid()}"]
    if library:
        lines.append("ВидПроекта: Библиотека")
    lines += [
        f"Представление: \"{representation or name}\"",
        f"Версия: {version}",
        f"Поставщик: {vendor}",
        f"Имя: {name}",
        f"ПредставлениеПоставщика: \"{vendor}\"",
        f"РежимСовместимости: {compatibility}",
        "ЯзыкиЛокализации: [Русский]",
        "ЯзыкПоУмолчанию: Русский",
        "ЯзыкРазработки: Русский",
    ]
    result = ScaffoldResult(
        [
            FileChange(project_dir / PROJECT_FILE, "\n".join(lines) + "\n", created=True),
            FileChange(project_dir / "Проект.xbsl", _PROJECT_MODULE_STUB, created=True),
            FileChange(
                project_dir / subsystem / SUBSYSTEM_FILE,
                "Интерфейс:\n    ВключатьВАвтоИнтерфейс: Истина\n",
                created=True,
            ),
        ]
    )
    if library:
        result.notes.append(
            "Библиотека не разворачивается как самостоятельное приложение – подключается через Импорт"
        )
    return result


# --- operation: library dependency --------------------------------------------------------

LIBRARIES_SECTION = "Библиотеки"
# A library RELEASE version is dot-separated numbers only. A BUILD version has a hyphenated
# suffix ("1.0-42") and cannot be attached: a project attaches a release.
_RELEASE_VERSION_RE = re.compile(r"^\d+(\.\d+)*$")


def project_libraries(text: str) -> list[dict[str, str]]:
    """Attached libraries - items of the Библиотеки section of Проект.yaml."""
    return section_items(text, LIBRARIES_SECTION, top_level=True)


def _find_project_yaml(root: Path) -> Path:
    projects = find_projects(Path(root))
    if not projects:
        raise ScaffoldError(f"Под корнем {root} не найден {PROJECT_FILE}")
    if len(projects) > 1:
        listed = ", ".join(f"{p['vendor']}::{p['name']}" for p in projects)
        raise ScaffoldError(
            f"Под корнем {root} несколько проектов ({listed}) – укажите project_yaml"
        )
    return projects[0]["dir"] / PROJECT_FILE


def op_add_dependency(
    root: Path,
    vendor: str,
    name: str,
    version: str,
    *,
    project_yaml: Path | None = None,
    reader=None,
) -> ScaffoldResult:
    """Attach a library to the project - the Библиотеки section of Проект.yaml.

    A section item is Имя, Поставщик, Версия (the "Подключить библиотеку к проекту"
    documentation). Different versions of one library are not allowed within a project,
    so re-attaching updates the version instead of adding a second entry.

    The version is the library RELEASE version: a release is published in the control
    panel, this step is not automated via API. Library metadata (vendor, name, version)
    comes from parsing its archive: elemctl inspect.
    """
    vendor = _check_identifier(vendor, "поставщика библиотеки")
    name = _check_identifier(name, "библиотеки")
    version = version.strip()
    if not _RELEASE_VERSION_RE.match(version):
        raise ScaffoldError(
            f"Недопустимая версия релиза библиотеки: '{version}' – нужны числа через точку "
            "(версия сборки с суффиксом, например 1.0-42, к проекту не подключается)"
        )
    path = Path(project_yaml) if project_yaml else _find_project_yaml(Path(root))
    text, nl = _load_for_edit(path, reader)
    # The descriptor declares no element kind, so its language is that of the project it heads.
    lang = yaml_language(text, path.parent)
    result = ScaffoldResult()

    for item in project_libraries(text):
        if item.get("Имя") != name:
            continue
        item_vendor = item.get("Поставщик", "")
        if item_vendor != vendor:
            raise ScaffoldError(
                f"К проекту уже подключена библиотека {item_vendor}::{name}, "
                f"подключается {vendor}::{name} – в пространстве имён типов они не "
                "различаются; отключите лишнюю вручную"
            )
        current = item.get("Версия", "")
        if current == version:
            result.notes.append(f"Библиотека {vendor}::{name} уже подключена, версия {version}")
            return result
        offset = find_section_item_offset(text, LIBRARIES_SECTION, name)
        if offset is None:
            raise ScaffoldError(
                f"Библиотека '{name}' записана в {path.name} в свёрнутом виде – "
                "обновите версию вручную"
            )
        block_end = offset + len(_block_at(text, offset))
        new_text, _ = _set_mapping_value(text, offset, block_end, "", "Версия", version, nl)
        result.changes.append(FileChange(path, new_text, created=False))
        result.notes.append(f"{vendor}::{name}: версия {current} -> {version}")
        return result

    lines = spelled_lines(
        [f"Имя: {name}", f"Поставщик: {vendor}", f"Версия: {version}"], lang
    )
    edit = insert_item_edit(text, LIBRARIES_SECTION, lines, nl, top_level=True, lang=lang)
    new_text = apply_edit(text, edit)
    cursor = _cursor_at(new_text, edit.start + len(edit.new_text))
    result.changes.append(FileChange(path, new_text, created=False, cursor=cursor))
    result.notes.append(f"Подключена библиотека {vendor}::{name} {version}")
    result.notes.append(
        f"Типы библиотеки с ОбластьВидимости: Глобально доступны как "
        f"{vendor}::{name}::Подсистема[::Пакет]::ИмяТипа; полное имя подсистемы "
        "указывается в Использование подсистемы и в импорт"
    )
    return result


# --- operations: HTTP service and routes --------------------------------------------------

_METHOD_ORDER = ["GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"]
_HANDLER_NAMES: dict[tuple[str, bool], str] = {
    ("GET", False): "ПолучитьСписок",
    ("POST", False): "Создать",
    ("GET", True): "ПолучитьПоИд",
    ("PUT", True): "Обновить",
    ("PATCH", True): "ОбновитьЧастично",
    ("DELETE", True): "Удалить",
}
_METHOD_RU = {
    "GET": "Получить", "POST": "Создать", "PUT": "Обновить",
    "PATCH": "ОбновитьЧастично", "DELETE": "Удалить",
}
#: The same vocabulary in English - for a project whose sources are written in English. These
#: names are the TOOL's, not the platform's: there is nothing to look them up in, and a
#: Russian handler in an English module would be an island of the kind the bilingual reading
#: was fixed to avoid.
_HANDLER_NAMES_EN: dict[tuple[str, bool], str] = {
    ("GET", False): "GetList",
    ("POST", False): "Create",
    ("GET", True): "GetById",
    ("PUT", True): "Update",
    ("PATCH", True): "UpdatePartially",
    ("DELETE", True): "Delete",
}
_METHOD_EN = {
    "GET": "Get", "POST": "Create", "PUT": "Update",
    "PATCH": "UpdatePartially", "DELETE": "Delete",
}
#: Template names the tool invents when the path gives it nothing to name them by.
_TEMPLATE_WORDS_EN = {"Список": "List", "ЭлементПоИд": "ItemById", "Шаблон": "Template"}
_PARENT_SUFFIX = ("ПоРодителю", "ByParent")


def parse_routes(routes_str: str) -> list[tuple[str, list[str]]]:
    """"GET /, POST /, GET /{id}" -> [(template, [methods])] preserving template order."""
    grouped: dict[str, list[str]] = {}
    order: list[str] = []
    for part in re.split(r"[,\n]+", routes_str):
        part = part.strip()
        if not part:
            continue
        tokens = part.split(None, 1)
        if len(tokens) != 2:
            raise ScaffoldError(f"Неверный формат маршрута: '{part}' (ожидается 'МЕТОД /путь')")
        method, path = tokens[0].upper(), tokens[1].strip()
        if not path.startswith("/"):
            path = "/" + path
        if path not in grouped:
            grouped[path] = []
            order.append(path)
        if method not in grouped[path]:
            grouped[path].append(method)
    for path in order:
        grouped[path].sort(key=lambda m: _METHOD_ORDER.index(m) if m in _METHOD_ORDER else 99)
    return [(path, grouped[path]) for path in order]


def _has_path_param(path: str) -> bool:
    return bool(re.search(r"\{[^}]+\}", path))


def _to_pascal(s: str) -> str:
    """Path segment -> identifier part: separators dropped, words capitalized.

    A path may legally contain characters invalid in a name (hyphen, dot, the wildcard
    asterisk of `/read/*`): we discard them, otherwise the result is not an identifier
    but broken yaml (`Имя: *` is read by the parser as an alias) and a non-compilable
    handler name.
    """
    s = s.strip("{}")
    parts = [p for p in re.split(r"[^A-Za-zА-Яа-яЁё0-9_]+", s) if p]
    return "".join(p[:1].upper() + p[1:] for p in parts)


def template_name(path: str, lang: str = "ru") -> str:
    """The name of a URL template, derived from the path itself.

    The words the tool adds when the path names nothing (`Список`, `ЭлементПоИд`) are its own
    vocabulary, so they exist in both languages; the literal segments of the path are the
    author's and are used as they are.
    """
    if path == "/":
        return tool_route_word("Список", lang)
    segments = [s for s in path.lstrip("/").split("/") if s]
    literal = [_to_pascal(s) for s in segments if not (s.startswith("{") and s.endswith("}"))]
    literal = [s for s in literal if s]
    params = [s for s in segments if s.startswith("{") and s.endswith("}")]
    if not literal:
        return tool_route_word("ЭлементПоИд", lang)
    if params:
        return literal[-1] + (_PARENT_SUFFIX[1] if lang == "en" else _PARENT_SUFFIX[0])
    return literal[-1]


def tool_route_word(name: str, lang: str) -> str:
    """A route word the tool invents, in the given language."""
    return _TEMPLATE_WORDS_EN.get(name, name) if lang == "en" else name


def assign_template_name(path: str, used: set[str], lang: str = "ru") -> str:
    """A URL template name unique within the service.

    The template name is a key: the platform stores access permissions by it, it is
    returned by Запрос.ИмяШаблона, and op_add_route looks up the block to extend by it.
    Different paths easily produce one name (`/users` and `/orders/users`), so duplicates
    are disambiguated with a suffix.
    """
    base = template_name(path, lang) or tool_route_word("Шаблон", lang)
    name, n = base, 2
    while name in used:
        name = f"{base}{n}"
        n += 1
    used.add(name)
    return name


def assign_handler(method: str, path: str, used: set[str], lang: str = "ru") -> str:
    """Route handler name: a dictionary one (ПолучитьСписок / GetList etc.), if taken -
    <Метод><ИмяШаблона>, then a numeric suffix. The name is marked as taken."""
    names = _HANDLER_NAMES_EN if lang == "en" else _HANDLER_NAMES
    methods = _METHOD_EN if lang == "en" else _METHOD_RU
    name = names.get((method, _has_path_param(path)))
    if name is None or name in used:
        name = f"{methods.get(method, method.capitalize())}{template_name(path, lang)}"
    base, n = name, 2
    while name in used:
        name = f"{base}{n}"
        n += 1
    used.add(name)
    return name


def _template_lines(path: str, method_handlers: list[tuple[str, str]], name: str,
                    lang: str = "ru") -> list[str]:
    lines = [f"Имя: {name}", f"Шаблон: {path}", "Методы:"]
    for method, handler in method_handlers:
        lines += [
            "    -",
            f"        Метод: {method}",
            f"        Обработчик: {handler}",
        ]
    return spelled_lines(lines, lang)


def _handler_stub(method: str, path: str, handler: str, lang: str = "ru") -> str:
    """Route handler stub: a canonical CRUD skeleton by method and path parameters.

    Two texts, not one text translated: the keywords, the stdlib names AND the comments all
    change with the language, and a token-by-token translation of prose is how a comment turns
    into nonsense. The platform spells both halves itself (`method`/`метод`,
    `HttpServiceRequest`/`HttpСервисЗапрос`), so neither text invents platform vocabulary.

    The live code is a valid response placeholder with no unused variables; the expanded
    example (limit parsing, lookup by Ид, serialization) goes as a comment to be
    uncommented. The status code and headers are set BEFORE writing the body, and
    УстановитьТело comes last: once body writing has started, changing the status or
    headers throws ИсключениеНедопустимоеСостояние, and the error handler can no longer
    set a 500 (see the HttpСервисОтвет documentation).
    """
    key = (method, _has_path_param(path))
    if lang == "en":
        return _handler_stub_en(method, path, handler, key)
    if key == ("GET", False):
        body = """\
    попытка
        // TODO: получить данные и отдать их телом. Пример чтения параметра limit:
        // знч ОграничениеПоУмолчанию = 100
        // знч ПараметрЛимит = Запрос.Параметры.ПолучитьПервый("limit")
        // знч Ограничение = ПараметрЛимит != Неопределено
        //     ? Мин(новый Число(ПараметрЛимит), ОграничениеПоУмолчанию) : ОграничениеПоУмолчанию
        // знч Данные = <Справочник>.ПолучитьСписок(Ограничение)
        Запрос.Ответ.Заголовки.Установить("Content-Type", "application/json")
        Запрос.Ответ.УстановитьТело("[]")
    поймать Ошибка: Исключение
        ОбработатьОшибку(Запрос.Ответ, Ошибка)
    ;"""
    elif key == ("POST", False):
        body = """\
    попытка
        // TODO: десериализовать тело и создать объект
        // знч Данные = СериализацияJson.ПрочитатьОбъект(Запрос.Тело, Тип<...>)
        // знч Ссылка = <Справочник>.Создать(Данные)
        Запрос.Ответ.УстановитьКодСтатуса(201)
    поймать Ошибка: Исключение
        ОбработатьОшибку(Запрос.Ответ, Ошибка)
    ;"""
    elif key == ("GET", True):
        m = re.search(r"\{([^}]+)\}", path)
        param = m.group(1) if m else "id"
        body = f"""\
    попытка
        знч Ид = Запрос.Параметры.ПолучитьПервый("{param}")
        // TODO: найти объект по Ид и отдать его телом
        // знч Объект = <Справочник>.НайтиПоИд(Ид)
        // если Объект != Неопределено
        //     Запрос.Ответ.УстановитьТело(СериализацияJson.ЗаписатьОбъект(Объект))
        //     возврат
        // ;
        Запрос.Ответ.УстановитьКодСтатуса(404)
        Запрос.Ответ.УстановитьТело("Не найдено: " + Ид)
    поймать Ошибка: Исключение
        ОбработатьОшибку(Запрос.Ответ, Ошибка)
    ;"""
    else:
        body = f"""\
    попытка
        // TODO: реализовать {method}
        Запрос.Ответ.УстановитьКодСтатуса(501)
    поймать Ошибка: Исключение
        ОбработатьОшибку(Запрос.Ответ, Ошибка)
    ;"""
    return f"метод {handler}(Запрос: HttpСервисЗапрос)\n{body}\n;"


def _handler_stub_en(method: str, path: str, handler: str, key: tuple[str, bool]) -> str:
    """The same skeleton for a project written in English."""
    if key == ("GET", False):
        body = """\
    try
        // TODO: read the data and send it as the body. Reading a `limit` parameter:
        // val DefaultLimit = 100
        // val LimitParameter = Query.Parameters.GetFirst("limit")
        // val Limit = LimitParameter != Undefined
        //     ? Min(new Number(LimitParameter), DefaultLimit) : DefaultLimit
        // val Data = <Catalog>.GetList(Limit)
        Query.Response.Headers.Set("Content-Type", "application/json")
        Query.Response.SetBody("[]")
    catch Error: Exception
        HandleError(Query.Response, Error)
    ;"""
    elif key == ("POST", False):
        body = """\
    try
        // TODO: deserialize the body and create the object
        // val Data = JsonSerialization.ReadObject(Query.Body, Type<...>)
        // val Reference = <Catalog>.Create(Data)
        Query.Response.SetStatusCode(201)
    catch Error: Exception
        HandleError(Query.Response, Error)
    ;"""
    elif key == ("GET", True):
        m = re.search(r"\{([^}]+)\}", path)
        param = m.group(1) if m else "id"
        body = f"""\
    try
        val Id = Query.Parameters.GetFirst("{param}")
        // TODO: find the object by Id and send it as the body
        // val Object = <Catalog>.FindById(Id)
        // if Object != Undefined
        //     Query.Response.SetBody(JsonSerialization.WriteObject(Object))
        //     return
        // ;
        Query.Response.SetStatusCode(404)
        Query.Response.SetBody("Not found: " + Id)
    catch Error: Exception
        HandleError(Query.Response, Error)
    ;"""
    else:
        body = f"""\
    try
        // TODO: implement {method}
        Query.Response.SetStatusCode(501)
    catch Error: Exception
        HandleError(Query.Response, Error)
    ;"""
    return f"method {handler}(Query: HttpServiceRequest)\n{body}\n;"


_ERROR_HELPER_EN = """\
method HandleError(Response: HttpServiceResponse, Error: Exception)
    Response.SetStatusCode(500)
    Response.Headers.Set("Content-Type", "text/plain; charset=utf-8")
    Response.SetBody(Error.Description)
;"""


_ERROR_HELPER = """\
метод ОбработатьОшибку(Ответ: HttpСервисОтвет, Ошибка: Исключение)
    Ответ.УстановитьКодСтатуса(500)
    Ответ.Заголовки.Установить("Content-Type", "text/plain; charset=utf-8")
    Ответ.УстановитьТело(Ошибка.Описание)
;"""


def _root_url(name: str) -> str:
    """Public URL prefix from the service name: without the kind suffix (naming/prefix-by-kind
    requires the HttpСервис suffix on an HttpСервис, but in the URL it is redundant - a real
    deployment uses /site, not /siteHttpСервис).
    """
    for suffix in ("HttpСервис", "HttpService"):
        if name.endswith(suffix) and len(name) > len(suffix):
            return name[: -len(suffix)]
    return name


def _new_http_service(
    yaml_path: Path, name: str, access: str | None, routes: str, result: ScaffoldResult,
    scope: str | None = None,
) -> ScaffoldResult:
    # A new service has no file to be judged by, so the language is the project's.
    lang = project_language(yaml_path.parent)
    templates = parse_routes(routes)
    used: set[str] = set()
    used_templates: set[str] = set()
    assigned = [
        (path, assign_template_name(path, used_templates, lang),
         [(m, assign_handler(m, path, used, lang)) for m in methods])
        for path, methods in templates
    ]
    root_url = _root_url(name)
    lines = spelled_lines([
        "ВидЭлемента: HttpСервис",
        f"Ид: {new_uuid()}",
        f"Имя: {name}",
        f"ОбластьВидимости: {scope or KIND_SPECS['HttpСервис'].scope}",
        f"КорневойUrl: /{root_url}",
    ], lang)
    if lang == "en":
        # The kind and the scope are the platform's own words - it spells them in English too.
        lines = [spelled_type(line, lang) if line.startswith(("ElementKind:", "VisibilityScope:"))
                 else line for line in lines]
    if any("а" <= c.lower() <= "я" for c in root_url):
        result.notes.append(
            f"КорневойUrl /{root_url} содержит кириллицу – это публичный префикс URL, "
            "обычно его задают латиницей (например, Имя КаталогHttpСервис, КорневойUrl /catalog)"
        )
    if access:
        lines += spelled_lines(
            ["КонтрольДоступа:", "    Разрешения:", f"        Вызов: {access}"], lang
        )
    lines.append(spelled_key("ШаблоныUrl", lang) + ":")
    for path, template, method_handlers in assigned:
        lines.append("    -")
        lines += [
            f"        {line}" for line in _template_lines(path, method_handlers, template, lang)
        ]
    blocks = [
        _handler_stub(m, path, handler, lang)
        for path, _template, method_handlers in assigned
        for m, handler in method_handlers
    ]
    blocks.append(_ERROR_HELPER_EN if lang == "en" else _ERROR_HELPER)
    result.changes.append(FileChange(yaml_path, "\n".join(lines) + "\n", created=True))
    result.changes.append(
        FileChange(yaml_path.with_suffix(".xbsl"), "\n\n".join(blocks) + "\n", created=True)
    )
    return result


def _new_soap_service(
    yaml_path: Path, name: str, access: str | None, result: ScaffoldResult,
    scope: str | None = None,
) -> ScaffoldResult:
    """SoapСервис stub: a service with one example operation + a handler method in the module.

    The structure is from the "Свойства элемента проекта SoapСервис" documentation:
    ПространствоИменСервиса (WSDL targetNamespace), ИмяСервиса (WSDL name), КорневойUrl,
    Обработчики (the operation Имя + the Метод in the module). The operation signature is
    defined by the WSDL contract - the method is left as a stub.
    """
    operation = "Операция1"
    root_url = _root_url(name)
    lines = [
        "ВидЭлемента: SoapСервис",
        f"Ид: {new_uuid()}",
        f"Имя: {name}",
        f"ОбластьВидимости: {scope or KIND_SPECS['SoapСервис'].scope}",
        f"ПространствоИменСервиса: https://example.com/{root_url}",
        f"ИмяСервиса: {name}",
        f"КорневойUrl: /{root_url}",
    ]
    if access:
        lines += ["КонтрольДоступа:", "    Разрешения:", f"        Вызов: {access}"]
    lines += ["Обработчики:", "    -", f"        Имя: {operation}", f"        Метод: {operation}"]
    module = (
        f"метод {operation}()\n"
        "    // TODO: реализовать операцию SOAP-сервиса (сигнатуру задаёт WSDL-контракт)\n;"
    )
    result.changes.append(FileChange(yaml_path, "\n".join(lines) + "\n", created=True))
    result.changes.append(FileChange(yaml_path.with_suffix(".xbsl"), module + "\n", created=True))
    if any("а" <= c.lower() <= "я" for c in root_url):
        result.notes.append(
            f"КорневойUrl /{root_url} и ПространствоИменСервиса содержат кириллицу – "
            "публичные адреса SOAP-сервиса обычно задают латиницей"
        )
    result.notes.append(
        f"Операция-пример {operation}: задайте её сигнатуру и опишите типы ошибок в "
        "Обработчики.Ошибки (типы-исключения) – по контракту сервиса"
    )
    return result


def _method_spans(text: str) -> list[tuple[str, int, int]]:
    """(name, start, end) of every method of a module, annotations included in the span.

    The parser puts the annotation block inside the method node, which is exactly what makes
    insertion safe: both borders of a method are outside anybody's annotation block.
    """
    from xbsl import engine as _engine
    from xbsl import parser as _parser
    from xbsl.parser import parse as _parse

    src = _engine.load_text("Модуль.xbsl", text)
    module, errors = _parse(src)
    if errors:
        from xbsl.lexer import linemap as _linemap

        line, _col = _linemap(src).linecol(errors[0].start)
        raise ScaffoldError(
            "Модуль не разбирается парсером – вставка метода отменена "
            f"(строка {line}: {errors[0].message})"
        )
    spans: list[tuple[str, int, int]] = []
    for m in module.members:
        if isinstance(m, _parser.Method):
            spans.append((m.name, m.start, m.end))
    return spans


def op_add_method(
    module_path: Path,
    name: str,
    *,
    params: str = "",
    returns: str | None = None,
    annotations: str | None = None,
    after: str | None = None,
    before: str | None = None,
    body: str | None = None,
    reader=None,
) -> ScaffoldResult:
    """Insert a method into an existing .xbsl module without tearing annotations apart.

    The trap this replaces: inserting by a text anchor like `"метод Имя"` lands BETWEEN an
    annotation block and the method it belongs to, so the new method silently inherits the
    neighbour's @НаСервере/@Локально and the neighbour loses them. The compiler then reports
    the damage far from the cause. Here the insertion point is always a method BORDER (the
    parser counts the annotation block as part of its method), so no block is ever split.

    Placement: `after`/`before` name an existing method, otherwise the method goes to the end
    of the module. `annotations` is a whitespace-separated list, with or without the `@`.
    """
    module_path = Path(module_path)
    if module_path.suffix != ".xbsl":
        raise ScaffoldError(f"Нужен модуль .xbsl, а не {module_path.name}")
    text, nl = _load_for_edit(module_path, reader)
    name = _check_identifier(name, "метода")
    if after and before:
        raise ScaffoldError("Укажите либо after, либо before, но не оба")

    spans = _method_spans(text)
    existing = {n for n, _, _ in spans}
    if name in existing:
        raise ScaffoldError(f"Метод '{name}' в модуле уже есть")

    anchor_name = after or before
    if anchor_name and anchor_name not in existing:
        known = ", ".join(sorted(existing)) or "методов нет"
        raise ScaffoldError(f"Метод '{anchor_name}' в модуле не найден (есть: {known})")

    header = f"метод {name}({params})"
    if returns:
        header += f": {returns}"
    lines = []
    if annotations:
        marks = [a if a.startswith("@") else f"@{a}" for a in annotations.split()]
        lines.append(" ".join(marks))
    lines.append(header)
    lines.append(f"    {body}" if body else "    // TODO")
    lines.append(";")
    block = "\n".join(lines)

    if anchor_name:
        span = next(s for s in spans if s[0] == anchor_name)
        point = span[2] if after else span[1]
    else:
        point = len(text.rstrip("\r\n"))

    head, tail = text[:point], text[point:]
    if after or not anchor_name:
        new_text = head.rstrip("\r\n") + "\n\n" + block + "\n" + tail.lstrip("\r\n")
        if tail.strip():
            new_text = head.rstrip("\r\n") + "\n\n" + block + "\n\n" + tail.lstrip("\r\n")
    else:
        new_text = head.rstrip("\r\n") + ("\n\n" if head.strip() else "") + block + "\n\n" + tail
    if not new_text.endswith("\n"):
        new_text += "\n"
    if nl != "\n":
        new_text = re.sub(r"(?<!\r)\n", nl, new_text)

    cursor_line = new_text[: new_text.find(block)].count("\n") + len(lines) - 2
    result = ScaffoldResult()
    result.changes.append(
        FileChange(module_path, new_text, created=False, cursor=(cursor_line, 4))
    )
    return result


def op_add_route(yaml_path: Path, routes: str, *, reader=None) -> ScaffoldResult:
    """Add routes to an existing HttpСервис: ШаблоныUrl in yaml + stubs in xbsl.

    An existing template is extended with the missing methods; fully existing routes are
    skipped with a mark in notes.
    """
    yaml_path = Path(yaml_path)
    text, nl = _load_for_edit(yaml_path, reader)
    if element_kind(text) != "HttpСервис":
        raise ScaffoldError(f"{yaml_path.name} – не HttpСервис")
    module_path = yaml_path.with_suffix(".xbsl")
    module_text = (reader or _read)(module_path) if module_path.is_file() else ""
    module_nl = _dominant_nl(module_text)
    # The routes are written in the language of the service they are added to.
    lang = yaml_language(text, yaml_path.parent)

    # Taken handler names: declared in the module and mentioned in yaml. The keyword is
    # bilingual, so a handler of an English module counts as taken just the same.
    declared = set(re.findall(r"^(?:метод|method)\s+([A-Za-zА-Яа-яЁё0-9_]+)", module_text, re.M))
    used = set(declared) | set(re.findall(r"(?:Обработчик|Handler):\s*(\S+)", text))
    # Taken template names: the name is the template key (the platform stores permissions
    # by it, Запрос.ИмяШаблона returns it, and the block to extend below is found by it).
    used_templates = {i.get("Имя", "") for i in section_items(text, "ШаблоныUrl", top_level=True)}
    error_helper_name = "HandleError" if lang == "en" else "ОбработатьОшибку"

    result = ScaffoldResult()
    added: list[tuple[str, str, str]] = []  # (method, template, handler)
    for path, methods in parse_routes(routes):
        template = next(
            (i for i in section_items(text, "ШаблоныUrl", top_level=True) if i.get("Шаблон") == path), None
        )
        if template is not None:
            offset = find_section_item_offset(text, "ШаблоныUrl", template.get("Имя", ""))
            if offset is None:
                raise ScaffoldError(f"Не удалось найти блок шаблона '{path}' в {yaml_path.name}")
            known = set(re.findall(r"(?:Метод|Method):\s*(\S+)", _block_at(text, offset)))
            for method in methods:
                if method in known:
                    result.notes.append(f"Маршрут {method} {path} уже есть – пропущен")
                    continue
                handler = assign_handler(method, path, used, lang)
                edit = insert_nested_item_edit(
                    text, offset, "Методы",
                    spelled_lines([f"Метод: {method}", f"Обработчик: {handler}"], lang), nl
                )
                text = apply_edit(text, edit)
                added.append((method, path, handler))
        else:
            method_handlers = [(m, assign_handler(m, path, used, lang)) for m in methods]
            template_name_ = assign_template_name(path, used_templates, lang)
            edit = insert_item_edit(
                text, "ШаблоныUrl",
                _template_lines(path, method_handlers, template_name_, lang), nl,
                top_level=True,
            )
            text = apply_edit(text, edit)
            added += [(m, path, handler) for m, handler in method_handlers]

    if not added and not result.notes:
        result.notes.append("Новых маршрутов нет")
    result.changes.append(FileChange(yaml_path, text, created=False))

    stubs = [_handler_stub(m, path, handler, lang) for m, path, handler in added]
    if stubs:
        if error_helper_name not in declared:
            stubs.append(_ERROR_HELPER_EN if lang == "en" else _ERROR_HELPER)
        if module_text.strip():
            new_module = module_text.rstrip("\r\n") + "\n\n" + "\n\n".join(stubs) + "\n"
        else:
            new_module = "\n\n".join(stubs) + "\n"
        if module_nl != "\n":
            new_module = re.sub(r"(?<!\r)\n", module_nl, new_module)
        result.changes.append(FileChange(module_path, new_module, created=not module_path.is_file()))
    return result


def _block_at(text: str, offset: int | None) -> str:
    if offset is None:
        return ""
    line_start = text.rfind("\n", 0, offset - 1) + 1
    field_indent = offset - line_start
    end = len(text)
    pos = _line_end(text, offset)
    while pos < len(text):
        ls = pos + 1
        le = _line_end(text, ls)
        line = text[ls:le]
        if line.strip() != "" and len(_LINE_INDENT.match(line).group(0)) < field_indent:
            end = ls
            break
        pos = le
    return text[offset:end]


# --- operations: report -------------------------------------------------------------------


def _new_report(yaml_path: Path, name: str, report: dict, result: ScaffoldResult,
                scope: str | None = None) -> ScaffoldResult:
    """A report with ВидИсточникаДанных: Таблица and a pivot layout over the given fields."""
    source = report.get("source")
    if not source:
        raise ScaffoldError(
            "Отчёту нужен источник: report={source: <Таблица>, rows: [...], columns: [...], measures: [...]}"
        )
    rows = report.get("rows") or []
    columns = report.get("columns") or []
    measures = report.get("measures") or []
    if not rows or not measures:
        raise ScaffoldError("Отчёту нужны хотя бы одно измерение в rows и одна мера в measures")
    lines = [
        "ВидЭлемента: Отчет",
        f"Ид: {new_uuid()}",
        f"Имя: {name}",
        f"ОбластьВидимости: {scope or KIND_SPECS['Отчет'].scope}",
        f"Представление: {report.get('title') or name}",
    ]
    if report.get("import_subsystem"):
        lines += ["Импорт:", f"    - {report['import_subsystem']}"]
    lines += [
        "ВидИсточникаДанных: Таблица",
        f"ИсточникДанных: {source}",
        "Макет:",
        "    ВидОтображения: СводнаяТаблица",
        "    Поля:",
    ]

    def dim(expr: str, role: str, total: bool = False) -> list[str]:
        roles = [f"                - {role}"] + (["                - Итог"] if total else [])
        return [
            "        -",
            "            Вид: Измерение",
            "            ВизуальныеРоли:",
            *roles,
            f"            Выражение: {expr}",
            f"            Ид: {new_uuid()}",
            "            Использовать: Истина",
        ]

    for expr in rows:
        lines += dim(expr, "Строки")
    for expr in columns:
        lines += dim(expr, "Колонки", total=True)
    for measure in measures:
        expr = measure["expr"] if isinstance(measure, dict) else str(measure)
        title = measure.get("title") if isinstance(measure, dict) else None
        if "(" not in expr:
            expr = f"СУММА({expr})"
        lines += [
            "        -",
            "            Вид: Мера",
            "            ВизуальныеРоли:",
            "                - ЗначенияКолонок",
            f"            Выражение: {expr}",
            f"            Ид: {new_uuid()}",
            "            Использовать: Истина",
        ]
        if title:
            lines.append(f"            Представление: {title}")
    result.changes.append(FileChange(yaml_path, "\n".join(lines) + "\n", created=True))
    return result


# --- operations: forms --------------------------------------------------------------------


def _form_field_component(name: str, type_: str, indent: str) -> list[str]:
    """Editing component by attribute type (the mapping from the form specification)."""
    if type_ == "Булево":
        return [f"{indent}-", f"{indent}    Тип: Флажок", f"{indent}    Имя: {name}",
                f"{indent}    Значение: =Объект.{name}"]
    component_type = type_ or "Строка"
    # '?' is added only where the type is known to have no default value: a reference and
    # an enumeration. Collections and generics (Массив<Строка> etc.) do have a default -
    # they used to get a '?', and the two-way binding Значение: =Объект.X diverged in type.
    needs_nullable = (
        component_type not in PRIMITIVE_TYPES
        and not component_type.endswith("?")
        and "<" not in component_type
    )
    if needs_nullable:
        component_type += "?"
    lines = [
        f"{indent}-",
        f"{indent}    Тип: ПолеВвода<{component_type}>",
        f"{indent}    Имя: {name}",
        f"{indent}    Значение: =Объект.{name}",
    ]
    if type_ in ("Строка", "") and name in ("Описание", "Комментарий"):
        lines += [f"{indent}    НастройкиВводаСтроки:", f"{indent}        Многострочная: Истина"]
    return lines


def _form_fields(info: dict) -> list[dict]:
    fields = list(info["fields"])
    if info["is_hierarchical"]:
        # The system hierarchy attribute: absent from the object yaml, needed in the form.
        obj = info["name"]
        after = 1 if fields and fields[0]["name"] == "Наименование" else 0
        fields.insert(after, {"name": "Родитель", "type": f"{obj}.Ссылка?"})
    return fields


def _tabular_table_lines(obj: str, tc_name: str, indent: str, panels: bool,
                         fields: list[dict] | None = None) -> list[str]:
    """Tabular part table: the source, columns by its attributes and row commands.

    Columns are mandatory - "Необходимо задать Колонки (колонки таблицы) и Источник"
    (the "Компонент интерфейса Таблица" documentation): without them the table shows
    empty rows. ПолеЗначения also defines column sorting, so it is written along with
    Заголовок.
    """
    lines = [
        f"{indent}Тип: Таблица<ИсточникДанныхМассив<{obj}.{tc_name}>>",
        f"{indent}Имя: {tc_name}",
    ]
    if panels:
        lines += [
            f"{indent}ВидОтображенияКомандСтроки: ПриНаведении",
            f"{indent}ОтображатьНумерациюСтрок: Ложь",
            f"{indent}РастягиватьПоВертикали: Ложь",
            f"{indent}ШиринаВКолонках: Четверная",
        ]
    lines += [
        f"{indent}Источник:",
        f"{indent}    Данные: =Объект.{tc_name}",
    ]
    if fields:
        lines.append(f"{indent}Колонки:")
        for field in fields:
            lines += [
                f"{indent}    -",
                f"{indent}        Тип: СтандартнаяКолонкаТаблицы<{obj}.{tc_name}>",
                f"{indent}        Заголовок: {field['name']}",
                f"{indent}        ПолеЗначения: {field['name']}",
            ]
    lines += [
        f"{indent}Команды:",
        f"{indent}    Тип: ФрагментКомандногоИнтерфейса",
        f"{indent}    Элементы:",
        f"{indent}        - =Компоненты.{tc_name}.ДобавитьСтроку",
        f"{indent}КомандыСтроки:",
        f"{indent}    Тип: ФрагментКомандногоИнтерфейса<КомандаСПараметром<{obj}.{tc_name}>>",
        f"{indent}    Элементы:",
        f"{indent}        - =Компоненты.{tc_name}.Удалить",
    ]
    return lines


def object_form_yaml(info: dict, uid: str) -> str:
    """ФормаОбъекта from the object summary: simple / panels / tabs by tabular part and attribute counts."""
    obj = info["name"]
    fields = _form_fields(info)
    tabulars = info["tabulars"]
    layout = info["suggested_layout"]
    lines = [
        "ВидЭлемента: КомпонентИнтерфейса",
        f"Ид: {uid}",
        f"Имя: {obj}ФормаОбъекта",
        "ОбластьВидимости: ВПодсистеме",
        "Наследует:",
        f"    Тип: ФормаОбъекта<{obj}.Объект>",
        "    ВключатьВАвтоИнтерфейс: Ложь",
        f"    Заголовок: {obj}",
    ]
    if tabulars:
        lines.append("    РастягиватьПоВертикали: Истина")
    lines += [
        "    ДополнительныеКоманды:",
        "        Тип: ФрагментКомандногоИнтерфейса",
        "        Элементы:",
        "            - =Удалить",
        "            - =Восстановить",
        "    ОсновнаяКоманда: =ЗаписатьИЗакрыть",
        "    Содержимое:",
    ]
    if layout == "simple":
        lines += [
            "        Тип: ПроизвольныйШаблонФормы",
            "        ШиринаВКолонках: Одинарная",
            "        Содержимое:",
            "            Тип: Группа",
            "            Содержимое:",
        ]
        for f in fields:
            lines += _form_field_component(f["name"], f["type"], "                ")
        return "\n".join(lines) + "\n"

    section_type = "Группа" if layout == "panels" else "РазделФормы"
    lines += [
        "        Тип: ШаблонФормыСРазделами",
        "        РастягиватьПоВертикали: Истина",
        "        ОсновнойРаздел:",
        f"            Тип: {section_type}",
        "            Заголовок: Основное",
        "            ШиринаВКолонках: Одинарная",
        "            Содержимое:",
    ]
    if section_type == "РазделФормы":
        # РазделФормы.Содержимое is Массив<Группа>: fields go into the section area, not
        # directly (a Группа's content is Массив<Компонент>, no wrapper needed there).
        lines += [
            "                -",
            "                    Содержимое:",
        ]
        field_indent = " " * 24
    else:
        field_indent = " " * 16
    for f in fields:
        lines += _form_field_component(f["name"], f["type"], field_indent)
    lines.append("        ДополнительныеРазделы:")
    for tc in tabulars:
        tc_name = tc["name"]
        if layout == "panels":
            lines += [
                "            -",
                "                Тип: Группа",
                f"                Заголовок: {tc_name}",
                "                ШиринаВКолонках: Двойная",
                "                Содержимое:",
                "                    -",
                "                        Тип: СворачиваемыйКомпонент",
                f"                        Заголовок: {tc_name}",
                "                        РастягиватьПоГоризонтали: Истина",
                "                        ШиринаВКолонках: Четверная",
                "                        Содержимое:",
            ] + _tabular_table_lines(obj, tc_name, " " * 28, panels=True, fields=tc["fields"])
        else:
            lines += [
                "            -",
                "                Тип: РазделФормы",
                f"                Заголовок: {tc_name}",
                "                Содержимое:",
                "                    -",
                "                        Содержимое:",
            ] + [" " * 28 + "-"] + _tabular_table_lines(
                obj, tc_name, " " * 32, panels=False, fields=tc["fields"]
            )
    return "\n".join(lines) + "\n"


def _list_sort_field(info: dict, fields: list[str]) -> str | None:
    """Default list sort field: Дата for a document, otherwise Наименование."""
    if info["kind"] == "Документ" and "Дата" in fields:
        return "Дата"
    return "Наименование" if "Наименование" in fields else None


def list_form_yaml(info: dict, uid: str) -> str:
    """ФормаСписка from the object summary: a dynamic list, columns by fields, hierarchy."""
    obj = info["name"]
    ns = info["namespace"]
    row_type = f"{ns}::{obj}ФормаСписка.ДанныеСтрокиСписка"
    hierarchical = info["is_hierarchical"]
    extra_hierarchies = info["additional_hierarchies"]
    list_type = (
        f"ДинамическийСписок<{row_type}, {row_type}>"
        if hierarchical
        else f"ДинамическийСписок<{row_type}>"
    )
    fields = [f["name"] for f in info["fields"]]
    list_fields = list(fields)
    if hierarchical and "Родитель" not in list_fields:
        list_fields.insert(0, "Родитель")

    lines = [
        "ВидЭлемента: КомпонентИнтерфейса",
        f"Ид: {uid}",
        f"Имя: {obj}ФормаСписка",
        "ОбластьВидимости: ВПодсистеме",
        "Наследует:",
        "    Тип: ФормаСписка",
        "    ВключатьВАвтоИнтерфейс: Ложь",
        f"    Заголовок: {obj}",
        "    ДополнительныеКоманды:",
        "        Тип: ФрагментКомандногоИнтерфейса",
        "        Элементы:",
        "            - =Обновить",
        "    КомандыСоздания: =Компоненты.ОсновнаяТаблица.ДобавитьСтроку",
        "    КомпонентТаблицы: =Компоненты.ОсновнаяТаблица",
        "    Содержимое:",
        "        Тип: ПроизвольныйШаблонФормы",
        "        Содержимое:",
        f"            Тип: Таблица<{list_type}>",
        "            Имя: ОсновнаяТаблица",
        "            Источник: =Список",
    ]
    if hierarchical:
        lines.append("            НачальныйУровеньРазворачивания: -1")
    lines.append("            Колонки:")
    for name in fields:
        # ПолеЗначения defines not only the displayed value but also column sorting
        # ("Также это поле будет использоваться для сортировки по данной колонке" - the
        # Таблица component documentation), so it is written along with Заголовок.
        lines += [
            "                -",
            f"                    Тип: СтандартнаяКолонкаТаблицы<СтрокаДинамическогоСписка<{row_type}>>",
            f"                    Имя: {name}",
            f"                    Заголовок: {name}",
            f"                    ПолеЗначения: {name}",
        ]
    lines += [
        "            КомандыСтроки:",
        f"                Тип: ФрагментКомандногоИнтерфейса<КомандаСПараметром<СтрокаДинамическогоСписка<{row_type}>>>",
        "                Элементы:",
        "                    - =Компоненты.ОсновнаяТаблица.СоздатьКопию",
        "Свойства:",
        "    -",
        "        Имя: Список",
        f"        Тип: {list_type}",
        "        ЗначениеПоУмолчанию:",
        "            ИмяТипаДанныхСтроки: ДанныеСтрокиСписка",
    ]
    if hierarchical:
        # Element hierarchy: no name to write and nothing to write - "Если ПоУмолчанию или
        # пустая строка, будет отображена иерархия, которая указана как иерархия
        # по-умолчанию в справочнике" (stdlib ДинамическийСписок). A hierarchy named
        # "Иерархия" does not exist: that is the name of a query language table, not of a
        # catalog hierarchy.
        lines += [
            "            ИспользуемаяИерархия:",
            "                Тип: РежимИерархии",
            "                Значение: ПоУмолчанию",
        ]
    elif extra_hierarchies:
        lines += [
            "            ИспользуемаяИерархия:",
            "                Тип: Строка",
            f"                Значение: {extra_hierarchies[0]['name']}",
        ]
    lines += [
        "            ОсновнаяТаблица:",
        f"                Таблица: {obj}",
        "            Поля:",
    ]
    for name in list_fields:
        lines += [
            "                -",
            "                    Тип: ПолеДинамическогоСписка",
            f"                    Выражение: {name}",
        ]
    sort_field = _list_sort_field(info, fields)
    if sort_field:
        lines += [
            "            Сортировка:",
            "                -",
            f"                    Поле: {sort_field}",
            "                    НаправлениеСортировки: ПоВозрастанию",
        ]
    return "\n".join(lines) + "\n"


# --- card list form ------------------------------------------------------------------------
#
# A list form with cards: ПроизвольныйСписок renders every record as a separate component
# (ТипКомпонентаСтроки), and a КонтейнерСтрок with matrix layout arranges the cards in a
# grid. There are two forms: the form itself and the row component СтрокаСписка<Объект>.
# Mapping to the 9.2 documentation: ПроизвольныйСписок.ТипКомпонентаСтроки /
# .КонтейнерСтрок, НастройкиМатричнойКомпоновки.ОписаниеАвтоматических{Колонок,Строк},
# АвтоЗаполнениеМатричнойГруппы.ДобавлятьКолонкиИСтроки (requires a definite column size -
# hence the МинимальнаяШирина on the auto columns), ФормаСписка.КомпонентТаблицы accepts
# any Компонент.

CARD_ROW_PREFIX = "СтрокаСписка"
_CARD_MIN_WIDTH = 400  # grid column width; with a photo the card is narrower - see _card_min_width
_CARD_MIN_WIDTH_PHOTO = 250
_CARD_CONTENT_LIMIT = 3  # beyond three fields a card is unreadable; the rest - by hand

# Types whose value fits directly into a Строка (СтандартнаяКарточка.Содержимое: Компонент|Строка).
_CARD_DATE_FORMATS = {
    "Дата": "дд ММММ гггг",
    "ДатаВремя": "дд ММММ гггг ЧЧ:мм",
    "Время": "ЧЧ:мм",
}


def _is_photo_type(type_: str) -> bool:
    return type_.replace(" ", "").startswith("ДвоичныйОбъект.Ссылка")


def _card_roles(fields: list[dict]) -> dict:
    """Card field roles: {title, photo, content} - the title, the photo, secondary fields.

    Title - Наименование, otherwise the first string field, otherwise the first field.
    Photo - the first ДвоичныйОбъект.Ссылка attribute. Content - the following fields,
    at most _CARD_CONTENT_LIMIT.
    """
    photo = next((f for f in fields if _is_photo_type(f["type"])), None)
    rest = [f for f in fields if f is not photo]
    title = (
        next((f for f in rest if f["name"] == "Наименование"), None)
        or next((f for f in rest if f["type"] in ("Строка", "")), None)
        or (rest[0] if rest else None)
    )
    content = [f for f in rest if f is not title][:_CARD_CONTENT_LIMIT]
    return {"title": title, "photo": photo, "content": content}


def _card_fields(roles: dict) -> list[dict]:
    """The fields the card actually shows, in title - photo - content order."""
    ordered = [roles["title"], roles["photo"], *roles["content"]]
    return [f for f in ordered if f is not None]


def _card_value(field: dict) -> str:
    """Binding of the row field value; date/time - via Представление(Формат)."""
    expr = f"=ДанныеСтроки.Данные.{field['name']}"
    fmt = _CARD_DATE_FORMATS.get(field["type"])
    return f'{expr}.Представление("{fmt}")' if fmt else expr


def _card_is_text(field: dict) -> bool:
    """Whether the value fits directly into a string property (card Заголовок/Содержимое)."""
    return field["type"] in ("Строка", "") or field["type"] in _CARD_DATE_FORMATS


def _card_label(field: dict, indent: str) -> list[str]:
    return [f"{indent}Тип: Надпись", f"{indent}Значение: {_card_value(field)}"]


def _card_content_lines(content: list[dict], indent: str) -> list[str]:
    """Lines of the card's Содержимое property: a string, one Надпись or a Группа of labels.

    Non-text values (references, enumerations, numbers) do not fit into a string
    property - a Надпись renders them.
    """
    if not content:
        return []
    if len(content) == 1 and _card_is_text(content[0]):
        return [f"{indent}Содержимое: {_card_value(content[0])}"]
    if len(content) == 1:
        return [f"{indent}Содержимое:"] + _card_label(content[0], indent + "    ")
    lines = [
        f"{indent}Содержимое:",
        f"{indent}    Тип: Группа",
        f"{indent}    Компоновка: Вертикальная",
        f"{indent}    Содержимое:",
    ]
    for field in content:
        lines.append(f"{indent}        -")
        lines += _card_label(field, indent + "            ")
    return lines


def _card_min_width(roles: dict, min_width: int | None) -> int:
    if min_width:
        return min_width
    return _CARD_MIN_WIDTH_PHOTO if roles["photo"] else _CARD_MIN_WIDTH


def card_row_yaml(info: dict, uid: str, *, placeholder: str | None = None) -> str:
    """Card list row component: СтандартнаяКарточка, with a photo - ПроизвольнаяКарточка.

    placeholder - a placeholder image expression (e.g. "Ресурс{Аккаунт.svg}.Ссылка");
    without it an empty photo is simply not displayed (Картинка.Изображение allows
    Неопределено).
    """
    obj = info["name"]
    row_type = f'{info["namespace"]}::{obj}ФормаСписка.ДанныеСтрокиСписка'
    roles = _card_roles(info["fields"])
    title, photo = roles["title"], roles["photo"]
    lines = [
        "ВидЭлемента: КомпонентИнтерфейса",
        f"Ид: {uid}",
        f"Имя: {CARD_ROW_PREFIX}{obj}",
        "ОбластьВидимости: ВПодсистеме",
        "Наследует:",
        f"    Тип: ПроизвольнаяСтрокаСписка<СтрокаДинамическогоСписка<{row_type}>>",
        "    Содержимое:",
    ]
    if photo is None:
        lines += [
            "        Тип: СтандартнаяКарточка",
            "        РастягиватьПоВертикали: Истина",
            "        РастягиватьПоГоризонтали: Истина",
        ]
        if title is not None:
            heading = _card_value(title) if _card_is_text(title) else f"=ДанныеСтроки.Данные.{title['name']}.ВСтроку()"
            lines.append(f"        Заголовок: {heading}")
        lines += _card_content_lines(roles["content"], "        ")
        return "\n".join(lines) + "\n"

    # With a photo - a custom card: in the standard one the image goes into the header,
    # while a vertical "photo above caption" stack is needed (a Группа is horizontal by
    # default).
    image = _card_value(photo)
    if placeholder:
        image = f"{image} ?? {placeholder}"
    lines += [
        "        Тип: ПроизвольнаяКарточка",
        "        РастягиватьПоВертикали: Истина",
        "        РастягиватьПоГоризонтали: Истина",
        "        Содержимое:",
        "            Тип: Группа",
        "            Компоновка: Вертикальная",
        "            РастягиватьПоГоризонтали: Истина",
        "            Содержимое:",
        "                -",
        "                    Тип: Картинка",
        "                    Высота: 200",
        "                    РастягиватьПоВертикали: Ложь",
        "                    РастягиватьПоГоризонтали: Истина",
        "                    Масштабирование: Пропорционально",
        f"                    Изображение: {image}",
    ]
    for field in ([title] if title is not None else []) + roles["content"]:
        lines += [
            "                -",
            "                    Тип: Надпись",
            "                    РастягиватьПоГоризонтали: Истина",
            f"                    Значение: {_card_value(field)}",
        ]
    return "\n".join(lines) + "\n"


def cards_list_form_yaml(info: dict, uid: str, *, min_width: int | None = None) -> str:
    """ФормаСписка with cards: ПроизвольныйСписок + a matrix КонтейнерСтрок.

    Differs from list_form_yaml only in the component: instead of a Таблица with columns -
    a list rendering every record with the CARD_ROW_PREFIX+Объект component. The dynamic
    list fields are Ссылка (needed for navigation) and those the card shows.
    """
    obj = info["name"]
    row_type = f'{info["namespace"]}::{obj}ФормаСписка.ДанныеСтрокиСписка'
    list_type = f"ДинамическийСписок<{row_type}>"
    roles = _card_roles(info["fields"])
    shown = [f["name"] for f in _card_fields(roles)]
    width = _card_min_width(roles, min_width)
    lines = [
        "ВидЭлемента: КомпонентИнтерфейса",
        f"Ид: {uid}",
        f"Имя: {obj}ФормаСписка",
        "ОбластьВидимости: ВПодсистеме",
        "Наследует:",
        "    Тип: ФормаСписка",
        "    ВключатьВАвтоИнтерфейс: Ложь",
        f"    Заголовок: {obj}",
        "    ДополнительныеКоманды:",
        "        Тип: ФрагментКомандногоИнтерфейса",
        "        Элементы:",
        "            - =Обновить",
        "    КомандыСоздания: =Компоненты.ОсновнаяТаблица.ДобавитьСтроку",
        "    КомпонентТаблицы: =Компоненты.ОсновнаяТаблица",
        "    Содержимое:",
        "        Тип: ПроизвольныйШаблонФормы",
        "        Содержимое:",
        f"            Тип: ПроизвольныйСписок<{list_type}>",
        "            Имя: ОсновнаяТаблица",
        "            Источник: =Список",
        "            ОбрабатыватьНажатие: Истина",
        f"            ТипКомпонентаСтроки: {CARD_ROW_PREFIX}{obj}",
        "            РастягиватьПоГоризонтали: Истина",
        "            РастягиватьПоВертикали: Истина",
        "            КонтейнерСтрок:",
        "                Тип: Группа",
        "                Имя: СеткаКарточек",
        "                Компоновка: Матричная",
        "                РастягиватьПоГоризонтали: Истина",
        "                НастройкиМатричнойКомпоновки:",
        "                    АвтоЗаполнение: ДобавлятьКолонкиИСтроки",
        "                    ОписаниеАвтоматическихКолонок:",
        f"                        МинимальнаяШирина: {width}",
        "                        РастягиватьПоГоризонтали: Истина",
        "                    ОписаниеАвтоматическихСтрок:",
        "                        РастягиватьПоВертикали: Истина",
        "Свойства:",
        "    -",
        "        Имя: Список",
        f"        Тип: {list_type}",
        "        ЗначениеПоУмолчанию:",
        "            ИмяТипаДанныхСтроки: ДанныеСтрокиСписка",
        "            ОсновнаяТаблица:",
        f"                Таблица: {obj}",
        "            Поля:",
    ]
    for name in ["Ссылка"] + shown:
        lines += [
            "                -",
            "                    Тип: ПолеДинамическогоСписка",
            f"                    Выражение: {name}",
        ]
    sort_field = _list_sort_field(info, shown)
    if sort_field:
        lines += [
            "            Сортировка:",
            "                -",
            f"                    Поле: {sort_field}",
            "                    НаправлениеСортировки: ПоВозрастанию",
        ]
    return "\n".join(lines) + "\n"


def report_form_yaml(info: dict, uid: str) -> str:
    """ФормаОтчета: report parameter fields + the ПросмотрОтчета component."""
    obj = info["name"]
    params = info["report_params"]
    lines = [
        "ВидЭлемента: КомпонентИнтерфейса",
        f"Ид: {uid}",
        f"Имя: {obj}ФормаОтчета",
        "ОбластьВидимости: ВПодсистеме",
        "Наследует:",
        "    Тип: ФормаОтчета",
        "    ВключатьВАвтоИнтерфейс: Ложь",
        "    Заголовок: =Отчет.Представление",
        "    Содержимое:",
        "        Тип: ПроизвольныйШаблонФормы",
        "        Содержимое:",
    ]
    viewer = [
        "Тип: ПросмотрОтчета",
        "Имя: ПросмотрОтчета",
        "Отчет: =Отчет",
        "РастягиватьПоВертикали: Истина",
        "РастягиватьПоГоризонтали: Истина",
        "ТолькоЧтение: Истина",
    ]
    if params:
        lines += [
            "            Тип: Группа",
            "            Компоновка: Вертикальная",
            "            Содержимое:",
            "                -",
            "                    Тип: Группа",
            "                    Содержимое:",
        ]
        for p in params:
            ptype = p["type"] or "Строка"
            lines += [
                "                        -",
                f"                            Тип: ПолеВвода<{ptype}>",
                f"                            Имя: {p['name']}",
                f"                            Заголовок: {p['name']}",
                f"                            Значение: =Отчет.Параметры.{p['name']}",
            ]
        lines += ["                -"] + [f"                    {line}" for line in viewer]
    else:
        lines += [f"            {line}" for line in viewer]
    lines += [
        "Свойства:",
        "    -",
        "        Имя: Отчет",
        f"        Тип: {obj}",
        "        ЗначениеПоУмолчанию:",
        f"            Тип: {obj}",
    ]
    return "\n".join(lines) + "\n"


def _interface_block(kind: str, obj: str, forms: list[str]) -> list[str]:
    lines = ["Интерфейс:", "    ВключатьВАвтоИнтерфейс: Истина"]
    if kind == "Отчет":
        return lines + [f"    Форма: {obj}ФормаОтчета"]
    if kind == "Справочник":
        lines.append("    ИспользоватьСозданиеПриВводе: Истина")
    if "object" in forms:
        lines += ["    Объект:", f"        Форма: {obj}ФормаОбъекта"]
    if "list" in forms:
        lines += ["    Список:", f"        Форма: {obj}ФормаСписка"]
    return lines


def _register_forms(text: str, nl: str, kind: str, obj: str, forms: list[str], result: ScaffoldResult) -> str:
    """Register forms in the object yaml: insert an Интерфейс section or extend an existing one."""
    if not re.search(r"^Интерфейс:", text, re.M):
        block = _interface_block(kind, obj, forms)
        anchor = None
        for key in ("ОбластьВидимости", "Имя", "Ид"):
            m = re.search(rf"^{key}:.*\r?$", text, re.M)
            if m:
                anchor = _line_end(text, m.start())
                break
        rendered = nl.join(block)
        if anchor is None:
            tail = "" if text.endswith("\n") else nl
            return text + f"{tail}{rendered}{nl}"
        return text[:anchor] + f"{nl}{rendered}" + text[anchor:]

    # The section exists - append the missing registrations at its end, leave existing ones.
    if kind == "Отчет":
        # A report form is registered by the single Интерфейс.Форма key (it has no
        # Объект/Список subsections), so the generic loop below does not serve it.
        form_name = f"{obj}ФормаОтчета"
        span = top_level_key_span(text, "Интерфейс")
        if re.search(rf"Форма:\s*{form_name}\b", text):
            result.notes.append(f"{form_name} уже зарегистрирована в Интерфейс")
        elif re.search(r"^\s{4}Форма:", text[span[0]: span[1]], re.M):
            result.notes.append("В Интерфейс уже указана Форма – регистрация вручную")
        else:
            text = text[: span[1]] + f"{nl}    Форма: {form_name}" + text[span[1]:]
        return text

    for form, subsection in (("object", "Объект"), ("list", "Список")):
        if form not in forms:
            continue
        form_name = f"{obj}Форма{'Объекта' if form == 'object' else 'Списка'}"
        if re.search(rf"Форма:\s*{form_name}\b", text):
            result.notes.append(f"{form_name} уже зарегистрирована в Интерфейс")
            continue
        span = top_level_key_span(text, "Интерфейс")
        body = text[span[0]: span[1]]
        sub = re.search(rf"^    {subsection}:[ \t]*\r?$", body, re.M)
        if sub is None:
            text = text[: span[1]] + f"{nl}    {subsection}:{nl}        Форма: {form_name}" + text[span[1]:]
        else:
            result.notes.append(
                f"В Интерфейс уже есть подсекция {subsection} – зарегистрируйте {form_name} вручную"
            )
    return text


FORM_KINDS = ("object", "list", "list-cards", "report")


def op_add_form(root: Path, name: str | None = None, yaml_path: Path | None = None,
                forms: list[str] | None = None, overwrite: bool = False,
                card_min_width: int | None = None, card_placeholder: str | None = None,
                reader=None) -> ScaffoldResult:
    """Create object forms populated from its attributes and register them in Интерфейс.

    forms is a subset of FORM_KINDS; by default object+list for data objects and report
    for Отчет. "list-cards" is the same list form but with cards (ПроизвольныйСписок with
    a matrix grid); it is incompatible with "list" (both are the file
    <Объект>ФормаСписка.yaml) and creates a second file - the row component
    СтрокаСписка<Объект>. card_min_width sets the grid column width (400 by default,
    250 with a photo), card_placeholder is a placeholder image expression. An existing
    form is not overwritten without overwrite - a note goes into notes instead.
    """
    info = object_info(Path(root), name=name, yaml_path=yaml_path)
    text_of_owner = (reader or _read)(Path(info["path"]))
    kind = info["kind"]
    obj = info["name"]
    owner_path = Path(info["path"])
    if forms is None:
        if kind == "Отчет":
            forms = ["report"]
        elif kind in OBJECT_FORM_KINDS:
            forms = ["object", "list"]
        elif kind in LIST_FORM_KINDS:
            forms = ["list"]  # registers and a constant set never have an object form
        else:
            raise ScaffoldError(
                f"У вида {kind} нет форм объекта и списка; они есть у: "
                + ", ".join(LIST_FORM_KINDS) + " (и форма отчёта у Отчет)"
            )
    unknown = [f for f in forms if f not in FORM_KINDS]
    if unknown:
        raise ScaffoldError(
            f"Неизвестный вид формы: {', '.join(unknown)}; доступны: {', '.join(FORM_KINDS)}"
        )
    if "list" in forms and "list-cards" in forms:
        raise ScaffoldError(
            "list и list-cards – одна и та же форма списка (<Объект>ФормаСписка): выберите одну"
        )
    if kind == "Отчет" and forms != ["report"]:
        raise ScaffoldError("Для отчёта доступна только форма отчёта: forms=[\"report\"]")
    if kind != "Отчет" and "report" in forms:
        raise ScaffoldError(f"Форма отчёта неприменима к виду {kind}")
    # Only reference entities produce the ФормаОбъекта<X.Объект> type; a register has none.
    if "object" in forms and kind not in OBJECT_FORM_KINDS:
        raise ScaffoldError(
            f"У вида {kind} нет формы объекта (тип ФормаОбъекта порождают только "
            + ", ".join(OBJECT_FORM_KINDS) + f"); для {kind} доступна форма списка"
        )
    if ("list" in forms or "list-cards" in forms) and kind not in LIST_FORM_KINDS:
        raise ScaffoldError(
            f"У вида {kind} нет формы списка; она есть у: " + ", ".join(LIST_FORM_KINDS)
        )

    result = ScaffoldResult()
    generators = {
        "object": ("ФормаОбъекта", object_form_yaml),
        "list": ("ФормаСписка", list_form_yaml),
        "list-cards": ("ФормаСписка", lambda i, uid: cards_list_form_yaml(i, uid, min_width=card_min_width)),
        "report": ("ФормаОтчета", report_form_yaml),
    }
    # The form is written in the language of the object it belongs to: a Russian form in an
    # English project would be exactly the island the bilingual reading was fixed to avoid.
    lang = yaml_language(text_of_owner, owner_path.parent)
    made: list[str] = []
    for form in forms:
        suffix, generator = generators[form]
        form_path = owner_path.parent / f"{obj}{form_suffix(suffix, lang)}.yaml"
        if form_path.exists() and not overwrite:
            result.notes.append(f"{form_path.name} уже существует – пропущена (overwrite=true перезапишет)")
            continue
        content = localize_form_text(generator(info, new_uuid()), info, lang)
        result.changes.append(
            FileChange(form_path, content, created=not form_path.exists())
        )
        if lang == "en":
            left = untranslated_words(content, author_names(info))
            if left:
                # The data spells the INTERFACE enum values in Russian only; inventing an
                # English one would be inventing platform vocabulary.
                result.notes.append(
                    f"{form_path.name}: значения перечислений интерфейса остались русскими "
                    "(английских написаний нет в данных платформы) – " + ", ".join(left)
                )
        made.append(form)
        if form == "list-cards":
            _add_card_row(info, owner_path, overwrite, card_placeholder, result)
    if made:
        text, nl = text_of_owner, _dominant_nl(text_of_owner)
        # The card list form is registered like a regular one: the same <Объект>ФормаСписка file.
        registered = ["list" if f == "list-cards" else f for f in made]
        new_text = _register_forms(text, nl, kind, obj, registered, result)
        if new_text != text:
            result.changes.append(FileChange(owner_path, new_text, created=False))
    return result


def _add_card_row(info: dict, owner_path: Path, overwrite: bool, placeholder: str | None,
                  result: ScaffoldResult) -> None:
    """The card list row component + notes about what made it into the card."""
    obj = info["name"]
    row_path = owner_path.parent / f"{CARD_ROW_PREFIX}{obj}.yaml"
    if row_path.exists() and not overwrite:
        result.notes.append(
            f"{row_path.name} уже существует – пропущен (overwrite=true перезапишет)"
        )
    else:
        result.changes.append(
            FileChange(row_path, card_row_yaml(info, new_uuid(), placeholder=placeholder),
                       created=not row_path.exists())
        )
    roles = _card_roles(info["fields"])
    shown = [f["name"] for f in _card_fields(roles)]
    result.notes.append(
        "В карточку вынесены поля: " + (", ".join(shown) if shown else "нет реквизитов")
    )
    hidden = [f["name"] for f in info["fields"] if f["name"] not in shown]
    if hidden:
        result.notes.append(
            "Не попали в карточку: " + ", ".join(hidden)
            + " – добавьте вручную в " + row_path.name + " и в Поля списка"
        )
    if info["is_hierarchical"]:
        result.notes.append(
            "Объект иерархический, но карточная сетка выводит плоский список – "
            "иерархия в форме не используется"
        )


# --- access control -------------------------------------------------------------------------
#
# КонтрольДоступа.Разрешения is a set of "Право: СпособКонтроляДоступа" entries (the
# "Контроль прав доступа" documentation). Entity rights are Создание/Чтение/Изменение/
# Удаление (Стд::Сущности::Сущность.Право), services have Вызов, registers and a constant
# set have Чтение/Изменение; ПоУмолчанию sets the method for all other rights. A right can
# also be custom - "ПравоНаX.ИмяПрава" (a project element of kind ПравоНаЭлемент). With no
# section the platform applies РазрешеноАдминистраторам.

ACCESS_METHODS = (
    "РазрешеноВсем",
    "РазрешеноАутентифицированным",
    "РазрешеноАдминистраторам",
    "РазрешенияВычисляются",
    "РазрешенияВычисляютсяДляКаждогоОбъекта",
)
ACCESS_DEFAULT_RIGHT = "ПоУмолчанию"
_ACCESS_IMPLICIT = "РазрешеноАдминистраторам"  # when there is no КонтрольДоступа section
_PER_OBJECT = "РазрешенияВычисляютсяДляКаждогоОбъекта"

# Rights per project element kind (the "Контроль прав доступа" documentation: exactly
# these kinds support access control). An empty tuple - the kind supports ПоУмолчанию only.
ACCESS_KIND_RIGHTS: dict[str, tuple[str, ...]] = {
    "Справочник": ("Создание", "Чтение", "Изменение", "Удаление"),
    "Документ": ("Создание", "Чтение", "Изменение", "Удаление"),
    "ПланОбмена": ("Создание", "Чтение", "Изменение", "Удаление"),
    "РегистрСведений": ("Чтение", "Изменение"),
    "РегистрНакопления": ("Чтение", "Изменение"),
    "НаборКонстант": ("Чтение", "Изменение"),
    "HttpСервис": ("Вызов",),
    "SoapСервис": ("Вызов",),
    "ХранилищеНастроек": (),
}
# A constant set does not support per-record permissions (the "Свойства элемента проекта
# вида НаборКонстант" documentation).
_NO_PER_OBJECT_KINDS = ("НаборКонстант",)

_ACCESS_SECTION = "КонтрольДоступа"
_PERMISSIONS_KEY = "Разрешения"
_CALC_BY_KEY = "РасчетРазрешенийПо"
# Where to insert the КонтрольДоступа section when missing: before the first of these sections.
_ACCESS_ANCHORS = (
    "Реквизиты", "Измерения", "Ресурсы", "ТабличныеЧасти", "ШаблоныUrl", "Операции",
    "Интерфейс", "НастройкиТипов", "Индексы", "Свойства",
)
_KEY_VALUE_LINE = re.compile(rf"^([ \t]*)([{_WORD}.]+):[ \t]*(\S.*?)[ \t]*$")


def _mapping_in(body: str, key: str) -> dict[str, str]:
    """Scalar "Ключ: Значение" pairs of a nested mapping section (e.g. Разрешения)."""
    bounds = _section_bounds(body, key)
    if bounds is None:
        return {}
    header_indent, header_line_end, body_end = bounds
    out: dict[str, str] = {}
    for line in body[header_line_end:body_end].split("\n"):
        m = _KEY_VALUE_LINE.match(line)
        if m and len(m.group(1)) > header_indent:
            out[m.group(2)] = m.group(3)
    return out


def _calc_by_values(body: str) -> list[str]:
    """РасчетРазрешенийПо values: both the inline list [A, B] and the "- A" item list."""
    m = None
    for spelling in key_forms(_CALC_BY_KEY):
        m = re.search(rf"^[ \t]*{re.escape(spelling)}:[ \t]*(.*)$", body, re.M)
        if m is not None:
            break
    if m is None:
        return []
    inline = m.group(1).strip()
    if inline.startswith("["):
        return [v.strip() for v in inline.strip("[]").split(",") if v.strip()]
    bounds = _section_bounds(body, _CALC_BY_KEY)
    if bounds is None:
        return []
    _, header_line_end, body_end = bounds
    return [
        line.strip().lstrip("-").strip()
        for line in body[header_line_end:body_end].split("\n")
        if line.strip().startswith("-")
    ]


def access_info(text: str) -> dict | None:
    """The object's КонтрольДоступа summary, or None if the section is missing.

    {permissions: {right: method}, default: method|None, calc_by: [fields]}. A missing
    section is precisely None, not an empty summary: the platform then applies
    РазрешеноАдминистраторам.
    """
    bounds = _section_bounds(text, _ACCESS_SECTION, top_level=True)
    if bounds is None:
        return None
    _, header_line_end, body_end = bounds
    body = text[header_line_end:body_end]
    permissions = _mapping_in(body, _PERMISSIONS_KEY)
    return {
        "permissions": permissions,
        "default": permissions.get(ACCESS_DEFAULT_RIGHT),
        "calc_by": _calc_by_values(body),
    }


def _access_anchor(text: str) -> int:
    """Insertion offset for the КонтрольДоступа section: before the first data section, else at the end."""
    offsets = [
        m.start()
        for key in _ACCESS_ANCHORS
        for spelling in key_forms(key)
        for m in [re.search(rf"^{re.escape(spelling)}:[ \t]*\r?$", text, re.M)]
        if m
    ]
    return min(offsets) if offsets else len(text)


def _set_mapping_value(text: str, section_offset_end: int, body_end: int, indent: str,
                       key: str, value: str, nl: str) -> tuple[str, int]:
    """Replace a mapping key's value or append the key at the end of the section.

    An existing key is recognized in either spelling and keeps the one it is written in;
    a key being added is written as the caller spelled it.
    Returns (new text, shift of the section end) - the caller recomputes the bounds.
    """
    body = text[section_offset_end:body_end]
    for spelling in key_forms(key):
        m = re.search(rf"^([ \t]*){re.escape(spelling)}:[ \t]*(.*)$", body, re.M)
        if m:
            start = section_offset_end + m.start()
            end = section_offset_end + m.end()
            new_line = f"{m.group(1)}{spelling}: {value}"
            return text[:start] + new_line + text[end:], len(new_line) - (end - start)
    addition = f"{nl}{indent}{key}: {value}"
    return text[:body_end] + addition + text[body_end:], len(addition)


def op_set_access(
    root: Path,
    name: str | None = None,
    yaml_path: Path | None = None,
    *,
    default: str | None = None,
    permissions: dict[str, str] | None = None,
    calc_by: list[str] | None = None,
    reader=None,
) -> ScaffoldResult:
    """Set the object's КонтрольДоступа.Разрешения: pinpoint, validating the kind and method.

    default - the method for the ПоУмолчанию right (the common case); permissions - the
    methods of individual rights ({"Чтение": "РазрешеноВсем"}), including custom ones
    ("ПравоНаX.ИмяПрава"). calc_by sets РасчетРазрешенийПо - it is mandatory for
    РазрешенияВычисляютсяДляКаждогоОбъекта. The operation does NOT write permission
    computation handlers: that is business logic (see the "Самостоятельное формирование
    разрешений и выдача экземпляров ключей" documentation) - a reminder is left in notes.
    """
    wanted: dict[str, str] = dict(permissions or {})
    if default:
        wanted[ACCESS_DEFAULT_RIGHT] = default
    if not wanted and calc_by is None:
        raise ScaffoldError("Нечего менять: задайте default, permissions или calc_by")

    info = object_info(Path(root), name=name, yaml_path=yaml_path)
    kind = info["kind"]
    owner_path = Path(info["path"])
    if kind not in ACCESS_KIND_RIGHTS:
        raise ScaffoldError(
            f"Вид {kind} не поддерживает управление доступом; поддерживают: "
            + ", ".join(sorted(ACCESS_KIND_RIGHTS))
        )

    result = ScaffoldResult()
    known = ACCESS_KIND_RIGHTS[kind]
    for right, method in wanted.items():
        if method not in ACCESS_METHODS:
            raise ScaffoldError(
                f"Недопустимый способ контроля доступа '{method}' у права '{right}'; "
                + "доступны: " + ", ".join(ACCESS_METHODS)
            )
        if method == _PER_OBJECT and kind in _NO_PER_OBJECT_KINDS:
            raise ScaffoldError(f"Вид {kind} не поддерживает {_PER_OBJECT}")
        if right != ACCESS_DEFAULT_RIGHT and "." not in right and right not in known:
            allowed = ", ".join(known) if known else "только " + ACCESS_DEFAULT_RIGHT
            raise ScaffoldError(
                f"У вида {kind} нет права '{right}'; доступны: {allowed} "
                f"(и {ACCESS_DEFAULT_RIGHT}; пользовательское право пишется как ПравоНаX.ИмяПрава)"
            )

    text, nl = _load_for_edit(owner_path, reader)
    current = access_info(text)
    per_object = [r for r, m in wanted.items() if m == _PER_OBJECT]
    if per_object:
        has_calc = bool(calc_by) or bool(current and current["calc_by"])
        if not has_calc:
            raise ScaffoldError(
                f"{_PER_OBJECT} требует {_CALC_BY_KEY} – передайте calc_by "
                "(поля объекта, по которым считаются разрешения)"
            )
    if calc_by is not None and not calc_by:
        raise ScaffoldError(f"{_CALC_BY_KEY} не может быть пустым")

    unchanged = [r for r, m in wanted.items() if current and current["permissions"].get(r) == m]
    if unchanged and len(unchanged) == len(wanted) and calc_by is None:
        result.notes.append(
            "Права уже имеют такие значения: "
            + ", ".join(f"{r}: {wanted[r]}" for r in unchanged)
        )
        return result

    if current is None:
        # The section keys are spelled like the file; the rights and the methods are the
        # platform's own names, which the caller passes and this operation validates.
        lang = yaml_language(text, owner_path.parent)
        lines = [
            f"{spelled_key(_ACCESS_SECTION, lang)}:",
            f"    {spelled_key(_PERMISSIONS_KEY, lang)}:",
        ]
        lines += [f"        {right}: {method}" for right, method in wanted.items()]
        if calc_by:
            lines.append(f"    {spelled_key(_CALC_BY_KEY, lang)}: [{', '.join(calc_by)}]")
        at = _access_anchor(text)
        block = nl.join(lines) + nl
        new_text = text[:at] + block + text[at:]
    else:
        new_text = text
        for right, method in wanted.items():
            new_text = _write_permission(new_text, right, method, nl)
        if calc_by:
            new_text = _write_calc_by(new_text, calc_by, nl)

    result.changes.append(FileChange(owner_path, new_text, created=False))
    was = (current["permissions"] if current else {})
    for right, method in wanted.items():
        before = was.get(right) or (f"нет секции – {_ACCESS_IMPLICIT}" if current is None else "не задано")
        result.notes.append(f"{right}: {before} -> {method}")
    if per_object:
        result.notes.append(
            "Нужны обработчики ВычислитьРазрешенияДоступа и "
            "ВычислитьРазрешенияДоступаДляОбъектов в модуле объекта, иначе доступа не будет"
        )
    elif any(m == "РазрешенияВычисляются" for m in wanted.values()):
        result.notes.append(
            "Нужен обработчик ВычислитьРазрешенияДоступа в модуле объекта, иначе доступа не будет"
        )
    return result


def _access_body_bounds(text: str) -> tuple[int, int]:
    _, header_line_end, body_end = _section_bounds(text, _ACCESS_SECTION, top_level=True)
    return header_line_end, body_end


def _write_permission(text: str, right: str, method: str, nl: str) -> str:
    """Pinpoint-set a right in an existing КонтрольДоступа section."""
    header_line_end, body_end = _access_body_bounds(text)
    body = text[header_line_end:body_end]
    perms = _section_bounds(body, _PERMISSIONS_KEY)
    if perms is None:  # the section exists but Разрешения does not - append the block
        key = spelled_key(_PERMISSIONS_KEY, yaml_language(text))
        addition = f"{nl}    {key}:{nl}        {right}: {method}"
        return text[:body_end] + addition + text[body_end:]
    perm_indent, perm_header_end, perm_body_end = perms
    new_text, _ = _set_mapping_value(
        text, header_line_end + perm_header_end, header_line_end + perm_body_end,
        " " * (perm_indent + 4), right, method, nl,
    )
    return new_text


def _write_calc_by(text: str, calc_by: list[str], nl: str) -> str:
    header_line_end, body_end = _access_body_bounds(text)
    value = f"[{', '.join(calc_by)}]"
    key = spelled_key(_CALC_BY_KEY, yaml_language(text))
    new_text, _ = _set_mapping_value(text, header_line_end, body_end, "    ", key, value, nl)
    return new_text


# --- operation: object rename --------------------------------------------------------------
#
# The rename is textual and contextual, without a full index: the name is replaced only
# where it references the object (values of yaml reference keys, chain roots in bindings
# and code, composite form names), while matching names of attributes, components and
# dynamic list fields are left alone. .xbsl string literals are not edited (UI text),
# comments are (mentions of the object in code documentation).

# Yaml keys whose values carry the object name as a reference to the object or a form.
# Read in either spelling: an English project writes the same keys as Type, Table, Form.
_YAML_REF_KEYS = ("Тип", "Таблица", "ИсточникДанных", "Форма", "ТипФормы")
_PRESENTATION_KEYS = ("Заголовок", "Представление")


@lru_cache(maxsize=1)
def _rename_key_sets() -> tuple[frozenset[str], frozenset[str], frozenset[str]]:
    """(reference keys, presentation keys, name keys) in both spellings."""
    def both(names: tuple[str, ...]) -> frozenset[str]:
        return frozenset(form for name in names for form in key_forms(name))

    return both(_YAML_REF_KEYS), both(_PRESENTATION_KEYS), both(("Имя",))


dataset.register_reset(_rename_key_sets.cache_clear)
_YAML_KEY_LINE = re.compile(rf"^([ \t]*(?:-[ \t]+)?)([{_WORD}]+):([ \t]*)(.*)$")
_IMPORT_LINE = re.compile(r"^[ \t]*импорт[ \t]+\S")


class _Renamer:
    """Object name replacements in text: the identifier and its composite form names.

    The identifier is replaced only in the root position (not after a dot - that is a
    member of another type, not after `@` - that is an annotation). A composite form name
    is `<Имя>Форма` with a capital letter after "Форма" (or exactly `<Имя>Форма`): a
    lowercase letter after "Форма" means an unrelated word like "Форматирование". The card
    list row component is `СтрокаСписка<Имя>`.
    """

    def __init__(self, old: str, new: str):
        self.old, self.new = old, new
        escaped = re.escape(old)
        self._ident = re.compile(rf"(?<![{_WORD}.@]){escaped}(?![{_WORD}])")
        self._composite = re.compile(
            rf"(?<![{_WORD}.]){escaped}(?=Форма(?:[А-ЯЁA-Z][{_WORD}]*)?(?![{_WORD}]))"
        )
        self._row = re.compile(rf"(?<![{_WORD}.])СтрокаСписка{escaped}(?![{_WORD}])")

    def identifier(self, s: str) -> tuple[str, int]:
        return self._ident.subn(self.new, s)

    def composites(self, s: str) -> tuple[str, int]:
        s, n1 = self._composite.subn(self.new, s)
        s, n2 = self._row.subn(f"СтрокаСписка{self.new}", s)
        return s, n1 + n2

    def file_base(self, base: str) -> str:
        """The new file owner name (the part before the first dot) if the file belongs to the object."""
        for sub in (self.composites, self.identifier):
            new_base, n = sub(base)
            if n:
                return new_base
        return base


def _split_strings(line: str) -> list[tuple[str, bool]]:
    """Code line segments: (text, is_string_literal). A quote inside a literal is doubled."""
    parts: list[tuple[str, bool]] = []
    start = 0
    in_str = False
    i, n = 0, len(line)
    while i < n:
        if line[i] == '"':
            if in_str and i + 1 < n and line[i + 1] == '"':
                i += 2
                continue
            if in_str:
                parts.append((line[start : i + 1], True))
                start = i + 1
            else:
                parts.append((line[start:i], False))
                start = i
            in_str = not in_str
        i += 1
    parts.append((line[start:], in_str))
    return parts


def _rename_in_xbsl(text: str, renamer: _Renamer) -> tuple[str, int]:
    """Replacements in a module: identifiers and composite form names outside string literals.

    An `импорт <Подсистема>` line is skipped entirely - it holds a subsystem name, not an
    object name.
    """
    total = 0
    out: list[str] = []
    for line in text.split("\n"):
        if _IMPORT_LINE.match(line):
            out.append(line)
            continue
        pieces: list[str] = []
        for segment, is_string in _split_strings(line):
            if not is_string:
                segment, n1 = renamer.composites(segment)
                segment, n2 = renamer.identifier(segment)
                total += n1 + n2
            pieces.append(segment)
        out.append("".join(pieces))
    return "\n".join(out), total


def _swap_presentation(value: str, old_values: set[str], new_value: str) -> tuple[str, bool]:
    """Replace a Заголовок/Представление value preserving quotes and trailing spaces."""
    raw = value.rstrip()
    tail = value[len(raw):]
    quote = raw[:1] if raw[:1] in "\"'" and len(raw) >= 2 and raw.endswith(raw[:1]) else ""
    core = raw[1:-1] if quote else raw
    if core not in old_values:
        return value, False
    return f"{quote}{new_value}{quote}{tail}", True


def _rename_in_yaml(
    text: str,
    renamer: _Renamer,
    *,
    own: bool = False,
    presentations: tuple[set[str], str] | None = None,
) -> tuple[str, int]:
    """Replacements in yaml: reference keys, bindings (`=...`), composite form names.

    own - this is the yaml of the object itself or of its form: additionally the top-level
    `Имя:` and the Заголовок/Представление values matching the old name/presentation are
    edited.
    """
    ref_keys, presentation_keys, name_keys = _rename_key_sets()
    total = 0
    out: list[str] = []
    for line in text.split("\n"):
        line, n = renamer.composites(line)
        total += n
        m = _YAML_KEY_LINE.match(line)
        if m:
            prefix, key, sep, value = m.groups()
            if key in ref_keys:
                value, n = renamer.identifier(value)
                total += n
                line = f"{prefix}{key}:{sep}{value}"
                out.append(line)
                continue
            if own and key in name_keys and prefix == "" and value.strip() == renamer.old:
                out.append(f"{prefix}{key}:{sep}{value.replace(renamer.old, renamer.new)}")
                total += 1
                continue
            if own and presentations and key in presentation_keys:
                value, swapped = _swap_presentation(value, *presentations)
                if swapped:
                    total += 1
                    out.append(f"{prefix}{key}:{sep}{value}")
                    continue
        eq = line.find("=")
        if eq != -1:
            replaced, n = renamer.identifier(line[eq:])
            if n:
                total += n
                line = line[:eq] + replaced
        out.append(line)
    return "\n".join(out), total


def op_rename_object(
    root: Path,
    old_name: str,
    new_name: str,
    *,
    new_presentation: str | None = None,
    old_presentation: str | None = None,
    yaml_path: Path | None = None,
    reader=None,
) -> ScaffoldResult:
    """Rename a configuration object and update references to it across all sources.

    The renamed files are the object's (yaml, the `<Имя>.xbsl` / `<Имя>.<Часть>.xbsl`
    modules), its forms' (`<Имя>Форма*`) and the list row component's
    (`СтрокаСписка<Имя>`). Edited in texts: values of yaml reference keys
    (Тип/Таблица/ИсточникДанных/Форма/ТипФормы), `=...` bindings, .xbsl code (except
    string literals) and composite form names; in the yaml of the object itself and its
    forms - also `Имя:` and Заголовок/Представление (the old presentation is given by
    old_presentation, the new one by new_presentation, defaulting to the new name).

    yaml_path resolves the ambiguity when the project has several objects named old_name.
    Also works for a КомпонентИнтерфейса (a form rename: the owner's `Форма:` is updated).
    """
    root = Path(root)
    if not root.is_dir():
        raise ScaffoldError(f"Корень проекта не найден: {root}")
    old_name = _check_identifier(old_name, "объекта")
    new_name = _check_identifier(new_name, "объекта")
    if old_name == new_name:
        raise ScaffoldError("Старое и новое имена совпадают")

    if yaml_path is not None:
        yaml_path = Path(yaml_path)
        if not yaml_path.is_file():
            raise ScaffoldError(f"Файл не найден: {yaml_path}")
        text = (reader or _read)(yaml_path)
        kind = element_kind(text)
        if kind is None:
            raise ScaffoldError(f"В {yaml_path} нет ВидЭлемента – это не объект конфигурации")
        file_name = element_name(text, yaml_path.stem)
        if file_name != old_name:
            raise ScaffoldError(f"В {yaml_path.name} объект называется '{file_name}', а не '{old_name}'")
        subsystem, namespace = _namespace_of(yaml_path, root)
        hit = ObjectHit(kind, file_name, yaml_path, subsystem, namespace, text)
    else:
        hit = find_object(root, old_name)

    namesakes = []
    for other_path, _kind, name, _text in _iter_objects(root):
        if name == new_name:
            raise ScaffoldError(f"Имя '{new_name}' уже занято: {other_path}")
        if name == old_name and other_path.resolve() != hit.path.resolve():
            namesakes.append(other_path)

    renamer = _Renamer(old_name, new_name)
    result = ScaffoldResult()
    if namesakes:
        listed = "; ".join(str(p) for p in namesakes)
        result.notes.append(
            f"В проекте остаются тёзки '{old_name}' ({listed}): ссылки по имени "
            "заменяются во всём проекте – проверьте затронутые файлы"
        )

    # File renames: the file owner is the name part before the first dot.
    directory = hit.path.parent
    for path in sorted(directory.iterdir()):
        if not path.is_file() or path.suffix not in (".yaml", ".xbsl"):
            continue
        base = path.name.split(".", 1)[0]
        new_base = renamer.file_base(base)
        if new_base == base:
            continue
        rename = FileRename(path, path.with_name(new_base + path.name[len(base):]))
        if _rename_clashes(rename):
            raise ScaffoldError(f"Файл уже существует: {rename.new_path}")
        result.renames.append(rename)
    renamed = {r.old_path.resolve(): r.new_path for r in result.renames}
    own_yaml = {
        r.old_path.resolve() for r in result.renames if r.old_path.suffix == ".yaml"
    }

    presentations = (
        {old_name} | ({old_presentation} if old_presentation else set()),
        new_presentation or new_name,
    )

    def rel(path: Path) -> str:
        try:
            return path.resolve().relative_to(root.resolve()).as_posix()
        except ValueError:
            return str(path)

    changed_files = 0
    total = 0
    for path in engine.find_sources(root, "*.yaml") + engine.find_sources(root, "*.xbsl"):
        text = (reader or _read)(path)
        if path.suffix == ".yaml":
            new_text, count = _rename_in_yaml(
                text, renamer,
                own=path.resolve() in own_yaml,
                presentations=presentations,
            )
        else:
            new_text, count = _rename_in_xbsl(text, renamer)
        if new_text == text:
            continue
        target = renamed.get(path.resolve(), path)
        result.changes.append(FileChange(target, new_text, created=False))
        result.notes.append(f"{rel(path)}: замен – {count}")
        changed_files += 1
        total += count

    if not result.renames and not result.changes:
        raise ScaffoldError(f"Ссылок на '{old_name}' не найдено – нечего переименовывать")
    result.notes.insert(0, f"Файлов переименовано: {len(result.renames)}, "
                           f"правок: {changed_files} файлов / {total} замен")
    if hit.kind == "HttpСервис" and re.search(r"^КорневойUrl:", hit.text, re.M):
        result.notes.append(
            "КорневойUrl не изменён (публичный контракт сервиса) – при необходимости поправьте вручную"
        )
    if any(_one_file_under_both_names(r) for r in result.renames):
        # The files are renamed here, but what the version control system makes of it is
        # beyond the tool's reach, and it differs by alphabet: git on a case-insensitive
        # filesystem (core.ignorecase=true) folds ASCII letters only, so a Latin name stays
        # in the index under the old spelling while a Cyrillic one is recorded as a delete
        # plus an add - and then every other clone on such a filesystem stops at
        # "untracked working tree files would be overwritten by merge".
        result.notes.append(
            "Имена отличаются только регистром: на регистронезависимой файловой системе "
            "(Windows, macOS) файлы переименованы в два шага через временное имя. "
            "Проверьте, что система контроля версий увидела новые имена: git сличает "
            "имена без учёта регистра только для латиницы, поэтому латинское "
            "переименование он не заметит – зафиксируйте его явно (git mv <старое> "
            "<новое>), а кириллическое покажет как удаление и добавление, и тогда в "
            "остальных клонах на такой же файловой системе git pull остановится с "
            "\"untracked working tree files would be overwritten by merge\" – там перед "
            "обновлением надо удалить файл со старым именем"
        )
    return result
