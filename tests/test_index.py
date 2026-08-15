"""The project index (--index): the field schema, positions, an empty project, CLI integration.

Depends on the Element data: the index needs the lexer (language.json) and the families of
derived types (stdlib.json object_members) - see conftest, the module is skipped without data.
"""

import json
from pathlib import Path

import pytest

from xbsl import __version__, cli
from xbsl.indexer import build_index

# The fixture project: line numbers in the checks below are 1-based positions in these literals.
_CATALOG_YAML = "\n".join([
    "ВидЭлемента: Справочник",                       # 1
    "Ид: 5d3f0a1b-2c4d-4e5f-8a9b-0c1d2e3f4a5b",      # 2
    "Имя: Товары",                                   # 3
    "Реквизиты:",                                    # 4
    "    -",                                         # 5
    "        Имя: Наименование",                     # 6
    "        Тип: Строка",                           # 7
    "ТабличныеЧасти:",                               # 8
    "    -",                                         # 9
    "        Имя: Состав",                           # 10
    "        Реквизиты:",                            # 11
    "            -",                                 # 12
    "                Имя: Наименование",             # 13 - deeper than the tabular section level, must not be counted
    "                Тип: Строка",                   # 14
    "",
])

_CATALOG_XBSL = "\n".join([
    "// Модуль товаров.",                            # 1
    "",                                              # 2
    "@НаСервере @НаКлиенте",                         # 3
    "структура Сводка",                              # 4
    "    пер Название: Строка",                      # 5
    ";",                                             # 6
    "",                                              # 7
    "@ВПроекте",                                     # 8
    "@НаСервере @ДоступноСКлиента",                  # 9
    "метод ДанныеСтраницы(Слаг: Строка): Сводка",    # 10
    "    возврат новый Сводка()",                    # 11
    ";",                                             # 12
    "",                                              # 13
    "@Обработчик(\"Событие\")",                      # 14 - an annotation with arguments
    "метод Обработать()",                            # 15
    ";",                                             # 16
    "",                                              # 17
    "метод БезАннотаций()",                          # 18
    ";",                                             # 19
    "",
])

_ENUM_YAML = "\n".join([
    "ВидЭлемента: Перечисление",                     # 1
    "Ид: 6e4a1b2c-3d5e-4f6a-9b0c-1d2e3f4a5b6c",      # 2
    "Имя: ВидТовара",                                # 3
    "Элементы:",                                     # 4
    "    -",                                         # 5
    "        Имя: Обычный",                          # 6
    "    -",                                         # 7
    "        Имя: Весовой",                          # 8
    "",
])

_FORM_YAML = "\n".join([
    "ВидЭлемента: КомпонентИнтерфейса",              # 1
    "Ид: 7f5b2c3d-4e6f-4a7b-8c9d-2e3f4a5b6c7d",      # 2
    "Имя: ФормаТоваров",                             # 3
    "Наследует:",                                    # 4
    "    Тип: ПроизвольныйКомпонент",                # 5
    "    Содержимое:",                               # 6
    "        Тип: Группа",                           # 7
    "        Имя: Корень",                           # 8
    "        Содержимое:",                           # 9
    "            -",                                 # 10
    "                Тип: СтандартнаяКарточка",      # 11
    "                Имя: КарточкаCTA",              # 12
    "",
])


_USAGE_XBSL = "\n".join([
    "метод Точка()",                              # 1
    "    ПодготовитьДанные()",                    # 2 - a bare call in its own module
    "    возврат Товары.ДанныеСтраницы(\"x\")",   # 3 - the root object + a call of a method of module Товары
    ";",                                          # 4
    "метод ПодготовитьДанные()",                  # 5 - a declaration, not a usage
    ";",                                          # 6
    "",
])

_USAGE_YAML = "\n".join([
    "ВидЭлемента: КомпонентИнтерфейса",           # 1
    "Ид: 8a6c3d4e-5f7a-4b8c-9d0e-3f4a5b6c7d8e",   # 2
    "Имя: Использование",                         # 3
    "Наследует:",                                 # 4
    "    Тип: ПроизвольныйКомпонент",             # 5
    "    Обработчик: ПодготовитьДанные",          # 6 - a reference to a method of the pair module
    "",
])


# A dictionary: its keys are the API - the platform compiles each one into a method.
_DICTIONARY_YAML = "\n".join([
    "ВидЭлемента: ЛокализованныеСтроки",              # 1
    "Ид: 7e1f0a1b-2c4d-4e5f-8a9b-0c1d2e3f4a5c",      # 2
    "Имя: Словарь",                                   # 3
    "Строки:",                                        # 4
    "    # подпись под кнопкой",                      # 5
    "    Отправить: \"Отправить\"",                   # 6
    "    Отмена: Отмена",                             # 7
    "Шаблоны:",                                       # 8
    "    Приветствие: \"Здравствуйте, $0!\"",         # 9
    "    Диапазон: \"с $1 по $0\"",                   # 10
    "",
])


# A type DESCRIBED IN METADATA: the members live in the Fields section, not in a module.
_STRUCTURE_YAML = "\n".join([
    "ВидЭлемента: ХранимаяСтруктура",                # 1
    "Ид: 9b7d4e5f-6a8b-4c9d-8e0f-4a5b6c7d8e9f",      # 2
    "Имя: ИтогОбработки",                            # 3
    "Поля:",                                         # 4
    "    -",                                         # 5
    "        Имя: Обработано",                       # 6
    "        Тип: Число",                            # 7
    "    -",                                         # 8
    "        Имя: Сообщение",                        # 9
    "        Тип: Строка",                           # 10
    "",
])

_STRUCTURE_XBSL = "\n".join([
    "метод Пусто(): Булево",                         # 1
    "    возврат Обработано == 0",                   # 2
    ";",                                             # 3
    "",
])

# A constants set: the constants are the members of the GENERATED types `<Name>.Record`
# and `<Name>.Data`, and `Get()` is the way the code reaches the record.
_CONSTANTS_YAML = "\n".join([
    "ВидЭлемента: НаборКонстант",                    # 1
    "Ид: 0c8e5f6a-7b9c-4d0e-9f1a-5b6c7d8e9f0a",      # 2
    "Имя: НастройкиПриложения",                      # 3
    "Константы:",                                    # 4
    "    -",                                         # 5
    "        Имя: АдресСервиса",                     # 6
    "        Тип: Строка",                           # 7
    "    -",                                         # 8
    "        Имя: ОтладкаВключена",                  # 9
    "        Тип: Булево",                           # 10
    "",
])

# The record module of the constants set: it extends the Record type of the set.
_CONSTANTS_RECORD_XBSL = "\n".join([
    "метод Настроен(): Булево",                      # 1
    "    возврат АдресСервиса != \"\"",              # 2
    ";",                                             # 3
    "",
])


@pytest.fixture()
def project(tmp_path: Path) -> Path:
    sub = tmp_path / "Основное"
    sub.mkdir()
    (sub / "Товары.yaml").write_text(_CATALOG_YAML, encoding="utf-8")
    (sub / "Товары.xbsl").write_text(_CATALOG_XBSL, encoding="utf-8")
    (sub / "ВидТовара.yaml").write_text(_ENUM_YAML, encoding="utf-8")
    (sub / "ФормаТоваров.yaml").write_text(_FORM_YAML, encoding="utf-8")
    (sub / "Словарь.yaml").write_text(_DICTIONARY_YAML, encoding="utf-8")
    (sub / "ИтогОбработки.yaml").write_text(_STRUCTURE_YAML, encoding="utf-8")
    (sub / "ИтогОбработки.xbsl").write_text(_STRUCTURE_XBSL, encoding="utf-8")
    (sub / "НастройкиПриложения.yaml").write_text(_CONSTANTS_YAML, encoding="utf-8")
    (sub / "НастройкиПриложения.Запись.xbsl").write_text(
        _CONSTANTS_RECORD_XBSL, encoding="utf-8",
    )
    return tmp_path


def test_meta_and_schema(project):
    idx = build_index(project)

    assert set(idx) >= {"meta", "objects", "methods", "components"}
    assert idx["meta"]["root"] == project.resolve().as_posix()
    assert "\\" not in idx["meta"]["root"]
    assert idx["meta"]["version"] == __version__
    json.dumps(idx, ensure_ascii=False)  # serializes losslessly

    for obj in idx["objects"]:
        assert set(obj) >= {"name", "kind", "path", "line", "tabular", "local_types", "family"}
        assert "\\" not in obj["path"]  # paths are POSIX, relative to meta.root
    for m in idx["methods"]:
        assert set(m) == {
            "module", "name", "path", "line", "annotations", "params", "returns", "doc",
        }
    for c in idx["components"]:
        assert set(c) == {"form", "name", "type", "path", "line"}


def test_object_tabular_and_local_types(project):
    idx = build_index(project)
    obj = next(o for o in idx["objects"] if o["name"] == "Товары")

    assert obj["kind"] == "Справочник"
    assert obj["path"] == "Основное/Товары.yaml"
    assert obj["line"] == 3  # the line of the Имя key
    assert obj["tabular"] == [{"name": "Состав", "line": 10}]
    assert obj["local_types"] == [
        {"name": "Сводка", "path": "Основное/Товары.xbsl", "line": 4},
    ]
    # family - a ready-made after-dot completion list: derived types + tabular sections + structures
    for member in ("Ссылка", "Объект", "Состав", "Сводка"):
        assert member in obj["family"]
    assert "values" not in obj  # values - enumerations only


def test_enum_values(project):
    idx = build_index(project)
    enum = next(o for o in idx["objects"] if o["name"] == "ВидТовара")

    assert enum["kind"] == "Перечисление"
    assert enum["line"] == 3
    assert enum["values"] == [
        {"name": "Обычный", "line": 6},
        {"name": "Весовой", "line": 8},
    ]


def test_methods_with_annotations(project):
    idx = build_index(project)
    methods = {m["name"]: m for m in idx["methods"]}

    m = methods["ДанныеСтраницы"]
    assert m["module"] == "Товары"
    assert m["path"] == "Основное/Товары.xbsl"
    assert m["line"] == 10
    assert m["annotations"] == ["ВПроекте", "НаСервере", "ДоступноСКлиента"]

    assert methods["Обработать"]["annotations"] == ["Обработчик"]  # the arguments are dropped
    assert methods["БезАннотаций"]["annotations"] == []


_DOC_XBSL = "\n".join([
    "// --- Раздел ---",                             # 1 - a section banner, not a description
    "",                                              # 2
    "// Логин пользователя для журнала.",            # 3
    "// Пусто на служебном сеансе.",                 # 4
    "@НаСервере @ВПроекте",                          # 5
    "метод Логин(Ид: Строка = \"\"): Массив<Строка>",  # 6
    "    возврат []",                                # 7
    ";",                                             # 8
    "",                                              # 9
    "// --- Служебное ---",                          # 10
    "метод Служебный()",                             # 11
    ";",                                             # 12
    "",
])


def test_method_signature_and_description(tmp_path):
    # The hover reads three things off a method declaration: the call as written, the return
    # type head (that is how `val X = Module.Method()` gets a type) and the comment above it.
    (tmp_path / "Журнал.xbsl").write_text(_DOC_XBSL, encoding="utf-8")
    methods = {m["name"]: m for m in build_index(tmp_path)["methods"]}

    login = methods["Логин"]
    assert login["params"] == '(Ид: Строка = "")'
    assert login["returns"] == "Массив"  # nominal head, generic arguments dropped
    assert login["doc"] == "Логин пользователя для журнала.\nПусто на служебном сеансе."

    # a banner describes the section, not the method that happens to follow it
    plain = methods["Служебный"]
    assert (plain["doc"], plain["returns"], plain["params"]) == ("", "", "()")


def test_components(project):
    idx = build_index(project)
    comps = {c["name"]: c for c in idx["components"]}

    root = comps["Корень"]
    assert root["form"] == "ФормаТоваров"
    assert root["type"] == "Группа"
    assert root["path"] == "Основное/ФормаТоваров.yaml"
    assert root["line"] == 8

    card = comps["КарточкаCTA"]
    assert card["type"] == "СтандартнаяКарточка"
    assert card["line"] == 12


def test_references(project):
    sub = project / "Основное"
    (sub / "Использование.xbsl").write_text(_USAGE_XBSL, encoding="utf-8")
    (sub / "Использование.yaml").write_text(_USAGE_YAML, encoding="utf-8")
    refs = build_index(project)["references"]

    for ref in refs:
        assert set(ref) == {"name", "qualifier", "module", "path", "line", "col"}
        assert "\\" not in ref["path"]

    def has(name, qualifier, module):
        return any(r["name"] == name and r["qualifier"] == qualifier and r["module"] == module for r in refs)

    assert has("ПодготовитьДанные", "", "Использование")  # a bare call and/or the yaml handler
    assert has("ДанныеСтраницы", "Товары", "Использование")  # Товары.ДанныеСтраницы(...)
    assert has("Товары", "", "Использование")  # the object as a chain root
    # a handler in yaml is a method usage too
    assert any(r["name"] == "ПодготовитьДанные" and r["path"].endswith("Использование.yaml") for r in refs)
    # a method declaration does not count as a usage (no record for line 5 in the .xbsl)
    assert not any(
        r["name"] == "ПодготовитьДанные" and r["path"].endswith("Использование.xbsl") and r["line"] == 5 for r in refs
    )
    # the call site of ДанныеСтраницы: line 3, col 0-based
    site = next(r for r in refs if r["name"] == "ДанныеСтраницы")
    assert site["line"] == 3 and site["path"] == "Основное/Использование.xbsl"
    assert isinstance(site["col"], int) and site["col"] >= 0
    json.dumps(refs, ensure_ascii=False)


def test_trailing_comments_in_yaml(tmp_path):
    # Per YAML, a comment after a value or a section key is not a part of them:
    # the object name and the tabular section lines are found as usual.
    (tmp_path / "Товары.yaml").write_text("\n".join([
        "ВидЭлемента: Справочник",                    # 1
        "Ид: 5d3f0a1b-2c4d-4e5f-8a9b-0c1d2e3f4a5b",   # 2
        "Имя: Товары # каталог",                      # 3
        "ТабличныеЧасти: # секция с комментарием",    # 4
        "    -",                                      # 5
        "        Имя: Состав # строки",               # 6
        "",
    ]), encoding="utf-8")
    idx = build_index(tmp_path)

    obj = next(o for o in idx["objects"] if o["name"] == "Товары")
    assert obj["line"] == 3
    assert obj["tabular"] == [{"name": "Состав", "line": 6}]


def test_empty_project(tmp_path):
    idx = build_index(tmp_path)

    assert idx["meta"]["root"] == tmp_path.resolve().as_posix()
    assert idx["objects"] == []
    assert idx["methods"] == []
    assert idx["components"] == []
    assert idx["references"] == []
    json.dumps(idx)


def test_cli_index_flag(project, capsys):
    code = cli.main(["--index", str(project)])

    payload = json.loads(capsys.readouterr().out)
    assert code == 0
    assert {o["name"] for o in payload["objects"]} == {
        "Товары", "ВидТовара", "ФормаТоваров", "Словарь",
        "ИтогОбработки", "НастройкиПриложения",
    }


def test_cli_index_needs_single_path(project, capsys):
    code = cli.main(["--index", str(project), str(project)])

    assert code == 2
    assert "--index" in capsys.readouterr().err


# --- a dictionary: keys as members --------------------------------------------------------


def test_dictionary_keys_are_indexed_as_methods(project):
    """Without this the editor knows no members of a dictionary at all: F12 on Dictionary.Send
    answers "not found" and the dot offers nothing, while the code calls exactly that."""
    idx = build_index(project)
    keys = {m["name"]: m for m in idx["methods"] if m["module"] == "Словарь"}

    assert set(keys) == {"Отправить", "Отмена", "Приветствие", "Диапазон"}
    assert keys["Отправить"]["path"] == "Основное/Словарь.yaml"
    assert keys["Отправить"]["line"] == 6
    assert keys["Приветствие"]["line"] == 9
    # The value is the description: hovering a key shows the string it stands for, and the
    # quotes of the yaml scalar are its form, not its text.
    assert keys["Отправить"]["doc"] == "Отправить"
    assert keys["Приветствие"]["doc"] == "Здравствуйте, $0!"


def test_dictionary_arity_follows_the_placeholders(project):
    """The Strings section compiles parameterless methods (that is the whole point of the
    placeholder rule), a
    template takes the substitutions its text names - numbered, so the HIGHEST one decides."""
    idx = build_index(project)
    keys = {m["name"]: m for m in idx["methods"] if m["module"] == "Словарь"}

    assert keys["Отправить"]["params"] == ""
    assert keys["Приветствие"]["params"] == "Строка"
    assert keys["Диапазон"]["params"] == "Строка, Строка"  # $1 with $0 - two, not one
    assert all(k["returns"] == "Строка" for k in keys.values())


def test_dictionary_keys_are_referable(project):
    """They join the ordinary methods, so "find usages" and the reference index see them."""
    idx = build_index(project)
    assert {m["name"] for m in idx["methods"]} >= {"Отправить", "Приветствие"}


# --- types described in metadata ----------------------------------------------------------


def test_structure_fields_are_indexed_as_members(project):
    """Without this the editor knows no members of a yaml structure at all: the dot after
    `новый ИтогОбработки()` offers nothing, while the type has fields and a module."""
    idx = build_index(project)
    record = idx["struct_members"]["ИтогОбработки"]

    assert record["properties"] == ["Обработано", "Сообщение"]
    assert record["kind"] == "ХранимаяСтруктура"
    # the module extending the type contributes its methods
    assert record["methods"] == ["Пусто"]


def test_constants_are_indexed_under_the_generated_type_names(project):
    """The constants belong to the types the platform generates from the set (docs
    topics/constants-set-types), not to the set's own name - the singleton type has methods."""
    idx = build_index(project)
    members = idx["struct_members"]

    assert members["НастройкиПриложения.Запись"]["properties"] == [
        "АдресСервиса", "ОтладкаВключена",
    ]
    assert members["НастройкиПриложения.Данные"]["properties"] == [
        "АдресСервиса", "ОтладкаВключена",
    ]
    assert members["НастройкиПриложения.Запись"]["kind"] == "НаборКонстант"
    # the record module (`<Name>.Record.xbsl`) extends exactly that type
    assert members["НастройкиПриложения.Запись"]["methods"] == ["Настроен"]
    assert "methods" not in members["НастройкиПриложения.Данные"]
    assert "НастройкиПриложения" not in members


def test_generated_returns_type_the_constants_set_call(project):
    """A variable initialized by a `Get()` of a constants set has to be typed for the dot
    after it to offer anything: the stdlib catalogue knows no project object."""
    idx = build_index(project)

    # The result types come from the data (the manager pages of every kind carry them);
    # the built-in row answers only for data generated before that section existed.
    assert idx["generated_returns"]["НастройкиПриложения"]["Получить"] == (
        "НастройкиПриложения.Запись"
    )
    assert idx["generated_returns"]["Товары"]["НайтиПоКоду"] == "Товары.Ссылка?"


def test_manager_members_of_the_kind_are_indexed(project):
    """A `Get()` of a constants set is written on the object NAME: without the members of
    the kind's singleton type the dot after it offered types only, never the method."""
    idx = build_index(project)
    constants = next(o for o in idx["objects"] if o["name"] == "НастройкиПриложения")
    catalog = next(o for o in idx["objects"] if o["name"] == "Товары")

    # properties and methods apart, so a completion list knows which takes parentheses
    assert "Получить" in constants["manager"]["methods"]
    assert "НайтиПоКоду" in catalog["manager"]["methods"]
    assert "members" not in constants["manager"]


def test_family_offers_the_catalogue_not_the_safety_net(project):
    """What is OFFERED is the catalogue alone. The safety net the member rules judge by is a
    union across all kinds - offered, it names types the kind does not generate."""
    idx = build_index(project)
    catalog = next(o for o in idx["objects"] if o["name"] == "Товары")
    dictionary = next(o for o in idx["objects"] if o["name"] == "Словарь")

    assert "Ссылка" in catalog["family"]           # the catalogue knows the kind
    assert "ПараметрыЗаполнения" not in catalog["family"]  # net only, no page names it
    # A kind that generates no types at all: an empty list, not somebody else's names.
    assert dictionary["family"] == []
    assert dictionary["manager"] == {}


def test_metadata_sections_are_read_in_both_spellings(tmp_path):
    """The sources are bilingual: a structure whose section is written `Fields` describes the
    same type as one written in Russian, and a field may name itself `Name`.
    """
    (tmp_path / "Данные.yaml").write_text("\n".join([
        "ElementKind: StorableStructure",
        "Id: 1d9f6a7b-8c0d-4e1f-a02b-6c7d8e9f0a1b",
        "Имя: Данные",
        "Fields:",
        "    -",
        "        Name: Идентификатор",
        "        Type: Строка",
        "",
    ]), encoding="utf-8")

    idx = build_index(tmp_path)

    assert idx["struct_members"]["Данные"]["properties"] == ["Идентификатор"]


def test_an_english_project_is_indexed_like_a_russian_one(tmp_path):
    """A project written entirely in English yields an index, not an empty one.

    Only the Russian keys were read before, so such a project indexed to nothing at all: no
    objects, no types, and the editor had neither a tree nor a dot completion to show.
    """
    (tmp_path / "ClientParameters.yaml").write_text("\n".join([
        "ElementKind: ClientWorkParameters",
        "Id: 57b9e1c6-46dc-491b-b4e8-3d8f5ceb92d6",
        "Name: ClientParameters",
        "Parameters:",
        "    -",
        "        Name: ServiceAddress",
        "        Type: String",
        "",
    ]), encoding="utf-8")

    idx = build_index(tmp_path)

    assert [o["name"] for o in idx["objects"]] == ["ClientParameters"]
    assert idx["struct_members"]["ClientParameters"]["properties"] == ["ServiceAddress"]


def test_an_english_object_lists_its_sections(tmp_path):
    """The named sections of an object are read in either spelling too - a catalog written in
    English carries its attributes and tabular sections into the index like a Russian one."""
    (tmp_path / "Products.yaml").write_text("\n".join([
        "ElementKind: Catalog",
        "Id: 4b2d6f8a-1c3e-4d5f-9a0b-2c4e6f8a0b1d",
        "Name: Products",
        "Attributes:",
        "    -",
        "        Name: Title",
        "        Type: String",
        "TabularParts:",
        "    -",
        "        Name: Lines",
        "",
    ]), encoding="utf-8")

    catalog = build_index(tmp_path)["objects"][0]

    assert [a["name"] for a in catalog["attributes"]] == ["Title"]
    assert [t["name"] for t in catalog["tabular"]] == ["Lines"]


def test_a_generated_type_answers_to_either_spelling(tmp_path):
    """The type the platform generates for an element is known by both of its names.

    The name is looked up as the code writes it, and which spelling that is depends on the
    language of the project - so both are registered, whichever language the element uses.
    """
    (tmp_path / "Параметры.yaml").write_text("\n".join([
        "ВидЭлемента: ПараметрыРаботыКлиента",
        "Ид: 3a1c5e7f-9b0d-4a2c-8e6f-1b3d5f7a9c0e",
        "Имя: Параметры",
        "Параметры:",
        "    -",
        "        Имя: АдресСервиса",
        "        Тип: Строка",
        "",
    ]), encoding="utf-8")

    members = build_index(tmp_path)["struct_members"]

    assert members["Параметры.Параметры"]["properties"] == ["АдресСервиса"]
    assert members["Параметры.Parameters"] == members["Параметры.Параметры"]


def test_an_interface_component_describes_the_type_of_its_value(tmp_path):
    """A component names its own data in Properties, and a value of that type carries them.

    A variable holding a form used to offer nothing after the dot - neither its own properties
    nor the platform type it extends, which is where `OpenInModalWindow` lives.
    """
    (tmp_path / "ФормаЗаявки.yaml").write_text("\n".join([
        "ВидЭлемента: КомпонентИнтерфейса",
        "Ид: 8c2e4a6b-0d1f-4a3c-9e5b-7d8f0a1c2e3b",
        "Имя: ФормаЗаявки",
        "Наследует:",
        "    Тип: Форма",
        "Свойства:",
        "    -",
        "        Имя: Комментарий",
        "        Тип: Строка",
        "",
    ]), encoding="utf-8")
    (tmp_path / "ФормаЗаявки.xbsl").write_text("метод Проверить(): Булево\n    возврат Истина\n;\n",
                                               encoding="utf-8")

    record = build_index(tmp_path)["struct_members"]["ФормаЗаявки"]

    assert record["properties"] == ["Комментарий"]
    assert record["methods"] == ["Проверить"]
    # The platform type it extends - the completion adds its members to the component's own.
    assert record["base"] == "Форма"
