"""Tests of code/duplicate-annotation: one declaration must not repeat an annotation.

The rule itself reads no Element catalogs, but the lexer/parser behind it read
language.json - so every test that parses a module is marked `needs_data`, and only
the yaml-skip test runs in a data-free public checkout.
"""

from __future__ import annotations

import pytest

from xbsl.diagnostics import Diagnostic
from xbsl.engine import load_text, run_sources


def _lint(code: str) -> list[Diagnostic]:
    src = load_text("Модуль.xbsl", code)
    return list(run_sources([src], select={"code/duplicate-annotation"}, scopes=("file",)))


@pytest.mark.needs_data
def test_dup_ann_through_comment_is_flagged():
    # the trap from real life: a comment between annotation groups does not split them,
    # both annotations land on the structure and the compiler refuses the module
    diags = _lint(
        "@НаСервере\n"
        "// комментарий чужого метода\n"
        "@НаСервере @Локально\n"
        "структура НастройкиСервера\n"
        "    знч Имя: Строка = \"\"\n"
        ";\n"
    )
    assert len(diags) == 1
    assert diags[0].severity.value == "error"
    assert "@НаСервере" in diags[0].message
    assert diags[0].line == 3


@pytest.mark.needs_data
def test_dup_ann_same_line_is_flagged():
    diags = _lint(
        "@НаСервере @НаСервере\n"
        "метод ДваждыНаСервере()\n"
        ";\n"
    )
    assert len(diags) == 1
    assert diags[0].line == 1


@pytest.mark.needs_data
def test_dup_ann_comment_between_annotation_and_declaration_is_legal():
    diags = _lint(
        "@НаСервере\n"
        "// поясняющий комментарий перед методом\n"
        "метод ЗаконныйМетод()\n"
        ";\n"
    )
    assert diags == [], [d.message for d in diags]


@pytest.mark.needs_data
def test_dup_ann_different_annotations_through_comment_are_legal():
    diags = _lint(
        "@НаСервере\n"
        "// комментарий\n"
        "@Локально\n"
        "метод ДругойЗаконныйМетод()\n"
        ";\n"
    )
    assert diags == [], [d.message for d in diags]


@pytest.mark.needs_data
def test_dup_ann_mixed_spellings_pass():
    # `@НаСервере`/`@OnServer` name one annotation, but the compiler's refusal for the
    # mixed pair is not proven - the rule flags exact repeats only
    diags = _lint(
        "@OnServer\n"
        "@НаСервере\n"
        "метод ДвуязычнаяПара()\n"
        ";\n"
    )
    assert diags == [], [d.message for d in diags]


@pytest.mark.needs_data
def test_dup_ann_with_arguments_pass():
    # arguments may legitimately differ and the refusal for `@Имя(...)` is not proven -
    # occurrences with an argument list drop out of the comparison
    diags = _lint(
        "структура ПереносДанных\n"
        "    @JsonСвойство(\"имя\")\n"
        "    // комментарий, оставшийся от старого поля\n"
        "    @JsonСвойство(\"название\")\n"
        "    знч Название: Строка = \"\"\n"
        ";\n"
    )
    assert diags == [], [d.message for d in diags]


@pytest.mark.needs_data
def test_dup_ann_empty_parens_count_as_arguments():
    # `@Имя()` carries an (empty) argument list - out of the comparison, like `@Имя(...)`
    diags = _lint(
        "@Проба()\n"
        "@Проба()\n"
        "метод СПустымиСкобками()\n"
        ";\n"
    )
    assert diags == [], [d.message for d in diags]


@pytest.mark.needs_data
def test_dup_ann_on_structure_field_is_flagged():
    diags = _lint(
        "структура Настройки\n"
        "    @Обязательное\n"
        "    // комментарий\n"
        "    @Обязательное\n"
        "    знч Поле: Строка = \"\"\n"
        ";\n"
    )
    assert len(diags) == 1
    assert diags[0].line == 4


@pytest.mark.needs_data
def test_dup_ann_triple_repeat_yields_two_findings():
    diags = _lint(
        "@НаСервере @НаСервере @НаСервере\n"
        "метод Трижды()\n"
        ";\n"
    )
    assert len(diags) == 2


@pytest.mark.needs_data
def test_dup_ann_bare_at_is_not_a_duplicate():
    # a bare `@` parses with an empty name; the parse errors cover it, not this rule
    diags = _lint(
        "@\n"
        "@\n"
        "метод ГолыеСобаки()\n"
        ";\n"
    )
    assert diags == [], [d.message for d in diags]


def test_dup_ann_yaml_sources_are_skipped():
    src = load_text("Форма.yaml", "Вид: Форма\n")
    diags = list(run_sources([src], select={"code/duplicate-annotation"}, scopes=("file",)))
    assert diags == []
