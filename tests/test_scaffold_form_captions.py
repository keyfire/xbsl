"""Captions of a generated form go through the project's dictionary.

The generators write one visible property - `Title` - and it used to be a literal: on a
live bilingual project one object produced eight findings of
conventions/untranslated-visible-literal (the form's own caption plus every table column), and
rewriting them by hand was the first thing done after generating.

The shape written instead is the project's own: of 303 table columns of that project 300 carry
a caption and every one of them is a `$Dictionary.Key` reference whose key is the field's name.
So the reference goes in together with the dictionary entries it needs - a reference to a key
that does not exist is worse than a literal, the apply fails and the stand rolls back.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml as pyyaml

import xbsl.engine  # noqa: F401 - breaks the scaffold <-> rules import cycle
from xbsl import dataset, engine, scaffold
from xbsl.cli import discover
from xbsl.scaffold import apply_result

_RULE = "conventions/untranslated-visible-literal"

_PROJECT = (
    "Ид: 6f0b6a44-0000-4000-8000-0000000000f0\n"
    "Поставщик: vendor\nИмя: Проба\nВерсия: 1.0.0\n"
    "ЯзыкиЛокализации: [Русский, Английский]\nЯзыкПоУмолчанию: Русский\n"
)

_DICTIONARY = (
    "ВидЭлемента: ЛокализованныеСтроки\n"
    "Ид: 6f0b6a44-0000-4000-8000-0000000000f1\n"
    "Имя: ОсновноеЛокализация\nОбластьВидимости: ВПроекте\n"
    "Строки:\n    Наименование: Наименование\n    Товары: Товары\n"
)

#: An existing form stating the project's intent: a caption goes through the dictionary. The
#: rule judges only the properties the project itself references somewhere.
_EXISTING_FORM = (
    "ВидЭлемента: КомпонентИнтерфейса\n"
    "Ид: 6f0b6a44-0000-4000-8000-0000000000f2\n"
    "Имя: Витрина\nОбластьВидимости: ВПодсистеме\n"
    "Наследует:\n    Тип: Группа\n    Заголовок: $ОсновноеЛокализация.Товары\n"
)


def _project(tmp_path: Path, languages: str = "[Русский, Английский]",
             dictionary: bool = True) -> Path:
    """A mini project with a subsystem; returns the subsystem folder."""
    subsystem = tmp_path / "vendor" / "Проба" / "Основное"
    subsystem.mkdir(parents=True)
    (subsystem.parent / "Проект.yaml").write_text(
        _PROJECT.replace("[Русский, Английский]", languages), encoding="utf-8")
    (subsystem / "Подсистема.yaml").write_text(
        "Интерфейс:\n    ВключатьВАвтоИнтерфейс: Ложь\n", encoding="utf-8")
    (subsystem / "Витрина.yaml").write_text(_EXISTING_FORM, encoding="utf-8")
    if dictionary:
        (subsystem / "ОсновноеЛокализация.yaml").write_text(_DICTIONARY, encoding="utf-8")
    return subsystem


def _catalog(subsystem: Path, name: str = "Товары") -> Path:
    apply_result(scaffold.op_new_object(subsystem, "Справочник", name,
                                        presentation="Наименование"))
    yaml_path = subsystem / f"{name}.yaml"
    apply_result(scaffold.op_add_field(yaml_path, "реквизит", "Цвет"))
    apply_result(scaffold.op_add_field(yaml_path, "реквизит", "Вес", type_="Число"))
    return yaml_path


def _captions(path: Path) -> list[str]:
    """Every Заголовок / Title value of a yaml file, in document order."""
    found: list[str] = []

    def walk(node):
        if isinstance(node, dict):
            for key, value in node.items():
                if key in ("Заголовок", "Title") and isinstance(value, str):
                    found.append(value)
                walk(value)
        elif isinstance(node, list):
            for item in node:
                walk(item)

    walk(pyyaml.safe_load(path.read_text(encoding="utf-8")))
    return found


def test_generated_captions_point_at_the_dictionary(tmp_path):
    subsystem = _project(tmp_path)
    _catalog(subsystem)
    result = scaffold.op_add_form(tmp_path, name="Товары")
    apply_result(result)

    assert _captions(subsystem / "ТоварыФормаОбъекта.yaml") == ["$ОсновноеЛокализация.Товары"]
    assert _captions(subsystem / "ТоварыФормаСписка.yaml") == [
        "$ОсновноеЛокализация.Товары",
        "$ОсновноеЛокализация.Наименование",
        "$ОсновноеЛокализация.Цвет",
        "$ОсновноеЛокализация.Вес",
    ]


def test_the_dictionary_gains_the_missing_keys_and_reuses_the_rest(tmp_path):
    """Both sections share one namespace - a repeated key is refused by the apply."""
    subsystem = _project(tmp_path)
    _catalog(subsystem)
    result = scaffold.op_add_form(tmp_path, name="Товары")
    apply_result(result)

    strings = pyyaml.safe_load(
        (subsystem / "ОсновноеЛокализация.yaml").read_text(encoding="utf-8"))["Строки"]
    assert strings == {
        "Наименование": "Наименование", "Товары": "Товары",
        "Цвет": "Цвет", "Вес": "Вес",
    }
    assert any("Цвет" in note and "Вес" in note for note in result.notes)


def test_the_new_keys_reach_the_translation(tmp_path):
    """A key present in the element and missing from a translation is a gap for later."""
    subsystem = _project(tmp_path)
    translation = subsystem / "Локализация" / "En"
    translation.mkdir(parents=True)
    (translation / "ОсновноеЛокализация.yaml").write_text(
        "Строки:\n    Наименование: Name\n    Товары: Goods\n", encoding="utf-8")
    _catalog(subsystem)
    result = scaffold.op_add_form(tmp_path, name="Товары")
    apply_result(result)

    echoed = pyyaml.safe_load(
        (translation / "ОсновноеЛокализация.yaml").read_text(encoding="utf-8"))["Строки"]
    # The default-language value goes in, exactly what op_add_localization copies.
    assert echoed == {"Наименование": "Name", "Товары": "Goods", "Цвет": "Цвет", "Вес": "Вес"}
    assert any("перевод" in note for note in result.notes)


def test_without_a_dictionary_the_caption_stays_a_literal(tmp_path):
    """Nothing to reference - and a reference to a key that does not exist fails the apply."""
    subsystem = _project(tmp_path, dictionary=False)
    _catalog(subsystem)
    apply_result(scaffold.op_add_form(tmp_path, name="Товары"))
    assert _captions(subsystem / "ТоварыФормаОбъекта.yaml") == ["Товары"]


def test_a_single_language_project_keeps_literals(tmp_path):
    """One language localizes nothing; a reference would be indirection nobody asked for."""
    subsystem = _project(tmp_path, languages="[Русский]")
    _catalog(subsystem)
    apply_result(scaffold.op_add_form(tmp_path, name="Товары"))
    assert _captions(subsystem / "ТоварыФормаОбъекта.yaml") == ["Товары"]
    assert "Цвет: Цвет" not in (subsystem / "ОсновноеЛокализация.yaml").read_text(
        encoding="utf-8")


def test_two_dictionaries_in_one_folder_are_no_answer(tmp_path):
    """Which of them a caption belongs to is the author's decision, not a guess."""
    subsystem = _project(tmp_path)
    (subsystem / "ВторойСловарь.yaml").write_text(
        _DICTIONARY.replace("ОсновноеЛокализация", "ВторойСловарь")
        .replace("0000000000f1", "0000000000f3"), encoding="utf-8")
    _catalog(subsystem)
    apply_result(scaffold.op_add_form(tmp_path, name="Товары"))
    assert _captions(subsystem / "ТоварыФормаОбъекта.yaml") == ["Товары"]


def test_a_name_the_templates_section_holds_stays_a_literal(tmp_path):
    """A reference resolves against the strings alone, and the two sections share a namespace.

    Pointing a caption at a template key fails the apply (yaml/localization-ref-to-template),
    and a string of the same name cannot be added beside it either.
    """
    subsystem = _project(tmp_path)
    (subsystem / "ОсновноеЛокализация.yaml").write_text(
        _DICTIONARY + 'Шаблоны:\n    Цвет: "Цвет $0"\n', encoding="utf-8")
    _catalog(subsystem)
    result = scaffold.op_add_form(tmp_path, name="Товары")
    apply_result(result)
    assert _captions(subsystem / "ТоварыФормаСписка.yaml") == [
        "$ОсновноеЛокализация.Товары",
        "$ОсновноеЛокализация.Наименование",
        "Цвет",
        "$ОсновноеЛокализация.Вес",
    ]
    strings = pyyaml.safe_load(
        (subsystem / "ОсновноеЛокализация.yaml").read_text(encoding="utf-8"))["Строки"]
    assert "Цвет" not in strings
    assert any("шаблонами" in note and "Цвет" in note for note in result.notes)


def test_a_repeated_generation_adds_no_second_key(tmp_path):
    """overwrite=True regenerates the forms; the dictionary must not grow a duplicate."""
    subsystem = _project(tmp_path)
    _catalog(subsystem)
    apply_result(scaffold.op_add_form(tmp_path, name="Товары"))
    again = scaffold.op_add_form(tmp_path, name="Товары", overwrite=True)
    apply_result(again)
    text = (subsystem / "ОсновноеЛокализация.yaml").read_text(encoding="utf-8")
    assert text.count("Цвет: Цвет") == 1
    assert not any("добавлены ключи" in note for note in again.notes)


@pytest.mark.skipif(not dataset.available_versions(), reason="нет данных Элемента")
def test_the_english_project_gets_the_english_caption_key(tmp_path):
    """The reference is written after the language pass - it is not a platform name.

    The built-in attribute of an English catalog still arrives under its Russian name
    (object_info completes the standard fields in Russian and localize_form_text protects
    them as author names) - a defect of its own, and the key follows the field name whatever
    that name is, so it is not asserted here.
    """
    subsystem = tmp_path / "Acme" / "TasksEn" / "Main"
    subsystem.mkdir(parents=True)
    (subsystem.parent / "Проект.yaml").write_text(
        "Id: 6f0b6a44-0000-4000-8000-0000000000e0\nVendor: Acme\nName: TasksEn\n"
        "Version: 1.0.0\nLocalizationLanguages: [Русский, Английский]\n"
        "DefaultLanguage: Английский\n", encoding="utf-8")
    (subsystem / "Подсистема.yaml").write_text(
        "Interface:\n    IncludeInAutoInterface: False\n", encoding="utf-8")
    (subsystem / "MainStrings.yaml").write_text(
        "ElementKind: LocalizedStrings\nId: 6f0b6a44-0000-4000-8000-0000000000e1\n"
        "Name: MainStrings\nVisibilityScope: InProject\n"
        "Strings:\n    Name: Name\n", encoding="utf-8")
    (subsystem / "Tasks.yaml").write_text(
        "ElementKind: Catalog\nId: 6f0b6a44-0000-4000-8000-0000000000e2\n"
        "Name: Tasks\nPresentation: Name\nVisibilityScope: InProject\n"
        "Attributes:\n    -\n        Id: 6f0b6a44-0000-4000-8000-0000000000e3\n"
        "        Name: DueDate\n        Type: Date\n", encoding="utf-8")

    apply_result(scaffold.op_add_form(tmp_path, name="Tasks"))
    list_form = subsystem / "TasksListForm.yaml"
    text = list_form.read_text(encoding="utf-8")
    # The English key of the property, and no caption left as a literal.
    assert "Title: $MainStrings.Tasks" in text and "Заголовок:" not in text
    captions = _captions(list_form)
    assert captions[0] == "$MainStrings.Tasks" and "$MainStrings.DueDate" in captions
    assert all(caption.startswith("$MainStrings.") for caption in captions)
    strings = pyyaml.safe_load((subsystem / "MainStrings.yaml").read_text(encoding="utf-8"))
    # The section keeps its English name, and every referenced key is declared in it.
    assert set(strings["Strings"]) >= {"Name", "Tasks", "DueDate"}
    assert all(caption.split(".", 1)[1] in strings["Strings"] for caption in captions)


@pytest.mark.skipif(not dataset.available_versions(), reason="нет данных Элемента")
def test_the_rule_finds_nothing_in_a_generated_form(tmp_path):
    """The measurement the change was made for: five findings on this project, now none."""
    subsystem = _project(tmp_path)
    _catalog(subsystem)
    apply_result(scaffold.op_add_form(tmp_path, name="Товары"))
    diagnostics = engine.run(discover([str(tmp_path)]), select={_RULE})
    assert diagnostics == []
