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
"""

from __future__ import annotations

import re
from collections import defaultdict
from collections.abc import Iterable

from xbsl import i18n
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
        "en": "Ид is not a UUID",
    },
    "yaml/id-uuid.not-uuid": {
        "ru": "Ид '{value}' не является UUID (формат 8-4-4-4-12).",
        "en": "Ид '{value}' is not a UUID (the 8-4-4-4-12 format).",
    },
    "yaml/id-required.title": {
        "ru": "У объекта нет Ид",
        "en": "The object has no Ид",
    },
    "yaml/id-required.missing": {
        "ru": "У объекта не задан Ид верхнего уровня.",
        "en": "The object has no top-level Ид.",
    },
    "yaml/standard-field-length.title": {
        "ru": "Длина стандартного реквизита сверх лимита",
        "en": "A standard field longer than the limit",
    },
    "yaml/standard-field-length.over": {
        "ru": "Длина стандартного реквизита '{field}' – {value}, лимит платформы – {limit}. "
              "Применение отвергнет реквизит, он выпадет из объекта, и компиляция посыплется "
              "по всему проекту ошибками \"Поле {field} не найдено\".",
        "en": "The standard field '{field}' has Длина {value} against the platform limit of "
              "{limit}. Apply rejects the field, it drops out of the object, and the "
              "compilation then fails project-wide with \"field {field} not found\".",
    },
    "yaml/name-matches-file.title": {
        "ru": "Имя не совпадает с именем файла",
        "en": "Имя does not match the file name",
    },
    "yaml/name-matches-file.mismatch": {
        "ru": "Имя '{name}' не совпадает с именем файла '{stem}'.",
        "en": "Имя '{name}' does not match the file name '{stem}'.",
    },
    "yaml/id-unique.title": {
        "ru": "Дубли Ид в проекте",
        "en": "Duplicate Ид in the project",
    },
    "yaml/id-unique.duplicate": {
        "ru": "Дублирующийся Ид '{value}' (также: {others}).",
        "en": "Duplicate Ид '{value}' (also: {others}).",
    },
}
i18n.register(MESSAGES)

_UUID_RE = re.compile(r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$")
_ID_LINE_RE = re.compile(r"(?m)^[ \t]*Ид:[ \t]*(\S+)")
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
# Lines of a field entry: the name and the Длина value (the position of a finding).
_FIELD_NAME_RE = re.compile(r"^[ \t]*(?:-[ \t]+)?Имя:[ \t]*['\"]?([^\r\n#'\"]*?)['\"]?[ \t]*$")
_LENGTH_RE = re.compile(r"^([ \t]*(?:-[ \t]+)?)Длина:[ \t]*(\d+)[ \t]*$")


# libyaml (CSafeLoader) parses 5-10x faster than the pure-Python loader and dominates the
# whole-project run time; the pure loader stays as the fallback for builds without it.
_LOADER = getattr(yaml, "CSafeLoader", yaml.SafeLoader)


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


def _is_object(data) -> bool:
    """Whether the file describes a metadata object (has ВидЭлемента)."""
    return isinstance(data, dict) and data.get("ВидЭлемента") is not None


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
    """{key: (key node, value node)} of a mapping, scalar keys only."""
    return {
        k.value: (k, v)
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
    if source.kind != "yaml":
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
    if "Ид" not in data:
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
    fields = data.get("Реквизиты")
    if not isinstance(fields, list):
        return
    for item in fields:
        if not isinstance(item, dict):
            continue
        name = item.get("Имя")
        limit = _STANDARD_LENGTH_LIMITS.get(name)
        length = item.get("Длина")
        if limit is None or not isinstance(length, int) or isinstance(length, bool):
            continue
        if name == "Код" and item.get("Тип") not in (None, "Строка"):
            continue  # a numeric Код counts digits - a different limit, not measured
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
    name = data.get("Имя")
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


def _id_unique_mapper(source: SourceFile) -> list[tuple[str, int, int]] | None:
    """The map phase: every Ид value of the file with its position."""
    if source.kind != "yaml":
        return None
    ids = _id_lines(source)
    return ids or None


@rule(
    "yaml/id-unique", "yaml/id-unique.title", "A",
    scope="project", severity=Severity.ERROR, mapper=_id_unique_mapper,
)
def yaml_id_unique(facts: dict[str, list[tuple[str, int, int]]]) -> Iterable[Diagnostic]:
    occ: dict[str, list[tuple[str, int, int]]] = defaultdict(list)
    for rel, ids in facts.items():
        for value, line, col in ids:
            occ[value].append((rel, line, col))
    for value, places in occ.items():
        if len(places) < 2:
            continue
        for i, (rel, line, col) in enumerate(places):
            others = [f"{orel}:{ol}" for j, (orel, ol, _oc) in enumerate(places) if j != i]
            yield Diagnostic(
                rel, line, col, "yaml/id-unique", Severity.ERROR,
                i18n.t("yaml/id-unique.duplicate", value=value, others=", ".join(others[:3])),
            )
