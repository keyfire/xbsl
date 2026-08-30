"""Tier D: an image property bound to an expression that reaches the server.

The code/image-binding-server-call rule. In the yaml of an interface component the Image
property of a platform component is bound to an expression (`Изображение: =...`) whose
call resolves - directly or transitively - into a server method. Such a project compiles
and even shows the picture, which is why the finding is INFO: the cost is timing, not
correctness. The platform draws the component first and evaluates the binding after, so
the image arrives by its OWN server round-trip once the rows are already on screen, and
the expression runs again - another round-trip - on every redraw. Measured on a live
account page: the rows were drawn at 1197 ms, the logos arrived at 2049 ms; the cure that
fixed it hands the image over WITH the row (a field of the query or of a joined table) or
builds it from data already on the client (a resource reference, a ready Url).

The predicate, with every narrowing settled on the live corpora:

- a node is judged only when its type names a SCHEMA component that declares the Image
  property (Picture, Button, StandardTableColumn, Label among others - the set comes from
  the ui schema); a project component's own property that happens to carry the same name
  is never judged;
- the value must be a plain-scalar `=` binding that CONTAINS a call: `=RowData.Data.Logo`
  without parentheses is the cure (the field came with the row), not a finding;
- a constructor head after `новый`/`new` is a type, not a method to resolve - without the
  skip the type name of `=новый РазмерБайтов(...)` reads as an unresolved call;
- a call resolves into the server through: a member of an element module of a server kind
  (Catalog, Document, InformationRegister, Processing, HttpService, ScheduledJob,
  AccessKey, ServiceContract - their modules live in the Server environment, docs
  topics/module-execution), a member of a common module with `Environment: Server`, a
  method annotated @OnServer wherever it is declared, or a client method that TRANSITIVELY
  calls any of those. The transitive step is what the live case needed: the account page
  reached the server through a client wrapper method of the form module;
- an unresolved name is skipped rather than guessed: a built-in, a library module, a chain
  of three and more segments, a shadowed root - a missed case is a false negative, never a
  false positive on working code.

Bare calls of a binding resolve in the module paired with the yaml by stem; qualified
calls resolve by element name across the project - hence the project scope. The call map
is built the way the environment checks of this tier build theirs (_module_decls /
_method_bodies / _shadowed_names), and the server-kind list follows the module-execution
table rather than guessing about the kinds it does not name.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from functools import lru_cache

from xbsl import dataset, i18n, uischema
from xbsl.diagnostics import Diagnostic, Severity
from xbsl.engine import SourceFile, rule
from xbsl.rules._syntax import code_tokens
from xbsl.rules.enum_values import _shadowed_names
from xbsl.rules.environment import (
    _decl_anchors,
    _environment_forms,
    _method_bodies,
    _module_decls,
    _on_server_forms,
    _pair_stem,
    _parsed_object,
)
from xbsl.rules.yaml_schema import (
    _composed,
    _HAVE_YAML,
    _mapping_nodes,
    _scalar_entries,
    object_kind,
    value_of,
)

if _HAVE_YAML:
    import yaml

MESSAGES = {
    "code/image-binding-server-call.title": {
        "ru": "Картинка отдельным серверным вызовом",
        "en": "An image by a separate server call",
    },
    "code/image-binding-server-call.direct": {
        "ru": "Свойство '{prop}' вычисляется выражением с серверным вызовом '{call}' – "
              "картинка приезжает отдельным обращением к серверу после отрисовки и "
              "перезапрашивается при каждой перерисовке. Отдавайте её вместе с данными "
              "(полем запроса или присоединённой таблицы) либо стройте из клиентских "
              "данных (ресурс, готовый Url).",
        "en": "Property '{prop}' is computed by an expression with the server call "
              "'{call}' - the image arrives by its own server round-trip after the rows "
              "are drawn and is requested again on every redraw. Hand it over with the "
              "data (a field of the query or of a joined table), or build it from "
              "client-side data (a resource, a ready Url).",
    },
    "code/image-binding-server-call.chain": {
        "ru": "Свойство '{prop}' вычисляется выражением с вызовом '{call}', транзитивно "
              "доходящим до серверного метода '{endpoint}' – картинка приезжает отдельным "
              "обращением к серверу после отрисовки и перезапрашивается при каждой "
              "перерисовке. Отдавайте её вместе с данными (полем запроса или "
              "присоединённой таблицы) либо стройте из клиентских данных (ресурс, "
              "готовый Url).",
        "en": "Property '{prop}' is computed by an expression whose call '{call}' "
              "transitively reaches the server method '{endpoint}' - the image arrives by "
              "its own server round-trip after the rows are drawn and is requested again "
              "on every redraw. Hand it over with the data (a field of the query or of a "
              "joined table), or build it from client-side data (a resource, a ready Url).",
    },
}
i18n.register(MESSAGES)

# Kinds whose element module lives in the Server environment (docs topics/module-execution):
# a bare `Имя.Метод(...)` of such an element is a server hop whatever the method says.
_SERVER_KINDS = ("HttpСервис", "Документ", "ЗапланированноеЗадание", "КлючДоступа",
                 "КонтрактСервиса", "Обработка", "РегистрСведений", "Справочник")

#: String and pattern literals of a binding expression: a `(` inside them is text.
_QUOTED_RE = re.compile(r"\"[^\"\n]*\"|'[^'\n]*'")

#: An identifier chain followed by `(` - the call form of a binding expression.
_CHAIN_RE = re.compile(r"[^\W\d]\w*(?:[ \t]*\.[ \t]*[^\W\d]\w*)*[ \t]*\(")

#: The constructor keyword closing the text before a chain. Spelled out like in
#: xbsl/lsp_nav.py: the two forms are the language's own and are not in the term data.
_NEW_RE = re.compile(r"(?:^|[^\w])(?:новый|new)$")


@lru_cache(maxsize=1)
def _image_components() -> frozenset[str]:
    """Schema components that declare the Image property, in the schema's own spellings.

    The gate that keeps a project component's namesake property out: the node's type must
    canonicalize into this set before its Image value is judged at all.
    """
    schema = dataset.load_ui_schema()
    if not schema:
        return frozenset()
    return frozenset(
        name for name, rec in (schema.get("components") or {}).items()
        if "Изображение" in (rec.get("props") or {})
    )


@lru_cache(maxsize=1)
def _image_key_re() -> re.Pattern | None:
    """The fast path: a line binding the Image property, in either spelling.

    Composing the node graph costs a second, pure-python parse of the file, so it only
    happens when the text carries at least one line this rule could judge.
    """
    if not _image_components():
        return None
    spellings = {"Изображение"}
    english = uischema.english_property("Изображение")
    if english:
        spellings.add(english)
    return re.compile(
        r"(?m)^[ \t]*(?:-[ \t]+)?(?:%s)[ \t]*:[ \t]*="
        % "|".join(sorted(map(re.escape, spellings)))
    )


dataset.register_reset(_image_components.cache_clear)
dataset.register_reset(_image_key_re.cache_clear)


def _binding_calls(expr: str) -> list[list[str]]:
    """[root, member, the call as written] for every resolvable call of an expression.

    root is "" for a bare call of the paired module. Skipped rather than guessed: a
    constructor head after `новый`/`new`, a chain of three and more segments, a chain that
    is itself a member of a computed value (preceded by `.`) or namespace-qualified
    (preceded by `:`). Quoted literals are cut out first.
    """
    cleaned = _QUOTED_RE.sub(" ", expr)
    out: list[list[str]] = []
    seen: set[tuple[str, str]] = set()
    for m in _CHAIN_RE.finditer(cleaned):
        before = cleaned[: m.start()].rstrip()
        if before.endswith((".", ":")):
            continue  # a member of a computed value, or namespace-qualified
        if _NEW_RE.search(before):
            continue  # a constructor names a type, not a method to resolve
        segments = [s.strip() for s in m.group(0)[:-1].rstrip().split(".")]
        if len(segments) == 1:
            key = ("", segments[0])
        elif len(segments) == 2:
            key = (segments[0], segments[1])
        else:
            continue  # a deeper chain does not resolve statically
        if key not in seen:
            seen.add(key)
            out.append([key[0], key[1], ".".join(segments)])
    return out


def _image_bindings(source: SourceFile) -> list[list]:
    """[line, col, the property as written, calls] per image binding that holds a call."""
    root = _composed(source)
    if root is None:
        return []
    components = _image_components()
    out: list[list] = []
    for mapping in _mapping_nodes(root):
        entries = _scalar_entries(mapping)
        type_entry = entries.get("Тип")
        if type_entry is None or not isinstance(type_entry[1], yaml.ScalarNode):
            continue
        head = uischema.canonical_component(type_entry[1].value.split("<", 1)[0].strip())
        if head not in components:
            continue  # not a platform component with an Image property
        image = entries.get("Изображение")
        if image is None:
            continue
        key_node, value_node = image
        if not isinstance(value_node, yaml.ScalarNode) or value_node.style:
            continue  # a quoted or block scalar is a literal, not a binding
        value = value_node.value.strip()
        if not value.startswith("="):
            continue
        calls = _binding_calls(value[1:])
        if calls:
            out.append([value_node.start_mark.line + 1, value_node.start_mark.column + 1,
                        key_node.value, calls])
    return out


def _image_binding_mapper(source: SourceFile) -> dict | None:
    """The map phase. A yaml contributes either its image bindings (an interface
    component), its name as a server hop (a server-kind element, a server common module)
    or its name as a resolvable module (any other common module); a module contributes,
    per method, the @OnServer bit and the resolvable calls of its body. The reduce joins
    the pairs by stem and walks the calls."""
    if not _HAVE_YAML:
        return None
    if source.kind == "yaml":
        data = _parsed_object(source)
        if data is None:
            return None
        kind = object_kind(data)
        stem = _pair_stem(source.rel)
        if kind == "КомпонентИнтерфейса":
            gate = _image_key_re()
            if gate is None or not gate.search(source.text):
                return None
            bindings = _image_bindings(source)
            if not bindings:
                return None
            return {"k": "y", "stem": stem, "role": "form", "bindings": bindings}
        name = value_of(data, "Имя", kind)
        if not isinstance(name, str) or not name:
            return None
        if kind in _SERVER_KINDS:
            return {"k": "y", "stem": stem, "role": "server", "name": name}
        if kind == "ОбщийМодуль":
            server_env, _client_env = _environment_forms()
            env = value_of(data, "Окружение", kind)
            role = "server" if env in server_env else "module"
            return {"k": "y", "stem": stem, "role": role, "name": name}
        return None
    if source.kind != "xbsl":
        return None
    toks = code_tokens(source)
    _decls, methods = _module_decls(toks)
    if not methods:
        return None
    on_server = _on_server_forms()
    server_bit = {name: bool(anns & on_server) for name, anns, _ in methods}
    bodies = _method_bodies(toks, methods, _decl_anchors(toks))
    shadowed = _shadowed_names(toks)
    n = len(toks)
    calls: dict[str, list[list[str]]] = {}
    for name, (start, end) in bodies.items():
        seen: set[tuple[str, str]] = set()
        for i in range(start, min(end, n)):
            t = toks[i]
            if t.kind != "IDENT" or t.value in shadowed:
                continue
            prev = toks[i - 1] if i else None
            if prev is not None and prev.kind == "OP" and prev.value in (".", "::"):
                continue  # a member of another value, or namespace-qualified
            if prev is not None and prev.kind == "KEYWORD" and prev.canonical == "NEW":
                continue  # a constructor names a type, not a method to resolve
            if i + 1 < n and toks[i + 1].kind == "OP" and toks[i + 1].value == "(":
                if t.value not in server_bit:
                    continue  # a bare call of a built-in or an unknown name
                key = ("", t.value)
            elif (i + 3 < n and toks[i + 1].kind == "OP" and toks[i + 1].value == "."
                    and toks[i + 2].kind == "IDENT"
                    and toks[i + 3].kind == "OP" and toks[i + 3].value == "("):
                key = (t.value, toks[i + 2].value)
            else:
                continue
            if key not in seen:
                seen.add(key)
                calls.setdefault(name, []).append(list(key))
    if not any(server_bit.values()) and not calls:
        return None
    return {"k": "x", "stem": _pair_stem(source.rel), "server": server_bit, "calls": calls}


@rule(
    "code/image-binding-server-call", "code/image-binding-server-call.title", "D",
    scope="project", severity=Severity.INFO, mapper=_image_binding_mapper,
)
def image_binding_server_call(facts: dict[str, dict]) -> Iterable[Diagnostic]:
    forms: list[tuple[str, str, list]] = []
    server_names: set[str] = set()
    module_stems: dict[str, str] = {}
    modules: dict[str, dict] = {}
    for rel, fact in facts.items():
        if fact["k"] == "y":
            if fact["role"] == "form":
                forms.append((rel, fact["stem"], fact["bindings"]))
            elif fact["role"] == "server":
                server_names.add(fact["name"])
            else:
                module_stems[fact["name"]] = fact["stem"]
        else:
            modules[fact["stem"]] = fact
    if not forms:
        return

    # Positive results are memoized; negatives are not, so a path truncated by the cycle
    # guard cannot cache "not server" for a method whose other callers would reach it.
    memo: dict[tuple[str, str], str] = {}

    def endpoint(stem: str, method: str, active: set) -> str | None:
        """The server endpoint a method reaches, or None. Bare while it is a method of
        the module itself, dotted once the chain crosses into another element."""
        key = (stem, method)
        if key in memo:
            return memo[key]
        if key in active:
            return None
        fact = modules.get(stem)
        if fact is None or method not in fact["server"]:
            return None  # an unresolved name is skipped, not guessed
        if fact["server"][method]:
            memo[key] = method
            return method
        active.add(key)
        for root, member in fact["calls"].get(method, ()):
            hit = resolve_call(stem, root, member, active)
            if hit is not None:
                memo[key] = hit
                return hit
        return None

    def resolve_call(stem: str, root: str, member: str, active: set) -> str | None:
        """The server endpoint of one call, or None when the call stays on the client."""
        if not root:
            return endpoint(stem, member, active)
        if root in server_names:
            return f"{root}.{member}"  # the element module lives on the server whole
        target = module_stems.get(root)
        if target is None:
            return None
        hit = endpoint(target, member, active)
        if hit is None:
            return None
        return hit if "." in hit else f"{root}.{hit}"

    for rel, stem, bindings in sorted(forms):
        for line, col, prop, binding_calls in bindings:
            for root, member, spelled in binding_calls:
                hit = resolve_call(stem, root, member, set())
                if hit is None:
                    continue
                if hit == spelled:
                    message = i18n.t("code/image-binding-server-call.direct",
                                     prop=prop, call=spelled)
                else:
                    message = i18n.t("code/image-binding-server-call.chain",
                                     prop=prop, call=spelled, endpoint=hit)
                yield Diagnostic(
                    rel, line, col, "code/image-binding-server-call",
                    Severity.INFO, message,
                )
                break  # one finding per binding: the cure is the same
