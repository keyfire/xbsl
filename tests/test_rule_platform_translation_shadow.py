"""A project declaration only warns when it blocks an otherwise available translation."""

from pathlib import Path

import pytest

from xbsl import engine
from xbsl.rules.platform_translation_shadow import RULE_ID
from xbsl.rules.yaml_schema import _parsed
from xbsl.translation import names
from xbsl.translation.code import Resolver, translate_code
from xbsl.translation.dictionary import Dictionary
from xbsl.translation.reporting import FileReport
from xbsl.translation.yamlfile import translate_yaml


pytestmark = pytest.mark.needs_data


def _write(path: Path, content: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


def _lint(paths: list[Path]):
    return engine.run_sources([engine.load(path) for path in paths], select={RULE_ID})


def _dictionary(root: Path, pairs: str = "") -> Path:
    return _write(
        root / "xbsl-translation" / "tokens.yaml",
        "version: 1\nlanguage: en\ntokens:\n" + (pairs or "  {}\n"),
    )


def test_reports_missing_pairs_on_durable_declarations(tmp_path):
    project = tmp_path / "project"
    _dictionary(tmp_path)
    enum = _write(
        project / "sample.yaml",
        "ВидЭлемента: Перечисление\n"
        "Имя: ПробнаяКатегорияКедр\n"
        "Элементы:\n"
        "  - Имя: Таблица\n",
    )
    module = _write(
        project / "sample.xbsl",
        "метод Подменю()\n;\n"
        "структура ПробнаяСтруктураКедр\n"
        "    пер Группы: Массив<Строка>\n;\n",
    )
    found = _lint([enum, module])
    assert {(Path(d.path).name, d.line, d.col) for d in found} == {
        ("sample.yaml", 4, 10),
        ("sample.xbsl", 1, 7),
        ("sample.xbsl", 4, 9),
    }
    assert all(d.severity.value == "warning" for d in found)
    assert all(d.rule_id == RULE_ID and d.fix is None for d in found)


def test_explicit_pair_is_clean_and_removing_it_is_a_negative_control(tmp_path):
    project = tmp_path / "project"
    dictionary_file = _dictionary(tmp_path, "  Таблица: Table\n")
    source = _write(
        project / "sample.yaml",
        "ВидЭлемента: Перечисление\n"
        "Имя: ПробнаяКатегорияКедр\n"
        "Элементы:\n"
        "  - Имя: Таблица\n",
    )
    assert _parsed(engine.load(source))[1] is None
    assert _lint([source]) == []
    dictionary_file.write_text("version: 1\nlanguage: en\ntokens: {}\n", encoding="utf-8")
    assert _parsed(engine.load(source))[1] is None
    assert [d.line for d in _lint([source])] == [4]


def test_scoped_pair_covers_its_owner(tmp_path):
    project = tmp_path / "project"
    _dictionary(tmp_path, "  ПробнаяКатегорияКедр.Таблица: Table\n")
    source = _write(
        project / "sample.yaml",
        "ВидЭлемента: Перечисление\n"
        "Имя: ПробнаяКатегорияКедр\n"
        "Элементы:\n"
        "  - Имя: Таблица\n",
    )
    assert _lint([source]) == []


def test_explicit_project_spelling_is_not_a_missing_pair(tmp_path):
    _dictionary(tmp_path, "  Таблица: GridView\n")
    source = _write(
        tmp_path / "project" / "sample.yaml",
        "ВидЭлемента: Перечисление\n"
        "Имя: ПробнаяКатегорияКедр\n"
        "Элементы:\n"
        "  - Имя: Таблица\n",
    )
    assert _lint([source]) == []


def test_stacked_field_modifiers_report_once(tmp_path):
    _dictionary(tmp_path)
    source = _write(
        tmp_path / "project" / "sample.xbsl",
        "структура ПробнаяСтруктураКедр\n"
        "    req var Группы: Массив<Строка>\n;\n",
    )
    found = _lint([source])
    assert [(d.line, d.col) for d in found] == [(2, 13)]


def test_locals_parameters_and_english_names_do_not_enter_collector(tmp_path):
    project = tmp_path / "project"
    _dictionary(tmp_path)
    source = _write(
        project / "sample.xbsl",
        "метод ПробныйМетодКедр(Таблица: Строка)\n"
        "    пер Группы = Таблица\n"
        "    для Подменю из Список\n"
        "        Группы = Подменю\n"
        "    ;\n"
        "    Сообщить(\"Подменю\")\n"
        ";\n"
        "// Таблица\n",
    )
    translated = _write(
        project / "english.yaml",
        "ElementKind: Enumeration\nName: SampleCategory\nItems:\n  - Name: Table\n",
    )
    assert _lint([source, translated]) == []


def test_without_translation_dictionary_is_clean(tmp_path):
    source = _write(
        tmp_path / "project" / "sample.yaml",
        "ВидЭлемента: Перечисление\nИмя: ПробнаяКатегорияКедр\n"
        "Элементы:\n  - Имя: Таблица\n",
    )
    assert _lint([source]) == []


def test_two_projects_use_their_own_dictionaries(tmp_path):
    first = tmp_path / "first"
    second = tmp_path / "second"
    _dictionary(first, "  Таблица: Table\n")
    _dictionary(second)
    content = (
        "ВидЭлемента: Перечисление\nИмя: ПробнаяКатегорияКедр\n"
        "Элементы:\n  - Имя: Таблица\n"
    )
    source_with_pair = _write(first / "project" / "sample.yaml", content)
    source_without_pair = _write(second / "project" / "sample.yaml", content)
    found = _lint([source_with_pair, source_without_pair])
    assert [(d.path, d.line) for d in found] == [(str(source_without_pair), 4)]


def test_name_line_inside_block_scalar_is_not_a_declaration(tmp_path):
    _dictionary(tmp_path)
    source = _write(
        tmp_path / "project" / "sample.yaml",
        "Описание: |\n"
        "  Имя: Таблица\n"
        "ВидЭлемента: Перечисление\n"
        "Имя: ПробнаяКатегорияКедр\n"
        "Элементы:\n"
        "  - Имя: Таблица\n",
    )
    assert _parsed(engine.load(source))[1] is None
    assert [d.line for d in _lint([source])] == [6]


def test_xbsl_enum_scoped_pair_does_not_translate_the_declaration(tmp_path):
    _dictionary(tmp_path, "  ПробнаяКатегорияКедр.Таблица: Table\n")
    source = _write(
        tmp_path / "project" / "sample.xbsl",
        "перечисление ПробнаяКатегорияКедр\n"
        "    Таблица\n;\n",
    )
    assert [d.line for d in _lint([source])] == [2]
    loaded = engine.load(source)
    declared = frozenset(names.declared_in_module(loaded))
    qualified = Dictionary(tokens={"ПробнаяКатегорияКедр.Таблица": "Table"})
    bare = Dictionary(tokens={"Таблица": "Table"})
    assert "    Таблица\n" in translate_code(
        loaded, Resolver(qualified, declared), FileReport(str(source)),
    ).replace("\r\n", "\n")
    assert "    Table\n" in translate_code(
        loaded, Resolver(bare, declared), FileReport(str(source)),
    ).replace("\r\n", "\n")


def test_nested_component_name_uses_root_owner_scope(tmp_path):
    root_name = "ПробноеОкноКедр"
    _dictionary(tmp_path, f"  {root_name}.Таблица: Table\n")
    source = _write(
        tmp_path / "project" / "sample.yaml",
        "ВидЭлемента: КомпонентИнтерфейса\n"
        f"Имя: {root_name}\n"
        "Наследует:\n"
        "  Тип: ВсплывающийКомпонент\n"
        "  Содержимое:\n"
        "    Тип: Группа\n"
        "    Имя: ПромежуточныйУзелКедр\n"
        "    Содержимое:\n"
        "      - Тип: Группа\n"
        "        Имя: Таблица\n",
    )
    assert _parsed(engine.load(source))[1] is None
    assert _lint([source]) == []
    loaded = engine.load(source)
    declared = frozenset(names.declared_in_yaml(loaded))
    scoped = Dictionary(tokens={f"{root_name}.Таблица": "Table"})
    translated = translate_yaml(loaded, Resolver(scoped, declared), FileReport(str(source)))
    assert "Name: Table" in translated


def test_plain_yaml_descriptor_has_no_owner_scope(tmp_path):
    _dictionary(tmp_path, "  Таблица.Таблица: Table\n")
    source = _write(tmp_path / "project" / "sample.yaml", "Имя: Таблица\n")
    assert [d.line for d in _lint([source])] == [1]
