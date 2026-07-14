"""Общие синтаксические помощники для правил кода (тиры B/C).

Здесь собрано то, что нужно сразу нескольким модулям правил и что нельзя выразить одним
проходом по токенам:

- `query_ranges` – смещения блоков `Запрос{ ... }`. Внутри них живёт язык запросов, который
  соглашения по написанию кода XBSL не охватывают (CODE_STYLE, "Область действия"),
  поэтому правила кода эти диапазоны пропускают;
- `code_tokens` – токены модуля без комментариев и без содержимого блоков запроса;
- `lines` / `line_span` – доступ к строкам исходника по номеру;
- `type_expr` – токены выражения типа и разбор его альтернатив (`Строка|Число|?`);
- `declaration_types` / `method_params` – позиции типов в объявлениях и сигнатурах методов.

Разбор ведётся по токенам, без полного AST: правила обязаны давать ноль ложных срабатываний
на корпусе, поэтому неоднозначную конструкцию лучше пропустить, чем угадывать.
"""

from __future__ import annotations

import bisect
from dataclasses import dataclass

from xbsllint.engine import SourceFile
from xbsllint.lexer import Token, tokens

# Ключевые слова, вводящие объявление с аннотацией типа: `знч/пер/конст/поймать/обз Имя: Тип`.
DECL_KEYWORDS = ("VAL", "VAR", "CONST", "CATCH", "REQ")
# Ключевые слова, несущие сигнатуру (список параметров и тип возвращаемого значения).
SIGNATURE_KEYWORDS = ("METHOD", "CONSTRUCTOR")

# DSL запросов – вложенный язык: его слова лексер видит как обычные словарные токены, поэтому
# они сопоставляются по значению (на обоих языках), а не по каноническому ключевому слову.
WORD_KINDS = ("IDENT", "KEYWORD")
QUERY_TABLE_INTRO = frozenset({"ИЗ", "FROM", "СОЕДИНЕНИЕ", "JOIN"})  # следующее слово – таблица
QUERY_ALIAS_INTRO = frozenset({"КАК", "AS"})  # `ИЗ Акция КАК А`

_OPEN_CH = "([{"
_CLOSE_CH = ")]}"


# --- Блоки Запрос{ ... } --------------------------------------------------------------

def query_ranges(source: SourceFile) -> list[tuple[int, int]]:
    """Смещения [начало, конец) блоков `Запрос{ ... }`, включая сами фигурные скобки."""
    cached = source.cache.get("query_ranges")
    if cached is not None:
        return cached

    toks = tokens(source)
    ranges: list[tuple[int, int]] = []
    i, n = 0, len(toks)
    while i < n:
        t = toks[i]
        if t.kind == "KEYWORD" and t.canonical == "QUERY":
            j = _skip_comments(toks, i + 1)
            if j < n and toks[j].kind == "OP" and toks[j].value == "{":
                k, depth = j, 0
                while k < n:
                    tk = toks[k]
                    if tk.kind == "OP" and tk.value == "{":
                        depth += 1
                    elif tk.kind == "OP" and tk.value == "}":
                        depth -= 1
                        if depth == 0:
                            break
                    k += 1
                end = toks[k].end if k < n else len(source.text)
                ranges.append((toks[j].start, end))
                i = k + 1
                continue
        i += 1

    source.cache["query_ranges"] = ranges
    return ranges


def in_query(source: SourceFile, offset: int) -> bool:
    """Смещение попадает внутрь блока запроса."""
    ranges = query_ranges(source)
    idx = bisect.bisect_right([r[0] for r in ranges], offset) - 1
    return idx >= 0 and offset < ranges[idx][1]


def query_alias_pairs(block: list[Token]) -> list[tuple[str, str]]:
    """Пары (алиас, таблица) блока запроса, в порядке появления.

    `ИЗ Акция КАК А` даёт ("А", "Акция"). Таблицы с точкой (виртуальные вроде
    `РегистрСведений.СрезПоследних`) пропускаются: их набор полей – не набор полей объекта.
    Пары, а не словарь: один алиас может быть переопределён в подзапросе, и тому, кто на них
    опирается, важно уметь это заметить.
    """
    out: list[tuple[str, str]] = []
    i, n = 0, len(block)
    while i < n:
        t = block[i]
        if not (t.kind in WORD_KINDS and t.value.upper() in QUERY_TABLE_INTRO):
            i += 1
            continue
        j = i + 1
        if j >= n or block[j].kind not in WORD_KINDS:
            i = j  # подзапрос или интерполяция в позиции таблицы
            continue
        table = block[j]
        j += 1
        dotted = False
        while j + 1 < n and block[j].kind == "OP" and block[j].value == "." and block[j + 1].kind in WORD_KINDS:
            dotted = True
            j += 2
        if (
            not dotted
            and j + 1 < n
            and block[j].kind in WORD_KINDS and block[j].value.upper() in QUERY_ALIAS_INTRO
            and block[j + 1].kind in WORD_KINDS
        ):
            out.append((block[j + 1].value, table.value))
            j += 2
        i = j
    return out


def query_block_tokens(source: SourceFile, span: tuple[int, int]) -> list[Token]:
    """Значимые токены блока запроса [начало, конец): без комментариев и BOM."""
    start, end = span
    return [t for t in tokens(source) if start <= t.start < end and t.kind not in ("COMMENT", "BOM")]


def query_aliases(source: SourceFile, offset: int) -> dict[str, str]:
    """Алиас таблицы -> имя таблицы внутри блока запроса, содержащего `offset` (вне блока – пусто).

    Без этого автодополнению после `А.` нечего разрешать: запросы в проекте пишутся через алиасы.
    Переопределённый алиас разрешается последним вхождением – дополнению лучше предложить хоть
    что-то, чем ничего.
    """
    span = next((r for r in query_ranges(source) if r[0] <= offset < r[1]), None)
    if span is None:
        return {}
    return dict(query_alias_pairs(query_block_tokens(source, span)))


def _query_columns(toks: list[Token], start: int, end: int) -> list[str]:
    """Имена колонок блока запроса [start, end): алиас `КАК Имя` либо последний сегмент простой
    цепочки полей (`А.Заголовок` -> `Заголовок`). Вычисляемые колонки без алиаса пропускаются –
    угадывать их имя не наша задача.
    """
    block = [t for t in toks if start <= t.start < end and t.kind not in ("COMMENT", "BOM")]
    stop = len(block)
    for i, t in enumerate(block):
        if t.kind in WORD_KINDS and t.value.upper() in QUERY_TABLE_INTRO:
            stop = i  # секция выборки кончается на ИЗ/СОЕДИНЕНИЕ
            break

    items: list[list[Token]] = [[]]
    depth = 0
    for t in block[1:stop]:  # block[0] – открывающая `{`
        if t.kind == "OP" and t.value in _OPEN_CH:
            depth += 1
        elif t.kind == "OP" and t.value in _CLOSE_CH:
            depth -= 1
        elif depth == 0 and t.kind == "OP" and t.value == ",":
            items.append([])
            continue
        items[-1].append(t)

    out: list[str] = []
    for item in items:
        name = None
        for k in range(len(item) - 2, -1, -1):  # последнее КАК/AS элемента
            if item[k].kind in WORD_KINDS and item[k].value.upper() in QUERY_ALIAS_INTRO:
                name = item[k + 1]
                break
        if name is None and item and item[-1].kind == "IDENT":
            name = item[-1]  # поле без алиаса: имя – последний сегмент цепочки
        if name is not None and name.kind == "IDENT" and name.value not in out:
            out.append(name.value)
    return out


def query_row_columns(source: SourceFile, offset: int) -> dict[str, list[str]]:
    """Переменная цикла -> колонки строки запроса, которую она перебирает, для циклов выше `offset`.

    `знч Р = Запрос{...}.Выполнить()` связывает колонки этого блока с Р, а `для С из Р` переносит
    их на переменную цикла, поэтому `С.` дополняется именами колонок. Ключевые слова двуязычные
    (канонические QUERY/FOR/IN), поэтому обход идёт по токенам.
    """
    toks = tokens(source)
    code = code_tokens(source)
    ranges = query_ranges(source)

    results: dict[str, list[str]] = {}
    for d in declarations(code):
        if d.value_start is None or d.value_start >= len(code):
            continue
        value = code[d.value_start]
        if value.kind != "KEYWORD" or value.canonical != "QUERY":
            continue
        span = next((r for r in ranges if r[0] >= value.start), None)
        if span is None:
            continue
        columns = _query_columns(toks, *span)
        if columns:
            for tok in d.names:
                results[tok.value] = columns

    out: dict[str, list[str]] = {}
    for i, t in enumerate(code[:-3]):
        if not (t.kind == "KEYWORD" and t.canonical == "FOR" and t.start < offset):
            continue
        name, keyword, iterated = code[i + 1], code[i + 2], code[i + 3]
        if name.kind != "IDENT" or keyword.kind != "KEYWORD" or keyword.canonical != "IN":
            continue
        columns = results.get(iterated.value) if iterated.kind == "IDENT" else None
        if columns:
            out[name.value] = columns
    return out


def code_tokens(source: SourceFile) -> list[Token]:
    """Токены кода: без комментариев, без EOF и без содержимого блоков запроса."""
    cached = source.cache.get("code_tokens")
    if cached is not None:
        return cached
    out = [
        t for t in tokens(source)
        if t.kind not in ("COMMENT", "EOF") and not in_query(source, t.start)
    ]
    source.cache["code_tokens"] = out
    return out


def _skip_comments(toks: list[Token], k: int) -> int:
    n = len(toks)
    while k < n and toks[k].kind == "COMMENT":
        k += 1
    return k


# --- Строки исходника -----------------------------------------------------------------

def lines(source: SourceFile) -> list[str]:
    """Строки исходника без переводов строки (строка 1 – индекс 0)."""
    cached = source.cache.get("lines")
    if cached is None:
        cached = source.text.splitlines()
        source.cache["lines"] = cached
    return cached


def line_starts(source: SourceFile) -> list[int]:
    """Смещение начала каждой строки (строка 1 – индекс 0)."""
    cached = source.cache.get("line_starts")
    if cached is not None:
        return cached
    starts, pos = [], 0
    text = source.text
    n = len(text)
    while pos <= n:
        starts.append(pos)
        nl = text.find("\n", pos)
        if nl == -1:
            break
        pos = nl + 1
    source.cache["line_starts"] = starts
    return starts


def line_span(source: SourceFile, line: int) -> tuple[int, int]:
    """Смещения [начало, конец) строки с номером `line` (нумерация с 1), без перевода строки."""
    starts = line_starts(source)
    start = starts[line - 1]
    return start, start + len(lines(source)[line - 1])


def spans_of(source: SourceFile, kinds: tuple[str, ...]) -> list[tuple[int, int]]:
    """Смещения токенов заданных видов (например, STRING/COMMENT) – для проверок по тексту."""
    key = "spans_" + "_".join(kinds)
    cached = source.cache.get(key)
    if cached is None:
        cached = [(t.start, t.end) for t in tokens(source) if t.kind in kinds]
        source.cache[key] = cached
    return cached


def inside(spans: list[tuple[int, int]], offset: int) -> bool:
    """Смещение лежит внутри одного из диапазонов (граница – включительно слева)."""
    idx = bisect.bisect_right([s[0] for s in spans], offset) - 1
    return idx >= 0 and offset < spans[idx][1]


# --- Выражения типов ------------------------------------------------------------------

@dataclass
class TypeExpr:
    """Выражение типа: его токены и альтернативы верхнего уровня (через `|`)."""

    toks: list[Token]
    alternatives: list[list[Token]]
    end: int  # индекс токена за концом выражения


def type_expr(toks: list[Token], start: int) -> TypeExpr | None:
    """Разобрать выражение типа, начинающееся в позиции start (первый токен типа).

    Понимает полные имена (`Справочник.Товары.Ссылка`), обобщения (`Массив<Строка>`), суффикс
    nullable `?` и объединения `Строка|Число|?`. Возвращает None, если в позиции start типа нет.
    """
    n = len(toks)
    i = _skip_comments(toks, start)
    if i >= n or (toks[i].kind != "IDENT" and not _is_undefined(toks[i])):
        return None

    collected: list[Token] = []
    alternatives: list[list[Token]] = [[]]
    depth = 0
    expect_operand = True  # ждём имя типа (начало выражения, после `|`, `<`, `,`, `.`)

    while i < n:
        t = toks[i]
        if t.kind == "COMMENT":
            i += 1
            continue
        if t.kind == "IDENT" or _is_undefined(t):
            if not expect_operand and depth == 0:
                break
            collected.append(t)
            alternatives[-1].append(t)
            expect_operand = False
            i += 1
            continue
        if t.kind == "OP":
            v = t.value
            if v == "." and not expect_operand:
                collected.append(t)
                alternatives[-1].append(t)
                expect_operand = True
                i += 1
                continue
            if v == "<":
                depth += 1
                collected.append(t)
                alternatives[-1].append(t)
                expect_operand = True
                i += 1
                continue
            if v == ">" and depth > 0:
                depth -= 1
                collected.append(t)
                alternatives[-1].append(t)
                expect_operand = False
                i += 1
                continue
            if v == "," and depth > 0:
                collected.append(t)
                alternatives[-1].append(t)
                expect_operand = True
                i += 1
                continue
            if v == "?" and not expect_operand:  # суффикс nullable у типа
                collected.append(t)
                alternatives[-1].append(t)
                i += 1
                continue
            if v == "?" and expect_operand:  # самостоятельная альтернатива `|?`
                collected.append(t)
                alternatives[-1].append(t)
                expect_operand = False
                i += 1
                continue
            if v == "|":
                collected.append(t)
                if depth == 0:
                    alternatives.append([])
                else:
                    alternatives[-1].append(t)
                expect_operand = True
                i += 1
                continue
        break

    if not collected or expect_operand and depth == 0 and not alternatives[-1]:
        # выражение оборвалось на разделителе – разбирать нечего
        return None if not collected else TypeExpr(collected, [a for a in alternatives if a], i)
    return TypeExpr(collected, [a for a in alternatives if a], i)


def _is_undefined(tok: Token) -> bool:
    return tok.kind == "KEYWORD" and tok.canonical == "UNDEFINED"


# --- Объявления и сигнатуры -----------------------------------------------------------

@dataclass
class Declaration:
    """Объявление `знч/пер/поймать/обз Имя[, Имя2]: Тип [= инициализация]`."""

    keyword: Token
    names: list[Token]
    colon: Token | None
    type_start: int | None  # индекс токена, с которого начинается тип
    assign: Token | None  # токен `=`, если есть инициализация
    value_start: int | None  # индекс первого токена значения


def declarations(toks: list[Token]) -> list[Declaration]:
    """Все объявления, вводимые знч/пер/поймать/обз, в списке токенов."""
    out: list[Declaration] = []
    n = len(toks)
    for i, t in enumerate(toks):
        if t.kind != "KEYWORD" or t.canonical not in DECL_KEYWORDS:
            continue
        j = _skip_comments(toks, i + 1)
        names: list[Token] = []
        while j < n and toks[j].kind == "IDENT":
            names.append(toks[j])
            k = _skip_comments(toks, j + 1)
            if k < n and toks[k].kind == "OP" and toks[k].value == ",":
                j = _skip_comments(toks, k + 1)
                continue
            j = k
            break
        if not names:
            continue

        colon = type_start = None
        if j < n and toks[j].kind == "OP" and toks[j].value == ":":
            colon = toks[j]
            type_start = _skip_comments(toks, j + 1)
            te = type_expr(toks, type_start)
            j = te.end if te is not None else type_start

        assign = value_start = None
        j = _skip_comments(toks, j)
        if j < n and toks[j].kind == "OP" and toks[j].value == "=":
            assign = toks[j]
            value_start = _skip_comments(toks, j + 1)

        out.append(Declaration(t, names, colon, type_start, assign, value_start))
    return out


@dataclass
class Param:
    """Параметр метода: имя, двоеточие типа (если есть) и значение по умолчанию."""

    name: Token
    colon: Token | None
    type_start: int | None
    has_default: bool


@dataclass
class Signature:
    """Сигнатура метода или конструктора: имя, параметры и двоеточие типа возвращаемого значения."""

    keyword: Token
    name: Token
    params: list[Param]
    return_colon: Token | None
    return_type_start: int | None


def signatures(toks: list[Token]) -> list[Signature]:
    """Сигнатуры всех методов и конструкторов в списке токенов."""
    out: list[Signature] = []
    n = len(toks)
    for i, t in enumerate(toks):
        if t.kind != "KEYWORD" or t.canonical not in SIGNATURE_KEYWORDS or not t.value[:1].islower():
            continue
        j = _skip_comments(toks, i + 1)
        if j >= n or toks[j].kind != "IDENT":
            continue
        name = toks[j]
        p = _skip_comments(toks, j + 1)
        if p >= n or not (toks[p].kind == "OP" and toks[p].value == "("):
            continue

        params: list[Param] = []
        depth, k = 1, p + 1
        expect_name = True
        current: Param | None = None
        while k < n and depth > 0:
            tk = toks[k]
            if tk.kind == "COMMENT":
                k += 1
                continue
            if tk.kind == "OP" and tk.value in _OPEN_CH:
                depth += 1
                k += 1
                continue
            if tk.kind == "OP" and tk.value in _CLOSE_CH:
                depth -= 1
                k += 1
                continue
            if depth == 1 and expect_name and tk.kind == "IDENT":
                current = Param(tk, None, None, False)
                params.append(current)
                expect_name = False
                c = _skip_comments(toks, k + 1)
                if c < n and toks[c].kind == "OP" and toks[c].value == ":":
                    current.colon = toks[c]
                    current.type_start = _skip_comments(toks, c + 1)
                    te = type_expr(toks, current.type_start)
                    k = te.end if te is not None else current.type_start
                    continue
                k = c
                continue
            if depth == 1 and tk.kind == "OP" and tk.value == "=":
                if current is not None:
                    current.has_default = True
                k += 1
                continue
            if depth == 1 and tk.kind == "OP" and tk.value == ",":
                expect_name = True
                k += 1
                continue
            k += 1

        return_colon = return_type_start = None
        r = _skip_comments(toks, k)
        if r < n and toks[r].kind == "OP" and toks[r].value == ":":
            return_colon = toks[r]
            return_type_start = _skip_comments(toks, r + 1)

        out.append(Signature(t, name, params, return_colon, return_type_start))
    return out


# --- Типы локальных переменных (автодополнение) ---------------------------------------

def _type_head(toks: list[Token], start: int) -> str | None:
    """Голова выражения типа: `Массив<Строка>` -> `Массив`, `Товар.Ссылка?` -> `Товар.Ссылка`.

    Аргументы обобщений и суффикс nullable отбрасываются намеренно: члены типа от них не
    зависят.
    """
    te = type_expr(toks, start)
    if te is None or not te.alternatives:
        return None
    parts: list[str] = []
    for t in te.alternatives[0]:
        if t.kind == "IDENT":
            parts.append(t.value)
        elif t.kind == "OP" and t.value == ".":
            parts.append(".")
        else:
            break  # `<`, `?`, `|` – здесь имя кончается
    return "".join(parts).strip(".") or None


def _constructed_type(toks: list[Token], start: int) -> str | None:
    """Тип инициализатора `новый Массив<Строка>()` либо None, если значение – что-то другое."""
    i = _skip_comments(toks, start)
    if i >= len(toks) or toks[i].kind != "KEYWORD" or toks[i].canonical != "NEW":
        return None
    return _type_head(toks, _skip_comments(toks, i + 1))


def local_var_types(source: SourceFile, offset: int) -> dict[str, str]:
    """Имя переменной -> голова типа для имён, видимых в точке `offset`.

    Собираются параметры объемлющего метода и объявления выше смещения внутри него; тип берётся
    либо из аннотации (`пер Список: Массив<Строка>`), либо из инициализатора
    (`пер Список = новый Массив<Строка>()`). Ключевые слова двуязычные, поэтому обход идёт по
    токенам (канонические VAR/NEW), а не по сырому тексту.

    Метод считается простирающимся от своей сигнатуры до следующей: без AST у тела нет границы,
    а для видимости достаточно не смешивать локальные переменные соседних методов.
    """
    toks = code_tokens(source)
    enclosing = None
    for s in signatures(toks):
        if s.keyword.start > offset:
            break
        enclosing = s
    start = enclosing.keyword.start if enclosing else 0

    out: dict[str, str] = {}
    if enclosing is not None:
        for p in enclosing.params:
            name = _type_head(toks, p.type_start) if p.type_start is not None else None
            if name:
                out[p.name.value] = name
    for d in declarations(toks):
        if not start <= d.keyword.start < offset:
            continue
        if d.type_start is not None:
            name = _type_head(toks, d.type_start)
        elif d.value_start is not None:
            name = _constructed_type(toks, d.value_start)
        else:
            continue
        if not name:
            continue
        for tok in d.names:
            out[tok.value] = name
    return out
