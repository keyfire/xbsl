"""Tier D: a client-available server method that only reads the text of a package resource.

`ResourcesPackage.Current().Get(Path).OpenReadableStream().ReadAsString()` reads a file of the
build. In the type catalog the package and a resource have reading members only (`Current`,
`Get`, `GetAll`; `Path`, `Reference`, `OpenReadableStream`), so the text of a file changes with
a new build and not in between. A server method available from the client costs a server call
whenever the client calls it. With `CacheResult = True` the first answer is kept on the client
for the session of the user, per set of arguments, and exceptions are not kept (the page of the
`AvailableFromClient` annotation). The finding offers that cache or passing the text through the
client parameters. The author decides, because only the author knows how long the result may
live.

One shape is proven, and anything else is left alone:

- the body of a module method is a single `return` of exactly that chain;
- `Get` takes one argument and `ReadAsString` at most one. Each is a string literal without
  interpolation or a parameter of the method, and a parameter default is a literal. A member,
  a call, an operator or an interpolation may bring in the user, the settings or other data;
- the root is the platform type. It is spelled the way the dictionary spells the type, and no
  parameter, member or import of the module, no `Name` of the paired description and no project
  element carries the name in either spelling. Names are compared ignoring case;
- every link is checked against the type catalog: `Current` returns the package, `Get` a
  resource, `OpenReadableStream` a readable stream and `ReadAsString` a string. Without the
  platform data the rule is silent.

Availability, environment and `CacheResult` are the facts of the shared server call model
(`_server_calls`), so `code/computed-property-server-call` and this rule agree on what a
client-available server method is. A client variant wins, a handler is not a candidate, and an
enabled or unknown cache is not reported. The rule skips a module without valid paired metadata,
a duplicated method or element name, and a module the parser could not read.
"""

from __future__ import annotations

from collections.abc import Iterable

from xbsl import dataset, i18n, parser as P, terms
from xbsl.diagnostics import Diagnostic, Severity
from xbsl.engine import SourceFile, is_query_file, rule
from xbsl.rules._server_calls import ServerCallGraph, server_call_mapper
from xbsl.rules.environment import _parsed_object
from xbsl.rules.style_literals import _interpolated

MESSAGES = {
    "code/resource-read-without-cache.title": {
        "ru": "Чтение ресурса без кеша результата",
        "en": "Resource read without the result cache",
    },
    "code/resource-read-without-cache.found": {
        "ru": "Метод '{method}' доступен с клиента и только читает текст ресурса из "
              "{n[ПакетРесурсов]} без штатного кеша результата. Ресурс меняется только вместе "
              "со сборкой. Проверьте, как долго результат должен оставаться верным, и "
              "рассмотрите {n[КешироватьРезультат]} = {n[Истина]} в аннотации "
              "{n[ДоступноСКлиента]}. Текст можно также передать клиенту через "
              "{n[ПараметрыРаботыКлиента]}.",
        "en": "Method '{method}' is available from the client and only reads the text of a "
              "{n[ПакетРесурсов]} resource, without the standard result cache. A resource "
              "changes only with the build. Check how long the result must stay valid and "
              "consider {n[КешироватьРезультат]} = {n[Истина]} in the {n[ДоступноСКлиента]} "
              "annotation. The text can also reach the client through "
              "{n[ПараметрыРаботыКлиента]}.",
    },
}
i18n.register(MESSAGES)

_RULE = "code/resource-read-without-cache"

#: The root type and the links of the chain in the Russian spelling. The English spellings and
#: the type every link returns are read from the platform data.
_ROOT = "ПакетРесурсов"
_LINKS = ("Текущий", "Получить", "ОткрытьПотокЧтения", "ПрочитатьКакСтроку")
_RESULT = "Строка"
#: The fewest and the most arguments of every link this shape accepts.
_ARITY = ((0, 0), (1, 1), (0, 0), (0, 1))
#: Literal kinds a parameter default may have: none of them reads anything at call time.
_CONSTANT_KINDS = frozenset({"STRING", "NUMBER", "TRUE", "FALSE", "UNDEFINED"})


_Chain = tuple[frozenset[str], tuple[frozenset[str], ...]]
#: The answer of a catalog that was read; the dataset reset hooks empty it.
_PROOF: dict[str, _Chain | None] = {}


def _chain() -> _Chain | None:
    """Spellings of the root and of every link, checked by the type catalog; None if unproven.

    Every link must return the type the next one is declared on, and the last one a string. A
    catalog that says otherwise, or no catalog at all, leaves the shape unproven. Only the answer
    of a catalog that was read is kept: data installed while an editor or an MCP server keeps
    running must not meet a remembered None.
    """
    if "chain" not in _PROOF:
        try:
            stdlib = dataset.load_json("stdlib.json") or {}
        except dataset.DatasetError:
            return None
        _PROOF["chain"] = _prove(stdlib)
    return _PROOF["chain"]


def _prove(stdlib: dict) -> _Chain | None:
    member_types = stdlib.get("member_types") or {}
    names = frozenset(stdlib.get("names") or ())
    owner = _ROOT
    links: list[frozenset[str]] = []
    for member in _LINKS:
        returned = (member_types.get(owner) or {}).get(member)
        if not isinstance(returned, str):
            return None
        english = terms.member_english_of(owner, member)
        links.append(frozenset({member, english} if english else {member}))
        owner = dataset.member_type_head(returned)
    roots = frozenset(form for form in terms.forms(_ROOT, "types") if form in names)
    if owner != _RESULT or _ROOT not in roots:
        return None
    return roots, tuple(links)


dataset.register_reset(_PROOF.clear)


def _plain(value: P.Expr | None, params: frozenset[str]) -> bool:
    """A string literal without interpolation, or a parameter of the method."""
    if isinstance(value, P.Literal):
        return value.kind == "STRING" and not _interpolated(value.text)
    return isinstance(value, P.Name) and value.name in params


def _constant_default(value: P.Expr | None) -> bool:
    if value is None:
        return True
    return (isinstance(value, P.Literal) and value.kind in _CONSTANT_KINDS
            and not (value.kind == "STRING" and _interpolated(value.text)))


def _links(expr: P.Expr | None) -> tuple[str, list[tuple[str, P.Call]]] | None:
    """The root name and the (member, call) pairs of a plain call chain, innermost first."""
    links: list[tuple[str, P.Call]] = []
    node = expr
    while isinstance(node, P.Call):
        callee = node.callee
        if not isinstance(callee, P.Member) or callee.safe:
            return None
        links.append((callee.name, node))
        node = callee.obj
    if not isinstance(node, P.Name):
        return None
    links.reverse()
    return node.name, links


def _reads_resource_text(module: P.Module, method: P.Method, chain: _Chain) -> bool:
    """Whether the method body is exactly the proven read and nothing local hides its root."""
    roots, spellings = chain
    if len(method.body) != 1 or not isinstance(method.body[0], P.Return):
        return False
    if not all(_constant_default(param.default) for param in method.params):
        return False
    found = _links(method.body[0].value)
    if found is None:
        return False
    root, links = found
    if root not in roots or len(links) != len(spellings):
        return False
    params = frozenset(param.name for param in method.params)
    for (member, call), names, (fewest, most) in zip(links, spellings, _ARITY):
        if (member not in names or call.type_args or not fewest <= len(call.args) <= most
                or not all(_plain(arg.value, params) for arg in call.args)):
            return False
    # A parameter, a declaration or an import of the module may hide the platform type.
    folded = {name.casefold() for name in roots}
    local = [param.name for param in method.params]
    local += [getattr(member, "name", "") for member in module.members]
    local += [item.name.rsplit("::", 1)[-1] for item in module.imports]
    return not any(name.casefold() in folded for name in local)


def _names_root(source: SourceFile, roots: frozenset[str]) -> bool:
    """Whether any `Name` of the description spells the root, in either spelling or case."""
    folded = {root.casefold() for root in roots}
    text = source.text.casefold()
    if not any(root in text for root in folded):
        return False
    keys = frozenset(terms.key_forms("Имя"))
    stack: list[object] = [_parsed_object(source)]
    while stack:
        node = stack.pop()
        if isinstance(node, dict):
            for key, value in node.items():
                if key in keys and isinstance(value, str) and value.casefold() in folded:
                    return True
                stack.append(value)
        elif isinstance(node, list):
            stack.extend(node)
    return False


def _resource_read_mapper(source: SourceFile) -> dict | None:
    """The shared server call facts, narrowed to what this rule reads.

    A description keeps its kind, names and base, and says whether it names the root anywhere.
    A module is kept only when one of its methods is the proven read. The shared fact is copied
    and never changed: the other rules hold the same cached dictionary.
    """
    chain = _chain()
    if chain is None:
        return None
    if source.kind == "yaml":
        fact = server_call_mapper(source)
        if fact is None or not fact.get("valid"):
            return fact
        return {**fact, "bindings": [], "names_root": _names_root(source, chain[0])}
    if source.kind != "xbsl" or is_query_file(source.path):
        return None
    if not any(root in source.text for root in chain[0]):
        return None
    fact = server_call_mapper(source)
    if fact is None or fact.get("methods") is None:
        return None
    module, _errors = P.parse(source)
    reads = list(dict.fromkeys(
        member.name for member in module.members
        if isinstance(member, P.Method) and _reads_resource_text(module, member, chain)))
    return {**fact, "reads": reads} if reads else None


@rule(
    _RULE, f"{_RULE}.title", "D",
    scope="project", severity=Severity.INFO, mapper=_resource_read_mapper,
)
def resource_read_without_cache(facts: dict[str, dict]) -> Iterable[Diagnostic]:
    """One finding per proven reader, at the name of the method."""
    chain = _chain()
    if chain is None or not any(fact.get("reads") for fact in facts.values()):
        return
    graph = ServerCallGraph(facts)
    folded = {root.casefold() for root in chain[0]}
    # A project element named like the root hides the platform type from every module.
    if not graph.has_data or any(name.casefold() in folded for name in graph.names):
        return
    for rel, fact in sorted(facts.items()):
        if fact["k"] != "x" or not fact.get("reads"):
            continue
        stem = fact["stem"]
        meta = graph.metadata.get(stem, {})
        name = meta.get("name")
        scope = graph.shadows(stem)
        if (not meta.get("valid") or meta.get("names_root") or not isinstance(name, str)
                or len(graph.names.get(name, ())) != 1 or scope is None
                or any(item.casefold() in folded for item in scope)):
            continue
        methods = fact["methods"] or {}
        found = []
        for method_name in fact["reads"]:
            method = methods.get(method_name)
            if (method is None or method["handler"] or not method["available"]
                    or method["cache"] not in ("missing", "false")
                    or graph.method_environment(stem, method) != "server"):
                continue
            found.append((method["line"], method["col"], method_name))
        for line, col, method_name in sorted(found):
            yield Diagnostic(rel, line, col, _RULE, Severity.INFO,
                             i18n.t(f"{_RULE}.found", method=f"{name}.{method_name}"))
