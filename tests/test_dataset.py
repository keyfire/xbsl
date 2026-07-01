"""Проверки версионированного доступа к данным (самодостаточность, выбор версии)."""

import pytest

from xbsllint import dataset


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
