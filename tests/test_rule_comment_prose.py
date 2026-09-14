"""The `comment/` group: the subjunctive, the first person and emphasis in capitals.

A comment of an element description and a comment of a resource file need no Element data -
the first is cut out with the yaml composer, the second with the resource scanner - so most of
the tests here run in a public checkout. A module is read by the lexer, which takes its words
from the dataset: those tests are marked `needs_data`.
"""

import pytest

from xbsl import engine, fixer, i18n
from xbsl.cli import discover
from xbsl.rules import _comments

SUBJUNCTIVE = "comment/subjunctive"
FIRST_PERSON = "comment/first-person"
CAPS = "comment/emphasis-caps"

_HEAD = "ВидЭлемента: Справочник\nИмя: Склады\n"


def _yaml(comment_lines: str, rule: str, body: str = ""):
    """Lint an element description whose comments are `comment_lines`."""
    text = comment_lines + _HEAD + body
    return engine.run_sources([engine.load_text("Склады.yaml", text)], select={rule})


def _lint(name: str, text: str, rule: str):
    return engine.run_sources([engine.load_text(name, text)], select={rule})


def _write(tmp_path, name: str, text: str):
    path = tmp_path / name
    path.parent.mkdir(parents=True, exist_ok=True)
    # Bytes, not write_text: on Windows the text mode turns a line break into CRLF, and the
    # offsets of a fix would then be measured against a different text.
    path.write_bytes(text.encode("utf-8"))
    return path


def _info(rule_id: str):
    return next(r for r in engine.RULES if r.id == rule_id)


# --- the group as a whole ---------------------------------------------------------------------

@pytest.mark.parametrize("rule_id", (SUBJUNCTIVE, FIRST_PERSON, CAPS))
def test_comment_rules_are_warnings_that_a_project_turns_on(rule_id):
    info = _info(rule_id)

    assert info.severity.value == "warning"
    assert info.enabled_by_default is False
    assert info.tier == "B" and info.scope == "file"
    assert "--enable comment" in info.off_reason_text


@pytest.mark.parametrize("rule_id", (SUBJUNCTIVE, FIRST_PERSON, CAPS))
def test_comment_rules_speak_english_without_cyrillic_outside_quotes(rule_id):
    i18n.set_lang("en")
    try:
        texts = [
            i18n.t(key, word="w", suggestion="s")
            for key in i18n.registered_keys() if key.startswith(rule_id + ".")
        ]
    finally:
        i18n.set_lang("ru")
    assert texts
    for text in texts:
        bare = [part for index, part in enumerate(text.split('"')) if index % 2 == 0]
        assert not any("а" <= ch.lower() <= "я" for part in bare for ch in part), text


# --- where the comments are -------------------------------------------------------------------

def test_yaml_comment_lines_skip_the_hash_inside_values():
    text = (
        "# описание склада\n"
        "ВидЭлемента: Справочник\n"
        "Имя: Склады # хвост строки\n"
        "Описание: \"значение # не комментарий\"\n"
        "Текст: |\n"
        "    # строка блочного значения\n"
        "Код: а#б\n"
    )
    found = _comments.lines(engine.load_text("Склады.yaml", text))

    assert [(c.line, c.text) for c in found] == [(1, "# описание склада"), (3, "# хвост строки")]


def test_yaml_comment_line_offsets_point_at_the_hash():
    text = "Имя: Склады  # пометка\n"
    source = engine.load_text("Склады.yaml", text)

    (found,) = _comments.lines(source)

    assert (found.line, found.column) == (1, 14)
    assert text[found.offset:found.offset + 3] == "# п"


def test_a_yaml_of_comments_alone_still_has_comments():
    found = _comments.lines(engine.load_text("Склады.yaml", "# первая\n# вторая\n"))

    assert [c.line for c in found] == [1, 2]


def test_a_broken_yaml_gives_no_comments():
    found = _comments.lines(engine.load_text("Склады.yaml", "# пометка\nИмя: [незакрытый\n"))

    assert found == []


# --- comment/subjunctive ------------------------------------------------------------------------

def test_subjunctive_particle_in_a_yaml_comment_is_reported():
    diags = _yaml("# без индекса поиск читал бы всю таблицу\n", SUBJUNCTIVE)

    assert [(d.rule_id, d.line, d.col) for d in diags] == [(SUBJUNCTIVE, 1, 27)]
    assert diags[0].fix is None


def test_subjunctive_message_asks_for_a_word_of_condition():
    (diag,) = _yaml("# запись стёрла бы остаток\n", SUBJUNCTIVE)

    assert "если" in diag.message and "иначе" in diag.message
    assert "снять частицу нельзя" in diag.message


@pytest.mark.parametrize("comment", (
    "# достаточно хотя бы одной записи",
    "# что бы ни пришло в ответе, остаток сохраняется",
    "# каким бы путём ни пришла запись, код заполняется",
    "# как бы то ни было, склад остаётся",
    "# сколько бы их ни было, колонки равной ширины",
    "# будто бы пустое поле",
    "# лишь бы список не пустел",
))
def test_subjunctive_fixed_and_concessive_turns_are_left_alone(comment):
    assert _yaml(comment + "\n", SUBJUNCTIVE) == []


def test_subjunctive_concessive_turn_may_end_on_the_next_line():
    comments = "# инвариант держит модуль объекта, каким бы путём\n# ни пришла запись\n"

    assert _yaml(comments, SUBJUNCTIVE) == []


def test_subjunctive_turn_of_the_line_above_is_read_too():
    comments = "# хотя\n# бы одна запись\n"

    assert _yaml(comments, SUBJUNCTIVE) == []


def test_subjunctive_misspelled_conjunction_is_not_the_mood():
    assert _yaml("# метод нужен для того, что бы список не мерцал\n", SUBJUNCTIVE) == []


def test_subjunctive_inside_quotes_and_in_values_is_not_judged():
    body = "Описание: склад закрылся бы\n"

    assert _yaml("# подпись \"закрылся бы\" показывается как есть\n", SUBJUNCTIVE, body) == []


def test_subjunctive_in_a_resource_comment_but_not_in_a_script_string():
    text = "// иначе окно закрывалось бы сразу\nvar note = 'закрылось бы';\n"

    diags = _lint("Ресурсы/окно.js", text, SUBJUNCTIVE)

    assert [d.line for d in diags] == [1]


@pytest.mark.needs_data
def test_subjunctive_in_a_module_comment():
    text = "// пересчёт шёл бы на каждой записи\nметод Пересчитать()\n;\n"

    diags = _lint("Склады.xbsl", text, SUBJUNCTIVE)

    assert [(d.line, d.col) for d in diags] == [(1, 17)]


# --- comment/first-person -----------------------------------------------------------------------

@pytest.mark.parametrize(("comment", "word"), (
    ("# здесь мы видим остаток", "мы"),
    ("# наши колонки уже на месте", "наши"),
    ("# остаток проверяем до записи", "проверяем"),
    ("# список обновляем целиком", "обновляем"),
    ("# к сервису обращаемся один раз", "обращаемся"),
    ("# код берём из настройки", "берём"),
    ("# код берем из настройки", "берем"),
    ("# данные тащим пачкой", "тащим"),
    ("# запись валим с отказом", "валим"),
    ("# потом переведём строку", "переведём"),
))
def test_first_person_is_reported(comment, word):
    diags = _yaml(comment + "\n", FIRST_PERSON)

    assert len(diags) == 1, [d.message for d in diags]
    assert f'"{word}"' in diags[0].message


def test_first_person_pronoun_and_verb_have_their_own_wording():
    pronoun, verb = _yaml("# наш склад\n# склад закрываем\n", FIRST_PERSON)

    assert "Местоимение" in pronoun.message
    assert "Глагол" in verb.message


@pytest.mark.parametrize("comment", (
    "# склад заполняет свой список",
    "# остаток задан полем и значением по умолчанию",
    "# режим одним вызовом с внешним ключом",
    "# колонка прижата краем, в этом случае без отступа",
    "# отбор видим только администратору, способ применим к любой таблице",
    "# программа в раскрывающемся списке карточки",
    "# отказ приходит с завершившимся заданием",
    "# при заполнении в открывшемся окне",
    "# тёмный фон нечитаем, отклик предсказуем заранее",
    "# подпись \"обновляем\" и имя `ОбновляемСписок` - данные",
))
def test_first_person_leaves_nouns_adjectives_and_participles_alone(comment):
    assert _yaml(comment + "\n", FIRST_PERSON) == []


@pytest.mark.needs_data
def test_first_person_in_a_trailing_module_comment():
    text = "метод Собрать()\n    пер Вид = 1 // какой список собираем сейчас\n;\n"

    diags = _lint("Склады.xbsl", text, FIRST_PERSON)

    assert [(d.line, d.col) for d in diags] == [(2, 33)]


def test_first_person_in_a_stylesheet_comment():
    diags = _lint("Ресурсы/склад.css", "/* наши отступы снимаются */\n.a { margin: 0; }\n",
                  FIRST_PERSON)

    assert [d.line for d in diags] == [1]


# --- comment/emphasis-caps ----------------------------------------------------------------------

def _fixed(tmp_path, text: str):
    """Run the rule over a file on disk and apply its fixes to the text of the file."""
    path = _write(tmp_path, "Склады.yaml", text)
    diags = engine.run(discover([str(tmp_path)]), select={CAPS})
    return diags, fixer.fix_source(engine.load(path), diags).text


def test_emphasis_caps_word_inside_a_sentence_is_lowered(tmp_path):
    diags, text = _fixed(tmp_path, "# склад НЕ закрывается\n" + _HEAD)

    assert [(d.line, d.col) for d in diags] == [(1, 9)]
    assert "\"не\"" in diags[0].message
    assert text.startswith("# склад не закрывается\n")


def test_emphasis_caps_word_opening_a_sentence_keeps_a_capital(tmp_path):
    _diags, text = _fixed(tmp_path, "# ТОЛЬКО чтение. ВСЕ склады видны\n" + _HEAD)

    assert text.startswith("# Только чтение. Все склады видны\n")


def test_emphasis_caps_continuation_line_is_lowered(tmp_path):
    comments = "# остаток пересчитывается\n# ДО записи документа.\n# ДО записи - так проще\n"

    _diags, text = _fixed(tmp_path, comments + _HEAD)

    assert text.startswith(
        "# остаток пересчитывается\n# до записи документа.\n# До записи - так проще\n"
    )


def test_emphasis_caps_fix_lands_on_the_file_with_crlf(tmp_path):
    source_text = "# первая строка\r\n# склад ОДИН на всех\r\n" + _HEAD.replace("\n", "\r\n")
    path = _write(tmp_path, "Склады.yaml", source_text)

    diags = engine.run(discover([str(tmp_path)]), select={CAPS})

    written = path.read_bytes().decode("utf-8")
    assert [written[d.fix.start:d.fix.end] for d in diags] == ["ОДИН"]


@pytest.mark.parametrize("comment", (
    "# строки ТЧ и таблица СУБД",
    "# ответ в JSON, запрос в SQL",
    "# СКЛАД ЗАКРЫТ НА ПЕРЕУЧЁТ",
    "# условие ГДЕ НЕ Удалён",
    "# подпись \"НЕ ТРОГАТЬ\" показывается как есть",
    "# константа НОВАЯ_СТРОКА",
))
def test_emphasis_caps_leaves_abbreviations_citations_and_shouted_lines_alone(comment):
    assert _yaml(comment + "\n", CAPS) == []


def test_emphasis_caps_phrase_of_ordinary_words_is_fixed_word_by_word():
    """Every word of the phrase is judged now, so none of them is left shouting."""
    diags = _yaml("# остаток читается ПОД ПРАВАМИ ПОЛЬЗОВАТЕЛЯ\n", CAPS)

    assert [(d.col, d.fix.new) for d in diags] == [(20, "под"), (24, "правами"), (32, "пользователя")]


def test_emphasis_caps_run_of_listed_words_is_fixed_word_by_word(tmp_path):
    _diags, text = _fixed(tmp_path, "# склады держат ТЕ ЖЕ строки\n" + _HEAD)

    assert text.startswith("# склады держат те же строки\n")


def test_emphasis_caps_in_a_markup_comment():
    text = '<svg xmlns="http://www.w3.org/2000/svg"><!-- слой НАД фоном --></svg>\n'

    diags = _lint("Ресурсы/склад.svg", text, CAPS)

    assert [d.line for d in diags] == [1]


@pytest.mark.needs_data
def test_emphasis_caps_in_a_doc_comment_of_a_module(tmp_path):
    text = "/*\n * Метод НЕ доступен с клиента\n */\nметод Закрыть()\n;\n"
    path = _write(tmp_path, "Склады.xbsl", text)

    diags = engine.run(discover([str(tmp_path)]), select={CAPS})

    assert [(d.line, d.col) for d in diags] == [(2, 10)]
    assert fixer.fix_source(engine.load(path), diags).text.startswith(
        "/*\n * Метод не доступен с клиента\n"
    )
