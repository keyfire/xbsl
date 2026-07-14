"""Shared syntactic helpers for code rules (tiers B/C).

Collected here is what several rule modules need and what cannot be expressed with a single
pass over the tokens:

- `query_ranges` – offsets of `Запрос{ ... }` blocks. Inside them lives the query language,
  which the XBSL code-writing conventions do not cover (CODE_STYLE, "Область действия"),
  so code rules skip these ranges;
- `code_tokens` – the module tokens without comments and without query-block contents;
- `lines` / `line_span` – access to source lines by number;
- `type_expr` – the tokens of a type expression and the parsing of its alternatives (`Строка|Число|?`);
- `declaration_types` / `method_params` – type positions of declarations and method signatures.

Parsing is token-based, without a full AST: rules must yield zero false positives on the
corpus, so an ambiguous construct is better skipped than guessed.
"""

from __future__ import annotations

import bisect
from dataclasses import dataclass

from xbsllint.engine import SourceFile
from xbsllint.lexer import Token, tokens

# Keywords that introduce a declaration with a type annotation: `знч/пер/конст/поймать/обз Имя: Тип`.
DECL_KEYWORDS = ("VAL", "VAR", "CONST", "CATCH", "REQ")
# Keywords that carry a signature (parameter list and return type).
SIGNATURE_KEYWORDS = ("METHOD", "CONSTRUCTOR")

# The query DSL is a nested language: the lexer sees its words as plain word tokens, so they are
# matched by value (in both languages) rather than by a canonical keyword.
WORD_KINDS = ("IDENT", "KEYWORD")
QUERY_TABLE_INTRO = frozenset({"ИЗ", "FROM", "СОЕДИНЕНИЕ", "JOIN"})  # next word is a table
QUERY_ALIAS_INTRO = frozenset({"КАК", "AS"})  # `ИЗ Акция КАК А`

_OPEN_CH = "([{"
_CLOSE_CH = ")]}"


# --- Запрос{ ... } blocks -------------------------------------------------------------

def query_ranges(source: SourceFile) -> list[tuple[int, int]]:
    """Offsets [start, end) of `Запрос{ ... }` blocks, including the curly braces."""
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
    """The offset falls inside a query block."""
    ranges = query_ranges(source)
    idx = bisect.bisect_right([r[0] for r in ranges], offset) - 1
    return idx >= 0 and offset < ranges[idx][1]


def query_aliases(source: SourceFile, offset: int) -> dict[str, str]:
    """Table alias -> table name inside the query block holding `offset` (empty outside a block).

    `ИЗ Акция КАК А` gives {"А": "Акция"} - without it, completion after `А.` has nothing to
    resolve, and aliases are how the project actually writes its queries. Dotted tables (virtual
    ones like `РегистрСведений.СрезПоследних`) are skipped: their field set is not the object's.
    """
    span = next((r for r in query_ranges(source) if r[0] <= offset < r[1]), None)
    if span is None:
        return {}
    start, end = span
    block = [t for t in tokens(source) if start <= t.start < end and t.kind not in ("COMMENT", "BOM")]

    out: dict[str, str] = {}
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
            out[block[j + 1].value] = table.value
            j += 2
        i = j
    return out


def _query_columns(toks: list[Token], start: int, end: int) -> list[str]:
    """Column names of the query block [start, end): the `КАК Имя` alias, or the last segment of a
    plain field chain (`А.Заголовок` -> `Заголовок`). Computed columns without an alias are skipped -
    their name is not ours to guess.
    """
    block = [t for t in toks if start <= t.start < end and t.kind not in ("COMMENT", "BOM")]
    stop = len(block)
    for i, t in enumerate(block):
        if t.kind in WORD_KINDS and t.value.upper() in QUERY_TABLE_INTRO:
            stop = i  # секция выборки кончается на ИЗ/СОЕДИНЕНИЕ
            break

    items: list[list[Token]] = [[]]
    depth = 0
    for t in block[1:stop]:  # block[0] - открывающая `{`
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
            name = item[-1]  # поле без алиаса: имя - последний сегмент цепочки
        if name is not None and name.kind == "IDENT" and name.value not in out:
            out.append(name.value)
    return out


def query_row_columns(source: SourceFile, offset: int) -> dict[str, list[str]]:
    """Loop variable -> the columns of the query row it iterates, for the loops above `offset`.

    `знч Р = Запрос{...}.Выполнить()` binds the columns of that block to Р, and `для С из Р` carries
    them over to the loop variable, so `С.` can complete to the column names. Keywords are bilingual
    (canonical QUERY/FOR/IN), so the scan runs over tokens.
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
    """Code tokens: without comments, without EOF and without query-block contents."""
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


# --- Source lines ---------------------------------------------------------------------

def lines(source: SourceFile) -> list[str]:
    """Source lines without line breaks (line 1 – index 0)."""
    cached = source.cache.get("lines")
    if cached is None:
        cached = source.text.splitlines()
        source.cache["lines"] = cached
    return cached


def line_starts(source: SourceFile) -> list[int]:
    """Offset of the start of each line (line 1 – index 0)."""
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
    """Offsets [start, end) of the line numbered `line` (1-based), without the line break."""
    starts = line_starts(source)
    start = starts[line - 1]
    return start, start + len(lines(source)[line - 1])


def spans_of(source: SourceFile, kinds: tuple[str, ...]) -> list[tuple[int, int]]:
    """Offsets of tokens of the given kinds (e.g. STRING/COMMENT) – for text-based checks."""
    key = "spans_" + "_".join(kinds)
    cached = source.cache.get(key)
    if cached is None:
        cached = [(t.start, t.end) for t in tokens(source) if t.kind in kinds]
        source.cache[key] = cached
    return cached


def inside(spans: list[tuple[int, int]], offset: int) -> bool:
    """The offset lies within one of the ranges (bounds – left-inclusive)."""
    idx = bisect.bisect_right([s[0] for s in spans], offset) - 1
    return idx >= 0 and offset < spans[idx][1]


# --- Type expressions -----------------------------------------------------------------

@dataclass
class TypeExpr:
    """A type expression: its tokens and top-level alternatives (via `|`)."""

    toks: list[Token]
    alternatives: list[list[Token]]
    end: int  # index of the token past the end of the expression


def type_expr(toks: list[Token], start: int) -> TypeExpr | None:
    """Parse a type expression starting at position start (the first type token).

    Understands FQNs (`Справочник.Товары.Ссылка`), generics (`Массив<Строка>`), the nullable
    suffix `?` and unions `Строка|Число|?`. Returns None if there is no type at position start.
    """
    n = len(toks)
    i = _skip_comments(toks, start)
    if i >= n or (toks[i].kind != "IDENT" and not _is_undefined(toks[i])):
        return None

    collected: list[Token] = []
    alternatives: list[list[Token]] = [[]]
    depth = 0
    expect_operand = True  # expect a type name (start of the expression, after `|`, `<`, `,`, `.`)

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
            if v == "?" and not expect_operand:  # nullable type suffix
                collected.append(t)
                alternatives[-1].append(t)
                i += 1
                continue
            if v == "?" and expect_operand:  # standalone `|?` alternative
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
        # the expression broke off at a separator – nothing to parse
        return None if not collected else TypeExpr(collected, [a for a in alternatives if a], i)
    return TypeExpr(collected, [a for a in alternatives if a], i)


def _is_undefined(tok: Token) -> bool:
    return tok.kind == "KEYWORD" and tok.canonical == "UNDEFINED"


# --- Declarations and signatures ------------------------------------------------------

@dataclass
class Declaration:
    """A declaration `знч/пер/поймать/обз Имя[, Имя2]: Тип [= инициализация]`."""

    keyword: Token
    names: list[Token]
    colon: Token | None
    type_start: int | None  # index of the token where the type begins
    assign: Token | None  # the `=` token, if there is an initialization
    value_start: int | None  # index of the first token of the value


def declarations(toks: list[Token]) -> list[Declaration]:
    """All declarations introduced by знч/пер/поймать/обз in the token list."""
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
    """A method parameter: name, the type colon (if any) and the default value."""

    name: Token
    colon: Token | None
    type_start: int | None
    has_default: bool


@dataclass
class Signature:
    """A method/constructor signature: name, parameters and the return-type colon."""

    keyword: Token
    name: Token
    params: list[Param]
    return_colon: Token | None
    return_type_start: int | None


def signatures(toks: list[Token]) -> list[Signature]:
    """Signatures of all methods and constructors in the token list."""
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


# --- Types of local variables (completion) --------------------------------------------

def _type_head(toks: list[Token], start: int) -> str | None:
    """The head of a type expression: `Массив<Строка>` -> `Массив`, `Товар.Ссылка?` -> `Товар.Ссылка`.

    Generic arguments and the nullable suffix are dropped on purpose: the members of a type do
    not depend on them.
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
            break  # `<`, `?`, `|` - the name ends here
    return "".join(parts).strip(".") or None


def _constructed_type(toks: list[Token], start: int) -> str | None:
    """The type of an initializer `новый Массив<Строка>()`, or None when the value is something else."""
    i = _skip_comments(toks, start)
    if i >= len(toks) or toks[i].kind != "KEYWORD" or toks[i].canonical != "NEW":
        return None
    return _type_head(toks, _skip_comments(toks, i + 1))


def local_var_types(source: SourceFile, offset: int) -> dict[str, str]:
    """Variable name -> type head for the names visible at `offset`.

    Collected are the parameters of the enclosing method and the declarations above the offset
    inside it; the type comes either from the annotation (`пер Список: Массив<Строка>`) or from
    the initializer (`пер Список = новый Массив<Строка>()`). Keywords are bilingual, so the scan
    runs over tokens (canonical VAR/NEW) and never over the raw text.

    A method spans from its signature to the next one: without an AST the body has no boundary,
    and for visibility it is enough not to mix the locals of neighbouring methods.
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
