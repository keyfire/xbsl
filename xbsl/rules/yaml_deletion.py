"""Tier D: the on-delete action of a reference attribute against its owner's deletion mode.

An attribute that references another object declares what happens to its own record when the
referenced object goes away. `DeleteCurrent` means the record is deleted outright, and the
platform allows that only for an owner that is itself deleted outright: with the deletion mode
`DeletionMark` - which is the metamodel's DEFAULT, so an object that never mentions the
property is in it - the record survives as a marked one, and the apply refuses the whole
project with `Action DeleteCurrent cannot apply to object with a DeletionMark`.

A cascading cache - a catalog whose rows are genuinely removed together with what they
describe - therefore has to declare `DeletionMode: Immediately` on the OWNER of the reference,
not on the object referenced.

Both facts live in the same file (the owner's deletion mode and its attribute's action), so
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
        "ru": "Реквизит '{name}': {action} требует, чтобы у владельца ссылки было "
              "РежимУдаления: Немедленно, а он {mode} – применение отвечает "
              "\"Action УдалятьТекущий cannot apply to object with a DeletionMark\".",
        "en": "Attribute '{name}': {action} requires the owner of the reference to have "
              "{n[РежимУдаления]}: {n[Немедленно]}, and it {mode} – the apply answers "
              "\"Action DeleteCurrent cannot apply to object with a DeletionMark\".",
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


def _spellings(name: str, english: str | None) -> frozenset[str]:
    return frozenset({name, english} - {None})


@lru_cache(maxsize=1)
def _forms() -> tuple[frozenset[str], frozenset[str], frozenset[str], frozenset[str], str]:
    """Both spellings of the two keys and the two values, plus the default deletion mode.

    Taken from the metamodel and terms rather than written out: the English spelling of a
    platform name is the platform's own, and the default of a property is what the metamodel
    records - an object that never mentions the mode is in it.
    """
    default = "ПометкаУдаления"
    for kind in metamodel.kinds():
        record = metamodel.properties(kind).get(_MODE_KEY)
        if record and record.get("default"):
            default = record["default"]
            break
    return (
        _spellings(_ACTION_KEY, metamodel.english_name(_ACTION_KEY)),
        _spellings(_ACTION_VALUE, terms.english(_ACTION_VALUE, "enums")
                   or terms.common_english(_ACTION_VALUE)),
        _spellings(_MODE_KEY, metamodel.english_name(_MODE_KEY)),
        _spellings(_SAFE_MODE, terms.english(_SAFE_MODE, "enums")
                   or terms.common_english(_SAFE_MODE)),
        default,
    )


dataset.register_reset(_forms.cache_clear)


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
    """`DeleteCurrent` on an attribute of an owner the platform only marks as deleted."""
    if not _HAVE_YAML or source.kind != "yaml":
        return
    action_keys, action_values, mode_keys, safe_modes, default_mode = _forms()
    if not any(key in source.text for key in action_keys):
        return  # the cheap gate - composing the node graph costs a second parse
    data, error = _parsed(source)
    if error is not None or not isinstance(data, dict) or not object_kind(data):
        return
    declared = _declared_mode(data, mode_keys)
    mode = declared if declared is not None else default_mode
    if mode in safe_modes:
        return
    said = i18n.t(
        "yaml/delete-current-needs-immediate."
        + ("declared" if declared is not None else "default"),
        value=mode,
    )
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
