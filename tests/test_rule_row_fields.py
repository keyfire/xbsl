"""Checks of the code/unknown-row-field rule (a field of a dynamic list row)."""

import builtins

from xbsl import engine

_RULE = "code/unknown-row-field"

_FORM = """\
ВидЭлемента: КомпонентИнтерфейса
Ид: 1f9b6d38-5c27-4e91-8a43-2d7e0b5c9a11
Имя: Кабинет
Свойства:
    -
        Ид: 8f3a2c14-7b6d-4e05-9a1c-2d5f8b47e903
        Имя: Список
        Тип: ДинамическийСписок<Кабинет.СтрокаСписка>
        ЗначениеПоУмолчанию:
            ИмяТипаДанныхСтроки: СтрокаСписка
            ОсновнаяТаблица:
                Таблица: Приложения
            Поля:
                -
                    Тип: ПолеДинамическогоСписка
                    Выражение: Наименование
                -
                    Тип: ПолеДинамическогоСписка
                    Выражение: Абонент.Код.ЗаменитьNull(0)
                    Псевдоним: КодАбонента
"""


def _lint(code: str):
    sources = [
        engine.load_text("acme/П/О/Кабинет.yaml", _FORM),
        engine.load_text("acme/П/О/Кабинет.xbsl", code),
    ]
    return engine.run_sources(sources, select={_RULE})


_HANDLER = (
    "метод Клик(ДанныеСтроки: СтрокаДинамическогоСписка<Кабинет.СтрокаСписка>)\n"
    "    знч Строка = ДанныеСтроки.Данные\n"
    "    Ф(Строка.{field})\n"
    ";\n"
)


def test_unknown_field_is_reported_with_a_hint():
    d = _lint(_HANDLER.format(field="КодАбонент"))
    assert len(d) == 1 and d[0].rule_id == _RULE and d[0].line == 3
    assert "КодАбонента" in d[0].message


def test_declared_field_is_silent():
    assert _lint(_HANDLER.format(field="КодАбонента")) == []


def test_field_named_by_the_expression_is_silent():
    # a field without an alias is named by the last segment of its expression
    assert _lint(_HANDLER.format(field="Наименование")) == []


def test_object_protocol_members_are_allowed():
    assert _lint(_HANDLER.format(field="ВСтроку()")) == []


def test_same_variable_name_with_another_row_type_is_not_mixed():
    """One map per file fails exactly here: one map per FILE reported eight
    false misses, because `Строка` carries different row types in different handlers."""
    code = (
        "метод А(ДанныеСтроки: СтрокаДинамическогоСписка<Кабинет.СтрокаСписка>)\n"
        "    знч Строка = ДанныеСтроки.Данные\n"
        "    Ф(Строка.КодАбонента)\n"
        ";\n"
        "метод Б(Строка: Строка)\n"
        "    Ф(Строка.Длина())\n"
        ";\n"
    )
    assert _lint(code) == []


def test_a_variable_of_an_unrelated_type_is_silent():
    code = (
        "метод А(Список: Массив<Строка>)\n"
        "    Ф(Список.Размер())\n"
        ";\n"
    )
    assert _lint(code) == []


# --- code/row-field-null ---------------------------------------------------------------

_NULL_FORM = """\
ВидЭлемента: КомпонентИнтерфейса
Ид: 1f9b6d38-5c27-4e91-8a43-2d7e0b5c9a11
Имя: Кабинет
Свойства:
    -
        Ид: 8f3a2c14-7b6d-4e05-9a1c-2d5f8b47e903
        Имя: Список
        Тип: ДинамическийСписок<Кабинет.СтрокаСписка>
        ЗначениеПоУмолчанию:
            ИмяТипаДанныхСтроки: СтрокаСписка
            ОсновнаяТаблица:
                Таблица: Приложения
            Поля:
                -
                    Тип: ПолеДинамическогоСписка
                    Выражение: Абонент.Номер
                    Псевдоним: НомерАбонента
                -
                    Тип: ПолеДинамическогоСписка
                    Выражение: Вид.Код.ЗаменитьNull("")
                    Псевдоним: КодВида
"""

_NULL_MODULE = """\
структура Карточка
    знч Номер: Число = 0
    знч Код: Строка = ""
    знч Мягкий: Число? = 0
;
метод Клик(ДанныеСтроки: СтрокаДинамическогоСписка<Кабинет.СтрокаСписка>)
    знч Строка = ДанныеСтроки.Данные
    знч К = новый Карточка({args})
;
"""


def _lint_null(args: str):
    sources = [
        engine.load_text("acme/П/О/Кабинет.yaml", _NULL_FORM),
        engine.load_text("acme/П/О/Кабинет.xbsl", _NULL_MODULE.format(args=args)),
    ]
    return engine.run_sources(sources, select={"code/row-field-null"})


def test_reference_field_into_a_typed_structure_field_is_reported():
    d = _lint_null("Номер = Строка.НомерАбонента")
    assert len(d) == 1 and d[0].rule_id == "code/row-field-null"
    assert "Абонент.Номер" in d[0].message and "ЗаменитьNull" in d[0].message


def test_guarded_field_is_silent():
    assert _lint_null("Код = Строка.КодВида") == []


def test_nullable_target_field_is_silent():
    assert _lint_null("Мягкий = Строка.НомерАбонента") == []


def test_the_constructor_walk_does_not_need_dunder_dict(monkeypatch):
    """In the released wheel the parser is compiled by mypyc, and a compiled node has no
    `__dict__` at all: the walk that fed on `vars(node)` raised TypeError there and took the
    whole lint of the project down (0.36.0). Here `vars` is a landmine, so the walk that reads
    the declared fields passes and an attribute walk cannot come back unnoticed."""
    def _no_dict(*args, **kwargs):
        raise TypeError("vars() argument must have __dict__ attribute")

    monkeypatch.setattr(builtins, "vars", _no_dict)
    d = _lint_null("Номер = Строка.НомерАбонента")
    assert len(d) == 1 and d[0].rule_id == "code/row-field-null"


def test_the_key_of_a_row_is_a_member_of_the_row_type():
    """The key of a row reaches the reference behind it - a property of the row TYPE.

    The row is not only the list's fields: the catalog gives the row type its own data and key
    members, and a row command casts the key to the reference type. While the rule knew the
    data member alone, that documented shape read as a field the list does not have.
    """
    d = _lint(
        "метод Открыть(Строка: СтрокаДинамическогоСписка<Кабинет.СтрокаСписка>)\n"
        "    Форма.Открыть(Ключ = Строка.Ключ)\n"
        ";\n"
    )
    assert d == [], [x.message for x in d]


def test_an_unknown_field_is_still_reported_next_to_the_key():
    d = _lint(
        "метод Открыть(Строка: СтрокаДинамическогоСписка<Кабинет.СтрокаСписка>)\n"
        "    Форма.Открыть(Ключ = Строка.Ключ, Имя = Строка.НетТакого)\n"
        ";\n"
    )
    assert len(d) == 1 and "НетТакого" in d[0].message
