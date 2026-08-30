"""Tier C: an annotation must not repeat on one declaration.

The compiler rejects a duplicated annotation ("Annotation 'X' is already placed"), but
today only the server-side compilation on deploy says so - the linter reports it before.
The typical way to produce the duplicate is an insertion of a new declaration between a
neighbour's leading comment and its annotations: annotations pile up until the nearest
declaration and comments do not separate them, so a block like
`@НаСервере // комментарий @НаСервере структура ...` hands BOTH annotations to the one
declaration. The engine parser mirrors the compiler here - COMMENT tokens are dropped
before parsing and `annotations()` greedily collects every consecutive `@Имя` group -
which makes the duplicate visible directly in the AST node, with no token scan of its
own (and keeps `@media`/`@keyframes` inside CSS string literals out of sight).
"""

from __future__ import annotations

from collections.abc import Iterable

from xbsl import i18n
from xbsl import parser as P
from xbsl.diagnostics import Diagnostic, Severity
from xbsl.engine import SourceFile, is_query_file, rule
from xbsl.lexer import linemap
from xbsl.parser import parse

MESSAGES = {
    "code/duplicate-annotation.title": {
        "ru": "Повторная аннотация у объявления",
        "en": "Duplicate annotation on a declaration",
    },
    "code/duplicate-annotation.repeat": {
        "ru": "Аннотация @{name} у этого объявления уже стоит – компилятор такое отвергает;"
              " аннотации копятся до ближайшего объявления, и комментарий между ними"
              " их не разделяет",
        "en": "Annotation @{name} is already placed on this declaration - the compiler"
              " rejects it; annotations pile up until the nearest declaration, and a"
              " comment between them does not separate them",
    },
}
i18n.register(MESSAGES)


def _annotated(module: P.Module) -> Iterable[list[P.Annotation]]:
    """Annotation lists of every declaration the grammar lets carry them.

    Module members (methods, structures, exceptions, enumerations, fields and consts),
    structure members (fields, methods, the constructor), enumeration methods, and the
    parameters of every method met along the way.
    """

    def walk(node: P.Node) -> Iterable[list[P.Annotation]]:
        anns = getattr(node, "annotations", None)
        if anns is not None:
            yield anns
        if isinstance(node, P.Structure):
            for member in node.members:
                yield from walk(member)
        elif isinstance(node, P.Enum):
            for method in node.methods:
                yield from walk(method)
        if isinstance(node, P.Method):
            for param in node.params:
                yield param.annotations

    for member in module.members:
        yield from walk(member)


def _has_args(source: SourceFile, ann: P.Annotation) -> bool:
    """Whether the annotation is written with an argument list.

    `ann.args` is empty both for a bare `@Имя` and for `@Имя()`, so the source slice is
    checked for the opening bracket too - the node's end covers the bracket only when
    the parser consumed an argument list.
    """
    return bool(ann.args) or "(" in source.text[ann.start:ann.end]


@rule("code/duplicate-annotation", "code/duplicate-annotation.title", "C",
      severity=Severity.ERROR)
def duplicate_annotation(source: SourceFile) -> Iterable[Diagnostic]:
    """One declaration must not carry the same annotation twice - the compiler refuses.

    The predicate: within the annotation list of a single declaration, an argument-free
    annotation whose full (possibly `::`-qualified) name already occurred in that list.
    Deliberately narrow, and the narrowing is part of the contract:

      * only an EXACT, case-sensitive repeat of the name is flagged - for mixed
        spellings of one annotation (`@НаСервере` next to `@OnServer`) the compiler's
        refusal is not proven by a live compilation, so they pass;
      * only annotations WITHOUT arguments are compared - for `@Имя(...)` the refusal
        is likewise unproven (arguments may legitimately differ), so any occurrence
        carrying an argument list drops out of the comparison entirely.

    Proven by a fixture against the engine parser (the duplicate-through-comment trap,
    the same-line duplicate, and both legal comment layouts) and by four clean corpora:
    no real declaration repeats an annotation name, so every hit reproduces the
    guaranteed deploy-time refusal - hence ERROR. A bare `@` parses with an empty name
    and is skipped (`code/parse-error` territory); an orphaned annotation block without
    a declaration is likewise already covered by the parse errors.
    """
    if source.kind != "xbsl" or is_query_file(source.path):
        return
    module, _errors = parse(source)
    lm = None
    for anns in _annotated(module):
        if len(anns) < 2:
            continue
        seen: set[str] = set()
        for ann in anns:
            if not ann.name or _has_args(source, ann):
                continue
            if ann.name in seen:
                if lm is None:
                    lm = linemap(source)
                line, col = lm.linecol(ann.start)
                yield Diagnostic(
                    source.rel, line, col, "code/duplicate-annotation", Severity.ERROR,
                    i18n.t("code/duplicate-annotation.repeat", name=ann.name),
                )
            seen.add(ann.name)
