"""Context ownership decisions that do not require generated Element data."""

from __future__ import annotations

from xbsl.translation import dictionary as dict_module
from xbsl.translation import platform_map
from xbsl.translation import code as code_module
from xbsl.translation import yamlfile
from xbsl.translation.code import Resolver, apply_edits
from xbsl.translation.reporting import FileReport


def _dictionary(tokens: dict | None = None) -> dict_module.Dictionary:
    return dict_module.Dictionary(tokens=dict(tokens or {}), phrases={}, literals={})


def test_annotation_catalog_uses_inheritance_instead_of_the_name_shape(monkeypatch):
    catalog = {
        "bases": {
            "Обработчик": ["Аннотация", "Объект"],
            "МеткаПроверки": ["Объект"],
        },
    }
    monkeypatch.setattr(code_module.dataset, "load_json", lambda _name: catalog)
    monkeypatch.setattr(
        code_module.terms,
        "forms",
        lambda name, _section: {
            "Аннотация": ("Аннотация", "Annotation"),
            "Обработчик": ("Обработчик", "Handler"),
        }.get(name, (name,)),
    )
    code_module._platform_annotation_names.cache_clear()
    try:
        assert code_module._platform_annotation_names() == frozenset({"Обработчик", "Handler"})
    finally:
        code_module._platform_annotation_names.cache_clear()


def test_platform_annotation_and_project_homonym_use_their_own_planes(monkeypatch):
    monkeypatch.setattr(
        code_module, "_platform_annotation_names", lambda: frozenset({"Обработчик"})
    )
    monkeypatch.setattr(
        platform_map, "type_english", lambda name: "Handler" if name == "Обработчик" else None
    )
    resolver = Resolver(
        _dictionary({"Обработчик": "ProjectHandler"}),
        project_names=frozenset({"Обработчик"}),
    )

    assert resolver.annotation_name("Обработчик") == ("Handler", code_module.PLATFORM_TYPE)
    assert resolver.identifier("Обработчик") == ("ProjectHandler", "user")


def _component_mapping(text: str, resolver: Resolver, monkeypatch) -> str:
    mapping = {
        "Обработчик": "Handler",
        "Представление": "Presentation",
        "Изображение": "Image",
        "Элементы": "Items",
    }
    monkeypatch.setattr(platform_map, "property_english", mapping.get)
    root = yamlfile.yaml.compose(text)
    edits = []
    yamlfile._walk_component_mapping(
        root, resolver, FileReport(path="Component.yaml"), edits
    )
    return apply_edits(text, edits)


def test_typed_standard_and_declared_project_components_own_their_keys(monkeypatch):
    resolver = Resolver(
        _dictionary({"Обработчик": "ProjectHandler"}),
        project_names=frozenset({"Обработчик"}),
        project_component_types=frozenset({"Panel", "Acme::Demo::Panel"}),
    )

    standard = _component_mapping(
        "Type: CommandWithParameter<String>\nОбработчик: Run\n", resolver, monkeypatch
    )
    project = _component_mapping(
        "Type: Panel\nОбработчик: Run\n", resolver, monkeypatch
    )
    qualified_project = _component_mapping(
        "Type: Acme::Demo::Panel\nОбработчик: Run\n", resolver, monkeypatch
    )
    qualified_platform = _component_mapping(
        "Type: Std::Interface::Panel\nОбработчик: Run\n", resolver, monkeypatch
    )

    assert "Handler: Run" in standard
    assert "ProjectHandler: Run" in project
    assert "ProjectHandler: Run" in qualified_project
    assert "Handler: Run" in qualified_platform


def test_type_facet_and_plain_member_keep_separate_contexts(monkeypatch):
    monkeypatch.setattr(
        platform_map,
        "facet_suffix_english",
        lambda name: "Object" if name == "Объект" else None,
    )
    monkeypatch.setattr(
        platform_map,
        "type_english",
        lambda name: "CommandWithParameter" if name == "КомандаСПараметром" else None,
    )
    resolver = Resolver(
        _dictionary({
            "Объект": "ProjectObjectField",
            "КомандаСПараметром": "ProjectCommandName",
            "Событие": "Occurrence",
        }),
        project_names=frozenset({"Объект", "КомандаСПараметром", "Событие"}),
        project_types=frozenset({"Событие"}),
    )

    assert resolver.type_name("Объект", after_dot=True) == ("Object", "platform")
    assert resolver.identifier("Объект", after_dot=True) == ("ProjectObjectField", "user")
    assert resolver.type_name("КомандаСПараметром") == (
        "CommandWithParameter", code_module.PLATFORM_TYPE,
    )
    assert resolver.identifier("КомандаСПараметром") == ("ProjectCommandName", "user")
    assert resolver.type_name("Событие") == ("Occurrence", "user")


# --- the values of a platform facet ------------------------------------------------------------


def _facet_root(tmp_path, name: str, *, with_facet_values: bool = True):
    """A data root that knows the privilege facet of the generic entity and one enumeration of its
    own - the table of the facet is present only when asked."""
    import json

    root = tmp_path / name
    version = root / "1.0.0"
    version.mkdir(parents=True)
    tables = {"ВидДоступаАкме": {"Изменение": "Change"}}
    if with_facet_values:
        tables["Сущность.Право"] = {
            "Изменение": "Update", "Создание": "Create", "Удаление": "Delete", "Чтение": "Read",
        }
    files = {
        "terms.json": {"facets": {"Сущность.Право": "Entity.Privilege"}},
        "stdlib.json": {"facet_members": {"Сущность.Право": {
            "properties": ["Изменение", "Создание", "Удаление", "Чтение"]}}},
        "uiterms.json": {"enum_values": tables},
    }
    for file, content in files.items():
        (version / file).write_text(json.dumps(content, ensure_ascii=False), encoding="utf-8")
    (root / "index.json").write_text(
        json.dumps({"available": ["1.0.0"], "default": "1.0.0"}), encoding="utf-8")
    return root


def test_a_facet_value_is_spelled_by_the_table_of_the_whole_facet(tmp_path):
    """The owner is the facet as a whole, in either spelling of either part."""
    platform_map.dataset.set_data_root(_facet_root(tmp_path, "data"))
    try:
        assert platform_map.facet_value_of("Сущность", "Право", "Чтение") == "Read"
        assert platform_map.facet_value_of("Entity", "Privilege", "Удаление") == "Delete"
        assert platform_map.facet_value_of("Сущность", "Privilege", "Изменение") == "Update"
        assert platform_map.facet_value_of("Entity", "Право", "Создание") == "Create"
    finally:
        platform_map.dataset.set_data_root(None)


def test_a_value_after_what_is_no_facet_of_the_platform_answers_nothing(tmp_path):
    platform_map.dataset.set_data_root(_facet_root(tmp_path, "data"))
    try:
        assert platform_map.facet_value_of("Склады", "Право", "Чтение") is None
        assert platform_map.facet_value_of("Сущность", "Ссылка", "Чтение") is None
        assert platform_map.facet_value_of("Сущность", "Право", "Архив") is None
        assert platform_map.facet_value_of("", "Право", "Чтение") is None
    finally:
        platform_map.dataset.set_data_root(None)


def test_the_values_of_a_facet_stay_out_of_the_tables_read_without_an_owner(tmp_path):
    """A value whose enumeration is not pinned is answered only when every table agrees. The
    table of a facet is read through the facet alone: counted there, it would take the
    answer away from a word only one enumeration spells."""
    platform_map.dataset.set_data_root(_facet_root(tmp_path, "data"))
    try:
        assert platform_map._unanimous_enum_value("Изменение") == "Change"
    finally:
        platform_map.dataset.set_data_root(None)


def test_data_without_the_facet_table_keeps_the_value_and_is_read_afresh(tmp_path):
    with_table = _facet_root(tmp_path, "with")
    without = _facet_root(tmp_path, "without", with_facet_values=False)
    try:
        platform_map.dataset.set_data_root(with_table)
        assert platform_map.facet_value_of("Сущность", "Право", "Чтение") == "Read"
        platform_map.dataset.set_data_root(without)
        assert platform_map.facet_value_of("Сущность", "Право", "Чтение") is None
    finally:
        platform_map.dataset.set_data_root(None)
