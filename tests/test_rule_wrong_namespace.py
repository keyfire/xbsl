"""yaml/wrong-namespace and code/wrong-namespace: a full name that outlived a move of its element.

`Поставщик::Проект::Подсистема[::Пакет]::Имя` names the placement of the element outright, so a
move of the element into a package leaves every such name leading to a namespace where the
element is no more, and the build answers `Неизвестный тип`. The live case was a list form moved
into a package with its row type still spelled by the subsystem alone.

The fixture is the project `Демо::Учет`: subsystem `Склад` keeps a catalog at its root and a
package `Партии` with a catalog and its list form. The yaml side runs in every checkout; the code
side tokenizes the module and needs the language data.
"""

import pytest

from xbsl import cli, engine, i18n

YAML_RULE = "yaml/wrong-namespace"
CODE_RULE = "code/wrong-namespace"

BASE = "Демо/Учет"
ROW = "ПартииТоваровФормаСписка.ДанныеСтрокиСписка"


def _catalog(name: str) -> str:
    return f"ВидЭлемента: Справочник\nИмя: {name}\nОбластьВидимости: ВПроекте\n"


def _form(row_type: str, extra: str = "") -> str:
    return (
        "ВидЭлемента: КомпонентИнтерфейса\nИмя: ПартииТоваровФормаСписка\n" + extra
        + "Наследует:\n    Тип: ФормаСписка<Неопределено>\nРеквизиты:\n    -\n"
        f"        Имя: Список\n        Тип: ДинамическийСписок<{row_type}>\n"
    )


def _project(extra: dict[str, str] | None = None, *, descriptor: bool = True) -> dict[str, str]:
    files = {
        "Склад/Подсистема.yaml": "Интерфейс:\n    ВключатьВАвтоИнтерфейс: Ложь\n",
        "Склад/Номенклатура.yaml": _catalog("Номенклатура"),
        "Склад/Партии/ПартииТоваров.yaml": _catalog("ПартииТоваров"),
    }
    if descriptor:
        files["Проект.yaml"] = "Поставщик: Демо\nИмя: Учет\nВерсия: 1.0.0\n"
    files.update(extra or {})
    return {f"{BASE}/{name}": text for name, text in files.items()}


def _lint(rule_id: str, files: dict[str, str]):
    sources = [engine.load_text(name, content) for name, content in files.items()]
    return engine.run_sources(sources, select={rule_id}), {s.rel: s for s in sources}


def _rel(diag) -> str:
    return diag.path.replace("\\", "/").removeprefix(f"{BASE}/")


def _form_in_package(row_type: str, extra: str = "") -> dict[str, str]:
    return _project({"Склад/Партии/ПартииТоваровФормаСписка.yaml": _form(row_type, extra)})


# --- yaml -------------------------------------------------------------------------------------------


def test_a_row_type_without_the_package_segment_is_reported_with_the_repair():
    """The live case: the form moved into the package, the row type kept the subsystem alone."""
    diags, sources = _lint(YAML_RULE, _form_in_package(f"Демо::Учет::Склад::{ROW}"))
    assert [(d.rule_id, _rel(d), d.line, d.severity.value) for d in diags] == [
        (YAML_RULE, "Склад/Партии/ПартииТоваровФормаСписка.yaml", 8, "error")
    ]
    assert "Демо::Учет::Склад::Партии" in diags[0].message
    source = sources[diags[0].path]
    fix = diags[0].fix
    assert source.text[fix.start:fix.end] == "Склад" and fix.new == "Склад::Партии"
    assert diags[0].data == {"name": "ПартииТоваровФормаСписка", "namespace": "Склад",
                             "namespaces": ["Склад::Партии"]}


def test_the_full_name_that_spells_the_package_is_silent():
    diags, _ = _lint(YAML_RULE, _form_in_package(f"Демо::Учет::Склад::Партии::{ROW}"))
    assert diags == []


def test_a_name_that_spells_a_package_the_element_left_is_reported():
    """The move back: a root element written with a package segment."""
    form = _form("Демо::Учет::Склад::Партии::Номенклатура.Ссылка")
    diags, sources = _lint(YAML_RULE, _project({"Склад/Форма.yaml": form}))
    assert len(diags) == 1
    fix = diags[0].fix
    assert sources[diags[0].path].text[fix.start:fix.end] == "Склад::Партии" and fix.new == "Склад"


def test_names_of_another_project_or_nobody_are_left_alone():
    # The partial form is judged as well (tests/test_rule_partial_namespace.py).
    for row_type in (f"Внешний::Проект::Склад::{ROW}", "Демо::Учет::Склад::НетТакого.Ссылка"):
        diags, _ = _lint(YAML_RULE, _form_in_package(row_type))
        assert diags == [], row_type


def test_the_lists_of_namespaces_are_not_names():
    extra = "Импорт:\n    - Демо::Учет::Склад::ПартииТоваров\n"
    diags, _ = _lint(YAML_RULE, _form_in_package(f"Демо::Учет::Склад::Партии::{ROW}", extra))
    assert diags == []


def test_a_resource_reference_is_not_a_name():
    extra = "Изображение: Демо::Учет::Склад::ПартииТоваров.svg\nПуть: Демо::Учет::Склад::ПартииТоваров/Значок.svg\n"
    diags, _ = _lint(YAML_RULE, _form_in_package(f"Демо::Учет::Склад::Партии::{ROW}", extra))
    assert diags == []


def test_two_elements_of_the_name_leave_the_choice_to_the_author():
    files = _project({
        "Склад/Архив/ПартииТоваров.yaml": _catalog("ПартииТоваров"),
        "Склад/Форма.yaml": _form("Демо::Учет::Склад::ПартииТоваров.Ссылка"),
    })
    diags, _ = _lint(YAML_RULE, files)
    assert len(diags) == 1 and diags[0].fix is None
    assert "Демо::Учет::Склад::Архив/Демо::Учет::Склад::Партии" in diags[0].message


def test_a_value_of_the_project_descriptor_is_read():
    files = _project()
    files[f"{BASE}/Проект.yaml"] += "ПриложениеРегистрации: Демо::Учет::Склад::ПартииТоваров\n"
    diags, _ = _lint(YAML_RULE, files)
    assert [(_rel(d), d.line) for d in diags] == [("Проект.yaml", 4)]


def test_a_localization_reference_names_its_dictionary_the_same_way():
    files = _project({
        "Склад/Партии/ПодписиПартий.yaml": (
            "ВидЭлемента: ЛокализованныеСтроки\nИмя: ПодписиПартий\nОбластьВидимости: ВПроекте\n"
        ),
        "Склад/Карточка.yaml": (
            "ВидЭлемента: КомпонентИнтерфейса\nИмя: Карточка\nНаследует:\n    Тип: Группа\n"
            "    Заголовок: $Демо::Учет::Склад::ПодписиПартий.Заголовок\n"
        ),
    })
    diags, _ = _lint(YAML_RULE, files)
    assert len(diags) == 1 and diags[0].line == 5


def test_without_the_project_descriptor_the_prefix_is_unknown():
    files = _project({"Склад/Партии/ПартииТоваровФормаСписка.yaml": _form(f"Демо::Учет::Склад::{ROW}")},
                     descriptor=False)
    diags, _ = _lint(YAML_RULE, files)
    assert diags == []


def test_an_unreadable_element_still_lies_where_the_name_leads():
    """A yaml that does not parse still declares its element at its place."""
    files = _project({
        "Склад/Архив/ПартииТоваров.yaml": "ВидЭлемента: Справочник\nИмя: ПартииТоваров\nРеквизиты: [\n",
        "Склад/Форма.yaml": _form("Демо::Учет::Склад::Архив::ПартииТоваров.Ссылка"),
    })
    diags, _ = _lint(YAML_RULE, files)
    assert diags == []


def test_the_english_message():
    i18n.set_lang("en")
    try:
        diags, _ = _lint(YAML_RULE, _form_in_package(f"Демо::Учет::Склад::{ROW}"))
    finally:
        i18n.set_lang("ru")
    assert len(diags) == 1 and "The prefix must be 'Демо::Учет::Склад::Партии::'" in diags[0].message


@pytest.mark.needs_data  # the command line refuses to run without the language data
def test_fix_rewrites_the_file_on_disk(tmp_path):
    """--fix on a copy: every stale name of the file takes the segment, the rest stays byte-exact."""
    stale = "Демо::Учет::Склад::ПартииТоваровФормаСписка"
    right = "Демо::Учет::Склад::Партии::ПартииТоваровФормаСписка"
    form = _form(f"{stale}.ДанныеСтрокиСписка").replace(
        "Реквизиты:", f"Таблица: \"{stale}\"\nРеквизиты:")
    for newline in ("\n", "\r\n"):
        root = tmp_path / ("crlf" if newline == "\r\n" else "lf")
        files = _form_in_package(f"{stale}.ДанныеСтрокиСписка")
        files[f"{BASE}/Склад/Партии/ПартииТоваровФормаСписка.yaml"] = form
        for rel, text in files.items():
            path = root / rel
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(text.replace("\n", newline).encode("utf-8"))
        target = root / BASE / "Склад" / "Партии" / "ПартииТоваровФормаСписка.yaml"
        before = target.read_bytes().decode("utf-8")
        cli.main([str(root), "--select", YAML_RULE, "--no-baseline", "--fix"])
        after = target.read_bytes().decode("utf-8")
        assert before.count(stale) == 2
        assert after == before.replace(stale, right)


# --- code -------------------------------------------------------------------------------------------


def _module(code: str) -> dict[str, str]:
    return _project({
        "Склад/Отчеты.yaml": "ВидЭлемента: ОбщийМодуль\nИмя: Отчеты\n",
        "Склад/Отчеты.xbsl": code,
    })


@pytest.mark.needs_data  # the mapper tokenizes the module: the lexer needs language.json
def test_a_query_table_written_in_full_is_reported_in_code():
    code = ("метод Т()\n    знч Выборка = Запрос{ВЫБРАТЬ П.Ссылка КАК Ссылка "
            "ИЗ Демо::Учет::Склад::ПартииТоваров КАК П}\n    Выборка.Выполнить()\n;\n")
    diags, sources = _lint(CODE_RULE, _module(code))
    assert [(d.rule_id, _rel(d), d.line, d.col) for d in diags] == [
        (CODE_RULE, "Склад/Отчеты.xbsl", 2, 57)
    ]
    fix = diags[0].fix
    assert sources[diags[0].path].text[fix.start:fix.end] == "Склад" and fix.new == "Склад::Партии"


@pytest.mark.needs_data
def test_a_type_written_in_full_is_reported_in_code():
    code = "метод Т(): Демо::Учет::Склад::Партии::Номенклатура.Ссылка?\n    возврат Неопределено\n;\n"
    diags, _ = _lint(CODE_RULE, _module(code))
    assert [(d.line, d.col) for d in diags] == [(1, 12)]


@pytest.mark.needs_data
def test_imports_resources_strings_and_correct_names_are_silent_in_code():
    code = (
        "импорт Демо::Учет::Склад::ПартииТоваров\n\n"
        "метод Т()\n"
        "    знч Значок = Ресурс{Демо::Учет::Склад::ПартииТоваров.svg}\n"
        '    знч Текст = "Демо::Учет::Склад::ПартииТоваров"\n'
        "    // Демо::Учет::Склад::ПартииТоваров\n"
        "    знч Ссылка: Демо::Учет::Склад::Партии::ПартииТоваров.Ссылка? = Неопределено\n"
        ";\n"
    )
    diags, _ = _lint(CODE_RULE, _module(code))
    assert diags == []


@pytest.mark.needs_data
def test_a_standalone_query_is_read_by_the_code_rule():
    files = _project({
        "Склад/ОстаткиПартий.yaml": "ВидЭлемента: ВиртуальнаяТаблица\nИмя: ОстаткиПартий\n",
        "Склад/ОстаткиПартий.xbql": "ВЫБРАТЬ П.Ссылка КАК Ссылка\nИЗ Демо::Учет::Склад::ПартииТоваров КАК П\n",
    })
    diags, _ = _lint(CODE_RULE, files)
    assert [(_rel(d), d.line) for d in diags] == [("Склад/ОстаткиПартий.xbql", 2)]


def test_both_rules_are_registered_as_project_errors():
    for rule_id in (YAML_RULE, CODE_RULE):
        info = next(r for r in engine.active_rules() if r.id == rule_id)
        assert (info.tier, info.scope, info.severity.value, info.enabled_by_default) == (
            "D", "project", "error", True)
