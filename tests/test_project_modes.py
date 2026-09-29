"""xbsl/typeinfer.py: the compatibility mode a project is read in, one reading for every rule.

The reader of a project description in the platform takes the declared mode when it is a
supported one. No mode at all, a value that names no mode and a mode outside the supported
range are errors of the description - the build refuses the project - and the reader goes on in
the newest mode. The rules that depend on the mode (code/handler-overrides-nothing,
code/deprecated-api, code/contract-parameter-name, yaml/property-since-compat) read it through
`typeinfer.project_modes`, and the visibility of a resources folder without a descriptor
through `resources.project_compatibility`, which reads it with `typeinfer.read_mode`.

Every test builds its own tiny data root with the enumeration of the modes, so the module is
checked in a public checkout too.
"""

import json

import pytest

from xbsl import dataset, engine, resources, typeinfer

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


# --- yaml/property-since-compat -------------------------------------------------------------------

#: The data of a platform whose newest mode is 8.0, with a component property that appeared in
#: 9.0: a project read in the newest mode still uses a property newer than its mode, so the
#: rule has something to say about a description that declares no supported mode.
_STDLIB_UP_TO_8 = {
    "names": ["РежимСовместимости"],
    "type_members": {"РежимСовместимости": {
        "properties": ["Версия6_0", "Версия7_0", "Версия8_0"],
    }},
}
_UI_SCHEMA = {"components": {"Таблица": {"props": {
    "ИспользоватьМножественнуюСортировку": {"since": "9.0"},
}}}}

_ORDERS_FORM = (
    "ВидЭлемента: КомпонентИнтерфейса\n"
    "Ид: 4b7e2a90-6c1d-4f38-9e52-0a8d3c6b1f27\n"
    "Имя: СписокЗаказов\n"
    "Наследует:\n"
    "    Тип: Форма\n"
    "    Содержимое:\n"
    "        Тип: Таблица<ДинамическийСписок>\n"
    "        Имя: Список\n"
    "        ИспользоватьМножественнуюСортировку: Истина\n"
)

_SINCE_RULE = "yaml/property-since-compat"


@pytest.fixture
def since_data(tmp_path):
    version = tmp_path / "9.9.9"
    version.mkdir()
    (tmp_path / "index.json").write_text(
        json.dumps({"available": ["9.9.9"], "default": "9.9.9"}), encoding="utf-8")
    for name, data in (("stdlib.json", _STDLIB_UP_TO_8), ("uischema.json", _UI_SCHEMA)):
        (version / name).write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    dataset.set_data_root(tmp_path)
    try:
        yield
    finally:
        dataset.set_data_root(None)


def _since_findings(*sources: tuple[str, str]):
    return engine.run_sources([engine.load_text(rel, text) for rel, text in sources],
                              select={_SINCE_RULE})


@pytest.mark.parametrize("line", [
    "",
    "РежимСовместимости: новейший\n",
    "РежимСовместимости: 5.0\n",
], ids=["no-mode", "not-a-mode", "below-the-oldest"])
def test_property_since_judges_a_description_without_a_supported_mode_in_the_newest_one(
        since_data, line):
    found = _since_findings(("Склады/Проект.yaml", _PROJECT + line),
                            ("Склады/Основное/СписокЗаказов.yaml", _ORDERS_FORM))

    assert [d.rule_id for d in found] == [_SINCE_RULE]
    # The message names the mode the project is read in and says it is assumed, not declared.
    assert "8.0 (новейший" in found[0].message
    assert "5.0" not in found[0].message


def test_property_since_judges_a_supported_mode_as_declared(since_data):
    found = _since_findings(("Склады/Проект.yaml", _PROJECT + "РежимСовместимости: 7.0\n"),
                            ("Склады/Основное/СписокЗаказов.yaml", _ORDERS_FORM))

    assert [d.rule_id for d in found] == [_SINCE_RULE]
    assert "7.0" in found[0].message and "новейший" not in found[0].message


def test_property_since_knows_no_mode_outside_every_described_project(since_data):
    found = _since_findings(("Склады/Проект.yaml", _PROJECT),
                            ("Архив/СписокЗаказов.yaml", _ORDERS_FORM))

    assert found == []


# --- resources.project_compatibility ---------------------------------------------------------------


def _described(tmp_path, text: str | None):
    project = tmp_path / "Склады"
    project.mkdir()
    if text is not None:
        (project / "Проект.yaml").write_text(text, encoding="utf-8")
    return project


@pytest.mark.parametrize("line, expected", [
    ("РежимСовместимости: 7.0\n", (7, 0)),
    ("", (10, 0)),
    ("РежимСовместимости: новейший\n", (10, 0)),
    ("РежимСовместимости: 5.0\n", (10, 0)),
], ids=["declared", "no-mode", "not-a-mode", "below-the-oldest"])
def test_the_resources_read_the_mode_the_platform_reads(modes, tmp_path, line, expected):
    # Below 8.0 a resources folder without a descriptor is public, from 8.0 on private: a
    # description the platform reads in the newest mode keeps such a folder private.
    assert resources.project_compatibility(_described(tmp_path, _PROJECT + line)) == expected


def test_the_resources_know_no_mode_without_the_description(modes, tmp_path):
    assert resources.project_compatibility(_described(tmp_path, None)) is None
    assert resources.project_compatibility(None) is None


def test_without_data_the_resources_take_the_declared_mode_as_written(tmp_path):
    dataset.set_data_root(tmp_path / "no-data")
    try:
        assert resources.project_compatibility(
            _described(tmp_path, _PROJECT + "РежимСовместимости: 5.0\n")) == (5, 0)
        (tmp_path / "Склады" / "Проект.yaml").write_text(_PROJECT, encoding="utf-8")
        assert resources.project_compatibility(tmp_path / "Склады") is None
    finally:
        dataset.set_data_root(None)


_PROJECT_EN = "Vendor: Acme\nName: Warehouses\n"


def _described_in_english(tmp_path, line: str):
    project = tmp_path / "Warehouses"
    project.mkdir()
    (project / "Project.yaml").write_text(_PROJECT_EN + line, encoding="utf-8")
    return project


def test_an_english_description_gives_the_resources_its_mode_without_the_term_data(tmp_path):
    """The resources read the key of the mode the way the project rules do, both spellings
    always: looked up in the term data, `CompatibilityMode` was no key at all without it, and a
    folder of an English project lost the mode its description declares."""
    dataset.set_data_root(tmp_path / "no-data")
    try:
        project = _described_in_english(tmp_path, "CompatibilityMode: 5.0\n")
        assert resources.project_compatibility(project) == (5, 0)
    finally:
        dataset.set_data_root(None)


def test_the_resources_and_the_project_rules_read_one_declared_mode(modes, tmp_path):
    # The tiny data root holds the modes and no term pairs, exactly where the two readers
    # used to part: the rules knew both keys by heart, the resources asked the terms.
    project = _described_in_english(tmp_path, "CompatibilityMode: 7.0\n")
    facts = _facts({"Warehouses/Project.yaml": _PROJECT_EN + "CompatibilityMode: 7.0\n",
                    "Warehouses/Stock.txt": ""})

    assert resources.project_compatibility(project) == (7, 0)
    assert typeinfer.project_modes(facts)["Warehouses/Stock.txt"] == ((7, 0), False)
    assert typeinfer.declared_compatibility({"CompatibilityMode": "7.0"}) == (7, 0)
    assert typeinfer.declared_compatibility({"РежимСовместимости": 8.0}) == (8, 0)
    assert typeinfer.declared_compatibility({"CompatibilityMode": "newest"}) is None
    assert typeinfer.declared_compatibility({}) is None
