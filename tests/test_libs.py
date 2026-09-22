# -*- coding: utf-8 -*-
"""Types of attached libraries: parsing Проект.yaml, locating the archive, reading global names."""
import os
import shutil
import zipfile
from pathlib import Path

import pytest

from xbsl import engine, libs
from xbsl.cli import discover
from xbsl.lexer import _IDENT_RE

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


# A local, ignored directory with genuine library deliveries. It deliberately has no default:
# public test runs must never need or name a vendor archive.
_XLIB_CORPUS = os.environ.get("XBSL_XLIB_CORPUS")


def _real_xlib_paths(root):
    root = Path(root)
    if root.is_file():
        return [root] if root.suffix == ".xlib" else []
    return root.rglob("*.xlib")


def _actual_library_cases(root):
    """Real archives with one global and one internal XBSL identifier type each."""
    for archive_path in sorted(_real_xlib_paths(root), key=lambda path: str(path).casefold()):
        try:
            with zipfile.ZipFile(archive_path) as archive:
                assembly = libs.yaml.load(
                    archive.read("Assembly.yaml").decode("utf-8-sig"), Loader=libs._LOADER,
                )
                if not isinstance(assembly, dict):
                    continue
                vendor = libs._first(assembly, libs._VENDOR_KEYS)
                name = libs._first(assembly, libs._NAME_KEYS)
                if not isinstance(vendor, str) or not isinstance(name, str) or not vendor or not name:
                    continue
                prefix = f"{vendor}-{name}-"
                if not archive_path.name.startswith(prefix):
                    continue
                version = archive_path.name[len(prefix) : -len(".xlib")]
                if not version:
                    continue
                global_names, internal_names = set(), set()
                for entry in archive.namelist():
                    if (
                        not entry.endswith(".yaml")
                        or entry.count("/") < 3
                        or entry.rsplit("/", 1)[-1] in libs._NON_ELEMENT_FILES
                    ):
                        continue
                    try:
                        values = libs.yaml.load(
                            archive.read(entry).decode("utf-8-sig"), Loader=libs._LOADER,
                        )
                    except (libs.yaml.YAMLError, UnicodeDecodeError):
                        continue
                    if not isinstance(values, dict) or not libs._first(values, libs._KIND_KEYS):
                        continue
                    element = libs._first(values, libs._NAME_KEYS)
                    if not isinstance(element, str) or not _IDENT_RE.fullmatch(element):
                        continue
                    if libs._first(values, libs._SCOPE_KEYS) in libs._global_scopes():
                        global_names.add(element)
                    else:
                        internal_names.add(element)
        except (KeyError, OSError, UnicodeDecodeError, libs.yaml.YAMLError, zipfile.BadZipFile):
            continue
        global_names -= internal_names
        if global_names and internal_names:
            yield archive_path, vendor, name, version, sorted(global_names), sorted(internal_names)


def _архив(path, элементы):
    """A synthetic .xlib: {path inside the subsystem: (name, kind, visibility scope)}."""
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


@pytest.mark.needs_data
def test_declared_libraries_ru_and_en():
    assert libs.declared_libraries(ПРОЕКТ) == [("acme", "ТаймерЛиб", "9.0.2")]
    assert libs.declared_libraries(PROJECT_EN) == [("acme", "QueueLib", "1.0.0")]
    # a regular project element declares no libraries - the fast path with no yaml parsing
    assert libs.declared_libraries("ВидЭлемента: Справочник\nИмя: Товар\n") == []


def test_archive_global_types_only(tmp_path):
    архив = _архив(tmp_path / "acme-ТаймерЛиб-9.0.2.xlib", ЭЛЕМЕНТЫ)
    имена = libs.archive_global_types(архив)
    # only the global scope is visible; ВПодсистеме is the library's internal business,
    # and the subsystem describes a namespace and is not a type
    assert имена == {"ОписаниеАдресата", "Интерфейс"}


def test_archive_not_found_and_broken(tmp_path):
    assert libs.find_archive(tmp_path, "acme", "ТаймерЛиб", "9.0.2") is None
    битый = tmp_path / "acme-ТаймерЛиб-9.0.2.xlib"
    битый.write_text("не архив", encoding="utf-8")
    assert libs.archive_global_types(битый) == frozenset()


def test_archive_found_above_sources(tmp_path):
    # the delivery layout: the archive next to the source root, the descriptor two levels deeper
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
    # no archive nearby - nothing to judge the library types by, behavior stays as before
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


@pytest.mark.needs_data
@pytest.mark.skipif(
    not _XLIB_CORPUS,
    reason="архивы недоступны (задайте XBSL_XLIB_CORPUS)",
)
def test_real_xlib_global_type_is_known_but_internal_type_is_not_exported(tmp_path):
    """A vendor archive remains outside git while its real visibility contract is checked."""
    root, archive, global_type, internal_type, project = _real_xlib_control(tmp_path)
    _assert_real_xlib_read(root, archive, global_type, internal_type, project)


@pytest.mark.needs_data
@pytest.mark.skipif(
    not _XLIB_CORPUS,
    reason="архивы недоступны (задайте XBSL_XLIB_CORPUS)",
)
def test_real_xlib_reader_regression_fails_instead_of_skipping(tmp_path, monkeypatch):
    """The assertion stays active when archive_global_types cannot expose a library."""
    root, archive, global_type, internal_type, project = _real_xlib_control(tmp_path)
    monkeypatch.setattr(libs, "archive_global_types", lambda path: frozenset())
    with pytest.raises(AssertionError):
        _assert_real_xlib_read(root, archive, global_type, internal_type, project)


def _real_xlib_control(tmp_path):
    """First deterministic real control pair unknown without its delivery archive."""
    for number, case in enumerate(_actual_library_cases(_XLIB_CORPUS), start=1):
        archive, vendor, name, version, global_types, internal_types = case
        for global_number, global_type in enumerate(global_types, start=1):
            for internal_number, internal_type in enumerate(internal_types, start=1):
                root = tmp_path / f"{number}-{global_number}-{internal_number}"
                project = _project_without_real_xlib(
                    root, vendor, name, version, global_type, internal_type,
                )
                if project is not None:
                    return root, archive, global_type, internal_type, project
    pytest.fail(
        "XBSL_XLIB_CORPUS задан, но в нем нет архива с типами, которые проверяются "
        "на обеих поверхностях без совпадения со stdlib или проектом",
    )


def _project_without_real_xlib(root, vendor, name, version, global_type, internal_type):
    """A disposable dependency project only when both archive types are unknown without it."""
    root.mkdir()
    project = root / "verification" / "Site"
    project.mkdir(parents=True)
    descriptor = {
        "Ид": "f25543fb-c726-496e-9af5-71f61527e97c",
        "Имя": "Site",
        "Поставщик": vendor,
        "Библиотеки": [{"Версия": version, "Имя": name, "Поставщик": vendor}],
    }
    (project / "Проект.yaml").write_text(
        libs.yaml.safe_dump(descriptor, allow_unicode=True, sort_keys=False), encoding="utf-8",
    )
    (project / "М.yaml").write_text(
        "ВидЭлемента: ОбщийМодуль\n"
        "Ид: 33333333-3333-3333-3333-333333333333\n"
        "Имя: М\n",
        encoding="utf-8",
    )
    (project / "М.xbsl").write_text(
        f"метод Получить(): {global_type}\n    возврат новый {internal_type}()\n;\n",
        encoding="utf-8",
    )
    (project / "Проверка.yaml").write_text(
        libs.yaml.safe_dump(
            {
                "ВидЭлемента": "Структура",
                "Ид": "44444444-4444-4444-4444-444444444444",
                "Имя": "Проверка",
                "Поля": [{"Имя": "Глобальный", "Тип": global_type}, {"Имя": "Внутренний", "Тип": internal_type}],
            },
            allow_unicode=True,
            sort_keys=False,
        ),
        encoding="utf-8",
    )

    without_archive = engine.run(
        discover([str(project)]), select={"code/unknown-type", "yaml/unknown-type"},
    )
    expected_without_archive = {
        ("М.xbsl", "code/unknown-type"): {global_type, internal_type},
        ("Проверка.yaml", "yaml/unknown-type"): {global_type, internal_type},
    }
    if not _matches_unknown_types(without_archive, expected_without_archive):
        return None
    return project


def _assert_real_xlib_read(root, archive, global_type, internal_type, project):
    """The global type becomes known from the copied genuine archive, or this assertion fails."""
    shutil.copy2(archive, root / archive.name)

    # The global type must become known only after the genuine archive is available. Do not
    # treat a failure here as an unsuitable candidate: it is the behavior under test.
    with_archive = engine.run(
        discover([str(project)]), select={"code/unknown-type", "yaml/unknown-type"},
    )
    expected_with_archive = {
        ("М.xbsl", "code/unknown-type"): {internal_type},
        ("Проверка.yaml", "yaml/unknown-type"): {internal_type},
    }
    assert _matches_unknown_types(with_archive, expected_with_archive)


def _unknown_types(diagnostics):
    """{(file name, rule): exact unknown type names}, without depending on substrings."""
    result = {}
    for diagnostic in diagnostics:
        before, quote, tail = diagnostic.message.partition("'")
        value, closing_quote, after = tail.partition("'")
        if not before or not quote or not closing_quote or not after:
            return None
        key = Path(diagnostic.path).name, diagnostic.rule_id
        result.setdefault(key, set()).add(value)
    return result


def _matches_unknown_types(diagnostics, expected):
    return _unknown_types(diagnostics) == expected
