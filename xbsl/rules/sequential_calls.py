"""Tier D: one client method that calls the server several times in a row.

A call of a client-available server method from the client is a round trip. When a client
method makes two or more of them one after another on the same path of execution - the usual
shape is an opening handler that reads the settings, then a list, then the counters - the
waits add up, and one server method returning a typed result would make a single trip.

The rule rides on the shared server-call facts (`_server_calls`): environments, the
`AvailableFromClient` annotation, the result cache, unique element names and shadowing. Those
facts keep the calls of a method as a set, and a sequence needs their ORDER, so the mapper adds
a compact flow of every method body, compiled from the syntax tree the shared mapper has
already parsed: the calls with their positions and receivers, the branches, loops,
short-circuit operands, tries and catches around them, and the names read and written, which
carry the data dependencies. The reduce walks those flows; no syntax tree crosses the process
boundary.

Counted as a server call: a bare call of a same-module method, `Module.Method(...)` and
`Components.Child.Method(...)` that reach a client-available server method without
`CacheResult = True`. A client method of the same module is walked in place (up to six levels
deep). A client method of another module or of a child component is one opaque call, and it
counts only when its own main path calls the server before any early exit: a wrapper that
reaches the server under a condition says nothing about this call.

Skipped by design:
- calls inside a lambda or a method reference: a timer or a subscription runs in another tick;
- calls in different branches of `if`/`case` and in the right operand of `and`/`or`/`?:`/`??`
  (a branch is a barrier, its body is judged as a block of its own);
- a loop body (also a barrier; a server call inside a loop is a question of its own);
- a method with `CacheResult = True` or an argument the annotation check cannot read, and
  `@OnServer @OnClient`, which runs on the client;
- a run inside a `catch` body, and a run whose calls stand in different `try` statements: the
  split may be deliberate error handling;
- unresolved, shadowed, ambiguous and platform names (the ServerCallGraph guards).

By default only the client methods reachable from the opening handlers (`AfterCreate`,
`AfterRead`, `OnOpenByLink`) are judged - through same-module calls, client modules,
`Components.X.M(...)` and timer lambdas; the `scope` parameter set to `all` judges every client
method. One finding per run, on the line of its first call. Identical runs found from several
methods are reported once, for the innermost one, and a run contained in a longer one is
dropped. There is no autofix: the cure is a new composite server method.
"""

from __future__ import annotations

import dataclasses
from collections import deque
from collections.abc import Iterable
from functools import lru_cache

from xbsl import dataset, i18n, parser as P, terms
from xbsl.diagnostics import Diagnostic, Severity
from xbsl.engine import SourceFile, rule, rule_param
from xbsl.lexer import linemap
from xbsl.rules._server_calls import ServerCallGraph, _type_head, server_call_mapper
from xbsl.rules.yaml_schema import _HAVE_YAML, _composed, _mapping_nodes, _scalar_entries

if _HAVE_YAML:
    import yaml

RULE = "code/sequential-server-calls"

MESSAGES = {
    f"{RULE}.title": {
        "ru": "Несколько обращений к серверу подряд",
        "en": "Several server calls in a row",
    },
    f"{RULE}.open": {
        "ru": "При открытии метод '{method}' обращается к серверу несколько раз подряд "
              "({count}): {calls}.",
        "en": "On open, method '{method}' calls the server several times in a row ({count}): "
              "{calls}.",
    },
    f"{RULE}.any": {
        "ru": "Метод '{method}' обращается к серверу несколько раз подряд ({count}): {calls}.",
        "en": "Method '{method}' calls the server several times in a row ({count}): {calls}.",
    },
    f"{RULE}.advice": {
        "ru": "Каждый вызов – отдельный круг до сервера и обратно, а те же данные может вернуть "
              "один серверный метод с типизированным результатом. Объединение меняет границы "
              "транзакций и обработку ошибок, поэтому сначала проверьте, что эти вызовы "
              "допустимо выполнить за одно обращение.",
        "en": "Each call is a round trip of its own, while one server method with a typed "
              "result could return the same data. Merging changes transaction boundaries and "
              "error handling, so first check that these calls may run as one request.",
    },
    f"{RULE}.data": {
        "ru": "Аргументы '{later}' вычисляются из результата '{earlier}', и это вычисление "
              "переедет на сервер вместе с вызовами.",
        "en": "The arguments of '{later}' are computed from the result of '{earlier}', and that "
              "computation moves to the server along with the calls.",
    },
    f"{RULE}.off": {
        "ru": "находок на зрелом проекте десятки, и многие повторяют один узор форм, а "
              "исправление архитектурное: новый составной серверный метод вместо правки строки. "
              "Включайте, когда ищете лишние обращения к серверу при открытии страниц и форм",
        "en": "a mature project gets dozens of findings, many of them one repeated form pattern, "
              "and the fix is architectural: a new composite server method rather than an edit "
              "of a line. Enable it when looking for extra server round trips on opening pages "
              "and forms",
    },
    f"{RULE}.param.scope": {
        "ru": "какие клиентские методы проверяются: open – достижимые от обработчиков открытия "
              "(ПослеСоздания, ПослеЧтения, ПриОткрытииПоСсылке), all – все",
        "en": "which client methods are judged: open - the ones reachable from the opening "
              "handlers ({n[ПослеСоздания]}, {n[ПослеЧтения]}, {n[ПриОткрытииПоСсылке]}), "
              "all - every one",
    },
    f"{RULE}.param.min-calls": {
        "ru": "сколько обращений подряд составляют серию, от двух",
        "en": "how many calls in a row make a run, two or more",
    },
}
i18n.register(MESSAGES)

#: Which client methods are judged: "open" - the ones an opening handler may run, "all" - all.
SCOPE = rule_param(RULE, "scope", "open", f"{RULE}.param.scope",
                   valid=lambda value: value in ("open", "all"))
#: The shortest run that is reported.
MIN_CALLS = rule_param(RULE, "min-calls", 2, f"{RULE}.param.min-calls",
                       valid=lambda value: value >= 2)

#: The short-circuit operators: their right operand runs only on some paths.
_LOGIC_OPS = frozenset({"и", "или", "and", "or"})


@lru_cache(maxsize=None)
def _forms(name: str) -> frozenset[str]:
    """Both spellings of a platform name, taken from the term dictionary."""
    found = {name, *terms.key_forms(name)}
    english = terms.common_english(name)
    if english:
        found.add(english)
    return frozenset(found)


dataset.register_reset(_forms.cache_clear)


@lru_cache(maxsize=None)
def _fields(cls: type) -> tuple[str, ...]:
    """Field names of a node class (a node of the native build has no instance dictionary)."""
    return tuple(f.name for f in dataclasses.fields(cls))


def _children(node) -> list:
    return [getattr(node, name) for name in _fields(type(node))]


def _path_key(expr) -> str | None:
    """`A.B.C` for a member chain rooted at a bare name, else None."""
    parts = []
    while isinstance(expr, P.Member):
        parts.append(expr.name)
        expr = expr.obj
    if isinstance(expr, P.Name):
        parts.append(expr.name)
        return ".".join(reversed(parts))
    return None


def _local_names(method: P.Method) -> set[str]:
    """Parameters and every name declared anywhere in the body, lambdas included (flat)."""
    names = {param.name for param in method.params}
    stack: list = [method.body]
    while stack:
        item = stack.pop()
        if isinstance(item, (list, tuple)):
            stack.extend(item)
            continue
        if not isinstance(item, P.Node):
            continue
        if isinstance(item, P.VarDecl):
            names.add(item.name)
        elif isinstance(item, (P.ForEach, P.ForTo)):
            names.add(item.var)
        elif isinstance(item, P.Try):
            names.update(var for var, _type, _body in item.catches if var)
        elif isinstance(item, P.Lambda):
            names.update(param.name for param in item.params)
        stack.extend(_children(item))
    return names


def _exits(bodies: list) -> bool:
    """Whether a statement list can leave its block early: return, break, continue, throw."""
    stack: list = [bodies]
    while stack:
        item = stack.pop()
        if isinstance(item, (list, tuple)):
            stack.extend(item)
            continue
        if not isinstance(item, P.Node) or isinstance(item, (P.Lambda, P.MethodRef)):
            continue
        if isinstance(item, (P.Return, P.Break, P.Continue, P.Throw)):
            return True
        stack.extend(_children(item))
    return False


class _Flow:
    """Compile one method body into the JSON flow the reduce walks.

    Statements: `["v", name, expr]` a declaration, `["a", key, op, target, expr]` an assignment
    (`target` is the target expression when it is not a plain name chain), `["e", expr]`,
    `["r", expr]` a return, `["b"]` a break or continue, `["if", subject, arms, else, exits]`
    for `if` and `case` (an arm is `[conditions, body]`), `["loop", heads, condition, body]`,
    `["t", id, body, catches, finally]` and `["s", body]` a scope.

    Expressions: `["n", key]` reads a name chain, `["c", target, receiver, args, line, col,
    spelled]` a call, `["and", left, right]`, `["?", cond, then, else]`, `["??", left, right]`
    and `["g", parts]` for anything else that holds reads or calls. An expression with neither
    is None. A call target is `["m", name]` (a method of the module), `["q", element, method]`
    or `["k", child, method]` (`Components.Child.Method`); a local name, a safe member access
    and any other callee leave it None. A lambda and a method reference are not entered.
    """

    def __init__(self, source: SourceFile, components: frozenset[str], timers: frozenset[str]):
        self.lines = linemap(source)
        self.components = components
        self.timers = timers
        self.locals: set[str] = set()

    def method(self, method: P.Method) -> dict:
        self.locals = _local_names(method)
        return {
            "params": [param.name for param in method.params],
            "locals": sorted(self.locals),
            "body": self.block(method.body),
            "edges": self.edges(method),
        }

    # --- statements ----------------------------------------------------------------------

    def block(self, statements: list) -> list:
        out = []
        for statement in statements:
            node = self.statement(statement)
            if node is not None:
                out.append(node)
        return out

    def statement(self, st) -> list | None:
        if isinstance(st, P.VarDecl):
            return ["v", st.name, self.expr(st.init)]
        if isinstance(st, P.Assign):
            key = _path_key(st.target)
            return ["a", key, st.op, None if key is not None else self.expr(st.target),
                    self.expr(st.value)]
        if isinstance(st, (P.ExprStmt, P.UseStmt)):
            return ["e", self.expr(st.expr)]
        if isinstance(st, P.Return):
            return ["r", self.expr(st.value)]
        if isinstance(st, (P.Break, P.Continue)):
            return ["b"]
        if isinstance(st, (P.If, P.Case)):
            if isinstance(st, P.If):
                subject = None
                arms = [([condition], body) for condition, body in st.branches]
            else:
                subject = self.expr(st.subject)
                arms = [(when.conditions, when.body) for when in st.whens]
            bodies = [body for _conditions, body in arms]
            if st.else_body is not None:
                bodies.append(st.else_body)
            return ["if", subject,
                    [[[self.expr(c) for c in conditions], self.block(body)]
                     for conditions, body in arms],
                    None if st.else_body is None else self.block(st.else_body),
                    _exits(bodies)]
        if isinstance(st, P.ForEach):
            return ["loop", [self.expr(st.source)], None, self.block(st.body)]
        if isinstance(st, P.ForTo):
            return ["loop", [self.expr(e) for e in (st.start_expr, st.to, st.step)], None,
                    self.block(st.body)]
        if isinstance(st, P.While):
            return ["loop", [], self.expr(st.cond), self.block(st.body)]
        if isinstance(st, P.Try):
            return ["t", st.start, self.block(st.body),
                    [self.block(body) for _var, _type, body in st.catches],
                    None if st.finally_body is None else self.block(st.finally_body)]
        if isinstance(st, P.Scope):
            return ["s", self.block(st.body)]
        return None

    # --- expressions ---------------------------------------------------------------------

    def expr(self, e) -> list | None:
        if e is None or isinstance(e, (P.Lambda, P.MethodRef)):
            return None
        if isinstance(e, P.Name):
            return ["n", e.name]
        if isinstance(e, P.Member):
            key = _path_key(e)
            return ["n", key] if key is not None else self.expr(e.obj)
        if isinstance(e, P.Call):
            return self.call(e)
        if isinstance(e, P.Binary) and e.op.lower() in _LOGIC_OPS:
            return self.pair("and", self.expr(e.left), self.expr(e.right))
        if isinstance(e, P.Ternary):
            parts = [self.expr(e.cond), self.expr(e.then), self.expr(e.otherwise)]
            return ["?", *parts] if any(p is not None for p in parts) else None
        if isinstance(e, P.Coalesce):
            return self.pair("??", self.expr(e.left), self.expr(e.right))
        parts = []
        for value in _children(e):
            for sub in (value if isinstance(value, list) else [value]):
                if isinstance(sub, P.CallArg):
                    sub = sub.value
                if isinstance(sub, tuple):
                    parts.extend(self.expr(x) for x in sub if isinstance(x, P.Expr))
                elif isinstance(sub, P.Expr):
                    parts.append(self.expr(sub))
        parts = [p for p in parts if p is not None]
        if not parts:
            return None
        return parts[0] if len(parts) == 1 else ["g", parts]

    @staticmethod
    def pair(kind: str, left, right) -> list | None:
        return None if left is None and right is None else [kind, left, right]

    def target(self, callee) -> list | None:
        """What a call resolves against in the reduce; None for a local or an unknown shape."""
        if isinstance(callee, P.Name):
            return None if callee.name in self.locals else ["m", callee.name]
        if not isinstance(callee, P.Member) or callee.safe:
            return None
        obj = callee.obj
        if isinstance(obj, P.Name):
            return None if obj.name in self.locals else ["q", obj.name, callee.name]
        if (isinstance(obj, P.Member) and isinstance(obj.obj, P.Name)
                and obj.obj.name in self.components and obj.obj.name not in self.locals):
            return ["k", obj.name, callee.name]
        return None

    def call(self, e: P.Call) -> list | None:
        receiver = self.expr(e.callee.obj) if isinstance(e.callee, P.Member) else None
        args = [[arg.name, self.expr(arg.value)] for arg in e.args]
        target = self.target(e.callee)
        if target is None and receiver is None and all(value is None for _n, value in args):
            return None
        line, col = self.lines.linecol(e.start)
        callee = e.callee
        if target is None:
            spelled = ""
        elif target[0] == "k":
            spelled = f"{callee.obj.obj.name}.{target[1]}.{target[2]}"
        elif target[0] == "q":
            spelled = f"{target[1]}.{target[2]}"
        else:
            spelled = target[1]
        return ["c", target, receiver, args, line, col, spelled]

    # --- reachability --------------------------------------------------------------------

    def edges(self, method: P.Method) -> list:
        """Every method the body may run, the lambdas handed to a timer included.

        The opening path follows these: a handler that starts a timer with `() -> Load()`
        opens the page through `Load` as much as through a direct call. Any other lambda - a
        subscription to an event, a filter - runs when something else happens, and a method
        reference is not followed at all.
        """
        out: list = []
        timed: set[int] = set()
        stack: list = [method.body]
        while stack:
            item = stack.pop()
            if isinstance(item, (list, tuple)):
                stack.extend(reversed(item))
                continue
            if not isinstance(item, P.Node) or isinstance(item, P.MethodRef):
                continue
            if isinstance(item, P.Lambda) and id(item) not in timed:
                continue
            if isinstance(item, P.Call):
                edge = self.edge(item.callee)
                if edge is not None and edge not in out:
                    out.append(edge)
                if (isinstance(item.callee, P.Name) and item.callee.name in self.timers
                        and item.callee.name not in self.locals):
                    timed.update(id(arg.value) for arg in item.args
                                 if isinstance(arg.value, P.Lambda))
            stack.extend(reversed(_children(item)))
        return out

    def edge(self, callee) -> list | None:
        if isinstance(callee, P.Name):
            return None if callee.name in self.locals else ["m", callee.name]
        if not isinstance(callee, P.Member) or callee.safe:
            return None
        obj = callee.obj
        if isinstance(obj, P.Name):
            return None if obj.name in self.locals else ["q", obj.name, callee.name]
        if (isinstance(obj, P.Member) and isinstance(obj.obj, P.Name)
                and obj.obj.name in self.components):
            return ["k", obj.name, callee.name]
        return None


def _child_types(source: SourceFile) -> dict[str, str]:
    """`Name -> type` of the components a form declares; a name with two types is left out."""
    root = _composed(source)
    if root is None:
        return {}
    names: dict[str, set[str]] = {}
    for mapping in _mapping_nodes(root):
        entries = _scalar_entries(mapping)
        written, name = entries.get("Тип"), entries.get("Имя")
        if (written and name and isinstance(written[1], yaml.ScalarNode)
                and isinstance(name[1], yaml.ScalarNode)):
            names.setdefault(name[1].value, set()).add(_type_head(written[1].value))
    return {name: next(iter(types)) for name, types in names.items() if len(types) == 1}


def sequence_mapper(source: SourceFile) -> dict | None:
    """The shared server-call fact of a source plus what an ordered walk needs.

    A module gets `flows` (method name -> compiled flow, for the methods its fact names once),
    a form description gets `children` (the declared components by name). The shared fact is
    copied, never changed: other rules read the same cached object.
    """
    base = server_call_mapper(source)
    if base is None:
        return None
    key = "sequential_call_facts"
    if key not in source.cache:
        source.cache[key] = _extend(source, base)
    return source.cache[key]


def _extend(source: SourceFile, base: dict) -> dict:
    if base["k"] == "y":
        if base.get("kind") != "КомпонентИнтерфейса" or not _HAVE_YAML:
            return base
        return {**base, "children": _child_types(source)}
    methods = base.get("methods")
    if not methods or source.path.suffix != ".xbsl":  # a query file has no methods to walk
        return base
    module, errors = P.parse(source)  # cached: the shared mapper has already parsed it
    if errors:
        return base
    compiler = _Flow(source, _forms("Компоненты"), _forms("ПодключитьОбработчикТаймера"))
    flows = {}
    for member in module.members:
        if isinstance(member, P.Method) and methods.get(member.name) is not None:
            flows[member.name] = compiler.method(member)
    return {**base, "flows": flows}


# --- reduce: walking the flows ------------------------------------------------------------

#: How deep same-module client methods are walked in place; a deeper call ends the walk there
#: (on the projects measured, doubling the depth changed no finding).
_MAX_INLINE = 6
_EMPTY: frozenset = frozenset()
#: Splits a walked path: a branch, a loop or a conditional operand stood between two calls.
_BARRIER = object()


class _Ev:
    """One server call on a walked path, with what it depends on."""

    __slots__ = ("id", "call", "line", "col", "via", "deps", "ctrl", "try_id", "guarded")

    def __init__(self, ident: int, call: str, line: int, col: int, via: tuple, deps: frozenset,
                 ctrl: frozenset, try_id: int | None, guarded: bool):
        self.id = ident
        self.call = call  # the callee as written: `Method`, `Module.Method`, `Components.X.M`
        self.line = line
        self.col = col
        self.via = via  # the same-module methods walked in place below the host
        self.deps = deps  # the calls whose results reach the receiver or the arguments
        self.ctrl = ctrl  # the calls whose results decide whether this one runs
        self.try_id = try_id  # the innermost `try` around the call
        self.guarded = guarded  # an early exit of the host may leave before the call


def _has_call(items: list) -> bool:
    return any(isinstance(x, _Ev) for x in items)


def _runs(items: list) -> list[list[_Ev]]:
    """The calls between two barriers."""
    runs: list[list[_Ev]] = []
    current: list[_Ev] = []
    for item in items:
        if item is _BARRIER:
            if current:
                runs.append(current)
            current = []
        elif isinstance(item, _Ev):
            current.append(item)
    if current:
        runs.append(current)
    return runs


class _Project:
    """The flows of a project joined with the server-call graph."""

    def __init__(self, facts: dict[str, dict]):
        self.graph = ServerCallGraph(facts)
        self.flows: dict[str, dict[str, dict]] = {}
        self.rels: dict[str, str] = {}
        self.children: dict[str, dict[str, str]] = {}
        for rel, fact in facts.items():
            if fact.get("k") == "x" and "flows" in fact:
                self.flows[fact["stem"]] = fact["flows"]
                self.rels[fact["stem"]] = rel
            elif fact.get("k") == "y" and "children" in fact:
                self.children[fact["stem"]] = fact["children"]
        self._locals: dict[tuple[str, str], frozenset[str]] = {}
        self._reaches: dict[tuple[str, str], bool] = {}
        self._active: set[tuple[str, str]] = set()

    def fact(self, stem: str, name: str) -> dict | None:
        return ((self.graph.modules.get(stem) or {}).get("methods") or {}).get(name)

    def env(self, stem: str, name: str) -> str | None:
        fact = self.fact(stem, name)
        return None if fact is None else self.graph.method_environment(stem, fact)

    def flow(self, stem: str, name: str) -> dict | None:
        return self.flows.get(stem, {}).get(name)

    def local_names(self, stem: str, name: str) -> frozenset[str]:
        key = (stem, name)
        if key not in self._locals:
            self._locals[key] = frozenset(self.flows[stem][name]["locals"])
        return self._locals[key]

    def module_target(self, stem: str, root: str, member: str) -> tuple[str, str] | None:
        """Where `root.member(...)` lands, under the guards of ServerCallGraph.paths."""
        graph = self.graph
        if root in graph.declared(stem):
            return None
        target = graph.receiver(stem, root)
        if target is None or not graph.metadata.get(target, {}).get("valid"):
            return None
        if self.fact(target, member) is None:
            return None
        return target, member

    def child_target(self, stem: str, child: str, member: str) -> tuple[str, str] | None:
        """Where `Components.child.member(...)` lands: the child's type must be one component."""
        type_name = self.children.get(stem, {}).get(child)
        if not type_name:
            return None
        choices = self.graph.components.get(type_name) or []
        if len(choices) != 1:
            return None
        target = choices[0]["stem"]
        if self.flow(target, member) is None:
            return None
        return target, member

    def reaches_server(self, stem: str, name: str) -> bool:
        """Whether every run of a client method calls the server: its main path holds a server
        call before any early exit.

        A method that reaches the server only in a branch, a loop or after a guard is not one
        more call of the series that calls it - on the path the series takes it may return
        without a trip.
        """
        key = (stem, name)
        if key in self._reaches:
            return self._reaches[key]
        flow = self.flow(stem, name)
        if flow is None or key in self._active:
            return False
        self._active.add(key)
        try:
            host = _Host(self, stem, name, flow)
            host.run()
            found = any(isinstance(x, _Ev) and not x.guarded for x in host.blocks[0][1])
        finally:
            self._active.discard(key)
        self._reaches[key] = found
        return found

    def open_reach(self) -> set[tuple[str, str]]:
        """The client methods an opening handler of a form may run."""
        names = _forms("ПослеСоздания") | _forms("ПриОткрытииПоСсылке") | _forms("ПослеЧтения")
        roots = [(stem, name) for stem in sorted(self.flows)
                 if self.graph.metadata.get(stem, {}).get("kind") == "КомпонентИнтерфейса"
                 for name in self.flows[stem] if name in names]
        reached = set(roots)
        queue = deque(roots)
        while queue:
            for target in self.edges(*queue.popleft()):
                if target not in reached:
                    reached.add(target)
                    queue.append(target)
        return reached

    def edges(self, stem: str, name: str) -> list[tuple[str, str]]:
        flow = self.flow(stem, name)
        if flow is None:
            return []
        out: list[tuple[str, str]] = []
        for edge in flow["edges"]:
            if edge[0] == "m":
                target = (stem, edge[1]) if edge[1] in self.flows.get(stem, {}) else None
            elif edge[0] == "q":
                target = self.module_target(stem, edge[1], edge[2])
            else:
                target = self.child_target(stem, edge[1], edge[2])
            if target is not None and self.env(*target) == "client" and target not in out:
                out.append(target)
        return out


class _Host:
    """The ordered walk of one client method.

    The main path collects the calls in execution order; a branch, a loop, a conditional
    operand and a catch body are walked as blocks of their own and leave a barrier on the
    path. A same-module client method is walked in place. Dependencies are a taint over names:
    a name written from a call's result carries that call, a later call that reads it in its
    receiver or arguments depends on it by data, and a call behind a condition that read it
    depends on it by control.
    """

    def __init__(self, project: _Project, stem: str, name: str, flow: dict):
        self.p = project
        self.stem = stem
        self.flow = flow
        self.events: list[_Ev] = []
        self.blocks: list[tuple[str, list]] = []
        self.taint: dict[str, frozenset] = {}
        self.ctrl: list[frozenset] = []
        self.path_ctrl: set = set()
        self.try_stack: list[int] = []
        self.inline: list[str] = [name]
        self.rets: list[set] = []
        self.guarded = False
        self.in_catch = 0
        self.in_loop = 0

    def run(self) -> None:
        items = self.block(self.flow["body"])
        self.blocks.insert(0, ("main", items))

    def add_block(self, kind: str, items: list) -> None:
        # Whatever nests in a catch body is error handling, and whatever nests in a loop body
        # repeats per item: neither is judged, so an inner block takes the outer kind.
        if self.in_catch:
            kind = "catch"
        elif self.in_loop:
            kind = "loop"
        self.blocks.append((kind, items))

    # --- taint -------------------------------------------------------------------------

    def taint_of(self, key: str) -> frozenset:
        if "." not in key:
            return self.taint.get(key, _EMPTY)
        parts = key.split(".")
        found: set = set()
        for i in range(1, len(parts) + 1):
            found |= self.taint.get(".".join(parts[:i]), _EMPTY)
        return frozenset(found)

    def write(self, key: str, value: frozenset, op: str) -> None:
        if op != "=":
            value = value | self.taint.get(key, _EMPTY)
        self.taint[key] = value

    def current_ctrl(self) -> frozenset:
        found = set(self.path_ctrl)
        for condition in self.ctrl:
            found |= condition
        return frozenset(found)

    def merge_into(self, merged: dict) -> None:
        for key, value in self.taint.items():
            merged[key] = merged.get(key, _EMPTY) | value

    # --- statements ----------------------------------------------------------------------

    def block(self, statements: list) -> list:
        out: list = []
        for st in statements:
            kind = st[0]
            if kind == "v":
                items, taint = self.expr(st[2])
                out += items
                self.write(st[1], taint, "=")
            elif kind == "a":
                _kind, key, op, target, value = st
                items, taint = self.expr(value)
                if key is None:
                    target_items, target_taint = self.expr(target)
                    items = target_items + items
                    taint = taint | target_taint
                out += items
                if key:
                    self.write(key, taint, op)
            elif kind == "e":
                out += self.expr(st[1])[0]
            elif kind == "r":
                items, taint = self.expr(st[1])
                out += items
                if self.rets:
                    self.rets[-1] |= taint
                break
            elif kind == "b":
                break
            elif kind == "if":
                out += self.branches(st)
            elif kind == "loop":
                out += self.loop(st)
            elif kind == "t":
                out += self.attempt(st)
            elif kind == "s":
                out += self.block(st[1])
        return out

    def branches(self, st: list) -> list:
        _kind, subject, arms, else_body, leaves = st
        out: list = []
        head: frozenset = _EMPTY
        if subject is not None:
            out, head = self.expr(subject)
        # The first condition always runs; the others run only when the ones before fail.
        for condition in (arms[0][0][:1] if arms else ()):
            items, taint = self.expr(condition)
            out += items
            head = head | taint
        saved = dict(self.taint)
        merged = dict(self.taint)
        saved_path_ctrl = set(self.path_ctrl)
        saved_guarded = self.guarded
        bodies = []
        self.ctrl.append(head)
        for index, (conditions, body) in enumerate(arms):
            self.taint = dict(saved)
            pre: list = []
            for condition in (conditions[1:] if index == 0 else conditions):
                pre += self.expr(condition)[0]
            bodies.append(pre + self.block(body))
            self.merge_into(merged)
        if else_body is not None:
            self.taint = dict(saved)
            bodies.append(self.block(else_body))
            self.merge_into(merged)
        self.ctrl.pop()
        self.path_ctrl = saved_path_ctrl
        self.guarded = saved_guarded
        self.taint = merged
        if leaves:
            self.guarded = True
        if any(_has_call(body) for body in bodies):
            out.append(_BARRIER)
            for body in bodies:
                if _has_call(body):
                    self.add_block("branch", body)
        elif head and leaves:
            # A guard without calls of its own: what follows runs only when it lets through.
            self.path_ctrl |= head
        return out

    def loop(self, st: list) -> list:
        _kind, heads, condition, body = st
        out: list = []
        head: frozenset = _EMPTY
        for expr in heads:
            items, taint = self.expr(expr)
            out += items
            head = head | taint
        pre: list = []
        self.in_loop += 1  # the condition of `while` runs per iteration as well
        if condition is not None:
            pre, head = self.expr(condition)
        self.ctrl.append(head)
        saved = dict(self.taint)
        saved_path_ctrl = set(self.path_ctrl)
        saved_guarded = self.guarded
        walked = pre + self.block(body)
        self.in_loop -= 1
        self.path_ctrl = saved_path_ctrl
        self.guarded = saved_guarded
        self.ctrl.pop()
        self.merge_into(saved)
        self.taint = saved
        if _has_call(walked):
            out.append(_BARRIER)
            self.add_block("loop", walked)
        return out

    def attempt(self, st: list) -> list:
        _kind, try_id, body, catches, final = st
        self.try_stack.append(try_id)
        out = self.block(body)
        self.try_stack.pop()
        for catch in catches:
            saved = dict(self.taint)
            self.in_catch += 1
            walked = self.block(catch)
            self.in_catch -= 1
            self.taint = saved
            if _has_call(walked):
                self.add_block("catch", walked)
        if final is not None:
            out += self.block(final)
        return out

    # --- expressions ---------------------------------------------------------------------

    def expr(self, e) -> tuple[list, frozenset]:
        if e is None:
            return [], _EMPTY
        kind = e[0]
        if kind == "n":
            return [], self.taint_of(e[1])
        if kind == "c":
            return self.call(e)
        if kind == "and" or kind == "??":
            left, left_taint = self.expr(e[1])
            right, right_taint = self.expr(e[2])
            return left + self.conditional(right, kind), left_taint | right_taint
        if kind == "?":
            cond, cond_taint = self.expr(e[1])
            then, then_taint = self.expr(e[2])
            other, other_taint = self.expr(e[3])
            return (cond + self.conditional(then, kind) + self.conditional(other, kind),
                    cond_taint | then_taint | other_taint)
        items: list = []
        taint: frozenset = _EMPTY
        for part in e[1]:
            part_items, part_taint = self.expr(part)
            items += part_items
            taint = taint | part_taint
        return items, taint

    def conditional(self, items: list, kind: str) -> list:
        """An operand that runs on some paths only: its calls become a block of their own."""
        if not _has_call(items):
            return items
        self.add_block(kind, items)
        return [_BARRIER]

    def event(self, call: str, line: int, col: int, deps: frozenset) -> _Ev:
        ev = _Ev(len(self.events), call, line, col, tuple(self.inline[1:]), deps,
                 self.current_ctrl(), self.try_stack[-1] if self.try_stack else None,
                 self.guarded)
        self.events.append(ev)
        return ev

    def call(self, e: list) -> tuple[list, frozenset]:
        _kind, target, receiver, args, line, col, spelled = e
        items, taint = self.expr(receiver)
        items = list(items)
        arg_taints = []
        for name, value in args:
            arg_items, arg_taint = self.expr(value)
            items += arg_items
            taint = taint | arg_taint
            arg_taints.append((name, arg_taint))
        if target is None:
            return items, taint
        project = self.p
        stem = self.stem
        if target[0] == "m":
            name = target[1]
            if name in project.graph.declared(stem) or project.flow(stem, name) is None:
                return items, taint
            env = project.env(stem, name)
            if env == "client":
                return self.inline_call(name, items, taint, arg_taints)
            fact = project.fact(stem, name)
            if (env != "server" or fact is None or not fact["available"]
                    or fact["cache"] not in ("missing", "false")):
                return items, taint
        elif target[0] == "q":
            found = project.module_target(stem, target[1], target[2])
            if found is None:
                return items, taint
            env = project.env(*found)
            if env == "server":
                fact = project.fact(*found)
                if fact is None or (fact["available"]
                                    and fact["cache"] not in ("missing", "false")):
                    return items, taint  # the client cache answers a repeated call
                if not project.graph.paths(stem, [target[1], target[2], spelled]):
                    return items, taint
            elif env != "client" or not project.reaches_server(*found):
                return items, taint
        else:
            found = project.child_target(stem, target[1], target[2])
            if (found is None or project.env(*found) != "client"
                    or not project.reaches_server(*found)):
                return items, taint
        ev = self.event(spelled, line, col, taint)
        return items + [ev], taint | {ev.id}

    def inline_call(self, name: str, items: list, taint: frozenset,
                    arg_taints: list) -> tuple[list, frozenset]:
        """Walk a same-module client method in place, its parameters tainted by the arguments."""
        if name in self.inline or len(self.inline) > _MAX_INLINE:
            return items, taint
        flow = self.p.flows[self.stem][name]
        callee_locals = self.p.local_names(self.stem, name)
        snapshot = dict(self.taint)
        by_name = {arg: arg_taint for arg, arg_taint in arg_taints if arg}
        positional = [arg_taint for arg, arg_taint in arg_taints if not arg]
        for index, param in enumerate(flow["params"]):
            self.taint[param] = by_name.get(
                param, positional[index] if index < len(positional) else _EMPTY)
        self.inline.append(name)
        self.rets.append(set())
        # An early return inside the callee ends the callee only, not the caller's path.
        saved_path_ctrl = set(self.path_ctrl)
        saved_guarded = self.guarded
        body = self.block(flow["body"])
        self.path_ctrl = saved_path_ctrl
        self.guarded = saved_guarded
        returned = frozenset(self.rets.pop())
        self.inline.pop()
        after = snapshot
        for key, value in self.taint.items():
            if key.split(".", 1)[0] not in callee_locals:
                after[key] = value
        self.taint = after
        return items + body, taint | returned


class _Series:
    """A run of server calls found in one client method."""

    __slots__ = ("stem", "host", "on_open", "calls")

    def __init__(self, stem: str, host: str, on_open: bool, calls: list[_Ev]):
        self.stem = stem
        self.host = host
        self.on_open = on_open
        self.calls = calls

    def data_dependency(self) -> tuple[_Ev, list[_Ev]] | None:
        """The first call whose receiver or arguments come from an earlier call of the run."""
        for index, later in enumerate(self.calls[1:], 1):
            earlier = [e for e in self.calls[:index] if e.id in later.deps]
            if earlier:
                return later, earlier
        return None


def find_series(facts: dict[str, dict], scope: str,
                min_calls: int) -> tuple[_Project, list[_Series]]:
    """The runs of `min_calls` and more server calls, one per distinct set of call sites.

    `scope` is "open" (the methods an opening handler may run) or "all" (every client
    method). A run in a catch or a loop body and a run whose calls stand in different `try`
    statements are left out before the runs are compared, so a clean run inside a mixed one
    survives.
    The same call sites found from several methods are kept once, for the method that walks
    the fewest levels in place; a run contained in a longer one is dropped.
    """
    project = _Project(facts)
    if not project.graph.has_data:
        return project, []
    reach = project.open_reach()
    found: list[_Series] = []
    for stem in sorted(project.flows):
        for name, flow in project.flows[stem].items():
            if project.env(stem, name) != "client":
                continue
            on_open = (stem, name) in reach
            if scope != "all" and not on_open:
                continue
            host = _Host(project, stem, name, flow)
            host.run()
            for kind, items in host.blocks:
                if kind in ("catch", "loop"):
                    continue
                for run in _runs(items):
                    if len(run) >= min_calls and len({e.try_id for e in run}) == 1:
                        found.append(_Series(stem, name, on_open, run))
    best: dict[frozenset, tuple[int, _Series]] = {}
    for series in found:
        key = frozenset((series.stem, e.line, e.col) for e in series.calls)
        depth = sum(len(e.via) for e in series.calls)
        if key not in best or depth < best[key][0]:
            best[key] = (depth, series)
    keys = list(best)
    kept = [best[key][1] for key in keys if not any(key < other for other in keys)]
    kept.sort(key=lambda s: (project.rels[s.stem], s.calls[0].line, s.calls[0].col))
    return project, kept


@rule(
    RULE, f"{RULE}.title", "D", scope="project", severity=Severity.INFO,
    enabled_by_default=False, off_reason=f"{RULE}.off", mapper=sequence_mapper,
)
def sequential_server_calls(facts: dict[str, dict]) -> Iterable[Diagnostic]:
    """One finding per run of server calls, on the line of its first call."""
    project, found = find_series(facts, SCOPE, MIN_CALLS)
    for series in found:
        calls = ", ".join(f"{e.call}:{e.line}" for e in series.calls)
        head = "open" if series.on_open else "any"
        parts = [
            i18n.t(f"{RULE}.{head}", method=series.host, count=len(series.calls), calls=calls),
            i18n.t(f"{RULE}.advice"),
        ]
        dependency = series.data_dependency()
        if dependency is not None:
            later, earlier = dependency
            parts.append(i18n.t(f"{RULE}.data", later=f"{later.call}:{later.line}",
                                earlier=", ".join(f"{e.call}:{e.line}" for e in earlier)))
        first = series.calls[0]
        yield Diagnostic(project.rels[series.stem], first.line, first.col, RULE, Severity.INFO,
                         " ".join(parts))
