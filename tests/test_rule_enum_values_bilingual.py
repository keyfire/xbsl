"""The code/unknown-enum-value rule on an ENGLISH project.

The platform reads a project in either spelling, so an enumeration may declare itself as
`ElementKind: Enumeration` / `Name` / `Items` / `Name`. The rule used to read those keys as
plain Russian strings: it crashed on the missing "Имя" of an item, and the diagnostic the run
produced was the linter's own failure instead of the check. The tests below keep the whole rule
bilingual - the declaration, the guard that skips a name the file itself declares, the built-in
members of the enumeration type and the bindings of an English form.
"""

from __future__ import annotations

from xbsl.diagnostics import Diagnostic
from xbsl.engine import load_text, run_sources

RULE = "code/unknown-enum-value"

#: The state of a step, spelled the way `xbsl translate` writes a project out.
STEP_STATE = """\
ElementKind: Enumeration
Id: 0f2a6c31-1d54-4b90-9c07-5ab3e8d4f612
Name: StepState
Items:
    -
        Id: 4c1b7e28-90da-4f36-b8e1-73c05a29d4f7
        Name: Planned
    -
        Id: b7d95f10-2a63-4c8e-95af-1e6407bd3a52
        Name: Done
"""


def _lint(*sources: tuple[str, str]) -> list[Diagnostic]:
    files = [load_text("StepState.yaml", STEP_STATE)]
    files += [load_text(name, text) for name, text in sources]
    return [d for d in run_sources(files, select={RULE}) if d.rule_id == RULE]


def _crashes(diags: list[Diagnostic]) -> list[Diagnostic]:
    """Findings that report the rule itself failing rather than the code under check."""
    return [d for d in diags if "KeyError" in d.message or "Traceback" in d.message]


def test_english_enumeration_does_not_break_the_rule():
    diags = _lint(("Steps.xbsl", "method Probe(): StepState\n    return StepState.Planned\n;\n"))
    assert _crashes(diags) == [], [d.message for d in diags]
    assert diags == [], [d.message for d in diags]


def test_english_enumeration_alone_is_clean():
    """A project of the enumeration alone: the file used to fail the rule by itself."""
    assert _lint() == []


def test_unknown_value_of_an_english_enumeration_is_flagged():
    diags = _lint(("Steps.xbsl", "method Probe(): StepState\n    return StepState.Started\n;\n"))
    assert [d.rule_id for d in diags] == [RULE]
    assert "StepState.Started" in diags[0].message


def test_english_builtin_members_are_not_values():
    """`Presentation`, `ByName` and `Items` belong to the type, not to the declaration."""
    diags = _lint((
        "Steps.xbsl",
        "method Probe(): String\n"
        "    val All = StepState.Items()\n"
        "    val Some = StepState.ByName(\"Planned\")\n"
        "    return StepState.Planned.Presentation()\n;\n",
    ))
    assert diags == [], [d.message for d in diags]


def test_english_form_binding_with_a_known_value_is_clean():
    diags = _lint((
        "StepCard.yaml",
        "ElementKind: InterfaceComponent\n"
        "Id: 8e30d5a7-64b1-4f22-a0c9-95d178e2b463\n"
        "Name: StepCard\n"
        "Inherits:\n"
        "    Type: Group\n"
        "    Content:\n"
        "        -\n"
        "            Type: Label\n"
        "            Name: Hint\n"
        "            Visibility: '=State == StepState.Done'\n",
    ))
    assert diags == [], [d.message for d in diags]


def test_english_form_binding_with_an_unknown_value_is_flagged():
    diags = _lint((
        "StepCard.yaml",
        "ElementKind: InterfaceComponent\n"
        "Id: 8e30d5a7-64b1-4f22-a0c9-95d178e2b463\n"
        "Name: StepCard\n"
        "Inherits:\n"
        "    Type: Group\n"
        "    Content:\n"
        "        -\n"
        "            Type: Label\n"
        "            Name: Hint\n"
        "            Visibility: '=State == StepState.Cancelled'\n",
    ))
    assert [d.rule_id for d in diags] == [RULE]
    assert "StepState.Cancelled" in diags[0].message


def test_english_form_field_named_after_the_enumeration_is_skipped():
    """The guard reads the `Name:` key too - otherwise a local name reads as a value."""
    diags = _lint((
        "StepCard.yaml",
        "ElementKind: InterfaceComponent\n"
        "Id: 8e30d5a7-64b1-4f22-a0c9-95d178e2b463\n"
        "Name: StepCard\n"
        "Attributes:\n"
        "    -\n"
        "        Id: 5a41c9b6-73e0-4d18-8fa2-6c0b93e57d14\n"
        "        Name: StepState\n"
        "        Type: String\n"
        "Inherits:\n"
        "    Type: Group\n"
        "    Content:\n"
        "        -\n"
        "            Type: Label\n"
        "            Name: Hint\n"
        "            Value: '=StepState.Whatever'\n",
    ))
    assert diags == [], [d.message for d in diags]
