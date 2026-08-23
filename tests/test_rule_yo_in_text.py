"""The letter "ё" in the text a user reads (typography/yo-in-text).

The rule found its way here from a live case: the admin lists of a site carried a command
labelled with that letter, `naming/yo` looked at names only, and nothing else judged the
label - it reached the product.
"""

from xbsl import engine
from xbsl.cli import discover

RULE = "typography/yo-in-text"

_FORM = """ВидЭлемента: КомпонентИнтерфейса
Ид: aaaaaaaa-1111-2222-3333-444444444444
Имя: ФормаПроба
Тип: Форма
Содержимое:
    Тип: Группа
    Содержимое:
        -
            Тип: ОбычнаяКоманда
            Имя: Команда
{lines}"""

_DICTIONARY = """ВидЭлемента: ЛокализованныеСтроки
Ид: cccccccc-1111-2222-3333-444444444444
Имя: Словарь
Строки:
{strings}"""


def _lint(tmp_path, text, name="ФормаПроба.yaml", select=(RULE,)):
    (tmp_path / name).write_text(text, encoding="utf-8")
    return engine.run(discover([str(tmp_path)]), select=set(select) or None)


def _findings(diags):
    return [d for d in diags if d.rule_id == RULE]


def test_a_label_with_the_letter_is_reported_with_a_fix(tmp_path):
    diags = _findings(_lint(tmp_path, _FORM.format(
        lines="            Представление: Показать удалённые\n")))

    assert len(diags) == 1
    assert "удалённые" in diags[0].message and "удаленные" in diags[0].message
    assert diags[0].fix is not None and diags[0].fix.new == "е"


def test_the_fix_lands_on_the_letter_itself(tmp_path):
    diags = _findings(_lint(tmp_path, _FORM.format(
        lines="            Заголовок: \"Показать удалённые\"\n")))

    fix = diags[0].fix
    # The offsets address the file as the engine read it - bytes, line endings and all.
    written = (tmp_path / "ФормаПроба.yaml").read_bytes().decode("utf-8")
    assert written[fix.start:fix.end] == "ё"


def test_the_dictionary_of_localized_strings_is_judged(tmp_path):
    """Every entry of such a dictionary is a phrase shown to the user."""
    diags = _findings(_lint(
        tmp_path, _DICTIONARY.format(strings="    Подсказка: \"Второй берётся из даты.\"\n"),
        name="Словарь.yaml",
    ))

    assert len(diags) == 1 and "берётся" in diags[0].message


def test_a_key_of_the_dictionary_is_not_this_rules_business(tmp_path):
    """A key is a NAME - `naming/yo` judges it; a rule about labels must not double up."""
    diags = _findings(_lint(
        tmp_path, _DICTIONARY.format(strings="    ПоказатьУдалённые: Показать удаленные\n"),
        name="Словарь.yaml",
    ))

    assert diags == []


def test_a_binding_is_not_text(tmp_path):
    """A computed label is code: the name behind it is judged where it is declared."""
    diags = _findings(_lint(tmp_path, _FORM.format(
        lines="            Представление: =ИдётЗагрузка()\n")))

    assert diags == []


def test_a_reference_to_a_localized_string_is_not_text(tmp_path):
    diags = _findings(_lint(tmp_path, _FORM.format(
        lines="            Представление: $Словарь.ПоказатьУдалённые\n")))

    assert diags == []


def test_a_technical_string_is_left_alone(tmp_path):
    """A path is an address, not a phrase - the set of judged properties is curated."""
    diags = _findings(_lint(tmp_path, _FORM.format(
        lines="            Путь: \"/раздел/ёлки\"\n")))

    assert diags == []


def test_the_word_that_carries_the_meaning_comes_without_a_fix(tmp_path):
    """The word `всё` is not `все`: the replacement would change the phrase, so a human decides."""
    diags = _findings(_lint(tmp_path, _FORM.format(
        lines="            Представление: \"Показать всё\"\n")))

    assert len(diags) == 1 and diags[0].fix is None
    assert "всё" in diags[0].message


def test_the_rule_is_off_by_default(tmp_path):
    """Typography is a project convention: the engine ships the rule, a profile turns it on."""
    from xbsl.engine import SEVERITY_OVERRIDES

    if RULE in SEVERITY_OVERRIDES:  # pragma: no cover - depends on the installed plugin
        return
    diags = _findings(_lint(tmp_path, _FORM.format(
        lines="            Представление: Показать удалённые\n"), select=()))

    assert diags == []
