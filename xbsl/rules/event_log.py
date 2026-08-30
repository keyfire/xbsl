"""Tier D: contracts of an event log event that only the server-side compilation enforces.

The `yaml/event-needs-importance` rule. `Importance` of an `EventLogEvent` has the metamodel
default `FromConstructor`, and the documentation of the kind states what that default means:
the importance of the event is then set in the constructor (topics/event-properties, the
`Importance` section, which spells the constructor call out as the example). A description that
never mentions the property is therefore in that mode, and the compiler then demands the value
at EVERY construction site. A single write that omits it fails the apply of the whole project
on the constructor line - the parameter has no default value - and nothing in the description
hints at the obligation. Both sides of that are visible on real sources: an event that declares
the importance once is constructed with a bare `new MyEvent()`, while an event that leaves it
out repeats `Importance = ...` in every one of its constructor calls.

Deliberate narrowing, so that the rule keeps the zero-false-positive bar:

- any explicit value silences it, `Importance: FromConstructor` included. Writing the
  platform's own word for the constructor mode is a decision, self-documenting at that, and a
  rule has no business arguing with it; it is also the intended way to switch the warning off
  for an event whose importance genuinely varies per write;
- the check runs only while the metamodel records `FromConstructor` as the default of the
  property, so a platform release that changes the default turns the rule off through the data
  rather than through a code edit;
- the sibling property `ErrorNature` carries the same default and, for an event of kind
  `Error`, the same obligation (topics/event-properties). It is not covered here: it is a check
  of its own, with its own corpus run, and one rule states one thing.

Both facts live in the same file - the element kind and the presence of the property - so this
is a file rule and the editor highlights it while typing. The finding is anchored on the line
declaring the kind: the property the message is about is precisely the one the file does not
have, and the kind declaration is what makes it required.

The `yaml/event-property-type` rule. The `Type` of an event's property (an entry of `Properties`)
is a CLOSED platform list: the metamodel constrains `EventLogEventProperty.Тип` with
`Std::Type<Std::Number | ... | Std::Uuid>`, identically in every extracted version. A project
enumeration in that position - the natural way to declare a variant value - passes the generic
type checks of the linter and is refused only by the server-side compilation on deploy, which
costs the apply of the whole project. The rule reads the list from the metamodel record rather
than restating it in code (a platform release that opens the list turns the rule off through
the data), resolves every member into both spellings through the term dictionary, and flags
each property whose normalized `Type` falls outside. Without the data the list is unknown and
the rule stays silent - silence over guessing.

The normalization and the narrowings, each a measured decision:

- the nullable marker `?` and a namespace qualification (`Стд::` / `Std::`, any depth) are
  stripped and TOLERATED: whether the compiler refuses `Строка?` or `Стд::Момент` here is not
  proven, and a false cut on a legal type matters more than an unproven refusal;
- an explicit `Undefined` is tolerated for the same reason: the documentation of the kind
  (topics/event-properties) spells the type union with a `| Неопределено` tail, so flagging it
  as a guaranteed refusal would overstate what is known. `EventLogEventKind` is the
  mirror case - present in the metamodel constraint, absent from the documentation page - and
  the metamodel, extracted from the compiler's own distribution, wins: it is allowed;
- a property without `Type` (or with a non-scalar value) is a concern of its own and is skipped;
- a union (`Строка|Число`) normalizes to itself, falls outside the list and is flagged: the
  constraint enumerates single types only.

Severity is an error: a finding is the compiler's own closed constraint violated, measured at
zero false positives on the corpora (the site alone: 8 events, 32 typed properties, all within
the list). The sibling `yaml/enum-needs-nullable` may double on the same line with advice that
is wrong for this kind - a `?` or a default value does not legalize an enumeration here - so
this rule carries the right one: write variant values as string codes and list the allowed
codes in the property's `Description`, which is localized and shown in the log. Both facts - the
element kind and the property types - live in one file, so the rule is file-scoped and runs in
the editor while typing. Findings are anchored on the value of the offending `Type`, taken from
the composed node graph - equal values in different properties keep their own lines.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from functools import lru_cache

from xbsl import dataset, i18n, metamodel, terms
from xbsl.diagnostics import Diagnostic, Severity
from xbsl.engine import SourceFile, rule
from xbsl.lexer import linemap
from xbsl.rules.yaml_schema import (
    _HAVE_YAML,
    _KIND_KEYS,
    _composed,
    _parsed,
    object_kind,
    value_of,
)

if _HAVE_YAML:
    import yaml

MESSAGES = {
    "yaml/event-needs-importance.title": {
        "ru": "Событие журнала без явной Важности",
        "en": "An event log event without an explicit {n[Важность]}",
    },
    "yaml/event-needs-importance.unset": {
        "ru": "Событие '{name}': Важность не задана в описании, а умолчание – "
              "ИзКонструктора, поэтому важность придётся передавать в каждом конструкторе: "
              "новый {name}(Важность = ...). Пропуск хотя бы в одном месте записи роняет "
              "применение на строке конструктора – у параметра Важность нет значения по "
              "умолчанию. Задайте Важность в описании либо передавайте её при каждой записи; "
              "явное 'Важность: ИзКонструктора' снимает предупреждение.",
        "en": "Event '{name}': {n[Важность]} is not set in the description and the default is "
              "{n[ИзКонструктора]}, so the value has to be passed in every constructor: "
              "new {name}({n[Важность]} = ...). One write that omits it fails the apply on the "
              "constructor line - the parameter has no default value. Set {n[Важность]} in the "
              "description or pass it at every write; an explicit "
              "'{n[Важность]}: {n[ИзКонструктора]}' silences the warning.",
    },
    "yaml/event-property-type.title": {
        "ru": "Тип свойства события журнала вне закрытого списка",
        "en": "An event log property type outside the closed list",
    },
    "yaml/event-property-type.outside": {
        "ru": "Свойство '{name}': тип '{value}' не входит в закрытый список типов свойств "
              "события журнала – {types}. Перечисление проекта туда положить нельзя: отказ "
              "придёт только серверной компиляцией и будет стоить деплоя. Вариантные значения "
              "пишите строковыми кодами (Строка), а допустимые коды перечислите в Описании "
              "свойства – оно локализуется и видно в журнале.",
        "en": "Property '{name}': type '{value}' is outside the closed list of event log "
              "property types – {types}. A project enumeration cannot go there: the refusal "
              "comes only from the server-side compilation and costs the deploy. Write variant "
              "values as string codes ({n[Строка]}) and list the allowed codes in the "
              "property's {n[Описание]} – it is localized and shown in the log.",
    },
}
i18n.register(MESSAGES)

_KIND = "СобытиеЖурналаСобытий"
_KEY = "Важность"
_FROM_CONSTRUCTOR = "ИзКонструктора"

# The line declaring the element kind - the anchor of a finding about a property the file never
# mentions. Both spellings of the key, taken from the one place that holds the pair; which kind
# the line names has already been answered by the parsed tree, so the value side is not matched.
_KIND_LINE_RE = re.compile(
    r"(?m)^[ \t]*(?:" + "|".join(re.escape(key) for key in _KIND_KEYS) + r")[ \t]*:"
)


@lru_cache(maxsize=1)
def _applies() -> bool:
    """Whether the metamodel still records `FromConstructor` as the default of `Importance`.

    The whole rule rests on that one fact: the property is optional in the description exactly
    because the platform expects the constructor to carry it. Reading it from the data (rather
    than restating it here) means a version that ships another default is answered correctly by
    the same code.
    """
    record = metamodel.properties(_KIND).get(_KEY) or {}
    return record.get("default") == _FROM_CONSTRUCTOR


@lru_cache(maxsize=1)
def _kind_spellings() -> tuple[str, ...]:
    """Both spellings of the kind name - the cheap gate before the yaml is parsed."""
    english = terms.english(_KIND, "types") or terms.common_english(_KIND)
    return tuple({_KIND, english} - {None})


dataset.register_reset(_applies.cache_clear)
dataset.register_reset(_kind_spellings.cache_clear)


@rule(
    "yaml/event-needs-importance", "yaml/event-needs-importance.title", "D",
    severity=Severity.WARNING,
)
def event_needs_importance(source: SourceFile) -> Iterable[Diagnostic]:
    """An event log event whose `Importance` is left to every constructor call."""
    if not _HAVE_YAML or source.kind != "yaml" or not _applies():
        return
    if not any(spelling in source.text for spelling in _kind_spellings()):
        return
    data, error = _parsed(source)
    if error is not None or object_kind(data) != _KIND:
        return
    if value_of(data, _KEY, _KIND) is not None:
        return
    name = value_of(data, "Имя", _KIND)
    if not isinstance(name, str) or not name:
        name = source.path.stem
    match = _KIND_LINE_RE.search(source.text)
    line, col = linemap(source).linecol(match.start()) if match else (1, 1)
    yield Diagnostic(
        source.rel, line, col, "yaml/event-needs-importance", Severity.WARNING,
        i18n.t("yaml/event-needs-importance.unset", name=name),
    )


_PROPERTY_CLASS = "EventLogEventProperty"
_PROPS_KEY = "Свойства"
_TYPE_KEY = "Тип"
_NAME_KEY = "Имя"
_UNDEFINED = "Неопределено"


@lru_cache(maxsize=1)
def _type_options() -> tuple[str, ...]:
    """The members of the closed constraint of the property `Type`, Russian spellings.

    The metamodel record carries `Std::Type<...>`; `metamodel.type_options` resolves the
    members into the platform's Russian names. Empty without the data - and the rule is
    then off: the closed list is the whole ground of the check.
    """
    record = metamodel.properties_of_class(_PROPERTY_CLASS).get(_TYPE_KEY) or {}
    return tuple(metamodel.type_options(record) or ())


@lru_cache(maxsize=1)
def _allowed_spellings() -> frozenset[str]:
    """Every allowed name in both spellings, plus the tolerated explicit `Undefined`."""
    options = _type_options()
    if not options:
        return frozenset()
    out: set[str] = set()
    for option in options:
        base = option[:-1].rstrip() if option.endswith("?") else option
        out.update(terms.forms(base, "types"))
    out.update(terms.forms(_UNDEFINED, "types"))
    return frozenset(out)


@lru_cache(maxsize=1)
def _property_keys() -> tuple[frozenset[str], frozenset[str], frozenset[str]]:
    """Both spellings of the three keys the rule reads, out of the metamodel records."""

    def spellings(key: str, records: dict) -> frozenset[str]:
        english = (records.get(key) or {}).get("en")
        return frozenset({key, english} - {None})

    item_records = metamodel.properties_of_class(_PROPERTY_CLASS)
    return (
        spellings(_PROPS_KEY, metamodel.properties(_KIND)),
        spellings(_TYPE_KEY, item_records),
        spellings(_NAME_KEY, item_records),
    )


dataset.register_reset(_type_options.cache_clear)
dataset.register_reset(_allowed_spellings.cache_clear)
dataset.register_reset(_property_keys.cache_clear)


def _normalized(value: str) -> str:
    """The bare type name: the nullable marker and any namespace qualification stripped.

    Both cuts are TOLERANCE, not judgement: `Строка?` and `Стд::Момент` come back as the
    allowed base name, so neither spelling is flagged on an unproven refusal.
    """
    name = value.strip()
    if name.endswith("?"):
        name = name[:-1].rstrip()
    if "::" in name:
        name = name.rsplit("::", 1)[-1].lstrip()
    return name


def _entry(mapping, keys: frozenset[str]):
    """The value node of the first key of the mapping named by either spelling, or None."""
    for key_node, value_node in mapping.value:
        if isinstance(key_node, yaml.ScalarNode) and key_node.value in keys:
            return value_node
    return None


@rule(
    "yaml/event-property-type", "yaml/event-property-type.title", "D",
    severity=Severity.ERROR,
)
def event_property_type(source: SourceFile) -> Iterable[Diagnostic]:
    """An event log property whose `Type` falls outside the platform's closed list."""
    if not _HAVE_YAML or source.kind != "yaml":
        return
    allowed = _allowed_spellings()
    if not allowed:
        return
    if not any(spelling in source.text for spelling in _kind_spellings()):
        return
    data, error = _parsed(source)
    if error is not None or object_kind(data) != _KIND:
        return
    root = _composed(source)
    if not isinstance(root, yaml.MappingNode):
        return
    props_keys, type_keys, name_keys = _property_keys()
    props = _entry(root, props_keys)
    if not isinstance(props, yaml.SequenceNode):
        return
    types = ", ".join(
        i18n.name(option[:-1].rstrip() if option.endswith("?") else option, "types")
        for option in _type_options()
    )
    for item in props.value:
        if not isinstance(item, yaml.MappingNode):
            continue
        value_node = _entry(item, type_keys)
        if not isinstance(value_node, yaml.ScalarNode):
            continue  # a missing type is a concern of its own; a nested value names no type
        raw = (value_node.value or "").strip()
        if not raw or _normalized(raw) in allowed:
            continue
        name_node = _entry(item, name_keys)
        name = name_node.value if isinstance(name_node, yaml.ScalarNode) and name_node.value else "?"
        mark = value_node.start_mark
        yield Diagnostic(
            source.rel, mark.line + 1, mark.column + 1,
            "yaml/event-property-type", Severity.ERROR,
            i18n.t("yaml/event-property-type.outside", name=name, value=raw, types=types),
        )
