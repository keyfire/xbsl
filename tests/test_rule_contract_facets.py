"""yaml/contract-facet-mismatch and yaml/contract-standard-length.

Every expectation below is a case of the live probe: the compiler answered each implementation
the way the test says ("Restrictions must not be set ...", "No restrictions are set ...",
"... must be equal to 50", "... cannot be greater than 50", "The maximum length for property
... is not set in entity contract", "... cannot exceed 100"), and the silent cases
applied cleanly in the same run.

The rules need no Element data, so the tests live outside test_rules and run in the public CI;
the English spelling of a file is covered by the parity seeds.
"""

import pytest

from xbsl import engine

_FACETS = "yaml/contract-facet-mismatch"
_STANDARD = "yaml/contract-standard-length"
_ID = "11111111-1111-1111-1111-11111111111{}"


def _contract(prop: str, name: str = "КонтрактЦены", tables: str = "") -> str:
    body = "".join(f"        {line}\n" for line in prop.split("\n")) if prop else ""
    props = f"Свойства:\n    -\n        Ид: {_ID.format(2)}\n{body}" if prop else ""
    return (f"ВидЭлемента: КонтрактСущности\nИд: {_ID.format(1)}\nИмя: {name}\n"
            f"ОбластьВидимости: ВПроекте\n{props}{tables}")


def _catalog(attr: str, contract: str = "КонтрактЦены", kind: str = "Справочник",
             tables: str = "") -> str:
    body = "".join(f"        {line}\n" for line in attr.split("\n"))
    return (f"ВидЭлемента: {kind}\nИд: {_ID.format(3)}\nИмя: Товары\nОбластьВидимости: ВПроекте\n"
            f"НастройкиТипов:\n    {kind}.Объект:\n        Контракты:\n"
            f"            - {contract}.Объект\n"
            f"Реквизиты:\n    -\n{body}{tables}")


def _run(contract: str, catalog: str, rule: str = _FACETS, extra: dict | None = None):
    sources = [engine.load_text("КонтрактЦены.yaml", contract),
               engine.load_text("Товары.yaml", catalog)]
    for name, text in (extra or {}).items():
        sources.append(engine.load_text(name, text))
    return engine.run_sources(sources, select={rule})


def _attr(lines: str) -> str:
    return f"Ид: {_ID.format(4)}\nИмя: Значение\n" + lines


def _apply(text: str, fix) -> str:
    return text[:fix.start] + fix.new + text[fix.end:]


# --- a regular attribute: the string length ------------------------------------------------


def test_restricted_attribute_of_an_unrestricted_property():
    catalog = _catalog(_attr("Тип: Строка\nМаксимальнаяДлина: 50"))
    d = _run(_contract("Имя: Значение\nТип: Строка"), catalog)
    assert len(d) == 1, [x.message for x in d]
    assert str(d[0].path).endswith("Товары.yaml") and (d[0].line, d[0].col) == (14, 28)
    assert "Restrictions must not be set" in d[0].message and d[0].fix is None


@pytest.mark.parametrize("switch", ["Многострочная: Истина", "КонтрольДлины: Исправлять"])
def test_a_switch_alone_makes_the_attribute_restricted(switch):
    # Both failed in the probe exactly like a length: any key of the group creates it.
    d = _run(_contract("Имя: Значение\nТип: Строка"), _catalog(_attr("Тип: Строка\n" + switch)))
    assert len(d) == 1 and "Restrictions must not be set" in d[0].message


def test_nullable_string_changes_nothing():
    d = _run(_contract("Имя: Значение\nТип: Строка?"),
             _catalog(_attr("Тип: Строка?\nМаксимальнаяДлина: 20")))
    assert len(d) == 1 and "Restrictions must not be set" in d[0].message


def test_unrestricted_attribute_of_a_restricted_property_gets_the_length():
    catalog = _catalog(_attr("Тип: Строка"))
    d = _run(_contract("Имя: Значение\nТип: Строка\nМаксимальнаяДлина: 50\nТолькоЧтение: Истина"),
             catalog)
    assert len(d) == 1 and "No restrictions are set" in d[0].message
    fixed = _apply(catalog, d[0].fix)
    assert "        Тип: Строка\n        МаксимальнаяДлина: 50\n" in fixed


def test_unequal_length_is_set_to_the_property_value():
    catalog = _catalog(_attr("Тип: Строка\nМаксимальнаяДлина: 30"))
    contract = _contract("Имя: Значение\nТип: Строка\nМаксимальнаяДлина: 50")
    d = _run(contract, catalog)
    assert len(d) == 1 and "must be equal to 50" in d[0].message
    fixed = _apply(catalog, d[0].fix)
    assert "МаксимальнаяДлина: 50" in fixed and _run(contract, fixed) == []


def test_read_only_property_caps_the_length_only():
    contract = _contract("Имя: Значение\nТип: Строка\nМаксимальнаяДлина: 50\nТолькоЧтение: Истина")
    wider = _run(contract, _catalog(_attr("Тип: Строка\nМаксимальнаяДлина: 60")))
    assert len(wider) == 1 and "cannot be greater than 50" in wider[0].message
    assert _run(contract, _catalog(_attr("Тип: Строка\nМаксимальнаяДлина: 40"))) == []
    # A read-only property without a length lets the attribute restrict itself.
    free = _contract("Имя: Значение\nТип: Строка\nТолькоЧтение: Истина")
    assert _run(free, _catalog(_attr("Тип: Строка\nМаксимальнаяДлина: 60"))) == []


def test_attribute_of_a_contract_table():
    table = ("ТабличныеЧасти:\n    -\n        Ид: {}\n        Имя: Строки\n        Реквизиты:\n"
             "            -\n                Ид: {}\n                Имя: Текст\n"
             "                Тип: Строка\n{}")
    contract = _contract("", tables=table.format(_ID.format(5), _ID.format(6), ""))
    catalog = _catalog("Имя: Наименование", tables=table.format(
        _ID.format(7), _ID.format(8), "                МаксимальнаяДлина: 20\n"))
    d = _run(contract, catalog)
    assert len(d) == 1 and "'Строки.Текст'" in d[0].message


# --- a regular attribute: the number restrictions ------------------------------------------


def test_number_restrictions_follow_the_compiler():
    unrestricted = _contract("Имя: Значение\nТип: Число")
    d = _run(unrestricted, _catalog(_attr("Тип: Число\nДлинаЦелойЧасти: 12")))
    assert len(d) == 1 and "Restrictions must not be set" in d[0].message
    restricted = _contract("Имя: Значение\nТип: Число\nДлинаЦелойЧасти: 12")
    d = _run(restricted, _catalog(_attr("Тип: Число")))
    assert len(d) == 1 and "No restrictions are set" in d[0].message
    d = _run(restricted, _catalog(_attr("Тип: Число\nДлинаЦелойЧасти: 10")))
    assert len(d) == 1 and "must be equal to 12" in d[0].message
    # The rest of the group takes the defaults: the fractional part is 0, not the contract's 2.
    fraction = _contract("Имя: Значение\nТип: Число\nДлинаЦелойЧасти: 12\nДлинаДробнойЧасти: 2")
    d = _run(fraction, _catalog(_attr("Тип: Число\nДлинаЦелойЧасти: 12")))
    assert len(d) == 1 and "ДлинаДробнойЧасти" in d[0].message and "must be equal to 2" in d[0].message
    bound = _contract("Имя: Значение\nТип: Число\nМаксимальноеЗначение: 100")
    d = _run(bound, _catalog(_attr("Тип: Число\nДлинаЦелойЧасти: 10")))
    assert len(d) == 1 and "No ... value is specified" in d[0].message


# --- what is not judged ---------------------------------------------------------------------


def test_left_alone_shapes():
    restricted = _contract("Имя: Значение\nТип: Строка\nМаксимальнаяДлина: 50")
    # A type mismatch is another error; a union of a string and a number and an array are
    # outside the rule; a property of an unknown contract is not read.
    assert _run(restricted, _catalog(_attr("Тип: Число"))) == []
    both = _contract("Имя: Значение\nТип: Строка|Число|?\nМаксимальнаяДлина: 50")
    assert _run(both, _catalog(_attr("Тип: Строка|Число|?"))) == []
    array = _contract("Имя: Значение\nТип: Массив<Строка>")
    assert _run(array, _catalog(_attr("Тип: Массив<Строка>\nМаксимальнаяДлина: 5"))) == []
    assert _run(restricted, _catalog(_attr("Тип: Строка"), contract="ДругойКонтракт")) == []


def test_ambiguous_contract_name_is_skipped():
    restricted = _contract("Имя: Значение\nТип: Строка\nМаксимальнаяДлина: 50")
    catalog = _catalog(_attr("Тип: Строка"))
    assert len(_run(restricted, catalog)) == 1
    twin = _contract("Имя: Значение\nТип: Строка")
    assert _run(restricted, catalog, extra={"Другое/КонтрактЦены.yaml": twin}) == []


# --- a standard attribute ------------------------------------------------------------------


def test_standard_name_needs_the_length_in_the_contract():
    catalog = _catalog("Имя: Наименование")
    d = _run(_contract("Имя: Наименование\nТип: Строка"), catalog, _STANDARD)
    assert len(d) == 1, [x.message for x in d]
    assert "'Наименование'" in d[0].message and "150" in d[0].message and d[0].fix is None
    # The negative control: the same length in the contract is what the compiler wants.
    assert _run(_contract("Имя: Наименование\nТип: Строка\nМаксимальнаяДлина: 150"), catalog,
                _STANDARD) == []


def test_standard_name_length_follows_the_contract():
    catalog = _catalog("Имя: Наименование")
    contract = _contract("Имя: Наименование\nТип: Строка\nМаксимальнаяДлина: 100")
    d = _run(contract, catalog, _STANDARD)
    assert len(d) == 1 and "must be equal to 100" in d[0].message
    fixed = _apply(catalog, d[0].fix)
    assert "        Имя: Наименование\n        Длина: 100\n" in fixed
    assert _run(contract, fixed, _STANDARD) == []


def test_standard_name_of_a_read_only_property_is_capped():
    contract = _contract(
        "Имя: Наименование\nТип: Строка\nМаксимальнаяДлина: 100\nТолькоЧтение: Истина")
    d = _run(contract, _catalog("Имя: Наименование\nДлина: 120"), _STANDARD)
    assert len(d) == 1 and "cannot exceed 100" in d[0].message
    assert _apply(_catalog("Имя: Наименование\nДлина: 120"), d[0].fix).count("Длина: 100") == 1
    assert _run(contract, _catalog("Имя: Наименование\nДлина: 90"), _STANDARD) == []


def test_standard_code_and_document_number():
    d = _run(_contract("Имя: Код\nТип: Строка"), _catalog("Имя: Код"), _STANDARD)
    assert len(d) == 1 and "'Код'" in d[0].message and " 7," in d[0].message
    number = _catalog("Имя: Номер", kind="Документ")
    d = _run(_contract("Имя: Номер\nТип: Строка"), number, _STANDARD)
    assert len(d) == 1 and "'Номер'" in d[0].message and " 9," in d[0].message
    # A developer attribute of that name (it has an `Id`) is not the standard one.
    developer = _catalog(f"Ид: {_ID.format(9)}\nИмя: Код\nТип: Строка")
    assert _run(_contract("Имя: Код\nТип: Строка"), developer, _STANDARD) == []
