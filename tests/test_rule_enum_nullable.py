"""Checks of the yaml/enum-needs-nullable rule (an enum in Тип: without nullable)."""

import pytest

from xbsl import engine
from xbsl.cli import discover

_ВИД_YAML = (
    "ВидЭлемента: Перечисление\nИмя: ВидСообщения\nЭлементы:\n"
    "    -\n        Имя: Важное\n    -\n        Имя: Обычное\n"
)

_ВИД_YAML_С_ДЕФОЛТОМ = (
    "ВидЭлемента: Перечисление\nИмя: ВидСообщения\nЭлементы:\n"
    "    -\n        Имя: Важное\n        ПоУмолчанию: Истина\n"
    "    -\n        Имя: Обычное\n"
)

_RULE = "yaml/enum-needs-nullable"


def _вид(tmp_path, extra_yaml, enum_yaml=_ВИД_YAML):
    (tmp_path / "ВидСообщения.yaml").write_text(enum_yaml, encoding="utf-8")
    (tmp_path / "Ф.yaml").write_text(extra_yaml, encoding="utf-8")
    return engine.run(discover([str(tmp_path)]), select={_RULE})


def _has(diags, rule_id=_RULE):
    return any(d.rule_id == rule_id for d in diags)


def test_bare_enum_attribute_flagged(tmp_path):
    d = _вид(
        tmp_path,
        "ВидЭлемента: Справочник\nИмя: Письма\nРеквизиты:\n"
        "    -\n        Имя: Вид\n        Тип: ВидСообщения\n",
    )
    assert len(d) == 1 and d[0].rule_id == _RULE
    assert "ВидСообщения?" in d[0].message
    assert (d[0].line, d[0].col) == (6, 14)  # the exact position of the name in 'Тип: ВидСообщения'


def test_nullable_enum_attribute_not_flagged(tmp_path):
    d = _вид(
        tmp_path,
        "ВидЭлемента: Справочник\nИмя: Письма\nРеквизиты:\n"
        "    -\n        Имя: Вид\n        Тип: ВидСообщения?\n",
    )
    assert not _has(d)


def test_tabular_section_attribute_flagged(tmp_path):
    d = _вид(
        tmp_path,
        "ВидЭлемента: Справочник\nИмя: Письма\nТабличныеЧасти:\n"
        "    -\n        Имя: Строки\n        Реквизиты:\n"
        "            -\n                Имя: Вид\n                Тип: ВидСообщения\n",
    )
    assert len(d) == 1 and d[0].line == 9


def test_component_property_flagged(tmp_path):
    d = _вид(
        tmp_path,
        "ВидЭлемента: КомпонентИнтерфейса\nИмя: Ф\nСвойства:\n"
        "    -\n        Имя: Вид\n        Тип: ВидСообщения\n",
    )
    assert len(d) == 1


def test_input_field_argument_flagged(tmp_path):
    d = _вид(
        tmp_path,
        "ВидЭлемента: КомпонентИнтерфейса\nИмя: Ф\nСодержимое:\n"
        "    -\n        Имя: ПолеВид\n        Тип: ПолеВвода<ВидСообщения>\n",
    )
    assert len(d) == 1 and "ПолеВвода<ВидСообщения?>" in d[0].message
    # the position is the start of the argument inside 'Тип: ПолеВвода<ВидСообщения>'
    assert (d[0].line, d[0].col) == (6, 24)


def test_input_field_nullable_argument_not_flagged(tmp_path):
    d = _вид(
        tmp_path,
        "ВидЭлемента: КомпонентИнтерфейса\nИмя: Ф\nСодержимое:\n"
        "    -\n        Имя: ПолеВид\n        Тип: ПолеВвода<ВидСообщения?>\n",
    )
    assert not _has(d)


def test_explicit_default_value_not_flagged(tmp_path):
    # ЗначениеПоУмолчанию next to Тип sets the default explicitly - a legal form without '?'
    d = _вид(
        tmp_path,
        "ВидЭлемента: Справочник\nИмя: Письма\nРеквизиты:\n"
        "    -\n        Имя: Вид\n        Тип: ВидСообщения\n"
        "        ЗначениеПоУмолчанию: Важное\n",
    )
    assert not _has(d)


def test_enum_default_element_not_flagged(tmp_path):
    # the enum has an element with ПоУмолчанию: Истина - the type itself has a default
    d = _вид(
        tmp_path,
        "ВидЭлемента: Справочник\nИмя: Письма\nРеквизиты:\n"
        "    -\n        Имя: Вид\n        Тип: ВидСообщения\n",
        enum_yaml=_ВИД_YAML_С_ДЕФОЛТОМ,
    )
    assert not _has(d)


def test_union_and_other_generics_skipped(tmp_path):
    # narrowing: unions and other generics are not flagged
    d = _вид(
        tmp_path,
        "ВидЭлемента: Справочник\nИмя: Письма\nРеквизиты:\n"
        "    -\n        Имя: А\n        Тип: ВидСообщения|Строка\n"
        "    -\n        Имя: Б\n        Тип: Массив<ВидСообщения>\n",
    )
    assert not _has(d)


def test_non_element_file_skipped(tmp_path):
    (tmp_path / "ВидСообщения.yaml").write_text(_ВИД_YAML, encoding="utf-8")
    (tmp_path / "конфиг.yaml").write_text("Тип: ВидСообщения\n", encoding="utf-8")
    d = engine.run(discover([str(tmp_path)]), select={_RULE})
    assert not _has(d)


def test_block_scalar_not_scanned(tmp_path):
    # the line 'Тип: ВидСообщения' inside a literal block is text, not a type
    d = _вид(
        tmp_path,
        "ВидЭлемента: КомпонентИнтерфейса\nИмя: Ф\nОписание: |\n    Тип: ВидСообщения\n",
    )
    assert not _has(d)


def test_same_value_guarded_elsewhere_skipped(tmp_path):
    # the same value both with and without a default: text positions are indistinguishable - skip
    d = _вид(
        tmp_path,
        "ВидЭлемента: Справочник\nИмя: Письма\nРеквизиты:\n"
        "    -\n        Имя: А\n        Тип: ВидСообщения\n"
        "        ЗначениеПоУмолчанию: Важное\n"
        "    -\n        Имя: Б\n        Тип: ВидСообщения\n",
    )
    assert not _has(d)


def test_typed_value_of_a_filter_element_not_flagged(tmp_path):
    # `Значение: {Тип: ..., Значение: ...}` names the type of a literal (topics/dynamic-list);
    # the compiler rejects 'ВидСообщения?' there, so the advice would break working code
    d = _вид(
        tmp_path,
        "ВидЭлемента: КомпонентИнтерфейса\nИмя: Ф\nСодержимое:\n"
        "    -\n        Тип: Таблица<ДинамическийСписок>\n        Имя: Таблица\n"
        "        Источник:\n            Фильтр:\n                Элементы:\n"
        "                    -\n                        Тип: ЭлементФильтра\n"
        "                        Поле: Вид\n"
        "                        Значение:\n"
        "                            Тип: ВидСообщения\n"
        "                            Значение: Важное\n",
    )
    assert not _has(d)


def test_attribute_named_value_is_still_flagged(tmp_path):
    # the guard is the typed-literal SHAPE, not the key name: a declaration under `Значение`
    # that carries no value of its own stays a declaration
    d = _вид(
        tmp_path,
        "ВидЭлемента: КомпонентИнтерфейса\nИмя: Ф\nСодержимое:\n"
        "    -\n        Тип: Группа\n        Значение:\n"
        "            Тип: ВидСообщения\n",
    )
    assert len(d) == 1 and d[0].line == 7


@pytest.mark.needs_data  # the English spellings come from terms.json
def test_english_source_is_judged_and_its_typed_value_skipped(tmp_path):
    # the same pair spelled in English: the declaration is caught, the typed value is not
    # the platform spells the kind `Enum`, not `Enumeration` - the term dictionary names the pair
    enum_en = (
        "ElementKind: Enum\nName: MessageKind\nItems:\n"
        "    -\n        Name: Important\n    -\n        Name: Plain\n"
    )
    flagged = _вид(
        tmp_path,
        "ElementKind: Catalog\nName: Letters\nAttributes:\n"
        "    -\n        Name: Kind\n        Type: MessageKind\n",
        enum_yaml=enum_en,
    )
    assert len(flagged) == 1 and "MessageKind?" in flagged[0].message
    clean = _вид(
        tmp_path,
        "ElementKind: InterfaceComponent\nName: F\nContent:\n"
        "    -\n        Type: FilterElement\n        Field: Kind\n"
        "        Value:\n            Type: MessageKind\n            Value: Important\n",
        enum_yaml=enum_en,
    )
    assert not _has(clean)


@pytest.mark.needs_data  # the English spellings come from terms.json
def test_english_default_value_guards_and_english_input_field_advice(tmp_path):
    enum_en = (
        "ElementKind: Enum\nName: MessageKind\nItems:\n"
        "    -\n        Name: Important\n    -\n        Name: Plain\n"
    )
    guarded = _вид(
        tmp_path,
        "ElementKind: Catalog\nName: Letters\nAttributes:\n"
        "    -\n        Name: Kind\n        Type: MessageKind\n"
        "        DefaultValue: Important\n",
        enum_yaml=enum_en,
    )
    assert not _has(guarded)
    d = _вид(
        tmp_path,
        "ElementKind: InterfaceComponent\nName: F\nContent:\n"
        "    -\n        Name: KindField\n        Type: InputField<MessageKind>\n",
        enum_yaml=enum_en,
    )
    # the advice keeps the spelling of the file
    assert len(d) == 1 and "InputField<MessageKind?>" in d[0].message
    assert "ПолеВвода" not in d[0].message


def test_crlf_positions(tmp_path):
    # a file with CRLF: the value position is found, a single diagnostic
    (tmp_path / "ВидСообщения.yaml").write_text(_ВИД_YAML, encoding="utf-8")
    (tmp_path / "Ф.yaml").write_bytes(
        "ВидЭлемента: Справочник\r\nИмя: Письма\r\nРеквизиты:\r\n"
        "    -\r\n        Имя: Вид\r\n        Тип: ВидСообщения\r\n".encode("utf-8")
    )
    d = engine.run(discover([str(tmp_path)]), select={_RULE})
    assert len(d) == 1 and (d[0].line, d[0].col) == (6, 14)
