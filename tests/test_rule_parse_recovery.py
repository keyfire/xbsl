"""Healthy declarations retain diagnostics without trusting damaged method bodies."""
import pytest
from xbsl import parser
from xbsl.engine import load_text, run_sources

pytestmark = pytest.mark.needs_data
BROKEN = "method Damaged()\n    var Bare\n;\n"
CASES = [
    ("code/declaration-needs-init", "method Check()\n    var Value: Number|String\n;\n"),
    ("code/duplicate-declaration", "method Check()\n    var Value = 1\n    var Value = 2\n;\n"),
    ("code/required-field-default", "structure Packet\n    req var Value: Number = 1\n;\n"),
    ("code/duplicate-when", "method Check(Value: Number)\n    case Value\n    when 1\n    when 1\n    ;\n;\n"),
    ("code/duplicate-catch", "method Check()\n    try\n    catch First: Exception\n    catch Second: Exception\n    ;\n;\n"),
]

@pytest.mark.parametrize("rule,healthy", CASES)
@pytest.mark.parametrize("damaged_first", [True, False])
def test_valid_member_survives_an_unrelated_parse_error(rule, healthy, damaged_first):
    source = load_text("Example.xbsl", BROKEN + healthy if damaged_first else healthy + BROKEN)
    before, errors = parser.parse(source)
    assert errors
    diags = list(run_sources([source], select={rule}))
    assert len(diags) == 1
    assert diags[0].line > 3 if damaged_first else diags[0].line <= len(healthy.splitlines())
    after, after_errors = parser.parse(source)
    assert after is before and after_errors is errors
    assert any(getattr(m, "name", "") == "Damaged" for m in after.members)

@pytest.mark.parametrize("rule,healthy", [CASES[0], CASES[1], CASES[3], CASES[4]])
def test_healthy_method_in_the_same_structure_is_preserved(rule, healthy):
    source=load_text("Example.xbsl", "structure Packet\n" + BROKEN + healthy + ";\n")
    assert parser.parse(source)[1]
    assert len(list(run_sources([source], select={rule}))) == 1

@pytest.mark.parametrize("rule,healthy", [CASES[0], CASES[1], CASES[3], CASES[4]])
def test_the_damaged_method_itself_is_not_judged(rule, healthy):
    at=healthy.index("\n")+1
    source=load_text("Example.xbsl", healthy[:at]+"    var Bare\n"+healthy[at:])
    assert parser.parse(source)[1]
    assert list(run_sources([source],select={rule})) == []

def test_a_required_field_fix_uses_the_original_file_offsets():
    source=load_text("Example.xbsl", BROKEN+CASES[2][1])
    diag, = run_sources([source],select={"code/required-field-default"})
    assert diag.fix is not None
    assert source.text[diag.fix.start:diag.fix.end] == " = 1"

def test_a_broken_structure_header_does_not_authorize_its_fields():
    source=load_text("Example.xbsl", "structure Packet<\n    req var Value: Number = 1\n;\n")
    assert parser.parse(source)[1]
    assert list(run_sources([source],select={"code/required-field-default"})) == []
