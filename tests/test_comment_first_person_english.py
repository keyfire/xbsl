"""comment/first-person in the English line of a translated comment.

A project that translates its sources keeps the English line of every comment as a `phrases`
value of its `xbsl-translation` dictionary. The rule reads those values for the first person
the way it reads a Russian comment for "мы". The dictionary is yaml and the discovery walks the
folders, so no Element data is needed and the tests run in a public checkout.
"""

from xbsl import engine, i18n
from xbsl.cli import discover

RULE = "comment/first-person"


def _dictionary(tmp_path, body: str, *, name: str = "030-phrases.yaml"):
    """A dictionary file with `body` under its head; bytes as written, no newline translation."""
    folder = tmp_path / "xbsl-translation"
    folder.mkdir(exist_ok=True)
    path = folder / name
    path.write_bytes(("version: 1\nlanguage: en\n\n" + body).encode("utf-8"))
    return path


def _lint(tmp_path):
    return [d for d in engine.run(discover([str(tmp_path)]), select={RULE}) if d.rule_id == RULE]


def _words(diags):
    return sorted(d.message.split('"')[1] for d in diags)


def test_english_first_person_in_a_phrase_value_is_reported(tmp_path):
    _dictionary(tmp_path, (
        "phrases:\n"
        '    "Остаток пересчитывается при записи партии.": "we recount the stock when a batch is written."\n'
        '    "Склад берётся из своей настройки.": "The warehouse comes from our own setting."\n'
        '    "Курс задаётся явно.": "Let\'s set the rate by hand, it is up to us."\n'
        '    "Строки задаются сами.": "We set both sides ourselves; my test showed it, I checked."\n'
    ))
    diags = _lint(tmp_path)

    assert _words(diags) == ["I", "Let's", "We", "my", "our", "ourselves", "us", "we"]
    assert all("английской строке комментария" in d.message for d in diags)


def test_english_first_person_message_names_the_translation(tmp_path):
    _dictionary(tmp_path, 'phrases:\n    "Задачи читаются пачкой.": "we read the tasks in a batch."\n')
    i18n.set_lang("en")
    try:
        (diag,) = _lint(tmp_path)
    finally:
        i18n.set_lang("ru")

    assert '"we"' in diag.message and "translation dictionary" in diag.message


def test_literals_tokens_and_terms_are_not_comment_lines(tmp_path):
    """A literal is a string of the code - often a text the user reads; tokens and terms are names."""
    _dictionary(tmp_path, (
        "tokens:\n"
        "    НашиСклады: OurWarehouses\n"
        "    Наша: Ours\n"
        "literals:\n"
        '    "Мы отправили код на почту": "We have sent a code to your email"\n'
        '    "Я принимаю условия": "I accept the terms"\n'
        "terms:\n"
        "    мой склад: my warehouse\n"
    ))

    assert _lint(tmp_path) == []


def test_quoted_captions_and_cited_code_stay_silent(tmp_path):
    _dictionary(tmp_path, (
        "phrases:\n"
        '    "Флажок \\"Я согласен\\" обязателен.": "The \\"I agree\\" flag is required."\n'
        '    "Поле `мой_курс` читается.": "The `my_rate` field is read."\n'
        '    "Язык en-us и путь /us/ не судятся.": "The en-us language and the /us/ path, I/O."\n'
    ))

    assert _lint(tmp_path) == []


def test_a_capital_inside_a_sentence_is_a_caption_of_the_interface(tmp_path):
    """"My data" named mid-sentence is the panel a user sees, not the author speaking."""
    _dictionary(tmp_path, (
        "phrases:\n"
        '    "справа - Мои данные (без вкладок)": "on the right - My data (no tabs)"\n'
        '    "Ссылка ведёт на страницу Напишите нам.": "The link leads to the Contact Us page."\n'
        '    "── Мои данные ──": "── My details ──"\n'
    ))

    assert _lint(tmp_path) == []


def test_a_capital_opening_the_value_follows_the_key(tmp_path):
    """A line that goes on from the line above starts with a small letter in the key; a capital
    in its translation is then a name. A key that opens a sentence lets the capital open one."""
    _dictionary(tmp_path, (
        "phrases:\n"
        '    "собственное окно платформы не подходит": "Our Window of the platform does not fit"\n'
        '    "Собственное окно, а не панель платформы.": "Our own window rather than the panel."\n'
    ))

    assert _words(_lint(tmp_path)) == ["Our"]


def test_a_letter_i_and_the_country_are_not_the_first_person(tmp_path):
    _dictionary(tmp_path, (
        "phrases:\n"
        '    "Буква I похожа на l, этап I закрыт.": "The letter I looks like l, part I is closed."\n'
        '    "Курс доллара США (I).": "The US dollar rate (I)."\n'
        '    "Индекс i цикла.": "The loop index i."\n'
        '    "Строки НАШИ снимаются.": "OUR lines are removed."\n'
    ))

    assert _words(_lint(tmp_path)) == ["OUR"]


def test_the_finding_points_at_the_word_in_the_dictionary_file(tmp_path):
    path = _dictionary(tmp_path, (
        "phrases:\n"
        '    "Сначала склад, затем партия.": "we take the warehouse, then we take the batch."\n'
    ))
    diags = sorted(_lint(tmp_path), key=lambda d: d.col)
    text = path.read_bytes().decode("utf-8").split("\n")

    assert [(d.line, text[d.line - 1][d.col - 1:d.col + 1]) for d in diags] == [(5, "we"), (5, "we")]
    assert diags[0].col < diags[1].col


def test_a_yaml_outside_a_dictionary_is_not_read_for_english(tmp_path):
    path = tmp_path / "Склады.yaml"
    path.write_bytes((
        "ВидЭлемента: Справочник\nИмя: Склады\n"
        "phrases:\n    ключ: we keep it\n"
    ).encode("utf-8"))

    assert _lint(tmp_path) == []


def test_russian_comments_of_a_dictionary_are_still_judged(tmp_path):
    _dictionary(tmp_path, (
        "# Строки комментариев у нас лежат здесь.\n"
        "phrases:\n"
        '    "Склад задаётся явно.": "The warehouse is set explicitly."\n'
    ))
    (diag,) = _lint(tmp_path)

    assert diag.line == 4 and '"нас"' in diag.message
