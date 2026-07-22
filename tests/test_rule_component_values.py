"""Checks of the yaml/unknown-enum-value rule (a component property value vs the ui schema).

The schema is written into a temporary data root, so the tests need no generated Element
data and run in a public checkout as well.
"""

import json

import pytest

from xbsl import dataset, engine
from xbsl.cli import discover
from xbsl.rules import component_values

_RULE = "yaml/unknown-enum-value"
_VER = "9.9.9+0"
_SCHEMA = {
    "meta": {"source": "docs", "element_version": _VER, "tool": "extract_uischema", "count": 2},
    "components": {
        "КарточкаАкме": {
            "package": "Стд::Интерфейс::ОбщиеКомпоненты",
            "props": {
                # purely enumerated: every union member is an enumeration or the literal Авто
                "ВидОтображения": {"types": ["Авто", "ВидВиджета"], "enum": ["Карточка", "Баннер"]},
                # a real type among the members - the value may be anything
                "Заголовок": {
                    "types": ["Авто", "ВидВиджета", "Строка"], "enum": ["Карточка", "Баннер"],
                },
                "ПриНажатии": {"event": "(КарточкаАкме, СобытиеПриНажатии)->ничто"},
                "Значение": {"types": ["Объект"]},
            },
        },
        "ГруппаАкме": {
            "package": "Стд::Интерфейс",
            "props": {
                "Выравнивание": {
                    "types": ["Авто", "ВидГраницы"], "enum": ["Сплошная", "Пунктирная"],
                },
            },
        },
    },
    "enums": {
        "ВидВиджета": {"package": "Стд::Интерфейс", "values": ["Карточка", "Баннер"]},
        "ВидГраницы": {"package": "Стд::Интерфейс", "values": ["Сплошная", "Пунктирная"]},
    },
}


@pytest.fixture
def ui_root(tmp_path):
    """A data root holding the schema above; the rule reads it as if it were real."""
    root = tmp_path / "data"
    ver_dir = root / _VER
    ver_dir.mkdir(parents=True)
    (ver_dir / "uischema.json").write_text(
        json.dumps(_SCHEMA, ensure_ascii=False), encoding="utf-8"
    )
    (root / "index.json").write_text(
        json.dumps({"available": [_VER], "default": _VER}), encoding="utf-8"
    )
    dataset.set_data_root(root)
    component_values._enumerated_props.cache_clear()
    component_values._object_props.cache_clear()
    yield root
    dataset.set_data_root(None)
    component_values._enumerated_props.cache_clear()
    component_values._object_props.cache_clear()


@pytest.fixture
def no_data(tmp_path):
    """An empty data root: no ui schema - the public-checkout degradation."""
    root = tmp_path / "empty"
    root.mkdir()
    dataset.set_data_root(root)
    component_values._enumerated_props.cache_clear()
    component_values._object_props.cache_clear()
    yield
    dataset.set_data_root(None)
    component_values._enumerated_props.cache_clear()
    component_values._object_props.cache_clear()


def _run(tmp_path, text, name="Ф.yaml"):
    src = tmp_path / "src"
    src.mkdir(exist_ok=True)
    (src / name).write_text(text, encoding="utf-8")
    return engine.run(discover([str(src)]), select={_RULE})


def _has(diags):
    return any(d.rule_id == _RULE for d in diags)


def _form(body):
    return "ВидЭлемента: КомпонентИнтерфейса\nИмя: Ф\nСодержимое:\n    -\n" + body


def test_value_outside_the_enumeration_flagged(tmp_path, ui_root):
    d = _run(tmp_path, _form("        Тип: КарточкаАкме\n        ВидОтображения: Плитка\n"))
    assert len(d) == 1 and d[0].rule_id == _RULE
    assert d[0].severity.name == "ERROR"
    assert "Плитка" in d[0].message and "Баннер, Карточка" in d[0].message
    assert (d[0].line, d[0].col) == (6, 25)


def test_value_from_the_enumeration_not_flagged(tmp_path, ui_root):
    d = _run(tmp_path, _form("        Тип: КарточкаАкме\n        ВидОтображения: Баннер\n"))
    assert not _has(d)


def test_literal_auto_not_flagged(tmp_path, ui_root):
    d = _run(tmp_path, _form("        Тип: КарточкаАкме\n        ВидОтображения: Авто\n"))
    assert not _has(d)


def test_property_with_a_real_type_member_not_flagged(tmp_path, ui_root):
    # Заголовок accepts Строка too - any value is legal
    d = _run(tmp_path, _form("        Тип: КарточкаАкме\n        Заголовок: Что угодно\n"))
    assert not _has(d)


def test_binding_not_flagged(tmp_path, ui_root):
    d = _run(
        tmp_path,
        _form("        Тип: КарточкаАкме\n        ВидОтображения: =ЭтоМобильный()?1:2\n"),
    )
    assert not _has(d)


def test_qualified_value_not_flagged(tmp_path, ui_root):
    # the enumeration spelled out: ВидВиджета.Баннер
    d = _run(
        tmp_path, _form("        Тип: КарточкаАкме\n        ВидОтображения: ВидВиджета.Баннер\n")
    )
    assert not _has(d)


def test_unknown_component_not_judged(tmp_path, ui_root):
    # a project component of the same shape: its properties are its own
    d = _run(tmp_path, _form("        Тип: МояКарточка\n        ВидОтображения: Плитка\n"))
    assert not _has(d)


def test_generic_component_head_is_used(tmp_path, ui_root):
    d = _run(
        tmp_path, _form("        Тип: КарточкаАкме<Строка>\n        ВидОтображения: Плитка\n")
    )
    assert len(d) == 1


def test_event_property_not_judged(tmp_path, ui_root):
    d = _run(tmp_path, _form("        Тип: КарточкаАкме\n        ПриНажатии: МойОбработчик\n"))
    assert not _has(d)


def test_block_scalar_not_scanned(tmp_path, ui_root):
    d = _run(
        tmp_path,
        "ВидЭлемента: КомпонентИнтерфейса\nИмя: Ф\nОписание: |\n"
        "    Тип: КарточкаАкме\n    ВидОтображения: Плитка\n",
    )
    assert not _has(d)


def test_structural_file_not_scanned(tmp_path, ui_root):
    d = _run(
        tmp_path, "Имя: Проект\nТип: КарточкаАкме\nВидОтображения: Плитка\n", name="Проект.yaml"
    )
    assert not _has(d)


def test_two_nodes_told_apart(tmp_path, ui_root):
    d = _run(
        tmp_path,
        "ВидЭлемента: КомпонентИнтерфейса\nИмя: Ф\nСодержимое:\n"
        "    -\n        Тип: КарточкаАкме\n        ВидОтображения: Баннер\n"
        "    -\n        Тип: КарточкаАкме\n        ВидОтображения: Плитка\n",
    )
    assert len(d) == 1 and d[0].line == 9


def test_different_components_have_own_value_sets(tmp_path, ui_root):
    # Сплошная is legal for ГруппаАкме.Выравнивание and unknown to КарточкаАкме.ВидОтображения
    d = _run(
        tmp_path,
        "ВидЭлемента: КомпонентИнтерфейса\nИмя: Ф\nСодержимое:\n"
        "    -\n        Тип: ГруппаАкме\n        Выравнивание: Сплошная\n"
        "    -\n        Тип: КарточкаАкме\n        ВидОтображения: Сплошная\n",
    )
    assert len(d) == 1 and d[0].line == 9


def test_without_ui_schema_silent(tmp_path, no_data):
    d = _run(tmp_path, _form("        Тип: КарточкаАкме\n        ВидОтображения: Плитка\n"))
    assert not _has(d)


# --- yaml/no-expression-in-literal (needs no schema at all) --------------------------------

_LITERAL_RULE = "yaml/no-expression-in-literal"


def _run_literal(tmp_path, text, name="Ф.yaml"):
    src = tmp_path / "lit"
    src.mkdir(exist_ok=True)
    (src / name).write_text(text, encoding="utf-8")
    return engine.run(discover([str(src)]), select={_LITERAL_RULE})


def _form_with_font(value):
    return (
        "ВидЭлемента: КомпонентИнтерфейса\nИмя: Ф\nСодержимое:\n"
        "    -\n        Тип: Надпись\n        Имя: Текст\n"
        "        Шрифт:\n            Тип: АбсолютныйШрифт\n"
        f"            Размер: {value}\n"
    )


def test_binding_inside_font_flagged(tmp_path):
    d = _run_literal(tmp_path, _form_with_font("=Мобильный?28:40"))
    assert len(d) == 1 and d[0].rule_id == _LITERAL_RULE
    assert d[0].severity.name == "ERROR"
    assert "Шрифт: =Выражение" in d[0].message
    assert (d[0].line, d[0].col) == (9, 21)


def test_literal_value_inside_font_not_flagged(tmp_path):
    assert not _run_literal(tmp_path, _form_with_font("13"))


def test_any_property_of_a_literal_type_is_judged(tmp_path):
    # the restriction is about the nesting, not about Размер
    d = _run_literal(
        tmp_path,
        "ВидЭлемента: КомпонентИнтерфейса\nИмя: Ф\nСодержимое:\n"
        "    -\n        Тип: Надпись\n        Шрифт:\n"
        "            Тип: АбсолютныйШрифт\n            Полужирный: =Истина\n",
    )
    assert len(d) == 1 and "Полужирный" in d[0].message


def test_binding_on_the_whole_object_not_flagged(tmp_path):
    # computing the whole object is the way out, not an error
    d = _run_literal(
        tmp_path,
        "ВидЭлемента: КомпонентИнтерфейса\nИмя: Ф\nСодержимое:\n"
        "    -\n        Тип: Надпись\n        Шрифт: =ШрифтНадписи()\n",
    )
    assert not d


def test_binding_inside_colour_flagged(tmp_path):
    d = _run_literal(
        tmp_path,
        "ВидЭлемента: КомпонентИнтерфейса\nИмя: Ф\nСодержимое:\n"
        "    -\n        Тип: Группа\n        ЦветФона:\n"
        "            Тип: АбсолютныйЦвет\n            Красный: =10\n            Зеленый: 20\n",
    )
    assert len(d) == 1 and "ЦветФона: =Выражение" in d[0].message


def test_binding_inside_a_component_node_not_flagged(tmp_path):
    # bindings inside ordinary components and commands are legal and common
    d = _run_literal(
        tmp_path,
        "ВидЭлемента: КомпонентИнтерфейса\nИмя: Ф\nСодержимое:\n"
        "    -\n        Тип: ОбычнаяКоманда\n        Видимость: =МожноРедактировать\n",
    )
    assert not d


def test_type_key_itself_not_judged(tmp_path):
    d = _run_literal(
        tmp_path,
        "ВидЭлемента: КомпонентИнтерфейса\nИмя: Ф\nСодержимое:\n"
        "    -\n        Тип: Надпись\n        Шрифт:\n"
        "            Тип: АбсолютныйШрифт\n            Размер: 13\n",
    )
    assert not d


def test_structural_file_not_scanned_literal(tmp_path):
    d = _run_literal(
        tmp_path, "Имя: Проект\nШрифт:\n    Тип: АбсолютныйШрифт\n    Размер: =40\n",
        name="Проект.yaml",
    )
    assert not d


# --- yaml/bare-object-value ---------------------------------------------------------------

_BARE_RULE = "yaml/bare-object-value"


def _run_bare(tmp_path, body, name="Ф.yaml"):
    src = tmp_path / "bare"
    src.mkdir(exist_ok=True)
    (src / name).write_text(
        "ВидЭлемента: КомпонентИнтерфейса\nИмя: Ф\nСодержимое:\n"
        "    -\n        Тип: КарточкаАкме\n" + body,
        encoding="utf-8",
    )
    return engine.run(discover([str(src)]), select={_BARE_RULE})


def test_bare_word_flagged(tmp_path, ui_root):
    d = _run_bare(tmp_path, "        Значение: Титул\n")
    assert len(d) == 1 and d[0].rule_id == _BARE_RULE
    assert d[0].severity.name == "ERROR"
    assert '"Титул"' in d[0].message and "=Титул" in d[0].message
    assert (d[0].line, d[0].col) == (6, 19)


def test_quoted_value_not_flagged(tmp_path, ui_root):
    assert not _run_bare(tmp_path, '        Значение: "Титул"\n')


def test_binding_not_flagged_bare(tmp_path, ui_root):
    assert not _run_bare(tmp_path, "        Значение: =Титул\n")


def test_localized_string_ref_not_flagged(tmp_path, ui_root):
    # '$' opens the documented localized-string identifier; the platform's editor writes these
    assert not _run_bare(tmp_path, "        Значение: $ЛокализованныеСтроки.Заголовок\n")


def test_qualified_localized_string_ref_not_flagged(tmp_path, ui_root):
    assert not _run_bare(
        tmp_path, "        Значение: $Акме::ЛокализованныеСтроки.Заголовок\n"
    )


def test_number_not_flagged(tmp_path, ui_root):
    # yaml reads it as a number, not a word
    assert not _run_bare(tmp_path, "        Значение: 42\n")


def test_boolean_not_flagged(tmp_path, ui_root):
    assert not _run_bare(tmp_path, "        Значение: true\n")


def test_non_object_property_not_judged(tmp_path, ui_root):
    # ВидОтображения is an enumeration, not Объект - another rule's business
    assert not _run_bare(tmp_path, "        ВидОтображения: Баннер\n")


def test_nested_object_value_not_flagged(tmp_path, ui_root):
    # a mapping under the property is a literal with its type spelled out
    d = _run_bare(
        tmp_path,
        "        Значение:\n            Тип: Строка\n            Значение: \"Текст\"\n",
    )
    assert not d


def test_without_ui_schema_silent_bare(tmp_path, no_data):
    assert not _run_bare(tmp_path, "        Значение: Титул\n")
