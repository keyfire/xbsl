"""The forms a documentation page prints for one member: current, deprecated, of an older version.

The pages below are synthetic, written for the tests: only the shape of the markup follows the
help pages (a struck heading for the form of an older version, the version line under a heading,
the compatibility mark as a link inside the signature block). No distribution is needed.
"""

import json

from xbsl import dataset
from xbsl.extract import stdlib as extractor


def _heading(name: str, struck: bool = False, anchor: str = "") -> str:
    shown = f"<del>{name}</del>" if struck else name
    return (f'<h3 class="anchor" id="{anchor or name.lower()}">{shown}'
            f'<a href="#{anchor or name.lower()}" class="hash-link">​</a></h3>')


def _version(text: str) -> str:
    return f"<p><code>{text}</code></p>"


def _signature(text: str, deprecated: bool = False) -> str:
    mark = '@<a href="/Std/Annotations/Deprecated_ru/">Устарело</a>\n' if deprecated else ""
    escaped = text.replace("<", "&lt;").replace(">", "&gt;")
    return ('<div class="highlight"><pre class="highlight"><code>'
            f"{mark}{escaped}</code></pre></div>")


def _page(*sections: tuple[str, str]) -> str:
    body = "".join(f"<h2>{title}</h2>{content}" for title, content in sections)
    return f"<html><head><title>ОтражениеСкладов | 1С</title></head><body><article>{body}</article></body></html>"


def test_a_struck_property_form_does_not_take_the_empty_value_away():
    """The current form admits the empty value, the form of an older version does not: folding the
    two into the head used to lose the `?` of the form the code meets today."""
    page = _page(("Свойства", (
        _heading("ОсновнаяЗапись") + _version("Версия 8.0 и выше")
        + _signature("ОсновнаяЗапись: ОтражениеЗаписи?")
        + _heading("ОсновнаяЗапись", struck=True, anchor="основнаязапись-1") + _version("Версия 7.0 и ниже")
        + _signature("ОсновнаяЗапись: ОтражениеЗаписи")
        + "<p>Свойство заменено на <a href='#основнаязапись'>ОсновнаяЗапись</a>.</p>"
    )))

    assert extractor.page_member_types(page) == {"ОсновнаяЗапись": "ОтражениеЗаписи?"}


def test_a_struck_form_with_another_head_no_longer_drops_the_property():
    """Forms with differing heads drop the member - but only among the forms that count."""
    page = _page(("Свойства", (
        _heading("Картинка") + _version("Версия 9.0 и выше") + _signature("Картинка: Url|?")
        + _heading("Картинка", struck=True, anchor="картинка-1") + _version("Версия 8.0 и ниже")
        + _signature("Картинка: Строка?")
    )))

    assert extractor.page_member_types(page) == {"Картинка": "Url|?"}


def test_a_member_with_nothing_but_struck_forms_keeps_them():
    page = _page(("Методы", (
        _heading("Пересчитать", struck=True) + _version("Версия 9.0 и ниже")
        + _signature("Пересчитать(Партии: Массив<Строка>): Число")
    )))

    assert extractor.page_member_types(page) == {"Пересчитать": "Число"}
    assert extractor.page_member_signatures(page) == {"Пересчитать": ["Пересчитать(Партии: Массив<Строка>): Число"]}


def test_differing_current_forms_of_a_method_keep_the_head_and_are_named():
    """Overloads of a method differ by design; the head stays, and the fold is reported."""
    page = _page(("Методы", (
        _heading("Получить") + _signature("Получить(): ЗаписьСклада")
        + _heading("Получить", anchor="получить-1") + _signature("Получить(Период: Дата): ЗаписьСклада?")
    )))
    folded: list = []

    assert extractor.page_member_types(page, folded) == {"Получить": "ЗаписьСклада"}
    assert folded == [("Получить", ["ЗаписьСклада", "ЗаписьСклада?"])]


def test_differing_current_forms_of_a_property_store_no_type():
    """One value, two spellings: the page does not say which one holds, so neither is stated."""
    page = _page(("Свойства", (
        _heading("Остаток") + _signature("Остаток: Число")
        + _heading("Остаток", anchor="остаток-1") + _signature("Остаток: Число?")
    )))
    folded: list = []

    assert extractor.page_member_types(page, folded) == {}
    assert folded == [("Остаток", ["Число", "Число?"])]


def test_signatures_leave_out_the_overload_of_an_older_version():
    page = _page(("Методы", (
        _heading("Разделить") + _signature("Разделить(Разделитель: Строка): Массив<Строка>")
        + _heading("Разделить", struck=True, anchor="разделить-1") + _version("Версия 8.0 и ниже")
        + _signature("Разделить(Разделитель: Строка, КоличествоЧастей: Число): Массив<Строка>")
    )))

    assert extractor.page_member_signatures(page) == {"Разделить": ["Разделить(Разделитель: Строка): Массив<Строка>"]}


def test_a_method_kept_only_for_compatibility_has_its_signatures_without_the_mark():
    """The mark opens the block, so demanding the member's name first dropped such a method's
    signatures altogether - the hover and the typing of its calls had nothing to read."""
    page = _page(("Методы", (
        _heading("ЗагрузитьПартию")
        + _signature("ЗагрузитьПартию(Данные: Байты): ДвоичныйОбъект", deprecated=True)
    )))

    assert extractor.page_member_signatures(page) == {
        "ЗагрузитьПартию": ["ЗагрузитьПартию(Данные: Байты): ДвоичныйОбъект"]
    }
    assert extractor.page_member_types(page) == {"ЗагрузитьПартию": "ДвоичныйОбъект"}


def test_type_parameters_of_a_method_come_from_the_forms_that_count():
    page = _page(("Методы", (
        _heading("Прочитать") + _signature("Прочитать<ТипОбъекта>(Источник: Строка, Тип: Тип<ТипОбъекта>): ТипОбъекта")
        + _heading("Прочитать", struck=True, anchor="прочитать-1") + _version("Версия 9.0 и ниже")
        + _signature("Прочитать<ТипСтарый>(Источник: Строка): ТипСтарый")
    )))

    assert extractor.page_method_type_params(page) == {"Прочитать": ["ТипОбъекта"]}


def test_the_forms_of_a_deprecated_member_carry_marks_versions_and_replacements():
    page = _page(("Методы", (
        _heading("Прочитать") + _version("Версия 8.0 и выше")
        + _signature("Прочитать<ТипОбъекта>(Источник: Строка): ТипОбъекта")
        + _heading("Прочитать", anchor="прочитать-1")
        + _signature("Прочитать<ТипОбъекта>(Источник: Строка, Тип: Тип<ТипОбъекта>): ТипОбъекта")
        + _heading("Прочитать", struck=True, anchor="прочитать-2") + _version("Версия 9.0 и ниже")
        + _signature("Прочитать(Источник: Строка): Объект?", deprecated=True)
        + "<p>Метод заменен на <a href='#прочитать'>Прочитать</a>.</p>"
        + _heading("ПрочитатьМассив")
        + _signature("ПрочитатьМассив(Источник: Строка): Массив<Объект?>", deprecated=True)
        + "Вызывает метод <a href='#прочитать'>Прочитать</a>&lt;Массив&lt;Объект?&gt;&gt;()."
        + "<h4>Пример</h4><p>Метод заменен на <a href='#x'>Другой</a>.</p>"
    )))

    forms = extractor.page_member_forms(page)

    assert forms == {
        "Прочитать": [
            {"signature": "Прочитать<ТипОбъекта>(Источник: Строка): ТипОбъекта", "since": "8.0"},
            {"signature": "Прочитать<ТипОбъекта>(Источник: Строка, Тип: Тип<ТипОбъекта>): ТипОбъекта"},
            {"signature": "Прочитать(Источник: Строка): Объект?", "deprecated": True, "until": "9.0",
             "replacement": "Прочитать"},
        ],
        "ПрочитатьМассив": [
            {"signature": "ПрочитатьМассив(Источник: Строка): Массив<Объект?>", "deprecated": True,
             "replacement": "Прочитать"},
        ],
    }


def test_members_without_a_marked_form_are_not_listed_among_the_deprecated():
    """A struck form alone is history: the compiler of a newer version rejects it outright."""
    page = _page(("Свойства", (
        _heading("Остаток") + _version("Версия 8.0 и выше") + _signature("Остаток: Число?")
        + _heading("Остаток", struck=True, anchor="остаток-1") + _version("Версия 7.0 и ниже")
        + _signature("Остаток: Число")
    )))

    assert extractor.page_member_forms(page) == {}


def test_a_form_may_exist_between_two_versions():
    page = _page(("Методы", (
        _heading("Выдать") + _signature("Выдать(Ключи: Массив<Строка>)")
        + _heading("Выдать", struck=True, anchor="выдать-1")
        + _version("Версия 8.0 и выше") + _version("Версия 9.0 и ниже")
        + _signature("Выдать(Ключ: Строка)", deprecated=True)
    )))

    assert extractor.page_member_forms(page)["Выдать"][1] == {
        "signature": "Выдать(Ключ: Строка)", "deprecated": True, "since": "8.0", "until": "9.0",
    }


def test_a_template_result_naming_objects_of_other_kinds_keeps_its_head():
    """`{ИмяСклада}` stands for the object itself; a selection over several placeholders names
    objects of other kinds, which the name of this one cannot be put in for."""
    page = ("<html><head><title>{ИмяСклада} | 1С</title></head><body><article><h2>Методы</h2>"
            + _heading("Получить") + _signature("Получить(): {ИмяСклада}.Запись")
            + _heading("ВыбратьИзменения")
            + _signature("ВыбратьИзменения(): ВыборкаДанных<{ИмяСправочника}.Объект|{ИмяДокумента}.Объект>")
            + "</article></body></html>")

    assert extractor.manager_member_types(page) == {
        "Получить": "{}.Запись",
        "ВыбратьИзменения": "ВыборкаДанных",
    }


def test_the_nearest_ancestor_wins_a_member_two_ancestors_declare():
    """`bases` is sorted by name, not by distance: merged in that order, the override of the
    nearer ancestor lost to its own base whenever the base sorted later."""
    data = {
        "meta": {"members": "own"},
        "bases": {
            "ОтражениеСкладов": ["Объект", "ОтражениеСущности", "ОтражениеЭлемента"],
            "ОтражениеСущности": ["Объект", "ОтражениеЭлемента"],
            "ОтражениеЭлемента": ["Объект"],
        },
        "type_members": {
            "ОтражениеСкладов": {},
            "ОтражениеСущности": {"properties": ["ОсновнаяЗапись"]},
            "ОтражениеЭлемента": {"properties": ["ОсновнаяЗапись"]},
        },
        "member_types": {
            "ОтражениеСущности": {"ОсновнаяЗапись": "ОтражениеЗаписи"},
            "ОтражениеЭлемента": {"ОсновнаяЗапись": "ОтражениеЗаписи?"},
        },
    }

    expanded = dataset._expand_inherited(json.loads(json.dumps(data, ensure_ascii=False)))

    assert expanded["member_types"]["ОтражениеСкладов"]["ОсновнаяЗапись"] == "ОтражениеЗаписи"
    assert dataset.nearest_last(["Объект", "ОтражениеСущности", "ОтражениеЭлемента"], data["bases"]) == [
        "Объект", "ОтражениеЭлемента", "ОтражениеСущности",
    ]
