"""Checks of the two cross-subsystem yaml rules: yaml/missing-import (importing a foreign
subsystem) and yaml/foreign-not-public (the foreign element is not public at all)."""

import pytest

from xbsl import dataset, engine
from xbsl.diagnostics import Severity
from xbsl.rules import semantics

RULE = "yaml/missing-import"

# The mini-project layout: subsystem А uses the Товары catalog from subsystem Б.
SUB_A = "Использование:\n    - Б\n"
SUB_B = "Интерфейс:\n    ВключатьВАвтоИнтерфейс: Ложь\n"
GOODS = (
    "ВидЭлемента: Справочник\n"
    "Имя: Товары\n"
    "ОбластьВидимости: ВПроекте\n"
)
FORM_HEAD = (
    "ВидЭлемента: КомпонентИнтерфейса\n"
    "Имя: Форма\n"
)
FORM_BODY = (
    "Наследует:\n"
    "    Тип: Группа\n"
    "Реквизиты:\n"
    "    -\n"
    "        Имя: Товар\n"
    "        Тип: Товары.Ссылка?\n"
)


def _lint(files):
    sources = [engine.load_text(name, content) for name, content in files.items()]
    return engine.run_sources(sources, select={RULE})


def _project(form_yaml, **extra):
    files = {
        "А/Подсистема.yaml": SUB_A,
        "Б/Подсистема.yaml": SUB_B,
        "Б/Товары.yaml": GOODS,
        "А/Форма.yaml": form_yaml,
    }
    files.update(extra)
    return files


def test_rule_registered_project_scope():
    info = next(r for r in engine.active_rules() if r.id == RULE)
    assert info.tier == "D" and info.scope == "project" and info.enabled_by_default


def test_cross_subsystem_with_import_ok():
    form = FORM_HEAD + "Импорт:\n    - Б\n" + FORM_BODY
    assert _lint(_project(form)) == []


def test_cross_subsystem_without_import_flagged():
    diags = _lint(_project(FORM_HEAD + FORM_BODY))
    assert len(diags) == 1
    d = diags[0]
    assert d.rule_id == RULE
    assert "Товары.Ссылка" in d.message and "'Б'" in d.message
    assert d.line == 8  # the line "        Тип: Товары.Ссылка?"


def test_empty_import_section_flagged():
    form = FORM_HEAD + "Импорт:\n" + FORM_BODY  # the section exists but is empty
    assert len(_lint(_project(form))) == 1


def test_import_of_other_subsystem_does_not_cover():
    form = FORM_HEAD + "Импорт:\n    - В\n" + FORM_BODY
    files = _project(form)
    files["В/Подсистема.yaml"] = ""
    assert len(_lint(files)) == 1


def test_generic_argument_flagged():
    form = (
        FORM_HEAD
        + "Наследует:\n"
        + "    Тип: Группа\n"
        + "Свойства:\n"
        + "    -\n"
        + "        Имя: Отбор\n"
        + "        Тип: Массив<Товары.Ссылка>\n"
    )
    diags = _lint(_project(form))
    assert len(diags) == 1 and "Товары" in diags[0].message


def test_two_usages_one_diagnostic():
    form = (
        FORM_HEAD
        + FORM_BODY
        + "    -\n"
        + "        Имя: Аналог\n"
        + "        Тип: Товары.Ссылка\n"
    )
    assert len(_lint(_project(form))) == 1


def test_same_subsystem_no_import_ok():
    form = FORM_HEAD + FORM_BODY
    files = {
        "Б/Подсистема.yaml": SUB_B,
        "Б/Товары.yaml": GOODS,
        "Б/Форма.yaml": form,
    }
    assert _lint(files) == []


def test_private_target_skipped():
    # With ВПодсистеме (and by default) the object is invisible from outside - not a missing import.
    private = "ВидЭлемента: Справочник\nИмя: Товары\nОбластьВидимости: ВПодсистеме\n"
    files = _project(FORM_HEAD + FORM_BODY)
    files["Б/Товары.yaml"] = private
    assert _lint(files) == []

    default = "ВидЭлемента: Справочник\nИмя: Товары\n"
    files["Б/Товары.yaml"] = default
    assert _lint(files) == []


def test_xbsl_import_does_not_cover_yaml():
    # The pitfall: the paired module has the import, but the yaml does not.
    files = _project(FORM_HEAD + FORM_BODY)
    files["А/Форма.xbsl"] = "импорт Б\n"
    assert len(_lint(files)) == 1


def test_own_subsystem_name_wins():
    # The name also exists in its own subsystem - the short name resolves locally, no import needed.
    files = _project(FORM_HEAD + FORM_BODY)
    files["А/Товары.yaml"] = "ВидЭлемента: Справочник\nИмя: Товары\n"
    assert _lint(files) == []


def test_stdlib_collision_skipped(monkeypatch):
    # The name coincides with a stdlib type - without an import it resolves to the standard namespace.
    monkeypatch.setattr(semantics, "_stdlib_names", lambda: frozenset({"Товары"}))
    assert _lint(_project(FORM_HEAD + FORM_BODY)) == []


@pytest.mark.skipif(
    not dataset.available_versions(),
    reason="нет данных Элемента – токенизация модулей недоступна",
)
def test_local_type_collision_skipped():
    # The name coincides with a structure declared in the module - leave the yaml reference alone.
    files = _project(FORM_HEAD + FORM_BODY)
    files["А/Общий.xbsl"] = "структура Товары\n    поле Ссылка: Строка\n;\n"
    files["А/Общий.yaml"] = "ВидЭлемента: ОбщийМодуль\nИмя: Общий\n"
    assert _lint(files) == []


def test_two_foreign_candidates_listed_and_any_import_ok():
    dup = "ВидЭлемента: Справочник\nИмя: Товары\nОбластьВидимости: ВПроекте\n"
    files = _project(FORM_HEAD + FORM_BODY)
    files["В/Подсистема.yaml"] = ""
    files["В/Товары.yaml"] = dup
    diags = _lint(files)
    assert len(diags) == 1 and "'Б/В'" in diags[0].message

    files["А/Форма.yaml"] = FORM_HEAD + "Импорт:\n    - В\n" + FORM_BODY
    assert _lint(files) == []


def test_no_subsystem_layout_skipped():
    files = {
        "Товары.yaml": GOODS,
        "Форма.yaml": FORM_HEAD + FORM_BODY,
    }
    assert _lint(files) == []


def test_qualified_and_binding_values_skipped():
    form = (
        FORM_HEAD
        + "Наследует:\n"
        + "    Тип: Группа\n"
        + "Реквизиты:\n"
        + "    -\n"
        + "        Имя: Товар\n"
        + "        Тип: Б::Товары.Ссылка?\n"
        + "    -\n"
        + "        Имя: Значение\n"
        + "        Тип: =ВычислитьТип()\n"
    )
    assert _lint(_project(form)) == []


# --- yaml/missing-import: binding chain roots -------------------------------------------

MODULE_B = "ВидЭлемента: ОбщийМодуль\nИмя: ЧужойМодуль\nОбластьВидимости: ВПроекте\n"
BINDING_FORM = (
    FORM_HEAD
    + "Наследует:\n"
    + "    Тип: Группа\n"
    + "Содержимое:\n"
    + "    -\n"
    + "        Тип: Надпись\n"
    + "        Имя: Метка\n"
    + "        Значение: =ЧужойМодуль.ОриентацияЭтапов()\n"
)


def _binding_project(form_yaml, **extra):
    files = {
        "А/Подсистема.yaml": SUB_A,
        "Б/Подсистема.yaml": SUB_B,
        "Б/ЧужойМодуль.yaml": MODULE_B,
        "А/Форма.yaml": form_yaml,
    }
    files.update(extra)
    return files


def test_binding_call_of_a_foreign_module_is_reported():
    """The live case: a form markup calls a method of a foreign common module from a
    binding, with no import line - the linter read only the type positions and passed
    the project clean, and the server compiler refused at the price of a full deploy."""
    diags = _lint(_binding_project(BINDING_FORM))
    assert len(diags) == 1
    d = diags[0]
    assert d.rule_id == RULE
    assert "ЧужойМодуль.ОриентацияЭтапов" in d.message and "'Б'" in d.message
    assert (d.line, d.col) == (9, 20)  # the root inside the binding value


def test_binding_with_the_import_is_silent():
    form = BINDING_FORM.replace("Имя: Форма\n", "Имя: Форма\nИмпорт:\n    - Б\n", 1)
    assert _lint(_binding_project(form)) == []


def test_binding_root_declared_in_this_yaml_is_silent():
    # The root is an attribute of the form itself - the markup scope explains it.
    form = (
        FORM_HEAD
        + "Наследует:\n    Тип: Группа\n"
        + "Реквизиты:\n    -\n        Имя: ЧужойМодуль\n        Тип: Строка\n"
        + "Содержимое:\n    -\n        Тип: Надпись\n        Имя: Метка\n"
        + "        Значение: =ЧужойМодуль.Длина()\n"
    )
    assert _lint(_binding_project(form)) == []


@pytest.mark.needs_data  # the mapper parses the paired module: the lexer needs language.json
def test_binding_root_declared_in_the_paired_module_is_silent():
    """The paired module declares the name (a field here) - the markup addresses it
    locally even when a foreign subsystem holds a public element of the same name."""
    form = BINDING_FORM.replace("ЧужойМодуль.ОриентацияЭтапов()", "Кэш.Длина()")
    files = _binding_project(form)
    files["Б/Кэш.yaml"] = "ВидЭлемента: Справочник\nИмя: Кэш\nОбластьВидимости: ВПроекте\n"
    files["А/Форма.xbsl"] = "пер Кэш: Строка\n\nметод Т()\n;\n"
    assert _lint(files) == []


def test_binding_qualified_and_localization_refs_are_not_chains():
    # `Б::ЧужойМодуль.Метод()` relies on the usage declaration and needs no import line;
    # `$ЧужойМодуль.Ключ` is a localization reference - the sibling rule's case.
    form = (
        FORM_HEAD
        + "Наследует:\n    Тип: Группа\n"
        + "Содержимое:\n    -\n        Тип: Надпись\n        Имя: Метка\n"
        + "        Значение: =Б::ЧужойМодуль.Метод() + $ЧужойМодуль.Ключ\n"
    )
    assert _lint(_binding_project(form)) == []


def test_a_plain_string_value_is_not_a_binding():
    form = BINDING_FORM.replace(
        "=ЧужойМодуль.ОриентацияЭтапов()", "Текст про ЧужойМодуль.Метод"
    )
    assert _lint(_binding_project(form)) == []


def test_a_binding_to_a_non_public_foreign_element_is_the_visibility_rules_case():
    """A binding to a NON-public foreign element: no import can help, so this rule stays
    silent and yaml/foreign-not-public reports it - a server build refuses such a binding
    at its position with the same message the type positions get (probe of 02.09.2026)."""
    files = _binding_project(BINDING_FORM)
    files["Б/ЧужойМодуль.yaml"] = "ВидЭлемента: ОбщийМодуль\nИмя: ЧужойМодуль\n"
    assert _lint(files) == []
    diags = _lint_vis(files)
    assert len(diags) == 1
    assert "ЧужойМодуль" in diags[0].message and "'Б'" in diags[0].message
    assert diags[0].line == 9  # the binding line of BINDING_FORM


def test_a_qualified_binding_to_a_non_public_foreign_element_is_reported():
    """`Б::ЧужойМодуль.Метод()` needs no import, but the element must still be public: the
    same probe refused the qualified binding too. The qualified root resolves by the
    subsystem it names - a public namesake elsewhere would not reach it."""
    form = (
        FORM_HEAD
        + "Наследует:\n    Тип: Группа\n"
        + "Содержимое:\n    -\n        Тип: Надпись\n        Имя: Метка\n"
        + "        Значение: =Б::ЧужойМодуль.Метод()\n"
    )
    files = _binding_project(form)
    files["Б/ЧужойМодуль.yaml"] = "ВидЭлемента: ОбщийМодуль\nИмя: ЧужойМодуль\n"
    assert _lint(files) == []
    diags = _lint_vis(files)
    assert len(diags) == 1
    assert "Б::ЧужойМодуль" in diags[0].message and "'Б'" in diags[0].message
    files["Б/ЧужойМодуль.yaml"] = MODULE_B  # public: the qualified form is clean
    assert _lint_vis(files) == []


def test_a_qualified_type_position_names_its_subsystem():
    """`Тип: Б::Товары.Ссылка` does not parse as a plain chain and used to slip through both
    rules; the visibility rule reads it by the subsystem it names."""
    form = FORM_HEAD + FORM_BODY.replace("Товары.Ссылка", "Б::Товары.Ссылка")
    assert "Б::Товары.Ссылка" in form
    files = _project(form)
    files["Б/Товары.yaml"] = "ВидЭлемента: Справочник\nИмя: Товары\n"  # non-public
    diags = _lint_vis(files)
    assert len(diags) == 1
    assert "Б::Товары" in diags[0].message
    files["Б/Товары.yaml"] = GOODS  # public: nothing to say
    assert _lint_vis(files) == []


@pytest.mark.needs_data
def test_a_binding_root_the_paired_module_declares_is_not_a_reference_for_visibility():
    """`=Сводка.Итог()` where the paired module declares `Сводка`: the file explains the
    root, and a non-public foreign namesake is not what the binding reaches."""
    form = BINDING_FORM.replace("ЧужойМодуль.ОриентацияЭтапов()", "Сводка.Итог()")
    files = _binding_project(form)
    files["Б/Сводка.yaml"] = "ВидЭлемента: ОбщийМодуль\nИмя: Сводка\n"  # non-public namesake
    files["А/Форма.xbsl"] = "метод Сводка(): Строка\n    возврат \"\"\n;\n"
    assert _lint_vis(files) == []
    files["А/Форма.xbsl"] = "метод Другое()\n;\n"  # no explanation - the namesake is reached
    assert len(_lint_vis(files)) == 1


def test_a_type_and_a_binding_of_one_subsystem_are_one_diagnostic():
    # The fix is a single import line, so one report per missing subsystem per file.
    form = (
        FORM_HEAD
        + FORM_BODY
        + "Содержимое:\n    -\n        Тип: Надпись\n        Имя: Метка\n"
        + "        Значение: =ЧужойМодуль.Метод()\n"
    )
    files = _binding_project(form)
    files["Б/Товары.yaml"] = GOODS
    assert len(_lint(files)) == 1


# --- yaml/foreign-not-public: the other half of the same boundary -----------------------

VIS_RULE = "yaml/foreign-not-public"

# A navigation command in subsystem А opening a form that lives in subsystem Б.
PANEL = (
    "ВидЭлемента: КомпонентИнтерфейса\n"
    "Имя: Панель\n"
    "Содержимое:\n"
    "    -\n"
    "        Тип: НавигационнаяКоманда\n"
    "        Имя: Команда\n"
    "        ТипФормы: ЦелеваяФорма\n"
)


def _lint_vis(files):
    sources = [engine.load_text(name, content) for name, content in files.items()]
    return engine.run_sources(sources, select={VIS_RULE})


def _nav_project(target: str, **extra):
    files = {
        "А/Подсистема.yaml": SUB_A,
        "Б/Подсистема.yaml": SUB_B,
        "Б/ЦелеваяФорма.yaml": target,
        "А/Панель.yaml": PANEL,
    }
    files.update(extra)
    return files


def test_navigation_target_needs_import_too(tmp_path=None):
    # A navigation target is a reference like any other: a public foreign form still has to be
    # imported. Before this the rule read only `Тип:` and such a panel passed unnoticed.
    target = "ВидЭлемента: КомпонентИнтерфейса\nИмя: ЦелеваяФорма\nОбластьВидимости: ВПроекте\n"
    files = {
        "А/Подсистема.yaml": SUB_A,
        "Б/Подсистема.yaml": SUB_B,
        "Б/ЦелеваяФорма.yaml": target,
        "А/Панель.yaml": PANEL,
    }
    diags = _lint(files)
    assert len(diags) == 1
    assert "ЦелеваяФорма" in diags[0].message and "'Б'" in diags[0].message

    files["А/Панель.yaml"] = PANEL.replace(
        "Имя: Панель\n", "Имя: Панель\nИмпорт:\n    - Б\n", 1
    )
    assert _lint(files) == []


def test_visibility_rule_registered_project_scope():
    info = next(r for r in engine.active_rules() if r.id == VIS_RULE)
    assert info.tier == "D" and info.scope == "project" and info.enabled_by_default
    # error, not warning: the compiler rejects such a project - verified
    assert info.severity is Severity.ERROR


def test_navigation_to_private_foreign_form_flagged():
    # The default (no ОбластьВидимости) is ВПодсистеме - unreachable from А.
    diags = _lint_vis(_nav_project("ВидЭлемента: КомпонентИнтерфейса\nИмя: ЦелеваяФорма\n"))
    assert len(diags) == 1
    d = diags[0]
    assert d.rule_id == VIS_RULE
    assert "ЦелеваяФорма" in d.message and "'Б'" in d.message and "ВПодсистеме" in d.message
    assert d.line == 7  # the line "        ТипФормы: ЦелеваяФорма"


def test_navigation_to_public_foreign_form_ok():
    target = "ВидЭлемента: КомпонентИнтерфейса\nИмя: ЦелеваяФорма\nОбластьВидимости: ВПроекте\n"
    assert _lint_vis(_nav_project(target)) == []


def test_navigation_inside_own_subsystem_ok():
    files = {
        "А/Подсистема.yaml": SUB_A,
        "А/ЦелеваяФорма.yaml": "ВидЭлемента: КомпонентИнтерфейса\nИмя: ЦелеваяФорма\n",
        "А/Панель.yaml": PANEL,
    }
    assert _lint_vis(files) == []


def test_private_target_in_type_position_flagged():
    # Not only navigation: a type reference to a private foreign object is the same error.
    private = "ВидЭлемента: Справочник\nИмя: Товары\nОбластьВидимости: ВПодсистеме\n"
    files = _project(FORM_HEAD + FORM_BODY)
    files["Б/Товары.yaml"] = private
    diags = _lint_vis(files)
    assert len(diags) == 1 and "Товары" in diags[0].message


def test_public_target_is_left_to_the_sibling_rule():
    # Public but not imported: yaml/missing-import's case, not this rule's - no overlap.
    assert _lint_vis(_project(FORM_HEAD + FORM_BODY)) == []


def test_unknown_target_is_silent():
    # A platform form (ФормаЖурналаСобытий) no project element declares - unknown, not wrong.
    panel = PANEL.replace("ЦелеваяФорма", "ФормаЖурналаСобытий")
    files = {
        "А/Подсистема.yaml": SUB_A,
        "Б/Подсистема.yaml": SUB_B,
        "А/Панель.yaml": panel,
    }
    assert _lint_vis(files) == []


def test_visibility_no_subsystem_layout_skipped():
    files = {
        "ЦелеваяФорма.yaml": "ВидЭлемента: КомпонентИнтерфейса\nИмя: ЦелеваяФорма\n",
        "Панель.yaml": PANEL,
    }
    assert _lint_vis(files) == []


# --- code/unused-import ---------------------------------------------------------------

UNUSED = "code/unused-import"


def _lint_unused(files):
    sources = [engine.load_text(name, content) for name, content in files.items()]
    return engine.run_sources(sources, select={UNUSED})


def _module_project(module_code: str, **extra):
    files = {
        "А/Подсистема.yaml": SUB_A,
        "Б/Подсистема.yaml": SUB_B,
        "Б/Товары.yaml": GOODS,
        "А/Модуль.yaml": "ВидЭлемента: ОбщийМодуль\nИмя: Модуль\n",
        "А/Модуль.xbsl": module_code,
    }
    files.update(extra)
    return files


@pytest.mark.needs_data  # the mapper tokenizes the module: the lexer needs language.json
def test_unused_import_is_reported():
    """The live case: a module imports a subsystem its code never mentions."""
    diags = _lint_unused(_module_project("импорт Б\n\nметод Т()\n;\n"))
    assert [(x.rule_id, x.line, x.col) for x in diags] == [(UNUSED, 1, 1)]
    assert "Б" in diags[0].message


@pytest.mark.needs_data  # the mapper tokenizes the module: the lexer needs language.json
def test_an_import_whose_element_is_used_is_silent():
    diags = _lint_unused(_module_project(
        "импорт Б\n\nметод Т(): Товары.Ссылка?\n    возврат Неопределено\n;\n"
    ))
    assert diags == []


@pytest.mark.needs_data  # the mapper tokenizes the module: the lexer needs language.json
def test_a_reference_from_the_paired_yaml_is_not_a_use():
    """The yaml has an import section of its own - a module import does not cover it, and
    that is exactly the shape the rule was written for."""
    diags = _lint_unused(_module_project(
        "импорт Б\n\nметод Т()\n;\n",
        **{"А/Модуль.yaml": "ВидЭлемента: ОбщийМодуль\nИмя: Модуль\n"
                            "Импорт:\n    - Б\nРеквизиты:\n    -\n        Имя: Т\n"
                            "        Тип: Товары.Ссылка?\n"},
    ))
    assert [x.rule_id for x in diags] == [UNUSED]


@pytest.mark.needs_data  # the mapper tokenizes the module: the lexer needs language.json
def test_an_unknown_subsystem_is_not_judged():
    """A library or a typo - the rule has nothing to check the import against."""
    diags = _lint_unused(_module_project("импорт Чужая\n\nметод Т()\n;\n"))
    assert diags == []


@pytest.mark.needs_data  # the mapper tokenizes the module: the lexer needs language.json
def test_without_subsystem_files_the_rule_stands_down():
    files = {"Модуль.yaml": "ВидЭлемента: ОбщийМодуль\nИмя: Модуль\n",
             "Модуль.xbsl": "импорт Б\n\nметод Т()\n;\n"}
    assert _lint_unused(files) == []


# --- code/missing-import ----------------------------------------------------------------

MISSING_CODE = "code/missing-import"


def _lint_missing_code(files):
    sources = [engine.load_text(name, content) for name, content in files.items()]
    return engine.run_sources(sources, select={MISSING_CODE})


def test_missing_code_import_registered_project_scope():
    info = next(r for r in engine.active_rules() if r.id == MISSING_CODE)
    assert info.tier == "D" and info.scope == "project" and info.enabled_by_default


@pytest.mark.needs_data  # the mapper parses the module: the lexer needs language.json
def test_a_foreign_type_without_an_import_is_reported():
    """The live case: the return type names an element of another subsystem, the module
    imports only its own, and the server compiler refuses the project."""
    diags = _lint_missing_code(_module_project(
        "метод Т(): Товары.Ссылка?\n    возврат Неопределено\n;\n"
    ))
    assert [(x.rule_id, x.line) for x in diags] == [(MISSING_CODE, 1)]
    assert "Товары.Ссылка" in diags[0].message and "Б" in diags[0].message


@pytest.mark.needs_data
def test_the_same_type_with_the_import_is_silent():
    diags = _lint_missing_code(_module_project(
        "импорт Б\n\nметод Т(): Товары.Ссылка?\n    возврат Неопределено\n;\n"
    ))
    assert diags == []


@pytest.mark.needs_data
def test_a_type_argument_of_a_generic_counts():
    diags = _lint_missing_code(_module_project(
        "метод Т(Список: Массив<Товары.Ссылка>)\n;\n"
    ))
    assert [x.rule_id for x in diags] == [MISSING_CODE]


@pytest.mark.needs_data
def test_a_type_of_the_own_subsystem_needs_no_import():
    diags = _lint_missing_code(_module_project(
        "метод Т(): Свои.Ссылка?\n    возврат Неопределено\n;\n",
        **{"А/Свои.yaml": "ВидЭлемента: Справочник\nИмя: Свои\nОбластьВидимости: ВПодсистеме\n"},
    ))
    assert diags == []


@pytest.mark.needs_data
def test_a_non_public_foreign_element_is_left_to_the_visibility_rule():
    """No import can reach a non-public element - that is yaml/foreign-not-public's case."""
    diags = _lint_missing_code(_module_project(
        "метод Т(): Скрытый.Ссылка?\n    возврат Неопределено\n;\n",
        **{"Б/Скрытый.yaml": "ВидЭлемента: Справочник\nИмя: Скрытый\n"},
    ))
    assert diags == []


@pytest.mark.needs_data
def test_a_module_without_subsystem_files_stands_down():
    files = {"Модуль.yaml": "ВидЭлемента: ОбщийМодуль\nИмя: Модуль\n",
             "Модуль.xbsl": "метод Т(): Товары.Ссылка?\n    возврат Неопределено\n;\n"}
    assert _lint_missing_code(files) == []


# --- yaml/missing-subsystem-usage ---------------------------------------------------------

USAGE = "yaml/missing-subsystem-usage"


def _lint_usage(files):
    sources = [engine.load_text(name, content) for name, content in files.items()]
    return engine.run_sources(sources, select={USAGE})


def _usage_project(sub_a: str, **extra):
    """Subsystem А imports Б from its module; what А declares as used is the variable."""
    files = {
        "А/Подсистема.yaml": sub_a,
        "Б/Подсистема.yaml": SUB_B,
        "Б/Товары.yaml": GOODS,
        "А/Модуль.yaml": "ВидЭлемента: ОбщийМодуль\nИмя: Модуль\n",
        "А/Модуль.xbsl": "импорт Б\n\nметод Т(): Товары.Ссылка?\n    возврат Неопределено\n;\n",
    }
    files.update(extra)
    return files


def test_missing_usage_registered_project_scope():
    info = next(r for r in engine.active_rules() if r.id == USAGE)
    assert info.tier == "D" and info.scope == "project" and info.enabled_by_default


@pytest.mark.needs_data  # the mapper tokenizes the module: the lexer needs language.json
def test_an_import_without_the_usage_declaration_is_reported():
    """The compiler refuses to apply such a project, naming the description of the subsystem."""
    diags = _lint_usage(_usage_project("Использование:\n    - В\n"))
    # the descriptor is where the single missing line goes, so that is where the report sits
    assert [(x.rule_id, x.path.replace("\\", "/")) for x in diags] == [
        (USAGE, "А/Подсистема.yaml")
    ]
    assert "Б" in diags[0].message


@pytest.mark.needs_data
def test_the_declared_usage_is_silent():
    assert _lint_usage(_usage_project(SUB_A)) == []


@pytest.mark.needs_data
def test_the_report_points_at_the_usage_block():
    diags = _lint_usage(_usage_project("Интерфейс:\n    ВключатьВАвтоИнтерфейс: Ложь\n"
                                       "Использование:\n    - В\n"))
    assert [x.line for x in diags] == [3]


@pytest.mark.needs_data
def test_without_a_usage_block_the_report_sits_at_the_top():
    diags = _lint_usage(_usage_project("Интерфейс:\n    ВключатьВАвтоИнтерфейс: Ложь\n"))
    assert [(x.line, x.col) for x in diags] == [(1, 1)]


@pytest.mark.needs_data
def test_an_import_of_the_own_subsystem_needs_no_usage():
    files = _usage_project("Интерфейс:\n    ВключатьВАвтоИнтерфейс: Ложь\n",
                           **{"А/Модуль.xbsl": "импорт А\n\nметод Т()\n;\n"})
    assert _lint_usage(files) == []


@pytest.mark.needs_data
def test_a_library_import_is_not_judged():
    """Another project or a typo - the rule has no subsystem of this project to check."""
    files = _usage_project("Интерфейс:\n    ВключатьВАвтоИнтерфейс: Ложь\n",
                           **{"А/Модуль.xbsl": "импорт Чужая\n\nметод Т()\n;\n"})
    assert _lint_usage(files) == []


@pytest.mark.needs_data
def test_the_import_section_of_a_yaml_counts_too():
    """An element imports in its own yaml section, and it needs the usage just as the code."""
    files = _usage_project(
        "Интерфейс:\n    ВключатьВАвтоИнтерфейс: Ложь\n",
        **{"А/Модуль.xbsl": "метод Т()\n;\n",
           "А/Форма.yaml": FORM_HEAD + "Импорт:\n    - Б\n" + FORM_BODY},
    )
    assert [x.rule_id for x in _lint_usage(files)] == [USAGE]


def test_without_subsystem_files_the_usage_rule_stands_down():
    files = {"Модуль.yaml": "ВидЭлемента: ОбщийМодуль\nИмя: Модуль\nИмпорт:\n    - Б\n"}
    assert _lint_usage(files) == []


@pytest.mark.needs_data
def test_a_call_of_a_foreign_module_is_reported_too():
    """The other shape: the foreign subsystem is reached by a chain root, not a written type."""
    diags = _lint_missing_code(_module_project(
        "метод Т()\n    знч Х = Товары.НайтиПоКоду(\"1\")\n;\n"
    ))
    assert [(x.rule_id, x.line) for x in diags] == [(MISSING_CODE, 2)]
    assert "Товары.НайтиПоКоду" in diags[0].message


@pytest.mark.needs_data
def test_a_local_name_is_not_a_reference():
    """A variable, a parameter and a loop name explain themselves - the module says so."""
    files = _module_project(
        "метод Т(Товары: Строка)\n    знч Х = Товары.ВВерхнийРегистр()\n;\n"
        "метод П()\n    знч Товары = \"\"\n    знч Х = Товары.Длина()\n;\n"
    )
    assert _lint_missing_code(files) == []


@pytest.mark.needs_data
def test_a_section_of_the_paired_yaml_is_not_a_reference():
    """The live false one: a scheduled job reads its own parameters by the section name, and
    the project happens to hold an element of that name in another subsystem."""
    files = _module_project(
        "метод Т()\n    знч Х = Товары.ХранитьДней\n;\n",
        **{"А/Модуль.yaml": "ВидЭлемента: ЗапланированноеЗадание\nИмя: Модуль\n"
                            "Товары:\n    -\n        Имя: ХранитьДней\n        Тип: Число\n"},
    )
    assert _lint_missing_code(files) == []


@pytest.mark.needs_data
def test_a_name_the_module_declares_is_not_a_reference():
    files = _module_project(
        "структура Товары\n    поле Код: Строка\n;\n\n"
        "метод Т()\n    знч Х = новый Товары()\n    знч К = Х.Код\n;\n"
    )
    assert _lint_missing_code(files) == []
