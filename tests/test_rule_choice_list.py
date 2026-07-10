"""Проверки правила yaml/choice-needs-static-list (данные платформы не нужны)."""

from xbsllint import engine

_SELECT = {"yaml/choice-needs-static-list"}


def _lint(content, name="Форма.yaml"):
    return engine.run_sources([engine.load_text(name, content)], select=_SELECT)


def _wrap(*components):
    """Объект-форма с перечисленными компонентами в Содержимое."""
    body = "".join(components)
    return (
        "ВидЭлемента: КомпонентИнтерфейса\n"
        "Ид: 11111111-2222-3333-4444-555555555555\n"
        "Имя: Форма\n"
        "Интерфейс:\n"
        "    Тип: Форма\n"
        "    Содержимое:\n" + body
    )


_CHOICE_WITH_LIST = (
    "        -\n"
    "            Тип: ВыборЗначения<Строка>\n"
    "            Имя: ВыборВариант\n"
    "            Значение: =ВариантТекст\n"
    "            СписокВыбора:\n"
    "                Тип: Массив<Строка|ЭлементСпискаЗначений<Строка>>\n"
    "                Значение:\n"
    "                    - Первый\n"
    "                    - Второй\n"
)

_CHOICE_WITHOUT_LIST = (
    "        -\n"
    "            Тип: ВыборЗначения<Строка>\n"
    "            Имя: ВыборРоль\n"
    "            Значение: =РольТекст\n"
)


def test_missing_list_flagged_with_position():
    d = _lint(_wrap(_CHOICE_WITHOUT_LIST))
    assert len(d) == 1
    assert d[0].rule_id == "yaml/choice-needs-static-list"
    # Позиция – строка узла `Тип: ВыборЗначения<Строка>` (8-я), колонка значения.
    assert d[0].line == 8
    assert "СписокВыбора" in d[0].message


def test_static_list_ok():
    assert _lint(_wrap(_CHOICE_WITH_LIST)) == []


def test_mixed_nodes_only_bare_one_flagged():
    # Два одинаковых типа: со списком и без – ловится только второй, по своей позиции.
    d = _lint(_wrap(_CHOICE_WITH_LIST, _CHOICE_WITHOUT_LIST))
    assert len(d) == 1
    assert d[0].line == 17  # узел без списка идёт после узла со списком


def test_binding_value_counts_as_present():
    # СписокВыбора биндингом – ключ есть, содержимое не проверяем.
    content = _wrap(
        "        -\n"
        "            Тип: ВыборЗначения<Строка>\n"
        "            СписокВыбора: =Варианты\n"
    )
    assert _lint(content) == []


def test_enum_and_project_types_skipped():
    # Не-примитивный параметр (перечисление/проектный тип) – платформа строит список сама.
    content = _wrap(
        "        -\n"
        "            Тип: ВыборЗначения<КатегорияПрограммы>\n"
        "        -\n"
        "            Тип: ВыборЗначения<Массив<КатегорияПрограммы>>\n"
    )
    assert _lint(content) == []


def test_bare_and_nullable_variants():
    # Голый ВыборЗначения – пропуск (тип неизвестен); nullable-примитив – диагностика.
    content = _wrap(
        "        -\n"
        "            Тип: ВыборЗначения\n"
        "        -\n"
        "            Тип: ВыборЗначения<Строка?>\n"
        "        -\n"
        "            Тип: ВыборЗначения<Число|?>\n"
    )
    d = _lint(content)
    assert [x.line for x in d] == [10, 12]


def test_array_primitive_flagged():
    d = _lint(_wrap(
        "        -\n"
        "            Тип: ВыборЗначения<Массив<Строка>>\n"
    ))
    assert len(d) == 1


def test_non_object_yaml_skipped():
    # Файл без ВидЭлемента (структурный) не проверяется.
    content = "Имя: Проект\nСодержимое:\n    - Тип: ВыборЗначения<Строка>\n"
    assert _lint(content) == []


def test_crlf_position():
    content = _wrap(_CHOICE_WITHOUT_LIST).replace("\n", "\r\n")
    d = _lint(content)
    assert len(d) == 1 and d[0].line == 8


def test_off_when_not_selected_by_default_run():
    # Правило включено по умолчанию – без select тоже находится.
    d = engine.run_sources([engine.load_text("Форма.yaml", _wrap(_CHOICE_WITHOUT_LIST))],
                           select={"yaml"})
    assert any(x.rule_id == "yaml/choice-needs-static-list" for x in d)
