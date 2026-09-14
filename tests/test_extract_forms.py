"""The forms a documentation page prints for one member: current, deprecated, of an older version.

The pages below are synthetic, written for the tests: only the shape of the markup follows the
help pages (a struck heading for the form of an older version, the version line under a heading,
the compatibility mark as a link inside the signature block). No distribution is needed.
"""

import io
import json
import struct
import zipfile

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


# --- the compatibility modes a deprecation applies in (classcode.declared_deprecations) ----------------
#
# The class below is assembled by the test, byte for byte, in the shape of a declaration of members:
# the two spellings of a member pushed before its builder, an annotation filed under a range of
# modes, the builder finished. Only the layout of a class file is reproduced - a public standard.


class _Pool:
    def __init__(self) -> None:
        self.blobs: list[bytes] = []

    def _add(self, blob: bytes) -> int:
        self.blobs.append(blob)
        return len(self.blobs)

    def text(self, value: str) -> int:
        body = value.encode("utf-8")
        return self._add(bytes([1]) + struct.pack(">H", len(body)) + body)

    def string(self, value: str) -> int:
        return self._add(bytes([8]) + struct.pack(">H", self.text(value)))

    def klass(self, name: str) -> int:
        return self._add(bytes([7]) + struct.pack(">H", self.text(name)))

    def _ref(self, tag: int, owner: str, name: str, descriptor: str) -> int:
        owner_index = self.klass(owner)
        nat = self._add(bytes([12]) + struct.pack(">HH", self.text(name), self.text(descriptor)))
        return self._add(bytes([tag]) + struct.pack(">HH", owner_index, nat))

    def method(self, owner: str, name: str) -> int:
        return self._ref(10, owner, name, "()V")

    def field(self, owner: str, name: str) -> int:
        return self._ref(9, owner, name, "Ljava/lang/Object;")


def _class(steps: list[tuple]) -> bytes:
    """A class with one method made of steps: ("ldc", text), ("call", "Owner.name"),
    ("mode", "CMODE_9_0"), ("null",), ("store", local), ("load", local)."""
    pool = _Pool()
    code_name = pool.text("Code")
    body = bytearray()
    for step in steps:
        kind = step[0]
        if kind == "ldc":
            body += bytes([0x13]) + struct.pack(">H", pool.string(step[1]))
        elif kind == "call":
            owner, name = step[1].rsplit(".", 1)
            body += bytes([0xB6]) + struct.pack(">H", pool.method("demo/" + owner, name))
        elif kind == "mode":
            body += bytes([0xB2]) + struct.pack(">H", pool.field("demo/Modes", step[1]))
        elif kind == "null":
            body += bytes([0x01])
        elif kind == "store":
            body += bytes([0x3A, step[1]])
        elif kind == "load":
            body += bytes([0x19, step[1]])
    body += bytes([0xB1])
    code = struct.pack(">HHI", 8, 8, len(body)) + bytes(body) + struct.pack(">HH", 0, 0)
    this_class, super_class = pool.klass("Demo"), pool.klass("java/lang/Object")
    method = struct.pack(">HHHH", 0, pool.text("members"), pool.text("()V"), 1)
    method += struct.pack(">HI", code_name, len(code)) + code
    return (b"\xca\xfe\xba\xbe" + struct.pack(">HH", 0, 61) + struct.pack(">H", len(pool.blobs) + 1)
            + b"".join(pool.blobs) + struct.pack(">HHHH", 0, this_class, super_class, 0)
            + struct.pack(">H", 0) + struct.pack(">H", 1) + method + struct.pack(">H", 0))


def _deprecated(first: str, last: str | None) -> list[tuple]:
    return [("call", "DeprecatedG5Annotation.<init>"), ("mode", first),
            ("mode", last) if last else ("null",), ("call", "ElementCollectionInCmptMode$Builder.add")]


def test_a_deprecation_declared_before_the_member_is_named_belongs_to_it():
    blob = _class([
        ("ldc", "Count"), ("ldc", "Количество"), ("call", "CtMetaMethodBuilder.meth"),
        ("call", "CtMetaMethodBuilder.build"),
        *_deprecated("CMODE_9_0", None),
        ("ldc", "ReadAll"), ("ldc", "ПрочитатьВсе"), ("call", "CtMetaMethodBuilder.meth"),
        ("call", "CtMetaMethodBuilder.build"),
    ])

    assert extractor.classcode.declared_deprecations(blob) == [("ПрочитатьВсе", "9.0", None)]


def test_a_member_named_by_a_stored_term_takes_the_deprecation_declared_after_it():
    blob = _class([
        ("call", "Term$TermWithHistory.builder"), ("ldc", "Load"), ("ldc", "Загрузить"),
        ("mode", "CMODE_9_0"), ("call", "Term$TermWithHistory$Builder.add"),
        ("ldc", "LoadOld"), ("ldc", "ЗагрузитьСтарое"), ("call", "Term$TermWithHistory$Builder.add"),
        ("call", "Term$TermWithHistory$Builder.build"), ("store", 2),
        ("load", 2), ("call", "CtMetaMethodBuilder.meth"),
        *_deprecated("CMODE_8_0", "CMODE_9_0"),
        ("call", "CtMetaMethodBuilder.build"),
    ])

    assert extractor.classcode.declared_deprecations(blob) == [("Загрузить", "8.0", "9.0")]


def test_a_member_without_an_annotation_is_not_deprecated():
    blob = _class([("ldc", "Count"), ("ldc", "Количество"), ("call", "CtMetaMethodBuilder.meth"),
                   ("mode", "CMODE_9_0"), ("call", "CtMetaMethodBuilder.cmptMode"),
                   ("call", "CtMetaMethodBuilder.build")])

    assert extractor.classcode.declared_deprecations(blob) == []


def _car_with(classes: dict[str, bytes]) -> zipfile.ZipFile:
    jar = io.BytesIO()
    with zipfile.ZipFile(jar, "w") as out:
        for name, blob in classes.items():
            out.writestr(f"demo/{name}.class", blob)
    car = io.BytesIO()
    with zipfile.ZipFile(car, "w") as out:
        out.writestr("data/ide/plugins/bin/repo/demo.lsp.server.appengine-1.0.jar", jar.getvalue())
    return zipfile.ZipFile(io.BytesIO(car.getvalue()))


def test_the_mode_range_goes_onto_the_deprecated_forms_of_the_member():
    declaration = _class([*_deprecated("CMODE_9_0", None), ("ldc", "ReadAll"), ("ldc", "ПрочитатьВсе"),
                          ("call", "CtMetaMethodBuilder.meth"), ("call", "CtMetaMethodBuilder.build")])
    deprecated = {"ЧтениеСкладов": {"ПрочитатьВсе": [
        {"signature": "ПрочитатьВсе(): Массив<Строка>", "deprecated": True},
        {"signature": "ПрочитатьВсе(Настройки: НастройкиЧтения): Массив<Строка>"},
    ]}}

    extractor._apply_deprecation_modes(_car_with({"WarehouseReaderCtMetaObject": declaration}),
                                       deprecated, {"WarehouseReader": "ЧтениеСкладов"})

    forms = deprecated["ЧтениеСкладов"]["ПрочитатьВсе"]
    assert forms[0]["deprecated_modes"] == ["9.0", None]
    assert "deprecated_modes" not in forms[1]


def test_overloads_deprecated_in_different_modes_leave_the_mode_unstated():
    declaration = _class([
        *_deprecated("CMODE_8_0", None), ("ldc", "Load"), ("ldc", "Загрузить"),
        ("call", "CtMetaMethodBuilder.meth"), ("call", "CtMetaMethodBuilder.build"),
        *_deprecated("CMODE_9_0", None), ("ldc", "Load"), ("ldc", "Загрузить"),
        ("call", "CtMetaMethodBuilder.meth"), ("call", "CtMetaMethodBuilder.build"),
    ])
    deprecated = {"ХранилищеСкладов": {"Загрузить": [
        {"signature": "Загрузить(Поток: ПотокЧтения): Число", "deprecated": True},
        {"signature": "Загрузить(Строка: Строка): Число", "deprecated": True},
    ]}}

    extractor._apply_deprecation_modes(_car_with({"WarehouseStorageCtMetaObject": declaration}),
                                       deprecated, {"WarehouseStorage": "ХранилищеСкладов"})

    assert all("deprecated_modes" not in form for form in deprecated["ХранилищеСкладов"]["Загрузить"])
