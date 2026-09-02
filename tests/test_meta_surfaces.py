"""Scaffolding surfaces: meta_* MCP tools, CLI subcommands and xbsl/meta* LSP methods.

MCP is loaded via the stub FastMCP of the `mcp_module` fixture (conftest) - the [mcp]
extra is not needed; the LSP part checks the handlers directly when pygls is installed,
otherwise it is skipped.
"""

import inspect
import json
from pathlib import Path

import pytest

from xbsl import cli, scaffold


def test_mcp_meta_tools_registered(mcp_module):
    expected = {
        "meta_project_info", "meta_object_info", "meta_new_project", "meta_new_object",
        "meta_add_field", "meta_add_route", "meta_add_form", "meta_add_subsystem",
        "meta_add_dependency",
    }
    assert expected.issubset(mcp_module.mcp.tools)


def test_mcp_meta_new_object_writes_and_lints(mcp_module, tmp_path):
    res = mcp_module.meta_new_object(str(tmp_path), "Справочник", "Товары")
    assert [f["path"] for f in res["files"]] == [str(tmp_path / "Товары.yaml")]
    assert res["files"][0]["created"] is True
    assert "lint" in res
    assert (tmp_path / "Товары.yaml").is_file()

    dup = mcp_module.meta_new_object(str(tmp_path), "Справочник", "Товары")
    assert "уже существует" in dup["error"]


def test_mcp_meta_field_and_info(mcp_module, tmp_path):
    mcp_module.meta_new_object(str(tmp_path), "Справочник", "Товары")
    res = mcp_module.meta_add_field(str(tmp_path / "Товары.yaml"), "реквизит", "Цвет")
    assert res["files"][0]["created"] is False

    info = mcp_module.meta_object_info(str(tmp_path), name="Товары")
    assert [f["name"] for f in info["fields"]] == ["Наименование", "Цвет"]

    overview = mcp_module.meta_project_info(str(tmp_path))
    assert any(o["name"] == "Товары" for o in overview["objects"])
    assert "Справочник" in overview["creatable_kinds"]


# --- CLI ---------------------------------------------------------------------------------


def _run_cli(capsys, *argv) -> tuple[int, dict]:
    code = cli.main(list(argv))
    out = capsys.readouterr().out.strip()
    return code, json.loads(out)


def test_cli_new_object_and_field(tmp_path, capsys):
    code, out = _run_cli(capsys, "new-object", str(tmp_path), "Справочник", "Товары")
    assert code == 0
    assert out["files"][0]["created"] is True

    code, out = _run_cli(
        capsys, "add-field", str(tmp_path / "Товары.yaml"), "реквизит", "Цвет", "--type", "Строка"
    )
    assert code == 0
    text = (tmp_path / "Товары.yaml").read_text(encoding="utf-8")
    assert "Имя: Цвет" in text


def test_cli_dry_run_writes_nothing(tmp_path, capsys):
    code, out = _run_cli(capsys, "new-object", str(tmp_path), "Справочник", "Товары", "--dry-run")
    assert code == 0
    assert out["files"][0]["content"].startswith("ВидЭлемента: Справочник")
    assert not (tmp_path / "Товары.yaml").exists()


def test_cli_error_is_json(tmp_path, capsys):
    code, out = _run_cli(capsys, "new-object", str(tmp_path), "НеВид", "Имя")
    assert code == 2
    assert "не поддерживается" in out["error"]


def test_cli_project_info(tmp_path, capsys):
    scaffold.apply_result(scaffold.op_new_project(tmp_path, "vendor", "Приложение"))
    code, out = _run_cli(capsys, "project-info", str(tmp_path))
    assert code == 0
    assert out["projects"][0]["name"] == "Приложение"


@pytest.mark.needs_data
def test_cli_lint_alias(tmp_path, capsys):
    (tmp_path / "М.xbsl").write_text("метод Ф()\n;\n", encoding="utf-8")
    code = cli.main(["lint", str(tmp_path), "--format", "json"])
    assert code in (0, 1)
    json.loads(capsys.readouterr().out)


# --- LSP ---------------------------------------------------------------------------------

pygls = pytest.importorskip("pygls", reason="LSP-методы проверяются при установленном extra [lsp]")


def _server_features():
    from xbsl import lsp as lsp_module

    server = lsp_module._make_server()
    # Across pygls versions the handler registry lives in the protocol's fm.features.
    fm = getattr(server.lsp, "fm", None) or getattr(server.lsp, "_features", None)
    features = getattr(fm, "features", fm)
    return server, features


def test_lsp_meta_methods_registered():
    _, features = _server_features()
    for method in (
        "xbsl/metaCapabilities", "xbsl/metaNewObject", "xbsl/metaAddField",
        "xbsl/metaAddForm", "xbsl/metaAddRoute", "xbsl/metaAddSubsystem",
    ):
        assert method in features


def test_lsp_meta_capabilities_and_new_object(tmp_path):
    _, features = _server_features()
    caps = features["xbsl/metaCapabilities"](None)
    assert "Справочник" in caps["kinds"]
    assert "Отчет" not in caps["kinds"] and "Отчет" in caps["allKinds"]

    result = features["xbsl/metaNewObject"](
        {"directory": str(tmp_path), "kind": "Справочник", "name": "Товары"}
    )
    files = result["files"]
    assert files[0]["path"].endswith("Товары.yaml")
    assert files[0]["content"].startswith("ВидЭлемента: Справочник")
    # LSP only computes: nothing is written to disk - the editor applies the changes.
    assert not (tmp_path / "Товары.yaml").exists()


def test_lsp_meta_add_field_error_shape(tmp_path):
    _, features = _server_features()
    result = features["xbsl/metaAddField"](
        {"path": str(tmp_path / "Нет.yaml"), "fieldKind": "реквизит", "name": "Цвет"}
    )
    assert "не найден" in result["error"].lower()


def test_mcp_meta_rename_object(mcp_module, tmp_path):
    mcp_module.meta_new_object(str(tmp_path), "Справочник", "Склады")
    mcp_module.meta_new_object(str(tmp_path), "Справочник", "Заказы")
    mcp_module.meta_add_field(str(tmp_path / "Заказы.yaml"), "реквизит", "Склад",
                              type="Склады.Ссылка?")

    plan = mcp_module.meta_rename_object(str(tmp_path), "Склады", "Хранилища", dry_run=True)
    assert plan["renames"] == [
        {"from": str(tmp_path / "Склады.yaml"), "to": str(tmp_path / "Хранилища.yaml")}
    ]
    assert all("content" not in f for f in plan["files"])
    assert (tmp_path / "Склады.yaml").is_file()  # dry_run writes nothing

    res = mcp_module.meta_rename_object(str(tmp_path), "Склады", "Хранилища")
    assert res["renames"] and "lint" in res
    assert (tmp_path / "Хранилища.yaml").is_file()
    assert not (tmp_path / "Склады.yaml").exists()
    assert "Тип: Хранилища.Ссылка?" in (tmp_path / "Заказы.yaml").read_text(encoding="utf-8")

    err = mcp_module.meta_rename_object(str(tmp_path), "Нет", "Куда")
    assert "не найден" in err["error"]


def test_cli_rename_object(capsys, tmp_path):
    _run_cli(capsys, "new-object", str(tmp_path), "Справочник", "Склады")
    code, plan = _run_cli(
        capsys, "rename-object", str(tmp_path), "Склады", "Хранилища", "--dry-run"
    )
    assert code == 0
    assert plan["renames"][0]["to"].endswith("Хранилища.yaml")
    assert (tmp_path / "Склады.yaml").is_file()

    code, out = _run_cli(capsys, "rename-object", str(tmp_path), "Склады", "Хранилища")
    assert code == 0
    assert out["renames"] and (tmp_path / "Хранилища.yaml").is_file()

    code, err = _run_cli(capsys, "rename-object", str(tmp_path), "Склады", "Хранилища")
    assert code == 2 and "не найден" in err["error"]


def test_mcp_meta_add_form_cards(mcp_module, tmp_path):
    mcp_module.meta_new_object(str(tmp_path), "Справочник", "Сотрудники")
    mcp_module.meta_add_field(str(tmp_path / "Сотрудники.yaml"), "реквизит", "Фото",
                              type="ДвоичныйОбъект.Ссылка?")
    res = mcp_module.meta_add_form(str(tmp_path), name="Сотрудники", forms=["list-cards"],
                                   card_min_width=320)
    created = [f["path"] for f in res["files"] if f["created"]]
    assert str(tmp_path / "СотрудникиФормаСписка.yaml") in created
    assert str(tmp_path / "СтрокаСпискаСотрудники.yaml") in created
    assert "lint" in res
    form = (tmp_path / "СотрудникиФормаСписка.yaml").read_text(encoding="utf-8")
    assert "МинимальнаяШирина: 320" in form
    assert "ТипКомпонентаСтроки: СтрокаСпискаСотрудники" in form

    err = mcp_module.meta_add_form(str(tmp_path), name="Сотрудники", forms=["list", "list-cards"])
    assert "выберите одну" in err["error"]


def test_cli_add_form_cards(capsys, tmp_path):
    _run_cli(capsys, "new-object", str(tmp_path), "Справочник", "Сотрудники")
    code, out = _run_cli(capsys, "add-form", str(tmp_path), "--name", "Сотрудники",
                         "--forms", "list-cards", "--card-min-width", "300")
    assert code == 0
    names = {Path(f["path"]).name for f in out["files"]}
    assert {"СотрудникиФормаСписка.yaml", "СтрокаСпискаСотрудники.yaml"} <= names
    assert "МинимальнаяШирина: 300" in (tmp_path / "СотрудникиФормаСписка.yaml").read_text(encoding="utf-8")


def test_mcp_meta_set_access(mcp_module, tmp_path):
    mcp_module.meta_new_object(str(tmp_path), "Справочник", "Товары")
    res = mcp_module.meta_set_access(str(tmp_path), name="Товары",
                                     default="РазрешеноАутентифицированным",
                                     permissions={"Чтение": "РазрешеноВсем"})
    assert res["files"][0]["created"] is False
    assert "lint" in res
    text = (tmp_path / "Товары.yaml").read_text(encoding="utf-8")
    assert "        ПоУмолчанию: РазрешеноАутентифицированным" in text
    assert "        Чтение: РазрешеноВсем" in text

    info = mcp_module.meta_object_info(str(tmp_path), name="Товары")
    assert info["access"]["default"] == "РазрешеноАутентифицированным"
    assert info["access"]["permissions"]["Чтение"] == "РазрешеноВсем"

    overview = mcp_module.meta_project_info(str(tmp_path))
    товары = next(o for o in overview["objects"] if o["name"] == "Товары")
    assert товары["access_default"] == "РазрешеноАутентифицированным"
    assert "РазрешенияВычисляются" in overview["access_methods"]

    err = mcp_module.meta_set_access(str(tmp_path), name="Товары", default="ЧтоТоНеТо")
    assert "Недопустимый способ" in err["error"]


def test_cli_set_access(capsys, tmp_path):
    _run_cli(capsys, "new-object", str(tmp_path), "Справочник", "Задачи")
    _run_cli(capsys, "add-field", str(tmp_path / "Задачи.yaml"), "реквизит", "Ответственный",
             "--type", "Пользователи.Ссылка?")
    code, out = _run_cli(capsys, "set-access", str(tmp_path), "--name", "Задачи",
                         "--default", "РазрешенияВычисляютсяДляКаждогоОбъекта",
                         "--calc-by", "Ответственный")
    assert code == 0
    text = (tmp_path / "Задачи.yaml").read_text(encoding="utf-8")
    assert "РасчетРазрешенийПо: [Ответственный]" in text
    assert any("ВычислитьРазрешенияДоступаДляОбъектов" in n for n in out["notes"])

    code, err = _run_cli(capsys, "set-access", str(tmp_path), "--name", "Задачи",
                         "--permission", "Чтение")
    assert code == 2 and "ПРАВО=СПОСОБ" in err["error"]


@pytest.mark.needs_data  # linting the written Проект.xbsl tokenizes it - needs language.json
def test_mcp_meta_add_dependency(mcp_module, tmp_path):
    mcp_module.meta_new_project(str(tmp_path), "vendor", "Приложение")
    res = mcp_module.meta_add_dependency(str(tmp_path), "acme", "CurrencyConverter", "9.0.2")
    assert res["files"][0]["created"] is False
    text = (tmp_path / "vendor" / "Приложение" / "Проект.yaml").read_text(encoding="utf-8")
    assert "Библиотеки:" in text and "Имя: CurrencyConverter" in text

    overview = mcp_module.meta_project_info(str(tmp_path))
    assert overview["projects"][0]["libraries"] == [
        {"Имя": "CurrencyConverter", "Поставщик": "acme", "Версия": "9.0.2"}
    ]

    err = mcp_module.meta_add_dependency(str(tmp_path), "acme", "CurrencyConverter", "1.0-42")
    assert "версия сборки" in err["error"]


def test_cli_add_dependency(capsys, tmp_path):
    _run_cli(capsys, "new-project", str(tmp_path), "vendor", "Приложение")
    code, out = _run_cli(capsys, "add-dependency", str(tmp_path), "acme", "CurrencyConverter", "2.0")
    assert code == 0
    assert any("Подключена библиотека acme::CurrencyConverter" in n for n in out["notes"])
    assert "Версия: 2.0" in (tmp_path / "vendor" / "Приложение" / "Проект.yaml").read_text(
        encoding="utf-8"
    )


@pytest.mark.needs_data
def test_mcp_type_members(mcp_module):
    got = mcp_module.type_members("КлиентHttp")
    assert got["type"] == "КлиентHttp"
    assert got["methods"].get("ЗапросGet") == "ЗапросHttp"
    aggr = mcp_module.type_members("Пользователи")
    assert "Пользователи.Объект" in aggr.get("facets", [])
    miss = mcp_module.type_members("НетТакогоТипа")
    assert "error" in miss and "close_matches" in miss


# --- the caller's root -------------------------------------------------------------------
#
# The server's working directory is where the CLIENT started it, not where the caller works: a
# session in a git worktree that passed `vendor/app/Main` had its files created in the main
# checkout, and the answer's relative paths looked right. Every meta_* tool therefore takes
# `root`, resolves relative paths against it and answers with absolute paths plus the root they
# were counted from - the discrepancy shows without a find.


def _elsewhere(tmp_path, monkeypatch) -> tuple[Path, Path]:
    """A server started in one directory while the caller works in another."""
    server_cwd = tmp_path / "server"
    server_cwd.mkdir()
    monkeypatch.chdir(server_cwd)
    root = tmp_path / "worktree"
    root.mkdir()
    return server_cwd, root


def test_every_meta_tool_takes_root_and_documents_it(mcp_module):
    for name, tool in mcp_module.mcp.tools.items():
        if name.startswith("meta_"):
            assert "root" in inspect.signature(tool).parameters, name
            assert "root" in (tool.__doc__ or ""), name


def test_mcp_meta_new_object_lands_under_the_callers_root(mcp_module, tmp_path, monkeypatch):
    server_cwd, root = _elsewhere(tmp_path, monkeypatch)
    res = mcp_module.meta_new_object("vendor/app/Main", "Справочник", "Задачи", root=str(root))
    expected = root / "vendor" / "app" / "Main" / "Задачи.yaml"
    assert [f["path"] for f in res["files"]] == [str(expected)]
    assert res["root"] == str(root)
    assert expected.is_file()
    assert not (server_cwd / "vendor").exists()


def test_mcp_meta_without_root_stays_in_the_server_directory_but_answers_absolute(
    mcp_module, tmp_path, monkeypatch,
):
    monkeypatch.chdir(tmp_path)
    res = mcp_module.meta_new_object("Main", "Справочник", "Задачи")
    assert res["root"] == str(tmp_path)
    assert [f["path"] for f in res["files"]] == [str(tmp_path / "Main" / "Задачи.yaml")]
    assert (tmp_path / "Main" / "Задачи.yaml").is_file()


def test_mcp_meta_yaml_path_resolves_against_root(mcp_module, tmp_path, monkeypatch):
    server_cwd, root = _elsewhere(tmp_path, monkeypatch)
    mcp_module.meta_new_object("Main", "Справочник", "Задачи", root=str(root))
    yaml_path = root / "Main" / "Задачи.yaml"

    res = mcp_module.meta_add_field("Main/Задачи.yaml", "реквизит", "Цвет", root=str(root))
    assert [f["path"] for f in res["files"]] == [str(yaml_path)]
    assert "Цвет" in yaml_path.read_text(encoding="utf-8")
    assert not (server_cwd / "Main").exists()

    info = mcp_module.meta_object_info(str(root), yaml_path="Main/Задачи.yaml")
    assert info["path"] == str(yaml_path)
    assert info["root"] == str(root)


@pytest.mark.needs_data  # the written files are linted, and linting tokenizes them - needs language.json
def test_mcp_meta_project_info_answers_absolute_paths_for_a_relative_root(
    mcp_module, tmp_path, monkeypatch,
):
    monkeypatch.chdir(tmp_path)
    mcp_module.meta_new_project("repo", "vendor", "app")
    mcp_module.meta_new_object("repo/vendor/app/Основное", "Справочник", "Задачи")

    overview = mcp_module.meta_project_info("repo")
    assert overview["root"] == str(tmp_path / "repo")
    assert overview["projects"][0]["dir"] == str(tmp_path / "repo" / "vendor" / "app")
    assert [o["path"] for o in overview["objects"]] == [
        str(tmp_path / "repo" / "vendor" / "app" / "Основное" / "Задачи.yaml")
    ]


@pytest.mark.needs_data  # the written files are linted, and linting tokenizes them - needs language.json
def test_mcp_meta_form_tools_resolve_against_root(mcp_module, tmp_path, monkeypatch):
    _server_cwd, root = _elsewhere(tmp_path, monkeypatch)
    mcp_module.meta_new_object("Main", "Справочник", "Задачи", root=str(root))
    mcp_module.meta_add_form(str(root), name="Задачи", forms=["object"])
    form = "Main/ЗадачиФормаОбъекта.yaml"

    tree = mcp_module.meta_component_tree(form, root=str(root))
    assert tree["file"] == str(root / "Main" / "ЗадачиФормаОбъекта.yaml")
    assert tree["root"]["type"].startswith("Форма")

    res = mcp_module.meta_add_component(
        form, tree["root"]["id"], "Содержимое", type="Кнопка", name="Проба", root=str(root),
    )
    assert [f["path"] for f in res["files"]] == [str(root / "Main" / "ЗадачиФормаОбъекта.yaml")]
    assert res["root"] == str(root)

    bound = mcp_module.meta_add_handler(form, res["node"]["id"], "ПриНажатии", root=str(root))
    assert bound["module"] == str(root / "Main" / "ЗадачиФормаОбъекта.xbsl")
    assert bound["root"] == str(root)


@pytest.mark.needs_data  # the written files are linted, and linting tokenizes them - needs language.json
def test_mcp_meta_module_and_subsystem_tools_resolve_against_root(
    mcp_module, tmp_path, monkeypatch,
):
    _server_cwd, root = _elsewhere(tmp_path, monkeypatch)
    res = mcp_module.meta_add_subsystem("vendor/app", "Новая", root=str(root))
    assert [f["path"] for f in res["files"]] == [
        str(root / "vendor" / "app" / "Новая" / "Подсистема.yaml")
    ]
    mcp_module.meta_new_object("vendor/app/Новая", "ОбщийМодуль", "Служебный", root=str(root))

    res = mcp_module.meta_add_method("vendor/app/Новая/Служебный.xbsl", "Проба", root=str(root))
    assert [f["path"] for f in res["files"]] == [
        str(root / "vendor" / "app" / "Новая" / "Служебный.xbsl")
    ]
    assert res["root"] == str(root)


def test_mcp_meta_dry_runs_and_errors_name_the_root(mcp_module, tmp_path, monkeypatch):
    _server_cwd, root = _elsewhere(tmp_path, monkeypatch)
    mcp_module.meta_new_object(".", "Справочник", "Склады", root=str(root))

    plan = mcp_module.meta_rename_object(str(root), "Склады", "Хранилища", dry_run=True)
    assert plan["root"] == str(root)
    assert plan["renames"] == [
        {"from": str(root / "Склады.yaml"), "to": str(root / "Хранилища.yaml")}
    ]

    plan = mcp_module.meta_delete_object(str(root), "Склады")
    assert plan["root"] == str(root) and plan["dry-run"] is True
    assert plan["deletes"] == [str(root / "Склады.yaml")]

    err = mcp_module.meta_add_field("Нет.yaml", "реквизит", "Цвет", root=str(root))
    assert str(root / "Нет.yaml") in err["error"]
    assert err["root"] == str(root)
