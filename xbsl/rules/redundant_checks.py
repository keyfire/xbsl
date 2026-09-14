"""Tier D: operations whose outcome the types of the code already decide.

The platform's own editor warns about two such operations, and until now the linter named
neither - both are questions about the SET of types an expression holds (`typeinfer.TypeSet`).

**`code/redundant-undefined-guard`** - `А ?? Б`, `Х!` and `Х?.Член` over a value whose type has
no empty value: the default of `??` is never used, the insistent operation asserts what the type
already guarantees, the safe access guards against nothing. The editor warns about such a guard
when the set of types of the operand is known and has no `Undefined` in it - for all three
operations alike - and so does the rule. On a live project the editor points at three such places,
and all three are typed by readings the engine lacked: the value of a component its markup
declares `ПолеВвода<Число>`, the new value of an event parameter declared
`СобытиеПриИзменении<Строка>`.

The fix removes `?? Б` and `!`, and only when nothing else moves: the text left behind must parse
into the same tree with the operand in place of the operation, and for `??` the default must not
widen the type of the whole (`Строка ?? 0` is a string or a number, and a variable declared by it
would change its type). The safe access keeps no fix: `Х?.Член` is nullable and `Х.Член` is not,
so a declaration initialized by it would change its type.

**`code/redundant-type-check`** - `Х это Тип` whose result the type of `Х` decides: every type of
the set fits the checked list, so the check passes whatever the value is, and `это не` never does.
The editor judges that by whether the checked types can hold every value of the expression; the
rule reads it with the relation the cast rules take (`typeinfer.always_holds`): the same type, a
base the catalog states (a string fits the object type, `Array<String>` fits
`ReadableArray<String>`), an entity contract an element of the project implements. A relation
the data does not state is no relation - silence, never a false finding. The one place on a live
project is a column of a query row, and a column is typed by the fields the project's yaml
declares - which is why this rule runs over the whole project (the facts and the typing are the
ones the cast rules read, see `typeinfer.project_typings`): a module alone cannot tell the type
of `Запись.Цена`. The guard stays a file rule and reads the module with its paired markup
(`typeinfer.file_typing`) - the places it judges are typed there, and the editor highlights them
on every keystroke.

Both rules judge the methods of the module itself; a structure's methods reach its fields by a
bare name, and they are skipped.
"""

from __future__ import annotations

import dataclasses
import re
from collections.abc import Iterable

from xbsl import i18n
from xbsl import parser as P
from xbsl import typeinfer
from xbsl.diagnostics import Diagnostic, Severity, TextEdit
from xbsl.engine import SourceFile, rule
from xbsl.lexer import linemap, tokens
from xbsl.typeinfer import TypeSet

GUARD = "code/redundant-undefined-guard"
CHECK = "code/redundant-type-check"

MESSAGES = {
    f"{GUARD}.title": {
        "ru": "Защита от Неопределено у значения, которое им не бывает",
        "en": "A guard against Undefined on a value that never is",
    },
    f"{GUARD}.coalesce": {
        "ru": "Значение слева от '??' не бывает '{n[Неопределено]}': его тип '{type}', поэтому "
              "значение по умолчанию справа никогда не используется – '?? ...' можно убрать.",
        "en": "The value left of '??' is never '{n[Неопределено]}': its type is '{type}', so "
              "the default on the right is never used - the '?? ...' can go.",
    },
    f"{GUARD}.insist": {
        "ru": "Значение перед '!' не бывает '{n[Неопределено]}': его тип '{type}' – "
              "настойчивая операция ничего не проверяет, '!' можно убрать.",
        "en": "The value before '!' is never '{n[Неопределено]}': its type is '{type}' - "
              "the insistent operation checks nothing, the '!' can go.",
    },
    f"{GUARD}.safe": {
        "ru": "Значение перед '?.' не бывает '{n[Неопределено]}': его тип '{type}' – "
              "безопасный доступ ни от чего не защищает, достаточно '.'.",
        "en": "The value before '?.' is never '{n[Неопределено]}': its type is '{type}' - "
              "the safe access guards against nothing, a plain '.' will do.",
    },
    f"{CHECK}.title": {
        "ru": "Проверка типа, результат которой известен заранее",
        "en": "A type check whose result is known in advance",
    },
    f"{CHECK}.true": {
        "ru": "Результат '{n[это]} {check}' известен заранее: значение типа '{type}' проходит "
              "такую проверку всегда, и условие ничего не проверяет.",
        "en": "The result of '{n[это]} {check}' is known in advance: a value of type '{type}' "
              "always passes it, so the condition checks nothing.",
    },
    f"{CHECK}.false": {
        "ru": "Результат '{n[это]} {n[не]} {check}' известен заранее: значение типа '{type}' "
              "всегда подходит под '{check}', и условие не выполняется никогда.",
        "en": "The result of '{n[это]} {n[не]} {check}' is known in advance: a value of type "
              "'{type}' always fits '{check}', so the condition never holds.",
    },
}
i18n.register(MESSAGES)


def display(types: TypeSet, local: dict[str, str] | None = None) -> str:
    """A set as the reader's language writes it: the names through the platform dictionary.

    `local` spells the structures and enumerations of the module itself the way its code
    writes them: the bare name, not the name the inference qualifies by the module."""
    names = sorted(_display_name(name, local or {}) for name in types.names)
    if not types.undefined:
        return "|".join(names)
    return f"{names[0]}?" if len(names) == 1 else "|".join([*names, "?"])


def _display_name(name: str, local: dict[str, str]) -> str:
    if name in local:
        return local[name]
    head, args = typeinfer.split_nominal(name)
    shown = local.get(head) or (i18n.name(head, "types") if "." not in head else i18n.name(head))
    if not args:
        return shown
    parts = [typeinfer.parse_type(arg, lambda word: word) for arg in args]
    if any(part is None for part in parts):
        return name
    return f"{shown}<{', '.join(display(part, local) for part in parts if part is not None)}>"


def _local_names(typing: typeinfer.ModuleTyping) -> dict[str, str]:
    """{qualified name: the name the module writes} of its own structures and enumerations."""
    module = typing.scope.module
    own = typing.catalog.modules.get(module or "") or {}
    return {f"{module}.{name}": name
            for name in (*(own.get("structures") or {}), *(own.get("enums") or {}))}


# --- code/redundant-undefined-guard ---------------------------------------------------------

#: A guard in the text: `??`, `?.` or a `!` that is not the start of `!=`.
_GUARD_TEXT_RE = re.compile(r"\?\?|\?\.|!(?!=)")


@rule(GUARD, f"{GUARD}.title", "D", severity=Severity.WARNING)
def redundant_undefined_guard(source: SourceFile) -> Iterable[Diagnostic]:
    """`??`, `!` and `?.` over a value whose type has no empty value."""
    if source.kind != "xbsl" or not _GUARD_TEXT_RE.search(source.text):
        return
    typing = typeinfer.file_typing(source)
    if typing is None:
        return
    lm = linemap(source)
    local = _local_names(typing)
    for site in typing.guards():
        types = site.types
        if types is None or not types.names or types.undefined or types.null:
            continue
        line, col = lm.linecol(int(site.operand.start))
        fix = None
        if site.kind == "coalesce":
            fix = _coalesce_fix(source, typing.tree, site.node, types, site.right)
        elif site.kind == "insist":
            fix = _insist_fix(source, typing.tree, site.node)
        yield Diagnostic(
            source.rel, line, col, GUARD, Severity.WARNING,
            i18n.t(f"{GUARD}.{site.kind}", type=display(types, local)), fix=fix,
        )


def _significant(source: SourceFile) -> list:
    return [token for token in tokens(source) if token.kind not in ("COMMENT", "BOM", "EOF")]


def _coalesce_fix(source: SourceFile, module: object, node: P.Coalesce, left: TypeSet,
                  right: TypeSet | None) -> TextEdit | None:
    """Remove `?? Б` when the default cannot widen the type and the tree stays the same."""
    if right is None or right.undefined or right.null or not right.names <= left.names:
        return None
    toks = _significant(source)
    operator = next((i for i, t in enumerate(toks)
                     if t.kind == "OP" and t.value == "??" and int(node.left.end) <= t.start
                     and t.start < int(node.right.start)), None)
    if operator is None or operator == 0:
        return None
    start = toks[operator - 1].end
    opened = sum(1 for t in toks[operator + 1:] if t.start < int(node.right.start)
                 and t.kind == "OP" and t.value == "(")
    end = int(node.right.end)
    after = [t for t in toks if t.start >= end]
    for token in after[:opened]:
        if not (token.kind == "OP" and token.value == ")"):
            return None
        end = token.end
    return _verified(source, module, node, node.left, start, end)


def _insist_fix(source: SourceFile, module: object, node: P.NonNull) -> TextEdit | None:
    """Remove the `!` when the tree stays the same without it."""
    toks = _significant(source)
    bang = next((t for t in toks if t.kind == "OP" and t.value == "!"
                 and int(node.operand.end) <= t.start < int(node.end)), None)
    if bang is None:
        return None
    return _verified(source, module, node, node.operand, bang.start, bang.end)


def _verified(source: SourceFile, module: object, node: P.Node, operand: P.Node,
              start: int, end: int) -> TextEdit | None:
    """The edit, when the text without [start, end) parses into the tree with `operand` for `node`.

    A removed range must hold no comment: the edit would take it along.
    """
    if any(token.kind == "COMMENT" and start <= token.start < end for token in tokens(source)):
        return None
    edited, errors = P.parse_text(source.text[:start] + source.text[end:])
    if errors:
        return None
    if _shape(edited) != _shape(module, replace=(node, operand)):
        return None
    return TextEdit(start, end, "")


def _shape(node: object, replace: tuple[object, object] | None = None) -> object:
    """A node tree without offsets, `replace` = (node, the node standing in for it)."""
    if replace is not None and node is replace[0]:
        node = replace[1]
    if isinstance(node, (list, tuple)):
        return tuple(_shape(item, replace) for item in node)
    if not isinstance(node, P.Node):
        return node
    return (type(node).__name__, tuple(
        _shape(getattr(node, f.name), replace)
        for f in dataclasses.fields(node) if f.name not in ("start", "end")
    ))


# --- code/redundant-type-check ------------------------------------------------------------------


@rule(CHECK, f"{CHECK}.title", "D", scope="project", severity=Severity.WARNING,
      mapper=typeinfer.project_fact)
def redundant_type_check(facts: dict[str, dict]) -> Iterable[Diagnostic]:
    """`Х это Тип` whose result the type of `Х` already decides."""
    for rel, typing in typeinfer.project_typings(facts).items():
        sites = typing.checks()
        if not sites:
            continue
        lm = linemap(_TextSource(typing.text))
        local = _local_names(typing)
        for site in sites:
            if site.types is None or site.check is None:
                continue
            if not typeinfer.always_holds(site.types, site.check, typing.catalog.assignable):
                continue
            line, col = lm.linecol(int(site.node.start))
            yield _check_diagnostic(rel, line, col, bool(site.node.negated),
                                    display(site.types, local), display(site.check, local))


class _TextSource:
    """The minimal source the line map needs: the text and a cache."""

    def __init__(self, text: str) -> None:
        self.text = text
        self.cache: dict = {}


def _check_diagnostic(rel: str, line: int, col: int, negated: bool, shown: str,
                      check: str) -> Diagnostic:
    variant = "false" if negated else "true"
    return Diagnostic(rel, line, col, CHECK, Severity.WARNING,
                      i18n.t(f"{CHECK}.{variant}", type=shown, check=check))
