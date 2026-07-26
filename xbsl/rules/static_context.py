"""Tier C: what a static method may not touch - the object context of its own type.

The docs section "Статические методы элементов проекта" states both bans in one breath:
"Статические методы не могут использовать контекст объекта и обращения к этот" and "Из
статического метода нельзя вызывать обычные методы в данном модуле". A static method is
common to the whole type, so there is no instance behind it - the compiler rejects the
project rather than failing at runtime, which is why both rules are errors.

- code/this-in-static-method: the keyword `этот` inside the body of a static method. The
  method boundaries come from the AST (so a broken file is left to code/parse-error), the
  occurrences from the code tokens - a `этот` inside a lambda nested in a static method is
  in the same static context and counts, while one inside a comment does not.

- code/instance-call-from-static: a bare `Метод(...)` call of a method of the same owner
  declared without `статический`. Guards: a member call (`х.Метод()`) is not a bare one; a
  name bound anywhere in the module is skipped (a variable holding a lambda shadows the
  method); a name declared BOTH static and instance is skipped as well - the docs allow the
  pair when the signatures do not overlap, and the call may bind to the static one.

Both are judged per owner: the module itself, a structure and an enumeration declared in it
each have their own set of methods, and a sibling of another owner is not callable by a bare
name anyway. Both positions of a violation are reported exactly, and a static method that
keeps to its own context is silent.
"""

from __future__ import annotations

from collections.abc import Iterable, Iterator

from xbsl import i18n
from xbsl import parser as P
from xbsl.diagnostics import Diagnostic, Severity
from xbsl.engine import SourceFile, rule
from xbsl.lexer import linemap
from xbsl.parser import parse
from xbsl.rules._syntax import code_tokens
from xbsl.rules.enum_values import _shadowed_names

MESSAGES = {
    "code/this-in-static-method.title": {
        "ru": "Обращение к 'этот' в статическом методе",
        "en": "Access to '{n[этот]}' in a static method",
    },
    "code/this-in-static-method.found": {
        "ru": "Статический метод '{name}' обращается к 'этот': у него нет контекста "
              "объекта. Уберите модификатор 'статический' либо передайте значение "
              "параметром.",
        "en": "Static method '{name}' accesses '{n[этот]}': it has no object context. "
              "Drop the '{n[статический]}' modifier or pass the value as a parameter.",
    },
    "code/instance-call-from-static.title": {
        "ru": "Вызов обычного метода из статического",
        "en": "Instance method called from a static one",
    },
    "code/instance-call-from-static.found": {
        "ru": "Статический метод '{name}' вызывает обычный метод '{callee}' этого же "
              "модуля – из статического метода это запрещено. Сделайте '{callee}' "
              "статическим либо вызовите его у значения.",
        "en": "Static method '{name}' calls instance method '{callee}' of the same module – "
              "that is not allowed from a static method. Make '{callee}' static, or call it "
              "on a value.",
    },
}
i18n.register(MESSAGES)


def _owners(module: P.Module) -> Iterator[list[P.Method]]:
    """The method sets a bare name may resolve in: the module, and every structure or
    enumeration declared in it (each holds its own methods)."""
    yield [m for m in module.members if isinstance(m, P.Method)]
    for member in module.members:
        if isinstance(member, P.Structure):
            yield [m for m in member.members if isinstance(m, P.Method)]
        elif isinstance(member, P.Enum):
            yield list(member.methods)


def _static_module(source: SourceFile) -> P.Module | None:
    """The parsed module when it declares at least one static method, else None."""
    if source.kind != "xbsl":
        return None
    module, errors = parse(source)
    if errors:
        return None  # a broken file is code/parse-error territory
    for methods in _owners(module):
        if any(m.is_static for m in methods):
            return module
    return None


@rule(
    "code/this-in-static-method", "code/this-in-static-method.title", "C",
    severity=Severity.ERROR,
)
def this_in_static_method(source: SourceFile) -> Iterable[Diagnostic]:
    """`этот` inside a static method - the compiler rejects the project."""
    module = _static_module(source)
    if module is None:
        return
    toks = code_tokens(source)
    if not any(t.kind == "KEYWORD" and t.canonical == "THIS" for t in toks):
        return
    lm = linemap(source)
    for methods in _owners(module):
        for method in methods:
            if not method.is_static:
                continue
            for t in toks:
                if t.start < method.start:
                    continue
                if t.start >= method.end:
                    break
                if t.kind == "KEYWORD" and t.canonical == "THIS":
                    line, col = lm.linecol(t.start)
                    yield Diagnostic(
                        source.rel, line, col, "code/this-in-static-method",
                        Severity.ERROR,
                        i18n.t("code/this-in-static-method.found", name=method.name),
                    )


@rule(
    "code/instance-call-from-static", "code/instance-call-from-static.title", "C",
    severity=Severity.ERROR,
)
def instance_call_from_static(source: SourceFile) -> Iterable[Diagnostic]:
    """A bare call of an instance method of the same owner from a static method."""
    module = _static_module(source)
    if module is None:
        return
    toks = code_tokens(source)
    shadowed = _shadowed_names(toks)
    lm = linemap(source)
    n = len(toks)
    for methods in _owners(module):
        static_names = {m.name for m in methods if m.is_static}
        instance_names = {m.name for m in methods if not m.is_static} - static_names
        if not instance_names:
            continue
        for method in methods:
            if not method.is_static:
                continue
            for i, t in enumerate(toks):
                if t.start < method.start:
                    continue
                if t.start >= method.end:
                    break
                if t.kind != "IDENT" or t.value not in instance_names:
                    continue
                if t.value in shadowed:
                    continue
                if i and toks[i - 1].kind == "OP" and toks[i - 1].value in (".", "::"):
                    continue  # a member of another object, not a bare call
                if not (i + 1 < n and toks[i + 1].kind == "OP" and toks[i + 1].value == "("):
                    continue  # a method reference, not a call
                line, col = lm.linecol(t.start)
                yield Diagnostic(
                    source.rel, line, col, "code/instance-call-from-static",
                    Severity.ERROR,
                    i18n.t("code/instance-call-from-static.found",
                           name=method.name, callee=t.value),
                )
