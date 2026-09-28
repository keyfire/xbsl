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
