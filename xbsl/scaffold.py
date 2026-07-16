"""Скаффолдинг метаданных 1С:Элемент: создание объектов, полей, маршрутов, форм и проектов.

Модуль – единственный источник шаблонов и правок yaml/xbsl для всех поверхностей
инструментария: MCP-инструменты meta_* (mcp_server.py), кастомные LSP-запросы xbsl/meta*
(lsp.py) и подкоманды CLI (cli.py). Расширение VS Code – тонкий клиент этих поверхностей,
собственной логики записи у него нет.

Слои:
    - чистые функции текста: вставка элемента секции (insert_item_edit и родня), шаблоны
      новых объектов и форм – без файловой системы, покрыты модульными тестами;
    - разведка проекта: лёгкий текстовый скан (проекты, подсистемы, объекты, реквизиты) –
      те же соглашения разбора, что в индексаторе, но без построения полного индекса;
    - операции (op_*): собирают изменения в ScaffoldResult {создаваемые файлы + полные
      новые тексты правимых файлов}, НИЧЕГО не пишут – применение отдано вызывающему:
      MCP/CLI пишут на диск (apply_result), редактор применяет через WorkspaceEdit;
    - применение: apply_result сохраняет с переводами строк и BOM исходного файла.

Разбор yaml здесь текстовый (по заголовкам секций и отступам), а не через PyYAML:
правки должны быть точечными вставками в существующий текст, не переформатированием
документа; парсер позиций вставки не даёт.
"""

from __future__ import annotations

import re
import uuid as _uuid
from dataclasses import dataclass, field
from pathlib import Path

from xbsl import engine, fixer

PROJECT_FILE = "Проект.yaml"
SUBSYSTEM_FILE = "Подсистема.yaml"

_IDENTIFIER = re.compile(r"^[A-Za-zА-Яа-яЁё_][A-Za-zА-Яа-яЁё0-9_]*$")
_KIND_RE = re.compile(r"^ВидЭлемента:\s*(\S+)", re.M)
_NAME_RE = re.compile(r"^Имя:\s*(\S+)", re.M)
_VENDOR_RE = re.compile(r"^Поставщик:\s*(\S+)", re.M)
_LINE_INDENT = re.compile(r"^[ \t]*")


class ScaffoldError(RuntimeError):
    """Ошибка операции скаффолдинга; текст показывается пользователю как есть."""


def _check_identifier(name: str, что: str) -> str:
    name = name.strip()
    if not _IDENTIFIER.match(name):
        raise ScaffoldError(
            f"Недопустимое имя {что}: '{name}' (нужен идентификатор: буквы, цифры, подчёркивание)"
        )
    return name


def new_uuid() -> str:
    return str(_uuid.uuid4())


# --- правки текста -------------------------------------------------------------------


@dataclass(frozen=True)
class TextEdit:
    start: int
    end: int
    new_text: str


def apply_edit(text: str, edit: TextEdit) -> str:
    return text[: edit.start] + edit.new_text + text[edit.end :]


def _line_end(text: str, offset: int) -> int:
    nl = text.find("\n", offset)
    return len(text) if nl == -1 else nl


def _detect_indent(body_slice: str, header_indent: int) -> tuple[str, str]:
    """Отступы элемента секции по первому существующему "-" в теле; иначе – по заголовку."""
    m = re.search(r"^([ \t]*)-[ \t]*\r?\n([ \t]*)\S", body_slice, re.M)
    if m:
        return m.group(1), m.group(2)
    return " " * (header_indent + 4), " " * (header_indent + 8)


def _section_bounds(text: str, section: str) -> tuple[int, int, int] | None:
    """(отступ заголовка, конец строки заголовка, конец тела) секции верхнего уровня или None.

    Конец тела – конец последней непустой строки с отступом больше отступа заголовка.
    """
    header = re.search(rf"^([ \t]*){re.escape(section)}:[ \t]*\r?$", text, re.M)
    if header is None:
        return None
    header_indent = len(header.group(1))
    header_line_end = _line_end(text, header.start())
    body_end = header_line_end
    pos = header_line_end
    while pos < len(text):
        line_start = pos + 1
        line_end = _line_end(text, line_start)
        line = text[line_start:line_end]
        blank = line.strip() == ""
        indent = len(_LINE_INDENT.match(line).group(0))
        if not blank and indent <= header_indent:
            break
        if not blank:
            body_end = line_end
        pos = line_end
    return header_indent, header_line_end, body_end


def insert_item_edit(text: str, section: str, item_lines: list[str], nl: str = "\n") -> TextEdit:
    """Точечная вставка нового элемента (набор строк-полей) в конец секции верхнего уровня.

    Нет секции – дописывается в конец файла. Порт insertItemEdit из расширения VS Code
    (metadataCore.ts) с одним отличием: перевод строки задаётся параметром, чтобы правка
    не смешивала стили в CRLF-файлах.
    """

    def body(item: str, fld: str) -> str:
        return f"{item}-{nl}" + nl.join(f"{fld}{line}" for line in item_lines)

    bounds = _section_bounds(text, section)
    if bounds is None:
        tail = "" if (not text or text.endswith("\n")) else nl
        new = f"{tail}{section}:{nl}{body('    ', '        ')}{nl}"
        return TextEdit(len(text), len(text), new)

    header_indent, header_line_end, body_end = bounds
    item, fld = _detect_indent(text[header_line_end:body_end], header_indent)
    insert_at = body_end
    return TextEdit(insert_at, insert_at, f"{nl}{body(item, fld)}")


def insert_nested_item_edit(
    text: str, block_offset: int, section: str, item_lines: list[str], nl: str = "\n"
) -> TextEdit:
    """Вставка элемента во вложенную секцию блока-элемента (напр. Реквизиты табличной части).

    block_offset – смещение первого ключа блока (см. find_section_item_offset). Границы блока –
    до первой непустой строки с отступом меньше отступа полей блока. Порт insertTabularAttrEdit.
    """
    line_start = text.rfind("\n", 0, block_offset) + 1
    field_indent = block_offset - line_start
    block_end = len(text)
    pos = _line_end(text, block_offset)
    while pos < len(text):
        ls = pos + 1
        le = _line_end(text, ls)
        line = text[ls:le]
        if line.strip() != "" and len(_LINE_INDENT.match(line).group(0)) < field_indent:
            block_end = ls
            break
        pos = le
    block = text[block_offset:block_end]
    has_section = re.search(rf"^[ \t]{{{field_indent}}}{re.escape(section)}:[ \t]*\r?$", block, re.M)
    if has_section:
        sub = insert_item_edit(block, section, item_lines, nl)
        return TextEdit(block_offset + sub.start, block_offset + sub.end, sub.new_text)
    # Нет вложенной секции – дописываем её в конец содержимого блока.
    head = " " * field_indent
    item = " " * (field_indent + 4)
    fld = " " * (field_indent + 8)
    content_end = 0
    p = 0
    while p < len(block):
        e = block.find("\n", p)
        end = len(block) if e == -1 else e
        if block[p:end].strip() != "":
            content_end = end
        if e == -1:
            break
        p = e + 1
    body = nl.join(f"{fld}{line}" for line in item_lines)
    new = f"{nl}{head}{section}:{nl}{item}-{nl}{body}"
    return TextEdit(block_offset + content_end, block_offset + content_end, new)


def section_items(text: str, section: str) -> list[dict[str, str]]:
    """Скалярные поля элементов секции верхнего уровня (для проверок дублей и обзора).

    Элемент – блок за "-" на минимальном отступе тела секции; вложенные секции элемента
    (Реквизиты ТЧ, Методы шаблона) в словарь не попадают, их поля – глубже отступа полей.
    """
    bounds = _section_bounds(text, section)
    if bounds is None:
        return []
    _, header_line_end, body_end = bounds
    body = text[header_line_end:body_end]
    m = re.search(r"^([ \t]*)-", body, re.M)
    if m is None:
        return []
    item_indent = len(m.group(1))
    items: list[dict[str, str]] = []
    current: dict[str, str] | None = None
    field_indent: int | None = None
    for line in body.split("\n"):
        stripped = line.strip()
        if not stripped:
            continue
        indent = len(_LINE_INDENT.match(line).group(0))
        if indent == item_indent and stripped.startswith("-"):
            if current is not None:
                items.append(current)
            current = {}
            field_indent = None
            rest = stripped[1:].strip()
            if rest and ":" in rest:  # инлайновая форма "- Имя: X"
                k, _, v = rest.partition(":")
                current[k.strip()] = v.strip()
            continue
        if current is None:
            continue
        if field_indent is None and indent > item_indent and ":" in stripped:
            field_indent = indent
        if indent == field_indent and ":" in stripped and not stripped.startswith("-"):
            k, _, v = stripped.partition(":")
            v = v.strip()
            if v:
                current[k.strip()] = v
    if current is not None:
        items.append(current)
    return items


def find_section_item_offset(text: str, section: str, name: str) -> int | None:
    """Смещение первого ключа элемента секции с Имя == name (для вложенных вставок)."""
    bounds = _section_bounds(text, section)
    if bounds is None:
        return None
    _, header_line_end, body_end = bounds
    body = text[header_line_end:body_end]
    m = re.search(r"^([ \t]*)-", body, re.M)
    if m is None:
        return None
    item_indent = len(m.group(1))
    pos = 0
    current_start: int | None = None
    current_named = False
    for raw in body.split("\n"):
        line_len = len(raw) + 1
        stripped = raw.strip()
        indent = len(_LINE_INDENT.match(raw).group(0))
        if stripped.startswith("-") and indent == item_indent:
            current_start = None
            current_named = False
        elif stripped and current_start is None and indent > item_indent:
            current_start = header_line_end + pos + indent
        if stripped.startswith("Имя:") and current_start is not None and not current_named:
            value = stripped[len("Имя:"):].strip()
            if value == name:
                return current_start
            current_named = True
        pos += line_len
    return None


def top_level_key_span(text: str, key: str) -> tuple[int, int] | None:
    """(начало строки ключа, конец тела) ключа верхнего уровня со вложенным содержимым."""
    m = re.search(rf"^{re.escape(key)}:[ \t]*\r?$", text, re.M)
    if m is None:
        return None
    bounds = _section_bounds(text, key)
    if bounds is None:
        return None
    _, _, body_end = bounds
    return m.start(), body_end


# --- шаблоны новых объектов -----------------------------------------------------------


def new_object_yaml(kind: str, uid: str, name: str, scope: str, extra_lines: list[str]) -> str:
    lines = [f"ВидЭлемента: {kind}", f"Ид: {uid}", f"Имя: {name}", f"ОбластьВидимости: {scope}"]
    return "\n".join(lines + list(extra_lines)) + "\n"


@dataclass(frozen=True)
class KindSpec:
    scope: str = "ВПроекте"  # ОбластьВидимости по умолчанию
    module: bool = False  # создавать парный .xbsl
    extra: tuple[str, ...] = ()  # доп. строки шаблона (могут содержать {name})


# Создаваемые виды объектов: набор витрины VS Code плюс Отчет, КлючДоступа и
# ЛокализованныеСтроки.
KIND_SPECS: dict[str, KindSpec] = {
    "Справочник": KindSpec(),
    "Документ": KindSpec(),
    "Перечисление": KindSpec(),
    "Структура": KindSpec(extra=("Окружение: КлиентИСервер",)),
    "РегистрСведений": KindSpec(),
    "РегистрНакопления": KindSpec(),
    "ПараметрыРаботыКлиента": KindSpec(),
    "ОбщийМодуль": KindSpec(module=True, extra=("Окружение: Сервер",)),
    "HttpСервис": KindSpec(scope="ВПодсистеме", module=True, extra=("КорневойUrl: /{name}",)),
    "ГлобальноеКлиентскоеСобытие": KindSpec(),
    "ФрагментКомандногоИнтерфейса": KindSpec(),
    "КомпонентИнтерфейса": KindSpec(
        scope="ВПодсистеме",
        extra=(
            "Наследует:",
            "    Тип: Форма",
            "    Содержимое:",
            "        Тип: Группа",
            "        Компоновка: Вертикальная",
        ),
    ),
    "КлючДоступа": KindSpec(module=True),
    "ЛокализованныеСтроки": KindSpec(scope="ВПодсистеме"),
    "Отчет": KindSpec(scope="ВПодсистеме"),
}

# Пополняемые секции: yaml-секция + строки нового элемента.
_WITH_TYPE = ("Ид: {uuid}", "Имя: {name}", "Тип: {type}")
_SECTION_SPECS: dict[str, dict] = {
    "реквизит": {"section": "Реквизиты", "lines": _WITH_TYPE},
    "измерение": {"section": "Измерения", "lines": _WITH_TYPE},
    "ресурс": {"section": "Ресурсы", "lines": _WITH_TYPE},
    "значение": {"section": "Элементы", "lines": ("Ид: {uuid}", "Имя: {name}")},
    "параметр": {"section": "Параметры", "lines": ("Имя: {name}", "Тип: {type}")},
    "поле": {"section": "Поля", "lines": ("Имя: {name}", "Тип: {type}")},
    "табличная-часть": {
        "section": "ТабличныеЧасти",
        # Табличная часть с одним стартовым реквизитом (пустая обычно бесполезна).
        "lines": (
            "Ид: {uuid}",
            "Имя: {name}",
            "Реквизиты:",
            "    -",
            "        Ид: {uuid2}",
            "        Имя: Реквизит1",
            "        Тип: Строка",
        ),
    },
}

# Вид объекта -> какие секции у него пополняемы.
KIND_SECTIONS: dict[str, tuple[str, ...]] = {
    "Справочник": ("реквизит", "табличная-часть"),
    "Документ": ("реквизит", "табличная-часть"),
    "РегистрСведений": ("измерение", "ресурс", "реквизит"),
    "РегистрНакопления": ("измерение", "ресурс", "реквизит"),
    "Перечисление": ("значение",),
    "ПараметрыРаботыКлиента": ("параметр",),
    "Структура": ("поле",),
    "ХранимаяСтруктура": ("поле",),
    "КлючДоступа": ("параметр",),
}

FIELD_KINDS = tuple(_SECTION_SPECS)


# --- разведка проекта -----------------------------------------------------------------


def _read(path: Path) -> str:
    return engine.load(path).text


@dataclass
class ObjectHit:
    kind: str
    name: str
    path: Path  # yaml объекта
    subsystem: str | None
    namespace: str  # vendor::project::subsystem
    text: str = field(repr=False, default="")


def find_projects(root: Path) -> list[dict]:
    """Проекты под корнем: [{vendor, name, dir, subsystems: [имена]}], скрытые каталоги пропускаются."""
    out = []
    for project_yaml in sorted(root.rglob(PROJECT_FILE)):
        rel = project_yaml.relative_to(root)
        if any(part.startswith(".") for part in rel.parts):
            continue
        text = _read(project_yaml)
        project_dir = project_yaml.parent
        vendor = (_VENDOR_RE.search(text) or [None, project_dir.parent.name])[1]
        name = (_NAME_RE.search(text) or [None, project_dir.name])[1]
        subsystems = sorted(
            p.parent.name for p in project_dir.rglob(SUBSYSTEM_FILE)
            if not any(part.startswith(".") for part in p.relative_to(project_dir).parts)
        )
        out.append({"vendor": vendor, "name": name, "dir": project_dir, "subsystems": subsystems})
    return out


def _iter_objects(root: Path):
    for yaml_path in engine.find_sources(root, "*.yaml"):
        if yaml_path.name in (PROJECT_FILE, SUBSYSTEM_FILE):
            continue
        text = _read(yaml_path)
        kind_m = _KIND_RE.search(text)
        if kind_m is None:
            continue
        name = (_NAME_RE.search(text) or [None, yaml_path.stem])[1]
        yield yaml_path, kind_m.group(1), name, text


def _namespace_of(yaml_path: Path, root: Path) -> tuple[str | None, str]:
    """(имя подсистемы, vendor::project::subsystem) для файла объекта."""
    subsystem = yaml_path.parent.name if (yaml_path.parent / SUBSYSTEM_FILE).is_file() else None
    project_dir = yaml_path.parent
    while project_dir != project_dir.parent:
        if (project_dir / PROJECT_FILE).is_file():
            break
        if project_dir == root:
            break
        project_dir = project_dir.parent
    vendor = project = ""
    project_yaml = project_dir / PROJECT_FILE
    if project_yaml.is_file():
        text = _read(project_yaml)
        vendor = (_VENDOR_RE.search(text) or [None, project_dir.parent.name])[1]
        project = (_NAME_RE.search(text) or [None, project_dir.name])[1]
    parts = [p for p in (vendor, project, subsystem) if p]
    return subsystem, "::".join(parts)


def find_object(root: Path, name: str) -> ObjectHit:
    """Объект по имени; несколько тёзок или отсутствие – ошибка с перечислением кандидатов."""
    hits = []
    for yaml_path, kind, obj_name, text in _iter_objects(root):
        if obj_name == name:
            subsystem, namespace = _namespace_of(yaml_path, root)
            hits.append(ObjectHit(kind, obj_name, yaml_path, subsystem, namespace, text))
    if not hits:
        raise ScaffoldError(f"Объект '{name}' не найден под {root}")
    if len(hits) > 1:
        paths = "; ".join(str(h.path) for h in hits)
        raise ScaffoldError(f"Имя '{name}' неоднозначно: {paths} – укажите файл объекта явно")
    return hits[0]


PRIMITIVE_TYPES = {
    "Строка", "Число", "Булево", "Дата", "ДатаВремя", "Время", "УникальныйИдентификатор",
}

# Стандартные (предопределённые платформой) реквизиты: в yaml их обычно нет, но в формах они нужны.
_STANDARD_FIELDS = {
    "Справочник": [{"name": "Наименование", "type": "Строка"}],
    "Документ": [{"name": "Номер", "type": "Строка"}, {"name": "Дата", "type": "ДатаВремя"}],
}


def object_info(root: Path, name: str | None = None, yaml_path: Path | None = None) -> dict:
    """Сводка объекта для генерации форм и обзора.

    Реквизиты дополняются стандартными полями вида (Наименование / Номер+Дата), если их нет
    в yaml: формы строятся по полному списку.
    """
    if yaml_path is not None:
        yaml_path = Path(yaml_path)
        if not yaml_path.is_file():
            raise ScaffoldError(f"Файл не найден: {yaml_path}")
        text = _read(yaml_path)
        kind_m = _KIND_RE.search(text)
        if kind_m is None:
            raise ScaffoldError(f"В {yaml_path} нет ВидЭлемента – это не объект конфигурации")
        subsystem, namespace = _namespace_of(yaml_path, root)
        hit = ObjectHit(
            kind_m.group(1), (_NAME_RE.search(text) or [None, yaml_path.stem])[1],
            yaml_path, subsystem, namespace, text,
        )
    else:
        hit = find_object(root, name or "")
        text = hit.text

    fields = []
    for item in section_items(text, "Реквизиты"):
        fields.append({"name": item.get("Имя", "?"), "type": item.get("Тип", "")})
    declared = {f["name"] for f in fields}
    standard = [f for f in _STANDARD_FIELDS.get(hit.kind, []) if f["name"] not in declared]
    fields = standard + fields

    tabulars = [
        {
            "name": item.get("Имя", "?"),
            "fields": [],
        }
        for item in section_items(text, "ТабличныеЧасти")
    ]
    hierarchies = [
        {"name": h.get("Имя", ""), "field": h.get("ПолеРодителя", "")}
        for h in section_items(text, "ДополнительныеИерархии")
    ]
    is_hierarchical = bool(re.search(r"^Иерархический:\s*Истина", text, re.M))

    stem = hit.path.stem
    if hit.kind == "Отчет":
        existing_forms = {"ФормаОтчета": _existing(hit.path.parent, f"{stem}ФормаОтчета.yaml")}
        layout = "report"
    else:
        existing_forms = {
            "ФормаОбъекта": _existing(hit.path.parent, f"{stem}ФормаОбъекта.yaml"),
            "ФормаСписка": _existing(hit.path.parent, f"{stem}ФормаСписка.yaml"),
        }
        layout = _suggest_layout(len(fields), len(tabulars))

    return {
        "path": str(hit.path),
        "kind": hit.kind,
        "name": hit.name,
        "subsystem": hit.subsystem,
        "namespace": hit.namespace,
        "fields": fields,
        "tabulars": tabulars,
        "suggested_layout": layout,
        "existing_forms": existing_forms,
        "is_hierarchical": is_hierarchical,
        "additional_hierarchies": hierarchies,
        "report_params": [
            {"name": p.get("Имя", "?"), "type": p.get("Тип", "")}
            for p in section_items(text, "ПараметрыЗапроса")
        ],
        "sections": {
            kind: [i.get("Имя", "?") for i in section_items(text, _SECTION_SPECS[kind]["section"])]
            for kind in KIND_SECTIONS.get(hit.kind, ())
        },
    }


def _existing(directory: Path, filename: str) -> str | None:
    return filename if (directory / filename).is_file() else None


def _suggest_layout(field_count: int, tc_count: int) -> str:
    if tc_count == 0:
        return "simple"
    if tc_count == 1 and field_count >= 5:
        return "panels"
    return "tabs"


def project_info(root: Path) -> dict:
    """Обзор исходников под корнем: проекты, подсистемы и объекты по видам."""
    projects = find_projects(root)
    objects = []
    for yaml_path, kind, name, _text in _iter_objects(root):
        subsystem, namespace = _namespace_of(yaml_path, root)
        objects.append(
            {"kind": kind, "name": name, "path": str(yaml_path), "subsystem": subsystem, "namespace": namespace}
        )
    return {
        "projects": [
            {**p, "dir": str(p["dir"])} for p in projects
        ],
        "objects": sorted(objects, key=lambda o: (o["kind"], o["name"])),
        "creatable_kinds": sorted(KIND_SPECS),
        "field_kinds": {kind: list(sections) for kind, sections in KIND_SECTIONS.items()},
    }


# --- результат операции и применение ---------------------------------------------------


@dataclass
class FileChange:
    path: Path
    content: str  # полный новый текст файла
    created: bool  # True – новый файл, False – правка существующего
    cursor: tuple[int, int] | None = None  # (строка, колонка) точки интереса, 0-базные


@dataclass(frozen=True)
class FileRename:
    old_path: Path
    new_path: Path


@dataclass
class ScaffoldResult:
    changes: list[FileChange] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)  # предупреждения, ручные шаги
    renames: list[FileRename] = field(default_factory=list)  # переименования файлов (до правок)

    def as_dict(self, content: bool = True) -> dict:
        files = []
        for c in self.changes:
            entry = {"path": str(c.path), "created": c.created}
            if content:
                entry["content"] = c.content
            entry["cursor"] = (
                {"line": c.cursor[0], "character": c.cursor[1]} if c.cursor else None
            )
            files.append(entry)
        return {
            "renames": [
                {"from": str(r.old_path), "to": str(r.new_path)} for r in self.renames
            ],
            "files": files,
            "notes": self.notes,
        }


def apply_result(result: ScaffoldResult) -> list[str]:
    """Записать изменения на диск; возвращает пути записанных файлов.

    Переименования файлов выполняются до записи правок: правки переименованных файлов
    ссылаются на новые пути. Правка существующего файла сохраняет его BOM (кодировку
    определяет engine.load); переводы строк выбирает сама операция при генерации текста.
    """
    for rename in result.renames:
        if rename.new_path.exists():
            raise ScaffoldError(f"Файл уже существует: {rename.new_path}")
        rename.new_path.parent.mkdir(parents=True, exist_ok=True)
        rename.old_path.rename(rename.new_path)
    written = []
    for change in result.changes:
        change.path.parent.mkdir(parents=True, exist_ok=True)
        if change.created or not change.path.exists():
            change.path.write_bytes(change.content.encode("utf-8"))
        else:
            source = engine.load(change.path)
            change.path.write_bytes(fixer.encode(source, change.content))
        written.append(str(change.path))
    return written


def _cursor_at(text: str, offset: int) -> tuple[int, int]:
    line = text.count("\n", 0, offset)
    return line, offset - (text.rfind("\n", 0, offset) + 1)


def _dominant_nl(text: str) -> str:
    return fixer._dominant_newline(text) if text else "\n"


# Чтение правимого файла. reader: Callable[[Path], str]; LSP подставляет читателя, который
# сначала смотрит в открытые буферы редактора: правка обязана исходить из текста с
# несохранёнными изменениями, иначе применение полного нового текста их затёрло бы.
def _load_for_edit(yaml_path: Path, reader=None) -> tuple[str, str]:
    if not yaml_path.is_file():
        raise ScaffoldError(f"Файл не найден: {yaml_path}")
    text = (reader or _read)(yaml_path)
    return text, _dominant_nl(text)


# --- операции: объект, поле, подсистема, проект ----------------------------------------


def op_new_object(
    directory: Path,
    kind: str,
    name: str,
    *,
    scope: str | None = None,
    environment: str | None = None,
    access: str | None = None,
    routes: str | None = None,
    report: dict | None = None,
) -> ScaffoldResult:
    """Создать объект конфигурации: Имя.yaml (+ Имя.xbsl у видов с модулем).

    environment – Окружение для ОбщийМодуль/Структура; access – КонтрольДоступа
    (у HttpСервис – Разрешения.Вызов, у объектов данных – ПоУмолчанию); routes –
    маршруты HttpСервис ("GET /, POST /, GET /{id}"); report – источник и макет отчёта.
    """
    spec = KIND_SPECS.get(kind)
    if spec is None:
        raise ScaffoldError(
            f"Вид '{kind}' не поддерживается; доступны: {', '.join(sorted(KIND_SPECS))}"
        )
    name = _check_identifier(name, "объекта")
    directory = Path(directory)
    yaml_path = directory / f"{name}.yaml"
    if yaml_path.exists():
        raise ScaffoldError(f"Файл уже существует: {yaml_path}")

    result = ScaffoldResult()
    if kind == "HttpСервис":
        return _new_http_service(yaml_path, name, access, routes or "GET /", result)
    if kind == "Отчет":
        return _new_report(yaml_path, name, report or {}, result)

    extra = [line.format(name=name) for line in spec.extra]
    if environment:
        extra = [line for line in extra if not line.startswith("Окружение:")]
        extra.append(f"Окружение: {environment}")
    if access:
        extra += ["КонтрольДоступа:", f"    ПоУмолчанию: {access}"]
    content = new_object_yaml(kind, new_uuid(), name, scope or spec.scope, extra)
    result.changes.append(FileChange(yaml_path, content, created=True))
    if spec.module:
        result.changes.append(
            FileChange(yaml_path.with_suffix(".xbsl"), f"// {name}\n", created=True)
        )
    return result


def op_add_field(
    yaml_path: Path,
    field_kind: str,
    name: str,
    *,
    type_: str = "Строка",
    tabular: str | None = None,
    reader=None,
) -> ScaffoldResult:
    """Добавить элемент секции объекта: реквизит, измерение, ресурс, значение перечисления,
    параметр, поле структуры или табличную часть; tabular – имя ТЧ для реквизита в неё.
    """
    yaml_path = Path(yaml_path)
    name = _check_identifier(name, "элемента")
    text, nl = _load_for_edit(yaml_path, reader)
    kind_m = _KIND_RE.search(text)
    kind = kind_m.group(1) if kind_m else "?"

    if tabular:
        if field_kind != "реквизит":
            raise ScaffoldError("В табличную часть добавляются только реквизиты")
        offset = find_section_item_offset(text, "ТабличныеЧасти", tabular)
        if offset is None:
            raise ScaffoldError(f"Табличная часть '{tabular}' не найдена в {yaml_path.name}")
        lines = [f"Ид: {new_uuid()}", f"Имя: {name}", f"Тип: {type_}"]
        edit = insert_nested_item_edit(text, offset, "Реквизиты", lines, nl)
        new_text = apply_edit(text, edit)
        cursor = _cursor_at(new_text, edit.start + len(edit.new_text))
        return ScaffoldResult([FileChange(yaml_path, new_text, created=False, cursor=cursor)])

    spec = _SECTION_SPECS.get(field_kind)
    if spec is None:
        raise ScaffoldError(
            f"Неизвестный вид элемента '{field_kind}'; доступны: {', '.join(FIELD_KINDS)}"
        )
    allowed = KIND_SECTIONS.get(kind)
    if allowed is not None and field_kind not in allowed:
        raise ScaffoldError(
            f"У вида {kind} нет секции для '{field_kind}'; доступны: {', '.join(allowed)}"
        )
    existing = {i.get("Имя") for i in section_items(text, spec["section"])}
    if name in existing:
        raise ScaffoldError(f"'{name}' уже есть в секции {spec['section']} файла {yaml_path.name}")
    lines = [
        line.format(uuid=new_uuid(), uuid2=new_uuid(), name=name, type=type_)
        for line in spec["lines"]
    ]
    edit = insert_item_edit(text, spec["section"], lines, nl)
    new_text = apply_edit(text, edit)
    cursor = _cursor_at(new_text, edit.start + len(edit.new_text))
    return ScaffoldResult([FileChange(yaml_path, new_text, created=False, cursor=cursor)])


def op_add_subsystem(
    parent_dir: Path,
    name: str,
    *,
    representation: str | None = None,
    auto_interface: bool = True,
    uses: list[str] | None = None,
) -> ScaffoldResult:
    """Создать подсистему: папка + Подсистема.yaml (блоки собираются по параметрам)."""
    name = _check_identifier(name, "подсистемы")
    parent_dir = Path(parent_dir)
    yaml_path = parent_dir / name / SUBSYSTEM_FILE
    if yaml_path.exists():
        raise ScaffoldError(f"Файл уже существует: {yaml_path}")
    lines: list[str] = []
    if uses:
        lines.append("Использование:")
        lines += [f"    - {u}" for u in uses]
    if auto_interface or representation:
        lines.append("Интерфейс:")
        lines.append(f"    ВключатьВАвтоИнтерфейс: {'Истина' if auto_interface else 'Ложь'}")
        if representation:
            lines.append(f"    Представление: {representation}")
    content = ("\n".join(lines) + "\n") if lines else ""
    return ScaffoldResult([FileChange(yaml_path, content, created=True)])


_PROJECT_MODULE_STUB = """\
// @НастройкаПриложения(Ид = "НастройкаПриложения", Номер = 1)
// метод НастройкаПриложения(НоваяВерсия: Версия)
// TODO Раскомментируйте метод и вставьте код обработчика. Метод с таким Ид будет выполнен только один раз!
// ;

// @ОбновлениеПроекта(Ид = "КонвертацияДанных", Номер = 1)
// метод КонвертацияДанных(ИсходнаяВерсия: Версия, ЦелеваяВерсия: Версия)
// TODO Раскомментируйте метод и вставьте код обработчика. Метод с таким Ид будет выполнен только один раз!
// ;
"""


def op_new_project(
    root: Path,
    vendor: str,
    name: str,
    *,
    representation: str | None = None,
    version: str = "1.0",
    compatibility: str = "9.0",
    subsystem: str = "Основное",
    library: bool = False,
) -> ScaffoldResult:
    """Создать проект с нуля: Проект.yaml + Проект.xbsl + первая подсистема."""
    vendor = _check_identifier(vendor, "поставщика")
    name = _check_identifier(name, "проекта")
    subsystem = _check_identifier(subsystem, "подсистемы")
    project_dir = Path(root) / vendor / name
    if (project_dir / PROJECT_FILE).exists():
        raise ScaffoldError(f"Проект уже существует: {project_dir / PROJECT_FILE}")
    lines = [f"Ид: {new_uuid()}"]
    if library:
        lines.append("ВидПроекта: Библиотека")
    lines += [
        f"Представление: \"{representation or name}\"",
        f"Версия: {version}",
        f"Поставщик: {vendor}",
        f"Имя: {name}",
        f"ПредставлениеПоставщика: \"{vendor}\"",
        f"РежимСовместимости: {compatibility}",
        "ЯзыкиЛокализации: [Русский]",
        "ЯзыкПоУмолчанию: Русский",
        "ЯзыкРазработки: Русский",
    ]
    result = ScaffoldResult(
        [
            FileChange(project_dir / PROJECT_FILE, "\n".join(lines) + "\n", created=True),
            FileChange(project_dir / "Проект.xbsl", _PROJECT_MODULE_STUB, created=True),
            FileChange(
                project_dir / subsystem / SUBSYSTEM_FILE,
                "Интерфейс:\n    ВключатьВАвтоИнтерфейс: Истина\n",
                created=True,
            ),
        ]
    )
    if library:
        result.notes.append(
            "Библиотека не разворачивается как самостоятельное приложение – подключается через Импорт"
        )
    return result


# --- операции: HTTP-сервис и маршруты ---------------------------------------------------

_METHOD_ORDER = ["GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"]
_HANDLER_NAMES: dict[tuple[str, bool], str] = {
    ("GET", False): "ПолучитьСписок",
    ("POST", False): "Создать",
    ("GET", True): "ПолучитьПоИд",
    ("PUT", True): "Обновить",
    ("PATCH", True): "ОбновитьЧастично",
    ("DELETE", True): "Удалить",
}
_METHOD_RU = {
    "GET": "Получить", "POST": "Создать", "PUT": "Обновить",
    "PATCH": "ОбновитьЧастично", "DELETE": "Удалить",
}


def parse_routes(routes_str: str) -> list[tuple[str, list[str]]]:
    """"GET /, POST /, GET /{id}" -> [(шаблон, [методы])] с сохранением порядка шаблонов."""
    grouped: dict[str, list[str]] = {}
    order: list[str] = []
    for part in re.split(r"[,\n]+", routes_str):
        part = part.strip()
        if not part:
            continue
        tokens = part.split(None, 1)
        if len(tokens) != 2:
            raise ScaffoldError(f"Неверный формат маршрута: '{part}' (ожидается 'МЕТОД /путь')")
        method, path = tokens[0].upper(), tokens[1].strip()
        if not path.startswith("/"):
            path = "/" + path
        if path not in grouped:
            grouped[path] = []
            order.append(path)
        if method not in grouped[path]:
            grouped[path].append(method)
    for path in order:
        grouped[path].sort(key=lambda m: _METHOD_ORDER.index(m) if m in _METHOD_ORDER else 99)
    return [(path, grouped[path]) for path in order]


def _has_path_param(path: str) -> bool:
    return bool(re.search(r"\{[^}]+\}", path))


def _to_pascal(s: str) -> str:
    s = s.strip("{}")
    return s[:1].upper() + s[1:] if s else s


def template_name(path: str) -> str:
    if path == "/":
        return "Список"
    segments = [s for s in path.lstrip("/").split("/") if s]
    literal = [s for s in segments if not (s.startswith("{") and s.endswith("}"))]
    params = [s for s in segments if s.startswith("{") and s.endswith("}")]
    if not literal:
        return "ЭлементПоИд"
    if params:
        return _to_pascal(literal[-1]) + "ПоРодителю"
    return _to_pascal(literal[-1])


def assign_handler(method: str, path: str, used: set[str]) -> str:
    """Имя обработчика маршрута: словарное (ПолучитьСписок и т.п.), при занятости –
    <Метод><ИмяШаблона>, дальше числовой суффикс. Имя помечается занятым."""
    name = _HANDLER_NAMES.get((method, _has_path_param(path)))
    if name is None or name in used:
        name = f"{_METHOD_RU.get(method, method.capitalize())}{template_name(path)}"
    base, n = name, 2
    while name in used:
        name = f"{base}{n}"
        n += 1
    used.add(name)
    return name


def _template_lines(path: str, method_handlers: list[tuple[str, str]]) -> list[str]:
    lines = [f"Имя: {template_name(path)}", f"Шаблон: {path}", "Методы:"]
    for method, handler in method_handlers:
        lines += [
            "    -",
            f"        Метод: {method}",
            f"        Обработчик: {handler}",
        ]
    return lines


def _handler_stub(method: str, path: str, handler: str) -> str:
    """Заготовка обработчика маршрута: канонический CRUD-скелет по методу и параметрам пути."""
    key = (method, _has_path_param(path))
    if key == ("GET", False):
        body = """\
    попытка
        знч ОграничениеПоУмолчанию = 100
        пер Ограничение: Число
        знч ПараметрЛимит = Запрос.Параметры.ПолучитьПервый("limit")
        если ПараметрЛимит != Неопределено
            Ограничение = Мин(новый Число(ПараметрЛимит), ОграничениеПоУмолчанию)
        иначе
            Ограничение = ОграничениеПоУмолчанию
        ;
        // TODO: получить данные
        // знч Данные = <Справочник>.ПолучитьСписок(Ограничение)
        // Запрос.Ответ.Заголовки.Установить("Content-Type", "application/json")
        // Запрос.Ответ.УстановитьТело(СериализацияJson.ЗаписатьОбъект(Данные))
    поймать Исключение: Исключение
        ОбработатьОшибку(Запрос.Ответ, Исключение)
    ;"""
    elif key == ("POST", False):
        body = """\
    попытка
        // TODO: десериализовать тело и создать объект
        // знч Данные = СериализацияJson.ПрочитатьОбъект(Запрос.Тело, Тип<...>)
        // знч Ссылка = <Справочник>.Создать(Данные)
        Запрос.Ответ.УстановитьКодСтатуса(201)
        // Запрос.Ответ.УстановитьТело(Ссылка.Ид.ВСтроку())
    поймать Исключение: Исключение
        ОбработатьОшибку(Запрос.Ответ, Исключение)
    ;"""
    elif key == ("GET", True):
        m = re.search(r"\{([^}]+)\}", path)
        param = m.group(1) if m else "id"
        body = f"""\
    попытка
        знч Ид = Запрос.Параметры.ПолучитьПервый("{param}")
        // TODO: найти объект по Ид
        // знч Объект = <Справочник>.НайтиПоИд(Ид)
        // если Объект == Неопределено
        //     Запрос.Ответ.УстановитьКодСтатуса(404)
        //     возврат
        // ;
        // Запрос.Ответ.УстановитьТело(СериализацияJson.ЗаписатьОбъект(Объект))
    поймать Исключение: Исключение
        ОбработатьОшибку(Запрос.Ответ, Исключение)
    ;"""
    else:
        body = f"""\
    попытка
        // TODO: реализовать {method}
    поймать Исключение: Исключение
        ОбработатьОшибку(Запрос.Ответ, Исключение)
    ;"""
    return f"метод {handler}(Запрос: HttpСервисЗапрос)\n{body}\n;"


_ERROR_HELPER = """\
метод ОбработатьОшибку(Ответ: HttpСервисОтвет, Исключение: Исключение)
    Ответ.УстановитьКодСтатуса(500)
    Ответ.Заголовки.Установить("Content-Type", "text/plain; charset=utf-8")
    Ответ.УстановитьТело(Исключение.Описание)
;"""


def _new_http_service(
    yaml_path: Path, name: str, access: str | None, routes: str, result: ScaffoldResult
) -> ScaffoldResult:
    templates = parse_routes(routes)
    used: set[str] = set()
    assigned = [
        (path, [(m, assign_handler(m, path, used)) for m in methods])
        for path, methods in templates
    ]
    lines = [
        "ВидЭлемента: HttpСервис",
        f"Ид: {new_uuid()}",
        f"Имя: {name}",
        "ОбластьВидимости: ВПодсистеме",
        f"КорневойUrl: /{name}",
    ]
    if access:
        lines += ["КонтрольДоступа:", "    Разрешения:", f"        Вызов: {access}"]
    lines.append("ШаблоныUrl:")
    for path, method_handlers in assigned:
        lines.append("    -")
        lines += [f"        {line}" for line in _template_lines(path, method_handlers)]
    blocks = [
        _handler_stub(m, path, handler)
        for path, method_handlers in assigned
        for m, handler in method_handlers
    ]
    blocks.append(_ERROR_HELPER)
    result.changes.append(FileChange(yaml_path, "\n".join(lines) + "\n", created=True))
    result.changes.append(
        FileChange(yaml_path.with_suffix(".xbsl"), "\n\n".join(blocks) + "\n", created=True)
    )
    return result


def op_add_route(yaml_path: Path, routes: str, *, reader=None) -> ScaffoldResult:
    """Добавить маршруты в существующий HttpСервис: ШаблоныUrl в yaml + заготовки в xbsl.

    Существующий шаблон пополняется недостающими методами; полностью существующие
    маршруты пропускаются с пометкой в notes.
    """
    yaml_path = Path(yaml_path)
    text, nl = _load_for_edit(yaml_path, reader)
    kind_m = _KIND_RE.search(text)
    if kind_m is None or kind_m.group(1) != "HttpСервис":
        raise ScaffoldError(f"{yaml_path.name} – не HttpСервис")
    module_path = yaml_path.with_suffix(".xbsl")
    module_text = (reader or _read)(module_path) if module_path.is_file() else ""
    module_nl = _dominant_nl(module_text)

    # Занятые имена обработчиков: объявленные в модуле и упомянутые в yaml.
    declared = set(re.findall(r"^метод\s+([A-Za-zА-Яа-яЁё0-9_]+)", module_text, re.M))
    used = set(declared) | set(re.findall(r"Обработчик:\s*(\S+)", text))

    result = ScaffoldResult()
    added: list[tuple[str, str, str]] = []  # (метод, шаблон, обработчик)
    for path, methods in parse_routes(routes):
        template = next(
            (i for i in section_items(text, "ШаблоныUrl") if i.get("Шаблон") == path), None
        )
        if template is not None:
            offset = find_section_item_offset(text, "ШаблоныUrl", template.get("Имя", ""))
            if offset is None:
                raise ScaffoldError(f"Не удалось найти блок шаблона '{path}' в {yaml_path.name}")
            known = set(re.findall(r"Метод:\s*(\S+)", _block_at(text, offset)))
            for method in methods:
                if method in known:
                    result.notes.append(f"Маршрут {method} {path} уже есть – пропущен")
                    continue
                handler = assign_handler(method, path, used)
                edit = insert_nested_item_edit(
                    text, offset, "Методы", [f"Метод: {method}", f"Обработчик: {handler}"], nl
                )
                text = apply_edit(text, edit)
                added.append((method, path, handler))
        else:
            method_handlers = [(m, assign_handler(m, path, used)) for m in methods]
            edit = insert_item_edit(text, "ШаблоныUrl", _template_lines(path, method_handlers), nl)
            text = apply_edit(text, edit)
            added += [(m, path, handler) for m, handler in method_handlers]

    if not added and not result.notes:
        result.notes.append("Новых маршрутов нет")
    result.changes.append(FileChange(yaml_path, text, created=False))

    stubs = [_handler_stub(m, path, handler) for m, path, handler in added]
    if stubs:
        if "ОбработатьОшибку" not in declared:
            stubs.append(_ERROR_HELPER)
        if module_text.strip():
            new_module = module_text.rstrip("\r\n") + "\n\n" + "\n\n".join(stubs) + "\n"
        else:
            new_module = "\n\n".join(stubs) + "\n"
        if module_nl != "\n":
            new_module = re.sub(r"(?<!\r)\n", module_nl, new_module)
        result.changes.append(FileChange(module_path, new_module, created=not module_path.is_file()))
    return result


def _block_at(text: str, offset: int | None) -> str:
    if offset is None:
        return ""
    line_start = text.rfind("\n", 0, offset - 1) + 1
    field_indent = offset - line_start
    end = len(text)
    pos = _line_end(text, offset)
    while pos < len(text):
        ls = pos + 1
        le = _line_end(text, ls)
        line = text[ls:le]
        if line.strip() != "" and len(_LINE_INDENT.match(line).group(0)) < field_indent:
            end = ls
            break
        pos = le
    return text[offset:end]


# --- операции: отчёт --------------------------------------------------------------------


def _new_report(yaml_path: Path, name: str, report: dict, result: ScaffoldResult) -> ScaffoldResult:
    """Отчёт с ВидИсточникаДанных: Таблица и сводным макетом по заданным полям."""
    source = report.get("source")
    if not source:
        raise ScaffoldError(
            "Отчёту нужен источник: report={source: <Таблица>, rows: [...], columns: [...], measures: [...]}"
        )
    rows = report.get("rows") or []
    columns = report.get("columns") or []
    measures = report.get("measures") or []
    if not rows or not measures:
        raise ScaffoldError("Отчёту нужны хотя бы одно измерение в rows и одна мера в measures")
    lines = [
        "ВидЭлемента: Отчет",
        f"Ид: {new_uuid()}",
        f"Имя: {name}",
        "ОбластьВидимости: ВПодсистеме",
        f"Представление: {report.get('title') or name}",
    ]
    if report.get("import_subsystem"):
        lines += ["Импорт:", f"    - {report['import_subsystem']}"]
    lines += [
        "ВидИсточникаДанных: Таблица",
        f"ИсточникДанных: {source}",
        "Макет:",
        "    ВидОтображения: СводнаяТаблица",
        "    Поля:",
    ]

    def dim(expr: str, role: str, total: bool = False) -> list[str]:
        roles = [f"                - {role}"] + (["                - Итог"] if total else [])
        return [
            "        -",
            "            Вид: Измерение",
            "            ВизуальныеРоли:",
            *roles,
            f"            Выражение: {expr}",
            f"            Ид: {_uuid.uuid4().hex}",
            "            Использовать: Истина",
        ]

    for expr in rows:
        lines += dim(expr, "Строки")
    for expr in columns:
        lines += dim(expr, "Колонки", total=True)
    for measure in measures:
        expr = measure["expr"] if isinstance(measure, dict) else str(measure)
        title = measure.get("title") if isinstance(measure, dict) else None
        if "(" not in expr:
            expr = f"СУММА({expr})"
        lines += [
            "        -",
            "            Вид: Мера",
            "            ВизуальныеРоли:",
            "                - ЗначенияКолонок",
            f"            Выражение: {expr}",
            f"            Ид: {_uuid.uuid4().hex}",
            "            Использовать: Истина",
        ]
        if title:
            lines.append(f"            Представление: {title}")
    result.changes.append(FileChange(yaml_path, "\n".join(lines) + "\n", created=True))
    return result


# --- операции: формы --------------------------------------------------------------------


def _form_field_component(name: str, type_: str, indent: str) -> list[str]:
    """Компонент редактирования по типу реквизита (маппинг из спецификации форм)."""
    if type_ == "Булево":
        return [f"{indent}-", f"{indent}    Тип: Флажок", f"{indent}    Имя: {name}",
                f"{indent}    Значение: =Объект.{name}"]
    component_type = type_ or "Строка"
    if component_type not in PRIMITIVE_TYPES and not component_type.endswith("?"):
        component_type += "?"  # ссылка/перечисление в поле ввода – всегда nullable
    lines = [
        f"{indent}-",
        f"{indent}    Тип: ПолеВвода<{component_type}>",
        f"{indent}    Имя: {name}",
        f"{indent}    Значение: =Объект.{name}",
    ]
    if type_ in ("Строка", "") and name in ("Описание", "Комментарий"):
        lines += [f"{indent}    НастройкиВводаСтроки:", f"{indent}        Многострочная: Истина"]
    return lines


def _form_fields(info: dict) -> list[dict]:
    fields = list(info["fields"])
    if info["is_hierarchical"]:
        # Системный реквизит иерархии: в yaml объекта его нет, в форме он нужен.
        obj = info["name"]
        after = 1 if fields and fields[0]["name"] == "Наименование" else 0
        fields.insert(after, {"name": "Родитель", "type": f"{obj}.Ссылка?"})
    return fields


def _tabular_table_lines(obj: str, tc_name: str, indent: str, panels: bool) -> list[str]:
    lines = [
        f"{indent}Тип: Таблица<ИсточникДанныхМассив<{obj}.{tc_name}>>",
        f"{indent}Имя: {tc_name}",
    ]
    if panels:
        lines += [
            f"{indent}ВидОтображенияКомандСтроки: ПриНаведении",
            f"{indent}ОтображатьНумерациюСтрок: Ложь",
            f"{indent}РастягиватьПоВертикали: Ложь",
            f"{indent}ШиринаВКолонках: Четверная",
        ]
    lines += [
        f"{indent}Источник:",
        f"{indent}    Данные: =Объект.{tc_name}",
        f"{indent}Команды:",
        f"{indent}    Тип: ФрагментКомандногоИнтерфейса",
        f"{indent}    Элементы:",
        f"{indent}        - =Компоненты.{tc_name}.ДобавитьСтроку",
        f"{indent}КомандыСтроки:",
        f"{indent}    Тип: ФрагментКомандногоИнтерфейса<КомандаСПараметром<{obj}.{tc_name}>>",
        f"{indent}    Элементы:",
        f"{indent}        - =Компоненты.{tc_name}.Удалить",
    ]
    return lines


def object_form_yaml(info: dict, uid: str) -> str:
    """ФормаОбъекта по сводке объекта: simple / panels / tabs по числу ТЧ и реквизитов."""
    obj = info["name"]
    fields = _form_fields(info)
    tabulars = info["tabulars"]
    layout = info["suggested_layout"]
    lines = [
        "ВидЭлемента: КомпонентИнтерфейса",
        f"Ид: {uid}",
        f"Имя: {obj}ФормаОбъекта",
        "ОбластьВидимости: ВПодсистеме",
        "Наследует:",
        f"    Тип: ФормаОбъекта<{obj}.Объект>",
        "    ВключатьВАвтоИнтерфейс: Ложь",
        f"    Заголовок: {obj}",
    ]
    if tabulars:
        lines.append("    РастягиватьПоВертикали: Истина")
    lines += [
        "    ДополнительныеКоманды:",
        "        Тип: ФрагментКомандногоИнтерфейса",
        "        Элементы:",
        "            - =Удалить",
        "            - =Восстановить",
        "    ОсновнаяКоманда: =ЗаписатьИЗакрыть",
        "    Содержимое:",
    ]
    if layout == "simple":
        lines += [
            "        Тип: ПроизвольныйШаблонФормы",
            "        ШиринаВКолонках: Одинарная",
            "        Содержимое:",
            "            Тип: Группа",
            "            Содержимое:",
        ]
        for f in fields:
            lines += _form_field_component(f["name"], f["type"], "                ")
        return "\n".join(lines) + "\n"

    section_type = "Группа" if layout == "panels" else "РазделФормы"
    lines += [
        "        Тип: ШаблонФормыСРазделами",
        "        РастягиватьПоВертикали: Истина",
        "        ОсновнойРаздел:",
        f"            Тип: {section_type}",
        "            Заголовок: Основное",
        "            ШиринаВКолонках: Одинарная",
        "            Содержимое:",
    ]
    for f in fields:
        lines += _form_field_component(f["name"], f["type"], "                ")
    lines.append("        ДополнительныеРазделы:")
    for tc in tabulars:
        tc_name = tc["name"]
        if layout == "panels":
            lines += [
                "            -",
                "                Тип: Группа",
                f"                Заголовок: {tc_name}",
                "                ШиринаВКолонках: Двойная",
                "                Содержимое:",
                "                    -",
                "                        Тип: СворачиваемыйКомпонент",
                f"                        Заголовок: {tc_name}",
                "                        РастягиватьПоГоризонтали: Истина",
                "                        ШиринаВКолонках: Четверная",
                "                        Содержимое:",
            ] + _tabular_table_lines(obj, tc_name, " " * 28, panels=True)
        else:
            lines += [
                "            -",
                "                Тип: РазделФормы",
                f"                Заголовок: {tc_name}",
                "                Содержимое:",
                "                    -",
                "                        Содержимое:",
            ] + [" " * 28 + "-"] + _tabular_table_lines(obj, tc_name, " " * 32, panels=False)
    return "\n".join(lines) + "\n"


def _list_sort_field(info: dict, fields: list[str]) -> str | None:
    """Поле сортировки списка по умолчанию: у документа – Дата, иначе Наименование."""
    if info["kind"] == "Документ" and "Дата" in fields:
        return "Дата"
    return "Наименование" if "Наименование" in fields else None


def list_form_yaml(info: dict, uid: str) -> str:
    """ФормаСписка по сводке объекта: динамический список, колонки по полям, иерархия."""
    obj = info["name"]
    ns = info["namespace"]
    row_type = f"{ns}::{obj}ФормаСписка.ДанныеСтрокиСписка"
    hierarchical = info["is_hierarchical"]
    extra_hierarchies = info["additional_hierarchies"]
    list_type = (
        f"ДинамическийСписок<{row_type}, {row_type}>"
        if hierarchical
        else f"ДинамическийСписок<{row_type}>"
    )
    fields = [f["name"] for f in info["fields"]]
    list_fields = list(fields)
    if hierarchical and "Родитель" not in list_fields:
        list_fields.insert(0, "Родитель")

    lines = [
        "ВидЭлемента: КомпонентИнтерфейса",
        f"Ид: {uid}",
        f"Имя: {obj}ФормаСписка",
        "ОбластьВидимости: ВПодсистеме",
        "Наследует:",
        "    Тип: ФормаСписка",
        "    ВключатьВАвтоИнтерфейс: Ложь",
        f"    Заголовок: {obj}",
        "    ДополнительныеКоманды:",
        "        Тип: ФрагментКомандногоИнтерфейса",
        "        Элементы:",
        "            - =Обновить",
        "    КомандыСоздания: =Компоненты.ОсновнаяТаблица.ДобавитьСтроку",
        "    КомпонентТаблицы: =Компоненты.ОсновнаяТаблица",
        "    Содержимое:",
        "        Тип: ПроизвольныйШаблонФормы",
        "        Содержимое:",
        f"            Тип: Таблица<{list_type}>",
        "            Имя: ОсновнаяТаблица",
        "            Источник: =Список",
    ]
    if hierarchical:
        lines.append("            НачальныйУровеньРазворачивания: -1")
    lines.append("            Колонки:")
    for name in fields:
        lines += [
            "                -",
            f"                    Тип: СтандартнаяКолонкаТаблицы<СтрокаДинамическогоСписка<{row_type}>>",
            f"                    Имя: {name}",
            f"                    Значение: =ДанныеСтроки.Данные.{name}",
        ]
    lines += [
        "            КомандыСтроки:",
        f"                Тип: ФрагментКомандногоИнтерфейса<КомандаСПараметром<СтрокаДинамическогоСписка<{row_type}>>>",
        "                Элементы:",
        "                    - =Компоненты.ОсновнаяТаблица.СоздатьКопию",
        "Свойства:",
        "    -",
        "        Имя: Список",
        f"        Тип: {list_type}",
        "        ЗначениеПоУмолчанию:",
        "            ИмяТипаДанныхСтроки: ДанныеСтрокиСписка",
    ]
    if hierarchical:
        lines += [
            "            ИспользуемаяИерархия:",
            "                Тип: Строка",
            "                Значение: Иерархия",
        ]
    elif extra_hierarchies:
        lines += [
            "            ИспользуемаяИерархия:",
            "                Тип: Строка",
            f"                Значение: {extra_hierarchies[0]['name']}",
        ]
    lines += [
        "            ОсновнаяТаблица:",
        f"                Таблица: {obj}",
        "            Поля:",
    ]
    for name in list_fields:
        lines += [
            "                -",
            "                    Тип: ПолеДинамическогоСписка",
            f"                    Выражение: {name}",
        ]
    sort_field = _list_sort_field(info, fields)
    if sort_field:
        lines += [
            "            Сортировка:",
            "                -",
            f"                    Поле: {sort_field}",
            "                    НаправлениеСортировки: ПоВозрастанию",
        ]
    return "\n".join(lines) + "\n"


# --- карточная форма списка --------------------------------------------------------------
#
# Форма списка карточками: ПроизвольныйСписок выводит каждую запись отдельным компонентом
# (ТипКомпонентаСтроки), а КонтейнерСтрок с матричной компоновкой раскладывает карточки
# сеткой. Формы две: сама форма и компонент строки СтрокаСписка<Объект>.
# Соответствие документации 9.2: ПроизвольныйСписок.ТипКомпонентаСтроки /
# .КонтейнерСтрок, НастройкиМатричнойКомпоновки.ОписаниеАвтоматических{Колонок,Строк},
# АвтоЗаполнениеМатричнойГруппы.ДобавлятьКолонкиИСтроки (требует определённого размера
# колонок – поэтому у автоколонок задана МинимальнаяШирина), ФормаСписка.КомпонентТаблицы
# принимает любой Компонент.

CARD_ROW_PREFIX = "СтрокаСписка"
_CARD_MIN_WIDTH = 400  # ширина колонки сетки; с фото карточка уже – см. _card_min_width
_CARD_MIN_WIDTH_PHOTO = 250
_CARD_CONTENT_LIMIT = 3  # больше трёх полей карточка не читается; остальное – вручную

# Типы, чьё значение годится прямо в Строку (СтандартнаяКарточка.Содержимое: Компонент|Строка).
_CARD_DATE_FORMATS = {
    "Дата": "дд ММММ гггг",
    "ДатаВремя": "дд ММММ гггг ЧЧ:мм",
    "Время": "ЧЧ:мм",
}


def _is_photo_type(type_: str) -> bool:
    return type_.replace(" ", "").startswith("ДвоичныйОбъект.Ссылка")


def _card_roles(fields: list[dict]) -> dict:
    """Роли полей карточки: {title, photo, content} – заголовок, фото, вторичные поля.

    Заголовок – Наименование, иначе первое строковое поле, иначе первое поле. Фото – первый
    реквизит ДвоичныйОбъект.Ссылка. Содержимое – следующие поля, не более _CARD_CONTENT_LIMIT.
    """
    photo = next((f for f in fields if _is_photo_type(f["type"])), None)
    rest = [f for f in fields if f is not photo]
    title = (
        next((f for f in rest if f["name"] == "Наименование"), None)
        or next((f for f in rest if f["type"] in ("Строка", "")), None)
        or (rest[0] if rest else None)
    )
    content = [f for f in rest if f is not title][:_CARD_CONTENT_LIMIT]
    return {"title": title, "photo": photo, "content": content}


def _card_fields(roles: dict) -> list[dict]:
    """Поля, которые карточка реально показывает, в порядке заголовок – фото – содержимое."""
    ordered = [roles["title"], roles["photo"], *roles["content"]]
    return [f for f in ordered if f is not None]


def _card_value(field: dict) -> str:
    """Биндинг значения поля строки; дата/время – через Представление(Формат)."""
    expr = f"=ДанныеСтроки.Данные.{field['name']}"
    fmt = _CARD_DATE_FORMATS.get(field["type"])
    return f'{expr}.Представление("{fmt}")' if fmt else expr


def _card_is_text(field: dict) -> bool:
    """Годится ли значение прямо в строковое свойство (Заголовок/Содержимое карточки)."""
    return field["type"] in ("Строка", "") or field["type"] in _CARD_DATE_FORMATS


def _card_label(field: dict, indent: str) -> list[str]:
    return [f"{indent}Тип: Надпись", f"{indent}Значение: {_card_value(field)}"]


def _card_content_lines(content: list[dict], indent: str) -> list[str]:
    """Строки свойства Содержимое карточки: строка, одна Надпись или Группа надписей.

    Нетекстовые значения (ссылки, перечисления, числа) в строковое свойство не годятся –
    их выводит Надпись.
    """
    if not content:
        return []
    if len(content) == 1 and _card_is_text(content[0]):
        return [f"{indent}Содержимое: {_card_value(content[0])}"]
    if len(content) == 1:
        return [f"{indent}Содержимое:"] + _card_label(content[0], indent + "    ")
    lines = [
        f"{indent}Содержимое:",
        f"{indent}    Тип: Группа",
        f"{indent}    Компоновка: Вертикальная",
        f"{indent}    Содержимое:",
    ]
    for field in content:
        lines.append(f"{indent}        -")
        lines += _card_label(field, indent + "            ")
    return lines


def _card_min_width(roles: dict, min_width: int | None) -> int:
    if min_width:
        return min_width
    return _CARD_MIN_WIDTH_PHOTO if roles["photo"] else _CARD_MIN_WIDTH


def card_row_yaml(info: dict, uid: str, *, placeholder: str | None = None) -> str:
    """Компонент строки карточного списка: СтандартнаяКарточка, с фото – ПроизвольнаяКарточка.

    placeholder – выражение картинки-заглушки (напр. "Ресурс{Аккаунт.svg}.Ссылка"); без него
    пустое фото просто не отображается (Картинка.Изображение допускает Неопределено).
    """
    obj = info["name"]
    row_type = f'{info["namespace"]}::{obj}ФормаСписка.ДанныеСтрокиСписка'
    roles = _card_roles(info["fields"])
    title, photo = roles["title"], roles["photo"]
    lines = [
        "ВидЭлемента: КомпонентИнтерфейса",
        f"Ид: {uid}",
        f"Имя: {CARD_ROW_PREFIX}{obj}",
        "ОбластьВидимости: ВПодсистеме",
        "Наследует:",
        f"    Тип: ПроизвольнаяСтрокаСписка<СтрокаДинамическогоСписка<{row_type}>>",
        "    Содержимое:",
    ]
    if photo is None:
        lines += [
            "        Тип: СтандартнаяКарточка",
            "        РастягиватьПоВертикали: Истина",
            "        РастягиватьПоГоризонтали: Истина",
        ]
        if title is not None:
            heading = _card_value(title) if _card_is_text(title) else f"=ДанныеСтроки.Данные.{title['name']}.ВСтроку()"
            lines.append(f"        Заголовок: {heading}")
        lines += _card_content_lines(roles["content"], "        ")
        return "\n".join(lines) + "\n"

    # С фото – произвольная карточка: у стандартной картинка идёт в заголовок, а нужен
    # вертикальный стек "фото над подписью" (Группа по умолчанию горизонтальная).
    image = _card_value(photo)
    if placeholder:
        image = f"{image} ?? {placeholder}"
    lines += [
        "        Тип: ПроизвольнаяКарточка",
        "        РастягиватьПоВертикали: Истина",
        "        РастягиватьПоГоризонтали: Истина",
        "        Содержимое:",
        "            Тип: Группа",
        "            Компоновка: Вертикальная",
        "            РастягиватьПоГоризонтали: Истина",
        "            Содержимое:",
        "                -",
        "                    Тип: Картинка",
        "                    Высота: 200",
        "                    РастягиватьПоВертикали: Ложь",
        "                    РастягиватьПоГоризонтали: Истина",
        "                    Масштабирование: Пропорционально",
        f"                    Изображение: {image}",
    ]
    for field in ([title] if title is not None else []) + roles["content"]:
        lines += [
            "                -",
            "                    Тип: Надпись",
            "                    РастягиватьПоГоризонтали: Истина",
            f"                    Значение: {_card_value(field)}",
        ]
    return "\n".join(lines) + "\n"


def cards_list_form_yaml(info: dict, uid: str, *, min_width: int | None = None) -> str:
    """ФормаСписка карточками: ПроизвольныйСписок + матричный КонтейнерСтрок.

    От list_form_yaml отличается только компонентом: вместо Таблицы с колонками – список,
    рисующий каждую запись компонентом CARD_ROW_PREFIX+Объект. Поля динамического списка –
    Ссылка (нужна навигации) и те, что показывает карточка.
    """
    obj = info["name"]
    row_type = f'{info["namespace"]}::{obj}ФормаСписка.ДанныеСтрокиСписка'
    list_type = f"ДинамическийСписок<{row_type}>"
    roles = _card_roles(info["fields"])
    shown = [f["name"] for f in _card_fields(roles)]
    width = _card_min_width(roles, min_width)
    lines = [
        "ВидЭлемента: КомпонентИнтерфейса",
        f"Ид: {uid}",
        f"Имя: {obj}ФормаСписка",
        "ОбластьВидимости: ВПодсистеме",
        "Наследует:",
        "    Тип: ФормаСписка",
        "    ВключатьВАвтоИнтерфейс: Ложь",
        f"    Заголовок: {obj}",
        "    ДополнительныеКоманды:",
        "        Тип: ФрагментКомандногоИнтерфейса",
        "        Элементы:",
        "            - =Обновить",
        "    КомандыСоздания: =Компоненты.ОсновнаяТаблица.ДобавитьСтроку",
        "    КомпонентТаблицы: =Компоненты.ОсновнаяТаблица",
        "    Содержимое:",
        "        Тип: ПроизвольныйШаблонФормы",
        "        Содержимое:",
        f"            Тип: ПроизвольныйСписок<{list_type}>",
        "            Имя: ОсновнаяТаблица",
        "            Источник: =Список",
        "            ОбрабатыватьНажатие: Истина",
        f"            ТипКомпонентаСтроки: {CARD_ROW_PREFIX}{obj}",
        "            РастягиватьПоГоризонтали: Истина",
        "            РастягиватьПоВертикали: Истина",
        "            КонтейнерСтрок:",
        "                Тип: Группа",
        "                Имя: СеткаКарточек",
        "                Компоновка: Матричная",
        "                РастягиватьПоГоризонтали: Истина",
        "                НастройкиМатричнойКомпоновки:",
        "                    АвтоЗаполнение: ДобавлятьКолонкиИСтроки",
        "                    ОписаниеАвтоматическихКолонок:",
        f"                        МинимальнаяШирина: {width}",
        "                        РастягиватьПоГоризонтали: Истина",
        "                    ОписаниеАвтоматическихСтрок:",
        "                        РастягиватьПоВертикали: Истина",
        "Свойства:",
        "    -",
        "        Имя: Список",
        f"        Тип: {list_type}",
        "        ЗначениеПоУмолчанию:",
        "            ИмяТипаДанныхСтроки: ДанныеСтрокиСписка",
        "            ОсновнаяТаблица:",
        f"                Таблица: {obj}",
        "            Поля:",
    ]
    for name in ["Ссылка"] + shown:
        lines += [
            "                -",
            "                    Тип: ПолеДинамическогоСписка",
            f"                    Выражение: {name}",
        ]
    sort_field = _list_sort_field(info, shown)
    if sort_field:
        lines += [
            "            Сортировка:",
            "                -",
            f"                    Поле: {sort_field}",
            "                    НаправлениеСортировки: ПоВозрастанию",
        ]
    return "\n".join(lines) + "\n"


def report_form_yaml(info: dict, uid: str) -> str:
    """ФормаОтчета: поля параметров отчёта + компонент ПросмотрОтчета."""
    obj = info["name"]
    params = info["report_params"]
    lines = [
        "ВидЭлемента: КомпонентИнтерфейса",
        f"Ид: {uid}",
        f"Имя: {obj}ФормаОтчета",
        "ОбластьВидимости: ВПодсистеме",
        "Наследует:",
        "    Тип: ФормаОтчета",
        "    ВключатьВАвтоИнтерфейс: Ложь",
        "    Заголовок: =Отчет.Представление",
        "    Содержимое:",
        "        Тип: ПроизвольныйШаблонФормы",
        "        Содержимое:",
    ]
    viewer = [
        "Тип: ПросмотрОтчета",
        "Имя: ПросмотрОтчета",
        "Отчет: =Отчет",
        "РастягиватьПоВертикали: Истина",
        "РастягиватьПоГоризонтали: Истина",
        "ТолькоЧтение: Истина",
    ]
    if params:
        lines += [
            "            Тип: Группа",
            "            Компоновка: Вертикальная",
            "            Содержимое:",
            "                -",
            "                    Тип: Группа",
            "                    Содержимое:",
        ]
        for p in params:
            ptype = p["type"] or "Строка"
            lines += [
                "                        -",
                f"                            Тип: ПолеВвода<{ptype}>",
                f"                            Заголовок: {p['name']}",
                f"                            Значение: =Отчет.Параметры.{p['name']}",
            ]
        lines += ["                -"] + [f"                    {line}" for line in viewer]
    else:
        lines += [f"            {line}" for line in viewer]
    lines += [
        "Свойства:",
        "    -",
        "        Имя: Отчет",
        f"        Тип: {obj}",
        "        ЗначениеПоУмолчанию:",
        f"            Тип: {obj}",
    ]
    return "\n".join(lines) + "\n"


def _interface_block(kind: str, obj: str, forms: list[str]) -> list[str]:
    lines = ["Интерфейс:", "    ВключатьВАвтоИнтерфейс: Истина"]
    if kind == "Отчет":
        return lines + [f"    Форма: {obj}ФормаОтчета"]
    if kind == "Справочник":
        lines.append("    ИспользоватьСозданиеПриВводе: Истина")
    if "object" in forms:
        lines += ["    Объект:", f"        Форма: {obj}ФормаОбъекта"]
    if "list" in forms:
        lines += ["    Список:", f"        Форма: {obj}ФормаСписка"]
    return lines


def _register_forms(text: str, nl: str, kind: str, obj: str, forms: list[str], result: ScaffoldResult) -> str:
    """Регистрация форм в yaml объекта: вставка секции Интерфейс или дополнение существующей."""
    if not re.search(r"^Интерфейс:", text, re.M):
        block = _interface_block(kind, obj, forms)
        anchor = None
        for key in ("ОбластьВидимости", "Имя", "Ид"):
            m = re.search(rf"^{key}:.*\r?$", text, re.M)
            if m:
                anchor = _line_end(text, m.start())
                break
        rendered = nl.join(block)
        if anchor is None:
            tail = "" if text.endswith("\n") else nl
            return text + f"{tail}{rendered}{nl}"
        return text[:anchor] + f"{nl}{rendered}" + text[anchor:]

    # Секция есть – дописываем недостающие регистрации в её конец, существующие не трогаем.
    for form, subsection in (("object", "Объект"), ("list", "Список")):
        if form not in forms:
            continue
        form_name = f"{obj}Форма{'Объекта' if form == 'object' else 'Списка'}"
        if re.search(rf"Форма:\s*{form_name}\b", text):
            result.notes.append(f"{form_name} уже зарегистрирована в Интерфейс")
            continue
        span = top_level_key_span(text, "Интерфейс")
        body = text[span[0]: span[1]]
        if kind == "Отчет":
            if re.search(r"^\s{4}Форма:", body, re.M):
                result.notes.append("В Интерфейс уже указана Форма – регистрация вручную")
                continue
            text = text[: span[1]] + f"{nl}    Форма: {form_name}" + text[span[1]:]
            continue
        sub = re.search(rf"^    {subsection}:[ \t]*\r?$", body, re.M)
        if sub is None:
            text = text[: span[1]] + f"{nl}    {subsection}:{nl}        Форма: {form_name}" + text[span[1]:]
        else:
            result.notes.append(
                f"В Интерфейс уже есть подсекция {subsection} – зарегистрируйте {form_name} вручную"
            )
    return text


FORM_KINDS = ("object", "list", "list-cards", "report")


def op_add_form(root: Path, name: str | None = None, yaml_path: Path | None = None,
                forms: list[str] | None = None, overwrite: bool = False,
                card_min_width: int | None = None, card_placeholder: str | None = None,
                reader=None) -> ScaffoldResult:
    """Создать формы объекта с наполнением по его реквизитам и зарегистрировать в Интерфейс.

    forms – подмножество FORM_KINDS; по умолчанию object+list для объектов данных и report
    для Отчет. "list-cards" – та же форма списка, но карточками (ПроизвольныйСписок с
    матричной сеткой); она несовместима с "list" (обе – файл <Объект>ФормаСписка.yaml) и
    создаёт второй файл – компонент строки СтрокаСписка<Объект>. card_min_width задаёт
    ширину колонки сетки (по умолчанию 400, с фото – 250), card_placeholder – выражение
    картинки-заглушки. Существующая форма не перезаписывается без overwrite – вместо этого
    пометка в notes.
    """
    info = object_info(Path(root), name=name, yaml_path=yaml_path)
    kind = info["kind"]
    obj = info["name"]
    owner_path = Path(info["path"])
    if forms is None:
        forms = ["report"] if kind == "Отчет" else ["object", "list"]
    unknown = [f for f in forms if f not in FORM_KINDS]
    if unknown:
        raise ScaffoldError(
            f"Неизвестный вид формы: {', '.join(unknown)}; доступны: {', '.join(FORM_KINDS)}"
        )
    if "list" in forms and "list-cards" in forms:
        raise ScaffoldError(
            "list и list-cards – одна и та же форма списка (<Объект>ФормаСписка): выберите одну"
        )
    if kind == "Отчет" and forms != ["report"]:
        raise ScaffoldError("Для отчёта доступна только форма отчёта: forms=[\"report\"]")
    if kind != "Отчет" and "report" in forms:
        raise ScaffoldError(f"Форма отчёта неприменима к виду {kind}")

    result = ScaffoldResult()
    generators = {
        "object": ("ФормаОбъекта", object_form_yaml),
        "list": ("ФормаСписка", list_form_yaml),
        "list-cards": ("ФормаСписка", lambda i, uid: cards_list_form_yaml(i, uid, min_width=card_min_width)),
        "report": ("ФормаОтчета", report_form_yaml),
    }
    made: list[str] = []
    for form in forms:
        suffix, generator = generators[form]
        form_path = owner_path.parent / f"{obj}{suffix}.yaml"
        if form_path.exists() and not overwrite:
            result.notes.append(f"{form_path.name} уже существует – пропущена (overwrite=true перезапишет)")
            continue
        result.changes.append(
            FileChange(form_path, generator(info, new_uuid()), created=not form_path.exists())
        )
        made.append(form)
        if form == "list-cards":
            _add_card_row(info, owner_path, overwrite, card_placeholder, result)
    if made:
        text, nl = _load_for_edit(owner_path, reader)
        # Карточная форма списка регистрируется как обычная: тот же файл <Объект>ФормаСписка.
        registered = ["list" if f == "list-cards" else f for f in made]
        new_text = _register_forms(text, nl, kind, obj, registered, result)
        if new_text != text:
            result.changes.append(FileChange(owner_path, new_text, created=False))
    return result


def _add_card_row(info: dict, owner_path: Path, overwrite: bool, placeholder: str | None,
                  result: ScaffoldResult) -> None:
    """Компонент строки карточного списка + пометки о том, что попало в карточку."""
    obj = info["name"]
    row_path = owner_path.parent / f"{CARD_ROW_PREFIX}{obj}.yaml"
    if row_path.exists() and not overwrite:
        result.notes.append(
            f"{row_path.name} уже существует – пропущен (overwrite=true перезапишет)"
        )
    else:
        result.changes.append(
            FileChange(row_path, card_row_yaml(info, new_uuid(), placeholder=placeholder),
                       created=not row_path.exists())
        )
    roles = _card_roles(info["fields"])
    shown = [f["name"] for f in _card_fields(roles)]
    result.notes.append(
        "В карточку вынесены поля: " + (", ".join(shown) if shown else "нет реквизитов")
    )
    hidden = [f["name"] for f in info["fields"] if f["name"] not in shown]
    if hidden:
        result.notes.append(
            "Не попали в карточку: " + ", ".join(hidden)
            + " – добавьте вручную в " + row_path.name + " и в Поля списка"
        )
    if info["is_hierarchical"]:
        result.notes.append(
            "Объект иерархический, но карточная сетка выводит плоский список – "
            "иерархия в форме не используется"
        )


# --- операция: переименование объекта ----------------------------------------------------
#
# Переименование текстовое и контекстное, без полного индекса: имя заменяется только там,
# где оно ссылается на объект (значения ссылочных ключей yaml, корни цепочек в биндингах
# и коде, составные имена форм), а совпадающие имена реквизитов, компонентов и полей
# динамических списков не трогаются. Строковые литералы .xbsl не правятся (UI-текст),
# комментарии – правятся (упоминания объекта в документации кода).

_WORD = "A-Za-zА-Яа-яЁё0-9_"

# Ключи yaml, в значениях которых имя объекта – ссылка на объект или форму.
_YAML_REF_KEYS = ("Тип", "Таблица", "ИсточникДанных", "Форма", "ТипФормы")
_PRESENTATION_KEYS = ("Заголовок", "Представление")
_YAML_KEY_LINE = re.compile(rf"^([ \t]*(?:-[ \t]+)?)([{_WORD}]+):([ \t]*)(.*)$")
_IMPORT_LINE = re.compile(r"^[ \t]*импорт[ \t]+\S")


class _Renamer:
    """Замены имени объекта в тексте: идентификатор и составные имена его форм.

    Идентификатор заменяется только в корневой позиции (не после точки – там член чужого
    типа, не после `@` – там аннотация). Составное имя формы – `<Имя>Форма` с заглавной
    буквой после "Форма" (или ровно `<Имя>Форма`): строчная буква после "Форма" – чужое
    слово вида "Форматирование". Компонент строки карточного списка – `СтрокаСписка<Имя>`.
    """

    def __init__(self, old: str, new: str):
        self.old, self.new = old, new
        escaped = re.escape(old)
        self._ident = re.compile(rf"(?<![{_WORD}.@]){escaped}(?![{_WORD}])")
        self._composite = re.compile(
            rf"(?<![{_WORD}.]){escaped}(?=Форма(?:[А-ЯЁA-Z][{_WORD}]*)?(?![{_WORD}]))"
        )
        self._row = re.compile(rf"(?<![{_WORD}.])СтрокаСписка{escaped}(?![{_WORD}])")

    def identifier(self, s: str) -> tuple[str, int]:
        return self._ident.subn(self.new, s)

    def composites(self, s: str) -> tuple[str, int]:
        s, n1 = self._composite.subn(self.new, s)
        s, n2 = self._row.subn(f"СтрокаСписка{self.new}", s)
        return s, n1 + n2

    def file_base(self, base: str) -> str:
        """Новое имя владельца файла (часть до первой точки), если файл принадлежит объекту."""
        for sub in (self.composites, self.identifier):
            new_base, n = sub(base)
            if n:
                return new_base
        return base


def _split_strings(line: str) -> list[tuple[str, bool]]:
    """Сегменты строки кода: (текст, это_строковый_литерал). Кавычка в литерале удваивается."""
    parts: list[tuple[str, bool]] = []
    start = 0
    in_str = False
    i, n = 0, len(line)
    while i < n:
        if line[i] == '"':
            if in_str and i + 1 < n and line[i + 1] == '"':
                i += 2
                continue
            if in_str:
                parts.append((line[start : i + 1], True))
                start = i + 1
            else:
                parts.append((line[start:i], False))
                start = i
            in_str = not in_str
        i += 1
    parts.append((line[start:], in_str))
    return parts


def _rename_in_xbsl(text: str, renamer: _Renamer) -> tuple[str, int]:
    """Замены в модуле: идентификаторы и составные имена форм вне строковых литералов.

    Строка `импорт <Подсистема>` пропускается целиком – там имя подсистемы, не объекта.
    """
    total = 0
    out: list[str] = []
    for line in text.split("\n"):
        if _IMPORT_LINE.match(line):
            out.append(line)
            continue
        pieces: list[str] = []
        for segment, is_string in _split_strings(line):
            if not is_string:
                segment, n1 = renamer.composites(segment)
                segment, n2 = renamer.identifier(segment)
                total += n1 + n2
            pieces.append(segment)
        out.append("".join(pieces))
    return "\n".join(out), total


def _swap_presentation(value: str, old_values: set[str], new_value: str) -> tuple[str, bool]:
    """Заменить значение Заголовок/Представление с сохранением кавычек и хвостовых пробелов."""
    raw = value.rstrip()
    tail = value[len(raw):]
    quote = raw[:1] if raw[:1] in "\"'" and len(raw) >= 2 and raw.endswith(raw[:1]) else ""
    core = raw[1:-1] if quote else raw
    if core not in old_values:
        return value, False
    return f"{quote}{new_value}{quote}{tail}", True


def _rename_in_yaml(
    text: str,
    renamer: _Renamer,
    *,
    own: bool = False,
    presentations: tuple[set[str], str] | None = None,
) -> tuple[str, int]:
    """Замены в yaml: ссылочные ключи, биндинги (`=...`), составные имена форм.

    own – это yaml самого объекта или его формы: дополнительно правится верхнеуровневое
    `Имя:` и значения Заголовок/Представление, совпадающие со старым именем/представлением.
    """
    total = 0
    out: list[str] = []
    for line in text.split("\n"):
        line, n = renamer.composites(line)
        total += n
        m = _YAML_KEY_LINE.match(line)
        if m:
            prefix, key, sep, value = m.groups()
            if key in _YAML_REF_KEYS:
                value, n = renamer.identifier(value)
                total += n
                line = f"{prefix}{key}:{sep}{value}"
                out.append(line)
                continue
            if own and key == "Имя" and prefix == "" and value.strip() == renamer.old:
                out.append(f"{prefix}{key}:{sep}{value.replace(renamer.old, renamer.new)}")
                total += 1
                continue
            if own and presentations and key in _PRESENTATION_KEYS:
                value, swapped = _swap_presentation(value, *presentations)
                if swapped:
                    total += 1
                    out.append(f"{prefix}{key}:{sep}{value}")
                    continue
        eq = line.find("=")
        if eq != -1:
            replaced, n = renamer.identifier(line[eq:])
            if n:
                total += n
                line = line[:eq] + replaced
        out.append(line)
    return "\n".join(out), total


def op_rename_object(
    root: Path,
    old_name: str,
    new_name: str,
    *,
    new_presentation: str | None = None,
    old_presentation: str | None = None,
    yaml_path: Path | None = None,
    reader=None,
) -> ScaffoldResult:
    """Переименовать объект конфигурации и обновить ссылки на него по всем исходникам.

    Переименовываются файлы объекта (yaml, модули `<Имя>.xbsl` / `<Имя>.<Часть>.xbsl`),
    его форм (`<Имя>Форма*`) и компонента строки списка (`СтрокаСписка<Имя>`). В текстах
    правятся: значения ссылочных ключей yaml (Тип/Таблица/ИсточникДанных/Форма/ТипФормы),
    биндинги `=...`, код .xbsl (кроме строковых литералов) и составные имена форм; в yaml
    самого объекта и его форм – ещё `Имя:` и Заголовок/Представление (старое представление
    задаёт old_presentation, новое – new_presentation, по умолчанию новое имя).

    yaml_path разрешает неоднозначность, когда в проекте несколько объектов с именем
    old_name. Работает и для КомпонентИнтерфейса (переименование формы: обновляется
    `Форма:` у владельца).
    """
    root = Path(root)
    if not root.is_dir():
        raise ScaffoldError(f"Корень проекта не найден: {root}")
    old_name = _check_identifier(old_name, "объекта")
    new_name = _check_identifier(new_name, "объекта")
    if old_name == new_name:
        raise ScaffoldError("Старое и новое имена совпадают")

    if yaml_path is not None:
        yaml_path = Path(yaml_path)
        if not yaml_path.is_file():
            raise ScaffoldError(f"Файл не найден: {yaml_path}")
        text = (reader or _read)(yaml_path)
        kind_m = _KIND_RE.search(text)
        if kind_m is None:
            raise ScaffoldError(f"В {yaml_path} нет ВидЭлемента – это не объект конфигурации")
        file_name = (_NAME_RE.search(text) or [None, yaml_path.stem])[1]
        if file_name != old_name:
            raise ScaffoldError(f"В {yaml_path.name} объект называется '{file_name}', а не '{old_name}'")
        subsystem, namespace = _namespace_of(yaml_path, root)
        hit = ObjectHit(kind_m.group(1), file_name, yaml_path, subsystem, namespace, text)
    else:
        hit = find_object(root, old_name)

    namesakes = []
    for other_path, _kind, name, _text in _iter_objects(root):
        if name == new_name:
            raise ScaffoldError(f"Имя '{new_name}' уже занято: {other_path}")
        if name == old_name and other_path.resolve() != hit.path.resolve():
            namesakes.append(other_path)

    renamer = _Renamer(old_name, new_name)
    result = ScaffoldResult()
    if namesakes:
        listed = "; ".join(str(p) for p in namesakes)
        result.notes.append(
            f"В проекте остаются тёзки '{old_name}' ({listed}): ссылки по имени "
            "заменяются во всём проекте – проверьте затронутые файлы"
        )

    # Переименования файлов: владелец файла – часть имени до первой точки.
    directory = hit.path.parent
    for path in sorted(directory.iterdir()):
        if not path.is_file() or path.suffix not in (".yaml", ".xbsl"):
            continue
        base = path.name.split(".", 1)[0]
        new_base = renamer.file_base(base)
        if new_base == base:
            continue
        new_path = path.with_name(new_base + path.name[len(base):])
        if new_path.exists():
            raise ScaffoldError(f"Файл уже существует: {new_path}")
        result.renames.append(FileRename(path, new_path))
    renamed = {r.old_path.resolve(): r.new_path for r in result.renames}
    own_yaml = {
        r.old_path.resolve() for r in result.renames if r.old_path.suffix == ".yaml"
    }

    presentations = (
        {old_name} | ({old_presentation} if old_presentation else set()),
        new_presentation or new_name,
    )

    def rel(path: Path) -> str:
        try:
            return path.resolve().relative_to(root.resolve()).as_posix()
        except ValueError:
            return str(path)

    changed_files = 0
    total = 0
    for path in engine.find_sources(root, "*.yaml") + engine.find_sources(root, "*.xbsl"):
        text = (reader or _read)(path)
        if path.suffix == ".yaml":
            new_text, count = _rename_in_yaml(
                text, renamer,
                own=path.resolve() in own_yaml,
                presentations=presentations,
            )
        else:
            new_text, count = _rename_in_xbsl(text, renamer)
        if new_text == text:
            continue
        target = renamed.get(path.resolve(), path)
        result.changes.append(FileChange(target, new_text, created=False))
        result.notes.append(f"{rel(path)}: замен – {count}")
        changed_files += 1
        total += count

    if not result.renames and not result.changes:
        raise ScaffoldError(f"Ссылок на '{old_name}' не найдено – нечего переименовывать")
    result.notes.insert(0, f"Файлов переименовано: {len(result.renames)}, "
                           f"правок: {changed_files} файлов / {total} замен")
    if hit.kind == "HttpСервис" and re.search(r"^КорневойUrl:", hit.text, re.M):
        result.notes.append(
            "КорневойUrl не изменён (публичный контракт сервиса) – при необходимости поправьте вручную"
        )
    return result
