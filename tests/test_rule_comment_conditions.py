"""`comment/dash-condition`: a condition written with a dash instead of a word of condition.

The comments of an element description and of a resource file are found without Element data -
the yaml composer and the resource scanner cut them out - so most tests here run in a public
checkout. A module is read by the lexer, which takes its words from the dataset: those tests are
marked `needs_data`.
"""

import pytest

from xbsl import engine, i18n
from xbsl.cli import discover
from xbsl.rules import comment_conditions

RULE = "comment/dash-condition"

_HEAD = "ВидЭлемента: Справочник\nИмя: Склады\n"


def _yaml(comment_lines: str, body: str = ""):
    """Lint an element description whose comments are `comment_lines`."""
    text = comment_lines + _HEAD + body
    return engine.run_sources([engine.load_text("Склады.yaml", text)], select={RULE})


def _lint(name: str, text: str):
    return engine.run_sources([engine.load_text(name, text)], select={RULE})


def _info():
    return next(r for r in engine.RULES if r.id == RULE)


# --- the rule as a whole ------------------------------------------------------------------------

def test_dash_condition_is_a_warning_a_project_turns_on():
    info = _info()

    assert info.severity.value == "warning"
    assert info.enabled_by_default is False
    assert info.tier == "B" and info.scope == "file"
    assert "--enable comment" in info.off_reason_text


def test_dash_condition_speaks_english_without_cyrillic_outside_quotes():
    i18n.set_lang("en")
    try:
        texts = [
            i18n.t(key, left="w", suggestion="s")
            for key in i18n.registered_keys() if key.startswith(RULE + ".")
        ]
    finally:
        i18n.set_lang("ru")
    assert texts
    for text in texts:
        bare = [part for index, part in enumerate(text.split('"')) if index % 2 == 0]
        assert not any("а" <= ch.lower() <= "я" for part in bare for ch in part), text


# --- what is reported ---------------------------------------------------------------------------

def test_dash_condition_in_a_yaml_comment_is_reported_with_the_wording():
    (diag,) = _yaml("# Склад не задан - берется основной склад.\n")

    assert (diag.rule_id, diag.line, diag.col) == (RULE, 1, 3)
    assert '"Склад не задан - ..."' in diag.message
    assert '"Если склад не задан, берется основной склад."' in diag.message
    assert diag.fix is None


def test_dash_condition_after_a_colon_goes_on_in_lower_case():
    (diag,) = _yaml("# Повтор безопасен: партия с таким кодом уже есть - она не создается.\n")

    assert diag.col == 21
    assert '"если партия с таким кодом уже есть, она не создается."' in diag.message


def test_dash_condition_keeps_a_name_from_the_code_as_it_is():
    (diag,) = _yaml("# КодСклада пуст - остаток берется из партии.\n")

    assert '"Если КодСклада пуст, остаток берется из партии."' in diag.message


def test_dash_condition_spanning_two_comment_lines_is_one_sentence():
    (diag,) = _yaml("# Склад\n# не задан - остаток не считается.\n")

    assert (diag.line, diag.col) == (1, 3)


@pytest.mark.parametrize("dash", ("-", "\u2013", "\u2014"))
def test_dash_condition_takes_every_kind_of_dash(dash):
    assert len(_yaml(f"# Склад не задан {dash} берется основной склад.\n")) == 1


@pytest.mark.parametrize("consequence", (
    "берется основной склад",
    "остаток заполняет загрузка",
    "партии пересчитываются",
    "запись создавалась заново",
    "остатка нет",
    "создание, иначе замена найденной записи",
))
def test_dash_condition_consequence_with_a_verb_or_a_predicate(consequence):
    assert len(_yaml(f"# Склад не задан - {consequence}.\n")) == 1


@pytest.mark.parametrize("state", (
    "не задан", "пуст", "не найден", "отсутствует", "не указан", "не заполнен", "истек",
    "равен", "больше", "не совпадает", "изменился", "пришел", "готов",
    "есть",
))
def test_dash_condition_states_of_the_left_part(state):
    assert len(_yaml(f"# Остаток склада {state} - партия пересчитывается.\n")) == 1


def test_dash_condition_in_a_list_item():
    comments = (
        "# Режимы:\n"
        "# - склад не задан - берется основной;\n"
        "# - склад задан - берется он.\n"
    )

    diags = _yaml(comments)

    assert [(d.line, d.col) for d in diags] == [(2, 5), (3, 5)]


def test_dash_condition_in_a_resource_comment():
    text = "/* Склад не задан - берется основной склад. */\n.склад { color: red; }\n"

    diags = _lint("Ресурсы/склад.css", text)

    assert [(d.line, d.col) for d in diags] == [(1, 4)]


def test_dash_condition_through_the_cli_discovery(tmp_path):
    folder = tmp_path / "Склады"
    folder.mkdir()
    path = folder / "Склады.yaml"
    # Bytes, not write_text: on Windows the text mode turns a line break into CRLF.
    path.write_bytes(("# Склад не задан - берется основной склад.\n" + _HEAD).encode("utf-8"))

    diags = engine.run(discover([str(tmp_path)]), select={RULE})

    assert [(d.rule_id, d.line) for d in diags] == [(RULE, 1)]


# --- what is left alone -------------------------------------------------------------------------

@pytest.mark.parametrize("comment", (
    "# Пусто - вид свободен.",
    "# Код не задан - склад свободен.",
    "# Код не задан - проверить остаток.",
    "# Флажок снят - склад занят.",
))
def test_dash_legend_without_a_verb_is_left_alone(comment):
    assert _yaml(comment + "\n") == []


@pytest.mark.parametrize("comment", (
    "# Не задан - берется основной склад.",
    "# Пусто - остаток не считается.",
    "# Снят - раздела нет.",
))
def test_dash_legend_of_a_value_without_a_subject_is_left_alone(comment):
    assert _yaml(comment + "\n") == []


def test_dash_absence_counts_only_with_the_other_branch():
    assert _yaml("# У склада адреса нет - строка идет без ссылки.\n") == []
    assert len(_yaml("# Адреса нет - строка без ссылки, иначе ссылка на карточку.\n")) == 1


@pytest.mark.parametrize("comment", (
    "# Если склад не задан - берется основной.",
    "# Когда склад не задан - берется основной.",
    "# В остальных случаях склад не задан - берется основной.",
    "# Код склада всегда есть - берется из настройки.",
    "# Код склада тоже есть - берется из настройки.",
))
def test_dash_in_a_sentence_that_is_conditional_or_a_fact_is_left_alone(comment):
    assert _yaml(comment + "\n") == []


@pytest.mark.parametrize("comment", (
    "# Автонумерация отключена - код задает загрузка.",
    "# Нумерация выключена - код пишется вручную.",
    "# Нумерация включена - код назначает платформа.",
))
def test_dash_after_a_switch_describes_a_setting(comment):
    assert _yaml(comment + "\n") == []


@pytest.mark.parametrize("comment", (
    "# Код основного склада первой партии прошлого года не задан - берется основной.",
    '# Поле "Код" не задано - берется основной склад.',
    "# Ничего не выбрано - вариант 1 = первый склад.",
    "# Склад - это место хранения, код не задан.",
))
def test_dash_long_quoted_or_encoded_parts_are_left_alone(comment):
    assert _yaml(comment + "\n") == []


def test_dash_in_a_yaml_value_is_not_a_comment():
    body = 'Описание: "Склад не задан - берется основной склад"\n'

    assert _yaml("", body) == []


def test_dash_trailing_yaml_comment_does_not_join_the_next_line():
    text = "ВидЭлемента: Справочник # Склад\n# не задан - берется основной склад.\nИмя: Склады\n"

    assert engine.run_sources([engine.load_text("Склады.yaml", text)], select={RULE}) == []


# --- the judgement of one sentence --------------------------------------------------------------

@pytest.mark.parametrize(("sentence", "left"), (
    ("Склад не задан - берется основной.", "Склад не задан"),
    ("1. Остаток пуст - партия закрывается.", "Остаток пуст"),
    ("(Склад не найден - берется основной.)", "Склад не найден"),
    ("Остаток пуст, - партия закрывается.", "Остаток пуст"),
))
def test_judge_returns_the_left_part(sentence, left):
    verdict = comment_conditions.judge(sentence)

    assert verdict is not None and verdict[0] == left
    assert sentence[verdict[2]:].startswith(left)


@pytest.mark.parametrize("sentence", (
    "Склад не задан, берется основной.",
    "Склад не задан-берется основной.",
    "Остатки проверяются и склад не задан - берется основной.",
))
def test_judge_rejects_sentences_of_another_shape(sentence):
    assert comment_conditions.judge(sentence) is None


# --- a module -----------------------------------------------------------------------------------

@pytest.mark.needs_data
def test_dash_condition_in_a_module_comment():
    text = "// Склад не задан - берется основной склад.\nметод Пересчитать()\n;\n"

    diags = _lint("Склады.xbsl", text)

    assert [(d.line, d.col) for d in diags] == [(1, 4)]


@pytest.mark.needs_data
def test_dash_condition_block_comment_of_a_module_is_one_paragraph():
    text = "/* Склад\n * не задан - берется основной склад.\n */\nметод Пересчитать()\n;\n"

    diags = _lint("Склады.xbsl", text)

    assert [(d.line, d.col) for d in diags] == [(1, 4)]


@pytest.mark.needs_data
def test_dash_condition_comment_after_code_stands_alone():
    text = "пер Код = 1 // Склад\n// не задан - берется основной склад.\n"

    assert _lint("Склады.xbsl", text) == []
