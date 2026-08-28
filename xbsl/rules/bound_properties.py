"""A component property COMPUTED by an expression is not assignable from code.

The platform refuses `Component.Property = value` when the yaml computes that property
(`Height: =Common.IsNarrowScreen()?820:528`): it answers "Cannot set the value of property ...
specified by expression". The refusal is easy to miss because such an assignment usually
sits inside a `try/catch` cascade - then nothing is raised and nothing happens, and the
symptom is a layout that quietly ignores the code.

A DATA BINDING is a different thing and is left alone. `Value: =Record.Value` is a plain
path into the form's data, and the documentation says such a link is two-way for an
editable component ("the data link is bidirectional or unidirectional depending on
ReadOnly") - writing to it is the ordinary way an editor gives the value back. So the
rule judges the SHAPE of the expression: a bare path is a binding, anything computed - a
call, a ternary, arithmetic - is not assignable.

The pair is read from the disk neighbour: a form's components are declared in the yaml
next to the module, so one file plus its pair is enough and the rule stays file-scope -
the editor then reports it on every keystroke, not only on a project run.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from functools import lru_cache
from pathlib import Path

from xbsl import dataset, i18n, terms
from xbsl.diagnostics import Diagnostic, Severity
from xbsl.engine import SourceFile, make_source, rule
from xbsl.lexer import Token
from xbsl.rules._syntax import code_tokens, signatures
from xbsl.rules.environment import _pair_stem
from xbsl.rules.yaml_schema import (
    _composed,
    _mapping_nodes,
    _parsed,
    _scalar_entries,
    object_kind,
    yaml,
)

MESSAGES = {
    "code/bound-property-assign.title": {
        "ru": "Присваивание свойству, заданному выражением",
        "en": "Assigning to a property specified by an expression",
    },
    "code/bound-property-assign.msg": {
        "ru": "Свойство '{prop}' компонента '{name}' ВЫЧИСЛЯЕТСЯ выражением в разметке "
              "(строка {line}) – платформа отвергает присваивание такого свойства из кода "
              "(\"Cannot set the value of property ... specified by expression\"), а в "
              "попытка/поймать отказ не виден вовсе. Либо задайте свойство литералом, либо "
              "меняйте то, от чего зависит выражение.",
        "en": "Property '{prop}' of component '{name}' is COMPUTED by an expression in the "
              "markup (line {line}) - the platform refuses to assign such a property from code "
              "(\"Cannot set the value of property ... specified by expression\"), and inside "
              "a try/catch the refusal is not visible at all. Either give the property a "
              "literal value, or change what the expression reads.",
    },
}
i18n.register(MESSAGES)

# The name of a component in the markup: the platform reads both spellings.
_NAME_KEYS = ("Имя", "Name")
# The root through which a form reaches its own components.
_COMPONENT_ROOTS = frozenset({"Компоненты", "Components"})
# A data binding: a bare path over the form's data (`=Запись.Значение`, `=Объект.Товар.Код`).
# Anything else - a call, a ternary, arithmetic, a literal - is a computed expression.
_DATA_PATH_RE = re.compile(
    r"=\s*[A-Za-zА-Яа-яЁё_][\wА-Яа-яЁё]*(?:\s*\??\.\s*[A-Za-zА-Яа-яЁё_][\wА-Яа-яЁё]*)*\s*$"
)


def _computed(expression: str) -> bool:
    """Is the expression computed (and therefore not assignable), not a data binding?"""
    return not _DATA_PATH_RE.match(expression.strip())


def _bound_properties(pair: Path) -> dict[str, dict[str, int]]:
    """Component name -> {property: markup line} for COMPUTED properties.

    The value is the LINE of the expression: the message names it, so the reader goes
    straight to the markup instead of searching for the property by eye.
    """
    try:
        if not pair.is_file():
            return {}
        source = make_source(pair, pair.read_bytes())
    except OSError:
        return {}
    root = _composed(source)
    if root is None:
        return {}
    found: dict[str, dict[str, int]] = {}
    for mapping in _mapping_nodes(root):
        entries = _scalar_entries(mapping)
        named = next((entries[key] for key in _NAME_KEYS if key in entries), None)
        if named is None or not isinstance(named[1], yaml.ScalarNode):
            continue
        name = named[1].value
        for prop, (_key, value) in entries.items():
            if not isinstance(value, yaml.ScalarNode):
                continue
            text = value.value.lstrip()
            if text.startswith("=") and _computed(text):
                found.setdefault(name, {})[prop] = value.start_mark.line + 1
    return found


def _assignment_target(toks: list[Token], i: int) -> tuple[str, str] | None:
    """`Компоненты.Кнопка.Видимость =` at the `=` token -> ("Кнопка", "Видимость").

    Only the access through the components root is judged. An event handler's `Источник`
    is the same component at runtime, but statically it is just a parameter - naming it
    here would mean guessing.
    """
    if i < 4:
        return None
    if toks[i].kind != "OP" or toks[i].value != "=":
        return None
    prop, dot, name, dot2, root = (
        toks[i - 1], toks[i - 2], toks[i - 3], toks[i - 4], toks[i - 5] if i >= 5 else None
    )
    if prop.kind != "IDENT" or dot.value != "." or name.kind != "IDENT" or dot2.value != ".":
        return None
    if root is None or root.kind != "IDENT" or root.value not in _COMPONENT_ROOTS:
        return None
    return name.value, prop.value


@rule("code/bound-property-assign", "code/bound-property-assign.title", "D",
      severity=Severity.WARNING)
def bound_property_assign(source: SourceFile) -> Iterable[Diagnostic]:
    """A property bound by an expression in the paired yaml must not be assigned in code."""
    if source.kind != "xbsl":
        return
    toks = code_tokens(source)
    if not toks:
        return
    bound: dict[str, dict[str, int]] | None = None
    for i, tok in enumerate(toks):
        if tok.kind != "OP" or tok.value != "=":
            continue
        # `==` reaches the rule as a single token, but `=` followed by `=` would not:
        # comparisons are not assignments, and neither are `+=`-style compounds.
        target = _assignment_target(toks, i)
        if target is None:
            continue
        if bound is None:  # the pair is read only when the module has a candidate
            bound = _bound_properties(Path(source.path).with_suffix(".yaml"))
        name, prop = target
        line = bound.get(name, {}).get(prop)
        if line is None:
            continue
        yield Diagnostic(
            source.rel, toks[i - 1].line, toks[i - 1].col, "code/bound-property-assign",
            Severity.WARNING,
            i18n.t("code/bound-property-assign.msg", prop=prop, name=name, line=line),
        )


# --- yaml/computed-binding-assigned ---------------------------------------------------------
#
# The cross-file half of the same defect (found live: every instance of one component
# bound a property with computed expressions while the component assigned it - the
# platform threw IllegalStateException on each run of that code). The in-form rule above cannot see it:
# the assignment lives in the COMPONENT's module and the binding at the INSTANCE in another
# file. What reconnaissance settled, and the rule encodes:
#
# - a bare `Prop = ...` is an assignment only at paren depth 0: the same spelling inside
#   a constructor call is a NAMED ARGUMENT, and two of the three raw corpus hits were
#   exactly that;
# - an instance the code CONSTRUCTS (`новый Кнопка(...)`) is a legal assignment target, and a
#   component may guard the expression-bound instances at runtime (the live corpus carries
#   exactly that pattern, with a comment saying so) - so one code construction anywhere
#   silences the pair;
# - an instance that binds the property with a bare path, a literal, or not at all is a
#   legal target too - the rule fires only when EVERY instance of the component binds the
#   property computed, which is how the live defect looked.

MESSAGES_CROSS = {
    "yaml/computed-binding-assigned.title": {
        "ru": "Вычисляемая связь свойства, которое компонент присваивает",
        "en": "A computed binding of a property the component assigns",
    },
    "yaml/computed-binding-assigned.msg": {
        "ru": "Свойство '{prop}' связано вычисляемым выражением, а компонент '{name}' "
              "ПРИСВАИВАЕТ его в своём модуле ({module}:{line}) – на присваивании платформа "
              "падает (IllegalStateException), то есть падает каждое срабатывание этого кода. "
              "Так связан каждый экземпляр компонента{more}. Свяжите свойство голым путём к "
              "реквизиту или задайте литералом – либо уберите присваивание в компоненте.",
        "en": "Property '{prop}' is bound by a computed expression while component '{name}' "
              "ASSIGNS it in its module ({module}:{line}) - the platform crashes on the "
              "assignment (IllegalStateException), i.e. every run of that code crashes. Every "
              "instance of the component is bound this way{more}. Bind the property with a "
              "bare path to an attribute or a literal - or drop the assignment in the "
              "component.",
    },
    "yaml/computed-binding-assigned.more": {
        "ru": "; таких мест ещё {count}",
        "en": "; {count} more such places",
    },
}
i18n.register(MESSAGES_CROSS)

_COMPONENT_KIND = "КомпонентИнтерфейса"
_PROPERTY_SECTIONS = ("Свойства", "Properties")


@lru_cache(maxsize=1)
def _component_kind_names() -> frozenset[str]:
    """Every spelling of the interface-component kind, from the platform dictionaries."""
    return frozenset({
        _COMPONENT_KIND,
        terms.kinds_table().get(_COMPONENT_KIND),
        terms.english(_COMPONENT_KIND, "types"),
    } - {None})


dataset.register_reset(_component_kind_names.cache_clear)


def _declared_properties(data: dict) -> list[str]:
    """Names of the properties a component declares, either spelling of the section."""
    out: list[str] = []
    for section in _PROPERTY_SECTIONS:
        for item in data.get(section) or []:
            if isinstance(item, dict):
                for key in _NAME_KEYS:
                    if isinstance(item.get(key), str):
                        out.append(item[key])
    return out


def _own_assignments(toks: list[Token]) -> dict[str, int]:
    """Name -> first line of a bare `Name = ...` STATEMENT of the module.

    Depth 0 only: the same spelling inside parentheses is a named argument. A name the
    method declares itself (a parameter, `пер`/`знч`) is the method's local, not the
    component's property - assigning it is free.
    """
    sigs = signatures(toks)
    spans: list[tuple[int, int, set[str]]] = []
    for number, sig in enumerate(sigs):
        end = sigs[number + 1].name.line if number + 1 < len(sigs) else 1 << 30
        spans.append((sig.name.line, end, {p.name.value for p in sig.params}))
    for i, tok in enumerate(toks):
        if tok.kind == "KEYWORD" and tok.canonical in ("VAR", "VAL") and i + 1 < len(toks):
            declared = toks[i + 1]
            if declared.kind == "IDENT":
                for span in spans:
                    if span[0] <= declared.line < span[1]:
                        span[2].add(declared.value)
    out: dict[str, int] = {}
    depth = 0
    for i, tok in enumerate(toks):
        if tok.kind == "OP" and tok.value in "([{":
            depth += 1
            continue
        if tok.kind == "OP" and tok.value in ")]}":
            depth = max(0, depth - 1)
            continue
        if depth or tok.kind != "IDENT" or tok.value in out:
            continue
        if i + 1 >= len(toks) or toks[i + 1].kind != "OP" or toks[i + 1].value != "=":
            continue
        prev = toks[i - 1] if i else None
        if prev is not None and prev.kind == "OP" and prev.value in (".", "?."):
            continue
        if prev is not None and prev.kind == "KEYWORD" and prev.canonical in ("VAR", "VAL"):
            continue
        if any(start <= tok.line < end and tok.value in names
               for start, end, names in spans):
            continue
        out[tok.value] = tok.line
    return out


def _cross_mapper(source: SourceFile) -> dict | None:
    """The map phase: a component yaml contributes its declared properties, a module its
    bare assignments and the components it constructs, any yaml - its instances and their
    computed-bound properties."""
    if source.kind == "xbsl":
        toks = code_tokens(source)
        if not toks:
            return None
        constructed = sorted({
            toks[i + 1].value
            for i, tok in enumerate(toks)
            if tok.kind == "KEYWORD" and tok.canonical == "NEW" and i + 1 < len(toks)
            and toks[i + 1].kind == "IDENT"
        })
        assigns = [[name, line] for name, line in _own_assignments(toks).items()]
        if not constructed and not assigns:
            return None
        return {"k": "x", "stem": _pair_stem(source.rel), "rel": source.rel,
                "assigns": assigns, "constructed": constructed}
    if source.kind != "yaml" or yaml is None:
        return None
    fact: dict = {}
    data, err = _parsed(source)
    if err is None and isinstance(data, dict) and object_kind(data) in _component_kind_names():
        name = next((data[k] for k in _NAME_KEYS if isinstance(data.get(k), str)), None)
        props = _declared_properties(data)
        if name and props:
            fact["comp"] = {"stem": _pair_stem(source.rel), "name": name, "props": props}
    root = _composed(source)
    if root is not None:
        counts: dict[str, int] = {}
        computed: list[list] = []
        for mapping in _mapping_nodes(root):
            entries = _scalar_entries(mapping)
            typed = next((entries[key] for key in ("Тип", "Type") if key in entries), None)
            if typed is None or not isinstance(typed[1], yaml.ScalarNode):
                continue
            head = typed[1].value.split("<", 1)[0].strip()
            counts[head] = counts.get(head, 0) + 1
            for _prop, (key, value) in entries.items():
                if not isinstance(value, yaml.ScalarNode):
                    continue
                text = (value.value or "").lstrip()
                if text.startswith("=") and _computed(text):
                    # The RAW spelling of the key: the component declares its properties in
                    # its own file's spelling, and both sides of one tree share it.
                    computed.append(
                        [head, key.value, value.start_mark.line + 1,
                         value.start_mark.column + 1])
        if counts:
            fact["inst"] = counts
        if computed:
            fact["computed"] = computed
    return fact or None


@rule(
    "yaml/computed-binding-assigned", "yaml/computed-binding-assigned.title", "D",
    scope="project", severity=Severity.WARNING, mapper=_cross_mapper,
)
def computed_binding_assigned(facts: dict[str, dict]) -> Iterable[Diagnostic]:
    """Every instance binds the property computed while the component assigns it."""
    modules: dict[str, dict] = {}
    constructed: set[str] = set()
    for fact in facts.values():
        if fact.get("k") == "x":
            modules[fact["stem"]] = fact
            constructed.update(fact["constructed"])
    instance_counts: dict[str, int] = {}
    computed_places: dict[tuple[str, str], list[tuple[str, int, int]]] = {}
    for rel, fact in facts.items():
        for head, count in (fact.get("inst") or {}).items():
            instance_counts[head] = instance_counts.get(head, 0) + count
        for head, prop, line, col in fact.get("computed") or ():
            computed_places.setdefault((head, prop), []).append((rel, line, col))
    for fact in facts.values():
        comp = fact.get("comp")
        if not comp or comp["name"] in constructed:
            continue
        module = modules.get(comp["stem"])
        if module is None:
            continue
        assigns = {name: line for name, line in module["assigns"] if name in comp["props"]}
        for prop, line in sorted(assigns.items()):
            places = sorted(computed_places.get((comp["name"], prop), []))
            if not places:
                continue
            if len(places) < instance_counts.get(comp["name"], 0):
                continue  # an instance without the computed binding is a legal target
            rel, at_line, at_col = places[0]
            more = (i18n.t("yaml/computed-binding-assigned.more", count=len(places) - 1)
                    if len(places) > 1 else "")
            yield Diagnostic(
                rel, at_line, at_col, "yaml/computed-binding-assigned", Severity.WARNING,
                i18n.t("yaml/computed-binding-assigned.msg", prop=prop, name=comp["name"],
                       module=module["rel"], line=line, more=more),
            )
