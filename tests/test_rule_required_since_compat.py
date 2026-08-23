"""A property the compatibility mode demands in writing (yaml/property-required-since-compat).

Met live: a project raised to 10.0 stopped applying, the refusal naming the access-key
setting the sources never wrote, while the same sources under 9.0 applied without a word. The
platform default exists (`false`) and does not satisfy the compiler there, so no data answers
this - the rule carries the measured case, wording and all, in a table.
"""

from xbsl import engine
from xbsl.cli import discover

RULE = "yaml/property-required-since-compat"

_KEY = """ВидЭлемента: КлючДоступа
Ид: 2f617cf5-7067-4de5-b183-f2125e50b623
Имя: КлючДоступаПробы
ОбластьВидимости: ВПроекте
"""


def _project(tmp_path, *, compat: str = "10.0", key: str = _KEY, descriptor: bool = True):
    if descriptor:
        # A project description carries no element kind - that is what tells it from an element.
        (tmp_path / "Проект.yaml").write_text(
            "Ид: 11111111-2222-3333-4444-555555555555\n"
            f"Имя: Проба\nВерсия: 1.0\nПоставщик: acme\nРежимСовместимости: {compat}\n",
            encoding="utf-8",
        )
    (tmp_path / "КлючДоступаПробы.yaml").write_text(key, encoding="utf-8")
    return [d for d in engine.run(discover([str(tmp_path)]), select={RULE}) if d.rule_id == RULE]


def test_the_omitted_property_is_an_error_under_the_new_mode(tmp_path):
    diags = _project(tmp_path)

    assert len(diags) == 1 and diags[0].severity.value == "error"
    assert "РучнаяВыдача" in diags[0].message and "10.0" in diags[0].message
    # The compiler names the file rather than a place inside it, and so does the rule.
    assert (diags[0].line, diags[0].col) == (1, 1)


def test_the_property_written_out_is_accepted(tmp_path):
    diags = _project(tmp_path, key=_KEY + "РучнаяВыдача: Ложь\n")

    assert diags == []


def test_the_english_spelling_counts_as_written(tmp_path):
    diags = _project(tmp_path, key=_KEY + "ManualGrant: false\n")

    assert diags == []


def test_the_older_mode_hears_nothing(tmp_path):
    """Under 9.0 the same sources applied without a word - the rule must not invent a defect."""
    assert _project(tmp_path, compat="9.0") == []


def test_without_a_project_description_the_mode_is_unknown(tmp_path):
    """A single file checked outside its project: silence, not a guess."""
    assert _project(tmp_path, descriptor=False) == []


def test_another_kind_is_not_judged(tmp_path):
    other = """ВидЭлемента: ОбщийМодуль
Ид: 66666666-2222-3333-4444-555555555555
Имя: Модуль
"""
    diags = _project(tmp_path, key=other)

    assert diags == []
