"""Tier C: what may stand at MODULE level, outside every method body.

Only a constant may. The documentation says so from one side:
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
"""

from __future__ import annotations

from collections.abc import Iterable

from xbsl import i18n
from xbsl import parser as P
from xbsl.diagnostics import Diagnostic, Severity
from xbsl.engine import SourceFile, rule
from xbsl.lexer import linemap
from xbsl.parser import parse

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
