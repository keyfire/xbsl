"""comment/emphasis-caps beyond the function words: any stressed word, a capital letter, a
negation glued on, and the English line of a translated comment.

An element description, a resource file and a translation dictionary need no Element data -
the comments of the first are cut out with the yaml composer, the dictionary is read as yaml -
so the tests run in a public checkout. The words of a cited query come from the keyword table
of the dataset, and nothing else of it: the tests of a cited query pin a data root holding a
table of their own (`keyword_table`) and run there too. A module is read by the lexer, and the
platform's own table is the platform's data: those tests are marked `needs_data`.
"""

import json

import pytest

from xbsl import dataset, engine, fixer
from xbsl.cli import discover
from xbsl.rules import _comments
from xbsl.rules import comment_prose

CAPS = "comment/emphasis-caps"
SHAPE = "translation/english-shape"

_HEAD = "ВидЭлемента: Справочник\nИмя: Склады\n"

#: A keyword table of the query language in the shape the dataset keeps it (terms.json, section
#: `query`): the pairs the tests below cite, keywords of several words among them.
_TABLE = {
    "В": "IN", "И": "AND", "ИЛИ": "OR", "НЕ": "NOT", "КАК": "AS", "ПО": "ON", "ИЗ": "FROM",
    "ГДЕ": "WHERE", "ЕСТЬ": "IS", "ВСЕ": "ALL", "КОГДА": "WHEN", "ТОГДА": "THEN", "ИНАЧЕ": "ELSE",
    "КОНЕЦ": "END", "ПЕРВЫЕ": "TOP", "ПОЛУЧИТЬ": "FETCH", "СО СМЕЩЕНИЕМ": "OFFSET",
    "КОЛИЧЕСТВО": "COUNT", "ВЫБРАТЬ": "SELECT", "ВЫБОР": "CASE", "ВОЗР": "ASC", "УБЫВ": "DESC",
    "УПОРЯДОЧИТЬ ПО": "ORDER BY", "СГРУППИРОВАТЬ ПО": "GROUP BY", "ДЛЯ ИЗМЕНЕНИЯ": "FOR UPDATE",
    "ПО УМОЛЧАНИЮ": "DEFAULT", "СОЗДАТЬ ВРЕМЕННУЮ ТАБЛИЦУ": "CREATE TEMPORARY TABLE",
    "ССЫЛКА": "REFS", "ЗНАЧЕНИЯ": "VALUES", "ПОЛНОЕ": "FULL", "СОЕДИНЕНИЕ": "JOIN",
    "ЛЕВОЕ": "LEFT",
}


@pytest.fixture()
def keyword_table(tmp_path_factory):
    """Pin a data root holding nothing but a keyword table (`_TABLE` unless the test swaps it).

    Returns the pin: a test that compares two tables calls it with the second one, and a test
    of the reserved words passes the other keys of terms.json along with the table.
    """
    def pin(table=_TABLE, **other):
        root = tmp_path_factory.mktemp("data")
        (root / "1.0.0").mkdir()
        (root / "1.0.0" / "terms.json").write_text(
            json.dumps({"query": table, **other}, ensure_ascii=False), encoding="utf-8",
        )
        (root / "index.json").write_text(
            json.dumps({"available": ["1.0.0"], "default": "1.0.0"}), encoding="utf-8",
        )
        dataset.set_data_root(root)
        dataset.set_version("1.0.0")

    pin()
    yield pin
    dataset.set_version(None)
    dataset.set_data_root(None)


@pytest.fixture()
def no_data(tmp_path_factory):
    """Pin a data root with nothing in it: a public checkout without the data."""
    dataset.set_data_root(tmp_path_factory.mktemp("empty"))
    yield
    dataset.set_data_root(None)


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
def test_a_capital_letter_in_its_right_is_left_alone(comment, keyword_table):
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
    "# а предложение ПОЛУЧИТЬ принимает размер и смещение только константами",
    "#     ПОЛУЧИТЬ 10 СО СМЕЩЕНИЕМ 20",
    "# партии читаются порциями, начало порции задаёт СО СМЕЩЕНИЕМ",
    "# сортировка стоит перед ПОЛУЧИТЬ",
    "# ВЫБОР КОГДА Остаток > 0 ТОГДА 1 ИНАЧЕ 0 КОНЕЦ",
    "# ВЫБОР Партии.Вид КОГДА 1 ТОГДА 2 ИНАЧЕ 0 КОНЕЦ",
    "#     Партии.Дата ВОЗР, Партии.Номер УБЫВ",
    "#     ГДЕ Партии.Склад = &Склад ДЛЯ ИЗМЕНЕНИЯ",
    "# таблица задаётся СОЗДАТЬ ВРЕМЕННУЮ ТАБЛИЦУ Остатки",
    "# остатки берутся ГДЕ Партии.Документ ССЫЛКА Поступления",
    "#     ЗНАЧЕНИЯ (&Код, &Имя)",
    "# ВСТАВИТЬ В Остатки (Склад, Количество) ЗНАЧЕНИЯ (&Склад, 0)",
    "# ИЗМЕНИТЬ Остатки УСТАНОВИТЬ Количество = 0",
    "# УДАЛИТЬ ИЗ Остатки ГДЕ Количество = 0",
    "# УДАЛИТЬ ИЗ ВТ_Остатки",
    "# отбор ГДЕ Т.Активен = ИСТИНА И Т.Код В (&Коды)",
    "# отбор ГДЕ Т.Удален <> ИСТИНА",
))
def test_a_cited_query_is_syntax_not_stress(comment, keyword_table):
    """A marker (the Russian DESC), the head of a CASE expression in either form, the head of a
    statement that changes a temporary table, a keyword of several words, and an ordinary word
    of the table - or a literal it does not hold - with code after it; a literal is syntax
    after a comparison sign as well."""
    assert _lint_yaml(comment + "\n") == []


@pytest.mark.parametrize(("comment", "words"), (
    ("# журнал не показывает, ГДЕ остановилась загрузка", ["ГДЕ"]),
    ("# партии берутся ИЗ АРХИВА, архив пополняет задание", ["ИЗ", "АРХИВА"]),
    ("# ПересчётОстатков НЕ меняет дату", ["НЕ"]),
    ("# метод пересчёта нарочно НЕ @ДоступноСКлиента", ["НЕ"]),
    ("# права нужно ПОЛУЧИТЬ заранее", ["ПОЛУЧИТЬ"]),
    ("# на складе ТОЛЬКО один остаток", ["ТОЛЬКО"]),
    ("# остаток считается ДЛЯ КАЖДОГО склада", ["ДЛЯ", "КАЖДОГО"]),
    ("# решает ССЫЛКА на склад, а не код", ["ССЫЛКА"]),
    ("# партии сравнивают ЗНАЧЕНИЯ, а не ссылки", ["ЗНАЧЕНИЯ"]),
    ("# склад закрыт ПО УМОЛЧАНИЮ", ["ПО", "УМОЛЧАНИЮ"]),
    ("# отчет делает ВЫБОР склада по остатку", ["ВЫБОР"]),
    ("# нельзя УДАЛИТЬ склад, пока на нем есть партии", ["УДАЛИТЬ"]),
    ("# запись нельзя УДАЛИТЬ ИЗ Склады, пока идет загрузка", ["УДАЛИТЬ"]),
    ("# DELETE /data/склады: пометка ТОЛЬКО удаления", ["ТОЛЬКО"]),
))
def test_a_query_word_among_prose_is_a_stress(comment, words, keyword_table):
    """What follows the keyword decides: prose puts its own word there even after a name. A word
    of a keyword of several words is judged alone, and "ПО УМОЛЧАНИЮ" is the stock phrase of
    prose rather than the keyword of the table. CASE without WHEN after it, and a verb of a
    statement without the shape of one, are words of prose too; so is the HTTP method."""
    assert _words(_lint_yaml(comment + "\n")) == words


def test_the_words_of_a_cited_query_come_from_the_keyword_table(keyword_table):
    """The same line is a cited query while the table names the keyword and a stress once it
    does not: the rule keeps no list of the words of its own."""
    comment = "# остатки берутся ГДЕ Партии.Документ ССЫЛКА Поступления\n"
    known = _lint_yaml(comment)

    keyword_table({key: value for key, value in _TABLE.items() if key != "ССЫЛКА"})

    assert known == [] and _words(_lint_yaml(comment)) == ["ССЫЛКА"]


def test_a_keyword_a_later_table_adds_is_an_ordinary_word(keyword_table):
    """A keyword the rule has never heard of counts as a word of prose as well: code after it
    makes it syntax, and it does not hide a stress on its line the way a marker would."""
    keyword_table({**_TABLE, "РЕКУРСИВНО": "RECURSIVE"})

    assert _lint_yaml("# склады обходятся РЕКУРСИВНО Склады.Родитель\n") == []
    assert _words(_lint_yaml("# обход идёт РЕКУРСИВНО, а НЕ циклом\n")) == ["РЕКУРСИВНО", "НЕ"]


def test_without_the_table_the_words_kept_by_hand_stand_in_for_it(keyword_table):
    """Data without the keyword table: a marker still marks a cited query, and the ordinary words
    the rule kept by hand before it read the table are syntax in context again - a word only
    the table knows is judged like prose."""
    keyword_table({})

    assert _lint_yaml("# ВЫБРАТЬ Склады.Код ИЗ Склады ГДЕ НЕ Склады.Удалён\n") == []
    assert _lint_yaml("# условие ГДЕ НЕ Удалён\n") == []
    assert _lint_yaml("#     ПОЛУЧИТЬ 10 СО СМЕЩЕНИЕМ 20\n") == []
    assert _words(_lint_yaml("# остатки берутся ГДЕ Партии.Документ ССЫЛКА Поступления\n")) == [
        "ССЫЛКА"]


def test_a_checkout_without_data_judges_a_cited_query_as_before(no_data):
    """No data at all: the words kept by hand, the shapes and the literals are there all the
    same, and a stress stays a stress."""
    assert _lint_yaml("# условие ГДЕ НЕ Удалён\n") == []
    assert _lint_yaml("# ВЫБОР КОГДА Остаток > 0 ТОГДА 1 ИНАЧЕ 0 КОНЕЦ\n") == []
    assert _lint_yaml("# ВСТАВИТЬ В Остатки (Склад) ЗНАЧЕНИЯ (&Склад)\n") == []
    assert _lint_yaml("# отбор ГДЕ Т.Активен = ИСТИНА И Т.Код В (&Коды)\n") == []
    assert _words(_lint_yaml("# на складе ТОЛЬКО один остаток\n")) == ["ТОЛЬКО"]
    assert _words(_lint_yaml("# отчет делает ВЫБОР склада по остатку\n")) == ["ВЫБОР"]


def test_the_literals_the_table_lacks_are_words_of_the_language(keyword_table):
    """The Boolean literals, the empty value and `TEMP` are reserved words of the query language
    the keyword table does not hold; they are ordinary words, not markers."""
    words = comment_prose._query_words()

    assert {"ИСТИНА", "ЛОЖЬ", "НЕОПРЕДЕЛЕНО", "TRUE", "FALSE", "UNDEFINED", "TEMP"} <= words
    # An ordinary word does not hide a stress on its line the way a marker would, and out of
    # context it is judged like any other word.
    assert _words(_lint_yaml("# флаг Т.Активен = ИСТИНА, а склад ТОЛЬКО один\n")) == ["ТОЛЬКО"]
    assert _words(_lint_yaml("# это ИСТИНА, а не догадка\n")) == ["ИСТИНА"]


@pytest.mark.needs_data
@pytest.mark.parametrize("comment", (
    "# ВЫБОР КОГДА Остаток > 0 ТОГДА 1 ИНАЧЕ 0 КОНЕЦ",
    "#     Партии.Дата ВОЗР, Партии.Номер УБЫВ",
    "#     ГДЕ Партии.Склад = &Склад ДЛЯ ИЗМЕНЕНИЯ",
    "# таблица задаётся СОЗДАТЬ ВРЕМЕННУЮ ТАБЛИЦУ Остатки",
    "# остатки берутся ГДЕ Партии.Документ ССЫЛКА Поступления",
    "#     ЗНАЧЕНИЯ (&Код, &Имя)",
    "#     ВСТАВИТЬ ИГНОРИРУЯ В Остатки ЗНАЧЕНИЯ (&Склад)",
    "# остаток правит запрос ИЗМЕНИТЬ Остатки УСТАНОВИТЬ Количество = &Количество",
    "# индекс строится как СОЗДАТЬ ИНДЕКС ПоКоду ДЛЯ Остатки (Код)",
))
def test_the_platform_table_holds_the_keywords_of_a_cited_query(comment):
    """Each line holds a keyword the hand-kept tables lacked and was reported before."""
    assert _lint_yaml(comment + "\n") == []


@pytest.mark.needs_data
def test_the_division_written_by_hand_names_words_of_the_platform_table():
    """A marker, a function and a phrase of prose written by hand are words of the platform's
    own table - a keyword the platform renames would leave them marking nothing - except the
    markers the table is known not to hold."""
    table = dataset.load_json("terms.json")["query"]
    words = {word for pair in table.items() for keyword in pair for word in keyword.split()}
    by_hand = (
        comment_prose._RUSSIAN_MARKERS | comment_prose._ENGLISH_MARKERS
        | comment_prose._ENGLISH_MARKERS_OF_A_RUSSIAN_LINE | comment_prose._QUERY_FUNCTIONS
    )

    assert by_hand - words == set()
    assert comment_prose._MARKERS_OUTSIDE_THE_TABLE & words == set()
    assert comment_prose._PROSE_PHRASES <= set(table)
    # The fallback knows no word the table does not; the literals are outside it - once a table
    # holds them, the list written by hand has nothing left to add.
    assert comment_prose._FALLBACK_WORDS - words == set()
    assert {word for phrase in comment_prose._FALLBACK_PHRASES for word in phrase.split()} <= words
    assert comment_prose._FALLBACK_WORDS_OUTSIDE_THE_TABLE & words == set()


@pytest.mark.needs_data
def test_the_reserved_words_kept_by_hand_are_the_ones_the_documentation_lists():
    """The words outside the table stand in for the documentation's list only where the data
    has none: with the list, every one of them is read from it, and the translator's spellings
    of the reserved words agree with it."""
    from xbsl.translation import platform_map

    data = dataset.load_json("terms.json")
    if not data.get("query_reserved"):
        pytest.skip("the data keeps no list of the reserved words of the query language")

    outside = comment_prose._words_outside_the_table()
    assert comment_prose._FALLBACK_WORDS_OUTSIDE_THE_TABLE <= outside
    assert platform_map._RESERVED_FALLBACK.items() <= platform_map._reserved_spellings(data).items()


_RESERVED = {"ИЗ": "FROM", "ИСТИНА": "TRUE", "ЛОЖЬ": "FALSE", "ПУСТО": "EMPTY"}


def test_the_reserved_words_outside_the_table_are_read_from_the_data(keyword_table):
    """A reserved word the data lists is a word of the language: a literal compared with is
    syntax. A word of the keyword table is not "outside" it, and a marker (`NULL`) stays a
    marker. The control is the same line over a table alone: the word is a stress then."""
    comment = "# отбор ГДЕ Т.Вид = ПУСТО\n"
    assert _words(_lint_yaml(comment)) == ["ПУСТО"]

    keyword_table(query_reserved=_RESERVED, query_reserved_english_only=["NULL", "TEMP"])

    assert comment_prose._words_outside_the_table() == {
        "ИСТИНА", "ЛОЖЬ", "ПУСТО", "TRUE", "FALSE", "EMPTY", "TEMP",
    }
    assert _lint_yaml(comment) == []
    assert "NULL" not in comment_prose._query_words()


def test_without_the_list_the_reserved_words_kept_by_hand_stand_in(keyword_table):
    """Data with the keyword table and no list of the reserved words (an older extraction)."""
    fallback = comment_prose._FALLBACK_WORDS_OUTSIDE_THE_TABLE
    assert comment_prose._words_outside_the_table() == fallback


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


def test_a_query_keyword_of_an_english_line(tmp_path, keyword_table):
    _dictionary(tmp_path, (
        "phrases:\n"
        '    "склады идут операндом условия В.": "warehouses are an operand of an IN condition."\n'
        '    "запрос с КОЛИЧЕСТВО(*) НЕ группирует": "a query with COUNT(*) does NOT group"\n'
        '    "склады ИЛИ партии, но не ВСЕ": "warehouses OR batches, but not ALL"\n'
    ))

    assert _words(_lint_dictionary(tmp_path)) == ["OR", "ALL"]


def test_the_fetch_clause_of_an_english_line_is_syntax(tmp_path, keyword_table):
    """The keyword pairs of the FETCH clause: a key that cites the clause passes its keyword on,
    and a stressed verb of the key stays a stress in its translation."""
    _dictionary(tmp_path, (
        "phrases:\n"
        '    "а предложение ПОЛУЧИТЬ принимает размер": "and the FETCH clause takes the size"\n'
        '    "партии читаются СО СМЕЩЕНИЕМ": "the batches are read with an OFFSET"\n'
        '    "сначала ПОЛУЧИТЬ права": "FETCH the rights first"\n'
    ))

    assert _words(_lint_dictionary(tmp_path)) == ["FETCH"]


def test_an_english_line_citing_a_query_with_keywords_of_the_table(tmp_path, keyword_table):
    """A marker (`DESC`), a keyword of several words (`ORDER BY`, `GROUP BY`), and the words a key
    citing a query passes on to its translation (`CASE`, `WHERE`)."""
    _dictionary(tmp_path, (
        "phrases:\n"
        '    "УПОРЯДОЧИТЬ ПО Партии.Дата УБЫВ": "ORDER BY Batches.Date DESC"\n'
        '    "Партии.Дата УБЫВ": "Batches.Date DESC"\n'
        '    "ВЫБОР КОГДА Остаток > 0 ТОГДА 1 ИНАЧЕ 0 КОНЕЦ":'
        ' "CASE WHEN Balance > 0 THEN 1 ELSE 0 END"\n'
        '    "СГРУППИРОВАТЬ ПО Партии.Склад": "GROUP BY Batches.Warehouse"\n'
        '    "отбор ГДЕ Код == %Код": "a filter WHERE Code == %Code"\n'
    ))

    assert _lint_dictionary(tmp_path) == []


def test_an_english_line_citing_a_shape_or_a_literal(tmp_path, keyword_table):
    """The head of a statement in an English line cites a query by its shape, and the literals
    and `TEMP` are words of the language a key citing a query passes on."""
    _dictionary(tmp_path, (
        "phrases:\n"
        '    "ВСТАВИТЬ В Остатки (Склад) ЗНАЧЕНИЯ (&Склад)":'
        ' "INSERT INTO Balances (Warehouse) VALUES (&Warehouse)"\n'
        '    "отбор ГДЕ Т.Активен = ИСТИНА И Т.Код В (&Коды)":'
        ' "a filter WHERE T.Active = TRUE AND T.Code IN (&Codes)"\n'
        '    "таблица задаётся СОЗДАТЬ ВРЕМЕННУЮ ТАБЛИЦУ Остатки":'
        ' "the table is made by CREATE TEMP TABLE Balances"\n'
    ))

    assert _lint_dictionary(tmp_path) == []


def test_keywords_of_the_table_are_english_words_of_prose_as_well(tmp_path, keyword_table):
    """An English keyword a key does not cite is a stressed word like any other: the capitals of
    a translated stress ("a VIRTUAL TABLE") are not a query."""
    _dictionary(tmp_path, (
        "phrases:\n"
        '    "Список строится ВИРТУАЛЬНОЙ ТАБЛИЦЕЙ": "The list is built by a VIRTUAL TABLE"\n'
        '    "Колонка идёт ОТ ВЕРХА блока": "The column starts FROM THE TOP of the block"\n'
        '    "Набор ПОЛНЫЙ всегда": "The set is FULL always"\n'
    ))

    assert _words(_lint_dictionary(tmp_path)) == ["VIRTUAL", "TABLE", "FROM", "THE", "TOP", "FULL"]


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
