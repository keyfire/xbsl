"""Tier C: where a declaration may stand - the parser accepts it, the compiler does not.

Two placements the grammar allows and the compiler refuses, both from the declaration rules
of `topics/variable-declaration-statement`. Nothing caught either before a deploy, and a
refused build rolls the stand back to the previous one.

Module level (`code/module-var-not-const`). Only a constant may stand there. The
documentation says so from one side:
"Константа может быть объявлена только на уровне модуля"
(topics/variable-declaration-statement). The compiler says it from the other: a
`знч ИМЯ = "..."` written above the methods is answered with
"Выражения запрещено использовать вне тела метода", the apply fails and the stand
rolls back to the previous build.

The two statements are not the same claim, and it is the compiler's that the rule
enforces: a constant is initialized by an expression computed AT COMPILE TIME, while
`пер` / `знч` / `исп` need a running method to evaluate their initializer in - there is
no such place at module level, so the modifier alone decides the verdict.

The parser accepts all four modifiers there (the grammar rule is shared with an object
field), which is exactly why nothing caught this before the deploy. Reconnaissance: 288
modules of four corpora carry 36 module-level declarations and every one of them is
already `конст`, so the check costs nothing on written code.

A parameter's name (`code/param-redeclared`). The same page states
"Имя переменной не может совпадать с именем параметра метода", and `topics/name-scope`
shows the compiler's answer - "Переменная с именем Сумма уже определена в параметрах метода" -
on a `пер Сумма` written under `метод РассчитатьИтог(Сумма: Число)`. A method is one block
scope with its parameters inside it, and a nested block (a loop, a branch, `попытка`,
`область`) may not redeclare a name of an enclosing scope, so a `знч` inside a loop is
refused the same way. That is the case behind the rule: a parameter added to a method whose
loop already declared a `знч` of that name - the linter silent, the apply rolled back.

Judged: `знч` / `пер` / `исп` declarations in the method's own statement bodies at any
nesting, in both spellings (the parser reads the keywords through the lexer). Not judged,
and said here so that nobody widens the rule by analogy: a loop variable, a `поймать`
variable, a lambda parameter and a declaration inside a full-form lambda body
(`метод(...) -> ... ;`) that repeat a parameter's name - the documentation forbids those
too, but four corpora (1106 modules, 7462 methods with parameters) carry none of them and
no compiler run confirms the exact answer, so the rule keeps to the proven shape; the same
goes for a name that differs from the parameter only by letter case. A structure
constructor is not judged either: the parser keeps no body for it.
"""

from __future__ import annotations

import re
from collections.abc import Iterable

from xbsl import i18n
from xbsl import parser as P
from xbsl.diagnostics import Diagnostic, Severity
from xbsl.engine import SourceFile, rule
from xbsl.lexer import linemap
from xbsl.parser import parse
from xbsl.rules.return_mismatch import _methods

MESSAGES = {
    "code/module-var-not-const.title": {
        "ru": "Объявление уровня модуля не конст",
        "en": "A module-level declaration that is not a constant",
    },
    "code/module-var-not-const.found": {
        "ru": "'{kind} {name}' стоит на уровне модуля, вне тела метода – там живёт только "
              "'{n[конст]}', и компилятор отвечает \"Выражения запрещено использовать вне "
              "тела метода\" (применение сборки падает, стенд откатывается на прежнюю "
              "сборку). Значение константы вычисляется при компиляции; если нужно "
              "вычислять его в работе, перенесите объявление в метод.",
        "en": "'{kind} {name}' stands at module level, outside any method body – only "
              "'{n[конст]}' lives there, and the compiler answers \"an expression is not "
              "allowed outside a method body\" (the apply fails and the stand rolls back "
              "to the previous build). A constant is computed at compile time; when the "
              "value has to be computed at run time, move the declaration into a method.",
    },
    "code/param-redeclared.title": {
        "ru": "Переобъявление параметра метода",
        "en": "A method parameter re-declared in the body",
    },
    "code/param-redeclared.found": {
        "ru": "'{kind} {name}' повторяет имя параметра метода '{method}' (строка {line}) – "
              "параметр входит в область видимости всего тела метода, вложенные блоки "
              "включительно, и компилятор отвечает \"Переменная с именем {name} уже "
              "определена\" (применение сборки падает, стенд откатывается на прежнюю "
              "сборку). Переименуйте переменную или присваивайте значение самому параметру.",
        "en": "'{kind} {name}' repeats the name of a parameter of method '{method}' "
              "(line {line}) – the parameter is in scope through the whole method body, "
              "nested blocks included, and the compiler answers \"a variable named {name} "
              "is already defined\" (the apply fails and the stand rolls back to the "
              "previous build). Rename the variable, or assign to the parameter itself.",
    },
}
i18n.register(MESSAGES)

#: The modifier as it is written, by the canonical kind the parser reports.
_SPELLING = {"VAL": "знч", "VAR": "пер", "USE": "исп"}


@rule("code/module-var-not-const", "code/module-var-not-const.title", "C",
      severity=Severity.ERROR)
def module_var_not_const(source: SourceFile) -> Iterable[Diagnostic]:
    """A module-level `пер` / `знч` / `исп` - only a constant may stand there."""
    if source.kind != "xbsl":
        return
    module, _errors = parse(source)
    fields = [
        member for member in module.members
        if isinstance(member, P.ObjectField) and member.kind in _SPELLING
    ]
    if not fields:
        return
    lm = linemap(source)
    for member in fields:
        line, col = lm.linecol(member.start)
        yield Diagnostic(
            source.rel, line, col, "code/module-var-not-const", Severity.ERROR,
            i18n.t("code/module-var-not-const.found",
                   kind=_SPELLING[member.kind], name=member.name),
        )


# The declaration head as written: the modifier and the name (`знч Итог`, `val Total`).
_DECL_HEAD = re.compile(r"(\w+)\s+(\w+)")


def _local_declarations(stmts: list[P.Stmt]) -> Iterable[P.VarDecl]:
    """The `знч` / `пер` / `исп` declarations of the statement bodies, nested blocks included.

    Lambdas are expressions and are never entered: a full-form lambda body is a scope of
    its own, and the rule does not judge it (see the module docstring).
    """
    for st in stmts:
        if isinstance(st, P.VarDecl):
            yield st
        elif isinstance(st, P.If):
            for _cond, body in st.branches:
                yield from _local_declarations(body)
            if st.else_body is not None:
                yield from _local_declarations(st.else_body)
        elif isinstance(st, P.Case):
            for when in st.whens:
                yield from _local_declarations(when.body)
            if st.else_body is not None:
                yield from _local_declarations(st.else_body)
        elif isinstance(st, (P.While, P.ForEach, P.ForTo, P.Scope)):
            yield from _local_declarations(st.body)
        elif isinstance(st, P.Try):
            yield from _local_declarations(st.body)
            for _var, _type, body in st.catches:
                yield from _local_declarations(body)
            if st.finally_body is not None:
                yield from _local_declarations(st.finally_body)


@rule("code/param-redeclared", "code/param-redeclared.title", "C", severity=Severity.ERROR)
def param_redeclared(source: SourceFile) -> Iterable[Diagnostic]:
    """A local `знч` / `пер` / `исп` with the name of the method's own parameter."""
    if source.kind != "xbsl":
        return
    module, errors = parse(source)
    if errors:
        return  # a broken file is code/parse-error territory
    lm = linemap(source)
    for method in _methods(module):
        if not method.params:
            continue
        params = {p.name: p for p in method.params}
        for decl in _local_declarations(method.body):
            param = params.get(decl.name)
            if param is None:
                continue
            # The finding sits on the NAME, the way the unused-local rule anchors its own;
            # the modifier is quoted as the source spells it, not by the canonical kind.
            head = _DECL_HEAD.match(source.text, decl.start)
            kind = head.group(1) if head else _SPELLING.get(decl.kind, decl.kind)
            line, col = lm.linecol(head.start(2) if head else decl.start)
            param_line, _param_col = lm.linecol(param.start)
            yield Diagnostic(
                source.rel, line, col, "code/param-redeclared", Severity.ERROR,
                i18n.t("code/param-redeclared.found",
                       kind=kind, name=decl.name, method=method.name, line=param_line),
            )
