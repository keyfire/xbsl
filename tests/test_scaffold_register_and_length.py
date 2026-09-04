"""Two defects of the scaffolding, both found by using it on a live project.

A register is born with a placeholder dimension (the platform refuses an empty list), and the
first real dimension used to land NEXT to it - the stub was then deleted by hand after every
add. A tabular part had that fix long ago; the register did not.

And the `Length` of a standard field was written as given: the platform's limit is caught by the
linter on the NEXT run, over a file the tool has already written. A limit the tool knows
belongs in the tool.
"""

import io
from pathlib import Path

import pytest

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
