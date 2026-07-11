"""Индекс проекта (--index): схема полей, позиции, пустой проект, интеграция с CLI.

Зависит от данных Элемента: индексу нужны лексер (language.json) и семейства порождаемых
типов (stdlib.json object_members) – см. conftest, модуль пропускается без данных.
"""

import json
from pathlib import Path

import pytest

from xbsllint import __version__, cli
from xbsllint.indexer import build_index

# Fixture-проект: номера строк в проверках ниже – 1-based позиции в этих литералах.
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
    "                Имя: Наименование",             # 13 – глубже уровня ТЧ, не должно засчитаться
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
    "@Обработчик(\"Событие\")",                      # 14 – аннотация с аргументами
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


@pytest.fixture()
def project(tmp_path: Path) -> Path:
    sub = tmp_path / "Основное"
    sub.mkdir()
    (sub / "Товары.yaml").write_text(_CATALOG_YAML, encoding="utf-8")
    (sub / "Товары.xbsl").write_text(_CATALOG_XBSL, encoding="utf-8")
    (sub / "ВидТовара.yaml").write_text(_ENUM_YAML, encoding="utf-8")
    (sub / "ФормаТоваров.yaml").write_text(_FORM_YAML, encoding="utf-8")
    return tmp_path


def test_meta_and_schema(project):
    idx = build_index(project)

    assert set(idx) >= {"meta", "objects", "methods", "components"}
    assert idx["meta"]["root"] == project.resolve().as_posix()
    assert "\\" not in idx["meta"]["root"]
    assert idx["meta"]["version"] == __version__
    json.dumps(idx, ensure_ascii=False)  # сериализуется без потерь

    for obj in idx["objects"]:
        assert set(obj) >= {"name", "kind", "path", "line", "tabular", "local_types", "family"}
        assert "\\" not in obj["path"]  # пути – POSIX, относительные к meta.root
    for m in idx["methods"]:
        assert set(m) == {"module", "name", "path", "line", "annotations"}
    for c in idx["components"]:
        assert set(c) == {"form", "name", "type", "path", "line"}


def test_object_tabular_and_local_types(project):
    idx = build_index(project)
    obj = next(o for o in idx["objects"] if o["name"] == "Товары")

    assert obj["kind"] == "Справочник"
    assert obj["path"] == "Основное/Товары.yaml"
    assert obj["line"] == 3  # строка ключа Имя
    assert obj["tabular"] == [{"name": "Состав", "line": 10}]
    assert obj["local_types"] == [
        {"name": "Сводка", "path": "Основное/Товары.xbsl", "line": 4},
    ]
    # family – готовый список для автодополнения после точки: порождаемые типы + ТЧ + структуры
    for member in ("Ссылка", "Объект", "Состав", "Сводка"):
        assert member in obj["family"]
    assert "values" not in obj  # values – только у перечислений


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

    assert methods["Обработать"]["annotations"] == ["Обработчик"]  # аргументы отброшены
    assert methods["БезАннотаций"]["annotations"] == []


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


def test_empty_project(tmp_path):
    idx = build_index(tmp_path)

    assert idx["meta"]["root"] == tmp_path.resolve().as_posix()
    assert idx["objects"] == []
    assert idx["methods"] == []
    assert idx["components"] == []
    json.dumps(idx)


def test_cli_index_flag(project, capsys):
    code = cli.main(["--index", str(project)])

    payload = json.loads(capsys.readouterr().out)
    assert code == 0
    assert {o["name"] for o in payload["objects"]} == {"Товары", "ВидТовара", "ФормаТоваров"}


def test_cli_index_needs_single_path(project, capsys):
    code = cli.main(["--index", str(project), str(project)])

    assert code == 2
    assert "--index" in capsys.readouterr().err
