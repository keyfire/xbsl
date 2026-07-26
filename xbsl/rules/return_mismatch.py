"""Tier C: `возврат` must match the method signature.

A method with no return type must not return a value, and a method with a return type
must not use a bare `возврат` - the compiler rejects both, the linter reports them before
a deploy. Lambdas are their own context (their return type is not declared), and `Return`
lives only in statement bodies, so the walk never descends into expressions at all.
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
    "code/return-mismatch.title": {
        "ru": "Возврат не по сигнатуре метода",
        "en": "Return does not match the method signature",
    },
    "code/return-mismatch.value-in-void": {
        "ru": "Возврат значения в методе без типа возврата – объявите тип в сигнатуре",
        "en": "A value is returned from a method with no return type - declare it in the signature",
    },
    "code/return-mismatch.empty-in-typed": {
        "ru": "Пустой 'возврат' в методе с типом возврата {type}",
        "en": "A bare 'возврат' in a method with return type {type}",
    },
}
i18n.register(MESSAGES)


def _returns(stmts: list[P.Stmt], out: list[P.Return]) -> None:
    """Collect Return statements of the method's own bodies (lambdas are not entered:
    a Return can only sit in a statement body, and lambda bodies live in expressions)."""
    for st in stmts:
        if isinstance(st, P.Return):
            out.append(st)
        elif isinstance(st, P.If):
            for _cond, body in st.branches:
                _returns(body, out)
            if st.else_body is not None:
                _returns(st.else_body, out)
        elif isinstance(st, P.Case):
            for when in st.whens:
                _returns(when.body, out)
            if st.else_body is not None:
                _returns(st.else_body, out)
        elif isinstance(st, (P.While, P.ForEach, P.ForTo, P.Scope)):
            _returns(st.body, out)
        elif isinstance(st, P.Try):
            _returns(st.body, out)
            for _var, _type, body in st.catches:
                _returns(body, out)
            if st.finally_body is not None:
                _returns(st.finally_body, out)


def _methods(module: P.Module) -> Iterable[P.Method]:
    for m in module.members:
        if isinstance(m, P.Method):
            yield m
        elif isinstance(m, P.Structure):
            for sub in m.members:
                if isinstance(sub, P.Method):
                    yield sub
        elif isinstance(m, P.Enum):
            yield from m.methods


@rule("code/return-mismatch", "code/return-mismatch.title", "C", severity=Severity.ERROR)
def return_mismatch(source: SourceFile) -> Iterable[Diagnostic]:
    """A method's returns must agree with its declared return type - the compiler insists."""
    if source.kind != "xbsl":
        return
    module, errors = parse(source)
    if errors:
        return  # a broken file is code/parse-error territory
    lm = linemap(source)
    for method in _methods(module):
        found: list[P.Return] = []
        _returns(method.body, found)
        for st in found:
            if st.value is None and method.return_type is not None:
                line, col = lm.linecol(st.start)
                yield Diagnostic(
                    source.rel, line, col, "code/return-mismatch", Severity.ERROR,
                    i18n.t("code/return-mismatch.empty-in-typed", type=method.return_type.text),
                )
            elif st.value is not None and method.return_type is None:
                line, col = lm.linecol(st.start)
                yield Diagnostic(
                    source.rel, line, col, "code/return-mismatch", Severity.ERROR,
                    i18n.t("code/return-mismatch.value-in-void"),
                )
