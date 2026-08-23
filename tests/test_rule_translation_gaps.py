"""Translation gaps (conventions/missing-translation): what the dictionary does not cover.

The rule is off by default and silent without a dictionary, so the tests ask for it the way
a project does - by enabling it.
"""

from xbsl import engine
from xbsl.cli import discover

RULE = "conventions/missing-translation"

_MODULE = """@Обработчик
метод ПоказатьОтчёт()
    // Считаем итог по строкам
;
"""

_DICTIONARY = """version: 1
language: en

# Записи, добавленные вручную: имена форм и команд.
tokens:
    ПоказатьОтчёт: ShowReport
    Проба: Trial
    Модуль: Module
"""


def _project(tmp_path, *, dictionary: bool = True, entries: str = _DICTIONARY):
    (tmp_path / "Проект.yaml").write_text(
        "ВидЭлемента: Проект\nИд: 11111111-2222-3333-4444-555555555555\nИмя: Проба\n"
        "Версия: 1.0\nПоставщик: acme\n",
        encoding="utf-8",
    )
    (tmp_path / "Модуль.xbsl").write_text(_MODULE, encoding="utf-8")
    (tmp_path / "Модуль.yaml").write_text(
        "ВидЭлемента: ОбщийМодуль\nИд: 66666666-2222-3333-4444-555555555555\nИмя: Модуль\n",
        encoding="utf-8",
    )
    if dictionary:
        folder = tmp_path / "xbsl-translation"
        folder.mkdir()
        (folder / "010-tokens.yaml").write_text(entries, encoding="utf-8")
    return [
        d for d in engine.run(discover([str(tmp_path)]), enable={RULE}) if d.rule_id == RULE
    ]


def test_a_comment_the_dictionary_does_not_cover_is_a_gap(tmp_path):
    diags = _project(tmp_path)

    assert len(diags) == 1 and diags[0].path.endswith("Модуль.xbsl")
    assert "Считаем итог" in diags[0].message


def test_the_dictionary_files_themselves_are_not_judged(tmp_path):
    """They are Russian by construction: the keys are the words, the head comment says what
    the batch is about. Judged as sources, they gave 826 "gaps" on a covered project."""
    diags = _project(tmp_path)

    assert all("xbsl-translation" not in d.path for d in diags), [d.path for d in diags]


def test_without_a_dictionary_the_rule_says_nothing(tmp_path):
    """A project that does not translate its sources hears nothing, enabled or not."""
    assert _project(tmp_path, dictionary=False) == []


def test_a_covered_project_is_clean(tmp_path):
    covered = _DICTIONARY + "\nphrases:\n    Считаем итог по строкам: Sum up the rows\n"
    diags = _project(tmp_path, entries=covered)

    assert diags == []


def test_the_rule_is_off_until_it_is_asked_for(tmp_path):
    """The most expensive rule of the set: every file goes through the translation pass."""
    from xbsl.engine import SEVERITY_OVERRIDES

    if RULE in SEVERITY_OVERRIDES:  # pragma: no cover - depends on the installed plugin
        return
    (tmp_path / "Модуль.xbsl").write_text(_MODULE, encoding="utf-8")
    folder = tmp_path / "xbsl-translation"
    folder.mkdir()
    (folder / "010-tokens.yaml").write_text(_DICTIONARY, encoding="utf-8")

    diags = [d for d in engine.run(discover([str(tmp_path)])) if d.rule_id == RULE]

    assert diags == []
