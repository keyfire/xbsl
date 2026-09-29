"""code/undefined-name: the spelling hint is the closest name of the whole scope.

The hint used to stop at the first group of names that had any candidate at all: the module's
own names first, then the element and the project, and the global names never. A module name
barely over the cutoff hid the attribute the typo was one letter away from, and a misspelled
global function got no hint at all. Now every group competes - the module, the element, the
project, the global names - the closest candidate wins, and a tie goes to the nearer group.

The position narrows the candidates: a call is offered what can be called, a bare name what holds
a value. A short name is offered only a candidate one edit away: across the whole scope a short
word almost always had a neighbour two edits off (`Close` got the function `Cos`).

The search is bounded so that the global names cost next to nothing, and the bounds never change
what difflib would pick: the last tests hold the two side by side.
"""

import difflib
import random

import pytest

from xbsl import engine
from xbsl.rules.undefined_names import _HINT_CUTOFF, _closest_in, _hint_table

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
    } | {"Сумма", "Суммы", "Итог", "Итоги", "ПолучитьЗначение", "Значение", "aaaa", "aaab"})
    table = _hint_table(names)
    words = _typos(rng.sample(names, 300), rng) + rng.sample(names, 50) + ["", "а", "zz"]
    for word in words:
        others = [n for n in names if n != word]
        expected = difflib.get_close_matches(word, others, n=1, cutoff=_HINT_CUTOFF)
        found = _closest_in(word, table)
        assert (found[1] if found else None) == (expected[0] if expected else None), word


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
