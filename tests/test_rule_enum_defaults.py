"""Checks of the yaml/enum-default-value rule (enumeration defaults in yaml)."""

import pytest

from xbsl import engine
from xbsl.cli import discover

_ENUM_YAML = (
    "ВидЭлемента: Перечисление\nИмя: ВидимостьКапчи\nЭлементы:\n"
    "    -\n        Имя: Невидимая\n    -\n        Имя: Видимая\n"
)

_RULE = "yaml/enum-default-value"


def _run_rule(tmp_path, extra_yaml, enum_yaml=_ENUM_YAML):
    (tmp_path / "ВидимостьКапчи.yaml").write_text(enum_yaml, encoding="utf-8")
    (tmp_path / "Ф.yaml").write_text(extra_yaml, encoding="utf-8")
    return engine.run(discover([str(tmp_path)]), select={_RULE})


def _has(diags, rule_id=_RULE):
    return any(d.rule_id == rule_id for d in diags)


def test_qualified_default_on_constant_flagged(tmp_path):
    # the production shape: a constants-set constant with the type-prefixed default
    d = _run_rule(
        tmp_path,
        "ВидЭлемента: НаборКонстант\nИмя: Настройки\nКонстанты:\n"
        "    -\n        Имя: ВидимостьКапчи\n        Тип: ВидимостьКапчи?\n"
        "        ЗначениеПоУмолчанию: ВидимостьКапчи.Невидимая\n",
    )
    assert len(d) == 1 and d[0].rule_id == _RULE
    assert "'Невидимая'" in d[0].message
    # the exact position of the value in the default-value line
    assert (d[0].line, d[0].col) == (7, 30)


def test_bare_declared_default_not_flagged(tmp_path):
    d = _run_rule(
        tmp_path,
        "ВидЭлемента: НаборКонстант\nИмя: Настройки\nКонстанты:\n"
        "    -\n        Имя: ВидимостьКапчи\n        Тип: ВидимостьКапчи?\n"
        "        ЗначениеПоУмолчанию: Невидимая\n",
    )
    assert not _has(d)


def test_bare_unknown_default_flagged(tmp_path):
    d = _run_rule(
        tmp_path,
        "ВидЭлемента: НаборКонстант\nИмя: Настройки\nКонстанты:\n"
        "    -\n        Имя: ВидимостьКапчи\n        Тип: ВидимостьКапчи?\n"
        "        ЗначениеПоУмолчанию: Прозрачная\n",
    )
    assert len(d) == 1 and "Прозрачная" in d[0].message and "ВидимостьКапчи" in d[0].message


def test_catalog_attribute_judged_like_a_constant(tmp_path):
    # the metamodel types the pair identically for every attribute descriptor - a catalog
    # attribute is judged exactly like a constants-set constant
    d = _run_rule(
        tmp_path,
        "ВидЭлемента: Справочник\nИмя: Письма\nРеквизиты:\n"
        "    -\n        Имя: Вид\n        Тип: ВидимостьКапчи\n"
        "        ЗначениеПоУмолчанию: ВидимостьКапчи.Видимая\n",
    )
    assert len(d) == 1 and "'Видимая'" in d[0].message


def test_string_typed_dotted_default_not_flagged(tmp_path):
    # a dotted default of a non-enumeration type is an ordinary string value
    d = _run_rule(
        tmp_path,
        "ВидЭлемента: НаборКонстант\nИмя: Настройки\nКонстанты:\n"
        "    -\n        Имя: Заголовок\n        Тип: Строка\n"
        "        ЗначениеПоУмолчанию: Сайт.Главная\n",
    )
    assert not _has(d)


def test_non_string_default_not_flagged(tmp_path):
    d = _run_rule(
        tmp_path,
        "ВидЭлемента: НаборКонстант\nИмя: Настройки\nКонстанты:\n"
        "    -\n        Имя: Включено\n        Тип: Булево\n"
        "        ЗначениеПоУмолчанию: Истина\n"
        "    -\n        Имя: Предел\n        Тип: Число\n"
        "        ЗначениеПоУмолчанию: 5\n",
    )
    assert not _has(d)


def test_union_and_generic_types_skipped(tmp_path):
    # narrowing: only the bare enumeration name (with or without '?') is judged
    d = _run_rule(
        tmp_path,
        "ВидЭлемента: НаборКонстант\nИмя: Настройки\nКонстанты:\n"
        "    -\n        Имя: А\n        Тип: ВидимостьКапчи|Строка\n"
        "        ЗначениеПоУмолчанию: ВидимостьКапчи.Невидимая\n"
        "    -\n        Имя: Б\n        Тип: Массив<ВидимостьКапчи>\n"
        "        ЗначениеПоУмолчанию: ВидимостьКапчи.Невидимая\n",
    )
    assert not _has(d)


def test_foreign_prefix_skipped(tmp_path):
    # a dotted default whose prefix is not the type name is not the proven mistake
    d = _run_rule(
        tmp_path,
        "ВидЭлемента: НаборКонстант\nИмя: Настройки\nКонстанты:\n"
        "    -\n        Имя: ВидимостьКапчи\n        Тип: ВидимостьКапчи?\n"
        "        ЗначениеПоУмолчанию: ДругойТип.Невидимая\n",
    )
    assert not _has(d)


def test_same_text_default_elsewhere_skipped(tmp_path):
    # the same default string on a string-typed field: textual positions cannot tell the
    # two lines apart, so the value is skipped in this file
    d = _run_rule(
        tmp_path,
        "ВидЭлемента: НаборКонстант\nИмя: Настройки\nКонстанты:\n"
        "    -\n        Имя: ВидимостьКапчи\n        Тип: ВидимостьКапчи?\n"
        "        ЗначениеПоУмолчанию: Прозрачная\n"
        "    -\n        Имя: Заголовок\n        Тип: Строка\n"
        "        ЗначениеПоУмолчанию: Прозрачная\n",
    )
    assert not _has(d)


def test_no_project_enum_declared_silent(tmp_path):
    (tmp_path / "Ф.yaml").write_text(
        "ВидЭлемента: НаборКонстант\nИмя: Настройки\nКонстанты:\n"
        "    -\n        Имя: Вид\n        Тип: ЧужойТип?\n"
        "        ЗначениеПоУмолчанию: ЧужойТип.Значение\n",
        encoding="utf-8",
    )
    d = engine.run(discover([str(tmp_path)]), select={_RULE})
    assert not _has(d)


def test_crlf_default_position(tmp_path):
    (tmp_path / "ВидимостьКапчи.yaml").write_text(_ENUM_YAML, encoding="utf-8")
    (tmp_path / "Ф.yaml").write_bytes(
        "ВидЭлемента: НаборКонстант\r\nИмя: Настройки\r\nКонстанты:\r\n"
        "    -\r\n        Имя: Вид\r\n        Тип: ВидимостьКапчи?\r\n"
        "        ЗначениеПоУмолчанию: ВидимостьКапчи.Невидимая\r\n".encode("utf-8")
    )
    d = engine.run(discover([str(tmp_path)]), select={_RULE})
    assert len(d) == 1 and (d[0].line, d[0].col) == (7, 30)


@pytest.mark.needs_data  # the English key spellings come from the metamodel
def test_english_tree_judged_and_translator_hole_caught(tmp_path):
    # the translated tree keeps English element names; a default left in Russian names no
    # declared value and fails the server compilation - a true finding, not a false one
    enum_en = (
        "ElementKind: Enumeration\nName: CaptchaVisibility\nItems:\n"
        "    -\n        Name: Invisible\n    -\n        Name: Visible\n"
    )
    hole = _run_rule(
        tmp_path,
        "ElementKind: ConstantsSet\nName: Settings\nConstants:\n"
        "    -\n        Name: CaptchaVisibility\n        Type: CaptchaVisibility?\n"
        "        DefaultValue: Невидимая\n",
        enum_yaml=enum_en,
    )
    assert len(hole) == 1 and "Невидимая" in hole[0].message
    qualified = _run_rule(
        tmp_path,
        "ElementKind: ConstantsSet\nName: Settings\nConstants:\n"
        "    -\n        Name: CaptchaVisibility\n        Type: CaptchaVisibility?\n"
        "        DefaultValue: CaptchaVisibility.Invisible\n",
        enum_yaml=enum_en,
    )
    assert len(qualified) == 1 and "'Invisible'" in qualified[0].message
    clean = _run_rule(
        tmp_path,
        "ElementKind: ConstantsSet\nName: Settings\nConstants:\n"
        "    -\n        Name: CaptchaVisibility\n        Type: CaptchaVisibility?\n"
        "        DefaultValue: Invisible\n",
        enum_yaml=enum_en,
    )
    assert not _has(clean)
