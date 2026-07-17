# -*- coding: utf-8 -*-
"""Типы подключённых библиотек: разбор Проект.yaml, поиск архива и чтение глобальных имён."""
import zipfile
from pathlib import Path

import pytest

from xbsl import engine, libs
from xbsl.cli import discover

ПРОЕКТ = """Ид: f25543fb-c726-496e-9af5-71f61527e97c
Имя: Сайт
Поставщик: acme
РежимСовместимости: 9.0
Библиотеки:
    -
        Версия: 9.0.2
        Имя: ТаймерЛиб
        Поставщик: acme
"""

PROJECT_EN = """Id: f25543fb-c726-496e-9af5-71f61527e97c
Name: Site
Libraries:
    -
        Version: 1.0.0
        Name: QueueLib
        Vendor: acme
"""


def _архив(path, элементы):
    """Синтетический .xlib: {путь внутри подсистемы: (имя, вид, областьВидимости)}."""
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("Assembly.yaml", "ManifestVersion: 1.0\nVendor: acme\nName: ТаймерЛиб\n")
        z.writestr("acme/ТаймерЛиб/Проект.yaml", "Ид: 1\nИмя: ТаймерЛиб\n")
        for entry, (имя, вид, область) in элементы.items():
            z.writestr(
                f"acme/ТаймерЛиб/{entry}",
                f"ВидЭлемента: {вид}\nИд: 2\nИмя: {имя}\nОбластьВидимости: {область}\n",
            )
    return path


ЭЛЕМЕНТЫ = {
    "Таймер/Структуры/ОписаниеАдресата.yaml": ("ОписаниеАдресата", "Структура", "Глобально"),
    "Таймер/Структуры/ОписаниеТокена.yaml": ("ОписаниеТокена", "Структура", "ВПодсистеме"),
    "Таймер/Интерфейс.yaml": ("Интерфейс", "ОбщийМодуль", "Глобально"),
    "Таймер/Подсистема.yaml": ("Таймер", "Подсистема", "Глобально"),
}


def test_declared_libraries_ru_and_en():
    assert libs.declared_libraries(ПРОЕКТ) == [("acme", "ТаймерЛиб", "9.0.2")]
    assert libs.declared_libraries(PROJECT_EN) == [("acme", "QueueLib", "1.0.0")]
    # обычный элемент проекта библиотек не объявляет – быстрый путь без разбора yaml
    assert libs.declared_libraries("ВидЭлемента: Справочник\nИмя: Товар\n") == []


def test_archive_global_types_only(tmp_path):
    архив = _архив(tmp_path / "acme-ТаймерЛиб-9.0.2.xlib", ЭЛЕМЕНТЫ)
    имена = libs.archive_global_types(архив)
    # видно только глобальное; ВПодсистеме – внутреннее дело библиотеки,
    # подсистема описывает пространство имён и типом не является
    assert имена == {"ОписаниеАдресата", "Интерфейс"}


def test_archive_not_found_and_broken(tmp_path):
    assert libs.find_archive(tmp_path, "acme", "ТаймерЛиб", "9.0.2") is None
    битый = tmp_path / "acme-ТаймерЛиб-9.0.2.xlib"
    битый.write_text("не архив", encoding="utf-8")
    assert libs.archive_global_types(битый) == frozenset()


def test_archive_found_above_sources(tmp_path):
    # раскладка как у поставки: архив рядом с корнем исходников, дескриптор на два уровня глубже
    _архив(tmp_path / "acme-ТаймерЛиб-9.0.2.xlib", ЭЛЕМЕНТЫ)
    описание = tmp_path / "acme" / "Сайт" / "Проект.yaml"
    описание.parent.mkdir(parents=True)
    описание.write_text(ПРОЕКТ, encoding="utf-8")
    assert libs.project_library_types(описание, ПРОЕКТ) == ["Интерфейс", "ОписаниеАдресата"]


def test_archive_found_from_relative_descriptor(tmp_path, monkeypatch):
    # running the linter from inside the project directory yields a relative descriptor
    # path: the walk up to the archive must not end at cwd ('.'.parent == '.')
    _архив(tmp_path / "acme-ТаймерЛиб-9.0.2.xlib", ЭЛЕМЕНТЫ)
    descriptor = tmp_path / "acme" / "Сайт" / "Проект.yaml"
    descriptor.parent.mkdir(parents=True)
    descriptor.write_text(ПРОЕКТ, encoding="utf-8")
    monkeypatch.chdir(descriptor.parent)
    assert libs.project_library_types(Path("Проект.yaml"), ПРОЕКТ) == [
        "Интерфейс", "ОписаниеАдресата",
    ]


def _проект(tmp_path):
    корень = tmp_path / "acme" / "Сайт"
    корень.mkdir(parents=True)
    (корень / "Проект.yaml").write_text(ПРОЕКТ, encoding="utf-8")
    (корень / "М.xbsl").write_text(
        "метод Ф(): ОписаниеАдресата\n    возврат новый ОписаниеАдресата()\n;\n",
        encoding="utf-8",
    )
    (корень / "М.yaml").write_text(
        "ВидЭлемента: ОбщийМодуль\nИд: 33333333-3333-3333-3333-333333333333\nИмя: М\n",
        encoding="utf-8",
    )
    return корень


@pytest.mark.needs_data
def test_library_type_known_when_archive_present(tmp_path):
    _архив(tmp_path / "acme-ТаймерЛиб-9.0.2.xlib", ЭЛЕМЕНТЫ)
    корень = _проект(tmp_path)
    d = engine.run(discover([str(корень)]), select={"code/unknown-type"})
    assert not [x for x in d if "ОписаниеАдресата" in x.message]


@pytest.mark.needs_data
def test_library_type_unknown_without_archive(tmp_path):
    # архива рядом нет – судить о типах библиотеки не по чему, поведение прежнее
    корень = _проект(tmp_path)
    d = engine.run(discover([str(корень)]), select={"code/unknown-type"})
    assert [x for x in d if "ОписаниеАдресата" in x.message]


@pytest.mark.needs_data
def test_library_type_known_in_yaml(tmp_path):
    _архив(tmp_path / "acme-ТаймерЛиб-9.0.2.xlib", ЭЛЕМЕНТЫ)
    корень = _проект(tmp_path)
    (корень / "С.yaml").write_text(
        "ВидЭлемента: Структура\nИд: 44444444-4444-4444-4444-444444444444\nИмя: С\n"
        "Поля:\n    -\n        Имя: Адресат\n        Тип: ОписаниеАдресата\n",
        encoding="utf-8",
    )
    d = engine.run(discover([str(корень)]), select={"yaml/unknown-type"})
    assert not [x for x in d if "ОписаниеАдресата" in x.message]
