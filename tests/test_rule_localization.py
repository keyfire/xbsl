"""Checks of the localization rules (xbsl/rules/yaml_localization.py)."""

from xbsl import engine
from xbsl.cli import discover
from xbsl.rules import localization

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


def test_map_phase_ships_candidates_not_the_file(tmp_path):
    """Факт правила едет между процессами – в нём не должно быть исходника.

    Раньше маппер клал в факт целый SourceFile: пикл рос вместе с проектом, а родитель
    заново токенизировал каждый модуль в редьюсе.
    """
    import pickle

    module = tmp_path / "Модуль.xbsl"
    module.write_text(
        '@ВПроекте\nметод Проба(): Булево\n    возврат Словарь.Новость() == "Новость"\n;\n',
        encoding="utf-8",
    )
    fact = localization._compare_mapper(engine.load(module))
    assert fact is not None and "source" not in fact
    assert [span["what"] for span in fact["spans"]] == ["Словарь.Новость"]

    # Размер факта не зависит от размера модуля – только от числа сравнений.
    padding = "".join("метод Пустой%d()\n;\n" % n for n in range(300))
    big = tmp_path / "Большой.xbsl"
    big.write_text(module.read_text(encoding="utf-8") + padding, encoding="utf-8")
    small_blob = pickle.dumps(fact, protocol=pickle.HIGHEST_PROTOCOL)
    big_blob = pickle.dumps(
        localization._compare_mapper(engine.load(big)), protocol=pickle.HIGHEST_PROTOCOL
    )
    assert len(big_blob) == len(small_blob)
    assert len(big.read_bytes()) > 20 * len(module.read_bytes())


def test_module_without_comparisons_contributes_nothing(tmp_path):
    """Кандидаты сужены сравнением: обычный модуль в редьюс не едет вовсе."""
    module = tmp_path / "Модуль.xbsl"
    module.write_text(
        "@ВПроекте\nметод Проба(): Строка\n    возврат Модуль.Значение()\n;\n", encoding="utf-8"
    )
    assert localization._compare_mapper(engine.load(module)) is None


# --- yaml/localization-ref-to-template ---------------------------------------------------

REF_RULE = "yaml/localization-ref-to-template"

_REF_DICT = (
    "ВидЭлемента: ЛокализованныеСтроки\n"
    "Ид: dddddddd-1111-2222-3333-444444444444\n"
    "Имя: Словарь\n"
    "Строки:\n"
    "    Заголовок: Каталог\n"
    "Шаблоны:\n"
    "    ВсеМатериалы: Все материалы\n"
    "    Расширена: \"Расширена (до $0)\"\n"
)


def _refs(tmp_path, value, dictionary=_REF_DICT):
    (tmp_path / "Словарь.yaml").write_text(dictionary, encoding="utf-8")
    (tmp_path / "Ф.yaml").write_text(
        "ВидЭлемента: КомпонентИнтерфейса\n"
        "Имя: Ф\n"
        "Содержимое:\n"
        "    -\n"
        "        Тип: Надпись\n"
        f"        Значение: {value}\n",
        encoding="utf-8",
    )
    return engine.run(discover([str(tmp_path)]), select={REF_RULE})


def test_reference_to_a_template_key_flagged(tmp_path):
    """The apply refuses over it: a reference resolves against the strings section alone."""
    d = _refs(tmp_path, "$Словарь.ВсеМатериалы")
    assert [x.rule_id for x in d] == [REF_RULE]
    assert "ВсеМатериалы" in d[0].message
    assert (d[0].line, d[0].col) == (6, 19)  # the reference itself


def test_reference_to_a_strings_key_is_silent(tmp_path):
    d = _refs(tmp_path, "$Словарь.Заголовок")
    assert d == []


def test_a_template_key_nobody_references_is_left_alone(tmp_path):
    """Reconnaissance: a live project keeps placeholder-less keys in the templates section
    on purpose - code calls them, and only a yaml REFERENCE goes through the strings lookup."""
    d = _refs(tmp_path, "Просто текст")
    assert d == []


def test_a_key_declared_in_both_sections_is_silent(tmp_path):
    """The strings section answers the reference - the template namesake is not the target."""
    dictionary = _REF_DICT.replace(
        "    Заголовок: Каталог\n", "    Заголовок: Каталог\n    ВсеМатериалы: Все материалы\n"
    )
    d = _refs(tmp_path, "$Словарь.ВсеМатериалы", dictionary=dictionary)
    assert d == []


def test_an_unknown_key_is_not_this_rule(tmp_path):
    """A key the dictionary declares nowhere is another defect (a typo, a foreign library)."""
    d = _refs(tmp_path, "$Словарь.НетТакого")
    assert d == []


def test_a_foreign_dictionary_is_left_alone(tmp_path):
    d = _refs(tmp_path, "$Чужой.ВсеМатериалы")
    assert d == []
