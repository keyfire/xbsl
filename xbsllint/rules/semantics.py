"""Тир D: семантические проверки по каталогу stdlib.

Правило code/unknown-type: база типа, на которую ссылается код, должна быть известна –
это либо символ stdlib (xbsllint/data/stdlib.json, генерит tools/extract_stdlib.py), либо
объект проекта (Имя из yaml с ВидЭлемента), либо локально объявленный тип (структура/
перечисление/исключение). Проверяются все типовые позиции модуля:

- `новый <Тип>` – создание;
- `<выражение> как <Тип>` – приведение;
- аннотация объявления/поля/перехвата `знч/пер/поймать <имя>: <Тип>` (в т.ч. список имён
  через запятую с общим типом – `знч a, b: <Тип>`);
- сигнатура метода – типы параметров `(<имя>: <Тип>, ...)` и тип возврата `): <Тип>`.

Типовое выражение разбирается по корню: у FQN (`КэшДанныхСервиса.СтрокаКопии`) проверяется
только первый сегмент (вложенные типы каталогом не описаны – их не трогаем, чтобы не давать
ложных); nullable-суффикс `?` игнорируется; у дженерика (`Массив<ОрганизацияJSON>`)
проверяются и база, и каждый аргумент. Корни-пространства имён (Справочник/Документ/...)
присутствуют в каталоге, поэтому FQN вида `Справочник.Товары.Ссылка` резолвится по корню.

Правило проектное (кросс-файловое): корректно только зная весь проект (объекты и локальные
типы всех модулей), поэтому в режиме одиночного файла (lint_source) не выполняется – это
исключает ложные срабатывания. Выверено на корпусе сайта: 0 ложных.
"""

from __future__ import annotations

from collections.abc import Iterable
from functools import lru_cache

from xbsllint import dataset
from xbsllint.diagnostics import Diagnostic, Severity
from xbsllint.engine import SourceFile, rule
from xbsllint.lexer import tokens
from xbsllint.rules.yaml_schema import _HAVE_YAML, _parsed

_LOCAL_TYPE_KW = ("STRUCTURE", "ENUMERATION", "EXCEPTION")


@lru_cache(maxsize=1)
def _stdlib_names() -> frozenset[str]:
    try:
        return frozenset(dataset.load_json("stdlib.json")["names"])
    except (dataset.DatasetError, KeyError, ValueError):
        return frozenset()


def _project_object_names(sources: list[SourceFile]) -> set[str]:
    names: set[str] = set()
    if not _HAVE_YAML:
        return names
    for s in sources:
        if s.kind != "yaml":
            continue
        data, err = _parsed(s)
        if err is None and isinstance(data, dict) and data.get("ВидЭлемента"):
            nm = data.get("Имя")
            if isinstance(nm, str):
                names.add(nm)
    return names


def _local_type_names(sources: list[SourceFile]) -> set[str]:
    names: set[str] = set()
    for s in sources:
        if s.kind != "xbsl":
            continue
        toks = tokens(s)
        for i, t in enumerate(toks):
            if t.kind == "KEYWORD" and t.value[:1].islower() and t.canonical in _LOCAL_TYPE_KW:
                for j in range(i + 1, min(i + 3, len(toks))):
                    if toks[j].kind == "IDENT":
                        names.add(toks[j].value)
                        break
    return names


# --- Разбор типовых выражений по токенам ---------------------------------------------

def _next(toks: list, k: int) -> int:
    """Индекс ближайшего не-комментария начиная с k (может вернуть len при исчерпании)."""
    n = len(toks)
    while k < n and toks[k].kind == "COMMENT":
        k += 1
    return k


def _type_roots(toks: list, start: int) -> tuple[list, int]:
    """Корневые имена-типы типового выражения с позиции start и индекс за его концом.

    Корень – IDENT в начале выражения, база дженерика и начало каждого аргумента (после
    `<` или `,`). Хвост FQN (после `.`) корнем не считается. Если выражение не начинается
    с IDENT (напр. ключевое слово `неизвестно` или скобка) – корней нет.
    """
    roots: list = []
    depth = 0
    prev: str | None = None  # None | '<' | ',' | '.' | 'ident'
    i, n = start, len(toks)
    while i < n:
        t = toks[i]
        if t.kind == "COMMENT":
            i += 1
            continue
        if t.kind == "IDENT":
            if prev in (None, "<", ","):
                roots.append(t)
            prev = "ident"
            i += 1
            continue
        if t.kind == "OP":
            v = t.value
            if v == ".":
                prev = "."
                i += 1
                continue
            if v == "<":
                depth += 1
                prev = "<"
                i += 1
                continue
            if v == ">":
                if depth == 0:
                    break
                depth -= 1
                prev = "ident"
                i += 1
                continue
            if v == ",":
                if depth == 0:
                    break
                prev = ","
                i += 1
                continue
            if v == "?":  # nullable-суффикс – не влияет на разбор
                prev = "ident"
                i += 1
                continue
        break
    return roots, i


def _annotation_start(toks: list, j: int) -> int | None:
    """С позиции первого имени в объявлении/перехвате вернуть старт типа после `:`.

    Поддерживает список имён через запятую с общим типом (`знч a, b: Тип`) и одиночную
    форму (`пер x: Тип`, `поймать Ошибка: Тип`). Если аннотации типа нет – None.
    """
    n = len(toks)
    while j < n and toks[j].kind == "IDENT":
        k = _next(toks, j + 1)
        if k < n and toks[k].kind == "OP" and toks[k].value == ",":
            j = _next(toks, k + 1)
            continue
        if k < n and toks[k].kind == "OP" and toks[k].value == ":":
            return _next(toks, k + 1)
        return None
    return None


def _signature_type_starts(toks: list, i: int) -> list[int]:
    """Старты типовых выражений в сигнатуре метода/конструктора с индекса ключевого слова:
    типы параметров и тип возврата. Список параметров балансируется по круглым скобкам;
    внутри типов параметров дженерики (`<...>`) проглатывает _type_roots, так что запятая
    внутри `Соответствие<Строка, Число>` не путается с разделителем параметров."""
    n = len(toks)
    j = _next(toks, i + 1)  # имя метода
    if j >= n or toks[j].kind != "IDENT":
        return []
    p = _next(toks, j + 1)  # ожидается '('
    if p >= n or not (toks[p].kind == "OP" and toks[p].value == "("):
        return []

    starts: list[int] = []
    depth = 1
    expect_name = True  # начало параметра (после '(' или ',' на верхнем уровне)
    k = p + 1
    while k < n and depth > 0:
        t = toks[k]
        if t.kind == "COMMENT":
            k += 1
            continue
        if t.kind == "OP" and t.value in "([{":
            depth += 1
            expect_name = False
            k += 1
            continue
        if t.kind == "OP" and t.value in ")]}":
            depth -= 1
            k += 1
            continue
        if depth == 1 and expect_name and t.kind == "IDENT":
            c = _next(toks, k + 1)
            if c < n and toks[c].kind == "OP" and toks[c].value == ":":
                s = _next(toks, c + 1)
                starts.append(s)
                _, end = _type_roots(toks, s)
                k = end
                expect_name = False
                continue
            k += 1
            continue
        if depth == 1 and t.kind == "OP" and t.value == ",":
            expect_name = True
            k += 1
            continue
        k += 1

    # тип возврата: сразу после закрывающей ')' списка параметров
    r = _next(toks, k)
    if r < n and toks[r].kind == "OP" and toks[r].value == ":":
        starts.append(_next(toks, r + 1))
    return starts


def _type_ref_starts(toks: list) -> list[int]:
    """Индексы стартов всех типовых выражений модуля (по якорным конструкциям)."""
    starts: list[int] = []
    n = len(toks)
    for i, t in enumerate(toks):
        if t.kind != "KEYWORD" or not t.value[:1].islower():
            continue
        c = t.canonical
        if c in ("NEW", "AS"):
            starts.append(_next(toks, i + 1))
        elif c in ("VAL", "VAR", "CATCH"):
            s = _annotation_start(toks, _next(toks, i + 1))
            if s is not None:
                starts.append(s)
        elif c in ("METHOD", "CONSTRUCTOR"):
            starts.extend(_signature_type_starts(toks, i))
    return starts


@rule(
    "code/unknown-type", "Неизвестный тип", "D",
    scope="project", severity=Severity.WARNING,
)
def unknown_type(sources: list[SourceFile]) -> Iterable[Diagnostic]:
    stdlib = _stdlib_names()
    if not stdlib:
        return []  # каталог не сгенерирован – проверку не выполняем
    known = set(stdlib) | _project_object_names(sources) | _local_type_names(sources)

    diags: list[Diagnostic] = []
    for s in sources:
        if s.kind != "xbsl":
            continue
        toks = tokens(s)
        for start in _type_ref_starts(toks):
            roots, _ = _type_roots(toks, start)
            for r in roots:
                if r.value not in known:
                    diags.append(Diagnostic(
                        s.rel, r.line, r.col, "code/unknown-type",
                        Severity.WARNING,
                        f"Неизвестный тип '{r.value}' – нет ни в stdlib, "
                        "ни среди объектов проекта или локальных типов.",
                    ))
    return diags
