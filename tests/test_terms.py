"""Тесты пар русского и английского написания (terms.json).

Данные извлекаются из дистрибутива, поэтому в клоне без них модуль обязан молча
деградировать до русского написания - это проверяется отдельно.
"""

from __future__ import annotations

import pytest

from xbsl import terms


@pytest.fixture(autouse=True)
def _clear_cache():
    terms._cache = None
    yield
    terms._cache = None


needs_data = pytest.mark.skipif(
    not terms._terms().get("types"), reason="нет данных Элемента (terms.json)"
)


@needs_data
def test_pairs_come_from_the_platform():
    assert terms.english("Запрос", "types") == "Query"
    assert terms.english("ОбластьВидимости", "properties") == "VisibilityScope"
    assert terms.english("ВПроекте", "enums") == "InProject"


@needs_data
def test_role_decides_the_spelling():
    """Одно слово в разных ролях переводится по-разному - секции их разделяют.

    `Ссылка` как свойство - Link, а как часть фасета типа - Reference; общая карта
    без ролей дала бы в одном из случаев неверное имя.
    """
    assert terms.english("Ссылка", "properties") == "Link"
    assert terms.english("ДвоичныйОбъект.Ссылка", "facets") == "BinaryObject.Reference"


@needs_data
def test_name_without_english_stays_russian():
    # ТипФормы объявлен в метамодели только с ru - выдумывать написание нельзя
    assert terms.english("ТипФормы", "properties") is None
    assert terms.forms("ТипФормы", "properties") == ("ТипФормы",)


@needs_data
def test_key_forms_falls_back_to_type_names_and_extras():
    # `Версия` объявлена типом, а не свойством; `Vendor` знает только манифест .xlib
    assert terms.key_forms("Версия") == ("Версия", "Version")
    assert terms.key_forms("Поставщик", extra=("Vendor",)) == ("Поставщик", "Vendor")


def test_without_data_only_russian(monkeypatch):
    monkeypatch.setattr(terms.dataset, "load_json", lambda name: (_ for _ in ()).throw(OSError))
    terms._cache = None
    assert terms.english("Запрос", "types") is None
    assert terms.forms("Запрос", "types") == ("Запрос",)
    assert terms.key_forms("Имя") == ("Имя",)


def test_unknown_section_is_not_an_error():
    assert terms.english("Запрос", "нет-такой-секции") is None


# --- the manager of an element kind, spelled by the owner the data names ----------------------


def _data_root(tmp_path, name: str, full: dict):
    """A data root of one version whose compiler dictionary is `full`."""
    import json

    root = tmp_path / name
    version = root / "1.0.0"
    version.mkdir(parents=True)
    (version / "terms_full.json").write_text(json.dumps(full, ensure_ascii=False), encoding="utf-8")
    (root / "index.json").write_text(
        json.dumps({"available": ["1.0.0"], "default": "1.0.0"}), encoding="utf-8")
    return root


_MEMBERS = {
    "AcmeRightManager": {"Проверить": "Check"},
    "AcmeVerifier": {"Проверить": "Verify"},
}


def test_a_manager_member_is_spelled_by_the_owner_the_data_names(tmp_path):
    """`Проверить` is Check on the manager of one kind and Verify elsewhere: only the owner the
    data joins to the kind answers, and a kind the data joins to nothing answers nothing."""
    root = _data_root(tmp_path, "with", {
        "members": _MEMBERS, "manager_owners": {"АкмеПраво": "AcmeRightManager"},
    })
    terms.dataset.set_data_root(root)
    try:
        assert terms.manager_member_english("АкмеПраво", "Проверить") == "Check"
        assert terms.manager_member_english("АкмеПраво", "Записать") is None
        assert terms.manager_member_english("Справочник", "Проверить") is None
        assert terms.manager_member_english("", "Проверить") is None
    finally:
        terms.dataset.set_data_root(None)


def test_data_without_the_manager_section_answers_nothing_and_is_read_afresh(tmp_path):
    """Data extracted before the section existed keeps the call a gap; switching the root drops
    the table read from the previous one."""
    with_section = _data_root(tmp_path, "with", {
        "members": _MEMBERS, "manager_owners": {"АкмеПраво": "AcmeRightManager"},
    })
    without = _data_root(tmp_path, "without", {"members": _MEMBERS})
    try:
        terms.dataset.set_data_root(with_section)
        assert terms.manager_member_english("АкмеПраво", "Проверить") == "Check"
        terms.dataset.set_data_root(without)
        assert terms.manager_member_english("АкмеПраво", "Проверить") is None
    finally:
        terms.dataset.set_data_root(None)
