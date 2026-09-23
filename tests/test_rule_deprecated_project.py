"""code/deprecated-project: a use bound to a project declaration marked deprecated."""

import pytest

from xbsl import engine
from xbsl import parser as P
from xbsl.diagnostics import Severity

from xbsl.rules import deprecated_project  # noqa: F401 - registers the rule under test

RULE = "code/deprecated-project"

pytestmark = pytest.mark.needs_data


def _project(*modules: tuple[str, str]) -> dict[str, str]:
    files = {
        "Project.yaml": "Name: Probe\nCompatibilityMode: 9.0\nVendor: test\nVersion: 1.0.0\n",
    }
    for name, text in modules:
        files[f"{name}.yaml"] = f"ElementKind: CommonModule\nName: {name}\nEnvironment: Server\n"
        files[f"{name}.xbsl"] = text
    return files


def _lint(files: dict[str, str]):
    sources = [engine.load_text(name, text) for name, text in files.items()]
    assert all(not P.parse(source)[1] for source in sources if source.kind == "xbsl")
    return [d for d in engine.run_sources(sources, select={RULE}) if d.rule_id == RULE]


def _where(found) -> list[tuple[str, int]]:
    return sorted((d.path, d.line) for d in found)


def test_a_call_of_a_deprecated_method_is_reported_with_the_note():
    tasks = """@Deprecated(Message = "Use NewTitle")
method OldTitle(): String
    return "old"
;

method NewTitle(): String
    return "new"
;

method Probe(): String
    val Old = OldTitle()
    return NewTitle()
;
"""
    found = _lint(_project(("Tasks", tasks)))
    assert _where(found) == [("Tasks.xbsl", 11)]
    assert found[0].severity is Severity.WARNING
    assert "'OldTitle'" in found[0].message and "Use NewTitle" in found[0].message


def test_a_name_with_a_current_overload_is_left_alone():
    tasks = """@Deprecated
method Title(Short: Boolean): String
    return ""
;

method Title(): String
    return ""
;

method Probe()
    val Value = Title()
;
"""
    assert _lint(_project(("Tasks", tasks))) == []


def test_an_argument_for_a_deprecated_parameter_is_reported_by_position_and_by_name():
    tasks = """method Save(Name: String, @Deprecated Force: Boolean = False)
;

method Probe()
    Save("a", True)
    Save("b", Force = True)
    Save("c")
;
"""
    found = _lint(_project(("Tasks", tasks)))
    assert _where(found) == [("Tasks.xbsl", 5), ("Tasks.xbsl", 6)]
    assert all("'Force'" in d.message and "'Save'" in d.message for d in found)


def test_constructor_fields_and_enumeration_values():
    tasks = """structure Point
    @Deprecated
    var X: Number
    var Y: Number
    @Deprecated
    constructor

    method Shift()
        X = X + 1
    ;
;

enum Mode
    @Deprecated Old,
    Current
;

method Probe()
    val P = new Point()
    val A = P.X
    val B = P.Y
    val C = Mode.Old
    val D = Mode.Current
;
"""
    found = _lint(_project(("Tasks", tasks)))
    assert _where(found) == [
        ("Tasks.xbsl", 9), ("Tasks.xbsl", 9),
        ("Tasks.xbsl", 19), ("Tasks.xbsl", 20), ("Tasks.xbsl", 22),
    ]
    messages = " ".join(d.message for d in found)
    assert "'Point'" in messages and "'X'" in messages and "'Mode.Old'" in messages


def test_a_parameter_that_shadows_a_deprecated_field_is_not_its_use():
    tasks = """@Deprecated
const Limit = 10

method Probe(Limit: Number): Number
    return Limit
;

method Other(): Number
    return Limit
;
"""
    found = _lint(_project(("Tasks", tasks)))
    assert _where(found) == [("Tasks.xbsl", 9)]


def test_a_declaration_of_another_module_is_reached_through_its_name():
    legacy = """@Deprecated("Use Tasks.Load")
method Load()
;

@Deprecated
const Limit = 5

method Fresh()
;
"""
    caller = """method Probe()
    Legacy.Load()
    Legacy.Fresh()
    val L = Legacy.Limit
;
"""
    found = _lint(_project(("Legacy", legacy), ("Caller", caller)))
    assert _where(found) == [("Caller.xbsl", 2), ("Caller.xbsl", 4)]
    assert "Use Tasks.Load" in found[0].message


def test_a_same_named_method_of_another_module_is_not_a_match():
    legacy = """@Deprecated
method Load()
;
"""
    caller = """method Load()
;

method Probe()
    Load()
;
"""
    assert _lint(_project(("Legacy", legacy), ("Caller", caller))) == []


def test_the_russian_spelling_is_judged_the_same_way():
    files = {
        "Проект.yaml": "Имя: Проба\nРежимСовместимости: 9.0\nПоставщик: test\nВерсия: 1.0.0\n",
        "Задачи.yaml": "ВидЭлемента: ОбщийМодуль\nИмя: Задачи\nОкружение: Сервер\n",
        "Задачи.xbsl": """@Устарело("Используйте Новое")
метод Старое(): Строка
    возврат ""
;

перечисление Шаги
    @Устарело Черновик,
    Готово
;

метод Проба()
    знч А = Старое()
    знч Б = Шаги.Черновик
    знч В = Шаги.Готово
;
""",
    }
    found = _lint(files)
    assert _where(found) == [("Задачи.xbsl", 12), ("Задачи.xbsl", 13)]
    assert "Используйте Новое" in found[0].message


def test_no_deprecated_declaration_means_no_finding():
    tasks = """method Load()
;

method Probe()
    Load()
;
"""
    assert _lint(_project(("Tasks", tasks))) == []


def test_the_parser_keeps_the_annotations_of_an_enumeration_value():
    source = engine.load_text("Probe.xbsl", "enum Mode\n    @Deprecated Old,\n    Current\n;\n")
    tree, errors = P.parse(source)
    assert not errors
    (enum,) = tree.members
    assert [item.name for item in enum.items] == ["Old", "Current"]
    assert [[a.name for a in item.annotations] for item in enum.items] == [["Deprecated"], []]
