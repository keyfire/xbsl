"""What the scaffolding INVENTS is written in the language of the object.

The names of the standard attributes are not in the yaml - the tool completes them - and the
language pass protects the field names as the author's, so a Russian one used to survive into
an English project: `Name: Наименование`, `Value: =Object.Наименование`, `Type: Edit<Tasks.Ссылка?>`.
"""

import re

import pytest
import yaml as pyyaml

import xbsl.engine  # noqa: F401 - breaks the scaffold <-> rules import cycle
from xbsl import dataset, scaffold
from xbsl.scaffold import apply_result


def _english_catalog(tmp_path, extra_header=""):
    subsystem = tmp_path / "Acme" / "TasksEn" / "Main"
    subsystem.mkdir(parents=True)
    (subsystem.parent / "Проект.yaml").write_text(
        "Id: 6f0b6a44-0000-4000-8000-0000000000f0\nVendor: Acme\nName: TasksEn\n"
        "Version: 1.0.0\nLocalizationLanguages: [Русский, Английский]\n"
        "DefaultLanguage: Английский\n", encoding="utf-8")
    (subsystem / "Подсистема.yaml").write_text(
        "Interface:\n    IncludeInAutoInterface: False\n", encoding="utf-8")
    (subsystem / "Tasks.yaml").write_text(
        "ElementKind: Catalog\nId: 6f0b6a44-0000-4000-8000-0000000000f2\n"
        "Name: Tasks\nVisibilityScope: InProject\n" + extra_header +
        "Attributes:\n    -\n        Id: 6f0b6a44-0000-4000-8000-0000000000f3\n"
        "        Name: DueDate\n        Type: Date\n", encoding="utf-8")
    return subsystem


@pytest.mark.needs_data
def test_the_standard_attribute_of_an_english_catalog_is_english(tmp_path):
    _english_catalog(tmp_path)
    info = scaffold.object_info(tmp_path, name="Tasks")
    assert [f["name"] for f in info["fields"]] == ["Name", "DueDate"]
    assert info["lang"] == "en"


@pytest.mark.needs_data
def test_the_hierarchy_attribute_is_english_with_its_facet(tmp_path):
    _english_catalog(tmp_path, extra_header="Hierarchical: True\n")
    fields = {f["name"]: f["type"] for f in scaffold._form_fields(
        scaffold.object_info(tmp_path, name="Tasks"))}
    assert fields["Parent"] == "Tasks.Reference?"


@pytest.mark.skipif(not dataset.available_versions(), reason="нет данных Элемента")
def test_generated_forms_carry_no_russian_field_names(tmp_path):
    """The measurement the change was made for, on the finished files."""
    subsystem = _english_catalog(tmp_path, extra_header="Hierarchical: True\n")
    apply_result(scaffold.op_add_form(tmp_path, name="Tasks"))
    for form in sorted(subsystem.glob("Tasks*Form.yaml")):
        text = form.read_text(encoding="utf-8")
        assert "Наименование" not in text and "Родитель" not in text
        assert "Ссылка" not in text
        # The list still sorts by the standard attribute - under its English name.
        pyyaml.safe_load(text)


@pytest.mark.skipif(not dataset.available_versions(), reason="нет данных Элемента")
def test_the_list_sorts_by_the_standard_attribute(tmp_path):
    subsystem = _english_catalog(tmp_path)
    apply_result(scaffold.op_add_form(tmp_path, name="Tasks", forms=["list"]))
    text = (subsystem / "TasksListForm.yaml").read_text(encoding="utf-8")
    assert re.search(r"Field: Name\b", text)
