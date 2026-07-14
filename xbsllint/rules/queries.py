"""Проверки DSL запросов (блоки `Запрос{ ... }`).

query/unknown-table – таблица, на которую ссылается ИЗ/СОЕДИНЕНИЕ (FROM/JOIN), должна быть
объектом проекта, а `<Объект>.<Секция>` – называть табличную часть этого объекта. Такие
ошибки иначе проявляются только в базе во время выполнения.

query/in-subquery-composite – стандарт платформы "Использование выражения В с подзапросом для
выражений составного типа": на большинстве СУБД такой вариант реализован неэффективно, условие
пишется через СУЩЕСТВУЕТ (EXISTS). Составным считается тип поля с двумя и более альтернативами
в yaml (`Строка|Число|?`), где `?` – лишь допустимость Неопределено, а не отдельный тип.

Разбор намеренно консервативен (инвариант нулевых ложных срабатываний):

- блок с конструкциями вне поддержанного подмножества (временные таблицы, объединения,
  подзапрос или что угодно, кроме простого имени в позиции таблицы) пропускается целиком;
- таблица с точкой, корень которой не является объектом проекта, считается внешней
  (библиотечной) и пропускается – сообщается только об ИЗВЕСТНОМ корне с неизвестной секцией;
- секция после точки из словаря виртуальных таблиц (СрезПоследних, Остатки, ...) под сомнение
  не ставится, а цепочки глубже двух сегментов не трогаются;
- в `В` под сомнение ставится только поле, тип которого известен наверняка: `Алиас.Поле` или
  `Таблица.Поле`, где алиас однозначен в пределах блока (переопределённый в подзапросе –
  пропускается), а поле найдено в yaml таблицы.
"""

from __future__ import annotations

from typing import Iterable, Iterator, Optional

from xbsllint import i18n
from xbsllint.diagnostics import Diagnostic, Severity
from xbsllint.engine import SourceFile, rule
from xbsllint.lexer import Token, tokens
from xbsllint.rules._syntax import (
    QUERY_TABLE_INTRO,
    WORD_KINDS,
    query_alias_pairs,
    query_block_tokens,
    query_ranges,
)
from xbsllint.rules.yaml_schema import _HAVE_YAML, _parsed

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

# Слова, вводящие таблицу (следующий словарный токен начинает табличное выражение), и виды
# словарных токенов – общие с разбором алиасов в _syntax.
_TABLE_INTRO = QUERY_TABLE_INTRO
_WORD_KINDS = WORD_KINDS
# Конструкции вне поддержанного подмножества – блок с ними пропускается целиком.
_UNSUPPORTED = frozenset({"ПОМЕСТИТЬ", "INTO", "ОБЪЕДИНИТЬ", "UNION", "ВРЕМЕННАЯ", "TEMPORARY"})
# Виртуальные таблицы после точки – не подвергаются сомнению.
_VIRTUAL = frozenset({
    "СРЕЗПОСЛЕДНИХ", "СРЕЗПЕРВЫХ", "ОСТАТКИ", "ОБОРОТЫ", "ОСТАТКИИОБОРОТЫ",
    "SLICELAST", "SLICEFIRST", "BALANCE", "TURNOVERS", "BALANCEANDTURNOVERS",
})
# Слова языка запросов – в обеих формах, как их видит лексер (значение токена, не канон).
_IN = frozenset({"В", "IN"})
_NOT = frozenset({"НЕ", "NOT"})
_SELECT = frozenset({"ВЫБРАТЬ", "SELECT"})
# Секции yaml, дающие поля таблицы запроса.
_FIELD_SECTIONS = ("Реквизиты", "Измерения", "Ресурсы")


def _query_tables(source: SourceFile) -> Iterable[tuple]:
    """Табличные выражения всех блоков запроса файла: (сегменты-токены,) по одному на таблицу.

    Блок, где после ИЗ/СОЕДИНЕНИЕ стоит не имя (подзапрос, интерполяция) или встречается
    неподдержанное слово, не даёт ни одного выражения – молчание вместо догадок.
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
                    supported = False  # подзапрос/интерполяция в позиции таблицы
                    break
                segs = [block[j]]
                j += 1
                while (
                    j + 1 < n
                    and block[j].kind == "OP" and block[j].value == "."
                    and block[j + 1].kind in _WORD_KINDS
                ):
                    segs.append(block[j + 1])
                    j += 2
                tables.append(segs)
                i = j
                continue
            i += 1
        if supported:
            yield from tables


def _tabular_catalog(sources: list[SourceFile]) -> dict[str, dict]:
    """Объекты проекта: имя -> {kind, tabular, fields}.

    Табличные части – только из yaml (локальные типы модулей таблицами базы не являются), поля –
    реквизиты, измерения и ресурсы вместе с записью их типа (`Строка|Число|?`).
    """
    info: dict[str, dict] = {}
    if not _HAVE_YAML:
        return info
    for s in sources:
        if s.kind != "yaml":
            continue
        data, err = _parsed(s)
        if err is not None or not isinstance(data, dict) or not data.get("ВидЭлемента"):
            continue
        nm = data.get("Имя")
        if not isinstance(nm, str):
            continue
        tabular: set[str] = set()
        parts = data.get("ТабличныеЧасти")
        if isinstance(parts, list):
            for p in parts:
                if isinstance(p, dict) and isinstance(p.get("Имя"), str):
                    tabular.add(p["Имя"])
        fields: dict[str, str] = {}
        for section in _FIELD_SECTIONS:
            items = data.get(section)
            if not isinstance(items, list):
                continue
            for it in items:
                if isinstance(it, dict) and isinstance(it.get("Имя"), str) and isinstance(it.get("Тип"), str):
                    fields[it["Имя"]] = it["Тип"]
        info[nm] = {"kind": data["ВидЭлемента"], "tabular": tabular, "fields": fields}
    return info


def _alternatives(spec: str) -> list[str]:
    """Альтернативы типа верхнего уровня: `Строка|Число|?` -> ["Строка", "Число"].

    `?` – не тип, а допустимость Неопределено (у составного типа он обязателен, потому что
    значения по умолчанию у такого типа нет), поэтому в счёт не идёт. Внутри обобщений `|` не
    делит: `Массив<Строка|Число>` – один тип, а не составной.
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
    """Алиас -> таблица для блока; переопределённый в подзапросе алиас выбрасывается.

    Один и тот же алиас в блоке и в его подзапросе может указывать на разные таблицы – тогда по
    алиасу мы таблицу не знаем и молчим, а не выбираем наугад.
    """
    out: dict[str, str] = {}
    for alias, table in query_alias_pairs(block):
        if alias in out and out[alias] != table:
            out[alias] = ""  # конфликт: алиас неразрешим
        else:
            out.setdefault(alias, table)
    return {a: t for a, t in out.items() if t}


def _in_subqueries(source: SourceFile) -> Iterator[tuple[Token, Token, bool, dict[str, str]]]:
    """Конструкции `<Таблица|Алиас>.<Поле> [НЕ] В (ВЫБРАТЬ ...)`: (префикс, поле, отрицание, алиасы).

    Отбираются только квалифицированные поля: у голого имени в условии нет способа надёжно
    установить таблицу, а список значений в скобках (`В (1, 2, &Коды)`) стандарта не касается –
    речь только о подзапросе.
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
                continue  # список значений, а не подзапрос
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
                continue  # цепочка глубже двух сегментов – тип последнего поля нам неизвестен
            yield prefix, field, negated, aliases


@rule(
    "query/unknown-table", "query/unknown-table.title", "D",
    scope="project", severity=Severity.WARNING,
)
def unknown_query_table(sources: list[SourceFile]) -> Iterable[Diagnostic]:
    catalog = _tabular_catalog(sources)
    if not catalog:
        return []  # yaml не разобран (нет PyYAML) или проект без объектов – молчим

    diags: list[Diagnostic] = []
    for s in sources:
        if s.kind != "xbsl":
            continue
        for segs in _query_tables(s):
            root = segs[0]
            name = ".".join(t.value for t in segs)
            rec = catalog.get(root.value)
            if len(segs) == 1:
                if rec is None:
                    diags.append(Diagnostic(
                        s.rel, root.line, root.col, "query/unknown-table",
                        Severity.WARNING,
                        i18n.t("query/unknown-table.unknown", name=name),
                    ))
                continue
            if len(segs) != 2 or rec is None:
                continue  # глубокие цепочки и внешние корни – вне охвата
            seg = segs[1]
            if seg.value in rec["tabular"] or seg.value.upper() in _VIRTUAL:
                continue
            diags.append(Diagnostic(
                s.rel, seg.line, seg.col, "query/unknown-table",
                Severity.WARNING,
                i18n.t(
                    "query/unknown-table.tabular",
                    name=name, root=root.value, kind=rec["kind"], seg=seg.value,
                ),
            ))
    return diags


@rule(
    "query/in-subquery-composite", "query/in-subquery-composite.title", "D",
    scope="project", severity=Severity.WARNING,
)
def in_subquery_composite(sources: list[SourceFile]) -> Iterable[Diagnostic]:
    """Поле составного типа в `В (ВЫБРАТЬ ...)` – условие переписывается через СУЩЕСТВУЕТ."""
    catalog = _tabular_catalog(sources)
    if not catalog:
        return []  # yaml не разобран (нет PyYAML) или проект без объектов – молчим

    diags: list[Diagnostic] = []
    for s in sources:
        if s.kind != "xbsl":
            continue
        for prefix, field, negated, aliases in _in_subqueries(s):
            table = aliases.get(prefix.value)
            if table is None and prefix.value in catalog:
                table = prefix.value  # таблица названа своим именем, без алиаса
            rec = catalog.get(table) if table else None
            if rec is None:
                continue
            alternatives = _alternatives(rec["fields"].get(field.value, ""))
            if len(alternatives) < 2:
                continue  # простой или nullable тип – стандарт про него ничего не говорит
            key = ".not-in" if negated else ".in"
            diags.append(Diagnostic(
                s.rel, prefix.line, prefix.col, "query/in-subquery-composite",
                Severity.WARNING,
                i18n.t(
                    "query/in-subquery-composite" + key,
                    expr=f"{prefix.value}.{field.value}",
                    types="|".join(alternatives),
                ),
            ))
    return diags
