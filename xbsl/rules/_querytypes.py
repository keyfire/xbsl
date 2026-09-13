"""The type of a column of a query literal, read off the SELECT list and the project's fields.

A loop over `Запрос{...}.Выполнить()` hands out rows, and the editor types a column of a row by
the expression that selects it: a field of the table behind an alias has the type its yaml
declares, a field read THROUGH a reference also holds `Null` (the reference may be empty), and
`.ЗаменитьNull(<literal>)` takes the `Null` out and puts the type of the literal in. A union of
several SELECT parts merges the columns by position. That is how a live module ends up with a
check whose result the editor reports as known in advance: the column is
`<reference>.<number field>.ЗаменитьNull(0)` in both parts of the union, so it is a number whatever
the data.

The reading is split the way the engine runs a project rule. The map phase describes a column
without the project - `column_shapes` names, for every part of the union, the table behind the
alias, the fields read off it and the literal of the null replacement; the reduce phase types
the description with the fields every yaml of the project declares (`resolve`).

Deliberately narrow, so that doubt keeps silence: a batch of statements, a temporary table, a
right or a full join, a comma list of tables, a subquery in the table position, a field without
a declared type (the standard ones included) and any expression other than a field chain or a
literal leave the column unknown. So does a field declared with `?`: a query keeps the empty
value of such a field in a way the probes of this rule did not settle.
"""

from __future__ import annotations

from collections.abc import Iterable

from xbsl import terms
from xbsl.engine import SourceFile
from xbsl.lexer import Token
from xbsl.rules._syntax import WORD_KINDS, query_block_tokens, query_words
from xbsl.rules._typesets import TypeSet, parse_type

#: The type a query adds to a field read through a reference.
NULL = "Null"

_LITERAL_KINDS = {"NUMBER": "Число", "STRING": "Строка", "TRUE": "Булево", "FALSE": "Булево"}


def _words(*english: str) -> frozenset[str]:
    return frozenset(word.casefold() for word in query_words(*english))


def _replace_null_spellings() -> frozenset[str]:
    english = terms.common_english("ЗаменитьNull")
    return frozenset(word.casefold() for word in ("ЗаменитьNull", english) if word)


def _is_word(token: Token, words: frozenset[str]) -> bool:
    return token.kind in WORD_KINDS and token.value.casefold() in words


def _split_top(tokens: list[Token], is_separator) -> list[list[Token]]:
    parts: list[list[Token]] = [[]]
    depth = 0
    for index, token in enumerate(tokens):
        if token.kind == "OP" and token.value == "(":
            depth += 1
        elif token.kind == "OP" and token.value == ")":
            depth -= 1
        elif depth == 0 and is_separator(tokens, index):
            parts.append([])
            continue
        parts[-1].append(token)
    return parts


def column_shapes(source: SourceFile, span: tuple[int, int], column: str) -> list | None:
    """For every SELECT part of the literal at `span`, how it selects `column`; None when unsure.

    A shape is `["lit", <type>]` for a literal and `["chain", <table>, <alias may be null>,
    [<fields>], <replacement type or None>]` for a field chain - plain data, so it travels from
    a worker process to the reduce phase.
    """
    tokens = query_block_tokens(source, span)
    # The literal's own head: `Query` and the braces around the text.
    while tokens and not (tokens[0].kind == "OP" and tokens[0].value == "{"):
        tokens = tokens[1:]
    if len(tokens) < 2 or not (tokens[-1].kind == "OP" and tokens[-1].value == "}"):
        return None
    body = tokens[1:-1]
    if any(token.kind == "OP" and token.value == ";" for token in body):
        return None
    union, every = _words("UNION"), _words("ALL")
    parts = _split_top(body, lambda toks, i: _is_word(toks[i], union))
    parts = [part[1:] if part and _is_word(part[0], every) else part for part in parts]
    columns: list[list[Token]] | None = None
    index: int | None = None
    shapes: list = []
    for number, part in enumerate(parts):
        read = _read_part(part)
        if read is None:
            return None
        items, aliases = read
        if number == 0:
            columns = items
            index = _column_index(items, column)
            if index is None:
                return None
        if columns is None or index is None or len(items) != len(columns):
            return None
        shape = _item_shape(_item_expression(items[index]), aliases)
        if shape is None:
            return None
        shapes.append(shape)
    return shapes or None


def _read_part(part: list[Token]) -> tuple[list[list[Token]], dict[str, tuple[str | None, bool]]] | None:
    """(the select items, {alias: (table or None, may be null)}) of one SELECT part."""
    select = _words("SELECT")
    if not part or not _is_word(part[0], select):
        return None
    position = 1
    skippable = _words("ALLOWED", "DISTINCT")
    while position < len(part) and _is_word(part[position], skippable):
        position += 1
    if position < len(part) and _is_word(part[position], _words("TOP")):
        position += 2
    clauses = _words("FROM", "INTO", "WHERE", "GROUP BY", "HAVING", "ORDER BY", "FOR UPDATE")
    clause_heads = frozenset(word.split()[0] for word in clauses)
    depth, end = 0, len(part)
    for at in range(position, len(part)):
        token = part[at]
        if token.kind == "OP" and token.value == "(":
            depth += 1
        elif token.kind == "OP" and token.value == ")":
            depth -= 1
        elif depth == 0 and _is_word(token, clause_heads):
            end = at
            break
    items = _split_top(part[position:end], lambda toks, i: toks[i].kind == "OP" and toks[i].value == ",")
    if end >= len(part) or not _is_word(part[end], _words("FROM")):
        return None
    aliases = _read_from(part[end + 1:], clause_heads)
    if aliases is None:
        return None
    return items, aliases


def _read_from(tokens: list[Token], clause_heads: frozenset[str]) -> dict[str, tuple[str | None, bool]] | None:
    depth, end = 0, len(tokens)
    for at, token in enumerate(tokens):
        if token.kind == "OP" and token.value == "(":
            depth += 1
        elif token.kind == "OP" and token.value == ")":
            depth -= 1
        elif depth == 0 and _is_word(token, clause_heads):
            end = at
            break
        elif depth == 0 and token.kind == "OP" and token.value == ",":
            return None
    tokens = tokens[:end]
    join, left, inner = _words("JOIN"), _words("LEFT"), _words("INNER")
    unsupported = _words("RIGHT", "FULL")
    aliases: dict[str, tuple[str | None, bool]] = {}
    table = _read_table(tokens, 0, aliases, False)
    if table is None:
        return None
    position = table
    depth = 0
    while position < len(tokens):
        token = tokens[position]
        if token.kind == "OP" and token.value == "(":
            depth += 1
        elif token.kind == "OP" and token.value == ")":
            depth -= 1
        elif depth == 0 and _is_word(token, unsupported):
            return None
        elif depth == 0 and (_is_word(token, left) or _is_word(token, inner) or _is_word(token, join)):
            nullable = _is_word(token, left)
            if not _is_word(token, join):
                position += 1
                if position >= len(tokens) or not _is_word(tokens[position], join):
                    return None
            after = _read_table(tokens, position + 1, aliases, nullable)
            if after is None:
                return None
            position = after
            continue
        position += 1
    return aliases


def _read_table(tokens: list[Token], position: int, aliases: dict[str, tuple[str | None, bool]],
                nullable: bool) -> int | None:
    """Read `Таблица[.Секция] [КАК] Псевдоним` at `position`; the index after it, or None."""
    if position >= len(tokens):
        return None
    table: str | None = None
    token = tokens[position]
    if token.kind == "OP" and token.value == "(":
        depth = 0
        while position < len(tokens):
            if tokens[position].kind == "OP" and tokens[position].value == "(":
                depth += 1
            elif tokens[position].kind == "OP" and tokens[position].value == ")":
                depth -= 1
                if depth == 0:
                    break
            position += 1
        position += 1
    elif token.kind in WORD_KINDS:
        segments = [token.value]
        position += 1
        while (position + 1 < len(tokens) and tokens[position].kind == "OP"
               and tokens[position].value == "." and tokens[position + 1].kind in WORD_KINDS):
            segments.append(tokens[position + 1].value)
            position += 2
        if position < len(tokens) and tokens[position].kind == "OP" and tokens[position].value in ("(", "::"):
            return None
        table = ".".join(segments)
    else:
        return None
    if position < len(tokens) and _is_word(tokens[position], _words("AS")):
        position += 1
    if position >= len(tokens) or tokens[position].kind not in WORD_KINDS:
        return None
    alias = tokens[position].value.casefold()
    if alias in aliases:
        return None
    aliases[alias] = (table, nullable)
    return position + 1


def _column_index(items: list[list[Token]], column: str) -> int | None:
    wanted = column.casefold()
    found = [index for index, item in enumerate(items) if (_item_name(item) or "").casefold() == wanted]
    return found[0] if len(found) == 1 else None


def _item_name(item: list[Token]) -> str | None:
    as_words = _words("AS")
    for at in range(len(item) - 2, -1, -1):
        if _is_word(item[at], as_words) and item[at + 1].kind in WORD_KINDS:
            return item[at + 1].value if at + 2 == len(item) else None
    if item and item[-1].kind in WORD_KINDS and _chain(item) is not None:
        return item[-1].value
    return None


def _item_expression(item: list[Token]) -> list[Token]:
    as_words = _words("AS")
    if len(item) >= 3 and _is_word(item[-2], as_words):
        return item[:-2]
    return item


def _chain(tokens: list[Token]) -> list[str] | None:
    """`А.Б.В` -> ["А", "Б", "В"], or None when the tokens are not a plain dotted chain."""
    if not tokens or len(tokens) % 2 == 0:
        return None
    words: list[str] = []
    for at, token in enumerate(tokens):
        if at % 2 == 0:
            if token.kind not in WORD_KINDS:
                return None
            words.append(token.value)
        elif not (token.kind == "OP" and token.value == "."):
            return None
    return words


def _item_shape(expression: list[Token], aliases: dict[str, tuple[str | None, bool]]) -> list | None:
    if len(expression) == 1 and expression[0].kind in _LITERAL_KINDS:
        return ["lit", _LITERAL_KINDS[expression[0].kind]]
    replacement: str | None = None
    tokens = expression
    if (len(tokens) >= 6 and tokens[-1].kind == "OP" and tokens[-1].value == ")"
            and tokens[-3].kind == "OP" and tokens[-3].value == "("
            and tokens[-4].kind in WORD_KINDS and tokens[-4].value.casefold() in _replace_null_spellings()
            and tokens[-5].kind == "OP" and tokens[-5].value == "."):
        literal = tokens[-2]
        if literal.kind not in _LITERAL_KINDS:
            return None
        replacement = _LITERAL_KINDS[literal.kind]
        tokens = tokens[:-5]
    words = _chain(tokens)
    if words is None or len(words) < 2:
        return None
    target = aliases.get(words[0].casefold())
    if target is None or target[0] is None:
        return None
    table, nullable = target
    return ["chain", table, nullable, words[1:], replacement]


def resolve(shapes: Iterable[list], fields_of) -> TypeSet | None:
    """The type of a column from its shapes; `fields_of(table)` answers {field: written type}."""
    merged: TypeSet | None = None
    for shape in shapes:
        got = _resolve_shape(shape, fields_of)
        if got is None:
            return None
        merged = got if merged is None else merged.merge(got)
    return merged


def _resolve_shape(shape: list, fields_of) -> TypeSet | None:
    if shape[0] == "lit":
        return TypeSet(frozenset({shape[1]}))
    _kind, table, nullable, fields, replacement = shape
    record = fields_of(table)
    null = bool(nullable)
    final: TypeSet | None = None
    for index, name in enumerate(fields):
        if record is None:
            return None
        written = record.get(name.casefold())
        types = parse_type(written) if isinstance(written, str) else None
        if types is None or types.undefined and index == len(fields) - 1:
            return None
        if index == len(fields) - 1:
            final = types
            break
        if len(types.names) != 1:
            return None
        (reference,) = types.names
        owner, dot, facet = reference.rpartition(".")
        if not dot or facet != "Ссылка":
            return None
        record = fields_of(owner)
        null = True
    if final is None:
        return None
    names = set(final.names)
    if null:
        names.add(NULL)
    if replacement is not None:
        names.discard(NULL)
        names.add(replacement)
    return TypeSet(frozenset(names))
