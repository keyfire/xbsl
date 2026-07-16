"""Скаффолдинг метаданных (xbsl/scaffold.py): правки текста, шаблоны, операции.

Каждый сгенерированный yaml дополнительно прогоняется через PyYAML: шаблон, который
не разбирается парсером, не должен пройти тесты независимо от точечных проверок.
"""

from pathlib import Path

import pytest
import yaml as pyyaml

from xbsl import scaffold
from xbsl.scaffold import (
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


# --- правки текста -------------------------------------------------------------------


def test_insert_item_into_existing_section():
    edit = insert_item_edit(CATALOG, "Реквизиты", ["Ид: х", "Имя: Цвет", "Тип: Строка"])
    out = apply_edit(CATALOG, edit)
    names = [i["Имя"] for i in section_items(out, "Реквизиты")]
    assert names == ["Артикул", "Цвет"]
    # Вставка точечная: секция ТабличныеЧасти не сдвинулась по содержимому.
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
    # Реквизиты верхнего уровня не пострадали.
    assert [i["Имя"] for i in section_items(out, "Реквизиты")] == ["Артикул"]


def test_section_items_inline_form():
    text = "Использование:\nЭлементы:\n    - Имя: Один\n    -\n        Имя: Два\n"
    assert [i["Имя"] for i in section_items(text, "Элементы")] == ["Один", "Два"]


# --- объекты ---------------------------------------------------------------------------


def test_new_object_catalog(tmp_path):
    result = scaffold.op_new_object(tmp_path, "Справочник", "Товары")
    written = apply_result(result)
    assert written == [str(tmp_path / "Товары.yaml")]
    text = (tmp_path / "Товары.yaml").read_text(encoding="utf-8")
    parsed = _valid_yaml(text)
    assert parsed["ВидЭлемента"] == "Справочник"
    # Умолчание – платформенное: видимость не расширяется за разработчика.
    assert parsed["ОбластьВидимости"] == "ВПодсистеме"
    assert parsed["Ид"]

    apply_result(scaffold.op_new_object(tmp_path, "Справочник", "Склады", scope="ВПроекте"))
    wider = _valid_yaml((tmp_path / "Склады.yaml").read_text(encoding="utf-8"))
    assert wider["ОбластьВидимости"] == "ВПроекте"


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
    # Право лежит внутри Разрешения: КонтрольДоступа – набор "Право: СпособКонтроляДоступа".
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
    assert all(len(f["Ид"]) == 32 for f in fields)  # hex без дефисов

    with pytest.raises(ScaffoldError, match="источник"):
        scaffold.op_new_object(tmp_path, "Отчет", "Пустой")


# --- поля ------------------------------------------------------------------------------


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


# --- подсистема и проект ----------------------------------------------------------------


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


# --- маршруты в существующий сервис ------------------------------------------------------


def test_add_route_extends_service(tmp_path):
    apply_result(scaffold.op_new_object(tmp_path, "HttpСервис", "Апи", routes="GET /, GET /{id}"))
    yaml_path = tmp_path / "Апи.yaml"
    result = scaffold.op_add_route(yaml_path, "DELETE /{id}, GET /")
    apply_result(result)
    parsed = _valid_yaml(yaml_path.read_text(encoding="utf-8"))
    by_template = {t["Шаблон"]: [m["Метод"] for m in t["Методы"]] for t in parsed["ШаблоныUrl"]}
    assert by_template["/{id}"] == ["GET", "DELETE"]
    assert by_template["/"] == ["GET"]  # дубль не добавился
    assert any("уже есть" in note for note in result.notes)
    module = (tmp_path / "Апи.xbsl").read_text(encoding="utf-8")
    assert module.count("метод Удалить") == 1
    assert module.count("метод ОбработатьОшибку") == 1


def test_add_route_new_template(tmp_path):
    apply_result(scaffold.op_new_object(tmp_path, "HttpСервис", "Апи", routes="GET /"))
    apply_result(scaffold.op_add_route(tmp_path / "Апи.yaml", "GET /users"))
    parsed = _valid_yaml((tmp_path / "Апи.yaml").read_text(encoding="utf-8"))
    assert {t["Шаблон"] for t in parsed["ШаблоныUrl"]} == {"/", "/users"}


# --- формы -------------------------------------------------------------------------------


def _make_project(tmp_path) -> Path:
    """Мини-проект: vendor/Приложение/Основное с иерархией папок как в реальных исходниках."""
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
    # Колонка динамического списка адресует поле строки через ПолеЗначения (оно же даёт
    # сортировку по колонке) – как в рабочих формах проекта и эталонов.
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
    # Обязательный реквизит Дата документа попал в форму (он создаётся в yaml сразу).
    # Номер опционален и по умолчанию отсутствует – фантомного поля Номер в форме быть не должно.
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
    # Имени иерархии "Иерархия" не существует (так называется таблица языка запросов):
    # для иерархии элементов используется режим ПоУмолчанию.
    hierarchy = _valid_yaml(form)["Свойства"][0]["ЗначениеПоУмолчанию"]["ИспользуемаяИерархия"]
    assert hierarchy == {"Тип": "РежимИерархии", "Значение": "ПоУмолчанию"}
    assert "Выражение: Родитель" in form
    assert _valid_yaml(form)


# --- разведка ----------------------------------------------------------------------------


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


# --- переименование объекта ---------------------------------------------------------------


def _make_rename_project(tmp_path) -> Path:
    """Проект со складом, его формами и ловушками совпадающих имён."""
    subsystem = _make_project(tmp_path)
    apply_result(scaffold.op_new_object(subsystem, "Справочник", "Склады"))
    apply_result(scaffold.op_new_object(subsystem, "Справочник", "СкладыАрхив"))
    apply_result(scaffold.op_new_object(subsystem, "Справочник", "Заказы"))
    apply_result(scaffold.op_add_form(tmp_path, name="Склады"))

    # Представление объекта и заголовок формы.
    yaml_path = subsystem / "Склады.yaml"
    yaml_path.write_text(
        yaml_path.read_text(encoding="utf-8") + "Представление: Склад\n", encoding="utf-8"
    )

    # Реквизит-ловушка: называется как объект (не должен переименоваться).
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
    # Компонент строки карточного списка.
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
    assert "Имя: Склады" in orders  # реквизит-тёзка не переименован

    module = (subsystem / "Заказы.xbsl").read_text(encoding="utf-8")
    assert "импорт Склады" in module          # подсистема в импорте не трогается
    assert "пер С: Хранилища.Ссылка?" in module
    assert "ИЗ Хранилища КАК С" in module
    assert '"Склады не изменились"' in module  # строковый литерал сохранён
    assert "Хранилища в комментарии" in module
    assert "Объект.Склады" in module           # член после точки – чужое имя

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

    # Тёзки в двух подсистемах: без файла – ошибка, с файлом – переименовывается указанный.
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
    # Ничего не записано: операция только вычисляет изменения.
    assert (tmp_path / "vendor" / "Приложение" / "Основное" / "Склады.yaml").is_file()


# --- карточная форма списка ---------------------------------------------------------------


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

    # Поля списка: Ссылка для навигации + показанные карточкой.
    fields = [f["Выражение"] for f in form["Свойства"][0]["ЗначениеПоУмолчанию"]["Поля"]]
    assert fields == ["Ссылка", "Наименование", "Должность", "Отдел"]

    row = _valid_yaml((subsystem / "СтрокаСпискаСотрудники.yaml").read_text(encoding="utf-8"))
    assert row["Имя"] == "СтрокаСпискаСотрудники"
    card = row["Наследует"]["Содержимое"]
    assert row["Наследует"]["Тип"] == f"ПроизвольнаяСтрокаСписка<СтрокаДинамическогоСписка<{row_type}>>"
    assert card["Тип"] == "СтандартнаяКарточка"
    assert card["Заголовок"] == "=ДанныеСтроки.Данные.Наименование"
    # Строковое поле идёт прямо в Содержимое, ссылка – Надписью: обе в Группе.
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
    assert settings["ОписаниеАвтоматическихКолонок"]["МинимальнаяШирина"] == 250  # фото – уже

    row = _valid_yaml((subsystem / "СтрокаСпискаСотрудники.yaml").read_text(encoding="utf-8"))
    card = row["Наследует"]["Содержимое"]
    assert card["Тип"] == "ПроизвольнаяКарточка"
    stack = card["Содержимое"]
    assert stack["Компоновка"] == "Вертикальная"
    picture, label = stack["Содержимое"]
    assert picture["Тип"] == "Картинка"
    assert picture["Масштабирование"] == "Пропорционально"
    assert picture["Изображение"] == "=ДанныеСтроки.Данные.Фото ?? Ресурс{Аккаунт.svg}.Ссылка"
    assert picture["РастягиватьПоВертикали"] == "Ложь"  # иначе Высота растянется на остаток
    assert label["Значение"] == "=ДанныеСтроки.Данные.Наименование"


def test_cards_document_formats_date_and_notes_hidden_fields(tmp_path):
    subsystem = _make_project(tmp_path)
    apply_result(scaffold.op_new_object(subsystem, "Документ", "Заказы"))
    # Номер у документа опционален и по умолчанию не создаётся – объявляем его явно, чтобы
    # он стал заголовком карточки (стартовая Дата уже есть в yaml).
    for name in ("Номер", "ПолеА", "ПолеБ", "ПолеВ", "ПолеГ"):
        apply_result(scaffold.op_add_field(subsystem / "Заказы.yaml", "реквизит", name))
    result = scaffold.op_add_form(tmp_path, name="Заказы", forms=["list-cards"])
    apply_result(result)

    row = _valid_yaml((subsystem / "СтрокаСпискаЗаказы.yaml").read_text(encoding="utf-8"))
    card = row["Наследует"]["Содержимое"]
    # Заголовок – Номер (первое строковое), Дата форматируется, лишние поля не влезли.
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

    # Форма уже есть – ни она, ни её компонент строки не трогаются.
    again = scaffold.op_add_form(tmp_path, name="Сотрудники", forms=["list-cards"])
    assert any("СотрудникиФормаСписка.yaml уже существует" in n for n in again.notes)
    assert again.changes == []

    # Форма удалена, компонент остался: форма создаётся заново, компонент – пропускается.
    (subsystem / "СотрудникиФормаСписка.yaml").unlink()
    partial = scaffold.op_add_form(tmp_path, name="Сотрудники", forms=["list-cards"])
    created = [c.path.name for c in partial.changes if c.created]
    assert created == ["СотрудникиФормаСписка.yaml"]
    assert any("СтрокаСпискаСотрудники.yaml уже существует" in n for n in partial.notes)


# --- контроль доступа ---------------------------------------------------------------------


def test_access_info_and_set_default(tmp_path):
    subsystem = _make_project(tmp_path)
    apply_result(scaffold.op_new_object(subsystem, "Справочник", "Товары"))
    apply_result(scaffold.op_add_field(subsystem / "Товары.yaml", "реквизит", "Цвет"))
    yaml_path = subsystem / "Товары.yaml"

    # Секции нет – сводка None (значит, действует РазрешеноАдминистраторам).
    assert scaffold.object_info(tmp_path, name="Товары")["access"] is None

    result = scaffold.op_set_access(tmp_path, name="Товары", default="РазрешеноАутентифицированным")
    apply_result(result)
    text = yaml_path.read_text(encoding="utf-8")
    parsed = _valid_yaml(text)
    assert parsed["КонтрольДоступа"]["Разрешения"]["ПоУмолчанию"] == "РазрешеноАутентифицированным"
    assert parsed["Реквизиты"][0]["Имя"] == "Цвет"  # секция данных не пострадала
    assert any("нет секции" in n for n in result.notes)

    info = scaffold.object_info(tmp_path, name="Товары")
    assert info["access"]["default"] == "РазрешеноАутентифицированным"
    assert info["access_rights"] == ["Создание", "Чтение", "Изменение", "Удаление"]

    # Повторная установка того же значения – файл не трогается.
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
    # Существующее ПоУмолчанию сохранено, новые права дописаны.
    assert perms == {
        "ПоУмолчанию": "РазрешеноАдминистраторам",
        "Чтение": "РазрешеноВсем",
        "Создание": "РазрешеноАутентифицированным",
    }

    # Замена значения существующего права – на месте.
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

    # У сервиса своё право Вызов; шаблоны URL не трогаются.
    apply_result(scaffold.op_set_access(tmp_path, name="Каталог",
                                        permissions={"Вызов": "РазрешеноВсем"}))
    service = _valid_yaml((subsystem / "Каталог.yaml").read_text(encoding="utf-8"))
    assert service["КонтрольДоступа"]["Разрешения"]["Вызов"] == "РазрешеноВсем"
    assert service["ШаблоныUrl"]

    # Пользовательское право (ПравоНаЭлемент) допускается как есть.
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
    assert by_name["Склады"]["access_default"] is None  # секции нет
    assert "access_default" not in by_name["Хелпер"]  # вид без управления доступом
    assert "РазрешеноВсем" in overview["access_methods"]
    assert overview["access_kind_rights"]["HttpСервис"] == ["Вызов"]


def test_report_form_registered_when_interface_exists(tmp_path):
    subsystem = _make_project(tmp_path)
    apply_result(scaffold.op_new_object(
        subsystem, "Отчет", "Продажи2",
        report={"source": "Регистр.Продажи", "rows": ["Клиент"], "measures": ["Сумма"]},
    ))
    yaml_path = subsystem / "Продажи2.yaml"
    # У отчёта уже есть секция Интерфейс – регистрация формы обязана в неё дописаться.
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


# --- виды объектов: покрытие и парные файлы -----------------------------------------------


def test_every_bare_kind_creates_valid_yaml(tmp_path):
    """Каждый вид без обязательных параметров создаётся и даёт разбираемый yaml."""
    for kind in scaffold.bare_kinds():
        result = scaffold.op_new_object(tmp_path, kind, f"Проверка{len(kind)}{abs(hash(kind)) % 97}")
        yaml_change = next(c for c in result.changes if c.path.suffix == ".yaml")
        parsed = _valid_yaml(yaml_change.content)
        assert parsed["ВидЭлемента"] == kind
        # Умолчание видимости платформенное – инструмент не расширяет её за разработчика.
        assert parsed["ОбластьВидимости"] == "ВПодсистеме"


def test_kind_module_pairs(tmp_path):
    """Парный файл создаётся ровно у тех видов, которым он нужен, и с нужным расширением."""
    def files(kind: str) -> list[str]:
        return [c.path.suffix for c in scaffold.op_new_object(tmp_path / kind, kind, "Э").changes]

    # Право на элемент – перечисление: "Не имеет модуля".
    assert files("ПравоНаЭлемент") == [".yaml"]
    # Право на действие вычисляет разрешения в модуле.
    assert files("ПравоНаДействие") == [".yaml", ".xbsl"]
    # Контракты типа и сущности – одни свойства, модуль только под абстрактные методы.
    assert files("КонтрактТипа") == [".yaml"]
    assert files("КонтрактСущности") == [".yaml"]
    assert files("КонтрактСервиса") == [".yaml", ".xbsl"]
    # У виртуальной таблицы парный файл – запрос, а не модуль.
    assert files("ВиртуальнаяТаблица") == [".yaml", ".xbql"]
    # Навигационная команда декларативна, остальные команды живут обработчиком.
    assert files("НавигационнаяКоманда") == [".yaml"]
    assert files("ОбычнаяКоманда") == [".yaml", ".xbsl"]
    assert files("СобытиеЖурналаСобытий") == [".yaml"]


def test_kind_module_stubs_carry_documented_handlers(tmp_path):
    def module(kind: str, name: str) -> str:
        changes = scaffold.op_new_object(tmp_path / kind, kind, name).changes
        return next(c for c in changes if c.path.suffix in (".xbsl", ".xbql")).content

    # Имя элемента подставляется в обобщения; КлючДоступа.Объект – литеральный базовый тип.
    stub = module("ПравоНаДействие", "ПравоМодератора")
    assert "метод ВычислитьРазрешенияДоступа(Права: ЧитаемыйМассив<ПравоМодератора.Объект>)" in stub
    assert "ЧитаемаяКоллекция<КлючДоступа.Объект>" in stub
    assert "возврат {:}" in stub

    assert "метод Обработчик()" in module("ЗапланированноеЗадание", "ОчисткаКэша")
    assert "метод ВычислитьПараметрыРаботыКлиента()" in module("ПараметрыРаботыКлиента", "Парам")
    assert "метод ПослеПодключения()" in module(
        "ПараметрСамостоятельнойРегистрацииПользователя", "Приглашение"
    )
    # Среда разработки создаёт запрос пустым – генератор не выдумывает текст запроса.
    assert module("ВиртуальнаяТаблица", "Остатки").strip() == ""


def test_kind_notes_and_mandatory_fields(tmp_path):
    # Событию журнала обязателен ШаблонПредставления (для вида Информация).
    result = scaffold.op_new_object(tmp_path, "СобытиеЖурналаСобытий", "ИмпортДанных")
    parsed = _valid_yaml(result.changes[0].content)
    assert parsed["ВидСобытия"] == "Информация"
    assert parsed["ШаблонПредставления"] == "ИмпортДанных"
    assert any("ХарактерОшибки" in n for n in result.notes)

    # Цветовой схеме обязательно Представление.
    scheme = scaffold.op_new_object(tmp_path, "ЦветоваяСхемаОтчета", "СхемаОтчета")
    assert _valid_yaml(scheme.changes[0].content)["Представление"] == "СхемаОтчета"
    assert any("Цвета" in n for n in scheme.notes)

    # Виртуальной таблице напоминаем про обязательный запрос.
    vt = scaffold.op_new_object(tmp_path, "ВиртуальнаяТаблица", "Остатки")
    assert any(".xbql" in n for n in vt.notes)


def test_new_sections_of_added_kinds(tmp_path):
    subsystem = _make_project(tmp_path)
    # Константы набора констант – с Ид (как реквизиты).
    apply_result(scaffold.op_new_object(subsystem, "НаборКонстант", "КурсыВалют"))
    apply_result(scaffold.op_add_field(subsystem / "КурсыВалют.yaml", "константа", "КурсЦБ",
                                       type_="Число"))
    const = _valid_yaml((subsystem / "КурсыВалют.yaml").read_text(encoding="utf-8"))["Константы"][0]
    assert const["Имя"] == "КурсЦБ" and const["Ид"]

    # Свойства контракта типа – без Ид, контракта сущности – с Ид.
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

    # Действия права на элемент – секция Элементы.
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
    # Правило project/version требует A.B.C – генератор не должен ему противоречить.
    assert project["Версия"] == "1.0.0"


# --- форма объекта: колонки табличной части и обёртка раздела ------------------------------


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
    # Реквизит1 добавляется вместе с самой ТЧ (пустая ТЧ платформой не поддерживается).
    assert [f["name"] for f in tabular["fields"]] == ["Реквизит1", "Количество"]
    assert [f["type"] for f in tabular["fields"]] == ["Строка", "Число"]
    assert subsystem  # каталог подсистемы использован


def test_tabular_table_has_columns(tmp_path):
    subsystem = _doc_with_tabular(tmp_path)
    apply_result(scaffold.op_add_form(tmp_path, name="Приходы", forms=["object"]))
    form = _valid_yaml((subsystem / "ПриходыФормаОбъекта.yaml").read_text(encoding="utf-8"))
    section = form["Наследует"]["Содержимое"]["ДополнительныеРазделы"][0]
    table = section["Содержимое"][0]["Содержимое"][0]
    assert table["Тип"] == "Таблица<ИсточникДанныхМассив<Приходы.Товары>>"
    # Колонки обязательны: без них таблица показывает пустые строки.
    columns = table["Колонки"]
    assert [c["Заголовок"] for c in columns] == ["Реквизит1", "Количество"]
    # ПолеЗначения задаёт и сортировку по колонке.
    assert [c["ПолеЗначения"] for c in columns] == ["Реквизит1", "Количество"]
    assert columns[0]["Тип"] == "СтандартнаяКолонкаТаблицы<Приходы.Товары>"


def test_form_section_wraps_fields_in_group(tmp_path):
    """РазделФормы.Содержимое – Массив<Группа>: поля кладутся в область, а не напрямую."""
    subsystem = _doc_with_tabular(tmp_path)
    apply_result(scaffold.op_add_form(tmp_path, name="Приходы", forms=["object"]))
    form = _valid_yaml((subsystem / "ПриходыФормаОбъекта.yaml").read_text(encoding="utf-8"))
    section = form["Наследует"]["Содержимое"]["ОсновнойРаздел"]
    assert section["Тип"] == "РазделФормы"
    area = section["Содержимое"][0]
    assert set(area) == {"Содержимое"}  # область раздела: как в эталонных формах, без Тип
    assert [c["Имя"] for c in area["Содержимое"]] == ["Дата"]


def test_group_section_keeps_fields_inline(tmp_path):
    """Ветка panels: у Группы содержимое – Массив<Компонент>, обёртка не нужна."""
    subsystem = _doc_with_tabular(tmp_path, extra_fields=4)
    info = scaffold.object_info(tmp_path, name="Приходы")
    assert info["suggested_layout"] == "panels"
    apply_result(scaffold.op_add_form(tmp_path, name="Приходы", forms=["object"]))
    form = _valid_yaml((subsystem / "ПриходыФормаОбъекта.yaml").read_text(encoding="utf-8"))
    section = form["Наследует"]["Содержимое"]["ОсновнойРаздел"]
    assert section["Тип"] == "Группа"
    assert all("Тип" in c for c in section["Содержимое"])  # поля лежат прямо в группе


def test_object_attribute_never_lands_in_tabular(tmp_path):
    """Реквизит объекта пишется в секцию объекта, даже если своей секции ещё нет.

    Ловушка: у документа с табличной частью есть ВЛОЖЕННАЯ секция `Реквизиты`, и поиск
    секции по любому отступу принимал её за секцию объекта – реквизит уезжал в ТЧ, а поля
    ТЧ считались полями объекта.
    """
    apply_result(scaffold.op_new_object(tmp_path, "Документ", "Приходы"))
    yaml_path = tmp_path / "Приходы.yaml"
    apply_result(scaffold.op_add_field(yaml_path, "табличная-часть", "Товары"))
    apply_result(scaffold.op_add_field(yaml_path, "реквизит", "Контрагент", type_="Строка"))
    apply_result(scaffold.op_add_field(yaml_path, "реквизит", "Цена", type_="Число",
                                       tabular="Товары"))

    parsed = _valid_yaml(yaml_path.read_text(encoding="utf-8"))
    # Дата – стартовый реквизит документа в секции объекта; Контрагент дописан к ней.
    assert [f["Имя"] for f in parsed["Реквизиты"]] == ["Дата", "Контрагент"]
    assert [f["Имя"] for f in parsed["ТабличныеЧасти"][0]["Реквизиты"]] == ["Реквизит1", "Цена"]

    info = scaffold.object_info(tmp_path, name="Приходы")
    assert [f["name"] for f in info["fields"]] == ["Дата", "Контрагент"]
    assert [f["name"] for f in info["tabulars"][0]["fields"]] == ["Реквизит1", "Цена"]

    # Имя, занятое в табличной части, не считается дублем реквизита объекта.
    apply_result(scaffold.op_add_field(yaml_path, "реквизит", "Реквизит1", type_="Строка"))
    parsed = _valid_yaml(yaml_path.read_text(encoding="utf-8"))
    assert [f["Имя"] for f in parsed["Реквизиты"]] == ["Дата", "Контрагент", "Реквизит1"]


# --- применимость форм к виду -------------------------------------------------------------


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
    # Данные регистра – Измерения и Ресурсы; раньше сводка видела только Реквизиты.
    # Измерение1 – стартовое измерение (без него РС не компилируется), затем добавленные.
    assert [f["name"] for f in info["fields"]] == ["Измерение1", "Валюта", "Курс", "Источник"]


def test_register_gets_list_form_only(tmp_path):
    subsystem = _register(tmp_path)
    result = scaffold.op_add_form(tmp_path, name="КурсыВалют")
    apply_result(result)
    # Формы объекта у регистра не бывает – по умолчанию делается только список.
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


# --- сводка: регистры и обработчики разрешений --------------------------------------------


def test_object_info_balance_register(tmp_path):
    subsystem = _make_project(tmp_path)
    apply_result(scaffold.op_new_object(subsystem, "РегистрНакопления", "ОстаткиТоваров"))
    yaml_path = subsystem / "ОстаткиТоваров.yaml"
    apply_result(scaffold.op_add_field(yaml_path, "измерение", "Товар", type_="Строка"))
    apply_result(scaffold.op_add_field(yaml_path, "ресурс", "Количество", type_="Число"))

    info = scaffold.object_info(tmp_path, name="ОстаткиТоваров")
    # Остатки – значение ВидРегистра по умолчанию; движению нужен ВидЗаписи (Приход/Расход).
    assert info["register"]["register_kind"] == "Остатки"
    assert info["register"]["needs_record_type"] is True
    # Ресурс1 – стартовый ресурс (без него РН не компилируется), стоит в секции Ресурсы
    # перед добавленным Количеством.
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
    # Непериодический – Период не порождается.
    assert info["register"]["periodicity"] == "Непериодический"
    assert info["register"]["needs_record_type"] is False
    assert "Период" not in [f["name"] for f in info["fields"]]

    yaml_path = subsystem / "Настройки.yaml"
    yaml_path.write_text(yaml_path.read_text(encoding="utf-8") + "Периодичность: День\n",
                         encoding="utf-8")
    periodic = scaffold.object_info(tmp_path, name="Настройки")
    assert periodic["register"]["periodicity"] == "День"
    # Период (стандартное поле периодического РС) + стартовое Измерение1.
    assert [f["name"] for f in periodic["fields"]] == ["Период", "Измерение1"]


def test_object_info_access_handlers(tmp_path):
    subsystem = _make_project(tmp_path)
    apply_result(scaffold.op_new_object(subsystem, "Справочник", "Задачи"))
    info = scaffold.object_info(tmp_path, name="Задачи")
    assert info["access_handlers"] == {"module": None, "level1": False, "level2": False}
    assert info["register"] is None  # не регистр

    # Обработчики разрешений живут в модуле объекта <Имя>.xbsl.
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


# --- зависимость от библиотеки -----------------------------------------------------------


def _project_yaml(tmp_path) -> Path:
    _make_project(tmp_path)
    return tmp_path / "vendor" / "Приложение" / "Проект.yaml"


def test_add_dependency_creates_section(tmp_path):
    project = _project_yaml(tmp_path)
    result = scaffold.op_add_dependency(tmp_path, "e1c", "CurrencyConverter", "9.0.2")
    apply_result(result)
    # Формат раздела – из документации "Подключить библиотеку к проекту".
    assert _valid_yaml(project.read_text(encoding="utf-8"))["Библиотеки"] == [
        {"Имя": "CurrencyConverter", "Поставщик": "e1c", "Версия": "9.0.2"}
    ]
    assert any("Подсистема[::Пакет]::ИмяТипа" in note for note in result.notes)


def test_add_dependency_version_stays_unquoted(tmp_path):
    project = _project_yaml(tmp_path)
    apply_result(scaffold.op_add_dependency(tmp_path, "e1c", "CurrencyConverter", "2.0"))
    # Версия пишется без кавычек – так её пишет платформа и показывает документация,
    # хотя разбор yaml и делает из "2.0" число.
    assert "Версия: 2.0" in project.read_text(encoding="utf-8")


def test_add_dependency_appends_to_existing_section(tmp_path):
    project = _project_yaml(tmp_path)
    apply_result(scaffold.op_add_dependency(tmp_path, "e1c", "CurrencyConverter", "2.0"))
    apply_result(scaffold.op_add_dependency(tmp_path, "e1c", "MessageQueue", "9.0.2"))
    libraries = _valid_yaml(project.read_text(encoding="utf-8"))["Библиотеки"]
    assert [item["Имя"] for item in libraries] == ["CurrencyConverter", "MessageQueue"]


def test_add_dependency_updates_version_in_place(tmp_path):
    project = _project_yaml(tmp_path)
    apply_result(scaffold.op_add_dependency(tmp_path, "e1c", "CurrencyConverter", "9.0.2"))
    result = scaffold.op_add_dependency(tmp_path, "e1c", "CurrencyConverter", "9.1.0")
    apply_result(result)
    # Разные версии одной библиотеки внутри проекта не допускаются: запись одна, версия новая.
    assert _valid_yaml(project.read_text(encoding="utf-8"))["Библиотеки"] == [
        {"Имя": "CurrencyConverter", "Поставщик": "e1c", "Версия": "9.1.0"}
    ]
    assert result.notes == ["e1c::CurrencyConverter: версия 9.0.2 -> 9.1.0"]


def test_add_dependency_same_version_is_noop(tmp_path):
    _project_yaml(tmp_path)
    apply_result(scaffold.op_add_dependency(tmp_path, "e1c", "CurrencyConverter", "2.0"))
    result = scaffold.op_add_dependency(tmp_path, "e1c", "CurrencyConverter", "2.0")
    assert result.changes == []
    assert any("уже подключена" in note for note in result.notes)


def test_add_dependency_rejects_build_version(tmp_path):
    _project_yaml(tmp_path)
    # 1.0-42 – версия сборки; к проекту подключается версия релиза.
    with pytest.raises(ScaffoldError, match="версия сборки"):
        scaffold.op_add_dependency(tmp_path, "e1c", "CurrencyConverter", "1.0-42")


def test_add_dependency_rejects_namesake_from_other_vendor(tmp_path):
    _project_yaml(tmp_path)
    apply_result(scaffold.op_add_dependency(tmp_path, "e1c", "CurrencyConverter", "2.0"))
    with pytest.raises(ScaffoldError, match="уже подключена"):
        scaffold.op_add_dependency(tmp_path, "acme", "CurrencyConverter", "3.0")


def test_add_dependency_reports_ambiguous_root(tmp_path):
    apply_result(scaffold.op_new_project(tmp_path, "vendor", "Первый"))
    apply_result(scaffold.op_new_project(tmp_path, "vendor", "Второй"))
    with pytest.raises(ScaffoldError, match="несколько проектов"):
        scaffold.op_add_dependency(tmp_path, "e1c", "CurrencyConverter", "2.0")
    # Явный путь снимает неоднозначность.
    target = tmp_path / "vendor" / "Второй" / "Проект.yaml"
    apply_result(scaffold.op_add_dependency(
        tmp_path, "e1c", "CurrencyConverter", "2.0", project_yaml=target
    ))
    assert "CurrencyConverter" in target.read_text(encoding="utf-8")


def test_project_info_lists_libraries(tmp_path):
    _project_yaml(tmp_path)
    apply_result(scaffold.op_add_dependency(tmp_path, "e1c", "CurrencyConverter", "2.0"))
    project = scaffold.project_info(tmp_path)["projects"][0]
    assert project["libraries"] == [
        {"Имя": "CurrencyConverter", "Поставщик": "e1c", "Версия": "2.0"}
    ]
