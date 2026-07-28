"""Checks of code/unknown-tabular-member (xbsl/rules/tabular_members.py).

The fixtures repeat the live failure: `.Количество()` on a tabular section's rows passed
the linter (the receiver is typed by project metadata, not by a declaration) and failed
the server apply with `Неизвестный метод "Массив<Задачи.Шаги>.Количество"`.
"""

from xbsl import engine, i18n

RULE = "code/unknown-tabular-member"

_ENTITY = engine.load_text(
    "Задачи.yaml",
    "ВидЭлемента: Справочник\n"
    "Ид: 019ef4c8-232f-7f33-9da6-c3604720b3aa\n"
    "Имя: Задачи\n"
    "ТабличныеЧасти:\n"
    "    -\n"
    "        Ид: 019ef4c8-232f-7f33-9da6-c3604720b3ab\n"
    "        Имя: Шаги\n"
    "        Реквизиты:\n"
    "            -\n"
    "                Ид: 019ef4c8-232f-7f33-9da6-c3604720b3ac\n"
    "                Имя: Название\n"
    "                Тип: Строка\n",
)

_FORM = engine.load_text(
    "ЗадачиФормаОбъекта.yaml",
    "ВидЭлемента: КомпонентИнтерфейса\n"
    "Ид: 019ef4c8-232f-7f33-9da6-c3604720b3ad\n"
    "Имя: ЗадачиФормаОбъекта\n"
    "Наследует:\n"
    "    Тип: ФормаОбъекта<Задачи.Объект>\n",
)


def _lint(*sources):
    return engine.run_sources(list(sources), select={RULE})


def _form_module(body):
    return engine.load_text(
        "ЗадачиФормаОбъекта.xbsl",
        f"@Обработчик\nметод Проверить()\n{body};\n",
    )


def test_object_chain_in_form_module_flagged():
    i18n.set_lang("ru")
    try:
        d = _lint(_ENTITY, _FORM, _form_module(
            "    если Объект.Шаги.Количество() > 4\n        возврат\n    ;\n"))
        assert len(d) == 1
        assert d[0].rule_id == RULE and d[0].severity.value == "error"
        assert "Массив<Задачи.Шаги>" in d[0].message
        assert "Размер" in d[0].message  # the habit hint difflib cannot bridge
        assert d[0].line == 3 and d[0].col == 10
    finally:
        i18n.set_lang(None)


def test_known_member_silent():
    assert _lint(_ENTITY, _FORM, _form_module(
        "    если Объект.Шаги.Размер() > 4\n        возврат\n    ;\n")) == []


def test_bare_section_in_entity_module_flagged():
    d = _lint(_ENTITY, engine.load_text(
        "Задачи.Объект.xbsl",
        "метод ПередЗаписью()\n"
        "    если Шаги.Количество() > 0\n"
        "        знч Всего = этот.Шаги.Размер()\n"
        "    ;\n"
        ";\n",
    ))
    assert len(d) == 1 and d[0].line == 2


def test_this_chain_flagged():
    d = _lint(_ENTITY, engine.load_text(
        "Задачи.Объект.xbsl",
        "метод ПередЗаписью()\n    знч Всего = этот.Шаги.Количество()\n;\n",
    ))
    assert len(d) == 1 and d[0].line == 2


def test_attribute_is_not_judged():
    """Only a declared tabular section types the middle link - an attribute never does."""
    assert _lint(_ENTITY, _FORM, _form_module(
        "    если Объект.Метки.Количество() > 4\n        возврат\n    ;\n")) == []


def test_rebound_name_silences():
    """A method that binds the root or the section name judges nothing through it."""
    assert _lint(_ENTITY, _FORM, _form_module(
        "    знч Объект = ДругоеХранилище()\n"
        "    если Объект.Шаги.Количество() > 4\n        возврат\n    ;\n")) == []
    assert _lint(_ENTITY, engine.load_text(
        "Задачи.Объект.xbsl",
        "метод ПередЗаписью(Шаги: Массив<Строка>)\n"
        "    если Шаги.Количество() > 0\n        возврат\n    ;\n;\n",
    )) == []


def test_module_named_after_section_shadows():
    """Real projects keep modules called after a section - the bare name is the
    module there, and its methods are no business of the array catalog."""
    d = _lint(_ENTITY,
              engine.load_text("Шаги.xbsl",
                               "@ВПроекте\nметод Показать(Ид: Строка): Строка\n"
                               "    возврат Ид\n;\n"),
              engine.load_text("Задачи.xbsl",
                               "метод Опубликовать()\n"
                               "    знч Витрина = Шаги.Показать(\"м1\")\n;\n"))
    assert d == []


def test_form_of_another_entity_is_silent():
    """The form's base type names the entity - a section of a DIFFERENT one stays alone."""
    другая = engine.load_text(
        "Заметки.yaml",
        "ВидЭлемента: Справочник\n"
        "Ид: 019ef4c8-232f-7f33-9da6-c3604720b3ae\n"
        "Имя: Заметки\n"
        "ТабличныеЧасти:\n"
        "    -\n"
        "        Ид: 019ef4c8-232f-7f33-9da6-c3604720b3af\n"
        "        Имя: Разделы\n",
    )
    assert _lint(другая, _FORM, _form_module(
        "    если Объект.Разделы.Количество() > 4\n        возврат\n    ;\n")) == []


def test_message_is_bilingual():
    i18n.set_lang("en")
    try:
        d = _lint(_ENTITY, _FORM, _form_module(
            "    если Объект.Шаги.Количество() > 4\n        возврат\n    ;\n"))
        assert d and "tabular section" in d[0].message
    finally:
        i18n.set_lang(None)
