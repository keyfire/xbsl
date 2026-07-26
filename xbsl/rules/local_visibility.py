"""Tier D: a call from outside a module must target a method visible outside it.

Two rules, one invariant of the platform: @Локально is the DEFAULT visibility of a language
construct (docs: topic "Модульная разработка" - "@Локально - конструкция видна только в своем
модуле (значение по умолчанию)"), so a method with no visibility annotation is reachable from
its own module alone. The rules differ in how the call reaches the method:
code/local-method-cross-component goes through a component INSTANCE (`Компоненты.X.Метод(...)`,
which fails at runtime) and code/local-method-cross-module through the MODULE NAME
(`Модуль.Метод(...)`, which the compiler rejects on deploy).

The code/local-method-cross-component rule: a method of an interface component is
@Локально by default – a call `Компоненты.X.Метод(...)` from ANOTHER component's module
fails at runtime with "Method is invisible due to visibility modifier @Локально" unless
the method carries a visibility annotation wider than local: @ВПодсистеме, @ВПроекте,
@ВТипе or @Глобально (docs: Стд::Аннотации::ОбластиВидимости, topic "Модульная
разработка" – @Локально is the default for language constructs).

The pattern the rule encodes: every cross-component call targets a method
annotated @ВПодсистеме (a router page-switch is the reference shape –
`Компоненты.КарточкаЗадачи.Загрузить(...)`); every other `Компоненты.X.Y(...)` call
hits a form-local instance (an HTML container, a table) whose X is not a project
component, so those are skipped by construction. Yaml bindings (`=Компоненты...`)
reference form-local tables and platform built-ins only, never project components –
bindings are not checked.

Zero-false-positive guards:

- only CALLS are checked (the member name is followed by `(`); reads and writes of
  properties are left alone;
- the caller must be the paired module of a КомпонентИнтерфейса yaml, and that yaml
  must embed the component under the same instance name (a node with `Имя: X` and
  `Тип: X`) – this rules out a same-name instance of a different type;
- X must be a project КомпонентИнтерфейса with a paired module `X.xbsl`, and the called
  name must be found among the methods declared in that module – platform built-ins on
  component instances (ПодключитьОбработчикТаймера, ВызватьМетод...) are not declared
  there and are skipped;
- a module where the name `Компоненты` is shadowed (declared, assigned, annotated or
  bound by a lambda parameter) is skipped entirely for the rule;
- comments and `Запрос{...}` blocks are excluded via code_tokens; a root preceded by
  `.` is a member of another object, not the components collection;
- the component's own module is never checked against itself (visibility does not
  restrict calls inside one module).

The diagnostic is reported at the CALL site: that is where the runtime error surfaces
and where the drift is introduced; the fix (the annotation on the declaration) lives in
the other file and is named in the message. The rule is project-wide: it needs the
target component's yaml and module next to the caller.
"""

from __future__ import annotations

from collections.abc import Iterable

from xbsl import dataset, i18n
from xbsl import parser as P
from xbsl.diagnostics import Diagnostic, Severity
from xbsl.engine import SourceFile, rule
from xbsl.lexer import linemap
from xbsl.parser import parse
from xbsl.rules._syntax import code_tokens
# The AST walkers of the sibling cross-module rule: the same "every call, every locally
# bound name" collection, kept in one place rather than written twice.
from xbsl.rules.call_arity import _walk_body, _walk_expr
from xbsl.rules.yaml_schema import _HAVE_YAML, _parsed, object_kind, value_of

MESSAGES = {
    "code/local-method-cross-component.title": {
        "ru": "Кросс-компонентный вызов локального метода",
        "en": "Cross-component call of a local method",
    },
    "code/local-method-cross-component.invisible": {
        "ru": "Метод '{method}' компонента '{comp}' виден только в своём модуле "
              "(@Локально по умолчанию) – вызов из другого компонента упадёт в рантайме. "
              "Пометьте метод в {module} аннотацией @ВПодсистеме или шире.",
        "en": "Method '{method}' of component '{comp}' is only visible inside its module "
              "(@{n[Локально]} by default) – the call from another component fails at runtime. "
              "Mark the method in {module} with @{n[ВПодсистеме]} or a wider visibility.",
    },
}
i18n.register(MESSAGES)

# The visibility-scope annotations (Стд::Аннотации::ОбластиВидимости). Anything from
# _WIDE makes the method callable from another component's module; @ВТипе is counted as
# wide too – the docs describe it as visible "в данном типе, его наследниках и внешних
# объектах", so treating it as local could produce false positives.
_VISIBILITY = frozenset({"Локально", "ВПодсистеме", "ВПроекте", "ВТипе", "Глобально"})
_WIDE = _VISIBILITY - {"Локально"}

# Declaration keywords that bind a name (shadowing the components collection).
_DECL_KW = ("VAL", "VAR", "CONST", "REQ", "CATCH", "FOR")


def _annotations_before(toks: list, i: int) -> set[str]:
    """Names of the annotations directly above the method keyword at index i.

    Walks backwards over `@Имя` pairs (annotation arguments in parentheses are skipped
    by bracket balance) and over the `статический` keyword; any other token ends the
    annotation block.
    """
    names: set[str] = set()
    j = i - 1
    if j >= 0 and toks[j].kind == "KEYWORD" and toks[j].canonical == "STATIC":
        j -= 1
    while j >= 0:
        t = toks[j]
        if t.kind == "OP" and t.value == ")":
            depth = 0
            while j >= 0:
                if toks[j].kind == "OP" and toks[j].value == ")":
                    depth += 1
                elif toks[j].kind == "OP" and toks[j].value == "(":
                    depth -= 1
                    if depth == 0:
                        break
                j -= 1
            j -= 1
            continue
        if t.kind == "IDENT" and j >= 1 and toks[j - 1].kind == "OP" and toks[j - 1].value == "@":
            names.add(t.value)
            j -= 2
            continue
        break
    return names


def _method_visibility(module: SourceFile) -> dict[str, set[str]]:
    """Module method name -> the annotation names above its declaration (cached on the file)."""
    cached = module.cache.get("local_visibility_methods")
    if cached is not None:
        return cached
    toks = code_tokens(module)
    n = len(toks)
    result: dict[str, set[str]] = {}
    for i, t in enumerate(toks):
        if t.kind != "KEYWORD" or t.canonical != "METHOD" or not t.value[:1].islower():
            continue
        if i + 1 < n and toks[i + 1].kind == "IDENT":
            result[toks[i + 1].value] = _annotations_before(toks, i)
    module.cache["local_visibility_methods"] = result
    return result


def _shadows(toks: list, name: str) -> bool:
    """The module binds the name somewhere: a declaration, an assignment, an annotation.

    Wider than necessary on purpose – a shadowed name only makes the rule skip.
    """
    n = len(toks)
    for i, t in enumerate(toks):
        if t.kind == "KEYWORD" and t.value[:1].islower() and t.canonical in _DECL_KW:
            for j in range(i + 1, min(i + 3, n)):
                if toks[j].kind == "IDENT":
                    if toks[j].value == name:
                        return True
                    break
        elif t.kind == "IDENT" and t.value == name and i + 1 < n and toks[i + 1].kind == "OP":
            # `Объект.Компоненты = ...` is a member of another object, not the collection
            member = i > 0 and toks[i - 1].kind == "OP" and toks[i - 1].value == "."
            if not member and toks[i + 1].value in ("=", ":", "->"):
                return True
    return False


def _instance_types(node, out: dict[str, set[str]]) -> None:
    """Collect `Имя -> {Тип}` pairs from the parsed yaml tree (component placements)."""
    if isinstance(node, dict):
        nm, tp = value_of(node, "Имя"), value_of(node, "Тип")
        if isinstance(nm, str) and isinstance(tp, str):
            out.setdefault(nm, set()).add(tp)
        for v in node.values():
            _instance_types(v, out)
    elif isinstance(node, list):
        for item in node:
            _instance_types(item, out)


def _pair_stem(rel: str) -> str:
    slash = rel.replace("\\", "/")
    return slash[: slash.rfind(".")] if "." in slash.rsplit("/", 1)[-1] else slash


def _cross_component_mapper(source: SourceFile) -> dict | None:
    """The map phase. The yaml of an interface component contributes its name and the
    embedded instances; a module contributes its method visibility and its
    `Компоненты.X.Y(...)` calls with the local skips settled. The reduce joins the
    caller's pair, resolves X to the component's module and checks the visibility."""
    if not _HAVE_YAML:
        return None
    if source.kind == "yaml":
        data, err = _parsed(source)
        if err is not None or not isinstance(data, dict):
            return None
        if object_kind(data) != "КомпонентИнтерфейса":
            return None
        name = value_of(data, "Имя")
        instances: dict[str, set[str]] = {}
        _instance_types(data, instances)
        return {
            "k": "y",
            "stem": _pair_stem(source.rel),
            "name": name if isinstance(name, str) else None,
            "instances": {inst: sorted(types) for inst, types in instances.items()},
        }
    if source.kind != "xbsl":
        return None
    toks = code_tokens(source)
    visibility = {
        name: sorted(anns) for name, anns in _method_visibility(source).items()
    }
    calls: list[tuple[str, str, int, int]] = []
    if not _shadows(toks, "Компоненты"):
        owner = source.path.name[: -len(".xbsl")].split(".", 1)[0]
        n = len(toks)
        for i, t in enumerate(toks):
            if t.kind != "IDENT" or t.value != "Компоненты" or i + 5 >= n:
                continue
            if i > 0 and toks[i - 1].kind == "OP" and toks[i - 1].value == ".":
                continue  # member of another object, not the components collection
            if not (toks[i + 1].kind == "OP" and toks[i + 1].value == "."
                    and toks[i + 2].kind == "IDENT"
                    and toks[i + 3].kind == "OP" and toks[i + 3].value == "."
                    and toks[i + 4].kind == "IDENT"
                    and toks[i + 5].kind == "OP" and toks[i + 5].value == "("):
                continue  # not a call Компоненты.X.Y(...)
            comp, meth = toks[i + 2], toks[i + 4]
            if comp.value == owner:
                continue  # the component's own module – locality never restricts it
            calls.append((comp.value, meth.value, meth.line, meth.col))
    if not visibility and not calls:
        return None
    return {
        "k": "x",
        "stem": _pair_stem(source.rel),
        "file": source.path.name,
        "visibility": visibility,
        "calls": calls,
    }


@rule(
    "code/local-method-cross-component", "code/local-method-cross-component.title", "D",
    scope="project", severity=Severity.WARNING, mapper=_cross_component_mapper,
)
def local_method_cross_component(facts: dict[str, dict]) -> Iterable[Diagnostic]:
    # Component name -> the stem of its paired module; caller stem -> its instances.
    comp_stems: dict[str, str] = {}
    instances_by_stem: dict[str, dict[str, list[str]]] = {}
    module_facts: dict[str, dict] = {}
    for fact in facts.values():
        if fact["k"] == "y":
            instances_by_stem[fact["stem"]] = fact["instances"]
            if fact["name"]:
                comp_stems[fact["name"]] = fact["stem"]
    for fact in facts.values():
        if fact["k"] == "x":
            module_facts[fact["stem"]] = fact
    if not comp_stems:
        return
    for rel, fact in facts.items():
        if fact["k"] != "x" or not fact["calls"]:
            continue
        instances = instances_by_stem.get(fact["stem"])
        if instances is None:
            continue  # not an interface component module – no components collection
        for comp, meth, line, col in fact["calls"]:
            target_stem = comp_stems.get(comp)
            if target_stem is None or target_stem == fact["stem"]:
                continue  # X is not a project component with a paired module
            target = module_facts.get(target_stem)
            if target is None:
                continue
            if instances.get(comp) != [comp]:
                continue  # the form embeds no instance X of type X – ambiguous, skip
            annotations = target["visibility"].get(meth)
            if annotations is None:
                continue  # not declared in the module – a platform built-in, skip
            if set(annotations) & _WIDE:
                continue
            yield Diagnostic(
                rel, line, col, "code/local-method-cross-component",
                Severity.WARNING,
                i18n.t(
                    "code/local-method-cross-component.invisible",
                    method=meth, comp=comp, module=target["file"],
                ),
            )


# --- the same invariant reached through the MODULE NAME ---------------------------------

MESSAGES_MODULE = {
    "code/local-method-cross-module.title": {
        "ru": "Межмодульный вызов локального метода",
        "en": "Cross-module call of a local method",
    },
    "code/local-method-cross-module.invisible": {
        "ru": "Метод '{method}' модуля '{module}' виден только в своём модуле "
              "(@Локально по умолчанию) – компилятор отклонит вызов при сборке. "
              "Пометьте метод в {file} аннотацией @ВПодсистеме или шире.",
        "en": "Method '{method}' of module '{module}' is only visible inside its own module "
              "(@{n[Локально]} by default) - the compiler rejects the call on build. "
              "Mark the method in {file} with @{n[ВПодсистеме]} or a wider visibility.",
    },
}
i18n.register(MESSAGES_MODULE)


def _module_method_visibility(module: P.Module) -> dict[str, list[str]]:
    """Module-level method -> the names of its annotations.

    Only the methods of the module itself: `Модуль.Метод(...)` reaches nothing else in one
    hop. A name declared twice is dropped - the compiler rejects that anyway, and the rule
    must not guess which declaration was meant.
    """
    result: dict[str, list[str]] = {}
    dupes: set[str] = set()
    for m in module.members:
        if not isinstance(m, P.Method):
            continue
        if m.name in result or m.name in dupes:
            dupes.add(m.name)
            result.pop(m.name, None)
            continue
        result[m.name] = [a.name for a in m.annotations]
    return result


def _cross_module_mapper(source: SourceFile) -> dict | None:
    """The map phase: this module's method visibility plus its `Основа.Метод(...)` calls.

    The callable name of a module is its file stem; dotted stems (object and manager
    modules) are not reachable as `Имя.Метод(...)`. Bases bound by the module itself (a
    declaration, a parameter, an own member, a qualified `::` name) are settled here.
    """
    if source.kind != "xbsl":
        return None
    stem = source.path.name.removesuffix(".xbsl")
    if "." in stem:
        stem = ""
    module, errors = parse(source)
    if errors:
        # A broken file gives no candidates, but its stem must still poison the name.
        return {"stem": stem, "visibility": None, "calls": []} if stem else None
    own: set[str] = set()
    declared: set[str] = set()
    calls: list[P.Call] = []
    for m in module.members:
        if isinstance(m, (P.Method, P.Structure, P.Enum, P.ObjectField)):
            own.add(m.name)
        if isinstance(m, P.Method):
            declared.update(p.name for p in m.params)
            for p in m.params:
                _walk_expr(p.default, calls, declared)
            _walk_body(m.body, calls, declared)
        elif isinstance(m, P.ObjectField):
            if m.init is not None:
                _walk_expr(m.init, calls, declared)
        elif isinstance(m, (P.Structure, P.Enum)):
            subs = m.members if isinstance(m, P.Structure) else m.methods
            for sub in subs:
                if isinstance(sub, P.Method):
                    declared.update(p.name for p in sub.params)
                    _walk_body(sub.body, calls, declared)
                elif isinstance(sub, P.ObjectField) and sub.init is not None:
                    _walk_expr(sub.init, calls, declared)
    lm = None
    candidates: list[tuple[str, str, int, int]] = []
    for call in calls:
        callee = call.callee
        if not (
            isinstance(callee, P.Member)
            and isinstance(callee.obj, P.Name)
            and not callee.safe  # `Основа?.Метод()` reads a nullable value, not a module
        ):
            continue
        base = callee.obj.name
        if "::" in base or base in declared or base in own or base == stem:
            continue
        if lm is None:
            lm = linemap(source)
        line, col = lm.linecol(callee.start)
        candidates.append((base, callee.name, line, col))
    if not stem and not candidates:
        return None
    return {"stem": stem, "visibility": _module_method_visibility(module), "calls": candidates}


@rule(
    "code/local-method-cross-module", "code/local-method-cross-module.title", "D",
    scope="project", severity=Severity.ERROR, mapper=_cross_module_mapper,
)
def local_method_cross_module(facts: dict[str, dict]) -> Iterable[Diagnostic]:
    """`Модуль.Метод(...)` must target a method carrying a visibility annotation.

    A finding needs the base name to resolve to exactly one clean project module (the file
    stem, the resolution of code/call-arity-cross) and the method to be declared there at
    module level with no annotation wider than @Локально. Skipped: stdlib name shadows,
    twin module names, broken files (as callers and as sources), bases bound by the caller,
    methods the target does not declare (a platform built-in reached through a name the
    project also uses), and the module's own methods - locality never restricts them.

    The reach of a wide annotation is not judged: @ВПодсистеме outside its own subsystem is
    a narrower question that needs the subsystem boundaries, while it is the annotation
    itself that drifts.
    """
    try:
        stdlib_names = set(dataset.load_json("stdlib.json").get("names", ()))
    except Exception:  # noqa: BLE001 - without the catalog only the stdlib shadow is lost
        stdlib_names = set()
    # Module name -> {method: annotations}; None marks an unusable name (a parse-broken
    # file or twin modules in different directories).
    visibility: dict[str, dict[str, list[str]] | None] = {}
    files: dict[str, str] = {}
    for fact in facts.values():
        stem = fact["stem"]
        if not stem:
            continue
        if fact["visibility"] is None or stem in visibility:
            visibility[stem] = None
        else:
            visibility[stem] = fact["visibility"]
            files[stem] = f"{stem}.xbsl"
    if not any(visibility.values()):
        return
    for rel, fact in facts.items():
        for base, method, line, col in fact["calls"]:
            if base in stdlib_names:
                continue
            target = visibility.get(base)
            if not target:
                continue
            annotations = target.get(method)
            if annotations is None:
                continue  # not declared there - a platform built-in or another meaning
            if set(annotations) & _WIDE:
                continue
            yield Diagnostic(
                rel, line, col, "code/local-method-cross-module", Severity.ERROR,
                i18n.t(
                    "code/local-method-cross-module.invisible",
                    method=method, module=base, file=files[base],
                ),
            )
