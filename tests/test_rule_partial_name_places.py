"""yaml/wrong-namespace and code/wrong-namespace judge a partial name of an element in several places.

The compiler looks for `Подсистема[::Пакет]::Имя` in the namespace the qualifiers spell and
nowhere else. The IDE server answered it on a probe project: with a catalog at the root of a
subsystem and a namesake in its package, `Подсистема::Имя` compiled clean as the catalog of the
root; with two namesakes in two packages and none at the root, the same partial name was an
unknown type in yaml and in a module, an unknown table in a query and in a dynamic list, and a
dictionary that is not found in a localization reference. The rules used to leave a partial name
of an element in several places alone, "which of the places was meant" being open - but the
compiler never asks that question.

The finding lists the places and carries no edit: which of them the author meant is still theirs.

The fixture is the project `Демо::Учет`: subsystem `Склад` keeps a catalog `Двойники` at its root
and in its package `Партии`, a catalog `Тройники` and a dictionary in the packages `Партии` and
`Архив`; subsystem `Продажи` uses `Склад`. The yaml side runs in every checkout; the code side
tokenizes the module and needs the language data.
"""

import pytest

from xbsl import cli, engine, i18n

YAML_RULE = "yaml/wrong-namespace"
CODE_RULE = "code/wrong-namespace"
BASE = "Демо/Учет"


def _catalog(name: str) -> str:
    return f"ВидЭлемента: Справочник\nИмя: {name}\nОбластьВидимости: ВПроекте\n"


def _dictionary(name: str) -> str:
    return f"ВидЭлемента: ЛокализованныеСтроки\nИмя: {name}\nОбластьВидимости: ВПроекте\n"


def _project(extra: dict[str, str]) -> dict[str, str]:
    files = {
        "Проект.yaml": "Поставщик: Демо\nИмя: Учет\nВерсия: 1.0.0\n",
        "Склад/Подсистема.yaml": "Интерфейс:\n    ВключатьВАвтоИнтерфейс: Ложь\n",
        "Склад/Двойники.yaml": _catalog("Двойники"),
        "Склад/Партии/Двойники.yaml": _catalog("Двойники"),
        "Склад/Партии/Тройники.yaml": _catalog("Тройники"),
        "Склад/Архив/Тройники.yaml": _catalog("Тройники"),
        "Склад/Партии/ПодписиСклада.yaml": _dictionary("ПодписиСклада"),
        "Склад/Архив/ПодписиСклада.yaml": _dictionary("ПодписиСклада"),
        "Продажи/Подсистема.yaml": "Использование:\n    - Склад\n",
        **extra,
    }
    return {f"{BASE}/{name}": text for name, text in files.items()}


def _card(type_text: str) -> str:
    return (
        "ВидЭлемента: КомпонентИнтерфейса\nИмя: КарточкаЗаказа\n"
        "Наследует:\n    Тип: Группа\nСвойства:\n    -\n        Имя: Товар\n"
        f"        Тип: {type_text}\n"
    )


def _lint(rule_id: str, files: dict[str, str]):
    sources = [engine.load_text(name, content) for name, content in files.items()]
    return engine.run_sources(sources, select={rule_id})


# --- yaml -----------------------------------------------------------------------------------------


def test_a_partial_name_of_an_element_in_two_packages_is_reported_without_an_edit():
    diags = _lint(YAML_RULE, _project({"Продажи/КарточкаЗаказа.yaml": _card("Склад::Тройники.Ссылка?")}))
    assert [(d.rule_id, d.line, d.col, d.severity.value) for d in diags] == [(YAML_RULE, 8, 14, "error")]
    message = diags[0].message
    assert "Частичное имя 'Склад::Тройники'" in message
    assert "'Склад::Архив/Склад::Партии'" in message and "Укажите пространство имён" in message
    assert diags[0].fix is None
    assert diags[0].data == {"name": "Тройники", "namespace": "Склад",
                             "namespaces": ["Склад::Архив", "Склад::Партии"]}


def test_a_partial_name_of_an_element_at_the_root_and_in_a_package_names_the_root():
    """The IDE server compiled this one clean: the name leads to the root, and the root holds it."""
    diags = _lint(YAML_RULE, _project({"Продажи/КарточкаЗаказа.yaml": _card("Склад::Двойники.Ссылка?")}))
    assert diags == []


def test_a_package_segment_of_neither_place_is_reported():
    diags = _lint(YAML_RULE, _project({
        "Продажи/КарточкаЗаказа.yaml": _card("Склад::Архив::Двойники.Ссылка?"),
    }))
    assert len(diags) == 1 and diags[0].fix is None
    assert diags[0].data["namespaces"] == ["Склад", "Склад::Партии"]


def test_a_table_of_a_list_and_a_dictionary_in_two_packages_are_reported():
    card = (
        "ВидЭлемента: КомпонентИнтерфейса\nИмя: ПодборТроек\nНаследует:\n"
        "    Тип: Таблица<ДинамическийСписок>\n    Заголовок: $Склад::ПодписиСклада.Заголовок\n"
        "    Источник:\n        ОсновнаяТаблица:\n            Таблица: Склад::Тройники\n"
    )
    diags = _lint(YAML_RULE, _project({"Продажи/ПодборТроек.yaml": card}))
    assert [(d.line, d.col) for d in diags] == [(5, 16), (8, 22)]
    assert all(d.fix is None for d in diags)


def test_the_english_message_of_a_partial_name_in_several_places():
    i18n.set_lang("en")
    try:
        diags = _lint(YAML_RULE, _project({"Продажи/КарточкаЗаказа.yaml": _card("Склад::Тройники.Ссылка?")}))
    finally:
        i18n.set_lang("ru")
    assert len(diags) == 1
    assert "The partial name 'Склад::Тройники'" in diags[0].message
    assert "Name the namespace of the element meant" in diags[0].message


# --- code ----------------------------------------------------------------------------------------


def _module(code: str) -> dict[str, str]:
    return _project({
        "Продажи/Заказы.yaml": "ВидЭлемента: ОбщийМодуль\nИмя: Заказы\n",
        "Продажи/Заказы.xbsl": code,
    })


@pytest.mark.needs_data  # the mapper tokenizes the module: the lexer needs language.json
def test_a_partial_type_and_table_of_an_element_in_two_packages_are_reported_in_code():
    code = (
        "метод Тройка(): Склад::Тройники.Ссылка?\n    возврат Неопределено\n;\n\n"
        "метод Тройки()\n    знч Выборка = Запрос{\n        ВЫБРАТЬ Т.Ссылка КАК Ссылка\n"
        "        ИЗ Склад::Тройники КАК Т\n    }.Выполнить()\n;\n\n"
        "метод Двойка(): Склад::Двойники.Ссылка?\n    возврат Неопределено\n;\n"
    )
    diags = _lint(CODE_RULE, _module(code))
    assert [(d.rule_id, d.line, d.col) for d in diags] == [(CODE_RULE, 1, 17), (CODE_RULE, 8, 12)]
    assert all(d.fix is None and "Частичное имя" in d.message for d in diags)


@pytest.mark.needs_data  # the command line refuses to run without the language data
def test_fix_leaves_a_partial_name_of_several_places_as_written(tmp_path):
    files = _module("метод Тройка(): Склад::Тройники.Ссылка?\n    возврат Неопределено\n;\n")
    for rel, text in files.items():
        path = tmp_path / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(text.encode("utf-8"))
    target = tmp_path / BASE / "Продажи" / "Заказы.xbsl"
    before = target.read_bytes()
    cli.main([str(tmp_path), "--select", f"{YAML_RULE},{CODE_RULE}", "--no-baseline", "--fix"])
    assert target.read_bytes() == before
