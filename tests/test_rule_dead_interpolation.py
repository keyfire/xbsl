"""code/dead-interpolation: an interpolation the platform swallows instead of evaluating.

Found on a live site by reviewers of the platform: a substring search built its pattern as
"%%{Запрос}%" and matched nothing, silently. The doubled sign reads as an escaped one - the
value carries the text of the expression instead of its result - and neither the compiler nor
the linter said a word.

Measured on a probe project compiled by the platform: the compiler reports the unknown name
inside %{...} and ${...} (so the module did compile - that is the control) and stays silent
on %%{...} and $${...}, which is the swallowing, for both signs.

The rule tokenizes a module, so it needs the Element data (the lexer reads the grammar from
the dataset) - hence the marker on the module.
"""

import pytest

from xbsl import engine

pytestmark = pytest.mark.needs_data

SELECT = {"code/dead-interpolation"}


def _lint(content: str):
    return engine.run_sources([engine.load_text("Проба.xbsl", content)], select=SELECT)


def _method(*lines: str) -> str:
    return "метод Проба(Запрос: Строка)\n" + "".join(f"    {line}\n" for line in lines) + ";\n"


def test_the_doubled_sign_before_a_brace_is_reported():
    found = _lint(_method('знч Шаблон = "%%{Запрос}%"'))

    assert len(found) == 1, [d.message for d in found]
    assert found[0].line == 2 and found[0].severity.value == "error"
    assert "%{...}" in found[0].message


def test_the_escaped_spelling_is_the_correct_one_and_stays_quiet():
    """A backslash before the pair is what the author meant: a literal sign, then the value."""
    assert _lint(_method('знч Шаблон = "\\%%{Запрос}\\%"')) == []


def test_a_lone_sign_and_an_ordinary_percent_are_left_alone():
    assert _lint(_method(
        'знч Один = "%{Запрос}"',
        'знч Текст = "50% заряда"',
        'знч Цена = "цена 10$"',
    )) == []


def test_the_dollar_form_is_reported_the_same_way():
    found = _lint(_method('знч Шаблон = "$${Запрос}"'))

    assert len(found) == 1 and "${...}" in found[0].message


def test_the_fix_inserts_the_escape_and_nothing_else():
    text = _method('знч Шаблон = "%%{Запрос}%"')
    found = _lint(text)

    fix = found[0].fix
    assert fix is not None
    assert text[:fix.start] + fix.new + text[fix.end:] == _method(
        'знч Шаблон = "\\%%{Запрос}%"')


def test_a_comment_that_mentions_the_pair_is_not_code():
    """The check walks string tokens: the same characters in prose are not a defect."""
    assert _lint(_method('// так писать нельзя: "%%{Запрос}"', 'знч Шаблон = "%{Запрос}"')) == []
