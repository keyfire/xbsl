"""code/procedure-as-value: a resolved procedure call used for its missing result."""

import pytest

from xbsl import engine, i18n
from xbsl import parser as P
from xbsl.diagnostics import Severity

from xbsl.rules import procedure_value  # noqa: F401 - registers the rule under test

RULE = "code/procedure-as-value"

pytestmark = pytest.mark.needs_data


def _project(*modules: tuple[str, str]) -> dict[str, str]:
    files = {
        "Project.yaml": (
            "Name: Probe\nCompatibilityMode: 8.0\nVendor: test\nVersion: 1.0.0\n"
        ),
    }
    for name, text in modules:
        files[f"{name}.yaml"] = f"ElementKind: CommonModule\nName: {name}\nEnvironment: Server\n"
        files[f"{name}.xbsl"] = text
    return files


def _placed_project(*, caller_subsystem: str, imported: bool, visibility: str = "InProject"):
    caller = "import A\n\n" if imported else ""
    caller += "method Probe()\n    val Value = Procedures.Notify()\n;\n"
    files = {
        "Project.yaml": (
            "Name: Probe\nCompatibilityMode: 8.0\nVendor: test\nVersion: 1.0.0\n"
        ),
        "A/Subsystem.yaml": "Name: A\n",
        "A/Procedures.yaml": (
            "ElementKind: CommonModule\nName: Procedures\nEnvironment: Server\n"
            f"VisibilityScope: {visibility}\n"
        ),
        "A/Procedures.xbsl": "method Notify()\n;\n",
        f"{caller_subsystem}/Caller.yaml": (
            "ElementKind: CommonModule\nName: Caller\nEnvironment: Server\n"
        ),
        f"{caller_subsystem}/Caller.xbsl": caller,
    }
    if caller_subsystem != "A":
        files[f"{caller_subsystem}/Subsystem.yaml"] = f"Name: {caller_subsystem}\n"
    return files


def _lint(files: dict[str, str]):
    sources = [engine.load_text(name, text) for name, text in files.items()]
    assert all(not P.parse(source)[1] for source in sources if source.kind == "xbsl")
    return engine.run_sources(sources, select={RULE})


def test_local_procedure_in_every_proven_value_context_is_reported():
    module = """method Notify()
;

method Take(Value: Number)
;

method Probe()
    val Initialized = Notify()
    Take(Notify())
    return Notify()
;

method Text(): String
    return "Value: %{Notify()}"
;
"""
    found = _lint(_project(("Calls", module)))

    assert [(item.line, item.severity) for item in found] == [
        (8, Severity.ERROR),
        (9, Severity.ERROR),
        (10, Severity.ERROR),
        (14, Severity.ERROR),
    ]


def test_direct_calls_use_statements_and_procedure_lambdas_are_clean():
    module = """method Notify()
;

method Take(Handler: Object)
;

method Probe()
    Notify()
    use Notify()
    Take(() -> Notify())
;
"""
    assert _lint(_project(("Calls", module))) == []


def test_cross_module_procedure_is_reported_but_unknown_and_mixed_targets_are_silent():
    procedures = """method Notify()
;

method Mixed()
;

method Mixed(): Number
    return 1
;
"""
    caller = """method Probe(Service: Object)
    val Cross = Procedures.Notify()
    val Unknown = Missing.Notify()
    val Receiver = Service.Notify()
    val Mixed = Procedures.Mixed()
;
"""
    found = _lint(_project(("Procedures", procedures), ("Caller", caller)))

    assert len(found) == 1
    assert found[0].path.endswith("Caller.xbsl") and found[0].line == 2


def test_local_and_module_name_shadows_are_not_resolved_as_procedures():
    procedures = "method Notify()\n;\n"
    caller = """method Probe(Notify: ()->Number, Procedures: Object)
    val Local = Notify()
    val Receiver = Procedures.Notify()
;
"""
    assert _lint(_project(("Procedures", procedures), ("Caller", caller))) == []


def test_partial_project_without_the_callee_declaration_is_silent():
    caller = """method Probe()
    val Value = Procedures.Notify()
;
"""
    assert _lint(_project(("Caller", caller))) == []


def test_foreign_module_without_its_namespace_import_is_unresolved():
    assert _lint(_placed_project(caller_subsystem="B", imported=False)) == []


def test_imported_public_foreign_module_is_resolved():
    found = _lint(_placed_project(caller_subsystem="B", imported=True))
    assert len(found) == 1 and found[0].path.endswith("Caller.xbsl")


def test_module_in_the_same_subsystem_needs_no_import():
    found = _lint(_placed_project(caller_subsystem="A", imported=False))
    assert len(found) == 1 and found[0].path.endswith("Caller.xbsl")


def test_private_foreign_module_is_unresolved_even_when_imported():
    assert _lint(_placed_project(
        caller_subsystem="B", imported=True, visibility="InSubsystem",
    )) == []


def test_interpolation_only_caller_is_carried_into_the_shared_project_typing():
    procedures = "method Notify()\n;\n"
    caller = "method Probe()\n val Text = \"Value: %{Procedures.Notify()}\"\n;\n"
    found = _lint(_project(("Procedures", procedures), ("Caller", caller)))
    assert len(found) == 1 and found[0].path.endswith("Caller.xbsl") and found[0].line == 2


def test_module_field_initializer_is_a_value_context():
    module = """method Notify()
;

val Initial = Notify()
"""
    found = _lint(_project(("Calls", module)))
    assert len(found) == 1 and found[0].line == 4


def test_structure_field_shadows_a_same_named_module_procedure():
    module = """method Notify()
;

structure Box
    val Notify: ()->Number
    method Probe()
        val Value = Notify()
    ;
;
"""
    assert _lint(_project(("Calls", module))) == []


def test_mixed_owner_overloads_do_not_fall_back_to_the_module_procedure():
    module = """method Notify()
;

structure Box
    method Notify()
    ;
    method Notify(): Number
        return 1
    ;
    method Probe()
        val Value = Notify()
    ;
;
"""
    assert _lint(_project(("Calls", module))) == []


def test_message_is_bilingual():
    files = _project(("Calls", "method Notify()\n;\nmethod Probe()\n val X = Notify()\n;\n"))
    i18n.set_lang("ru")
    ru = _lint(files)[0].message
    i18n.set_lang("en")
    en = _lint(files)[0].message
    i18n.set_lang(None)
    assert "процедур" in ru.lower() and "procedure" in en.lower()
