"""Checks of the yaml/ref-needs-nullable rule (a reference type in Тип: without '?').

The rule needs no Element data (the shape of the value is enough), so these tests run in a
public checkout too.
"""

import pytest

from xbsl import engine
from xbsl.cli import discover

_RULE = "yaml/ref-needs-nullable"


def _run(tmp_path, text, name="Ф.yaml"):
    (tmp_path / name).write_text(text, encoding="utf-8")
    return engine.run(discover([str(tmp_path)]), select={_RULE})


def _has(diags):
    return any(d.rule_id == _RULE for d in diags)


def test_attribute_reference_flagged(tmp_path):
    d = _run(
        tmp_path,
        "ВидЭлемента: Справочник\nИмя: Письма\nРеквизиты:\n"
        "    -\n        Имя: Владелец\n        Тип: Организации.Ссылка\n",
    )
    assert len(d) == 1 and d[0].rule_id == _RULE
    assert d[0].severity.name == "ERROR"
    assert "Организации.Ссылка?" in d[0].message
    # the exact position of the value, as the compiler reports it
    assert (d[0].line, d[0].col) == (6, 14)


def test_nullable_attribute_not_flagged(tmp_path):
    d = _run(
        tmp_path,
        "ВидЭлемента: Справочник\nИмя: Письма\nРеквизиты:\n"
        "    -\n        Имя: Владелец\n        Тип: Организации.Ссылка?\n",
    )
    assert not _has(d)


def test_input_field_argument_flagged(tmp_path):
    d = _run(
        tmp_path,
        "ВидЭлемента: КомпонентИнтерфейса\nИмя: Ф\nСодержимое:\n"
        "    -\n        Имя: Поле\n        Тип: ПолеВвода<Организации.Ссылка>\n",
    )
    assert len(d) == 1 and "ПолеВвода<Организации.Ссылка?>" in d[0].message
    # the position points at the argument inside the value - the place to edit
    assert (d[0].line, d[0].col) == (6, 24)


def test_input_field_nullable_argument_not_flagged(tmp_path):
    d = _run(
        tmp_path,
        "ВидЭлемента: КомпонентИнтерфейса\nИмя: Ф\nСодержимое:\n"
        "    -\n        Имя: Поле\n        Тип: ПолеВвода<Организации.Ссылка?>\n",
    )
    assert not _has(d)


def test_component_property_flagged(tmp_path):
    d = _run(
        tmp_path,
        "ВидЭлемента: КомпонентИнтерфейса\nИмя: Ф\nСвойства:\n"
        "    -\n        Имя: Выбранный\n        Тип: Организации.Ссылка\n",
    )
    assert len(d) == 1


def test_stdlib_reference_flagged(tmp_path):
    # a stdlib reference behaves exactly like a project one (verified),
    # so the rule needs no project knowledge
    d = _run(
        tmp_path,
        "ВидЭлемента: Справочник\nИмя: Письма\nРеквизиты:\n"
        "    -\n        Имя: Файл\n        Тип: ДвоичныйОбъект.Ссылка\n",
    )
    assert len(d) == 1 and "ДвоичныйОбъект.Ссылка?" in d[0].message


def test_array_of_references_not_flagged(tmp_path):
    # a collection has its own default - the compiler accepts this
    d = _run(
        tmp_path,
        "ВидЭлемента: Справочник\nИмя: Письма\nРеквизиты:\n"
        "    -\n        Имя: Файлы\n        Тип: Массив<ДвоичныйОбъект.Ссылка>\n",
    )
    assert not _has(d)


def test_union_of_references_flagged(tmp_path):
    # probe 2026-08-13: "Default value initialization is not supported for types ..."
    d = _run(
        tmp_path,
        "ВидЭлемента: Справочник\nИмя: Письма\nРеквизиты:\n"
        "    -\n        Имя: А\n        Тип: Организации.Ссылка|Товары.Ссылка\n",
    )
    assert len(d) == 1 and "Организации.Ссылка|Товары.Ссылка|?" in d[0].message
    assert (d[0].line, d[0].col) == (6, 14)


def test_mixed_union_flagged(tmp_path):
    # the same probe: a value-typed member does not provide the default
    d = _run(
        tmp_path,
        "ВидЭлемента: Справочник\nИмя: Письма\nРеквизиты:\n"
        "    -\n        Имя: А\n        Тип: Строка|Организации.Ссылка\n",
    )
    assert len(d) == 1 and "Строка|Организации.Ссылка|?" in d[0].message


def test_union_with_nullable_marker_not_flagged(tmp_path):
    d = _run(
        tmp_path,
        "ВидЭлемента: Справочник\nИмя: Письма\nРеквизиты:\n"
        "    -\n        Имя: А\n        Тип: Организации.Ссылка|Товары.Ссылка|?\n",
    )
    assert not _has(d)


def test_union_with_nullable_member_not_flagged(tmp_path):
    # a nullable MEMBER injects the empty value into the whole set (a live project ships this)
    d = _run(
        tmp_path,
        "ВидЭлемента: Справочник\nИмя: Письма\nРеквизиты:\n"
        "    -\n        Имя: А\n        Тип: Организации.Ссылка|Товары.Ссылка?\n",
    )
    assert not _has(d)


def test_union_without_references_not_flagged(tmp_path):
    # not established by the probe - silence is the safe side
    d = _run(
        tmp_path,
        "ВидЭлемента: Справочник\nИмя: Письма\nРеквизиты:\n"
        "    -\n        Имя: А\n        Тип: Строка|Число\n",
    )
    assert not _has(d)


def test_union_with_generic_member_not_flagged(tmp_path):
    d = _run(
        tmp_path,
        "ВидЭлемента: Справочник\nИмя: Письма\nРеквизиты:\n"
        "    -\n        Имя: А\n        Тип: Массив<Строка>|Организации.Ссылка\n",
    )
    assert not _has(d)


def test_union_with_qualified_member_not_flagged(tmp_path):
    d = _run(
        tmp_path,
        "ВидЭлемента: Справочник\nИмя: Письма\nРеквизиты:\n"
        "    -\n        Имя: А\n        Тип: acme::Проект::Организации.Ссылка|Строка\n",
    )
    assert not _has(d)


def test_input_field_union_flagged(tmp_path):
    # probe 2026-08-13: Parameter "ТипДанных" ... must have a default value
    d = _run(
        tmp_path,
        "ВидЭлемента: КомпонентИнтерфейса\nИмя: Ф\nСодержимое:\n"
        "    -\n        Имя: Поле\n        Тип: ПолеВвода<Организации.Ссылка|Товары.Ссылка>\n",
    )
    assert len(d) == 1
    assert "ПолеВвода<Организации.Ссылка|Товары.Ссылка|?>" in d[0].message
    # the position points at the argument inside the value
    assert (d[0].line, d[0].col) == (6, 24)


def test_input_field_union_with_nullable_not_flagged(tmp_path):
    d = _run(
        tmp_path,
        "ВидЭлемента: КомпонентИнтерфейса\nИмя: Ф\nСодержимое:\n"
        "    -\n        Имя: Поле\n"
        "        Тип: ПолеВвода<Организации.Ссылка|Товары.Ссылка|?>\n",
    )
    assert not _has(d)


def test_qualified_name_not_flagged(tmp_path):
    # a foreign, namespace-qualified type is left alone
    d = _run(
        tmp_path,
        "ВидЭлемента: Справочник\nИмя: Письма\nРеквизиты:\n"
        "    -\n        Имя: А\n        Тип: acme::Проект::Организации.Ссылка\n",
    )
    assert not _has(d)


def test_bare_reference_word_not_flagged(tmp_path):
    # a one-segment chain is a local type name, not an object reference
    d = _run(
        tmp_path,
        "ВидЭлемента: Структура\nИмя: С\nПоля:\n"
        "    -\n        Имя: А\n        Тип: Ссылка\n",
    )
    assert not _has(d)


def test_structural_file_not_scanned(tmp_path):
    # no ВидЭлемента - a Проект/Подсистема file carries no types
    d = _run(tmp_path, "Имя: Проект\nТип: Организации.Ссылка\n", name="Проект.yaml")
    assert not _has(d)


def test_block_scalar_not_scanned(tmp_path):
    # the line 'Тип: Организации.Ссылка' inside a literal block is text, not a type
    d = _run(
        tmp_path,
        "ВидЭлемента: КомпонентИнтерфейса\nИмя: Ф\nОписание: |\n    Тип: Организации.Ссылка\n",
    )
    assert not _has(d)


def test_quoted_value_position(tmp_path):
    # a quoted value: the position skips the opening quote
    d = _run(
        tmp_path,
        "ВидЭлемента: Справочник\nИмя: Письма\nРеквизиты:\n"
        '    -\n        Имя: А\n        Тип: "Организации.Ссылка"\n',
    )
    assert len(d) == 1 and (d[0].line, d[0].col) == (6, 15)


def test_crlf_positions(tmp_path):
    (tmp_path / "Ф.yaml").write_bytes(
        "ВидЭлемента: Справочник\r\nИмя: Письма\r\nРеквизиты:\r\n"
        "    -\r\n        Имя: А\r\n        Тип: Организации.Ссылка\r\n".encode("utf-8")
    )
    d = engine.run(discover([str(tmp_path)]), select={_RULE})
    assert len(d) == 1 and (d[0].line, d[0].col) == (6, 14)


def test_two_references_in_one_file(tmp_path):
    # positions come from the node graph, so equal values in different nodes are told apart
    d = _run(
        tmp_path,
        "ВидЭлемента: Справочник\nИмя: Письма\nРеквизиты:\n"
        "    -\n        Имя: А\n        Тип: Организации.Ссылка\n"
        "    -\n        Имя: Б\n        Тип: Организации.Ссылка\n",
    )
    assert [(x.line, x.col) for x in d] == [(6, 14), (9, 14)]


@pytest.mark.needs_data  # the English spellings come from terms.json
def test_english_input_field_spelling_is_judged(tmp_path):
    """The platform reads `Edit<...>` the same way; the advice keeps the spelling of the file."""
    from xbsl.engine import load_text, run_sources

    src = load_text(
        "F.yaml",
        "ElementKind: InterfaceComponent\n"
        "Id: 1f9b6d38-5c27-4e91-8a43-2d7e0b5c9a11\n"
        "Name: F\n"
        "Properties:\n"
        "    -\n        Id: 8f3a2c14-7b6d-4e05-9a1c-2d5f8b47e903\n"
        "        Name: Goods\n        Type: Edit<Товары.Ссылка>\n",
    )
    diags = list(run_sources([src], select={"yaml/ref-needs-nullable"}))
    assert len(diags) == 1
    assert "Edit<Товары.Ссылка?>" in diags[0].message and "ПолеВвода" not in diags[0].message
