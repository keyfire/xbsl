"""Tier D: an event log event that leaves its importance to every constructor.

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
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from functools import lru_cache

from xbsl import dataset, i18n, metamodel, terms
from xbsl.diagnostics import Diagnostic, Severity
from xbsl.engine import SourceFile, rule
from xbsl.lexer import linemap
from xbsl.rules.yaml_schema import _HAVE_YAML, _KIND_KEYS, _parsed, object_kind, value_of

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
