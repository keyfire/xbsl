"""yaml/localization-missing-import: an unqualified `$Словарь.Ключ` across a subsystem
boundary without the subsystem in THIS yaml's own `Import` section.

The resolution rules come from the documentation ("Локализация", the collision rules): an
unqualified reference reaches the local and the imported subsystems, and a used-but-not-
imported subsystem must be named in the reference itself. The live case behind the rule was
refused at apply time with the namespace-not-imported message while the paired module DID
import the subsystem - which is exactly why the module import must not count.

The rule needs no Element data (spellings degrade to Russian), so the tests live outside
test_rules and run in the public CI; the English-spelling case needs the term data.
"""

import pytest

from xbsl import engine
from xbsl.diagnostics import Severity

RULE = "yaml/localization-missing-import"

DICTIONARY = (
    "ВидЭлемента: ЛокализованныеСтроки\n"
    "Ид: 11111111-1111-1111-1111-111111111111\n"
    "Имя: Словарь\n"
    "ОбластьВидимости: ВПроекте\n"
    "Строки:\n"
    "    Ключ: Значение\n"
)
FORM_HEAD = (
    "ВидЭлемента: КомпонентИнтерфейса\n"
    "Ид: 11111111-1111-1111-1111-111111111112\n"
    "Имя: Форма\n"
)


def _lint(files):
    sources = [engine.load_text(name, content) for name, content in files.items()]
    return engine.run_sources(sources, select={RULE})


def _project(form_yaml, **extra):
    files = {
        "А/Подсистема.yaml": "Имя: А\n",
        "Б/Подсистема.yaml": "Имя: Б\n",
        "А/Словарь.yaml": DICTIONARY,
        "Б/Форма.yaml": form_yaml,
    }
    files.update(extra)
    return files


def test_rule_registered_project_scope():
    info = next(r for r in engine.active_rules() if r.id == RULE)
    assert info.tier == "D" and info.scope == "project"
    assert info.severity is Severity.ERROR and info.enabled_by_default


def test_foreign_ref_without_import_flagged():
    form = FORM_HEAD + "Наследует:\n    Тип: Страница\n    Заголовок: $Словарь.Ключ\n"
    d = _lint(_project(form))
    assert len(d) == 1, [x.message for x in d]
    assert d[0].rule_id == RULE and d[0].severity is Severity.ERROR
    assert "$Словарь.Ключ" in d[0].message and "'А'" in d[0].message
    assert "$А::Словарь.Ключ" in d[0].message  # the import-free cure is spelled out
    assert d[0].line == 6  # the line of the reference


def test_foreign_ref_with_import_ok():
    form = (FORM_HEAD + "Импорт:\n    - А\n"
            + "Наследует:\n    Тип: Страница\n    Заголовок: $Словарь.Ключ\n")
    assert _lint(_project(form)) == []


def test_qualified_ref_needs_no_import():
    # The documentation's own escape hatch: the subsystem named in the reference itself.
    form = FORM_HEAD + "Наследует:\n    Тип: Страница\n    Заголовок: $А::Словарь.Ключ\n"
    assert _lint(_project(form)) == []


def test_local_ref_ok():
    # A dictionary of the same subsystem resolves locally - collisions favour the local one.
    form = FORM_HEAD + "Наследует:\n    Тип: Страница\n    Заголовок: $Словарь.Ключ\n"
    files = _project(form)
    files["Б/Словарь.yaml"] = DICTIONARY.replace(
        "11111111-1111-1111-1111-111111111111", "11111111-1111-1111-1111-111111111113")
    assert _lint(files) == []


def test_non_public_dictionary_silent():
    # No public owner - a visibility problem, not an import one; the rule stays out.
    form = FORM_HEAD + "Наследует:\n    Тип: Страница\n    Заголовок: $Словарь.Ключ\n"
    private = DICTIONARY.replace("ОбластьВидимости: ВПроекте\n", "")
    assert _lint(_project(form, **{"А/Словарь.yaml": private})) == []


def test_unknown_dictionary_silent():
    # A name no project dictionary declares is unknown, not wrong.
    form = FORM_HEAD + "Наследует:\n    Тип: Страница\n    Заголовок: $Чужое.Ключ\n"
    assert _lint(_project(form)) == []


def test_module_import_does_not_cover():
    # The live shape: the paired module imports the subsystem, the yaml does not.
    form = FORM_HEAD + "Наследует:\n    Тип: Страница\n    Заголовок: $Словарь.Ключ\n"
    files = _project(form)
    files["Б/Форма.xbsl"] = "импорт А\n"
    assert len(_lint(files)) == 1


def test_one_diagnostic_per_subsystem_per_file():
    form = (FORM_HEAD + "Наследует:\n    Тип: Страница\n"
            + "    Заголовок: $Словарь.Ключ\n    Подзаголовок: $Словарь.Ключ\n")
    assert len(_lint(_project(form))) == 1


def test_reference_inside_dictionary_silent():
    # A dictionary's own texts are data; a `$X.Y` inside one is not a markup reference.
    dictionary = DICTIONARY + "    Другой: $Словарь.Ключ\n"
    files = {
        "А/Подсистема.yaml": "Имя: А\n",
        "А/Словарь.yaml": dictionary,
    }
    assert _lint(files) == []


def test_no_subsystem_files_silent():
    files = {
        "Словарь.yaml": DICTIONARY,
        "Форма.yaml": FORM_HEAD + "Наследует:\n    Заголовок: $Словарь.Ключ\n",
    }
    assert _lint(files) == []


@pytest.mark.needs_data
def test_english_spellings_flagged():
    files = {
        "A/Подсистема.yaml": "Имя: A\n",
        "B/Подсистема.yaml": "Имя: B\n",
        "A/Dictionary.yaml": (
            "ElementKind: LocalizedStrings\n"
            "Ид: 11111111-1111-1111-1111-111111111114\n"
            "Name: Dictionary\n"
            "ОбластьВидимости: ВПроекте\n"
            "Строки:\n"
            "    Key: Value\n"
        ),
        "B/Form.yaml": (
            "ElementKind: КомпонентИнтерфейса\n"
            "Ид: 11111111-1111-1111-1111-111111111115\n"
            "Name: Form\n"
            "Inherits:\n"
            "    Type: Страница\n"
            "    Заголовок: $Dictionary.Key\n"
        ),
    }
    d = _lint(files)
    assert len(d) == 1, [x.message for x in d]
    assert "$Dictionary.Key" in d[0].message
