"""code/qualified-member-unavailable: `Module.NAME` of a common module of both environments read
by a method compiled for a side the declaration lacks.

The cases repeat the verdict of the compiler on probe projects: a common module of both
environments declared constants, structures and enumerations for one side each, and a server
common module, an HTTP service, a component and a command reached them by the qualified name.
Every use reported here was refused there - `Unknown property "Module.NAME"` for a constant or
an enumeration read as a value, `Type "Module.Name" is unavailable in the current environment`
in a type position - and every one passed here compiled. A declaration without a visibility
annotation fails outside its module on the visibility first, and is left alone.
"""

import pytest

from xbsl import engine, i18n
from xbsl.cli import discover

RULE = "code/qualified-member-unavailable"

# The rule parses the modules and reads the term dictionary: without the platform data it
# cannot answer, and in a public clone the tests SKIP rather than fail.
pytestmark = pytest.mark.needs_data

_COMMON = """ВидЭлемента: ОбщийМодуль
Ид: 6a0c4a57-0000-4000-8000-0000000000{number}
Имя: {name}
ОбластьВидимости: ВПодсистеме
Окружение: {environment}
"""

_CARD = """ВидЭлемента: КомпонентИнтерфейса
Ид: 6a0c4a57-0000-4000-8000-000000000031
Имя: КарточкаЗадачи
ОбластьВидимости: ВПодсистеме
Наследует:
    Тип: Форма
"""

_SERVICE = """ВидЭлемента: HttpСервис
Ид: 6a0c4a57-0000-4000-8000-000000000032
Имя: СервисЗадач
ОбластьВидимости: ВПодсистеме
КорневойUrl: /tasks
"""

_DECLARATIONS = ("@ВПроекте @НаКлиенте\n"
                 'конст ПРЕФИКС = "З-"\n'
                 "@ВПроекте @НаСервере\n"
                 'конст СУФФИКС = "-С"\n'
                 "@ВПроекте\n"
                 'конст РАЗДЕЛИТЕЛЬ = "/"\n'
                 "@ВПроекте @НаКлиенте\n"
                 "структура ДанныеКлиента\n"
                 '    пер Название: Строка = ""\n'
                 ";\n"
                 "@ВПроекте @НаКлиенте\n"
                 "перечисление Уровень\n"
                 "    Низкий,\n"
                 "    Высокий\n"
                 ";\n"
                 "@НаКлиенте\n"
                 'конст ЛОКАЛЬНАЯ = "Л"\n')


def _write(folder, name, pair, module):
    (folder / f"{name}.yaml").write_text(pair, encoding="utf-8", newline="")
    (folder / f"{name}.xbsl").write_text(module, encoding="utf-8", newline="")


def _lint(tmp_path, *modules, declarations=_DECLARATIONS, environment="КлиентИСервер"):
    _write(tmp_path, "Расчеты", _COMMON.format(number="30", name="Расчеты",
                                               environment=environment), declarations)
    for name, pair, module in modules:
        _write(tmp_path, name, pair, module)
    return [d for d in engine.run(discover([str(tmp_path)]), select={RULE}) if d.rule_id == RULE]


def _server(module):
    return ("Сервер", _COMMON.format(number="33", name="Сервер", environment="Сервер"), module)


def _found(diags):
    return [(d.path.replace("\\", "/").rsplit("/", 1)[-1], d.line, d.col) for d in diags]


def test_a_client_constant_read_by_server_code_is_unknown_there(tmp_path):
    diags = _lint(tmp_path, _server("метод Префикс(): Строка\n"
                                    "    возврат Расчеты.ПРЕФИКС\n"
                                    ";\n"))
    assert _found(diags) == [("Сервер.xbsl", 2, 21)]
    message = diags[0].message
    assert "'Расчеты.ПРЕФИКС' (константа) есть только на клиенте" in message
    assert "Неизвестное свойство Расчеты.ПРЕФИКС" in message and "'Префикс'" in message


def test_every_server_side_reader_is_judged(tmp_path):
    card = ("@НаСервере\n"
            "статический метод Серверный(): Строка\n"
            "    возврат Расчеты.ПРЕФИКС\n"
            ";\n"
            "метод Клиентский(): Строка\n"
            "    возврат Расчеты.ПРЕФИКС\n"
            ";\n")
    service = ("метод Префикс(): Строка\n"
               '    возврат "%{Расчеты.ПРЕФИКС}"\n'
               ";\n")
    diags = _lint(tmp_path, ("КарточкаЗадачи", _CARD, card), ("СервисЗадач", _SERVICE, service))
    assert _found(diags) == [("КарточкаЗадачи.xbsl", 3, 21), ("СервисЗадач.xbsl", 2, 24)]


def test_a_server_constant_read_by_client_code_is_the_mirror(tmp_path):
    card = ("метод Показать(): Строка\n"
            "    возврат Расчеты.СУФФИКС + Расчеты.РАЗДЕЛИТЕЛЬ\n"
            ";\n")
    diags = _lint(tmp_path, ("КарточкаЗадачи", _CARD, card))
    assert _found(diags) == [("КарточкаЗадачи.xbsl", 2, 21)]
    assert "есть только на сервере" in diags[0].message
    assert "компилируется для клиента" in diags[0].message


def test_types_and_enumerations_are_judged_where_the_compiler_points(tmp_path):
    module = ("метод Создать(Уровень: Расчеты.Уровень?)\n"
              "    знч Данные = новый Расчеты.ДанныеКлиента()\n"
              "    пер Пустые: Расчеты.ДанныеКлиента? = Неопределено\n"
              "    знч Высокий = Расчеты.Уровень.Высокий\n"
              ";\n")
    diags = _lint(tmp_path, _server(module))
    assert _found(diags) == [("Сервер.xbsl", 1, 24), ("Сервер.xbsl", 2, 24),
                             ("Сервер.xbsl", 3, 17), ("Сервер.xbsl", 4, 27)]
    assert "(перечисление)" in diags[0].message
    assert "Тип Расчеты.ДанныеКлиента недоступен в текущем окружении" in diags[1].message
    assert "Неизвестное свойство Расчеты.Уровень" in diags[3].message


def test_the_declaring_module_reaching_itself_is_judged_too(tmp_path):
    declarations = _DECLARATIONS + ("@НаСервере\n"
                                    "метод Серверный(): Строка\n"
                                    "    возврат Расчеты.ЛОКАЛЬНАЯ + Расчеты.РАЗДЕЛИТЕЛЬ\n"
                                    ";\n")
    diags = _lint(tmp_path, declarations=declarations)
    assert _found(diags) == [("Расчеты.xbsl", 20, 21)]


def test_control_what_the_rule_leaves_alone(tmp_path):
    module = ("метод Разное(Расчеты: Строка): Строка\n"
              "    возврат Расчеты\n"
              ";\n"
              "метод Общее(): Строка\n"
              "    возврат Расчеты.РАЗДЕЛИТЕЛЬ + Расчеты.ЛОКАЛЬНАЯ + Расчеты.Посчитать()\n"
              ";\n"
              "метод Скрытое(): Строка\n"
              '    знч Расчеты = "текст"\n'
              "    возврат Расчеты.ПРЕФИКС\n"
              ";\n")
    # A declaration of both sides, a local one (its visibility fails first), a method (not
    # judged) and a name the method declares for itself are all silent.
    assert _lint(tmp_path, _server(module)) == []


def test_a_module_of_one_environment_declares_nothing_here(tmp_path):
    reader = _server("метод Префикс(): Строка\n"
                     "    возврат Расчеты.ПРЕФИКС\n"
                     ";\n")
    assert _lint(tmp_path, reader, environment="Клиент") == []


def test_the_english_spelling_is_judged(tmp_path):
    i18n.set_lang("en")
    declarations = ("@InProject @OnClient\n"
                    'const PREFIX = "T-"\n')
    common = ("ElementKind: CommonModule\n"
              "Id: 6a0c4a57-0000-4000-8000-000000000034\n"
              "Name: Calculations\n"
              "VisibilityScope: InSubsystem\n"
              "Environment: ClientAndServer\n")
    server = ("ElementKind: CommonModule\n"
              "Id: 6a0c4a57-0000-4000-8000-000000000035\n"
              "Name: ServerSide\n"
              "VisibilityScope: InSubsystem\n"
              "Environment: Server\n")
    _write(tmp_path, "Calculations", common, declarations)
    _write(tmp_path, "ServerSide", server, "method Prefix(): String\n"
                                            "    return Calculations.PREFIX\n"
                                            ";\n")
    diags = [d for d in engine.run(discover([str(tmp_path)]), select={RULE})]
    assert _found(diags) == [("ServerSide.xbsl", 2, 25)]
    assert "'Calculations.PREFIX' (a constant) exists on the client only" in diags[0].message
    assert "Unknown property Calculations.PREFIX" in diags[0].message
