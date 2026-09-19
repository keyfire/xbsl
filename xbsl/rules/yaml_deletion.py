"""Tier D: the on-delete action of a reference attribute against the deletion mode of its element.

An attribute that references another object declares what happens to its own record when the
referenced object goes away. `DeleteCurrent` means the record is deleted outright, and the
platform allows that only inside an element that is itself deleted outright. `topics/data-deletion`
puts it the other way round: when an element of the project is in the deletion mode `DeletionMark`,
its attributes may not set `OnReferencedObjectDeletion` to `DeleteCurrent`. The restriction is on
the element that DECLARES the attribute, and `DeletionMark` is the default of the property, so an
element that never mentions the mode is in it.

A cascading cache - a catalog whose rows are genuinely removed together with what they
describe - therefore has to declare `DeletionMode: Immediately` on the element that HOLDS the
reference, not on the object referenced.

A project that breaks the restriction does not compile: the compiler refuses it with
`Action DeleteCurrent cannot apply to object with a "DeletionMark"` and points at the value in
the file of the element that HOLDS the reference. That sentence is the compiler's own and
appears on no page of the shipped documentation, which is why the message names its source.

Only some kinds have a deletion mode at all - four of the forty one. A register has none -
neither the metamodel nor `topics/information-register-properties` gives the kind such a
property - while its dimensions and resources may well carry the action, and the compiler takes
them. So a register is out of the rule's reach entirely.

Both facts live in the same file (the element's deletion mode and its attribute's action), so
this is a file rule and the editor highlights it while typing. The query side of the same
platform fact - a condition on the deletion mark of an object deleted outright, which has no
such field - is `query/deletion-mark-immediate`.
"""

from __future__ import annotations

from collections.abc import Iterable
from functools import lru_cache

import yaml

from xbsl import dataset, i18n, metamodel, terms
from xbsl.diagnostics import Diagnostic, Severity
from xbsl.engine import SourceFile, rule
from xbsl.rules.yaml_schema import (
    _composed,
    _HAVE_YAML,
    _mapping_nodes,
    _parsed,
    object_kind,
)

MESSAGES = {
    "yaml/delete-current-needs-immediate.title": {
        "ru": "УдалятьТекущий при режиме удаления с пометкой",
        "en": "DeleteCurrent against a deletion mode that only marks",
    },
    "yaml/delete-current-needs-immediate.conflict": {
        "ru": "Реквизит '{name}': {action} допустим только в элементе проекта с "
              "РежимУдаления: Немедленно. А у элемента, который объявляет реквизит, "
              "РежимУдаления {mode}. Компилятор отвечает "
              "'Action {action} cannot apply to object with a \"DeletionMark\"'.",
        "en": "Attribute '{name}': {action} is allowed only inside a project element whose "
              "{n[РежимУдаления]} is {n[Немедленно]}. The element that holds the attribute "
              "{mode}. The compiler answers "
              "'Action {action} cannot apply to object with a \"DeletionMark\"'.",
    },
    "yaml/delete-current-needs-immediate.declared": {
        "ru": "объявлен как {value}",
        "en": "declares {value}",
    },
    "yaml/delete-current-needs-immediate.default": {
        "ru": "не объявлен вовсе, а умолчание – {value}",
        "en": "does not declare it at all, and the default is {value}",
    },
}
i18n.register(MESSAGES)

_ACTION_KEY = "ПриУдаленииОбъектаПоСсылке"
_ACTION_VALUE = "УдалятьТекущий"
_MODE_KEY = "РежимУдаления"
_SAFE_MODE = "Немедленно"
#: The mode an element of a kind that HAS the property falls into when nothing names one.
#: Written out for the records that carry no default of their own (see _default_mode).
_MARKING_MODE = "ПометкаУдаления"


def _spellings(name: str, english: str | None) -> frozenset[str]:
    return frozenset({name, english} - {None})


@lru_cache(maxsize=1)
def _forms() -> tuple[frozenset[str], frozenset[str], frozenset[str], frozenset[str]]:
    """Both spellings of the two keys and the two values.

    Taken from the metamodel and terms rather than written out: the English spelling of a
    platform name is the platform's own.
    """
    return (
        _spellings(_ACTION_KEY, metamodel.english_name(_ACTION_KEY)),
        _spellings(_ACTION_VALUE, terms.english(_ACTION_VALUE, "enums")
                   or terms.common_english(_ACTION_VALUE)),
        _spellings(_MODE_KEY, metamodel.english_name(_MODE_KEY)),
        _spellings(_SAFE_MODE, terms.english(_SAFE_MODE, "enums")
                   or terms.common_english(_SAFE_MODE)),
    )


@lru_cache(maxsize=None)
def _default_mode(kind: str) -> str | None:
    """The mode an element of this kind is in when its yaml never names one.

    Two different noes, and only one of them stands the rule down. `None` means the kind has
    no deletion mode AT ALL - four kinds out of the forty one declare the property, and a
    register is not among them, so its action contradicts nothing.

    A kind that DOES declare the property is answered even when its record spells no default:
    44 of the 63 enumeration records of the element kinds carry none, so a record without one
    is the ordinary shape of the data rather than its edge, and reading it as "this kind has
    no mode" would put the very miss this gate removes one border further along. The mode an
    element falls into is `DeletionMark`, which the compiler settled on its own - it refused
    `DeleteCurrent` in a catalog that named no mode at all.

    The default is read from the record of THIS kind. Collapsing every record into one value
    and applying it to every kind reported the dimensions of a register by a catalog's default.
    """
    props = metamodel.properties(kind)
    if _MODE_KEY not in props:
        return None
    return (props[_MODE_KEY] or {}).get("default") or _MARKING_MODE


def _reset() -> None:
    _forms.cache_clear()
    _default_mode.cache_clear()


dataset.register_reset(_reset)


def _declared_mode(data: dict, mode_keys: frozenset[str]) -> str | None:
    for key in mode_keys:
        value = data.get(key)
        if isinstance(value, str) and value:
            return value
    return None


@rule(
    "yaml/delete-current-needs-immediate",
    "yaml/delete-current-needs-immediate.title", "D",
    severity=Severity.ERROR,
)
def delete_current_needs_immediate(source: SourceFile) -> Iterable[Diagnostic]:
    """`DeleteCurrent` on an attribute of an element the platform only marks as deleted."""
    if not _HAVE_YAML or source.kind != "yaml":
        return
    action_keys, action_values, mode_keys, safe_modes = _forms()
    if not any(key in source.text for key in action_keys):
        return  # the cheap gate - composing the node graph costs a second parse
    data, error = _parsed(source)
    if error is not None or not isinstance(data, dict):
        return
    kind = object_kind(data)
    if kind is None:
        return
    default_mode = _default_mode(kind)
    if default_mode is None:
        return  # the kind has no deletion mode - a register and its neighbours
    declared = _declared_mode(data, mode_keys)
    mode = declared if declared is not None else default_mode
    if mode in safe_modes:
        return
    # A declared mode is quoted from the file as it stands there; a default comes from the
    # metamodel, whose names are Russian, so it is spelled in the language of the message.
    said = (i18n.t("yaml/delete-current-needs-immediate.declared", value=declared)
            if declared is not None
            else i18n.t("yaml/delete-current-needs-immediate.default",
                        value=i18n.name(default_mode, "enums")))
    root = _composed(source)
    if root is None:
        return
    for mapping in _mapping_nodes(root):
        name = "?"
        hit = None
        for key_node, value_node in mapping.value:
            if not isinstance(key_node, yaml.ScalarNode):
                continue
            if key_node.value in ("Имя", "Name") and isinstance(value_node, yaml.ScalarNode):
                name = value_node.value
            elif (key_node.value in action_keys
                  and isinstance(value_node, yaml.ScalarNode)
                  and value_node.value in action_values):
                hit = (key_node, value_node.value)
        if hit is None:
            continue
        key_node, action = hit
        yield Diagnostic(
            source.rel, key_node.start_mark.line + 1, key_node.start_mark.column + 1,
            "yaml/delete-current-needs-immediate", Severity.ERROR,
            i18n.t("yaml/delete-current-needs-immediate.conflict",
                   name=name, action=action, mode=said),
        )
