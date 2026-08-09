"""Checks of the query DSL (`Запрос{ ... }` blocks).

query/unknown-table - a table referenced by ИЗ/СОЕДИНЕНИЕ (FROM/JOIN) must be an object of the
project, and `<Объект>.<Секция>` must name a tabular section of that object. Otherwise such
errors only show up in the database at run time.

query/in-subquery-composite - the platform standard "Использование выражения В с подзапросом для
выражений составного типа": on most DBMSs that variant is implemented inefficiently, the
condition is written via СУЩЕСТВУЕТ (EXISTS). A field type counts as composite when it has two
or more alternatives in yaml (`Строка|Число|?`), where `?` is only Неопределено being allowed,
not a separate type.

The parsing is deliberately conservative (the zero-false-positives invariant):

- a block with constructs outside the supported subset (temporary tables, unions, a subquery or
  anything but a plain name in the table position) is skipped as a whole;
- a dotted table whose root is not an object of the project is considered external (from a
  library) and skipped - only a KNOWN root with an unknown section is reported;
- a section after the dot found in the virtual table dictionary (СрезПоследних, Остатки, ...)
  is not questioned, and chains deeper than two segments are left alone;
- in `В` only a field whose type is known for sure is questioned: `Алиас.Поле` or
  `Таблица.Поле` where the alias is unambiguous within the block (one redefined in a subquery
  is skipped) and the field is found in the table's yaml.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Iterable, Iterator, Optional

from xbsl import dataset, i18n, libs
from xbsl.diagnostics import Diagnostic, Severity
from xbsl.engine import SourceFile, rule
from xbsl.lexer import Token, tokens
from xbsl.rules._syntax import (
    query_table_intro,
    query_words,
    WORD_KINDS,
    query_alias_pairs,
    query_block_tokens,
    query_ranges,
)
from xbsl.rules.yaml_schema import _HAVE_YAML, _parsed, object_kind, value_of

MESSAGES = {
    "query/unknown-table.title": {
        "ru": "Неизвестная таблица в запросе",
        "en": "Unknown table in a query",
    },
    "query/unknown-table.unknown": {
        "ru": "Неизвестная таблица запроса '{name}' – такого объекта нет в проекте.",
        "en": "Unknown query table '{name}' – no such object in the project.",
    },
    "query/unknown-table.tabular": {
        "ru": "Неизвестная таблица запроса '{name}' – у объекта '{root}' ({kind}) нет "
              "табличной части '{seg}'.",
        "en": "Unknown query table '{name}' – object '{root}' ({kind}) has no tabular "
              "section named '{seg}'.",
    },
    "query/in-subquery-composite.title": {
        "ru": "'В' с подзапросом по составному типу",
        "en": "'IN' with a subquery over a composite type",
    },
    "query/in-subquery-composite.in": {
        "ru": "'{expr}' составного типа ({types}): 'В' с подзапросом на большинстве СУБД "
              "реализовано неэффективно – использовать 'СУЩЕСТВУЕТ (ВЫБРАТЬ 1 ИЗ ... ГДЕ "
              "... = {expr})'.",
        "en": "'{expr}' is of a composite type ({types}): 'IN' with a subquery is implemented "
              "inefficiently on most DBMSs – use 'EXISTS (SELECT 1 FROM ... WHERE ... = {expr})'.",
    },
    "query/deletion-mark-immediate.title": {
        "ru": "ПометкаУдаления у объекта с немедленным удалением",
        "en": "DeletionMark on an object deleted immediately",
    },
    "query/deletion-mark-immediate.absent": {
        "ru": "'{prefix}.{field}' – у объекта '{table}' задано 'РежимУдаления: Немедленно', "
              "поэтому поля пометки удаления у него нет: запрос падает применением "
              "('Поле не найдено'). Условие с пометкой здесь лишнее.",
        "en": "'{prefix}.{field}' – object '{table}' declares '{n[РежимУдаления]}: {n[Немедленно]}', so it "
              "has no deletion-mark field: the query fails on apply ('Поле не найдено'). The "
              "condition on the mark is redundant here.",
    },
    "query/no-isnull.title": {
        "ru": "Функции нет в языке запросов",
        "en": "A function the query language does not have",
    },
    "query/no-isnull.absent": {
        "ru": "Функции {name} в языке запросов нет – компилятор отвергнет запрос. Разверните "
              "проверку в самом запросе: {n[ВЫБОР]} {n[КОГДА]} <поле> {n[ЕСТЬ]} NULL "
              "{n[ТОГДА]} <замена> {n[ИНАЧЕ]} <поле> {n[КОНЕЦ]}.",
        "en": "The query language has no {name} function – the compiler will reject the query. "
              "Spell the check out in the query itself: {n[ВЫБОР]} {n[КОГДА]} <field> "
              "{n[ЕСТЬ]} NULL {n[ТОГДА]} <replacement> {n[ИНАЧЕ]} <field> {n[КОНЕЦ]}.",
    },
    "query/named-parameter.title": {
        "ru": "Именованный параметр в литерале запроса",
        "en": "Named parameter in a query literal",
    },
    "query/named-parameter.amp": {
        "ru": "'&{name}' – в литералах запросов именованные параметры не поддерживаются: "
              "значение подставляется интерполяцией '%{name}' (или '%{{выражение}}').",
        "en": "'&{name}' – named parameters are not supported in query literals: the value is "
              "passed by interpolation, '%{name}' (or '%{{expression}}').",
    },
    "query/in-subquery-composite.not-in": {
        "ru": "'{expr}' составного типа ({types}): 'НЕ В' с подзапросом на большинстве СУБД "
              "реализовано неэффективно – использовать 'НЕ СУЩЕСТВУЕТ (ВЫБРАТЬ 1 ИЗ ... ГДЕ "
              "... = {expr})'.",
        "en": "'{expr}' is of a composite type ({types}): 'NOT IN' with a subquery is implemented "
              "inefficiently on most DBMSs – use 'NOT EXISTS (SELECT 1 FROM ... WHERE "
              "... = {expr})'.",
    },
}
i18n.register(MESSAGES)

# Words that introduce a table (the next word token starts a table expression) and the word
# token kinds - shared with the alias parsing in _syntax.
_TABLE_INTRO = query_table_intro()
_WORD_KINDS = WORD_KINDS
# Constructs outside the supported subset - a block with them is skipped as a whole.
_UNSUPPORTED = query_words("INTO", "UNION", "TEMPORARY")
# Virtual tables after the dot - not questioned.
_VIRTUAL = frozenset({
    "СРЕЗПОСЛЕДНИХ", "СРЕЗПЕРВЫХ", "ОСТАТКИ", "ОБОРОТЫ", "ОСТАТКИИОБОРОТЫ",
    "SLICELAST", "SLICEFIRST", "BALANCE", "TURNOVERS", "BALANCEANDTURNOVERS",
})
# Query language words - in both forms, as the lexer sees them (the token value, not the canon).
_IN = query_words("IN")
_NOT = query_words("NOT")
_SELECT = query_words("SELECT")
# Yaml sections that provide the fields of a query table.
_FIELD_SECTIONS = ("Реквизиты", "Измерения", "Ресурсы")


def _query_tables(source: SourceFile) -> Iterable[tuple]:
    """Table expressions of all query blocks of a file: (namespace tokens, segment tokens).

    A table may be addressed by its qualified name - `acme::Проект::Подсистема::Заказы` - so
    the `::` prefix is parsed away from the name: the namespace goes first, the dotted chain
    (the object and its tabular section) second. For an unqualified name the namespace is
    empty.

    A block where ИЗ/СОЕДИНЕНИЕ is followed by something other than a name (a subquery, an
    interpolation) or where an unsupported word occurs yields no expressions at all - silence
    instead of guessing.
    """
    toks = tokens(source)
    for start, end in query_ranges(source):
        block = [t for t in toks if start <= t.start < end and t.kind not in ("COMMENT", "BOM")]
        tables: list[list] = []
        supported = True
        i, n = 0, len(block)
        while i < n:
            t = block[i]
            if t.kind in _WORD_KINDS and t.value.upper() in _UNSUPPORTED:
                supported = False
                break
            if t.kind in _WORD_KINDS and t.value.upper() in _TABLE_INTRO:
                j = i + 1
                if j >= n or block[j].kind not in _WORD_KINDS:
                    supported = False  # a subquery/interpolation in the table position
                    break
                ns: list = []
                segs = [block[j]]
                j += 1
                while (
                    j + 1 < n
                    and block[j].kind == "OP" and block[j].value == "::"
                    and block[j + 1].kind in _WORD_KINDS
                ):
                    ns.append(segs.pop())  # everything before the last :: segment is the namespace
                    segs.append(block[j + 1])
                    j += 2
                while (
                    j + 1 < n
                    and block[j].kind == "OP" and block[j].value == "."
                    and block[j + 1].kind in _WORD_KINDS
                ):
                    segs.append(block[j + 1])
                    j += 2
                tables.append((ns, segs))
                i = j
                continue
            i += 1
        if supported:
            yield from tables


def _catalog_slice(source: SourceFile) -> tuple[str, dict] | None:
    """One yaml file's slice of the project object catalog: (name, {kind, tabular, fields}).

    Tabular sections come only from yaml (local module types are not database tables); the
    fields are attributes, dimensions and resources together with their type spec
    (`Строка|Число|?`). Cached on the file - both query rules share it.
    """
    if not _HAVE_YAML or source.kind != "yaml":
        return None
    key = "query_catalog_slice"
    if key in source.cache:
        return source.cache[key]
    result: tuple[str, dict] | None = None
    data, err = _parsed(source)
    if err is None and isinstance(data, dict) and object_kind(data):
        nm = value_of(data, "Имя")
        if isinstance(nm, str):
            tabular: list[str] = []
            parts = data.get("ТабличныеЧасти")
            if isinstance(parts, list):
                tabular = [
                    p["Имя"] for p in parts
                    if isinstance(p, dict) and isinstance(p.get("Имя"), str)
                ]
            fields: dict[str, str] = {}
            for section in _FIELD_SECTIONS:
                items = data.get(section)
                if not isinstance(items, list):
                    continue
                for it in items:
                    if isinstance(it, dict) and isinstance(it.get("Имя"), str) and isinstance(it.get("Тип"), str):
                        fields[it["Имя"]] = it["Тип"]
            result = (nm, {"kind": object_kind(data), "tabular": tabular, "fields": fields})
    source.cache[key] = result
    return result


def _alternatives(spec: str) -> list[str]:
    """Top-level type alternatives: `Строка|Число|?` -> ["Строка", "Число"].

    `?` is not a type but Неопределено being allowed (mandatory for a composite type, because
    such a type has no default value), so it does not count. Inside generics `|` does not
    split: `Массив<Строка|Число>` is one type, not a composite one.
    """
    parts: list[str] = []
    depth = 0
    current = ""
    for ch in spec:
        if ch == "<":
            depth += 1
        elif ch == ">":
            depth -= 1
        elif ch == "|" and depth == 0:
            parts.append(current)
            current = ""
            continue
        current += ch
    parts.append(current)
    return [p.strip() for p in parts if p.strip() and p.strip() != "?"]


def _block_aliases(block: list[Token]) -> dict[str, str]:
    """Alias -> table for a block; an alias redefined in a subquery is dropped.

    The same alias in a block and in its subquery may point to different tables - then the
    alias does not tell us the table, and we stay silent rather than pick one at random.
    """
    out: dict[str, str] = {}
    for alias, table in query_alias_pairs(block):
        if alias in out and out[alias] != table:
            out[alias] = ""  # conflict: the alias cannot be resolved
        else:
            out.setdefault(alias, table)
    return {a: t for a, t in out.items() if t}


def _in_subqueries(source: SourceFile) -> Iterator[tuple[Token, Token, bool, dict[str, str]]]:
    """`<Таблица|Алиас>.<Поле> [НЕ] В (ВЫБРАТЬ ...)` constructs: (prefix, field, negation, aliases).

    Only qualified fields are picked: for a bare name in a condition there is no reliable way
    to establish the table, and a value list in parentheses (`В (1, 2, &Коды)`) is outside the
    standard - it only speaks of a subquery.
    """
    for span in query_ranges(source):
        block = query_block_tokens(source, span)
        aliases = _block_aliases(block)
        n = len(block)
        for i, t in enumerate(block):
            if t.kind not in _WORD_KINDS or t.value.upper() not in _IN:
                continue
            if i + 2 >= n or not (block[i + 1].kind == "OP" and block[i + 1].value == "("):
                continue
            after = block[i + 2]
            if after.kind not in _WORD_KINDS or after.value.upper() not in _SELECT:
                continue  # a value list, not a subquery
            j = i - 1
            negated = j >= 0 and block[j].kind in _WORD_KINDS and block[j].value.upper() in _NOT
            if negated:
                j -= 1
            if j < 2:
                continue
            field, dot, prefix = block[j], block[j - 1], block[j - 2]
            if field.kind not in _WORD_KINDS or prefix.kind not in _WORD_KINDS:
                continue
            if not (dot.kind == "OP" and dot.value == "."):
                continue
            if j - 3 >= 0 and block[j - 3].kind == "OP" and block[j - 3].value == ".":
                continue  # a chain deeper than two segments - the type of the last field is unknown
            yield prefix, field, negated, aliases


@lru_cache(maxsize=1)
def _entity_tables() -> frozenset[str]:
    """Entity types of the platform, which are queryable tables just like a project object.

    They are recognized by their facets in the catalog (`Пользователи.Объект`,
    `ДвоичныйОбъект.Ссылка`): an entity is exactly the type that generates them. Their
    structure is the platform's, so only the name is checked here, not the sections.
    """
    try:
        catalog = dataset.load_json("stdlib.json")
    except dataset.DatasetError:
        return frozenset()
    return frozenset(
        key.split(".", 1)[0] for key in (catalog.get("facet_members") or {})
    )


def _query_table_mapper(source: SourceFile) -> dict | None:
    """The map phase: a yaml contributes its catalog slice (or, if it is the project
    descriptor, the project's own coordinates), a module its query table references with
    per-segment positions."""
    if source.kind == "yaml":
        got = _catalog_slice(source)
        if got:
            return {"k": "y", "slice": got}
        coords = libs.project_coordinates(source.text)
        return {"k": "p", "coords": list(coords)} if coords else None
    if source.kind != "xbsl":
        return None
    tables = [
        ([t.value for t in ns], [(t.value, t.line, t.col) for t in segs])
        for ns, segs in _query_tables(source)
    ]
    return {"k": "x", "tables": tables} if tables else None


@rule(
    "query/unknown-table", "query/unknown-table.title", "D",
    scope="project", severity=Severity.WARNING, mapper=_query_table_mapper,
)
def unknown_query_table(facts: dict[str, dict]) -> Iterable[Diagnostic]:
    catalog: dict[str, dict] = {}
    own: set[tuple[str, str]] = set()
    for fact in facts.values():
        if fact["k"] == "y":
            name, rec = fact["slice"]
            catalog[name] = rec
        elif fact["k"] == "p":
            own.add(tuple(fact["coords"]))
    if not catalog:
        return  # yaml not parsed (no PyYAML) or a project with no objects - stay silent
    for rel, fact in facts.items():
        for ns, segs in fact.get("tables", ()):
            # A qualified name is judged only when its namespace is this very project: the
            # objects of a library are not in the catalog, and calling them unknown would be
            # a lie rather than a finding.
            if ns and (len(ns) < 2 or (ns[0], ns[1]) not in own):
                continue
            root_value, root_line, root_col = segs[0]
            name = ".".join(v for v, _l, _c in segs)
            if root_value in _entity_tables():
                continue  # an entity of the platform, its structure is not the project's
            rec = catalog.get(root_value)
            if len(segs) == 1:
                if rec is None:
                    yield Diagnostic(
                        rel, root_line, root_col, "query/unknown-table",
                        Severity.WARNING,
                        i18n.t("query/unknown-table.unknown", name=name),
                    )
                continue
            if len(segs) != 2 or rec is None:
                continue  # deep chains and external roots - out of scope
            seg_value, seg_line, seg_col = segs[1]
            if seg_value in rec["tabular"] or seg_value.upper() in _VIRTUAL:
                continue
            yield Diagnostic(
                rel, seg_line, seg_col, "query/unknown-table",
                Severity.WARNING,
                i18n.t(
                    "query/unknown-table.tabular",
                    name=name, root=root_value, kind=rec["kind"], seg=seg_value,
                ),
            )


def _in_subquery_mapper(source: SourceFile) -> dict | None:
    """The map phase: a yaml contributes its catalog slice, a module its `В (ВЫБРАТЬ ...)`
    conditions (prefix, field, negation, aliases, position)."""
    if source.kind == "yaml":
        got = _catalog_slice(source)
        return {"k": "y", "slice": got} if got else None
    if source.kind != "xbsl":
        return None
    ins = [
        (prefix.value, field.value, negated, dict(aliases), prefix.line, prefix.col)
        for prefix, field, negated, aliases in _in_subqueries(source)
    ]
    return {"k": "x", "ins": ins} if ins else None


@rule(
    "query/in-subquery-composite", "query/in-subquery-composite.title", "D",
    scope="project", severity=Severity.WARNING, mapper=_in_subquery_mapper,
)
def in_subquery_composite(facts: dict[str, dict]) -> Iterable[Diagnostic]:
    """A composite-type field in `В (ВЫБРАТЬ ...)` - the condition is rewritten via СУЩЕСТВУЕТ."""
    catalog: dict[str, dict] = {}
    for fact in facts.values():
        if fact["k"] == "y":
            name, rec = fact["slice"]
            catalog[name] = rec
    if not catalog:
        return  # yaml not parsed (no PyYAML) or a project with no objects - stay silent
    for rel, fact in facts.items():
        for prefix, field, negated, aliases, line, col in fact.get("ins", ()):
            table = aliases.get(prefix)
            if table is None and prefix in catalog:
                table = prefix  # the table is referenced by its own name, without an alias
            rec = catalog.get(table) if table else None
            if rec is None:
                continue
            alternatives = _alternatives(rec["fields"].get(field, ""))
            if len(alternatives) < 2:
                continue  # a plain or nullable type - the standard says nothing about it
            key = ".not-in" if negated else ".in"
            yield Diagnostic(
                rel, line, col, "query/in-subquery-composite",
                Severity.WARNING,
                i18n.t(
                    "query/in-subquery-composite" + key,
                    expr=f"{prefix}.{field}",
                    types="|".join(alternatives),
                ),
            )


# The deletion-mark field, either spelling (the platform reads a project written in English
# the same way); the modes come from the metamodel enumeration DeletionMode.
_DELETION_MARK = frozenset({"ПометкаУдаления", "DeletionMark"})
_IMMEDIATE = frozenset({"Немедленно", "Immediately"})


def _deletion_mark_mapper(source: SourceFile) -> dict | None:
    """The map phase: a yaml of a deletable kind contributes its deletion mode, a module the
    `<Алиас|Таблица>.ПометкаУдаления` accesses of its query blocks."""
    if source.kind == "yaml":
        if not _HAVE_YAML:
            return None
        data, err = _parsed(source)
        if err is not None or not isinstance(data, dict):
            return None
        kind = object_kind(data)
        name = value_of(data, "Имя")
        if kind not in ("Справочник", "Документ", "ПланОбмена") or not isinstance(name, str):
            return None
        mode = value_of(data, "РежимУдаления")
        # The metamodel default is ПометкаУдаления - only an explicit Немедленно drops the field.
        return {"k": "y", "name": name, "immediate": isinstance(mode, str) and mode in _IMMEDIATE}
    if source.kind != "xbsl":
        return None
    hits: list[tuple[str, str, int, int]] = []
    for span in query_ranges(source):
        block = query_block_tokens(source, span)
        aliases = _block_aliases(block)
        for i in range(2, len(block)):
            field, dot, prefix = block[i], block[i - 1], block[i - 2]
            if field.kind not in _WORD_KINDS or field.value not in _DELETION_MARK:
                continue
            if not (dot.kind == "OP" and dot.value == "." and prefix.kind in _WORD_KINDS):
                continue
            if i - 3 >= 0 and block[i - 3].kind == "OP" and block[i - 3].value == ".":
                continue  # `А.Владелец.ПометкаУдаления` - the mark belongs to another object
            table = aliases.get(prefix.value, prefix.value)
            hits.append((prefix.value, table, field.line, field.col))
    return {"k": "x", "hits": hits} if hits else None


@rule(
    "query/deletion-mark-immediate", "query/deletion-mark-immediate.title", "D",
    scope="project", severity=Severity.ERROR, mapper=_deletion_mark_mapper,
)
def deletion_mark_immediate(facts: dict[str, dict]) -> Iterable[Diagnostic]:
    """A deletion-mark condition on an object whose РежимУдаления is Немедленно.

    Such an object has no mark at all - the query fails on apply with `Поле не найдено`,
    which costs a deploy cycle. The mode is declared in the object's own yaml, so the check
    is purely static; the table comes from the block alias (`ИЗ Склады КАК С`), and an
    alias the block redefines resolves to nothing and is skipped.
    """
    immediate = {
        fact["name"] for fact in facts.values()
        if fact["k"] == "y" and fact["immediate"]
    }
    if not immediate:
        return
    for rel, fact in facts.items():
        if fact["k"] != "x":
            continue
        for prefix, table, line, col in fact["hits"]:
            if table not in immediate:
                continue
            yield Diagnostic(
                rel, line, col, "query/deletion-mark-immediate", Severity.ERROR,
                i18n.t(
                    "query/deletion-mark-immediate.absent",
                    prefix=prefix, field="ПометкаУдаления", table=table,
                ),
            )


@rule("query/named-parameter", "query/named-parameter.title", "C", severity=Severity.ERROR)
def query_named_parameter(source: SourceFile) -> Iterable[Diagnostic]:
    """`&Имя` inside `Запрос{ ... }` - the literal takes its values by interpolation.

    "Параметры в литерал запроса передаются с помощью символа %: либо %имя-переменной, либо
    %{выражение}" (topics/query-literal). The `&Имя` of the query language belongs to a
    ПроизвольныйЗапрос with `.Установить("Имя", ...)`; inside a literal the compiler refuses
    the whole module ("В литералах запросов не поддерживаются именованные параметры"), so the
    cost of missing it is a deploy cycle.

    Only `&` glued to a name is reported - a lone `&` is some other construct, and guessing
    is not this rule's job.
    """
    if source.kind != "xbsl" or "&" not in source.text:
        return
    for span in query_ranges(source):
        block = query_block_tokens(source, span)
        for amp, name in zip(block, block[1:]):
            if (
                amp.kind == "OP" and amp.value == "&"
                and name.kind in _WORD_KINDS and name.start == amp.end
            ):
                yield Diagnostic(
                    source.rel, amp.line, amp.col, "query/named-parameter", Severity.ERROR,
                    i18n.t("query/named-parameter.amp", name=name.value),
                )


# The names of the absent function, in both spellings the query language could be written in.
_ISNULL_NAMES = frozenset({"ЕСТЬNULL", "ISNULL"})


@rule("query/no-isnull", "query/no-isnull.title", "C", severity=Severity.ERROR)
def query_no_isnull(source: SourceFile) -> Iterable[Diagnostic]:
    """`ЕСТЬNULL(...)` inside `Запрос{ ... }` - the function does not exist in the language.

    Dereferencing a nullable reference in a query yields `Null` (not `Неопределено`), and the
    habit brought over from other query languages is to wrap it into ЕСТЬNULL. There is no such
    function here: the check is spelled out with `ВЫБОР КОГДА ... ЕСТЬ NULL ТОГДА ... КОНЕЦ`,
    and the `??` operator does not help either - it does not handle `Null`.

    Only the name glued to an opening parenthesis is reported, so a field or an alias that
    happens to carry the word is left alone.
    """
    if source.kind != "xbsl":
        return
    lowered = source.text.lower()
    if not any(name.lower() in lowered for name in _ISNULL_NAMES):
        return
    for span in query_ranges(source):
        block = query_block_tokens(source, span)
        for name, paren in zip(block, block[1:]):
            if (
                name.kind in _WORD_KINDS and name.value.upper() in _ISNULL_NAMES
                and paren.kind == "OP" and paren.value == "("
            ):
                yield Diagnostic(
                    source.rel, name.line, name.col, "query/no-isnull", Severity.ERROR,
                    i18n.t("query/no-isnull.absent", name=name.value),
                )
