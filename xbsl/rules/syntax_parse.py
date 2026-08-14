"""Tier C: full syntax check of an XBSL module by the parser (xbsl/parser.py).

The parser follows the platform grammar (the generated InternalBsl.g of the distribution),
so anything it rejects the compiler rejects too - but the linter reports it before a deploy.
Unlike the narrow token rules (code/blocks, code/brackets, code/param-type-required), this
one sees the whole structure: unclosed calls and collections, a missing `;`, a broken
ternary, a dangling `иначе`, garbage on the module level.

Error recovery is per statement, so one broken statement yields one diagnostic and the
rest of the file is still checked. A cap guards against error cascades in truly mangled
files - the first errors are the informative ones.
"""

from __future__ import annotations

from collections.abc import Iterable

from xbsl import i18n
from xbsl.diagnostics import Diagnostic, Severity
from xbsl.engine import SourceFile, is_query_file, rule
from xbsl.lexer import linemap
from xbsl.parser import parse

MESSAGES = {
    "code/parse-error.title": {
        "ru": "Синтаксическая ошибка",
        "en": "Syntax error",
    },
    "code/parse-error.more": {
        "ru": "... и ещё {count} синтаксических ошибок в этом файле",
        "en": "... and {count} more syntax errors in this file",
    },
}
i18n.register(MESSAGES)

# Past this many errors the file counts as broken outright - the rest is only noise.
_MAX_PER_FILE = 10


@rule("code/parse-error", "code/parse-error.title", "C", severity=Severity.ERROR)
def parse_error(source: SourceFile) -> Iterable[Diagnostic]:
    """The file must parse against the platform grammar - the compiler will not take it.

    A query file is skipped: it lexes as code and is loaded with kind `xbsl`, but it is not a
    module - the whole file is one query expression, and the module parser meets it with
    "a module import, method, structure, enumeration or constant is expected" on line 1.
    """
    if source.kind != "xbsl" or is_query_file(source.path):
        return
    _, errors = parse(source)
    if not errors:
        return
    lm = linemap(source)
    for err in errors[:_MAX_PER_FILE]:
        line, col = lm.linecol(err.start)
        yield Diagnostic(source.rel, line, col, "code/parse-error", Severity.ERROR, err.message)
    rest = len(errors) - _MAX_PER_FILE
    if rest > 0:
        line, col = lm.linecol(errors[_MAX_PER_FILE].start)
        yield Diagnostic(
            source.rel, line, col, "code/parse-error", Severity.ERROR,
            i18n.t("code/parse-error.more", count=rest),
        )
