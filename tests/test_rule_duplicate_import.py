"""code/duplicate-import and yaml/duplicate-import: a namespace imported a second time.

The platform IDE warns about every repeat of a module import after the first; its language server
confirmed on probe projects that the short and the full name of a namespace repeat each other,
that the letter case matters (a differently cased name is an unknown namespace) and that a repeated
unused import gets both warnings. The `Import` section of a yaml gets no warning from the IDE - the
yaml rule reports its repeats by the same reading, as a rule of its own.

The rules tokenize the module and read the yaml keys from the data, so the tests need it.
"""

from pathlib import Path

import pytest

from xbsl import cli, engine

pytestmark = pytest.mark.needs_data

CODE = "code/duplicate-import"
YAML = "yaml/duplicate-import"

_PROJECT = ("Acme/Tasks/Проект.yaml",
            "Ид: 00000000-0000-4000-8000-0000000000a1\nПоставщик: Acme\nИмя: Tasks\nВерсия: 1.0.0\n")
_MODULE_YAML = ("ВидЭлемента: ОбщийМодуль\nИд: 00000000-0000-4000-8000-0000000000a2\nИмя: Сводка\n"
                "ОбластьВидимости: ВПроекте\nОкружение: Сервер\n")


def _lint(files: dict[str, str], rules: set[str]):
    sources = [engine.load_text(name, text) for name, text in files.items()]
    return engine.run_sources(sources, select=rules)


def _module(*imports: str) -> str:
    return "".join(f"{line}\n" for line in imports) + "\nметод Проба(): Число\n    возврат 1\n;\n"


def _fixed(text: str, found) -> str:
    fix = found.fix
    assert fix is not None, found.message
    return text[:fix.start] + fix.new + text[fix.end:]


# --- modules ----------------------------------------------------------------------------------

def test_a_repeated_import_is_reported_at_the_repeat_with_its_line_removed():
    text = _module("импорт Справочники", "импорт Склады", "импорт Справочники")
    found = _lint({"Acme/Tasks/Основное/Сводка.xbsl": text}, {CODE})

    assert [(d.line, d.col) for d in found] == [(3, 1)]
    assert found[0].severity.value == "warning"
    assert "строке 1" in found[0].message
    assert _fixed(text, found[0]) == _module("импорт Справочники", "импорт Склады")


def test_the_full_name_of_the_own_project_repeats_the_short_one():
    text = _module("импорт Справочники::Партии", "импорт Acme::Tasks::Справочники::Партии", "импорт Справочники::Партии")
    files = {_PROJECT[0]: _PROJECT[1], "Acme/Tasks/Основное/Сводка.xbsl": text,
             "Acme/Tasks/Основное/Сводка.yaml": _MODULE_YAML}

    assert [(d.line, d.col) for d in _lint(files, {CODE})] == [(2, 1), (3, 1)]


def test_without_the_descriptor_only_equal_texts_repeat_each_other():
    text = _module("импорт Справочники", "импорт Acme::Tasks::Справочники")

    assert _lint({"Acme/Tasks/Основное/Сводка.xbsl": text}, {CODE}) == []


def test_a_full_name_of_another_project_is_another_namespace():
    text = _module("импорт Справочники", "импорт Acme::Other::Справочники")
    files = {_PROJECT[0]: _PROJECT[1], "Acme/Tasks/Основное/Сводка.xbsl": text}

    assert _lint(files, {CODE}) == []


def test_the_letter_case_tells_namespaces_apart():
    text = _module("импорт Справочники", "импорт справочники")

    assert _lint({"Acme/Tasks/Основное/Сводка.xbsl": text}, {CODE}) == []


def test_a_comment_on_the_line_keeps_the_finding_without_a_fix():
    text = _module("импорт Справочники", "импорт Справочники // ещё раз")
    found = _lint({"Acme/Tasks/Основное/Сводка.xbsl": text}, {CODE})

    assert len(found) == 1
    assert found[0].fix is None


def test_the_english_keyword_is_read():
    text = "import Catalogs\nimport Catalogs\n\nmethod Probe(): Number\n    return 1\n;\n"
    found = _lint({"Acme/Tasks/Main/Summary.xbsl": text}, {CODE})

    assert [(d.line, d.col) for d in found] == [(2, 1)]


def test_the_module_rule_does_not_read_the_yaml():
    yaml_text = _MODULE_YAML + "Импорт:\n    - Справочники\n    - Справочники\n"
    assert _lint({"Acme/Tasks/Основное/Сводка.yaml": yaml_text}, {CODE}) == []


# --- yaml -------------------------------------------------------------------------------------

def test_a_repeated_entry_of_the_yaml_section_is_reported_with_its_line_removed():
    text = _MODULE_YAML + "Импорт:\n    - Справочники\n    - Склады\n    - Справочники\n"
    found = _lint({"Acme/Tasks/Основное/Сводка.yaml": text}, {YAML})

    assert [(d.line, d.col) for d in found] == [(9, 7)]
    assert "строка 7" in found[0].message
    assert _fixed(text, found[0]) == _MODULE_YAML + "Импорт:\n    - Справочники\n    - Склады\n"


def test_the_yaml_section_compares_the_full_name_too():
    text = _MODULE_YAML + "Импорт:\n    - Справочники\n    - Acme::Tasks::Справочники\n"
    files = {_PROJECT[0]: _PROJECT[1], "Acme/Tasks/Основное/Сводка.yaml": text}

    assert [(d.line, d.col) for d in _lint(files, {YAML})] == [(8, 7)]


def test_the_english_key_of_the_yaml_section_is_read():
    text = ("ElementKind: CommonModule\nId: 00000000-0000-4000-8000-0000000000a2\nName: Summary\n"
            "Import:\n    - Catalogs\n    - Catalogs\n")

    assert len(_lint({"Acme/Tasks/Main/Summary.yaml": text}, {YAML})) == 1


def test_a_flow_list_keeps_the_finding_without_a_fix():
    text = _MODULE_YAML + "Импорт: [Справочники, Справочники]\n"
    found = _lint({"Acme/Tasks/Основное/Сводка.yaml": text}, {YAML})

    assert len(found) == 1
    assert found[0].fix is None


def test_the_yaml_rule_does_not_read_the_module():
    text = _module("импорт Справочники", "импорт Справочники")
    assert _lint({"Acme/Tasks/Основное/Сводка.xbsl": text}, {YAML}) == []


# --- --fix on files ---------------------------------------------------------------------------

def test_fix_rewrites_both_files_by_their_own_offsets(tmp_path: Path):
    folder = tmp_path / "Acme" / "Tasks" / "Основное"
    folder.mkdir(parents=True)
    (tmp_path / "Acme" / "Tasks" / "Проект.yaml").write_bytes(_PROJECT[1].encode("utf-8"))
    module = folder / "Сводка.xbsl"
    module.write_bytes("\r\n".join(["импорт Справочники", "импорт Acme::Tasks::Справочники", "",
                                    "метод Проба(): Число", "    возврат 1", ";", ""]).encode("utf-8"))
    descriptor = folder / "Сводка.yaml"
    descriptor.write_bytes((_MODULE_YAML + "Импорт:\n    - Склады\n    - Склады\n").replace("\n", "\r\n").encode("utf-8"))

    code = cli.main([str(tmp_path), "--select", f"{CODE},{YAML}", "--no-baseline", "--fix"])

    assert code == 0
    assert module.read_bytes().decode("utf-8") == "\r\n".join(
        ["импорт Справочники", "", "метод Проба(): Число", "    возврат 1", ";", ""])
    assert descriptor.read_bytes().decode("utf-8") == \
        (_MODULE_YAML + "Импорт:\n    - Склады\n").replace("\n", "\r\n")
