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
