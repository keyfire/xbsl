"""A component property COMPUTED by an expression is not assignable from code.

The platform refuses `Component.Property = value` when the yaml computes that property
(`Height: =Common.IsMobile()?820:528`): it answers "Cannot set the value of property ...
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
from pathlib import Path

from xbsl import i18n
from xbsl.diagnostics import Diagnostic, Severity
from xbsl.engine import SourceFile, make_source, rule
from xbsl.lexer import Token
from xbsl.rules._syntax import code_tokens
from xbsl.rules.yaml_schema import _composed, _mapping_nodes, _scalar_entries, yaml

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
