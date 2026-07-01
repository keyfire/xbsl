"""Лексер XBSL.

Токенизация верна грамматике платформы (InternalBsl.g): двуязычные ключевые слова,
идентификаторы (Latin/Cyrillic/CJK), числа (в т.ч. форма с буквенными частями),
многострочные строки с экранированием и интерполяцией, комментарии // /* */ /** */.

Языковые таблицы берутся из xbsllint/data/language.json (генерит tools/extract_grammar.py).
"""

from __future__ import annotations

import bisect
import re
from dataclasses import dataclass, field
from functools import lru_cache

from xbsllint import dataset

# Класс «буквы» из fragment RULE_LETTER грамматики (Latin + Cyrillic в Ā..῿ + CJK).
_LETTER = (
    "A-Za-z"
    "À-ÖØ-öø-ÿ"
    "Ā-῿぀-㆏㌀-㍿㐀-㴭一-鿿豈-﫿"
)
_IDENT_RE = re.compile(rf"[_{_LETTER}][_{_LETTER}0-9]*")
# RULE_LITERAL_WITH_NUMBER_PARTS: сначала форма с буквенными частями (макс. откус), затем число.
_NUMBER_RE = re.compile(rf"(?:[0-9]+[{_LETTER}]+)+[0-9]*|[0-9]+(?:\.[0-9]+)?")


@lru_cache(maxsize=1)
def _language() -> dict:
    return dataset.load_json("language.json")


@lru_cache(maxsize=1)
def _keyword_forms() -> dict[str, str]:
    forms: dict[str, str] = {}
    for canon, entry in _language()["keywords"].items():
        for f in entry["forms"]:
            forms[f] = canon
    return forms


@lru_cache(maxsize=1)
def _operators() -> list[str]:
    # По убыванию длины – для максимального откуса (?? и ?. раньше ?, :: раньше : и т.д.)
    return sorted(_language()["operators"], key=lambda s: (-len(s), s))


@dataclass
class Token:
    kind: str  # KEYWORD | IDENT | NUMBER | STRING | COMMENT | OP | BOM | UNKNOWN | EOF
    value: str
    start: int  # смещение начала (вкл.)
    end: int  # смещение конца (искл.)
    line: int  # 1-индекс
    col: int  # 1-индекс
    end_line: int
    end_col: int
    canonical: str | None = None  # для KEYWORD – канон (IF/METHOD/...)
    subkind: str | None = None  # для COMMENT – line|block|doc
    flags: dict = field(default_factory=dict)  # напр. {'unterminated': True}

    def __repr__(self) -> str:  # компактно для отладки
        v = self.value if len(self.value) <= 20 else self.value[:17] + "..."
        extra = f" {self.canonical}" if self.canonical else (f" {self.subkind}" if self.subkind else "")
        return f"<{self.kind}{extra} {v!r} @{self.line}:{self.col}>"


def _line_starts(text: str) -> list[int]:
    starts = [0]
    i, n = 0, len(text)
    while i < n:
        c = text[i]
        if c == "\r":
            i += 2 if (i + 1 < n and text[i + 1] == "\n") else 1
            starts.append(i)
        elif c == "\n":
            i += 1
            starts.append(i)
        else:
            i += 1
    return starts


class _LineMap:
    def __init__(self, text: str) -> None:
        self._starts = _line_starts(text)

    def linecol(self, offset: int) -> tuple[int, int]:
        line = bisect.bisect_right(self._starts, offset)
        return line, offset - self._starts[line - 1] + 1


def tokenize(text: str) -> list[Token]:
    """Разобрать исходный текст в список токенов (без пробелов и переводов строк)."""
    lm = _LineMap(text)
    ops = _operators()
    kwforms = _keyword_forms()
    tokens: list[Token] = []
    i, n = 0, len(text)

    def emit(kind: str, start: int, end: int, **kw) -> None:
        sl, sc = lm.linecol(start)
        el, ec = lm.linecol(end)
        tokens.append(Token(kind, text[start:end], start, end, sl, sc, el, ec, **kw))

    while i < n:
        c = text[i]

        # BOM (обычно снимается при декодировании utf-8-sig, но на всякий случай)
        if c == "﻿":
            emit("BOM", i, i + 1)
            i += 1
            continue

        # Пробелы и переводы строк – тривия, пропускаем
        if c in " \t":
            i += 1
            continue
        if c in "\r\n":
            i += 2 if (c == "\r" and i + 1 < n and text[i + 1] == "\n") else 1
            continue

        # Комментарии (раньше оператора '/')
        if c == "/" and i + 1 < n:
            nxt = text[i + 1]
            if nxt == "/":
                j = i + 2
                while j < n and text[j] not in "\r\n":
                    j += 1
                emit("COMMENT", i, j, subkind="line")
                i = j
                continue
            if nxt == "*":
                # doc-комментарий /** ... */ (но не /**/), иначе блочный /* ... */
                is_doc = text.startswith("/**", i) and not text.startswith("/**/", i)
                close = text.find("*/", i + 2)
                if close == -1:
                    emit("COMMENT", i, n, subkind="doc" if is_doc else "block", flags={"unterminated": True})
                    i = n
                    continue
                end = close + 2
                emit("COMMENT", i, end, subkind="doc" if is_doc else "block")
                i = end
                continue

        # Строки (многострочные, с экранированием \)
        if c == '"':
            j = i + 1
            unterminated = True
            while j < n:
                cj = text[j]
                if cj == "\\":
                    j += 2
                    continue
                if cj == '"':
                    j += 1
                    unterminated = False
                    break
                j += 1
            flags = {"unterminated": True} if unterminated else {}
            emit("STRING", i, min(j, n), flags=flags)
            i = min(j, n)
            continue

        # Числа (лидирующая цифра ⇒ число)
        if c.isdigit():
            m = _NUMBER_RE.match(text, i)
            end = m.end() if m else i + 1
            emit("NUMBER", i, end)
            i = end
            continue

        # Идентификаторы и ключевые слова (максимальный откус, затем проверка на ключевое слово)
        if c == "_" or _IDENT_RE.match(text, i):
            m = _IDENT_RE.match(text, i)
            word = m.group(0)
            canon = kwforms.get(word)
            if canon is not None:
                emit("KEYWORD", i, m.end(), canonical=canon)
            else:
                emit("IDENT", i, m.end())
            i = m.end()
            continue

        # Операторы и пунктуация (максимальный откус по длине)
        matched = None
        for op in ops:
            if text.startswith(op, i):
                matched = op
                break
        if matched is not None:
            emit("OP", i, i + len(matched))
            i += len(matched)
            continue

        # Неизвестный символ – одиночный токен (пусть правило его пометит)
        emit("UNKNOWN", i, i + 1)
        i += 1

    sl, sc = lm.linecol(n)
    tokens.append(Token("EOF", "", n, n, sl, sc, sl, sc))
    return tokens


def tokens(source) -> list[Token]:
    """Токены исходного файла с кэшированием в source.cache."""
    cached = source.cache.get("tokens")
    if cached is None:
        cached = tokenize(source.text)
        source.cache["tokens"] = cached
    return cached


def linemap(source) -> _LineMap:
    """Карта смещение -> (строка, колонка) для файла, с кэшированием."""
    lm = source.cache.get("linemap")
    if lm is None:
        lm = _LineMap(source.text)
        source.cache["linemap"] = lm
    return lm
