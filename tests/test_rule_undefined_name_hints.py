"""code/undefined-name: the spelling hint is the closest name of the whole scope.

The hint used to stop at the first group of names that had any candidate at all: the module's
own names first, then the element and the project, and the global names never. A module name
barely over the cutoff hid the attribute the typo was one letter away from, and a misspelled
global function got no hint at all. Now every group competes - the module, the element, the
project, the global names - the closest candidate wins, and a tie goes to the nearer group.

The position narrows the candidates: a call is offered what can be called, a bare name what holds
a value. A short name is offered only a candidate one edit away: across the whole scope a short
word almost always had a neighbour two edits off (`Close` got the function `Cos`).

A long name barely similar to a candidate is offered it only when the two differ by scattered
letters, the way a typo does, and not by a word (`Condition` got `ConditionString`).

The search is bounded so that the global names cost next to nothing, and the bounds never change
what difflib would pick among the candidates that pass: the last tests hold the two side by side.
"""

import difflib
import random

import pytest

from xbsl import engine
from xbsl.rules.undefined_names import (
    _HINT_CUTOFF,
    _TYPO_BAND,
    _closest_in,
    _hint_table,
    _typo_shaped,
)

_RULE = "code/undefined-name"

_FLIGHTS = """\
ВидЭлемента: Справочник
Ид: 1d1f5c60-0000-4000-8000-00000000e001
Имя: Рейсы
ОбластьВидимости: ВПроекте
Реквизиты:
    -
        Ид: 1d1f5c60-0000-4000-8000-00000000e002
        Имя: Пассажир
        Тип: Строка
    -
        Ид: 1d1f5c60-0000-4000-8000-00000000e003
        Имя: Багажи
        Тип: Строка
ТабличныеЧасти:
    -
        Ид: 1d1f5c60-0000-4000-8000-00000000e004
        Имя: Места
        Реквизиты:
            -
                Ид: 1d1f5c60-0000-4000-8000-00000000e005
                Имя: Ряд
                Тип: Число
"""


def _lint(files: dict[str, str]) -> list:
    sources = [engine.load_text(name, text) for name, text in files.items()]
    return [d for d in engine.run_sources(sources) if d.rule_id == _RULE]


def _hints(module: str, text: str) -> list[tuple[str, str | None]]:
    """(name, hint) of every finding; the hint is the second quoted word of a hint message."""
    out = []
    for d in _lint({"Рейсы.yaml": _FLIGHTS, module: text}):
        parts = d.message.split("'")
        hinted = "в виду" in d.message or "did you mean" in d.message
        out.append((parts[1], parts[3] if hinted else None))
    return out


@pytest.mark.needs_data
def test_an_attribute_closer_to_the_typo_beats_a_name_of_the_module():
    # The regression: the parameter `Пассажиры` of the module is close enough to pass the
    # cutoff, and the rule offered it without looking at the attribute one letter away.
    found = _hints("Рейсы.Объект.xbsl", (
        "@ВПроекте\nметод Список(Пассажиры: Массив<Строка>): Строка\n"
        "    возврат Пасажир\n;\n"
    ))
    assert found == [("Пасажир", "Пассажир")]


@pytest.mark.needs_data
def test_a_tie_goes_to_the_nearer_name():
    # `Багажа` of the module and the attribute `Багажи` are equally close; a plain difflib over
    # both would take the greater string, the attribute. The module is nearer.
    found = _hints("Рейсы.Объект.xbsl", (
        "@ВПроекте\nметод Список(Багажа: Строка): Строка\n    возврат Багажн\n;\n"
    ))
    assert found == [("Багажн", "Багажа")]


@pytest.mark.needs_data
def test_a_misspelled_global_name_is_offered_the_global_one():
    found = _hints("Рейсы.Объект.xbsl", '@ВПроекте\nметод Сказать()\n    Сообщть("х")\n;\n')
    assert found == [("Сообщть", "Сообщить")]


@pytest.mark.needs_data
def test_the_name_itself_is_no_hint():
    # Declared in another method, the local is out of reach; offering it back to the reader
    # ("did you mean 'Остаток'?") said nothing. The control is the name one letter away.
    text = (
        "@ВПроекте\nметод Первый(): Число\n    знч Остаток = 1\n    возврат Остаток\n;\n"
        "@ВПроекте\nметод Второй(): Число\n    возврат {name}\n;\n"
    )
    assert _hints("Рейсы.Объект.xbsl", text.format(name="Остаток")) == [("Остаток", None)]
    assert _hints("Рейсы.Объект.xbsl", text.format(name="Остатк")) == [("Остатк", "Остаток")]


@pytest.mark.needs_data
def test_a_method_of_the_row_type_is_offered_to_a_misspelled_call():
    found = _hints("Рейсы.Места.xbsl", (
        "@ВПроекте\nметод Текст(): Строка\n    возврат Представлени()\n;\n"
    ))
    assert found == [("Представлени", "Представление")]


@pytest.mark.needs_data
def test_offered_to_a_bare_name_the_method_comes_with_its_parentheses():
    # A bare name of a method is refused by the compiler, so the hint is the call to write.
    found = _hints("Рейсы.Места.xbsl", (
        "@ВПроекте\nметод Текст(): Строка\n    возврат Представлени\n;\n"
    ))
    assert found == [("Представлени", "Представление()")]


@pytest.mark.needs_data
def test_a_call_is_not_offered_a_value():
    text = (
        "@ВПроекте\nметод Сводка(): Строка\n    знч Заголовок = \"х\"\n"
        "    возврат {expr}\n;\n"
    )
    assert _hints("Рейсы.Объект.xbsl", text.format(expr="Заголовк()")) == [("Заголовк", None)]
    # The control: the same name bare is offered the variable.
    assert _hints("Рейсы.Объект.xbsl", text.format(expr="Заголовк")) == [
        ("Заголовк", "Заголовок")]


@pytest.mark.needs_data
def test_a_bare_name_is_not_offered_a_method_of_the_module():
    text = (
        "@ВПроекте\nметод Пересчитать(): Число\n    возврат 1\n;\n"
        "@ВПроекте\nметод Сводка(): Число\n    возврат {expr}\n;\n"
    )
    assert _hints("Рейсы.Объект.xbsl", text.format(expr="Пересчитат")) == [("Пересчитат", None)]
    assert _hints("Рейсы.Объект.xbsl", text.format(expr="Пересчитат()")) == [
        ("Пересчитат", "Пересчитать")]


@pytest.mark.needs_data
def test_a_value_that_holds_a_function_is_offered_to_a_call():
    found = _hints("Рейсы.Объект.xbsl", (
        "@ВПроекте\nметод Проверить(Условие: (Строка)->Булево): Булево\n"
        "    возврат Услвие(\"х\")\n;\n"
    ))
    assert found == [("Услвие", "Условие")]


@pytest.mark.needs_data
def test_a_method_and_a_variable_of_one_name_serve_both_positions():
    # The method returns what its callers keep under the same name.
    text = (
        "@ВПроекте\nметод Контракт(): Строка\n    возврат \"х\"\n;\n"
        "@ВПроекте\nметод Сводка(): Строка\n    знч Контракт = Контракт()\n"
        "    возврат {expr}\n;\n"
    )
    assert _hints("Рейсы.Объект.xbsl", text.format(expr="Контрак")) == [("Контрак", "Контракт")]
    assert _hints("Рейсы.Объект.xbsl", text.format(expr="Контрак()")) == [
        ("Контрак", "Контракт")]


@pytest.mark.needs_data
def test_a_short_name_is_offered_only_a_candidate_one_edit_away():
    # `Close` and the global function `Cos` score exactly the cutoff: two letters apart.
    call = '@ВПроекте\nметод Сводка()\n    {expr}("х")\n;\n'
    assert _hints("Рейсы.Объект.xbsl", call.format(expr="Close")) == [("Close", None)]
    assert _hints("Рейсы.Объект.xbsl", call.format(expr="Coss")) == [("Coss", "Cos")]
    # The same for a variable of the module; one swapped pair is still a single typo.
    bare = (
        "@ВПроекте\nметод Сводка(): Строка\n    знч Подписка = \"х\"\n    знч Итог = \"у\"\n"
        "    возврат {expr}\n;\n"
    )
    assert _hints("Рейсы.Объект.xbsl", bare.format(expr="Поиск")) == [("Поиск", None)]
    assert _hints("Рейсы.Объект.xbsl", bare.format(expr="Подпска")) == [("Подпска", "Подписка")]
    assert _hints("Рейсы.Объект.xbsl", bare.format(expr="Итго")) == [("Итго", "Итог")]


@pytest.mark.needs_data
def test_a_long_name_is_not_offered_a_name_a_word_away():
    # `ДатаРейса` and the local score exactly the cutoff, and what tells them apart is the whole
    # word `Начала`, not a typo: the distribution's own modules got hints like `Condition` ->
    # `ConditionString` this way. The control is a letter dropped from the same local.
    text = (
        "@ВПроекте\nметод Сводка(): Число\n    знч ДатаНачалаРейса = 1\n"
        "    возврат {expr}\n;\n"
    )
    assert _hints("Рейсы.Объект.xbsl", text.format(expr="ДатаРейса")) == [("ДатаРейса", None)]
    assert _hints("Рейсы.Объект.xbsl", text.format(expr="ДатаНачлаРейса")) == [
        ("ДатаНачлаРейса", "ДатаНачалаРейса")]


@pytest.mark.needs_data
def test_two_changed_letters_of_a_long_name_are_still_a_typo():
    # Two letters of an eight-letter name changed score the very same cutoff, and they are a
    # typo: the letters lie apart, so the name is still offered.
    text = "@ВПроекте\nметод Сводка(): Число\n    знч Перелеты = 1\n    возврат Пкрелетя\n;\n"
    assert _hints("Рейсы.Объект.xbsl", text) == [("Пкрелетя", "Перелеты")]


def test_a_typo_is_told_from_a_word_by_the_runs_left_unmatched():
    def shaped(candidate: str, name: str) -> bool:
        return _typo_shaped(difflib.SequenceMatcher(None, candidate, name))

    assert shaped("Перелеты", "Пкрелетя")  # two letters apart
    assert shaped("ДатаНачалаРейса", "ДатаНачлаРейса")  # one letter dropped
    assert not shaped("ДатаНачалаРейса", "ДатаРейса")  # a word dropped
    assert not shaped("ConditionString", "Condition")  # a word added at the end


def _typos(names: list[str], rng: random.Random) -> list[str]:
    out = []
    for name in names:
        i = rng.randrange(len(name))
        kind = rng.randrange(3)
        if kind == 0 and len(name) > 1:
            out.append(name[:i] + name[i + 1:])
        elif kind == 1:
            out.append(name[:i] + rng.choice(name) + name[i:])
        else:
            out.append(name[:i] + rng.choice("аеиоуxyzЫ") + name[i + 1:])
    return out


def test_the_bounded_search_picks_what_difflib_picks():
    """Needs no data: the search is plain string work.

    The candidates mix both alphabets, repeated letters and the lengths around the cutoff,
    where the bounds decide; the typos are taken from the candidates themselves so that most
    lookups have an answer to agree on.
    """
    rng = random.Random(20260929)
    letters = "абвгдежзиклмнопрстуфхцшщыэюяABCDEFGHabcdefghxyz_0"
    names = sorted({
        "".join(rng.choice(letters) for _ in range(rng.randint(1, 16))) for _ in range(600)
    } | {"Сумма", "Суммы", "Итог", "Итоги", "ПолучитьЗначение", "Значение", "aaaa", "aaab",
         "ДатаНачалаРейса", "Перелеты"})
    table = _hint_table(names)
    words = _typos(rng.sample(names, 300), rng) + rng.sample(names, 50) + ["", "а", "zz"]
    # The typo band from both sides: a word away (difflib alone would offer the date) and two
    # letters changed (a typo, offered all the same).
    words += ["ДатаРейса", "КлючИЗначение", "Пкрелетя"]
    for word in words:
        others = [n for n in names if n != word]
        # difflib's own pick, less the candidates of the typo band that differ by a word: the
        # check is made on every candidate, so the answer is the best of those that pass it.
        passing = [(score, n) for n in others
                   if (score := difflib.SequenceMatcher(None, n, word).ratio()) >= _HINT_CUTOFF
                   and (score >= _TYPO_BAND
                        or _typo_shaped(difflib.SequenceMatcher(None, n, word)))]
        expected = max(passing)[1] if passing else None
        found = _closest_in(word, table)
        assert (found[1] if found else None) == expected, word


def _one_edit(word: str, candidate: str) -> bool:
    matcher = difflib.SequenceMatcher(None, candidate, word)
    matched = sum(block.size for block in matcher.get_matching_blocks())
    return matched >= max(len(word), len(candidate)) - 1


def test_the_bounded_search_for_one_edit_picks_what_difflib_picks():
    """The same agreement when only a candidate one edit away counts.

    The check is made on every candidate rather than on the winner, so the expected answer is
    the best of those that pass it - a candidate two edits away may well score higher.
    """
    rng = random.Random(20260930)
    letters = "абвгдежзиклмнопрстуABCDEFabcdefxyz_0"
    names = sorted({
        "".join(rng.choice(letters) for _ in range(rng.randint(1, 9))) for _ in range(600)
    } | {"Итог", "Итоги", "Итого", "Cos", "Close", "Подписка", "Поиск", "Код", "Кодекс"})
    table = _hint_table(names)
    words = _typos(rng.sample(names, 300), rng) + ["Close", "Поиск", "Итго", "Кодд", "", "а"]
    for word in words:
        scored = [(difflib.SequenceMatcher(None, n, word).ratio(), n) for n in names if n != word]
        passing = [(s, n) for s, n in scored if s >= _HINT_CUTOFF and _one_edit(word, n)]
        expected = max(passing)[1] if passing else None
        found = _closest_in(word, table, one_edit=True)
        assert (found[1] if found else None) == expected, word
