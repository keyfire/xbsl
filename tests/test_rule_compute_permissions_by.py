"""yaml/compute-permissions-by: the attributes the permissions of objects are computed by.

The kinds judged and the privileges of each come from the metamodel, hence `needs_data`.
"""

import pytest

from xbsl import engine, i18n

RULE = "yaml/compute-permissions-by"


def _lint(name, text):
    return engine.run_sources([engine.load_text(name, text)], select={RULE})


def _catalog(control, kind="Справочник"):
    return (f"ВидЭлемента: {kind}\nИд: 4d2f7c60-8e3b-4b5c-9a0f-9c3d4e5f6a71\nИмя: Склады\n"
            "ОбластьВидимости: ВПодсистеме\n" + control)


PER_OBJECT = "        Чтение: РазрешенияВычисляютсяДляКаждогоОбъекта\n"


@pytest.mark.needs_data
def test_per_object_permissions_without_the_attributes_are_reported():
    diags = _lint("Склады.yaml", _catalog("КонтрольДоступа:\n    Разрешения:\n" + PER_OBJECT))
    assert [(d.line, d.col) for d in diags] == [(6, 5)]
    assert ("\"Attributes for calculating object access permissions are missing\""
            in diags[0].message)


@pytest.mark.needs_data
def test_the_default_computed_for_each_object_counts_for_the_privileges_left_out():
    control = ("КонтрольДоступа:\n    Разрешения:\n"
               "        ПоУмолчанию: РазрешенияВычисляютсяДляКаждогоОбъекта\n")
    assert len(_lint("Склады.yaml", _catalog(control))) == 1


@pytest.mark.needs_data
def test_control_the_listed_attributes_are_silent():
    control = ("КонтрольДоступа:\n    РасчетРазрешенийПо: [Склад]\n    Разрешения:\n"
               + PER_OBJECT)
    assert _lint("Склады.yaml", _catalog(control)) == []


@pytest.mark.needs_data
def test_control_an_empty_list_is_no_list():
    control = ("КонтрольДоступа:\n    РасчетРазрешенийПо: []\n    Разрешения:\n" + PER_OBJECT)
    assert len(_lint("Склады.yaml", _catalog(control))) == 1


@pytest.mark.needs_data
def test_control_permissions_computed_not_for_each_object_need_no_list():
    control = "КонтрольДоступа:\n    Разрешения:\n        Чтение: РазрешенияВычисляются\n"
    assert _lint("Склады.yaml", _catalog(control)) == []


@pytest.mark.needs_data
def test_a_list_without_per_object_permissions_is_reported_at_its_first_attribute():
    control = ("КонтрольДоступа:\n    РасчетРазрешенийПо:\n        - Склад\n"
               "    Разрешения:\n        Чтение: РазрешенияВычисляются\n")
    diags = _lint("Склады.yaml", _catalog(control))
    assert [(d.line, d.col) for d in diags] == [(7, 11)]
    assert "without configuring access permissions calculation for each object" \
        in diags[0].message


@pytest.mark.needs_data
def test_the_standard_permissions_of_a_settings_storage_need_no_list():
    control = ("КонтрольДоступа:\n    СтандартныеРазрешения: Истина\n    Разрешения:\n"
               + PER_OBJECT)
    assert _lint("Настройки.yaml", _catalog(control, "ХранилищеНастроек")) == []
    control = "КонтрольДоступа:\n    Разрешения:\n" + PER_OBJECT
    assert len(_lint("Настройки.yaml", _catalog(control, "ХранилищеНастроек"))) == 1


@pytest.mark.needs_data
def test_a_register_is_judged_and_a_kind_without_the_property_is_not():
    register = _catalog("КонтрольДоступа:\n    Разрешения:\n" + PER_OBJECT, "РегистрСведений")
    assert len(_lint("Остатки.yaml", register)) == 1
    constants = _catalog("КонтрольДоступа:\n    Разрешения:\n" + PER_OBJECT, "НаборКонстант")
    assert _lint("Константы.yaml", constants) == []


@pytest.mark.needs_data
def test_the_english_spelling_is_read_and_reported_in_english():
    i18n.set_lang("en")
    catalog = ("ElementKind: Catalog\nId: 4d2f7c60-8e3b-4b5c-9a0f-9c3d4e5f6a71\nName: Stock\n"
               "AccessControl:\n    Permissions:\n"
               "        Read: PermissionsComputedForEachObject\n")
    diags = _lint("Stock.yaml", catalog)
    assert [(d.line, d.col) for d in diags] == [(5, 5)]
    assert "ComputePermissionsBy lists no attribute" in diags[0].message


# --- yaml/compute-permissions-by-unknown ----------------------------------------------------

UNKNOWN = "yaml/compute-permissions-by-unknown"


def _unknown(name, text):
    return engine.run_sources([engine.load_text(name, text)], select={UNKNOWN})


def _catalog_with(listed, attributes="", extra=""):
    return _catalog(extra + "КонтрольДоступа:\n    РасчетРазрешенийПо: [" + listed + "]\n"
                    "    Разрешения:\n" + PER_OBJECT
                    + "Реквизиты:\n"
                    "    -\n        Ид: 4d2f7c60-8e3b-4b5c-9a0f-9c3d4e5f6a72\n"
                    "        Имя: Склад\n        Тип: Строка\n        МаксимальнаяДлина: 50\n"
                    + attributes)


@pytest.mark.needs_data
def test_a_name_the_element_does_not_declare_is_reported_at_the_name():
    diags = _unknown("Склады.yaml", _catalog_with("Скалд"))
    assert [(d.line, d.col) for d in diags] == [(6, 26)]
    assert "\"Attribute \"Скалд\" is not found\"" in diags[0].message


@pytest.mark.needs_data
def test_a_standard_attribute_counts_only_when_declared():
    assert len(_unknown("Склады.yaml", _catalog_with("Наименование"))) == 1
    declared = "    -\n        Имя: Наименование\n"
    assert _unknown("Склады.yaml", _catalog_with("Наименование", declared)) == []


@pytest.mark.needs_data
def test_an_identifier_and_a_tabular_section_are_no_fields():
    table = ("ТабличныеЧасти:\n    -\n        Ид: 4d2f7c60-8e3b-4b5c-9a0f-9c3d4e5f6a73\n"
             "        Имя: Строки\n")
    assert len(_unknown("Склады.yaml", _catalog_with("Ид"))) == 1
    assert len(_unknown("Склады.yaml", _catalog_with("Строки", extra=table))) == 1


@pytest.mark.needs_data
def test_control_declared_and_service_fields_are_silent():
    # The probe took all of them: a declared attribute, the reference, the parent of a
    # hierarchical catalog.
    assert _unknown("Склады.yaml", _catalog_with("Склад")) == []
    assert _unknown("Склады.yaml", _catalog_with("Ссылка")) == []
    assert _unknown("Склады.yaml", _catalog_with("Родитель", extra="Иерархический: Истина\n")) == []


@pytest.mark.needs_data
def test_the_fields_of_a_register_are_its_dimensions_resources_and_attributes():
    register = ("ВидЭлемента: РегистрСведений\nИд: 4d2f7c60-8e3b-4b5c-9a0f-9c3d4e5f6a74\n"
                "Имя: Остатки\nОбластьВидимости: ВПодсистеме\nПериодичность: День\n"
                "КонтрольДоступа:\n    РасчетРазрешенийПо: [{listed}]\n    Разрешения:\n"
                + PER_OBJECT
                + "Измерения:\n    -\n        Ид: 4d2f7c60-8e3b-4b5c-9a0f-9c3d4e5f6a75\n"
                  "        Имя: Склад\n        Тип: Строка\n        МаксимальнаяДлина: 50\n"
                  "Ресурсы:\n    -\n        Ид: 4d2f7c60-8e3b-4b5c-9a0f-9c3d4e5f6a76\n"
                  "        Имя: Количество\n        Тип: Число\n")
    for listed in ("Склад", "Количество", "Период"):
        assert _unknown("Остатки.yaml", register.format(listed=listed)) == [], listed
    assert len(_unknown("Остатки.yaml", register.format(listed="Остаток"))) == 1


@pytest.mark.needs_data
def test_a_path_through_a_reference_is_not_judged():
    assert _unknown("Склады.yaml", _catalog_with("Склад.Владелец")) == []


@pytest.mark.needs_data
def test_a_kind_no_probe_settled_is_not_judged():
    storage = _catalog("КонтрольДоступа:\n    РасчетРазрешенийПо: [Пользователь]\n"
                       "    Разрешения:\n" + PER_OBJECT, "ХранилищеНастроек")
    assert _unknown("Настройки.yaml", storage) == []


@pytest.mark.needs_data
def test_the_english_spelling_is_read():
    i18n.set_lang("en")
    catalog = ("ElementKind: Catalog\nId: 4d2f7c60-8e3b-4b5c-9a0f-9c3d4e5f6a71\nName: Stock\n"
               "AccessControl:\n    ComputePermissionsBy: [Warehouse, Reference, Wharehouse]\n"
               "    Permissions:\n        Read: PermissionsComputedForEachObject\n"
               "Attributes:\n    -\n        Id: 4d2f7c60-8e3b-4b5c-9a0f-9c3d4e5f6a72\n"
               "        Name: Warehouse\n        Type: String\n        MaxLength: 50\n")
    diags = _unknown("Stock.yaml", catalog)
    assert [(d.line, d.col) for d in diags] == [(5, 50)]
    assert "\"Attribute \"Wharehouse\" is not found\"" in diags[0].message
