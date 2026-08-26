"""Tier A: checks on the YAML descriptions of elements.

- yaml/valid            – the YAML parses correctly;
- yaml/id-uuid          – every Ид (including the nested attributes) is a valid UUID;
- yaml/id-unique        – Ид values are unique within the project (a cross-file rule);
- yaml/id-required      – an object (has ВидЭлемента) carries a top-level Ид;
- yaml/name-matches-file – the object Имя matches the file name;
- yaml/standard-field-length – Наименование/Код stay within the platform limits.

Structural files (Проект/Подсистема/Ресурсы) are recognised by the absence of ВидЭлемента and
are exempt from the Имя/required-Ид rules; the Ид checks (format/uniqueness) apply to every Ид
in every file.

A translation dictionary is not a description at all and no rule of this module judges it - see
`is_translation_dictionary`.
"""

from __future__ import annotations

import re
from collections import defaultdict
from collections.abc import Iterable

from xbsl import i18n, metamodel, uischema
from xbsl.diagnostics import Diagnostic, Severity
from xbsl.engine import SourceFile, rule
from xbsl.lexer import linemap

try:
    import yaml

    _HAVE_YAML = True
except ImportError:  # pragma: no cover
    _HAVE_YAML = False

MESSAGES = {
    "yaml/valid.title": {
        "ru": "YAML не парсится",
        "en": "YAML does not parse",
    },
    "yaml/valid.default-problem": {
        "ru": "ошибка синтаксиса YAML",
        "en": "YAML syntax error",
    },
    "yaml/valid.error": {
        "ru": "YAML: {problem}.",
        "en": "YAML: {problem}.",
    },
    "yaml/id-uuid.title": {
        "ru": "Ид не является UUID",
        "en": "{n[Ид]} is not a UUID",
    },
    "yaml/id-uuid.not-uuid": {
        "ru": "Ид '{value}' не является UUID (формат 8-4-4-4-12).",
        "en": "{n[Ид]} '{value}' is not a UUID (the 8-4-4-4-12 format).",
    },
    "yaml/id-required.title": {
        "ru": "У объекта нет Ид",
        "en": "The object has no {n[Ид]}",
    },
    "yaml/id-required.missing": {
        "ru": "У объекта не задан Ид верхнего уровня.",
        "en": "The object has no top-level {n[Ид]}.",
    },
    "yaml/standard-field-length.title": {
        "ru": "Длина стандартного реквизита сверх лимита",
        "en": "A standard field longer than the limit",
    },
    "yaml/standard-field-length.over": {
        "ru": "Длина стандартного реквизита '{field}' – {value}, лимит платформы – {limit}. "
              "Применение отвергнет реквизит, он выпадет из объекта, и компиляция посыплется "
              "по всему проекту ошибками \"Поле {field} не найдено\".",
        "en": "The standard field '{field}' has {n[Длина]} {value} against the platform limit of "
              "{limit}. Apply rejects the field, it drops out of the object, and the "
              "compilation then fails project-wide with \"field {field} not found\".",
    },
    "yaml/name-matches-file.title": {
        "ru": "Имя не совпадает с именем файла",
        "en": "{n[Имя]} does not match the file name",
    },
    "yaml/name-matches-file.mismatch": {
        "ru": "Имя '{name}' не совпадает с именем файла '{stem}'.",
        "en": "{n[Имя]} '{name}' does not match the file name '{stem}'.",
    },
    "yaml/id-unique.title": {
        "ru": "Дубли Ид в проекте",
        "en": "Duplicate {n[Ид]} in the project",
    },
    "yaml/id-unique.duplicate": {
        "ru": "Дублирующийся Ид '{value}' (также: {others}).",
        "en": "Duplicate {n[Ид]} '{value}' (also: {others}).",
    },
}
i18n.register(MESSAGES)

_UUID_RE = re.compile(r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$")
#: An `Ид:` line in either spelling - the platform reads the English key just as well.
_ID_LINE_RE = re.compile(r"(?m)^[ \t]*(?:Ид|Id):[ \t]*(\S+)")
# A line with the `Имя:` key: the indent (a list-item dash counts as indent), the value with or
# without quotes, an optional trailing comment (per YAML it is not part of the value); `\r?` lets
# CRLF files match (`$` anchors before `\n`). Groups: 1 – indent, 2 – quote, 3 – value.
# Shared by the naming rules and the indexer.
_NAME_LINE_RE = re.compile(
    r"(?m)^([ \t]*(?:-[ \t]+)?)Имя:[ \t]*(['\"]?)([^\r\n#]*?)\2[ \t]*(?:#.*)?\r?$"
)

# The platform limits on the length of the standard fields, both verified by the compiler on a
# probe: 51 and 401 are rejected ('The length of attribute "Код" must fall between zero and 50',
# same wording for Наименование and 400), while 50 and 400 pass. The Наименование limit is
# documented as well ("Свойства элемента проекта вида Справочник"); the Код one is not, so it
# rests on the probe. Длина belongs to the standard fields only - a developer's field carries
# МаксимальнаяДлина instead, so the name lookup cannot collide with an ordinary field.
_STANDARD_LENGTH_LIMITS = {"Наименование": 400, "Код": 50}
#: The same limits under the English spellings of those field names - a translated project
#: writes `Name`/`Code`, and read by the Russian names alone the rule saw nothing there at all.
_STANDARD_LENGTH_LIMITS_EN = {"Name": 400, "Code": 50}
#: The section and the keys of a field entry, in either spelling.
_ATTRIBUTE_SECTIONS = ("Реквизиты", "Attributes")
_STRING_TYPES = (None, "Строка", "String")
# Lines of a field entry: the name and the length value (the position of a finding).
_FIELD_NAME_RE = re.compile(
    r"^[ \t]*(?:-[ \t]+)?(?:Имя|Name):[ \t]*['\"]?([^\r\n#'\"]*?)['\"]?[ \t]*$"
)
_LENGTH_RE = re.compile(r"^([ \t]*(?:-[ \t]+)?)(?:Длина|Length):[ \t]*(\d+)[ \t]*$")


# libyaml (CSafeLoader) parses 5-10x faster than the pure-Python loader and dominates the
# whole-project run time; the pure loader stays as the fallback for builds without it.
_BASE_LOADER = getattr(yaml, "CSafeLoader", yaml.SafeLoader)

#: The spellings of a boolean the platform's serializer writes. YAML 1.1 - which is what PyYAML
#: implements - also reads `Yes`, `No`, `On`, `Off`, `y` and `n` as booleans, and those are
#: perfectly ordinary NAMES in 1C:Element: an enumeration item spelled `Name: No` came back as
#: the value False, so the item vanished from the declaration and every reference to it was
#: reported unknown, while the compiler accepted the very same file. The platform types a scalar
#: by its schema (`Multiline:` is a flag, `Name:` is a name), not by YAML 1.1 resolution, so
#: narrowing the implicit resolver to the two words it actually writes is what matches it - the
#: YAML 1.2 core schema does the same.
_BOOL_SPELLINGS = re.compile(r"^(?:true|True|TRUE|false|False|FALSE)$")


class _Loader(_BASE_LOADER):  # type: ignore[misc, valid-type]
    """The base loader with the YAML 1.1 boolean words that are also names left as strings."""


_Loader.yaml_implicit_resolvers = {
    first: [(tag, regexp) for tag, regexp in pairs if tag != "tag:yaml.org,2002:bool"]
    for first, pairs in _BASE_LOADER.yaml_implicit_resolvers.items()
}
_Loader.add_implicit_resolver("tag:yaml.org,2002:bool", _BOOL_SPELLINGS, list("tTfF"))

_LOADER = _Loader


def _parsed(source: SourceFile):
    """The parsed YAML (or None) and the parse error (or None), cached.

    The platform parser is more lenient than PyYAML: real shipped sources carry `\\'`
    inside double-quoted scalars (an HTML/JS onclick in real code), which the platform
    accepts as a plain apostrophe while PyYAML rejects the escape. The retry below
    only runs when the strict parse has already failed, so no valid document can be
    misread by it.
    """
    if "yaml" not in source.cache:
        data = None
        err = None
        try:
            data = yaml.load(source.text, Loader=_LOADER)
        except yaml.YAMLError as exc:  # noqa: BLE001
            err = exc
            if "unknown escape character" in str(exc):
                try:
                    data = yaml.load(source.text.replace("\\'", "'"), Loader=_LOADER)
                    err = None
                except yaml.YAMLError:
                    data = None
        source.cache["yaml"] = data
        source.cache["yaml_error"] = err
    return source.cache["yaml"], source.cache["yaml_error"]


def _id_lines(source: SourceFile) -> list[tuple[str, int, int]]:
    """List of (Ид value, line, column) for every 'Ид:' line in the file."""
    key = "id_lines"
    if key not in source.cache:
        lm = linemap(source)
        out: list[tuple[str, int, int]] = []
        for m in _ID_LINE_RE.finditer(source.text):
            line, col = lm.linecol(m.start(1))
            out.append((m.group(1).strip(), line, col))
        source.cache[key] = out
    return source.cache[key]


# The kind key in both spellings: the platform reads the sources either way (proven against the
# compiler - a catalog spelled `ElementKind: Catalog` applies), and a rule that knows only the
# Russian one skips such a file WHOLE, so not even a typo in it is reported.
_KIND_KEYS = ("ВидЭлемента", "ElementKind")


def object_kind(data) -> str | None:
    """The element kind of a parsed yaml, as the metamodel names it, or None.

    Reads either spelling of the key and returns the kind in the metamodel's own (Russian)
    spelling, so every caller keeps comparing against one name.
    """
    if not isinstance(data, dict):
        return None
    for key in _KIND_KEYS:
        value = data.get(key)
        if isinstance(value, str) and value:
            return metamodel.canonical_kind(value)
    return None


def _is_object(data) -> bool:
    """Whether the file describes a metadata object (it carries an element kind)."""
    return object_kind(data) is not None


#: The planes a translation dictionary carries (xbsl/translation/dictionary.py).
_DICTIONARY_SECTIONS = ("tokens", "phrases", "literals", "terms")

#: The cheap gate before the parse: the dictionary format writes its version at the top level,
#: and the loader takes only the integer 1 - a quoted value is already rejected there.
_DICTIONARY_HEAD_RE = re.compile(r"(?m)^version:[ \t]*\d")


def is_translation_dictionary(source: SourceFile) -> bool:
    """Whether the file is a translation dictionary rather than a description of an element.

    A dictionary (`xbsl-translation`, see xbsl/translation/dictionary.py) writes platform names
    as ordinary map KEYS: the pair `Ид: Id` is the translation of a name, not the id of an
    object, and a schema rule reading that line judges a thing that is not there. The other
    rules of this module are already silent on such a file - it carries no element kind - so
    the gate is needed by the id checks, which read every file.

    Recognised by its own content and not by the path discovery of
    `conventions/missing-translation`: these are file-scope rules the editor runs on every
    keystroke, a buffer checked through `--stdin` has no real path, and walking up the tree per
    file is the wrong price for them.
    """
    key = "translation_dictionary"
    if key not in source.cache:
        verdict = False
        if _HAVE_YAML and source.kind == "yaml" and _DICTIONARY_HEAD_RE.search(source.text):
            data, err = _parsed(source)
            verdict = (
                err is None
                and isinstance(data, dict)
                and object_kind(data) is None
                and "version" in data
                and ("language" in data or any(s in data for s in _DICTIONARY_SECTIONS))
            )
        source.cache[key] = verdict
    return source.cache[key]


def value_of(data, key: str, kind: str | None = None):
    """The value of a property named the metamodel's way, whichever spelling the file uses.

    `Ид` and `Id` are the same key of the same object, and a rule that asks for one must see the
    other; the pair comes from the metamodel record of the KIND (globally the map is ambiguous -
    `Name` is both `Имя` and `Наименование`). Without a kind, or without data, only the name as
    given is tried.
    """
    if not isinstance(data, dict):
        return None
    if key in data:
        return data[key]
    kind = kind or object_kind(data)
    english = (metamodel.properties(kind).get(key) or {}).get("en") if kind else None
    # No kind (a collection item, a fragment): the pair is taken globally, and only when the
    # whole metamodel agrees on one English spelling.
    english = english or metamodel.english_name(key) or uischema.english_property(key)
    return data.get(english) if english else None


def _composed(source: SourceFile):
    """The composed node graph of the file (line/column marks kept), or None.

    libyaml composes the same graph as the pure-python loader - tags, values and
    line/column marks are identical (verified node by node); the differences are
    `Mark.buffer` (the snippet text, which nothing here reads) and the style of a
    plain scalar (None vs "", both falsy - the consumers only test for block and
    quote styles). Cached per source: several rules walk the same graph.
    """
    key = "yaml_composed"
    if key not in source.cache:
        try:
            source.cache[key] = yaml.compose(source.text, Loader=_LOADER)
        except yaml.YAMLError:
            source.cache[key] = None
    return source.cache[key]


def _mapping_nodes(root):
    """Every mapping of a composed node graph, in document order.

    Positions taken from these nodes tell apart equal values in different nodes, which a
    text search for the value cannot do (PyYAML counts CRLF line breaks correctly).
    """
    stack = [root]
    seen: set[int] = set()
    while stack:
        node = stack.pop()
        if id(node) in seen:  # an anchor may alias the same node twice
            continue
        seen.add(id(node))
        if isinstance(node, yaml.MappingNode):
            yield node
            stack.extend(v for _k, v in reversed(node.value))
        elif isinstance(node, yaml.SequenceNode):
            stack.extend(reversed(node.value))


def _scalar_entries(mapping) -> dict:
    """{key: (key node, value node)} of a mapping, scalar keys only, keyed CANONICALLY.

    A form may be written in English (`Layout:` for `Компоновка:`) - the platform reads it either
    way - so the rules compare against one name; the spelling the author used stays available on
    the key node itself.
    """
    return {
        uischema.canonical_property(k.value): (k, v)
        for k, v in mapping.value
        if isinstance(k, yaml.ScalarNode)
    }


@rule("yaml/valid", "yaml/valid.title", "A", severity=Severity.ERROR)
def yaml_valid(source: SourceFile) -> Iterable[Diagnostic]:
    if not _HAVE_YAML or source.kind != "yaml":
        return
    _data, err = _parsed(source)
    if err is not None:
        mark = getattr(err, "problem_mark", None)
        line = mark.line + 1 if mark else 1
        col = mark.column + 1 if mark else 1
        problem = getattr(err, "problem", None) or i18n.t("yaml/valid.default-problem")
        yield Diagnostic(
            source.rel, line, col, "yaml/valid", Severity.ERROR,
            i18n.t("yaml/valid.error", problem=problem),
        )


@rule("yaml/id-uuid", "yaml/id-uuid.title", "A", severity=Severity.ERROR)
def yaml_id_uuid(source: SourceFile) -> Iterable[Diagnostic]:
    if source.kind != "yaml" or is_translation_dictionary(source):
        return
    for value, line, col in _id_lines(source):
        if not _UUID_RE.match(value):
            yield Diagnostic(
                source.rel, line, col, "yaml/id-uuid", Severity.ERROR,
                i18n.t("yaml/id-uuid.not-uuid", value=value),
            )


@rule("yaml/id-required", "yaml/id-required.title", "A", severity=Severity.WARNING)
def yaml_id_required(source: SourceFile) -> Iterable[Diagnostic]:
    if not _HAVE_YAML or source.kind != "yaml":
        return
    data, err = _parsed(source)
    if err is not None or not _is_object(data):
        return
    if value_of(data, "Ид") is None:
        yield Diagnostic(
            source.rel, 1, 1, "yaml/id-required", Severity.WARNING,
            i18n.t("yaml/id-required.missing"),
        )


@rule(
    "yaml/standard-field-length", "yaml/standard-field-length.title", "A",
    severity=Severity.ERROR,
)
def yaml_standard_field_length(source: SourceFile) -> Iterable[Diagnostic]:
    if not _HAVE_YAML or source.kind != "yaml":
        return
    data, err = _parsed(source)
    if err is not None or not _is_object(data):
        return
    # The spelling is taken from the FILE, not from a global map: `Name` is the English
    # spelling of the standard field here and an ordinary developer name elsewhere, and the
    # section key is what says which language this file speaks.
    english = "Реквизиты" not in data
    limits = _STANDARD_LENGTH_LIMITS_EN if english else _STANDARD_LENGTH_LIMITS
    code_field = "Code" if english else "Код"
    fields = value_of(data, "Реквизиты")
    if not isinstance(fields, list):
        return
    for item in fields:
        if not isinstance(item, dict):
            continue
        name = value_of(item, "Имя")
        limit = limits.get(name)
        length = value_of(item, "Длина")
        if limit is None or not isinstance(length, int) or isinstance(length, bool):
            continue
        if name == code_field and value_of(item, "Тип") not in _STRING_TYPES:
            continue  # a numeric code counts digits - a different limit, not measured
        if length <= limit:
            continue
        line, col = _length_position(source, name, length)
        yield Diagnostic(
            source.rel, line, col, "yaml/standard-field-length", Severity.ERROR,
            i18n.t("yaml/standard-field-length.over", field=name, value=length, limit=limit),
        )


def _length_position(source: SourceFile, field: str, length: int) -> tuple[int, int]:
    """The `Длина:` line of the given standard field, or the file start when unmatched.

    The value is known from the parsed document; the scan only locates it, so an exotic
    layout (a flow-style mapping) costs a position, never a false finding.
    """
    current: str | None = None
    for number, text in enumerate(source.text.splitlines(), 1):
        name = _FIELD_NAME_RE.match(text)
        if name:
            current = name.group(1)
            continue
        value = _LENGTH_RE.match(text)
        if value and current == field and int(value.group(2)) == length:
            return number, len(value.group(1)) + 1
    return 1, 1


@rule("yaml/name-matches-file", "yaml/name-matches-file.title", "A", severity=Severity.WARNING)
def yaml_name_matches_file(source: SourceFile) -> Iterable[Diagnostic]:
    if not _HAVE_YAML or source.kind != "yaml":
        return
    data, err = _parsed(source)
    if err is not None or not _is_object(data):
        return
    name = value_of(data, "Имя")
    stem = source.path.stem
    if isinstance(name, str) and name != stem:
        m = _NAME_LINE_RE.search(source.text)
        line, col = (1, 1)
        if m:
            line, col = linemap(source).linecol(m.start(3))
        yield Diagnostic(
            source.rel, line, col, "yaml/name-matches-file", Severity.WARNING,
            i18n.t("yaml/name-matches-file.mismatch", name=name, stem=stem),
        )


#: The id of the OBJECT itself - the key stands at the start of the line, with no indent.
_TOP_ID_RE = re.compile(r"(?m)^(?:Ид|Id):[ \t]*(\S+)")


def _id_unique_mapper(source: SourceFile) -> dict | None:
    """The map phase: the ids of the file, the object's own told from the nested ones.

    An id is unique WITHIN ITS OWNER, not across the project: the published assembly of the
    platform's own demo project gives two different catalogs an attribute with the very same id,
    and the build accepts it. So the ids of items are compared inside the file, and only the
    object's own id is compared project-wide - two objects sharing one identity is what a copied
    file really breaks.
    """
    if source.kind != "yaml":
        return None
    ids = _id_lines(source)
    if not ids:
        return None
    top = {m.group(1).strip() for m in _TOP_ID_RE.finditer(source.text)}
    return {
        "top": [item for item in ids if item[0] in top],
        "nested": [item for item in ids if item[0] not in top],
    }


@rule(
    "yaml/id-unique", "yaml/id-unique.title", "A",
    scope="project", severity=Severity.ERROR, mapper=_id_unique_mapper,
)
def yaml_id_unique(facts: dict[str, dict]) -> Iterable[Diagnostic]:
    occ: dict[str, list[tuple[str, int, int]]] = defaultdict(list)
    for rel, fact in facts.items():
        for value, line, col in fact["top"]:  # objects share the whole project
            occ[value].append((rel, line, col))
        by_file: dict[str, list[tuple[str, int, int]]] = defaultdict(list)
        for value, line, col in fact["nested"]:  # items share their owner alone
            by_file[value].append((rel, line, col))
        for value, places in by_file.items():
            if len(places) > 1:
                occ[value].extend(places)
    for value, places in occ.items():
        if len(places) < 2:
            continue
        for i, (rel, line, col) in enumerate(places):
            others = [f"{orel}:{ol}" for j, (orel, ol, _oc) in enumerate(places) if j != i]
            yield Diagnostic(
                rel, line, col, "yaml/id-unique", Severity.ERROR,
                i18n.t("yaml/id-unique.duplicate", value=value, others=", ".join(others[:3])),
            )
