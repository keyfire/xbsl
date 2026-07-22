"""Values of yaml properties: enumerations of the ui schema and literal-typed nodes.

Three rules live here:

- yaml/unknown-enum-value (tier D) – a value outside the property's enumeration;
- yaml/no-expression-in-literal (tier A) – a binding inside a node the platform wants literal;
- yaml/bare-object-value (tier D) – a bare word where a literal or a binding is expected.

The yaml/unknown-enum-value rule. A component property whose type is an enumeration accepts
only the elements of that enumeration; anything else is rejected when the build is applied –
`Неизвестный элемент "Анонимный" перечисления "РежимАутентификации"` (a compiler message
recorded on a probe), the class that also covers the alignment gotcha: the horizontal axis
has `Начало|Центр|Конец|ПоШирине` while the vertical one has `Верх|Центр|Низ|ПоБазовойЛинии`,
so a `ВыравниваниеСодержимогоПоВертикали: Конец` copied over from a neighbouring property
does not exist.

The value lists come from the ui schema (uischema.json, `tools/extract_uischema.py`), which
is exactly what the compiler validates against: every property carries its union of types
plus the resolved `enum` list.

Zero-false-positive guards:

- a node is judged only when its `Тип` names a component the schema knows (the generic head
  is taken: `ПолеВвода<Строка>` -> `ПолеВвода`); a project component is skipped, so its own
  properties can never be mistaken for the platform's;
- a property is judged only when EVERY member of its type union is either an enumeration of
  the schema or the literal `Авто` – the only non-enumeration member the schema uses next to
  an `enum` (354 occurrences, no other). One `Строка`/`Булево`/`Число` member and the
  property is skipped: such a value may be anything;
- a binding (`=...`), an interpolation (`%...`), a qualified value
  (`ВыравниваниеПоГоризонтали.Центр` – the enumeration spelled out) and a non-scalar are
  skipped, as is a block scalar (text, not a value).

Corpus survey before the rule was written: 2619 component nodes, 2545 property values judged,
zero findings – deployed code follows the schema, so the rule guards against regressions and
against a value invented from a neighbouring axis.

The yaml/no-expression-in-literal rule. A value object nested in a component property –
`Шрифт: {Тип: АбсолютныйШрифт, ...}`, `ЦветФона: {Тип: АбсолютныйЦвет, ...}` – must be spelled
out literally: a binding inside it is rejected when the build is applied. Measured on the same
probe, with two different wordings from the compiler:

    ФормаШрифтПолужирный.yaml [20:37]: Свойство 'Полужирный' не поддерживает вычисляемое выражение
    ФормаЦветВыражением.yaml  [13:17]: Значение типа АбсолютныйЦвет должно быть описано в виде
                                       литерала

The restriction is about the nesting, not about a particular property: `Размер` was the known
case, `Полужирный` behaves the same. The way out is to compute the WHOLE object – the control
form with `Шрифт: =ШрифтНадписи()` applied cleanly.

Which types are literal cannot be derived from the data – checked in all three sources: the ui
schema describes components only, `stdlib.json` keeps a flat name list, and the metamodel has no
such flag (it does hold `AbsoluteFontModel`, but nothing marking it literal). So the set is an
explicit list of types proven by the compiler, extended as new ones are proven. Judging by "not
a component" instead would be wrong: `ОбычнаяКоманда`, `ЗаголовокСекции` and project components
are not in the schema either, and bindings inside them are legal and common (39 in the corpus).
Inside the two listed types the corpus has 687 nodes and not a single binding – the rule guards
a convention the code already follows.

The yaml/bare-object-value rule. A property whose type union includes `Объект` (`Значение` of a
label, `ДополнительныеДанные`, ...) takes a quoted literal, an `=` binding or a `$` reference
to a localized string (`$ЛокализованныеСтроки.Заголовок`, qualified
`$НС::ЛокализованныеСтроки.Ключ` – the documented identifier syntax, and the platform's own
editor writes such values when a text is localized); a bare word is rejected outright. The probe settled what the backlog had guessed wrong: the platform does
NOT read the bare word as an expression to be resolved – `Значение: Титул` fails even when
`Титул` is a declared property of that very form, with exactly the message an unknown name gets:

    ФормаГолоеИмяРеквизита.yaml   [16:21]: Ожидалось Неопределено или указание типа
    ФормаГолоеНеизвестноеИмя.yaml [16:21]: (the same)

while `Значение: =Титул` and `Значение: "Титул"` in the same project applied cleanly. So no name
resolution is needed and the rule stays file-scoped: the shape of the value decides. Values that
yaml reads as a number or a boolean are left alone (a plain `42` is not a word), as are block
scalars. The corpus has 409 quoted values and 71 bindings on such properties and not a single
bare word – the rule guards a convention the code already follows. The compiler points at the
property key; the rule points at the value, where the fix goes.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from functools import lru_cache

from xbsl import dataset, i18n
from xbsl.diagnostics import Diagnostic, Severity
from xbsl.engine import SourceFile, rule
from xbsl.rules.yaml_schema import (
    _composed,
    _HAVE_YAML,
    _is_object,
    _mapping_nodes,
    _parsed,
    _scalar_entries,
)

if _HAVE_YAML:
    import yaml

MESSAGES = {
    "yaml/unknown-enum-value.title": {
        "ru": "Недопустимое значение свойства",
        "en": "Invalid property value",
    },
    "yaml/unknown-enum-value.unknown": {
        "ru": "Значение '{value}' недопустимо для свойства '{prop}' компонента '{component}' – "
              "применение сборки отвергнет его как неизвестный элемент перечисления. "
              "Допустимые значения: {allowed}.",
        "en": "Value '{value}' is not allowed for property '{prop}' of component "
              "'{component}' – applying the build rejects it as an unknown enumeration "
              "element. Allowed values: {allowed}.",
    },
    "yaml/bare-object-value.title": {
        "ru": "Голое значение у свойства-объекта",
        "en": "A bare value on an object property",
    },
    "yaml/bare-object-value.bare": {
        "ru": "Значение свойства '{prop}' записано голым словом – платформа ждёт здесь литерал "
              "с указанием типа либо выражение, применение упадёт 'Ожидалось Неопределено или "
              "указание типа'. Текст берётся в кавычки (\"{value}\"), биндинг начинается с "
              "'=' (={value}).",
        "en": "Property '{prop}' carries a bare value – the platform expects a literal with its "
              "type or an expression here, applying the build will fail with 'Ожидалось "
              "Неопределено или указание типа'. Quote the text (\"{value}\") or start a binding "
              "with '=' (={value}).",
    },
    "yaml/no-expression-in-literal.title": {
        "ru": "Выражение внутри литерального значения",
        "en": "An expression inside a literal value",
    },
    "yaml/no-expression-in-literal.binding": {
        "ru": "Свойство '{prop}' узла типа '{type}' задано выражением – платформа принимает "
              "здесь только литерал, применение сборки упадёт ('не поддерживает вычисляемое "
              "выражение'). Вычислять нужно ВЕСЬ объект: '{owner}: =Выражение'.",
        "en": "Property '{prop}' of a '{type}' node is given as an expression – the platform "
              "accepts only a literal here, applying the build will fail ('does not support a "
              "computed expression'). Compute the WHOLE object instead: '{owner}: =Выражение'.",
    },
}
i18n.register(MESSAGES)

#: Union members that are a VALUE rather than a type with an open set of values.
_LITERAL_MEMBERS = frozenset({"Авто"})

#: Types whose nested node the compiler demands literally (proven on a probe). Extend only
#: with types shown to behave the same - see the module docstring on why the data cannot say.
_LITERAL_TYPES = frozenset({"АбсолютныйШрифт", "АбсолютныйЦвет"})


def _allowed_values(prop: dict, enums: dict) -> frozenset[str] | None:
    """The value set of a purely enumerated property, or None when it is not one."""
    allowed = set(prop.get("enum") or ())
    if not allowed:
        return None
    for member in prop.get("types") or ():
        name = str(member).strip().rstrip("?")
        if not name:
            continue
        if name in _LITERAL_MEMBERS:
            allowed.add(name)
        elif name in enums:
            allowed.update(enums[name].get("values") or ())
        else:
            return None  # a real type among the members – the value may be anything
    return frozenset(allowed)


@lru_cache(maxsize=1)
def _enumerated_props() -> tuple[dict[str, dict[str, frozenset[str]]], "re.Pattern | None"]:
    """({component: {property: allowed values}}, a key regex), both empty without a schema.

    Built once: resolving the dataset is not free (it walks the installed data plugins), and
    the value sets are the same for every file. The regex is the fast path – composing the
    node graph costs a second, pure-python parse of the file, so it only happens when the
    text carries at least one key the rule could judge.
    """
    schema = dataset.load_ui_schema()
    if not schema:
        return {}, None
    enums = schema.get("enums") or {}
    table: dict[str, dict[str, frozenset[str]]] = {}
    names: set[str] = set()
    for component, rec in (schema.get("components") or {}).items():
        judged = {}
        for prop, info in (rec.get("props") or {}).items():
            allowed = _allowed_values(info, enums)
            if allowed is not None:
                judged[prop] = allowed
                names.add(prop)
        if judged:
            table[component] = judged
    if not names:
        return {}, None
    keys_re = re.compile(
        r"(?m)^[ \t]*(?:-[ \t]+)?(?:%s)[ \t]*:" % "|".join(sorted(map(re.escape, names)))
    )
    return table, keys_re


@rule("yaml/unknown-enum-value", "yaml/unknown-enum-value.title", "D", severity=Severity.ERROR)
def unknown_enum_value(source: SourceFile) -> Iterable[Diagnostic]:
    if source.kind != "yaml" or not _HAVE_YAML:
        return
    table, keys_re = _enumerated_props()
    if keys_re is None or not keys_re.search(source.text):
        return  # no ui schema, or nothing in this file the rule could judge
    data, err = _parsed(source)
    if err is not None or not _is_object(data):
        return
    root = _composed(source)
    if root is None:  # pragma: no cover - _parsed has already vetted the syntax
        return
    for mapping in _mapping_nodes(root):
        entries = _scalar_entries(mapping)
        type_entry = entries.get("Тип")
        if type_entry is None or not isinstance(type_entry[1], yaml.ScalarNode):
            continue
        component = type_entry[1].value.split("<", 1)[0].strip()
        props = table.get(component)
        if props is None:
            continue  # not a platform component (a project one, a data type, a generic)
        for key, (_key_node, value_node) in entries.items():
            allowed = props.get(key)
            if allowed is None or not isinstance(value_node, yaml.ScalarNode):
                continue
            if value_node.style in ("|", ">"):
                continue
            value = value_node.value.strip()
            if not value or value[0] in "=%" or value in allowed:
                continue
            if value.rsplit(".", 1)[-1] in allowed:
                continue  # a qualified value: ВыравниваниеПоГоризонтали.Центр
            yield Diagnostic(
                source.rel,
                value_node.start_mark.line + 1, value_node.start_mark.column + 1,
                "yaml/unknown-enum-value", Severity.ERROR,
                i18n.t(
                    "yaml/unknown-enum-value.unknown",
                    value=value, prop=key, component=component,
                    allowed=", ".join(sorted(allowed)),
                ),
            )


@rule(
    "yaml/no-expression-in-literal", "yaml/no-expression-in-literal.title", "A",
    severity=Severity.ERROR,
)
def no_expression_in_literal(source: SourceFile) -> Iterable[Diagnostic]:
    if source.kind != "yaml" or not _HAVE_YAML:
        return
    if not any(t in source.text for t in _LITERAL_TYPES):
        return  # the fast path: no literal-typed node in this file at all
    data, err = _parsed(source)
    if err is not None or not _is_object(data):
        return
    root = _composed(source)
    if root is None:  # pragma: no cover - _parsed has already vetted the syntax
        return
    for mapping in _mapping_nodes(root):
        entries = _scalar_entries(mapping)
        type_entry = entries.get("Тип")
        if (
            type_entry is None
            or not isinstance(type_entry[1], yaml.ScalarNode)
            or type_entry[1].value.strip() not in _LITERAL_TYPES
        ):
            continue
        owner = _owner_key(root, mapping)
        for key, (_key_node, value_node) in entries.items():
            if key == "Тип" or not isinstance(value_node, yaml.ScalarNode):
                continue
            if value_node.style in ("|", ">") or not value_node.value.strip().startswith("="):
                continue
            yield Diagnostic(
                source.rel,
                value_node.start_mark.line + 1, value_node.start_mark.column + 1,
                "yaml/no-expression-in-literal", Severity.ERROR,
                i18n.t(
                    "yaml/no-expression-in-literal.binding",
                    prop=key, type=type_entry[1].value.strip(), owner=owner,
                ),
            )


def _owner_key(root, target) -> str:
    """The key the node hangs on (`Шрифт`, `ЦветФона`), or `Значение` when unknown.

    The message tells the author to compute the whole object, so it needs the name of the
    property to write the binding on; the graph is walked from the root because a node does
    not know its parent.
    """
    for mapping in _mapping_nodes(root):
        for key_node, value_node in mapping.value:
            if value_node is target and isinstance(key_node, yaml.ScalarNode):
                return key_node.value
    return "Значение"


@rule("yaml/bare-object-value", "yaml/bare-object-value.title", "D", severity=Severity.ERROR)
def bare_object_value(source: SourceFile) -> Iterable[Diagnostic]:
    if source.kind != "yaml" or not _HAVE_YAML:
        return
    table = _object_props()
    if not table:
        return  # no ui schema – the property types are unknown
    data, err = _parsed(source)
    if err is not None or not _is_object(data):
        return
    root = _composed(source)
    if root is None:  # pragma: no cover - _parsed has already vetted the syntax
        return
    for mapping in _mapping_nodes(root):
        entries = _scalar_entries(mapping)
        type_entry = entries.get("Тип")
        if type_entry is None or not isinstance(type_entry[1], yaml.ScalarNode):
            continue
        props = table.get(type_entry[1].value.split("<", 1)[0].strip())
        if not props:
            continue
        for key, (_key_node, value_node) in entries.items():
            if key not in props or not isinstance(value_node, yaml.ScalarNode):
                continue
            if value_node.style:  # quoted or a block scalar - a literal, not a bare word
                continue
            value = value_node.value.strip()
            if not value or value[0] in "=$":
                continue  # '=' opens a binding, '$' a localized-string reference
            if _yaml_scalar_is_word(value_node) is False:
                continue  # a number/boolean/null - yaml reads it as a typed literal
            yield Diagnostic(
                source.rel,
                value_node.start_mark.line + 1, value_node.start_mark.column + 1,
                "yaml/bare-object-value", Severity.ERROR,
                i18n.t("yaml/bare-object-value.bare", prop=key, value=value),
            )


@lru_cache(maxsize=1)
def _object_props() -> dict[str, frozenset[str]]:
    """{component: properties whose type union includes Объект}, empty without a schema."""
    schema = dataset.load_ui_schema()
    if not schema:
        return {}
    table = {}
    for component, rec in (schema.get("components") or {}).items():
        names = frozenset(
            prop for prop, info in (rec.get("props") or {}).items()
            if any(str(t).strip() == "Объект" for t in (info.get("types") or ()))
        )
        if names:
            table[component] = names
    return table


def _yaml_scalar_is_word(node) -> bool:
    """Whether a plain scalar is a word rather than a number/boolean/null literal."""
    return isinstance(yaml.safe_load(node.value), str)
