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

_WORD = "A-Za-zА-Яа-яЁё0-9_"  # класс символов идентификатора (для regex-границ слова)
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


def _section_bounds(text: str, section: str, top_level: bool = False) -> tuple[int, int, int] | None:
    """(отступ заголовка, конец строки заголовка, конец тела) секции или None.

    Конец тела – конец последней непустой строки с отступом больше отступа заголовка.
    top_level=True – искать только заголовок без отступа: иначе одноимённая ВЛОЖЕННАЯ секция
    (`Реквизиты` внутри табличной части) будет принята за секцию объекта. Вызовы по срезу
    блока (реквизиты ТЧ, Разрешения внутри КонтрольДоступа) ищут с любым отступом.
    """
    indent_pattern = "()" if top_level else "([ \t]*)"
    header = re.search(rf"^{indent_pattern}{re.escape(section)}:[ \t]*\r?$", text, re.M)
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


def insert_item_edit(text: str, section: str, item_lines: list[str], nl: str = "\n",
                     top_level: bool = False) -> TextEdit:
    """Точечная вставка нового элемента (набор строк-полей) в конец секции.

    Нет секции – дописывается в конец файла. top_level=True – только секция без отступа
    (иначе реквизит объекта уедет во вложенную секцию табличной части). Порт insertItemEdit
    из расширения VS Code (metadataCore.ts) с одним отличием: перевод строки задаётся
    параметром, чтобы правка не смешивала стили в CRLF-файлах.
    """

    def body(item: str, fld: str) -> str:
        return f"{item}-{nl}" + nl.join(f"{fld}{line}" for line in item_lines)

    bounds = _section_bounds(text, section, top_level)
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


def section_items(text: str, section: str, top_level: bool = False) -> list[dict[str, str]]:
    """Скалярные поля элементов секции (для проверок дублей и обзора).

    Элемент – блок за "-" на минимальном отступе тела секции; вложенные секции элемента
    (Реквизиты ТЧ, Методы шаблона) в словарь не попадают, их поля – глубже отступа полей.
    top_level=True – только секция объекта, без отступа (см. _section_bounds).
    """
    bounds = _section_bounds(text, section, top_level)
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


def find_section_item_offset(text: str, section: str, name: str,
                             top_level: bool = True) -> int | None:
    """Смещение первого ключа элемента секции с Имя == name (для вложенных вставок).

    Ищется в секции объекта (без отступа): вызывающие адресуют ТабличныеЧасти и ШаблоныUrl.
    """
    bounds = _section_bounds(text, section, top_level)
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
    # Умолчание видимости – платформенное: "Стандартно элемент виден только внутри своей
    # подсистемы (ВПодсистеме)... Если хочется использовать в других подсистемах – нужно
    # установить ВПроекте" (документация "Модульная разработка"). Инструмент не расширяет
    # видимость за разработчика: шире – явным параметром scope.
    scope: str = "ВПодсистеме"
    module: bool = False  # создавать парный файл модуля
    module_suffix: str = ".xbsl"  # у ВиртуальнаяТаблица парный файл – запрос .xbql
    module_stub: str = ""  # шаблон модуля ({name}); пусто – комментарий с именем
    extra: tuple[str, ...] = ()  # доп. строки шаблона (могут содержать {name})
    # Вид требует данных от вызывающего (Отчет – источник и макет): в меню "создать" его
    # предлагать нечем, поэтому в витрину без параметров (bare_kinds) он не попадает.
    needs_args: bool = False
    # Что осталось дописать руками: платформа этого не подставит, а генератор не выдумывает.
    note: str = ""


# Заготовки модулей: обработчик, без которого элемент этого вида бесполезен. Сигнатуры –
# дословно из документации (сверено с рабочим кодом там, где он есть).
_STUB_HANDLER = """\
@Обработчик
метод Обработчик()
    // TODO: действия команды
;
"""
_STUB_JOB = """\
@Обработчик
метод Обработчик()
    // TODO: логика запланированного задания
;
"""
_STUB_CLIENT_PARAMS = """\
@Обработчик
метод ВычислитьПараметрыРаботыКлиента()
    // TODO: вычислить значения параметров (выполняется на сервере при открытии приложения)
;
"""
# Право на действие: имя элемента подставляется в параметры-обобщения; КлючДоступа.Объект –
# литеральный базовый тип ключей (подтверждено рабочим ПравоМодератора.xbsl).
_STUB_ACTION_PRIVILEGE = """\
@Обработчик
метод ВычислитьРазрешенияДоступа(Права: ЧитаемыйМассив<{name}.Объект>):
        ЧитаемоеСоответствие<{name}.Объект, ЧитаемаяКоллекция<КлючДоступа.Объект>>
    // TODO: вернуть соответствие "экземпляр права -> ключи доступа, которым оно выдано"
    возврат {{:}}
;
"""
_STUB_SELF_REGISTRATION = """\
@Обработчик
метод ПослеПодключения()
    // TODO: действия после подключения пользователя (выполняется на сервере)
;
"""
_STUB_SERVICE_CONTRACT = """\
// Контракт состоит из абстрактных методов; реализуют их элементы проекта,
// которые объявляют этот контракт в НастройкиТипа.Контракты. Например:
// абстрактный метод Рассчитать(Параметр: Строка): Число
"""

# Создаваемые виды объектов. Перечень видов – Стд::Отражение::ВидЭлементаПроекта; здесь те,
# что осмысленно создавать файлами. Не заводятся намеренно: ПанельОтчетов и ПроцессИнтеграции
# (содержимое рисуется в дизайнере, у процесса – ещё и координаты узлов; в облаке недоступен),
# КлиентSoapСервиса (без загруженного из IDE WSDL бесполезен), SoapСервис (нужен набор
# параметров сервиса – как маршруты у HttpСервис, отдельная доработка), КомандаСКомпонентом
# (документация расходится с примерами в имени свойства Компонент/ТипКомпонента).
KIND_SPECS: dict[str, KindSpec] = {
    "Справочник": KindSpec(),
    "Документ": KindSpec(),
    "Перечисление": KindSpec(),
    "Структура": KindSpec(extra=("Окружение: КлиентИСервер",)),
    "ХранимаяСтруктура": KindSpec(),
    "РегистрСведений": KindSpec(),
    "РегистрНакопления": KindSpec(),
    "ПланОбмена": KindSpec(),
    "НаборКонстант": KindSpec(),
    "ХранилищеНастроек": KindSpec(),
    # Парный файл – НЕ модуль, а запрос .xbql: "наличие файла и запроса в нем обязательно".
    # Среда разработки создаёт его пустым – делаем так же, а требование пишем в notes.
    "ВиртуальнаяТаблица": KindSpec(
        module=True, module_suffix=".xbql", module_stub="\n",
        note="Запрос виртуальной таблицы обязателен: заполните парный .xbql "
             "(пустой файл – невалидный элемент) и объявите в Параметры все параметры запроса",
    ),
    "Обработка": KindSpec(
        module=True,
        module_stub="// На каждую операцию из секции Операции нужен метод-обработчик с "
                    "тем же именем:\n// @Обработчик\n// метод РассчитатьВсе()\n// ;\n",
        note="Обработка без операций бесполезна: добавьте Операции и одноимённые "
             "@Обработчик-методы в модуль (иначе ошибка \"Обязательный обработчик не определен\")",
    ),
    "ЗапланированноеЗадание": KindSpec(
        module=True, module_stub=_STUB_JOB,
        note="Расписание не задано – ПредопределенноеЗадание может быть только НеСоздавать",
    ),
    "СобытиеЖурналаСобытий": KindSpec(
        extra=("ВидСобытия: Информация", "ШаблонПредставления: {name}"),
        note="Для ВидСобытия: Ошибка нужен ещё ХарактерОшибки, для Операция – "
             "ШаблонПредставленияНачала, ШаблонПредставленияКонца и ШаблонПредставленияОшибки",
    ),
    # Модуль обязателен: платформа ждёт в нём обработчик ВычислитьПараметрыРаботыКлиента,
    # без него параметры не вычисляются (документация "ПараметрыРаботыКлиента").
    "ПараметрыРаботыКлиента": KindSpec(module=True, module_stub=_STUB_CLIENT_PARAMS),
    "ОбщийМодуль": KindSpec(module=True, extra=("Окружение: Сервер",)),
    "HttpСервис": KindSpec(module=True, extra=("КорневойUrl: /{name}",)),
    "ГлобальноеКлиентскоеСобытие": KindSpec(),
    "ФрагментКомандногоИнтерфейса": KindSpec(),
    "КомпонентИнтерфейса": KindSpec(
        extra=(
            "Наследует:",
            "    Тип: Форма",
            "    Содержимое:",
            "        Тип: Группа",
            "        Компоновка: Вертикальная",
        ),
    ),
    "КлючДоступа": KindSpec(module=True),
    "ЛокализованныеСтроки": KindSpec(),
    "Отчет": KindSpec(needs_args=True),
    # Права: у права НА ЭЛЕМЕНТ модуля не бывает ("Не имеет модуля" – это перечисление),
    # у права НА ДЕЙСТВИЕ модуль вычисляет разрешения на сервере.
    "ПравоНаЭлемент": KindSpec(),
    "ПравоНаДействие": KindSpec(module=True, module_stub=_STUB_ACTION_PRIVILEGE),
    # Контракты: модуль нужен только под абстрактные методы, поэтому у контрактов типа и
    # сущности (одни свойства) его не создаём – рабочие контракты в проектах без модулей.
    "КонтрактСервиса": KindSpec(module=True, module_stub=_STUB_SERVICE_CONTRACT),
    "КонтрактТипа": KindSpec(),
    "КонтрактСущности": KindSpec(
        note="ТаблицыКонтракта по умолчанию Недоступны – с ним контракт не виден в запросах; "
             "нужны таблицы – добавьте ТаблицыКонтракта: Доступны",
    ),
    # Команды: у навигационной поведение целиком декларативно (ТипФормы), у остальных смысл
    # в обработчике модуля (исполняется на клиенте).
    "НавигационнаяКоманда": KindSpec(
        extra=("Представление: {name}",),
        note="Задайте ТипФормы – форму, которую открывает команда; без неё команда ничего не делает",
    ),
    "ОбычнаяКоманда": KindSpec(
        module=True, module_stub=_STUB_HANDLER, extra=("Представление: {name}",),
    ),
    "ПереключаемаяКоманда": KindSpec(
        module=True, module_stub=_STUB_HANDLER,
        extra=("ПредставлениеАктивного: {name}", "ПредставлениеНеактивного: {name}"),
        note="Задайте пару представлений (активное/неактивное) и Активна – это смысл вида",
    ),
    "ЦветоваяСхемаОтчета": KindSpec(
        extra=("Представление: {name}",),
        note="Заполните Цвета (Массив<АбсолютныйЦвет>, напр. RGB(009E73)); "
             "ЦветаТемнойТемы необязательны – без них берутся Цвета",
    ),
    "ПараметрСамостоятельнойРегистрацииПользователя": KindSpec(
        module=True, module_stub=_STUB_SELF_REGISTRATION,
        note="Обработчик ПослеПодключения обязателен; параметр работает в связке с "
             "КомпонентСамостоятельнойРегистрации и свойством проекта "
             "КлиентскоеПриложениеСамостоятельнойРегистрации",
    ),
}


def bare_kinds() -> list[str]:
    """Виды, создаваемые одним именем – их можно показать в меню "создать" как есть."""
    return sorted(k for k, spec in KIND_SPECS.items() if not spec.needs_args)

# Пополняемые секции: yaml-секция + строки нового элемента.
_WITH_TYPE = ("Ид: {uuid}", "Имя: {name}", "Тип: {type}")
_SECTION_SPECS: dict[str, dict] = {
    "реквизит": {"section": "Реквизиты", "lines": _WITH_TYPE},
    "измерение": {"section": "Измерения", "lines": _WITH_TYPE},
    "ресурс": {"section": "Ресурсы", "lines": _WITH_TYPE},
    "значение": {"section": "Элементы", "lines": ("Ид: {uuid}", "Имя: {name}")},
    "параметр": {"section": "Параметры", "lines": ("Имя: {name}", "Тип: {type}")},
    "поле": {"section": "Поля", "lines": ("Имя: {name}", "Тип: {type}")},
    "константа": {"section": "Константы", "lines": _WITH_TYPE},
    "свойство": {"section": "Свойства", "lines": ("Имя: {name}", "Тип: {type}")},
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
    # Табличные части – только у ссылочных сущностей (документация "Табличная часть":
    # Справочник, Документ, ПланОбмена, ХранилищеНастроек, КонтрактСущности).
    "Справочник": ("реквизит", "табличная-часть"),
    "Документ": ("реквизит", "табличная-часть"),
    "ПланОбмена": ("реквизит", "табличная-часть"),
    "ХранилищеНастроек": ("реквизит", "табличная-часть"),
    "РегистрСведений": ("измерение", "ресурс", "реквизит"),
    "РегистрНакопления": ("измерение", "ресурс", "реквизит"),
    "НаборКонстант": ("константа",),
    "Обработка": ("реквизит",),
    "Перечисление": ("значение",),
    "ПараметрыРаботыКлиента": ("параметр",),
    "ГлобальноеКлиентскоеСобытие": ("параметр",),
    "ЗапланированноеЗадание": ("параметр",),
    "ВиртуальнаяТаблица": ("параметр",),
    "Структура": ("поле",),
    "ХранимаяСтруктура": ("поле",),
    "ПараметрСамостоятельнойРегистрацииПользователя": ("поле",),
    "КлючДоступа": ("параметр",),
    "ПравоНаДействие": ("параметр",),
    "ПравоНаЭлемент": ("значение",),  # секция Элементы: действия права
    "КонтрактТипа": ("свойство",),
    "КонтрактСущности": ("свойство", "табличная-часть"),
    "СобытиеЖурналаСобытий": ("свойство",),
}

# Состав строк, отличный от общего для вида объекта: у полей ХранимойСтруктуры и параметров
# КлючаДоступа документация описывает Ид – он держит привязку данных при переименовании
# (у обычной Структуры и у ПараметрыРаботыКлиента Ид в составе нет).
_KIND_SECTION_LINES: dict[tuple[str, str], tuple[str, ...]] = {
    ("ХранимаяСтруктура", "поле"): _WITH_TYPE,
    ("КлючДоступа", "параметр"): _WITH_TYPE,
    ("ПравоНаДействие", "параметр"): _WITH_TYPE,
    ("ЗапланированноеЗадание", "параметр"): _WITH_TYPE,
    ("КонтрактСущности", "свойство"): _WITH_TYPE,
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


# Типы со значением по умолчанию: ПолеВвода<Тип> принимает их как есть. У ПолеВвода
# "параметр типа должен иметь значение по умолчанию ИЛИ Неопределено в составе типов"
# (stdlib ПолеВвода) – дефолта нет у ссылок и у перечислений без ПоУмолчанию, им нужен '?'.
PRIMITIVE_TYPES = {
    "Строка", "Число", "Булево", "Дата", "ДатаВремя", "Время", "УникальныйИдентификатор",
    "Момент", "Длительность", "Ууид",
}

# Стандартные (предопределённые платформой) реквизиты: в yaml их обычно нет, но в формах они нужны.
_STANDARD_FIELDS = {
    "Справочник": [{"name": "Наименование", "type": "Строка"}],
    "Документ": [{"name": "Номер", "type": "Строка"}, {"name": "Дата", "type": "ДатаВремя"}],
}

# Виды, у которых бывают формы объекта и списка (дочерние типы ФормаОбъекта / ФормаСписка
# в stdlib). У регистров и набора констант формы объекта нет – только список.
OBJECT_FORM_KINDS = ("Справочник", "Документ", "ПланОбмена", "ХранилищеНастроек")
LIST_FORM_KINDS = OBJECT_FORM_KINDS + (
    "РегистрСведений", "РегистрНакопления", "НаборКонстант",
)
# Данные регистра лежат в Измерениях и Ресурсах, а не только в Реквизитах: для списка
# показывать нужно их все.
_REGISTER_FIELD_SECTIONS = ("Измерения", "Ресурсы", "Реквизиты")


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

    # У регистра данные – это Измерения и Ресурсы, реквизиты лишь дополняют их.
    sections = (
        _REGISTER_FIELD_SECTIONS if hit.kind.startswith("Регистр") else ("Реквизиты",)
    )
    fields = [
        {"name": item.get("Имя", "?"), "type": item.get("Тип", "")}
        for section in sections
        for item in section_items(text, section, top_level=True)
    ]
    declared = {f["name"] for f in fields}
    standard = [f for f in _STANDARD_FIELDS.get(hit.kind, []) if f["name"] not in declared]
    fields = standard + fields

    tabulars = [
        {
            "name": item.get("Имя", "?"),
            "fields": _tabular_fields(text, item.get("Имя", "")),
        }
        for item in section_items(text, "ТабличныеЧасти", top_level=True)
    ]
    hierarchies = [
        {"name": h.get("Имя", ""), "field": h.get("ПолеРодителя", "")}
        for h in section_items(text, "ДополнительныеИерархии", top_level=True)
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
        # None – секции КонтрольДоступа нет: платформа применяет РазрешеноАдминистраторам.
        "access": access_info(text),
        "access_rights": list(ACCESS_KIND_RIGHTS.get(hit.kind, ())),
        "fields": fields,
        "tabulars": tabulars,
        "suggested_layout": layout,
        "existing_forms": existing_forms,
        "is_hierarchical": is_hierarchical,
        "additional_hierarchies": hierarchies,
        "report_params": [
            {"name": p.get("Имя", "?"), "type": p.get("Тип", "")}
            for p in section_items(text, "ПараметрыЗапроса", top_level=True)
        ],
        "sections": {
            kind: [i.get("Имя", "?") for i in section_items(text, _SECTION_SPECS[kind]["section"], top_level=True)]
            for kind in KIND_SECTIONS.get(hit.kind, ())
        },
    }


def _tabular_fields(text: str, tc_name: str) -> list[dict]:
    """Реквизиты табличной части: они лежат во вложенной секции её блока, а не наверху."""
    if not tc_name:
        return []
    offset = find_section_item_offset(text, "ТабличныеЧасти", tc_name)
    if offset is None:
        return []
    block = _block_at(text, offset)
    return [
        {"name": item.get("Имя", "?"), "type": item.get("Тип", "")}
        for item in section_items(block, "Реквизиты")
    ]


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
    for yaml_path, kind, name, text in _iter_objects(root):
        subsystem, namespace = _namespace_of(yaml_path, root)
        entry = {
            "kind": kind, "name": name, "path": str(yaml_path),
            "subsystem": subsystem, "namespace": namespace,
        }
        if kind in ACCESS_KIND_RIGHTS:
            # Сводка прав по проекту: способ для ПоУмолчанию (None – секции нет, значит
            # действует РазрешеноАдминистраторам) и способы отдельных прав.
            access = access_info(text)
            entry["access_default"] = access["default"] if access else None
            entry["access_permissions"] = access["permissions"] if access else {}
        objects.append(entry)
    return {
        "projects": [
            {**p, "dir": str(p["dir"])} for p in projects
        ],
        "objects": sorted(objects, key=lambda o: (o["kind"], o["name"])),
        "creatable_kinds": sorted(KIND_SPECS),
        "field_kinds": {kind: list(sections) for kind, sections in KIND_SECTIONS.items()},
        "access_methods": list(ACCESS_METHODS),
        "access_kind_rights": {k: list(v) for k, v in ACCESS_KIND_RIGHTS.items()},
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

    environment – Окружение для ОбщийМодуль/Структура; access – способ контроля доступа
    (у HttpСервис пишется в Разрешения.Вызов, у объектов данных – в Разрешения.ПоУмолчанию;
    отдельные права задаёт op_set_access); routes – маршруты HttpСервис
    ("GET /, POST /, GET /{id}"); report – источник и макет отчёта.
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

    if access and kind not in ACCESS_KIND_RIGHTS:
        raise ScaffoldError(
            f"Вид {kind} не поддерживает управление доступом – параметр access неприменим; "
            "поддерживают: " + ", ".join(sorted(ACCESS_KIND_RIGHTS))
        )
    if access and access not in ACCESS_METHODS:
        raise ScaffoldError(
            f"Недопустимый способ контроля доступа '{access}'; доступны: " + ", ".join(ACCESS_METHODS)
        )

    result = ScaffoldResult()
    if access in ("РазрешенияВычисляются", _PER_OBJECT):
        result.notes.append(
            f"{access}: разрешения нужно вычислить самому – напишите обработчик "
            "ВычислитьРазрешенияДоступа" + (
                " и ВычислитьРазрешенияДоступаДляОбъектов (+ РасчетРазрешенийПо)"
                if access == _PER_OBJECT else ""
            ) + " в модуле объекта"
        )
    if kind == "HttpСервис":
        return _new_http_service(yaml_path, name, access, routes or "GET /", result, scope)
    if kind == "Отчет":
        return _new_report(yaml_path, name, report or {}, result, scope)

    extra = [line.format(name=name) for line in spec.extra]
    if environment:
        extra = [line for line in extra if not line.startswith("Окружение:")]
        extra.append(f"Окружение: {environment}")
    if access:
        # Разрешения обязательны: КонтрольДоступа – это набор "Право: СпособКонтроляДоступа"
        # внутри Разрешения (см. ACCESS_KIND_RIGHTS и документацию "Контроль прав доступа").
        extra += ["КонтрольДоступа:", f"    {_PERMISSIONS_KEY}:",
                  f"        {ACCESS_DEFAULT_RIGHT}: {access}"]
    content = new_object_yaml(kind, new_uuid(), name, scope or spec.scope, extra)
    result.changes.append(FileChange(yaml_path, content, created=True))
    if spec.module:
        stub = spec.module_stub.format(name=name) if spec.module_stub else f"// {name}\n"
        result.changes.append(
            FileChange(yaml_path.with_suffix(spec.module_suffix), stub, created=True)
        )
    if spec.note:
        result.notes.append(spec.note)
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
    if allowed is None:
        # Вид без пополняемых секций (ОбщийМодуль, HttpСервис, КомпонентИнтерфейса и т.п.):
        # раньше проверка пропускала такой вид и молча дописывала ему чужую секцию.
        raise ScaffoldError(
            f"У вида {kind} нет пополняемых секций; они есть у: " + ", ".join(sorted(KIND_SECTIONS))
        )
    if field_kind not in allowed:
        raise ScaffoldError(
            f"У вида {kind} нет секции для '{field_kind}'; доступны: {', '.join(allowed)}"
        )
    existing = {i.get("Имя") for i in section_items(text, spec["section"], top_level=True)}
    if name in existing:
        raise ScaffoldError(f"'{name}' уже есть в секции {spec['section']} файла {yaml_path.name}")
    template = _KIND_SECTION_LINES.get((kind, field_kind), spec["lines"])
    lines = [
        line.format(uuid=new_uuid(), uuid2=new_uuid(), name=name, type=type_)
        for line in template
    ]
    edit = insert_item_edit(text, spec["section"], lines, nl, top_level=True)
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
    # Блок Интерфейс пишется всегда: умолчание платформы – Истина, поэтому отключение
    # автоинтерфейса существует только как явная запись ВключатьВАвтоИнтерфейс: Ложь.
    lines.append("Интерфейс:")
    lines.append(f"    ВключатьВАвтоИнтерфейс: {'Истина' if auto_interface else 'Ложь'}")
    if representation:
        lines.append(f"    Представление: {representation}")
    content = "\n".join(lines) + "\n"
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
    # Три числа A.B.C – семантическое версионирование по стандарту свойств проекта
    # (на "1.0" ругается собственное правило линтера project/version).
    version: str = "1.0.0",
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
    """Сегмент пути -> часть идентификатора: разделители убираются, слова с заглавной.

    В пути законны символы, недопустимые в имени (дефис, точка, звёздочка шаблона
    `/read/*`): их отбрасываем, иначе получится не идентификатор, а сломанный yaml
    (`Имя: *` парсер читает как алиас) и некомпилируемое имя обработчика.
    """
    s = s.strip("{}")
    parts = [p for p in re.split(r"[^A-Za-zА-Яа-яЁё0-9_]+", s) if p]
    return "".join(p[:1].upper() + p[1:] for p in parts)


def template_name(path: str) -> str:
    if path == "/":
        return "Список"
    segments = [s for s in path.lstrip("/").split("/") if s]
    literal = [_to_pascal(s) for s in segments if not (s.startswith("{") and s.endswith("}"))]
    literal = [s for s in literal if s]
    params = [s for s in segments if s.startswith("{") and s.endswith("}")]
    if not literal:
        return "ЭлементПоИд"
    if params:
        return literal[-1] + "ПоРодителю"
    return literal[-1]


def assign_template_name(path: str, used: set[str]) -> str:
    """Имя шаблона URL, уникальное в пределах сервиса.

    Имя шаблона – ключ: по нему платформа хранит разрешения доступа и его отдаёт
    Запрос.ИмяШаблона, а op_add_route ищет по нему блок для дополнения. Разные пути легко
    дают одно имя (`/users` и `/orders/users`), поэтому дубли разводятся суффиксом.
    """
    base = template_name(path) or "Шаблон"
    name, n = base, 2
    while name in used:
        name = f"{base}{n}"
        n += 1
    used.add(name)
    return name


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


def _template_lines(path: str, method_handlers: list[tuple[str, str]], name: str) -> list[str]:
    lines = [f"Имя: {name}", f"Шаблон: {path}", "Методы:"]
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
    поймать Ошибка: Исключение
        ОбработатьОшибку(Запрос.Ответ, Ошибка)
    ;"""
    elif key == ("POST", False):
        body = """\
    попытка
        // TODO: десериализовать тело и создать объект
        // знч Данные = СериализацияJson.ПрочитатьОбъект(Запрос.Тело, Тип<...>)
        // знч Ссылка = <Справочник>.Создать(Данные)
        Запрос.Ответ.УстановитьКодСтатуса(201)
        // Запрос.Ответ.УстановитьТело(Ссылка.Ид.ВСтроку())
    поймать Ошибка: Исключение
        ОбработатьОшибку(Запрос.Ответ, Ошибка)
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
    поймать Ошибка: Исключение
        ОбработатьОшибку(Запрос.Ответ, Ошибка)
    ;"""
    else:
        body = f"""\
    попытка
        // TODO: реализовать {method}
    поймать Ошибка: Исключение
        ОбработатьОшибку(Запрос.Ответ, Ошибка)
    ;"""
    return f"метод {handler}(Запрос: HttpСервисЗапрос)\n{body}\n;"


_ERROR_HELPER = """\
метод ОбработатьОшибку(Ответ: HttpСервисОтвет, Ошибка: Исключение)
    Ответ.УстановитьКодСтатуса(500)
    Ответ.Заголовки.Установить("Content-Type", "text/plain; charset=utf-8")
    Ответ.УстановитьТело(Ошибка.Описание)
;"""


def _new_http_service(
    yaml_path: Path, name: str, access: str | None, routes: str, result: ScaffoldResult,
    scope: str | None = None,
) -> ScaffoldResult:
    templates = parse_routes(routes)
    used: set[str] = set()
    used_templates: set[str] = set()
    assigned = [
        (path, assign_template_name(path, used_templates),
         [(m, assign_handler(m, path, used)) for m in methods])
        for path, methods in templates
    ]
    lines = [
        "ВидЭлемента: HttpСервис",
        f"Ид: {new_uuid()}",
        f"Имя: {name}",
        f"ОбластьВидимости: {scope or KIND_SPECS['HttpСервис'].scope}",
        f"КорневойUrl: /{name}",
    ]
    if access:
        lines += ["КонтрольДоступа:", "    Разрешения:", f"        Вызов: {access}"]
    lines.append("ШаблоныUrl:")
    for path, template, method_handlers in assigned:
        lines.append("    -")
        lines += [f"        {line}" for line in _template_lines(path, method_handlers, template)]
    blocks = [
        _handler_stub(m, path, handler)
        for path, _template, method_handlers in assigned
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
    # Занятые имена шаблонов: имя – ключ шаблона (по нему платформа хранит разрешения,
    # его отдаёт Запрос.ИмяШаблона, и по нему же ищется блок для дополнения ниже).
    used_templates = {i.get("Имя", "") for i in section_items(text, "ШаблоныUrl", top_level=True)}

    result = ScaffoldResult()
    added: list[tuple[str, str, str]] = []  # (метод, шаблон, обработчик)
    for path, methods in parse_routes(routes):
        template = next(
            (i for i in section_items(text, "ШаблоныUrl", top_level=True) if i.get("Шаблон") == path), None
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
            template_name_ = assign_template_name(path, used_templates)
            edit = insert_item_edit(
                text, "ШаблоныUrl", _template_lines(path, method_handlers, template_name_), nl,
                top_level=True,
            )
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


def _new_report(yaml_path: Path, name: str, report: dict, result: ScaffoldResult,
                scope: str | None = None) -> ScaffoldResult:
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
        f"ОбластьВидимости: {scope or KIND_SPECS['Отчет'].scope}",
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
    # '?' добавляется только там, где у типа заведомо нет значения по умолчанию: ссылка и
    # перечисление. Коллекции и обобщения (Массив<Строка> и т.п.) дефолт имеют – раньше им
    # приписывалось '?', и двусторонняя привязка Значение: =Объект.X расходилась по типу.
    needs_nullable = (
        component_type not in PRIMITIVE_TYPES
        and not component_type.endswith("?")
        and "<" not in component_type
    )
    if needs_nullable:
        component_type += "?"
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


def _tabular_table_lines(obj: str, tc_name: str, indent: str, panels: bool,
                         fields: list[dict] | None = None) -> list[str]:
    """Таблица табличной части: источник, колонки по её реквизитам и команды строк.

    Колонки обязательны – "Необходимо задать Колонки (колонки таблицы) и Источник"
    (документация "Компонент интерфейса Таблица"): без них таблица показывает пустые строки.
    ПолеЗначения задаёт и сортировку по колонке, поэтому пишется вместе с Заголовком.
    """
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
    ]
    if fields:
        lines.append(f"{indent}Колонки:")
        for field in fields:
            lines += [
                f"{indent}    -",
                f"{indent}        Тип: СтандартнаяКолонкаТаблицы<{obj}.{tc_name}>",
                f"{indent}        Заголовок: {field['name']}",
                f"{indent}        ПолеЗначения: {field['name']}",
            ]
    lines += [
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
    if section_type == "РазделФормы":
        # РазделФормы.Содержимое – Массив<Группа>: поля кладутся в область раздела, а не
        # напрямую (у Группы содержимое – Массив<Компонент>, там обёртка не нужна).
        lines += [
            "                -",
            "                    Содержимое:",
        ]
        field_indent = " " * 24
    else:
        field_indent = " " * 16
    for f in fields:
        lines += _form_field_component(f["name"], f["type"], field_indent)
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
            ] + _tabular_table_lines(obj, tc_name, " " * 28, panels=True, fields=tc["fields"])
        else:
            lines += [
                "            -",
                "                Тип: РазделФормы",
                f"                Заголовок: {tc_name}",
                "                Содержимое:",
                "                    -",
                "                        Содержимое:",
            ] + [" " * 28 + "-"] + _tabular_table_lines(
                obj, tc_name, " " * 32, panels=False, fields=tc["fields"]
            )
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
        # ПолеЗначения задаёт не только отображаемое значение, но и сортировку по колонке
        # ("Также это поле будет использоваться для сортировки по данной колонке" –
        # документация компонента Таблица), поэтому пишется вместе с Заголовком.
        lines += [
            "                -",
            f"                    Тип: СтандартнаяКолонкаТаблицы<СтрокаДинамическогоСписка<{row_type}>>",
            f"                    Имя: {name}",
            f"                    Заголовок: {name}",
            f"                    ПолеЗначения: {name}",
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
        # Иерархия элементов: имя писать не нужно и нечего – "Если ПоУмолчанию или пустая
        # строка, будет отображена иерархия, которая указана как иерархия по-умолчанию в
        # справочнике" (stdlib ДинамическийСписок). Имени иерархии "Иерархия" не существует:
        # так называется таблица языка запросов, а не иерархия справочника.
        lines += [
            "            ИспользуемаяИерархия:",
            "                Тип: РежимИерархии",
            "                Значение: ПоУмолчанию",
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
                f"                            Имя: {p['name']}",
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
    if kind == "Отчет":
        # У отчёта форма регистрируется одним ключом Интерфейс.Форма (подсекций Объект/Список
        # у него нет), поэтому общий цикл ниже его не обслуживает.
        form_name = f"{obj}ФормаОтчета"
        span = top_level_key_span(text, "Интерфейс")
        if re.search(rf"Форма:\s*{form_name}\b", text):
            result.notes.append(f"{form_name} уже зарегистрирована в Интерфейс")
        elif re.search(r"^\s{4}Форма:", text[span[0]: span[1]], re.M):
            result.notes.append("В Интерфейс уже указана Форма – регистрация вручную")
        else:
            text = text[: span[1]] + f"{nl}    Форма: {form_name}" + text[span[1]:]
        return text

    for form, subsection in (("object", "Объект"), ("list", "Список")):
        if form not in forms:
            continue
        form_name = f"{obj}Форма{'Объекта' if form == 'object' else 'Списка'}"
        if re.search(rf"Форма:\s*{form_name}\b", text):
            result.notes.append(f"{form_name} уже зарегистрирована в Интерфейс")
            continue
        span = top_level_key_span(text, "Интерфейс")
        body = text[span[0]: span[1]]
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
        if kind == "Отчет":
            forms = ["report"]
        elif kind in OBJECT_FORM_KINDS:
            forms = ["object", "list"]
        elif kind in LIST_FORM_KINDS:
            forms = ["list"]  # у регистров и набора констант формы объекта не бывает
        else:
            raise ScaffoldError(
                f"У вида {kind} нет форм объекта и списка; они есть у: "
                + ", ".join(LIST_FORM_KINDS) + " (и форма отчёта у Отчет)"
            )
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
    # Тип ФормаОбъекта<X.Объект> порождают только ссылочные сущности; у регистра его нет.
    if "object" in forms and kind not in OBJECT_FORM_KINDS:
        raise ScaffoldError(
            f"У вида {kind} нет формы объекта (тип ФормаОбъекта порождают только "
            + ", ".join(OBJECT_FORM_KINDS) + f"); для {kind} доступна форма списка"
        )
    if ("list" in forms or "list-cards" in forms) and kind not in LIST_FORM_KINDS:
        raise ScaffoldError(
            f"У вида {kind} нет формы списка; она есть у: " + ", ".join(LIST_FORM_KINDS)
        )

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


# --- контроль доступа --------------------------------------------------------------------
#
# КонтрольДоступа.Разрешения – набор записей "Право: СпособКонтроляДоступа" (документация:
# "Контроль прав доступа"). Права сущности – Создание/Чтение/Изменение/Удаление
# (Стд::Сущности::Сущность.Право), у сервисов – Вызов, у регистров и набора констант –
# Чтение/Изменение; ПоУмолчанию задаёт способ для всех прочих прав. Право может быть и
# пользовательским – "ПравоНаX.ИмяПрава" (элемент проекта вида ПравоНаЭлемент). Секции нет –
# платформа применяет РазрешеноАдминистраторам.

ACCESS_METHODS = (
    "РазрешеноВсем",
    "РазрешеноАутентифицированным",
    "РазрешеноАдминистраторам",
    "РазрешенияВычисляются",
    "РазрешенияВычисляютсяДляКаждогоОбъекта",
)
ACCESS_DEFAULT_RIGHT = "ПоУмолчанию"
_ACCESS_IMPLICIT = "РазрешеноАдминистраторам"  # когда секции КонтрольДоступа нет
_PER_OBJECT = "РазрешенияВычисляютсяДляКаждогоОбъекта"

# Права по видам элементов проекта (документация "Контроль прав доступа": управление
# доступом поддерживают именно эти виды). Пустой кортеж – вид поддерживает только ПоУмолчанию.
ACCESS_KIND_RIGHTS: dict[str, tuple[str, ...]] = {
    "Справочник": ("Создание", "Чтение", "Изменение", "Удаление"),
    "Документ": ("Создание", "Чтение", "Изменение", "Удаление"),
    "ПланОбмена": ("Создание", "Чтение", "Изменение", "Удаление"),
    "РегистрСведений": ("Чтение", "Изменение"),
    "РегистрНакопления": ("Чтение", "Изменение"),
    "НаборКонстант": ("Чтение", "Изменение"),
    "HttpСервис": ("Вызов",),
    "SoapСервис": ("Вызов",),
    "ХранилищеНастроек": (),
}
# Набор констант не поддерживает построчные разрешения (документация "Свойства элемента
# проекта вида НаборКонстант").
_NO_PER_OBJECT_KINDS = ("НаборКонстант",)

_ACCESS_SECTION = "КонтрольДоступа"
_PERMISSIONS_KEY = "Разрешения"
_CALC_BY_KEY = "РасчетРазрешенийПо"
# Куда вставить секцию КонтрольДоступа, если её нет: перед первой из этих секций.
_ACCESS_ANCHORS = (
    "Реквизиты", "Измерения", "Ресурсы", "ТабличныеЧасти", "ШаблоныUrl", "Операции",
    "Интерфейс", "НастройкиТипов", "Индексы", "Свойства",
)
_KEY_VALUE_LINE = re.compile(rf"^([ \t]*)([{_WORD}.]+):[ \t]*(\S.*?)[ \t]*$")


def _mapping_in(body: str, key: str) -> dict[str, str]:
    """Скалярные пары "Ключ: Значение" вложенной секции-отображения (напр. Разрешения)."""
    bounds = _section_bounds(body, key)
    if bounds is None:
        return {}
    header_indent, header_line_end, body_end = bounds
    out: dict[str, str] = {}
    for line in body[header_line_end:body_end].split("\n"):
        m = _KEY_VALUE_LINE.match(line)
        if m and len(m.group(1)) > header_indent:
            out[m.group(2)] = m.group(3)
    return out


def _calc_by_values(body: str) -> list[str]:
    """Значения РасчетРазрешенийПо: и инлайн-список [A, B], и список из "- A"."""
    m = re.search(rf"^[ \t]*{_CALC_BY_KEY}:[ \t]*(.*)$", body, re.M)
    if m is None:
        return []
    inline = m.group(1).strip()
    if inline.startswith("["):
        return [v.strip() for v in inline.strip("[]").split(",") if v.strip()]
    bounds = _section_bounds(body, _CALC_BY_KEY)
    if bounds is None:
        return []
    _, header_line_end, body_end = bounds
    return [
        line.strip().lstrip("-").strip()
        for line in body[header_line_end:body_end].split("\n")
        if line.strip().startswith("-")
    ]


def access_info(text: str) -> dict | None:
    """Сводка КонтрольДоступа объекта или None, если секции нет.

    {permissions: {право: способ}, default: способ|None, calc_by: [поля]}. Отсутствие секции –
    именно None, а не пустая сводка: платформа тогда применяет РазрешеноАдминистраторам.
    """
    bounds = _section_bounds(text, _ACCESS_SECTION, top_level=True)
    if bounds is None:
        return None
    _, header_line_end, body_end = bounds
    body = text[header_line_end:body_end]
    permissions = _mapping_in(body, _PERMISSIONS_KEY)
    return {
        "permissions": permissions,
        "default": permissions.get(ACCESS_DEFAULT_RIGHT),
        "calc_by": _calc_by_values(body),
    }


def _access_anchor(text: str) -> int:
    """Смещение вставки секции КонтрольДоступа: перед первой секцией данных, иначе в конец."""
    offsets = [
        m.start()
        for key in _ACCESS_ANCHORS
        for m in [re.search(rf"^{re.escape(key)}:[ \t]*\r?$", text, re.M)]
        if m
    ]
    return min(offsets) if offsets else len(text)


def _set_mapping_value(text: str, section_offset_end: int, body_end: int, indent: str,
                       key: str, value: str, nl: str) -> tuple[str, int]:
    """Заменить значение ключа отображения или дописать ключ в конец секции.

    Возвращает (новый текст, сдвиг конца секции) – вызывающий пересчитывает границы.
    """
    body = text[section_offset_end:body_end]
    m = re.search(rf"^([ \t]*){re.escape(key)}:[ \t]*(.*)$", body, re.M)
    if m:
        start = section_offset_end + m.start()
        end = section_offset_end + m.end()
        new_line = f"{m.group(1)}{key}: {value}"
        return text[:start] + new_line + text[end:], len(new_line) - (end - start)
    addition = f"{nl}{indent}{key}: {value}"
    return text[:body_end] + addition + text[body_end:], len(addition)


def op_set_access(
    root: Path,
    name: str | None = None,
    yaml_path: Path | None = None,
    *,
    default: str | None = None,
    permissions: dict[str, str] | None = None,
    calc_by: list[str] | None = None,
    reader=None,
) -> ScaffoldResult:
    """Задать КонтрольДоступа.Разрешения объекта: точечно, с проверкой вида и способа.

    default – способ для права ПоУмолчанию (частый случай); permissions – способы отдельных
    прав ({"Чтение": "РазрешеноВсем"}), в том числе пользовательских ("ПравоНаX.ИмяПрава").
    calc_by задаёт РасчетРазрешенийПо – он обязателен для РазрешенияВычисляютсяДляКаждогоОбъекта.
    Обработчики вычисления разрешений операция НЕ пишет: это бизнес-логика (см. документацию
    "Самостоятельное формирование разрешений и выдача экземпляров ключей") – в notes остаётся
    напоминание.
    """
    wanted: dict[str, str] = dict(permissions or {})
    if default:
        wanted[ACCESS_DEFAULT_RIGHT] = default
    if not wanted and calc_by is None:
        raise ScaffoldError("Нечего менять: задайте default, permissions или calc_by")

    info = object_info(Path(root), name=name, yaml_path=yaml_path)
    kind = info["kind"]
    owner_path = Path(info["path"])
    if kind not in ACCESS_KIND_RIGHTS:
        raise ScaffoldError(
            f"Вид {kind} не поддерживает управление доступом; поддерживают: "
            + ", ".join(sorted(ACCESS_KIND_RIGHTS))
        )

    result = ScaffoldResult()
    known = ACCESS_KIND_RIGHTS[kind]
    for right, method in wanted.items():
        if method not in ACCESS_METHODS:
            raise ScaffoldError(
                f"Недопустимый способ контроля доступа '{method}' у права '{right}'; "
                + "доступны: " + ", ".join(ACCESS_METHODS)
            )
        if method == _PER_OBJECT and kind in _NO_PER_OBJECT_KINDS:
            raise ScaffoldError(f"Вид {kind} не поддерживает {_PER_OBJECT}")
        if right != ACCESS_DEFAULT_RIGHT and "." not in right and right not in known:
            allowed = ", ".join(known) if known else "только " + ACCESS_DEFAULT_RIGHT
            raise ScaffoldError(
                f"У вида {kind} нет права '{right}'; доступны: {allowed} "
                f"(и {ACCESS_DEFAULT_RIGHT}; пользовательское право пишется как ПравоНаX.ИмяПрава)"
            )

    text, nl = _load_for_edit(owner_path, reader)
    current = access_info(text)
    per_object = [r for r, m in wanted.items() if m == _PER_OBJECT]
    if per_object:
        has_calc = bool(calc_by) or bool(current and current["calc_by"])
        if not has_calc:
            raise ScaffoldError(
                f"{_PER_OBJECT} требует {_CALC_BY_KEY} – передайте calc_by "
                "(поля объекта, по которым считаются разрешения)"
            )
    if calc_by is not None and not calc_by:
        raise ScaffoldError(f"{_CALC_BY_KEY} не может быть пустым")

    unchanged = [r for r, m in wanted.items() if current and current["permissions"].get(r) == m]
    if unchanged and len(unchanged) == len(wanted) and calc_by is None:
        result.notes.append(
            "Права уже имеют такие значения: "
            + ", ".join(f"{r}: {wanted[r]}" for r in unchanged)
        )
        return result

    if current is None:
        lines = [f"{_ACCESS_SECTION}:", f"    {_PERMISSIONS_KEY}:"]
        lines += [f"        {right}: {method}" for right, method in wanted.items()]
        if calc_by:
            lines.append(f"    {_CALC_BY_KEY}: [{', '.join(calc_by)}]")
        at = _access_anchor(text)
        block = nl.join(lines) + nl
        new_text = text[:at] + block + text[at:]
    else:
        new_text = text
        for right, method in wanted.items():
            new_text = _write_permission(new_text, right, method, nl)
        if calc_by:
            new_text = _write_calc_by(new_text, calc_by, nl)

    result.changes.append(FileChange(owner_path, new_text, created=False))
    was = (current["permissions"] if current else {})
    for right, method in wanted.items():
        before = was.get(right) or (f"нет секции – {_ACCESS_IMPLICIT}" if current is None else "не задано")
        result.notes.append(f"{right}: {before} -> {method}")
    if per_object:
        result.notes.append(
            "Нужны обработчики ВычислитьРазрешенияДоступа и "
            "ВычислитьРазрешенияДоступаДляОбъектов в модуле объекта, иначе доступа не будет"
        )
    elif any(m == "РазрешенияВычисляются" for m in wanted.values()):
        result.notes.append(
            "Нужен обработчик ВычислитьРазрешенияДоступа в модуле объекта, иначе доступа не будет"
        )
    return result


def _access_body_bounds(text: str) -> tuple[int, int]:
    _, header_line_end, body_end = _section_bounds(text, _ACCESS_SECTION, top_level=True)
    return header_line_end, body_end


def _write_permission(text: str, right: str, method: str, nl: str) -> str:
    """Точечно задать право в существующей секции КонтрольДоступа."""
    header_line_end, body_end = _access_body_bounds(text)
    body = text[header_line_end:body_end]
    perms = _section_bounds(body, _PERMISSIONS_KEY)
    if perms is None:  # секция есть, а Разрешения нет – дописываем блок
        addition = f"{nl}    {_PERMISSIONS_KEY}:{nl}        {right}: {method}"
        return text[:body_end] + addition + text[body_end:]
    perm_indent, perm_header_end, perm_body_end = perms
    new_text, _ = _set_mapping_value(
        text, header_line_end + perm_header_end, header_line_end + perm_body_end,
        " " * (perm_indent + 4), right, method, nl,
    )
    return new_text


def _write_calc_by(text: str, calc_by: list[str], nl: str) -> str:
    header_line_end, body_end = _access_body_bounds(text)
    value = f"[{', '.join(calc_by)}]"
    new_text, _ = _set_mapping_value(text, header_line_end, body_end, "    ", _CALC_BY_KEY, value, nl)
    return new_text


# --- операция: переименование объекта ----------------------------------------------------
#
# Переименование текстовое и контекстное, без полного индекса: имя заменяется только там,
# где оно ссылается на объект (значения ссылочных ключей yaml, корни цепочек в биндингах
# и коде, составные имена форм), а совпадающие имена реквизитов, компонентов и полей
# динамических списков не трогаются. Строковые литералы .xbsl не правятся (UI-текст),
# комментарии – правятся (упоминания объекта в документации кода).

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
