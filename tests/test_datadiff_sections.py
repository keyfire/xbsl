"""Every section of the data reaches the version diff (xbsl/datadiff.py).

Two neighbouring builds once differed in two places - a module of an element lost a handler, and
a dozen help pages got another text - while `xbsl data-diff` said "no changes" in every section:
the handler table was a stdlib section the diff never read, and pages were compared by id and
title alone. The tests build small data roots in a temporary directory and read them the way the
command does; the rest compare the loaded structures directly. Versions and names are invented.
"""

from __future__ import annotations

import copy
import json
import sqlite3
from pathlib import Path

import pytest

from xbsl import datadiff, dataset, i18n

OLD, NEW = "1.2.3+4", "1.2.3+5"

#: A small catalog of one version: a collection hierarchy with signatures, a component, the
#: handler tables and the per-type sections - every test changes one thing in a copy of it.
STDLIB = {
    "names": ["Array", "Collection", "Коллекция", "Массив"],
    "object_members": {"Справочник": ["Объект", "Ссылка"]},
    "component_props": {"Компонент": ["Видимость"], "Кнопка": ["Видимость", "Заголовок"]},
    "retired_components": {"СтараяГруппа": {
        "term": {"ru": "СтараяГруппа", "en": "OldGroup"}, "to": 8.0,
        "properties": [{"term": {"ru": "Заголовок", "en": "Title"}, "type": "Std::String"}]}},
    "component_from": {"Карта": "1.0"},
    "module_handlers": {"Компонент": [{"ru": "ПослеСоздания", "en": "AfterCreate"}]},
    "element_module_handlers": {"Справочник": {
        "": {"handlers": [{"ru": "ВычислитьРазрешения", "en": "ComputePermissions"}]},
        "Объект": {"handlers": [{"ru": "ПриЗаписи", "en": "OnWrite"},
                                {"ru": "ПриКопировании", "en": "OnCopy"}]},
    }},
    "type_members": {
        "Объект": {"methods": ["ВСтроку"]},
        "Коллекция": {"methods": ["Добавить", "Количество"]},
        "Массив": {"methods": ["Вставить"]},
        "Компонент": {"properties": ["Видимость"]},
        "Кнопка": {"properties": ["Заголовок"]},
    },
    "globals": ["Мин"],
    "global_availability": {"Мин": "КлиентИСервер"},
    "type_availability": {"Коллекция": "КлиентИСервер", "Массив": "КлиентИСервер"},
    "manager_members": {"Справочник": {"methods": ["Найти"]}},
    "manager_member_types": {"Справочник": {"Найти": "{}.Ссылка?"}},
    "member_types": {"Коллекция": {"Количество": "Число"}},
    "checked_return_methods": {"Коллекция": ["Добавить"], "Массив": ["Добавить"]},
    "member_signatures": {
        "Коллекция": {"Добавить": ["Добавить(Элемент: Т)"], "Количество": ["Количество(): Число"]},
        "Массив": {"Вставить": ["Вставить(Индекс: Число, Элемент: Т)"]},
    },
    "bases": {"Коллекция": ["Объект"], "Массив": ["Коллекция", "Объект"],
              "Кнопка": ["Компонент", "Объект"], "Компонент": ["Объект"]},
    "generic_bases": {"Массив": {"Коллекция": ["Т"]}},
    "type_ctors": {"Коллекция": "none", "Массив": "empty"},
    "type_params": {"Коллекция": ["Т"], "Массив": ["Т"]},
    "type_param_variance": {"Коллекция": ["out"]},
    "member_type_params": {"Коллекция": {"Преобразовать": ["Р"]}},
    "deprecated_members": {"Коллекция": {"Добавить": [
        {"signature": "Добавить(Элемент: Т)"},
        {"signature": "Добавить(Элемент: Т, Флаг: Булево)", "deprecated": True}]}},
}
FILES = {
    "language.json": {"keywords": {"IF": {"forms": ["if", "если"]}}, "operators": ["+"],
                      "token_ids": {"RULE_IF_KW": 5}},
    "stdlib.json": STDLIB,
    "metamodel.json": {"classes": {"CatalogModel": {"props": {"Имя": {"type": "str"}},
                                                    "ext": ["Base"]}},
                       "enums": {"Вид": ["А"]}, "vid2class": {"Справочник": "CatalogModel"},
                       "vetted": ["Справочник"], "common": ["Имя"]},
    "uischema.json": {"components": {"Кнопка": {"package": "Стд::Интерфейс", "props": {},
                                                "yaml_props": ["Имя"]}},
                      "enums": {"ВидКнопки": {"package": "Стд::Интерфейс", "values": ["А", "Б"]}},
                      "type_params": {"Кнопка": {"params": ["Т"]}}},
    "terms.json": {"types": {"Массив": "Array"}, "kinds": {"Справочник": "Catalog"},
                   "query_reserved_english_only": ["NULL"]},
    "uiterms.json": {"packages": {"Стд": "Std"}, "enum_values": {"ВидКнопки": {"А": "A"}},
                     "member_names": {"Array": {"Вставить": "Insert"}}},
    "terms_full.json": {"members": {"Array": {"Вставить": "Insert"}},
                        "common": {"Вставить": "Insert"}},
}
#: (id, kind, title, html) of the help pages.
PAGES = [
    ("std/array", "type", "Массив", "<h1>Массив</h1><p>A collection.</p>"),
    ("std/map", "type", "Соответствие", "<h1>Соответствие</h1><p>Pairs.</p>"),
    ("std/old", "member", "Старое", "<h1>Старое</h1>"),
]


@pytest.fixture(autouse=True)
def _unpinned_root():
    """The command pins the data root for the process; the next test must not inherit it."""
    yield
    dataset.set_data_root(None)


def _write_version(root: Path, version: str, files: dict, pages: list) -> None:
    folder = root / version
    folder.mkdir(parents=True)
    for name, data in files.items():
        # The meta always differs between versions; it is no change of the platform.
        body = {"meta": {"element_version": version, "count": len(data)}, **data}
        (folder / name).write_text(json.dumps(body, ensure_ascii=False), encoding="utf-8")
    con = sqlite3.connect(folder / "docs.sqlite")
    try:
        con.execute("CREATE TABLE pages (id TEXT PRIMARY KEY, kind TEXT, title TEXT, "
                    "qualified TEXT, availability TEXT, url TEXT, html TEXT)")
        con.executemany("INSERT INTO pages (id, kind, title, html) VALUES (?, ?, ?, ?)", pages)
        con.commit()
    finally:
        con.close()


def _data_root(tmp_path: Path, new_files: dict | None = None, new_pages: list | None = None) -> Path:
    root = tmp_path / "data"
    _write_version(root, OLD, FILES, PAGES)
    _write_version(root, NEW, new_files or FILES, PAGES if new_pages is None else new_pages)
    (root / "index.json").write_text(json.dumps({"available": [OLD, NEW], "default": NEW}),
                                     encoding="utf-8")
    return root


def _report(root: Path, capsys, *options: str) -> str:
    assert datadiff.cli_main([OLD, NEW, "--data-dir", str(root), *options]) == 0
    return capsys.readouterr().out


def _changed(**edits) -> dict:
    """A copy of the files with some sections replaced: {"stdlib.json": {"bases": {...}}}."""
    files = copy.deepcopy(FILES)
    for name, sections in edits.items():
        files[name.replace("_", ".", 1) if name.endswith("_json") else name].update(sections)
    return files


def _stdlib(**sections) -> dict:
    new = copy.deepcopy(STDLIB)
    new.update(sections)
    return new


def test_versions_that_differ_in_their_meta_alone_have_no_changes(tmp_path, capsys):
    """The control for everything below: the same data under two versions is no change."""
    out = _report(_data_root(tmp_path), capsys)

    assert out.count(i18n.t("datadiff.no-changes")) == len(datadiff._JSON_SECTIONS)
    assert i18n.t("datadiff.group.pages-changed") not in out


def test_a_module_that_lost_a_handler_is_named_with_the_handler(tmp_path, capsys):
    handlers = copy.deepcopy(STDLIB["element_module_handlers"])
    handlers["Справочник"]["Объект"]["handlers"].pop()  # the second handler goes away
    root = _data_root(tmp_path, {**FILES, "stdlib.json": _stdlib(element_module_handlers=handlers)})

    out = _report(root, capsys)

    assert i18n.t("datadiff.group.element-module-handlers") + " ~1:" in out
    assert "~ Справочник.Объект: -ПриКопировании" in out
    stdlib_part = out.split(i18n.t("datadiff.section.stdlib") + ":")[1].split("\n\n")[0]
    assert i18n.t("datadiff.no-changes") not in stdlib_part


def test_a_help_page_with_another_text_is_listed(tmp_path, capsys):
    """A page is compared by its HTML, not by its id and title alone. A retitled page is listed
    once, among the retitled - its HTML carries the heading and changed as well."""
    pages = [
        ("std/array", "type", "Массив", "<h1>Массив</h1><p>An ordered collection.</p>"),
        ("std/map", "type", "Соответствие2", "<h1>Соответствие2</h1><p>Pairs.</p>"),
        ("std/new", "member", "Новое", "<h1>Новое</h1>"),
    ]
    root = _data_root(tmp_path, new_pages=pages)

    diff = json.loads(_report(root, capsys, "--format", "json"))["docs"]

    assert diff["pages"]["changed"] == [["std/array", "Массив", "type"]]
    assert diff["pages"]["retitled"] == {"std/map": ["Соответствие", "Соответствие2"]}
    assert diff["pages"]["added"] == [["std/new", "Новое", "member"]]
    assert diff["pages"]["removed"] == [["std/old", "Старое", "member"]]

    out = _report(root, capsys)
    assert i18n.t("datadiff.group.pages-changed") + " ~1:" in out
    assert "~ Массив  [type]  std/array" in out


def test_the_text_report_shows_a_count_and_the_first_pages_and_limit_zero_shows_all(tmp_path, capsys):
    old_pages = [(f"std/page{n}", "member", f"Page{n}", f"<h1>Page{n}</h1>") for n in range(5)]
    new_pages = [(pid, kind, title, html + "<p>more</p>") for pid, kind, title, html in old_pages]
    root = tmp_path / "data"
    _write_version(root, OLD, FILES, old_pages)
    _write_version(root, NEW, FILES, new_pages)
    (root / "index.json").write_text(json.dumps({"available": [OLD, NEW], "default": NEW}),
                                     encoding="utf-8")

    capped = _report(root, capsys, "--limit", "2")
    assert i18n.t("datadiff.group.pages-changed") + " ~5:" in capped
    assert capped.count("  std/page") == 2
    assert i18n.t("datadiff.more", n=3) in capped

    full = _report(root, capsys, "--limit", "0")
    assert full.count("  std/page") == 5
    assert i18n.t("datadiff.more", n=3) not in full


# Every stdlib section: (section, the new value) - a copy of the catalog changed in it alone.
_SECTION_CHANGES = [
    ("names", ["Array", "Collection", "Коллекция", "Массив", "Очередь"]),
    ("object_members", {"Справочник": ["Объект", "Ссылка"], "Документ": ["Объект"]}),
    ("component_props", {"Компонент": ["Видимость"], "Кнопка": ["Видимость", "Картинка"]}),
    ("retired_components", {"СтараяГруппа": {
        "term": {"ru": "СтараяГруппа", "en": "OldGroup"}, "to": 8.0,
        "properties": [{"term": {"ru": "Заголовок", "en": "Title"}, "type": "Std::Text"}]}}),
    ("component_from", {"Карта": "1.1"}),
    ("module_handlers", {"Компонент": [{"ru": "ПослеСоздания", "en": "AfterCreate", "to": "2.0"}]}),
    ("global_availability", {"Мин": "Сервер"}),
    ("type_availability", {"Коллекция": "КлиентИСервер", "Массив": "Клиент"}),
    ("manager_member_types", {"Справочник": {"Найти": "{}.Ссылка"}}),
    ("checked_return_methods", {"Коллекция": ["Добавить"], "Массив": ["Добавить", "Вставить"]}),
    ("member_signatures", {
        "Коллекция": {"Добавить": ["Добавить(Элемент: Т)"], "Количество": ["Количество(): Число"]},
        "Массив": {"Вставить": ["Вставить(Индекс: Число, Элемент: Т)", "Вставить(Элемент: Т)"]}}),
    ("bases", {"Коллекция": ["Объект"], "Массив": ["Коллекция", "Объект", "Обходимое"],
               "Кнопка": ["Компонент", "Объект"], "Компонент": ["Объект"]}),
    ("generic_bases", {"Массив": {"Коллекция": ["Элемент"]}}),
    ("type_ctors", {"Коллекция": "args", "Массив": "empty"}),
    ("type_params", {"Коллекция": ["Т"], "Массив": ["Элемент"]}),
    ("type_param_variance", {"Коллекция": ["in_out"]}),
    ("member_type_params", {"Коллекция": {"Преобразовать": ["Р", "К"]}}),
    ("deprecated_members", {"Коллекция": {"Добавить": [
        {"signature": "Добавить(Элемент: Т)", "deprecated": True},
        {"signature": "Добавить(Элемент: Т, Флаг: Булево)", "deprecated": True}]}}),
    # A section a newer extractor may add is compared too, under its own name.
    ("future_section", {"Массив": "что-то новое"}),
]


@pytest.mark.parametrize("section, value", _SECTION_CHANGES, ids=[s for s, _ in _SECTION_CHANGES])
def test_every_stdlib_section_is_compared(section, value):
    diff = datadiff.diff_stdlib(copy.deepcopy(STDLIB), _stdlib(**{section: value}))

    assert diff, f"a change of {section} went unseen"
    lines = datadiff._section_lines("stdlib", diff, None)
    assert lines, f"a change of {section} is in the diff but not in the report"


def test_a_section_change_lands_in_its_own_group():
    """The group is named after the section and says what changed inside the entry."""
    cases = {
        "module_handlers": ("~ Компонент: ~ПослеСоздания (+to)", "datadiff.group.module-handlers"),
        "type_ctors": ("~ Коллекция: none -> args", "datadiff.group.type-ctors"),
        "type_params": ("~ Массив: [Т] -> [Элемент]", "datadiff.group.type-params"),
        "deprecated_members": ("~ Коллекция: ~Добавить (~Добавить(Элемент: Т) (+deprecated))",
                               "datadiff.group.deprecated-members"),
        "retired_components": ("~ СтараяГруппа: ~properties (~Заголовок (~type (Std::String -> "
                               "Std::Text)))", "datadiff.group.retired-components"),
    }
    values = dict(_SECTION_CHANGES)
    for section, (line, title) in cases.items():
        diff = datadiff.diff_stdlib(copy.deepcopy(STDLIB), _stdlib(**{section: values[section]}))
        rendered = [text for _, text in datadiff._section_lines("stdlib", diff, None)]
        assert any(text.startswith(i18n.t(title)) for text in rendered), section
        assert line in rendered, (section, rendered)


def test_a_change_made_by_a_base_is_reported_at_the_base_alone():
    """The heir inherits the new overload, and the diff names the collection, not the array."""
    signatures = copy.deepcopy(STDLIB["member_signatures"])
    signatures["Коллекция"]["Добавить"].append("Добавить(Элементы: Массив<Т>)")

    diff = datadiff.diff_stdlib(copy.deepcopy(STDLIB), _stdlib(member_signatures=signatures))

    assert list(diff["member_signatures"]["changed"]) == ["Коллекция"]


def test_a_change_the_heir_makes_itself_stays_at_the_heir():
    """The control: an override of the heir's own is the heir's change."""
    signatures = copy.deepcopy(STDLIB["member_signatures"])
    signatures["Массив"]["Добавить"] = ["Добавить(Элемент: Т): Число"]

    diff = datadiff.diff_stdlib(copy.deepcopy(STDLIB), _stdlib(member_signatures=signatures))

    assert list(diff["member_signatures"]["changed"]) == ["Массив"]
    assert diff["member_signatures"]["changed"]["Массив"]["changed"]["Добавить"] == {
        "added": ["Добавить(Элемент: Т): Число"], "removed": ["Добавить(Элемент: Т)"]}


def test_a_base_an_ancestor_gains_is_reported_at_the_ancestor_alone():
    bases = {"Коллекция": ["Объект", "Обходимое"], "Массив": ["Коллекция", "Объект", "Обходимое"],
             "Кнопка": ["Компонент", "Объект"], "Компонент": ["Объект"]}

    diff = datadiff.diff_stdlib(copy.deepcopy(STDLIB), _stdlib(bases=bases))

    assert diff["bases"] == {"changed": {"Коллекция": {"added": ["Обходимое"]}}}


def test_a_type_that_came_is_named_once_among_the_types():
    """A new type brings its bases, constructor, availability and signatures along; the sections
    keyed by type leave it to the "types" group instead of naming it five times."""
    new = copy.deepcopy(STDLIB)
    new["type_members"]["Очередь"] = {"methods": ["Взять"]}
    new["bases"]["Очередь"] = ["Коллекция", "Объект"]
    new["type_ctors"]["Очередь"] = "empty"
    new["type_availability"]["Очередь"] = "Сервер"
    new["member_signatures"]["Очередь"] = {"Взять": ["Взять(): Т"]}

    diff = datadiff.diff_stdlib(copy.deepcopy(STDLIB), new)

    assert diff["types"] == {"added": ["Очередь"]}
    for section in ("bases", "type_ctors", "type_availability", "member_signatures"):
        assert section not in diff, section


def test_a_dynamic_module_is_named_by_the_place_it_reads_the_handlers_from():
    handlers = copy.deepcopy(STDLIB["element_module_handlers"])
    handlers["Справочник"][""]["dynamic"] = ["DescriptionReader.handlerName"]

    diff = datadiff.diff_stdlib(copy.deepcopy(STDLIB), _stdlib(element_module_handlers=handlers))

    assert diff["element_module_handlers"] == {
        "changed": {"Справочник": {"added": ["dynamic:DescriptionReader.handlerName"]}}}


def test_the_values_of_a_ui_schema_enumeration_are_compared():
    """An enumeration of the schema is a record with a package and values; comparing the two
    records as key sets reported nothing whatever happened to the values."""
    old = copy.deepcopy(FILES["uischema.json"])
    new = copy.deepcopy(old)
    new["enums"]["ВидКнопки"] = {"package": "Стд::Кнопки", "values": ["А", "В"]}

    diff = datadiff.diff_uischema(old, new)

    assert diff["enum_values"] == {"ВидКнопки": {"added": ["В"], "removed": ["Б"]}}
    assert diff["enum_packages"] == {"changed": {"ВидКнопки": ["Стд::Интерфейс", "Стд::Кнопки"]}}


def test_the_rest_of_the_ui_schema_is_compared():
    old = copy.deepcopy(FILES["uischema.json"])
    new = copy.deepcopy(old)
    new["components"]["Кнопка"]["yaml_props"] = ["Имя", "Тип"]
    new["components"]["Кнопка"]["props"] = {}
    new["type_params"]["Кнопка"] = {"params": ["Т", "К"]}
    new["components"]["Кнопка"]["retired"] = True

    diff = datadiff.diff_uischema(old, new)

    assert diff["yaml_props"] == {"changed": {"Кнопка": {"added": ["Тип"]}}}
    assert diff["type_params"] == {"changed": {"Кнопка": {"changed": {"params": [["Т"], ["Т", "К"]]}}}}
    assert diff["flags"] == {"Кнопка": {"retired": [None, True]}}


def test_the_sections_of_the_metamodel_and_the_terms_without_a_comparison_are_compared():
    meta_old = copy.deepcopy(FILES["metamodel.json"])
    meta_new = copy.deepcopy(meta_old)
    meta_new["vetted"].append("Документ")
    meta_new["common"].remove("Имя")
    meta_new["classes"]["CatalogModel"]["ext"] = ["Base", "Named"]

    meta = datadiff.diff_metamodel(meta_old, meta_new)

    assert meta["vetted"] == {"added": ["Документ"]}
    assert meta["common"] == {"removed": ["Имя"]}
    assert meta["class_attrs"] == {"changed": {"CatalogModel": {"changed": {"ext": {"added": ["Named"]}}}}}
    lines = [text for _, text in datadiff._section_lines("metamodel", meta, None)]
    assert i18n.t("datadiff.metamodel.vetted") + " +1:" in lines

    terms_old = copy.deepcopy(FILES["terms.json"])
    terms_new = {**terms_old, "kinds": {"Справочник": "Catalog", "Документ": "Document"},
                 "query_reserved_english_only": ["NULL", "TEMP"]}
    terms = datadiff.diff_terms(terms_old, terms_new)
    assert terms["kinds"] == {"added": ["Документ"]}
    assert terms["query_reserved_english_only"] == {"added": ["TEMP"]}


def test_the_interface_spellings_and_the_compiler_dictionary_are_compared(tmp_path, capsys):
    files = copy.deepcopy(FILES)
    files["uiterms.json"]["enum_values"]["ВидКнопки"]["Б"] = "B"
    files["terms_full.json"]["common"]["Вставить"] = "Put"
    root = _data_root(tmp_path, files)

    out = _report(root, capsys)
    diff = json.loads(_report(root, capsys, "--format", "json"))

    assert diff["uiterms"] == {"enum_values": {"changed": {"ВидКнопки": {"added": ["Б"]}}}}
    assert diff["terms_full"] == {"common": {"changed": {"Вставить": ["Insert", "Put"]}}}
    assert i18n.t("datadiff.section.uiterms") + ":" in out
    assert "~ Вставить: Insert -> Put" in out


def test_the_numbering_of_the_grammar_tokens_is_no_change():
    """The engine reads keywords and operators, never the token numbers, and every rule added to
    the grammar moves them - they would bury the one change that matters."""
    old = copy.deepcopy(FILES["language.json"])
    new = {**old, "token_ids": {"RULE_IF_KW": 6}}

    assert datadiff.diff_language(old, new) == {}


def test_events_and_moves_of_members_reach_the_text_report():
    """The member line named methods and properties only: a type whose change was an event
    printed its name and nothing after it."""
    old = {"type_members": {"Кнопка": {"properties": ["Заголовок", "ПриНажатии"]}}, "bases": {}}
    new = {"type_members": {"Кнопка": {"properties": ["Заголовок"],
                                       "events": ["ПриНажатии", "ПриНаведении"]}}, "bases": {}}

    lines = [text for _, text in datadiff._section_lines("stdlib", datadiff.diff_stdlib(old, new),
                                                         None)]

    line = next(text for text in lines if text.startswith("Кнопка:"))
    assert i18n.t("datadiff.group.events") + " +ПриНаведении" in line
    assert i18n.t("datadiff.group.moved") + " ПриНажатии (" in line
