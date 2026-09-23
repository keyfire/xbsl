"""code/contract-parameter-name: @Implementation follows its project contract signature."""

import pytest

from xbsl import engine, i18n
from xbsl import parser as P
from xbsl.diagnostics import Severity

from xbsl.rules import contract_parameters  # noqa: F401 - registers the rule under test

RULE = "code/contract-parameter-name"

pytestmark = pytest.mark.needs_data


def _project(
    implementation: str,
    contract: str = "abstract method Execute(Value: String): String\n",
    *,
    compatibility: str | None = "8.0",
    contracts: tuple[str, ...] = ("ProbeContract",),
    extra: dict[str, str] | None = None,
) -> dict[str, str]:
    project = "Name: Probe\nVendor: test\nVersion: 1.0.0\n"
    if compatibility is not None:
        project += f"CompatibilityMode: {compatibility}\n"
    listed = "\n".join(f"        - {name}" for name in contracts)
    files = {
        "Project.yaml": project,
        "ProbeContract.yaml": "ElementKind: ServiceContract\nName: ProbeContract\nEnvironment: Server\n",
        "ProbeContract.xbsl": contract,
        "Service.yaml": (
            "ElementKind: CommonModule\nName: Service\nEnvironment: Server\n"
            "TypeOptions:\n    Contracts:\n" + listed + "\n"
        ),
        "Service.xbsl": implementation,
    }
    files.update(extra or {})
    return files


def _lint(files: dict[str, str]):
    sources = [engine.load_text(name, text) for name, text in files.items()]
    assert all(not P.parse(source)[1] for source in sources if source.kind == "xbsl")
    return engine.run_sources(sources, select={RULE})


def test_parameter_name_mismatch_is_error_from_compatibility_8():
    implementation = """@Implementation
method Execute(Renamed: String): String
    return Renamed
;
"""
    found = _lint(_project(implementation))

    assert len(found) == 1
    assert (found[0].line, found[0].severity) == (2, Severity.ERROR)
    assert "Renamed" in found[0].message and "Value" in found[0].message


def test_parameter_name_mismatch_is_warning_before_compatibility_8():
    implementation = """@Implementation
method Execute(Renamed: String): String
    return Renamed
;
"""
    found = _lint(_project(implementation, compatibility="7.0"))
    assert len(found) == 1 and found[0].severity is Severity.WARNING


@pytest.mark.parametrize("compatibility", (None, "invalid"))
def test_missing_or_invalid_compatibility_is_silent(compatibility):
    implementation = "@Implementation\nmethod Execute(Renamed: String): String\n return Renamed\n;\n"
    assert _lint(_project(implementation, compatibility=compatibility)) == []


def test_matching_name_and_method_without_implementation_annotation_are_clean():
    matching = "@Implementation\nmethod Execute(Value: String): String\n return Value\n;\n"
    ordinary = "method Execute(Renamed: String): String\n return Renamed\n;\n"
    assert _lint(_project(matching)) == []
    assert _lint(_project(ordinary)) == []


def test_cross_language_parameter_names_without_a_project_term_pair_are_unresolved():
    implementation = "@Implementation\nmethod Execute(Значение: String): String\n return Значение\n;\n"
    assert _lint(_project(implementation)) == []


def test_platform_only_contract_and_partial_project_are_silent():
    implementation = "@Implementation\nmethod Execute(Renamed: String): String\n return Renamed\n;\n"
    platform = _project(implementation, contracts=("PlatformContract",))
    platform.pop("ProbeContract.yaml")
    platform.pop("ProbeContract.xbsl")
    assert _lint(platform) == []


def test_unresolved_qualified_contract_does_not_bind_to_a_local_namesake():
    implementation = "@Implementation\nmethod Execute(Renamed: String): String\n return Renamed\n;\n"
    files = _project(implementation, contracts=("Foreign::ProbeContract",))
    assert _lint(files) == []


def test_qualified_namesake_is_not_the_standard_implementation_annotation():
    implementation = """@Foreign::Implementation
method Execute(Renamed: String): String
    return Renamed
;
"""
    assert _lint(_project(implementation)) == []


def test_incompatible_or_ambiguous_abstract_signatures_are_silent():
    implementation = "@Implementation\nmethod Execute(Renamed: String): String\n return Renamed\n;\n"
    wrong_type = _project(
        implementation,
        contract="abstract method Execute(Value: Number): String\n",
    )
    second = {
        "SecondContract.yaml": "ElementKind: ServiceContract\nName: SecondContract\nEnvironment: Server\n",
        "SecondContract.xbsl": "abstract method Execute(Other: String): String\n",
    }
    ambiguous = _project(
        implementation,
        contracts=("ProbeContract", "SecondContract"),
        extra=second,
    )
    assert _lint(wrong_type) == []
    assert _lint(ambiguous) == []


def test_duplicated_contract_or_implementation_modules_are_silent():
    implementation = "@Implementation\nmethod Execute(Renamed: String): String\n return Renamed\n;\n"
    duplicate_contract = _project(
        implementation,
        extra={
            "Copy/ProbeContract.xbsl": "abstract method Execute(Other: String): String\n",
            "Copy/ProbeContract.yaml": (
                "ElementKind: ServiceContract\nName: ProbeContract\nEnvironment: Server\n"
            ),
        },
    )
    duplicate_implementation = _project(
        implementation,
        extra={
            "Copy/Service.xbsl": implementation,
            "Copy/Service.yaml": (
                "ElementKind: CommonModule\nName: Service\nEnvironment: Server\n"
                "TypeOptions:\n    Contracts:\n        - ProbeContract\n"
            ),
        },
    )
    assert _lint(duplicate_contract) == []
    assert _lint(duplicate_implementation) == []


def test_russian_spelling_is_judged_and_message_is_bilingual():
    contract = "абстрактный метод Выполнить(Значение: Строка): Строка\n"
    implementation = """@Реализация
метод Выполнить(Переименовано: Строка): Строка
    возврат Переименовано
;
"""
    files = _project(implementation, contract)
    i18n.set_lang("ru")
    ru = _lint(files)[0].message
    i18n.set_lang("en")
    en = _lint(files)[0].message
    i18n.set_lang(None)
    assert "Переименовано" in ru and "Значение" in ru
    assert "Переименовано" in en and "Значение" in en and "contract" in en.lower()


def test_rule_registry_severity_is_error():
    info = next(item for item in engine.RULES if item.id == RULE)
    assert info.tier == "D" and info.scope == "project"
    assert info.severity is Severity.ERROR and info.enabled_by_default
