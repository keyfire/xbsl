"""Tier A: a union type in a yaml type position must carry the empty value.

The yaml/union-needs-nullable rule. A `Type` value that is a union of two or more plain types
with no empty member - `String|Number`, `Number|Boolean` - has no implicit default value: the
platform builds a default only for a single type, and for a set of types without `Undefined` it
gives up at once, whatever the members are. The server-side compilation then fails with
"Default value initialization is not supported for types ...", advising to specify a value or
to add the empty member to the set.

A live probe got exactly this on the property of an entity contract (`String|Number`, and again
`String|Boolean`) - a place with no `DefaultValue` key at all, so the only way out there is the
empty member. The same probe covered the other stored positions: an attribute of a catalog and
of its tabular section, a dimension and a resource of an information register, a field of a
structure and a property of an interface component all fail the same way. What compiles is a
union with the empty member (`String|Number|?`), an attribute that states its default next to
the type (`DefaultValue`), a structure field marked `Required: True` (its value comes from the
constructor) and a parameter of a global client event (the value comes from whoever raises the
event).

A union with a REFERENCE member is the business of the sibling yaml/ref-needs-nullable (the
same compiler message, reported there with the reference named); this rule takes the unions
that have none, so one position never gets two findings. Narrowing, as there: an alternative
outside the plain-chain shape (a generic, a qualified name) leaves the union alone, a typed
literal (a `Value` node holding its own `Type`) is not a declaration, and a value is judged only
in the bare shape - an input field around a union is not covered by the probe.

The fix is mechanical - append the empty member, `String|Number|?` - and is offered as a quick
fix when the value is written as a plain scalar.
"""

from __future__ import annotations

from collections.abc import Iterable

from xbsl import i18n, metamodel
from xbsl.diagnostics import Diagnostic, Severity, TextEdit
from xbsl.engine import SourceFile, rule
from xbsl.rules.ref_fields import (
    _NULLABLE_ALTS,
    _YAML_UNION_ALT_RE,
    _is_required,
    _parameter_mappings,
    _yaml_patterns,
)
from xbsl.rules.yaml_schema import (
    _HAVE_YAML,
    _composed,
    _is_object,
    _mapping_nodes,
    _parsed,
    _scalar_entries,
    object_kind,
)

if _HAVE_YAML:
    import yaml

MESSAGES = {
    "yaml/union-needs-nullable.title": {
        "ru": "Составной тип без пустого значения",
        "en": "Union type without the empty value",
    },
    "yaml/union-needs-nullable.union": {
        "ru": "Тип '{name}' – составной тип без пустого значения: значение по умолчанию "
              "строится только для одного типа, серверная компиляция упадет с 'Default value "
              "initialization is not supported for types ...'. Добавьте пустое значение в "
              "состав: '{name}|?'{default}.",
        "en": "Type '{name}' – a union without the empty value: a default value is built only "
              "for a single type, the server-side compilation will fail with 'Default value "
              "initialization is not supported for types ...'. Add the empty value to the set: "
              "'{name}|?'{default}.",
    },
    "yaml/union-needs-nullable.or-default": {
        "ru": " либо задайте {key} рядом с {type}",
        "en": " or set {key} next to {type}",
    },
}
i18n.register(MESSAGES)

#: The key whose presence next to `Type` gives the position a value of its own.
_DEFAULT_KEY = "ЗначениеПоУмолчанию"
#: A typed literal holds `Type` and `Value` side by side - see the module docstring.
_VALUE_KEY = "Значение"


def _plain_union(text: str) -> bool:
    """A union of two or more plain chains, none empty, none a reference."""
    alternatives = [alt.strip() for alt in text.split("|")]
    if len(alternatives) < 2:
        return False
    reference = _yaml_patterns()[0]
    for alt in alternatives:
        if alt in _NULLABLE_ALTS or alt.endswith("?"):
            return False
        if not _YAML_UNION_ALT_RE.match(alt) or reference.fullmatch(alt):
            return False
    return True


def _contract_file(data) -> bool:
    """A description of an entity contract: its properties cannot carry a default value."""
    return object_kind(data) == "КонтрактСущности"


@rule("yaml/union-needs-nullable", "yaml/union-needs-nullable.title", "A",
      severity=Severity.ERROR)
def yaml_union_needs_nullable(source: SourceFile) -> Iterable[Diagnostic]:
    if source.kind != "yaml" or not _HAVE_YAML or "|" not in source.text:
        return
    data, err = _parsed(source)
    if err is not None or not _is_object(data):
        return
    root = _composed(source)
    if root is None:  # pragma: no cover - _parsed has already vetted the syntax
        return
    contract = _contract_file(data)
    parameters = _parameter_mappings(root)
    for mapping in _mapping_nodes(root):
        if id(mapping) in parameters:
            continue
        entries = _scalar_entries(mapping)
        entry = entries.get("Тип")
        if entry is None or not isinstance(entry[1], yaml.ScalarNode):
            continue
        if _DEFAULT_KEY in entries or _VALUE_KEY in entries or _is_required(entries):
            continue
        value_node = entry[1]
        if value_node.style in ("|", ">"):  # a block scalar is text, not a type
            continue
        value = value_node.value
        stripped = value.strip()
        if not _plain_union(stripped):
            continue
        type_key = entry[0].value
        default_key = _DEFAULT_KEY
        if type_key != "Тип":  # the file speaks English - so does the advice
            default_key = metamodel.english_name(_DEFAULT_KEY) or _DEFAULT_KEY
        default = "" if contract else i18n.t(
            "yaml/union-needs-nullable.or-default", key=default_key, type=type_key,
        )
        start, end = value_node.start_mark.index, value_node.end_mark.index
        fix = None
        if not value_node.style and source.text[start:end] == value:
            fix = TextEdit(end, end, "|?")
        quote = 1 if value_node.style in ("'", '"') else 0
        yield Diagnostic(
            source.rel,
            value_node.start_mark.line + 1,
            value_node.start_mark.column + 1 + quote,
            "yaml/union-needs-nullable", Severity.ERROR,
            i18n.t("yaml/union-needs-nullable.union", name=stripped, default=default),
            fix=fix,
        )
