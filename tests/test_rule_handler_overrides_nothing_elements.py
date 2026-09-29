"""code/handler-overrides-nothing over the modules of elements other than components.

The compiler declares the handlers of such a module in code - the object module of a catalog,
the record set of a register, the module of a scheduled job - and the extractor reads them
into the `element_module_handlers` section of stdlib.json (xbsl/extract/elementhandlers.py),
by the kind of the element and the module its file names ("" for the element's own module).
A module whose handler names come from the element's own description at build time - the
operations of a processing - carries `dynamic` there and is not judged.

The tests put a table of the same shape in place of the section, so they do not wait for a
data release; the lexer and the parser still need the language data, hence `needs_data`.
"""

from functools import lru_cache

import pytest

from xbsl import engine, i18n, modulehandlers
from xbsl.fixer import fix_source
from xbsl.rules import handler_annotation

RULE = "code/handler-overrides-nothing"

_OBJECT_ROWS = (
    {"ru": "ПередЗаписью", "en": "BeforeWrite"},
    {"ru": "ПослеЗаписи", "en": "AfterWrite"},
    {"ru": "ПриСозданииКопии", "en": "OnCreateCopy"},
)
_TABLE = {
    "Справочник": {
        "": {"handlers": ({"ru": "ПолучитьЗначенияВыбора", "en": "GetChoiceValues"},),
             "dynamic": ("computeHandlerTerm",)},
        "Объект": {"handlers": _OBJECT_ROWS, "dynamic": ()},
    },
    "РегистрСведений": {
        "НаборЗаписей": {"handlers": ({"ru": "ПередЗаписью", "en": "BeforeWrite"},
                                      {"ru": "ПослеЗаписи", "en": "AfterWrite"}),
                         "dynamic": ()},
    },
    "ЗапланированноеЗадание": {
        "": {"handlers": ({"ru": "Обработчик", "en": "Handler"},), "dynamic": ()},
    },
    "Обработка": {
        "Объект": {"handlers": ({"ru": "ПриЗаполнении", "en": "OnFill"},),
                   "dynamic": ("getNameTerm",)},
    },
}


def _reset() -> None:
    """Both caches that read the lists: the module's own and the rule's.

    The words of module files derived from the lists (`modulehandlers.module_words`) are kept
    with the lists; an earlier test of the same run that read the real data leaves them filled,
    and a table put in place here would not be seen by the rule.
    """
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


CATALOG_YAML = "ВидЭлемента: Справочник\nИд: 4d2f7c60-8e3b-4b5c-9a0f-9c3d4e5f6a71\nИмя: Склады\n"
JOB_YAML = ("ВидЭлемента: ЗапланированноеЗадание\nИд: 6a3f8d71-9f4c-4c6d-8b1a-0d4e5f6a7b82\n"
            "Имя: ОчисткаСкладов\n")


def _lint(files):
    sources = [engine.load_text(name, text) for name, text in files.items()]
    return engine.run_sources(sources, select={RULE})


def _object(module):
    return _lint({"Склады/Склады.yaml": CATALOG_YAML, "Склады/Склады.Объект.xbsl": module})


@pytest.mark.needs_data
def test_the_handlers_of_the_object_module_are_silent(handlers):
    module = "@Обработчик\nметод ПередЗаписью()\n;\n\n@Обработчик\nметод ПриСозданииКопии()\n;\n"
    assert _object(module) == []


@pytest.mark.needs_data
def test_a_method_of_the_object_module_that_overrides_nothing_is_reported(handlers):
    diags = _object("@Обработчик\nметод Пересчитать()\n;\n")
    assert [(d.line, d.col) for d in diags] == [(1, 1)]
    message = diags[0].message
    assert "модуль Справочник.Объект переопределяет только" in message
    assert "ПередЗаписью, ПослеЗаписи, ПриСозданииКопии" in message
    assert diags[0].fix is not None


@pytest.mark.needs_data
def test_the_fix_takes_the_annotation_away(handlers):
    module = "@Обработчик\nметод Пересчитать()\n;\n"
    source = engine.load_text("Склады/Склады.Объект.xbsl", module)
    fixed = fix_source(source, _object(module)).text
    assert fixed == "метод Пересчитать()\n;\n"


@pytest.mark.needs_data
def test_a_near_miss_is_called_a_misspelling_and_left_unfixed(handlers):
    diags = _object("@Обработчик\nметод ПередЗапсью()\n;\n")
    assert len(diags) == 1 and diags[0].fix is None
    assert "Похоже на опечатку в ПередЗаписью" in diags[0].message


@pytest.mark.needs_data
def test_the_record_set_module_of_a_register_is_judged(handlers):
    register = ("ВидЭлемента: РегистрСведений\nИд: 7b4a9e82-0a5d-4d7e-9c2b-1e5f6a7b8c93\n"
                "Имя: ОстаткиСкладов\n")
    files = {"Склады/ОстаткиСкладов.yaml": register,
             "Склады/ОстаткиСкладов.НаборЗаписей.xbsl":
                 "@Обработчик\nметод ПослеЗаписи()\n;\n\n@Обработчик\nметод ПриЗаполнении()\n;\n"}
    diags = _lint(files)
    assert [d.line for d in diags] == [5]
    assert "модуль РегистрСведений.НаборЗаписей" in diags[0].message


@pytest.mark.needs_data
def test_the_own_module_of_a_scheduled_job_is_judged(handlers):
    files = {"Склады/ОчисткаСкладов.yaml": JOB_YAML,
             "Склады/ОчисткаСкладов.xbsl":
                 "@Обработчик\nметод Обработчик()\n;\n\n@Обработчик\nметод Очистить()\n;\n"}
    diags = _lint(files)
    assert [d.line for d in diags] == [5]
    assert "модуль элемента вида ЗапланированноеЗадание переопределяет только Обработчик" \
        in diags[0].message


@pytest.mark.needs_data
def test_a_module_whose_names_come_from_the_description_is_not_judged(handlers):
    """The own module of the catalog takes access handlers from its access settings."""
    processing = ("ВидЭлемента: Обработка\nИд: 8c5b0f93-1b6e-4e8f-8d3c-2f6a7b8c9d04\n"
                  "Имя: ПересчетСкладов\n")
    files = {"Склады/Склады.yaml": CATALOG_YAML,
             "Склады/Склады.xbsl": "@Обработчик\nметод ВычислитьЧтоУгодно()\n;\n",
             "Склады/ПересчетСкладов.yaml": processing,
             "Склады/ПересчетСкладов.Объект.xbsl": "@Обработчик\nметод Пересчитать()\n;\n"}
    assert _lint(files) == []


@pytest.mark.needs_data
def test_a_kind_the_data_does_not_list_is_not_judged(handlers):
    service = ("ВидЭлемента: HttpСервис\nИд: 9d6c1a04-2c7f-4f90-9e4d-3a7b8c9d0e15\n"
               "Имя: СкладыApi\n")
    assert _lint({"Склады/СкладыApi.yaml": service,
                  "Склады/СкладыApi.xbsl": "@Обработчик\nметод Пересчитать()\n;\n"}) == []


@pytest.mark.needs_data
def test_a_module_without_its_element_description_is_not_judged(handlers):
    assert _lint({"Склады/Склады.Объект.xbsl": "@Обработчик\nметод Пересчитать()\n;\n"}) == []


@pytest.mark.needs_data
def test_the_english_spelling_is_read_and_reported_in_english(handlers):
    i18n.set_lang("en")
    catalog = "ElementKind: Catalog\nId: 4d2f7c60-8e3b-4b5c-9a0f-9c3d4e5f6a71\nName: Stock\n"
    module = "@Handler\nmethod BeforeWrite()\n;\n\n@Handler\nmethod Recount()\n;\n"
    diags = _lint({"Stock/Stock.yaml": catalog, "Stock/Stock.Object.xbsl": module})
    assert [d.line for d in diags] == [5]
    assert "the Справочник.Объект module overrides only BeforeWrite, AfterWrite, OnCreateCopy" \
        in diags[0].message


@pytest.mark.needs_data
def test_control_without_the_element_lists_nothing_is_judged(monkeypatch):
    """The negative control: the same module with the section taken away says nothing."""
    _use(monkeypatch, {})
    try:
        assert _object("@Обработчик\nметод Пересчитать()\n;\n") == []
    finally:
        monkeypatch.undo()
        modulehandlers._reset()


@pytest.mark.needs_data
def test_control_the_row_is_what_keeps_the_override_silent(monkeypatch):
    """The same override is reported once its row is taken out of the table."""
    table = {"Справочник": {"Объект": {"handlers": _OBJECT_ROWS[1:], "dynamic": ()}}}
    _use(monkeypatch, table)
    try:
        diags = _object("@Обработчик\nметод ПередЗаписью()\n;\n")
        assert len(diags) == 1 and "ПослеЗаписи, ПриСозданииКопии" in diags[0].message
    finally:
        monkeypatch.undo()
        modulehandlers._reset()


# --- the own module of an entity: the access settings pick the handlers ---------------------

_PERMISSIONS = {"ru": "ВычислитьРазрешенияДоступа", "en": "ComputeAccessPermissions"}
_SECURITY_TABLE = {
    "Справочник": {
        "": {"handlers": (_PERMISSIONS, {"ru": "ПолучитьЗначенияВыбора", "en": "GetChoiceValues"}),
             "dynamic": (modulehandlers.RECORD_SECURITY_SOURCE,)},
    },
    "РегистрСведений": {
        "": {"handlers": (_PERMISSIONS,), "dynamic": (modulehandlers.RECORD_SECURITY_SOURCE,)},
    },
}
_OWN = ("@Обработчик\nметод ВычислитьРазрешенияДоступа(): Массив<РазрешениеДоступа>\n;\n\n"
        "@Обработчик\nметод ВычислитьРазрешенияДоступаДляОбъектов(Объекты: Массив<Склады.Объект>)"
        "\n;\n\n@Обработчик\nметод ПолучитьЗначенияВыбора()\n;\n")
_NOT_USED = "is not used in this project item"
_NOT_FOUND = "A handler associated with method"


@pytest.fixture
def security(monkeypatch):
    """The own modules of a catalog and of an information register take the security names."""
    _use(monkeypatch, _SECURITY_TABLE)
    yield
    monkeypatch.undo()
    _reset()


def _catalog(access: str, module: str = _OWN):
    return _lint({"Склады/Склады.yaml": CATALOG_YAML + access, "Склады/Склады.xbsl": module})


def _found(diags):
    return [(d.line, _NOT_USED in d.message, _NOT_FOUND in d.message) for d in diags]


@pytest.mark.needs_data
def test_without_access_settings_the_access_handlers_are_not_used(security):
    diags = _catalog("")
    assert _found(diags) == [(1, True, False), (5, True, False)]
    assert "только когда настройки вычисляют разрешения (РазрешенияВычисляются" \
        in diags[0].message
    assert "для каждого объекта" in diags[1].message
    assert all(d.fix is None for d in diags)


@pytest.mark.needs_data
def test_computed_permissions_use_the_permissions_handler(security):
    access = "КонтрольДоступа:\n    Разрешения:\n        Чтение: РазрешенияВычисляются\n"
    assert _found(_catalog(access)) == [(5, True, False)]


@pytest.mark.needs_data
def test_permissions_for_each_object_use_both_handlers(security):
    access = ("КонтрольДоступа:\n    Разрешения:\n"
              "        Чтение: РазрешенияВычисляютсяДляКаждогоОбъекта\n")
    assert _catalog(access) == []


@pytest.mark.needs_data
def test_the_default_counts_only_for_a_privilege_left_out(security):
    """Every privilege given its own value: the default the settings name is never read."""
    access = ("КонтрольДоступа:\n    Разрешения:\n"
              "        ПоУмолчанию: РазрешенияВычисляютсяДляКаждогоОбъекта\n"
              "        Создание: РазрешеноАдминистраторам\n        Чтение: РазрешеноВсем\n"
              "        Изменение: РазрешеноАдминистраторам\n"
              "        Удаление: РазрешеноАдминистраторам\n")
    assert _found(_catalog(access)) == [(1, True, False), (5, True, False)]
    left_out = access.replace("        Удаление: РазрешеноАдминистраторам\n", "")
    assert _catalog(left_out) == []


@pytest.mark.needs_data
def test_a_name_the_entity_cannot_declare_is_not_found(security):
    access = ("КонтрольДоступа:\n    Разрешения:\n"
              "        Чтение: РазрешенияВычисляютсяДляКаждогоОбъекта\n")
    diags = _catalog(access, "@Обработчик\nметод ВычислитьКлючиДоступаДляЧтения()\n;\n")
    assert _found(diags) == [(1, False, True)]
    assert "переопределяет только ВычислитьРазрешенияДоступа, ПолучитьЗначенияВыбора, " \
           "ВычислитьРазрешенияДоступаДляОбъектов" in diags[0].message


@pytest.mark.needs_data
def test_a_periodic_register_takes_the_keys_apart(security):
    register = ("ВидЭлемента: РегистрСведений\nИд: 7b4a9e82-0a5d-4d7e-9c2b-1e5f6a7b8c93\n"
                "Имя: ОстаткиСкладов\nПериодичность: Месяц\nКонтрольДоступа:\n"
                "    Разрешения:\n        Чтение: РазрешенияВычисляютсяДляКаждогоОбъекта\n")
    module = ("@Обработчик\nметод ВычислитьКлючиДоступаДляЧтения()\n;\n\n"
              "@Обработчик\nметод ВычислитьРазрешенияДоступаДляОбъектов()\n;\n")
    diags = _lint({"Склады/ОстаткиСкладов.yaml": register,
                   "Склады/ОстаткиСкладов.xbsl": module})
    assert _found(diags) == [(5, False, True)]
    flat = register.replace("Периодичность: Месяц\n", "")
    diags = _lint({"Склады/ОстаткиСкладов.yaml": flat, "Склады/ОстаткиСкладов.xbsl": module})
    assert _found(diags) == [(1, False, True)]


@pytest.mark.needs_data
def test_an_english_project_reads_its_settings_and_is_told_in_english(security):
    i18n.set_lang("en")
    catalog = ("ElementKind: Catalog\nId: 4d2f7c60-8e3b-4b5c-9a0f-9c3d4e5f6a71\nName: Stock\n"
               "AccessControl:\n    Permissions:\n        Read: PermissionsComputed\n")
    module = ("@Handler\nmethod ComputeAccessPermissions(): Array<AccessPermission>\n;\n\n"
              "@Handler\nmethod ComputeAccessPermissionsForObjects()\n;\n")
    diags = _lint({"Stock/Stock.yaml": catalog, "Stock/Stock.xbsl": module})
    assert _found(diags) == [(5, True, False)]
    assert "does not use the ComputeAccessPermissionsForObjects handler" in diags[0].message
    assert "(PermissionsComputedForEachObject)" in diags[0].message


@pytest.mark.needs_data
def test_settings_that_cannot_be_read_use_every_handler_of_the_kind(security):
    access = "КонтрольДоступа:\n    Разрешения:\n        Чтение: РазрешеноКому-то\n"
    diags = _catalog(access, _OWN + "\n@Обработчик\nметод Пересчитать()\n;\n")
    assert _found(diags) == [(13, False, True)]


@pytest.mark.needs_data
def test_control_a_slot_of_another_source_keeps_the_own_module_unjudged(monkeypatch):
    """The negative control: the same catalog, the slot dynamic by another source."""
    table = {"Справочник": {"": {"handlers": (_PERMISSIONS,), "dynamic": ("computeHandlerTerm",)}}}
    _use(monkeypatch, table)
    try:
        assert _catalog("") == []
    finally:
        monkeypatch.undo()
        _reset()


@pytest.mark.needs_data
def test_settings_that_leave_every_handler_off_still_judge_the_module(monkeypatch):
    """A settings storage on the standard permissions and a constants set use no handler."""
    table = {kind: {"": {"handlers": (_PERMISSIONS,),
                         "dynamic": (modulehandlers.RECORD_SECURITY_SOURCE,)}}
             for kind in ("ХранилищеНастроек", "НаборКонстант")}
    _use(monkeypatch, table)
    storage = ("ВидЭлемента: ХранилищеНастроек\nИд: 5e3a8c71-9f4c-4c6d-8b1a-0d4e5f6a7b82\n"
               "Имя: НастройкиСкладов\nКонтрольДоступа:\n    СтандартныеРазрешения: Истина\n"
               "    Разрешения:\n        Чтение: РазрешенияВычисляютсяДляКаждогоОбъекта\n")
    constants = ("ВидЭлемента: НаборКонстант\nИд: 6f4b9d82-0a5d-4d7e-9c2b-1e5f6a7b8c93\n"
                 "Имя: КонстантыСкладов\nКонтрольДоступа:\n    Разрешения:\n"
                 "        Чтение: РазрешенияВычисляются\n")
    try:
        diags = _lint({
            "Склады/НастройкиСкладов.yaml": storage,
            "Склады/НастройкиСкладов.xbsl": "@Обработчик\nметод ВычислитьРазрешенияДоступа()\n;\n"
                                            "\n@Обработчик\nметод Пересчитать()\n;\n",
            "Склады/КонстантыСкладов.yaml": constants,
            "Склады/КонстантыСкладов.xbsl": "@Обработчик\nметод ВычислитьРазрешенияДоступа()\n;\n"
                                            "\n@Обработчик\nметод ВычислитьКлючиДоступаДляЧтения()"
                                            "\n;\n",
        })
        by_file = {(d.path.replace("\\", "/"), d.line): d.message for d in diags}
        assert sorted(by_file) == [("Склады/КонстантыСкладов.xbsl", 5),
                                   ("Склады/НастройкиСкладов.xbsl", 1),
                                   ("Склады/НастройкиСкладов.xbsl", 5)]
        assert "не вычисляют" in by_file[("Склады/КонстантыСкладов.xbsl", 5)]
        assert "при стандартных разрешениях" in by_file[("Склады/НастройкиСкладов.xbsl", 1)]
        nothing = by_file[("Склады/НастройкиСкладов.xbsl", 5)]
        assert "такого обработчика не объявляет" in nothing and _NOT_FOUND in nothing
    finally:
        monkeypatch.undo()
        _reset()


# --- a module that declares nothing, a handler per item, a service, the project --------------

_ON_BASIS = {"ru": "ПриСозданииНаОсновании", "en": "OnCreateOnBasis",
             "per": "RuntimeEntityMetadata.createOnBasisSources"}
_SYSTEM = {"ru": "ВычислитьСистемныеРазрешенияДоступа", "en": "ComputeSystemAccessPermissions"}
_MORE_TABLE = {
    "Справочник": {"Объект": {"handlers": (*_OBJECT_ROWS, _ON_BASIS), "dynamic": ()}},
    "ОбщийМодуль": {"": {"handlers": (), "dynamic": ()}},
    "HttpСервис": {"": {"handlers": (_PERMISSIONS,), "dynamic": ()}},
    "SoapСервис": {"": {"handlers": (_PERMISSIONS,), "dynamic": ()}},
    "Обработка": {"": {"handlers": (_PERMISSIONS,), "dynamic": ()}},
    "Проект": {"": {"handlers": (_SYSTEM,), "dynamic": ()}},
}


@pytest.fixture
def more(monkeypatch):
    """Empty, per-item, service and project slots in place of the data section."""
    _use(monkeypatch, _MORE_TABLE)
    yield
    monkeypatch.undo()
    _reset()


COMMON_YAML = ("ВидЭлемента: ОбщийМодуль\nИд: 2b7e4c10-3d5f-4a6b-8c7d-9e0f1a2b3c4d\n"
               "Имя: РасчетыСкладов\n")


@pytest.mark.needs_data
def test_any_handler_of_a_module_that_declares_nothing_is_not_found(more):
    diags = _lint({"Склады/РасчетыСкладов.yaml": COMMON_YAML,
                   "Склады/РасчетыСкладов.xbsl": "@Обработчик\nметод ПередЗаписью()\n;\n"})
    assert _found(diags) == [(1, False, True)]
    assert "модуль элемента вида ОбщийМодуль такого обработчика не объявляет" \
        in diags[0].message
    assert diags[0].fix is not None


@pytest.mark.needs_data
def test_control_a_module_the_data_does_not_list_stays_unjudged(monkeypatch):
    """The negative control: the same common module once the empty slot is gone."""
    table = {kind: modules for kind, modules in _MORE_TABLE.items() if kind != "ОбщийМодуль"}
    _use(monkeypatch, table)
    try:
        assert _lint({"Склады/РасчетыСкладов.yaml": COMMON_YAML,
                      "Склады/РасчетыСкладов.xbsl": "@Обработчик\nметод ПередЗаписью()\n;\n"}) == []
    finally:
        monkeypatch.undo()
        _reset()


_BASIS = "@Обработчик\nметод ПриСозданииНаОсновании(Основание: ПоступленияТоваров.Ссылка)\n;\n"


@pytest.mark.needs_data
def test_on_create_on_basis_needs_the_types_of_the_description(more):
    diags = _object(_BASIS)
    assert _found(diags) == [(1, False, True)]
    assert "объявляет обработчик ПриСозданииНаОсновании только для типов, которые " \
           "перечисляет свойство СозданиеНаОсновании" in diags[0].message
    assert diags[0].fix is None  # the description lacks the list, not the method its mark
    given = CATALOG_YAML + "СозданиеНаОсновании:\n    - ПоступленияТоваров.Ссылка\n"
    assert _lint({"Склады/Склады.yaml": given, "Склады/Склады.Объект.xbsl": _BASIS}) == []
    empty = CATALOG_YAML + "СозданиеНаОсновании: []\n"
    assert len(_lint({"Склады/Склады.yaml": empty, "Склады/Склады.Объект.xbsl": _BASIS})) == 1


@pytest.mark.needs_data
def test_an_english_description_lists_its_types_too(more):
    i18n.set_lang("en")
    catalog = "ElementKind: Catalog\nId: 4d2f7c60-8e3b-4b5c-9a0f-9c3d4e5f6a71\nName: Stock\n"
    module = "@Handler\nmethod OnCreateOnBasis(Basis: Receipts.Ref)\n;\n"
    diags = _lint({"Stock/Stock.yaml": catalog, "Stock/Stock.Object.xbsl": module})
    assert len(diags) == 1
    assert "declares the OnCreateOnBasis handler only for the types the CreateOnBasis property" \
        in diags[0].message
    listed = catalog + "CreateOnBasis:\n    - Receipts.Ref\n"
    assert _lint({"Stock/Stock.yaml": listed, "Stock/Stock.Object.xbsl": module}) == []


@pytest.mark.needs_data
def test_control_an_unconditional_row_keeps_on_create_on_basis_silent(monkeypatch):
    """The negative control: the same row without `per` is declared whatever the description."""
    plain = {"ru": _ON_BASIS["ru"], "en": _ON_BASIS["en"]}
    _use(monkeypatch, {"Справочник": {"Объект": {"handlers": (*_OBJECT_ROWS, plain),
                                                 "dynamic": ()}}})
    try:
        assert _object(_BASIS) == []
    finally:
        monkeypatch.undo()
        _reset()


SERVICE_YAML = ("ВидЭлемента: HttpСервис\nИд: 9d6c1a04-2c7f-4f90-9e4d-3a7b8c9d0e15\n"
                "Имя: СкладыApi\n")
_COMPUTE = "@Обработчик\nметод ВычислитьРазрешенияДоступа(): Массив<РазрешениеДоступа>\n;\n"


def _service(access: str, yaml: str = SERVICE_YAML, files: dict | None = None):
    stem = "Склады/" + yaml.split("Имя: ", 1)[1].split("\n", 1)[0]
    return _lint({f"{stem}.yaml": yaml + access, f"{stem}.xbsl": _COMPUTE, **(files or {})})


@pytest.mark.needs_data
def test_a_service_uses_the_permissions_handler_by_its_settings(more):
    diags = _service("")
    assert _found(diags) == [(1, True, False)]
    assert "только когда настройки вычисляют разрешения" in diags[0].message
    assert diags[0].fix is None
    call = "КонтрольДоступа:\n    Разрешения:\n        Вызов: РазрешенияВычисляются\n"
    assert _service(call) == []
    default = "КонтрольДоступа:\n    Разрешения:\n        ПоУмолчанию: РазрешенияВычисляются\n"
    assert _service(default) == []
    others = ("КонтрольДоступа:\n    Разрешения:\n        ПоУмолчанию: РазрешенияВычисляются\n"
              "        Вызов: РазрешеноВсем\n")
    assert _found(_service(others)) == [(1, True, False)]


@pytest.mark.needs_data
def test_a_soap_service_and_a_processing_take_the_same_test(more):
    soap = SERVICE_YAML.replace("HttpСервис", "SoapСервис").replace("СкладыApi", "СкладыSoap")
    assert _found(_service("", soap)) == [(1, True, False)]
    processing = ("ВидЭлемента: Обработка\nИд: 8c5b0f93-1b6e-4e8f-8d3c-2f6a7b8c9d04\n"
                  "Имя: ПересчетСкладов\n")
    project = "Ид: 1d1f5c60-0000-4000-8000-000000000f1e\nИмя: Склад\n"
    # A project that states no mode is read in the newest one, where the settings are read.
    assert _found(_service("", processing, {"Проект.yaml": project})) == [(1, True, False)]
    # Below the mode its settings came in, the build does not read them: not judged.
    old = project + "РежимСовместимости: 9.0\n"
    assert _service("", processing, {"Проект.yaml": old}) == []


@pytest.mark.needs_data
def test_control_a_service_without_the_permissions_row_is_judged_as_a_plain_module(monkeypatch):
    """The negative control: a slot without the permissions handler leaves nothing to split."""
    _use(monkeypatch, {"HttpСервис": {"": {"handlers": (), "dynamic": ()}}})
    try:
        assert _found(_service("")) == [(1, False, True)]
    finally:
        monkeypatch.undo()
        _reset()


PROJECT_YAML = "Ид: 1d1f5c60-0000-4000-8000-000000000f1e\nПоставщик: acme\nИмя: Склад\n"
_SYSTEM_MODULE = ("@Обработчик\nметод ВычислитьСистемныеРазрешенияДоступа()"
                  ": Массив<РазрешениеДоступа>\n;\n")


def _project(kind: str = "", module: str = _SYSTEM_MODULE):
    yaml = PROJECT_YAML + (f"ВидПроекта: {kind}\n" if kind else "")
    return _lint({"Проект.yaml": yaml, "Проект.xbsl": module})


@pytest.mark.needs_data
def test_the_module_of_an_application_overrides_the_system_permissions(more):
    assert _project() == []
    assert _project("Приложение") == []
    diags = _project(module="@Обработчик\nметод Пересчитать()\n;\n")
    assert _found(diags) == [(1, False, True)]
    assert "модуль проекта вида Приложение переопределяет только " \
           "ВычислитьСистемныеРазрешенияДоступа" in diags[0].message


@pytest.mark.needs_data
@pytest.mark.parametrize("kind", ["Библиотека", "Расширение"])
def test_the_module_of_a_library_or_an_extension_declares_nothing(more, kind):
    diags = _project(kind)
    assert _found(diags) == [(1, False, True)]
    assert f"модуль проекта вида {kind} такого обработчика не объявляет" in diags[0].message


@pytest.mark.needs_data
def test_an_english_library_is_told_in_english(more):
    i18n.set_lang("en")
    yaml = "Id: 1d1f5c60-0000-4000-8000-000000000f1e\nVendor: acme\nName: Stock\n" \
           "ProjectKind: Library\n"
    module = "@Handler\nmethod ComputeSystemAccessPermissions(): Array<AccessPermission>\n;\n"
    diags = _lint({"Project.yaml": yaml, "Project.xbsl": module})
    assert len(diags) == 1
    assert "the module of a project of kind Library declares no such handler" in diags[0].message


@pytest.mark.needs_data
def test_control_the_project_is_not_judged_without_its_slot_or_with_an_unknown_kind(monkeypatch):
    """The negative controls: data without the module of the project, a kind it does not have."""
    _use(monkeypatch, {kind: modules for kind, modules in _MORE_TABLE.items() if kind != "Проект"})
    try:
        assert _project("Библиотека") == []
    finally:
        monkeypatch.undo()
        _reset()
    _use(monkeypatch, _MORE_TABLE)
    try:
        assert _project("Сервис") == []
    finally:
        monkeypatch.undo()
        _reset()


@pytest.mark.needs_data
def test_control_an_element_named_like_the_project_is_no_project_module(more):
    """The negative control: a catalog that bears the name of the project description."""
    catalog = "ВидЭлемента: Справочник\nИд: 3c8f5d21-4e6a-4b7c-9d8e-0f1a2b3c4d5e\nИмя: Проект\n"
    assert _lint({"Склады/Проект.yaml": catalog,
                  "Склады/Проект.xbsl": "@Обработчик\nметод Пересчитать()\n;\n"}) == []
