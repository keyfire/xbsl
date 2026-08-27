"""yaml/inline-command-name: a `Name` on a command declared inline in the markup.

The evidence is the platform's own refusal at apply time ("a command name is allowed
only in command-interface-fragment project elements") - met live on a component
whose inline command-interface fragment carried a named command; the same command in a
fragment PROJECT ELEMENT applies clean, which is why a fragment-rooted file is skipped.

The rule needs no Element data (English spellings degrade to Russian without it), so the
tests live outside test_rules and run in the public CI; the English-spelling case is the
one that needs the term data.
"""

import pytest

from xbsl import engine
from xbsl.diagnostics import Severity

RULE = "yaml/inline-command-name"

_HEAD = (
    "ВидЭлемента: КомпонентИнтерфейса\n"
    "Ид: 11111111-1111-1111-1111-111111111111\n"
    "Имя: Форма\n"
)


def _lint(content, name="Форма.yaml"):
    return engine.run_sources([engine.load_text(name, content)], select={RULE})


def _fragment_markup(command: str) -> str:
    return (
        "Наследует:\n"
        "    Тип: Страница\n"
        "    ДополнительныеКоманды:\n"
        "        Тип: ФрагментКомандногоИнтерфейса\n"
        "        Элементы:\n"
        "            -\n"
        + "".join(f"                {line}\n" for line in command.splitlines())
    )


def test_rule_registered_file_scope():
    info = next(r for r in engine.active_rules() if r.id == RULE)
    assert info.tier == "A" and info.scope == "file"
    assert info.severity is Severity.ERROR and info.enabled_by_default


def test_named_inline_command_flagged():
    d = _lint(_HEAD + _fragment_markup(
        "Тип: ОбычнаяКоманда\nИмя: МояКоманда\nОбработчик: Обработчик"))
    assert len(d) == 1, [x.message for x in d]
    assert d[0].rule_id == RULE and d[0].severity is Severity.ERROR
    assert "'МояКоманда'" in d[0].message
    assert d[0].line == 11  # the `Name` line itself - the key to remove


@pytest.mark.parametrize("kind", ["ПереключаемаяКоманда", "КомандаСПараметром"])
def test_other_command_kinds_flagged(kind):
    d = _lint(_HEAD + _fragment_markup(f"Тип: {kind}\nИмя: К\nОбработчик: О"))
    assert len(d) == 1, [x.message for x in d]


def test_generic_command_type_flagged():
    # The generic head decides: an inline fragment of parametrized commands is the same case.
    d = _lint(_HEAD + _fragment_markup(
        "Тип: КомандаСПараметром<Строка>\nИмя: К\nОбработчик: О"))
    assert len(d) == 1, [x.message for x in d]


def test_unnamed_inline_command_silent():
    d = _lint(_HEAD + _fragment_markup(
        "Тип: ОбычнаяКоманда\nОбработчик: Обработчик\nПредставление: Кнопка"))
    assert d == [], [x.message for x in d]


def test_single_command_property_flagged():
    # Not only fragment children: a command standing as a property value is inline too.
    d = _lint(
        _HEAD
        + "Наследует:\n"
        + "    Тип: Страница\n"
        + "    ОсновнаяКоманда:\n"
        + "        Тип: ОбычнаяКоманда\n"
        + "        Имя: Главная\n"
        + "        Обработчик: Обработчик\n"
    )
    assert len(d) == 1, [x.message for x in d]


def test_fragment_project_element_silent():
    # In a fragment PROJECT ELEMENT the same key is the point - names are legal there.
    d = _lint(
        "ВидЭлемента: ФрагментКомандногоИнтерфейса\n"
        "Ид: 11111111-1111-1111-1111-111111111112\n"
        "Имя: Фрагмент\n"
        "Элементы:\n"
        "    -\n"
        "        Тип: ОбычнаяКоманда\n"
        "        Имя: ИменованнаяКоманда\n"
        "        Обработчик: Обработчик\n",
        name="Фрагмент.yaml",
    )
    assert d == [], [x.message for x in d]


def test_outside_markup_silent():
    # Outside `Inherits` a command spelling next to a `Name` is a declaration, not markup.
    d = _lint(
        _HEAD
        + "Реквизиты:\n"
        + "    -\n"
        + "        Имя: Команда\n"
        + "        Тип: ОбычнаяКоманда\n"
    )
    assert d == [], [x.message for x in d]


@pytest.mark.needs_data
def test_english_spellings_flagged():
    d = _lint(
        "ElementKind: КомпонентИнтерфейса\n"
        "Ид: 11111111-1111-1111-1111-111111111113\n"
        "Name: Form\n"
        "Inherits:\n"
        "    Type: Страница\n"
        "    ДополнительныеКоманды:\n"
        "        Type: CommandInterfaceFragment\n"
        "        Элементы:\n"
        "            -\n"
        "                Type: UsualCommand\n"
        "                Name: MyCommand\n",
        name="Form.yaml",
    )
    assert len(d) == 1, [x.message for x in d]
    assert "'MyCommand'" in d[0].message
