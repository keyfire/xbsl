"""code/deprecated-api: a call that binds only to forms of a platform method kept for compatibility.

The shapes below are the ones a probe project put through the editor's language server, in two
compatibility modes: each finding is a call the editor warns about, each silent case one it does
not. The table of deprecated forms is written here, in the shape the extractor stores - the rule
is tested on its reading of the table, not on the documentation of a particular build. The types
and members are the platform's own, so the receivers and the arguments are typed by the catalog.
"""

import pytest

from xbsl import engine, i18n
from xbsl.rules import deprecated_api as D

RULE = "code/deprecated-api"

_LOAD_STREAM = "Загрузить(ВходнойПоток: ПотокЧтения, Размер: РазмерБайтов|Число|? = Неопределено): ДвоичныйОбъект"
_LOAD_BYTES = "Загрузить(ИмяФайла: Строка?, Байты: Байты, ТипСодержимого: Строка? = Неопределено): ДвоичныйОбъект"
_LOAD_NAMED_STREAM = ("Загрузить(ИмяФайла: Строка?, ВходнойПоток: ПотокЧтения, Размер: РазмерБайтов|Число|? = "
                      "Неопределено): ДвоичныйОбъект")

TABLE = {
    "ОбъектноеХранилище": {
        "ЗагрузитьИзБайт": [
            {"signature": "ЗагрузитьИзБайт(Байты: Байты, ТипСодержимого: Строка? = Неопределено): ДвоичныйОбъект",
             "deprecated": True, "deprecated_modes": ["8.0", None]},
        ],
        "Загрузить": [
            {"signature": _LOAD_STREAM, "deprecated": True, "deprecated_modes": ["8.0", None]},
            {"signature": _LOAD_BYTES},
            {"signature": _LOAD_NAMED_STREAM},
        ],
    },
    "СериализацияJson": {
        "ПрочитатьОбъект": [
            {"signature": "ПрочитатьОбъект<ТипОбъекта>(Источник: ПотокЧтения|ЧтениеJson|Строка, Настройки: "
                          "НастройкиЧтенияОбъектовJson): ТипОбъекта", "since": "9.0"},
            {"signature": "ПрочитатьОбъект<ТипОбъекта>(Источник: ПотокЧтения|ЧтениеJson|Строка, Тип: "
                          "Тип<ТипОбъекта>, Настройки: НастройкиЧтенияОбъектовJson): ТипОбъекта"},
            {"signature": "ПрочитатьОбъект(Источник: ПотокЧтения|Строка, Тип: Коллекция<Тип>, Настройки: "
                          "НастройкиЧтенияОбъектовJson): Объект?",
             "deprecated": True, "until": "8.0", "deprecated_modes": ["7.0", None], "replacement": "ПрочитатьОбъект"},
        ],
        "ПрочитатьСоответствие": [
            {"signature": "ПрочитатьСоответствие(Источник: ПотокЧтения|Строка): Соответствие<Строка, Объект?>",
             "deprecated": True, "deprecated_modes": ["8.0", None], "replacement": "ПрочитатьОбъект"},
        ],
    },
    "ЧтениеJson": {
        "ПрочитатьСодержимоеКакМассив": [
            {"signature": "ПрочитатьСодержимоеКакМассив(): Массив<Объект?>", "deprecated": True,
             "deprecated_modes": ["9.0", None], "replacement": "ПрочитатьСодержимое"},
        ],
    },
}

@pytest.fixture(autouse=True)
def _table(monkeypatch):
    names = frozenset({"ЗагрузитьИзБайт", "UploadFromBytes", "Upload", "Загрузить", "ПрочитатьОбъект",
                       "ПрочитатьСоответствие", "ПрочитатьСодержимоеКакМассив"})
    monkeypatch.setattr(D, "_deprecated", lambda: (TABLE, names))


def _project(mode: str | None, body: str, params: str = "Текст: Строка, Поток: ПотокЧтения, Данные: Байты",
             extra: dict[str, str] | None = None) -> list:
    files = {
        "Склады/Основное/Остатки.yaml": "ВидЭлемента: ОбщийМодуль\nИмя: Остатки\nОкружение: Сервер\n",
        "Склады/Основное/Остатки.xbsl": f"метод Проверка({params})\n{body};\n",
    }
    if mode is not None:
        files["Склады/Проект.yaml"] = f"Поставщик: Acme\nИмя: Склады\nРежимСовместимости: {mode}\n"
    files.update(extra or {})
    sources = [engine.load_text(name, text) for name, text in files.items()]
    return [d for d in engine.run_sources(sources, select={RULE}) if d.rule_id == RULE]


def _places(found: list) -> list[tuple[int, int]]:
    return [(d.line, d.col) for d in found]


@pytest.mark.needs_data
def test_a_method_deprecated_in_every_form_is_found_at_its_name():
    found = _project("9.0", "    знч Объект = ОбъектноеХранилище.ЗагрузитьИзБайт(Данные)\n")

    assert _places(found) == [(2, 37)]
    assert "ЗагрузитьИзБайт" in found[0].message and "ОбъектноеХранилище" in found[0].message


@pytest.mark.needs_data
def test_the_type_of_an_argument_picks_the_deprecated_overload():
    found = _project("9.0", (
        "    знч Старый = ОбъектноеХранилище.Загрузить(Поток, 10)\n"
        '    знч Новый = ОбъектноеХранилище.Загрузить("файл.txt", Данные)\n'
        "    знч СИменем = ОбъектноеХранилище.Загрузить(Текст, Поток)\n"
        "    знч Пустое = ОбъектноеХранилище.Загрузить(Неопределено, Данные)\n"
    ))

    assert [line for line, _col in _places(found)] == [2]


@pytest.mark.needs_data
def test_a_call_of_a_static_member_types_the_argument():
    found = _project("9.0", "    знч Объект = ОбъектноеХранилище.Загрузить(ПотокЧтения.ИзБайтов(Данные), Данные.Размер())\n")

    assert [line for line, _col in _places(found)] == [2]


@pytest.mark.needs_data
def test_named_arguments_leave_out_the_form_that_needs_a_file_name():
    """A nullable parameter without a printed default must be passed: the named call binds only to
    the deprecated form, the one that starts with the stream."""
    found = _project("9.0", "    знч Объект = ОбъектноеХранилище.Загрузить(ВходнойПоток = Поток, Размер = 5)\n")

    assert [line for line, _col in _places(found)] == [2]


@pytest.mark.needs_data
def test_a_deprecation_applies_from_the_mode_it_names():
    body = "    знч Чтение = новый ЧтениеJson(Текст)\n    знч Массив = Чтение.ПрочитатьСодержимоеКакМассив()\n"

    assert _project("8.0", body) == []
    assert [line for line, _col in _places(_project("9.0", body))] == [3]


@pytest.mark.needs_data
def test_a_mode_the_platform_does_not_support_is_checked_as_the_newest():
    """The build refuses such a project, and the editor checks its code in the newest mode."""
    body = "    знч Чтение = новый ЧтениеJson(Текст)\n    знч Массив = Чтение.ПрочитатьСодержимоеКакМассив()\n"

    assert [line for line, _col in _places(_project("5.0", body))] == [3]


@pytest.mark.needs_data
def test_a_form_of_an_older_version_is_deprecated_only_where_it_exists():
    """One argument binds to the old form while it exists; in a newer mode the generic forms cannot
    infer their type parameter from it, and the editor answers with an error instead."""
    body = "    знч Прочитанное = СериализацияJson.ПрочитатьОбъект(Текст)\n"

    in_old_mode = _project("8.0", body)
    assert [line for line, _col in _places(in_old_mode)] == [2]
    assert _project("9.0", body) == []
    assert _project("8.0", "    знч Массив = СериализацияJson.ПрочитатьОбъект(Текст, Тип<Массив<Число>>)\n") == []


@pytest.mark.needs_data
def test_the_message_names_the_replacement_the_documentation_gives():
    found = _project("8.0", "    знч Карта = СериализацияJson.ПрочитатьСоответствие(Поток)\n")
    old_form = _project("8.0", "    знч Прочитанное = СериализацияJson.ПрочитатьОбъект(Текст)\n")

    assert "'ПрочитатьОбъект'" in found[0].message
    assert found[0].message != old_form[0].message
    assert "ПрочитатьОбъект" in old_form[0].message


@pytest.mark.needs_data
def test_an_english_spelling_is_the_same_call():
    found = _project("9.0", "    знч Объект = ObjectStorage.UploadFromBytes(Данные)\n")

    assert [line for line, _col in _places(found)] == [2]
    i18n.set_lang("en")
    try:
        english = _project("9.0", "    знч Объект = ObjectStorage.UploadFromBytes(Данные)\n")
    finally:
        i18n.set_lang("ru")
    assert "UploadFromBytes" in english[0].message and "ObjectStorage" in english[0].message


@pytest.mark.needs_data
def test_a_project_element_named_like_a_platform_type_is_not_the_platform_type():
    storage = {"Склады/Основное/ОбъектноеХранилище.yaml": "ВидЭлемента: ОбщийМодуль\nИмя: ОбъектноеХранилище\n"
                                                            "Окружение: Сервер\n",
               "Склады/Основное/ОбъектноеХранилище.xbsl": "метод ЗагрузитьИзБайт(Данные: Байты): Число\n"
                                                            "    возврат Данные.Размер()\n;\n"}

    assert _project("9.0", "    знч Размер = ОбъектноеХранилище.ЗагрузитьИзБайт(Данные)\n", extra=storage) == []


@pytest.mark.needs_data
def test_an_unqualified_call_of_a_method_of_the_module_is_not_a_platform_call():
    body = "    знч Размер = ЗагрузитьИзБайт(Данные)\n;\n\nметод ЗагрузитьИзБайт(Данные: Байты): Число\n    возврат 1\n"

    assert _project("9.0", body) == []


@pytest.mark.needs_data
def test_without_the_mode_of_the_project_a_limited_deprecation_decides_nothing():
    assert _project(None, "    знч Чтение = новый ЧтениеJson(Текст)\n    знч М = Чтение.ПрочитатьСодержимоеКакМассив()\n") == []


@pytest.mark.needs_data
def test_a_deprecation_the_data_gives_no_modes_warns_only_in_the_newest_mode(monkeypatch):
    """A catalog extracted from a distribution without the declarations of the members."""
    table = {"ЧтениеJson": {"ПрочитатьСодержимоеКакМассив": [
        {"signature": "ПрочитатьСодержимоеКакМассив(): Массив<Объект?>", "deprecated": True},
    ]}}
    monkeypatch.setattr(D, "_deprecated", lambda: (table, frozenset({"ПрочитатьСодержимоеКакМассив"})))
    newest = max(D._supported_modes())
    older = max(mode for mode in D._supported_modes() if mode < newest)
    body = "    знч Чтение = новый ЧтениеJson(Текст)\n    знч Массив = Чтение.ПрочитатьСодержимоеКакМассив()\n"

    assert [line for line, _col in _places(_project(".".join(map(str, newest)), body))] == [3]
    assert _project(".".join(map(str, older)), body) == []
    assert _project(None, body) == []


@pytest.mark.needs_data
def test_an_unknown_argument_fits_every_parameter():
    """A receiver of an unknown result leaves the overloads open: the call is not judged."""
    found = _project("9.0", "    знч Объект = ОбъектноеХранилище.Загрузить(Неизвестно(), Данные)\n")

    assert found == []


# --- data-free pieces --------------------------------------------------------------------------------


@pytest.mark.parametrize("written, required", [
    ("Строка?", True),
    ("РазмерБайтов|Число|?", True),
    ("Строка", True),
    ("НастройкиЧтенияОбъектовJson", False),
    ("Коллекция<Тип>", False),
])
def test_a_parameter_without_a_printed_default_is_required_only_when_a_default_would_be_printed(written, required):
    assert D._required(D._Param("Параметр", written, False, False)) is required


def test_a_printed_default_or_a_variadic_parameter_is_never_required():
    assert D._required(D._Param("Имя", "Строка?", False, True)) is False
    assert D._required(D._Param("Аргументы", "Объект?", True, False)) is False


def test_a_signature_is_read_into_parameters_and_type_parameters():
    form = D._form("Прочитать<ТипОбъекта>(Источник: Строка, Тип: Тип<ТипОбъекта>, Кодировка: Кодировка|Строка = "
                   "Кодировка.Utf8): ТипОбъекта", True, "", "8.0", ("7.0", ""), "Прочитать")

    assert [(p.name, p.written, p.default) for p in form.params] == [
        ("Источник", "Строка", False), ("Тип", "Тип<ТипОбъекта>", False),
        ("Кодировка", "Кодировка|Строка", True),
    ]
    assert form.type_params == frozenset({"ТипОбъекта"})
    assert form.exists_in((8, 0)) and not form.exists_in((9, 0))
    assert form.deprecated_in((7, 0), (8, 0)) and not form.deprecated_in((6, 0), (8, 0))


def test_a_deprecation_without_stated_modes_holds_in_the_newest_mode_only():
    """The data knows the mark of the documentation and nothing else, and the documentation
    describes the newest mode."""
    form = D._form("Прочитать(): Строка", True, "", "", None, "")

    assert form.deprecated_in((8, 0), (8, 0)) and not form.deprecated_in((7, 0), (8, 0))
    assert not form.deprecated_in((8, 0), None)
    assert form.depends_on_mode()
    assert not D._form("Прочитать(): Строка", True, "", "", ("", ""), "").depends_on_mode()


@pytest.mark.needs_data
@pytest.mark.parametrize("callee", ["ОбъектноеХранилище.Загрузить", "ObjectStorage.Upload"])
def test_named_argument_uses_the_parameters_direct_english_spelling(callee):
    found = _project("9.0", f"    знч Загруженное = {callee}(InputStream = Поток, Size = 5)\n")

    assert [line for line, _col in _places(found)] == [2]


@pytest.mark.needs_data
@pytest.mark.parametrize("member", ["ЗагрузитьИзБайт", "UploadFromBytes"])
def test_comment_between_dot_and_method_name_does_not_hide_the_call(member):
    body = f"    знч Загруженное = ObjectStorage. // continue the call\n        {member}(Данные)\n"
    found = _project("9.0", body)

    assert [line for line, _col in _places(found)] == [3]
