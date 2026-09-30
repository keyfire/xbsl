"""The seeded bilingual parity check, run as a test so the seeds cannot rot.

`tools/parity_seed.py` plants a case in a Russian tree, translates it with the toolkit's own
translator and demands the same verdict from the rule in both spellings. Running it here keeps
two things honest at once: the rules stay bilingual, and the seeds keep describing the rules
they name - a seed that stops planting what it claims to plant reports `stale` rather than
passing quietly.

The tool is a script rather than part of the package, so it is loaded by path - the same way
tests/test_claims_registry.py loads the claims tool.

The tests that run a seed need the Element data and are marked one by one. The module as a whole
is not: the check that no constant of the tool is bound twice reads the tool's source alone, and
it has to run in a public checkout as well.
"""

import ast
import dataclasses
import importlib.util
import sys
from pathlib import Path

import pytest

from xbsl import dataset

ROOT = Path(__file__).resolve().parent.parent


def _tool():
    spec = importlib.util.spec_from_file_location(
        "parity_seed", ROOT / "tools" / "parity_seed.py"
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


_TOOL = _tool()


@pytest.mark.needs_data
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
    if result["status"] == "no-data":
        pytest.skip(f"the data carries no {seed.needs_section} section: {seed.note}")
    detail = (f"{result['status']}: {seed.note} "
              f"(ru={result['russian']}, en={result['english']})")
    if seed.known:
        assert result["status"] != "fixed!", (
            f"the gap closed - remove the `known` note. {detail}")
        assert result["status"].startswith("known"), detail
    else:
        assert result["status"] == "ok", detail


@pytest.mark.needs_data
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


def test_a_seed_whose_data_section_is_missing_is_not_judged():
    """A rule that reads a section of the data is silent without it by design: a FINDING seed
    would read as a miss of both trees ("stale"), so the seed is not run at all."""
    seed = _TOOL.Seed(
        rule="structure/xbsl-pair",
        expect=_TOOL.FINDING,
        note="a seed that asks for a section no data carries",
        files={"Цены.yaml": _TOOL._REGISTER_RU},
        needs_section="section_no_data_carries",
    )
    result = _TOOL.run_seed(seed)
    assert result["status"] == "no-data"
    assert (result["russian"], result["english"]) == (0, 0)


@pytest.mark.needs_data
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


@pytest.mark.needs_data
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


@pytest.mark.needs_data
def test_the_translator_leaves_no_problem_behind_on_a_seed():
    """A seed whose translation collides is testing the dictionary, not the rule."""
    problems = {
        seed.rule: _TOOL.run_seed(seed)["translation_problems"]
        for seed in _TOOL.SEEDS
    }
    assert {rule: found for rule, found in problems.items() if found} == {}


def test_no_constant_of_the_tool_is_bound_twice():
    """Every module constant of the tool is bound once.

    `SEEDS` is built after all the constants, so every seed reads a name bound twice at its
    LAST binding - the seeds written for the first binding included. Two names were once bound
    twice: the seeds of code/query-needs-server got the tokens of the subquery seeds, and their
    Russian tree came out untranslated; five seeds planted the task card of another rule rather
    than the object form their English twin describes. Nothing failed - the only trace was a
    `translator differs` line under seeds that passed.
    """
    tree = ast.parse((ROOT / "tools" / "parity_seed.py").read_text(encoding="utf-8"))
    bound: dict[str, list[int]] = {}
    for node in tree.body:
        if isinstance(node, ast.Assign):
            targets = node.targets
        elif isinstance(node, ast.AnnAssign):
            targets = [node.target]
        else:
            continue
        for target in targets:
            if isinstance(target, ast.Name):
                bound.setdefault(target.id, []).append(node.lineno)
    assert {name: lines for name, lines in bound.items() if len(lines) > 1} == {}


#: One pair of the platform's picture library, as the extractor files it (uiterms.resource_paths).
_TRUCK = {"Icons/Стд/Ресурсы/Грузовик.svg": "Icons/Std/Resources/Truck.svg"}
#: The module of the picture seeds, written by hand in English.
_PICTURES_XBSL_EN = ("method Picture(): BinaryObject.Reference\n"
                     "    return Resource{{{key}}}.Link\n;\n")


def _serve_picture_table(monkeypatch, table):
    """Serve the installed data with the given table of pictures, or without one (None)."""
    original = dataset.load_json

    def load_json(name, *args, **kwargs):
        data = original(name, *args, **kwargs)
        if name != "uiterms.json":
            return data
        data = {key: value for key, value in data.items() if key != "resource_paths"}
        if table is not None:
            data["resource_paths"] = dict(table)
        return data

    monkeypatch.setattr(dataset, "load_json", load_json)
    dataset.set_data_root(None)  # the reset hooks drop every table read before


@pytest.mark.needs_data
def test_a_picture_of_the_library_reads_the_same_on_data_with_the_picture_table_and_without(
        monkeypatch):
    """The library seed on data with the table of pictures and without it.

    With the table the translator writes `Std::Truck.svg`, exactly as the hand-written twin
    spells it, and all three trees pass. Without the table the translator keeps the Russian
    name, and the seed still agrees. The control is the hand-written twin on that data: only
    the table carries the English name, so without it the name is reported.
    """
    seed = next(s for s in _TOOL.SEEDS if s.rule == "code/unknown-resource"
                and "Стд::Грузовик.svg" in "".join(s.files.values()))
    twin = dataclasses.replace(seed, english={
        "Project.yaml": _TOOL._PROJECT_EN.format(mode="9.0"),
        "Main/Resources/Own.svg": "<svg/>",
        "Main/Pictures.xbsl": _PICTURES_XBSL_EN.format(key="Std::Truck.svg"),
    })
    try:
        _serve_picture_table(monkeypatch, _TRUCK)
        with_table = _TOOL.run_seed(twin)
        monkeypatch.undo()
        _serve_picture_table(monkeypatch, None)
        plain = _TOOL.run_seed(seed)
        control = _TOOL.run_seed(twin)
    finally:
        monkeypatch.undo()
        dataset.set_data_root(None)

    assert with_table["status"] == "ok", with_table
    assert with_table["translator_differs"] == []
    assert plain["status"] == "ok", plain
    assert control["status"] == "en-invents", control
    assert (control["russian"], control["english"], control["translated"]) == (0, 1, 0)
    assert control["translator_differs"] == ["Main/Pictures.xbsl"]
