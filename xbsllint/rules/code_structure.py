"""Тир C: структурный баланс кода по токенам (без полного AST).

Модель выверена на корпусе сайта (openers == ';' во всех модулях):
- открыватель блока – ключевое слово в НИЖНЕМ регистре из набора OPENERS; заглавные формы
  (Метод, Исключение, Выбор) – это PascalCase-идентификаторы, а не ключевые слова;
- `иначе если` на одной строке – else-if (продолжение того же if, не новый блок);
  вложенный `если` в ветке `иначе` (на другой строке) – новый блок;
- `;` закрывает текущий блок; скобки () [] {} балансируются отдельным стеком.
"""

from __future__ import annotations

from collections.abc import Iterable

from xbsllint.diagnostics import Diagnostic, Severity
from xbsllint.engine import SourceFile, rule
from xbsllint.lexer import tokens

_OPENERS = {
    "METHOD", "STRUCTURE", "ENUMERATION", "EXCEPTION", "CONSTRUCTOR",
    "IF", "FOR", "WHILE", "TRY", "CASE",
}
_BLOCK_WORD = {
    "METHOD": "метод", "STRUCTURE": "структура", "ENUMERATION": "перечисление",
    "EXCEPTION": "исключение", "CONSTRUCTOR": "конструктор", "IF": "если",
    "FOR": "для", "WHILE": "пока", "TRY": "попытка", "CASE": "выбор",
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

    for t in tokens(source):
        if t.kind == "COMMENT":
            continue
        if t.kind == "EOF":
            break

        if t.kind == "KEYWORD" and t.canonical in _OPENERS and t.value[:1].islower():
            is_else_if = (
                t.canonical == "IF"
                and prev_sig is not None
                and prev_sig[0] == "KEYWORD"
                and prev_sig[1] == "ELSE"
                and prev_sig[2] == t.line
            )
            if not is_else_if:
                blocks.append((t.canonical, t.line, t.col))
        elif t.kind == "OP":
            v = t.value
            if v == ";":
                if blocks:
                    blocks.pop()
                else:
                    diags.append(Diagnostic(
                        source.rel, t.line, t.col, "code/blocks", Severity.ERROR,
                        "Лишний ';' – нет открытого блока для закрытия.",
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
                        f"Непарная скобка: ожидалась '{exp}', встречена '{v}'.",
                    ))
                    brackets.pop()
                else:
                    diags.append(Diagnostic(
                        source.rel, t.line, t.col, "code/brackets", Severity.ERROR,
                        f"Непарная закрывающая скобка '{v}'.",
                    ))

        prev_sig = (t.kind, t.canonical if t.kind == "KEYWORD" else t.value, t.line)

    for ch, line, col in brackets:
        diags.append(Diagnostic(
            source.rel, line, col, "code/brackets", Severity.ERROR,
            f"Не закрыта скобка '{ch}'.",
        ))
    for canon, line, col in blocks:
        diags.append(Diagnostic(
            source.rel, line, col, "code/blocks", Severity.ERROR,
            f"Не закрыт блок '{_BLOCK_WORD.get(canon, canon)}' – ожидается ';'.",
        ))

    source.cache["struct_diags"] = diags
    return diags


@rule("code/brackets", "Дисбаланс скобок () [] {}", "C", severity=Severity.ERROR)
def brackets_balance(source: SourceFile) -> Iterable[Diagnostic]:
    if source.kind != "xbsl":
        return []
    return [d for d in _compute(source) if d.rule_id == "code/brackets"]


@rule("code/blocks", "Дисбаланс блоков и ';'", "C", severity=Severity.ERROR)
def blocks_balance(source: SourceFile) -> Iterable[Diagnostic]:
    if source.kind != "xbsl":
        return []
    return [d for d in _compute(source) if d.rule_id == "code/blocks"]
