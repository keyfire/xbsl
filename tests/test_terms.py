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
