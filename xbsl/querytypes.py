"""The row type of a query literal: the columns of its select list, typed by the project.

`Запрос{ВЫБРАТЬ Т.Ссылка КАК Ссылка ИЗ Товары КАК Т}.Выполнить()` is iterated row by row, and the
compiler types every column of that row by the select list - the field a column reads, as its
table declares it. The cast rules need exactly that: `Запись.Ссылка как Товары.Ссылка` is the
commonest redundant cast of a live project, and the type of the operand lives in the yaml of
the catalog the query reads.

Only the shapes whose type follows from the declarations are answered, and each of them was
shown to the compiler of the platform (the probe project of the cast rules):

- a field of a table in FROM: the type its element declares (an attribute, a dimension, a
  resource, a property of a contract, a standard attribute);
- a field read THROUGH a reference (`Т.Группа.Наименование`) and a field of the joined side of
  an outer join: the same type plus Null - the row may have nothing there;
- `<выражение>.ЗаменитьNull(<значение>)`: the expression without Null, plus the value;
  without an argument the empty value takes the place of Null;
- a literal, `CASE` over typed branches, `COUNT(...)`.

Anything else - a parameter, arithmetic, a subquery, a batch with temporary tables - leaves the
column unknown, and a block the reading does not understand as a whole leaves the ROW unknown:
a cast over it is then never judged.
"""

from __future__ import annotations

import bisect
from dataclasses import dataclass

from xbsl import lexer
from xbsl.typeinfer import ModuleScope, TypeSet, TABULAR_STANDARD_FIELDS, _MISSING_FIELD

_WORD_KINDS = ("IDENT", "KEYWORD")

#: Fields every table of a kind may carry without declaring them: the service fields of a
#: catalog, a document, a register, a tabular section. A column that reads one of them is typed
#: only where `typeinfer.STANDARD_FIELDS` knows the type, but it never breaks the row - a field
#: the project neither declares nor finds here does (see _BrokenQuery).
_SERVICE_FIELDS = frozenset({
    "Ссылка", "ПометкаУдаления", "Владелец", "Родитель", "ЭтоГруппа",
    "Предопределенный", "ИмяПредопределенных", "Дата", "Номер", "Проведен", "Период",
    "Регистратор", "НомерСтроки", "Активность", "ВидДвижения", "КлючЗаписи", "ВерсияДанных",
    "КлючСтроки", "Представление",
})

#: The semantics of the constructs the compiler was asked about; one place to read them.
NULL_THROUGH_REFERENCE = True
NULL_ON_OUTER_JOIN_SIDE = True


def _words(*english: str) -> frozenset[str]:
    from xbsl.rules._syntax import query_words

    return query_words(*english)


def row_type(scope: ModuleScope, start: int, end: int, parameter=None) -> str | None:
    """The canonical name of the row type of the query literal at [start, end), registered in
    the catalog of the scope, or None when the literal is not read.

    `parameter(name)` types a `%Имя` of the literal by the code value of that name."""
    catalog = scope.catalog
    key = f"#Q{len(catalog.rows)}"
    cache = getattr(catalog, "_row_keys", None)
    if cache is None:
        cache = {}
        catalog._row_keys = cache  # type: ignore[attr-defined]
    marker = (scope.module, start, end, hash(scope.text[start:end]))
    if marker in cache:
        return cache[marker]
    if scope.tokens is not None:
        starts = getattr(scope, "_token_starts", None)
        if starts is None:
            starts = [t.start for t in scope.tokens]
            scope._token_starts = starts  # type: ignore[attr-defined]
        first = bisect.bisect_left(starts, start)
        last = bisect.bisect_left(starts, end)
        columns = row_columns_from_tokens(scope.tokens[first:last], scope, parameter)
    else:
        columns = row_columns(scope.text[start:end], scope, parameter)
    got = catalog.register_row(key, columns) if columns is not None else None
    cache[marker] = got
    return got


class _BrokenQuery(Exception):
    """The compiler refuses the query: the row it would produce is not there to be typed.

    A field a table of the project does not have (`Реквизит ... не найден`) or a table the
    project does not know fails the whole literal, and the compiler then types no column of it -
    the probe project showed a single unknown field in the select list silencing every cast over
    the row. Reading the other columns anyway would judge casts the compiler never judges.
    """


@dataclass
class _Table:
    element: str | None          # the element the fields belong to (None: unknown table)
    part: str | None = None      # a tabular section of the element
    nullable: bool = False       # the joined side of an outer join


def row_columns(text: str, scope: ModuleScope, parameter=None) -> dict[str, TypeSet | None] | None:
    """{column: its type or None} of the query literal text, or None for a block not read."""
    try:
        tokens = lexer.tokenize(text)
    except Exception:  # noqa: BLE001 - no data, no query reading
        return None
    return row_columns_from_tokens(tokens, scope, parameter)


def row_columns_from_tokens(tokens: list, scope: ModuleScope,
                            parameter=None) -> dict[str, TypeSet | None] | None:
    """`row_columns` over the tokens of the literal, `Запрос{` to `}`."""
    tokens = [t for t in tokens if t.kind not in ("COMMENT", "BOM", "EOF")]
    # `Запрос { ... }`: the block without the keyword and the braces.
    open_at = next((i for i, t in enumerate(tokens) if t.kind == "OP" and t.value == "{"), None)
    if open_at is None or not tokens or not (tokens[-1].kind == "OP" and tokens[-1].value == "}"):
        return None
    block = tokens[open_at + 1:-1]
    words = {t.value.upper() for t in block if t.kind in _WORD_KINDS}
    if words & _words("INTO", "DROP", "INSERT", "UPDATE", "DELETE", "TRUNCATE", "SET", "HIERARCHY"):
        return None
    if any(t.kind == "OP" and t.value == ";" for t in block):
        return None
    parts = _split_union(block)
    if parts is None:
        return None
    merged: dict[str, TypeSet | None] | None = None
    order: list[str] = []
    for part in parts:
        try:
            columns = _select_columns(part, scope, parameter)
        except _BrokenQuery:
            return None
        if columns is None:
            return None
        if merged is None:
            merged = dict(columns)
            order = list(columns)
            continue
        if len(columns) != len(order):
            return None
        # A union names its columns by the first part and types each by all parts together.
        for name, (_other, got) in zip(order, columns.items()):
            known = merged[name]
            merged[name] = known.union(got) if known is not None and got is not None else None
    return merged


def _split_union(block: list) -> list[list] | None:
    union = _words("UNION")
    everything = _words("ALL")
    parts: list[list] = [[]]
    depth = 0
    index = 0
    while index < len(block):
        token = block[index]
        if token.kind == "OP" and token.value in "([{":
            depth += 1
        elif token.kind == "OP" and token.value in ")]}":
            depth -= 1
        if depth == 0 and token.kind in _WORD_KINDS and token.value.upper() in union:
            parts.append([])
            index += 1
            if index < len(block) and block[index].kind in _WORD_KINDS \
                    and block[index].value.upper() in everything:
                index += 1
            continue
        parts[-1].append(token)
        index += 1
    if depth != 0 or any(not part for part in parts):
        return None
    return parts


def _top_level_indexes(tokens: list, predicate) -> list[int]:
    out: list[int] = []
    depth = 0
    for index, token in enumerate(tokens):
        if token.kind == "OP" and token.value in "([{":
            depth += 1
        elif token.kind == "OP" and token.value in ")]}":
            depth -= 1
        elif depth == 0 and predicate(token):
            out.append(index)
    return out


def _is_word(token, spellings: frozenset[str]) -> bool:
    return token.kind in _WORD_KINDS and token.value.upper() in spellings


def _select_columns(part: list, scope: ModuleScope,
                    parameter=None) -> dict[str, TypeSet | None] | None:
    select = _words("SELECT")
    if not part or not _is_word(part[0], select):
        return None
    index = 1
    allowed = _words("ALLOWED", "DISTINCT")
    top = _words("TOP")
    while index < len(part):
        if _is_word(part[index], allowed):
            index += 1
        elif _is_word(part[index], top) and index + 1 < len(part) and part[index + 1].kind == "NUMBER":
            index += 2
        else:
            break
    clause_words = _words("FROM", "WHERE", "HAVING") | {"СГРУППИРОВАТЬ", "УПОРЯДОЧИТЬ", "GROUP", "ORDER",
                                                         "ИТОГИ", "TOTALS", "ДЛЯ", "FOR"}
    ends = _top_level_indexes(part[index:], lambda t: _is_word(t, clause_words))
    select_end = index + ends[0] if ends else len(part)
    select_list = part[index:select_end]
    tables = _from_tables(part[select_end:], scope)
    if tables is None or any(table.element is None for table in tables.values()):
        return None
    _check_paths(part[select_end:], tables, scope)
    columns: dict[str, TypeSet | None] = {}
    commas = _top_level_indexes(select_list, lambda t: t.kind == "OP" and t.value == ",")
    bounds = [-1] + commas + [len(select_list)]
    as_words = _words("AS")
    for left, right in zip(bounds, bounds[1:]):
        item = select_list[left + 1:right]
        if not item:
            return None
        if len(item) == 1 and item[0].kind == "OP" and item[0].value == "*":
            return None
        alias_at = _top_level_indexes(item, lambda t: _is_word(t, as_words))
        if alias_at and alias_at[-1] == len(item) - 2 and item[-1].kind in _WORD_KINDS:
            name = item[-1].value
            expression = item[:alias_at[-1]]
        else:
            expression = item
            if not (expression[-1].kind in _WORD_KINDS and _is_path(expression)):
                return None
            name = expression[-1].value
        if name in columns:
            return None
        columns[name] = _expression_type(expression, tables, scope, parameter)
    return columns


def _check_paths(tokens: list, tables: dict[str, "_Table"], scope: ModuleScope) -> None:
    """Every `Алиас.Поле` of the clauses after the select list must name a field its table has.

    The compiler refuses the whole literal over one unknown field in a condition as well (the
    probe project: an unknown field in WHERE silenced the cast over a known column), so such a
    field breaks the row here too. A dotted chain stops before a call (`Т.Поле.ЗаменитьNull(...)`),
    a subquery in parentheses and an interpolation (`%{...}`) are not read.
    """
    count = len(tokens)
    index = 0
    depth = 0
    while index < count:
        token = tokens[index]
        if token.kind == "OP" and token.value == "%" and index + 1 < count \
                and tokens[index + 1].kind == "OP" and tokens[index + 1].value == "{":
            close = index + 1
            level = 0
            while close < count:
                if tokens[close].kind == "OP" and tokens[close].value == "{":
                    level += 1
                elif tokens[close].kind == "OP" and tokens[close].value == "}":
                    level -= 1
                    if level == 0:
                        break
                close += 1
            index = close + 1
            continue
        if token.kind == "OP" and token.value == "(":
            depth += 1
        elif token.kind == "OP" and token.value == ")":
            depth -= 1
        elif (depth == 0 and token.kind in _WORD_KINDS and token.value in tables
              and index + 2 < count and tokens[index + 1].kind == "OP" and tokens[index + 1].value == "."
              and (index == 0 or not (tokens[index - 1].kind == "OP" and tokens[index - 1].value == "."))):
            segments = [token]
            cursor = index + 1
            while cursor + 1 < count and tokens[cursor].kind == "OP" and tokens[cursor].value == "." \
                    and tokens[cursor + 1].kind in _WORD_KINDS:
                follower = tokens[cursor + 2] if cursor + 2 < count else None
                if follower is not None and follower.kind == "OP" and follower.value == "(":
                    break
                segments.append(tokens[cursor + 1])
                cursor += 2
            if len(segments) > 1:
                _path(segments, tables, scope)
            index = cursor
            continue
        index += 1


def _is_path(tokens: list) -> bool:
    for index, token in enumerate(tokens):
        if index % 2 == 0 and token.kind not in _WORD_KINDS:
            return False
        if index % 2 == 1 and not (token.kind == "OP" and token.value == "."):
            return False
    return len(tokens) % 2 == 1


def _from_tables(clause: list, scope: ModuleScope) -> dict[str, _Table] | None:
    """{alias or table name: the table} of the FROM clause, None when the clause is not read."""
    if not clause:
        return {}
    if not _is_word(clause[0], _words("FROM")):
        return None
    stop = _words("WHERE", "HAVING") | {"СГРУППИРОВАТЬ", "УПОРЯДОЧИТЬ", "GROUP", "ORDER", "ИТОГИ",
                                         "TOTALS", "ДЛЯ", "FOR"}
    join = _words("JOIN")
    kinds = _words("LEFT", "RIGHT", "FULL", "INNER")
    outer = {"ВНЕШНЕЕ", "OUTER"}
    on_words = _words("ON")
    as_words = _words("AS")
    tables: dict[str, _Table] = {}
    order: list[_Table] = []
    count = len(clause)
    index = 1
    pending_kind = "FROM"
    while index < count:
        token = clause[index]
        # the table itself: a name, dotted into a tabular section, maybe namespace-qualified
        if token.kind not in _WORD_KINDS:
            return None
        segments = [token.value]
        index += 1
        while index + 1 < count and clause[index].kind == "OP" and clause[index].value in (".", "::") \
                and clause[index + 1].kind in _WORD_KINDS:
            if clause[index].value == "::":
                segments = [clause[index + 1].value]
            else:
                segments.append(clause[index + 1].value)
            index += 2
        if index < count and clause[index].kind == "OP" and clause[index].value == "(":
            return None  # a virtual table with parameters
        alias = segments[-1] if len(segments) == 1 else None
        if index + 1 < count and _is_word(clause[index], as_words) and clause[index + 1].kind in _WORD_KINDS:
            alias = clause[index + 1].value
            index += 2
        if alias is None or alias in tables:
            return None
        table = _table(segments, scope)
        if pending_kind in ("LEFT", "FULL"):
            table.nullable = True
        if pending_kind in ("RIGHT", "FULL"):
            for earlier in order:
                earlier.nullable = True
        order.append(table)
        tables[alias] = table
        # the ON condition of a join runs up to the next join, a clause word or the end
        if index < count and _is_word(clause[index], on_words):
            if pending_kind == "FROM":
                return None
            depth = 0
            index += 1
            while index < count:
                word = clause[index]
                if word.kind == "OP" and word.value in "([{":
                    depth += 1
                elif word.kind == "OP" and word.value in ")]}":
                    depth -= 1
                elif depth == 0 and (_is_word(word, kinds) or _is_word(word, join) or _is_word(word, stop)):
                    break
                elif depth == 0 and word.kind == "OP" and word.value == ",":
                    return None
                index += 1
        if index >= count or _is_word(clause[index], stop):
            return tables
        if clause[index].kind == "OP" and clause[index].value == ",":
            pending_kind = "INNER"
            index += 1
            continue
        pending_kind = ""
        while index < count and _is_word(clause[index], kinds):
            pending_kind = _english_join(clause[index].value)
            index += 1
            if index < count and clause[index].kind in _WORD_KINDS and clause[index].value.upper() in outer:
                index += 1
        if index >= count or not _is_word(clause[index], join):
            return None
        index += 1
        pending_kind = pending_kind or "INNER"
    return tables


def _english_join(word: str) -> str:
    upper = word.upper()
    for english in ("LEFT", "RIGHT", "FULL", "INNER"):
        if upper in _words(english):
            return english
    return "INNER"


def _table(segments: list[str], scope: ModuleScope) -> _Table:
    catalog = scope.catalog
    if len(segments) == 1 and segments[0] in catalog.elements:
        return _Table(segments[0])
    if len(segments) == 2 and segments[0] in catalog.elements:
        parts = catalog.elements[segments[0]].get("tabular") or {}
        if segments[1] in parts:
            return _Table(segments[0], segments[1])
    return _Table(None)


def _field(table: _Table, name: str, scope: ModuleScope) -> TypeSet | None:
    catalog = scope.catalog
    if table.element is None:
        return None
    if table.part is not None:
        fields = (catalog.elements[table.element].get("tabular") or {}).get(table.part) or {}
        if name in fields:
            return catalog.written(fields[name], None) if fields[name] else None
        standard = TABULAR_STANDARD_FIELDS.get(name)
        if standard is None:
            if not _service_field(name):
                raise _BrokenQuery(name)
            return None
        return catalog.written(standard.replace("{}", table.element), None)
    written = catalog.field_written(table.element, name)
    if written is _MISSING_FIELD:
        if not _service_field(name):
            raise _BrokenQuery(name)
        return None
    return catalog.written(written, None) if written else None


def _service_field(name: str) -> bool:
    if name in _SERVICE_FIELDS:
        return True
    from xbsl import terms

    russian = terms.russian(name, "properties") or terms.common_russian(name)
    return bool(russian) and russian in _SERVICE_FIELDS


def _expression_type(tokens: list, tables: dict[str, _Table], scope: ModuleScope,
                     parameter=None) -> TypeSet | None:
    """The type of one select expression (see the module docstring for the shapes)."""
    if not tokens:
        return None
    # `%Имя`: the code value of that name
    if len(tokens) == 2 and tokens[0].kind == "OP" and tokens[0].value == "%" \
            and tokens[1].kind in _WORD_KINDS:
        return parameter(tokens[1].value) if parameter is not None else None
    if len(tokens) == 1:
        literal = _literal(tokens[0])
        if literal is not None or tokens[0].kind not in _WORD_KINDS:
            return literal
        return _path(tokens, tables, scope)
    if _is_word(tokens[0], _words("CASE")) and _is_word(tokens[-1], _words("END")) \
            and _case_end(tokens) == len(tokens) - 1:
        return _case(tokens, tables, scope, parameter)
    arithmetic = _arithmetic(tokens, tables, scope, parameter)
    if arithmetic is not _NOT_ARITHMETIC:
        return arithmetic
    if _is_word(tokens[0], _words("CASE")):
        return None
    # a literal of a platform type (`ДатаВремя{}`): the type is the name that opens it
    if (tokens[0].kind in _WORD_KINDS and len(tokens) >= 3 and tokens[1].kind == "OP"
            and tokens[1].value == "{" and tokens[-1].kind == "OP" and tokens[-1].value == "}"):
        from xbsl.typeinfer import platform_head

        head = platform_head(tokens[0].value)
        return TypeSet.of(head) if head else None
    head = tokens[0]
    if head.kind in _WORD_KINDS and len(tokens) >= 3 and tokens[1].kind == "OP" and tokens[1].value == "(" \
            and tokens[-1].kind == "OP" and tokens[-1].value == ")":
        if _is_word(head, _words("COUNT")):
            return TypeSet.of("Число")
        return None
    # a path, maybe with `.ЗаменитьNull(...)` at its end
    if tokens[-1].kind == "OP" and tokens[-1].value == ")":
        open_at = _matching_open(tokens)
        if open_at is None or open_at < 2:
            return None
        function = tokens[open_at - 1]
        if not (function.kind in _WORD_KINDS and function.value.upper() in ("ЗАМЕНИТЬNULL", "REPLACENULL")):
            return None
        if not (tokens[open_at - 2].kind == "OP" and tokens[open_at - 2].value == "."):
            return None
        inner = _expression_type(tokens[:open_at - 2], tables, scope, parameter)
        if inner is None:
            return None
        argument = tokens[open_at + 1:-1]
        if not argument:
            return TypeSet(inner.names, True if inner.null else inner.undefined, False)
        replacement = _expression_type(argument, tables, scope, parameter)
        if replacement is None:
            return None
        return inner.without_null().union(replacement)
    if not _is_path(tokens):
        return None
    return _path(tokens[::2], tables, scope)


_NOT_ARITHMETIC = object()


def _case_end(tokens: list) -> int | None:
    """The index of the `END` that closes the `CASE` at index 0, counting nested ones."""
    case, end = _words("CASE"), _words("END")
    level = 0
    for index, token in enumerate(tokens):
        if _is_word(token, case):
            level += 1
        elif _is_word(token, end):
            level -= 1
            if level == 0:
                return index
    return None


def _arithmetic(tokens: list, tables: dict[str, _Table], scope: ModuleScope, parameter):
    """`А + Б`, `А * 2`: numbers give a number, `+` over two strings a string; anything else, and
    an operand with Null or the empty value, stays unknown. _NOT_ARITHMETIC when the expression has
    no operator at its top level."""
    for operators in (("+", "-"), ("*", "/", "%")):
        marks = [i for i in _top_level_indexes(tokens, lambda t: t.kind == "OP" and t.value in operators)
                 if i > 0 and not (tokens[i - 1].kind == "OP" and tokens[i - 1].value not in (")",))]
        if not marks:
            continue
        bounds = [-1] + marks + [len(tokens)]
        parts = [tokens[a + 1:b] for a, b in zip(bounds, bounds[1:])]
        types = [_expression_type(part, tables, scope, parameter) for part in parts]
        if any(t is None or t.null or t.undefined or not t.single for t in types):
            return None
        if all(t == TypeSet.of("Число") for t in types):
            return TypeSet.of("Число")
        signs = {tokens[i].value for i in marks}
        if signs == {"+"} and all(t == TypeSet.of("Строка") for t in types):
            return TypeSet.of("Строка")
        return None
    return _NOT_ARITHMETIC


def _matching_open(tokens: list) -> int | None:
    depth = 0
    for index in range(len(tokens) - 1, -1, -1):
        token = tokens[index]
        if token.kind == "OP" and token.value == ")":
            depth += 1
        elif token.kind == "OP" and token.value == "(":
            depth -= 1
            if depth == 0:
                return index
    return None


def _path(segments: list, tables: dict[str, _Table], scope: ModuleScope) -> TypeSet | None:
    names = [t.value for t in segments]
    table = tables.get(names[0])
    rest = names[1:]
    if table is None:
        if len(tables) != 1:
            return None
        table = next(iter(tables.values()))
        rest = names
    if not rest:
        return None
    got = _field(table, rest[0], scope)
    null = table.nullable and NULL_ON_OUTER_JOIN_SIDE
    for name in rest[1:]:
        if got is None or len(got.names) != 1 or got.null:
            return None
        head = next(iter(got.names))
        owner, dot, facet = head.partition(".")
        if not dot or facet != "Ссылка" or owner not in scope.catalog.elements:
            return None
        got = _field(_Table(owner), name, scope)
        null = null or NULL_THROUGH_REFERENCE
    if got is None:
        return None
    return TypeSet(got.names, got.undefined, got.null or null)


def _literal(token) -> TypeSet | None:
    if token.kind == "NUMBER":
        return TypeSet.of("Число")
    if token.kind == "STRING":
        return TypeSet.of("Строка")
    if token.kind in _WORD_KINDS:
        upper = token.value.upper()
        if upper in ("ИСТИНА", "ЛОЖЬ", "TRUE", "FALSE"):
            return TypeSet.of("Булево")
        if upper in ("НЕОПРЕДЕЛЕНО", "UNDEFINED"):
            return TypeSet(undefined=True)
        if upper == "NULL":
            return TypeSet(null=True)
    return None


def _case(tokens: list, tables: dict[str, _Table], scope: ModuleScope,
          parameter=None) -> TypeSet | None:
    """`ВЫБОР КОГДА ... ТОГДА r1 ... ИНАЧЕ r КОНЕЦ` - the union of the results."""
    if not _is_word(tokens[-1], _words("END")):
        return None
    when, then, otherwise = _words("WHEN"), _words("THEN"), _words("ELSE")
    inner = tokens[1:-1]
    marks = _top_level_indexes(inner, lambda t: _is_word(t, when | then | otherwise | _words("CASE")))
    # a nested CASE at the top level of a branch makes the marks ambiguous - not read
    if any(_is_word(inner[i], _words("CASE")) for i in marks):
        return None
    results: list[list] = []
    has_else = False
    for position, mark in enumerate(marks):
        token = inner[mark]
        end = marks[position + 1] if position + 1 < len(marks) else len(inner)
        if _is_word(token, then):
            results.append(inner[mark + 1:end])
        elif _is_word(token, otherwise):
            results.append(inner[mark + 1:end])
            has_else = True
    if not results:
        return None
    got: TypeSet | None = None
    for result in results:
        typed = _expression_type(result, tables, scope, parameter)
        if typed is None:
            return None
        got = typed if got is None else got.union(typed)
    if got is not None and not has_else:
        got = TypeSet(got.names, got.undefined, True)
    return got
