"""Tier D: a ВыборЗначения component must carry a static СписокВыбора in yaml.

A platform gotcha caught only at runtime (the form initialisation fails): filling the choice
list programmatically does not work for `ВыборЗначения<...>` – the list must be a static
`СписокВыбора` key right on the yaml node. When the list has to be computed, the component to
use is `ПолеВвода<Тип>`. So a form-tree node whose `Тип` is `ВыборЗначения<...>` and which has
no `СписокВыбора` key in the same node is diagnosed.

Zero-false-positive guards (narrowings):
- only yaml objects (files with `ВидЭлемента`) are looked at;
- the generic parameter must consist of primitive alternatives only – Строка, Число, Дата,
  Время, ДатаВремя, or Массив<такой примитив> (plus the nullable markers). For a parameter
  deriving from Перечисление (or Массив<Перечисление>) the platform builds the list itself
  (СписокВыбора: Авто – see the ВыборЗначения stdlib doc), and in per-file mode a project
  type cannot be resolved – such nodes are skipped rather than guessed. Булево is skipped
  for the same reason (two values, the platform may render them without a list);
- a bare `ВыборЗначения` without a generic parameter is skipped (the data type is unknown);
- the `СписокВыбора` key satisfies the rule with any value (a binding `=...` included) –
  only the presence of the key on the node is checked, not its content;
- positions come from a text search for the `Тип: <значение>` lines (CRLF-safe) zipped with
  the document-order tree walk; when the counts diverge (anchors, flow style), the value is
  skipped rather than mis-positioned.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from functools import lru_cache

from xbsl import dataset, i18n, terms, uischema
from xbsl.diagnostics import Diagnostic, Severity
from xbsl.engine import SourceFile, rule
from xbsl.rules.yaml_schema import _HAVE_YAML, _is_object, _parsed, value_of
from xbsl.rules.yaml_types import _value_positions

MESSAGES = {
    "yaml/choice-needs-static-list.title": {
        "ru": "ВыборЗначения без статичного СпискаВыбора",
        "en": "{n[ВыборЗначения]} without a static {n[СписокВыбора]}",
    },
    "yaml/choice-needs-static-list.missing": {
        "ru": "Компонент '{type}' без ключа СписокВыбора в узле – программное наполнение "
              "списка для ВыборЗначения не работает (инициализация формы падает); задайте "
              "статичный СписокВыбора в yaml или используйте ПолеВвода<...>.",
        "en": "Component '{type}' has no {n[СписокВыбора]} key on the node – filling the choice "
              "list programmatically does not work for {n[ВыборЗначения]} (the form "
              "initialisation fails); set a static {n[СписокВыбора]} in yaml or use {n[ПолеВвода]}<...>.",
    },
}
i18n.register(MESSAGES)

_CHOICE = "ВыборЗначения"
_CHOICE_LIST = "СписокВыбора"

# Primitive data types that certainly are not enumerations: for these the platform cannot
# build the list itself, so a static `ChoiceList` is mandatory. Both spellings of every name
# come from the platform's own dictionary - a translated project writes `ValueChoice<String>`,
# and the rule used to pass such a node by (found by a parity seed).
_PRIMITIVES_RU = ("Строка", "Число", "Дата", "Время", "ДатаВремя")


@lru_cache(maxsize=1)
def _choice_names() -> tuple[str, ...]:
    return terms.forms(_CHOICE, "types")


@lru_cache(maxsize=1)
def _primitives() -> frozenset[str]:
    return frozenset(name for ru in _PRIMITIVES_RU for name in terms.forms(ru, "types"))


@lru_cache(maxsize=1)
def _array_re() -> re.Pattern[str]:
    heads = "|".join(re.escape(name) for name in terms.forms("Массив", "types"))
    return re.compile(rf"^(?:{heads})<\s*([A-Za-zА-Яа-яЁё_][A-Za-zА-Яа-яЁё_0-9]*)\s*>$")


dataset.register_reset(_choice_names.cache_clear)
dataset.register_reset(_primitives.cache_clear)
dataset.register_reset(_array_re.cache_clear)


def _split_alternatives(param: str) -> list[str] | None:
    """The top-level `|` alternatives of a generic parameter, or None on unbalanced <>."""
    alts: list[str] = []
    depth = 0
    cur = ""
    for ch in param:
        if ch == "<":
            depth += 1
        elif ch == ">":
            depth -= 1
            if depth < 0:
                return None
        elif ch == "|" and depth == 0:
            alts.append(cur)
            cur = ""
            continue
        cur += ch
    if depth != 0:
        return None
    alts.append(cur)
    return alts


def _requires_static_list(type_value: str) -> bool:
    """Whether the ВыборЗначения data type certainly needs a static СписокВыбора.

    True only when every alternative of the generic parameter is a known primitive
    (or Массив<примитив>); everything else – an enumeration, a project type, a bare
    ВыборЗначения – is skipped rather than guessed.
    """
    head = next((name for name in _choice_names()
                 if type_value.startswith(name + "<")), None)
    if head is None or not type_value.endswith(">"):
        return False
    param = type_value[len(head) + 1:-1]
    alts = _split_alternatives(param)
    if alts is None:
        return False
    seen = False
    for alt in (a.strip() for a in alts):
        if alt in ("", "?"):  # nullable markers
            continue
        if alt.endswith("?"):
            alt = alt[:-1].strip()
        m = _array_re().match(alt)
        name = m.group(1) if m else alt
        if name not in _primitives():
            return False
        seen = True
    return seen


def _choice_nodes(node, out: list[tuple[str, bool]]) -> None:
    """(the Тип value, whether СписокВыбора is present) of every ВыборЗначения node, in document order."""
    if isinstance(node, dict):
        t = value_of(node, "Тип")
        if isinstance(t, str) and any(t == name or t.startswith(name + "<")
                                      for name in _choice_names()):
            # The key is canonized rather than matched: the term dictionary pairs no
            # spelling for it, while the ui schema does (`ChoiceList` is the English
            # spelling it canonizes).
            out.append((t, any(isinstance(key, str)
                               and uischema.canonical_property(key) == _CHOICE_LIST
                               for key in node)))
        for v in node.values():
            _choice_nodes(v, out)
    elif isinstance(node, list):
        for item in node:
            _choice_nodes(item, out)


@rule(
    "yaml/choice-needs-static-list", "yaml/choice-needs-static-list.title", "D",
    severity=Severity.WARNING,
)
def choice_needs_static_list(source: SourceFile) -> Iterable[Diagnostic]:
    if source.kind != "yaml" or not _HAVE_YAML:
        return
    data, err = _parsed(source)
    if err is not None or not _is_object(data):
        return
    nodes: list[tuple[str, bool]] = []
    _choice_nodes(data, nodes)
    if not nodes:
        return
    by_value: dict[str, list[bool]] = {}
    for value, has_list in nodes:
        by_value.setdefault(value, []).append(has_list)
    for value, flags in by_value.items():
        if all(flags) or not _requires_static_list(value):
            continue
        positions = _value_positions(source, value)
        if len(positions) != len(flags):  # anchors or flow style – skip rather than misplace
            continue
        for (line, col), has_list in zip(positions, flags):
            if has_list:
                continue
            yield Diagnostic(
                source.rel, line, col, "yaml/choice-needs-static-list", Severity.WARNING,
                i18n.t("yaml/choice-needs-static-list.missing", type=value),
            )
