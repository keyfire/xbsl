"""Checks of the query DSL (`Запрос{ ... }` blocks).

query/unknown-table – a table referenced in ИЗ/СОЕДИНЕНИЕ (FROM/JOIN) must be a project
object, and `<Объект>.<Секция>` must name a tabular section of that object. These are the
errors that otherwise surface only in the database at run time.

The parsing is deliberately conservative (the zero-false-positives invariant):

- a block that uses constructs outside the supported subset (temporary tables, unions,
  a subquery or anything but a plain name in the table position) is skipped whole;
- a dotted table whose root is not a project object is treated as external (a library)
  and skipped - only a KNOWN root with an unknown section is reported;
- a dotted section from the virtual-table vocabulary (СрезПоследних, Остатки, ...) is
  never questioned, and chains deeper than two segments are left alone.
"""

from __future__ import annotations

from typing import Iterable, Optional

from xbsllint import i18n
from xbsllint.diagnostics import Diagnostic, Severity
from xbsllint.engine import SourceFile, rule
from xbsllint.lexer import tokens
from xbsllint.rules._syntax import QUERY_TABLE_INTRO, WORD_KINDS, query_ranges
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


def _query_tables(source: SourceFile) -> Iterable[tuple]:
    """Табличные выражения всех блоков запроса файла: (сегменты-токены,) по одному на таблицу.

    Блок, где после ИЗ/СОЕДИНЕНИЕ стоит не имя (подзапрос, интерполяция) или встречается
    неподдержанное слово, не даёт ни одного выражения - молчание вместо догадок.
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
    """Объекты проекта: имя -> {kind, tabular}. Только табличные части из yaml -
    локальные типы модулей таблицами базы не являются."""
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
        info[nm] = {"kind": data["ВидЭлемента"], "tabular": tabular}
    return info


@rule(
    "query/unknown-table", "query/unknown-table.title", "D",
    scope="project", severity=Severity.WARNING,
)
def unknown_query_table(sources: list[SourceFile]) -> Iterable[Diagnostic]:
    catalog = _tabular_catalog(sources)
    if not catalog:
        return []  # yaml не разобран (нет PyYAML) или проект без объектов - молчим

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
                continue  # глубокие цепочки и внешние корни - вне охвата
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
