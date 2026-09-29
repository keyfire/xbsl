"""Tier D: the modules of an entity contract declare abstract methods only.

The rule code/contract-method-not-abstract.

An entity contract generates the contract type, the object type `<Contract>.Object` and a row
type for each of its tabular sections, and each of them may have a module: `<Contract>.xbsl`,
`<Contract>.Object.xbsl`, and `<Contract>.<Section>.xbsl` beside the yaml that declares the
section. The help page of the kind calls the object type abstract (`Абстрактный тип`), and the
probes settled what that means for the modules: an ordinary method got "Non-abstract method ...
cannot be defined" in each of the three, and so did a static method - in the module of the
contract, of its object and of a row alike - and a handler (`@Handler BeforeWrite` with a
body, in the object module). The row module compiled once the method was gone, and an abstract
method compiled in the module of the contract. An abstract method is a signature without a
body, so the fix is either that or moving the method out; a static method can only move out.

The yaml of the contract and its modules are different files, so the rule is a project one
(map-reduce): the yaml contributes its kind and the sections it declares, a module the methods it
declares without the `abstract` modifier. A row module is recognised by the declaration of its
section, the way code/undefined-name and structure/xbsl-pair recognise it. Narrowings:

- a yaml that does not parse leaves its modules alone - what it declares is unknown, and its own
  yaml/valid is the finding to read;
- a module that does not parse is left to code/parse-error;
- the methods of a structure declared inside the module belong to that structure and are not
  judged, and neither are the fields and constants of the module.
"""

from __future__ import annotations

from bisect import bisect_left
from collections.abc import Iterable

from xbsl import i18n
from xbsl import parser as P
from xbsl.diagnostics import Diagnostic, Severity
from xbsl.engine import SourceFile, rule
from xbsl.rules._syntax import OBJECT_MODULE_SUFFIXES, code_tokens
from xbsl.rules.undefined_names import _pair_key, _row_attributes, _row_candidate
from xbsl.rules.yaml_schema import _parsed, object_kind_fast, value_of

RULE_ID = "code/contract-method-not-abstract"

MESSAGES = {
    f"{RULE_ID}.title": {
        "ru": "Неабстрактный метод в модуле контракта сущности",
        "en": "A non-abstract method in an entity contract module",
    },
    f"{RULE_ID}.object": {
        "ru": "Метод '{name}' не абстрактный, а модуль объекта контракта сущности '{contract}' "
              "принимает только абстрактные методы – компилятор откажет. {advice}",
        "en": "Method '{name}' is not abstract, while the object module of the entity contract "
              "'{contract}' takes abstract methods only - the compiler will reject it. {advice}",
    },
    f"{RULE_ID}.row": {
        "ru": "Метод '{name}' не абстрактный, а модуль строки '{section}' контракта сущности "
              "'{contract}' принимает только абстрактные методы – компилятор откажет. {advice}",
        "en": "Method '{name}' is not abstract, while the module of the row '{section}' of the "
              "entity contract '{contract}' takes abstract methods only - the compiler will "
              "reject it. {advice}",
    },
    f"{RULE_ID}.own": {
        "ru": "Метод '{name}' не абстрактный, а модуль контракта сущности '{contract}' "
              "принимает только абстрактные методы – компилятор откажет. {advice}",
        "en": "Method '{name}' is not abstract, while the module of the entity contract "
              "'{contract}' takes abstract methods only - the compiler will reject it. {advice}",
    },
    f"{RULE_ID}.advice": {
        "ru": "Объявите 'абстрактный метод' без тела или уберите метод из модуля.",
        "en": "Declare an '{n[абстрактный]} {n[метод]}' without a body, or move the method out "
              "of the module.",
    },
    f"{RULE_ID}.advice-static": {
        "ru": "Статический метод этот модуль не принимает совсем: перенесите его, например, в "
              "общий модуль.",
        "en": "This module takes no static method at all: move it out, to a common module for "
              "instance.",
    },
}
i18n.register(MESSAGES)

#: The kind whose modules take abstract methods only.
_ENTITY_CONTRACT = "КонтрактСущности"


def _concrete_methods(source: SourceFile, module: P.Module) -> list[tuple[int, int, str, bool]]:
    """(line, column, name, static) of every method of the module declared without `abstract`.

    The position is that of the name, the way the other method rules report a declaration.
    """
    toks = code_tokens(source)
    starts = [tok.start for tok in toks]
    found: list[tuple[int, int, str, bool]] = []
    for member in module.members:
        if not isinstance(member, P.Method) or member.is_abstract or not member.name:
            continue
        # The declaring keyword follows the annotations and the modifiers; the name follows it.
        begin = member.annotations[-1].end if member.annotations else member.start
        index = bisect_left(starts, begin)
        while index < len(toks) and not (
                toks[index].kind == "KEYWORD" and toks[index].canonical == "METHOD"):
            index += 1
        name = toks[index + 1] if index + 1 < len(toks) else None
        if name is not None and name.value == member.name:
            found.append((name.line, name.col, member.name, member.is_static))
    return found


def _mapper(source: SourceFile) -> dict | None:
    """A contract yaml gives its name and sections, a module named after an element its methods."""
    directory, pair, fname = _pair_key(source.rel)
    if source.kind == "yaml":
        if object_kind_fast(source) != _ENTITY_CONTRACT:
            return None
        data, error = _parsed(source)
        if error is not None or not isinstance(data, dict):
            return None
        name = value_of(data, "Имя", _ENTITY_CONTRACT)
        return {
            "k": "y",
            "dir": directory,
            "file": fname,
            "name": name if isinstance(name, str) else fname[: -len(".yaml")],
            "rows": sorted(_row_attributes(data)),
        }
    if source.kind != "xbsl":
        return None
    obj = fname.endswith(OBJECT_MODULE_SUFFIXES)
    # Neither an object module nor a row candidate: the module of an element itself, judged
    # when its element turns out to be a contract.
    row = None if obj else _row_candidate(fname)
    module, errors = P.parse(source)
    if errors:
        return None
    methods = _concrete_methods(source, module)
    if not methods:
        return None
    return {"k": "x", "dir": directory, "pair": pair, "obj": obj, "row": row, "methods": methods}


@rule(
    RULE_ID, f"{RULE_ID}.title", "D", scope="project", severity=Severity.ERROR, mapper=_mapper,
)
def contract_method_not_abstract(facts: dict[str, dict]) -> Iterable[Diagnostic]:
    """Report the non-abstract methods of the modules of an entity contract."""
    contracts = {
        (fact["dir"], fact["file"]): fact for fact in facts.values() if fact["k"] == "y"
    }
    if not contracts:
        return
    for rel, fact in facts.items():
        if fact["k"] != "x":
            continue
        if fact["obj"]:
            contract = contracts.get((fact["dir"], fact["pair"]))
            key, section = f"{RULE_ID}.object", ""
        elif fact["row"] is None:
            contract = contracts.get((fact["dir"], fact["pair"]))
            key, section = f"{RULE_ID}.own", ""
        else:
            owner_file, section = fact["row"]
            contract = contracts.get((fact["dir"], owner_file))
            if contract is not None and section not in contract["rows"]:
                contract = None  # no such section: not a row module (structure/xbsl-pair)
            key = f"{RULE_ID}.row"
        if contract is None:
            continue
        for line, col, name, static in fact["methods"]:
            advice = i18n.t(f"{RULE_ID}.advice-static" if static else f"{RULE_ID}.advice")
            yield Diagnostic(
                rel, line, col, RULE_ID, Severity.ERROR,
                i18n.t(key, name=name, contract=contract["name"], section=section,
                       advice=advice),
            )
