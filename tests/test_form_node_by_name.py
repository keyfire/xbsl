"""A form node named by its component name: every surface that takes a node takes the name too.

The tree addresses nodes by positional paths, while a caller knows a component by its `Name`.
The node arguments of the form operations (xbsl/formedits.py, xbsl/formhandlers.py) and of
their surfaces (MCP meta_* tools, CLI form-edit/form-tree/form-handlers) are resolved by one
function, formmodel.get_node: a path first, then a name carried by exactly one component.
The checks below hold the four cases - a name found, a name repeated, a name unknown, a
path - and the parity that matters most: an edit by name writes the same bytes as the edit
by path.
"""

import importlib
import json
import sys
import types

import pytest

from xbsl import cli, formedits, formhandlers, formmodel
from xbsl.formmodel import FormModelError, parse_form

FORM = """\
ВидЭлемента: КомпонентИнтерфейса
Ид: 6f0b6a44-0000-4000-8000-000000000301
Имя: КарточкаЗадачи
ОбластьВидимости: ВПодсистеме
Наследует:
    Тип: ФормаОбъекта<Задачи.Объект>
    Заголовок: Задача
    Содержимое:
        Тип: ПроизвольныйШаблонФормы
        Содержимое:
            -
                Тип: Группа
                Имя: ГруппаСклад
                Содержимое:
                    -
                        Тип: ПолеВвода<Строка>
                        Имя: ПолеСклад
                        Значение: =Объект.Склад
                    -
                        Тип: Надпись
                        Имя: Пояснение
                        Значение: Склад отгрузки
            -
                Тип: Группа
                Имя: ГруппаСроки
                Содержимое:
                    -
                        Тип: Надпись
                        Имя: Пояснение
                        Значение: Сроки задачи
                    -
                        Тип: ПолеВвода<Дата>
                        Имя: ПолеСрок
                        Значение: =Объект.Срок
            -
                Тип: Кнопка
                Имя: КнопкаЗаписать
                Заголовок: Записать
"""

TPL = "Наследует/Содержимое[0]"
STOCK_GROUP = TPL + "/Содержимое[0]"
STOCK_FIELD = STOCK_GROUP + "/Содержимое[0]"
STOCK_NOTE = STOCK_GROUP + "/Содержимое[1]"
DATES_GROUP = TPL + "/Содержимое[1]"
DATES_NOTE = DATES_GROUP + "/Содержимое[0]"
DUE_FIELD = DATES_GROUP + "/Содержимое[1]"
SAVE_BUTTON = TPL + "/Содержимое[2]"

#: The component names of the fixture that occur once, with their paths.
PATHS = {
    "ГруппаСклад": STOCK_GROUP,
    "ПолеСклад": STOCK_FIELD,
    "ГруппаСроки": DATES_GROUP,
    "ПолеСрок": DUE_FIELD,
    "КнопкаЗаписать": SAVE_BUTTON,
}

SIG_CLICK = "(Кнопка, СобытиеПриНажатии)->ничто"


def _by_path(args: dict) -> dict:
    """The same operation arguments with every component name replaced by its path."""
    out = {}
    for key, value in args.items():
        if key in ("node", "parent", "new_parent", "before", "after"):
            out[key] = PATHS.get(value, value)
        elif key == "nodes":
            out[key] = [PATHS.get(v, v) for v in value]
        else:
            out[key] = value
    return out


# --- a name found ------------------------------------------------------------------------


def test_a_unique_name_resolves_to_its_node():
    form = parse_form(FORM)
    for name, path in PATHS.items():
        assert formmodel.get_node(form, name) is form.nodes[path]
        assert formmodel.get_component(form, name) is form.nodes[path]


def test_set_property_by_name_writes_what_the_path_writes():
    by_name = formedits.set_property(FORM, "ПолеСклад", "Подсказка", value="Склад отгрузки")
    by_path = formedits.set_property(FORM, STOCK_FIELD, "Подсказка", value="Склад отгрузки")
    assert by_name.new_text == by_path.new_text
    assert by_name.edits == by_path.edits
    # the answer names the node edited by its path - the one the tree would have given
    assert by_name.node_id == by_path.node_id == STOCK_FIELD


@pytest.mark.parametrize("op, args", [
    ("set_property", {"node": "КнопкаЗаписать", "key": "Ширина", "value": "200"}),
    ("reset_property", {"node": "ПолеСклад", "key": "Значение"}),
    ("rename", {"node": "КнопкаЗаписать", "new_name": "КнопкаСохранить"}),
    ("remove", {"node": "ПолеСрок"}),
    ("wrap", {"node": "КнопкаЗаписать", "container": "Группа", "name": "ГруппаКнопок"}),
    ("unwrap", {"node": "ГруппаСклад"}),
    ("duplicate", {"node": "КнопкаЗаписать"}),
    ("insert", {"parent": "ГруппаСроки", "slot": "Содержимое", "type": "Надпись",
                "name": "Итог", "before": "ПолеСрок"}),
    ("insert_fragment", {"parent": "ГруппаСклад", "slot": "Содержимое",
                         "fragment": "Тип: Флажок\nИмя: Срочно\n", "after": "ПолеСклад"}),
    ("move", {"node": "КнопкаЗаписать", "new_parent": "ГруппаСклад", "slot": "Содержимое",
              "before": "ПолеСклад"}),
    ("move_nodes", {"nodes": ["КнопкаЗаписать", "ПолеСклад"], "new_parent": "ГруппаСроки",
                    "slot": "Содержимое", "after": "ПолеСрок"}),
    ("remove_nodes", {"nodes": ["ПолеСклад", "КнопкаЗаписать"]}),
])
def test_every_operation_takes_a_name_like_its_path(op, args):
    by_name = formedits.apply_operation(FORM, op, args)
    by_path = formedits.apply_operation(FORM, op, _by_path(args))
    assert by_name.new_text != FORM
    assert by_name.new_text == by_path.new_text
    assert by_name.node_id == by_path.node_id


def test_a_name_and_the_path_of_one_node_count_once_in_a_batch():
    both = formedits.remove_nodes(FORM, ["ПолеСклад", STOCK_FIELD])
    single = formedits.remove_nodes(FORM, [STOCK_FIELD])
    assert both.new_text == single.new_text


def test_handler_binding_takes_a_name():
    by_name = formhandlers.add_handler(FORM, None, "КнопкаЗаписать", "ПриНажатии",
                                       event_signature=SIG_CLICK)
    by_path = formhandlers.add_handler(FORM, None, SAVE_BUTTON, "ПриНажатии",
                                       event_signature=SIG_CLICK)
    assert by_name.method == by_path.method == "КнопкаЗаписатьПриНажатии"
    assert by_name.new_yaml_text == by_path.new_yaml_text
    assert by_name.new_module_text == by_path.new_module_text
    removed = formhandlers.remove_handler(by_name.new_yaml_text, None, "КнопкаЗаписать",
                                          "ПриНажатии")
    assert removed.new_yaml_text == FORM


def test_guards_compare_the_resolved_nodes_not_the_strings():
    # the node positioned against itself, named once by its name and once by its path
    with pytest.raises(FormModelError, match="относительно самого себя"):
        formedits.move_node(FORM, "ПолеСклад", STOCK_GROUP, "Содержимое", before=STOCK_FIELD)
    with pytest.raises(FormModelError, match="относительно самого себя"):
        formedits.move_nodes(FORM, [STOCK_FIELD, "КнопкаЗаписать"], STOCK_GROUP,
                             "Содержимое", before="ПолеСклад")
    # a destination inside the moved node, both named by their names
    with pytest.raises(FormModelError, match="собственного поддерева"):
        formedits.move_node(FORM, "ГруппаСклад", "ПолеСклад", "Содержимое")
    with pytest.raises(FormModelError, match="собственного поддерева"):
        formedits.move_nodes(FORM, ["ГруппаСклад"], "ПолеСклад", "Содержимое")


# --- a name repeated ---------------------------------------------------------------------


@pytest.mark.parametrize("op, args", [
    ("set_property", {"node": "Пояснение", "key": "Ширина", "value": "200"}),
    ("remove_nodes", {"nodes": ["Пояснение"]}),
    ("insert", {"parent": "ГруппаСклад", "slot": "Содержимое", "type": "Надпись",
                "before": "Пояснение"}),
])
def test_a_repeated_name_is_refused_with_the_paths_to_choose_from(op, args):
    with pytest.raises(FormModelError) as caught:
        formedits.apply_operation(FORM, op, args)
    message = str(caught.value)
    assert "не единственное" in message
    assert STOCK_NOTE in message and DATES_NOTE in message


def test_a_long_list_of_carriers_is_cut():
    items = "            -\n                Тип: Надпись\n                Имя: Подпись\n" * 12
    text = FORM.replace("        Содержимое:\n            -\n", "        Содержимое:\n"
                        + items + "            -\n", 1)
    with pytest.raises(FormModelError, match="компонентов с ним: 12") as caught:
        formedits.remove_node(text, "Подпись")
    assert "и ещё 2" in str(caught.value)


# --- a name unknown ----------------------------------------------------------------------


def test_an_unknown_name_is_refused_with_the_close_names():
    with pytest.raises(FormModelError) as caught:
        formedits.set_property(FORM, "ПолеСкладов", "Ширина", value="200")
    message = str(caught.value)
    assert message.startswith("Узел не найден: ПолеСкладов.")
    assert "Похожие имена: ПолеСклад" in message


def test_close_names_ignore_the_case_and_keep_it():
    with pytest.raises(FormModelError, match="Похожие имена: КнопкаЗаписать"):
        formedits.remove_node(FORM, "кнопказаписать")


def test_an_unknown_name_with_nothing_close_says_how_a_node_is_given():
    with pytest.raises(FormModelError) as caught:
        formedits.remove_node(FORM, "Партии")
    message = str(caught.value)
    assert message.startswith("Узел не найден: Партии.")
    assert "путём из дерева формы" in message and "Похожие" not in message


# --- a path ------------------------------------------------------------------------------


def test_every_path_still_resolves_to_its_node():
    form = parse_form(FORM)
    for node_id, node in form.nodes.items():
        assert formmodel.get_node(form, node_id) is node


def test_a_path_is_never_read_as_a_name():
    with pytest.raises(FormModelError) as caught:
        formedits.remove_node(FORM, TPL + "/Содержимое[7]")
    message = str(caught.value)
    assert message.startswith("Узел не найден: " + TPL + "/Содержимое[7]")
    assert "позиционные" in message and "Похожие" not in message


def test_a_path_wins_over_a_name_spelled_the_same():
    text = FORM.replace("Имя: КнопкаЗаписать", "Имя: Наследует")
    form = parse_form(text)
    assert formmodel.get_node(form, "Наследует") is form.root
    assert [n.id for n in formmodel.find_by_name(form.root, "Наследует")] == [SAVE_BUTTON]


def test_a_slot_is_addressed_by_its_path_only():
    form = parse_form(FORM)
    assert formmodel.get_node(form, STOCK_GROUP + "/Содержимое").kind == "slot"
    with pytest.raises(FormModelError, match="не является компонентом"):
        formmodel.get_component(form, STOCK_GROUP + "/Содержимое")


# --- the surfaces ------------------------------------------------------------------------


@pytest.fixture()
def form_pair(tmp_path):
    """Two copies of the form: one edited by name, the other by path."""
    by_name = tmp_path / "by-name" / "КарточкаЗадачи.yaml"
    by_path = tmp_path / "by-path" / "КарточкаЗадачи.yaml"
    for path in (by_name, by_path):
        path.parent.mkdir()
        path.write_bytes(FORM.encode("utf-8"))
    return by_name, by_path


@pytest.fixture()
def mcp_module(monkeypatch):
    class _FakeMCP:
        def __init__(self, name):
            self.name = name
            self.tools = {}

        def tool(self):
            def deco(fn):
                self.tools[fn.__name__] = fn
                return fn

            return deco

    fast = types.ModuleType("mcp.server.fastmcp")
    fast.FastMCP = _FakeMCP
    monkeypatch.setitem(sys.modules, "mcp", types.ModuleType("mcp"))
    monkeypatch.setitem(sys.modules, "mcp.server", types.ModuleType("mcp.server"))
    monkeypatch.setitem(sys.modules, "mcp.server.fastmcp", fast)
    sys.modules.pop("xbsl.mcp_server", None)
    module = importlib.import_module("xbsl.mcp_server")
    yield module
    sys.modules.pop("xbsl.mcp_server", None)


def test_mcp_set_component_property_by_name(mcp_module, form_pair):
    by_name, by_path = form_pair
    res = mcp_module.meta_set_component_property(
        str(by_name), "ПолеСклад", "Подсказка", value="Склад отгрузки",
    )
    assert "error" not in res and res["node"]["id"] == STOCK_FIELD
    mcp_module.meta_set_component_property(
        str(by_path), STOCK_FIELD, "Подсказка", value="Склад отгрузки",
    )
    assert by_name.read_bytes() == by_path.read_bytes() != FORM.encode("utf-8")

    refused = mcp_module.meta_set_component_property(
        str(by_name), "Пояснение", "Ширина", value="200",
    )
    assert STOCK_NOTE in refused["error"] and DATES_NOTE in refused["error"]


def test_mcp_component_tree_node_id_takes_a_name(mcp_module, form_pair):
    by_name, _ = form_pair
    res = mcp_module.meta_component_tree(str(by_name), node_id="ГруппаСроки", brief=True)
    assert res["root"]["id"] == DATES_GROUP
    unknown = mcp_module.meta_component_tree(str(by_name), node_id="ГруппаСрок")
    assert "Похожие имена: ГруппаСроки" in unknown["error"]


def _run_cli(capsys, *argv) -> tuple[int, dict]:
    code = cli.main(list(argv))
    out = capsys.readouterr().out.strip()
    return code, json.loads(out)


def test_cli_form_edit_by_name_writes_what_the_path_writes(form_pair, capsys):
    by_name, by_path = form_pair
    code, out = _run_cli(capsys, "form-edit", str(by_name), "set-property",
                         "--node", "КнопкаЗаписать", "--key", "Ширина", "--value", "200")
    assert code == 0 and out["node"]["id"] == SAVE_BUTTON
    code, _ = _run_cli(capsys, "form-edit", str(by_path), "set-property",
                       "--node", SAVE_BUTTON, "--key", "Ширина", "--value", "200")
    assert code == 0
    assert by_name.read_bytes() == by_path.read_bytes() != FORM.encode("utf-8")


def test_cli_refusals_of_a_name_are_json(form_pair, capsys):
    by_name, _ = form_pair
    code, out = _run_cli(capsys, "form-tree", str(by_name), "--node", "Пояснение")
    assert code == 2 and STOCK_NOTE in out["error"] and DATES_NOTE in out["error"]
    code, out = _run_cli(capsys, "form-edit", str(by_name), "remove", "--node", "Склад")
    assert code == 2 and out["error"].startswith("Узел не найден: Склад.")
    assert by_name.read_bytes() == FORM.encode("utf-8")
