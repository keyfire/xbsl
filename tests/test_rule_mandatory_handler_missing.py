"""code/mandatory-handler-missing: a handler the compiler requires that the module lacks.

The rows the compiler requires come from the `element_module_handlers` section (`required`,
`per`, `needs`) and from the access settings of the description. The tests put a table of the
same shape in place of the section, so they do not wait for a data release; the lexer, the
parser and the reading of the access settings still need the language data, hence `needs_data`.
"""

from functools import lru_cache

import pytest

from xbsl import engine, i18n, modulehandlers
from xbsl.fixer import fix_source
from xbsl.rules import handler_annotation

RULE = "code/mandatory-handler-missing"

_PAIR = ("ВычислитьВнешнююНавигационнуюСсылку", "ВычислитьСсылкуПоВнешнейНавигационнойСсылке")
_TABLE = {
    "ОбычнаяКоманда": {
        "": {"handlers": ({"ru": "Обработчик", "en": "Handler", "required": True},),
             "dynamic": ()},
    },
    "ПереключаемаяКоманда": {
        "": {"handlers": ({"ru": "Обработчик", "en": "Handler"},), "dynamic": ()},
    },
    "Справочник": {
        "": {"handlers": (
            {"ru": _PAIR[0], "en": "ComputeExternalNavigationLink", "needs": [_PAIR[1]]},
            {"ru": "ВычислитьРазрешенияДоступа", "en": "ComputeAccessPermissions"},
            {"ru": _PAIR[1], "en": "ComputeReferenceByExternalNavigationLink",
             "needs": [_PAIR[0]]},
        ), "dynamic": (modulehandlers.RECORD_SECURITY_SOURCE,)},
        "Объект": {"handlers": (
            {"ru": "ПередЗаписью", "en": "BeforeWrite"},
            {"ru": "ПриСозданииНаОсновании", "en": "OnCreateOnBasis",
             "per": "RuntimeEntityMetadata.createOnBasisSources", "required": True},
        ), "dynamic": ()},
    },
    "HttpСервис": {
        "": {"handlers": ({"ru": "ВычислитьРазрешенияДоступа", "en": "ComputeAccessPermissions"},),
             "dynamic": ()},
    },
}


def _reset() -> None:
    modulehandlers._reset()
    handler_annotation._reset()


def _use(monkeypatch, table):
    monkeypatch.setattr(modulehandlers, "_elements", lru_cache(maxsize=1)(lambda: table))
    _reset()


@pytest.fixture
def handlers(monkeypatch):
    """The element lists in place of the data section."""
    _use(monkeypatch, _TABLE)
    yield
    monkeypatch.undo()
    _reset()


def _lint(files):
    sources = [engine.load_text(name, text) for name, text in files.items()]
    return engine.run_sources(sources, select={RULE})


def _rel(diag):
    return diag.path.replace("\\", "/")


def _head(kind, name, uid="4d2f7c60-8e3b-4b5c-9a0f-9c3d4e5f6a71"):
    return f"ВидЭлемента: {kind}\nИд: {uid}\nИмя: {name}\nОбластьВидимости: ВПодсистеме\n"


COMMAND = _head("ОбычнаяКоманда", "Пересчет") + "Представление: Пересчет\n"
READ_COMPUTED = "КонтрольДоступа:\n    Разрешения:\n        Чтение: РазрешенияВычисляются\n"
READ_PER_OBJECT = ("КонтрольДоступа:\n    РасчетРазрешенийПо:\n        - Склад\n"
                   "    Разрешения:\n        Чтение: РазрешенияВычисляютсяДляКаждогоОбъекта\n")
PERMISSIONS = ("@Обработчик\nметод ВычислитьРазрешенияДоступа(): Массив<РазрешениеДоступа>\n"
               "    возврат новый Массив<РазрешениеДоступа>()\n;\n")


# --- the handlers the data marks required ------------------------------------------------------

@pytest.mark.needs_data
def test_an_element_without_its_module_is_reported_at_the_description(handlers):
    diags = _lint({"Команды/Пересчет.yaml": COMMAND})
    assert [(_rel(d), d.line, d.col) for d in diags] == [("Команды/Пересчет.yaml", 1, 1)]
    assert "Модуля Пересчет.xbsl нет" in diags[0].message
    assert "\"Mandatory handler \"Обработчик\" is not defined\"" in diags[0].message


@pytest.mark.needs_data
def test_a_module_without_the_handler_is_reported_at_its_first_line(handlers):
    diags = _lint({"Команды/Пересчет.yaml": COMMAND,
                   "Команды/Пересчет.xbsl": "метод Пересчитать()\n;\n"})
    assert [(_rel(d), d.line, d.col) for d in diags] == [("Команды/Пересчет.xbsl", 1, 1)]
    assert diags[0].message.startswith("Модуль элемента вида ОбычнаяКоманда обязан объявить")


@pytest.mark.needs_data
def test_control_the_declared_handler_is_silent(handlers):
    assert _lint({"Команды/Пересчет.yaml": COMMAND,
                  "Команды/Пересчет.xbsl": "@Обработчик\nметод Обработчик()\n;\n"}) == []


@pytest.mark.needs_data
def test_control_a_handler_the_data_does_not_require_is_not_demanded(handlers):
    switch = (_head("ПереключаемаяКоманда", "Переключатель")
              + "ПредставлениеАктивного: Да\nПредставлениеНеактивного: Нет\n")
    assert _lint({"Команды/Переключатель.yaml": switch}) == []


@pytest.mark.needs_data
def test_a_method_without_the_annotation_gets_the_other_answer_and_a_fix(handlers):
    module = "метод Обработчик()\n;\n"
    diags = _lint({"Команды/Пересчет.yaml": COMMAND, "Команды/Пересчет.xbsl": module})
    assert [(d.line, d.col) for d in diags] == [(1, 1)]
    assert ("\"Handler method \"Обработчик\" is not marked with annotation @Обработчик\""
            in diags[0].message)
    source = engine.load_text("Команды/Пересчет.xbsl", module)
    assert fix_source(source, diags).text == "@Обработчик\nметод Обработчик()\n;\n"


@pytest.mark.needs_data
def test_a_module_with_a_syntax_error_is_not_judged(handlers):
    assert _lint({"Команды/Пересчет.yaml": COMMAND,
                  "Команды/Пересчет.xbsl": "метод Пересчитать(\n"}) == []


@pytest.mark.needs_data
def test_a_module_on_disk_outside_the_run_is_not_called_missing(handlers, tmp_path):
    folder = tmp_path / "Команды"
    folder.mkdir()
    (folder / "Пересчет.yaml").write_text(COMMAND, encoding="utf-8")
    yaml_only = [engine.make_source(folder / "Пересчет.yaml", COMMAND.encode("utf-8"))]
    assert len(engine.run_sources(yaml_only, select={RULE})) == 1
    (folder / "Пересчет.xbsl").write_text("@Обработчик\nметод Обработчик()\n;\n",
                                          encoding="utf-8")
    assert engine.run_sources(yaml_only, select={RULE}) == []


# --- the access settings ------------------------------------------------------------------------

@pytest.mark.needs_data
def test_computed_settings_require_the_permissions_handler(handlers):
    catalog = _head("Справочник", "Склады") + READ_COMPUTED
    diags = _lint({"Склады/Склады.yaml": catalog, "Склады/Склады.xbsl": "метод Счет()\n;\n"})
    assert len(diags) == 1 and "ВычислитьРазрешенияДоступа" in diags[0].message
    assert "настройки доступа вычисляют разрешения" in diags[0].message
    assert _lint({"Склады/Склады.yaml": catalog, "Склады/Склады.xbsl": PERMISSIONS}) == []


@pytest.mark.needs_data
def test_per_object_settings_require_the_record_level_handler(handlers):
    catalog = _head("Справочник", "Склады") + READ_PER_OBJECT
    diags = _lint({"Склады/Склады.yaml": catalog, "Склады/Склады.xbsl": PERMISSIONS})
    assert len(diags) == 1
    assert "ВычислитьРазрешенияДоступаДляОбъектов" in diags[0].message
    assert "для каждого объекта" in diags[0].message


@pytest.mark.needs_data
def test_control_without_access_settings_nothing_is_required(handlers):
    assert _lint({"Склады/Склады.yaml": _head("Справочник", "Склады")}) == []
    service = _head("HttpСервис", "Сервис") + "КорневойUrl: /s\n"
    assert _lint({"Сервис/Сервис.yaml": service}) == []


@pytest.mark.needs_data
def test_a_controlled_service_computing_its_call_requires_the_handler(handlers):
    service = (_head("HttpСервис", "Сервис") + "КорневойUrl: /s\n"
               "КонтрольДоступа:\n    Разрешения:\n        Вызов: РазрешенияВычисляются\n")
    diags = _lint({"Сервис/Сервис.yaml": service})
    assert len(diags) == 1 and "ВычислитьРазрешенияДоступа" in diags[0].message


# --- creation on basis --------------------------------------------------------------------------

def _based(*types):
    return _head("Справочник", "Заказы") + "СозданиеНаОсновании:\n" + "".join(
        f"    - {name}.Ссылка\n" for name in types)


@pytest.mark.needs_data
def test_a_listed_basis_requires_the_handler_of_the_object_module(handlers):
    diags = _lint({"Заказы/Заказы.yaml": _based("Клиенты")})
    assert [(_rel(d), d.line) for d in diags] == [("Заказы/Заказы.yaml", 1)]
    assert "Модуля Заказы.Объект.xbsl нет" in diags[0].message
    diags = _lint({"Заказы/Заказы.yaml": _based("Клиенты"),
                   "Заказы/Заказы.Объект.xbsl": "метод Счет()\n;\n"})
    assert [(_rel(d), d.line) for d in diags] == [("Заказы/Заказы.Объект.xbsl", 1)]
    assert "СозданиеНаОсновании" in diags[0].message


@pytest.mark.needs_data
def test_fewer_overloads_than_listed_types_are_reported(handlers):
    module = "@Обработчик\nметод ПриСозданииНаОсновании(Основание: Клиенты.Ссылка)\n;\n"
    diags = _lint({"Заказы/Заказы.yaml": _based("Клиенты", "Поставщики"),
                   "Заказы/Заказы.Объект.xbsl": module})
    assert len(diags) == 1 and "типов там 2" in diags[0].message


@pytest.mark.needs_data
def test_control_an_overload_over_a_union_of_types_is_not_counted_short(handlers):
    module = ("@Обработчик\n"
              "метод ПриСозданииНаОсновании(Основание: Клиенты.Ссылка|Поставщики.Ссылка)\n;\n")
    assert _lint({"Заказы/Заказы.yaml": _based("Клиенты", "Поставщики"),
                  "Заказы/Заказы.Объект.xbsl": module}) == []


@pytest.mark.needs_data
def test_control_without_a_basis_nothing_is_required(handlers):
    assert _lint({"Заказы/Заказы.yaml": _head("Справочник", "Заказы"),
                  "Заказы/Заказы.Объект.xbsl": "метод Счет()\n;\n"}) == []


# --- the pairs ----------------------------------------------------------------------------------

@pytest.mark.needs_data
def test_one_handler_of_a_pair_requires_the_other(handlers):
    module = f"@Обработчик\nметод {_PAIR[0]}()\n;\n"
    diags = _lint({"Склады/Склады.yaml": _head("Справочник", "Склады"),
                   "Склады/Склады.xbsl": module})
    assert len(diags) == 1 and _PAIR[1] in diags[0].message
    assert f"модуль объявляет {_PAIR[0]}" in diags[0].message
    both = module + f"\n@Обработчик\nметод {_PAIR[1]}()\n;\n"
    assert _lint({"Склады/Склады.yaml": _head("Справочник", "Склады"),
                  "Склады/Склады.xbsl": both}) == []


# --- the language and the data ------------------------------------------------------------------

@pytest.mark.needs_data
def test_the_message_follows_the_reader(handlers):
    i18n.set_lang("en")
    diags = _lint({"Команды/Пересчет.yaml": COMMAND})
    assert "There is no Пересчет.xbsl module" in diags[0].message
    assert "\"Mandatory handler \"Handler\" is not defined\"" in diags[0].message


@pytest.mark.needs_data
def test_control_without_the_element_lists_nothing_is_judged(monkeypatch):
    """The negative control: the same element with the section taken away says nothing."""
    _use(monkeypatch, {})
    try:
        assert _lint({"Команды/Пересчет.yaml": COMMAND}) == []
    finally:
        monkeypatch.undo()
        _reset()
