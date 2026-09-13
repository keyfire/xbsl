"""Packages of a subsystem in the scaffolding: placement, project_info and generated forms.

An object of a package lives in the namespace `Поставщик::Проект::Подсистема::Пакет`. The
scaffolding used to find a subsystem only in the PARENT folder of an object, so an object of
a package answered `subsystem: null` and a namespace without the subsystem - and a generated
list form spelled its row type by that namespace, an invalid name. project_info now places
every object by the same model the cross-subsystem rules use (xbsl.layout), lists the
packages, narrows by package and by project, and leaves the reference sections to the call
that asks for them.

The fixture: project `Демо::Учет` with subsystem `Склад` - a catalog at its root, a package
`Партии` (a catalog, a common module, a resources folder) and a nested package
`Партии::Архив`.
"""

import json
from pathlib import Path

import pytest

from xbsl import cli, scaffold
from xbsl.scaffold import ScaffoldError, apply_result

REFERENCE_KEYS = ("creatable_kinds", "field_kinds", "access_methods", "access_kind_rights")


def _project(tmp_path: Path) -> Path:
    apply_result(scaffold.op_new_project(tmp_path, "Демо", "Учет", subsystem="Склад"))
    project_dir = tmp_path / "Демо" / "Учет"
    stock = project_dir / "Склад"
    batches = stock / "Партии"
    archive = batches / "Архив"
    archive.mkdir(parents=True)
    apply_result(scaffold.op_new_object(stock, "Справочник", "Номенклатура"))
    apply_result(scaffold.op_new_object(batches, "Справочник", "ПартииТоваров"))
    apply_result(scaffold.op_new_object(batches, "ОбщийМодуль", "РасчетПартий"))
    apply_result(scaffold.op_new_object(archive, "Справочник", "АрхивПартий"))
    (batches / "Ресурсы").mkdir()
    (batches / "Ресурсы" / "Схема.svg").write_text("<svg/>", encoding="utf-8")
    return project_dir


def test_find_object_places_an_object_of_a_package(tmp_path):
    _project(tmp_path)
    at_root = scaffold.find_object(tmp_path, "Номенклатура")
    in_package = scaffold.find_object(tmp_path, "ПартииТоваров")
    nested = scaffold.find_object(tmp_path, "АрхивПартий")
    assert (at_root.subsystem, at_root.package, at_root.namespace) == (
        "Склад", None, "Демо::Учет::Склад")
    assert (in_package.subsystem, in_package.package, in_package.namespace) == (
        "Склад", "Партии", "Демо::Учет::Склад::Партии")
    assert (nested.package, nested.namespace) == (
        "Партии::Архив", "Демо::Учет::Склад::Партии::Архив")


def test_object_info_reports_the_package_by_name_and_by_path(tmp_path):
    project_dir = _project(tmp_path)
    by_name = scaffold.object_info(tmp_path, name="ПартииТоваров")
    by_path = scaffold.object_info(
        tmp_path, yaml_path=project_dir / "Склад" / "Партии" / "ПартииТоваров.yaml")
    for info in (by_name, by_path):
        assert (info["subsystem"], info["package"], info["namespace"]) == (
            "Склад", "Партии", "Демо::Учет::Склад::Партии")


def test_project_info_places_objects_and_lists_packages(tmp_path):
    project_dir = _project(tmp_path)
    info = scaffold.project_info(tmp_path)
    placed = {o["name"]: (o["subsystem"], o["package"], o["namespace"]) for o in info["objects"]}
    assert placed["Номенклатура"] == ("Склад", None, "Демо::Учет::Склад")
    assert placed["РасчетПартий"] == ("Склад", "Партии", "Демо::Учет::Склад::Партии")
    assert placed["АрхивПартий"] == ("Склад", "Партии::Архив", "Демо::Учет::Склад::Партии::Архив")
    # The resources folder of a package is not a package; a package counts what lies in it.
    batches = project_dir / "Склад" / "Партии"
    assert info["packages"] == [
        {"subsystem": "Склад", "package": "Партии", "dir": str(batches), "objects": 2},
        {"subsystem": "Склад", "package": "Партии::Архив", "dir": str(batches / "Архив"),
         "objects": 1},
    ]
    assert info["projects"][0]["subsystems"] == ["Склад"]


def test_an_intermediate_package_without_objects_is_listed_for_the_tree(tmp_path):
    project_dir = _project(tmp_path)
    deep = project_dir / "Склад" / "Учет" / "Сверки"
    deep.mkdir(parents=True)
    apply_result(scaffold.op_new_object(deep, "Справочник", "СверкиОстатков"))
    packages = {p["package"]: p["objects"] for p in scaffold.project_info(tmp_path)["packages"]}
    assert packages["Учет"] == 0 and packages["Учет::Сверки"] == 1


def test_the_subsystem_filter_keeps_the_objects_of_its_packages(tmp_path):
    _project(tmp_path)
    names = {o["name"] for o in scaffold.project_info(tmp_path, subsystem="склад")["objects"]}
    assert names == {"Номенклатура", "ПартииТоваров", "РасчетПартий", "АрхивПартий"}


def test_the_package_filter_takes_a_path_or_a_placement_key(tmp_path):
    _project(tmp_path)
    for spelled in ("Партии", "Склад::Партии"):
        info = scaffold.project_info(tmp_path, package=spelled)
        assert {o["name"] for o in info["objects"]} == {
            "ПартииТоваров", "РасчетПартий", "АрхивПартий"}
        assert info["filter"]["package"] == spelled
    nested = scaffold.project_info(tmp_path, package="Партии::Архив")
    assert [o["name"] for o in nested["objects"]] == ["АрхивПартий"]
    assert [p["package"] for p in nested["packages"]] == ["Партии::Архив"]
    assert nested["object_counts"]["Справочник"] == 3  # what the project holds


def test_the_packages_list_follows_the_filters_of_the_objects(tmp_path):
    """A narrow question must not drag the packages of the whole root along: at a repository
    root with vendor examples beside the project the unfiltered list took a narrow answer
    from 6 KB to 26 KB."""
    project_dir = _project(tmp_path)
    modules = scaffold.project_info(tmp_path, kind="ОбщийМодуль")
    assert [o["name"] for o in modules["objects"]] == ["РасчетПартий"]
    assert modules["packages"] == [{
        "subsystem": "Склад", "package": "Партии",
        "dir": str(project_dir / "Склад" / "Партии"), "objects": 1,
    }]
    # An object deep in a nested package brings the enclosing package along, uncounted.
    archive = scaffold.project_info(tmp_path, kind="Справочник", package="Партии")
    assert [(p["package"], p["objects"]) for p in archive["packages"]] == [
        ("Партии", 1), ("Партии::Архив", 1)]
    assert scaffold.project_info(tmp_path, subsystem="Нет")["packages"] == []


def test_find_projects_lists_a_subsystem_folder_without_a_descriptor(tmp_path):
    """A shipped library keeps a subsystem with no descriptor: objects make the folder one."""
    project_dir = _project(tmp_path)
    queue = project_dir / "Очередь" / "Сообщения"
    queue.mkdir(parents=True)
    apply_result(scaffold.op_new_object(queue, "Справочник", "Конверты"))
    (project_dir / "Пустая").mkdir()
    (project_dir / "Ресурсы").mkdir()
    (project_dir / ".служебная").mkdir()
    assert scaffold.find_projects(tmp_path)[0]["subsystems"] == ["Очередь", "Склад"]
    hit = scaffold.find_object(tmp_path, "Конверты")
    assert (hit.subsystem, hit.package, hit.namespace) == (
        "Очередь", "Сообщения", "Демо::Учет::Очередь::Сообщения")


def test_the_reference_sections_come_on_request_or_with_brief(tmp_path):
    _project(tmp_path)
    plain = scaffold.project_info(tmp_path)
    assert not any(key in plain for key in REFERENCE_KEYS)
    asked = scaffold.project_info(tmp_path, kind="Справочник", reference=True)
    assert all(key in asked for key in REFERENCE_KEYS)
    assert "Справочник" in asked["creatable_kinds"]
    brief = scaffold.project_info(tmp_path, brief=True)
    assert all(key in brief for key in REFERENCE_KEYS)
    assert "objects" not in brief and "packages" not in brief
    assert len(json.dumps(plain, ensure_ascii=False)) < len(json.dumps(asked, ensure_ascii=False))


def test_the_project_filter_walks_only_that_project(tmp_path):
    _project(tmp_path)
    apply_result(scaffold.op_new_project(tmp_path / "примеры", "Пример", "Черновик"))
    draft = tmp_path / "примеры" / "Пример" / "Черновик" / "Основное"
    apply_result(scaffold.op_new_object(draft, "Перечисление", "Статусы"))

    whole = scaffold.project_info(tmp_path)
    assert whole["object_counts"].get("Перечисление") == 1
    for spelled in ("Учет", "демо::учет"):
        narrowed = scaffold.project_info(tmp_path, project=spelled)
        assert [p["name"] for p in narrowed["projects"]] == ["Учет"]
        assert "Перечисление" not in narrowed["object_counts"]
        assert {o["namespace"].split("::")[1] for o in narrowed["objects"]} == {"Учет"}
        assert narrowed["filter"]["project"] == spelled
    with pytest.raises(ScaffoldError, match="Демо::Учет"):
        scaffold.project_info(tmp_path, project="Нет")


def test_the_project_filter_tells_same_named_checkouts_apart_by_folder(tmp_path):
    """Two checkouts of one project under a root share `Vendor::Name`; the folder picks one."""
    _project(tmp_path)
    copy_root = tmp_path / "копия"
    apply_result(scaffold.op_new_project(copy_root, "Демо", "Учет"))
    apply_result(scaffold.op_new_object(copy_root / "Демо" / "Учет" / "Основное",
                                        "Перечисление", "Статусы"))
    both = scaffold.project_info(tmp_path, project="Демо::Учет")
    assert len(both["projects"]) == 2 and both["object_counts"].get("Перечисление") == 1
    for spelled in ("Демо/Учет", str(tmp_path / "Демо" / "Учет")):
        one = scaffold.project_info(tmp_path, project=spelled)
        assert [p["dir"] for p in one["projects"]] == [str(tmp_path / "Демо" / "Учет")]
        assert "Перечисление" not in one["object_counts"]


def test_a_list_form_of_a_package_object_spells_the_package_in_the_row_type(tmp_path):
    _project(tmp_path)
    result = scaffold.op_add_form(tmp_path, name="ПартииТоваров", forms=["list"])
    form = next(c for c in result.changes if c.path.name == "ПартииТоваровФормаСписка.yaml")
    assert "Демо::Учет::Склад::Партии::ПартииТоваровФормаСписка.ДанныеСтрокиСписка" in form.content


def test_mcp_meta_add_form_and_project_info_for_a_package(mcp_module, tmp_path):
    project_dir = _project(tmp_path)
    mcp_module.meta_add_form(str(tmp_path), name="ПартииТоваров", forms=["list"])
    written = project_dir / "Склад" / "Партии" / "ПартииТоваровФормаСписка.yaml"
    assert "Демо::Учет::Склад::Партии::ПартииТоваровФормаСписка.ДанныеСтрокиСписка" in \
        written.read_text(encoding="utf-8")

    overview = mcp_module.meta_project_info(str(tmp_path), package="Партии", project="Учет")
    assert overview["filter"] == {
        "project": "Учет", "kind": None, "subsystem": None, "package": "Партии"}
    assert not any(key in overview for key in REFERENCE_KEYS)
    asked = mcp_module.meta_project_info(str(tmp_path), reference=True)
    assert "Справочник" in asked["creatable_kinds"]


def test_cli_project_info_takes_the_same_keys(tmp_path, capsys):
    _project(tmp_path)
    code = cli.main(["project-info", str(tmp_path), "--package", "Партии::Архив",
                     "--project", "Учет", "--reference"])
    out = json.loads(capsys.readouterr().out)
    assert code == 0
    assert [o["name"] for o in out["objects"]] == ["АрхивПартий"]
    assert out["objects"][0]["package"] == "Партии::Архив"
    assert "creatable_kinds" in out and out["filter"]["project"] == "Учет"
