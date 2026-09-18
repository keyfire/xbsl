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


# --- the pictures of the platform's library ------------------------------------------------------

#: The pairs of a library as the extractor files them: a Russian path, its English twin.
_PICTURES = {
    "Icons/Стд/Ресурсы/Команда.svg": "Icons/Std/Resources/Team.svg",
    "Icons/Стд/Ресурсы/Письмо.svg": "Icons/Std/Resources/Mail.svg",
    "Icons/Стд/Ресурсы/Папка/Вложенная.svg": "Icons/Std/Resources/Folder/Nested.svg",
}


def _picture_root(tmp_path, name: str, pictures: dict | None = _PICTURES):
    """A data root whose ui vocabulary carries the given pictures - or no such section at all,
    the way data extracted before the pictures looks."""
    import json

    root = tmp_path / name
    version = root / "1.0.0"
    version.mkdir(parents=True)
    uiterms: dict = {"enum_values": {}}
    if pictures is not None:
        uiterms["resource_paths"] = pictures
    (version / "uiterms.json").write_text(json.dumps(uiterms, ensure_ascii=False), encoding="utf-8")
    (root / "index.json").write_text(
        json.dumps({"available": ["1.0.0"], "default": "1.0.0"}), encoding="utf-8")
    return root


def test_a_picture_of_the_library_is_named_the_way_its_twin_is(tmp_path):
    """The documentation names a picture of the library by the subsystem of the library or bare
    (`Стд::Аккаунт.svg`, `Аккаунт.svg`); either way the reference follows the English twin."""
    platform_map.dataset.set_data_root(_picture_root(tmp_path, "data"))
    try:
        assert platform_map.resource_path_english("Команда.svg") == "Team.svg"
        assert platform_map.resource_path_english("Стд::Команда.svg") == "Std::Team.svg"
        assert platform_map.resource_path_english("Std::Письмо.svg") == "Std::Mail.svg"
        assert platform_map.resource_path_english("Стд::Team.svg") == "Std::Team.svg"
        # An English reference comes back as it is written.
        assert platform_map.resource_path_english("Std::Team.svg") == "Std::Team.svg"
        assert platform_map.resource_path_english("Team.svg") == "Team.svg"
    finally:
        platform_map.dataset.set_data_root(None)


def test_only_a_reference_the_library_holds_is_answered(tmp_path):
    """A path of the project whose last name is a picture of the library is not that picture:
    no answer by the name of the file alone."""
    platform_map.dataset.set_data_root(_picture_root(tmp_path, "data"))
    try:
        for reference in (
            "Иконки/Команда.svg",                  # a folder the library does not have
            "Сайт::Команда.svg",                   # another subsystem
            "Стд::Интерфейс::Команда.svg",         # a namespace below the library's
            "Icons/Стд/Ресурсы/Команда.svg",       # the place in the jar is no reference
            "Вложенная.svg",                       # a picture of a folder named without it
            "Команда.png", "Команда", "команда.svg", " Команда.svg", "Стд::", "",
        ):
            assert platform_map.resource_path_english(reference) is None, reference
    finally:
        platform_map.dataset.set_data_root(None)


def test_a_picture_in_a_folder_of_the_library_keeps_the_separators_as_written(tmp_path):
    platform_map.dataset.set_data_root(_picture_root(tmp_path, "data"))
    try:
        assert platform_map.resource_path_english("Папка/Вложенная.svg") == "Folder/Nested.svg"
        assert platform_map.resource_path_english("Папка\\Вложенная.svg") == "Folder\\Nested.svg"
        assert (platform_map.resource_path_english("Стд::Папка\\Вложенная.svg")
                == "Std::Folder\\Nested.svg")
    finally:
        platform_map.dataset.set_data_root(None)


def test_a_row_of_another_shape_is_not_read_as_a_picture(tmp_path):
    """A row that is not a picture below the folder of resources of a subsystem, in the same
    place on both sides, is skipped; the rest of the table still answers."""
    pictures = {
        "Icons/Стд/Ресурсы/Команда.svg": "Icons/Std/Resources/Team.svg",
        "Icons/Стд/Команда2.svg": "Icons/Std/Team2.svg",
        "Icons/Стд/Картинки/Команда3.svg": "Icons/Std/Pictures/Team3.svg",
        "Icons/Стд/Ресурсы/Команда4.svg": "Other/Std/Resources/Team4.svg",
        "Icons/Стд/Ресурсы/Команда5.svg": "Icons/Std/Resources/Sub/Team5.svg",
        "Icons/Стд/Ресурсы/Команда6.svg": 6,
    }
    platform_map.dataset.set_data_root(_picture_root(tmp_path, "data", pictures))
    try:
        assert platform_map.resource_path_english("Команда.svg") == "Team.svg"
        for number in range(2, 7):
            assert platform_map.resource_path_english(f"Команда{number}.svg") is None
    finally:
        platform_map.dataset.set_data_root(None)


def test_data_without_the_pictures_answers_nothing_and_is_read_afresh(tmp_path):
    with_table = _picture_root(tmp_path, "with")
    without = _picture_root(tmp_path, "without", None)
    empty = _picture_root(tmp_path, "empty", {})
    try:
        platform_map.dataset.set_data_root(with_table)
        assert platform_map.resource_path_english("Команда.svg") == "Team.svg"
        platform_map.dataset.set_data_root(without)
        assert platform_map.resource_path_english("Команда.svg") is None
        platform_map.dataset.set_data_root(empty)
        assert platform_map.resource_path_english("Стд::Команда.svg") is None
        platform_map.dataset.set_data_root(with_table)
        assert platform_map.resource_path_english("Стд::Команда.svg") == "Std::Team.svg"
    finally:
        platform_map.dataset.set_data_root(None)


def test_a_file_of_the_project_is_asked_before_the_library(tmp_path):
    """A BARE name the project keeps a file under is the project's: the reference is then to
    that file and the dictionary spells it. A name qualified by the library says outright
    which of the two is meant, and the file of the project does not take it away."""
    platform_map.dataset.set_data_root(_picture_root(tmp_path, "data"))
    try:
        own = Resolver(_dictionary(), resource_keys=frozenset({"Команда.svg"}))
        assert own.library_picture("Команда.svg") is None
        assert own.library_picture("Стд::Команда.svg") == "Std::Team.svg"
        assert own.library_picture("Письмо.svg") == "Mail.svg"
        assert Resolver(_dictionary()).library_picture("Команда.svg") == "Team.svg"
    finally:
        platform_map.dataset.set_data_root(None)


def test_an_entry_spelled_like_the_picture_is_an_echo_and_one_spelled_otherwise_is_not(tmp_path):
    platform_map.dataset.set_data_root(_picture_root(tmp_path, "data"))
    try:
        resolver = Resolver(_dictionary({"Команда": "Team", "Письмо": "Letter", "Стд": "Std"}))
        assert resolver.library_picture("Стд::Команда.svg") == "Std::Team.svg"
        assert resolver.library_picture("Письмо.svg") == "Mail.svg"
        assert resolver.echoes() == {"Команда": "Team", "Стд": "Std"}
    finally:
        platform_map.dataset.set_data_root(None)


def _yaml_value(text: str, resolver: Resolver, walk) -> tuple[str, FileReport]:
    root = yamlfile.yaml.compose(text)
    report = FileReport(path="Component.yaml")
    edits: list = []
    for _key, value in root.value:
        walk(value, resolver, report, edits)
    return apply_edits(text, edits), report


def test_a_yaml_value_naming_a_picture_of_the_library_takes_its_twin(tmp_path):
    platform_map.dataset.set_data_root(_picture_root(tmp_path, "data"))
    try:
        resolver = Resolver(_dictionary(), resource_keys=frozenset({"Своя.svg"}))
        text = ("Изображение: Команда.svg\n"
                "Картинка: Стд::Письмо.svg\n"
                "Значок: \"Команда.svg\"\n"
                "Своя: Своя.svg\n")
        for walk in (yamlfile._generic_scalar, yamlfile._identifier_value):
            out, report = _yaml_value(text, resolver, walk)
            assert out == ("Изображение: Team.svg\n"
                           "Картинка: Std::Mail.svg\n"
                           "Значок: \"Team.svg\"\n"
                           "Своя: Своя.svg\n"), walk
            # The file of the project waits for its entry; the pictures of the library are no gap.
            assert set(report.missing_tokens) == {"Своя"}
            assert report.resource_tokens == {"Своя"}
    finally:
        platform_map.dataset.set_data_root(None)


def test_a_yaml_value_read_with_data_that_has_no_pictures_is_read_as_before(tmp_path):
    platform_map.dataset.set_data_root(_picture_root(tmp_path, "data", None))
    try:
        out, report = _yaml_value("Изображение: Команда.svg\n", Resolver(_dictionary()),
                                  yamlfile._generic_scalar)
        assert out == "Изображение: Команда.svg\n"
        assert report.resource_tokens == {"Команда"}
    finally:
        platform_map.dataset.set_data_root(None)
