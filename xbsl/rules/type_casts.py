"""Tier D: casts the compiler calls needless - `code/redundant-cast` and `code/cast-to-non-null`.

The editor of the platform warns about two kinds of `<выражение> как <Тип>`:

- the expression is ALREADY of that type (or of one the type holds), and the cast is redundant.
  `Найдена!.Ссылка как Товары.Ссылка`, where the query row reads the reference of the
  very catalog, is the everyday shape;
- the expression is that type OR the empty value, and the cast does nothing but drop the empty
  value - the editor advises the non-null operator instead. `Строка.Товар как Товары.Ссылка`
  over a field declared `Товары.Ссылка?` says the same as `Строка.Товар!`, and the operator
  says it without naming the type again.

Neither is an error, and both hide what the code means: a cast reads as a conversion, and a
reader looks for the case where the value is of another type - there is none. The fixes are
mechanical: the cast is removed, or replaced by `!`.

The comparison is the compiler's own (see `typeinfer.cast_verdict`), and the hard part is the
type of the operand. Most of what a live project casts comes from the project itself - a column
of a query over a catalog, a field of a structure declared in another module, the result of a
common module's method - so the rules are PROJECT rules: the mapper (`typeinfer.project_fact`)
publishes per file what the catalog needs (the elements of the yaml, the declarations of the
modules) and, for a module that casts or checks a type at all, its text; the reduce
(`typeinfer.project_typings`) builds the project catalog and types the operands there, once for
these rules and the type check of `redundant_checks`, which read the same facts. A file rule
could see neither the yaml of the table a query reads nor the declaration of a structure in
another module, and without them the inference names nothing.

What keeps both rules at zero false findings:

- an operand the inference cannot name is not judged - a union with an unknown part, a type
  parameter, a column of a query the reading does not understand;
- the operand is typed by its declarations, the way the compiler types it for this check: a
  condition checked before the cast narrows nothing (see `typeinfer.CastSite`);
- a type the project does not declare in a way the catalog reads stays unknown, and so does a
  relation between two types the catalog cannot prove (the contract an element implements is
  the one relation of the project it knows).
"""

from __future__ import annotations

import re
from collections.abc import Iterable

from xbsl import i18n, terms
from xbsl import parser as P
from xbsl import typeinfer
from xbsl.diagnostics import Diagnostic, Severity, TextEdit
from xbsl.engine import rule
from xbsl.lexer import linemap

MESSAGES = {
    "code/redundant-cast.title": {
        "ru": "Приведение к типу, который у значения уже есть",
        "en": "A cast to the type the value already has",
    },
    "code/redundant-cast.found": {
        "ru": "Значение уже имеет тип '{source}': 'как {target}' ничего не проверяет, и приведение "
              "можно убрать.",
        "en": "The value already is of type '{source}': '{n[как]} {target}' checks nothing, and "
              "the cast can go.",
    },
    "code/redundant-cast.wider": {
        "ru": "Значение типа '{source}' и так относится к '{target}': приведение ничего не "
              "проверяет. Убрать его можно, если этот тип не нужен объявлению или перегрузке.",
        "en": "A value of type '{source}' already belongs to '{target}': the cast checks nothing. "
              "It can go unless a declaration or an overload needs that type.",
    },
    "code/cast-to-non-null.title": {
        "ru": "Приведение, которое только отбрасывает Неопределено",
        "en": "A cast that only drops Undefined",
    },
    "code/cast-to-non-null.found": {
        "ru": "Значение имеет тип '{source}', и 'как {target}' лишь отбрасывает Неопределено – "
              "то же скажет '!', не повторяя тип.",
        "en": "The value is of type '{source}', and '{n[как]} {target}' only drops "
              "{n[Неопределено]} - '!' says the same without repeating the type.",
    },
}
i18n.register(MESSAGES)

_REDUNDANT = "code/redundant-cast"
_NON_NULL = "code/cast-to-non-null"


# --- the reduce: the verdicts over the typing of the project ---------------------------------------

_last: tuple[object, dict[str, list[Diagnostic]]] | None = None


def _findings(facts: dict[str, dict]) -> dict[str, list[Diagnostic]]:
    """The findings of BOTH rules at once: each rule runs the reduce with the same facts, and
    the typing of every cast of the project is the expensive half."""
    global _last
    key = typeinfer._fingerprint(facts)
    if _last is not None and _last[0] == key:
        return _last[1]
    found: dict[str, list[Diagnostic]] = {_REDUNDANT: [], _NON_NULL: []}
    for rel, typing in typeinfer.project_typings(facts).items():
        _judge_module(rel, typing, found)
    _last = (key, found)
    return found


def _judge_module(rel: str, typing: typeinfer.ModuleTyping, found: dict[str, list[Diagnostic]]) -> None:
    sites = typing.casts()
    text = typing.text
    lines = None
    tokens: list | None = None
    for site in sites:
        if site.source is None or site.target is None:
            continue
        verdict = typeinfer.cast_verdict(site.source, site.target, typing.catalog.assignable)
        if verdict is None:
            continue
        if tokens is None:
            tokens = [t for t in typing.tokens if t.kind not in ("COMMENT", "BOM", "EOF")]
            lines = linemap(_TextSource(text))
        node = site.node
        line, col = lines.linecol(_reported_start(text, node))
        operand = node.operand
        target = _target_text(text, node)
        if verdict == "redundant":
            exact = site.source == site.target
            key = "code/redundant-cast.found" if exact else "code/redundant-cast.wider"
            found[_REDUNDANT].append(Diagnostic(
                rel, line, col, _REDUNDANT, Severity.WARNING,
                i18n.t(key, source=_shown(site.source), target=target),
                fix=_removal(text, tokens, node, operand) if exact else None,
            ))
        else:
            found[_NON_NULL].append(Diagnostic(
                rel, line, col, _NON_NULL, Severity.WARNING,
                i18n.t("code/cast-to-non-null.found", source=_shown(site.source), target=target),
                fix=_non_null(text, tokens, node, operand),
            ))


def _reported_start(text: str, node) -> int:
    """Where the finding stands: the start of the operand with the parentheses written around it.

    The compiler anchors its warning at the start of the cast expression as the source spells it,
    so `(А + Б) как Число` is reported at `(`, while the parser keeps the node from `А`."""
    start, end = node.operand.start, node.operand.end
    while True:
        left = start - 1
        while left >= 0 and text[left] in " \t\r\n":
            left -= 1
        right = end
        while right < len(text) and text[right] in " \t\r\n":
            right += 1
        if left < 0 or right >= len(text) or text[left] != "(" or text[right] != ")" or right >= node.end:
            return start
        start, end = left, right + 1


class _TextSource:
    """The minimal source the line map needs: the text and a cache."""

    def __init__(self, text: str) -> None:
        self.text = text
        self.cache: dict = {}


def _target_text(text: str, node) -> str:
    written = getattr(getattr(node, "type", None), "text", None)
    return written or text[node.operand.end:node.end].split(None, 1)[-1]


#: One name of a canonical type text: a head or a facet (`Товары.Ссылка`).
_SHOWN_NAME_RE = re.compile(r"[A-Za-zА-Яа-яЁё_][\wЁё]*(?:\.[A-Za-zА-Яа-яЁё_][\wЁё]*)?")


def _shown(types: typeinfer.TypeSet) -> str:
    """The inferred type as the message shows it: canonical names are the catalog's (Russian)
    ones, and an English message spells the platform names the English way, a facet of a project
    element included (`Goods.Reference`)."""
    text = types.text()
    if i18n.current_lang() != "en":
        return text

    def english(match: re.Match) -> str:
        name = match.group(0)
        head, dot, suffix = name.partition(".")
        if not dot:
            return terms.english(name, "types") or name
        facet = terms.english(name, "facets")
        if facet:
            return facet
        return f"{head}.{terms.facet_suffix_english(suffix) or suffix}"

    return _SHOWN_NAME_RE.sub(english, text)


#: Operands that stay one primary expression without parentheses: a name, a member chain, a
#: call, an index, a `!`, a literal - the parentheses around such an operand group nothing.
_PRIMARY = (P.Name, P.Member, P.Call, P.Index, P.NonNull, P.Literal, P.This)


def _grouping_parens(text: str, tokens: list, node) -> tuple[int, int] | None:
    """The offsets of `(` and `)` that group exactly the cast, or None.

    A parenthesis a call opens is not a grouping one: `Ф(X как Т)` keeps both. What stands
    before the `(` tells them apart - a name or the closing `>` of the arguments of a generic
    call makes it a call on the same line; an operator, a keyword or a new statement
    makes it a group, following Parser.starts_a_line.
    Only spaces may stand between the parentheses and the cast: a group spread over lines keeps
    its line breaks, and the edit then removes the cast alone.
    """
    left = node.start - 1
    while left >= 0 and text[left] in " \t":
        left -= 1
    right = node.end
    while right < len(text) and text[right] in " \t":
        right += 1
    if left < 0 or right >= len(text) or text[left] != "(" or text[right] != ")":
        return None
    index = next((i for i, token in enumerate(tokens) if token.start == left), None)
    if index is None:
        return None
    before = tokens[index - 1] if index > 0 else None
    if before is not None and tokens[index].line == before.end_line:
        if before.kind == "IDENT":
            return None
        if before.kind == "OP" and before.value in (">", ")", "]", "!"):
            return None
    return left, right


def _removal(text: str, tokens: list, node, operand) -> TextEdit | None:
    """`X как Т` -> `X`; `(X как Т).Член` -> `X.Член` when X is one primary expression."""
    if node.end <= operand.end:
        return None
    parens = _grouping_parens(text, tokens, node)
    if parens is not None and isinstance(operand, _PRIMARY):
        return TextEdit(parens[0], parens[1] + 1, text[operand.start:operand.end])
    return TextEdit(operand.end, node.end, "")


def _non_null(text: str, tokens: list, node, operand) -> TextEdit | None:
    """`X как Т` -> `X!`; an operand that is not one primary expression keeps its value in
    parentheses: `(А ?? Б)!`."""
    if node.end <= operand.end:
        return None
    operand_text = text[operand.start:operand.end]
    replacement = operand_text + "!" if isinstance(operand, _PRIMARY) else f"({operand_text})!"
    parens = _grouping_parens(text, tokens, node)
    if parens is not None and isinstance(operand, _PRIMARY):
        after = parens[1] + 1
        # `(X как Т)== У` must not become `X!== У`: glued to `=`, the `!` reads as `!=`.
        if after >= len(text) or text[after] != "=":
            return TextEdit(parens[0], parens[1] + 1, replacement)
    return TextEdit(node.start, node.end, replacement)


@rule(
    _REDUNDANT, "code/redundant-cast.title", "D",
    scope="project", severity=Severity.WARNING, mapper=typeinfer.project_fact,
)
def redundant_cast(facts: dict[str, dict]) -> Iterable[Diagnostic]:
    """`X как Т` where X is already of the type Т holds - the cast changes nothing."""
    return list(_findings(facts)[_REDUNDANT])


@rule(
    _NON_NULL, "code/cast-to-non-null.title", "D",
    scope="project", severity=Severity.WARNING, mapper=typeinfer.project_fact,
)
def cast_to_non_null(facts: dict[str, dict]) -> Iterable[Diagnostic]:
    """`X как Т` where X is `Т?` - the cast only drops the empty value, `X!` says the same."""
    return list(_findings(facts)[_NON_NULL])
