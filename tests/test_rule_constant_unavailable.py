"""code/constant-unavailable: a module constant read by a method compiled for a side it lacks.

The cases repeat the verdict of the compiler on one probe project: an interface component, a
command and a common module of both environments, each module with a control name that
certainly does not exist. Every reference reported here was refused there with
`Variable "X" is not defined` under the tag of the side, every one passed here compiled, and the
project fixed by the quick fix compiled with the control names alone left.
"""

import pytest

from xbsl import engine, i18n
from xbsl.cli import discover
from xbsl.fixer import fix_source

RULE = "code/constant-unavailable"

# The rule parses the module and reads the term dictionary: without the platform data it cannot
# answer, and in a public clone the tests SKIP rather than fail.
pytestmark = pytest.mark.needs_data

_CARD = """ВидЭлемента: КомпонентИнтерфейса
Ид: 6a0c4a57-0000-4000-8000-000000000001
Имя: КарточкаЗадачи
ОбластьВидимости: ВПодсистеме
Наследует:
    Тип: Форма
"""

_COMMON = """ВидЭлемента: ОбщийМодуль
Ид: 6a0c4a57-0000-4000-8000-000000000002
Имя: Расчеты
ОбластьВидимости: ВПодсистеме
Окружение: {environment}
"""

_CATALOG = """ВидЭлемента: Справочник
Ид: 6a0c4a57-0000-4000-8000-000000000003
Имя: Задачи
ОбластьВидимости: ВПодсистеме
"""


def _lint(tmp_path, module, pair=_CARD, name="КарточкаЗадачи"):
    if pair is not None:
        (tmp_path / f"{name}.yaml").write_text(pair, encoding="utf-8", newline="")
    (tmp_path / f"{name}.xbsl").write_text(module, encoding="utf-8", newline="")
    return [d for d in engine.run(discover([str(tmp_path)]), select={RULE}) if d.rule_id == RULE]


def _positions(diags):
    return [(d.line, d.col) for d in diags]


def test_an_unannotated_constant_of_a_component_is_unknown_to_its_server_method(tmp_path):
    module = ('конст ПРЕФИКС = "З-"\n'
              "\n"
              "@НаСервере @ДоступноСКлиента\n"
              "статический метод Номер(): Строка\n"
              "    возврат ПРЕФИКС\n"
              ";\n")
    diags = _lint(tmp_path, module)
    assert _positions(diags) == [(5, 13)]
    assert "'ПРЕФИКС'" in diags[0].message and "'Номер'" in diags[0].message
    assert "Переменная ПРЕФИКС не определена" in diags[0].message
    assert "@НаСервере @НаКлиенте" in diags[0].message


def test_every_method_compiled_for_the_server_is_judged(tmp_path):
    module = ('конст ПРЕФИКС = "З-"\n'
              "@НаСервере\n"
              "статический метод Один(): Строка\n"
              "    возврат ПРЕФИКС\n"
              ";\n"
              "@НаСервере @НаКлиенте\n"
              "статический метод Два(): Строка\n"
              "    возврат ПРЕФИКС\n"
              ";\n"
              "@НаСервере @Контекстный\n"
              "метод Три(): Строка\n"
              "    возврат ПРЕФИКС\n"
              ";\n"
              "@НаСервере\n"
              "статический метод Четыре(): Строка\n"
              "    знч Получить = () -> ПРЕФИКС\n"
              "    возврат Получить()\n"
              ";\n")
    assert _positions(_lint(tmp_path, module)) == [(4, 13), (8, 13), (12, 13), (16, 26)]


def test_control_a_client_method_and_a_constant_the_server_has_are_silent(tmp_path):
    module = ('конст ПРЕФИКС = "З-"\n'
              "@НаСервере\n"
              'конст СУФФИКС = "-С"\n'
              "@НаСервере @НаКлиенте\n"
              'конст РАЗДЕЛИТЕЛЬ = "/"\n'
              "метод Показать(): Строка\n"
              "    возврат ПРЕФИКС + РАЗДЕЛИТЕЛЬ\n"
              ";\n"
              "@НаСервере @ДоступноСКлиента\n"
              "статический метод Номер(): Строка\n"
              "    возврат СУФФИКС + РАЗДЕЛИТЕЛЬ\n"
              ";\n")
    assert _lint(tmp_path, module) == []


def test_a_server_constant_read_by_a_client_method_is_the_mirror(tmp_path):
    module = ("@НаСервере\n"
              'конст СУФФИКС = "-С"\n'
              "метод Показать(): Строка\n"
              "    возврат СУФФИКС\n"
              ";\n")
    diags = _lint(tmp_path, module)
    assert _positions(diags) == [(4, 13)]
    assert "объявлена @НаСервере" in diags[0].message
    assert "компилируется для клиента" in diags[0].message


def test_a_module_of_both_environments_judges_the_annotated_constants(tmp_path):
    module = ("@НаКлиенте\n"
              'конст ПРЕФИКС = "З-"\n'
              "@НаСервере\n"
              'конст СУФФИКС = "-С"\n'
              'конст РАЗДЕЛИТЕЛЬ = "/"\n'
              "метод Обе(): Строка\n"
              "    возврат ПРЕФИКС + СУФФИКС + РАЗДЕЛИТЕЛЬ\n"
              ";\n"
              "@НаСервере\n"
              "метод Серверный(): Строка\n"
              "    возврат ПРЕФИКС + РАЗДЕЛИТЕЛЬ\n"
              ";\n"
              "@НаКлиенте\n"
              "метод Клиентский(): Строка\n"
              "    возврат СУФФИКС + РАЗДЕЛИТЕЛЬ\n"
              ";\n")
    diags = _lint(tmp_path, module, _COMMON.format(environment="КлиентИСервер"), "Расчеты")
    assert _positions(diags) == [(7, 13), (7, 23), (11, 13), (15, 13)]
    assert "объявлена @НаКлиенте" in diags[0].message
    assert "объявлена @НаСервере" in diags[1].message


def test_a_constant_named_inside_a_string_is_read_too(tmp_path):
    module = ('конст ПРЕФИКС = "З-"\n'
              "@НаСервере\n"
              "статический метод Номер(Задача: Строка): Строка\n"
              '    знч Короткая = "%ПРЕФИКС"\n'
              '    знч Полная = "%{ПРЕФИКС + Задача}"\n'
              '    знч Экранированная = "\\%ПРЕФИКС"\n'
              '    знч Член = "%{Задача.ПРЕФИКС}"\n'
              "    возврат Короткая + Полная + Экранированная + Член\n"
              ";\n")
    assert _positions(_lint(tmp_path, module)) == [(4, 22), (5, 21)]


def test_a_name_the_method_declares_hides_the_constant(tmp_path):
    module = ('конст ПРЕФИКС = "З-"\n'
              "@НаСервере\n"
              "статический метод Один(ПРЕФИКС: Строка): Строка\n"
              "    возврат ПРЕФИКС\n"
              ";\n"
              "@НаСервере\n"
              "статический метод Два(): Строка\n"
              '    знч ПРЕФИКС = "Д-"\n'
              "    возврат ПРЕФИКС\n"
              ";\n")
    assert _lint(tmp_path, module) == []


def test_the_modules_the_rule_does_not_judge(tmp_path):
    module = ('конст ПРЕФИКС = "З-"\n'
              "@НаСервере\n"
              "метод Номер(): Строка\n"
              "    возврат ПРЕФИКС\n"
              ";\n")
    alone, catalog, client = (tmp_path / "alone", tmp_path / "catalog", tmp_path / "client")
    for folder in (alone, catalog, client):
        folder.mkdir()
    # No description beside the module: its environment is unknown.
    assert _lint(alone, module, pair=None) == []
    # A module of the server alone never meets the case.
    assert _lint(catalog, module, _CATALOG, "Задачи") == []
    # A common module of the client alone refuses the server annotation by itself.
    assert _lint(client, module, _COMMON.format(environment="Клиент"), "Расчеты") == []


def _fixed(tmp_path, module, pair=_CARD, name="КарточкаЗадачи"):
    diags = _lint(tmp_path, module, pair, name)
    source = engine.load(tmp_path / f"{name}.xbsl")
    return diags, fix_source(source, diags).text


def test_the_fix_gives_an_unannotated_constant_both_sides_once(tmp_path):
    module = ('конст ПРЕФИКС = "З-"\n'
              "@НаСервере\n"
              "статический метод Один(): Строка\n"
              "    возврат ПРЕФИКС\n"
              ";\n"
              "@НаСервере\n"
              "статический метод Два(): Строка\n"
              "    возврат ПРЕФИКС\n"
              ";\n")
    diags, text = _fixed(tmp_path, module)
    assert len(diags) == 2 and diags[0].fix == diags[1].fix
    assert text.startswith('@НаСервере @НаКлиенте\nконст ПРЕФИКС = "З-"\n@НаСервере\n')
    (tmp_path / "КарточкаЗадачи.xbsl").write_text(text, encoding="utf-8", newline="")
    assert [d for d in engine.run(discover([str(tmp_path)]), select={RULE})] == []


def test_the_fix_adds_the_missing_annotation_beside_the_one_there(tmp_path):
    module = ("@ВПодсистеме @НаКлиенте\n"
              'конст ПРЕФИКС = "З-"\n'
              "@НаСервере\n"
              "метод Серверный(): Строка\n"
              "    возврат ПРЕФИКС\n"
              ";\n")
    _diags, text = _fixed(tmp_path, module, _COMMON.format(environment="КлиентИСервер"),
                          "Расчеты")
    assert text.startswith('@ВПодсистеме @НаКлиенте @НаСервере\nконст ПРЕФИКС = "З-"\n')


def test_the_english_spelling_is_judged_and_fixed_in_english(tmp_path):
    i18n.set_lang("en")
    card = ("ElementKind: InterfaceComponent\n"
            "Id: 6a0c4a57-0000-4000-8000-000000000004\n"
            "Name: TaskCard\n"
            "VisibilityScope: InSubsystem\n"
            "Inherits:\n"
            "    Type: Form\n")
    module = ('const PREFIX = "T-"\n'
              "@OnServer @AvailableFromClient\n"
              "static method Number(): String\n"
              "    return PREFIX\n"
              ";\n")
    diags, text = _fixed(tmp_path, module, card, "TaskCard")
    assert _positions(diags) == [(4, 12)]
    assert "Variable PREFIX is not defined" in diags[0].message
    assert "@OnServer @OnClient" in diags[0].message
    assert text.startswith('@OnServer @OnClient\nconst PREFIX = "T-"\n')
