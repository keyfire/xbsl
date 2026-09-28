"""xbsl/typeinfer.py: the compatibility mode a project is read in, one reading for every rule.

The reader of a project description in the platform takes the declared mode when it is a
supported one. No mode at all, a value that names no mode and a mode outside the supported
range are errors of the description - the build refuses the project - and the reader goes on in
the newest mode. The rules that depend on the mode (code/handler-overrides-nothing,
code/deprecated-api, code/contract-parameter-name) read it through `typeinfer.project_modes`.

Every test builds its own tiny data root with the enumeration of the modes, so the module is
checked in a public checkout too.
"""

import json

import pytest

from xbsl import dataset, engine, typeinfer

#: The enumeration of the modes the way the catalog keeps it: a value per supported mode, and
#: a member that is not a mode at all.
_STDLIB = {
    "names": ["РежимСовместимости"],
    "type_members": {"РежимСовместимости": {
        "properties": ["Версия6_0", "Версия7_0", "Версия8_0", "Версия9_0", "Версия10_0", "Индекс"],
    }},
}


@pytest.fixture
def modes(tmp_path):
    version = tmp_path / "9.9.9"
    version.mkdir()
    (tmp_path / "index.json").write_text(
        json.dumps({"available": ["9.9.9"], "default": "9.9.9"}), encoding="utf-8")
    (version / "stdlib.json").write_text(json.dumps(_STDLIB, ensure_ascii=False), encoding="utf-8")
    dataset.set_data_root(tmp_path)
    try:
        yield
    finally:
        dataset.set_data_root(None)


def test_the_supported_modes_come_from_the_enumeration(modes):
    assert typeinfer.supported_modes() == {(6, 0), (7, 0), (8, 0), (9, 0), (10, 0)}


def test_a_supported_mode_is_read_as_declared(modes):
    assert typeinfer.read_mode((8, 0)) == ((8, 0), False)


@pytest.mark.parametrize("declared", [
    None,  # no mode at all, or a value that names no mode
    (5, 0),  # below the oldest supported mode
    (8, 5),  # between two supported modes
    (11, 0),  # above the newest one
    (9,),  # a mode written without its minor number is not a value of the enumeration either
], ids=["none", "below", "between", "above", "no-minor"])
def test_any_other_description_is_read_in_the_newest_mode(modes, declared):
    assert typeinfer.read_mode(declared) == ((10, 0), True)


def test_without_data_the_declared_mode_is_taken_as_written(tmp_path):
    dataset.set_data_root(tmp_path)
    try:
        assert typeinfer.supported_modes() == frozenset()
        assert typeinfer.read_mode((5, 0)) == ((5, 0), False)
        assert typeinfer.read_mode(None) == (None, False)
    finally:
        dataset.set_data_root(None)


def _facts(files: dict[str, str]) -> dict[str, dict]:
    """The facts of `project_fact`, as a project rule gets them."""
    facts = {}
    for name, text in files.items():
        fact = typeinfer.project_fact(engine.load_text(name, text))
        facts[name] = fact if fact is not None else {"k": "other"}
    return facts


_PROJECT = "Поставщик: Acme\nИмя: Склады\n"


@pytest.mark.parametrize("line, expected", [
    ("РежимСовместимости: 8.0\n", ((8, 0), False)),
    ("CompatibilityMode: 8.0\n", ((8, 0), False)),
    ("", ((10, 0), True)),
    ("РежимСовместимости: новейший\n", ((10, 0), True)),
    ("РежимСовместимости: 5.0\n", ((10, 0), True)),
], ids=["declared", "english-key", "no-mode", "not-a-mode", "below-the-oldest"])
def test_every_source_of_the_project_gets_the_mode_of_its_description(modes, line, expected):
    facts = _facts({"Склады/Проект.yaml": _PROJECT + line, "Склады/Остатки.txt": ""})

    assert typeinfer.project_modes(facts) == dict.fromkeys(facts, expected)


def test_a_source_outside_every_described_project_has_no_mode(modes):
    facts = _facts({"Склады/Проект.yaml": _PROJECT + "РежимСовместимости: 8.0\n",
                    "Архив/Остатки.txt": ""})

    assert typeinfer.project_modes(facts)["Архив/Остатки.txt"] == (None, False)


def test_each_project_of_a_run_is_read_in_its_own_mode(modes):
    facts = _facts({"Склады/Проект.yaml": _PROJECT + "РежимСовместимости: 7.0\n",
                    "Склады/Остатки.txt": "",
                    "Проект.yaml": _PROJECT,
                    "Учет/Остатки.txt": ""})

    found = typeinfer.project_modes(facts)
    assert found["Склады/Остатки.txt"] == ((7, 0), False)
    # A description at the root of the run speaks for the sources outside the nested project.
    assert found["Учет/Остатки.txt"] == ((10, 0), True)
