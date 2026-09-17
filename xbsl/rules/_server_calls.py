"""Shared, serializable facts for client bindings and server endpoint rules.

Only module methods and bare or single-receiver calls are resolved. Locals, metadata
properties, names a component inherits, ambiguous declarations and deferred closures
are deliberately left alone. Metadata whose used fields have unexpected types is
recorded like malformed YAML. The image rule retains its historical metadata-only
server inference when the source module is absent; other consumers require a declared,
client-available endpoint.
"""

from __future__ import annotations

from collections import defaultdict
from functools import lru_cache

from xbsl import dataset, engine, parser as P, terms, uischema
from xbsl.engine import SourceFile
from xbsl.rules.environment import _both_env_forms, _environment_forms, _pair_stem, _parsed_object
from xbsl.rules.locals_usage import _Walk
from xbsl.rules.style_variables import _component_extras, _inherited_properties
from xbsl.rules.yaml_schema import (
    _HAVE_YAML, _composed, _mapping_nodes, _parsed, _scalar_entries, object_kind, value_of,
)

if _HAVE_YAML:
    import yaml


SERVER_KINDS = frozenset({"HttpСервис", "Документ", "ЗапланированноеЗадание", "КлючДоступа",
                          "КонтрактСервиса", "Обработка", "РегистрСведений", "Справочник"})


@lru_cache(maxsize=None)
def annotation_forms(name: str) -> frozenset[str]:
    """Annotation and argument spellings from the selected platform dictionary."""
    return frozenset((*terms.key_forms(name), terms.common_english(name) or name))


@lru_cache(maxsize=1)
def _catalogs() -> tuple[dict, frozenset[str]] | None:
    """The ui schema and the stdlib names; None where the platform data is not installed."""
    try:
        stdlib = dataset.load_json("stdlib.json") or {}
    except dataset.DatasetError:
        return None
    return dataset.load_ui_schema() or {}, frozenset(stdlib.get("names", ()))


@lru_cache(maxsize=None)
def _platform_scope(head: str) -> frozenset[str] | None:
    """Properties and events a platform base type gives a component; None if unknown.

    A form's command is one of them: `WriteAndClose.Execute()` runs the inherited
    property and never reaches a common module that happens to share the name.
    """
    canonical = uischema.canonical_component(head)
    try:
        members = (dataset.load_json("stdlib.json") or {}).get("type_members") or {}
    except dataset.DatasetError:
        return None
    if canonical not in members:
        return None
    return _inherited_properties(canonical)


dataset.register_reset(annotation_forms.cache_clear)
dataset.register_reset(_catalogs.cache_clear)
dataset.register_reset(_platform_scope.cache_clear)


def _type_head(written: str) -> str:
    """The type name before generic arguments: `ObjectForm<Tasks.Object>` -> `ObjectForm`."""
    return written.split("<", 1)[0].strip()


def cache_state(source: SourceFile, annotations: list[P.Annotation]) -> str:
    """Return missing/false/true/unknown/not-applicable, without evaluating expressions.

    A literal must be the entire named argument. False followed by an operator is
    unknown, as are repeated annotations, duplicate arguments and positional arguments.
    """
    available = [a for a in annotations if a.name in annotation_forms("ДоступноСКлиента")]
    if not available:
        return "not-applicable"
    if len(available) != 1:
        return "unknown"
    from xbsl.lexer import tokenize

    ann = available[0]
    toks = [t for t in tokenize(source.text[ann.start:ann.end])
            if t.kind not in ("COMMENT", "BOM", "EOF")]
    if not any(t.value == "(" for t in toks):
        return "missing"
    start = next(i for i, t in enumerate(toks) if t.value == "(")
    args = toks[start + 1:-1]
    if not args:
        return "missing"
    # The platform annotation has a single optional CacheResult argument.
    if (len(args) == 3 and args[0].value in annotation_forms("КешироватьРезультат")
            and args[1].value == "="):
        if args[2].canonical == "TRUE":
            return "true"
        if args[2].canonical == "FALSE":
            return "false"
    return "unknown"


class _Calls(_Walk):
    """Reuse lexical scopes, but never enter a deferred lambda or method reference."""

    def __init__(self, source: SourceFile, own: set[str]):
        super().__init__(source)
        self.own = own
        self.calls: list[list[str]] = []

    def _expr(self, e: P.Expr | None) -> None:
        if isinstance(e, (P.Lambda, P.MethodRef)):
            return
        if isinstance(e, P.Call):
            callee = e.callee
            root = ""
            member = ""
            if isinstance(callee, P.Name):
                member = callee.name
            elif (isinstance(callee, P.Member) and not callee.safe
                  and isinstance(callee.obj, P.Name)):
                root, member = callee.obj.name, callee.name
            receiver = root or member
            if (member and "::" not in receiver and receiver not in self.own
                    and self._resolve(receiver) is None):
                call = [root, member, f"{root}.{member}" if root else member]
                if call not in self.calls:
                    self.calls.append(call)
        super()._expr(e)


def binding_calls(expression: str) -> list[list[str]]:
    """Calls evaluated by a plain binding expression; malformed expressions give none."""
    source = engine.load_text("binding.xbsl", f"method Binding()\nreturn {expression}\n;\n")
    try:
        module, errors = P.parse(source)
    except dataset.DatasetError:
        return []  # a YAML-only installation has no language data to read the expression
    if errors or len(module.members) != 1 or not isinstance(module.members[0], P.Method):
        return []
    walk = _Calls(source, set())
    walk.method(module.members[0])
    return walk.calls


class _Malformed(ValueError):
    """A metadata field the graph reads has a type that no valid description carries."""


def _optional_text(value) -> str | None:
    if value is None or isinstance(value, str):
        return value
    raise _Malformed


def _named_items(data: dict, section: str, kind: str | None) -> list[str]:
    rows = value_of(data, section, kind)
    if rows is None:
        return []
    if not isinstance(rows, list):
        raise _Malformed
    names = []
    for row in rows:
        name = value_of(row, "Имя") if isinstance(row, dict) else None
        if not isinstance(name, str):
            raise _Malformed
        names.append(name)
    return names


def _base(data: dict, kind: str | None) -> str | None:
    inherits = value_of(data, "Наследует", kind)
    if inherits is None:
        return None
    written = value_of(inherits, "Тип") if isinstance(inherits, dict) else None
    if not isinstance(written, str) or not _type_head(written):
        raise _Malformed
    return written


def _bindings(source: SourceFile) -> list[dict]:
    if "=" not in source.text or "(" not in source.text:
        return []
    root = _composed(source)
    if root is None:
        return []
    result = []
    for mapping in _mapping_nodes(root):
        entries = _scalar_entries(mapping)
        type_entry = entries.get("Тип")
        if type_entry is None or not isinstance(type_entry[1], yaml.ScalarNode):
            continue
        component = _type_head(type_entry[1].value)
        # Keep original keys: a project's own property spellings may be distinct.
        for key, value in mapping.value:
            if (not isinstance(key, yaml.ScalarNode) or not isinstance(value, yaml.ScalarNode)
                    or value.style or not value.value.strip().startswith("=")):
                continue
            calls = binding_calls(value.value.strip()[1:])
            if calls:
                result.append({"component": component, "property": key.value,
                               "line": value.start_mark.line + 1,
                               "col": value.start_mark.column + 1, "calls": calls})
    return result


def server_call_mapper(source: SourceFile) -> dict | None:
    """Map metadata and methods once per source; facts contain only JSON values."""
    key = "server_call_facts"
    if key not in source.cache:
        source.cache[key] = _map(source)
    return source.cache[key]


def _map(source: SourceFile) -> dict | None:
    if not _HAVE_YAML:
        return None
    stem = _pair_stem(source.rel)
    if source.kind == "yaml":
        data = _parsed_object(source)
        if data is None:
            _data, error = _parsed(source)
            return {"k": "y", "stem": stem, "valid": False} if error else None
        kind = object_kind(data)
        try:
            fact = {"k": "y", "stem": stem, "valid": True, "kind": kind,
                    "name": _optional_text(value_of(data, "Имя", kind)),
                    "environment": _optional_text(value_of(data, "Окружение", kind)),
                    "properties": _named_items(data, "Свойства", kind),
                    "events": _named_items(data, "События", kind), "base": _base(data, kind)}
        except _Malformed:
            # A date, list or mapping where the platform expects a name keeps the target
            # out of the analysis and out of the JSON facts.
            return {"k": "y", "stem": stem, "valid": False}
        fact["bindings"] = _bindings(source) if kind == "КомпонентИнтерфейса" else []
        return fact
    if source.kind != "xbsl":
        return None
    module, errors = P.parse(source)
    if errors:
        return {"k": "x", "stem": stem, "methods": None, "own": []}
    own = {m.name for m in module.members if isinstance(m, (P.Structure, P.Enum, P.ObjectField))}
    methods: dict[str, dict | None] = {}
    for method in module.members:
        if not isinstance(method, P.Method):
            continue
        if method.name in methods:
            methods[method.name] = None
            continue
        anns = {a.name for a in method.annotations}
        walk = _Calls(source, own)
        walk.method(method)
        declaration = next((t for i, t in enumerate(walk.code)
                            if method.start <= t.start < method.end and t.value == method.name
                            and i and walk.code[i - 1].canonical == "METHOD"), None)
        methods[method.name] = {
            "line": declaration.line if declaration else 1,
            "col": declaration.col if declaration else 1,
            "on_server": bool(anns & annotation_forms("НаСервере")),
            "on_client": bool(anns & annotation_forms("НаКлиенте")),
            "available": bool(anns & annotation_forms("ДоступноСКлиента")),
            "handler": bool(anns & annotation_forms("Обработчик")),
            "cache": cache_state(source, method.annotations), "calls": walk.calls,
        }
    return {"k": "x", "stem": stem, "methods": methods, "own": sorted(own)}


class ServerCallGraph:
    """Join shared mapper facts and prove client-to-server paths.

    paths() yields (endpoint stem, endpoint method, spelled chain). Consumers may
    inspect metadata, modules and method_environment() to reuse environment/cache facts.
    No negative memo is kept: a cycle must not hide an endpoint reached on another path.
    """

    def __init__(self, facts: dict[str, dict]):
        self.metadata = {f["stem"]: f for f in facts.values() if f["k"] == "y"}
        self.modules = {f["stem"]: f for f in facts.values() if f["k"] == "x"}
        self.forms = [(rel, f) for rel, f in facts.items() if f["k"] == "y"
                      and f.get("kind") == "КомпонентИнтерфейса"]
        self.names: dict[str, list[str]] = defaultdict(list)
        self.components: dict[str, list[dict]] = defaultdict(list)
        for stem, meta in self.metadata.items():
            if isinstance(meta.get("name"), str) and meta.get("kind"):
                self.names[meta["name"]].append(stem)
                if meta.get("kind") == "КомпонентИнтерфейса":
                    self.components[meta["name"]].append(meta)
            elif not meta.get("valid"):
                # Malformed metadata still poisons a same-stem candidate elsewhere.
                self.names[stem.rsplit("/", 1)[-1]].append(stem)
        catalogs = _catalogs()
        # Without the platform data neither stdlib names nor base types are known.
        self.has_data = catalogs is not None
        self.schema, self.stdlib = catalogs or ({}, frozenset())
        self._scopes: dict[str, frozenset[str] | None] = {}

    def property_kind(self, component: str, prop: str, active: frozenset = frozenset()) -> str | None:
        if component in self.components:
            choices = self.components[component]
            if len(choices) != 1 or component in active:
                return None
            meta = choices[0]
            if prop in meta["events"]:
                return "event"
            if prop in meta["properties"]:
                return "property"
            base = meta["base"]
            return self.property_kind(_type_head(base), prop, active | {component}) if isinstance(base, str) else None
        head = uischema.canonical_component(component)
        spec = self.schema.get("components", {}).get(head, {}).get("props", {}).get(uischema.canonical_property(prop))
        if spec is None:
            return None
        if "event" in spec:
            return "event"
        return "image" if uischema.canonical_property(prop) == "Изображение" else "property"

    def declared(self, stem: str) -> frozenset[str]:
        """Non-method names the module and its own metadata declare; they hide any call."""
        meta = self.metadata.get(stem, {})
        return frozenset((*self.modules.get(stem, {}).get("own", ()),
                          *meta.get("properties", ()), *meta.get("events", ())))

    def shadows(self, stem: str) -> frozenset[str] | None:
        """Names that hide a same-named module from a receiver; None if the scope is unknown.

        Besides its own declarations a component sees what its base chain gives it: the
        properties and events of project components and of the platform type the chain
        ends in, in both spellings, and the names the platform adds to every component.
        A chain that does not resolve (an unknown or ambiguous base, a cycle) leaves the
        scope unknown. Inherited names do not hide a bare call: shipped code calls its own
        method `Title(Picture)` from a form whose base type has a Title property.
        """
        if stem not in self._scopes:
            self._scopes[stem] = self._scope(stem)
        return self._scopes[stem]

    def _scope(self, stem: str) -> frozenset[str] | None:
        meta = self.metadata.get(stem, {})
        names = set(self.declared(stem))
        if meta.get("kind") == "КомпонентИнтерфейса":
            names.update(_component_extras())
        seen: set[str] = set()
        base = meta.get("base")
        while base is not None:
            head = _type_head(base)
            if head in seen:
                return None
            seen.add(head)
            choices = self.components.get(head)
            if choices:
                if len(choices) != 1:
                    return None
                names.update(choices[0]["properties"])
                names.update(choices[0]["events"])
                base = choices[0]["base"]
                continue
            inherited = _platform_scope(head)
            if inherited is None:
                return None
            names.update(inherited)
            break
        return frozenset(names)

    def method_environment(self, stem: str, method: dict) -> str | None:
        """Client takes priority; unannotated common modules need a known environment."""
        if method["on_client"]:
            return "client"
        if method["on_server"]:
            return "server"
        meta = self.metadata.get(stem, {})
        if meta.get("kind") in SERVER_KINDS or meta.get("environment") in _environment_forms()[0]:
            return "server"
        if (meta.get("kind") == "КомпонентИнтерфейса"
                or meta.get("environment") in _environment_forms()[1] | _both_env_forms()):
            return "client"
        return None

    def paths(self, stem: str, call: list[str], *, legacy_image: bool = False,
              active: frozenset = frozenset()) -> list[tuple[str, str, list[str]]]:
        root, name, spelled = call
        if not self.has_data or (root or name) in self.declared(stem):
            return []
        if root:
            # An unknown scope may hide the module behind an inherited name.
            scope = self.shadows(stem)
            if (scope is None or root in scope
                    or root in (self.modules.get(stem, {}).get("methods") or {})):
                return []
            choices = self.names.get(root, ())
            if root in self.stdlib or len(choices) != 1:
                return []
            target = choices[0]
        else:
            target = stem
        meta = self.metadata.get(target, {})
        if not meta.get("valid"):
            return []
        module = self.modules.get(target)
        if module is None:
            # Compatibility for the old image rule's metadata-only input contract.
            if legacy_image and root and (meta.get("kind") in SERVER_KINDS
                    or meta.get("environment") in _environment_forms()[0]):
                return [(target, name, [spelled])]
            return []
        method = (module["methods"] or {}).get(name)
        key = (target, name)
        if method is None or key in active:
            return []
        environment = self.method_environment(target, method)
        if environment == "server":
            if method["cache"] in ("true", "unknown"):
                return []
            if method["available"] or legacy_image:
                return [(target, name, [spelled])]
            return []
        if environment != "client":
            return []
        result = []
        for child in method["calls"]:
            for endpoint, member, chain in self.paths(target, child, legacy_image=legacy_image,
                                                       active=active | {key}):
                result.append((endpoint, member, [spelled, *chain]))
        return result
