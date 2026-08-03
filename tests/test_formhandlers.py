"""Event handlers of the form designer (xbsl/formhandlers.py).

The module model (top-level methods via the full parser), the event signature parsing,
the generic grounding and the two-file add_handler operation. Tests that parse XBSL code
need the language data (the parser sits on the lexer) and carry the needs_data marker;
the signature/stub logic and the created-module flows are data-free.
"""

import pytest

from xbsl import formhandlers
from xbsl.formmodel import FormModelError

YAML = """\
ВидЭлемента: КомпонентИнтерфейса
Ид: 6f0b6a44-0000-4000-8000-000000000104
Имя: Витрина
ОбластьВидимости: ВПодсистеме
Наследует:
    Тип: Форма
    Заголовок: Витрина
    Содержимое:
        Тип: Группа
        Компоновка: Вертикальная
        Содержимое:
            -
                Тип: ПолеВвода<Строка>
                Имя: Ввод
                Значение: =Титул
            -
                Тип: Кнопка
                Имя: КнопкаОк
                Заголовок: Ок
            -
                Тип: Надпись
                Значение: Подпись
Свойства:
    -
        Имя: Титул
        Тип: Строка
"""

GRP = "Наследует/Содержимое[0]"
FIELD = GRP + "/Содержимое[0]"
BUTTON = GRP + "/Содержимое[1]"
LABEL = GRP + "/Содержимое[2]"

MODULE = """\
@НаСервере @ДоступноСКлиента
метод Загрузить(Ключ: Строка): Строка
    возврат Ключ
;

@НаКлиенте @Локально
метод Обновить()
;

статический метод Хелпер()
;
"""

SIG_CLICK = "(Кнопка, СобытиеПриНажатии)->ничто"
SIG_CHANGE = "(ПолеВвода<ТипДанных>, СобытиеПриИзменении<ТипДанных>)->ничто"


def rebuilt(original: str, edits, new_text: str) -> bool:
    """The acceptance guarantee: nothing outside the reported edit ranges changed."""
    out, pos = [], 0
    for e in sorted(edits, key=lambda e: e.start):
        out.append(original[pos : e.start])
        out.append(e.new_text)
        pos = e.end
    out.append(original[pos:])
    return "".join(out) == new_text


# --- the module model -----------------------------------------------------------------------


@pytest.mark.needs_data
def test_module_methods_shape():
    methods, errors = formhandlers.module_methods(MODULE)
    assert errors == 0
    assert [m["name"] for m in methods] == ["Загрузить", "Обновить", "Хелпер"]
    load = methods[0]
    assert load["annotations"] == ["НаСервере", "ДоступноСКлиента"]
    assert load["visibility"] is None
    assert load["params"] == [{"name": "Ключ", "type": "Строка"}]
    assert load["returnType"] == "Строка"
    assert load["static"] is False and load["abstract"] is False
    # the span covers the annotations; nameSpan is the method name token
    assert MODULE[load["span"]["start"] : load["span"]["end"]].startswith("@НаСервере")
    assert MODULE[load["nameSpan"]["start"] : load["nameSpan"]["end"]] == "Загрузить"
    refresh = methods[1]
    assert refresh["visibility"] == "Локально"
    helper = methods[2]
    assert helper["static"] is True
    assert MODULE[helper["nameSpan"]["start"] : helper["nameSpan"]["end"]] == "Хелпер"


@pytest.mark.needs_data
def test_module_methods_skips_nested_and_counts_errors():
    text = (
        "структура Настройки\n"
        "    метод Внутри()\n"
        "    ;\n"
        ";\n"
        "\n"
        "метод Снаружи()\n"
        ";\n"
        "\n"
        "метод Оборванный(\n"
    )
    methods, errors = formhandlers.module_methods(text)
    names = [m["name"] for m in methods]
    assert "Снаружи" in names and "Внутри" not in names
    assert errors > 0
    assert formhandlers.module_methods("") == ([], 0)


def test_module_path_for(tmp_path):
    assert formhandlers.module_path_for(tmp_path / "Форма.yaml") == tmp_path / "Форма.xbsl"


# --- event signatures -------------------------------------------------------------------


def test_parse_event_signature():
    assert formhandlers.parse_event_signature(SIG_CLICK) == (
        ["Кнопка", "СобытиеПриНажатии"], "ничто",
    )
    # generic arguments keep their internal commas
    args, ret = formhandlers.parse_event_signature(
        "(XYДиаграмма<ТипДанных, ТипСерии>, СобытиеПриНажатии<ТипДанных>)->ничто"
    )
    assert args == ["XYДиаграмма<ТипДанных, ТипСерии>", "СобытиеПриНажатии<ТипДанных>"]
    # the nullable functional wrapping and a non-ничто return
    assert formhandlers.parse_event_signature("((ОписаниеЗадания)->Булево)?") == (
        ["ОписаниеЗадания"], "Булево",
    )
    assert formhandlers.parse_event_signature("()->ничто") == ([], "ничто")
    # garbage degrades to a parameterless stub, not an error
    assert formhandlers.parse_event_signature("мусор") == ([], None)
    assert formhandlers.parse_event_signature("") == ([], None)


def test_generic_grounding():
    mapping = formhandlers._generic_map("ПолеВвода<ТипДанных>", "ПолеВвода<Массив<Строка>>")
    assert mapping == {"ТипДанных": "Массив<Строка>"}
    assert formhandlers._substitute("СобытиеПриИзменении<ТипДанных>", mapping) == (
        "СобытиеПриИзменении<Массив<Строка>>"
    )
    # facet references after the formal are kept
    assert formhandlers._substitute(
        "Событие<ТипИсточника.NodesDataType>", {"ТипИсточника": "Проект"}
    ) == "Событие<Проект.NodesDataType>"
    # no grounding when the roots differ or either side is not generic
    assert formhandlers._generic_map("Кнопка", "Кнопка") == {}
    assert formhandlers._generic_map("ПолеВвода<Т>", "Кнопка<Строка>") == {}
    assert formhandlers._generic_map("ПолеВвода<А, Б>", "ПолеВвода<Строка>") == {}


# --- add_handler ------------------------------------------------------------------------


def test_add_handler_creates_module_file():
    plan = formhandlers.add_handler(YAML, None, BUTTON, "ПриНажатии",
                                    event_signature=SIG_CLICK)
    assert plan.created is True and plan.method_added is True
    assert plan.method == "КнопкаОкПриНажатии"
    # the new module is the stub alone: no annotation (handlers are bound by name),
    # the accepted parameter names, written types
    assert plan.new_module_text == (
        "метод КнопкаОкПриНажатии(Источник: Кнопка, Событие: СобытиеПриНажатии)\n"
        "    // TODO: действия обработчика\n"
        ";\n"
    )
    assert plan.module_edits == []
    # the yaml half is a normal set_property edit
    assert rebuilt(YAML, plan.yaml_edits, plan.new_yaml_text)
    assert "ПриНажатии: КнопкаОкПриНажатии" in plan.new_yaml_text
    # the cursor lands on the method name
    at = plan.cursor_offset
    assert plan.new_module_text[at : at + len(plan.method)] == plan.method


def test_add_handler_generic_signature_grounded_by_node_type():
    plan = formhandlers.add_handler(YAML, None, FIELD, "ПриИзменении",
                                    event_signature=SIG_CHANGE)
    assert plan.new_module_text.splitlines()[0] == (
        "метод ВводПриИзменении(Источник: ПолеВвода<Строка>, "
        "Событие: СобытиеПриИзменении<Строка>)"
    )


def test_add_handler_name_defaults_and_unknown_signature(monkeypatch):
    # no Имя on the node - the type root names the handler; the ui schema lookup is
    # stubbed out so the test does not depend on the generated dataset
    monkeypatch.setattr(formhandlers, "event_signature_for", lambda t, k: None)
    plan = formhandlers.add_handler(YAML, None, LABEL, "ПриНажатии")
    assert plan.method == "НадписьПриНажатии"
    assert plan.new_module_text.startswith("метод НадписьПриНажатии()\n")
    assert any("не найдена" in note for note in plan.notes)


def test_add_handler_return_type_gets_placeholder():
    plan = formhandlers.add_handler(YAML, None, BUTTON, "Фильтр",
                                    event_signature="((ОписаниеЗадания)->Булево)?")
    assert plan.new_module_text == (
        "метод КнопкаОкФильтр(Источник: ОписаниеЗадания): Булево\n"
        "    // TODO: действия обработчика\n"
        "    возврат Истина\n"
        ";\n"
    )


@pytest.mark.needs_data
def test_add_handler_appends_to_existing_module():
    plan = formhandlers.add_handler(YAML, MODULE, BUTTON, "ПриНажатии",
                                    event_signature=SIG_CLICK)
    assert plan.created is False and plan.method_added is True
    assert rebuilt(MODULE, plan.module_edits, plan.new_module_text)
    # one blank line separates the stub from the existing content
    assert plan.new_module_text == MODULE + (
        "\n"
        "метод КнопкаОкПриНажатии(Источник: Кнопка, Событие: СобытиеПриНажатии)\n"
        "    // TODO: действия обработчика\n"
        ";\n"
    )
    at = plan.cursor_offset
    assert plan.new_module_text[at : at + len(plan.method)] == plan.method


@pytest.mark.needs_data
def test_add_handler_module_without_trailing_newline_and_crlf():
    plan = formhandlers.add_handler(YAML, "метод А()\n;", BUTTON, "ПриНажатии",
                                    event_signature=SIG_CLICK)
    assert "\n;\n\nметод КнопкаОкПриНажатии" in plan.new_module_text

    crlf = MODULE.replace("\n", "\r\n")
    plan = formhandlers.add_handler(YAML, crlf, BUTTON, "ПриНажатии",
                                    event_signature=SIG_CLICK)
    addition = plan.new_module_text[len(crlf):]
    assert "\r\n" in addition and addition.replace("\r\n", "").find("\n") == -1


@pytest.mark.needs_data
def test_add_handler_binds_to_existing_method():
    plan = formhandlers.add_handler(YAML, MODULE, BUTTON, "ПриНажатии",
                                    method_name="Обновить")
    assert plan.method_added is False and plan.created is False
    assert plan.module_edits == [] and plan.new_module_text == MODULE
    assert "ПриНажатии: Обновить" in plan.new_yaml_text
    assert any("уже есть" in note for note in plan.notes)
    # the cursor points at the existing method for the jump
    at = plan.cursor_offset
    assert MODULE[at : at + len("Обновить")] == "Обновить"


@pytest.mark.needs_data
def test_add_handler_uniquifies_default_name():
    taken = MODULE + "\nметод КнопкаОкПриНажатии()\n;\n"
    plan = formhandlers.add_handler(YAML, taken, BUTTON, "ПриНажатии",
                                    event_signature=SIG_CLICK)
    assert plan.method == "КнопкаОкПриНажатии2"
    assert plan.method_added is True

    # an explicit NEW name is used as is
    plan = formhandlers.add_handler(YAML, taken, BUTTON, "ПриНажатии",
                                    method_name="Оплатить", event_signature=SIG_CLICK)
    assert plan.method == "Оплатить" and plan.method_added is True


@pytest.mark.needs_data
def test_add_handler_yaml_noop_when_already_bound():
    bound = YAML.replace("                Заголовок: Ок\n",
                         "                Заголовок: Ок\n"
                         "                ПриНажатии: Обновить\n")
    plan = formhandlers.add_handler(bound, MODULE, BUTTON, "ПриНажатии",
                                    method_name="Обновить")
    assert plan.yaml_edits == [] and plan.new_yaml_text == bound
    assert plan.module_edits == [] and plan.method_added is False


def test_add_handler_validation():
    with pytest.raises(FormModelError, match="не является компонентом"):
        formhandlers.add_handler(YAML, None, GRP + "/Содержимое", "ПриНажатии")
    with pytest.raises(FormModelError, match="слот дочерних компонентов"):
        formhandlers.add_handler(YAML, None, BUTTON, "Содержимое")
    with pytest.raises(FormModelError, match="Недопустимое имя"):
        formhandlers.add_handler(YAML, None, BUTTON, "ПриНажатии", method_name="1Плохое")
    with pytest.raises(FormModelError, match="Узел не найден"):
        formhandlers.add_handler(YAML, None, "Нет[7]", "ПриНажатии")


# --- the file-level wrapper -----------------------------------------------------------------


@pytest.fixture()
def pair(tmp_path):
    yaml_path = tmp_path / "Витрина.yaml"
    yaml_path.write_bytes(YAML.encode("utf-8"))
    return yaml_path


def test_op_add_handler_creates_module(pair):
    outcome = formhandlers.op_add_handler(pair, BUTTON, "ПриНажатии", signature=SIG_CLICK)
    changes = {c.path.name: c for c in outcome.result.changes}
    assert set(changes) == {"Витрина.yaml", "Витрина.xbsl"}
    assert changes["Витрина.xbsl"].created is True
    assert changes["Витрина.yaml"].created is False
    # the module change carries the cursor at the method name
    line, col = changes["Витрина.xbsl"].cursor
    assert line == 0 and col == len("метод ")
    assert outcome.module_path == pair.with_suffix(".xbsl")


@pytest.mark.needs_data
def test_op_add_handler_existing_module_and_noop(pair):
    module = pair.with_suffix(".xbsl")
    module.write_bytes(MODULE.encode("utf-8"))
    outcome = formhandlers.op_add_handler(pair, BUTTON, "ПриНажатии", method="Обновить")
    assert [c.path.name for c in outcome.result.changes] == ["Витрина.yaml"]

    # apply the yaml change, then repeat: nothing to do, said in notes
    changed = outcome.result.changes[0]
    changed.path.write_bytes(changed.content.encode("utf-8"))
    again = formhandlers.op_add_handler(pair, BUTTON, "ПриНажатии", method="Обновить")
    assert again.result.changes == []
    assert any("Изменений нет" in note for note in again.result.notes)


def test_op_add_handler_missing_yaml(tmp_path):
    with pytest.raises(FormModelError, match="Файл не найден"):
        formhandlers.op_add_handler(tmp_path / "Нет.yaml", BUTTON, "ПриНажатии")


# --- smoke over the demo pair ---------------------------------------------------------------


@pytest.mark.needs_data
def test_demo_pair_module_methods(request):
    demo = request.config.rootpath / "demo"
    pairs = [
        p for p in sorted(demo.rglob("*.yaml"))
        if p.with_suffix(".xbsl").is_file()
        and "ВидЭлемента: КомпонентИнтерфейса" in p.read_text(encoding="utf-8-sig")
    ]
    assert pairs, "в demo/ нет пары компонент+модуль"
    for yaml_path in pairs:
        text = yaml_path.with_suffix(".xbsl").read_text(encoding="utf-8-sig")
        methods, errors = formhandlers.module_methods(text)
        assert errors == 0
        assert methods, f"в модуле {yaml_path.stem} не нашлось методов"
        for m in methods:
            assert m["name"] and m["span"]["start"] < m["span"]["end"] <= len(text)
            if m["nameSpan"]:
                assert text[m["nameSpan"]["start"] : m["nameSpan"]["end"]] == m["name"]


# --- remove_handler: the mirror operation ----------------------------------------------------


def _bound(value: str) -> str:
    """The fixture yaml with the button's ПриНажатии bound to `value`."""
    anchor = "                Имя: КнопкаОк\n"
    assert anchor in YAML
    return YAML.replace(anchor, anchor + "                ПриНажатии: " + value + "\n")


@pytest.mark.needs_data
def test_remove_handler_drops_the_method_and_its_annotations():
    plan = formhandlers.remove_handler(_bound("Обновить"), MODULE, BUTTON, "ПриНажатии", drop_method=True)
    assert plan.method == "Обновить"
    assert plan.method_removed is True
    assert "ПриНажатии" not in plan.new_yaml_text
    # the method leaves with its annotation line, and the neighbours keep one blank line
    assert "Обновить" not in plan.new_module_text
    assert "@НаКлиенте" not in plan.new_module_text
    assert "\n\n\n" not in plan.new_module_text
    assert "метод Загрузить" in plan.new_module_text and "метод Хелпер" in plan.new_module_text


@pytest.mark.needs_data
def test_remove_handler_can_keep_the_method():
    plan = formhandlers.remove_handler(_bound("Обновить"), MODULE, BUTTON, "ПриНажатии", drop_method=False)
    assert plan.method == "Обновить"
    assert plan.method_removed is False
    assert plan.module_edits == []
    assert plan.new_module_text == MODULE
    assert "ПриНажатии" not in plan.new_yaml_text


@pytest.mark.needs_data
def test_remove_handler_the_last_method_leaves_no_trailing_blank_lines():
    plan = formhandlers.remove_handler(_bound("Хелпер"), MODULE, BUTTON, "ПриНажатии", drop_method=True)
    assert plan.method_removed is True
    assert "Хелпер" not in plan.new_module_text
    assert plan.new_module_text.endswith(";\n")
    assert not plan.new_module_text.endswith("\n\n")


@pytest.mark.needs_data
def test_remove_handler_reports_what_it_could_not_delete():
    # a key bound to an expression names no method - the binding goes, the module stays
    plan = formhandlers.remove_handler(_bound("=Что.То()"), MODULE, BUTTON, "ПриНажатии", drop_method=True)
    assert plan.method is None and plan.method_removed is False
    assert plan.notes and "удалять нечего" in plan.notes[0]

    # a name the module does not carry
    plan = formhandlers.remove_handler(_bound("Отсутствует"), MODULE, BUTTON, "ПриНажатии", drop_method=True)
    assert plan.method == "Отсутствует" and plan.method_removed is False
    assert plan.notes and "в модуле нет" in plan.notes[0]


# --- the metadata half: a module method for a handler that is not a form event ----------------

SERVICE_YAML = """\
ВидЭлемента: HttpСервис
Ид: 6f0b6a44-0000-4000-8000-000000000205
Имя: ПробныйСервис
ШаблоныUrl:
    -
        Имя: Ресурс
        Шаблон: /res/{ключ}
        Методы:
            -
                Метод: GET
                Обработчик: ОтдатьРесурс
    -
        Имя: Поле
        Шаблон: /pic/{вид}
        Методы:
            -
                Метод: GET
                Обработчик: ОтдатьПоле
"""

SERVICE_MODULE = """\
метод ОтдатьРесурс(Запрос: HttpСервисЗапрос)
    // отдаёт ресурс
;
"""


def test_add_module_method_creates_the_module_of_a_service_without_one():
    """No module file yet: the plan carries the whole content, the cursor sits on the name."""
    plan = formhandlers.add_module_method(None, "ОтдатьПоле", [("Запрос", "HttpСервисЗапрос")])
    assert plan.created is True and plan.method_added is True
    assert plan.module_edits == []
    assert plan.new_module_text.startswith("метод ОтдатьПоле(Запрос: HttpСервисЗапрос)")
    at = plan.cursor_offset
    assert plan.new_module_text[at : at + len("ОтдатьПоле")] == "ОтдатьПоле"


@pytest.mark.needs_data
def test_add_module_method_appends_a_stub_to_an_existing_module():
    plan = formhandlers.add_module_method(
        SERVICE_MODULE, "ОтдатьПоле", [("Запрос", "HttpСервисЗапрос")]
    )
    assert plan.created is False and plan.method_added is True
    assert plan.new_module_text.startswith(SERVICE_MODULE)  # what was there is untouched
    assert "метод ОтдатьПоле(Запрос: HttpСервисЗапрос)" in plan.new_module_text
    at = plan.cursor_offset
    assert plan.new_module_text[at : at + len("ОтдатьПоле")] == "ОтдатьПоле"


@pytest.mark.needs_data
def test_add_module_method_does_not_write_a_method_the_module_already_has():
    """The jump target of an existing method, and not a second copy of it."""
    plan = formhandlers.add_module_method(SERVICE_MODULE, "ОтдатьРесурс")
    assert plan.method_added is False and plan.module_edits == []
    assert plan.new_module_text == SERVICE_MODULE
    at = plan.cursor_offset
    assert SERVICE_MODULE[at : at + len("ОтдатьРесурс")] == "ОтдатьРесурс"
    assert plan.notes and "уже есть" in plan.notes[0]


@pytest.mark.needs_data
def test_signature_like_copies_the_neighbour_bound_to_the_same_key():
    """Nothing declares what the platform passes to a metadata handler - the working code does:
    the other handlers of the same element are written against the same contract."""
    methods, _errors = formhandlers.module_methods(SERVICE_MODULE)
    params, returns, like = formhandlers.signature_like(
        SERVICE_YAML, "Обработчик", methods, exclude="ОтдатьПоле"
    )
    assert like == "ОтдатьРесурс"
    assert params == [("Запрос", "HttpСервисЗапрос")]
    assert returns is None


@pytest.mark.needs_data
def test_signature_like_skips_the_method_being_created_and_finds_nothing_else():
    """The only neighbour is the handler itself - a parameterless stub is the honest answer."""
    methods, _errors = formhandlers.module_methods(SERVICE_MODULE)
    params, returns, like = formhandlers.signature_like(
        SERVICE_YAML.replace("ОтдатьРесурс", "ОтдатьПоле"), "Обработчик", methods,
        exclude="ОтдатьПоле",
    )
    assert (params, returns, like) == ([], None, "")


@pytest.mark.needs_data
def test_signature_like_ignores_expressions_and_names_the_module_does_not_have():
    methods, _errors = formhandlers.module_methods(SERVICE_MODULE)
    text = SERVICE_YAML.replace("Обработчик: ОтдатьРесурс", "Обработчик: =Что.То()")
    text = text.replace("Обработчик: ОтдатьПоле", "Обработчик: Отсутствует")
    assert formhandlers.signature_like(text, "Обработчик", methods) == ([], None, "")
