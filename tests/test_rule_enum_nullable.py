"""Проверки правила yaml/enum-needs-nullable (перечисление в Тип: без nullable)."""

from xbsllint import engine
from xbsllint.cli import discover

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
    assert (d[0].line, d[0].col) == (6, 14)  # точная позиция имени в 'Тип: ВидСообщения'


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
    # позиция – начало аргумента внутри 'Тип: ПолеВвода<ВидСообщения>'
    assert (d[0].line, d[0].col) == (6, 24)


def test_input_field_nullable_argument_not_flagged(tmp_path):
    d = _вид(
        tmp_path,
        "ВидЭлемента: КомпонентИнтерфейса\nИмя: Ф\nСодержимое:\n"
        "    -\n        Имя: ПолеВид\n        Тип: ПолеВвода<ВидСообщения?>\n",
    )
    assert not _has(d)


def test_explicit_default_value_not_flagged(tmp_path):
    # ЗначениеПоУмолчанию рядом с Тип задаёт дефолт явно - легальная форма без '?'
    d = _вид(
        tmp_path,
        "ВидЭлемента: Справочник\nИмя: Письма\nРеквизиты:\n"
        "    -\n        Имя: Вид\n        Тип: ВидСообщения\n"
        "        ЗначениеПоУмолчанию: Важное\n",
    )
    assert not _has(d)


def test_enum_default_element_not_flagged(tmp_path):
    # у перечисления есть элемент с ПоУмолчанию: Истина - дефолт есть у самого типа
    d = _вид(
        tmp_path,
        "ВидЭлемента: Справочник\nИмя: Письма\nРеквизиты:\n"
        "    -\n        Имя: Вид\n        Тип: ВидСообщения\n",
        enum_yaml=_ВИД_YAML_С_ДЕФОЛТОМ,
    )
    assert not _has(d)


def test_union_and_other_generics_skipped(tmp_path):
    # сужение: объединения и другие дженерики не флагаются
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
    # строка 'Тип: ВидСообщения' внутри литерального блока - текст, а не тип
    d = _вид(
        tmp_path,
        "ВидЭлемента: КомпонентИнтерфейса\nИмя: Ф\nОписание: |\n    Тип: ВидСообщения\n",
    )
    assert not _has(d)


def test_same_value_guarded_elsewhere_skipped(tmp_path):
    # одно и то же значение и с дефолтом, и без: текстовые позиции неразличимы - пропуск
    d = _вид(
        tmp_path,
        "ВидЭлемента: Справочник\nИмя: Письма\nРеквизиты:\n"
        "    -\n        Имя: А\n        Тип: ВидСообщения\n"
        "        ЗначениеПоУмолчанию: Важное\n"
        "    -\n        Имя: Б\n        Тип: ВидСообщения\n",
    )
    assert not _has(d)


def test_crlf_positions(tmp_path):
    # файл с CRLF: позиция значения находится, диагностика одна
    (tmp_path / "ВидСообщения.yaml").write_text(_ВИД_YAML, encoding="utf-8")
    (tmp_path / "Ф.yaml").write_bytes(
        "ВидЭлемента: Справочник\r\nИмя: Письма\r\nРеквизиты:\r\n"
        "    -\r\n        Имя: Вид\r\n        Тип: ВидСообщения\r\n".encode("utf-8")
    )
    d = engine.run(discover([str(tmp_path)]), select={_RULE})
    assert len(d) == 1 and (d[0].line, d[0].col) == (6, 14)
