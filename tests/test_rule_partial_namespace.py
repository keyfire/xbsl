"""yaml/wrong-namespace and code/wrong-namespace judge the partial name as well.

`Подсистема[::Пакет]::Имя` is the full name without the prefix of the project, and a move of the
element into a package leaves it leading where the element is no more. A server build refused
such a name in every position it was tried in - a type of a yaml property, a type and a query
table of a module, the table of a dynamic list - and compiled the same names with the segment of
the package. The rules used to judge the full form alone.

The fixture is the project `Демо::Учет`: subsystem `Склад` keeps a catalog at its root and a
package `Партии` with a catalog, its list form and a dictionary; subsystem `Продажи` uses
`Склад`. The yaml side runs in every checkout; the code side tokenizes the module and needs the
language data.
"""

import zipfile

import pytest

from xbsl import cli, engine, i18n

YAML_RULE = "yaml/wrong-namespace"
CODE_RULE = "code/wrong-namespace"
BASE = "Демо/Учет"
PROJECT = "Поставщик: Демо\nИмя: Учет\nВерсия: 1.0.0\n"


def _catalog(name: str) -> str:
    return f"ВидЭлемента: Справочник\nИмя: {name}\nОбластьВидимости: ВПроекте\n"


def _project(extra: dict[str, str] | None = None, *, descriptor: str = PROJECT) -> dict[str, str]:
    files = {
        "Проект.yaml": descriptor,
        "Склад/Подсистема.yaml": "Интерфейс:\n    ВключатьВАвтоИнтерфейс: Ложь\n",
        "Склад/Номенклатура.yaml": _catalog("Номенклатура"),
        "Склад/Партии/ПартииТоваров.yaml": _catalog("ПартииТоваров"),
        "Склад/Партии/ПодписиПартий.yaml": (
            "ВидЭлемента: ЛокализованныеСтроки\nИмя: ПодписиПартий\nОбластьВидимости: ВПроекте\n"
        ),
        "Продажи/Подсистема.yaml": "Использование:\n    - Склад\n",
    }
    files.update(extra or {})
    return {f"{BASE}/{name}": text for name, text in files.items()}


def _card(type_text: str, extra: str = "") -> str:
    """A component of subsystem Продажи with one property of the given type."""
    return (
        "ВидЭлемента: КомпонентИнтерфейса\nИмя: КарточкаЗаказа\n" + extra
        + "Наследует:\n    Тип: Группа\nСвойства:\n    -\n        Имя: Партия\n"
        f"        Тип: {type_text}\n"
    )


def _lint(rule_id: str, files: dict[str, str]):
    sources = [engine.load_text(name, content) for name, content in files.items()]
    return engine.run_sources(sources, select={rule_id}), {s.rel: s for s in sources}


def _rel(diag) -> str:
    return diag.path.replace("\\", "/").removeprefix(f"{BASE}/")


def _write(root, files: dict[str, str], newline: str = "\n"):
    for rel, text in files.items():
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(text.replace("\n", newline).encode("utf-8"))


# --- yaml -------------------------------------------------------------------------------------------


def test_a_partial_name_without_the_package_segment_is_reported_with_the_repair():
    """The position is the compiler's: the start of the name in the value."""
    diags, sources = _lint(YAML_RULE, _project({
        "Продажи/КарточкаЗаказа.yaml": _card("Склад::ПартииТоваров.Ссылка?"),
    }))
    assert [(d.rule_id, _rel(d), d.line, d.col, d.severity.value) for d in diags] == [
        (YAML_RULE, "Продажи/КарточкаЗаказа.yaml", 8, 14, "error")
    ]
    assert "Частичное имя 'Склад::ПартииТоваров'" in diags[0].message
    assert "'Склад::Партии'" in diags[0].message
    fix = diags[0].fix
    assert sources[diags[0].path].text[fix.start:fix.end] == "Склад" and fix.new == "Склад::Партии"
    assert diags[0].data == {"name": "ПартииТоваров", "namespace": "Склад",
                             "namespaces": ["Склад::Партии"]}


def test_the_row_type_of_a_moved_list_form_is_reported_in_the_partial_form():
    form = (
        "ВидЭлемента: КомпонентИнтерфейса\nИмя: ПартииТоваровФормаСписка\nНаследует:\n"
        "    Тип: ФормаСписка<Склад::ПартииТоваровФормаСписка.ДанныеСтрокиСписка>\n"
    )
    diags, sources = _lint(YAML_RULE, _project({"Склад/Партии/ПартииТоваровФормаСписка.yaml": form}))
    assert len(diags) == 1
    fix = diags[0].fix
    assert sources[diags[0].path].text[fix.start:fix.end] == "Склад" and fix.new == "Склад::Партии"


def test_the_partial_name_with_the_package_segment_is_silent():
    diags, _ = _lint(YAML_RULE, _project({
        "Продажи/КарточкаЗаказа.yaml": _card("Склад::Партии::ПартииТоваров.Ссылка?"),
    }))
    assert diags == []


def test_a_package_segment_the_element_left_is_reported():
    diags, sources = _lint(YAML_RULE, _project({
        "Продажи/КарточкаЗаказа.yaml": _card("Склад::Партии::Номенклатура.Ссылка?"),
    }))
    assert len(diags) == 1
    fix = diags[0].fix
    assert sources[diags[0].path].text[fix.start:fix.end] == "Склад::Партии" and fix.new == "Склад"


def test_a_table_of_a_dynamic_list_is_read():
    card = (
        "ВидЭлемента: КомпонентИнтерфейса\nИмя: ПодборПартий\nНаследует:\n"
        "    Тип: Таблица<ДинамическийСписок>\n    Источник:\n        ОсновнаяТаблица:\n"
        "            Таблица: Склад::ПартииТоваров\n"
    )
    diags, _ = _lint(YAML_RULE, _project({"Продажи/ПодборПартий.yaml": card}))
    assert [(d.line, d.col) for d in diags] == [(7, 22)]


def test_a_localization_reference_by_a_partial_name_is_read():
    """The finding is marked from the `$` of the reference; the repair starts at the name."""
    card = (
        "ВидЭлемента: КомпонентИнтерфейса\nИмя: КарточкаЗаказа\nНаследует:\n    Тип: Группа\n"
        "    Заголовок: $Склад::ПодписиПартий.Заголовок\n"
    )
    diags, sources = _lint(YAML_RULE, _project({"Продажи/КарточкаЗаказа.yaml": card}))
    assert [(d.line, d.col) for d in diags] == [(5, 16)]
    fix = diags[0].fix
    assert sources[diags[0].path].text[fix.start:fix.end] == "Склад" and fix.new == "Склад::Партии"


def test_a_first_qualifier_that_is_no_subsystem_is_left_alone():
    for type_text in ("Партии::ПартииТоваров.Ссылка?", "Стд::Массив<Строка>",
                      "Внешний::ПартииТоваров.Ссылка?", "Учет::Склад::ПартииТоваров.Ссылка?"):
        diags, _ = _lint(YAML_RULE, _project({"Продажи/КарточкаЗаказа.yaml": _card(type_text)}))
        assert diags == [], type_text


def test_a_chain_that_spells_a_package_whole_names_the_namespace():
    """A catalog named like its package: the chain is the package, not a misplaced catalog."""
    card = _card("Строка", extra="Описание: Склад::Партии\nПодсказка: Демо::Учет::Склад::Партии\n")
    diags, _ = _lint(YAML_RULE, _project({
        "Склад/Партии/Партии.yaml": _catalog("Партии"),
        "Продажи/КарточкаЗаказа.yaml": card,
    }))
    assert diags == []


def test_resource_references_and_import_lists_are_not_names():
    extra = (
        "Импорт:\n    - Склад::ПартииТоваров\n"
        "Изображение: Склад::ПартииТоваров.svg\nПуть: Склад::ПартииТоваров/Значок.svg\n"
    )
    diags, _ = _lint(YAML_RULE, _project({
        "Продажи/КарточкаЗаказа.yaml": _card("Склад::Партии::ПартииТоваров.Ссылка?", extra),
    }))
    assert diags == []


def test_the_vendor_as_the_first_qualifier_is_left_alone():
    """A subsystem named like the vendor would read a full name of another project as partial."""
    diags, _ = _lint(YAML_RULE, _project({
        "Демо/Подсистема.yaml": "Интерфейс:\n    ВключатьВАвтоИнтерфейс: Ложь\n",
        "Демо/Приемка/Товары.yaml": _catalog("Товары"),
        "Продажи/КарточкаЗаказа.yaml": _card("Демо::Товары.Ссылка?"),
    }))
    assert diags == []


def test_a_subsystem_a_library_also_keeps_is_left_alone(tmp_path):
    descriptor = PROJECT + (
        "Библиотеки:\n    -\n        Поставщик: Внешний\n        Имя: Библиотека\n"
        "        Версия: 2.0.0\n"
    )
    _write(tmp_path, _project({"Продажи/КарточкаЗаказа.yaml": _card("Склад::ПартииТоваров.Ссылка?")},
                              descriptor=descriptor))
    with zipfile.ZipFile(tmp_path / "Внешний-Библиотека-2.0.0.xlib", "w") as archive:
        archive.writestr("Внешний/Библиотека/Проект.yaml", "Поставщик: Внешний\nИмя: Библиотека\n")
        archive.writestr("Внешний/Библиотека/Склад/Товары.yaml", _catalog("Товары"))
    paths = engine.find_sources(tmp_path, "*.yaml")
    assert engine.run(paths, select={YAML_RULE}) == []
    # The control: a library that keeps another subsystem leaves the name judged.
    (tmp_path / "Внешний-Библиотека-2.0.0.xlib").unlink()
    with zipfile.ZipFile(tmp_path / "Внешний-Библиотека-2.0.0.xlib", "w") as archive:
        archive.writestr("Внешний/Библиотека/Доставка/Товары.yaml", _catalog("Товары"))
    assert [d.rule_id for d in engine.run(paths, select={YAML_RULE})] == [YAML_RULE]


def test_a_library_whose_archive_is_missing_leaves_partial_names_alone():
    descriptor = PROJECT + (
        "Библиотеки:\n    -\n        Поставщик: Внешний\n        Имя: НетАрхива\n"
        "        Версия: 1.0.0\n"
    )
    card = _card("Склад::ПартииТоваров.Ссылка?").replace(
        "Свойства:", "Свойства:\n    -\n        Имя: Товар\n"
        "        Тип: Демо::Учет::Склад::ПартииТоваров.Ссылка?")
    diags, _ = _lint(YAML_RULE, _project({"Продажи/КарточкаЗаказа.yaml": card},
                                         descriptor=descriptor))
    # The full name is still judged; the partial one is not.
    assert [d.message.split("'")[1] for d in diags] == ["Демо::Учет::Склад::ПартииТоваров"]


def test_the_english_message_of_a_partial_name():
    i18n.set_lang("en")
    try:
        diags, _ = _lint(YAML_RULE, _project({
            "Продажи/КарточкаЗаказа.yaml": _card("Склад::ПартииТоваров.Ссылка?"),
        }))
    finally:
        i18n.set_lang("ru")
    assert len(diags) == 1
    assert "The partial name 'Склад::ПартииТоваров'" in diags[0].message
    assert "The prefix must be 'Склад::Партии::'" in diags[0].message


# --- code -------------------------------------------------------------------------------------------


def _module(code: str, name: str = "Заказы") -> dict[str, str]:
    return _project({
        f"Продажи/{name}.yaml": f"ВидЭлемента: ОбщийМодуль\nИмя: {name}\n",
        f"Продажи/{name}.xbsl": code,
    })


@pytest.mark.needs_data  # the mapper tokenizes the module: the lexer needs language.json
def test_a_partial_type_and_a_partial_query_table_are_reported_in_code():
    code = (
        "метод Партия(): Склад::ПартииТоваров.Ссылка?\n    возврат Неопределено\n;\n\n"
        "метод Партии()\n    знч Выборка = Запрос{\n        ВЫБРАТЬ П.Ссылка КАК Ссылка\n"
        "        ИЗ Склад::ПартииТоваров КАК П\n    }.Выполнить()\n;\n"
    )
    diags, sources = _lint(CODE_RULE, _module(code))
    assert [(d.rule_id, _rel(d), d.line, d.col) for d in diags] == [
        (CODE_RULE, "Продажи/Заказы.xbsl", 1, 17), (CODE_RULE, "Продажи/Заказы.xbsl", 8, 12),
    ]
    for diag in diags:
        fix = diag.fix
        assert sources[diag.path].text[fix.start:fix.end] == "Склад"
        assert fix.new == "Склад::Партии"


@pytest.mark.needs_data
def test_imports_resources_strings_and_right_partial_names_are_silent_in_code():
    code = (
        "импорт Склад::Партии\n\n"
        "метод Т()\n"
        "    знч Значок = Ресурс{Склад::ПартииТоваров.svg}\n"
        '    знч Текст = "Склад::ПартииТоваров"\n'
        "    // Склад::ПартииТоваров\n"
        "    знч Ссылка: Склад::Партии::ПартииТоваров.Ссылка? = Неопределено\n"
        "    знч Номер: Склад::Номенклатура.Ссылка? = Неопределено\n"
        ";\n"
    )
    diags, _ = _lint(CODE_RULE, _module(code))
    assert diags == []


@pytest.mark.needs_data
def test_a_standalone_query_with_a_partial_table():
    files = _project({
        "Продажи/ОстаткиПартий.yaml": "ВидЭлемента: ВиртуальнаяТаблица\nИмя: ОстаткиПартий\n",
        "Продажи/ОстаткиПартий.xbql": "ВЫБРАТЬ П.Ссылка КАК Ссылка\nИЗ Склад::ПартииТоваров КАК П\n",
    })
    diags, _ = _lint(CODE_RULE, files)
    assert [(_rel(d), d.line, d.col) for d in diags] == [("Продажи/ОстаткиПартий.xbql", 2, 4)]


@pytest.mark.needs_data  # the command line refuses to run without the language data
def test_fix_rewrites_partial_names_on_disk(tmp_path):
    """--fix on a copy, both line endings: the stale names take the segment, the rest stays."""
    stale, right = "Склад::ПартииТоваров", "Склад::Партии::ПартииТоваров"
    code = (
        f"метод Партия(): {stale}.Ссылка?\n    возврат Неопределено\n;\n"
        f"метод Другая(): {right}.Ссылка?\n    возврат Неопределено\n;\n"
    )
    for newline in ("\n", "\r\n"):
        root = tmp_path / ("crlf" if newline == "\r\n" else "lf")
        files = _module(code)
        files[f"{BASE}/Продажи/КарточкаЗаказа.yaml"] = _card(f"{stale}.Ссылка?")
        _write(root, files, newline)
        targets = [root / BASE / "Продажи" / "Заказы.xbsl", root / BASE / "Продажи" / "КарточкаЗаказа.yaml"]
        before = [path.read_bytes().decode("utf-8") for path in targets]
        cli.main([str(root), "--select", f"{YAML_RULE},{CODE_RULE}", "--no-baseline", "--fix"])
        after = [path.read_bytes().decode("utf-8") for path in targets]
        for old, new in zip(before, after):
            assert new == old.replace(f"{stale}.", f"{right}."), newline
