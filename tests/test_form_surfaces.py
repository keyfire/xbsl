"""Form designer surfaces: meta_*component* MCP tools, CLI form-* and xbsl/form* LSP.

The same pattern as test_meta_surfaces.py: MCP is loaded via a stub FastMCP (the [mcp]
extra is not needed), the CLI goes through cli.main, and the LSP handlers are driven
directly when pygls is installed (skipped otherwise). All three surfaces sit on the same
xbsl.formmodel/xbsl.formedits pair, so the shapes must agree.
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


@pytest.fixture()
def form_file(tmp_path):
    path = tmp_path / "Витрина.yaml"
    path.write_text(FORM, encoding="utf-8")
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
