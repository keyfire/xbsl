"""yaml/register-entity-contract: a register implements a type contract only.

The shape is the one the live probe settled: an information register naming the object type of
an entity contract under its type options failed with "Invalid type of contract ...; a type
contract is expected". The documentation lists both registers among the implementations of a
type contract and neither among those of an entity contract. What stays silent is what compiles
(a type contract, an entity contract implemented by a catalog) and what the rule cannot resolve
(a shared name, a contract the project does not describe, a bare name).

The rule needs no Element data for a Russian description, so the tests live outside test_rules
and run in the public CI; the English spelling needs the platform dictionary and is marked.
"""

import pytest

from xbsl import engine

_RULE = "yaml/register-entity-contract"


def _register(entry: str, kind: str = "РегистрСведений", facet: str = "Запись") -> str:
    return (f"ВидЭлемента: {kind}\nИд: 11111111-1111-1111-1111-111111111111\n"
            f"Имя: ЗапасыКладовой\nОбластьВидимости: ВПроекте\n"
            f"НастройкиТипов:\n    {kind}.{facet}:\n        Контракты:\n"
            f"            - {entry}\n")


def _contract(kind: str = "КонтрактСущности", name: str = "КонтрактЗапасов",
              uid: str = "22222222-2222-2222-2222-222222222222") -> str:
    return f"ВидЭлемента: {kind}\nИд: {uid}\nИмя: {name}\nОбластьВидимости: ВПроекте\n"


def _run(files: dict[str, str]):
    sources = [engine.load_text(name, text) for name, text in files.items()]
    return engine.run_sources(sources, select={_RULE})


def test_a_register_naming_an_entity_contract_is_flagged():
    d = _run({"ЗапасыКладовой.yaml": _register("КонтрактЗапасов.Объект"),
              "КонтрактЗапасов.yaml": _contract()})
    assert len(d) == 1, [x.message for x in d]
    assert (d[0].path, d[0].line, d[0].col) == ("ЗапасыКладовой.yaml", 8, 15)
    assert "'ЗапасыКладовой'" in d[0].message and "'КонтрактЗапасов'" in d[0].message
    assert "a type contract is expected" in d[0].message and "Контракты" in d[0].message
    assert d[0].fix is None


def test_an_accumulation_register_and_a_qualified_entry_are_flagged_too():
    accumulation = _register("КонтрактЗапасов.Объект", kind="РегистрНакопления")
    assert len(_run({"ЗапасыКладовой.yaml": accumulation,
                     "КонтрактЗапасов.yaml": _contract()})) == 1
    qualified = _register("Кладовая::КонтрактЗапасов.Объект")
    d = _run({"ЗапасыКладовой.yaml": qualified, "КонтрактЗапасов.yaml": _contract()})
    assert len(d) == 1 and "'Кладовая::КонтрактЗапасов.Объект'" in d[0].message
    # The options of the register type itself, not only of its record, are read as well.
    own = _register("КонтрактЗапасов.Объект", facet="Запись").replace(
        "РегистрСведений.Запись:", "РегистрСведений:")
    assert len(_run({"ЗапасыКладовой.yaml": own, "КонтрактЗапасов.yaml": _contract()})) == 1


def test_negative_control_the_same_entry_against_a_type_contract_is_silent():
    # The kind of the contract is the whole condition: the same register and the same entry
    # pass once the named contract is a type contract, and fail again when it is not.
    files = {"ЗапасыКладовой.yaml": _register("КонтрактЗапасов.Объект"),
             "КонтрактЗапасов.yaml": _contract(kind="КонтрактТипа")}
    assert _run(files) == []
    files["КонтрактЗапасов.yaml"] = _contract()
    assert len(_run(files)) == 1


def test_a_type_contract_and_a_catalog_implementing_the_entity_contract_compile():
    assert _run({"ЗапасыКладовой.yaml": _register("Пополняемое"),
                 "Пополняемое.yaml": _contract(kind="КонтрактТипа", name="Пополняемое")}) == []
    catalog = _register("КонтрактЗапасов.Объект", kind="Справочник", facet="Объект")
    assert _run({"ЗапасыКладовой.yaml": catalog, "КонтрактЗапасов.yaml": _contract()}) == []


def test_what_the_rule_cannot_resolve_is_left_alone():
    # A bare name is outside the shape the probe settled; a contract the project does not
    # describe comes from a library; a name two contracts share cannot be resolved.
    assert _run({"ЗапасыКладовой.yaml": _register("КонтрактЗапасов"),
                 "КонтрактЗапасов.yaml": _contract()}) == []
    assert _run({"ЗапасыКладовой.yaml": _register("КонтрактЗапасов.Объект")}) == []
    shared = {"ЗапасыКладовой.yaml": _register("КонтрактЗапасов.Объект"),
              "КонтрактЗапасов.yaml": _contract(),
              "Кладовая/КонтрактЗапасов.yaml": _contract(
                  kind="КонтрактТипа", uid="33333333-3333-3333-3333-333333333333")}
    assert _run(shared) == []


def test_a_quoted_entry_points_past_the_quote():
    d = _run({"ЗапасыКладовой.yaml": _register("'КонтрактЗапасов.Объект'"),
              "КонтрактЗапасов.yaml": _contract()})
    assert len(d) == 1 and (d[0].line, d[0].col) == (8, 16)


@pytest.mark.needs_data
def test_an_english_register_is_judged_and_named_in_its_own_spelling():
    # The kinds, the keys and the facet come from the platform dictionary.
    register = ("ElementKind: InformationRegister\nId: 11111111-1111-1111-1111-111111111111\n"
                "Name: PantryStock\nVisibilityScope: InProject\nTypeOptions:\n"
                "    InformationRegister.Record:\n        Contracts:\n"
                "            - StockContract.Object\n")
    contract = ("ElementKind: EntityContract\nId: 22222222-2222-2222-2222-222222222222\n"
                "Name: StockContract\nVisibilityScope: InProject\n")
    d = _run({"PantryStock.yaml": register, "StockContract.yaml": contract})
    assert len(d) == 1 and (d[0].line, d[0].col) == (8, 15)
    assert "'PantryStock'" in d[0].message and "Contracts" in d[0].message
