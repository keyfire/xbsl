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
structure, a field of a storable structure, a constant of a constants set and a property of an
interface component all fail the same way. What compiles is a union with the empty member
(`String|Number|?`), an attribute that states its default next to the type (`DefaultValue`), a
structure field marked `Required: True` (its value comes from the constructor), a parameter of a
global client event and of a virtual table (the value comes from whoever raises the event or
reads the table), and a property of a TYPE contract - it only declares what the implementing
element stores, and the probe applied it with a union as it is.

Three positions fail with messages of their own, and the rule quotes each:

- a parameter of writing or deleting (`WriteParameters`, `DeleteParameters`) - "The type
  composition of parameter ... must contain "Undefined" type". There is no default key there,
  so the empty member is the only way out. The same message came for a single type (`Boolean`)
  - that is beyond a rule about unions and stays unreported here;
- a query parameter of a report (`QueryParameters`) - the default value of the parameter is
  not set; the stand answered in Russian here:
  `Не указано значение по умолчанию для параметра`. A single type, a union with the empty
  member and a union with `DefaultValue` compiled in the same run;
- an input field around a union (`Edit<String|Number>`) - "Parameter ... of type ... must
  have a default value". A `Value` given to the field does not help: the probe kept the
  refusal with the value bound.

A union with a REFERENCE member is the business of the sibling yaml/ref-needs-nullable (the
same compiler message, reported there with the reference named); this rule takes the unions
that have none, so one position never gets two findings. Narrowing, as there: an alternative
outside the plain-chain shape (a generic, a qualified name) leaves the union alone, and a typed
literal (a `Value` node holding its own `Type`) is not a declaration.

The fix is mechanical - append the empty member, `String|Number|?` (inside the angle brackets
for an input field) - and is offered as a quick fix when the value is written as a plain scalar.
"""

from __future__ import annotations

from collections.abc import Iterable
from functools import lru_cache

from xbsl import dataset, i18n, metamodel, terms
from xbsl.diagnostics import Diagnostic, Severity, TextEdit
from xbsl.engine import SourceFile, rule
from xbsl.rules.ref_fields import (
    _NULLABLE_ALTS,
    _YAML_INPUT_ANY_RE,
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
    "yaml/union-needs-nullable.operation": {
        "ru": "Тип '{name}' параметра записи или удаления – составной тип без пустого значения: "
              "в составе такого параметра должно быть Неопределено, серверная компиляция упадет "
              "с 'The type composition of parameter ... must contain \"Undefined\" type'. "
              "Добавьте пустое значение в состав: '{name}|?'.",
        "en": "Type '{name}' of a write or delete parameter – a union without the empty value: "
              "the type composition of such a parameter must contain Undefined, the server-side "
              "compilation will fail with 'The type composition of parameter ... must contain "
              "\"Undefined\" type'. Add the empty value to the set: '{name}|?'.",
    },
    "yaml/union-needs-nullable.report": {
        "ru": "Тип '{name}' параметра запроса отчета – составной тип без пустого значения: "
              "значение по умолчанию для него не строится, серверная компиляция упадет с 'Не "
              "указано значение по умолчанию для параметра'. Добавьте пустое значение в "
              "состав: '{name}|?'{default}.",
        "en": "Type '{name}' of a report query parameter – a union without the empty value: no "
              "default value is built for it, and the server-side compilation will fail: the "
              "default value of the parameter is not set. Add the empty value to the set: "
              "'{name}|?'{default}.",
    },
    "yaml/union-needs-nullable.input": {
        "ru": "Тип '{field}<{name}>' – составной аргумент без пустого значения: у поля ввода нет "
              "значения по умолчанию, серверная компиляция упадет с 'Parameter \"ТипДанных\" "
              "... must have a default value', и заданное полю Значение этого не меняет. "
              "Укажите '{field}<{name}|?>'.",
        "en": "Type '{field}<{name}>' – a union argument without the empty value: the input "
              "field has no default value, the server-side compilation will fail with "
              "'Parameter ... must have a default value', and a Value given to the field does "
              "not change that. Use '{field}<{name}|?>'.",
    },
}
i18n.register(MESSAGES)

#: The key whose presence next to `Type` gives the position a value of its own.
_DEFAULT_KEY = "ЗначениеПоУмолчанию"
#: A typed literal holds `Type` and `Value` side by side - see the module docstring.
_VALUE_KEY = "Значение"
#: The kind whose properties compile with any union - see the module docstring.
_TYPE_CONTRACT = "КонтрактТипа"
#: The sections whose items fail with a message of their own, by the message key.
_SECTIONS = {
    "operation": ("ПараметрыЗаписи", "ПараметрыУдаления"),
    "report": ("ПараметрыЗапроса",),
}


@lru_cache(maxsize=1)
def _section_keys() -> dict[str, str]:
    """{a spelling of a section key: the message key of its items}, both spellings."""
    out: dict[str, str] = {}
    for message, keys in _SECTIONS.items():
        for key in keys:
            for form in (*terms.key_forms(key), metamodel.english_name(key)):
                if form:
                    out[form] = message
    return out


dataset.register_reset(_section_keys.cache_clear)


def _section_items(root) -> dict[int, str]:
    """{id of a mapping: the message key} for the items of the sections of _SECTIONS."""
    keys = _section_keys()
    out: dict[int, str] = {}
    for mapping in _mapping_nodes(root):
        for key_node, value_node in mapping.value:
            if not isinstance(key_node, yaml.ScalarNode):
                continue
            message = keys.get(key_node.value)
            if message is None:
                continue
            for item in getattr(value_node, "value", ()) or ():
                if isinstance(item, yaml.MappingNode):
                    out[id(item)] = message
    return out


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


@rule("yaml/union-needs-nullable", "yaml/union-needs-nullable.title", "A",
      severity=Severity.ERROR)
def yaml_union_needs_nullable(source: SourceFile) -> Iterable[Diagnostic]:
    if source.kind != "yaml" or not _HAVE_YAML or "|" not in source.text:
        return
    data, err = _parsed(source)
    if err is not None or not _is_object(data):
        return
    kind = object_kind(data)
    if kind == _TYPE_CONTRACT:
        return
    root = _composed(source)
    if root is None:  # pragma: no cover - _parsed has already vetted the syntax
        return
    contract = kind == "КонтрактСущности"
    parameters = _parameter_mappings(root)
    sections = _section_items(root)
    for mapping in _mapping_nodes(root):
        if id(mapping) in parameters:
            continue
        entries = _scalar_entries(mapping)
        entry = entries.get("Тип")
        if entry is None or not isinstance(entry[1], yaml.ScalarNode):
            continue
        value_node = entry[1]
        if value_node.style in ("|", ">"):  # a block scalar is text, not a type
            continue
        value = value_node.value
        start, end = value_node.start_mark.index, value_node.end_mark.index
        plain = not value_node.style and source.text[start:end] == value
        quote = 1 if value_node.style in ("'", '"') else 0
        line = value_node.start_mark.line + 1
        column = value_node.start_mark.column + 1 + quote
        field = _YAML_INPUT_ANY_RE.match(value)
        if field is not None:
            # A value bound to the field does not help (see the module docstring), so the
            # guards of a declaration below do not apply to it.
            inner = field.group(2)
            if _plain_union(inner):
                yield Diagnostic(
                    source.rel, line, column + field.start(2),
                    "yaml/union-needs-nullable", Severity.ERROR,
                    i18n.t("yaml/union-needs-nullable.input", name=inner,
                           field=field.group(1)),
                    fix=TextEdit(start + field.end(2), start + field.end(2), "|?")
                    if plain else None,
                )
            continue
        if _DEFAULT_KEY in entries or _VALUE_KEY in entries or _is_required(entries):
            continue
        stripped = value.strip()
        if not _plain_union(stripped):
            continue
        type_key = entry[0].value
        default_key = _DEFAULT_KEY
        if type_key != "Тип":  # the file speaks English - so does the advice
            default_key = metamodel.english_name(_DEFAULT_KEY) or _DEFAULT_KEY
        section = sections.get(id(mapping))
        default = "" if contract or section == "operation" else i18n.t(
            "yaml/union-needs-nullable.or-default", key=default_key, type=type_key,
        )
        yield Diagnostic(
            source.rel, line, column,
            "yaml/union-needs-nullable", Severity.ERROR,
            i18n.t(f"yaml/union-needs-nullable.{section or 'union'}", name=stripped,
                   default=default),
            fix=TextEdit(end, end, "|?") if plain else None,
        )
