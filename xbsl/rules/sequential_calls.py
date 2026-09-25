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
from functools import lru_cache

from xbsl import dataset, parser as P, terms
from xbsl.engine import SourceFile
from xbsl.lexer import linemap
from xbsl.rules._server_calls import _type_head, server_call_mapper
from xbsl.rules.environment import _pair_stem
from xbsl.rules.yaml_schema import _HAVE_YAML, _composed, _mapping_nodes, _scalar_entries

if _HAVE_YAML:
    import yaml

RULE = "code/sequential-server-calls"

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

    def __init__(self, source: SourceFile, components: frozenset[str]):
        self.lines = linemap(source)
        self.components = components
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
        """Every method the body may run, timer lambdas included and method references not.

        The opening path follows these: a handler that starts a timer with `() -> Load()`
        opens the page through `Load` as much as through a direct call.
        """
        out: list = []
        stack: list = [method.body]
        while stack:
            item = stack.pop()
            if isinstance(item, (list, tuple)):
                stack.extend(reversed(item))
                continue
            if not isinstance(item, P.Node) or isinstance(item, P.MethodRef):
                continue
            if isinstance(item, P.Call):
                edge = self.edge(item.callee)
                if edge is not None and edge not in out:
                    out.append(edge)
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
    compiler = _Flow(source, _forms("Компоненты"))
    flows = {}
    for member in module.members:
        if isinstance(member, P.Method) and methods.get(member.name) is not None:
            flows[member.name] = compiler.method(member)
    return {**base, "flows": flows}
