"""`yaml/hierarchy-bare-value`: a bare mode word in `UsedHierarchy` of a dynamic list.

A probe on a live server: a bare `Disabled`, `Default` or `Auto` fails the apply ("the type of
the value is not specified"), while the typed node, a quoted word and any other word apply.
The spellings of the modes come from the ui schema of the Element data, so the module needs it.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from xbsl import engine
from xbsl.cli import discover

pytestmark = pytest.mark.needs_data

_RULE = "yaml/hierarchy-bare-value"

_FORM = """ВидЭлемента: КомпонентИнтерфейса
Ид: 6c7a0a8e-0d59-4f0b-9f3c-6b1f4d0a2e11
Имя: ТоварыФормаСписка
Наследует:
    Тип: Форма
    Содержимое:
        -
            Тип: Таблица<ДинамическийСписок<ТоварыФормаСписка.ДанныеСтрокиСписка>>
            Имя: Список
            Источник:
                Тип: ДинамическийСписок<ТоварыФормаСписка.ДанныеСтрокиСписка>
                ОсновнаяТаблица:
                    Таблица: Товары
                ИспользуемаяИерархия: {value}
"""


def _run(tmp_path: Path, value: str, name: str = "ТоварыФормаСписка.yaml"):
    path = tmp_path / name
    path.write_bytes(_FORM.format(value=value).encode("utf-8"))
    diags = [d for d in engine.run(discover([str(tmp_path)]), select={_RULE})
             if d.rule_id == _RULE]
    return diags, path.read_bytes().decode("utf-8")


@pytest.mark.parametrize("word", ["Выключено", "ПоУмолчанию", "Авто", "Disabled", "Auto"])
def test_a_bare_mode_word_fails_the_apply(tmp_path, word):
    diags, _text = _run(tmp_path, word)
    line = next(n for n, text in enumerate(_FORM.splitlines(), 1) if "{value}" in text)
    assert len(diags) == 1 and diags[0].line == line


@pytest.mark.parametrize("value", [
    "{Тип: РежимИерархии, Значение: Выключено}",  # the typed node of the platform's examples
    '"Выключено"',  # a quoted word is the name of a hierarchy
    "Основная",  # a name of a hierarchy
    "РежимИерархии.Выключено",  # qualified: read as a name too, and it applies
])
def test_what_applies_is_left_alone(tmp_path, value):
    diags, _text = _run(tmp_path, value)
    assert diags == []


def test_the_fix_writes_the_typed_node_in_the_language_of_the_file(tmp_path):
    diags, text = _run(tmp_path, "Выключено")
    fix = diags[0].fix
    assert text[:fix.start] + fix.new + text[fix.end:] == _FORM.format(
        value="{Тип: РежимИерархии, Значение: Выключено}")


def test_an_english_word_gets_an_english_node(tmp_path):
    diags, text = _run(tmp_path, "Disabled")
    fix = diags[0].fix
    assert fix.new == "{Type: HierarchyMode, Value: Disabled}"


def test_the_fix_of_auto_takes_the_line_out(tmp_path):
    diags, text = _run(tmp_path, "Авто")
    fix = diags[0].fix
    fixed = text[:fix.start] + fix.new + text[fix.end:]
    assert "ИспользуемаяИерархия" not in fixed
    assert fixed.endswith("Таблица: Товары\n")


def test_a_flow_mapping_keeps_the_finding_without_a_line_fix(tmp_path):
    path = tmp_path / "Товары.yaml"
    path.write_text(
        "Источник: {Тип: ДинамическийСписок, ИспользуемаяИерархия: Авто}\n", encoding="utf-8")
    diags = [d for d in engine.run(discover([str(tmp_path)]), select={_RULE})
             if d.rule_id == _RULE]
    assert len(diags) == 1 and diags[0].fix is None
