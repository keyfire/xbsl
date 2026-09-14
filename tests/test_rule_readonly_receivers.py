"""A `знч` field written through a typed receiver, and a `исп` resource handed out by `возврат`.

Both live in xbsl/rules/readonly_targets.py. The forms and their controls repeat what the IDE
language server answered on probe projects.
"""

import pytest

from xbsl.engine import load_text, run_sources

pytestmark = pytest.mark.needs_data  # the rules parse the module; the lexer reads the data

READONLY = "code/assign-readonly"
RETURN = "code/return-use-resource"

_CELL = (
    "структура Ячейка\n"
    "    пер Значение: Число = 0\n"
    "    знч Метка: Строка = \"\"\n"
    "    обз знч Код: Число\n"
    ";\n"
    "\n"
    "исключение ИсключениеЯчейки\n"
    "    знч Уровень: Число = 0\n"
    ";\n"
    "\n"
)


def _diags(code: str, rule: str) -> list:
    return run_sources([load_text("Модуль.xbsl", code)], select={rule}, scopes=("file",))


def _places(code: str, rule: str) -> list[tuple[int, int]]:
    return [(d.line, d.col) for d in _diags(code, rule)]


# --- code/assign-readonly through a receiver ----------------------------------------------------


def test_val_field_through_parameter_local_and_catch_variable():
    code = _CELL + (
        "метод Проба(Я: Ячейка, Искл: ИсключениеЯчейки, Пустая: Ячейка?): Число\n"
        "    Я.Метка = \"а\"\n"
        "    Я.Метка += \"б\"\n"
        "    Я.Код = 1\n"
        "    Искл.Уровень = 2\n"
        "    знч Своя = новый Ячейка(Код = 1)\n"
        "    Своя.Метка = \"в\"\n"
        "    пер Типизированная: Ячейка = новый Ячейка(Код = 2)\n"
        "    Типизированная.Метка = \"г\"\n"
        "    Пустая!.Метка = \"д\"\n"
        "    попытка\n"
        "        Я.Значение = 3\n"
        "    поймать Пойманное: ИсключениеЯчейки\n"
        "        Пойманное.Уровень = 4\n"
        "    ;\n"
        "    возврат Я.Значение\n"
        ";\n"
    )
    diags = _diags(code, READONLY)
    assert [(d.line, d.col) for d in diags] == [
        (12, 7), (13, 7), (14, 7), (15, 10), (17, 10), (19, 20), (20, 13), (24, 19),
    ]
    assert all(d.fix is None for d in diags)
    assert "'Метка'" in diags[0].message


def test_receivers_the_file_does_not_type_stay_silent():
    code = _CELL + (
        "метод Создать(): Ячейка\n"
        "    возврат новый Ячейка(Код = 1)\n"
        ";\n"
        "\n"
        "метод Проба(Я: Ячейка, Пустая: Ячейка?, Ячейки: Массив<Ячейка>,\n"
        "    Внешний: Задачи.Объект): Число\n"
        "    Я.Значение = 1\n"
        "    Пустая?.Метка = \"а\"\n"
        "    знч Полученная = Создать()\n"
        "    Полученная.Метка = \"б\"\n"
        "    для Эл из Ячейки\n"
        "        Эл.Метка = \"в\"\n"
        "    ;\n"
        "    Ячейки.ДляКаждого(Эл -> Эл.Метка = \"г\")\n"
        "    Внешний.Метка = \"д\"\n"
        "    возврат 0\n"
        ";\n"
    )
    assert _diags(code, READONLY) == []


def test_receiver_english_spelling():
    code = (
        "structure Cell\n"
        "    val Tag: String = \"\"\n"
        ";\n"
        "\n"
        "method Probe(Item: Cell)\n"
        "    Item.Tag = \"a\"\n"
        ";\n"
    )
    assert _places(code, READONLY) == [(6, 10)]


# --- code/return-use-resource ---------------------------------------------------------------------


def test_returned_resource_through_the_forms_that_pass_it_on():
    code = (
        "метод Проба(Данные: Байты, Флаг: Булево, Другой: ПотокЧтения?): ПотокЧтения?\n"
        "    исп Поток = ПотокЧтения.ИзБайтов(Данные)\n"
        "    если Флаг\n"
        "        возврат (Поток)\n"
        "    ;\n"
        "    если Другой == Неопределено\n"
        "        возврат Флаг ? Поток : Другой\n"
        "    ;\n"
        "    если Флаг\n"
        "        возврат Другой ?? Поток\n"
        "    ;\n"
        "    если Флаг\n"
        "        возврат Поток как ПотокЧтения\n"
        "    ;\n"
        "    возврат Поток!\n"
        ";\n"
    )
    diags = _diags(code, RETURN)
    assert [(d.line, d.col) for d in diags] == [(4, 18), (7, 24), (10, 27), (13, 17), (15, 13)]
    assert all(d.severity.value == "error" for d in diags)
    assert "'Поток'" in diags[0].message


def test_resource_returned_from_a_full_lambda():
    code = (
        "метод Проба(Данные: Байты): Число\n"
        "    исп Поток = ПотокЧтения.ИзБайтов(Данные)\n"
        "    знч Получить = метод() ->\n"
        "        возврат Поток\n"
        "    ;\n"
        "    возврат Получить().Размер()\n"
        ";\n"
    )
    assert _places(code, RETURN) == [(4, 17)]


def test_what_is_read_from_the_resource_may_be_returned():
    code = (
        "метод Проба(Данные: Байты): Число\n"
        "    исп Поток = ПотокЧтения.ИзБайтов(Данные)\n"
        "    знч Копия = Поток\n"
        "    если Данные.Размер() > 0\n"
        "        возврат Копия.Размер()\n"
        "    ;\n"
        "    возврат Поток.Размер()\n"
        ";\n"
        "\n"
        "метод Открыть(Данные: Байты): ПотокЧтения\n"
        "    знч Поток = ПотокЧтения.ИзБайтов(Данные)\n"
        "    возврат Поток\n"
        ";\n"
    )
    assert _diags(code, RETURN) == []


def test_return_use_resource_english_spelling():
    code = (
        "method Probe(Data: Bytes): ReadableStream\n"
        "    use Stream = ReadableStream.FromBytes(Data)\n"
        "    return Stream\n"
        ";\n"
    )
    assert _places(code, RETURN) == [(3, 12)]
