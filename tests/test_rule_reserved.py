"""Checks of the code/reserved-name and yaml/builtin-property-name rules."""

import pytest

from xbsl import dataset, engine
from xbsl.rules import reserved_names


def _lint(name, content, rule_id):
    return [
        d for d in engine.run_sources(
            [engine.load_text(name, content)], select={rule_id},
        )
        if d.rule_id == rule_id
    ]


# --- code/reserved-name: structure fields ----------------------------------------------

def test_structure_field_tip_flagged():
    d = _lint(
        "М.xbsl",
        "структура С\n    пер Тип: Строка\n;\n",
        "code/reserved-name",
    )
    assert len(d) == 1
    assert (d[0].line, d[0].col) == (2, 9)
    assert "поле структуры" in d[0].message


def test_structure_field_type_latin_flagged():
    d = _lint(
        "М.xbsl",
        "структура С\n    пер type: Строка\n;\n",
        "code/reserved-name",
    )
    assert len(d) == 1 and (d[0].line, d[0].col) == (2, 9)


def test_structure_field_type_capitalized_flagged():
    # The spelling an English structure field carries; a live apply refuses it like the others.
    d = _lint(
        "М.xbsl",
        "структура С\n    пер Type: Строка\n;\n",
        "code/reserved-name",
    )
    assert len(d) == 1 and (d[0].line, d[0].col) == (2, 9)


def test_structure_field_req_flagged():
    d = _lint(
        "М.xbsl",
        "структура С\n    обз пер Тип: Строка\n;\n",
        "code/reserved-name",
    )
    assert len(d) == 1 and (d[0].line, d[0].col) == (2, 13)


def test_structure_field_val_in_name_list_flagged():
    d = _lint(
        "М.xbsl",
        "структура С\n    знч А, Тип: Строка\n;\n",
        "code/reserved-name",
    )
    assert len(d) == 1 and (d[0].line, d[0].col) == (2, 12)


def test_structure_ordinary_fields_not_flagged():
    d = _lint(
        "М.xbsl",
        "структура С\n    пер Имя: Строка\n    пер ВидТипа: Строка\n;\n",
        "code/reserved-name",
    )
    assert d == []


def test_tip_as_type_annotation_not_flagged():
    # Тип in the TYPE position (not the name) is not a violation
    d = _lint(
        "М.xbsl",
        "структура С\n    пер ВидЗначения: Тип\n;\n",
        "code/reserved-name",
    )
    assert d == []


# --- code/reserved-name: method parameters ---------------------------------------------

def test_method_param_tip_flagged():
    d = _lint(
        "М.xbsl",
        "метод Ф(Тип: Строка): Строка\n    возврат Тип\n;\n",
        "code/reserved-name",
    )
    assert len(d) == 1
    assert (d[0].line, d[0].col) == (1, 9)
    assert "параметр метода" in d[0].message


def test_method_second_param_type_flagged():
    d = _lint(
        "М.xbsl",
        "метод Ф(Имя: Строка, type: Строка)\n;\n",
        "code/reserved-name",
    )
    assert len(d) == 1 and (d[0].line, d[0].col) == (1, 22)


def test_local_var_tip_not_flagged():
    # a local variable Тип in a method body is legal (legal code)
    d = _lint(
        "М.xbsl",
        'метод Ф()\n    пер Тип = ""\n    Тип = "х"\n;\n',
        "code/reserved-name",
    )
    assert d == []


def test_method_after_structure_not_treated_as_field():
    # the structure block is closed by `;` - declarations in a method after it do not count as fields
    d = _lint(
        "М.xbsl",
        "структура С\n    пер Имя: Строка\n;\n"
        'метод Ф()\n    пер Тип = ""\n;\n',
        "code/reserved-name",
    )
    assert d == []


# --- yaml/builtin-property-name ---------------------------------------------------------

_КАРТОЧКА = (
    "ВидЭлемента: КомпонентИнтерфейса\n"
    "Ид: 33333333-3333-3333-3333-333333333333\n"
    "Имя: Карточка1\n"
    "Наследует:\n"
    "    Тип: СтандартнаяКарточка\n"
    "Свойства:\n"
    "    -\n"
    "        Имя: {prop}\n"
    "        Тип: Строка\n"
)


def test_builtin_property_zagolovok_flagged():
    d = _lint(
        "Карточка1.yaml", _КАРТОЧКА.format(prop="Заголовок"), "yaml/builtin-property-name",
    )
    assert len(d) == 1
    assert (d[0].line, d[0].col) == (8, 14)
    assert "Заголовок" in d[0].message and "СтандартнаяКарточка" in d[0].message


def test_builtin_property_commented_section_key_positioned():
    # a comment after `Свойства:` does not break the block search - the position stays on the name
    content = _КАРТОЧКА.format(prop="Заголовок").replace("Свойства:", "Свойства: # собственные")
    d = _lint("Карточка1.yaml", content, "yaml/builtin-property-name")
    assert len(d) == 1
    assert (d[0].line, d[0].col) == (8, 14)


def test_builtin_inherited_property_flagged():
    # Видимость is inherited from Компонент - a built-in name as well
    d = _lint(
        "Карточка1.yaml", _КАРТОЧКА.format(prop="Видимость"), "yaml/builtin-property-name",
    )
    assert len(d) == 1 and (d[0].line, d[0].col) == (8, 14)


def test_custom_property_not_flagged():
    d = _lint(
        "Карточка1.yaml", _КАРТОЧКА.format(prop="КрупныйЗаголовок"), "yaml/builtin-property-name",
    )
    assert d == []


def test_container_html_zagolovok_not_flagged():
    # КонтейнерHtml's documented set has no Заголовок property; a descendant
    # of КонтейнерHtml legally declares such a property - the check is strictly per type
    content = _КАРТОЧКА.replace("СтандартнаяКарточка", "КонтейнерHtml").format(prop="Заголовок")
    d = _lint("Карточка1.yaml", content, "yaml/builtin-property-name")
    assert d == []


def test_unknown_base_type_skipped():
    # a base absent from the metamodel, the catalog and the fallback table
    # (e.g. the project's own component) - skip, do not guess
    content = _КАРТОЧКА.replace(
        "СтандартнаяКарточка", "НикакойБазовыйКомпонент",
    ).format(prop="Заголовок")
    d = _lint("Карточка1.yaml", content, "yaml/builtin-property-name")
    assert d == []


def _catalog_or_skip() -> dict:
    catalog = reserved_names._catalog_component_props()
    if not catalog:
        pytest.skip("в данных нет component_props (старые данные)")
    return catalog


def test_catalog_base_group_flagged():
    # a base from the distribution catalog (beyond the fallback table)
    assert "Группа" in _catalog_or_skip()
    content = _КАРТОЧКА.replace("СтандартнаяКарточка", "Группа").format(prop="Компоновка")
    d = _lint("Карточка1.yaml", content, "yaml/builtin-property-name")
    assert len(d) == 1
    assert "Компоновка" in d[0].message and "Группа" in d[0].message


def test_generic_base_root_resolved_via_catalog():
    # the root of a generic base (ФормаОбъекта<...>) is resolved via the component props catalog
    assert "ФормаОбъекта" in _catalog_or_skip()
    content = _КАРТОЧКА.replace(
        "СтандартнаяКарточка", "ФормаОбъекта<Товары.Объект>",
    ).format(prop="Заголовок")
    d = _lint("Карточка1.yaml", content, "yaml/builtin-property-name")
    assert len(d) == 1 and "ФормаОбъекта" in d[0].message


def test_catalog_wiring_reads_component_props(monkeypatch):
    # the catalog reaches the rule via dataset.load_json("stdlib.json").component_props
    fake = {"component_props": {"ОсобаяБаза": ["Заголовок", "Видимость"]}}
    monkeypatch.setattr(dataset, "load_json", lambda name, version=None: fake)
    reserved_names._catalog_component_props.cache_clear()
    try:
        content = _КАРТОЧКА.replace("СтандартнаяКарточка", "ОсобаяБаза").format(prop="Заголовок")
        d = _lint("Карточка1.yaml", content, "yaml/builtin-property-name")
        assert len(d) == 1 and "ОсобаяБаза" in d[0].message
    finally:
        reserved_names._catalog_component_props.cache_clear()


def test_event_with_builtin_name_not_flagged():
    # an Имя outside the Свойства block (an event) is not checked and yields no false position
    content = (
        "ВидЭлемента: КомпонентИнтерфейса\n"
        "Ид: 33333333-3333-3333-3333-333333333333\n"
        "Имя: Карточка1\n"
        "Наследует:\n"
        "    Тип: СтандартнаяКарточка\n"
        "События:\n"
        "    -\n"
        "        Имя: Заголовок\n"
        "Свойства:\n"
        "    -\n"
        "        Имя: Титул\n"
        "        Тип: Строка\n"
    )
    d = _lint("Карточка1.yaml", content, "yaml/builtin-property-name")
    assert d == []


def test_non_component_yaml_skipped():
    content = (
        "ВидЭлемента: Справочник\n"
        "Ид: 33333333-3333-3333-3333-333333333333\n"
        "Имя: Товары\n"
    )
    d = _lint("Товары.yaml", content, "yaml/builtin-property-name")
    assert d == []


def test_crlf_positions_stable():
    content = _КАРТОЧКА.format(prop="Заголовок").replace("\n", "\r\n")
    d = _lint("Карточка1.yaml", content, "yaml/builtin-property-name")
    assert len(d) == 1 and (d[0].line, d[0].col) == (8, 14)
