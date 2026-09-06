"""Three defects of the scaffolding, all found by using it on a live project.

A register is born with a placeholder dimension (the platform refuses an empty list), and the
first real dimension used to land NEXT to it - the stub was then deleted by hand after every
add. A tabular part had that fix long ago; the register did not.

The `Length` of a standard field was written as given: the platform's limit is caught by the
linter on the NEXT run, over a file the tool has already written. A limit the tool knows
belongs in the tool.

And a register field asked by the wrong kind: an attribute where every neighbour sat in
`Resources` opened a new `Attributes` section at the end of the file without a word, and the
field was then moved by hand, UUID and all. The section is still created - the caller asked
for it - but notes say so and name the kind that would have put the field beside its kin.
"""

import io
from pathlib import Path

import pytest
import yaml as pyyaml

import xbsl.engine  # noqa: F401 - breaks the scaffold <-> rules import cycle
from xbsl import scaffold


def _object(tmp_path: Path, kind: str, name: str, **kw) -> Path:
    directory = tmp_path / "Основное"
    directory.mkdir(parents=True, exist_ok=True)
    result = scaffold.op_new_object(directory, kind, name, **kw)
    for change in result.changes:
        change.path.parent.mkdir(parents=True, exist_ok=True)
        io.open(change.path, "w", encoding="utf-8", newline="").write(change.content)
    return next(c.path for c in result.changes if c.path.suffix == ".yaml")


def _apply(path: Path, result) -> str:
    text = result.changes[0].content
    io.open(path, "w", encoding="utf-8", newline="").write(text)
    return text


# --- the placeholder of a register ----------------------------------------------------


def test_the_first_dimension_takes_the_place_of_the_placeholder(tmp_path: Path):
    path = _object(tmp_path, "РегистрСведений", "Курсы")
    assert "Измерение1" in path.read_text(encoding="utf-8")

    result = scaffold.op_add_field(path, "измерение", "Валюта", type_="Строка")

    text = _apply(path, result)
    assert "Измерение1" not in text
    assert "Имя: Валюта" in text
    assert any("Измерение1" in note for note in result.notes)


def test_the_second_dimension_is_added_beside_the_first(tmp_path: Path):
    path = _object(tmp_path, "РегистрСведений", "Курсы")
    _apply(path, scaffold.op_add_field(path, "измерение", "Валюта", type_="Строка"))

    text = _apply(path, scaffold.op_add_field(path, "измерение", "Период", type_="ДатаВремя"))

    assert "Имя: Валюта" in text and "Имя: Период" in text


def test_a_renamed_placeholder_belongs_to_its_author(tmp_path: Path):
    """The control: a dimension the author touched is not a stub any more."""
    path = _object(tmp_path, "РегистрСведений", "Курсы")
    # Read with utf-8-sig: the tool writes a BOM, and without this it would ride into the
    # first line as part of the key, leaving the element kind unknown.
    was = io.open(path, encoding="utf-8-sig").read()
    io.open(path, "w", encoding="utf-8", newline="").write(
        was.replace("Имя: Измерение1", "Имя: Организация"))

    text = _apply(path, scaffold.op_add_field(path, "измерение", "Валюта", type_="Строка"))

    assert "Имя: Организация" in text and "Имя: Валюта" in text


def test_a_resource_of_an_accumulation_register_replaces_its_placeholder(tmp_path: Path):
    path = _object(tmp_path, "РегистрНакопления", "Остатки")
    assert "Ресурс1" in path.read_text(encoding="utf-8")

    text = _apply(path, scaffold.op_add_field(path, "ресурс", "Количество", type_="Число"))

    assert "Ресурс1" not in text and "Имя: Количество" in text


# --- the length of a standard field ---------------------------------------------------


@pytest.mark.parametrize("name,length", [("Код", 260), ("Код", 51), ("Наименование", 401)])
def test_a_length_above_the_platform_limit_is_refused(tmp_path: Path, name: str, length: int):
    path = _object(tmp_path, "Справочник", "Товары", presentation="Наименование")

    with pytest.raises(scaffold.ScaffoldError) as error:
        scaffold.op_add_field(path, "реквизит", name, props={"Длина": length})

    assert name in str(error.value) and str(length) in str(error.value)


@pytest.mark.parametrize("name,length", [("Код", 50), ("Наименование", 400)])
def test_the_limit_itself_passes(tmp_path: Path, name: str, length: int):
    """The control: the boundary is allowed - the compiler accepts it."""
    path = _object(tmp_path, "Справочник", "Товары", presentation="Наименование")

    text = _apply(path, scaffold.op_add_field(path, "реквизит", name, props={"Длина": length}))

    assert f"Длина: {length}" in text


def test_an_ordinary_field_keeps_its_own_length_property(tmp_path: Path):
    """The control on the name: the limit belongs to the standard fields alone."""
    path = _object(tmp_path, "Справочник", "Товары", presentation="Наименование")

    text = _apply(path, scaffold.op_add_field(
        path, "реквизит", "Описание", type_="Строка", props={"МаксимальнаяДлина": 1000}))

    assert "МаксимальнаяДлина: 1000" in text


# --- the section a register field goes into -------------------------------------------


def _register_with_resources(tmp_path: Path) -> Path:
    """An information register holding a dimension and a resource - no attributes section."""
    path = _object(tmp_path, "РегистрСведений", "Курсы")
    _apply(path, scaffold.op_add_field(path, "измерение", "Страна", type_="Строка"))
    _apply(path, scaffold.op_add_field(path, "ресурс", "Ставка", type_="Число"))
    return path


def _sections(text: str) -> dict:
    return pyyaml.safe_load(text)


def test_an_attribute_beside_resources_opens_a_new_section_and_says_so(tmp_path: Path):
    """The pain: the field went into a new section while every neighbour sat in Resources."""
    path = _register_with_resources(tmp_path)

    result = scaffold.op_add_field(path, "реквизит", "Примечание", type_="Строка")

    parsed = _sections(_apply(path, result))
    assert [i["Имя"] for i in parsed["Реквизиты"]] == ["Примечание"]
    assert [i["Имя"] for i in parsed["Ресурсы"]] == ["Ставка"]
    assert any("Секции Реквизиты" in note and "не было" in note for note in result.notes)
    assert any("Ресурсы" in note and "'ресурс'" in note for note in result.notes)


def test_a_resource_joins_the_existing_section_without_a_note(tmp_path: Path):
    path = _register_with_resources(tmp_path)

    result = scaffold.op_add_field(path, "ресурс", "Комиссия", type_="Число")

    parsed = _sections(_apply(path, result))
    assert [i["Имя"] for i in parsed["Ресурсы"]] == ["Ставка", "Комиссия"]
    assert "Реквизиты" not in parsed
    assert result.notes == []


def test_a_register_with_both_sections_takes_each_field_into_its_own(tmp_path: Path):
    path = _register_with_resources(tmp_path)
    _apply(path, scaffold.op_add_field(path, "реквизит", "Примечание", type_="Строка"))

    resource = scaffold.op_add_field(path, "ресурс", "Комиссия", type_="Число")
    _apply(path, resource)
    attribute = scaffold.op_add_field(path, "реквизит", "Автор", type_="Строка")
    text = _apply(path, attribute)

    parsed = _sections(text)
    assert [i["Имя"] for i in parsed["Ресурсы"]] == ["Ставка", "Комиссия"]
    assert [i["Имя"] for i in parsed["Реквизиты"]] == ["Примечание", "Автор"]
    # The resource sits inside its own section, ahead of the attributes header - not after
    # every section of the file.
    assert text.index("Имя: Комиссия") < text.index("Реквизиты:")
    assert resource.notes == [] and attribute.notes == []


@pytest.mark.needs_data  # the English spellings of the sections come from the metamodel
def test_the_hint_reads_and_spells_an_english_register(tmp_path: Path):
    path = tmp_path / "Rates.yaml"
    path.write_text(
        "ElementKind: InformationRegister\n"
        "Id: 6f0b6a44-0000-4000-8000-0000000000c1\n"
        "Name: Rates\n"
        "Dimensions:\n    -\n        Name: Country\n        Type: String\n"
        "Resources:\n    -\n        Name: Rate\n        Type: Number\n",
        encoding="utf-8",
    )

    result = scaffold.op_add_field(path, "реквизит", "Note", type_="String")

    text = _apply(path, result)
    assert [i["Name"] for i in _sections(text)["Attributes"]] == ["Note"]
    assert "Реквизиты:" not in text
    assert any("Attributes" in note and "не было" in note for note in result.notes)
    assert any("Resources" in note and "'ресурс'" in note for note in result.notes)


def test_a_catalog_attribute_is_added_the_old_way(tmp_path: Path):
    """The control: a catalog has one field section, so nothing to point at and no notes."""
    path = _object(tmp_path, "Справочник", "Товары", presentation="Наименование")

    result = scaffold.op_add_field(path, "реквизит", "Примечание", type_="Строка")

    parsed = _sections(_apply(path, result))
    assert [i["Имя"] for i in parsed["Реквизиты"]] == ["Примечание"]
    assert result.notes == []
