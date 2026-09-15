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
