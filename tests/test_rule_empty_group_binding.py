"""The binding flavour of yaml/empty-group-sized: an empty UNNAMED group sized by a binding.

The literal flavour is covered in test_rules_render_and_layout.py; these tests pin the branch
added for a size binding – the exact shape that survived on a live public page for a month and
a half (`Высота: =ОтступСнизу` on an unnamed spacer group, no content). The name filter is the
load-bearing part: a NAMED empty container is filled from code through its name, so the rule
must stay silent on it, while an unnamed one is unreachable from code and never renders.

Everything here goes through the yaml object walk, which needs the Element data (the component
dictionary supplies the spelling pairs the walk canonicalizes by), so every test is marked.
"""

from __future__ import annotations

import pytest

from xbsl.cli import discover
from xbsl.engine import run

_RULE = "yaml/empty-group-sized"

_HEAD = (
    "ВидЭлемента: КомпонентИнтерфейса\n"
    "Ид: 7c2e9f4a-aaaa-bbbb-cccc-444455556666\n"
    "Имя: ПробнаяФорма\n"
    "Содержимое:\n"
)

#: The historic defect verbatim: an unnamed spacer group whose height is a binding.
_HISTORIC_SPACER = (
    "ВидЭлемента: КомпонентИнтерфейса\n"
    "Ид: 7c2e9f4a-aaaa-bbbb-cccc-444455556667\n"
    "Имя: ЗаголовокСекции\n"
    "Наследует:\n"
    "    Тип: Группа\n"
    "    Компоновка: Вертикальная\n"
    "    Содержимое:\n"
    "        -\n"
    "            Тип: Надпись\n"
    "            Имя: Заголовок\n"
    "            Значение: =Текст\n"
    "        -\n"
    "            Тип: Группа\n"
    "            Высота: =ОтступСнизу\n"
    "            РастягиватьПоВертикали: Ложь\n"
    "Свойства:\n"
    "    -\n"
    "        Имя: Текст\n"
    "        Тип: Строка\n"
    "    -\n"
    "        Имя: ОтступСнизу\n"
    "        Тип: Число\n"
)


def _diags(tmp_path, name: str, text: str):
    (tmp_path / name).write_text(text, encoding="utf-8")
    found = run(discover([str(tmp_path)]), select={_RULE})
    return [(d.line, d.message) for d in found]


@pytest.mark.needs_data
def test_unnamed_binding_spacer_group_is_reported(tmp_path):
    found = _diags(tmp_path, "ЗаголовокСекции.yaml", _HISTORIC_SPACER)
    assert len(found) == 1
    assert found[0][0] == 14  # the size key of the spacer, not the outer group
    assert "=ОтступСнизу" in found[0][1]


@pytest.mark.needs_data
def test_named_binding_spacer_group_is_silent(tmp_path):
    """A named empty container is filled from code through the name - a legitimate pattern."""
    text = _HISTORIC_SPACER.replace(
        "            Высота: =ОтступСнизу\n",
        "            Имя: Контейнер\n            Высота: =ОтступСнизу\n",
    )
    assert _diags(tmp_path, "ЗаголовокСекции.yaml", text) == []


@pytest.mark.needs_data
def test_binding_group_with_content_is_silent(tmp_path):
    text = (
        _HEAD
        + "    -\n        Тип: Группа\n        Высота: =Отступ\n        Содержимое:\n"
          "            -\n                Тип: Надпись\n                Значение: Есть\n"
    )
    assert _diags(tmp_path, "ПробнаяФорма.yaml", text) == []


@pytest.mark.needs_data
def test_english_unnamed_binding_group_is_reported(tmp_path):
    text = _HEAD + "    -\n        Type: Group\n        Height: =BottomIndent\n"
    found = _diags(tmp_path, "ПробнаяФорма.yaml", text)
    assert len(found) == 1
    assert "=BottomIndent" in found[0][1]


@pytest.mark.needs_data
def test_english_named_binding_group_is_silent(tmp_path):
    """`Name` canonicalizes to the same key the filter reads."""
    text = (
        _HEAD
        + "    -\n        Type: Group\n        Name: Container\n        Height: =BottomIndent\n"
    )
    assert _diags(tmp_path, "ПробнаяФорма.yaml", text) == []


@pytest.mark.needs_data
def test_binding_width_of_an_unnamed_group_is_reported(tmp_path):
    text = _HEAD + "    -\n        Тип: Группа\n        Ширина: =ШиринаКолонки\n"
    found = _diags(tmp_path, "ПробнаяФорма.yaml", text)
    assert len(found) == 1
    assert "=ШиринаКолонки" in found[0][1]


@pytest.mark.needs_data
def test_block_scalar_size_is_not_a_binding(tmp_path):
    text = _HEAD + "    -\n        Тип: Группа\n        Высота: |\n            =Отступ\n"
    assert _diags(tmp_path, "ПробнаяФорма.yaml", text) == []


@pytest.mark.needs_data
def test_literal_size_is_reported_even_on_a_named_group(tmp_path):
    """The name filter belongs to the binding branch only: a literal-sized empty group never
    renders and a name does not save it, so the original reach of the rule is kept."""
    text = _HEAD + "    -\n        Тип: Группа\n        Имя: Распорка\n        Высота: 40\n"
    found = _diags(tmp_path, "ПробнаяФорма.yaml", text)
    assert len(found) == 1
    assert "40" in found[0][1]
