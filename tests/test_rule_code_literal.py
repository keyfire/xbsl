"""Rule conventions/untranslated-code-literal."""

import pytest

from xbsl import engine, i18n

RULE = "conventions/untranslated-code-literal"


@pytest.fixture(autouse=True)
def _ru_lang():
    # The tests read the Russian text; the environment language must not sway them.
    i18n.set_lang("ru")
    yield
    i18n.set_lang(None)


def _descriptor(languages="[Русский, Английский]"):
    return engine.load_text(
        "Проект.yaml",
        f"Ид: 019ef4c8-232f-7f33-9da6-c3604720b33c\nИмя: site\n"
        f"ЯзыкиЛокализации: {languages}\n",
    )


def _event(name="ОшибкаСервиса", prop="Подробности"):
    return engine.load_text(
        f"{name}.yaml",
        f"ВидЭлемента: СобытиеЖурналаСобытий\nИд: 019ef4c8-232f-7f33-9da6-c3604720b340\n"
        f"Имя: {name}\nВидСобытия: Ошибка\nХарактерОшибки: ДляПоддержки\n"
        f"Важность: Обычная\nШаблонПредставления: Отказ %{{{prop}}}\n"
        f"Свойства:\n    -\n        Ид: 019ef4c8-232f-7f33-9da6-c3604720b341\n"
        f"        Имя: {prop}\n        Тип: Строка\n",
    )


def _dictionary(name="Словарь", key="ОтказСервиса", value="Сервис недоступен, попробуйте позже"):
    return engine.load_text(
        f"{name}.yaml",
        f"ВидЭлемента: ЛокализованныеСтроки\nИд: 019ef4c8-232f-7f33-9da6-c3604720b342\n"
        f"Имя: {name}\nСтроки:\n    {key}: {value}\n",
    )


def _module(name, code):
    return engine.load_text(f"{name}.xbsl", code)


def _lint(*sources, languages="[Русский, Английский]"):
    return engine.run_sources([_descriptor(languages), *sources], select={RULE})


def test_message_call_is_a_sink():
    found = _lint(_module("М", 'метод Т()\n    Сообщить("Не заполнен адрес сайта")\n;\n'))
    assert len(found) == 1
    assert "сообщение пользователю" in found[0].message


def test_single_language_project_is_silent():
    found = _lint(
        _module("М", 'метод Т()\n    Сообщить("Не заполнен адрес сайта")\n;\n'),
        languages="[Русский]",
    )
    assert found == []


def test_event_property_is_a_sink():
    code = 'метод Т()\n    новый ОшибкаСервиса(Подробности = "Ответ не разобран совсем").Записать()\n;\n'
    found = _lint(_event(), _module("М", code))
    assert len(found) == 1
    assert "события журнала ОшибкаСервиса" in found[0].message


def test_property_of_a_plain_constructor_is_not_a_sink():
    # The same shape without an event-log event behind it: a structure carries data.
    code = 'метод Т()\n    новый Пара(Подробности = "Ответ не разобран совсем")\n;\n'
    assert _lint(_module("М", code)) == []


def test_forwarded_parameter_makes_the_call_a_finding():
    writer = (
        "метод ЗаписатьОшибку(Текст: Строка)\n"
        "    новый ОшибкаСервиса(Подробности = Текст).Записать()\n;\n"
    )
    caller = 'метод Т()\n    Журнал.ЗаписатьОшибку("Сервис ответил отказом")\n;\n'
    found = _lint(_event(), _module("Журнал", writer), _module("М", caller))
    assert len(found) == 1
    assert "через ЗаписатьОшибку()" in found[0].message


def test_namesake_in_another_module_does_not_forward():
    writer = (
        "метод ЗаписатьОшибку(Текст: Строка)\n"
        "    новый ОшибкаСервиса(Подробности = Текст).Записать()\n;\n"
    )
    # The call names ANOTHER module, whose same-named method forwards nothing.
    caller = 'метод Т()\n    Прочий.ЗаписатьОшибку("Сервис ответил отказом")\n;\n'
    other = "метод ЗаписатьОшибку(Текст: Строка)\n    возврат\n;\n"
    found = _lint(_event(), _module("Журнал", writer), _module("Прочий", other),
                  _module("М", caller))
    assert found == []


def test_technical_shapes_are_skipped():
    code = (
        "метод Т()\n"
        '    Сообщить("<div data-testid=Подвал>текст</div>")\n'
        '    Сообщить("%{Кто} (%{Чей})")\n'
        '    Сообщить("Наименование")\n'
        ";\n"
    )
    assert _lint(_module("М", code)) == []


def test_query_text_is_not_a_literal_of_the_code():
    code = (
        "метод Т()\n"
        "    знч В = Запрос{\n"
        "        ВЫБРАТЬ П.Ссылка КАК Ссылка ИЗ Задачи КАК П\n"
        '        ГДЕ П.Наименование == "Первая программа сервиса"\n'
        "    }.Выполнить()\n"
        ";\n"
    )
    assert _lint(_module("М", code)) == []


def test_existing_translation_is_named_in_the_message():
    code = 'метод Т()\n    Сообщить("Сервис недоступен, попробуйте позже")\n;\n'
    found = _lint(_dictionary(), _module("М", code))
    assert len(found) == 1
    assert "Словарь.ОтказСервиса" in found[0].message


def test_rule_is_off_by_default():
    info = next(r for r in engine.RULES if r.id == RULE)
    assert info.enabled_by_default is False
    assert info.off_reason
