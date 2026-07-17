"""Shared syntax helpers for the code rules (tiers B/C).

Collected here is what several rule modules need at once and what cannot be expressed as a
single pass over the tokens:

- `query_ranges` - offsets of `Запрос{ ... }` blocks. Inside them lives the query language,
  which the XBSL code conventions do not cover (CODE_STYLE, "Область действия"), so the code
  rules skip these ranges;
- `code_tokens` - module tokens without comments and without the contents of query blocks;
- `lines` / `line_span` - access to source lines by number;
- `type_expr` - the tokens of a type expression and the parsing of its alternatives
  (`Строка|Число|?`);
- `declaration_types` / `method_params` - the positions of types in declarations and method
  signatures.

The parsing works on tokens, without a full AST: the rules must produce zero false positives
on the corpus, so an ambiguous construct is better skipped than guessed.
"""

from __future__ import annotations

import bisect
from dataclasses import dataclass

from xbsl.engine import SourceFile
from xbsl.lexer import Token, tokens

# Keywords that introduce a declaration with a type annotation: `знч/пер/конст/поймать/обз Имя: Тип`.
DECL_KEYWORDS = ("VAL", "VAR", "CONST", "CATCH", "REQ")
# Keywords that carry a signature (a parameter list and a return type).
SIGNATURE_KEYWORDS = ("METHOD", "CONSTRUCTOR")

# The query DSL is a nested language: the lexer sees its words as ordinary word tokens, so they
# are matched by value (in both languages), not by the canonical keyword.
WORD_KINDS = ("IDENT", "KEYWORD")
QUERY_TABLE_INTRO = frozenset({"ИЗ", "FROM", "СОЕДИНЕНИЕ", "JOIN"})  # the next word is a table
QUERY_ALIAS_INTRO = frozenset({"КАК", "AS"})  # `ИЗ Акция КАК А`

_OPEN_CH = "([{"
_CLOSE_CH = ")]}"


# --- Запрос{ ... } blocks --------------------------------------------------------------

def query_ranges(source: SourceFile) -> list[tuple[int, int]]:
    """[start, end) offsets of `Запрос{ ... }` blocks, including the braces themselves."""
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
    """Whether the offset falls inside a query block."""
    ranges = query_ranges(source)
    idx = bisect.bisect_right([r[0] for r in ranges], offset) - 1
    return idx >= 0 and offset < ranges[idx][1]


def query_alias_pairs(block: list[Token]) -> list[tuple[str, str]]:
    """(alias, table) pairs of a query block, in order of appearance.

    `ИЗ Акция КАК А` yields ("А", "Акция"). Dotted tables (virtual ones like
    `РегистрСведений.СрезПоследних`) are skipped: their field set is not the object's field
    set. Pairs rather than a dict: an alias may be redefined in a subquery, and whoever relies
    on the pairs must be able to notice that.
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
            i = j  # a subquery or an interpolation in the table position
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
    """Significant tokens of the query block [start, end): no comments, no BOM."""
    start, end = span
    return [t for t in tokens(source) if start <= t.start < end and t.kind not in ("COMMENT", "BOM")]


def query_aliases(source: SourceFile, offset: int) -> dict[str, str]:
    """Table alias -> table name inside the query block containing `offset` (empty outside).

    Without this, completion after `А.` has nothing to resolve: queries in a project are
    written through aliases. A redefined alias resolves to the last occurrence - completion is
    better off offering something than nothing.
    """
    span = next((r for r in query_ranges(source) if r[0] <= offset < r[1]), None)
    if span is None:
        return {}
    return dict(query_alias_pairs(query_block_tokens(source, span)))


def _query_columns(toks: list[Token], start: int, end: int) -> list[str]:
    """Column names of the query block [start, end): the `КАК Имя` alias or the last segment
    of a plain field chain (`А.Заголовок` -> `Заголовок`). Computed columns without an alias
    are skipped - guessing their name is not our job.
    """
    block = [t for t in toks if start <= t.start < end and t.kind not in ("COMMENT", "BOM")]
    stop = len(block)
    for i, t in enumerate(block):
        if t.kind in WORD_KINDS and t.value.upper() in QUERY_TABLE_INTRO:
            stop = i  # the select section ends at ИЗ/СОЕДИНЕНИЕ
            break

    items: list[list[Token]] = [[]]
    depth = 0
    for t in block[1:stop]:  # block[0] is the opening `{`
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
        for k in range(len(item) - 2, -1, -1):  # the item's last КАК/AS
            if item[k].kind in WORD_KINDS and item[k].value.upper() in QUERY_ALIAS_INTRO:
                name = item[k + 1]
                break
        if name is None and item and item[-1].kind == "IDENT":
            name = item[-1]  # a field without an alias: the name is the last segment of the chain
        if name is not None and name.kind == "IDENT" and name.value not in out:
            out.append(name.value)
    return out


def query_row_columns(source: SourceFile, offset: int) -> dict[str, list[str]]:
    """Loop variable -> columns of the query row it iterates over, for loops above `offset`.

    `знч Р = Запрос{...}.Выполнить()` binds the columns of that block to Р, and `для С из Р`
    carries them over to the loop variable, so `С.` is completed with the column names.
    Keywords are bilingual (canonical QUERY/FOR/IN), so the walk goes over tokens.
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
    """Code tokens: no comments, no EOF and no query block contents."""
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


# --- Source lines -----------------------------------------------------------------------

def lines(source: SourceFile) -> list[str]:
    """Source lines without line breaks (line 1 is index 0)."""
    cached = source.cache.get("lines")
    if cached is None:
        cached = source.text.splitlines()
        source.cache["lines"] = cached
    return cached


def line_starts(source: SourceFile) -> list[int]:
    """The offset of the start of each line (line 1 is index 0)."""
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
    """[start, end) offsets of the line numbered `line` (1-based), without the line break."""
    starts = line_starts(source)
    start = starts[line - 1]
    return start, start + len(lines(source)[line - 1])


def spans_of(source: SourceFile, kinds: tuple[str, ...]) -> list[tuple[int, int]]:
    """Offsets of tokens of the given kinds (e.g. STRING/COMMENT) - for text-based checks."""
    key = "spans_" + "_".join(kinds)
    cached = source.cache.get(key)
    if cached is None:
        cached = [(t.start, t.end) for t in tokens(source) if t.kind in kinds]
        source.cache[key] = cached
    return cached


def inside(spans: list[tuple[int, int]], offset: int) -> bool:
    """Whether the offset lies inside one of the spans (left boundary inclusive)."""
    idx = bisect.bisect_right([s[0] for s in spans], offset) - 1
    return idx >= 0 and offset < spans[idx][1]


# --- Type expressions -------------------------------------------------------------------

@dataclass
class TypeExpr:
    """A type expression: its tokens and the top-level alternatives (split by `|`)."""

    toks: list[Token]
    alternatives: list[list[Token]]
    end: int  # index of the token right past the expression


def type_expr(toks: list[Token], start: int) -> TypeExpr | None:
    """Parse a type expression starting at position start (the first token of the type).

    Understands full names (`Справочник.Товары.Ссылка`), generics (`Массив<Строка>`), the
    nullable suffix `?` and unions `Строка|Число|?`. Returns None when there is no type at
    position start.
    """
    n = len(toks)
    i = _skip_comments(toks, start)
    if i >= n or (toks[i].kind != "IDENT" and not _is_undefined(toks[i])):
        return None

    collected: list[Token] = []
    alternatives: list[list[Token]] = [[]]
    depth = 0
    expect_operand = True  # expecting a type name (expression start, after `|`, `<`, `,`, `.`)

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
            if v == "?" and not expect_operand:  # the nullable suffix of a type
                collected.append(t)
                alternatives[-1].append(t)
                i += 1
                continue
            if v == "?" and expect_operand:  # a standalone `|?` alternative
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
        # the expression broke off at a separator - nothing to parse
        return None if not collected else TypeExpr(collected, [a for a in alternatives if a], i)
    return TypeExpr(collected, [a for a in alternatives if a], i)


def _is_undefined(tok: Token) -> bool:
    return tok.kind == "KEYWORD" and tok.canonical == "UNDEFINED"


# --- Declarations and signatures --------------------------------------------------------

@dataclass
class Declaration:
    """A `знч/пер/поймать/обз Имя[, Имя2]: Тип [= инициализация]` declaration."""

    keyword: Token
    names: list[Token]
    colon: Token | None
    type_start: int | None  # index of the token where the type starts
    assign: Token | None  # the `=` token, when there is an initialization
    value_start: int | None  # index of the first value token


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
    """A method parameter: the name, the type colon (if any) and the default value."""

    name: Token
    colon: Token | None
    type_start: int | None
    has_default: bool


@dataclass
class Signature:
    """A method or constructor signature: the name, the parameters and the return type colon."""

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
            # A parameter name may coincide with a language keyword (`Запрос: HttpСервисЗапрос`,
            # `Метод: Строка`): in the name position the lexer still emits KEYWORD, so any word
            # is accepted here - otherwise the parameter is lost and its TYPE is taken for the
            # next parameter.
            if depth == 1 and expect_name and tk.kind in WORD_KINDS:
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


# --- Local variable types (completion) --------------------------------------------------

def _type_head(toks: list[Token], start: int) -> str | None:
    """The head of a type expression: `Массив<Строка>` -> `Массив`, `Товар.Ссылка?` -> `Товар.Ссылка`.

    Generic arguments and the nullable suffix are dropped on purpose: the type's members do
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


def _skip_balanced(toks: list[Token], i: int, open_op: str, close_op: str) -> int:
    """Index just past the bracket pair opening at i (i must sit on `open_op`)."""
    depth = 0
    n = len(toks)
    while i < n:
        t = toks[i]
        if t.kind == "OP":
            if t.value == open_op:
                depth += 1
            elif t.value == close_op:
                depth -= 1
                if depth == 0:
                    return i + 1
        i += 1
    return n


def chain_type(
    toks: list[Token],
    start: int,
    resolve_root,
    returns: dict | None,
    stop_offset: int | None = None,
) -> str | None:
    """The type of a call chain `Корень.Метод(...).Метод2(...)` starting at `start`.

    The root is a constructor (`новый Тип`), a query literal (`Запрос{...}` ->
    ТипизированныйЗапрос) or a name resolved by `resolve_root` (a local variable's type
    or a stdlib type used statically). Every further link must be a CALL - property types
    are not in the catalog, an unresolved link ends the inference. Links starting at or
    past `stop_offset` are not consumed (completion looks at an unfinished chain whose
    tail is already typed to the right of the cursor).
    """
    i = _skip_comments(toks, start)
    n = len(toks)
    if i >= n:
        return None
    t = toks[i]
    current: str | None = None
    if t.kind == "KEYWORD" and t.canonical == "QUERY":
        # A query literal constructs a typed query (docs topics/query-literal).
        current = "ТипизированныйЗапрос"
        i += 1
        if i < n and toks[i].kind == "OP" and toks[i].value == "{":
            i = _skip_balanced(toks, i, "{", "}")
    elif t.kind == "KEYWORD" and t.canonical == "NEW":
        j = _skip_comments(toks, i + 1)
        te = type_expr(toks, j)
        current = _type_head(toks, j)
        if te is None or current is None:
            return None
        # past the type expression (dots inside generics are not chain links),
        # then past the constructor parentheses
        j = te.end
        i = _skip_balanced(toks, j, "(", ")") if (
            j < n and toks[j].kind == "OP" and toks[j].value == "("
        ) else j
    elif t.kind == "IDENT":
        current = resolve_root(t.value)
        if current is None:
            return None
        i += 1
    else:
        return None
    # the call links: .Имя(...) each
    while i < n and toks[i].kind == "OP" and toks[i].value == ".":
        if stop_offset is not None and toks[i].start >= stop_offset:
            break
        j = _skip_comments(toks, i + 1)
        if j >= n or toks[j].kind != "IDENT":
            break
        k = _skip_comments(toks, j + 1)
        if k >= n or toks[k].kind != "OP" or toks[k].value != "(":
            return None  # a property link - its type is not in the catalog
        current = (returns or {}).get(current, {}).get(toks[j].value)
        if current is None:
            return None
        i = _skip_balanced(toks, k, "(", ")")
    return current


def _constructed_type(
    toks: list[Token], start: int,
    resolve_root=None, returns: dict | None = None,
) -> str | None:
    """The type of an initializer: `новый Массив<Строка>()`, `Запрос{...}` or a call
    chain over a known root (`КлиентHttp.СБазовымUrl(...)`), or None."""
    return chain_type(toks, start, resolve_root or (lambda _name: None), returns)


def chain_type_at(
    source: SourceFile, offset: int,
    var_types: dict | None = None,
    returns: dict | None = None,
    static_roots=None,
) -> str | None:
    """The type of the call chain to the LEFT of the dot at `offset` (the cursor sits
    right after the dot, possibly with a partially typed name): the completion context
    of `ЗапросКБД.Выполнить().|`. Walks back to the chain root, then forward via
    `chain_type`, not consuming the links to the right of the cursor."""
    toks = code_tokens(source)
    idx = -1
    for k, t in enumerate(toks):
        if t.end <= offset:
            idx = k
        else:
            break
    if idx < 0:
        return None
    if toks[idx].kind == "IDENT" and idx > 0:
        idx -= 1  # a partially typed member name after the dot
    if not (toks[idx].kind == "OP" and toks[idx].value == "."):
        return None
    stop = toks[idx].start
    j = idx - 1
    root_i: int | None = None
    while j >= 0:
        t = toks[j]
        if t.kind == "OP" and t.value in (")", "}"):
            close, open_ = (")", "(") if t.value == ")" else ("}", "{")
            depth = 0
            while j >= 0:
                tk = toks[j]
                if tk.kind == "OP" and tk.value == close:
                    depth += 1
                elif tk.kind == "OP" and tk.value == open_:
                    depth -= 1
                    if depth == 0:
                        break
                j -= 1
            j -= 1  # onto the method name / the query keyword / the type head
            continue
        if t.kind == "IDENT":
            if j > 0 and toks[j - 1].kind == "OP" and toks[j - 1].value == ".":
                j -= 2
                continue
            root_i = j - 1 if (
                j > 0 and toks[j - 1].kind == "KEYWORD" and toks[j - 1].canonical == "NEW"
            ) else j
            break
        if t.kind == "KEYWORD" and t.canonical in ("QUERY", "NEW"):
            root_i = j
            break
        return None
    if root_i is None:
        return None
    vt = var_types or {}

    def resolve_root(name: str) -> str | None:
        got = vt.get(name)
        if got is not None:
            return got
        if static_roots is not None and name in static_roots:
            return name
        return None

    return chain_type(toks, root_i, resolve_root, returns, stop_offset=stop)


def local_var_types(
    source: SourceFile, offset: int,
    returns: dict | None = None, static_roots=None,
) -> dict[str, str]:
    """Variable name -> type head for the names visible at `offset`.

    Collects the parameters of the enclosing method and the declarations above the offset
    within it; the type comes from the annotation (`пер Список: Массив<Строка>`) or from
    the initializer - a constructor, a query literal or, when the caller passes the
    method-return catalog (`returns`) and the set of static type roots (`static_roots`,
    e.g. the stdlib type names), a call chain like `КлиентHttp.СБазовымUrl(...)`.
    Keywords are bilingual, so the walk goes over tokens, not over the raw text.

    A method is taken to extend from its signature to the next one: without an AST the body
    has no boundary, and for visibility it is enough not to mix the local variables of
    adjacent methods.
    """
    toks = code_tokens(source)
    enclosing = None
    for s in signatures(toks):
        if s.keyword.start > offset:
            break
        enclosing = s
    start = enclosing.keyword.start if enclosing else 0

    out: dict[str, str] = {}

    def resolve_root(name: str) -> str | None:
        got = out.get(name)
        if got is not None:
            return got
        if static_roots is not None and name in static_roots:
            return name
        return None

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
            name = _constructed_type(toks, d.value_start, resolve_root, returns)
        else:
            continue
        if not name:
            continue
        for tok in d.names:
            out[tok.value] = name
    return out
