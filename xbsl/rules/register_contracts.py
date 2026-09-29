"""Tier A: a register implements a type contract only (yaml/register-entity-contract).

An information register and an accumulation register take part in contracts through the types
they generate: the yaml names the contracts under `TypeOptions`, per type -
`InformationRegister.Record: Contracts: [...]`. The documentation lists both registers among the
implementations of a type contract (the dimensions, resources and attributes of the register and
the methods of its record module) and neither among those of an entity contract, which only a
catalog, a document, an exchange plan, an integrable application and a settings storage
implement, each with its object type. A live probe confirmed the refusal on an information
register that named the object type of an entity contract:

    Invalid type of contract "...::<Contract>.Object"; a type contract is expected

The rule is project-wide: the register names the contract, and only the contract's own
description says it is an entity contract. Either spelling of a file is read, and the message
names the key the way the file spells it. Narrowing, to keep the zero-false-positive bar:

- an entry is judged in the shape the probe settled - the object type of the contract
  (`<Contract>.Object`, either spelling of the facet, with or without the qualifying namespace);
  a bare name is left alone;
- a contract is found by its short name, and a name two contracts of the project share is
  skipped, as is a contract the project does not describe (one from a library);
- the other elements that implement type contracts only (a structure, a constants set, an
  interface component) are not judged: no probe has shown what the compiler answers there.

There is no quick fix: the cure is a decision - implement a type contract instead, or move the
data to an element that can implement the entity contract.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from functools import lru_cache

from xbsl import dataset, i18n, metamodel, terms
from xbsl.diagnostics import Diagnostic, Severity
from xbsl.engine import SourceFile, rule
from xbsl.rules.yaml_schema import (
    _HAVE_YAML,
    _composed,
    _parsed,
    object_kind,
    object_kind_fast,
    value_of,
)

if _HAVE_YAML:
    import yaml

MESSAGES = {
    "yaml/register-entity-contract.title": {
        "ru": "Регистр реализует контракт сущности",
        "en": "Register implements an entity contract",
    },
    "yaml/register-entity-contract.found": {
        "ru": "Регистр '{register}' называет в списке {key} контракт сущности '{contract}' "
              "('{entry}'): регистр может реализовать только контракт типа, сервер отвергнет "
              "сборку с 'Invalid type of contract ...; a type contract is expected'. Уберите "
              "строку из списка {key} или реализуйте контракт типа.",
        "en": "Register '{register}' names entity contract '{contract}' in the {key} list "
              "('{entry}'): a register can implement only a type contract, and the server "
              "rejects the build with 'Invalid type of contract ...; a type contract is "
              "expected'. Remove the entry from the {key} list or implement a type contract.",
    },
}
i18n.register(MESSAGES)

#: The kinds the rule judges, and the kinds whose names it resolves the entries against.
_REGISTER_KINDS = frozenset({"РегистрСведений", "РегистрНакопления"})
_CONTRACT_KINDS = frozenset({"КонтрактСущности", "КонтрактТипа", "КонтрактСервиса"})
_ENTITY_CONTRACT = "КонтрактСущности"
#: The keys on the way to an entry and the facet of the object type, in the metamodel's spelling.
_OPTIONS_KEY = "НастройкиТипов"
_CONTRACTS_KEY = "Контракты"
_OBJECT_FACET = "Объект"
_IDENT_RE = re.compile(r"[^\W\d]\w*")


@lru_cache(maxsize=1)
def _spellings() -> dict[str, frozenset[str]]:
    """Both spellings of the two keys and of the object facet, from the platform's own data."""
    out: dict[str, frozenset[str]] = {}
    for key in (_OPTIONS_KEY, _CONTRACTS_KEY):
        forms = (key, *terms.key_forms(key), metamodel.english_name(key))
        out[key] = frozenset(form for form in forms if form)
    out[_OBJECT_FACET] = frozenset(
        form for form in (_OBJECT_FACET, terms.facet_suffix_english(_OBJECT_FACET)) if form
    )
    return out


dataset.register_reset(_spellings.cache_clear)


def _contract_entries(source: SourceFile) -> list[tuple[str, str, str, int, int]]:
    """(the entry as written, the short name of the contract, the key as the file spells it,
    line, column) for every object type of a contract the element names under its type options."""
    root = _composed(source)
    if root is None or not isinstance(root, yaml.MappingNode):
        return []
    spellings = _spellings()
    out: list[tuple[str, str, str, int, int]] = []
    for key_node, options in root.value:
        if not (isinstance(key_node, yaml.ScalarNode) and key_node.value in spellings[_OPTIONS_KEY]
                and isinstance(options, yaml.MappingNode)):
            continue
        for _type_node, settings in options.value:
            if not isinstance(settings, yaml.MappingNode):
                continue
            for contracts_key, contracts in settings.value:
                if not (isinstance(contracts_key, yaml.ScalarNode)
                        and contracts_key.value in spellings[_CONTRACTS_KEY]
                        and isinstance(contracts, yaml.SequenceNode)):
                    continue
                for node in contracts.value:
                    if not isinstance(node, yaml.ScalarNode):
                        continue
                    written = node.value.strip()
                    head, _, facet = written.rpartition(".")
                    short = head.rsplit("::", 1)[-1]
                    if facet not in spellings[_OBJECT_FACET] or not _IDENT_RE.fullmatch(short):
                        continue  # a bare name or another shape - see the module docstring
                    quote = 1 if node.style in ("'", '"') else 0
                    out.append((written, short, contracts_key.value, node.start_mark.line + 1,
                                node.start_mark.column + 1 + quote))
    return out


def _mapper(source: SourceFile) -> dict | None:
    """A contract contributes its name and kind, a register the contract entries it names."""
    if source.kind != "yaml" or not _HAVE_YAML:
        return None
    if "Контракт" not in source.text and "Contract" not in source.text:
        return None  # neither a contract nor an element naming one - the cheap gate
    fast = object_kind_fast(source)
    if fast not in _CONTRACT_KINDS and fast not in _REGISTER_KINDS:
        return None
    data, err = _parsed(source)
    if err is not None or not isinstance(data, dict):
        return None
    kind = object_kind(data)
    name = value_of(data, "Имя", kind)
    if not isinstance(name, str) or not name:
        return None
    if kind in _CONTRACT_KINDS:
        return {"contract": (name, kind)}
    if kind not in _REGISTER_KINDS:
        return None
    entries = _contract_entries(source)
    return {"register": (name, entries)} if entries else None


@rule(
    "yaml/register-entity-contract", "yaml/register-entity-contract.title", "A",
    scope="project", severity=Severity.ERROR, mapper=_mapper,
)
def register_entity_contract(facts: dict[str, dict]) -> Iterable[Diagnostic]:
    kinds: dict[str, list[str]] = {}
    for fact in facts.values():
        if "contract" in fact:
            name, kind = fact["contract"]
            kinds.setdefault(name, []).append(kind)
    for rel, fact in sorted(facts.items()):
        if "register" not in fact:
            continue
        register, entries = fact["register"]
        for written, short, key, line, column in entries:
            if kinds.get(short) != [_ENTITY_CONTRACT]:
                continue  # a type contract, a shared name or one the project does not describe
            yield Diagnostic(
                rel, line, column, "yaml/register-entity-contract", Severity.ERROR,
                i18n.t("yaml/register-entity-contract.found", register=register,
                       contract=short, entry=written, key=key),
            )
