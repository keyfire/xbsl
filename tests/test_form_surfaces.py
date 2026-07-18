"""Form designer surfaces: meta_*component* MCP tools, CLI form-* and xbsl/form* LSP.

The same pattern as test_meta_surfaces.py: MCP is loaded via a stub FastMCP (the [mcp]
extra is not needed), the CLI goes through cli.main, and the LSP handlers are driven
directly when pygls is installed (skipped otherwise). All three surfaces sit on the same
xbsl.formmodel/xbsl.formedits pair, so the shapes must agree.

xbsl/formEdit is ALSO driven through the real pygls wire path (bytes in, JSON-RPC bytes
out): pygls deserializes the params of a custom request into nested namedtuples, and a
handler that only ever saw plain dicts from direct calls breaks exactly there.
"""

import importlib
import json
import sys
import types
from pathlib import Path

import pytest

from xbsl import cli

FORM = """\
ВидЭлемента: КомпонентИнтерфейса
Ид: 6f0b6a44-0000-4000-8000-000000000201
Имя: Витрина
ОбластьВидимости: ВПодсистеме
Наследует:
    Тип: Форма
    Заголовок: Витрина
    Содержимое:
        Тип: ПроизвольныйШаблонФормы
        Содержимое:
            -
                Тип: Надпись
                Имя: Приветствие
                Значение: Добро пожаловать
            -
                Тип: Кнопка
                Имя: КнопкаОбновить
                Заголовок: Обновить
"""

TPL = "Наследует/Содержимое[0]"
LABEL = TPL + "/Содержимое[0]"
BUTTON = TPL + "/Содержимое[1]"

PROPS_TAIL = """\
Свойства:
    -
        Имя: Титул
        Тип: Строка
"""

MODULE = """\
метод Обновить()
;
"""

FRAGMENT = "# пояснение\nТип: Флажок\nИмя: Показывать\n"

SIG_CLICK = "(Кнопка, СобытиеПриНажатии)->ничто"


@pytest.fixture()
def form_file(tmp_path):
    path = tmp_path / "Витрина.yaml"
    # write_bytes keeps LF as is (write_text would turn it into CRLF on Windows and
    # desynchronize the FORM.find offsets the LSP assertions rely on)
    path.write_bytes(FORM.encode("utf-8"))
    return path


@pytest.fixture()
def props_form_file(tmp_path):
    path = tmp_path / "Карточка.yaml"
    path.write_bytes((FORM + PROPS_TAIL).encode("utf-8"))
    return path


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


# --- MCP ---------------------------------------------------------------------------------


def test_mcp_component_tools_registered(mcp_module):
    expected = {
        "meta_component_tree", "meta_add_component", "meta_move_component",
        "meta_remove_component", "meta_set_component_property",
    }
    assert expected.issubset(mcp_module.mcp.tools)


def test_mcp_component_tree(mcp_module, form_file):
    res = mcp_module.meta_component_tree(str(form_file))
    root = res["root"]
    assert root["id"] == "Наследует" and root["type"] == "Форма"
    slot = root["children"][0]
    assert slot["kind"] == "slot" and slot["name"] == "Содержимое"
    label = slot["children"][0]["children"][0]["children"][0]
    assert label["name"] == "Приветствие"
    assert label["properties"][0]["valuePreview"] == "Добро пожаловать"
    # contentSpan is serialized for every node (equals span - no comments here)
    assert label["contentSpan"] == label["span"]
    assert root["contentSpan"] == root["span"]

    err = mcp_module.meta_component_tree(str(form_file.parent / "Нет.yaml"))
    assert "не найден" in err["error"].lower()


def test_mcp_add_component_writes_and_lints(mcp_module, form_file):
    res = mcp_module.meta_add_component(
        str(form_file), TPL, "Содержимое", type="Флажок", name="Показывать",
    )
    assert res["files"][0]["created"] is False
    assert "lint" in res
    assert res["node"]["id"] == TPL + "/Содержимое[2]"
    text = form_file.read_text(encoding="utf-8")
    assert "Тип: Флажок" in text and "Имя: Показывать" in text

    err = mcp_module.meta_add_component(str(form_file), TPL, "Реквизиты", type="Флажок")
    assert "Слот не поддерживается" in err["error"]


def test_mcp_move_and_remove_component(mcp_module, form_file):
    res = mcp_module.meta_move_component(
        str(form_file), BUTTON, TPL, "Содержимое", before=LABEL,
    )
    assert res["node"]["id"] == TPL + "/Содержимое[0]"
    text = form_file.read_text(encoding="utf-8")
    assert text.index("КнопкаОбновить") < text.index("Приветствие")

    res = mcp_module.meta_remove_component(str(form_file), TPL + "/Содержимое[0]")
    assert "node" not in res and "lint" in res
    assert "КнопкаОбновить" not in form_file.read_text(encoding="utf-8")

    err = mcp_module.meta_remove_component(str(form_file), "Наследует")
    assert "Корневой узел" in err["error"]


def test_mcp_batch_component_tools_registered(mcp_module):
    assert {"meta_remove_components", "meta_move_components"}.issubset(mcp_module.mcp.tools)


def test_mcp_remove_components(mcp_module, form_file):
    # both children of the template list in one call -> the slot key goes with them
    res = mcp_module.meta_remove_components(str(form_file), [LABEL, BUTTON])
    assert "node" not in res and "lint" in res
    text = form_file.read_text(encoding="utf-8")
    assert "Приветствие" not in text and "КнопкаОбновить" not in text
    assert "Содержимое:" not in text.split("ПроизвольныйШаблонФормы")[1]

    err = mcp_module.meta_remove_components(str(form_file.parent / "Витрина.yaml"),
                                            ["Наследует"])
    assert "Корневой узел" in err["error"]


def test_mcp_move_components(mcp_module, form_file):
    # selection order is reversed; the nodes land in document order in a fresh slot
    res = mcp_module.meta_move_components(str(form_file), [BUTTON, LABEL], TPL, "Подвал")
    assert res["node"]["id"] == TPL + "/Подвал[0]"
    text = form_file.read_text(encoding="utf-8")
    # Приветствие (LABEL) precedes КнопкаОбновить (BUTTON) - document order kept
    assert text.index("Приветствие") < text.index("КнопкаОбновить")
    assert "Подвал:" in text

    err = mcp_module.meta_move_components(str(form_file), ["Наследует/Нет[9]"],
                                          TPL, "Подвал")
    assert "не найден" in err["error"].lower()


def test_mcp_set_component_property(mcp_module, form_file):
    res = mcp_module.meta_set_component_property(
        str(form_file), LABEL, "РастягиватьПоГоризонтали", value="Истина",
    )
    assert "lint" in res and res["node"]["id"] == LABEL
    assert "РастягиватьПоГоризонтали: Истина" in form_file.read_text(encoding="utf-8")

    res = mcp_module.meta_set_component_property(
        str(form_file), LABEL, "Шрифт", value_yaml="Тип: АбсолютныйШрифт\nРазмер: 20",
    )
    assert "Размер: 20" in form_file.read_text(encoding="utf-8")

    # both values omitted - the key is removed
    res = mcp_module.meta_set_component_property(str(form_file), LABEL, "Шрифт")
    assert "АбсолютныйШрифт" not in form_file.read_text(encoding="utf-8")

    err = mcp_module.meta_set_component_property(str(form_file), LABEL, "Содержимое",
                                                 value="х")
    assert "слот" in err["error"]


def test_mcp_wave3_tools_registered(mcp_module):
    assert {"meta_insert_fragment", "meta_add_handler"}.issubset(mcp_module.mcp.tools)


def test_mcp_component_tree_component_properties(mcp_module, form_file, props_form_file):
    res = mcp_module.meta_component_tree(str(props_form_file))
    assert [p["name"] for p in res["componentProperties"]] == ["Титул"]
    assert res["componentProperties"][0]["type"] == "Строка"
    assert res["componentProperties"][0]["nameSpan"]

    assert mcp_module.meta_component_tree(str(form_file))["componentProperties"] == []


def test_mcp_insert_fragment(mcp_module, form_file):
    res = mcp_module.meta_insert_fragment(str(form_file), TPL, "Содержимое", FRAGMENT)
    assert res["files"][0]["created"] is False and "lint" in res
    assert res["node"]["id"] == TPL + "/Содержимое[2]"
    text = form_file.read_text(encoding="utf-8")
    assert "# пояснение" in text and "Тип: Флажок" in text

    # a block "-" list pastes several components at once - the first is reported
    res = mcp_module.meta_insert_fragment(str(form_file), TPL, "Содержимое",
                                          "- Тип: Надпись\n- Тип: Кнопка\n")
    assert res["node"]["id"] == TPL + "/Содержимое[3]"
    tree = mcp_module.meta_component_tree(str(form_file))
    slot = tree["root"]["children"][0]["children"][0]["children"][0]
    assert [c.get("type") for c in slot["children"]][-2:] == ["Надпись", "Кнопка"]

    err = mcp_module.meta_insert_fragment(str(form_file), TPL, "Содержимое",
                                          "просто строка")
    assert "ожидается маппинг" in err["error"]


@pytest.mark.needs_data
def test_mcp_add_handler_creates_module(mcp_module, form_file):
    res = mcp_module.meta_add_handler(str(form_file), BUTTON, "ПриНажатии",
                                      signature=SIG_CLICK)
    assert res["method"] == "КнопкаОбновитьПриНажатии"
    assert res["created"] is True and res["methodAdded"] is True
    assert "lint" in res
    by_name = {Path(f["path"]).name: f for f in res["files"]}
    assert by_name["Витрина.xbsl"]["created"] is True
    module_text = form_file.with_suffix(".xbsl").read_text(encoding="utf-8")
    assert module_text.startswith(
        "метод КнопкаОбновитьПриНажатии(Источник: Кнопка, Событие: СобытиеПриНажатии)"
    )
    assert "ПриНажатии: КнопкаОбновитьПриНажатии" in form_file.read_text(encoding="utf-8")


@pytest.mark.needs_data
def test_mcp_add_handler_binds_existing(mcp_module, form_file):
    form_file.with_suffix(".xbsl").write_bytes(MODULE.encode("utf-8"))
    res = mcp_module.meta_add_handler(str(form_file), BUTTON, "ПриНажатии",
                                      method="Обновить")
    assert res["methodAdded"] is False and res["created"] is False
    assert [f["path"] for f in res["files"]] == [str(form_file)]
    assert form_file.with_suffix(".xbsl").read_text(encoding="utf-8") == MODULE

    err = mcp_module.meta_add_handler(str(form_file), "Наследует/Нет", "ПриНажатии")
    assert "не найден" in err["error"].lower()


# --- CLI ---------------------------------------------------------------------------------


def _run_cli(capsys, *argv) -> tuple[int, dict]:
    code = cli.main(list(argv))
    out = capsys.readouterr().out.strip()
    return code, json.loads(out)


def test_cli_form_tree(form_file, capsys):
    code, out = _run_cli(capsys, "form-tree", str(form_file))
    assert code == 0
    assert out["root"]["typeFull"] == "Форма"

    offset = FORM.find("КнопкаОбновить")
    code, out = _run_cli(capsys, "form-tree", str(form_file), "--at", str(offset))
    assert code == 0
    assert out["node"]["id"] == BUTTON and out["node"]["name"] == "КнопкаОбновить"
    # parity with LSP formNodeAt: the nearest parent COMPONENT rides along
    assert out["parent"]["id"] == TPL and "children" not in out["parent"]

    code, out = _run_cli(capsys, "form-tree", str(form_file), "--at",
                         str(FORM.find("Тип: Форма")))
    assert code == 0
    assert out["node"]["id"] == "Наследует" and out["parent"] is None


def test_cli_form_edit_dry_run_writes_nothing(form_file, capsys):
    code, out = _run_cli(
        capsys, "form-edit", str(form_file), "insert",
        "--parent", TPL, "--slot", "Содержимое", "--type", "Надпись", "--name", "Итог",
        "--dry-run",
    )
    assert code == 0
    assert out["node"]["id"] == TPL + "/Содержимое[2]"
    assert out["edits"] and "newText" in out["edits"][0]
    assert "Имя: Итог" in out["files"][0]["content"]
    assert "Итог" not in form_file.read_text(encoding="utf-8")


def test_cli_form_edit_full_op_set(form_file, capsys):
    code, out = _run_cli(
        capsys, "form-edit", str(form_file), "wrap",
        "--node", LABEL, "--container", "Группа", "--name", "Обертка",
    )
    assert code == 0 and out["node"]["id"] == LABEL
    code, out = _run_cli(capsys, "form-edit", str(form_file), "unwrap", "--node", LABEL)
    assert code == 0
    assert form_file.read_text(encoding="utf-8") == FORM

    code, out = _run_cli(capsys, "form-edit", str(form_file), "duplicate", "--node", BUTTON)
    assert code == 0 and out["node"]["id"] == TPL + "/Содержимое[2]"
    code, out = _run_cli(
        capsys, "form-edit", str(form_file), "rename",
        "--node", TPL + "/Содержимое[2]", "--new-name", "КнопкаЗакрыть",
    )
    assert code == 0
    code, out = _run_cli(
        capsys, "form-edit", str(form_file), "set-property",
        "--node", LABEL, "--key", "Ширина", "--value", "220",
    )
    assert code == 0
    code, out = _run_cli(
        capsys, "form-edit", str(form_file), "reset-property",
        "--node", LABEL, "--key", "Ширина",
    )
    assert code == 0 and "lint" in out
    text = form_file.read_text(encoding="utf-8")
    assert "КнопкаЗакрыть" in text and "Ширина" not in text


def test_cli_form_edit_error_is_json(form_file, capsys):
    code, out = _run_cli(
        capsys, "form-edit", str(form_file), "remove", "--node", "Наследует",
    )
    assert code == 2
    assert "Корневой узел" in out["error"]


def test_cli_form_edit_insert_fragment(form_file, tmp_path, capsys):
    code, out = _run_cli(
        capsys, "form-edit", str(form_file), "insert-fragment",
        "--parent", TPL, "--slot", "Содержимое", "--fragment", FRAGMENT,
    )
    assert code == 0 and out["node"]["id"] == TPL + "/Содержимое[2]"
    assert "Тип: Флажок" in form_file.read_text(encoding="utf-8")

    frag_file = tmp_path / "фрагмент.yaml"
    frag_file.write_text("Тип: Гиперссылка\n", encoding="utf-8")
    code, out = _run_cli(
        capsys, "form-edit", str(form_file), "insert-fragment",
        "--parent", TPL, "--slot", "Содержимое", "--fragment-file", str(frag_file),
    )
    assert code == 0
    assert "Тип: Гиперссылка" in form_file.read_text(encoding="utf-8")

    code, out = _run_cli(
        capsys, "form-edit", str(form_file), "insert-fragment",
        "--parent", TPL, "--slot", "Содержимое",
        "--fragment", "Тип: А", "--fragment-file", str(frag_file),
    )
    assert code == 2 and "один из флагов" in out["error"]


def test_cli_form_edit_remove_nodes(form_file, capsys):
    # --nodes as a comma-separated list (node ids never contain a comma)
    code, out = _run_cli(
        capsys, "form-edit", str(form_file), "remove-nodes",
        "--nodes", f"{LABEL},{BUTTON}",
    )
    assert code == 0 and out["node"] is None and "lint" in out
    text = form_file.read_text(encoding="utf-8")
    assert "Приветствие" not in text and "КнопкаОбновить" not in text


def test_cli_form_edit_move_nodes_repeatable_flag(form_file, capsys):
    # --node repeated (the flag accumulates) and the document order is kept
    code, out = _run_cli(
        capsys, "form-edit", str(form_file), "move-nodes",
        "--nodes", BUTTON, "--nodes", LABEL,
        "--new-parent", TPL, "--slot", "Подвал",
    )
    assert code == 0 and out["node"]["id"] == TPL + "/Подвал[0]"
    text = form_file.read_text(encoding="utf-8")
    assert text.index("Приветствие") < text.index("КнопкаОбновить")
    assert "Подвал:" in text


def test_cli_form_edit_move_nodes_error_is_json(form_file, capsys):
    code, out = _run_cli(
        capsys, "form-edit", str(form_file), "move-nodes",
        "--nodes", "Наследует", "--new-parent", TPL, "--slot", "Содержимое",
    )
    assert code == 2 and "Корневой узел" in out["error"]


def test_cli_form_edit_property_ops(props_form_file, capsys):
    code, out = _run_cli(
        capsys, "form-edit", str(props_form_file), "property-add",
        "--name", "Итог", "--type", "Число",
    )
    assert code == 0 and out["node"]["id"] == "Свойства/Итог"
    code, out = _run_cli(
        capsys, "form-edit", str(props_form_file), "property-retype",
        "--name", "Итог", "--new-type", "Число?",
    )
    assert code == 0
    assert "Тип: Число?" in props_form_file.read_text(encoding="utf-8")
    code, out = _run_cli(
        capsys, "form-edit", str(props_form_file), "property-rename",
        "--name", "Титул", "--new-name", "Заглавие",
    )
    assert code == 0 and out["notes"] == []  # nothing in FORM binds =Титул
    code, out = _run_cli(
        capsys, "form-edit", str(props_form_file), "property-remove",
        "--name", "Итог",
    )
    assert code == 0 and "lint" in out
    text = props_form_file.read_text(encoding="utf-8")
    assert "Заглавие" in text and "Итог" not in text


def test_cli_form_edit_property_rename_note(props_form_file, capsys):
    bound = props_form_file.read_text(encoding="utf-8").replace(
        "Значение: Добро пожаловать", "Значение: =Титул",
    )
    props_form_file.write_bytes(bound.encode("utf-8"))
    code, out = _run_cli(
        capsys, "form-edit", str(props_form_file), "property-rename",
        "--name", "Титул", "--new-name", "Заглавие",
    )
    assert code == 0
    assert out["notes"] and "не переписаны" in out["notes"][0]


@pytest.mark.needs_data
def test_cli_form_handlers_list_and_add(form_file, capsys):
    code, out = _run_cli(capsys, "form-handlers", str(form_file))
    assert code == 0
    assert out == {"available": False, "module": None, "methods": []}

    form_file.with_suffix(".xbsl").write_bytes(MODULE.encode("utf-8"))
    code, out = _run_cli(capsys, "form-handlers", str(form_file))
    assert code == 0 and out["available"] is True
    assert [m["name"] for m in out["methods"]] == ["Обновить"]
    assert out["parseErrors"] == 0

    code, out = _run_cli(
        capsys, "form-handlers", str(form_file),
        "--node", BUTTON, "--key", "ПриНажатии", "--signature", SIG_CLICK, "--dry-run",
    )
    assert code == 0 and out["method"] == "КнопкаОбновитьПриНажатии"
    assert out["methodAdded"] is True and out["created"] is False
    assert "КнопкаОбновитьПриНажатии" not in form_file.with_suffix(".xbsl").read_text(
        encoding="utf-8"
    )

    code, out = _run_cli(
        capsys, "form-handlers", str(form_file),
        "--node", BUTTON, "--key", "ПриНажатии", "--signature", SIG_CLICK,
    )
    assert code == 0 and "lint" in out
    module_text = form_file.with_suffix(".xbsl").read_text(encoding="utf-8")
    assert "метод КнопкаОбновитьПриНажатии(Источник: Кнопка" in module_text

    code, out = _run_cli(capsys, "form-handlers", str(form_file), "--node", BUTTON)
    assert code == 2 and "оба флага" in out["error"]


# --- LSP ---------------------------------------------------------------------------------

pygls = pytest.importorskip("pygls", reason="LSP-методы проверяются при установленном extra [lsp]")


def _server_features():
    from xbsl import lsp as lsp_module

    server = lsp_module._make_server()
    fm = getattr(server.lsp, "fm", None) or getattr(server.lsp, "_features", None)
    features = getattr(fm, "features", fm)
    return server, features


def _uri(path: Path) -> str:
    from pygls import uris

    return uris.from_fs_path(str(path))


def test_lsp_form_methods_registered():
    _, features = _server_features()
    for method in ("xbsl/formTree", "xbsl/formNodeAt", "xbsl/formEdit"):
        assert method in features


def test_lsp_form_tree_and_node_at(form_file):
    _, features = _server_features()
    tree = features["xbsl/formTree"]({"uri": _uri(form_file)})
    assert tree["available"] is True
    assert tree["root"]["type"] == "Форма"
    # the tree carries compact properties - no spans until formNodeAt
    label = tree["root"]["children"][0]["children"][0]["children"][0]["children"][0]
    assert label["name"] == "Приветствие" and "span" not in label["properties"][0]

    node = features["xbsl/formNodeAt"](
        {"uri": _uri(form_file), "offset": FORM.find("КнопкаОбновить")}
    )
    assert node["node"]["id"] == BUTTON
    assert node["node"]["properties"][0]["valueSpan"]  # full properties for one node
    assert node["node"]["contentSpan"] == node["node"]["span"]  # no attached comments
    # the parent COMPONENT rides along: the slot between them is skipped
    assert node["parent"]["id"] == TPL
    assert node["parent"]["type"] == "ПроизвольныйШаблонФормы"
    assert "children" not in node["parent"] and "properties" in node["parent"]

    # a slot hit resolves the parent to the slot's owner component
    slot_hit = features["xbsl/formNodeAt"](
        {"uri": _uri(form_file), "offset": FORM.find("Содержимое:")}
    )
    assert slot_hit["node"]["kind"] == "slot"
    assert slot_hit["parent"]["id"] == "Наследует"

    # the root has no parent
    root_hit = features["xbsl/formNodeAt"](
        {"uri": _uri(form_file), "offset": FORM.find("Тип: Форма")}
    )
    assert root_hit["node"]["id"] == "Наследует" and root_hit["parent"] is None

    miss = features["xbsl/formNodeAt"]({"uri": _uri(form_file), "offset": 0})
    assert miss == {"node": None}


def test_lsp_form_tree_not_a_component(tmp_path):
    _, features = _server_features()
    other = tmp_path / "Товары.yaml"
    other.write_text("ВидЭлемента: Справочник\nИмя: Товары\n", encoding="utf-8")
    res = features["xbsl/formTree"]({"uri": _uri(other)})
    assert res["available"] is False and "reason" in res


def test_lsp_form_edit_computes_only(form_file):
    _, features = _server_features()
    res = features["xbsl/formEdit"]({
        "uri": _uri(form_file), "op": "insert",
        "args": {"parent": TPL, "slot": "Содержимое", "type": "Надпись", "name": "Итог"},
    })
    assert res["node"]["id"] == TPL + "/Содержимое[2]"
    assert res["edits"] and set(res["edits"][0]) == {"start", "end", "newText"}
    # LSP only computes: the editor applies the WorkspaceEdit
    assert form_file.read_text(encoding="utf-8") == FORM

    err = features["xbsl/formEdit"]({
        "uri": _uri(form_file), "op": "explode", "args": {},
    })
    assert "Неизвестная операция" in err["error"]


def test_lsp_form_edit_batch_ops(form_file):
    _, features = _server_features()
    # move_nodes with a list of node ids in the nested args
    res = features["xbsl/formEdit"]({
        "uri": _uri(form_file), "op": "move_nodes",
        "args": {"nodes": [BUTTON, LABEL], "newParent": TPL, "slot": "Подвал"},
    })
    assert res["node"]["id"] == TPL + "/Подвал[0]"
    assert res["edits"]
    assert form_file.read_text(encoding="utf-8") == FORM  # compute only

    res = features["xbsl/formEdit"]({
        "uri": _uri(form_file), "op": "remove_nodes",
        "args": {"nodes": [LABEL, BUTTON]},
    })
    assert res["node"] is None and res["edits"]


# --- LSP over the real pygls wire ----------------------------------------------------------
#
# Direct handler calls (above) feed plain dicts and cannot catch what the real channel
# does to params: pygls turns every JSON object of a custom request into a namedtuple
# (pygls.protocol._dict_to_object), which has no __dict__ and does not iterate as pairs.
# These tests push framed JSON-RPC bytes through server.lsp.data_received and read the
# response bytes back - serialization, deserialization and dispatch are all real.


class _CapturingTransport:
    """Minimal transport double: collects whatever pygls writes to the client."""

    def __init__(self):
        self.chunks: list[bytes] = []

    def write(self, data) -> None:
        self.chunks.append(data if isinstance(data, bytes) else str(data).encode("utf-8"))


def _wire_server():
    from xbsl import lsp as lsp_module

    server = lsp_module._make_server()
    transport = _CapturingTransport()
    server.lsp.connection_made(transport)
    return server, transport


def _wire_request(server, transport, method: str, params: dict, msg_id: int) -> dict:
    body = json.dumps(
        {"jsonrpc": "2.0", "id": msg_id, "method": method, "params": params}
    ).encode("utf-8")
    server.lsp.data_received(b"Content-Length: %d\r\n\r\n%s" % (len(body), body))
    for chunk in transport.chunks:
        message = json.loads(chunk.split(b"\r\n\r\n", 1)[-1].decode("utf-8"))
        if message.get("id") == msg_id:
            return message
    raise AssertionError(f"no response for request {msg_id}: {transport.chunks!r}")


def test_lsp_form_edit_nested_args_over_wire(form_file):
    """The {uri, op, args: {...}} shape: the nested args object arrives from pygls as a
    namedtuple. The old vars()/dict() conversion raised TypeError, pygls answered with a
    JSON-RPC error, and every write from the panels died with "engine does not answer".
    """
    server, transport = _wire_server()

    msg = _wire_request(server, transport, "xbsl/formEdit", {
        "uri": _uri(form_file), "op": "set_property",
        "args": {"node": LABEL, "key": "Ширина", "value": "220"},
    }, msg_id=1)
    assert "error" not in msg, msg
    assert msg["result"].get("error") is None, msg["result"]
    assert msg["result"]["edits"] and msg["result"]["node"]["id"] == LABEL

    msg = _wire_request(server, transport, "xbsl/formEdit", {
        "uri": _uri(form_file), "op": "insert",
        "args": {"parent": TPL, "slot": "Содержимое", "type": "Надпись", "name": "Итог"},
    }, msg_id=2)
    assert "error" not in msg, msg
    assert msg["result"].get("error") is None, msg["result"]
    assert msg["result"]["node"]["id"] == TPL + "/Содержимое[2]"
    # the wire path computes only, exactly like the direct one
    assert form_file.read_text(encoding="utf-8") == FORM


def test_lsp_form_edit_flat_params_over_wire(form_file):
    """The flat shape the VS Code panels send: op and the operation arguments directly
    in params, no nested args object."""
    server, transport = _wire_server()

    msg = _wire_request(server, transport, "xbsl/formEdit", {
        "uri": _uri(form_file), "op": "set_property",
        "node": LABEL, "key": "Заголовок", "value": "Привет",
    }, msg_id=1)
    assert "error" not in msg, msg
    assert msg["result"].get("error") is None, msg["result"]
    assert msg["result"]["edits"] and msg["result"]["node"]["id"] == LABEL

    msg = _wire_request(server, transport, "xbsl/formEdit", {
        "uri": _uri(form_file), "op": "insert",
        "parent": TPL, "slot": "Содержимое", "type": "Флажок", "name": "Показывать",
    }, msg_id=2)
    assert "error" not in msg, msg
    assert msg["result"].get("error") is None, msg["result"]
    assert msg["result"]["node"]["id"] == TPL + "/Содержимое[2]"

    # engine errors stay INSIDE the result: the request itself succeeds
    msg = _wire_request(server, transport, "xbsl/formEdit", {
        "uri": _uri(form_file), "op": "remove", "node": "Наследует",
    }, msg_id=3)
    assert "error" not in msg, msg
    assert "Корневой узел" in msg["result"]["error"]


def test_lsp_form_edit_nodes_array_over_wire(form_file):
    """The batch operations carry `nodes` as an ARRAY of strings. Over the real pygls
    channel a nested args object becomes a namedtuple, but a JSON array of SCALARS stays
    a list - _plain_params must pass the list of ids through untouched, in both the
    nested-args and the flat-params shapes.
    """
    server, transport = _wire_server()

    # nested args: {op, args: {nodes: [...]}}
    msg = _wire_request(server, transport, "xbsl/formEdit", {
        "uri": _uri(form_file), "op": "move_nodes",
        "args": {"nodes": [BUTTON, LABEL], "newParent": TPL, "slot": "Подвал"},
    }, msg_id=1)
    assert "error" not in msg, msg
    assert msg["result"].get("error") is None, msg["result"]
    assert msg["result"]["node"]["id"] == TPL + "/Подвал[0]"

    # flat params: nodes sits directly in params next to op (the panels' shape)
    msg = _wire_request(server, transport, "xbsl/formEdit", {
        "uri": _uri(form_file), "op": "remove_nodes", "nodes": [LABEL, BUTTON],
    }, msg_id=2)
    assert "error" not in msg, msg
    assert msg["result"].get("error") is None, msg["result"]
    assert msg["result"]["node"] is None and msg["result"]["edits"]

    # a scrambled selection still lands in document order - and computes only
    assert form_file.read_text(encoding="utf-8") == FORM
def test_lsp_wave3_methods_registered():
    _, features = _server_features()
    for method in ("xbsl/moduleHandlers", "xbsl/addHandler", "xbsl/objectInfo"):
        assert method in features


def test_lsp_form_tree_component_properties(form_file, props_form_file):
    _, features = _server_features()
    tree = features["xbsl/formTree"]({"uri": _uri(props_form_file)})
    assert [p["name"] for p in tree["componentProperties"]] == ["Титул"]
    assert tree["componentProperties"][0]["span"]

    assert features["xbsl/formTree"]({"uri": _uri(form_file)})["componentProperties"] == []


def test_lsp_form_edit_property_ops_and_notes(props_form_file):
    _, features = _server_features()
    bound = props_form_file.read_text(encoding="utf-8").replace(
        "Значение: Добро пожаловать", "Значение: =Титул",
    )
    props_form_file.write_bytes(bound.encode("utf-8"))
    res = features["xbsl/formEdit"]({
        "uri": _uri(props_form_file), "op": "property_rename",
        "args": {"name": "Титул", "newName": "Заглавие"},
    })
    # the pseudo id carries the record span; the binding warning rides in notes
    assert res["node"]["id"] == "Свойства/Заглавие"
    assert res["notes"] and "не переписаны" in res["notes"][0]

    res = features["xbsl/formEdit"]({
        "uri": _uri(props_form_file), "op": "property_add",
        "args": {"name": "Итог", "type": "Число"},
    })
    assert res["node"]["id"] == "Свойства/Итог" and "notes" not in res
    assert props_form_file.read_text(encoding="utf-8") == bound  # compute only


@pytest.mark.needs_data
def test_lsp_module_handlers(form_file):
    _, features = _server_features()
    res = features["xbsl/moduleHandlers"]({"uri": _uri(form_file)})
    assert res == {"available": False, "module": None, "methods": []}

    module = form_file.with_suffix(".xbsl")
    module.write_bytes(MODULE.encode("utf-8"))
    res = features["xbsl/moduleHandlers"]({"uri": _uri(form_file)})
    assert res["available"] is True and res["parseErrors"] == 0
    assert [m["name"] for m in res["methods"]] == ["Обновить"]
    # the module uri resolves the pair by stem; asking by the module itself agrees
    direct = features["xbsl/moduleHandlers"]({"uri": _uri(module)})
    assert direct["methods"] == res["methods"]


def test_lsp_add_handler_creates_module(form_file):
    _, features = _server_features()
    res = features["xbsl/addHandler"]({
        "uri": _uri(form_file), "node": BUTTON, "key": "ПриНажатии",
        "signature": SIG_CLICK,
    })
    assert res["method"] == "КнопкаОбновитьПриНажатии"
    assert res["created"] is True and res["methodAdded"] is True
    assert res["moduleEdits"] == []
    assert res["moduleText"].startswith(
        "метод КнопкаОбновитьПриНажатии(Источник: Кнопка, Событие: СобытиеПриНажатии)"
    )
    assert res["yamlEdits"] and set(res["yamlEdits"][0]) == {"start", "end", "newText"}
    assert res["cursor"]["uri"] == res["moduleUri"]
    at = res["cursor"]["offset"]
    assert res["moduleText"][at : at + len(res["method"])] == res["method"]
    # compute only: neither file is touched
    assert form_file.read_text(encoding="utf-8") == FORM
    assert not form_file.with_suffix(".xbsl").exists()


@pytest.mark.needs_data
def test_lsp_add_handler_existing_module(form_file):
    _, features = _server_features()
    module = form_file.with_suffix(".xbsl")
    module.write_bytes(MODULE.encode("utf-8"))
    res = features["xbsl/addHandler"]({
        "uri": _uri(form_file), "node": BUTTON, "key": "ПриНажатии",
        "signature": SIG_CLICK,
    })
    assert res["created"] is False and res["methodAdded"] is True
    assert "moduleText" not in res and res["moduleEdits"]
    edit = res["moduleEdits"][0]
    assert edit["start"] == edit["end"] == len(MODULE)

    bind = features["xbsl/addHandler"]({
        "uri": _uri(form_file), "node": BUTTON, "key": "ПриНажатии",
        "method": "Обновить",
    })
    assert bind["methodAdded"] is False and bind["moduleEdits"] == []
    assert bind["notes"]

    err = features["xbsl/addHandler"]({
        "uri": _uri(form_file), "node": "Наследует/Нет", "key": "ПриНажатии",
    })
    assert "не найден" in err["error"].lower()


def test_lsp_object_info(tmp_path):
    from xbsl import scaffold as sc

    _, features = _server_features()
    sc.apply_result(sc.op_new_object(tmp_path, "Справочник", "Товары"))
    res = features["xbsl/objectInfo"]({"root": str(tmp_path), "name": "Товары"})
    assert res["kind"] == "Справочник"
    assert [f["name"] for f in res["fields"]] == ["Наименование"]
    # the explicit path form mirrors meta_object_info too
    by_path = features["xbsl/objectInfo"]({
        "root": str(tmp_path), "path": str(tmp_path / "Товары.yaml"),
    })
    assert by_path["name"] == "Товары"

    err = features["xbsl/objectInfo"]({"root": str(tmp_path), "name": "Нет"})
    assert "error" in err
