"""Structural search over forms (xbsl/formsearch.py, docs/DESIGNER.md hook 10)."""

from xbsl.formsearch import Predicate, parse_query, search_form, search_forms

FORM_A = """\
ВидЭлемента: КомпонентИнтерфейса
Имя: ФормаЗаказа
Наследует:
    Тип: ФормаОбъекта<Заказы.Объект>
    Содержимое:
        Тип: Группа
        Имя: Корень
        Содержимое:
            -
                Тип: Надпись
                Имя: Подсказка
                Заголовок: Заполните поля
            -
                Тип: Кнопка
                Имя: КнопкаОплатить
                Заголовок: Оплатить
                Вид: Основная
"""

FORM_B = """\
ВидЭлемента: КомпонентИнтерфейса
Имя: ФормаКлиента
Наследует:
    Тип: ФормаОбъекта<Клиенты.Объект>
    Содержимое:
        Тип: Кнопка
        Имя: КнопкаОтмена
        Заголовок: Отмена
        Вид: Обычная
"""


def test_parse_query_type_and_predicates():
    assert parse_query("Кнопка Вид=Основная") == ("Кнопка", [Predicate("Вид", "Основная")])
    # A leading "*" (or a first token with "=") means any type.
    assert parse_query("* Заголовок=Оплатить") == (None, [Predicate("Заголовок", "Оплатить")])
    assert parse_query("Вид=Основная") == (None, [Predicate("Вид", "Основная")])
    # A key with no value only requires the key to be present.
    assert parse_query("Кнопка Вид=") == ("Кнопка", [Predicate("Вид", "")])
    assert parse_query("   ") == (None, [])


def test_search_form_by_type():
    hits = search_form(FORM_A, "Кнопка", [])
    assert [h["name"] for h in hits] == ["КнопкаОплатить"]
    assert hits[0]["type"] == "Кнопка"
    # 0-based line of the "Тип: Кнопка" node anchor - the dash line above it.
    assert isinstance(hits[0]["line"], int) and hits[0]["line"] > 0


def test_search_form_by_predicate():
    # Type + a value predicate (case-insensitive substring).
    assert [h["name"] for h in search_form(FORM_A, "Кнопка", [Predicate("Вид", "основ")])] == [
        "КнопкаОплатить"
    ]
    # A predicate with no type filter matches across component types.
    assert [h["name"] for h in search_form(FORM_A, None, [Predicate("Заголовок", "Оплатить")])] == [
        "КнопкаОплатить"
    ]
    # A predicate that no node satisfies yields nothing.
    assert search_form(FORM_A, "Кнопка", [Predicate("Вид", "Нет")]) == []
    # A missing key never matches.
    assert search_form(FORM_A, None, [Predicate("НетТакого", "")]) == []


def test_search_forms_carries_path_and_skips_broken():
    forms = [
        {"path": "a.yaml", "text": FORM_A},
        {"path": "broken.yaml", "text": "Наследует: [unterminated"},
        {"path": "b.yaml", "text": FORM_B},
    ]
    hits = search_forms(forms, "Кнопка")
    assert [(h["path"], h["name"]) for h in hits] == [
        ("a.yaml", "КнопкаОплатить"),
        ("b.yaml", "КнопкаОтмена"),
    ]
    # Narrow by a property present in only one form.
    narrowed = search_forms(forms, "Кнопка Вид=Основная")
    assert [(h["path"], h["name"]) for h in narrowed] == [("a.yaml", "КнопкаОплатить")]
