"""code/redundant-cast and code/cast-to-non-null: the casts the editor of the platform warns about.

The verdict itself is tested in test_typeinfer_sets.py; here the rules are run over small
projects, the way the engine runs them - the mapper per file, the reduce over the project - and
the operands come from the places a live project casts: a query row, a generic member, a
parameter of a union type, a structure of another module. Every shape has its control, the
variant the compiler of the platform does not warn about (see the probe project described in
the rule module).

The mapper parses modules and the reduce reads the type catalog, so the tests that lint carry
`needs_data`; the registration check runs in every checkout.
"""

import pytest

from xbsl import engine, fixer
from xbsl.diagnostics import Severity

REDUNDANT = "code/redundant-cast"
NON_NULL = "code/cast-to-non-null"

WAREHOUSES = """ВидЭлемента: Справочник
Имя: Склады
НастройкиТипов:
    Справочник.Объект:
        Контракты:
            - МестаХранения.Объект
Реквизиты:
    -
        Имя: Наименование
        Длина: 100
    -
        Имя: Вместимость
        Тип: Число
    -
        Имя: Основной
        Тип: Склады.Ссылка?
ТабличныеЧасти:
    -
        Имя: Ячейки
        Реквизиты:
            -
                Имя: Партия
                Тип: Партии.Ссылка?
            -
                Имя: Объем
                Тип: Число
"""

BATCHES = """ВидЭлемента: Справочник
Имя: Партии
Реквизиты:
    -
        Имя: Наименование
        Длина: 50
"""

STORAGE = """ВидЭлемента: КонтрактСущности
Имя: МестаХранения
ТаблицыКонтракта: Доступны
Свойства:
    -
        Имя: Наименование
        Тип: Строка
        ТолькоЧтение: Истина
"""

PLATFORMS = """ВидЭлемента: Справочник
Имя: Площадки
НастройкиТипов:
    Справочник.Объект:
        Контракты:
            - МестаХранения.Объект
Реквизиты:
    -
        Имя: Наименование
        Длина: 100
"""

MODULE_YAML = "ВидЭлемента: ОбщийМодуль\nИмя: Остатки\nОкружение: Сервер\n"


def _project(module: str, **extra) -> dict[str, str]:
    files = {
        "Основное/Склады.yaml": WAREHOUSES,
        "Основное/Партии.yaml": BATCHES,
        "Основное/МестаХранения.yaml": STORAGE,
        "Основное/Площадки.yaml": PLATFORMS,
        "Основное/Остатки.yaml": MODULE_YAML,
        "Основное/Остатки.xbsl": module,
    }
    files.update(extra)
    return files


def _lint(files: dict[str, str]):
    sources = [engine.load_text(name, content) for name, content in files.items()]
    return sources, engine.run_sources(sources, select={REDUNDANT, NON_NULL})


def _found(files: dict[str, str]) -> list[tuple[str, int]]:
    _sources, diags = _lint(files)
    return sorted((d.rule_id, d.line) for d in diags)


def _line(text: str, marker: str) -> int:
    return text[: text.index(marker)].count("\n") + 1


def _fixed(files: dict[str, str], name: str = "Основное/Остатки.xbsl") -> str:
    sources, diags = _lint(files)
    source = next(s for s in sources if s.rel.replace("\\", "/") == name)
    own = [d for d in diags if d.path.replace("\\", "/") == name]
    return fixer.fix_source(source, own).text


def test_both_rules_are_registered_as_project_warnings():
    for rule_id in (REDUNDANT, NON_NULL):
        info = next(r for r in engine.RULES if r.id == rule_id)
        assert info.tier == "D" and info.scope == "project" and info.mapper is not None
        assert info.severity is Severity.WARNING


# --- a query row ------------------------------------------------------------------------------

ROWS = """метод ПоСкладам()
    исп Выборка = Запрос{
        ВЫБРАТЬ
            С.Ссылка КАК Ссылка,
            С.Вместимость КАК Вместимость,
            С.Основной КАК Основной,
            С.Основной.Наименование КАК ИмяОсновного,
            С.Основной.Наименование.ЗаменитьNull("") КАК ИмяИлиПусто,
            ВЫБОР КОГДА С.Основной ЕСТЬ NULL ТОГДА ЛОЖЬ ИНАЧЕ ИСТИНА КОНЕЦ КАК ЕстьОсновной
        ИЗ Склады КАК С
    }.Выполнить()
    для Запись из Выборка
        знч Ссылка = Запись.Ссылка как Склады.Ссылка
        знч Объем = Запись.Вместимость как Число
        знч Основной = Запись.Основной как Склады.Ссылка
        знч ОсновнойИлиПусто = Запись.Основной как Склады.Ссылка?
        знч Имя = Запись.ИмяОсновного как Строка
        знч ИмяИлиПусто = Запись.ИмяИлиПусто как Строка
        знч Флаг = Запись.ЕстьОсновной как Булево
    ;
;
"""


@pytest.mark.needs_data  # the mapper parses the module, the reduce reads the type catalog
def test_a_query_row_is_typed_by_the_fields_it_reads():
    found = _found(_project(ROWS))
    assert found == sorted([
        (REDUNDANT, _line(ROWS, "Запись.Ссылка как")),
        (REDUNDANT, _line(ROWS, "Запись.Вместимость как")),
        (NON_NULL, _line(ROWS, "Запись.Основной как Склады.Ссылка\n")),
        (REDUNDANT, _line(ROWS, "Запись.Основной как Склады.Ссылка?")),
        (REDUNDANT, _line(ROWS, "Запись.ИмяИлиПусто как")),
        (REDUNDANT, _line(ROWS, "Запись.ЕстьОсновной как")),
    ])
    # the control: a field read THROUGH a reference may be Null, and no written type holds it
    assert (REDUNDANT, _line(ROWS, "Запись.ИмяОсновного как")) not in found


TABULAR = """метод ПоЯчейкам()
    исп Выборка = Запрос{
        ВЫБРАТЬ Я.Владелец КАК Склад, Я.Партия КАК Партия, Я.Объем КАК Объем,
            КОЛИЧЕСТВО(*) КАК Всего, СУММА(Я.Объем) КАК Сумма
        ИЗ Склады.Ячейки КАК Я
    }.Выполнить()
    знч Первая = Выборка.ПервыйИлиНеопределено()
    знч Склад = Первая!.Склад как Склады.Ссылка
    знч Партия = Первая!.Партия как Партии.Ссылка
    знч Всего = Первая!.Всего как Число
    знч Сумма = Первая!.Сумма как Число
;
"""


@pytest.mark.needs_data
def test_a_tabular_section_row_and_the_aggregates():
    found = _found(_project(TABULAR))
    assert found == sorted([
        (REDUNDANT, _line(TABULAR, "Первая!.Склад")),
        (NON_NULL, _line(TABULAR, "Первая!.Партия")),
        (REDUNDANT, _line(TABULAR, "Первая!.Всего")),
    ])
    # the control: a sum over no rows is Null - not a number the cast could be redundant over


BROKEN = """метод СОшибкой()
    исп Выборка = Запрос{
        ВЫБРАТЬ С.Вместимость КАК Вместимость, С.НетТакогоПоля КАК Поле ИЗ Склады КАК С
    }.Выполнить()
    для Запись из Выборка
        знч Объем = Запись.Вместимость как Число
    ;
;
"""


@pytest.mark.needs_data
def test_a_query_the_compiler_refuses_types_no_column():
    # a field the table does not have fails the whole literal, and the compiler judges no cast
    # over its row - the known column included
    assert _found(_project(BROKEN)) == []


# --- code ---------------------------------------------------------------------------------------

CODE = """структура Позиция
    пер Склад: Склады.Ссылка
    пер Примечание: Строка?
;

метод НайтиСклад(Код: Строка): Склады.Ссылка?
    возврат Неопределено
;

метод Разное(П: Строка?, Место: Склады.Ссылка|Площадки.Ссылка, Любое: Склады.Ссылка|Партии.Ссылка)
    знч Карта = новый Соответствие<Строка, Число>()
    знч Значение = Карта.ПолучитьИлиНеопределено("к")
    знч Первое = Значение! как Число
    знч Второе = Карта.ПолучитьИлиНеопределено("к") как Число
    знч Позиция1 = новый Позиция(Склад = НайтиСклад("1")!, Примечание = Неопределено)
    знч Склад = Позиция1.Склад как Склады.Ссылка
    знч Примечание = Позиция1.Примечание как Строка
    знч Найденный = НайтиСклад("2") как Склады.Ссылка
    знч Хранение = Место как МестаХранения.Ссылка
    знч Разнородное = Любое как МестаХранения.Ссылка
    если П != Неопределено
        знч Строка1 = П как Строка
    ;
;
"""


@pytest.mark.needs_data
def test_generic_members_structures_methods_and_contracts():
    found = _found(_project(CODE))
    assert found == sorted([
        (REDUNDANT, _line(CODE, "Значение! как")),
        (NON_NULL, _line(CODE, 'Карта.ПолучитьИлиНеопределено("к") как')),
        (REDUNDANT, _line(CODE, "Позиция1.Склад как")),
        (NON_NULL, _line(CODE, "Позиция1.Примечание как")),
        (NON_NULL, _line(CODE, 'НайтиСклад("2") как')),
        (REDUNDANT, _line(CODE, "Место как")),
        # the compiler narrows nothing for this check: the value checked above is still `Строка?`
        (NON_NULL, _line(CODE, "П как Строка")),
    ])
    # the control: one member of the union implements no such contract
    assert (REDUNDANT, _line(CODE, "Любое как")) not in found


@pytest.mark.needs_data
def test_the_structure_of_another_module_is_named_with_its_module():
    other = "метод Позиция(): Остатки.Позиция?\n    возврат Неопределено\n;\n"
    reader = ("метод Чтение()\n"
              "    знч Позиция1 = Сводка.Позиция()!\n"
              "    знч Склад = Позиция1.Склад как Склады.Ссылка\n"
              ";\n")
    files = _project(CODE, **{
        "Основное/Сводка.yaml": "ВидЭлемента: ОбщийМодуль\nИмя: Сводка\nОкружение: Сервер\n",
        "Основное/Сводка.xbsl": other,
        "Основное/Чтение.yaml": "ВидЭлемента: ОбщийМодуль\nИмя: Чтение\nОкружение: Сервер\n",
        "Основное/Чтение.xbsl": reader,
    })
    _sources, diags = _lint(files)
    where = [(d.path.replace("\\", "/"), d.line, d.rule_id) for d in diags]
    assert ("Основное/Чтение.xbsl", 3, REDUNDANT) in where


@pytest.mark.needs_data
def test_projects_linted_together_keep_their_names_apart():
    # the same catalog name means another catalog in a second project: there `Вместимость` is text
    other_catalog = WAREHOUSES.replace("Тип: Число", "Тип: Строка")
    module = ROWS
    files = {
        "А/Проект.yaml": "Имя: А\n", "А/Основное/Склады.yaml": WAREHOUSES,
        "А/Основное/Остатки.yaml": MODULE_YAML, "А/Основное/Остатки.xbsl": module,
        "Б/Проект.yaml": "Имя: Б\n", "Б/Основное/Склады.yaml": other_catalog,
        "Б/Основное/Остатки.yaml": MODULE_YAML, "Б/Основное/Остатки.xbsl": module,
    }
    _sources, diags = _lint(files)
    line = _line(ROWS, "Запись.Вместимость как")
    by_file = {(d.path.replace("\\", "/"), d.line) for d in diags if d.rule_id == REDUNDANT}
    assert ("А/Основное/Остатки.xbsl", line) in by_file
    assert ("Б/Основное/Остатки.xbsl", line) not in by_file


LIST_FORM_YAML = """ВидЭлемента: КомпонентИнтерфейса
Имя: СкладыФормаСписка
Наследует:
    Тип: ФормаСписка
Свойства:
    -
        Имя: Список
        Тип: ДинамическийСписок<СкладыФормаСписка.ДанныеСтрокиСписка>
        ЗначениеПоУмолчанию:
            ИмяТипаДанныхСтроки: ДанныеСтрокиСписка
            ОсновнаяТаблица:
                Таблица: Склады
"""

LIST_FORM_XBSL = """метод Открыть(Параметр: СтрокаДинамическогоСписка<СкладыФормаСписка.ДанныеСтрокиСписка>)
    знч Склад = Параметр.Ключ как Склады.Ссылка
    знч Партия = Параметр.Ключ как Партии.Ссылка
;
"""


@pytest.mark.needs_data
def test_the_key_of_a_dynamic_list_row_is_a_reference_of_its_main_table():
    files = _project(ROWS, **{
        "Основное/СкладыФормаСписка.yaml": LIST_FORM_YAML,
        "Основное/СкладыФормаСписка.xbsl": LIST_FORM_XBSL,
    })
    _sources, diags = _lint(files)
    where = sorted((d.rule_id, d.line) for d in diags
                   if d.path.replace("\\", "/") == "Основное/СкладыФормаСписка.xbsl")
    # the control on line 3: the key is no reference of another catalog
    assert where == [(REDUNDANT, 2)]


CARD_YAML = """ВидЭлемента: КомпонентИнтерфейса
Имя: КарточкаСклада
Наследует:
    Тип: Группа
    Содержимое:
        -
            Тип: ПолеВвода<Число>
            Имя: ПолеОбъема
        -
            Тип: ПолеВвода<Число?>
            Имя: ПолеОстатка
"""

CARD_XBSL = """@НаКлиенте
метод Собрать()
    знч Объем = Компоненты.ПолеОбъема.Значение как Число
    знч Остаток = Компоненты.ПолеОстатка.Значение как Число
;
"""


@pytest.mark.needs_data
def test_the_value_of_a_component_is_typed_by_the_paired_markup():
    """The markup types the value the way it does for the guards against the empty value."""
    files = _project(ROWS, **{
        "Основное/КарточкаСклада.yaml": CARD_YAML,
        "Основное/КарточкаСклада.xbsl": CARD_XBSL,
    })
    _sources, diags = _lint(files)
    where = sorted((d.rule_id, d.line) for d in diags
                   if d.path.replace("\\", "/") == "Основное/КарточкаСклада.xbsl")
    assert where == sorted([(REDUNDANT, 3), (NON_NULL, 4)])


OPERATORS = """перечисление Порядок
    Первый,
    Второй
;

конст Лимит = 10

метод Операции(А: Число, Б: Число, П: Строка?, Флаг: Булево)
    знч Сумма = (А + Б) как Число
    знч Строка1 = (А + "шт") как Строка
    знч Строка2 = (П ?? "") как Строка
    знч Выбор = (Флаг ? "а" : "б") как Строка
    знч Смесь = (Флаг ? "а" : 1) как Строка
    знч Список = новый Массив<Строка>()
    знч Первый = Список[0] как Строка
    знч Карта = новый Соответствие<Строка, Число>()
    знч Значение = Карта["к"] как Число
    знч Числа = [1, 2] как Массив<Число>
    знч Предел = Лимит как Число
    знч Место = Порядок.Первый как Порядок
;
"""


@pytest.mark.needs_data
def test_operators_literals_and_indexers_type_their_result():
    found = _found(_project(OPERATORS))
    expected = [(REDUNDANT, _line(OPERATORS, marker)) for marker in (
        "(А + Б) как", '(А + "шт") как', '(П ?? "") как', '(Флаг ? "а" : "б") как',
        "Список[0] как", 'Карта["к"] как', "[1, 2] как", "Лимит как", "Порядок.Первый как")]
    assert found == sorted(expected)
    # the control: a ternary of a string and a number is no string
    assert (REDUNDANT, _line(OPERATORS, '(Флаг ? "а" : 1) как')) not in found


@pytest.mark.needs_data
def test_a_parenthesized_operand_is_reported_at_its_parenthesis():
    _sources, diags = _lint(_project(OPERATORS))
    line = _line(OPERATORS, "(А + Б) как")
    finding = next(d for d in diags if d.line == line)
    assert finding.col == OPERATORS.splitlines()[line - 1].index("(А + Б)") + 1


QUERY_SHAPES = """метод Выборки(Код: Строка)
    исп Выборка = Запрос{
        ВЫБРАТЬ
            С.Вместимость * 2 КАК Двойная,
            С.Наименование + "!" КАК Имя,
            %Код КАК Параметр,
            С.Основной.ЗаменитьNull() КАК ОсновнойИлиПусто,
            О.Вместимость КАК ВместимостьОсновного
        ИЗ Склады КАК С
            ЛЕВОЕ СОЕДИНЕНИЕ Склады КАК О ПО О.Ссылка == С.Основной
    }.Выполнить()
    для Запись из Выборка
        знч Двойная = Запись.Двойная как Число
        знч Имя = Запись.Имя как Строка
        знч Параметр = Запись.Параметр как Строка
        знч Основной = Запись.ОсновнойИлиПусто как Склады.Ссылка
        знч Вместимость = Запись.ВместимостьОсновного как Число
    ;
    исп СОшибкой = Запрос{
        ВЫБРАТЬ С.Вместимость КАК Вместимость ИЗ Склады КАК С ГДЕ С.НетТакогоПоля == 1
    }.Выполнить()
    для Запись из СОшибкой
        знч Объем = Запись.Вместимость как Число
    ;
;
"""


@pytest.mark.needs_data
def test_query_columns_by_operators_parameters_and_joins():
    found = _found(_project(QUERY_SHAPES))
    assert found == sorted([
        (REDUNDANT, _line(QUERY_SHAPES, "Запись.Двойная как")),
        (REDUNDANT, _line(QUERY_SHAPES, "Запись.Имя как")),
        (REDUNDANT, _line(QUERY_SHAPES, "Запись.Параметр как")),
        # `ЗаменитьNull()` keeps the empty value of a nullable field, so the cast only drops it
        (NON_NULL, _line(QUERY_SHAPES, "Запись.ОсновнойИлиПусто как")),
    ])
    # the controls: the joined side of an outer join may be Null, and an unknown field in a
    # condition fails the whole query - the known column included
    assert (REDUNDANT, _line(QUERY_SHAPES, "Запись.ВместимостьОсновного как")) not in found
    assert (REDUNDANT, _line(QUERY_SHAPES, "Запись.Вместимость как")) not in found


# --- the fixes ------------------------------------------------------------------------------------

FIXES = """метод Исправления(Место: Склады.Ссылка|Площадки.Ссылка, Склад: Склады.Ссылка, П: Строка?)
    знч А = Склад как Склады.Ссылка
    знч Б = (Склад как Склады.Ссылка).ВСтроку()
    знч В = (П как Строка) == "а"
    знч Г = (П как Строка).Длина()
    знч Д = Место как МестаХранения.Ссылка
    знч Е = новый Массив<Строка>()
    Е.Добавить(П как Строка)
;
"""


@pytest.mark.needs_data
def test_the_fixes_remove_the_cast_or_put_the_operator():
    fixed = _fixed(_project(FIXES))
    assert "знч А = Склад\n" in fixed
    assert "знч Б = Склад.ВСтроку()" in fixed
    assert 'знч В = П! == "а"' in fixed
    assert "знч Г = П!.Длина()" in fixed
    # a call keeps its own parentheses
    assert "Е.Добавить(П!)" in fixed
    # a target WIDER than the operand is not removed: a declaration may need that type
    assert "знч Д = Место как МестаХранения.Ссылка" in fixed


@pytest.mark.needs_data
def test_the_fixed_module_has_nothing_left_to_fix(tmp_path):
    # the offsets are checked against the text of a FILE: `write_text` on Windows turns `\n`
    # into `\r\n`, and an edit computed over the in-memory string would miss by a line
    root = tmp_path / "Проект"
    for name, content in _project(FIXES).items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    module = root / "Основное" / "Остатки.xbsl"
    paths = sorted(p for p in root.rglob("*") if p.is_file())
    sources = [engine.load(p) for p in paths]
    diags = engine.run_sources(sources, select={REDUNDANT, NON_NULL})
    source = next(s for s in sources if s.path == module)
    own = [d for d in diags if d.path == source.rel]
    fixed = fixer.fix_source(source, own)
    module.write_bytes(fixer.encode(source, fixed.text))
    again = [engine.load(p) for p in paths]
    left = engine.run_sources(again, select={REDUNDANT, NON_NULL})
    text = module.read_bytes().decode("utf-8")
    assert [d.rule_id for d in left] == [REDUNDANT]  # the wider cast stays for the author
    assert "Место как МестаХранения.Ссылка" in text and "П как" not in text


@pytest.mark.needs_data
@pytest.mark.parametrize("previous", ["Склад.ВСтроку()", "знч А = Склад"])
def test_cast_at_statement_start_removes_grouping_parentheses(previous):
    module = ("метод Ф(Склад: Склады.Ссылка)\n    " + previous
              + "\n    (Склад как Склады.Ссылка).ЗагрузитьОбъект()\n;\n")
    fixed = _fixed(_project(module))
    assert "\n    Склад.ЗагрузитьОбъект()\n" in fixed
