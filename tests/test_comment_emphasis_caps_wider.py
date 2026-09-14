"""comment/emphasis-caps beyond the function words: any stressed word, a capital letter, a
negation glued on, and the English line of a translated comment.

An element description, a resource file and a translation dictionary need no Element data -
the comments of the first are cut out with the yaml composer, the dictionary is read as yaml -
so the tests run in a public checkout. A module is read by the lexer, which takes its words from
the dataset: that test is marked `needs_data`.
"""

import pytest

from xbsl import engine, fixer
from xbsl.cli import discover
from xbsl.rules import _comments

CAPS = "comment/emphasis-caps"
SHAPE = "translation/english-shape"

_HEAD = "ВидЭлемента: Справочник\nИмя: Склады\n"


def _lint_yaml(comments: str, body: str = ""):
    text = comments + _HEAD + body
    return engine.run_sources([engine.load_text("Склады.yaml", text)], select={CAPS})


def _words(diags):
    return [d.message.split('"')[1] for d in diags]


def _write(tmp_path, name: str, text: str):
    path = tmp_path / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(text.encode("utf-8"))
    return path


def _fixed(tmp_path, name: str, text: str, rules=(CAPS,)):
    path = _write(tmp_path, name, text)
    diags = engine.run(discover([str(tmp_path)]), select=set(rules))
    return diags, fixer.fix_source(engine.load(path), [d for d in diags if d.rule_id == CAPS]).text


# --- a stressed word outside the list of function words --------------------------------------

def test_a_word_the_file_also_writes_in_small_letters_is_stressed(tmp_path):
    comments = "# берётся ТЕКУЩИЙ склад\n# текущий склад задаётся в настройке\n"

    diags, text = _fixed(tmp_path, "Склады.yaml", comments + _HEAD)

    assert _words(diags) == ["ТЕКУЩИЙ"]
    assert text.startswith("# берётся текущий склад\n")


def test_a_word_of_two_vowels_is_stressed_without_a_small_spelling():
    diags = _lint_yaml("# остаток считается по ПРИНЯТЫМ партиям\n")

    assert _words(diags) == ["ПРИНЯТЫМ"]


@pytest.mark.parametrize("comment", (
    "# строки ТЧ и маска ГГГГММДД",
    "# подписка ИТС и программа УНФ",
    "# курс по коду ОКПО",
    "# курс по коду ОПКО",
))
def test_abbreviations_are_not_stressed_words(comment):
    """No vowel, one vowel in a short word, a part of a camel-case name of the file - the naming
    standard writes an abbreviation that way - and the same letters misspelled."""
    body = "Реквизиты:\n    - Имя: КодОкпоСклада\n"

    assert _lint_yaml(comment + "\n", body) == []


def test_a_short_word_counts_once_the_file_writes_it_small():
    assert _words(_lint_yaml("# КОД партии и код склада\n")) == ["КОД"]


def test_logical_operations_in_capitals_are_judged_like_any_stress():
    """A logical operation named in capitals (`по ИЛИ`, `- И`) is a stress all the same: a
    sweep of a project wrote such names in small letters, and the rule no longer spares them."""
    diags = _lint_yaml("# значения складываются по ИЛИ, между группами - И.\n")

    assert _words(diags) == ["ИЛИ", "И"]
    assert all(d.fix is not None for d in diags)


def test_a_phrase_with_a_capital_the_rule_cannot_judge_gets_no_fix():
    """`ПОСТАВЩИКА` is a part of a camel-case name here and may be a name: lowering its
    neighbour alone would leave the phrase half shouting."""
    diags = _lint_yaml(
        "# остаток читается ПОД ПОСТАВЩИКА\n", "Реквизиты:\n    - Имя: СкладыПоставщика\n",
    )

    assert [(d.message.split('"')[1], d.fix) for d in diags] == [("ПОД", None)]


# --- one capital letter ------------------------------------------------------------------------

@pytest.mark.parametrize(("comment", "word"), (
    ("# партии в порядке, В котором идут склады", "В"),
    ("# отметка красит рамку И фон строки", "И"),
    ("# Остаток С клиента не передаётся", "С"),
    ("# условия отбора соединяются по или, между блоками - И.", "И"),
    ("# Почему Склады.ТекущийСклад, А не Партии.Склад.", "А"),
))
def test_a_capital_letter_inside_a_sentence_is_a_stress(tmp_path, comment, word):
    diags, text = _fixed(tmp_path, "Склады.yaml", comment + "\n" + _HEAD)

    assert _words(diags) == [word]
    assert text.startswith(comment.replace(f" {word} ", f" {word.lower()} ", 1).replace(
        f" {word}.", f" {word.lower()}.", 1,
    ))


@pytest.mark.parametrize("comment", (
    "# Склад закрыт. В отчёте его нет",
    "# В отчёте склад не виден",
    "# Правило: В отчёте склад не виден",
    "# (В отчёте склад не виден)",
    "# Т.к. склад закрыт, отчёт пуст",
    "# Меню (Склады, Партии, О складе, Выход) собирается кодом",
    "# 2.1 С этой партией приходят остатки",
    "# склады идут операндом условия В.",
    "# отбор ГДЕ Партии.Склад В (&Склады)",
))
def test_a_capital_letter_in_its_right_is_left_alone(comment):
    """A sentence start, a colon, a bracket, an abbreviation, a list of names in title case, a
    numbered point, and the operator of a cited query."""
    assert _lint_yaml(comment + "\n") == []


def test_a_capital_letter_opening_a_continued_line():
    """Only `И` and `А` are judged at the start of a line that goes on from the line above: a
    line of a list starts with a preposition in capitals by right."""
    continued = _lint_yaml("# отметка красит рамку\n# И фон строки\n")
    listed = _lint_yaml("# ответ бывает двух видов\n# В остальных случаях текст пуст\n")
    headed = _lint_yaml("# ── Раздел складов ──\n# И партий тоже\n")
    after_stop = _lint_yaml("# отметка красит рамку.\n# И фон строки тоже\n")

    assert [d.line for d in continued] == [2]
    assert listed == [] and headed == [] and after_stop == []


def test_a_quote_left_open_on_the_line_above_hides_the_capital():
    comments = '# подпись "С этой\n# партией" стоит над таблицей\n'

    assert _lint_yaml(comments) == []


# --- a negation glued on in capitals -----------------------------------------------------------

def test_a_negation_in_capitals_is_lowered(tmp_path):
    comments = "# номер ставится партии с НЕзаполненным номером.\n# НЕзакрытые партии видны\n"

    diags, text = _fixed(tmp_path, "Склады.yaml", comments + _HEAD)

    assert _words(diags) == ["НЕзаполненным", "НЕзакрытые"]
    assert text.startswith(
        "# номер ставится партии с незаполненным номером.\n# Незакрытые партии видны\n"
    )


# --- a query cited in a comment ----------------------------------------------------------------

@pytest.mark.parametrize("comment", (
    "# условие ГДЕ НЕ Удалён",
    "#     Склады КАК Склады",
    "#     Склады.Код КАК Код,",
    "#     ПО Склады.Код == Партии.Склад",
    "# остатки считаются агрегатом КОЛИЧЕСТВО(*)",
    "# отбор по дате делается в коде, а не в ГДЕ: дата приходит параметром",
))
def test_a_cited_query_is_syntax_not_stress(comment):
    assert _lint_yaml(comment + "\n") == []


@pytest.mark.parametrize(("comment", "words"), (
    ("# журнал не показывает, ГДЕ остановилась загрузка", ["ГДЕ"]),
    ("# партии берутся ИЗ АРХИВА, архив пополняет задание", ["ИЗ", "АРХИВА"]),
    ("# ПересчётОстатков НЕ меняет дату", ["НЕ"]),
    ("# метод пересчёта нарочно НЕ @ДоступноСКлиента", ["НЕ"]),
))
def test_a_query_word_among_prose_is_a_stress(comment, words):
    """What follows the keyword decides: prose puts its own word there even after a name."""
    assert _words(_lint_yaml(comment + "\n")) == words


# --- where the comments are ------------------------------------------------------------------

def test_a_value_that_parses_only_leniently_holds_no_comment_lines():
    """A `\\'` inside a double-quoted scalar: the platform takes it, the composer does not, and
    the `#` of a color in the value was read as a comment running to the end of the value."""
    text = (
        "ВидЭлемента: Справочник\nИмя: Склады\n"
        "Описание: \"<a style=\\'color: #2D2F37\\'>склад В аренде МАКС</a>\"\n"
    )

    assert _comments.lines(engine.load_text("Склады.yaml", text)) == []


@pytest.mark.needs_data
def test_a_capital_letter_in_a_module_comment(tmp_path):
    text = "// Остаток приходит С клиента\nметод Пересчитать()\n;\n"

    diags, fixed = _fixed(tmp_path, "Склады.xbsl", text)

    assert [(d.line, d.col) for d in diags] == [(1, 21)]
    assert fixed.startswith("// Остаток приходит с клиента\n")


# --- the English line of a translated comment ---------------------------------------------------

def _dictionary(tmp_path, body: str):
    head = "version: 1\nlanguage: en\n\n"
    return _write(tmp_path, "xbsl-translation/030-phrases.yaml", head + body)


def _lint_dictionary(tmp_path, rules=(CAPS,)):
    diags = engine.run(discover([str(tmp_path)]), select=set(rules))
    return [d for d in diags if d.rule_id in rules]


def test_capitals_a_stressed_key_passed_on_are_reported_with_a_fix(tmp_path):
    path = _dictionary(tmp_path, (
        "phrases:\n"
        '    "Партии переносятся ПО ОДНОЙ": "The batches are moved ONE BY ONE"\n'
        '    "Склад НЕ закрывается": "The warehouse IS NOT closed"\n'
        '    "Номер ставится В момент записи": "The number is given AT the moment OF writing"\n'
        '    "ПОСЛЕ загрузки склад пуст": "AFTER loading the warehouse is empty"\n'
    ))
    diags = _lint_dictionary(tmp_path)
    text = fixer.fix_source(engine.load(path), diags).text

    assert _words(diags) == ["ONE", "BY", "ONE", "IS", "NOT", "AT", "OF", "AFTER"]
    assert "moved one by one" in text and "is not closed" in text
    assert "at the moment of writing" in text and '"After loading' in text


def test_capitals_of_a_key_without_stress_stay_with_english_shape(tmp_path):
    _dictionary(tmp_path, 'phrases:\n    "Склад не закрывается": "The warehouse does NOT close"\n')

    diags = _lint_dictionary(tmp_path, rules=(CAPS, SHAPE))

    assert [(d.rule_id, d.message.split("'")[1]) for d in diags] == [(SHAPE, "NOT")]


def test_a_prefix_and_an_article_in_capitals_are_reported(tmp_path):
    _dictionary(tmp_path, (
        "phrases:\n"
        '    "с НЕзаполненным номером": "with an UNfilled number"\n'
        '    "стоит в НЕредактируемой ячейке": "stands in a NON-editable cell"\n'
        '    "Курс ЧИСЛОМ хранится": "The rate is stored AS A number"\n'
    ))

    assert _words(_lint_dictionary(tmp_path)) == ["UNfilled", "NON", "AS", "A"]


def test_names_and_codes_of_an_english_line_stay_in_capitals(tmp_path):
    """A name carried over from the key, a Latin word of the key, a mask, a translated
    abbreviation, a color, a placeholder, a quote, a heading in capitals."""
    _dictionary(tmp_path, (
        "phrases:\n"
        '    "Тариф СТАРТ или МАКС НЕ меняется": "The START or MAKS plan does NOT change"\n'
        '    "Вход OIDC НЕ нужен": "The OIDC sign-in is NOT needed"\n'
        '    "Дата ДД.ММ.ГГГГ НЕ задана": "The DD.MM.YYYY date is NOT set"\n'
        '    "Кэш ЦФО НЕ обновляется": "The FRC cache is NOT refreshed"\n'
        '    "Цвет DBDBDB НЕ меняется": "The DBDBDB color does NOT change"\n'
        '    "{{FILL}} НЕ задан": "{{FILL}} is NOT set"\n'
        '    "Подпись \\"ЗАКРЫТ\\" НЕ видна": "The \\"CLOSED\\" caption is NOT visible"\n'
        '    "── СКЛАДЫ ──": "── WAREHOUSES ──"\n'
    ))

    assert _words(_lint_dictionary(tmp_path)) == ["NOT"] * 7


def test_a_query_keyword_of_an_english_line(tmp_path):
    _dictionary(tmp_path, (
        "phrases:\n"
        '    "склады идут операндом условия В.": "warehouses are an operand of an IN condition."\n'
        '    "запрос с КОЛИЧЕСТВО(*) НЕ группирует": "a query with COUNT(*) does NOT group"\n'
        '    "склады ИЛИ партии, но не ВСЕ": "warehouses OR batches, but not ALL"\n'
    ))

    assert _words(_lint_dictionary(tmp_path)) == ["OR", "ALL"]


def test_a_pronoun_that_is_also_a_product_counts_only_in_a_phrase(tmp_path):
    _dictionary(tmp_path, (
        "phrases:\n"
        '    "держит цвет СВОЕГО склада": "keeps the color of ITS OWN warehouse"\n'
        '    "остальные (номер договора, номер": "the rest (the contract number, ITS"\n'
    ))

    assert _words(_lint_dictionary(tmp_path)) == ["ITS", "OWN"]


def test_only_the_phrases_of_a_dictionary_are_english_comment_lines(tmp_path):
    _dictionary(tmp_path, (
        "tokens:\n"
        "    СкладНЕзакрыт: WarehouseNOTClosed\n"
        "literals:\n"
        '    "Склад ЗАКРЫТ": "The warehouse is CLOSED"\n'
        "terms:\n"
        "    ПО ОДНОЙ: ONE BY ONE\n"
    ))

    assert _lint_dictionary(tmp_path) == []
