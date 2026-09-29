"""The translator spells an override in a module of an element the way the platform does.

A component module overrides the handlers its base lists; every other module - the object
module of a catalog, the own module of a scheduled job or of an access key - overrides the
handlers the compiler declares for its kind and module, which the data keeps in the
`element_module_handlers` section (see xbsl/modulehandlers.py). The compiler finds such an
override by the platform's own word, so the English tree has to carry that word whatever the
dictionary says: an entry that spells it otherwise is a defect of the dictionary. The tests put
tables of the data's shape in place of the sections; the lexer still needs the language data,
hence `needs_data`.
"""

from functools import lru_cache

import pytest

from xbsl import modulehandlers
from xbsl.translation import names
from xbsl.translation.dictionary import Dictionary
from xbsl.translation.project import translate_project

pytestmark = pytest.mark.needs_data

#: The rows the distribution ships for the modules below, and one made-up handler of a register
#: record set that no platform table knows: only the element lists can spell it.
_ELEMENTS = {
    "Справочник": {
        "": {"handlers": ({"ru": "ВычислитьРазрешенияДоступа", "en": "ComputeAccessPermissions"},),
             "dynamic": (modulehandlers.RECORD_SECURITY_SOURCE,)},
        "Объект": {"handlers": ({"ru": "ПередЗаписью", "en": "BeforeWrite"},
                                {"ru": "ПриСозданииНаОсновании", "en": "OnCreateOnBasis"}),
                   "dynamic": ()},
    },
    "Документ": {
        "Объект": {"handlers": ({"ru": "ПриСозданииНаОсновании", "en": "OnCreateOnBasis"},),
                   "dynamic": ()},
    },
    "КлючДоступа": {
        "": {"handlers": ({"ru": "ПроверитьНаличиеКлючейДоступа", "en": "CheckHasAccessKeys"},),
             "dynamic": (modulehandlers.RECORD_SECURITY_SOURCE,)},
    },
    "ЗапланированноеЗадание": {
        "": {"handlers": ({"ru": "Обработчик", "en": "Handler"},), "dynamic": ()},
    },
    "РегистрСведений": {
        "НаборЗаписей": {"handlers": ({"ru": "ПослеПересчетаОстатков", "en": "AfterStockRecount"},),
                         "dynamic": ()},
    },
    "Проект": {
        "": {"handlers": ({"ru": "ВычислитьСистемныеРазрешенияДоступа",
                           "en": "ComputeSystemAccessPermissions"},), "dynamic": ()},
    },
}


def _use(monkeypatch, elements: dict) -> None:
    """The element lists in place of the data, and no component lists at all."""
    monkeypatch.setattr(modulehandlers, "_table", lru_cache(maxsize=1)(lambda: {}))
    monkeypatch.setattr(modulehandlers, "_elements", lru_cache(maxsize=1)(lambda: elements))
    modulehandlers._reset()
    names.forget()


@pytest.fixture(autouse=True)
def handlers(monkeypatch):
    _use(monkeypatch, _ELEMENTS)
    yield
    monkeypatch.undo()
    modulehandlers._reset()
    names.forget()


def _yaml(kind: str, name: str, uid: str) -> str:
    return f"ВидЭлемента: {kind}\nИд: {uid}\nИмя: {name}\nОбластьВидимости: ВПодсистеме\n"


CATALOG = _yaml("Справочник", "Склады", "4d2f7c60-8e3b-4b5c-9a0f-9c3d4e5f6a71")
DOCUMENT = _yaml("Документ", "Накладные", "5e3a8d71-9f4c-4c6d-8b1a-0d4e5f6a7b82")
KEY = _yaml("КлючДоступа", "КлючиСкладов", "6f4b9e82-0a5d-4d7e-9c2b-1e5f6a7b8c93")
JOB = _yaml("ЗапланированноеЗадание", "ОчисткаСкладов", "7a5c0f93-1b6e-4e8f-8d3c-2f6a7b8c9d04")
REGISTER = _yaml("РегистрСведений", "ОстаткиСкладов", "8b6d1a04-2c7f-4f90-9e4d-3a7b8c9d0e15")

TOKENS = {"Склады": "Stock", "Накладные": "Invoices", "КлючиСкладов": "StockKeys",
          "ОчисткаСкладов": "StockCleanup", "ОстаткиСкладов": "StockBalances",
          "Очистить": "Clean", "Основание": "Basis"}


def _translate(tmp_path, files, tokens=None):
    root = tmp_path / "ru"
    for name, text in files.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8", newline="\n")
    out = tmp_path / "en"
    report = translate_project(root, Dictionary(tokens={**TOKENS, **(tokens or {})}), out=out)
    written = {path.relative_to(out).as_posix(): path.read_text(encoding="utf-8")
               for path in out.rglob("*.xbsl")}
    return report, written


@pytest.mark.parametrize("files, module, english", [
    ({"Склады.yaml": CATALOG, "Склады.Объект.xbsl": "@Обработчик\nметод ПередЗаписью()\n;\n"},
     "Stock.Object.xbsl", "@Handler\nmethod BeforeWrite()\n;\n"),
    ({"Накладные.yaml": DOCUMENT, "Накладные.Объект.xbsl":
      "@Обработчик\nметод ПриСозданииНаОсновании(Основание: Объект)\n;\n"},
     "Invoices.Object.xbsl", "@Handler\nmethod OnCreateOnBasis(Basis: Object)\n;\n"),
    ({"КлючиСкладов.yaml": KEY, "КлючиСкладов.xbsl":
      "@Обработчик\nметод ПроверитьНаличиеКлючейДоступа()\n;\n"},
     "StockKeys.xbsl", "@Handler\nmethod CheckHasAccessKeys()\n;\n"),
    ({"ОчисткаСкладов.yaml": JOB, "ОчисткаСкладов.xbsl":
      "@Обработчик\nметод Обработчик()\n    Очистить()\n;\n\nметод Очистить()\n;\n"},
     "StockCleanup.xbsl", "@Handler\nmethod Handler()\n    Clean()\n;\n\nmethod Clean()\n;\n"),
    ({"Склады.yaml": CATALOG, "Склады.xbsl":
      "@Обработчик\nметод ВычислитьРазрешенияДоступаДляОбъектов()\n;\n"},
     "Stock.xbsl", "@Handler\nmethod ComputeAccessPermissionsForObjects()\n;\n"),
])
def test_an_override_takes_the_platform_spelling(tmp_path, files, module, english):
    report, written = _translate(tmp_path, files)
    assert written[module] == english
    # No entry is asked for: the name is the platform's, not the project's.
    missing = {name for file in report.files.values() for name in file.missing_tokens}
    assert not missing
    assert not report.problems


def test_the_override_and_its_bare_call_take_the_word_only_the_lists_know(tmp_path):
    module = ("@Обработчик\nметод ПослеПересчетаОстатков()\n;\n\n"
              "метод Пересчитать()\n    ПослеПересчетаОстатков()\n;\n")
    _report, written = _translate(tmp_path, {"ОстаткиСкладов.yaml": REGISTER,
                                             "ОстаткиСкладов.НаборЗаписей.xbsl": module},
                                  tokens={"Пересчитать": "Recount"})
    assert written["StockBalances.RecordSet.xbsl"] == (
        "@Handler\nmethod AfterStockRecount()\n;\n\nmethod Recount()\n    AfterStockRecount()\n;\n")


@pytest.mark.parametrize("files, name, owner", [
    ({"Накладные.yaml": DOCUMENT, "Накладные.Объект.xbsl":
      "@Обработчик\nметод ПриСозданииНаОсновании(Основание: Объект)\n;\n"},
     "ПриСозданииНаОсновании", "Документ.Объект"),
    ({"КлючиСкладов.yaml": KEY, "КлючиСкладов.xbsl":
      "@Обработчик\nметод ПроверитьНаличиеКлючейДоступа()\n;\n"},
     "ПроверитьНаличиеКлючейДоступа", "КлючДоступа"),
    ({"ОчисткаСкладов.yaml": JOB, "ОчисткаСкладов.xbsl": "@Обработчик\nметод Обработчик()\n;\n"},
     "Обработчик", "ЗапланированноеЗадание"),
])
def test_an_entry_that_spells_the_handler_otherwise_loses_and_is_reported(
        tmp_path, files, name, owner):
    report, written = _translate(tmp_path, files, tokens={name: "SomethingElse"})
    assert not any("SomethingElse" in text for text in written.values())
    assert any(f"'{name}: SomethingElse'" in problem and f"у {owner} пишется" in problem
               for problem in report.problems)


def test_an_entry_that_repeats_the_platform_spelling_is_an_echo(tmp_path):
    report, _written = _translate(
        tmp_path, {"Склады.yaml": CATALOG,
                   "Склады.Объект.xbsl": "@Обработчик\nметод ПередЗаписью()\n;\n"},
        tokens={"ПередЗаписью": "BeforeWrite"})
    assert report.echoed.get("ПередЗаписью") == "BeforeWrite"


def test_control_a_handler_of_another_module_is_left_to_the_dictionary(tmp_path):
    """The object module of a catalog does not override the handler of a register record set."""
    module = "@Обработчик\nметод ПослеПересчетаОстатков()\n;\n"
    report, written = _translate(tmp_path, {"Склады.yaml": CATALOG, "Склады.Объект.xbsl": module},
                                 tokens={"ПослеПересчетаОстатков": "AfterRecount"})
    assert written["Stock.Object.xbsl"] == "@Handler\nmethod AfterRecount()\n;\n"
    assert not report.problems


def test_control_a_method_without_the_annotation_stays_the_projects_word(tmp_path):
    module = "метод ПослеПересчетаОстатков()\n;\n"
    report, written = _translate(tmp_path, {"ОстаткиСкладов.yaml": REGISTER,
                                            "ОстаткиСкладов.НаборЗаписей.xbsl": module})
    assert written["StockBalances.RecordSet.xbsl"] == "method ПослеПересчетаОстатков()\n;\n"
    assert "ПослеПересчетаОстатков" in {
        name for file in report.files.values() for name in file.missing_tokens}


def test_control_without_the_element_lists_the_override_waits_for_the_dictionary(
        tmp_path, monkeypatch):
    _use(monkeypatch, {})
    module = "@Обработчик\nметод ПослеПересчетаОстатков()\n;\n"
    _report, written = _translate(tmp_path, {"ОстаткиСкладов.yaml": REGISTER,
                                             "ОстаткиСкладов.НаборЗаписей.xbsl": module})
    assert written["StockBalances.RecordSet.xbsl"] == (
        "@Handler\nmethod ПослеПересчетаОстатков()\n;\n")


PROJECT = "Ид: 9c7e2b15-3d80-4a01-8f5e-4b8c9d0e1f26\nИмя: Склады\nЯзыкРазработки: Русский\n"
PROJECT_MODULE = "@Обработчик\nметод ВычислитьСистемныеРазрешенияДоступа()\n;\n"


def test_the_module_of_the_project_takes_the_platform_spelling(tmp_path):
    """The project description names no kind: its module is the module of the project."""
    report, written = _translate(tmp_path, {"Проект.yaml": PROJECT, "Проект.xbsl": PROJECT_MODULE})
    assert list(written.values()) == ["@Handler\nmethod ComputeSystemAccessPermissions()\n;\n"]
    assert not {name for file in report.files.values() for name in file.missing_tokens}


def test_control_without_the_project_slot_the_handler_waits_for_the_dictionary(
        tmp_path, monkeypatch):
    _use(monkeypatch, {kind: slots for kind, slots in _ELEMENTS.items() if kind != "Проект"})
    report, written = _translate(tmp_path, {"Проект.yaml": PROJECT, "Проект.xbsl": PROJECT_MODULE})
    assert list(written.values()) == [
        "@Handler\nmethod ВычислитьСистемныеРазрешенияДоступа()\n;\n"]
    assert "ВычислитьСистемныеРазрешенияДоступа" in {
        name for file in report.files.values() for name in file.missing_tokens}
