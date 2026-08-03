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


@pytest.fixture()
def project(tmp_path: Path) -> Path:
    sub = tmp_path / "Основное"
    sub.mkdir()
    (sub / "Товары.yaml").write_text(_CATALOG_YAML, encoding="utf-8")
    (sub / "Товары.xbsl").write_text(_CATALOG_XBSL, encoding="utf-8")
    (sub / "ВидТовара.yaml").write_text(_ENUM_YAML, encoding="utf-8")
    (sub / "ФормаТоваров.yaml").write_text(_FORM_YAML, encoding="utf-8")
    (sub / "Словарь.yaml").write_text(_DICTIONARY_YAML, encoding="utf-8")
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
