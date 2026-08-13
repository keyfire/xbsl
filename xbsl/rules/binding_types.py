"""Tier D: a nullable method binding on a component property that has no empty value.

The yaml/binding-needs-auto rule. "Not set" for a component property is the `Авто` value,
not `Неопределено`: the palette declares properties as unions WITHOUT the empty value (the
card's background is `Авто|Цвет|Url|ДвоичныйОбъект.Ссылка`), and a nullable member is a
separate, explicit flag of the schema. A binding `Свойство: =Метод()` whose method is
declared `(): Цвет?` compiles, deploys and even looks right on the screen - the background
is simply "not set" - but the client registers an error on EVERY recomputation of the
binding, and the records go to the server log, invisible in the browser console.

The live case (2026-08): three cards of a live project returned the empty value from a
hover-background binding; the client log had accumulated 1866 records of the
"Неожиданное значение" error pointing at the binding's yaml coordinate before
anyone noticed. The neighbouring bindings of nullable-typed properties (`Изображение`,
declared with the nullable flag) produced none - the flag in the schema is exactly the
boundary of the defect.

What is judged - the narrow slice with both sides known exactly:

- the binding value is a bare call of a method of the same component (`=Метод()` - no
  arguments, no module qualifier);
- the paired module declares that method with an explicit nullable return type (an
  alternative carries `?`);
- the property is a TYPED property of a palette component, its union has NO nullable flag
  and DOES carry `Авто` - so the advice ("declare `Авто|Тип` and return `Авто`") is exactly
  right. A property without `Авто` in the union is skipped rather than guessed.

Everything else is silence by design: a binding with arguments, a cross-module call, a
ternary or any other expression (the result type is not written down), a property of a
project component (its own `Свойства` section is a future slice), an English-spelled key
the dictionaries cannot map. A schema generated before the nullable flag existed switches
the rule off entirely - judging against it would flag legal bindings of nullable
properties.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from functools import lru_cache

from xbsl import dataset, i18n, uischema
from xbsl.diagnostics import Diagnostic, Severity
from xbsl.engine import SourceFile, rule
from xbsl.rules._syntax import code_tokens, signatures, type_expr
from xbsl.rules.component_props import _markup_nodes, _type_value
from xbsl.rules.yaml_schema import (
    _HAVE_YAML,
    _composed,
    _is_object,
    _parsed,
    _scalar_entries,
    yaml,
)

MESSAGES = {
    "yaml/binding-needs-auto.title": {
        "ru": "Биндинг свойства возвращает Неопределено вместо Авто",
        "en": "A property binding returns the empty value instead of Auto",
    },
    "yaml/binding-needs-auto.nullable": {
        "ru": "Метод '{method}' объявлен '{rtype}', а свойство '{prop}' компонента "
              "'{component}' ({union}) Неопределено не принимает – клиент регистрирует "
              "'Неожиданное значение \"Неопределено\"' на каждом пересчёте биндинга (ошибки "
              "копятся в серверном логе, в консоли браузера их не видно). 'Не задано' – это "
              "значение Авто: объявите '{method}(): Авто|{base}' и возвращайте Авто.",
        "en": "Method '{method}' is declared '{rtype}', while property '{prop}' of component "
              "'{component}' ({union}) does not accept the empty value – the client registers "
              "an \"unexpected Undefined value\" error on every recomputation of the binding "
              "(the errors pile up in the server log, invisible in the browser console). "
              "\"Not set\" is the {n[Авто]} value: declare '{method}(): {n[Авто]}|{base}' and "
              "return {n[Авто]}.",
    },
}
i18n.register(MESSAGES)

#: A binding that is a bare call of a local method: `=Метод()`, spaces tolerated.
_BARE_CALL_RE = re.compile(r"^\s*=\s*([^\W\d]\w*)\s*\(\s*\)\s*$", re.UNICODE)

#: The union member that names the "not set" value of a component property.
_AUTO_NAMES = ("Авто", "Auto")


@lru_cache(maxsize=1)
def _prop_table() -> dict[str, dict[str, tuple[str, ...]]]:
    """{component: {property: union}} for judgeable properties only.

    A property enters the table when its union carries `Авто` and the record has no
    nullable flag - exactly the shape the rule flags a nullable binding against. The whole
    table is empty when the schema predates the nullable flag: an old schema cannot tell a
    nullable property from a plain one, and judging against it would report legal bindings.
    """
    schema = dataset.load_ui_schema()
    if not schema:
        return {}
    components = schema.get("components") or {}
    if not any(
        prop.get("nullable")
        for record in components.values()
        for prop in (record.get("props") or {}).values()
    ):
        return {}  # data older than the nullable flag - see the docstring
    table: dict[str, dict[str, tuple[str, ...]]] = {}
    for component, record in components.items():
        props: dict[str, tuple[str, ...]] = {}
        for prop, rec in (record.get("props") or {}).items():
            types = tuple(rec.get("types") or ())
            if rec.get("nullable") or not any(t in _AUTO_NAMES for t in types):
                continue
            props[prop] = types
        if props:
            table[component] = props
    return table


dataset.register_reset(_prop_table.cache_clear)


def _pair_stem(rel: str) -> str:
    slash = rel.replace("\\", "/")
    return slash[: slash.rfind(".")] if "." in slash.rsplit("/", 1)[-1] else slash


def _alt_nullable(alt: list) -> bool:
    """A top-level `?` in the alternative - one inside `<...>` belongs to a generic
    argument (`Массив<Булево?>` is a plain collection, not a nullable return)."""
    depth = 0
    for t in alt:
        if t.kind != "OP":
            continue
        if t.value == "<":
            depth += 1
        elif t.value == ">":
            depth -= 1
        elif t.value == ">>":
            depth -= 2
        elif t.value == "?" and depth == 0:
            return True
    return False


def _nullable_returns(source: SourceFile) -> dict[str, str]:
    """{method name: return type text} for methods declared with a nullable return."""
    toks = code_tokens(source)
    out: dict[str, str] = {}
    for sig in signatures(toks):
        if sig.return_type_start is None:
            continue
        te = type_expr(toks, sig.return_type_start)
        if te is None:
            continue
        if any(_alt_nullable(alt) for alt in te.alternatives):
            out[sig.name.value] = "".join(t.value for t in te.toks)
    return out


def _binding_mapper(source: SourceFile) -> dict | None:
    """The map phase: a yaml contributes its bare-call bindings of judgeable properties,
    a module the nullable-returning methods - the reduce joins the pair."""
    if source.kind == "xbsl":
        returns = _nullable_returns(source)
        if not returns:
            return None  # nothing a yaml ref could join with
        return {"k": "x", "stem": _pair_stem(source.rel), "returns": returns}
    if source.kind != "yaml" or not _HAVE_YAML:
        return None
    table = _prop_table()
    if not table or "=" not in source.text:
        return None
    data, err = _parsed(source)
    if err is not None or not _is_object(data):
        return None
    root = _composed(source)
    if root is None:  # pragma: no cover - _parsed has already vetted the syntax
        return None
    refs: list[list] = []
    for mapping in _markup_nodes(root):
        type_node = _type_value(mapping)
        if type_node is None:
            continue
        component = uischema.canonical_component(type_node.value.split("<", 1)[0].strip())
        props = table.get(component)
        if props is None:
            continue  # a project component or no palette record - a future slice
        for key, (key_node, value_node) in _scalar_entries(mapping).items():
            if not isinstance(value_node, yaml.ScalarNode) or value_node.style in ("|", ">"):
                continue
            union = props.get(uischema.canonical_property(key))
            if union is None:
                continue
            m = _BARE_CALL_RE.match(value_node.value)
            if m is None:
                continue
            quote = 1 if value_node.style in ("'", '"') else 0
            refs.append([
                key_node.value, component, m.group(1), "|".join(union),
                value_node.start_mark.line + 1,
                value_node.start_mark.column + 1 + quote,
            ])
    if not refs:
        return None
    return {"k": "y", "stem": _pair_stem(source.rel), "refs": refs}


@rule(
    "yaml/binding-needs-auto", "yaml/binding-needs-auto.title", "D",
    scope="project", severity=Severity.WARNING, mapper=_binding_mapper,
)
def binding_needs_auto(facts: dict[str, dict]) -> Iterable[Diagnostic]:
    returns_by_stem: dict[str, dict[str, str]] = {}
    for fact in facts.values():
        if fact["k"] == "x":
            returns_by_stem[fact["stem"]] = fact["returns"]
    for rel, fact in facts.items():
        if fact["k"] != "y":
            continue
        returns = returns_by_stem.get(fact["stem"])
        if not returns:
            continue  # no paired module, or it declares no nullable returns
        for prop, component, method, union, line, col in fact["refs"]:
            rtype = returns.get(method)
            if rtype is None:
                continue
            base = rtype.rstrip("?").rstrip("|")
            yield Diagnostic(
                rel, line, col, "yaml/binding-needs-auto", Severity.WARNING,
                i18n.t(
                    "yaml/binding-needs-auto.nullable",
                    method=method, rtype=rtype, prop=prop, component=component,
                    union=union, base=base,
                ),
            )
