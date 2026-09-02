"""The seeded bilingual parity check, run as a test so the seeds cannot rot.

`tools/parity_seed.py` plants a case in a Russian tree, translates it with the toolkit's own
translator and demands the same verdict from the rule in both spellings. Running it here keeps
two things honest at once: the rules stay bilingual, and the seeds keep describing the rules
they name - a seed that stops planting what it claims to plant reports `stale` rather than
passing quietly.

The tool is a script rather than part of the package, so it is loaded by path - the same way
tests/test_claims_registry.py loads the claims tool.
"""

import importlib.util
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent

pytestmark = pytest.mark.needs_data


def _tool():
    spec = importlib.util.spec_from_file_location(
        "parity_seed", ROOT / "tools" / "parity_seed.py"
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


_TOOL = _tool()


@pytest.mark.parametrize(
    "seed", _TOOL.SEEDS, ids=lambda s: f"{s.rule.replace('/', '-')}-{s.expect}",
)
def test_seed_reads_the_same_in_both_spellings(seed):
    """Every seed agrees across the two spellings - or carries the reason it cannot yet.

    A seed marked `known` is allowed to disagree: the gap is documented and the evidence is
    kept planted rather than deleted. What it is NOT allowed to do is start agreeing while
    still carrying the note - `fixed!` fails here on purpose, so a closed gap cannot keep a
    stale excuse attached to it.
    """
    result = _TOOL.run_seed(seed)
    detail = (f"{result['status']}: {seed.note} "
              f"(ru={result['russian']}, en={result['english']})")
    if seed.known:
        assert result["status"] != "fixed!", (
            f"the gap closed - remove the `known` note. {detail}")
        assert result["status"].startswith("known"), detail
    else:
        assert result["status"] == "ok", detail


def test_a_seed_that_stops_planting_its_case_is_reported_stale():
    """The tool's own negative control: passing must mean the case was actually planted.

    Without it a seed that quietly stopped violating anything would read as a green line -
    silence on both sides is what a CLEAN seed looks like, and the check would be measuring
    nothing while claiming parity.
    """
    stale = _TOOL.Seed(
        rule="structure/xbsl-pair",
        expect=_TOOL.FINDING,
        note="a module of a generated type, which the rule legitimately passes",
        files={
            "Цены.yaml": _TOOL._REGISTER_RU,
            "Цены.КлючЗаписи.xbsl": "метод Проба()\n;\n",
        },
        tokens={"Цены": "Prices", "Проба": "Probe"},
    )
    assert _TOOL.run_seed(stale)["status"] == "stale"


def test_a_hand_written_twin_the_rule_misreads_is_blamed_on_the_rule():
    """With a hand-written English twin the `en-...` verdict speaks about the rule alone.

    The hand writes a KNOWN type where the Russian tree plants an unknown one, so the rule is
    right to stay silent there - and the tool must still call it the English side's miss,
    while the translated tree (which carries the unknown type) is reported apart.
    """
    seed = _TOOL.Seed(
        rule="code/unknown-type",
        expect=_TOOL.FINDING,
        note="a hand-written twin that no longer plants the case",
        files={
            "Заявки.yaml": _TOOL._CATALOG_RU,
            "Заявки.xbsl": "метод Проба(Значение: НесуществующийТип)\n;\n",
        },
        english={
            "Applications.yaml": _TOOL._CATALOG_EN,
            "Applications.xbsl": "method Probe(Value: String)\n;\n",
        },
        tokens={"Заявки": "Applications", "Проба": "Probe", "Значение": "Value",
                "НесуществующийТип": "NonexistentType"},
    )
    result = _TOOL.run_seed(seed)
    assert result["status"] == "en-misses"
    assert result["translated"] == 1
    assert result["translator_differs"] == ["Applications.xbsl"]


def test_a_translated_twin_that_disagrees_alone_is_blamed_on_the_translator():
    """The dictionary maps the unknown type onto a platform one: the translated tree passes
    where the hand-written twin reports, and the verdict names the translator, not the rule."""
    seed = _TOOL.Seed(
        rule="code/unknown-type",
        expect=_TOOL.FINDING,
        note="a translation that turns the planted case into legal code",
        files={
            "Заявки.yaml": _TOOL._CATALOG_RU,
            "Заявки.xbsl": "метод Проба(Значение: НесуществующийТип)\n;\n",
        },
        english={
            "Applications.yaml": _TOOL._CATALOG_EN,
            "Applications.xbsl": "method Probe(Value: NonexistentType)\n;\n",
        },
        tokens={"Заявки": "Applications", "Проба": "Probe", "Значение": "Value",
                "НесуществующийТип": "String"},
    )
    result = _TOOL.run_seed(seed)
    assert result["status"] == "translator-misses"
    assert result["english"] == 1 and result["translated"] == 0
    assert result["translator_differs"] == ["Applications.xbsl"]


def test_the_translator_leaves_no_problem_behind_on_a_seed():
    """A seed whose translation collides is testing the dictionary, not the rule."""
    problems = {
        seed.rule: _TOOL.run_seed(seed)["translation_problems"]
        for seed in _TOOL.SEEDS
    }
    assert {rule: found for rule, found in problems.items() if found} == {}
