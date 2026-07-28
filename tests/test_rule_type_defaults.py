"""A structure field must not rely on a default value its type does not have.

code/collection-field-needs-req reads the `type_ctors` section of the catalog. The catalog is
PINNED here instead of being read from the machine: the tests then describe the rule, not the
vintage of the generated data.

The lexer still needs language.json, so the module is data-dependent (tests/conftest.py).
The sources under test are XBSL fixtures, so they are Russian - that is the language of the
samples, not of the file.
"""

from pathlib import Path

import pytest

from xbsl import engine
from xbsl.rules import type_defaults

FIELD_RULE = "code/collection-field-needs-req"

#: What the distribution says about the types used below (see xbsl/extract/stdlib.py). Keys
#: are the Russian spellings the catalog stores, plus the English twin the loader adds.
CATALOG = {
    "type_ctors": {
        "Массив": "empty",
        "Соответствие": "empty",
        "ЧитаемыйМассив": "args",
        "ReadableArray": "args",
        "Строка": "args",
        "String": "args",
    },
}


@pytest.fixture
def catalog(monkeypatch):
    """Pin the type catalog for the duration of one test."""
    monkeypatch.setattr(type_defaults, "_catalog", lambda: CATALOG)
    type_defaults._ctor_kinds.cache_clear()
    yield
    type_defaults._ctor_kinds.cache_clear()


def _run(tmp_path: Path, code: str, rule: str) -> list:
    module = tmp_path / "Модуль.xbsl"
    module.write_text(code, encoding="utf-8")
    return engine.run([module], select={rule})


# --- the field rule ------------------------------------------------------------------------

def test_read_only_collection_field_is_flagged(catalog, tmp_path):
    """The case the rule was written for: the type has no argument-less constructor."""
    diags = _run(tmp_path, "структура Тело\n    пер texts: ЧитаемыйМассив<Строка>\n;\n", FIELD_RULE)
    assert len(diags) == 1
    assert diags[0].line == 2 and "texts" in diags[0].message
    assert "обз пер texts" in diags[0].message


def test_english_spelling_of_the_same_type_is_flagged(catalog, tmp_path):
    diags = _run(tmp_path, "структура Тело\n    пер texts: ReadableArray<Строка>\n;\n", FIELD_RULE)
    assert len(diags) == 1


def test_advice_follows_the_language_of_the_module(catalog, tmp_path):
    """An English module is advised of the keyword ITS sources use, not of the other form."""
    module = tmp_path / "Module.xbsl"
    module.write_text("structure Body\n    var texts: ReadableArray<String>\n;\n", encoding="utf-8")
    diags = engine.run([module], select={FIELD_RULE})
    assert len(diags) == 1
    assert "req var texts" in diags[0].message


def test_collection_with_an_empty_constructor_is_not_flagged(catalog, tmp_path):
    """A collection with an argument-less constructor does have a default value."""
    code = (
        "структура Тело\n"
        "    пер Список: Массив<Строка>\n"
        "    пер Карта: Соответствие<Строка, Число>\n"
        ";\n"
    )
    assert _run(tmp_path, code, FIELD_RULE) == []


@pytest.mark.parametrize("field", [
    "обз пер texts: ЧитаемыйМассив<Строка>",  # required by the constructor
    "пер texts: ЧитаемыйМассив<Строка>?",  # nullable - the default is Undefined
    "пер texts: ЧитаемыйМассив<Строка> = <Строка>[]",  # an explicit initializer
    "пер texts: ЧитаемыйМассив<Строка>|Неопределено",  # a union is not judged
])
def test_legal_field_forms_are_silent(catalog, tmp_path, field):
    assert _run(tmp_path, f"структура Тело\n    {field}\n;\n", FIELD_RULE) == []


def test_plain_type_name_is_left_alone(catalog, tmp_path):
    """The narrowing: String has an argument-taking constructor and a default value both."""
    assert _run(tmp_path, "структура Тело\n    пер Имя: Строка\n;\n", FIELD_RULE) == []


def test_local_variable_is_not_a_structure_field(catalog, tmp_path):
    code = "метод Ф()\n    пер texts: ЧитаемыйМассив<Строка>\n;\n"
    assert _run(tmp_path, code, FIELD_RULE) == []


# --- no data, no findings -------------------------------------------------------------------

def test_the_rule_is_silent_without_the_catalog_section(monkeypatch, tmp_path):
    """A dataset generated before type_ctors existed leaves the rule mute."""
    monkeypatch.setattr(type_defaults, "_catalog", lambda: {"names": []})
    type_defaults._ctor_kinds.cache_clear()
    try:
        code = "структура Тело\n    пер texts: ЧитаемыйМассив<Строка>\n;\n"
        assert _run(tmp_path, code, FIELD_RULE) == []
    finally:
        type_defaults._ctor_kinds.cache_clear()
