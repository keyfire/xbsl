"""What the translate pass says about the DICTIONARY itself - two build breakers a coverage
number never shows.

An entry may spell a platform member as the platform spells it nowhere (`Важность: Severity`
against the event's `Importance`): where the receiver's type is known the platform wins and
the tree is right, but a receiver of no inferred type gets the entry's word, and the compiler
refuses it. A named literal may carry other substitutions than its key (`%{AccountCode}` for
a field that translates to `SubscriberCode`): the variable does not exist, or the event has
no such field. A real project lost its English build to both within one week while
`--strict` passed it with full coverage. Both are problems now, so the strict gate fails.

The receiver of the first case is typed by INFERENCE through a static call of a platform type
(`ЖурналСобытий.Найти(...)`, the search result, the event read off it) - the exact shape of
the live case, pinned here so the walk keeps reading type names in initializers.
"""

from pathlib import Path

import pytest

from xbsl import engine
from xbsl.translation import cli
from xbsl.translation import dictionary as dm
from xbsl.translation.code import Resolver, translate_code
from xbsl.translation.reporting import FileReport
from xbsl.translation.yamlfile import translate_yaml

pytestmark = pytest.mark.needs_data

_EVENT_MODULE = (
    "метод Проба(Запрос: Строка)\n"
    "    исп Поиск = ЖурналСобытий.Найти(ДатаНачала = Запрос)\n"
    "    пока Поиск.Следующий()\n"
    "        знч Событие = Поиск.Событие\n"
    "        знч Строка = новый Данные(Важность = Событие.Важность.ВСтроку(),"
    " Успешно = Событие.Успешно)\n"
    "    ;\n"
    ";\n"
)
_TOKENS = {"Проба": "Probe", "Данные": "Data", "Запрос": "Query"}


def _translate(text: str, tokens: dict, literals: dict | None = None, name: str = "Проба.xbsl"):
    source = engine.load_text(name, text)
    report = FileReport(path=name)
    dictionary = dm.Dictionary(tokens=dict(tokens), literals=dict(literals or {}))
    translate = translate_yaml if name.endswith(".yaml") else translate_code
    return translate(source, Resolver(dictionary), report), report


def test_an_entry_the_platform_overrules_at_a_typed_receiver_is_reported():
    out, report = _translate(
        _EVENT_MODULE, {**_TOKENS, "Важность": "Severity", "Успешно": "Succeeded"})
    # The platform wins where the receiver's type is known - inferred through the static call.
    assert "Event.Importance" in out and "Event.Succeed" in out
    assert set(report.shadows) == {"Важность", "Успешно"}
    _line, _col, entry, platform, owner = report.shadows["Важность"][0]
    assert (entry, platform, owner) == ("Severity", "Importance", "СобытиеЖурналаСобытий")
    assert report.shadows["Успешно"][0][2:4] == ("Succeeded", "Succeed")


def test_an_entry_spelled_as_the_platform_spells_it_passes():
    out, report = _translate(
        _EVENT_MODULE, {**_TOKENS, "Важность": "Importance", "Успешно": "Succeed"})
    assert "Event.Importance" in out and not report.shadows


def test_a_word_the_platform_spells_two_ways_is_not_judged():
    """`Загрузить` is Load on a binary object and Upload on the object storage: an entry
    matching either spelling names nothing wrong, so there is no one spelling to ask for."""
    out, report = _translate(
        "метод Проба(Хранилище: ОбъектноеХранилище, Данные: ДвоичныйОбъект)\n"
        "    Хранилище.Загрузить(Данные)\n"
        ";\n",
        {"Проба": "Probe", "Хранилище": "Storage", "Данные": "Data", "Загрузить": "Load"},
    )
    assert "Storage.Upload(Data)" in out
    assert not report.shadows


def test_a_literal_translated_with_other_substitutions_than_its_key_is_reported():
    text = 'метод Проба(Причина: Строка): Строка\n    возврат "Отказ: %{Причина}"\n;\n'
    out, report = _translate(
        text, {"Проба": "Probe", "Причина": "Reason"},
        literals={"Отказ: %{Причина}": "Refused: %{Cause}"},
    )
    assert '"Refused: %{Cause}"' in out  # the entry is applied as written - and reported
    assert [(t, e, f) for t, _l, _c, e, f in report.placeholder_mismatches] == [
        ("Отказ: %{Причина}", ["Reason"], ["Cause"]),
    ]


@pytest.mark.parametrize("value", ["Refused: %{Причина}", "Refused: %{Reason}"])
def test_substitutions_written_in_either_language_agree(value: str):
    """The entry may keep the source name (the pass translates it) or spell the translation."""
    text = 'метод Проба(Причина: Строка): Строка\n    возврат "Отказ: %{Причина}"\n;\n'
    out, report = _translate(
        text, {"Проба": "Probe", "Причина": "Reason"}, literals={"Отказ: %{Причина}": value})
    assert '"Refused: %{Reason}"' in out
    assert not report.placeholder_mismatches


def test_a_presentation_template_is_judged_the_same_way():
    text = (
        "ВидЭлемента: СобытиеЖурналаСобытий\n"
        "Ид: 1d1f5c60-0000-4000-8000-0000000000e1\n"
        "Имя: Отказ\n"
        'ШаблонПредставления: "Отказ: %{Причина}"\n'
        "Свойства:\n"
        "    -\n"
        "        Ид: 1d1f5c60-0000-4000-8000-0000000000e2\n"
        "        Имя: Причина\n"
        "        Тип: Строка\n"
    )
    _out, report = _translate(
        text, {"Отказ": "Refusal", "Причина": "Reason"},
        literals={"Отказ: %{Причина}": "Refused: %{Cause}"}, name="Отказ.yaml",
    )
    assert [(e, f) for _t, _l, _c, e, f in report.placeholder_mismatches] == [(["Reason"], ["Cause"])]


def _project(tmp_path: Path, dictionary: str) -> tuple[Path, Path]:
    root = tmp_path / "Acme" / "Demo"
    root.mkdir(parents=True)
    (root / "Проба.xbsl").write_text(
        "метод Проба(Событие: СобытиеЖурналаСобытий, Причина: Строка): Строка\n"
        "    знч Level = Событие.Важность\n"
        '    возврат "Отказ: %{Причина}"\n'
        ";\n",
        encoding="utf-8",
    )
    path = tmp_path / "dictionary.yaml"
    path.write_text(dictionary, encoding="utf-8")
    return root, path


_HEAD = "version: 1\nlanguage: en\ntokens:\n    Проба: Probe\n    Причина: Reason\n    Событие: Event\n"


def test_both_defects_fail_the_strict_gate_and_are_named(tmp_path: Path, capsys):
    root, dictionary = _project(
        tmp_path, _HEAD + '    Важность: Severity\nliterals:\n    "Отказ: %{Причина}": "Refused: %{Cause}"\n')
    code = cli.cli_main([str(root), "--dictionary", str(dictionary), "--strict", "--lang", "ru"])
    out = capsys.readouterr().out
    assert code == 1
    assert "'Важность: Severity'" in out and "'Importance'" in out
    assert "[Cause]" in out and "[Reason]" in out
    assert out.rstrip("\n").splitlines()[-1].startswith("НЕ ГОТОВО")


def test_the_same_project_with_a_sound_dictionary_is_ready(tmp_path: Path, capsys):
    root, dictionary = _project(
        tmp_path, _HEAD + '    Важность: Importance\nliterals:\n    "Отказ: %{Причина}": "Refused: %{Причина}"\n')
    code = cli.cli_main([str(root), "--dictionary", str(dictionary), "--strict", "--lang", "ru"])
    assert code == 0
    assert capsys.readouterr().out.rstrip("\n").splitlines()[-1] == "ГОТОВО"
