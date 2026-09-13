"""typography/non-keyboard and typography/en-dash-comment: characters judged in comments only.

Both rules read the comments of every kind of source - a module, an element description,
a resource file - and leave values and string literals alone. The module and yaml halves need
different machinery (the lexer against the yaml composer), so a module test is marked
`needs_data` and the rest run in a public checkout.
"""

import pytest

from xbsl import engine, fixer, i18n
from xbsl.cli import discover

NON_KEYBOARD = "typography/non-keyboard"
EN_DASH = "typography/en-dash-comment"

_HEAD = "ВидЭлемента: Справочник\nИмя: Партии\n"


def _yaml(text: str, rule: str):
    return engine.run_sources([engine.load_text("Партии.yaml", text)], select={rule})


def _lint(name: str, text: str, rule: str):
    return engine.run_sources([engine.load_text(name, text)], select={rule})


def _info(rule_id: str):
    return next(r for r in engine.RULES if r.id == rule_id)


def _fix_on_disk(tmp_path, name: str, text: str, rule: str):
    path = tmp_path / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(text.encode("utf-8"))
    diags = engine.run(discover([str(tmp_path)]), select={rule})
    return path, diags, fixer.fix_source(engine.load(path), diags).text


# --- the defaults -----------------------------------------------------------------------------

def test_non_keyboard_is_a_warning_on_by_default():
    info = _info(NON_KEYBOARD)

    assert (info.severity.value, info.enabled_by_default, info.scope) == ("warning", True, "file")


def test_en_dash_comment_is_info_off_by_default_with_a_reason():
    info = _info(EN_DASH)

    assert (info.severity.value, info.enabled_by_default, info.scope) == ("info", False, "file")
    assert "--enable typography/en-dash-comment" in info.off_reason_text


@pytest.mark.parametrize("key", (
    "typography/non-keyboard.found", "typography/non-keyboard.word",
    "typography/en-dash-comment.found", "typography/en-dash-comment.off",
))
def test_comment_character_rules_speak_english(key):
    i18n.set_lang("en")
    try:
        text = i18n.t(key, char="→", code="2192", replacement="->")
    finally:
        i18n.set_lang("ru")
    assert not any("а" <= ch.lower() <= "я" for ch in text), text


# --- typography/non-keyboard ------------------------------------------------------------------

@pytest.mark.parametrize(("char", "replacement"), (
    ("→", "->"), ("←", "<-"), ("↔", "<->"), ("⇒", "=>"), ("⇐", "<="), ("⇔", "<=>"),
    ("≥", ">="), ("≤", "<="), ("≠", "<>"), ("≈", "~"), ("±", "+-"),
))
def test_non_keyboard_character_gets_its_keyboard_spelling(char, replacement):
    (diag,) = _yaml(f"# остаток {char} 0\n" + _HEAD, NON_KEYBOARD)

    assert (diag.line, diag.col) == (1, 11)
    assert diag.fix.new == replacement
    assert f"'{replacement}'" in diag.message


def test_non_keyboard_multiplication_sign_is_kept_apart_from_letters():
    diags = _yaml("# партия×склад, размер 2×3\n" + _HEAD, NON_KEYBOARD)

    assert [d.fix.new for d in diags] == [" x ", "x"]


@pytest.mark.parametrize("char", ("↑", "↓"))
def test_non_keyboard_vertical_arrow_asks_for_a_word_without_a_fix(char):
    (diag,) = _yaml(f"# сортировка {char}\n" + _HEAD, NON_KEYBOARD)

    assert diag.fix is None
    assert "словом" in diag.message


@pytest.mark.parametrize("comment", (
    "# подпись у суммы: ₽, ₸, €, $",
    "# среднее тире \u2013 и длинное \u2014 у своих правил",
    "# буква ё тоже не отсюда",
))
def test_non_keyboard_leaves_currency_dashes_and_letters_alone(comment):
    assert _yaml(comment + "\n" + _HEAD, NON_KEYBOARD) == []


def test_non_keyboard_character_quoted_inside_a_comment_is_still_judged():
    # Quotes inside a comment do not make a string literal: the character is in the source
    # all the same, and nobody types it by hand.
    diags = _yaml("# подпись \"Далее →\" у кнопки\n" + _HEAD, NON_KEYBOARD)

    assert [d.col for d in diags] == [18]


def test_non_keyboard_leaves_yaml_values_and_script_strings_alone():
    assert _yaml(_HEAD + "Описание: цена → со скидкой\n", NON_KEYBOARD) == []
    assert _lint("Ресурсы/партия.js", "var label = 'назад ←';\n", NON_KEYBOARD) == []


def test_non_keyboard_in_a_stylesheet_comment_is_fixed_in_the_file(tmp_path):
    _path, diags, text = _fix_on_disk(
        tmp_path, "Ресурсы/партия.css", "/* ширина ≤ 100% */\r\n.a { width: 100%; }\r\n",
        NON_KEYBOARD,
    )

    assert len(diags) == 1
    assert text == "/* ширина <= 100% */\r\n.a { width: 100%; }\r\n"


@pytest.mark.needs_data
def test_non_keyboard_in_a_module_comment_but_not_in_its_string():
    text = "// шаг 1 → шаг 2\nметод Ф(): Строка\n    возврат \"шаг 1 → шаг 2\"\n;\n"

    diags = _lint("Партии.xbsl", text, NON_KEYBOARD)

    assert [(d.line, d.col) for d in diags] == [(1, 10)]


# --- typography/en-dash-comment ---------------------------------------------------------------

def test_en_dash_in_a_yaml_comment_is_replaced_with_a_hyphen(tmp_path):
    path, diags, text = _fix_on_disk(
        tmp_path, "Партии.yaml", "# партия – единица учёта\n" + _HEAD, EN_DASH,
    )

    assert [(d.line, d.col) for d in diags] == [(1, 10)]
    written = path.read_bytes().decode("utf-8")
    assert [written[d.fix.start:d.fix.end] for d in diags] == ["–"]
    assert text.startswith("# партия - единица учёта\n")


def test_en_dash_outside_comments_is_left_alone():
    assert _yaml(_HEAD + "Описание: партия – единица учёта\n", EN_DASH) == []
    assert _lint("Ресурсы/партия.js", "var t = 'а – б';\n", EN_DASH) == []


def test_en_dash_in_a_markup_comment_but_not_in_its_text():
    text = "<p>Партия – единица</p><!-- разметка – из шаблона -->\n"

    diags = _lint("Ресурсы/партия.html", text, EN_DASH)

    assert [d.col for d in diags] == [38]


@pytest.mark.needs_data
def test_en_dash_in_a_module_comment():
    diags = _lint("Партии.xbsl", "// партия – единица\nметод Ф()\n;\n", EN_DASH)

    assert [(d.line, d.col, d.severity.value) for d in diags] == [(1, 11, "info")]
