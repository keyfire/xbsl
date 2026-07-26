"""Tier D: what the localization mechanism silently lets through.

Two checks over the dictionary of localized strings and its use.

--- yaml/placeholder-key-in-strings ---

The two sections of a localized-strings dictionary are not interchangeable.

A `ЛокализованныеСтроки` element holds `Строки` and `Шаблоны`, and the platform compiles them
differently: an entry of `Строки` becomes a method WITHOUT parameters, an entry of `Шаблоны` a
method that takes the substitutions its text names (`$0`, `$1`, ...).

So a text carrying a placeholder is only useful in `Шаблоны`. Left in `Строки` it still
compiles - the placeholder is just text there - and the failure surfaces at the call site
instead: `Словарь.Ключ("значение")` finds no method of that arity and the apply answers
`Неизвестный метод`, naming the key but never the section, so the message points away from
the cause.

The check is file-local (both the section and its entries are in one yaml) and reads the
section names in either spelling, from the metamodel record of the kind.

--- code/compare-with-localized ---

A localized value is whatever the reader's language turns it into, so comparing it against a
fixed string decides on one language and silently misses on every other: the branch simply
never runs. Two shapes are read as localized - a call of a dictionary of the project
(`<Словарь>.<Ключ>(...)`) and the platform's own `Представление()` - and the comparison is
reported when the other side is a string literal or a second localized value.

The cure is to branch on the VALUE behind the presentation (an enumeration element, a code, a
reference) rather than on its text.

A comparison against a plain VARIABLE is skipped on purpose, even though the localized side
still varies by language there: what the variable holds is not visible to a token-level check,
and a rule that guessed would fire on every dispatch that legitimately compares two values.
The narrow form is the one the defect was actually met in.

The check is project-wide because the dictionaries are project elements: which names are
localized cannot be told from one module. The `Представление()` shape is kept in the same rule
rather than split into a file one - it is the same defect and the same message, and on the
corpus it is the smaller half by an order of magnitude.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from functools import lru_cache

import yaml as _yaml

from xbsl import dataset, i18n, metamodel, terms
from xbsl.diagnostics import Diagnostic, Severity
from xbsl.engine import SourceFile, rule
from xbsl.rules._syntax import code_tokens
from xbsl.rules.yaml_schema import _composed, _HAVE_YAML, _parsed, object_kind

MESSAGES = {
    "yaml/placeholder-key-in-strings.title": {
        "ru": "Подстановка в секции Строки, а не Шаблоны",
        "en": "A placeholder in the Strings section instead of Templates",
    },
    "code/compare-with-localized.title": {
        "ru": "Сравнение с локализованным значением",
        "en": "A comparison against a localized value",
    },
    "code/compare-with-localized.literal": {
        "ru": "Сравнение локализованного значения ({what}) с литералом {literal}: на другом "
              "языке ветка молча не сработает. Ветвитесь по значению – элементу перечисления, "
              "коду, ссылке, – а не по его тексту.",
        "en": "A localized value ({what}) is compared against the literal {literal}: in another "
              "language the branch simply never runs. Branch on the VALUE – an enumeration "
              "element, a code, a reference – rather than on its text.",
    },
    "code/compare-with-localized.both": {
        "ru": "Сравнение двух локализованных значений ({what}): совпадение зависит от языка "
              "читателя. Сравнивайте значения, стоящие за представлениями.",
        "en": "Two localized values are compared ({what}): whether they match depends on the "
              "reader's language. Compare the values behind the presentations.",
    },
    "yaml/placeholder-key-in-strings.found": {
        "ru": "Ключ '{key}' несёт подстановку {placeholder}, но лежит в секции Строки – она "
              "компилируется в метод БЕЗ параметров, и вызов с аргументом упадёт на применении "
              "\"Неизвестный метод\". Перенесите ключ в секцию Шаблоны.",
        "en": "Key '{key}' carries the placeholder {placeholder} but sits in the {n[Строки]} "
              "section, which compiles to a method WITHOUT parameters – a call with an argument "
              "fails the apply with \"Неизвестный метод\". Move the key to {n[Шаблоны]}.",
    },
}
i18n.register(MESSAGES)

_KIND = "ЛокализованныеСтроки"
_STRINGS = "Строки"
_TEMPLATES = "Шаблоны"

#: `$0`, `$1`, ... - the substitution a template names in its text.
_PLACEHOLDER = re.compile(r"\$\d")


@lru_cache(maxsize=1)
def _section_names() -> frozenset[str]:
    """Both spellings of the `Строки` section, from the metamodel record of the kind."""
    record = metamodel.properties(_KIND).get(_STRINGS) or {}
    return frozenset({_STRINGS, record.get("en")} - {None})


dataset.register_reset(_section_names.cache_clear)


@rule(
    "yaml/placeholder-key-in-strings",
    "yaml/placeholder-key-in-strings.title", "D",
    severity=Severity.ERROR,
)
def placeholder_key_in_strings(source: SourceFile) -> Iterable[Diagnostic]:
    """A dictionary entry with a substitution left outside the templates section."""
    if not _HAVE_YAML or source.kind != "yaml":
        return
    if not _PLACEHOLDER.search(source.text):
        return  # the cheap gate - no substitution anywhere in the file
    data, error = _parsed(source)
    if error is not None or not isinstance(data, dict) or object_kind(data) != _KIND:
        return
    sections = _section_names()
    root = _composed(source)
    if root is None or not isinstance(root, _yaml.MappingNode):
        return
    for key_node, value_node in root.value:
        if not (isinstance(key_node, _yaml.ScalarNode) and key_node.value in sections):
            continue
        if not isinstance(value_node, _yaml.MappingNode):
            continue
        for entry_key, entry_value in value_node.value:
            if not (isinstance(entry_key, _yaml.ScalarNode)
                    and isinstance(entry_value, _yaml.ScalarNode)):
                continue
            found = _PLACEHOLDER.search(entry_value.value or "")
            if found is None:
                continue
            yield Diagnostic(
                source.rel, entry_key.start_mark.line + 1, entry_key.start_mark.column + 1,
                "yaml/placeholder-key-in-strings", Severity.ERROR,
                i18n.t("yaml/placeholder-key-in-strings.found",
                       key=entry_key.value, placeholder=found.group(0)),
            )


# --- code/compare-with-localized -------------------------------------------------------

_COMPARISONS = frozenset({"==", "!="})
_PRESENTATION = "Представление"


@lru_cache(maxsize=1)
def _presentation_names() -> frozenset[str]:
    """Both spellings of the platform's presentation method."""
    english = terms.common_english(_PRESENTATION)
    return frozenset({_PRESENTATION, english} - {None})


dataset.register_reset(_presentation_names.cache_clear)


def _call_end(toks: list, name_at: int) -> int | None:
    """Index just past a `Имя(...)` call whose name token is at `name_at`, else None."""
    n = len(toks)
    if not (name_at + 1 < n and toks[name_at + 1].kind == "OP"
            and toks[name_at + 1].value == "("):
        return None
    depth, j = 1, name_at + 2
    while j < n and depth:
        if toks[j].kind == "OP" and toks[j].value == "(":
            depth += 1
        elif toks[j].kind == "OP" and toks[j].value == ")":
            depth -= 1
        j += 1
    return j if not depth else None


def _localized_spans(toks: list, dictionaries: frozenset[str]) -> list[tuple[int, int, str]]:
    """(first token, past-the-end token, what it is) of every localized expression."""
    spans: list[tuple[int, int, str]] = []
    presentation = _presentation_names()
    n = len(toks)
    for i, t in enumerate(toks):
        if t.kind != "IDENT":
            continue
        if (t.value in dictionaries and i + 2 < n
                and toks[i + 1].kind == "OP" and toks[i + 1].value == "."
                and toks[i + 2].kind == "IDENT"):
            end = _call_end(toks, i + 2)
            if end is not None:
                spans.append((i, end, f"{t.value}.{toks[i + 2].value}"))
        elif (t.value in presentation and i
              and toks[i - 1].kind == "OP" and toks[i - 1].value == "."):
            end = _call_end(toks, i)
            if end is not None:
                spans.append((i - 1, end, f".{t.value}()"))
    return spans


def _compare_mapper(source: SourceFile) -> dict | None:
    """The map phase: a yaml names a dictionary of the project, a module contributes its
    tokens' shape - the reduce needs the dictionary names before it can read a module."""
    if not _HAVE_YAML:
        return None
    if source.kind == "yaml":
        data, error = _parsed(source)
        if error is not None or not isinstance(data, dict) or object_kind(data) != _KIND:
            return None
        name = data.get("Имя") or data.get("Name")
        if not isinstance(name, str):
            return None
        return {"k": "y", "name": name}
    if source.kind != "xbsl":
        return None
    return {"k": "x", "source": source}


@rule(
    "code/compare-with-localized", "code/compare-with-localized.title", "D",
    scope="project", severity=Severity.WARNING, mapper=_compare_mapper,
)
def compare_with_localized(facts: dict[str, dict]) -> Iterable[Diagnostic]:
    dictionaries = frozenset(f["name"] for f in facts.values() if f["k"] == "y")
    for rel, fact in facts.items():
        if fact["k"] != "x":
            continue
        source = fact["source"]
        toks = code_tokens(source)
        spans = _localized_spans(toks, dictionaries)
        if not spans:
            continue
        starts = {start: (end, what) for start, end, what in spans}
        ends = {end: (start, what) for start, end, what in spans}
        n = len(toks)
        seen: set[int] = set()
        for start, end, what in spans:
            for op_at, other_at, other_dir in (
                (start - 1, start - 2, "before"), (end, end + 1, "after"),
            ):
                if not (0 <= op_at < n):
                    continue
                op = toks[op_at]
                if not (op.kind == "OP" and op.value in _COMPARISONS) or op_at in seen:
                    continue
                other = toks[other_at] if 0 <= other_at < n else None
                if other is None:
                    continue
                if other_dir == "before" and op_at in ends:
                    key, args = "code/compare-with-localized.both", {"what": what}
                elif other_dir == "after" and (other_at in starts):
                    key, args = "code/compare-with-localized.both", {"what": what}
                elif other.kind == "STRING":
                    key = "code/compare-with-localized.literal"
                    args = {"what": what, "literal": other.value}
                else:
                    continue  # comparing against a value, not against text
                seen.add(op_at)
                anchor = toks[start]
                yield Diagnostic(
                    rel, anchor.line, anchor.col,
                    "code/compare-with-localized", Severity.WARNING,
                    i18n.t(key, **args),
                )
