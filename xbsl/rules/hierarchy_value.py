"""`yaml/hierarchy-bare-value`: a bare mode word in the hierarchy property of a dynamic list.

`UsedHierarchy` of a dynamic list takes `Auto`, a `HierarchyMode` or a string - the name of a
hierarchy of the main table. A mode written as a bare word - `Disabled`, `Default`, `Auto` - is
none of the three to the server: the apply stops with "the type of the value is not specified"
at the line of the property, and the project is rolled back. A probe on a live server showed it
over a catalog with a hierarchy and over one without. A quoted word or any other word is read
as the name of a hierarchy and applies, and so does the typed node the examples of the platform
write, `{Type: HierarchyMode, Value: Disabled}`; a word qualified with the enumeration is read
as a name too, so it is no cure.

The fix writes the typed node for a mode (in the language of the file) and takes the line out
for `Auto`, which is what an unwritten property means. A property written inside a flow
mapping keeps the finding without a fix.

`yaml/auto-bare-value`: the same refusal is not particular to the hierarchy. Any property whose
type is the union of `Auto` and a string reads a bare `Auto` as neither: a live apply answered
"the type of the value is not specified" for the caption of a button (a component property of
the ui schema) and for three members of a dynamic list - the presentation of a filter group,
of a filter item and the ascending sort presentation of a field's automatic filter. The rule
walks the markup with types: a node is typed by its own `Type` (the head of the generic), or by
the member type its parent declares for its key - a component's property from the ui schema,
any other type's member from the type catalog; the source of a list takes the first generic
argument of the list (`Table<DynamicList>`), and a property's default value the type the
property declares. Judged is a property whose union is exactly `Auto` and `String` - a union
with anything else is another rule's (the hierarchy above) or nobody's business. There is no
fix: whether the author meant the default or the word as text is not in the file.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from functools import lru_cache

from xbsl import dataset, i18n, terms, uischema
from xbsl.diagnostics import Diagnostic, Severity, TextEdit
from xbsl.engine import SourceFile, rule
from xbsl.rules.yaml_schema import _composed, _HAVE_YAML, _mapping_nodes
from xbsl.rules.yaml_types import _key_spellings

if _HAVE_YAML:
    import yaml

MESSAGES = {
    "yaml/hierarchy-bare-value.title": {
        "ru": "Голое слово режима в иерархии динамического списка",
        "en": "A bare mode word in the hierarchy of a dynamic list",
    },
    "yaml/hierarchy-bare-value.mode": {
        "ru": "{n[ИспользуемаяИерархия]}: '{word}' голым словом сборка не применяет – сервер "
              "отвечает \"Не указан тип значения\". Запишите режим узлом с типом: {typed}.",
        "en": "{n[ИспользуемаяИерархия]}: a bare '{word}' fails the apply - the server answers "
              "that the type of the value is not specified. Write the mode as a typed node: "
              "{typed}.",
    },
    "yaml/hierarchy-bare-value.auto": {
        "ru": "{n[ИспользуемаяИерархия]}: '{word}' голым словом сборка не применяет – сервер "
              "отвечает \"Не указан тип значения\". {word} – умолчание свойства: уберите строку.",
        "en": "{n[ИспользуемаяИерархия]}: a bare '{word}' fails the apply - the server answers "
              "that the type of the value is not specified. {word} is what the property means "
              "unwritten: take the line out.",
    },
    "yaml/auto-bare-value.title": {
        "ru": "Голое Авто в свойстве типа Авто|Строка",
        "en": "A bare Auto in a property typed Auto|String",
    },
    "yaml/auto-bare-value.found": {
        "ru": "{key} ({owner}): '{word}' голым словом сборка не применяет – свойство принимает и "
              "{n[Авто]}, и строку, и сервер отвечает \"Не указан тип значения\". Уберите строку, "
              "если нужно значение по умолчанию, или возьмите слово в кавычки, если это текст.",
        "en": "{key} ({owner}): a bare '{word}' fails the apply - the property takes both "
              "{n[Авто]} and a string, and the server answers that the type of the value is not "
              "specified. Take the line out for the default value, or quote the word if it is "
              "text.",
    },
}
i18n.register(MESSAGES)

_PROPERTY = "ИспользуемаяИерархия"
_MODE_ENUM = "РежимИерархии"
_AUTO = "Авто"


@lru_cache(maxsize=1)
def _bare_words() -> dict[str, tuple[str, str]]:
    """{a bare word: (its Russian spelling, "ru" | "en")} of the modes and of `Auto`."""
    out: dict[str, tuple[str, str]] = {}
    for russian, english in uischema.enum_value_aliases(_MODE_ENUM).items():
        out[russian] = (russian, "ru")
        if english:
            out[english] = (russian, "en")
    out[_AUTO] = (_AUTO, "ru")
    out[terms.common_english(_AUTO) or _AUTO] = (_AUTO, "en")
    return out


dataset.register_reset(_bare_words.cache_clear)


def _typed(mode: str, language: str) -> str:
    """The typed node of a hierarchy mode, spelled in the language of the file."""
    if language == "ru":
        return "{Тип: %s, Значение: %s}" % (_MODE_ENUM, mode)
    english = uischema.enum_value_aliases(_MODE_ENUM).get(mode) or mode
    return "{Type: %s, Value: %s}" % (terms.common_english(_MODE_ENUM) or _MODE_ENUM, english)


def _line_fix(text: str, key, value) -> TextEdit | None:
    """The whole line of a property written alone on it, taken out; None for any other shape."""
    start = text.rfind("\n", 0, key.start_mark.index) + 1
    end = text.find("\n", value.end_mark.index)
    end = len(text) if end == -1 else end + 1
    line = text[start:end]
    pattern = r"[ \t]*%s[ \t]*:[ \t]*%s[ \t]*\r?\n?" % (re.escape(key.value), re.escape(value.value))
    return TextEdit(start, end, "") if re.fullmatch(pattern, line) else None


@rule("yaml/hierarchy-bare-value", "yaml/hierarchy-bare-value.title", "A",
      severity=Severity.ERROR)
def hierarchy_bare_value(source: SourceFile) -> Iterable[Diagnostic]:
    """A bare mode word in `UsedHierarchy` - see the module docstring."""
    if source.kind != "yaml" or not _HAVE_YAML:
        return
    root = _composed(source)
    if root is None:
        return
    keys = set(_key_spellings(_PROPERTY))
    words = _bare_words()
    for mapping in _mapping_nodes(root):
        for key, value in mapping.value:
            if not isinstance(key, yaml.ScalarNode) or key.value not in keys:
                continue
            if not isinstance(value, yaml.ScalarNode) or value.style not in (None, ""):
                continue  # a node, or a quoted word: a hierarchy name
            spelled = words.get(value.value)
            if spelled is None:
                continue  # another word: the name of a hierarchy
            russian, language = spelled
            if russian == _AUTO:
                message = i18n.t("yaml/hierarchy-bare-value.auto", word=value.value)
                fix = _line_fix(source.text, key, value)
            else:
                typed = _typed(russian, language)
                message = i18n.t("yaml/hierarchy-bare-value.mode", word=value.value, typed=typed)
                start, end = value.start_mark.index, value.end_mark.index
                fix = TextEdit(start, end, typed) if source.text[start:end] == value.value else None
            yield Diagnostic(
                source.rel, value.start_mark.line + 1, value.start_mark.column + 1,
                "yaml/hierarchy-bare-value", Severity.ERROR, message, fix=fix,
            )


# --- yaml/auto-bare-value ----------------------------------------------------------------------

AUTO_RULE = "yaml/auto-bare-value"
#: Keys of a node that name its type, and the key of a property's default value.
_TYPE_KEY = "Тип"
_DEFAULT_KEY = "ЗначениеПоУмолчанию"
_STRING = "Строка"
#: Union members that say nothing about the type a node carries.
_UNTYPED = frozenset({_AUTO, "Неопределено", "?"})


@lru_cache(maxsize=1)
def _member_types() -> dict[str, dict[str, str]]:
    """{type: {member: its type expression}} of the type catalog, Russian names."""
    data = dataset.load_optional("stdlib.json") or {}
    table = data.get("member_types")
    return table if isinstance(table, dict) else {}


@lru_cache(maxsize=1)
def _components() -> dict[str, dict]:
    """{component: its properties} of the ui schema."""
    schema = dataset.load_ui_schema() if uischema.available() else None
    components = (schema or {}).get("components") or {}
    return {name: rec.get("props") or {} for name, rec in components.items()}


dataset.register_reset(_member_types.cache_clear)
dataset.register_reset(_components.cache_clear)


def _head(expression: str) -> str:
    """`Table<DynamicList<X>>` -> the head, package dropped, spelled in Russian."""
    head = expression.split("<", 1)[0].strip().rpartition("::")[2].strip().rstrip("?")
    if head.isascii():
        head = uischema.canonical_component(head)
        if head.isascii():
            head = terms.russian(head, "types") or head
    return head


def _first_argument(expression: str) -> str | None:
    """The first generic argument of a type expression, or None."""
    start = expression.find("<")
    if start < 0 or not expression.endswith(">"):
        return None
    depth, inner = 0, expression[start + 1:-1]
    for i, char in enumerate(inner):
        depth += (char == "<") - (char == ">")
        if char in ",|" and depth == 0:
            return inner[:i].strip()
    return inner.strip()


def _union(owner: str, key: str) -> tuple[str, ...] | None:
    """The type union a node of type `owner` declares for `key`, or None."""
    props = _components().get(owner)
    if props is not None:
        record = props.get(uischema.canonical_property(key))
        return tuple(record.get("types") or ()) if isinstance(record, dict) else None
    member = _member_types().get(owner, {}).get(key if not key.isascii() else (
        terms.russian(key, "properties") or key))
    return tuple(part.strip() for part in member.split("|")) if isinstance(member, str) else None


def _scalar(mapping, keys: frozenset[str]) -> str | None:
    for key, value in mapping.value:
        if isinstance(key, yaml.ScalarNode) and key.value in keys and isinstance(value, yaml.ScalarNode):
            return value.value
    return None


def _walk(node, owner: str | None, type_expr: str, keys: dict[str, frozenset[str]], found: list):
    """Every bare Auto of the markup under `node`, typed as `owner` (None - not known)."""
    if isinstance(node, yaml.SequenceNode):
        for item in node.value:
            _walk(item, owner, type_expr, keys, found)
        return
    if not isinstance(node, yaml.MappingNode):
        return
    written = _scalar(node, keys["type"])
    if written:
        owner, type_expr = _head(written), written
    for key, value in node.value:
        if not isinstance(key, yaml.ScalarNode):
            continue
        union = _union(owner, key.value) if owner else None
        if isinstance(value, yaml.ScalarNode):
            if (union and set(union) == {_AUTO, _STRING} and value.style in (None, "")
                    and value.value in keys["auto"]):
                found.append((key, value, owner))
            continue
        child = None
        if key.value in keys["default"]:
            child = owner  # a property's default value is of the type the property declares
        elif union:
            typed = [member for member in union if member not in _UNTYPED]
            if len(typed) == 1:
                member = typed[0]
                element = _first_argument(member) if member.startswith("Массив<") else None
                child = _head(element or member)
                if child not in _components() and child not in _member_types():
                    # A generic parameter (the source of a list): the argument of the owner.
                    argument = _first_argument(type_expr)
                    child = _head(argument) if argument else None
        _walk(value, child, child or "", keys, found)


@lru_cache(maxsize=1)
def _keys() -> dict[str, frozenset[str]]:
    return {
        "type": frozenset(_key_spellings(_TYPE_KEY)),
        "default": frozenset(_key_spellings(_DEFAULT_KEY)),
        "auto": frozenset({_AUTO, terms.common_english(_AUTO) or _AUTO}),
    }


dataset.register_reset(_keys.cache_clear)


@rule(AUTO_RULE, f"{AUTO_RULE}.title", "D", severity=Severity.ERROR)
def auto_bare_value(source: SourceFile) -> Iterable[Diagnostic]:
    """A bare Auto in a property typed Auto|String - see the module docstring."""
    if source.kind != "yaml" or not _HAVE_YAML or not _components():
        return
    if not any(word in source.text for word in _keys()["auto"]):
        return
    root = _composed(source)
    if not isinstance(root, yaml.MappingNode):
        return
    found: list = []
    _walk(root, None, "", _keys(), found)
    for key, value, owner in found:
        yield Diagnostic(
            source.rel, value.start_mark.line + 1, value.start_mark.column + 1,
            AUTO_RULE, Severity.ERROR,
            i18n.t(f"{AUTO_RULE}.found", key=key.value, owner=i18n.name(owner, "types"),
                   word=value.value),
        )
