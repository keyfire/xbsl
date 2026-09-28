"""The translator spells an override of a platform handler the way the platform does.

A method under the handler annotation named like a handler of its component's base
(`AfterCreate` of every component, `BeforeClose` of a form) is found by the compiler under the
platform's own word. It used to be collected as the project's name, like any method, and the
project's names are answered by the dictionary alone - so without an entry the English tree
kept `method ПослеСоздания()`. The handler lists come from the data (see xbsl/modulehandlers.py);
the tests put the rows the distribution ships in place of it, and the lexer still needs the
language data, hence `needs_data`.
"""

from functools import lru_cache

import pytest

from xbsl import modulehandlers
from xbsl.translation import names
from xbsl.translation.dictionary import Dictionary
from xbsl.translation.project import translate_project

pytestmark = pytest.mark.needs_data

_TABLE = {
    "Компонент": ({"ru": "ПослеСоздания", "en": "AfterCreate"},),
    "Форма": ({"ru": "ПриОбновлении", "en": "OnRefresh"},
              {"ru": "ПередЗакрытием", "en": "BeforeClose"}),
    "ФормаОбъекта": ({"ru": "ПередЗаписью", "en": "BeforeWrite"},
                     {"ru": "ПослеЗаписи", "en": "AfterWrite"}),
}


@pytest.fixture(autouse=True)
def handlers(monkeypatch):
    monkeypatch.setattr(modulehandlers, "_table", lru_cache(maxsize=1)(lambda: _TABLE))
    modulehandlers._reset()
    names.forget()
    yield
    monkeypatch.undo()
    modulehandlers._reset()
    names.forget()


PANEL_YAML = """\
ВидЭлемента: КомпонентИнтерфейса
Ид: 2b0d5a4e-6c1f-4f3a-9e8d-7a1b2c3d4e5f
Имя: ПанельСкладов
ОбластьВидимости: ВПодсистеме
Наследует:
    Тип: Форма
"""

PANEL_XBSL = """\
@Обработчик
метод ПослеСоздания()
    Заполнить()
;

@Обработчик
метод ПриОбновлении()
    ПослеСоздания()
;

метод Заполнить()
;
"""

CARD_YAML = """\
ВидЭлемента: КомпонентИнтерфейса
Ид: 3c1e6b5f-7d2a-4a4b-8f9e-8b2c3d4e5f60
Имя: КарточкаСклада
ОбластьВидимости: ВПодсистеме
Наследует:
    Тип: ФормаОбъекта<Склады.Объект>
"""

CATALOG_YAML = """\
ВидЭлемента: Справочник
Ид: 4d2f7c60-8e3b-4b5c-9a0f-9c3d4e5f6a71
Имя: Склады
ОбластьВидимости: ВПодсистеме
"""

TOKENS = {"ПанельСкладов": "StockPanel", "Заполнить": "Fill", "КарточкаСклада": "StockCard",
          "Склады": "Stocks"}


def _translate(tmp_path, files, tokens=None):
    root = tmp_path / "ru"
    for name, text in files.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8", newline="\n")
    out = tmp_path / "en"
    report = translate_project(root, Dictionary(tokens=dict(TOKENS if tokens is None else tokens)),
                               out=out)
    written = {path.relative_to(out).as_posix(): path.read_text(encoding="utf-8")
               for path in out.rglob("*.xbsl")}
    return report, written


def test_an_override_and_its_bare_call_take_the_platform_spelling(tmp_path):
    report, written = _translate(tmp_path, {"ПанельСкладов.yaml": PANEL_YAML,
                                            "ПанельСкладов.xbsl": PANEL_XBSL})
    assert written["StockPanel.xbsl"] == """\
@Handler
method AfterCreate()
    Fill()
;

@Handler
method OnRefresh()
    AfterCreate()
;

method Fill()
;
"""
    # No entry is asked for: the name is the platform's, not the project's.
    missing = {name for file in report.files.values() for name in file.missing_tokens}
    assert "ПослеСоздания" not in missing and "ПриОбновлении" not in missing


def test_an_object_form_overrides_its_own_handlers_and_its_bases(tmp_path):
    module = "@Обработчик\nметод ПослеЗаписи()\n;\n\n@Обработчик\nметод ПередЗакрытием()\n;\n"
    _report, written = _translate(tmp_path, {"КарточкаСклада.yaml": CARD_YAML,
                                             "КарточкаСклада.xbsl": module,
                                             "Склады.yaml": CATALOG_YAML})
    assert written["StockCard.xbsl"] == (
        "@Handler\nmethod AfterWrite()\n;\n\n@Handler\nmethod BeforeClose()\n;\n")


def test_a_method_without_the_annotation_stays_the_projects_word(tmp_path):
    """A project may name a method of its own after an event: then the dictionary answers."""
    module = PANEL_XBSL + "\nметод ПослеЗаписи()\n;\n"
    report, written = _translate(tmp_path, {"ПанельСкладов.yaml": PANEL_YAML,
                                            "ПанельСкладов.xbsl": module})
    assert "method ПослеЗаписи()" in written["StockPanel.xbsl"]
    assert "ПослеЗаписи" in {name for file in report.files.values() for name in file.missing_tokens}


def test_an_override_of_an_object_module_reads_the_platform_tables(tmp_path):
    """The component lists do not speak for an object module; the name still is the platform's
    there - the element lists spell it (test_translate_element_handler_overrides), and without
    them the platform tables do."""
    module = "@Обработчик\nметод ПередЗаписью()\n;\n"
    _report, written = _translate(tmp_path, {"Склады.yaml": CATALOG_YAML,
                                             "Склады.Объект.xbsl": module})
    assert written["Stocks.Object.xbsl"] == "@Handler\nmethod BeforeWrite()\n;\n"


def test_a_dictionary_entry_that_spells_the_handler_otherwise_loses_and_is_reported(tmp_path):
    report, written = _translate(
        tmp_path, {"ПанельСкладов.yaml": PANEL_YAML, "ПанельСкладов.xbsl": PANEL_XBSL},
        tokens={**TOKENS, "ПослеСоздания": "OnAfterCreate"})
    assert "method AfterCreate()" in written["StockPanel.xbsl"]
    assert any("OnAfterCreate" in problem and "AfterCreate" in problem
               for problem in report.problems)


def test_an_entry_that_repeats_the_platform_spelling_is_an_echo(tmp_path):
    report, _written = _translate(
        tmp_path, {"ПанельСкладов.yaml": PANEL_YAML, "ПанельСкладов.xbsl": PANEL_XBSL},
        tokens={**TOKENS, "ПослеСоздания": "AfterCreate"})
    assert report.echoed.get("ПослеСоздания") == "AfterCreate"


def test_without_the_lists_the_override_waits_for_the_dictionary_as_before(tmp_path, monkeypatch):
    monkeypatch.setattr(modulehandlers, "_table", lru_cache(maxsize=1)(lambda: {}))
    modulehandlers._reset()
    names.forget()
    _report, written = _translate(tmp_path, {"ПанельСкладов.yaml": PANEL_YAML,
                                             "ПанельСкладов.xbsl": PANEL_XBSL})
    assert "method ПослеСоздания()" in written["StockPanel.xbsl"]
