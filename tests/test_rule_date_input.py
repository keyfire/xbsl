"""Checks of the yaml/date-input-needs-plain-date rule (a nullable date input field).

The rule needs no Element data (the shape of the value is enough), so these tests run in a
public checkout too.
"""

from xbsl import engine
from xbsl.cli import discover

_RULE = "yaml/date-input-needs-plain-date"


def _run(tmp_path, text, name="Ф.yaml"):
    (tmp_path / name).write_text(text, encoding="utf-8")
    return engine.run(discover([str(tmp_path)]), select={_RULE})


def _has(diags):
    return any(d.rule_id == _RULE for d in diags)


def test_nullable_date_input_flagged(tmp_path):
    d = _run(
        tmp_path,
        "ВидЭлемента: КомпонентИнтерфейса\nИмя: Ф\nСодержимое:\n"
        "    -\n        Имя: Поле\n        Тип: ПолеВвода<Дата?>\n",
    )
    assert len(d) == 1 and d[0].rule_id == _RULE
    assert d[0].severity.name == "WARNING"
    assert "ПолеВвода<Дата>" in d[0].message and "Дата{}" in d[0].message
    # the position points at the argument inside the value - the place to edit
    assert (d[0].line, d[0].col) == (6, 24)


def test_union_spelling_of_nullable_flagged(tmp_path):
    d = _run(
        tmp_path,
        "ВидЭлемента: КомпонентИнтерфейса\nИмя: Ф\nСодержимое:\n"
        "    -\n        Имя: Поле\n        Тип: ПолеВвода<Дата|?>\n",
    )
    assert len(d) == 1 and "ПолеВвода<Дата>" in d[0].message


def test_plain_date_input_not_flagged(tmp_path):
    d = _run(
        tmp_path,
        "ВидЭлемента: КомпонентИнтерфейса\nИмя: Ф\nСодержимое:\n"
        "    -\n        Имя: Поле\n        Тип: ПолеВвода<Дата>\n",
    )
    assert not _has(d)


def test_datetime_sibling_not_judged(tmp_path):
    # not verified on a live stand - silence is the safe side (see the module docstring)
    d = _run(
        tmp_path,
        "ВидЭлемента: КомпонентИнтерфейса\nИмя: Ф\nСодержимое:\n"
        "    -\n        Имя: Поле\n        Тип: ПолеВвода<ДатаВремя?>\n",
    )
    assert not _has(d)


def test_nullable_date_attribute_not_flagged(tmp_path):
    # only the input COMPONENT drops; a bare nullable date type is not its business
    d = _run(
        tmp_path,
        "ВидЭлемента: Справочник\nИмя: Письма\nРеквизиты:\n"
        "    -\n        Имя: Срок\n        Тип: Дата?\n",
    )
    assert not _has(d)


def test_english_spelling_flagged(tmp_path):
    d = _run(
        tmp_path,
        "ВидЭлемента: КомпонентИнтерфейса\nИмя: Ф\nСодержимое:\n"
        "    -\n        Имя: Поле\n        Тип: Edit<Date?>\n",
    )
    assert len(d) == 1 and "Edit<Date>" in d[0].message


def test_block_scalar_not_scanned(tmp_path):
    d = _run(
        tmp_path,
        "ВидЭлемента: КомпонентИнтерфейса\nИмя: Ф\nОписание: |\n    Тип: ПолеВвода<Дата?>\n",
    )
    assert not _has(d)


def test_quoted_value_position(tmp_path):
    d = _run(
        tmp_path,
        "ВидЭлемента: КомпонентИнтерфейса\nИмя: Ф\nСодержимое:\n"
        '    -\n        Имя: Поле\n        Тип: "ПолеВвода<Дата?>"\n',
    )
    assert len(d) == 1 and (d[0].line, d[0].col) == (6, 25)
