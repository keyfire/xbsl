"""Checks of versioned data access (self-containedness, version selection)."""

import pytest

from xbsl import dataset


def test_default_is_available():
    assert dataset.available_versions()
    assert dataset.default_version() in dataset.available_versions()


def test_load_language_and_stdlib():
    lang = dataset.load_json("language.json")
    assert lang["keywords"]["METHOD"]["forms"]
    std = dataset.load_json("stdlib.json")
    assert "Массив" in std["names"]


def test_data_stamped_with_element_version():
    lang = dataset.load_json("language.json")
    assert lang["meta"]["element_version"] == dataset.default_version()


def test_invalid_version_raises():
    with pytest.raises(dataset.DatasetError):
        dataset.resolve_version("0.0.0-нет-такой")


# --- inheritance expansion (dataset._expand_inherited), no distribution data needed --------

def _own_dataset():
    """A tiny stdlib.json in the own-members form: Наследник extends База extends Объект."""
    return {
        "meta": {"members": "own"},
        "bases": {"Наследник": ["База", "Объект"], "База": ["Объект"], "Объект": []},
        "type_members": {
            "Объект": {"methods": ["ВСтроку"]},
            "База": {"properties": ["Поле"], "methods": ["Метод"]},
            "Наследник": {"properties": ["Своё"]},
        },
        "member_types": {
            "Объект": {"ВСтроку": "Строка"},
            "База": {"Поле": "Число"},
            "Наследник": {"Своё": "Булево"},
        },
    }


def test_expand_inherited_completes_members_by_hierarchy():
    full = dataset._expand_inherited(_own_dataset())["type_members"]
    # Наследник gets its own member plus every ancestor's own.
    assert set(full["Наследник"]["properties"]) == {"Своё", "Поле"}
    assert set(full["Наследник"]["methods"]) == {"Метод", "ВСтроку"}
    assert set(full["База"]["methods"]) == {"Метод", "ВСтроку"}


def test_expand_inherited_completes_member_types():
    full = dataset._expand_inherited(_own_dataset())["member_types"]
    assert full["Наследник"] == {"Своё": "Булево", "Поле": "Число", "ВСтроку": "Строка"}


def test_expand_inherited_keeps_an_overridden_result_type():
    data = _own_dataset()
    data["member_types"]["Наследник"]["ВСтроку"] = "Представление"  # override the object's
    full = dataset._expand_inherited(data)["member_types"]
    assert full["Наследник"]["ВСтроку"] == "Представление"  # own wins over the ancestor's


def test_expand_inherited_leaves_full_datasets_untouched():
    full_form = {
        "meta": {},  # no "members": "own" marker - an older, already-full dataset
        "bases": {"Наследник": ["Объект"]},
        "type_members": {"Наследник": {"properties": ["Своё"]}},
    }
    assert dataset._expand_inherited(full_form)["type_members"] == {"Наследник": {"properties": ["Своё"]}}


# --- bilingual key expansion (dataset._add_english_keys) -----------------------------------

def _ru_only_dataset():
    """A catalog stored under Russian keys only, marked for English expansion."""
    return {
        "meta": {"members": "own", "bilingual_keys": "expand"},
        "bases": {"Запрос": ["Объект"], "Объект": []},
        "type_members": {"Запрос": {"methods": ["Выполнить"]}, "Объект": {"methods": ["ВСтроку"]}},
        "member_types": {"Запрос": {"Выполнить": "РезультатЗапроса"}},
    }


PAIRS = {"Запрос": "Query", "Объект": "Object", "Выполнить": "Execute"}


def test_add_english_keys_copies_the_russian_entry():
    data = dataset._add_english_keys(_ru_only_dataset(), PAIRS)
    assert data["type_members"]["Query"] == data["type_members"]["Запрос"]
    assert data["bases"]["Query"] == ["Объект"]  # bases stay Russian - they are values, not keys
    assert data["member_types"]["Query"] == {"Выполнить": "РезультатЗапроса"}


def test_english_type_inherits_like_the_russian_one():
    # the English keys are added BEFORE the inheritance expansion, so Query inherits too
    full = dataset._expand_inherited(dataset._add_english_keys(_ru_only_dataset(), PAIRS))
    assert set(full["type_members"]["Query"]["methods"]) == {"Выполнить", "ВСтроку"}
    assert full["type_members"]["Query"] == full["type_members"]["Запрос"]


def test_bilingual_expansion_skipped_without_marker_or_terms():
    no_marker = _ru_only_dataset()
    no_marker["meta"].pop("bilingual_keys")
    assert "Query" not in dataset._add_english_keys(no_marker, PAIRS)["type_members"]
    # marker present but terms.json absent (empty pairs) - Russian still works, no crash
    assert "Query" not in dataset._add_english_keys(_ru_only_dataset(), {})["type_members"]
