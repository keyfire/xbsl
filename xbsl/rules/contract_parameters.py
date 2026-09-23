"""Tier D: parameter names of a project contract implementation.

The rule code/contract-parameter-name.

An `@Implementation` method belongs to a project service contract named by its module yaml.
The compiler compares parameter names positionally with the contract's abstract method: a
mismatch is a warning below compatibility 8.0 and an error from 8.0 onward.

Only a uniquely matched project contract method with the same resolved signature is judged.
Platform-only contracts, incomplete projects, ambiguous methods and missing compatibility stay
silent. Trees and method declarations come from the shared project typing; the mapper adds only
the service-contract names which the generic element fact does not retain.
"""

from __future__ import annotations

import re
from collections.abc import Iterable

from xbsl import i18n
from xbsl import parser as P
from xbsl import typeinfer
from xbsl.diagnostics import Diagnostic, Severity
from xbsl.engine import SourceFile, rule
from xbsl.lexer import linemap
from xbsl.rules._server_calls import annotation_forms
from xbsl.rules.yaml_schema import _HAVE_YAML, _parsed, object_kind, value_of

RULE_ID = "code/contract-parameter-name"
_LATIN = re.compile(r"[A-Za-z]")
_CYRILLIC = re.compile(r"[А-Яа-яЁё]")

MESSAGES = {
    f"{RULE_ID}.title": {
        "ru": "Имя параметра реализации отличается от контракта",
        "en": "An implementation parameter name differs from its contract",
    },
    f"{RULE_ID}.found": {
        "ru": "Параметр '{actual}' метода '{method}' не совпадает с параметром '{expected}' "
              "абстрактного метода контракта '{contract}'.",
        "en": "Parameter '{actual}' of method '{method}' does not match parameter '{expected}' "
              "of the abstract method from contract '{contract}'.",
    },
}
i18n.register(MESSAGES)


def _wants_text(source: SourceFile) -> bool:
    if source.kind != "xbsl" or "метод" not in source.text.lower() and "method" not in source.text.lower():
        return False
    module, errors = P.parse(source)
    if errors:
        return False
    return any(
        isinstance(member, P.Method)
        and (member.is_abstract or _is_implementation(member))
        for member in module.members
    )


typeinfer.wants_text(_wants_text)


def _value(data: dict, russian: str, english: str):
    return data.get(russian, data.get(english))


def _service_contracts(source: SourceFile) -> tuple[str, list[str]] | None:
    if source.kind != "yaml" or not _HAVE_YAML:
        return None
    data, error = _parsed(source)
    if error is not None or not isinstance(data, dict) or object_kind(data) != "ОбщийМодуль":
        return None
    name = _value(data, "Имя", "Name")
    settings = value_of(data, "НастройкиТипа", "ОбщийМодуль")
    listed = value_of(settings, "Контракты")
    if not isinstance(name, str) or not isinstance(listed, list):
        return None
    contracts = [item.strip() for item in listed
                 if isinstance(item, str) and item.strip() and "::" not in item]
    return (name, contracts) if contracts else None


def _mapper(source: SourceFile) -> dict | None:
    fact = typeinfer.project_fact(source)
    if fact is None:
        return None
    related = _service_contracts(source)
    if related is None:
        return fact
    module, contracts = related
    return {**fact, "service_module": module, "service_contracts": contracts}


def _is_implementation(method: P.Method) -> bool:
    return any(annotation.name in annotation_forms("Реализация")
               for annotation in method.annotations)


def _methods(tree: P.Module) -> Iterable[P.Method]:
    return (member for member in tree.members if isinstance(member, P.Method))


def _written(ref: P.TypeRef | None) -> str | None:
    if ref is None:
        return None
    text = ref.text.strip()
    return text or None


def _same_type(
    catalog: typeinfer.ProjectCatalog,
    left: P.TypeRef | None,
    left_module: str,
    right: P.TypeRef | None,
    right_module: str,
) -> bool:
    left_text, right_text = _written(left), _written(right)
    if left_text is None or right_text is None:
        return left_text is None and right_text is None
    left_types = catalog.written(left_text, left_module)
    right_types = catalog.written(right_text, right_module)
    return left_types is not None and left_types == right_types


def _same_signature(
    catalog: typeinfer.ProjectCatalog,
    implementation: P.Method,
    implementation_module: str,
    abstract: P.Method,
    contract_module: str,
) -> bool:
    if (implementation.is_static != abstract.is_static
            or len(implementation.params) != len(abstract.params)
            or not _same_type(catalog, implementation.return_type, implementation_module,
                              abstract.return_type, contract_module)):
        return False
    for actual, expected in zip(implementation.params, abstract.params):
        if actual.default is not None or expected.default is not None:
            return False
        if not _same_type(catalog, actual.type, implementation_module,
                          expected.type, contract_module):
            return False
    return True


def _compatibilities(facts: dict[str, dict]) -> dict[str, tuple[int, ...] | None]:
    out: dict[str, tuple[int, ...] | None] = {}
    for root, group in typeinfer._projects(facts).items():
        declared = next((fact.get("compat") for fact in group.values()
                         if fact.get("k") == "project" and fact.get("root") in (root, ".")
                         and fact.get("compat")), None)
        mode = tuple(declared) if declared else None
        out.update({rel: mode for rel in group})
    return out


def _severity(mode: tuple[int, ...]) -> Severity:
    normalized = (*mode, 0, 0)
    return Severity.WARNING if normalized[:2] < (8, 0) else Severity.ERROR


def _proven_different(actual: str, expected: str) -> bool:
    """Whether two written names differ without needing the project's bilingual term table."""
    if actual == expected:
        return False
    actual_scripts = (bool(_LATIN.search(actual)), bool(_CYRILLIC.search(actual)))
    expected_scripts = (bool(_LATIN.search(expected)), bool(_CYRILLIC.search(expected)))
    return actual_scripts == expected_scripts


def _project_findings(
    group: dict[str, dict],
    typings: dict[str, typeinfer.ModuleTyping],
    modes: dict[str, tuple[int, ...] | None],
) -> Iterable[Diagnostic]:
    by_module = {typing.scope.module: typing for typing in typings.values()}
    related = {
        fact.get("service_module"): tuple(fact.get("service_contracts") or ())
        for fact in group.values() if fact.get("service_module")
    }
    abstract: dict[str, dict[str, list[P.Method]]] = {}
    for name, typing in by_module.items():
        element = typing.catalog.elements.get(name or "") or {}
        if element.get("kind") != "КонтрактСервиса" or not isinstance(typing.tree, P.Module):
            continue
        methods: dict[str, list[P.Method]] = {}
        for method in _methods(typing.tree):
            if method.is_abstract:
                methods.setdefault(method.name, []).append(method)
        abstract[name or ""] = methods
    for rel, typing in typings.items():
        mode = modes.get(rel)
        module = typing.scope.module or ""
        if mode is None or module not in related or not isinstance(typing.tree, P.Module):
            continue
        line_map = linemap(_TextSource(typing.text))
        for method in _methods(typing.tree):
            if not _is_implementation(method):
                continue
            candidates = [
                (contract, candidate)
                for contract in related[module]
                for candidate in (abstract.get(contract) or {}).get(method.name, ())
            ]
            if len(candidates) != 1:
                continue
            contract, target = candidates[0]
            if not _same_signature(typing.catalog, method, module, target, contract):
                continue
            for actual, expected in zip(method.params, target.params):
                if not _proven_different(actual.name, expected.name):
                    continue
                line, column = line_map.linecol(actual.start)
                severity = _severity(mode)
                yield Diagnostic(
                    rel, line, column, RULE_ID, severity,
                    i18n.t(f"{RULE_ID}.found", actual=actual.name, expected=expected.name,
                           method=method.name, contract=contract),
                )


@rule(
    RULE_ID, f"{RULE_ID}.title", "D", scope="project", severity=Severity.ERROR,
    mapper=_mapper,
)
def contract_parameter_name(facts: dict[str, dict]) -> Iterable[Diagnostic]:
    """Parameter names of a uniquely matched project contract implementation."""
    typings = typeinfer.project_typings(facts)
    modes = _compatibilities(facts)
    for _root, group in typeinfer._projects(facts).items():
        rels = set(group)
        subset = {rel: typing for rel, typing in typings.items() if rel in rels}
        yield from _project_findings(group, subset, modes)


class _TextSource:
    def __init__(self, text: str) -> None:
        self.text = text
        self.cache: dict = {}
