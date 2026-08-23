"""Metadata scaffolding (xbsl/scaffold.py) - text edits, templates, operations.

Every generated yaml is additionally fed through PyYAML: a template the parser cannot
parse must not pass the tests regardless of the targeted checks.
"""

import os
import re
from pathlib import Path

import pytest
import yaml as pyyaml

from xbsl import scaffold
from xbsl.scaffold import (
    FileRename,
    ScaffoldError,
    TextEdit,
    apply_edit,
    apply_result,
    find_section_item_offset,
    insert_item_edit,
    insert_nested_item_edit,
    section_items,
)

CATALOG = """\
ВидЭлемента: Справочник
Ид: 6f0b6a44-0000-4000-8000-000000000001
Имя: Товары
ОбластьВидимости: ВПроекте
Реквизиты:
    -
        Ид: 6f0b6a44-0000-4000-8000-000000000002
        Имя: Артикул
        Тип: Строка
ТабличныеЧасти:
    -
        Ид: 6f0b6a44-0000-4000-8000-000000000003
        Имя: Состав
        Реквизиты:
            -
                Ид: 6f0b6a44-0000-4000-8000-000000000004
                Имя: Компонент
                Тип: Строка
"""


def _valid_yaml(text: str) -> object:
    return pyyaml.safe_load(text)


# --- text edits ---------------------------------------------------------------------------


def test_insert_item_into_existing_section():
    edit = insert_item_edit(CATALOG, "Реквизиты", ["Ид: х", "Имя: Цвет", "Тип: Строка"])
    out = apply_edit(CATALOG, edit)
    names = [i["Имя"] for i in section_items(out, "Реквизиты")]
    assert names == ["Артикул", "Цвет"]
    # The insertion is targeted - the ТабличныеЧасти section content did not shift.
    assert out.count("ТабличныеЧасти:") == 1
    assert _valid_yaml(out)


def test_insert_item_creates_missing_section():
    text = "ВидЭлемента: Перечисление\nИмя: Статус\n"
    out = apply_edit(text, insert_item_edit(text, "Элементы", ["Ид: х", "Имя: Новый"]))
    assert [i["Имя"] for i in section_items(out, "Элементы")] == ["Новый"]
    assert _valid_yaml(out)


def test_insert_item_respects_crlf():
    text = CATALOG.replace("\n", "\r\n")
    edit = insert_item_edit(text, "Реквизиты", ["Имя: Цвет"], nl="\r\n")
    assert "\r\n" in edit.new_text and "\n\n" not in edit.new_text.replace("\r\n", "")


def test_insert_nested_item_into_tabular():
    offset = find_section_item_offset(CATALOG, "ТабличныеЧасти", "Состав")
    assert offset is not None
    edit = insert_nested_item_edit(CATALOG, offset, "Реквизиты", ["Имя: Количество", "Тип: Число"])
    out = apply_edit(CATALOG, edit)
    parsed = _valid_yaml(out)
    tc = parsed["ТабличныеЧасти"][0]
    assert [f["Имя"] for f in tc["Реквизиты"]] == ["Компонент", "Количество"]
    # Top-level Реквизиты are unaffected.
    assert [i["Имя"] for i in section_items(out, "Реквизиты")] == ["Артикул"]


def test_section_items_inline_form():
    text = "Использование:\nЭлементы:\n    - Имя: Один\n    -\n        Имя: Два\n"
    assert [i["Имя"] for i in section_items(text, "Элементы")] == ["Один", "Два"]


# --- objects ------------------------------------------------------------------------------


def test_new_object_catalog(tmp_path):
    result = scaffold.op_new_object(tmp_path, "Справочник", "Товары")
    written = apply_result(result)
    assert written == [str(tmp_path / "Товары.yaml")]
    text = (tmp_path / "Товары.yaml").read_text(encoding="utf-8")
    parsed = _valid_yaml(text)
    assert parsed["ВидЭлемента"] == "Справочник"
    # The default is the platform one - visibility is not widened on the developer's behalf.
    assert parsed["ОбластьВидимости"] == "ВПодсистеме"
    assert parsed["Ид"]

    apply_result(scaffold.op_new_object(tmp_path, "Справочник", "Склады", scope="ВПроекте"))
    wider = _valid_yaml((tmp_path / "Склады.yaml").read_text(encoding="utf-8"))
    assert wider["ОбластьВидимости"] == "ВПроекте"


_МОДУЛЬ = (
    "@НаСервере\n"
    "метод Первый(): Число\n"
    "    возврат 1\n"
    ";\n\n"
    "@НаСервере @ВПроекте\n"
    "метод Второй(): Число\n"
    "    возврат 2\n"
    ";\n"
)


def _annotations_of(text):
    from xbsl import engine
    from xbsl.parser import Method, parse

    module, errors = parse(engine.load_text("Модуль.xbsl", text))
    assert not errors, errors
    return {m.name: sorted(a.name for a in m.annotations)
            for m in module.members if isinstance(m, Method)}


def _module(tmp_path):
    p = tmp_path / "Модуль.xbsl"
    p.write_text(_МОДУЛЬ, encoding="utf-8")
    return p


@pytest.mark.needs_data
def test_add_method_keeps_annotation_bonds(tmp_path):
    # The whole point of the operation: an insertion must never split an annotation block
    # from its method. Checked for every placement, by parsing the result.
    for kwargs in ({"after": "Первый"}, {"before": "Второй"}, {}):
        p = _module(tmp_path)
        result = scaffold.op_add_method(p, "Новый", annotations="НаСервере", **kwargs)
        anns = _annotations_of(result.changes[0].content)
        assert anns["Первый"] == ["НаСервере"]
        assert anns["Второй"] == ["ВПроекте", "НаСервере"]
        assert anns["Новый"] == ["НаСервере"]


@pytest.mark.needs_data
def test_text_anchor_insertion_is_what_this_replaces(tmp_path):
    # The trap, reproduced: inserting before the "метод Второй" line hands the neighbour's
    # annotations to the new method and leaves Второй with none.
    naive = _МОДУЛЬ.replace(
        "метод Второй", "@НаСервере\nметод Новый()\n    возврат\n;\n\nметод Второй", 1
    )
    anns = _annotations_of(naive)
    assert anns["Второй"] == []
    assert anns["Новый"] == ["ВПроекте", "НаСервере", "НаСервере"]


@pytest.mark.needs_data
def test_add_method_placement_and_signature(tmp_path):
    p = _module(tmp_path)
    text = scaffold.op_add_method(
        p, "Считать", params="Ид: Строка", returns="Число",
        annotations="@НаСервере", after="Первый", body="возврат 0",
    ).changes[0].content
    assert "метод Считать(Ид: Строка): Число" in text
    assert "    возврат 0" in text
    assert text.index("метод Считать") > text.index("метод Первый")
    assert text.index("метод Считать") < text.index("метод Второй")


@pytest.mark.needs_data
def test_add_method_rejects_duplicates_and_unknown_anchors(tmp_path):
    p = _module(tmp_path)
    with pytest.raises(scaffold.ScaffoldError):
        scaffold.op_add_method(p, "Первый")
    with pytest.raises(scaffold.ScaffoldError):
        scaffold.op_add_method(p, "Новый", after="НетТакого")
    with pytest.raises(scaffold.ScaffoldError):
        scaffold.op_add_method(p, "Новый", after="Первый", before="Второй")
    with pytest.raises(scaffold.ScaffoldError):
        scaffold.op_add_method(p, "Плохое имя")
    with pytest.raises(scaffold.ScaffoldError):
        scaffold.op_add_method(p.with_suffix(".yaml"), "Новый")


@pytest.mark.needs_data
def test_add_method_refuses_a_broken_module(tmp_path):
    # A module the parser cannot read gives no reliable borders - better to refuse.
    p = tmp_path / "Модуль.xbsl"
    p.write_text("метод Первый(\n", encoding="utf-8")
    with pytest.raises(scaffold.ScaffoldError):
        scaffold.op_add_method(p, "Новый")


def test_new_object_form_wraps_content_in_a_template(tmp_path):
    # `Форма.Содержимое` is typed ШаблонФормы?: a Группа placed there directly makes the
    # server reject the build ("Значение типа "Группа" не может быть присвоено в "ШаблонФормы?"),
    # which is what the generated skeleton used to do.
    result = scaffold.op_new_object(tmp_path, "КомпонентИнтерфейса", "ФормаПробы")
    apply_result(result)
    parsed = _valid_yaml((tmp_path / "ФормаПробы.yaml").read_text(encoding="utf-8"))
    content = parsed["Наследует"]["Содержимое"]
    assert content["Тип"] == "ПроизвольныйШаблонФормы"
    assert content["Содержимое"]["Тип"] == "Группа"


def test_new_object_rejects_duplicates_and_bad_names(tmp_path):
    apply_result(scaffold.op_new_object(tmp_path, "Справочник", "Товары"))
    with pytest.raises(ScaffoldError, match="уже существует"):
        scaffold.op_new_object(tmp_path, "Справочник", "Товары")
    with pytest.raises(ScaffoldError, match="Недопустимое имя"):
        scaffold.op_new_object(tmp_path, "Справочник", "Плохое имя")
    with pytest.raises(ScaffoldError, match="не поддерживается"):
        scaffold.op_new_object(tmp_path, "НеВид", "Имя")


def test_new_common_module_with_environment(tmp_path):
    result = scaffold.op_new_object(
        tmp_path, "ОбщийМодуль", "Помощники", environment="КлиентИСервер"
    )
    apply_result(result)
    text = (tmp_path / "Помощники.yaml").read_text(encoding="utf-8")
    assert "Окружение: КлиентИСервер" in text
    assert (tmp_path / "Помощники.xbsl").is_file()


def test_new_object_access_control(tmp_path):
    apply_result(
        scaffold.op_new_object(tmp_path, "Справочник", "Заказы", access="РазрешеноАутентифицированным")
    )
    parsed = _valid_yaml((tmp_path / "Заказы.yaml").read_text(encoding="utf-8"))
    # The right sits inside Разрешения under КонтрольДоступа - a set of
    # "Право: СпособКонтроляДоступа" pairs.
    assert parsed["КонтрольДоступа"]["Разрешения"]["ПоУмолчанию"] == "РазрешеноАутентифицированным"


def test_new_http_service_routes(tmp_path):
    result = scaffold.op_new_object(
        tmp_path, "HttpСервис", "Каталог", access="РазрешеноВсем",
        routes="GET /, POST /, GET /{id}",
    )
    apply_result(result)
    text = (tmp_path / "Каталог.yaml").read_text(encoding="utf-8")
    parsed = _valid_yaml(text)
    templates = {t["Шаблон"]: t for t in parsed["ШаблоныUrl"]}
    assert set(templates) == {"/", "/{id}"}
    assert [m["Метод"] for m in templates["/"]["Методы"]] == ["GET", "POST"]
    module = (tmp_path / "Каталог.xbsl").read_text(encoding="utf-8")
    for handler in ("ПолучитьСписок", "Создать", "ПолучитьПоИд", "ОбработатьОшибку"):
        assert f"метод {handler}" in module


def test_new_component_command_uses_component_type_property(tmp_path):
    result = scaffold.op_new_object(tmp_path, "КомандаСКомпонентом", "КомандаЗакрытьФорму")
    apply_result(result)
    parsed = _valid_yaml((tmp_path / "КомандаЗакрытьФорму.yaml").read_text(encoding="utf-8"))
    # The property is named ТипКомпонента - the "Компонент" variant from the documented
    # property list was tried in a deploy and is rejected by the compiler ("Неизвестное свойство").
    assert parsed["ТипКомпонента"] == "Форма"
    assert "Компонент" not in parsed
    module = (tmp_path / "КомандаЗакрытьФорму.xbsl").read_text(encoding="utf-8")
    assert "@Обработчик" in module and "этот.Компонент" in module


def test_new_soap_service(tmp_path):
    result = scaffold.op_new_object(
        tmp_path, "SoapСервис", "СервисМагазина", access="РазрешеноАутентифицированным",
    )
    apply_result(result)
    parsed = _valid_yaml((tmp_path / "СервисМагазина.yaml").read_text(encoding="utf-8"))
    # Structure per the SoapСервис documentation - namespace, service name, URL, handlers.
    assert parsed["ИмяСервиса"] == "СервисМагазина"
    assert parsed["КорневойUrl"] == "/СервисМагазина"
    assert "ПространствоИменСервиса" in parsed
    assert parsed["Обработчики"][0]["Имя"] == "Операция1"
    assert parsed["Обработчики"][0]["Метод"] == "Операция1"
    assert parsed["КонтрольДоступа"]["Разрешения"]["Вызов"] == "РазрешеноАутентифицированным"
    # The operation method is declared in the paired module.
    module = (tmp_path / "СервисМагазина.xbsl").read_text(encoding="utf-8")
    assert "метод Операция1()" in module


def test_processing_gets_both_modules(tmp_path):
    # A processor has two modules, and the element one is not where the algorithm goes
    # (topics/processing-project-element): the stub of each says what belongs there.
    apply_result(scaffold.op_new_object(tmp_path, "Обработка", "РасчетДоставки"))
    element = (tmp_path / "РасчетДоставки.xbsl").read_text(encoding="utf-8")
    obj = (tmp_path / "РасчетДоставки.Объект.xbsl").read_text(encoding="utf-8")
    assert "РасчетДоставки.Объект.xbsl" in element
    assert "@Обработчик" in obj


@pytest.mark.needs_data
def test_processing_attribute_has_no_id(tmp_path):
    # The attribute class of a processor declares no Id at all; writing it fails the deploy
    # with an unknown-property error.
    apply_result(scaffold.op_new_object(tmp_path, "Обработка", "РасчетДоставки"))
    yaml_path = tmp_path / "РасчетДоставки.yaml"
    apply_result(scaffold.op_add_field(yaml_path, "реквизит", "Вес", type_="Число"))
    parsed = _valid_yaml(yaml_path.read_text(encoding="utf-8"))
    attribute = parsed["Реквизиты"][0]
    assert attribute["Имя"] == "Вес" and "Ид" not in attribute


def test_catalog_attribute_keeps_id(tmp_path):
    # the negative control of the test above: an identified item still gets its Id
    apply_result(scaffold.op_new_object(tmp_path, "Справочник", "Товары"))
    yaml_path = tmp_path / "Товары.yaml"
    apply_result(scaffold.op_add_field(yaml_path, "реквизит", "Артикул"))
    parsed = _valid_yaml(yaml_path.read_text(encoding="utf-8"))
    assert parsed["Реквизиты"][0]["Ид"]


@pytest.mark.needs_data
def test_event_log_property_gains_the_id_its_class_declares(tmp_path):
    # The reverse of the processing case: EventLogEventProperty DECLARES an Id, and applying
    # the build rejects the object without one ("ID required") - the hand-written template
    # missed exactly this section. The Id is reconciled from the metamodel, the same source
    # the yaml/item-id-required rule judges by.
    apply_result(scaffold.op_new_object(tmp_path, "СобытиеЖурналаСобытий", "ЗадачаЗавершена"))
    yaml_path = tmp_path / "ЗадачаЗавершена.yaml"
    apply_result(scaffold.op_add_field(yaml_path, "свойство", "Пользователь"))
    parsed = _valid_yaml(yaml_path.read_text(encoding="utf-8"))
    prop = parsed["Свойства"][0]
    assert prop["Имя"] == "Пользователь"
    assert prop["Ид"]


def test_processing_operation_writes_handler(tmp_path):
    apply_result(scaffold.op_new_object(tmp_path, "Обработка", "РасчетДоставки"))
    yaml_path = tmp_path / "РасчетДоставки.yaml"
    result = scaffold.op_add_field(yaml_path, "операция", "Рассчитать")
    apply_result(result)
    # The operation landed in the yaml, and the same-named @Handler method - in the OBJECT
    # module: in the element module the attributes of the processor are out of context.
    parsed = _valid_yaml(yaml_path.read_text(encoding="utf-8"))
    assert [o["Имя"] for o in parsed["Операции"]] == ["Рассчитать"]
    object_module = (tmp_path / "РасчетДоставки.Объект.xbsl").read_text(encoding="utf-8")
    assert "@Обработчик\nметод Рассчитать()" in object_module.replace("\r\n", "\n")
    element_module = (tmp_path / "РасчетДоставки.xbsl").read_text(encoding="utf-8")
    assert "метод Рассчитать()" not in element_module
    assert any("Рассчитать" in n for n in result.notes)

    # Adding the same method again does not duplicate it in the module.
    apply_result(scaffold.op_add_field(yaml_path, "операция", "РассчитатьПочтой"))
    again = scaffold.op_add_field(yaml_path, "операция", "Ещё")
    apply_result(again)
    object_module = (tmp_path / "РасчетДоставки.Объект.xbsl").read_text(encoding="utf-8")
    assert object_module.count("метод Рассчитать()") == 1


def test_http_root_url_drops_kind_suffix(tmp_path):
    # КорневойUrl is a public prefix - the HttpСервис kind suffix is redundant in it.
    result = scaffold.op_new_object(tmp_path, "HttpСервис", "КаталогHttpСервис", routes="GET /")
    apply_result(result)
    parsed = _valid_yaml((tmp_path / "КаталогHttpСервис.yaml").read_text(encoding="utf-8"))
    assert parsed["КорневойUrl"] == "/Каталог"
    # Cyrillic in a public URL warrants a warning (production URLs use Latin).
    assert any("латиницей" in note for note in result.notes)


def test_http_stub_has_no_dead_locals(tmp_path):
    # Handler stubs must not contain computed but unused variables - the live code is
    # a valid stub, and the expanded example goes as a comment.
    result = scaffold.op_new_object(
        tmp_path, "HttpСервис", "Каталог", routes="GET /, POST /, GET /{id}, DELETE /{id}",
    )
    apply_result(result)
    module = (tmp_path / "Каталог.xbsl").read_text(encoding="utf-8")
    # Live (not commented out) variable declarations - only those that are actually read.
    live = [ln for ln in module.splitlines() if not ln.lstrip().startswith("//")]
    assert not any("пер Ограничение" in ln for ln in live)  # used to be computed for nothing
    assert 'знч Ид = Запрос.Параметры.ПолучитьПервый("id")' in module
    assert 'УстановитьТело("Не найдено: " + Ид)' in module  # Ид is used - not a dead local


def test_http_handler_names_do_not_collide(tmp_path):
    result = scaffold.op_new_object(
        tmp_path, "HttpСервис", "Сервис", routes="GET /{id}, GET /{id}/items"
    )
    apply_result(result)
    parsed = _valid_yaml((tmp_path / "Сервис.yaml").read_text(encoding="utf-8"))
    handlers = [
        m["Обработчик"] for t in parsed["ШаблоныUrl"] for m in t["Методы"]
    ]
    assert len(handlers) == len(set(handlers))


def test_new_report_layout(tmp_path):
    result = scaffold.op_new_object(
        tmp_path, "Отчет", "Остатки",
        report={
            "source": "Регистр.Остатки",
            "rows": ["Номенклатура"],
            "columns": ["Склад"],
            "measures": [{"expr": "Количество", "title": "Количество"}],
        },
    )
    apply_result(result)
    parsed = _valid_yaml((tmp_path / "Остатки.yaml").read_text(encoding="utf-8"))
    fields = parsed["Макет"]["Поля"]
    kinds = [f["Вид"] for f in fields]
    assert kinds == ["Измерение", "Измерение", "Мера"]
    assert fields[2]["Выражение"] == "СУММА(Количество)"
    # Layout field Ид is a canonical hyphenated UUID (otherwise the yaml/id-uuid rule complains).
    assert all(re.fullmatch(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}",
                            f["Ид"]) for f in fields)

    with pytest.raises(ScaffoldError, match="источник"):
        scaffold.op_new_object(tmp_path, "Отчет", "Пустой")


def test_report_query_params(tmp_path):
    apply_result(scaffold.op_new_object(
        tmp_path, "Отчет", "Продажи",
        report={"source": "Заказы", "rows": ["Товар"], "measures": ["Сумма"]},
    ))
    result = scaffold.op_add_field(tmp_path / "Продажи.yaml", "параметр-запроса", "Период",
                                   type_="Дата")
    apply_result(result)
    parsed = _valid_yaml((tmp_path / "Продажи.yaml").read_text(encoding="utf-8"))
    assert parsed["ПараметрыЗапроса"] == [{"Имя": "Период", "Тип": "Дата"}]
    info = scaffold.object_info(tmp_path, name="Продажи")
    assert info["report_params"] == [{"name": "Период", "type": "Дата"}]


def test_localized_strings_mapping_sections(tmp_path):
    apply_result(scaffold.op_new_object(tmp_path, "ЛокализованныеСтроки", "СтрокиЛокализация"))
    yaml_path = tmp_path / "СтрокиЛокализация.yaml"
    apply_result(scaffold.op_add_field(yaml_path, "строка", "Задачи"))
    apply_result(scaffold.op_add_field(yaml_path, "строка", "Событие", type_="Событие"))
    apply_result(scaffold.op_add_field(yaml_path, "шаблон", "ТекущееВремя",
                                       type_="Текущее время: %0"))
    parsed = _valid_yaml(yaml_path.read_text(encoding="utf-8"))
    # The sections are key: value mappings (not lists). The default string value = the key.
    assert parsed["Строки"] == {"Задачи": "Задачи", "Событие": "Событие"}
    assert parsed["Шаблоны"] == {"ТекущееВремя": "Текущее время: %0"}  # the template is quoted

    with pytest.raises(ScaffoldError, match="уже есть"):
        scaffold.op_add_field(yaml_path, "строка", "Задачи")


def test_index_stub_field_and_note(tmp_path):
    subsystem = _make_project(tmp_path)
    apply_result(scaffold.op_new_object(subsystem, "Справочник", "Товары"))
    result = scaffold.op_add_field(subsystem / "Товары.yaml", "индекс", "ПоНаименованию")
    apply_result(result)
    parsed = _valid_yaml((subsystem / "Товары.yaml").read_text(encoding="utf-8"))
    assert parsed["Индексы"] == [{"Имя": "ПоНаименованию", "Поля": ["Реквизит1"]}]
    assert any("замените Поля" in n for n in result.notes)


# --- fields -------------------------------------------------------------------------------


@pytest.fixture()
def catalog_path(tmp_path) -> Path:
    path = tmp_path / "Товары.yaml"
    path.write_text(CATALOG, encoding="utf-8")
    return path


def test_add_field_attribute(catalog_path):
    result = scaffold.op_add_field(catalog_path, "реквизит", "Цвет", type_="Строка")
    apply_result(result)
    out = catalog_path.read_text(encoding="utf-8")
    items = section_items(out, "Реквизиты")
    assert [i["Имя"] for i in items] == ["Артикул", "Цвет"]
    assert len(items[1]["Ид"]) == 36
    assert _valid_yaml(out)


def test_add_field_rejects_duplicate_and_wrong_kind(catalog_path):
    with pytest.raises(ScaffoldError, match="уже есть"):
        scaffold.op_add_field(catalog_path, "реквизит", "Артикул")
    with pytest.raises(ScaffoldError, match="нет секции"):
        scaffold.op_add_field(catalog_path, "измерение", "Склад")
    with pytest.raises(ScaffoldError, match="Неизвестный вид"):
        scaffold.op_add_field(catalog_path, "колонка", "Икс")


def test_add_field_into_tabular(catalog_path):
    result = scaffold.op_add_field(
        catalog_path, "реквизит", "Количество", type_="Число", tabular="Состав"
    )
    apply_result(result)
    parsed = _valid_yaml(catalog_path.read_text(encoding="utf-8"))
    names = [f["Имя"] for f in parsed["ТабличныеЧасти"][0]["Реквизиты"]]
    assert names == ["Компонент", "Количество"]

    with pytest.raises(ScaffoldError, match="не найдена"):
        scaffold.op_add_field(catalog_path, "реквизит", "Х", tabular="Нет")


def test_add_tabular_with_starter_attribute(catalog_path):
    apply_result(scaffold.op_add_field(catalog_path, "табличная-часть", "Склады"))
    parsed = _valid_yaml(catalog_path.read_text(encoding="utf-8"))
    new_tc = parsed["ТабличныеЧасти"][1]
    assert new_tc["Имя"] == "Склады"
    assert new_tc["Реквизиты"][0]["Имя"] == "Реквизит1"


def test_the_first_attribute_replaces_the_starter_of_a_fresh_tabular(catalog_path):
    """A new tabular part is born with a placeholder; the first real attribute takes its place.

    Adding NEXT to it left the stub in the file, and it was deleted by hand after every add.
    """
    apply_result(scaffold.op_add_field(catalog_path, "табличная-часть", "Склады"))

    result = scaffold.op_add_field(
        catalog_path, "реквизит", "Склад", type_="Справочник.Товары.Ссылка", tabular="Склады",
    )
    apply_result(result)

    parsed = _valid_yaml(catalog_path.read_text(encoding="utf-8"))
    attributes = parsed["ТабличныеЧасти"][1]["Реквизиты"]
    assert [a["Имя"] for a in attributes] == ["Склад"]
    assert attributes[0]["Тип"] == "Справочник.Товары.Ссылка"
    assert len(attributes[0]["Ид"]) == 36
    assert any("заглушка" in note for note in result.notes)


def test_the_second_attribute_lands_next_to_the_first(catalog_path):
    apply_result(scaffold.op_add_field(catalog_path, "табличная-часть", "Склады"))
    apply_result(scaffold.op_add_field(catalog_path, "реквизит", "Склад", tabular="Склады"))

    result = scaffold.op_add_field(
        catalog_path, "реквизит", "Количество", type_="Число", tabular="Склады",
    )
    apply_result(result)

    parsed = _valid_yaml(catalog_path.read_text(encoding="utf-8"))
    attributes = parsed["ТабличныеЧасти"][1]["Реквизиты"]
    assert [a["Имя"] for a in attributes] == ["Склад", "Количество"]
    assert result.notes == []


def test_an_attribute_the_author_owns_is_not_taken_for_the_starter(catalog_path):
    """The stub is recognized by BOTH the name and the type: a renamed or retyped attribute
    belongs to the author, and an add must not overwrite it."""
    apply_result(scaffold.op_add_field(catalog_path, "табличная-часть", "Склады"))
    apply_result(scaffold.op_set_field_property(
        catalog_path, "реквизит", "Реквизит1", {"Тип": "Число"}, tabular="Склады",
    ))

    apply_result(scaffold.op_add_field(
        catalog_path, "реквизит", "Количество", type_="Число", tabular="Склады",
    ))

    parsed = _valid_yaml(catalog_path.read_text(encoding="utf-8"))
    attributes = parsed["ТабличныеЧасти"][1]["Реквизиты"]
    assert [a["Имя"] for a in attributes] == ["Реквизит1", "Количество"]


# --- subsystem and project ----------------------------------------------------------------


def test_add_subsystem_blocks(tmp_path):
    apply_result(
        scaffold.op_add_subsystem(
            tmp_path, "Задачи", representation="Мои задачи", uses=["Основное"]
        )
    )
    text = (tmp_path / "Задачи" / "Подсистема.yaml").read_text(encoding="utf-8")
    parsed = _valid_yaml(text)
    assert parsed["Использование"] == ["Основное"]
    assert parsed["Интерфейс"]["Представление"] == "Мои задачи"


def test_new_project_files(tmp_path):
    result = scaffold.op_new_project(tmp_path, "vendor", "Приложение")
    apply_result(result)
    project_dir = tmp_path / "vendor" / "Приложение"
    parsed = _valid_yaml((project_dir / "Проект.yaml").read_text(encoding="utf-8"))
    assert parsed["Поставщик"] == "vendor"
    assert parsed["РежимСовместимости"] == 9.0 or str(parsed["РежимСовместимости"]) == "9.0"
    assert (project_dir / "Проект.xbsl").is_file()
    assert (project_dir / "Основное" / "Подсистема.yaml").is_file()

    with pytest.raises(ScaffoldError, match="уже существует"):
        scaffold.op_new_project(tmp_path, "vendor", "Приложение")


# --- routes into an existing service ------------------------------------------------------


def test_add_route_extends_service(tmp_path):
    apply_result(scaffold.op_new_object(tmp_path, "HttpСервис", "Апи", routes="GET /, GET /{id}"))
    yaml_path = tmp_path / "Апи.yaml"
    result = scaffold.op_add_route(yaml_path, "DELETE /{id}, GET /")
    apply_result(result)
    parsed = _valid_yaml(yaml_path.read_text(encoding="utf-8"))
    by_template = {t["Шаблон"]: [m["Метод"] for m in t["Методы"]] for t in parsed["ШаблоныUrl"]}
    assert by_template["/{id}"] == ["GET", "DELETE"]
    assert by_template["/"] == ["GET"]  # the duplicate was not added
    assert any("уже есть" in note for note in result.notes)
    module = (tmp_path / "Апи.xbsl").read_text(encoding="utf-8")
    assert module.count("метод Удалить") == 1
    assert module.count("метод ОбработатьОшибку") == 1


def test_add_route_new_template(tmp_path):
    apply_result(scaffold.op_new_object(tmp_path, "HttpСервис", "Апи", routes="GET /"))
    apply_result(scaffold.op_add_route(tmp_path / "Апи.yaml", "GET /users"))
    parsed = _valid_yaml((tmp_path / "Апи.yaml").read_text(encoding="utf-8"))
    assert {t["Шаблон"] for t in parsed["ШаблоныUrl"]} == {"/", "/users"}


# --- forms --------------------------------------------------------------------------------


def _make_project(tmp_path) -> Path:
    """Mini project - vendor/Приложение/Основное with the folder hierarchy of real sources."""
    apply_result(scaffold.op_new_project(tmp_path, "vendor", "Приложение"))
    return tmp_path / "vendor" / "Приложение" / "Основное"


def test_add_forms_for_catalog(tmp_path):
    subsystem = _make_project(tmp_path)
    apply_result(scaffold.op_new_object(subsystem, "Справочник", "Товары"))
    yaml_path = subsystem / "Товары.yaml"
    apply_result(scaffold.op_add_field(yaml_path, "реквизит", "Цвет"))
    apply_result(scaffold.op_add_field(yaml_path, "реквизит", "Вес", type_="Число"))

    result = scaffold.op_add_form(tmp_path, name="Товары")
    apply_result(result)

    form_obj = (subsystem / "ТоварыФормаОбъекта.yaml").read_text(encoding="utf-8")
    parsed = _valid_yaml(form_obj)
    assert parsed["Наследует"]["Тип"] == "ФормаОбъекта<Товары.Объект>"
    assert "ПолеВвода<Строка>" in form_obj and "Значение: =Объект.Наименование" in form_obj
    assert "Значение: =Объект.Вес" in form_obj

    form_list = (subsystem / "ТоварыФормаСписка.yaml").read_text(encoding="utf-8")
    parsed_list = _valid_yaml(form_list)
    ns_type = "ДинамическийСписок<vendor::Приложение::Основное::ТоварыФормаСписка.ДанныеСтрокиСписка>"
    assert parsed_list["Свойства"][0]["Тип"] == ns_type
    # A dynamic list column addresses the row field via ПолеЗначения (which also enables
    # sorting by the column) - as in the project's working forms and the reference ones.
    columns = parsed_list["Наследует"]["Содержимое"]["Содержимое"]["Колонки"]
    assert [c["ПолеЗначения"] for c in columns] == ["Наименование", "Цвет", "Вес"]
    assert [c["Заголовок"] for c in columns] == ["Наименование", "Цвет", "Вес"]

    owner = _valid_yaml(yaml_path.read_text(encoding="utf-8"))
    assert owner["Интерфейс"]["Объект"]["Форма"] == "ТоварыФормаОбъекта"
    assert owner["Интерфейс"]["Список"]["Форма"] == "ТоварыФормаСписка"
    assert owner["Интерфейс"]["ИспользоватьСозданиеПриВводе"] is True or owner["Интерфейс"]["ИспользоватьСозданиеПриВводе"] == "Истина"


def test_add_forms_skips_existing(tmp_path):
    subsystem = _make_project(tmp_path)
    apply_result(scaffold.op_new_object(subsystem, "Справочник", "Товары"))
    apply_result(scaffold.op_add_form(tmp_path, name="Товары"))
    repeat = scaffold.op_add_form(tmp_path, name="Товары")
    assert any("уже существует" in note for note in repeat.notes)
    assert not repeat.changes


def test_add_form_layout_with_tabulars(tmp_path):
    subsystem = _make_project(tmp_path)
    apply_result(scaffold.op_new_object(subsystem, "Документ", "Заказ"))
    yaml_path = subsystem / "Заказ.yaml"
    apply_result(scaffold.op_add_field(yaml_path, "табличная-часть", "Строки"))
    apply_result(scaffold.op_add_form(tmp_path, name="Заказ", forms=["object"]))
    form = (subsystem / "ЗаказФормаОбъекта.yaml").read_text(encoding="utf-8")
    assert "ШаблонФормыСРазделами" in form
    assert "Таблица<ИсточникДанныхМассив<Заказ.Строки>>" in form
    assert "=Компоненты.Строки.ДобавитьСтроку" in form
    assert _valid_yaml(form)
    # The mandatory document attribute Дата made it into the form (it is created in the yaml
    # right away). Номер is optional and absent by default - the form must not get a phantom
    # Номер field.
    assert "Значение: =Объект.Дата" in form
    assert "=Объект.Номер" not in form


def test_add_report_form(tmp_path):
    subsystem = _make_project(tmp_path)
    apply_result(
        scaffold.op_new_object(
            subsystem, "Отчет", "Продажи",
            report={"source": "Заказы", "rows": ["Товар"], "measures": ["Сумма"]},
        )
    )
    apply_result(scaffold.op_add_form(tmp_path, name="Продажи"))
    form = (subsystem / "ПродажиФормаОтчета.yaml").read_text(encoding="utf-8")
    parsed = _valid_yaml(form)
    assert parsed["Наследует"]["Тип"] == "ФормаОтчета"
    owner = _valid_yaml((subsystem / "Продажи.yaml").read_text(encoding="utf-8"))
    assert owner["Интерфейс"]["Форма"] == "ПродажиФормаОтчета"


def test_hierarchical_list_form(tmp_path):
    subsystem = _make_project(tmp_path)
    apply_result(scaffold.op_new_object(subsystem, "Справочник", "Разделы"))
    yaml_path = subsystem / "Разделы.yaml"
    text = yaml_path.read_text(encoding="utf-8")
    yaml_path.write_text(text + "Иерархический: Истина\n", encoding="utf-8")
    apply_result(scaffold.op_add_form(tmp_path, name="Разделы", forms=["list"]))
    form = (subsystem / "РазделыФормаСписка.yaml").read_text(encoding="utf-8")
    row = "vendor::Приложение::Основное::РазделыФормаСписка.ДанныеСтрокиСписка"
    assert f"ДинамическийСписок<{row}, {row}>" in form
    # A hierarchy named "Иерархия" does not exist (that is the name of the query language
    # table) - item hierarchy uses the ПоУмолчанию mode.
    hierarchy = _valid_yaml(form)["Свойства"][0]["ЗначениеПоУмолчанию"]["ИспользуемаяИерархия"]
    assert hierarchy == {"Тип": "РежимИерархии", "Значение": "ПоУмолчанию"}
    assert "Выражение: Родитель" in form
    assert _valid_yaml(form)


# --- introspection ------------------------------------------------------------------------


def test_object_info_and_project_info(tmp_path):
    subsystem = _make_project(tmp_path)
    apply_result(scaffold.op_new_object(subsystem, "Справочник", "Товары"))
    apply_result(scaffold.op_add_field(subsystem / "Товары.yaml", "реквизит", "Цвет"))

    info = scaffold.object_info(tmp_path, name="Товары")
    assert info["kind"] == "Справочник"
    assert info["namespace"] == "vendor::Приложение::Основное"
    assert [f["name"] for f in info["fields"]] == ["Наименование", "Цвет"]
    assert info["suggested_layout"] == "simple"
    assert info["existing_forms"] == {"ФормаОбъекта": None, "ФормаСписка": None}

    overview = scaffold.project_info(tmp_path)
    assert overview["projects"][0]["name"] == "Приложение"
    assert any(o["name"] == "Товары" for o in overview["objects"])

    with pytest.raises(ScaffoldError, match="не найден"):
        scaffold.object_info(tmp_path, name="Нет")


# --- object rename ------------------------------------------------------------------------


def _make_rename_project(tmp_path) -> Path:
    """A project with the Склады catalog, its forms, and same-name traps."""
    subsystem = _make_project(tmp_path)
    apply_result(scaffold.op_new_object(subsystem, "Справочник", "Склады"))
    apply_result(scaffold.op_new_object(subsystem, "Справочник", "СкладыАрхив"))
    apply_result(scaffold.op_new_object(subsystem, "Справочник", "Заказы"))
    apply_result(scaffold.op_add_form(tmp_path, name="Склады"))

    # Object presentation and form title.
    yaml_path = subsystem / "Склады.yaml"
    yaml_path.write_text(
        yaml_path.read_text(encoding="utf-8") + "Представление: Склад\n", encoding="utf-8"
    )

    # Trap attribute - named like the object (must not get renamed).
    apply_result(scaffold.op_add_field(subsystem / "Заказы.yaml", "реквизит", "Склады",
                                       type_="Склады.Ссылка?"))

    (subsystem / "Склады.Объект.xbsl").write_text(
        "метод ПослеЗаписи()\n    Склады.ПересчитатьРазрешенияДоступа()\n;\n",
        encoding="utf-8",
    )
    (subsystem / "Заказы.xbsl").write_text(
        'импорт Склады\n'
        "\n"
        "метод Показать()\n"
        "    пер С: Склады.Ссылка?\n"
        "    знч Данные = Запрос{\n"
        "        ВЫБРАТЬ С.Наименование ИЗ Склады КАК С\n"
        "    }\n"
        '    Сообщить("Склады не изменились")  // строка не правится, а Склады в комментарии – да\n'
        "    возврат Объект.Склады\n"
        ";\n",
        encoding="utf-8",
    )
    # Card list row component.
    (subsystem / "СтрокаСпискаСклады.yaml").write_text(
        "ВидЭлемента: КомпонентИнтерфейса\nИд: x\nИмя: СтрокаСпискаСклады\n", encoding="utf-8"
    )
    return subsystem


def test_rename_object_files_and_references(tmp_path):
    subsystem = _make_rename_project(tmp_path)
    result = scaffold.op_rename_object(
        tmp_path, "Склады", "Хранилища",
        new_presentation="Хранилище", old_presentation="Склад",
    )

    renamed = {r.old_path.name: r.new_path.name for r in result.renames}
    assert renamed == {
        "Склады.yaml": "Хранилища.yaml",
        "Склады.Объект.xbsl": "Хранилища.Объект.xbsl",
        "СкладыФормаОбъекта.yaml": "ХранилищаФормаОбъекта.yaml",
        "СкладыФормаСписка.yaml": "ХранилищаФормаСписка.yaml",
        "СтрокаСпискаСклады.yaml": "СтрокаСпискаХранилища.yaml",
    }
    assert "СкладыАрхив.yaml" not in renamed

    apply_result(result)
    assert (subsystem / "Хранилища.yaml").is_file()
    assert not (subsystem / "Склады.yaml").exists()
    assert (subsystem / "СкладыАрхив.yaml").is_file()

    owner = (subsystem / "Хранилища.yaml").read_text(encoding="utf-8")
    assert "Имя: Хранилища" in owner
    assert "Представление: Хранилище" in owner
    assert "Форма: ХранилищаФормаОбъекта" in owner
    assert _valid_yaml(owner)

    form = (subsystem / "ХранилищаФормаОбъекта.yaml").read_text(encoding="utf-8")
    assert "Имя: ХранилищаФормаОбъекта" in form
    assert "ФормаОбъекта<Хранилища.Объект>" in form
    assert "Заголовок: Хранилище" in form
    assert _valid_yaml(form)

    list_form = (subsystem / "ХранилищаФормаСписка.yaml").read_text(encoding="utf-8")
    assert "Таблица: Хранилища" in list_form
    assert "ХранилищаФормаСписка.ДанныеСтрокиСписка" in list_form
    assert _valid_yaml(list_form)

    orders = (subsystem / "Заказы.yaml").read_text(encoding="utf-8")
    assert "Тип: Хранилища.Ссылка?" in orders
    assert "Имя: Склады" in orders  # the namesake attribute is not renamed

    module = (subsystem / "Заказы.xbsl").read_text(encoding="utf-8")
    assert "импорт Склады" in module          # the subsystem in the import is untouched
    assert "пер С: Хранилища.Ссылка?" in module
    assert "ИЗ Хранилища КАК С" in module
    assert '"Склады не изменились"' in module  # the string literal is preserved
    assert "Хранилища в комментарии" in module
    assert "Объект.Склады" in module           # a member after a dot is a foreign name

    object_module = (subsystem / "Хранилища.Объект.xbsl").read_text(encoding="utf-8")
    assert "Хранилища.ПересчитатьРазрешенияДоступа()" in object_module


def test_rename_object_errors(tmp_path):
    subsystem = _make_rename_project(tmp_path)
    with pytest.raises(ScaffoldError, match="уже занято"):
        scaffold.op_rename_object(tmp_path, "Склады", "Заказы")
    with pytest.raises(ScaffoldError, match="не найден"):
        scaffold.op_rename_object(tmp_path, "Нет", "Хранилища")
    with pytest.raises(ScaffoldError, match="совпадают"):
        scaffold.op_rename_object(tmp_path, "Склады", "Склады")

    # Namesakes in two subsystems - without a file it is an error, with a file the
    # specified one gets renamed.
    apply_result(scaffold.op_add_subsystem(subsystem.parent, "Дальняя"))
    other = subsystem.parent / "Дальняя"
    apply_result(scaffold.op_new_object(other, "Справочник", "Склады"))
    with pytest.raises(ScaffoldError, match="неоднозначно"):
        scaffold.op_rename_object(tmp_path, "Склады", "Хранилища")
    result = scaffold.op_rename_object(
        tmp_path, "Склады", "Хранилища", yaml_path=other / "Склады.yaml"
    )
    assert [r.old_path for r in result.renames] == [other / "Склады.yaml"]


def test_rename_object_dry_dict_shape(tmp_path):
    _make_rename_project(tmp_path)
    result = scaffold.op_rename_object(tmp_path, "Склады", "Хранилища")
    plan = result.as_dict(content=False)
    assert plan["renames"] and all("from" in r and "to" in r for r in plan["renames"])
    assert plan["files"] and all("content" not in f for f in plan["files"])
    assert any("замен" in note for note in plan["notes"])
    # Nothing is written - the operation only computes the changes.
    assert (tmp_path / "vendor" / "Приложение" / "Основное" / "Склады.yaml").is_file()


# --- rename that only changes letter case --------------------------------------------------
#
# The class the tests below are about: `Склады` -> `склады`. On a case-insensitive
# filesystem (Windows, macOS by default) the old and the new file are one and the same, so
# the plain existence check reads the target as an occupied name and the whole rename is
# refused; the assertions therefore ask the OS for the REAL name (os.listdir) instead of
# Path.exists, which answers True for either spelling there.


def _case_insensitive_fs(directory: Path) -> bool:
    probe = directory / "XbslCaseProbe.tmp"
    probe.write_text("x", encoding="utf-8")
    try:
        return (directory / "xbslcaseprobe.tmp").exists()
    finally:
        probe.unlink()


def _names(directory: Path) -> set[str]:
    """The names as the filesystem itself stores them."""
    return set(os.listdir(directory))


def test_file_rename_case_only_flag():
    assert FileRename(Path("a/Товары.yaml"), Path("a/товары.yaml")).case_only
    assert FileRename(Path("a/Товары.yaml"), Path("a/ТовАры.yaml")).case_only
    assert not FileRename(Path("a/Товары.yaml"), Path("a/Склады.yaml")).case_only
    assert not FileRename(Path("a/Товары.yaml"), Path("b/Товары.yaml")).case_only
    assert not FileRename(Path("a/Товары.yaml"), Path("a/Товары.yaml")).case_only


def test_rename_clashes_only_with_a_foreign_file(tmp_path):
    goods = tmp_path / "Товары.yaml"
    goods.write_text("a", encoding="utf-8")
    (tmp_path / "Склады.yaml").write_text("b", encoding="utf-8")

    assert scaffold._rename_clashes(FileRename(goods, tmp_path / "Склады.yaml"))
    assert not scaffold._rename_clashes(FileRename(goods, tmp_path / "Прочее.yaml"))
    # The same file under the other casing is not a clash on either filesystem: where the
    # target exists it IS this file, where it does not exist there is nothing to clash with.
    assert not scaffold._rename_clashes(FileRename(goods, tmp_path / "товары.yaml"))


def test_rename_object_case_only(tmp_path):
    subsystem = _make_rename_project(tmp_path)
    # The plain module of the object - the third shape of a satellite file, next to
    # <Имя>.yaml and <Имя>.<Часть>.xbsl.
    (subsystem / "Склады.xbsl").write_text("метод Пусто()\n;\n", encoding="utf-8")
    result = scaffold.op_rename_object(tmp_path, "Склады", "склады")

    renamed = {r.old_path.name: r.new_path.name for r in result.renames}
    assert renamed == {
        "Склады.yaml": "склады.yaml",
        "Склады.xbsl": "склады.xbsl",
        "Склады.Объект.xbsl": "склады.Объект.xbsl",
        "СкладыФормаОбъекта.yaml": "складыФормаОбъекта.yaml",
        "СкладыФормаСписка.yaml": "складыФормаСписка.yaml",
        "СтрокаСпискаСклады.yaml": "СтрокаСпискасклады.yaml",
    }
    assert all(r.case_only for r in result.renames)
    # The note about the two steps and about version control belongs to the filesystem that
    # actually merges the two names; on a case-sensitive one the rename is ordinary and the
    # note would only be noise.
    note = [n for n in result.notes if "только регистром" in n]
    if _case_insensitive_fs(subsystem):
        assert note and "git" in note[0]
    else:
        assert not note

    apply_result(result)
    names = _names(subsystem)
    assert "склады.yaml" in names and "Склады.yaml" not in names
    assert "склады.xbsl" in names and "Склады.xbsl" not in names
    assert "склады.Объект.xbsl" in names and "Склады.Объект.xbsl" not in names
    assert "складыФормаОбъекта.yaml" in names
    assert "СтрокаСпискасклады.yaml" in names
    assert "СкладыАрхив.yaml" in names  # the namesake object is untouched
    # The intermediate name of the two-step rename is not left behind.
    assert not [n for n in names if "xbsl-rename-tmp" in n]

    owner = (subsystem / "склады.yaml").read_text(encoding="utf-8")
    assert "Имя: склады" in owner
    assert "Форма: складыФормаОбъекта" in owner
    assert _valid_yaml(owner)

    orders = (subsystem / "Заказы.yaml").read_text(encoding="utf-8")
    assert "Тип: склады.Ссылка?" in orders
    module = (subsystem / "Заказы.xbsl").read_text(encoding="utf-8")
    assert "пер С: склады.Ссылка?" in module


def test_rename_object_case_only_inside_the_name(tmp_path):
    """The case changes in the middle of the name - the same class, and the owner's link."""
    subsystem = _make_rename_project(tmp_path)
    result = scaffold.op_rename_object(tmp_path, "СкладыФормаОбъекта", "СкладыФормаобъекта")
    apply_result(result)

    names = _names(subsystem)
    assert "СкладыФормаобъекта.yaml" in names
    assert "СкладыФормаОбъекта.yaml" not in names
    owner = (subsystem / "Склады.yaml").read_text(encoding="utf-8")
    assert "Форма: СкладыФормаобъекта" in owner
    assert _valid_yaml(owner)


def test_rename_object_case_only_keeps_a_foreign_file(tmp_path):
    """A name taken by ANOTHER file is still refused - the case-only branch must not eat it."""
    subsystem = _make_rename_project(tmp_path)
    if _case_insensitive_fs(subsystem):
        # Заказы.yaml is a different object: on a case-insensitive filesystem the target
        # name resolves to it, so the rename would destroy it.
        with pytest.raises(ScaffoldError, match="уже существует"):
            scaffold.op_rename_object(tmp_path, "Склады", "заказы")
    else:
        # Here the two names coexist; the rename is legitimate and Заказы.yaml stays put.
        apply_result(scaffold.op_rename_object(tmp_path, "Склады", "заказы"))
        assert {"заказы.yaml", "Заказы.yaml"} <= _names(subsystem)


def _force_two_step(monkeypatch) -> None:
    """Take the two-step branch regardless of the filesystem under the test run.

    Without this the branch is only reachable on a case-insensitive filesystem, and CI runs
    on a case-sensitive one - the rollback would go untested exactly where it is checked.
    """
    monkeypatch.setattr(scaffold, "_one_file_under_both_names", lambda rename: True)


def test_rename_file_two_steps_through_a_temporary_name(tmp_path, monkeypatch):
    path = tmp_path / "Товары.yaml"
    path.write_text("x", encoding="utf-8")
    _force_two_step(monkeypatch)
    steps = []
    real_rename = Path.rename
    monkeypatch.setattr(
        Path, "rename", lambda self, target: (steps.append(target.name), real_rename(self, target))[1]
    )

    scaffold._rename_file(FileRename(path, tmp_path / "товары.yaml"))
    assert steps == ["Товары.yaml.xbsl-rename-tmp", "товары.yaml"]
    assert _names(tmp_path) == {"товары.yaml"}


def test_rename_file_two_step_rolls_back(tmp_path, monkeypatch):
    """A failure of the second step leaves neither a temporary file nor a lost original."""
    path = tmp_path / "Товары.yaml"
    path.write_text("x", encoding="utf-8")
    _force_two_step(monkeypatch)
    real_rename = Path.rename
    calls = []

    def failing(self, target):
        calls.append(target)
        if len(calls) == 2:
            raise OSError("boom")
        return real_rename(self, target)

    monkeypatch.setattr(Path, "rename", failing)
    with pytest.raises(OSError, match="boom"):
        scaffold._rename_file(FileRename(path, tmp_path / "товары.yaml"))
    monkeypatch.undo()

    assert _names(tmp_path) == {"Товары.yaml"}
    assert path.read_text(encoding="utf-8") == "x"


def test_free_temp_path_skips_taken_names(tmp_path):
    path = tmp_path / "Товары.yaml"
    path.write_text("x", encoding="utf-8")
    first = scaffold._free_temp_path(path)
    assert first.name == "Товары.yaml.xbsl-rename-tmp"
    first.write_text("busy", encoding="utf-8")
    assert scaffold._free_temp_path(path).name == "Товары.yaml.xbsl-rename-tmp1"


# --- card list form -----------------------------------------------------------------------


def _cards_project(tmp_path, fields: list[tuple[str, str]]) -> Path:
    subsystem = _make_project(tmp_path)
    apply_result(scaffold.op_new_object(subsystem, "Справочник", "Сотрудники"))
    for name, type_ in fields:
        apply_result(scaffold.op_add_field(subsystem / "Сотрудники.yaml", "реквизит", name,
                                           type_=type_))
    return subsystem


def test_cards_list_form_without_photo(tmp_path):
    subsystem = _cards_project(tmp_path, [("Должность", "Строка"), ("Отдел", "Отделы.Ссылка?")])
    result = scaffold.op_add_form(tmp_path, name="Сотрудники", forms=["list-cards"])
    apply_result(result)

    form = _valid_yaml((subsystem / "СотрудникиФормаСписка.yaml").read_text(encoding="utf-8"))
    component = form["Наследует"]["Содержимое"]["Содержимое"]
    row_type = "vendor::Приложение::Основное::СотрудникиФормаСписка.ДанныеСтрокиСписка"
    assert component["Тип"] == f"ПроизвольныйСписок<ДинамическийСписок<{row_type}>>"
    assert component["ТипКомпонентаСтроки"] == "СтрокаСпискаСотрудники"
    assert form["Наследует"]["КомпонентТаблицы"] == "=Компоненты.ОсновнаяТаблица"

    grid = component["КонтейнерСтрок"]
    assert grid["Компоновка"] == "Матричная"
    settings = grid["НастройкиМатричнойКомпоновки"]
    assert settings["АвтоЗаполнение"] == "ДобавлятьКолонкиИСтроки"
    assert settings["ОписаниеАвтоматическихКолонок"]["МинимальнаяШирина"] == 400

    # List fields - Ссылка for navigation plus the fields the card shows.
    fields = [f["Выражение"] for f in form["Свойства"][0]["ЗначениеПоУмолчанию"]["Поля"]]
    assert fields == ["Ссылка", "Наименование", "Должность", "Отдел"]

    row = _valid_yaml((subsystem / "СтрокаСпискаСотрудники.yaml").read_text(encoding="utf-8"))
    assert row["Имя"] == "СтрокаСпискаСотрудники"
    card = row["Наследует"]["Содержимое"]
    assert row["Наследует"]["Тип"] == f"ПроизвольнаяСтрокаСписка<СтрокаДинамическогоСписка<{row_type}>>"
    assert card["Тип"] == "СтандартнаяКарточка"
    assert card["Заголовок"] == "=ДанныеСтроки.Данные.Наименование"
    # A string field goes straight into Содержимое, a reference - as a Надпись; both in a Группа.
    labels = card["Содержимое"]["Содержимое"]
    assert [l["Значение"] for l in labels] == [
        "=ДанныеСтроки.Данные.Должность", "=ДанныеСтроки.Данные.Отдел",
    ]

    owner = _valid_yaml((subsystem / "Сотрудники.yaml").read_text(encoding="utf-8"))
    assert owner["Интерфейс"]["Список"]["Форма"] == "СотрудникиФормаСписка"


def test_cards_single_text_field_goes_inline(tmp_path):
    subsystem = _cards_project(tmp_path, [("Должность", "Строка")])
    apply_result(scaffold.op_add_form(tmp_path, name="Сотрудники", forms=["list-cards"]))
    row = _valid_yaml((subsystem / "СтрокаСпискаСотрудники.yaml").read_text(encoding="utf-8"))
    assert row["Наследует"]["Содержимое"]["Содержимое"] == "=ДанныеСтроки.Данные.Должность"


def test_cards_list_form_with_photo(tmp_path):
    subsystem = _cards_project(tmp_path, [("Фото", "ДвоичныйОбъект.Ссылка?")])
    result = scaffold.op_add_form(
        tmp_path, name="Сотрудники", forms=["list-cards"],
        card_placeholder="Ресурс{Аккаунт.svg}.Ссылка",
    )
    apply_result(result)

    form = _valid_yaml((subsystem / "СотрудникиФормаСписка.yaml").read_text(encoding="utf-8"))
    settings = form["Наследует"]["Содержимое"]["Содержимое"]["КонтейнерСтрок"]["НастройкиМатричнойКомпоновки"]
    assert settings["ОписаниеАвтоматическихКолонок"]["МинимальнаяШирина"] == 250  # photo - narrower

    row = _valid_yaml((subsystem / "СтрокаСпискаСотрудники.yaml").read_text(encoding="utf-8"))
    card = row["Наследует"]["Содержимое"]
    assert card["Тип"] == "ПроизвольнаяКарточка"
    stack = card["Содержимое"]
    assert stack["Компоновка"] == "Вертикальная"
    picture, label = stack["Содержимое"]
    assert picture["Тип"] == "Картинка"
    assert picture["Масштабирование"] == "Пропорционально"
    assert picture["Изображение"] == "=ДанныеСтроки.Данные.Фото ?? Ресурс{Аккаунт.svg}.Ссылка"
    assert picture["РастягиватьПоВертикали"] == "Ложь"  # otherwise Высота stretches to the rest
    assert label["Значение"] == "=ДанныеСтроки.Данные.Наименование"


def test_cards_document_formats_date_and_notes_hidden_fields(tmp_path):
    subsystem = _make_project(tmp_path)
    apply_result(scaffold.op_new_object(subsystem, "Документ", "Заказы"))
    # A document's Номер is optional and not created by default - declare it explicitly so
    # it becomes the card title (the starter Дата is already in the yaml).
    for name in ("Номер", "ПолеА", "ПолеБ", "ПолеВ", "ПолеГ"):
        apply_result(scaffold.op_add_field(subsystem / "Заказы.yaml", "реквизит", name))
    result = scaffold.op_add_form(tmp_path, name="Заказы", forms=["list-cards"])
    apply_result(result)

    row = _valid_yaml((subsystem / "СтрокаСпискаЗаказы.yaml").read_text(encoding="utf-8"))
    card = row["Наследует"]["Содержимое"]
    # The title is Номер (the first string field), Дата gets formatted, extra fields did not fit.
    assert card["Заголовок"] == "=ДанныеСтроки.Данные.Номер"
    values = [l["Значение"] for l in card["Содержимое"]["Содержимое"]]
    assert values[0] == '=ДанныеСтроки.Данные.Дата.Представление("дд ММММ гггг ЧЧ:мм")'
    assert len(values) == 3
    assert any("Не попали в карточку: ПолеВ, ПолеГ" in n for n in result.notes)
    assert any("В карточку вынесены поля: Номер, Дата, ПолеА, ПолеБ" in n for n in result.notes)

    form = _valid_yaml((subsystem / "ЗаказыФормаСписка.yaml").read_text(encoding="utf-8"))
    sort = form["Свойства"][0]["ЗначениеПоУмолчанию"]["Сортировка"]
    assert sort[0]["Поле"] == "Дата"


def test_cards_conflicts_and_unknown_form_kind(tmp_path):
    _cards_project(tmp_path, [])
    with pytest.raises(ScaffoldError, match="выберите одну"):
        scaffold.op_add_form(tmp_path, name="Сотрудники", forms=["list", "list-cards"])
    with pytest.raises(ScaffoldError, match="Неизвестный вид формы"):
        scaffold.op_add_form(tmp_path, name="Сотрудники", forms=["cards"])

    subsystem = tmp_path / "vendor" / "Приложение" / "Основное"
    apply_result(scaffold.op_add_form(tmp_path, name="Сотрудники", forms=["list-cards"]))

    # The form already exists - neither it nor its row component is touched.
    again = scaffold.op_add_form(tmp_path, name="Сотрудники", forms=["list-cards"])
    assert any("СотрудникиФормаСписка.yaml уже существует" in n for n in again.notes)
    assert again.changes == []

    # The form was deleted, the component stayed - the form is recreated, the component is skipped.
    (subsystem / "СотрудникиФормаСписка.yaml").unlink()
    partial = scaffold.op_add_form(tmp_path, name="Сотрудники", forms=["list-cards"])
    created = [c.path.name for c in partial.changes if c.created]
    assert created == ["СотрудникиФормаСписка.yaml"]
    assert any("СтрокаСпискаСотрудники.yaml уже существует" in n for n in partial.notes)


# --- access control -----------------------------------------------------------------------


def test_access_info_and_set_default(tmp_path):
    subsystem = _make_project(tmp_path)
    apply_result(scaffold.op_new_object(subsystem, "Справочник", "Товары"))
    apply_result(scaffold.op_add_field(subsystem / "Товары.yaml", "реквизит", "Цвет"))
    yaml_path = subsystem / "Товары.yaml"

    # No section - the summary is None (meaning РазрешеноАдминистраторам is in effect).
    assert scaffold.object_info(tmp_path, name="Товары")["access"] is None

    result = scaffold.op_set_access(tmp_path, name="Товары", default="РазрешеноАутентифицированным")
    apply_result(result)
    text = yaml_path.read_text(encoding="utf-8")
    parsed = _valid_yaml(text)
    assert parsed["КонтрольДоступа"]["Разрешения"]["ПоУмолчанию"] == "РазрешеноАутентифицированным"
    assert parsed["Реквизиты"][0]["Имя"] == "Цвет"  # the data section is unaffected
    assert any("нет секции" in n for n in result.notes)

    info = scaffold.object_info(tmp_path, name="Товары")
    assert info["access"]["default"] == "РазрешеноАутентифицированным"
    assert info["access_rights"] == ["Создание", "Чтение", "Изменение", "Удаление"]

    # Setting the same value again - the file is not touched.
    again = scaffold.op_set_access(tmp_path, name="Товары", default="РазрешеноАутентифицированным")
    assert again.changes == []
    assert any("уже имеют такие значения" in n for n in again.notes)


def test_access_set_individual_rights_precisely(tmp_path):
    subsystem = _make_project(tmp_path)
    apply_result(scaffold.op_new_object(subsystem, "Справочник", "Товары",
                                        access="РазрешеноАдминистраторам"))
    yaml_path = subsystem / "Товары.yaml"
    apply_result(scaffold.op_set_access(
        tmp_path, name="Товары",
        permissions={"Чтение": "РазрешеноВсем", "Создание": "РазрешеноАутентифицированным"},
    ))
    perms = _valid_yaml(yaml_path.read_text(encoding="utf-8"))["КонтрольДоступа"]["Разрешения"]
    # The existing ПоУмолчанию is preserved, the new rights are appended.
    assert perms == {
        "ПоУмолчанию": "РазрешеноАдминистраторам",
        "Чтение": "РазрешеноВсем",
        "Создание": "РазрешеноАутентифицированным",
    }

    # Replacing the value of an existing right - in place.
    apply_result(scaffold.op_set_access(tmp_path, name="Товары",
                                        permissions={"Чтение": "РазрешеноАутентифицированным"}))
    perms = _valid_yaml(yaml_path.read_text(encoding="utf-8"))["КонтрольДоступа"]["Разрешения"]
    assert perms["Чтение"] == "РазрешеноАутентифицированным"
    assert len(perms) == 3


def test_access_per_object_requires_calc_by(tmp_path):
    subsystem = _make_project(tmp_path)
    apply_result(scaffold.op_new_object(subsystem, "Справочник", "Задачи"))
    apply_result(scaffold.op_add_field(subsystem / "Задачи.yaml", "реквизит", "Ответственный",
                                       type_="Пользователи.Ссылка?"))
    with pytest.raises(ScaffoldError, match="РасчетРазрешенийПо"):
        scaffold.op_set_access(tmp_path, name="Задачи",
                               default="РазрешенияВычисляютсяДляКаждогоОбъекта")

    result = scaffold.op_set_access(
        tmp_path, name="Задачи", default="РазрешенияВычисляютсяДляКаждогоОбъекта",
        calc_by=["Ответственный"],
    )
    apply_result(result)
    access = _valid_yaml((subsystem / "Задачи.yaml").read_text(encoding="utf-8"))["КонтрольДоступа"]
    assert access["Разрешения"]["ПоУмолчанию"] == "РазрешенияВычисляютсяДляКаждогоОбъекта"
    assert access["РасчетРазрешенийПо"] == ["Ответственный"]
    assert any("ВычислитьРазрешенияДоступаДляОбъектов" in n for n in result.notes)

    info = scaffold.object_info(tmp_path, name="Задачи")
    assert info["access"]["calc_by"] == ["Ответственный"]


def test_access_validation(tmp_path):
    subsystem = _make_project(tmp_path)
    apply_result(scaffold.op_new_object(subsystem, "Справочник", "Товары"))
    apply_result(scaffold.op_new_object(subsystem, "ОбщийМодуль", "Хелпер"))
    apply_result(scaffold.op_new_object(subsystem, "HttpСервис", "Каталог"))

    with pytest.raises(ScaffoldError, match="Недопустимый способ"):
        scaffold.op_set_access(tmp_path, name="Товары", default="РазрешеноГостям")
    with pytest.raises(ScaffoldError, match="не поддерживает управление доступом"):
        scaffold.op_set_access(tmp_path, name="Хелпер", default="РазрешеноВсем")
    with pytest.raises(ScaffoldError, match="нет права 'Вызов'"):
        scaffold.op_set_access(tmp_path, name="Товары", permissions={"Вызов": "РазрешеноВсем"})
    with pytest.raises(ScaffoldError, match="Нечего менять"):
        scaffold.op_set_access(tmp_path, name="Товары")

    # The service has its own Вызов right; URL templates are not touched.
    apply_result(scaffold.op_set_access(tmp_path, name="Каталог",
                                        permissions={"Вызов": "РазрешеноВсем"}))
    service = _valid_yaml((subsystem / "Каталог.yaml").read_text(encoding="utf-8"))
    assert service["КонтрольДоступа"]["Разрешения"]["Вызов"] == "РазрешеноВсем"
    assert service["ШаблоныUrl"]

    # A custom right (ПравоНаЭлемент) is accepted as is.
    apply_result(scaffold.op_set_access(
        tmp_path, name="Товары",
        permissions={"ПравоНаТовар.ИзменениеЦены": "РазрешенияВычисляются"},
    ))
    perms = _valid_yaml((subsystem / "Товары.yaml").read_text(encoding="utf-8"))["КонтрольДоступа"]["Разрешения"]
    assert perms["ПравоНаТовар.ИзменениеЦены"] == "РазрешенияВычисляются"


def test_project_info_access_summary(tmp_path):
    subsystem = _make_project(tmp_path)
    apply_result(scaffold.op_new_object(subsystem, "Справочник", "Товары",
                                        access="РазрешеноАутентифицированным"))
    apply_result(scaffold.op_new_object(subsystem, "Справочник", "Склады"))
    apply_result(scaffold.op_new_object(subsystem, "ОбщийМодуль", "Хелпер"))

    overview = scaffold.project_info(tmp_path)
    by_name = {o["name"]: o for o in overview["objects"]}
    assert by_name["Товары"]["access_default"] == "РазрешеноАутентифицированным"
    assert by_name["Склады"]["access_default"] is None  # no section
    assert "access_default" not in by_name["Хелпер"]  # a kind without access control
    assert "РазрешеноВсем" in overview["access_methods"]
    assert overview["access_kind_rights"]["HttpСервис"] == ["Вызов"]


def test_report_form_registered_when_interface_exists(tmp_path):
    subsystem = _make_project(tmp_path)
    apply_result(scaffold.op_new_object(
        subsystem, "Отчет", "Продажи2",
        report={"source": "Регистр.Продажи", "rows": ["Клиент"], "measures": ["Сумма"]},
    ))
    yaml_path = subsystem / "Продажи2.yaml"
    # The report already has an Интерфейс section - the form registration must append into it.
    yaml_path.write_text(
        yaml_path.read_text(encoding="utf-8") + "Интерфейс:\n    ВключатьВАвтоИнтерфейс: Ложь\n",
        encoding="utf-8",
    )
    apply_result(scaffold.op_add_form(tmp_path, name="Продажи2", forms=["report"]))
    owner = _valid_yaml(yaml_path.read_text(encoding="utf-8"))
    assert owner["Интерфейс"]["Форма"] == "Продажи2ФормаОтчета"
    assert owner["Интерфейс"]["ВключатьВАвтоИнтерфейс"] == "Ложь"

    again = scaffold.op_add_form(tmp_path, name="Продажи2", forms=["report"], overwrite=True)
    assert any("уже зарегистрирована" in n for n in again.notes)


# --- object kinds: coverage and paired files ----------------------------------------------


def test_every_bare_kind_creates_valid_yaml(tmp_path):
    """Every kind with no mandatory parameters gets created and yields parseable yaml."""
    for kind in scaffold.bare_kinds():
        result = scaffold.op_new_object(tmp_path, kind, f"Проверка{len(kind)}{abs(hash(kind)) % 97}")
        yaml_change = next(c for c in result.changes if c.path.suffix == ".yaml")
        parsed = _valid_yaml(yaml_change.content)
        assert parsed["ВидЭлемента"] == kind
        # The visibility default is the platform one - the tool does not widen it
        # on the developer's behalf.
        assert parsed["ОбластьВидимости"] == "ВПодсистеме"


def test_kind_module_pairs(tmp_path):
    """The paired file is created exactly for the kinds that need it, with the right extension."""
    def files(kind: str) -> list[str]:
        return [c.path.suffix for c in scaffold.op_new_object(tmp_path / kind, kind, "Э").changes]

    # ПравоНаЭлемент is an enumeration - "Не имеет модуля".
    assert files("ПравоНаЭлемент") == [".yaml"]
    # ПравоНаДействие computes its permissions in the module.
    assert files("ПравоНаДействие") == [".yaml", ".xbsl"]
    # Type and entity contracts are properties only - a module exists just for abstract methods.
    assert files("КонтрактТипа") == [".yaml"]
    assert files("КонтрактСущности") == [".yaml"]
    assert files("КонтрактСервиса") == [".yaml", ".xbsl"]
    # A virtual table's paired file is a query, not a module.
    assert files("ВиртуальнаяТаблица") == [".yaml", ".xbql"]
    # A navigation command is declarative, other commands live in a handler.
    assert files("НавигационнаяКоманда") == [".yaml"]
    assert files("ОбычнаяКоманда") == [".yaml", ".xbsl"]
    assert files("СобытиеЖурналаСобытий") == [".yaml"]


def test_kind_module_stubs_carry_documented_handlers(tmp_path):
    def module(kind: str, name: str) -> str:
        changes = scaffold.op_new_object(tmp_path / kind, kind, name).changes
        return next(c for c in changes if c.path.suffix in (".xbsl", ".xbql")).content

    # The element name is substituted into generics; КлючДоступа.Объект is a literal base type.
    stub = module("ПравоНаДействие", "ПравоМодератора")
    assert "метод ВычислитьРазрешенияДоступа(Права: ЧитаемыйМассив<ПравоМодератора.Объект>)" in stub
    assert "ЧитаемаяКоллекция<КлючДоступа.Объект>" in stub
    assert "возврат {:}" in stub

    assert "метод Обработчик()" in module("ЗапланированноеЗадание", "ОчисткаКэша")
    assert "метод ВычислитьПараметрыРаботыКлиента()" in module("ПараметрыРаботыКлиента", "Парам")
    assert "метод ПослеПодключения()" in module(
        "ПараметрСамостоятельнойРегистрацииПользователя", "Приглашение"
    )
    # The access-key handler is mandatory too; the key's own type goes into the generics,
    # the users are the system Пользователи.Ссылка facet.
    key = module("КлючДоступа", "КлючиГрупп")
    assert "метод ПроверитьНаличиеКлючейДоступа(" in key
    assert "ЧитаемыйМассив<КлючиГрупп.Объект>" in key
    assert "ЧитаемоеСоответствие<КлючиГрупп.Объект, ЧитаемыйМассив<Пользователи.Ссылка>>" in key
    assert "возврат {:}" in key
    # The IDE creates the query empty - the generator does not invent query text.
    assert module("ВиртуальнаяТаблица", "Остатки").strip() == ""


def test_kind_notes_and_mandatory_fields(tmp_path):
    # An event log event requires ШаблонПредставления (for the Информация kind).
    result = scaffold.op_new_object(tmp_path, "СобытиеЖурналаСобытий", "ИмпортДанных")
    parsed = _valid_yaml(result.changes[0].content)
    assert parsed["ВидСобытия"] == "Информация"
    assert parsed["ШаблонПредставления"] == "ИмпортДанных"
    assert any("ХарактерОшибки" in n for n in result.notes)

    # A color scheme requires Представление.
    scheme = scaffold.op_new_object(tmp_path, "ЦветоваяСхемаОтчета", "СхемаОтчета")
    assert _valid_yaml(scheme.changes[0].content)["Представление"] == "СхемаОтчета"
    assert any("Цвета" in n for n in scheme.notes)

    # For a virtual table we remind about the mandatory query.
    vt = scaffold.op_new_object(tmp_path, "ВиртуальнаяТаблица", "Остатки")
    assert any(".xbql" in n for n in vt.notes)


def test_new_sections_of_added_kinds(tmp_path):
    subsystem = _make_project(tmp_path)
    # Constant set constants carry Ид (like attributes).
    apply_result(scaffold.op_new_object(subsystem, "НаборКонстант", "КурсыВалют"))
    apply_result(scaffold.op_add_field(subsystem / "КурсыВалют.yaml", "константа", "КурсЦБ",
                                       type_="Число"))
    const = _valid_yaml((subsystem / "КурсыВалют.yaml").read_text(encoding="utf-8"))["Константы"][0]
    assert const["Имя"] == "КурсЦБ" and const["Ид"]

    # Type contract properties come without Ид, entity contract ones - with Ид.
    apply_result(scaffold.op_new_object(subsystem, "КонтрактТипа", "КонтрактПредставления"))
    apply_result(scaffold.op_add_field(subsystem / "КонтрактПредставления.yaml", "свойство",
                                       "Заголовок", type_="Строка"))
    prop = _valid_yaml(
        (subsystem / "КонтрактПредставления.yaml").read_text(encoding="utf-8")
    )["Свойства"][0]
    assert prop == {"Имя": "Заголовок", "Тип": "Строка"}

    apply_result(scaffold.op_new_object(subsystem, "КонтрактСущности", "Контрагенты"))
    apply_result(scaffold.op_add_field(subsystem / "Контрагенты.yaml", "свойство", "ИНН",
                                       type_="Строка"))
    entity_prop = _valid_yaml((subsystem / "Контрагенты.yaml").read_text(encoding="utf-8"))["Свойства"][0]
    assert entity_prop["Ид"]

    # Item right actions go into the Элементы section.
    apply_result(scaffold.op_new_object(subsystem, "ПравоНаЭлемент", "ПравоНаКонтрагента"))
    apply_result(scaffold.op_add_field(subsystem / "ПравoНаКонтрагента.yaml".replace("o", "о"),
                                       "значение", "ИзменениеЦены"))
    action = _valid_yaml(
        (subsystem / "ПравоНаКонтрагента.yaml").read_text(encoding="utf-8")
    )["Элементы"][0]
    assert action["Имя"] == "ИзменениеЦены" and action["Ид"]


def test_new_project_version_follows_standard(tmp_path):
    apply_result(scaffold.op_new_project(tmp_path, "vendor", "Приложение"))
    project = _valid_yaml(
        (tmp_path / "vendor" / "Приложение" / "Проект.yaml").read_text(encoding="utf-8")
    )
    # The project/version rule requires A.B.C - the generator must not contradict it.
    assert project["Версия"] == "1.0.0"


# --- object form: tabular part columns and section wrapper --------------------------------


def _doc_with_tabular(tmp_path, extra_fields: int = 0) -> Path:
    subsystem = _make_project(tmp_path)
    apply_result(scaffold.op_new_object(subsystem, "Документ", "Приходы"))
    yaml_path = subsystem / "Приходы.yaml"
    for i in range(extra_fields):
        apply_result(scaffold.op_add_field(yaml_path, "реквизит", f"Реквизит{i}", type_="Строка"))
    apply_result(scaffold.op_add_field(yaml_path, "табличная-часть", "Товары"))
    apply_result(scaffold.op_add_field(yaml_path, "реквизит", "Количество", type_="Число",
                                       tabular="Товары"))
    return subsystem


def test_object_info_reads_tabular_fields(tmp_path):
    subsystem = _doc_with_tabular(tmp_path)
    info = scaffold.object_info(tmp_path, name="Приходы")
    tabular = info["tabulars"][0]
    assert tabular["name"] == "Товары"
    # The stub attribute is added along with the tabular part itself (the platform does not
    # support an empty one), and the first real attribute takes its place.
    assert [f["name"] for f in tabular["fields"]] == ["Количество"]
    assert [f["type"] for f in tabular["fields"]] == ["Число"]
    assert subsystem  # the subsystem directory is used


def test_tabular_table_has_columns(tmp_path):
    subsystem = _doc_with_tabular(tmp_path)
    apply_result(scaffold.op_add_form(tmp_path, name="Приходы", forms=["object"]))
    form = _valid_yaml((subsystem / "ПриходыФормаОбъекта.yaml").read_text(encoding="utf-8"))
    section = form["Наследует"]["Содержимое"]["ДополнительныеРазделы"][0]
    table = section["Содержимое"][0]["Содержимое"][0]
    assert table["Тип"] == "Таблица<ИсточникДанныхМассив<Приходы.Товары>>"
    # Columns are mandatory - without them the table shows empty rows.
    columns = table["Колонки"]
    assert [c["Заголовок"] for c in columns] == ["Количество"]
    # ПолеЗначения also defines sorting by the column.
    assert [c["ПолеЗначения"] for c in columns] == ["Количество"]
    assert columns[0]["Тип"] == "СтандартнаяКолонкаТаблицы<Приходы.Товары>"


def test_form_section_wraps_fields_in_group(tmp_path):
    """РазделФормы.Содержимое is Массив<Группа> - fields go into an area, not directly."""
    subsystem = _doc_with_tabular(tmp_path)
    apply_result(scaffold.op_add_form(tmp_path, name="Приходы", forms=["object"]))
    form = _valid_yaml((subsystem / "ПриходыФормаОбъекта.yaml").read_text(encoding="utf-8"))
    section = form["Наследует"]["Содержимое"]["ОсновнойРаздел"]
    assert section["Тип"] == "РазделФормы"
    area = section["Содержимое"][0]
    assert set(area) == {"Содержимое"}  # section area - as in the reference forms, no Тип
    assert [c["Имя"] for c in area["Содержимое"]] == ["Дата"]


def test_group_section_keeps_fields_inline(tmp_path):
    """The panels branch - a Группа content is Массив<Компонент>, no wrapper is needed."""
    subsystem = _doc_with_tabular(tmp_path, extra_fields=4)
    info = scaffold.object_info(tmp_path, name="Приходы")
    assert info["suggested_layout"] == "panels"
    apply_result(scaffold.op_add_form(tmp_path, name="Приходы", forms=["object"]))
    form = _valid_yaml((subsystem / "ПриходыФормаОбъекта.yaml").read_text(encoding="utf-8"))
    section = form["Наследует"]["Содержимое"]["ОсновнойРаздел"]
    assert section["Тип"] == "Группа"
    assert all("Тип" in c for c in section["Содержимое"])  # fields sit directly in the group


def test_object_attribute_never_lands_in_tabular(tmp_path):
    """An object attribute goes into the object section even when that section does not exist yet.

    The trap: a document with a tabular part has a NESTED `Реквизиты` section, and a section
    lookup at any indent took it for the object section - the attribute drifted into the
    tabular part, and tabular part fields counted as object fields.
    """
    apply_result(scaffold.op_new_object(tmp_path, "Документ", "Приходы"))
    yaml_path = tmp_path / "Приходы.yaml"
    apply_result(scaffold.op_add_field(yaml_path, "табличная-часть", "Товары"))
    apply_result(scaffold.op_add_field(yaml_path, "реквизит", "Контрагент", type_="Строка"))
    apply_result(scaffold.op_add_field(yaml_path, "реквизит", "Цена", type_="Число",
                                       tabular="Товары"))

    parsed = _valid_yaml(yaml_path.read_text(encoding="utf-8"))
    # Дата is the document's starter attribute in the object section; Контрагент is appended.
    assert [f["Имя"] for f in parsed["Реквизиты"]] == ["Дата", "Контрагент"]
    assert [f["Имя"] for f in parsed["ТабличныеЧасти"][0]["Реквизиты"]] == ["Цена"]

    info = scaffold.object_info(tmp_path, name="Приходы")
    assert [f["name"] for f in info["fields"]] == ["Дата", "Контрагент"]
    assert [f["name"] for f in info["tabulars"][0]["fields"]] == ["Цена"]

    # A name taken in the tabular part does not count as a duplicate object attribute.
    apply_result(scaffold.op_add_field(yaml_path, "реквизит", "Реквизит1", type_="Строка"))
    parsed = _valid_yaml(yaml_path.read_text(encoding="utf-8"))
    assert [f["Имя"] for f in parsed["Реквизиты"]] == ["Дата", "Контрагент", "Реквизит1"]


# --- form applicability per kind ----------------------------------------------------------


def _register(tmp_path) -> Path:
    subsystem = _make_project(tmp_path)
    apply_result(scaffold.op_new_object(subsystem, "РегистрСведений", "КурсыВалют"))
    yaml_path = subsystem / "КурсыВалют.yaml"
    apply_result(scaffold.op_add_field(yaml_path, "измерение", "Валюта", type_="Строка"))
    apply_result(scaffold.op_add_field(yaml_path, "ресурс", "Курс", type_="Число"))
    apply_result(scaffold.op_add_field(yaml_path, "реквизит", "Источник", type_="Строка"))
    return subsystem


def test_register_fields_include_dimensions_and_resources(tmp_path):
    _register(tmp_path)
    info = scaffold.object_info(tmp_path, name="КурсыВалют")
    # Register data is Измерения and Ресурсы; the summary used to see only Реквизиты.
    # Измерение1 is the starter dimension (the information register does not compile
    # without it), then the added ones.
    assert [f["name"] for f in info["fields"]] == ["Измерение1", "Валюта", "Курс", "Источник"]


def test_register_gets_list_form_only(tmp_path):
    subsystem = _register(tmp_path)
    result = scaffold.op_add_form(tmp_path, name="КурсыВалют")
    apply_result(result)
    # A register has no object form - by default only the list form is generated.
    assert not (subsystem / "КурсыВалютФормаОбъекта.yaml").exists()
    form = _valid_yaml((subsystem / "КурсыВалютФормаСписка.yaml").read_text(encoding="utf-8"))
    columns = form["Наследует"]["Содержимое"]["Содержимое"]["Колонки"]
    assert [c["Имя"] for c in columns] == ["Измерение1", "Валюта", "Курс", "Источник"]

    with pytest.raises(ScaffoldError, match="нет формы объекта"):
        scaffold.op_add_form(tmp_path, name="КурсыВалют", forms=["object"])


def test_kinds_without_forms_are_rejected(tmp_path):
    subsystem = _make_project(tmp_path)
    apply_result(scaffold.op_new_object(subsystem, "ОбщийМодуль", "Хелпер"))
    with pytest.raises(ScaffoldError, match="нет форм объекта и списка"):
        scaffold.op_add_form(tmp_path, name="Хелпер")
    with pytest.raises(ScaffoldError, match="нет формы списка"):
        scaffold.op_add_form(tmp_path, name="Хелпер", forms=["list"])


# --- info summary: registers and permission handlers --------------------------------------


def test_object_info_balance_register(tmp_path):
    subsystem = _make_project(tmp_path)
    apply_result(scaffold.op_new_object(subsystem, "РегистрНакопления", "ОстаткиТоваров"))
    yaml_path = subsystem / "ОстаткиТоваров.yaml"
    apply_result(scaffold.op_add_field(yaml_path, "измерение", "Товар", type_="Строка"))
    apply_result(scaffold.op_add_field(yaml_path, "ресурс", "Количество", type_="Число"))

    info = scaffold.object_info(tmp_path, name="ОстаткиТоваров")
    # Остатки is the default ВидРегистра value; a movement needs ВидЗаписи (Приход/Расход).
    assert info["register"]["register_kind"] == "Остатки"
    assert info["register"]["needs_record_type"] is True
    # Ресурс1 is the starter resource (the accumulation register does not compile without
    # it); it sits in the Ресурсы section before the added Количество.
    assert [f["name"] for f in info["fields"]] == [
        "Период", "Регистратор", "ВидЗаписи", "Товар", "Ресурс1", "Количество",
    ]


def test_object_info_turnover_register_has_no_record_type(tmp_path):
    subsystem = _make_project(tmp_path)
    apply_result(scaffold.op_new_object(subsystem, "РегистрНакопления", "ОборотыПродаж"))
    yaml_path = subsystem / "ОборотыПродаж.yaml"
    yaml_path.write_text(yaml_path.read_text(encoding="utf-8") + "ВидРегистра: Обороты\n",
                         encoding="utf-8")
    info = scaffold.object_info(tmp_path, name="ОборотыПродаж")
    assert info["register"]["register_kind"] == "Обороты"
    assert info["register"]["needs_record_type"] is False
    assert "ВидЗаписи" not in [f["name"] for f in info["fields"]]


def test_object_info_information_register_periodicity(tmp_path):
    subsystem = _make_project(tmp_path)
    apply_result(scaffold.op_new_object(subsystem, "РегистрСведений", "Настройки"))
    info = scaffold.object_info(tmp_path, name="Настройки")
    # Непериодический - no Период is produced.
    assert info["register"]["periodicity"] == "Непериодический"
    assert info["register"]["needs_record_type"] is False
    assert "Период" not in [f["name"] for f in info["fields"]]

    yaml_path = subsystem / "Настройки.yaml"
    yaml_path.write_text(yaml_path.read_text(encoding="utf-8") + "Периодичность: День\n",
                         encoding="utf-8")
    periodic = scaffold.object_info(tmp_path, name="Настройки")
    assert periodic["register"]["periodicity"] == "День"
    # Период (the standard field of a periodic register) plus the starter Измерение1.
    assert [f["name"] for f in periodic["fields"]] == ["Период", "Измерение1"]


def test_object_info_access_handlers(tmp_path):
    subsystem = _make_project(tmp_path)
    apply_result(scaffold.op_new_object(subsystem, "Справочник", "Задачи"))
    info = scaffold.object_info(tmp_path, name="Задачи")
    assert info["access_handlers"] == {"module": None, "level1": False, "level2": False}
    assert info["register"] is None  # not a register

    # Permission handlers live in the object module <Имя>.xbsl.
    (subsystem / "Задачи.xbsl").write_text(
        "@Обработчик\n"
        "метод ВычислитьРазрешенияДоступа(): Массив<РазрешениеДоступа>\n    возврат []\n;\n\n"
        "@Обработчик\n"
        "метод ВычислитьРазрешенияДоступаДляОбъектов(Элементы: ЧитаемыйМассив<Задачи.ДанныеРасчетаРазрешений>)\n"
        "    возврат\n;\n",
        encoding="utf-8",
    )
    both = scaffold.object_info(tmp_path, name="Задачи")
    assert both["access_handlers"] == {"module": "Задачи.xbsl", "level1": True, "level2": True}


# --- library dependency -------------------------------------------------------------------


def _project_yaml(tmp_path) -> Path:
    _make_project(tmp_path)
    return tmp_path / "vendor" / "Приложение" / "Проект.yaml"


def test_add_dependency_creates_section(tmp_path):
    project = _project_yaml(tmp_path)
    result = scaffold.op_add_dependency(tmp_path, "acme", "CurrencyConverter", "9.0.2")
    apply_result(result)
    # The section format is from the "Подключить библиотеку к проекту" documentation.
    assert _valid_yaml(project.read_text(encoding="utf-8"))["Библиотеки"] == [
        {"Имя": "CurrencyConverter", "Поставщик": "acme", "Версия": "9.0.2"}
    ]
    assert any("Подсистема[::Пакет]::ИмяТипа" in note for note in result.notes)


def test_add_dependency_version_stays_unquoted(tmp_path):
    project = _project_yaml(tmp_path)
    apply_result(scaffold.op_add_dependency(tmp_path, "acme", "CurrencyConverter", "2.0"))
    # The version is written unquoted - that is how the platform writes it and the docs
    # show it, even though yaml parsing turns "2.0" into a number.
    assert "Версия: 2.0" in project.read_text(encoding="utf-8")


def test_add_dependency_appends_to_existing_section(tmp_path):
    project = _project_yaml(tmp_path)
    apply_result(scaffold.op_add_dependency(tmp_path, "acme", "CurrencyConverter", "2.0"))
    apply_result(scaffold.op_add_dependency(tmp_path, "acme", "MessageQueue", "9.0.2"))
    libraries = _valid_yaml(project.read_text(encoding="utf-8"))["Библиотеки"]
    assert [item["Имя"] for item in libraries] == ["CurrencyConverter", "MessageQueue"]


def test_add_dependency_updates_version_in_place(tmp_path):
    project = _project_yaml(tmp_path)
    apply_result(scaffold.op_add_dependency(tmp_path, "acme", "CurrencyConverter", "9.0.2"))
    result = scaffold.op_add_dependency(tmp_path, "acme", "CurrencyConverter", "9.1.0")
    apply_result(result)
    # Different versions of one library within a project are not allowed - one entry, new version.
    assert _valid_yaml(project.read_text(encoding="utf-8"))["Библиотеки"] == [
        {"Имя": "CurrencyConverter", "Поставщик": "acme", "Версия": "9.1.0"}
    ]
    assert result.notes == ["acme::CurrencyConverter: версия 9.0.2 -> 9.1.0"]


def test_add_dependency_same_version_is_noop(tmp_path):
    _project_yaml(tmp_path)
    apply_result(scaffold.op_add_dependency(tmp_path, "acme", "CurrencyConverter", "2.0"))
    result = scaffold.op_add_dependency(tmp_path, "acme", "CurrencyConverter", "2.0")
    assert result.changes == []
    assert any("уже подключена" in note for note in result.notes)


def test_add_dependency_rejects_build_version(tmp_path):
    _project_yaml(tmp_path)
    # 1.0-42 is a build version; a project links a release version.
    with pytest.raises(ScaffoldError, match="версия сборки"):
        scaffold.op_add_dependency(tmp_path, "acme", "CurrencyConverter", "1.0-42")


def test_add_dependency_rejects_namesake_from_other_vendor(tmp_path):
    _project_yaml(tmp_path)
    apply_result(scaffold.op_add_dependency(tmp_path, "globex", "CurrencyConverter", "2.0"))
    with pytest.raises(ScaffoldError, match="уже подключена"):
        scaffold.op_add_dependency(tmp_path, "acme", "CurrencyConverter", "3.0")


def test_add_dependency_reports_ambiguous_root(tmp_path):
    apply_result(scaffold.op_new_project(tmp_path, "vendor", "Первый"))
    apply_result(scaffold.op_new_project(tmp_path, "vendor", "Второй"))
    with pytest.raises(ScaffoldError, match="несколько проектов"):
        scaffold.op_add_dependency(tmp_path, "acme", "CurrencyConverter", "2.0")
    # An explicit path removes the ambiguity.
    target = tmp_path / "vendor" / "Второй" / "Проект.yaml"
    apply_result(scaffold.op_add_dependency(
        tmp_path, "acme", "CurrencyConverter", "2.0", project_yaml=target
    ))
    assert "CurrencyConverter" in target.read_text(encoding="utf-8")


def test_project_info_lists_libraries(tmp_path):
    _project_yaml(tmp_path)
    apply_result(scaffold.op_add_dependency(tmp_path, "acme", "CurrencyConverter", "2.0"))
    project = scaffold.project_info(tmp_path)["projects"][0]
    assert project["libraries"] == [
        {"Имя": "CurrencyConverter", "Поставщик": "acme", "Версия": "2.0"}
    ]


# --- the kind may be given in either language -----------------------------------------------


def test_resolve_kind_accepts_the_russian_spelling():
    assert scaffold.resolve_kind("Справочник") == "Справочник"


def test_resolve_kind_leaves_an_unknown_word_alone():
    # the caller reports it as an unsupported kind, with the list of the supported ones
    assert scaffold.resolve_kind("НетТакогоВида") == "НетТакогоВида"


def test_resolve_kind_maps_english_names(monkeypatch):
    monkeypatch.setattr(scaffold, "_kind_by_english", lambda: {"catalog": "Справочник"})
    assert scaffold.resolve_kind("Catalog") == "Справочник"
    assert scaffold.resolve_kind("catalog") == "Справочник"


def test_new_object_accepts_an_english_kind(tmp_path, monkeypatch):
    monkeypatch.setattr(scaffold, "_kind_by_english", lambda: {"catalog": "Справочник"})
    apply_result(scaffold.op_new_object(tmp_path, "Catalog", "Товары"))
    text = (tmp_path / "Товары.yaml").read_text(encoding="utf-8")
    assert "ВидЭлемента: Справочник" in text


def test_without_the_dictionary_only_russian_is_accepted(tmp_path, monkeypatch):
    monkeypatch.setattr(scaffold, "_kind_by_english", dict)
    with pytest.raises(scaffold.ScaffoldError):
        scaffold.op_new_object(tmp_path, "Catalog", "Товары")


@pytest.mark.needs_data
def test_english_kinds_come_from_the_real_dictionary():
    scaffold._kind_by_english.cache_clear()
    pairs = scaffold._kind_by_english()
    assert pairs.get("catalog") == "Справочник"
    assert pairs.get("interfacecomponent") == "КомпонентИнтерфейса"
    assert len(pairs) >= 30


# --- an English project: the scaffolding must read it as it reads the Russian one -------------
#
# 1C:Element is bilingual: `ElementKind: Catalog` is the very same object as
# `ВидЭлемента: Справочник`, and `Attributes` is the section `Реквизиты`. Such a project
# compiles - `demo-en/` in this repository is exactly one. Every pair below comes from the
# platform's own data (the metamodel's `en` of a property), never from a translation.

ENGLISH_CATALOG = """\
ElementKind: Catalog
Id: 6f0b6a44-0000-4000-8000-0000000000a1
Name: Tasks
Presentation: Name
VisibilityScope: InProject
Interface:
    Object:
        Form: TaskCard
Attributes:
    -
        Id: 6f0b6a44-0000-4000-8000-0000000000a2
        Name: DueDate
        Type: Date
TabularParts:
    -
        Id: 6f0b6a44-0000-4000-8000-0000000000a3
        Name: Steps
        Attributes:
            -
                Id: 6f0b6a44-0000-4000-8000-0000000000a4
                Name: Step
                Type: String
"""

ENGLISH_FORM = """\
ElementKind: InterfaceComponent
Id: 6f0b6a44-0000-4000-8000-0000000000a5
Name: TaskCard
VisibilityScope: InProject
Inherits:
    Type: ObjectForm<Tasks.Object>
    Title: Tasks
"""


def _make_english_project(tmp_path) -> Path:
    """A mini project written in English spellings; returns its subsystem directory."""
    project = tmp_path / "Acme" / "TasksEn"
    (project / "Main").mkdir(parents=True)
    (project / "Проект.yaml").write_text(
        "Id: 6f0b6a44-0000-4000-8000-0000000000a0\n"
        "Vendor: Acme\nName: TasksEn\nVersion: 1.0.0\n",
        encoding="utf-8",
    )
    (project / "Main" / "Подсистема.yaml").write_text(
        "Interface:\n    IncludeInAutoInterface: True\n", encoding="utf-8"
    )
    (project / "Main" / "Tasks.yaml").write_text(ENGLISH_CATALOG, encoding="utf-8")
    (project / "Main" / "TaskCard.yaml").write_text(ENGLISH_FORM, encoding="utf-8")
    return project / "Main"


def test_key_forms_without_the_metamodel_stay_russian(monkeypatch):
    """No pairs in the data - the Russian spelling alone, as before.

    The negative control of the whole bilingual layer: the English spellings must come from the
    platform data and from nowhere else, so cutting the data off has to cut them off too.
    """
    monkeypatch.setattr(scaffold.metamodel, "english_name", lambda name: None)
    scaffold.key_forms.cache_clear()
    scaffold._key_re.cache_clear()
    try:
        assert scaffold.key_forms("Реквизиты") == ("Реквизиты",)
        assert scaffold.element_kind(ENGLISH_CATALOG) is None
    finally:
        scaffold.key_forms.cache_clear()
        scaffold._key_re.cache_clear()


@pytest.mark.needs_data
def test_key_forms_come_from_the_metamodel():
    assert scaffold.key_forms("ВидЭлемента") == ("ВидЭлемента", "ElementKind")
    # The section names are the point: the compact term dictionary has no English for
    # `Реквизиты` at all, the metamodel declares `Attributes`.
    assert scaffold.key_forms("Реквизиты") == ("Реквизиты", "Attributes")
    assert scaffold.key_forms("ТабличныеЧасти") == ("ТабличныеЧасти", "TabularParts")


@pytest.mark.needs_data
def test_section_items_reads_english_sections():
    """The items are found by the English section name and come back under the Russian keys."""
    items = section_items(ENGLISH_CATALOG, "Реквизиты", top_level=True)
    assert [i["Имя"] for i in items] == ["DueDate"]
    assert items[0]["Тип"] == "Date"
    assert items[0]["Ид"] == "6f0b6a44-0000-4000-8000-0000000000a2"
    assert [i["Имя"] for i in section_items(ENGLISH_CATALOG, "ТабличныеЧасти", top_level=True)] \
        == ["Steps"]


@pytest.mark.needs_data
def test_find_section_item_offset_reads_english_names():
    offset = find_section_item_offset(ENGLISH_CATALOG, "ТабличныеЧасти", "Steps")
    assert offset is not None and ENGLISH_CATALOG[offset:].startswith("Id:")


@pytest.mark.needs_data
def test_element_kind_answers_in_the_metamodel_spelling():
    assert scaffold.element_kind(ENGLISH_CATALOG) == "Справочник"
    assert scaffold.element_kind(CATALOG) == "Справочник"
    assert scaffold.element_kind("Interface:\n    IncludeInAutoInterface: True\n") is None


@pytest.mark.needs_data
def test_find_object_in_an_english_project(tmp_path):
    subsystem = _make_english_project(tmp_path)
    hit = scaffold.find_object(tmp_path, "Tasks")
    assert hit.path == subsystem / "Tasks.yaml"
    # The kind comes back as the metamodel names it: every table of the module is keyed by it.
    assert hit.kind == "Справочник"
    assert hit.namespace == "Acme::TasksEn::Main"


@pytest.mark.needs_data
def test_project_info_lists_english_objects(tmp_path):
    _make_english_project(tmp_path)
    info = scaffold.project_info(tmp_path)
    assert [(o["kind"], o["name"]) for o in info["objects"]] == [
        ("КомпонентИнтерфейса", "TaskCard"),
        ("Справочник", "Tasks"),
    ]


@pytest.mark.needs_data
def test_object_info_of_an_english_object(tmp_path):
    subsystem = _make_english_project(tmp_path)
    info = scaffold.object_info(tmp_path, name="Tasks")
    assert info["kind"] == "Справочник"
    # The standard Наименование is added because this catalog does not declare it.
    assert [f["name"] for f in info["fields"]] == ["Наименование", "DueDate"]
    assert info["tabulars"] == [{"name": "Steps", "fields": [{"name": "Step", "type": "String"}]}]
    # The same object addressed by file - the other entry point into the same reading.
    by_path = scaffold.object_info(tmp_path, yaml_path=subsystem / "Tasks.yaml")
    assert by_path["fields"] == info["fields"]


@pytest.mark.needs_data
def test_a_standard_attribute_declared_in_english_is_not_doubled(tmp_path):
    """`Name` IS `Наименование` - a catalog that declares it must not get a phantom twin.

    demo-en/ declares exactly that attribute, and the phantom used to reach the generated
    form as a column over a field that does not exist.
    """
    subsystem = _make_english_project(tmp_path)
    yaml_path = subsystem / "Tasks.yaml"
    yaml_path.write_text(
        yaml_path.read_text(encoding="utf-8").replace(
            "        Name: DueDate\n        Type: Date\n",
            "        Name: Name\n        Length: 250\n",
        ),
        encoding="utf-8",
    )
    info = scaffold.object_info(tmp_path, name="Tasks")
    assert [f["name"] for f in info["fields"]] == ["Name"]


@pytest.mark.needs_data
def test_object_info_of_an_english_register(tmp_path):
    """The register keys are bilingual too: ВидРегистра is RegisterKind, its value Обороты."""
    subsystem = _make_english_project(tmp_path)
    (subsystem / "Sales.yaml").write_text(
        "ElementKind: AccumulationRegister\n"
        "Id: 6f0b6a44-0000-4000-8000-0000000000b1\n"
        "Name: Sales\n"
        "RegisterKind: Turnovers\n"
        "Dimensions:\n    -\n        Name: Product\n        Type: String\n"
        "Resources:\n    -\n        Name: Amount\n        Type: Number\n",
        encoding="utf-8",
    )
    info = scaffold.object_info(tmp_path, name="Sales")
    assert info["kind"] == "РегистрНакопления"
    assert [f["name"] for f in info["fields"]] == ["Период", "Регистратор", "Product", "Amount"]
    # A turnover register has no ВидЗаписи - reading the value in either spelling decides it.
    assert info["register"]["needs_record_type"] is False


@pytest.mark.needs_data
def test_add_field_into_an_english_object(tmp_path):
    subsystem = _make_english_project(tmp_path)
    yaml_path = subsystem / "Tasks.yaml"
    apply_result(scaffold.op_add_field(yaml_path, "реквизит", "Details", type_="String"))
    text = yaml_path.read_text(encoding="utf-8")

    # Into the section that is already there - no second, Russian-named one next to it.
    assert "Реквизиты:" not in text and text.count("Attributes:") == 2
    parsed = _valid_yaml(text)
    assert [a["Name"] for a in parsed["Attributes"]] == ["DueDate", "Details"]
    # The keys of the new item are spelled like the file around them.
    assert "Имя:" not in text and "Тип:" not in text and "Ид:" not in text
    assert parsed["Attributes"][1]["Type"] == "String"

    # A duplicate is refused - the check reads the English section as well.
    with pytest.raises(ScaffoldError, match="уже есть"):
        scaffold.op_add_field(yaml_path, "реквизит", "Details", type_="String")


@pytest.mark.needs_data
def test_add_field_into_an_english_tabular_part(tmp_path):
    subsystem = _make_english_project(tmp_path)
    yaml_path = subsystem / "Tasks.yaml"
    apply_result(
        scaffold.op_add_field(yaml_path, "реквизит", "Done", type_="Boolean", tabular="Steps")
    )
    parsed = _valid_yaml(yaml_path.read_text(encoding="utf-8"))
    tabular = parsed["TabularParts"][0]
    assert [a["Name"] for a in tabular["Attributes"]] == ["Step", "Done"]
    # The object-level section is untouched.
    assert [a["Name"] for a in parsed["Attributes"]] == ["DueDate"]


@pytest.mark.needs_data
def test_add_field_creates_a_missing_section_in_english(tmp_path):
    subsystem = _make_english_project(tmp_path)
    (subsystem / "Notes.yaml").write_text(
        "ElementKind: Catalog\nId: 6f0b6a44-0000-4000-8000-0000000000b2\nName: Notes\n",
        encoding="utf-8",
    )
    apply_result(scaffold.op_add_field(subsystem / "Notes.yaml", "реквизит", "Text"))
    text = (subsystem / "Notes.yaml").read_text(encoding="utf-8")
    assert "Attributes:" in text and "Реквизиты:" not in text
    assert [i["Имя"] for i in section_items(text, "Реквизиты", top_level=True)] == ["Text"]
    assert _valid_yaml(text)


@pytest.mark.needs_data
def test_an_ambiguous_key_keeps_the_russian_spelling(tmp_path):
    """A name the metamodel classes spell differently stays Russian - in reading and in writing.

    `Элементы` is `Items` for an enumeration and `Elements` elsewhere, so there is no single
    English spelling to write; a Russian key inside an English file compiles, an invented
    `Elements:` in an enumeration would not be what the platform declares. Reading and writing
    degrade together, which is what keeps the file readable by the very next call.
    """
    assert scaffold.key_forms("Элементы") == ("Элементы",)
    subsystem = _make_english_project(tmp_path)
    (subsystem / "Kinds.yaml").write_text(
        # `Enum` is the platform's own English name of the kind - not `Enumeration`.
        "ElementKind: Enum\nId: 6f0b6a44-0000-4000-8000-0000000000b3\nName: Kinds\n",
        encoding="utf-8",
    )
    apply_result(scaffold.op_add_field(subsystem / "Kinds.yaml", "значение", "Simple"))
    text = (subsystem / "Kinds.yaml").read_text(encoding="utf-8")
    assert "Элементы:" in text
    assert [i["Имя"] for i in section_items(text, "Элементы", top_level=True)] == ["Simple"]
    assert _valid_yaml(text)


@pytest.mark.needs_data
def test_set_access_on_an_english_object(tmp_path):
    subsystem = _make_english_project(tmp_path)
    result = scaffold.op_set_access(tmp_path, name="Tasks", default="РазрешеноВсем")
    apply_result(result)
    text = (subsystem / "Tasks.yaml").read_text(encoding="utf-8")
    assert "AccessControl:" in text and "КонтрольДоступа:" not in text
    assert "Permissions:" in text and "Разрешения:" not in text
    # The section lands before the first data section, not at the end of the file.
    assert text.index("AccessControl:") < text.index("Attributes:")
    assert scaffold.access_info(text)["default"] == "РазрешеноВсем"
    assert _valid_yaml(text)


@pytest.mark.needs_data
def test_rename_object_in_an_english_project(tmp_path):
    subsystem = _make_english_project(tmp_path)
    result = scaffold.op_rename_object(tmp_path, "Tasks", "Assignments")
    assert {r.old_path.name: r.new_path.name for r in result.renames} == {
        "Tasks.yaml": "Assignments.yaml"
    }
    apply_result(result)

    owner = (subsystem / "Assignments.yaml").read_text(encoding="utf-8")
    assert "Name: Assignments" in owner and "Name: Tasks" not in owner
    # The attribute named Name (the presentation field) is not an object reference.
    assert "Presentation: Name" in owner
    form = (subsystem / "TaskCard.yaml").read_text(encoding="utf-8")
    assert "Type: ObjectForm<Assignments.Object>" in form
    assert _valid_yaml(owner) and _valid_yaml(form)


@pytest.mark.needs_data
def test_add_dependency_updates_an_english_descriptor(tmp_path):
    """The Libraries section is read as Библиотеки - otherwise a second entry is appended."""
    project = _make_english_project(tmp_path).parent
    descriptor = project / "Проект.yaml"
    descriptor.write_text(
        descriptor.read_text(encoding="utf-8")
        + "Libraries:\n    -\n        Name: Converter\n        Vendor: acme\n"
          "        Version: 1.0.0\n",
        encoding="utf-8",
    )
    apply_result(scaffold.op_add_dependency(tmp_path, "acme", "Converter", "2.0.0"))
    parsed = _valid_yaml(descriptor.read_text(encoding="utf-8"))
    assert parsed["Libraries"] == [{"Name": "Converter", "Vendor": "acme", "Version": "2.0.0"}]

    # A new library is appended to the same section, spelled like it.
    apply_result(scaffold.op_add_dependency(tmp_path, "acme", "Charts", "1.0.0"))
    text = descriptor.read_text(encoding="utf-8")
    assert "Библиотеки:" not in text and "Имя:" not in text
    assert [i["Имя"] for i in scaffold.project_libraries(text)] == ["Converter", "Charts"]


@pytest.mark.needs_data
def test_add_subsystem_follows_the_project_spelling(tmp_path):
    _make_english_project(tmp_path)
    project = tmp_path / "Acme" / "TasksEn"
    apply_result(scaffold.op_add_subsystem(project, "Reports", uses=["Main"]))
    text = (project / "Reports" / "Подсистема.yaml").read_text(encoding="utf-8")
    assert "Interface:" in text and "Интерфейс:" not in text
    assert "IncludeInAutoInterface: True" in text
    assert "Using:" in text and "Использование:" not in text
    assert _valid_yaml(text)


# --- an English project: what the scaffolding WRITES is English too --------------------------
#
# Reading was only half the job. A form generated into an English project used to arrive with
# Russian keys, Russian type names and a file called `TasksФормаСписка.yaml` - the very island
# the bilingual reading was fixed to avoid. Every English spelling below comes from the
# platform's own data (metamodel classes, the compiler dictionary); the two words the tool
# invents for itself (a row-data structure, route handler names) are its own vocabulary.


@pytest.mark.needs_data
def test_generated_form_is_english_in_an_english_project(tmp_path):
    directory = _make_english_project(tmp_path)
    result = scaffold.op_add_form(directory, name="Tasks", forms=("list",))

    form = next(c for c in result.changes if str(c.path).endswith(".yaml") and "Form" in str(c.path))
    assert Path(form.path).name == "TasksListForm.yaml", "имя файла – по конвенции проекта"
    text = form.content
    assert "ElementKind: InterfaceComponent" in text and "ВидЭлемента" not in text
    assert "Name: TasksListForm" in text
    assert "Type: ListForm" in text and "ФормаСписка" not in text
    # A component property key comes from the compiler dictionary - demo-en spells it so.
    assert "Content:" in text and "Содержимое" not in text
    # The tool's own word for the row data structure.
    assert "ListRowData" in text and "ДанныеСтрокиСписка" not in text


def test_generated_form_stays_russian_in_a_russian_project(tmp_path):
    """Отрицательный контроль: русский проект получает ровно то же, что и раньше."""
    directory = tmp_path / "Acme" / "Tasks" / "Основное"
    directory.mkdir(parents=True)
    (directory.parent / "Проект.yaml").write_text(
        "Ид: 6f0b6a44-0000-4000-8000-0000000000b0\nПоставщик: Acme\nИмя: Tasks\nВерсия: 1.0.0\n",
        encoding="utf-8",
    )
    (directory / "Задачи.yaml").write_text(
        "ВидЭлемента: Справочник\nИд: 6f0b6a44-0000-4000-8000-0000000000b1\nИмя: Задачи\n"
        "ОбластьВидимости: ВПроекте\nРеквизиты:\n    -\n        Ид: 6f0b6a44-0000-4000-8000-0000000000b2\n"
        "        Имя: Срок\n        Тип: Дата\n",
        encoding="utf-8",
    )
    result = scaffold.op_add_form(directory, name="Задачи", forms=("list",))
    form = next(c for c in result.changes if "ФормаСписка" in str(c.path))
    assert Path(form.path).name == "ЗадачиФормаСписка.yaml"
    assert "ВидЭлемента: КомпонентИнтерфейса" in form.content
    assert "ListForm" not in form.content


@pytest.mark.needs_data
def test_untranslated_enum_values_are_named_in_the_notes(tmp_path):
    """Значения интерфейсных перечислений данные пишут только по-русски – об этом говорят."""
    directory = _make_english_project(tmp_path)
    result = scaffold.op_add_form(directory, name="Tasks", forms=("object",))
    notes = " ".join(result.notes)
    assert "Одинарная" in notes and "нет в данных платформы" in notes


@pytest.mark.needs_data
def test_new_http_service_is_english_in_an_english_project(tmp_path):
    directory = _make_english_project(tmp_path)
    result = scaffold.op_new_object(
        directory, "HttpСервис", "TasksApiHttpService", routes="GET /, GET /{id}"
    )
    yaml_text = next(c.content for c in result.changes if str(c.path).endswith(".yaml"))
    module_text = next(c.content for c in result.changes if str(c.path).endswith(".xbsl"))

    assert "ElementKind: HttpService" in yaml_text and "ВидЭлемента" not in yaml_text
    assert "UrlTemplates:" in yaml_text and "Handler: GetList" in yaml_text
    assert "Name: List" in yaml_text and "Имя: Список" not in yaml_text
    # The code stub: platform keywords and stdlib names in English, and so are the comments.
    assert module_text.startswith("method GetList(Query: HttpServiceRequest)")
    assert "catch Error: Exception" in module_text and "поймать" not in module_text
    assert "method HandleError(Response: HttpServiceResponse" in module_text
    assert "TODO: read the data" in module_text
    assert not any("а" <= ch <= "я" for ch in module_text), "в английском модуле кириллица"


@pytest.mark.needs_data
def test_routes_added_to_an_english_service_follow_it(tmp_path):
    directory = _make_english_project(tmp_path)
    created = scaffold.op_new_object(
        directory, "HttpСервис", "TasksApiHttpService", routes="GET /"
    )
    for change in created.changes:
        Path(change.path).write_text(change.content, encoding="utf-8")

    result = scaffold.op_add_route(directory / "TasksApiHttpService.yaml", "POST /, DELETE /{id}")

    yaml_text = next(c.content for c in result.changes if str(c.path).endswith(".yaml"))
    module_text = next(c.content for c in result.changes if str(c.path).endswith(".xbsl"))
    assert "Handler: Create" in yaml_text and "Обработчик" not in yaml_text
    assert "Handler: Delete" in yaml_text
    assert "method Create(Query: HttpServiceRequest)" in module_text
    # The error helper is already there from the first generation - not added twice.
    assert module_text.count("method HandleError(") == 1


# --- object deletion ------------------------------------------------------------------------


def test_delete_object_removes_the_family_and_lists_references(tmp_path):
    subsystem = _make_rename_project(tmp_path)
    result = scaffold.op_delete_object(tmp_path, "Склады")

    removed = {p.name for p in result.deletes}
    assert removed == {
        "Склады.yaml", "Склады.Объект.xbsl",
        "СкладыФормаОбъекта.yaml", "СкладыФормаСписка.yaml",
        "СтрокаСпискаСклады.yaml",
    }
    # Тёзка с продолжением имени - другой объект, он остаётся.
    assert "СкладыАрхив.yaml" not in removed

    # Оставшиеся упоминания названы файлом и строкой, ВКЛЮЧАЯ строковый литерал и
    # комментарий: при живой уборке хвостами оказались именно строки роутера и сидинга.
    listing = "\n".join(result.notes)
    assert "Заказы.yaml" in listing and "Заказы.xbsl" in listing
    assert "Склады не изменились" in listing

    apply_result(result)
    assert not (subsystem / "Склады.yaml").exists()
    assert not (subsystem / "СкладыФормаОбъекта.yaml").exists()
    assert not (subsystem / "СтрокаСпискаСклады.yaml").exists()
    assert (subsystem / "СкладыАрхив.yaml").is_file()
    assert (subsystem / "Заказы.yaml").is_file()


def test_delete_object_without_leftovers_says_so(tmp_path):
    subsystem = _make_project(tmp_path)
    apply_result(scaffold.op_new_object(subsystem, "Справочник", "Одинокий"))
    result = scaffold.op_delete_object(tmp_path, "Одинокий")
    assert any("не осталось" in note for note in result.notes)


def test_delete_object_unknown_name(tmp_path):
    _make_rename_project(tmp_path)
    with pytest.raises(ScaffoldError):
        scaffold.op_delete_object(tmp_path, "Нет")


# --- English service file names -------------------------------------------------------------


@pytest.mark.needs_data
def test_english_service_file_names_resolve(tmp_path):
    """An English-named project and subsystem: the platform accepts both spellings.

    Project discovery, an object's subsystem membership and the creation of a new
    subsystem must work exactly as with the Russian names; a subsystem created in such
    a project lands under the English name - a project keeps one spelling throughout.
    """
    project_dir = tmp_path / "Acme" / "Shop"
    subsystem = project_dir / "Core"
    subsystem.mkdir(parents=True)
    (project_dir / "Project.yaml").write_text(
        "Id: 019f0000-0000-7000-8000-000000000001\nVendor: Acme\nName: Shop\n"
        "Version: 1.0.0\n", encoding="utf-8")
    (subsystem / "Subsystem.yaml").write_text(
        "Interface:\n    IncludeInAutoInterface: True\n", encoding="utf-8")
    (subsystem / "Goods.yaml").write_text(
        "ElementKind: Catalog\nId: 019f0000-0000-7000-8000-000000000002\nName: Goods\n",
        encoding="utf-8")

    projects = scaffold.find_projects(tmp_path)
    assert [p["name"] for p in projects] == ["Shop"]
    assert projects[0]["subsystems"] == ["Core"]

    hit = scaffold.find_object(tmp_path, "Goods")
    assert hit.subsystem == "Core"

    result = scaffold.op_add_subsystem(project_dir, "Extra")
    assert [c.path for c in result.changes] == [project_dir / "Extra" / "Subsystem.yaml"]


# --- localization section -----------------------------------------------------------------


def _loc_element(tmp_path, name="ПробаЛокализация"):
    apply_result(scaffold.op_new_object(tmp_path, "ЛокализованныеСтроки", name))
    path = tmp_path / f"{name}.yaml"
    path.write_text(
        path.read_text(encoding="utf-8")
        + "Строки:\n    Привет: Привет\n    Пока: Пока\n"
        + 'Шаблоны:\n    Время: "Время: %0"\n',
        encoding="utf-8",
    )
    return path


def _loc_descriptor(tmp_path, languages=("Русский", "Английский"), default="Русский"):
    lines = [
        "Ид: 6f0b6a44-0000-4000-8000-0000000000b1",
        "Имя: Проба", "Поставщик: e1c", "Версия: 1.0.0",
        f"ЯзыкПоУмолчанию: {default}", "ЯзыкиЛокализации:",
        *[f"    - {lang}" for lang in languages],
    ]
    (tmp_path / "Проект.yaml").write_text("\n".join(lines) + "\n", encoding="utf-8")


def test_add_localization_copies_the_string_sections(tmp_path):
    _loc_descriptor(tmp_path)
    path = _loc_element(tmp_path)
    result = scaffold.op_add_localization(path, "Английский")
    written = apply_result(result)
    target = tmp_path / "Локализация" / "En" / "ПробаЛокализация.yaml"
    assert written == [str(target)]
    text = target.read_text(encoding="utf-8")
    # The translation repeats the string sections alone: the keys with the default-language
    # values to replace, no element header (the documentation allows only these sections).
    assert "ВидЭлемента" not in text
    assert "Привет: Привет" in text
    assert 'Время: "Время: %0"' in text
    assert any("переведите" in note for note in result.notes)


def test_add_localization_accepts_the_folder_code(tmp_path):
    _loc_descriptor(tmp_path)
    path = _loc_element(tmp_path)
    apply_result(scaffold.op_add_localization(path, "en"))
    assert (tmp_path / "Локализация" / "En" / "ПробаЛокализация.yaml").is_file()


def test_add_localization_reuses_the_existing_section_dir(tmp_path):
    _loc_descriptor(tmp_path)
    path = _loc_element(tmp_path)
    (tmp_path / "Localization").mkdir()
    apply_result(scaffold.op_add_localization(path, "Английский"))
    assert (tmp_path / "Localization" / "En" / "ПробаЛокализация.yaml").is_file()


def test_add_localization_rejections(tmp_path):
    _loc_descriptor(tmp_path)
    path = _loc_element(tmp_path)
    apply_result(scaffold.op_new_object(tmp_path, "Справочник", "Товары"))
    with pytest.raises(ScaffoldError, match="не ЛокализованныеСтроки"):
        scaffold.op_add_localization(tmp_path / "Товары.yaml", "Английский")
    with pytest.raises(ScaffoldError, match="Неизвестный язык"):
        scaffold.op_add_localization(path, "Французский")
    with pytest.raises(ScaffoldError, match="язык по умолчанию"):
        scaffold.op_add_localization(path, "Русский")
    apply_result(scaffold.op_add_localization(path, "Английский"))
    with pytest.raises(ScaffoldError, match="уже существует"):
        scaffold.op_add_localization(path, "Английский")


def test_add_localization_requires_a_declared_language(tmp_path):
    _loc_descriptor(tmp_path, languages=("Русский",))
    path = _loc_element(tmp_path)
    with pytest.raises(ScaffoldError, match="не указан в ЯзыкиЛокализации"):
        scaffold.op_add_localization(path, "Английский")


def test_add_localization_without_sections_writes_an_empty_one(tmp_path):
    _loc_descriptor(tmp_path)
    apply_result(scaffold.op_new_object(tmp_path, "ЛокализованныеСтроки", "Пустая"))
    result = scaffold.op_add_localization(tmp_path / "Пустая.yaml", "Английский")
    apply_result(result)
    text = (tmp_path / "Локализация" / "En" / "Пустая.yaml").read_text(encoding="utf-8")
    assert text == "Строки:\n"


def test_localization_info_candidates(tmp_path):
    _loc_descriptor(tmp_path)
    path = _loc_element(tmp_path)
    info = scaffold.localization_info(path)
    assert info["languages"] == ["Ru", "En"]
    assert info["default"] == "Ru"
    assert info["existing"] == []
    assert info["candidates"] == ["En"]
    assert info["names"] == {"En": "Английский"}
    apply_result(scaffold.op_add_localization(path, "Английский"))
    info = scaffold.localization_info(path)
    assert info["existing"] == ["En"]
    assert info["candidates"] == []


def test_localization_info_without_a_descriptor(tmp_path):
    path = _loc_element(tmp_path)
    info = scaffold.localization_info(path)
    # No declared languages: every supported language is offered, with the note that the
    # descriptor must declare them for localization to work at all.
    assert info["languages"] == []
    assert info["candidates"] == ["Ru", "En"]
    assert info["notes"]


def test_localization_info_reads_an_inline_language_list(tmp_path):
    # The real site descriptor writes the list inline - the form the block parser missed.
    (tmp_path / "Проект.yaml").write_text(
        "Ид: 6f0b6a44-0000-4000-8000-0000000000b2\n"
        "Имя: Проба\nПоставщик: e1c\nВерсия: 1.0.0\n"
        "ЯзыкиЛокализации: [Русский, Английский]\n"
        "ЯзыкПоУмолчанию: Русский\n",
        encoding="utf-8",
    )
    info = scaffold.localization_info(_loc_element(tmp_path))
    assert info["languages"] == ["Ru", "En"]
    assert info["candidates"] == ["En"]


# --- processing form ----------------------------------------------------------------------


def test_add_form_processing(tmp_path):
    apply_result(scaffold.op_new_object(tmp_path, "Обработка", "Расчет"))
    path = tmp_path / "Расчет.yaml"
    path.write_text(
        path.read_text(encoding="utf-8")
        + "Реквизиты:\n    -\n        Имя: Вес\n        Тип: Число\n"
        + "Операции:\n    -\n        Имя: Рассчитать\n        Основная: Истина\n",
        encoding="utf-8",
    )
    result = scaffold.op_add_form(tmp_path, yaml_path=path)
    apply_result(result)
    form = (tmp_path / "РасчетФормаОбработки.yaml").read_text(encoding="utf-8")
    _valid_yaml(form)
    assert "Тип: ФормаОбработки<Расчет.Объект>" in form
    # The commands come from the Commands type: new operations reach the form by themselves.
    assert "ОсновнаяКоманда: =Команды.ПолучитьОсновную()" in form
    assert "ОбычныеКоманды: =Команды.ПолучитьОбычные()" in form
    assert "Значение: =Объект.Вес" in form
    assert "Форма: РасчетФормаОбработки" in path.read_text(encoding="utf-8")


def test_add_form_processing_is_the_only_choice_for_a_processor(tmp_path):
    apply_result(scaffold.op_new_object(tmp_path, "Обработка", "Расчет"))
    with pytest.raises(ScaffoldError, match="только форма обработки"):
        scaffold.op_add_form(tmp_path, yaml_path=tmp_path / "Расчет.yaml", forms=["object"])
    apply_result(scaffold.op_new_object(tmp_path, "Справочник", "Товары"))
    with pytest.raises(ScaffoldError, match="неприменима"):
        scaffold.op_add_form(
            tmp_path, yaml_path=tmp_path / "Товары.yaml", forms=["processing"]
        )


def test_add_form_processing_registers_into_an_existing_interface(tmp_path):
    apply_result(scaffold.op_new_object(tmp_path, "Обработка", "Расчет"))
    path = tmp_path / "Расчет.yaml"
    path.write_text(
        path.read_text(encoding="utf-8") + "Интерфейс:\n    ВключатьВАвтоИнтерфейс: Ложь\n",
        encoding="utf-8",
    )
    apply_result(scaffold.op_add_form(tmp_path, yaml_path=path))
    owner = path.read_text(encoding="utf-8")
    assert "    ВключатьВАвтоИнтерфейс: Ложь\n    Форма: РасчетФормаОбработки" in owner


def test_section_insertions_keep_crlf_files_crlf(tmp_path):
    # A CRLF yaml stays CRLF after an insertion: body_end must not sit between \r and \n,
    # or the edit leaves a lone \r (a broken line, and git normalizes the whole file).
    path = tmp_path / "Товары.yaml"
    path.write_bytes(
        (
            "ВидЭлемента: Справочник\r\nИд: 6f0b6a44-0000-4000-8000-0000000000c3\r\n"
            "Имя: Товары\r\nОбластьВидимости: ВПодсистеме\r\n"
            "Реквизиты:\r\n    -\r\n        Имя: Цена\r\n        Тип: Число\r\n"
        ).encode("utf-8")
    )
    apply_result(scaffold.op_add_field(path, "реквизит", "Вес", type_="Число"))
    raw = path.read_bytes().decode("utf-8")
    assert "Имя: Вес" in raw
    assert "\r\r" not in raw
    assert raw.count("\n") == raw.count("\r\n")


# --- properties of metadata items ---------------------------------------------------------


def _constants_set(tmp_path, name="НастройкиПриложения"):
    apply_result(scaffold.op_new_object(tmp_path, "НаборКонстант", name))
    return tmp_path / f"{name}.yaml"


def test_add_field_writes_item_properties(tmp_path):
    path = _constants_set(tmp_path)
    apply_result(scaffold.op_add_field(
        path, "константа", "АдресExtApi", type_="Строка",
        props={"ЗначениеПоУмолчанию": "https://example.com/a/adm/hs/ext_api",
               "Представление": "Адрес ExtAPI"},
    ))
    text = path.read_text(encoding="utf-8")
    parsed = _valid_yaml(text)
    constant = parsed["Константы"][0]
    assert constant["Имя"] == "АдресExtApi"
    assert constant["ЗначениеПоУмолчанию"] == "https://example.com/a/adm/hs/ext_api"
    assert constant["Представление"] == "Адрес ExtAPI"
    # An address carries a colon - a bare scalar would lie about the value; a plain word does not.
    assert 'ЗначениеПоУмолчанию: "https://example.com/a/adm/hs/ext_api"' in text


@pytest.mark.needs_data
def test_add_field_property_names_are_checked(tmp_path):
    path = _constants_set(tmp_path)
    with pytest.raises(ScaffoldError, match="нет свойства"):
        scaffold.op_add_field(path, "константа", "К1", props={"ЗначениеПоУмолчнию": "1"})
    # What the operation writes itself is not a property to pass here.
    with pytest.raises(ScaffoldError, match="отдельным параметром"):
        scaffold.op_add_field(path, "константа", "К2", props={"Тип": "Число"})
    with pytest.raises(ScaffoldError, match="многострочное"):
        scaffold.op_add_field(path, "константа", "К3", props={"Представление": "две\nстроки"})


@pytest.mark.needs_data
def test_add_field_accepts_the_english_spelling_of_a_property(tmp_path):
    path = _constants_set(tmp_path)
    apply_result(scaffold.op_add_field(
        path, "константа", "Порог", type_="Число", props={"MaxValue": "100"},
    ))
    # The project is Russian - the key is written the Russian way whichever spelling came in.
    assert "МаксимальноеЗначение: 100" in path.read_text(encoding="utf-8")


def test_set_field_property_replaces_and_appends(tmp_path):
    path = _constants_set(tmp_path)
    apply_result(scaffold.op_add_field(
        path, "константа", "АдресСайта", type_="Строка", props={"ЗначениеПоУмолчанию": "старый"},
    ))
    apply_result(scaffold.op_set_field_property(
        path, "константа", "АдресСайта",
        {"ЗначениеПоУмолчанию": "https://example.com/site", "Представление": "Адрес сайта"},
    ))
    parsed = _valid_yaml(path.read_text(encoding="utf-8"))
    constant = parsed["Константы"][0]
    assert constant["ЗначениеПоУмолчанию"] == "https://example.com/site"  # replaced in place
    assert constant["Представление"] == "Адрес сайта"  # appended to the item
    assert len(parsed["Константы"]) == 1


def test_set_field_property_edits_the_named_item_only(tmp_path):
    path = _constants_set(tmp_path)
    for name in ("Первая", "Вторая", "Третья"):
        apply_result(scaffold.op_add_field(path, "константа", name, type_="Строка"))
    apply_result(scaffold.op_set_field_property(
        path, "константа", "Вторая", {"Представление": "Вторая константа"},
    ))
    constants = _valid_yaml(path.read_text(encoding="utf-8"))["Константы"]
    assert [c.get("Представление") for c in constants] == [None, "Вторая константа", None]


@pytest.mark.needs_data
def test_set_field_property_rejections(tmp_path):
    path = _constants_set(tmp_path)
    apply_result(scaffold.op_add_field(path, "константа", "Ключ", type_="Строка"))
    with pytest.raises(ScaffoldError, match="не найден"):
        scaffold.op_set_field_property(path, "константа", "Нет", {"Представление": "х"})
    with pytest.raises(ScaffoldError, match="нет свойства"):
        scaffold.op_set_field_property(path, "константа", "Ключ", {"Выдуманное": "х"})
    # Renaming updates references - that is meta_rename_object's job, not a property edit.
    with pytest.raises(ScaffoldError, match="отдельным параметром"):
        scaffold.op_set_field_property(path, "константа", "Ключ", {"Имя": "Другое"})
    with pytest.raises(ScaffoldError, match="Не заданы свойства"):
        scaffold.op_set_field_property(path, "константа", "Ключ", {})


def test_set_field_property_refuses_a_block_value(tmp_path):
    path = _constants_set(tmp_path)
    apply_result(scaffold.op_add_field(path, "константа", "Ключ", type_="Строка"))
    text = path.read_text(encoding="utf-8")
    path.write_text(
        text.replace(
            "        Тип: Строка",
            "        Тип: Строка\n        ОграниченияЭлементов:\n            МаксимальнаяДлина: 10",
        ),
        encoding="utf-8",
    )
    with pytest.raises(ScaffoldError, match="блоком"):
        scaffold.op_set_field_property(
            path, "константа", "Ключ", {"ОграниченияЭлементов": "нет"},
        )


def test_set_field_property_on_a_tabular_attribute(tmp_path):
    apply_result(scaffold.op_new_object(tmp_path, "Справочник", "Заказы"))
    path = tmp_path / "Заказы.yaml"
    apply_result(scaffold.op_add_field(path, "табличная-часть", "Строки"))
    apply_result(scaffold.op_add_field(path, "реквизит", "Реквизит1", type_="Строка"))
    apply_result(scaffold.op_set_field_property(
        path, "реквизит", "Реквизит1", {"МаксимальнаяДлина": "50"}, tabular="Строки",
    ))
    parsed = _valid_yaml(path.read_text(encoding="utf-8"))
    tabular_attr = parsed["ТабличныеЧасти"][0]["Реквизиты"][0]
    assert tabular_attr["МаксимальнаяДлина"] == 50
    # The object attribute of the same name is untouched: the tabular one was asked for.
    assert "МаксимальнаяДлина" not in parsed["Реквизиты"][0]


def test_new_object_presentation(tmp_path):
    apply_result(scaffold.op_new_object(
        tmp_path, "НаборКонстант", "НастройкиПриложения", presentation="Настройки приложения",
    ))
    text = (tmp_path / "НастройкиПриложения.yaml").read_text(encoding="utf-8")
    assert _valid_yaml(text)["Представление"] == "Настройки приложения"
    # Right after Name, the order the platform serializes the header in.
    assert "Имя: НастройкиПриложения\nПредставление: Настройки приложения\nОбластьВидимости:" in text


def test_new_object_presentation_for_a_generated_kind(tmp_path):
    # A report builds its yaml in a generator of its own - the caption still lands, right
    # after Name, because it is written into the finished text rather than by each generator.
    apply_result(scaffold.op_new_object(
        tmp_path, "Отчет", "Остатки", presentation="Остатки товаров",
        report={"source": "Заказы", "rows": ["Товар"], "measures": ["Сумма"]},
    ))
    text = (tmp_path / "Остатки.yaml").read_text(encoding="utf-8")
    assert _valid_yaml(text)["Представление"] == "Остатки товаров"
    # The generator writes a caption of its own (the name) - it is replaced, not doubled.
    assert text.count("Представление:") == 1


@pytest.mark.needs_data
def test_new_object_presentation_only_where_the_kind_has_one(tmp_path):
    # The metamodel is the judge: an HTTP service has no Presentation, and writing one
    # would produce a file the compiler rejects.
    with pytest.raises(ScaffoldError, match="нет свойства Представление"):
        scaffold.op_new_object(
            tmp_path, "HttpСервис", "ОбменHttpСервис", presentation="Сервис обмена",
        )


@pytest.mark.needs_data
def test_new_object_presentation_is_a_caption_or_an_attribute_name(tmp_path):
    """Presentation means two different things, and the tool refuses the wrong one.

    A catalog shows the value of a string ATTRIBUTE (metamodel type AttributeName); a
    caption written there compiles into "Field specified as a presentation field is not
    found" (checked on the server 07.08.2026). A constants set has no attributes at all -
    there the value is a caption, and the server takes it.
    """
    with pytest.raises(ScaffoldError, match="ИМЯ строкового реквизита"):
        scaffold.op_new_object(tmp_path, "Справочник", "Товары", presentation="Товары склада")
    apply_result(scaffold.op_new_object(
        tmp_path, "Справочник", "Товары", presentation="Название",
    ))
    assert "Представление: Название" in (tmp_path / "Товары.yaml").read_text(encoding="utf-8")
    apply_result(scaffold.op_new_object(
        tmp_path, "НаборКонстант", "Настройки", presentation="Настройки приложения",
    ))
    assert "Представление: Настройки приложения" in (tmp_path / "Настройки.yaml").read_text(encoding="utf-8")


# --- routes_for: the verbs are checked, not just upper-cased -------------------------------

def test_routes_for_composes_the_routes_string():
    assert scaffold.routes_for("/orders", ["GET", "POST"]) == "GET /orders, POST /orders"
    # any casing and stray spaces are the caller's convenience, not a mistake
    assert scaffold.routes_for("/orders", ["get", " post "]) == "GET /orders, POST /orders"


def test_routes_for_refuses_a_verb_that_is_not_one():
    """A caller passing the methods as a python-looking list used to have the quotes and
    brackets travel into the generated handler names - code that cannot parse."""
    with pytest.raises(scaffold.ScaffoldError) as info:
        scaffold.routes_for("/orders", ["['GET'", "'POST']"])
    assert "GET" in str(info.value)  # the message names what is allowed


def test_routes_for_still_requires_a_template_and_a_verb():
    with pytest.raises(scaffold.ScaffoldError):
        scaffold.routes_for("", ["GET"])
    with pytest.raises(scaffold.ScaffoldError):
        scaffold.routes_for("/orders", [])


# --- localization_strings: the texts behind the $Dictionary.Key references ------------------


def test_localization_strings_collects_the_default_language(tmp_path):
    _loc_descriptor(tmp_path)
    _loc_element(tmp_path)
    got = scaffold.localization_strings(tmp_path)
    assert got["strings"]["ПробаЛокализация.Привет"] == "Привет"
    assert got["strings"]["ПробаЛокализация.Время"] == "Время: %0"  # the templates section counts too
    assert got["default"] == "Ru"


def test_localization_strings_layers_a_translation_on_top(tmp_path):
    _loc_descriptor(tmp_path)
    path = _loc_element(tmp_path)
    folder = path.parent / "Локализация" / "En"
    folder.mkdir(parents=True)
    (folder / "ПробаЛокализация.yaml").write_text("Строки:\n    Привет: Hello\n", encoding="utf-8")

    got = scaffold.localization_strings(tmp_path, "En")

    assert got["strings"]["ПробаЛокализация.Привет"] == "Hello"
    # a key with no translation keeps the default text - the platform falls back the same way
    assert got["strings"]["ПробаЛокализация.Пока"] == "Пока"


def test_localization_strings_of_a_project_without_dictionaries_is_empty(tmp_path):
    _loc_descriptor(tmp_path)
    (tmp_path / "Модуль.xbsl").write_text("метод Ф()\n;\n", encoding="utf-8")
    assert scaffold.localization_strings(tmp_path)["strings"] == {}
