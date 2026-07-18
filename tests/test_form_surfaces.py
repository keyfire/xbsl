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


@pytest.fixture()
def form_file(tmp_path):
    path = tmp_path / "Витрина.yaml"
    # write_bytes keeps LF as is (write_text would turn it into CRLF on Windows and
    # desynchronize the FORM.find offsets the LSP assertions rely on)
    path.write_bytes(FORM.encode("utf-8"))
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
