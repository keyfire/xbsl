"""yaml/valid names the cause when the line shows it: a ternary written with spaces.

YAML reads ` : ` as the start of a nested mapping, so the parser complains about mapping
values over a line that has no mapping in it. The finding and its position stay the
parser's - only the explanation is added.
"""

from xbsl import engine, i18n
from xbsl.cli import discover

import pytest


@pytest.fixture(autouse=True)
def _ru_lang():
    i18n.set_lang("ru")
    yield
    i18n.set_lang(None)


def _lint(tmp_path, markup):
    (tmp_path / "Элемент.yaml").write_text(markup, encoding="utf-8")
    return [d for d in engine.run(discover([str(tmp_path)]), select={"yaml/valid"})]


def test_a_spaced_ternary_is_named(tmp_path):
    d = _lint(tmp_path, "ВидЭлемента: Справочник\nИмя: Товары\nВидимость: =Общее.Узко() ? Истина : Ложь\n")
    assert len(d) == 1
    assert "тернарн" in d[0].message


def test_an_ordinary_syntax_error_keeps_the_plain_message(tmp_path):
    """The control: the explanation is added only where the line shows the shape."""
    d = _lint(tmp_path, "ВидЭлемента: Справочник\nИмя: [оборванный\n")
    assert len(d) == 1
    assert "тернарн" not in d[0].message


def test_a_ternary_without_spaces_parses(tmp_path):
    assert _lint(tmp_path, "ВидЭлемента: Справочник\nИмя: Товары\nВидимость: =Общее.Узко() ? Истина :Ложь\n") == []
