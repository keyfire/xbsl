"""Pure navigation core for the LSP server: a Python port of the extension's navCore.

Operates on the project index built by `xbsllint.indexer` (the same frozen schema the
`--index` CLI dumps): definition, completion and hover resolution plus the dotted-chain
line parsing. No LSP or editor imports here - the module is unit-tested directly and the
pygls server (`xbsllint.lsp`) is a thin transport over it.
"""

from __future__ import annotations

import re
from typing import Any, Optional

IDENT = r"[A-Za-zА-Яа-яЁё_][A-Za-z0-9А-Яа-яЁё_]*"
# A character that may not directly precede an identifier chain we recognize.
NOT_BEFORE = r"[^.0-9A-Za-zА-Яа-яЁё_]"

_CHAIN_RE = re.compile(rf"{IDENT}(?:\.{IDENT})*")
_HANDLER_RE = re.compile(rf"^(\s*Обработчик\s*:\s*)({IDENT})\s*$")


class IndexLookup:
    """Precomputed lookups over the index dict produced by indexer.build_index."""

    def __init__(self, index: dict) -> None:
        self.index = index
        self._objects: dict[str, dict] = {}
        for o in index.get("objects", []) or []:
            self._objects.setdefault(o.get("name", ""), o)
        self._module_methods: dict[str, list[dict]] = {}
        self._file_methods: dict[str, list[dict]] = {}
        for m in index.get("methods", []) or []:
            self._module_methods.setdefault(m.get("module", ""), []).append(m)
            self._file_methods.setdefault(m.get("path", ""), []).append(m)
        self._form_components: dict[str, list[dict]] = {}
        for c in index.get("components", []) or []:
            self._form_components.setdefault(c.get("form", ""), []).append(c)

    def objects(self) -> list[dict]:
        return list(self.index.get("objects", []) or [])

    def object_by_name(self, name: str) -> Optional[dict]:
        return self._objects.get(name)

    def methods_by_module(self, module: str) -> list[dict]:
        return self._module_methods.get(module, [])

    def method(self, module: str, name: str) -> Optional[dict]:
        for m in self.methods_by_module(module):
            if m.get("name") == name:
                return m
        return None

    def method_in_file(self, path: str, name: str) -> Optional[dict]:
        for m in self._file_methods.get(path, []):
            if m.get("name") == name:
                return m
        return None

    def components_by_form(self, form: str) -> list[dict]:
        return self._form_components.get(form, [])

    def component(self, form: str, name: str) -> Optional[dict]:
        for c in self.components_by_form(form):
            if c.get("name") == name:
                return c
        return None


def chain_at(line_text: str, character: int) -> Optional[tuple[list[str], int]]:
    """The dotted identifier chain covering `character` (0-based) and the segment index."""
    for m in _CHAIN_RE.finditer(line_text):
        start, end = m.start(), m.end()
        if character < start:
            break
        if character > end:
            continue
        parts = m.group(0).split(".")
        offset = start
        for i, part in enumerate(parts):
            segment_end = offset + len(part)
            if character <= segment_end:
                return parts, i
            offset = segment_end + 1  # skip the dot
        return parts, len(parts) - 1
    return None


def _paired_module_path(file_path: Optional[str]) -> Optional[str]:
    if not file_path or not file_path.lower().endswith(".yaml"):
        return None
    return file_path[: -len(".yaml")] + ".xbsl"


def resolve_definition(
    lookup: IndexLookup,
    *,
    language_id: str,
    line_text: str,
    character: int,
    file_stem: str,
    file_path: Optional[str] = None,
) -> Optional[tuple[str, int]]:
    """The (path, line) target for the position, or None when the context is not recognized."""
    if language_id == "yaml":
        handler = _HANDLER_RE.match(line_text)
        if handler:
            start = len(handler.group(1))
            end = start + len(handler.group(2))
            if character < start or character > end:
                return None
            name = handler.group(2)
            paired = _paired_module_path(file_path)
            method = (lookup.method_in_file(paired, name) if paired else None) or lookup.method(file_stem, name)
            return (method["path"], method["line"]) if method else None

    hit = chain_at(line_text, character)
    if not hit:
        return None
    parts, at = hit
    word = parts[at]

    if at == 0:
        obj = lookup.object_by_name(word)
        if obj:
            return obj["path"], obj["line"]
        if len(parts) == 1 and language_id == "xbsl":
            method = (lookup.method_in_file(file_path, word) if file_path else None) or lookup.method(file_stem, word)
            if method:
                return method["path"], method["line"]
        return None

    if at == 1 and parts[0] == "Компоненты":
        component = lookup.component(file_stem, word)
        return (component["path"], component["line"]) if component else None
    if at == 2 and parts[0] == "Компоненты":
        method = lookup.method(parts[1], word)
        return (method["path"], method["line"]) if method else None
    if at != 1:
        return None  # deeper chains need type inference - out of scope

    qualifier = parts[at - 1]
    obj = lookup.object_by_name(qualifier)
    if obj:
        for t in obj.get("local_types", []):
            if t.get("name") == word:
                return t["path"], t["line"]
        for t in obj.get("tabular", []):
            if t.get("name") == word:
                return obj["path"], t["line"]
        for v in obj.get("values", []):
            if v.get("name") == word:
                return obj["path"], v["line"]
    method = lookup.method(qualifier, word)
    return (method["path"], method["line"]) if method else None


def _method_entry(m: dict) -> dict:
    annotations = m.get("annotations") or []
    return {
        "label": m.get("name", ""),
        "kind": "method",
        "detail": ", ".join(annotations) if annotations else "метод",
    }


def _object_member_entries(lookup: IndexLookup, name: str) -> Optional[list[dict]]:
    obj = lookup.object_by_name(name)
    methods = lookup.methods_by_module(name)
    if not obj and not methods:
        return None
    entries: list[dict] = []
    if obj:
        if obj.get("kind") == "Перечисление":
            for v in obj.get("values", []):
                entries.append({"label": v.get("name", ""), "kind": "enumMember", "detail": "значение перечисления"})
        else:
            for f in obj.get("family", []):
                entries.append({"label": str(f), "kind": "family", "detail": "тип"})
            for t in obj.get("tabular", []):
                entries.append({"label": t.get("name", ""), "kind": "tabular", "detail": "табличная часть"})
            for t in obj.get("local_types", []):
                entries.append({"label": t.get("name", ""), "kind": "localType", "detail": "локальный тип"})
    for m in methods:
        entries.append(_method_entry(m))
    return entries


def _match_end(prefix: str, pattern: str) -> Optional[re.Match]:
    return re.search(rf"(?:^|{NOT_BEFORE}){pattern}$", prefix)


# Стандартные (выбираемые в запросе) поля по виду объекта. Виды и имена полей – по-русски намеренно:
# метаданные в линтере русско-канонические (semantics._member_family и семейства типов везде русские).
# Двуязычны только ключевые слова КОДА; блок Запрос{...} распознаёт лексер (query_ranges у вызывающего,
# он передаёт in_query). Реквизиты объекта берём из индекса (поле "attributes").
_STANDARD_QUERY_FIELDS = {
    "Справочник": ["Ссылка", "Код", "Наименование", "ПометкаУдаления", "Предопределённый"],
    "Документ": ["Ссылка", "Номер", "Дата", "Проведён", "ПометкаУдаления"],
}


def _name_of(item) -> str:
    return item.get("name", "") if isinstance(item, dict) else str(item)


def _query_field_entries(kind: str, attributes: list, tabular: list) -> list[dict]:
    """Поля таблицы в запросе: стандартные поля вида + реквизиты + ТЧ, без дублей по имени."""
    seen: set = set()
    entries: list[dict] = []

    def add(label: str, detail: str) -> None:
        if label and label not in seen:
            seen.add(label)
            entries.append({"label": label, "kind": "field", "detail": detail})

    for f in _STANDARD_QUERY_FIELDS.get(kind, []):
        add(f, "стандартное поле")
    for a in attributes:
        add(_name_of(a), "реквизит")
    for t in tabular:
        add(_name_of(t), "табличная часть")
    return entries


def _stdlib_entries(members) -> list[dict]:
    """Члены stdlib-типа: свойства и методы раздельно (у методов свой вид и скобки при вставке).

    Датасет отдаёт {"properties": [...], "methods": [...]}; прежний плоский список имён
    (свойства и методы вперемешку) понимаем ради совместимости со старыми данными.
    """
    if not isinstance(members, dict):
        return [{"label": str(x), "kind": "field", "detail": "член"} for x in members or []]
    entries = [
        {"label": str(x), "kind": "field", "detail": "свойство"}
        for x in members.get("properties") or []
    ]
    entries += [
        {"label": str(x), "kind": "method", "detail": "метод", "snippet": f"{x}($0)"}
        for x in members.get("methods") or []
    ]
    return entries


def resolve_completions(
    lookup: IndexLookup,
    *,
    language_id: str,
    line_prefix: str,
    file_stem: str,
    in_query: bool = False,
    stdlib_members: Optional[dict] = None,
    local_vars: Optional[dict] = None,
    query_tables: Optional[dict] = None,
    query_rows: Optional[dict] = None,
) -> Optional[list[dict]]:
    """Completion entries [{label, kind, detail}] for the context, or None when unknown."""
    m = _match_end(line_prefix, rf"Компоненты\.({IDENT})\.(?:{IDENT})?")
    if m:
        return [_method_entry(x) for x in lookup.methods_by_module(m.group(1))]
    m = _match_end(line_prefix, rf"Компоненты\.(?:{IDENT})?")
    if m:
        return [
            {"label": c.get("name", ""), "kind": "component", "detail": c.get("type", "")}
            for c in lookup.components_by_form(file_stem)
        ]
    m = _match_end(line_prefix, rf"({IDENT})\.(?:{IDENT})?")
    if m:
        token = m.group(1)
        # В блоке Запрос{...} после <Таблица>. – поля таблицы (стандартные + реквизиты + ТЧ), а не
        # члены объекта/менеджера. Контекст запроса и карту алиасов (`ИЗ Акция КАК А` – в проекте
        # к таблицам обращаются именно так) определяет вызывающий: язык запросов разбирает лексер.
        if in_query:
            table = lookup.object_by_name((query_tables or {}).get(token, token))
            if not table:
                return None
            return _query_field_entries(
                table.get("kind", ""), table.get("attributes", []), table.get("tabular", [])
            )
        # Переменная цикла по результату запроса (`для С из Результат`) – её члены суть колонки
        # выборки: имена считает вызывающий по алиасам ВЫБРАТЬ ... КАК.
        columns = (query_rows or {}).get(token)
        if columns:
            return [{"label": str(c), "kind": "field", "detail": "колонка запроса"} for c in columns]
        # Переменная в области видимости перекрывает всё остальное: `пер Список = новый Массив<...>()`
        # – это про члены Массива, даже если в stdlib есть одноимённый тип Список (компонент) или в
        # проекте объект с таким именем. Типы видимых переменных считает вызывающий (лексер, двуязычно).
        # Тип не из stdlib (структура проекта) – подсказать нечем, молчим: пусть работает словарное
        # дополнение редактора.
        if local_vars and token in local_vars:
            members = (stdlib_members or {}).get(local_vars[token])
            return _stdlib_entries(members) if members else None
        entries = _object_member_entries(lookup, token)
        if entries is not None:
            return entries
        # Не проект-объект и не переменная – значит stdlib-тип или глобаль (КонтекстДоступа.):
        # члены берём из type_members датасета линтера, ключ там под обеими формами имени.
        members = (stdlib_members or {}).get(token)
        return _stdlib_entries(members) if members else None
    if language_id == "yaml" and re.search(rf"(?:^|\s)Тип\s*:\s*(?:{IDENT})?$", line_prefix):
        return [
            {
                "label": o.get("name", ""),
                "kind": "enum" if o.get("kind") == "Перечисление" else "object",
                "detail": o.get("kind", ""),
            }
            for o in lookup.objects()
        ]
    return None


def _hover_object(obj: dict) -> str:
    lines = [f"**{obj.get('kind', 'Объект')} {obj.get('name', '')}**", "", f"`{obj.get('path', '')}`"]
    if obj.get("kind") == "Перечисление" and obj.get("values"):
        names = ", ".join(v.get("name", "") for v in obj["values"][:12])
        lines += ["", f"Значения: {names}"]
    else:
        if obj.get("tabular"):
            lines += ["", "Табличные части: " + ", ".join(t.get("name", "") for t in obj["tabular"])]
        if obj.get("local_types"):
            lines += ["", "Локальные типы: " + ", ".join(t.get("name", "") for t in obj["local_types"])]
    return "\n".join(lines)


def _hover_method(m: dict) -> str:
    annotations = " ".join("@" + a for a in (m.get("annotations") or []))
    head = f"**метод {m.get('module', '')}.{m.get('name', '')}**"
    if annotations:
        head += f" {annotations}"
    return f"{head}\n\n`{m.get('path', '')}:{m.get('line', 1)}`"


def resolve_hover(
    lookup: IndexLookup,
    *,
    language_id: str,
    line_text: str,
    character: int,
    file_stem: str,
    file_path: Optional[str] = None,
) -> Optional[str]:
    """Markdown hover text for the position, or None. Mirrors the definition contexts."""
    hit = chain_at(line_text, character)
    if not hit:
        return None
    parts, at = hit
    word = parts[at]

    if at == 0:
        obj = lookup.object_by_name(word)
        if obj:
            return _hover_object(obj)
        if len(parts) == 1 and language_id == "xbsl":
            method = (lookup.method_in_file(file_path, word) if file_path else None) or lookup.method(file_stem, word)
            if method:
                return _hover_method(method)
        return None
    if at == 1 and parts[0] == "Компоненты":
        c = lookup.component(file_stem, word)
        return f"**Компонент {c.get('name', '')}: {c.get('type', '')}**\n\n`{c.get('path', '')}`" if c else None
    if at == 2 and parts[0] == "Компоненты":
        method = lookup.method(parts[1], word)
        return _hover_method(method) if method else None
    if at != 1:
        return None

    qualifier = parts[at - 1]
    obj = lookup.object_by_name(qualifier)
    if obj:
        for t in obj.get("tabular", []):
            if t.get("name") == word:
                return f"**Табличная часть {qualifier}.{word}**\n\n`{obj.get('path', '')}:{t.get('line', 1)}`"
        for t in obj.get("local_types", []):
            if t.get("name") == word:
                return f"**Локальный тип {qualifier}.{word}**\n\n`{t.get('path', '')}:{t.get('line', 1)}`"
        for v in obj.get("values", []):
            if v.get("name") == word:
                return f"**Значение перечисления {qualifier}.{word}**\n\n`{obj.get('path', '')}:{v.get('line', 1)}`"
    method = lookup.method(qualifier, word)
    return _hover_method(method) if method else None
