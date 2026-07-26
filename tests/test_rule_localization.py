"""Checks of the localization rules (xbsl/rules/yaml_localization.py)."""

from xbsl import engine
from xbsl.cli import discover

RULE = "yaml/placeholder-key-in-strings"

_DICT = """ВидЭлемента: ЛокализованныеСтроки
Ид: cccccccc-1111-2222-3333-444444444444
Имя: Словарь
Строки:
{strings}Шаблоны:
{templates}"""


def _has(diags, rule_id):
    return any(d.rule_id == rule_id for d in diags)


def _dictionary(tmp_path, strings, templates="    Готовый: \"Расширена (до $0)\"\n"):
    (tmp_path / "Словарь.yaml").write_text(
        _DICT.format(strings=strings, templates=templates), encoding="utf-8"
    )
    return engine.run(discover([str(tmp_path)]), select={RULE})


def test_placeholder_in_strings_flagged(tmp_path):
    d = _dictionary(tmp_path, "    СПодстановкой: \"Код ошибки $0.\"\n")
    assert any(x.rule_id == RULE and "СПодстановкой" in x.message for x in d)


def test_placeholder_in_templates_ok(tmp_path):
    """The twin in the same file: the very same text is correct in Шаблоны."""
    d = _dictionary(tmp_path, "    Простая: Простой текст\n")
    assert not _has(d, RULE)


def test_plain_string_ok(tmp_path):
    d = _dictionary(tmp_path, "    Простая: Простой текст\n", templates="    Другой: Текст\n")
    assert not _has(d, RULE)


def test_second_placeholder_flagged(tmp_path):
    d = _dictionary(tmp_path, "    Двойная: \"С $0 по $1\"\n")
    assert any(x.rule_id == RULE for x in d)


def test_english_sections_flagged(tmp_path):
    (tmp_path / "Dict.yaml").write_text(
        "ElementKind: LocalizedStrings\n"
        "Ид: cccccccc-1111-2222-3333-444444444445\n"
        "Name: Dict\n"
        "Strings:\n"
        "    WithPlaceholder: \"Error code $0.\"\n"
        "Templates:\n"
        "    Ready: \"Extended (until $0)\"\n",
        encoding="utf-8",
    )
    d = engine.run(discover([str(tmp_path)]), select={RULE})
    assert any(x.rule_id == RULE and "WithPlaceholder" in x.message for x in d)


def test_other_kind_not_checked(tmp_path):
    """A `$0` in a yaml of another kind is not a dictionary entry."""
    (tmp_path / "Модуль.yaml").write_text(
        "ВидЭлемента: ОбщийМодуль\nИмя: Модуль\nОкружение: Сервер\n"
        "Строки:\n    Ключ: \"текст $0\"\n",
        encoding="utf-8",
    )
    d = engine.run(discover([str(tmp_path)]), select={RULE})
    assert not _has(d, RULE)


# --- code/compare-with-localized -------------------------------------------------------

COMPARE = "code/compare-with-localized"

_DICT_ONLY = """ВидЭлемента: ЛокализованныеСтроки
Ид: cccccccc-1111-2222-3333-444444444446
Имя: Словарь
Строки:
    Новость: Новость
    Статья: Статья
"""

_MODULE_YAML = """ВидЭлемента: ОбщийМодуль
Ид: dddddddd-1111-2222-3333-444444444444
Имя: Модуль
Окружение: Сервер
"""


def _project(tmp_path, body):
    (tmp_path / "Словарь.yaml").write_text(_DICT_ONLY, encoding="utf-8")
    (tmp_path / "Модуль.yaml").write_text(_MODULE_YAML, encoding="utf-8")
    (tmp_path / "Модуль.xbsl").write_text(
        f"@ВПроекте\nметод Проба(Вид: Строка): Булево\n    возврат {body}\n;\n",
        encoding="utf-8",
    )
    return engine.run(discover([str(tmp_path)]), select={COMPARE})


def test_localized_compared_with_literal_flagged(tmp_path):
    d = _project(tmp_path, 'Словарь.Новость() == "Новость"')
    assert any(x.rule_id == COMPARE and "Словарь.Новость" in x.message for x in d)


def test_literal_on_the_left_flagged(tmp_path):
    d = _project(tmp_path, '"Новость" != Словарь.Новость()')
    assert _has(d, COMPARE)


def test_two_localized_flagged(tmp_path):
    d = _project(tmp_path, "Словарь.Новость() == Словарь.Статья()")
    assert any(x.rule_id == COMPARE and "двух" in x.message.lower() for x in d)


def test_presentation_compared_with_literal_flagged(tmp_path):
    d = _project(tmp_path, 'Вид.Представление() == "Новость"')
    assert any(x.rule_id == COMPARE and "Представление" in x.message for x in d)


def test_comparison_of_values_ok(tmp_path):
    d = _project(tmp_path, "Вид == Вид")
    assert not _has(d, COMPARE)


def test_localized_against_variable_not_checked(tmp_path):
    """Deliberately narrow: what the variable holds is invisible to a token check."""
    d = _project(tmp_path, "Вид == Словарь.Новость()")
    assert not _has(d, COMPARE)


def test_localized_used_without_comparison_ok(tmp_path):
    (tmp_path / "Словарь.yaml").write_text(_DICT_ONLY, encoding="utf-8")
    (tmp_path / "Модуль.yaml").write_text(_MODULE_YAML, encoding="utf-8")
    (tmp_path / "Модуль.xbsl").write_text(
        "@ВПроекте\nметод Проба(): Строка\n    возврат Словарь.Новость()\n;\n",
        encoding="utf-8",
    )
    d = engine.run(discover([str(tmp_path)]), select={COMPARE})
    assert not _has(d, COMPARE)


def test_call_of_a_module_that_is_not_a_dictionary_ok(tmp_path):
    """The same shape on a common module is an ordinary call, not a localized value."""
    (tmp_path / "Модуль.yaml").write_text(_MODULE_YAML, encoding="utf-8")
    (tmp_path / "Модуль.xbsl").write_text(
        '@ВПроекте\nметод Проба(): Булево\n    возврат Модуль.Что() == "Новость"\n;\n',
        encoding="utf-8",
    )
    d = engine.run(discover([str(tmp_path)]), select={COMPARE})
    assert not _has(d, COMPARE)
