"""Tier C: structural balance of code by tokens (without a full AST).

The model is calibrated on a real corpus (openers == ';' in every module):
- a block opener is a lowercase keyword from OPENERS; the capitalized forms
  (Метод, Исключение, Выбор) are PascalCase identifiers, not keywords;
- `иначе если` on one line is an else-if (a continuation of the same if, not a new block);
  a nested `если` in an `иначе` branch (on another line) is a new block;
- `;` closes the current block; brackets () [] {} are balanced by a separate stack.

The balance is counted over code_tokens - the contents of `Запрос{...}` are not code: a
BATCH query separates its statements with `;` (`ВЫБРАТЬ ... ПОМЕСТИТЬ вт ... ; ВЫБРАТЬ
... ИЗ вт`), and counting that `;` as a block closer shifted the whole balance and made
the module's real `;` look extra. The query braces leave together with the contents, so
the bracket balance is unaffected.
"""

from __future__ import annotations

from collections.abc import Iterable

from xbsl import i18n
from xbsl.diagnostics import Diagnostic, Severity
from xbsl.engine import SourceFile, rule
from xbsl.lexer import tokens
from xbsl.rules._syntax import code_tokens

MESSAGES = {
    # Braces are doubled: every template goes through str.format (see xbsl/i18n.py).
    "code/brackets.title": {
        "ru": "Дисбаланс скобок () [] {{}}",
        "en": "Unbalanced brackets () [] {{}}",
    },
    "code/brackets.mismatched": {
        "ru": "Непарная скобка: ожидалась '{exp}', встречена '{found}'.",
        "en": "Mismatched bracket: expected '{exp}', found '{found}'.",
    },
    "code/brackets.unmatched-close": {
        "ru": "Непарная закрывающая скобка '{ch}'.",
        "en": "Unmatched closing bracket '{ch}'.",
    },
    "code/brackets.unclosed": {
        "ru": "Не закрыта скобка '{ch}'.",
        "en": "Unclosed bracket '{ch}'.",
    },
    "code/blocks.title": {
        "ru": "Дисбаланс блоков и ';'",
        "en": "Unbalanced blocks and ';'",
    },
    "code/blocks.extra": {
        "ru": "Лишний ';' – нет открытого блока для закрытия.",
        "en": "Extra ';' – no open block to close.",
    },
    "code/blocks.unclosed": {
        "ru": "Не закрыт блок '{word}' – ожидается ';'.",
        "en": "Unclosed block '{word}' – ';' expected.",
    },
    "code/ternary-and-or.title": {
        "ru": "Составное условие тернарного оператора без скобок",
        "en": "Compound ternary condition without parentheses",
    },
    "code/ternary-and-or.compound": {
        "ru": "Условие тернарного оператора с '{word}' без скобок: "
              "'А {word} Б ? X : Y' парсится как 'А {word} (Б ? X : Y)'. "
              "Взять условие в скобки: '((А {word} Б) ? X : Y)'.",
        "en": "Ternary operator condition with '{word}' without parentheses: "
              "'A {word} B ? X : Y' parses as 'A {word} (B ? X : Y)'. "
              "Wrap the condition in parentheses: '((A {word} B) ? X : Y)'.",
    },
}
i18n.register(MESSAGES)

# `конструктор` is NOT here: in a structure/exception it is a bare marker that tunes the
# generated constructor (docs topics/structure: `@ИменованныеПараметры` + `конструктор`,
# no body and no `;`) - counting it as a block opener ate the structure's own `;`.
_OPENERS = {
    "METHOD", "STRUCTURE", "ENUMERATION", "EXCEPTION",
    "IF", "FOR", "WHILE", "TRY", "CASE", "SCOPE",
}
_BLOCK_WORD = {
    "METHOD": "метод", "STRUCTURE": "структура", "ENUMERATION": "перечисление",
    "EXCEPTION": "исключение", "IF": "если",
    "FOR": "для", "WHILE": "пока", "TRY": "попытка", "CASE": "выбор",
    "SCOPE": "область",
}
_PAIRS = {")": "(", "]": "[", "}": "{"}
_OPEN_CH = "([{"
_CLOSE_CH = ")]}"


def _compute(source: SourceFile) -> list[Diagnostic]:
    if "struct_diags" in source.cache:
        return source.cache["struct_diags"]

    diags: list[Diagnostic] = []
    blocks: list[tuple[str, int, int]] = []  # (canonical, line, col)
    brackets: list[tuple[str, int, int]] = []  # (char, line, col)
    prev_sig: tuple[str, str, int] | None = None  # (kind, canon|value, line)

    for t in code_tokens(source):
        if t.kind == "KEYWORD" and t.canonical in _OPENERS and t.value[:1].islower():
            is_else_if = (
                t.canonical == "IF"
                and prev_sig is not None
                and prev_sig[0] == "KEYWORD"
                and prev_sig[1] == "ELSE"
                and prev_sig[2] == t.line
            )
            # `абстрактный метод Имя(...)` declares a signature without a body: no `;`
            # follows it (the parser's ruleabstractMethod), so it opens no block.
            is_abstract = (
                t.canonical == "METHOD"
                and prev_sig is not None
                and prev_sig[0] == "KEYWORD"
                and prev_sig[1] == "ABSTRACT"
            )
            if not is_else_if and not is_abstract:
                blocks.append((t.canonical, t.line, t.col))
        elif t.kind == "OP":
            v = t.value
            if v == ";":
                if blocks:
                    blocks.pop()
                else:
                    diags.append(Diagnostic(
                        source.rel, t.line, t.col, "code/blocks", Severity.ERROR,
                        i18n.t("code/blocks.extra"),
                    ))
            elif v in _OPEN_CH:
                brackets.append((v, t.line, t.col))
            elif v in _CLOSE_CH:
                if brackets and brackets[-1][0] == _PAIRS[v]:
                    brackets.pop()
                elif brackets:
                    exp = {"(": ")", "[": "]", "{": "}"}[brackets[-1][0]]
                    diags.append(Diagnostic(
                        source.rel, t.line, t.col, "code/brackets", Severity.ERROR,
                        i18n.t("code/brackets.mismatched", exp=exp, found=v),
                    ))
                    brackets.pop()
                else:
                    diags.append(Diagnostic(
                        source.rel, t.line, t.col, "code/brackets", Severity.ERROR,
                        i18n.t("code/brackets.unmatched-close", ch=v),
                    ))

        prev_sig = (t.kind, t.canonical if t.kind == "KEYWORD" else t.value, t.line)

    for ch, line, col in brackets:
        diags.append(Diagnostic(
            source.rel, line, col, "code/brackets", Severity.ERROR,
            i18n.t("code/brackets.unclosed", ch=ch),
        ))
    for canon, line, col in blocks:
        diags.append(Diagnostic(
            source.rel, line, col, "code/blocks", Severity.ERROR,
            i18n.t("code/blocks.unclosed", word=_BLOCK_WORD.get(canon, canon)),
        ))

    source.cache["struct_diags"] = diags
    return diags


@rule("code/brackets", "code/brackets.title", "C", severity=Severity.ERROR)
def brackets_balance(source: SourceFile) -> Iterable[Diagnostic]:
    if source.kind != "xbsl":
        return []
    return [d for d in _compute(source) if d.rule_id == "code/brackets"]


@rule("code/blocks", "code/blocks.title", "C", severity=Severity.ERROR)
def blocks_balance(source: SourceFile) -> Iterable[Diagnostic]:
    if source.kind != "xbsl":
        return []
    return [d for d in _compute(source) if d.rule_id == "code/blocks"]


def _new_frame(line: int | None) -> dict:
    # and_or – position of the last 'и'/'или' at this depth level (before '?'),
    # pending – position of the '?' seen after and_or (waiting for ':' to confirm a ternary)
    return {"and_or": None, "pending": None, "line": line}


@rule(
    "code/ternary-and-or",
    "code/ternary-and-or.title",
    "C",
    severity=Severity.ERROR,
)
def ternary_compound_condition(source: SourceFile) -> Iterable[Diagnostic]:
    """The ternary '?:' binds tighter than 'и'/'или': 'A и B ? X : Y' == 'A и (B ? X : Y)'.

    The Element compiler fails with "Incompatible types of logical operator operands" /
    "Булево cannot be assigned to ...". We catch it by tokens: at the same bracket depth
    level 'и'/'или' appear, then '?', then ':' – the condition is not parenthesized.
    Correct: '((A и B) ? X : Y)' – there 'и' sits deeper and the sequence does not match.
    """
    if source.kind != "xbsl":
        return []
    diags: list[Diagnostic] = []
    frames: list[dict] = [_new_frame(None)]

    for t in tokens(source):
        if t.kind == "COMMENT":
            continue
        if t.kind == "EOF":
            break
        top = frames[-1]
        # Outside brackets an expression lives on one line – a new line resets the state.
        if len(frames) == 1 and top["line"] != t.line:
            frames[0] = top = _new_frame(t.line)

        if t.kind == "KEYWORD" and t.canonical in ("AND", "OR"):
            if top["pending"] is None:
                top["and_or"] = (t.line, t.col, t.value)
        elif t.kind == "OP":
            v = t.value
            if v in _OPEN_CH:
                frames.append(_new_frame(t.line))
            elif v in _CLOSE_CH:
                if len(frames) > 1:
                    frames.pop()
            elif v == "?":
                if top["and_or"] is not None and top["pending"] is None:
                    top["pending"] = (t.line, t.col)
            elif v == ":":
                if top["pending"] is not None:
                    line, col = top["pending"]
                    _, _, word = top["and_or"]
                    diags.append(Diagnostic(
                        source.rel, line, col, "code/ternary-and-or", Severity.ERROR,
                        i18n.t("code/ternary-and-or.compound", word=word),
                    ))
                frames[-1] = _new_frame(top["line"])
            elif v in (",", ";", "="):
                frames[-1] = _new_frame(top["line"])

    return diags
