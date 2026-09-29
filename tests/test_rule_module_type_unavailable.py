"""code/module-type-unavailable: a type of the module used by a method compiled for a side it lacks.

The cases repeat the verdict of the compiler on probe projects: an interface component, a
command and a common module of both environments, each module with a control name that
certainly does not exist. Every use reported here was refused there under the tag of the side -
`Type "X" is unavailable in the current environment` in a type position, `Variable "X" is not
defined` for an enumeration read as a value - every one passed here compiled, and the project
fixed by the quick fix compiled with the control names alone left. A structure widened to both
sides while a field of it has a client-only type was refused at that field, which is why the
fix is withheld there.
"""

import pytest

from xbsl import engine, i18n
from xbsl.cli import discover
from xbsl.fixer import fix_source

RULE = "code/module-type-unavailable"

# The rule parses the module and reads the term dictionary and the type catalog: without the
# platform data it cannot answer, and in a public clone the tests SKIP rather than fail.
pytestmark = pytest.mark.needs_data

_CARD = """ВидЭлемента: КомпонентИнтерфейса
Ид: 6a0c4a57-0000-4000-8000-000000000011
Имя: КарточкаЗадачи
ОбластьВидимости: ВПодсистеме
Наследует:
    Тип: Форма
"""

_COMMON = """ВидЭлемента: ОбщийМодуль
Ид: 6a0c4a57-0000-4000-8000-000000000012
Имя: Расчеты
ОбластьВидимости: ВПодсистеме
Окружение: {environment}
"""

_TYPES = ('структура ДанныеЗадачи\n'
          '    пер Название: Строка = ""\n'
          ';\n'
          'перечисление Приоритет\n'
          '    Низкий,\n'
          '    Высокий\n'
          ';\n'
          'исключение ОшибкаЗадачи\n'
          ';\n')


def _lint(tmp_path, module, pair=_CARD, name="КарточкаЗадачи"):
    if pair is not None:
        (tmp_path / f"{name}.yaml").write_text(pair, encoding="utf-8", newline="")
    (tmp_path / f"{name}.xbsl").write_text(module, encoding="utf-8", newline="")
    return [d for d in engine.run(discover([str(tmp_path)]), select={RULE}) if d.rule_id == RULE]


def _positions(diags):
    return [(d.line, d.col) for d in diags]


def test_an_unannotated_type_of_a_component_is_unknown_to_its_server_method(tmp_path):
    module = (_TYPES
              + "@НаСервере\n"
              "статический метод Создать()\n"
              "    знч Данные = новый ДанныеЗадачи()\n"
              ";\n")
    diags = _lint(tmp_path, module)
    assert _positions(diags) == [(12, 24)]
    assert "'ДанныеЗадачи'" in diags[0].message and "'Создать'" in diags[0].message
    assert "Тип ДанныеЗадачи недоступен в текущем окружении" in diags[0].message
    assert "@НаСервере @НаКлиенте" in diags[0].message


def test_every_type_position_is_judged(tmp_path):
    module = (_TYPES
              + "@НаСервере\n"
              "статический метод Проверить(Данные: ДанныеЗадачи?, Значение: Объект?): Приоритет?\n"
              "    пер Список = новый Массив<ДанныеЗадачи>()\n"
              "    если Значение это ДанныеЗадачи\n"
              '        выбросить новый ОшибкаЗадачи("текст")\n'
              "    ;\n"
              "    попытка\n"
              "        знч Сделать = () -> новый ДанныеЗадачи()\n"
              "    поймать Ошибка: ОшибкаЗадачи\n"
              "        возврат Неопределено\n"
              "    ;\n"
              "    возврат Неопределено\n"
              ";\n")
    assert _positions(_lint(tmp_path, module)) == [
        (11, 37), (11, 72), (12, 31), (13, 23), (14, 25), (17, 35), (18, 21)]


def test_an_enumeration_read_as_a_value_is_not_defined(tmp_path):
    module = (_TYPES
              + "@НаСервере\n"
              "статический метод Уровень(): Строка\n"
              "    знч Значение = Приоритет.Высокий\n"
              '    возврат "%{Приоритет.Низкий}"\n'
              ";\n")
    diags = _lint(tmp_path, module)
    assert _positions(diags) == [(12, 20), (13, 16)]
    assert all("Переменная Приоритет не определена" in d.message for d in diags)


def test_the_method_sides_follow_its_annotations(tmp_path):
    module = (_TYPES
              + "@НаСервере @НаКлиенте\n"
              "статический метод Оба()\n"
              "    знч Данные = новый ДанныеЗадачи()\n"
              ";\n"
              "@НаСервере @ДоступноСКлиента\n"
              "статический метод Доступный()\n"
              "    знч Данные = новый ДанныеЗадачи()\n"
              ";\n"
              "@НаСервере @Контекстный\n"
              "метод Контекстный()\n"
              "    знч Данные = новый ДанныеЗадачи()\n"
              ";\n")
    assert _positions(_lint(tmp_path, module)) == [(12, 24), (16, 24), (20, 24)]


def test_control_a_client_method_and_a_type_of_both_sides_are_silent(tmp_path):
    module = (_TYPES
              + "@НаСервере @НаКлиенте\n"
              "структура ОбщиеДанные\n"
              '    пер Название: Строка = ""\n'
              ";\n"
              "@НаСервере\n"
              "структура СерверныеДанные\n"
              '    пер Название: Строка = ""\n'
              ";\n"
              "метод Показать()\n"
              "    знч Данные = новый ДанныеЗадачи()\n"
              "    знч Значение = Приоритет.Высокий\n"
              ";\n"
              "@НаСервере\n"
              "статический метод Записать()\n"
              "    знч Общие = новый ОбщиеДанные()\n"
              "    знч Серверные = новый СерверныеДанные()\n"
              ";\n")
    assert _lint(tmp_path, module) == []


def test_a_server_type_used_by_a_client_method_is_the_mirror(tmp_path):
    module = ("@НаСервере\n"
              "структура СерверныеДанные\n"
              '    пер Название: Строка = ""\n'
              ";\n"
              "метод Показать()\n"
              "    знч Данные = новый СерверныеДанные()\n"
              ";\n")
    diags = _lint(tmp_path, module)
    assert _positions(diags) == [(6, 24)]
    assert "объявлен @НаСервере" in diags[0].message
    assert "компилируется для клиента" in diags[0].message


def test_a_module_of_both_environments_judges_the_annotated_types(tmp_path):
    module = ("@НаКлиенте\n"
              "структура КлиентскиеДанные\n"
              '    пер Название: Строка = ""\n'
              ";\n"
              "@НаСервере\n"
              "перечисление СерверныйПриоритет\n"
              "    Низкий\n"
              ";\n"
              "метод Обе()\n"
              "    знч Данные = новый КлиентскиеДанные()\n"
              "    знч Значение = СерверныйПриоритет.Низкий\n"
              ";\n"
              "@НаКлиенте\n"
              "метод Клиентский()\n"
              "    знч Данные = новый КлиентскиеДанные()\n"
              ";\n")
    diags = _lint(tmp_path, module, _COMMON.format(environment="КлиентИСервер"), "Расчеты")
    assert _positions(diags) == [(10, 24), (11, 20)]
    assert "объявлен @НаКлиенте" in diags[0].message
    assert "объявлен @НаСервере" in diags[1].message


def test_a_name_the_method_declares_hides_an_enumeration_value(tmp_path):
    module = (_TYPES
              + "@НаСервере\n"
              "статический метод Уровень(Приоритет: Строка): Строка\n"
              "    возврат Приоритет\n"
              ";\n")
    assert _lint(tmp_path, module) == []


def test_the_modules_the_rule_does_not_judge(tmp_path):
    module = (_TYPES
              + "@НаСервере\n"
              "метод Создать()\n"
              "    знч Данные = новый ДанныеЗадачи()\n"
              ";\n")
    alone, server, broken = (tmp_path / "alone", tmp_path / "server", tmp_path / "broken")
    for folder in (alone, server, broken):
        folder.mkdir()
    # No description beside the module: its environment is unknown.
    assert _lint(alone, module, pair=None) == []
    # A module of the server alone never meets the case.
    assert _lint(server, module, _COMMON.format(environment="Сервер"), "Расчеты") == []
    # A module that does not parse is not judged.
    assert _lint(broken, module + "метод (\n") == []


def _fixed(tmp_path, module, pair=_CARD, name="КарточкаЗадачи"):
    diags = _lint(tmp_path, module, pair, name)
    source = engine.load(tmp_path / f"{name}.xbsl")
    return diags, fix_source(source, diags).text


def test_the_fix_gives_an_unannotated_type_both_sides(tmp_path):
    module = (_TYPES
              + "@НаСервере\n"
              "статический метод Создать(Уровень: Приоритет)\n"
              "    знч Данные = новый ДанныеЗадачи()\n"
              '    выбросить новый ОшибкаЗадачи("текст")\n'
              ";\n")
    diags, text = _fixed(tmp_path, module)
    assert len(diags) == 3 and all(d.fix is not None for d in diags)
    assert text.startswith("@НаСервере @НаКлиенте\nструктура ДанныеЗадачи\n")
    assert "@НаСервере @НаКлиенте\nперечисление Приоритет\n" in text
    assert "@НаСервере @НаКлиенте\nисключение ОшибкаЗадачи\n" in text
    (tmp_path / "КарточкаЗадачи.xbsl").write_text(text, encoding="utf-8", newline="")
    assert [d for d in engine.run(discover([str(tmp_path)]), select={RULE})] == []


def test_the_fix_adds_the_missing_annotation_beside_the_one_there(tmp_path):
    module = ("@ВПодсистеме @НаКлиенте\n"
              "структура КлиентскиеДанные\n"
              '    пер Название: Строка = ""\n'
              ";\n"
              "@НаСервере\n"
              "метод Серверный()\n"
              "    знч Данные = новый КлиентскиеДанные()\n"
              ";\n")
    _diags, text = _fixed(tmp_path, module, _COMMON.format(environment="КлиентИСервер"),
                          "Расчеты")
    assert text.startswith("@ВПодсистеме @НаКлиенте @НаСервере\nструктура КлиентскиеДанные\n")


def test_the_fix_is_withheld_where_a_field_would_not_exist_on_the_other_side(tmp_path):
    module = ("структура ДанныеЭлемента\n"
              "    пер Элемент: Компонент? = Неопределено\n"
              ";\n"
              "структура ДанныеСписка\n"
              "    пер Строки: Массив<ДанныеЭлемента> = []\n"
              ";\n"
              "структура ДанныеРасчета\n"
              "    пер Сумма = Мин(1, 2)\n"
              ";\n"
              "@НаСервере\n"
              "статический метод Создать()\n"
              "    знч Элемент = новый ДанныеЭлемента()\n"
              "    знч Список = новый ДанныеСписка()\n"
              "    знч Расчет = новый ДанныеРасчета()\n"
              ";\n")
    diags = _lint(tmp_path, module)
    assert _positions(diags) == [(12, 25), (13, 24), (14, 24)]
    assert [d.fix for d in diags] == [None, None, None]


def test_the_english_spelling_is_judged_and_fixed_in_english(tmp_path):
    i18n.set_lang("en")
    card = ("ElementKind: InterfaceComponent\n"
            "Id: 6a0c4a57-0000-4000-8000-000000000013\n"
            "Name: TaskCard\n"
            "VisibilityScope: InSubsystem\n"
            "Inherits:\n"
            "    Type: Form\n")
    module = ("enum Priority\n"
              "    Low,\n"
              "    High\n"
              ";\n"
              "@OnServer @AvailableFromClient\n"
              "static method Level()\n"
              "    val Value = Priority.High\n"
              ";\n")
    diags, text = _fixed(tmp_path, module, card, "TaskCard")
    assert _positions(diags) == [(7, 17)]
    assert "Variable Priority is not defined" in diags[0].message
    assert "@OnServer @OnClient" in diags[0].message
    assert text.startswith("@OnServer @OnClient\nenum Priority\n")
