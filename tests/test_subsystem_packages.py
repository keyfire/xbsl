"""Packages of a subsystem in the placement model of the cross-subsystem rules.

An element of a package lives in the package's own namespace, `Подсистема::Пакет`. Within
one subsystem the root and the packages see each other without an import, but across a
subsystem boundary the package is imported by its own name: `импорт Склад` does not bring
the elements of `Склад::Партии`, and the compiler refuses the reference with
`Пространство имен "...::Склад::Партии" не импортировано` (a server build, 13.09.2026). The
model used to key every element by its subsystem alone, so `импорт Склад` covered a package
element and the rules stayed silent while the apply failed.

The fixtures are one project, `Демо::Учет`: subsystem `Склад` keeps a catalog at its root, a
package `Партии` with a catalog and a common module, and a nested package `Партии::Архив`;
subsystem `Продажи` uses `Склад`.

The mappers of the code rules tokenize and parse the module, so those tests carry
`needs_data` (the lexer needs language.json); the yaml shapes and the model itself run in
every checkout.
"""

from pathlib import Path

import pytest

from xbsl import engine, i18n
from xbsl.layout import Layout, package_of, service_dirs

MISSING_CODE = "code/missing-import"
MISSING_YAML = "yaml/missing-import"
UNUSED = "code/unused-import"
YAML_VISIBILITY = "yaml/foreign-not-public"
CODE_VISIBILITY = "code/foreign-not-public"
USAGE = "yaml/missing-subsystem-usage"
LOCALIZATION = "yaml/localization-missing-import"
SHADOWS = "yaml/property-shadows-module"

BASE = "Демо/Учет"
PROJECT = "Поставщик: Демо\nИмя: Учет\nВерсия: 1.0.0\n"
SUB_STOCK = "Интерфейс:\n    ВключатьВАвтоИнтерфейс: Ложь\n"
SUB_SALES = "Использование:\n    - Склад\n"


def _catalog(name: str, scope: str | None = "ВПроекте") -> str:
    head = f"ВидЭлемента: Справочник\nИмя: {name}\n"
    return head + (f"ОбластьВидимости: {scope}\n" if scope else "")


def _module_yaml(name: str, scope: str | None = None) -> str:
    head = f"ВидЭлемента: ОбщийМодуль\nИмя: {name}\n"
    return head + (f"ОбластьВидимости: {scope}\n" if scope else "")


def _project(extra: dict[str, str] | None = None) -> dict[str, str]:
    files = {
        "Проект.yaml": PROJECT,
        "Склад/Подсистема.yaml": SUB_STOCK,
        "Склад/Номенклатура.yaml": _catalog("Номенклатура"),
        "Склад/Партии/ПартииТоваров.yaml": _catalog("ПартииТоваров"),
        "Склад/Партии/РасчетПартий.yaml": _module_yaml("РасчетПартий", "ВПроекте"),
        "Склад/Партии/РасчетПартий.xbsl": "@ВПроекте\nметод Пересчитать()\n;\n",
        "Склад/Партии/Архив/АрхивПартий.yaml": _catalog("АрхивПартий"),
        "Продажи/Подсистема.yaml": SUB_SALES,
        "Продажи/Заказы.yaml": _module_yaml("Заказы"),
    }
    files.update(extra or {})
    return {f"{BASE}/{name}": text for name, text in files.items()}


def _lint(rule_id: str, files: dict[str, str]):
    sources = [engine.load_text(name, content) for name, content in files.items()]
    return engine.run_sources(sources, select={rule_id})


def _rel(diag) -> str:
    """The path of a finding under the project root, forward slashes on any platform."""
    return diag.path.replace("\\", "/").removeprefix(f"{BASE}/")


# --- the placement model --------------------------------------------------------------------


def _model() -> Layout:
    root = Path(BASE)
    return Layout({root: ("Демо", "Учет")}, {root / "Склад": "Склад", root / "Продажи": "Продажи"})


def test_place_reads_the_subsystem_the_package_and_a_nested_package():
    model = _model()
    root = Path(BASE)
    at_root = model.place(root / "Склад" / "Номенклатура.yaml")
    in_package = model.place(root / "Склад" / "Партии" / "ПартииТоваров.yaml")
    nested = model.place(root / "Склад" / "Партии" / "Архив" / "АрхивПартий.yaml")
    assert (at_root.subsystem, at_root.package, at_root.key) == ("Склад", None, "Склад")
    assert (in_package.package, in_package.key) == ("Партии", "Склад::Партии")
    assert (nested.package, nested.key) == ("Партии::Архив", "Склад::Партии::Архив")
    assert in_package.subsystem_dir == root / "Склад"


def test_place_keeps_service_folders_out_of_the_package_chain():
    model = _model()
    root = Path(BASE)
    assert "Ресурсы" in service_dirs() and "Resources" in service_dirs()
    assert model.place(root / "Склад" / "Партии" / "Ресурсы" / "Схема.yaml").package == "Партии"
    assert model.place(root / "Склад" / "Ресурсы" / "Схема.yaml").package is None
    assert package_of(["Локализация", "En"]) is None


def test_a_file_in_the_project_root_belongs_to_no_subsystem():
    assert _model().place(Path(BASE) / "Проект.xbsl") is None


def test_a_first_level_folder_is_a_subsystem_without_a_descriptor():
    """A shipped library keeps a subsystem with no descriptor at all: the folder names it."""
    root = Path(BASE)
    model = Layout({root: ("Демо", "Учет")}, {})
    place = model.place(root / "Очередь" / "Сообщения" / "Конверт.yaml")
    assert (place.subsystem, place.package) == ("Очередь", "Сообщения")


def test_the_descriptor_name_wins_over_the_folder_name():
    root = Path(BASE)
    model = Layout({root: ("Демо", "Учет")}, {root / "склад": "Склад"})
    assert model.place(root / "склад" / "Номенклатура.yaml").subsystem == "Склад"


def test_without_a_project_descriptor_the_nearest_subsystem_descriptor_decides():
    model = Layout({}, {Path("Склад"): "Склад"})
    assert model.place(Path("Склад/Партии/ПартииТоваров.yaml")).key == "Склад::Партии"
    assert model.place(Path("Прочее/Файл.yaml")) is None
    assert not Layout().known and model.known


def test_the_own_project_prefix_comes_off_an_import_and_a_foreign_one_stays():
    model = _model()
    root = Path(BASE)
    assert model.local_name("Демо::Учет::Склад::Партии", root) == "Склад::Партии"
    assert model.local_name("Внешний::Проект::Склад", root) == "Внешний::Проект::Склад"
    assert model.resolve(["Демо", "Учет", "Склад", "Партии"], root, {"Склад::Партии"}) \
        == "Склад::Партии"
    assert model.resolve(["Внешний", "Склад", "Партии"], root, {"Склад::Партии"}) is None
    # Without the project the prefix cannot be told apart: the longest known suffix stands.
    assert Layout().resolve(["Демо", "Учет", "Склад"], None, {"Склад"}) == "Склад"


# --- code/missing-import ----------------------------------------------------------------------


@pytest.mark.needs_data  # the mapper parses the module: the lexer needs language.json
def test_a_package_type_needs_the_package_import_in_code():
    """The live case: `импорт Склад` is there, the type lies in `Склад::Партии`."""
    code = "импорт Склад\n\nметод Т(): ПартииТоваров.Ссылка?\n    возврат Неопределено\n;\n"
    diags = _lint(MISSING_CODE, _project({"Продажи/Заказы.xbsl": code}))
    assert [(d.rule_id, _rel(d), d.line) for d in diags] == [
        (MISSING_CODE, "Продажи/Заказы.xbsl", 3)
    ]
    assert "импорт Склад::Партии" in diags[0].message


@pytest.mark.needs_data
def test_the_package_import_covers_the_package_type():
    code = ("импорт Склад::Партии\n\nметод Т(): ПартииТоваров.Ссылка?\n"
            "    возврат Неопределено\n;\n")
    assert _lint(MISSING_CODE, _project({"Продажи/Заказы.xbsl": code})) == []


@pytest.mark.needs_data
def test_the_full_form_of_the_package_import_covers_it_as_well():
    code = ("импорт Демо::Учет::Склад::Партии\n\nметод Т(): ПартииТоваров.Ссылка?\n"
            "    возврат Неопределено\n;\n")
    assert _lint(MISSING_CODE, _project({"Продажи/Заказы.xbsl": code})) == []


@pytest.mark.needs_data
def test_a_package_import_does_not_bring_the_subsystem_root():
    """The other direction: the root element still needs `импорт Склад`."""
    code = ("импорт Склад::Партии\n\nметод Т(): Номенклатура.Ссылка?\n"
            "    возврат Неопределено\n;\n")
    diags = _lint(MISSING_CODE, _project({"Продажи/Заказы.xbsl": code}))
    assert len(diags) == 1 and "импорт Склад'" in diags[0].message


@pytest.mark.needs_data
def test_a_nested_package_needs_its_own_import():
    code = ("импорт Склад::Партии\n\nметод Т(): АрхивПартий.Ссылка?\n"
            "    возврат Неопределено\n;\n")
    diags = _lint(MISSING_CODE, _project({"Продажи/Заказы.xbsl": code}))
    assert len(diags) == 1 and "импорт Склад::Партии::Архив" in diags[0].message
    covered = code.replace("импорт Склад::Партии\n", "импорт Склад::Партии::Архив\n")
    assert _lint(MISSING_CODE, _project({"Продажи/Заказы.xbsl": covered})) == []


@pytest.mark.needs_data
def test_a_call_of_a_package_module_names_the_package_import():
    code = "импорт Склад\n\nметод Т()\n    РасчетПартий.Пересчитать()\n;\n"
    diags = _lint(MISSING_CODE, _project({"Продажи/Заказы.xbsl": code}))
    assert [d.line for d in diags] == [4]
    assert "РасчетПартий.Пересчитать" in diags[0].message
    assert "импорт Склад::Партии" in diags[0].message


@pytest.mark.needs_data
def test_the_root_and_the_packages_of_one_subsystem_need_no_import():
    """Within a subsystem short names resolve both ways without an import (the probe showed
    it), package to package included."""
    files = _project({
        "Склад/Остатки.yaml": _module_yaml("Остатки"),
        "Склад/Остатки.xbsl": "метод Т(): ПартииТоваров.Ссылка?\n    возврат Неопределено\n;\n",
        "Склад/Партии/Сверка.yaml": _module_yaml("Сверка"),
        "Склад/Партии/Сверка.xbsl": (
            "метод Т(): Номенклатура.Ссылка?\n    возврат Неопределено\n;\n"
            "метод П(): АрхивПартий.Ссылка?\n    возврат Неопределено\n;\n"
        ),
    })
    assert _lint(MISSING_CODE, files) == []


# --- yaml/missing-import ----------------------------------------------------------------------

FORM_HEAD = "ВидЭлемента: КомпонентИнтерфейса\nИмя: ФормаЗаказа\n"
FORM_BODY = (
    "Наследует:\n"
    "    Тип: Группа\n"
    "Реквизиты:\n"
    "    -\n"
    "        Имя: Партия\n"
    "        Тип: ПартииТоваров.Ссылка?\n"
)


def test_a_yaml_import_of_the_subsystem_does_not_cover_a_package_type():
    form = FORM_HEAD + "Импорт:\n    - Склад\n" + FORM_BODY
    diags = _lint(MISSING_YAML, _project({"Продажи/ФормаЗаказа.yaml": form}))
    assert [(d.rule_id, d.line) for d in diags] == [(MISSING_YAML, 10)]
    assert "- Склад::Партии" in diags[0].message


def test_a_yaml_import_of_the_package_covers_its_type():
    form = FORM_HEAD + "Импорт:\n    - Склад::Партии\n" + FORM_BODY
    assert _lint(MISSING_YAML, _project({"Продажи/ФормаЗаказа.yaml": form})) == []


def test_a_yaml_reference_inside_the_subsystem_needs_no_package_import():
    form = FORM_HEAD + FORM_BODY
    assert _lint(MISSING_YAML, _project({"Склад/ФормаЗаказа.yaml": form})) == []


# --- code/unused-import -----------------------------------------------------------------------


@pytest.mark.needs_data  # the mapper tokenizes the module: the lexer needs language.json
def test_a_package_import_is_used_by_an_element_of_the_package():
    code = "импорт Склад::Партии\n\nметод Т()\n    РасчетПартий.Пересчитать()\n;\n"
    assert _lint(UNUSED, _project({"Продажи/Заказы.xbsl": code})) == []


@pytest.mark.needs_data
def test_a_subsystem_import_serving_only_package_elements_is_unused():
    """`импорт Склад` brings the root of the subsystem, and the module mentions none of it."""
    code = ("импорт Склад\nимпорт Склад::Партии\n\nметод Т()\n"
            "    РасчетПартий.Пересчитать()\n;\n")
    diags = _lint(UNUSED, _project({"Продажи/Заказы.xbsl": code}))
    assert [(d.rule_id, d.line) for d in diags] == [(UNUSED, 1)]
    assert "'Склад'" in diags[0].message and "Склад::Партии" in diags[0].message


@pytest.mark.needs_data
def test_both_imports_stay_when_the_root_and_the_package_are_mentioned():
    """The live shape of the probe: the module needs the root and the package alike."""
    code = ("импорт Склад\nимпорт Склад::Партии\n\nметод Т(): Номенклатура.Ссылка?\n"
            "    РасчетПартий.Пересчитать()\n    возврат Неопределено\n;\n")
    assert _lint(UNUSED, _project({"Продажи/Заказы.xbsl": code})) == []


@pytest.mark.needs_data
def test_an_unused_package_import_is_reported():
    code = "импорт Склад\nимпорт Склад::Партии\n\nметод Т(): Номенклатура.Ссылка?\n" \
           "    возврат Неопределено\n;\n"
    diags = _lint(UNUSED, _project({"Продажи/Заказы.xbsl": code}))
    assert [d.line for d in diags] == [2] and "'Склад::Партии'" in diags[0].message


@pytest.mark.needs_data
def test_an_import_of_a_foreign_qualified_namespace_is_left_alone():
    code = "импорт Внешний::Библиотека::Основное\n\nметод Т()\n;\n"
    assert _lint(UNUSED, _project({"Продажи/Заказы.xbsl": code})) == []


# --- the visibility rules ---------------------------------------------------------------------


def _hidden_package_element() -> dict[str, str]:
    return {"Склад/Партии/Закрытый.yaml": _catalog("Закрытый", scope=None)}


def test_a_qualified_yaml_reference_to_a_package_is_judged_by_that_package():
    form = FORM_HEAD + FORM_BODY.replace(
        "ПартииТоваров.Ссылка?", "Склад::Партии::Закрытый.Ссылка?")
    files = _project({**_hidden_package_element(), "Продажи/ФормаЗаказа.yaml": form})
    diags = _lint(YAML_VISIBILITY, files)
    assert [(d.rule_id, d.line) for d in diags] == [(YAML_VISIBILITY, 8)]
    assert "'Склад::Партии'" in diags[0].message


def test_a_qualified_yaml_reference_to_a_public_package_element_is_silent():
    form = FORM_HEAD + FORM_BODY.replace(
        "ПартииТоваров.Ссылка?", "Демо::Учет::Склад::Партии::ПартииТоваров.Ссылка?")
    assert _lint(YAML_VISIBILITY, _project({"Продажи/ФормаЗаказа.yaml": form})) == []


def test_a_package_element_is_not_foreign_to_the_root_of_its_subsystem():
    form = FORM_HEAD + FORM_BODY.replace("ПартииТоваров.Ссылка?", "Закрытый.Ссылка?")
    files = _project({**_hidden_package_element(), "Склад/ФормаЗаказа.yaml": form})
    assert _lint(YAML_VISIBILITY, files) == []


@pytest.mark.needs_data  # the mapper parses the module: the lexer needs language.json
def test_a_qualified_code_reference_to_a_package_is_judged_by_that_package():
    code = ("метод Т(): Склад::Партии::Закрытый.Ссылка?\n    возврат Неопределено\n;\n"
            "метод П(): Склад::Партии::ПартииТоваров.Ссылка?\n    возврат Неопределено\n;\n")
    files = _project({**_hidden_package_element(), "Продажи/Заказы.xbsl": code})
    diags = _lint(CODE_VISIBILITY, files)
    assert [(d.rule_id, d.line) for d in diags] == [(CODE_VISIBILITY, 1)]
    assert "'Склад::Партии'" in diags[0].message


# --- the rules that share the model -----------------------------------------------------------


@pytest.mark.needs_data  # the usage mapper reads the element kinds from the data
def test_a_package_import_asks_for_the_usage_of_its_subsystem():
    form = FORM_HEAD + "Импорт:\n    - Склад::Партии\n" + FORM_BODY
    files = _project({"Продажи/Подсистема.yaml": SUB_STOCK, "Продажи/ФормаЗаказа.yaml": form})
    diags = _lint(USAGE, files)
    assert [(d.rule_id, _rel(d)) for d in diags] == [(USAGE, "Продажи/Подсистема.yaml")]
    assert "'Склад'" in diags[0].message


def test_a_dictionary_of_a_package_needs_the_package_import():
    dictionary = (
        "ВидЭлемента: ЛокализованныеСтроки\nИмя: ПодписиПартий\nОбластьВидимости: ВПроекте\n"
    )
    card = FORM_HEAD + (
        "Импорт:\n    - Склад\nНаследует:\n    Тип: Группа\n"
        "    Заголовок: $ПодписиПартий.Заголовок\n"
    )
    files = _project({"Склад/Партии/ПодписиПартий.yaml": dictionary,
                      "Продажи/ФормаЗаказа.yaml": card})
    diags = _lint(LOCALIZATION, files)
    assert len(diags) == 1 and "'Склад::Партии'" in diags[0].message
    fixed = card.replace("    - Склад\n", "    - Склад::Партии\n")
    assert _lint(LOCALIZATION, _project({"Склад/Партии/ПодписиПартий.yaml": dictionary,
                                         "Продажи/ФормаЗаказа.yaml": fixed})) == []


@pytest.mark.needs_data  # the rule reads the yaml keys and kinds from the metamodel
def test_a_property_shadows_a_module_only_through_the_package_import():
    component = (
        "ВидЭлемента: КомпонентИнтерфейса\nИмя: КарточкаЗаказа\nИмпорт:\n    - {imported}\n"
        "Наследует:\n    Тип: Группа\nСвойства:\n    -\n        Имя: РасчетПартий\n"
        "        Тип: Строка\n"
    )
    through_package = _project({"Продажи/КарточкаЗаказа.yaml":
                                component.format(imported="Склад::Партии")})
    assert [d.rule_id for d in _lint(SHADOWS, through_package)] == [SHADOWS]
    through_root = _project({"Продажи/КарточкаЗаказа.yaml": component.format(imported="Склад")})
    assert _lint(SHADOWS, through_root) == []


def test_the_english_message_spells_the_import_line_in_english():
    form = FORM_HEAD + "Импорт:\n    - Склад\n" + FORM_BODY
    i18n.set_lang("en")
    try:
        diags = _lint(MISSING_YAML, _project({"Продажи/ФормаЗаказа.yaml": form}))
    finally:
        i18n.set_lang("ru")
    assert "namespace 'Склад::Партии'" in diags[0].message
