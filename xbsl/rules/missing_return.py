"""A typed method needs a result on every path that can finish normally.

Project scope is needed for complete cases over YAML enumerations and for calls whose
declared result is never. Unknown case domains and unresolved calls retain an unknown
outcome instead of becoming errors. A known void call still falls through. Loops do not
guarantee a return, including a literal true loop, and a lambda's return belongs to it.
"""

from __future__ import annotations

from collections.abc import Iterable
from functools import lru_cache

from xbsl import dataset, i18n, parser as P, terms, typeinfer as T
from xbsl.diagnostics import Diagnostic, Severity
from xbsl.engine import rule
from xbsl.lexer import linemap
from xbsl.rules.control_flow import _compared_value
from xbsl.rules.redundant_checks import _TextSource
from xbsl.rules.return_mismatch import _returns

RULE = "code/missing-return"
MESSAGES = {
    f"{RULE}.title": {
        "ru": "Метод может завершиться без возврата значения",
        "en": "Method can finish without returning a value",
    },
    f"{RULE}.found": {
        "ru": "Метод '{name}' объявляет результат '{type}', но может завершиться без его "
              "возврата. Верните значение на каждом пути выполнения.",
        "en": "Method '{name}' declares result '{type}' but can finish without returning "
              "it. Return a value on every execution path.",
    },
}
i18n.register(MESSAGES)


@lru_cache(maxsize=1)
def _result_keywords() -> tuple[frozenset[str], frozenset[str]]:
    keywords = dataset.load_json("language.json")["keywords"]
    return frozenset(keywords["VOID"]["forms"]), frozenset(keywords["NEVER"]["forms"])


dataset.register_reset(_result_keywords.cache_clear)


@lru_cache(maxsize=None)
def _platform_enum_values(name: str) -> dict[str, str] | None:
    """Both spellings of each enum constant, from the compiler's exact owner table."""
    owner = terms.type_english(name) + terms._ENUM_CLASS_MARK
    pairs = terms._members_by_owner().get(owner)
    if not pairs:
        return None
    return {spelling: russian for russian, english in pairs.items()
            for spelling in (russian, english)}


dataset.register_reset(_platform_enum_values.cache_clear)


def _wants_text(source) -> bool:
    module, errors = P.parse(source)
    return not errors and any(m.return_type is not None for m in T.walk_nodes(module)
                              if isinstance(m, P.Method))


T.wants_text(_wants_text)


def _branches(values: list[bool | None]) -> bool | None:
    """True: every path exits; False: a known path falls through; None: not established."""
    if False in values:
        return False
    return True if all(value is True for value in values) else None


class _Flow:
    def __init__(self, typing: T.ModuleTyping, evaluator: T._Evaluator) -> None:
        self.typing, self.evaluator = typing, evaluator
        self.catalog = typing.catalog

    def block(self, body: list[P.Stmt]) -> bool | None:
        outcome: bool | None = False
        for statement in body:
            result = self.statement(statement)
            if result is True:
                return True
            if result is None:
                outcome = None
        return outcome

    def statement(self, statement: P.Stmt) -> bool | None:
        if isinstance(statement, P.Return):
            return True
        if isinstance(statement, (P.Break, P.Continue)):
            return None  # misplaced jumps belong to their own rule
        if isinstance(statement, P.ExprStmt):
            if isinstance(statement.expr, P.Throw):
                return True
            if isinstance(statement.expr, P.Call):
                return self.call(statement.expr)
            return False
        if isinstance(statement, P.If):
            return _branches([self.block(body) for _, body in statement.branches]
                             + [self.block(statement.else_body or [])])
        if isinstance(statement, P.Case):
            outcomes = [self.block(when.body) for when in statement.whens]
            if statement.else_body is not None:
                outcomes.append(self.block(statement.else_body))
            else:
                coverage = self.coverage(statement)
                if coverage is not True:
                    outcomes.append(False if coverage is False else None)
            return _branches(outcomes)
        if isinstance(statement, (P.While, P.ForEach, P.ForTo)):
            return False
        if isinstance(statement, P.Scope):
            return self.block(statement.body)
        if isinstance(statement, P.Try):
            return _branches([self.block(statement.body)]
                             + [self.block(body) for _, _, body in statement.catches])
        return False

    def coverage(self, statement: P.Case) -> bool | None:
        """Compare the case labels with the finite domain its subject actually has."""
        types = T._typed(self.evaluator, statement.subject)
        conditions = [_compared_value(c) for when in statement.whens for c in when.conditions]
        if types is None:
            return None
        if all(isinstance(c, P.IsType) for c in conditions):
            if any(c.negated for c in conditions):
                return None
            checks = [self.typing.typer.written(c.type.text) for c in conditions
                      if isinstance(c, P.IsType) and not c.negated and c.type]
            if not checks or any(check is None for check in checks):
                return None
            atoms = [T.TypeSet.of(name) for name in types.names]
            if types.undefined:
                atoms.append(T.TypeSet(undefined=True))
            if types.null:
                atoms.append(T.TypeSet(null=True))
            return all(any(T.always_holds(atom, check, self.catalog.assignable)
                           for check in checks if check is not None) for atom in atoms)
        if any(isinstance(c, P.IsType) for c in conditions):
            return None  # mixed type and value patterns need a combined domain analysis
        remaining: set[tuple[str, str]] = set()
        platform_values: dict[str, dict[str, str]] = {}
        if types.undefined:
            remaining.add(("literal", "UNDEFINED"))
        if types.null:
            remaining.add(("literal", "NULL"))
        for name in types.names:
            if name == T._LITERAL_TYPES["TRUE"]:
                remaining.update({("literal", "TRUE"), ("literal", "FALSE")})
                continue
            enum = self.catalog.elements.get(name, {})
            values = enum.get("values") if enum.get("kind") == "Перечисление" else None
            module, _, nested = name.partition(".")
            if values is None:
                values = self.catalog.modules.get(module, {}).get("enums", {}).get(nested)
            if values is None:
                if "Перечисление" in T._platform_bases(name):
                    aliases = _platform_enum_values(name)
                    if aliases is None:
                        return None
                    platform_values[name] = aliases
                    values = set(aliases.values())
            if values is None:
                return False if T.platform_head(name) else None
            remaining.update((name, value) for value in values)
        for condition in conditions:
            if isinstance(condition, P.Literal):
                remaining.discard(("literal", condition.kind))
            elif isinstance(condition, P.Name):
                if self.evaluator.scope.lookup(condition.name, condition.start) is not T._MISSING:
                    return None
                for name in types.names:
                    value = platform_values.get(name, {}).get(condition.name, condition.name)
                    remaining.discard((name, value))
            elif isinstance(condition, P.Member) and not condition.safe:
                owner = self.evaluator.value(condition.obj)
                if isinstance(owner, T.StaticName):
                    resolved = self.catalog.head(owner.name, self.typing.scope.module) or owner.name
                    value = platform_values.get(resolved, {}).get(condition.name, condition.name)
                    remaining.discard((resolved, value))
        return not remaining

    def _raw_results(self, owner: str, name: str) -> list[str | None] | None:
        module, _, nested = owner.partition(".")
        facts = self.catalog.modules.get(module, {})
        if nested:
            return facts.get("structures", {}).get(nested, {}).get("methods", {}).get(name)
        return facts.get("methods", {}).get(name)

    def call(self, call: P.Call) -> bool | None:
        """A declared void/result call falls through; never exits; unknown stays unknown."""
        evaluator = self.evaluator
        if T._typed(evaluator, call) is not None:
            return False
        callee = call.callee
        results = None
        if isinstance(callee, P.Name):
            if (evaluator.scope.lookup(callee.name, callee.start) is not T._MISSING
                    or callee.name in (evaluator.owner_fields or {})
                    or callee.name in evaluator.typer.fields
                    or callee.name in evaluator.typer.scope.own_properties):
                return None
            if evaluator.this_type and len(evaluator.this_type.names) == 1:
                results = self._raw_results(next(iter(evaluator.this_type.names)), callee.name)
            if results is None:
                results = self._raw_results(self.typing.scope.module or "", callee.name)
        elif isinstance(callee, P.Member):
            owner = evaluator.value(callee.obj)
            if isinstance(owner, T.StaticName):
                name = owner.name
            elif (isinstance(owner, T.TypeSet) and len(owner.names) == 1 and not owner.null
                  and (not owner.undefined or callee.safe)):
                name = next(iter(owner.names))
            else:
                return None
            results = self._raw_results(name, callee.name)
            if results is None:
                head, _ = T.split_nominal(name)
                member = T._member_names(head).get(callee.name)
                signatures = T._catalog().get("member_signatures", {}).get(head, {}).get(member, [])
                if signatures:
                    shapes = [T._signature(signature) for signature in signatures]
                    if any(shape is None for shape in shapes):
                        return None
                    results = [shape[2] for shape in shapes if shape is not None]
        if not results:
            return None
        if (isinstance(callee, P.Member) and callee.safe
                and isinstance(owner, T.TypeSet) and owner.undefined):
            return False  # the empty receiver can reach the next statement without a call
        flags = [result in _result_keywords()[1] for result in results]
        return flags[0] if len(set(flags)) == 1 else None

    def fallthrough_at(self, body: list[P.Stmt]) -> int:
        """The last token on a known unfinished branch, including nested catch bodies."""
        statement = body[-1]
        branches = []
        if isinstance(statement, P.Try):
            branches = [statement.body, *[b for _, _, b in statement.catches]]
        elif isinstance(statement, P.If) and statement.else_body is not None:
            branches = [*[b for _, b in statement.branches], statement.else_body]
        elif isinstance(statement, P.Case):
            branches = [w.body for w in statement.whens]
            if statement.else_body is not None:
                branches.append(statement.else_body)
        elif isinstance(statement, P.Scope):
            branches = [statement.body]
        for branch in branches:
            if branch and self.block(branch) is False:
                return self.fallthrough_at(branch)
        return statement.end - 1


def _missing(typing: T.ModuleTyping) -> Iterable[tuple[P.Method, int]]:
    typer = typing.typer
    typer._prepare(typing.tree)
    for method, this_type, fields in typer._methods(typing.tree, True):
        if (method.is_abstract or method.return_type is None
                or method.return_type.text in _result_keywords()[0] | _result_keywords()[1]):
            continue
        element = typing.catalog.elements.get(typing.scope.module or "", {})
        if this_type is None and element.get("kind") == "Перечисление":
            this_type = T.TypeSet(frozenset({typing.scope.module}))
        try:
            scope = T._MethodScope(method, list(T.walk_nodes(method.body)))
            evaluator = T._Evaluator(typer, scope, this_type, fields)
            flow = _Flow(typing, evaluator)
            outcome = flow.block(method.body)
        except RecursionError:
            continue
        if outcome is False:
            returns: list[P.Return] = []
            _returns(method.body, returns)
            offset = (flow.fallthrough_at(method.body) if returns and method.body
                      else method.return_type.start)
            yield method, offset


@rule(RULE, f"{RULE}.title", "D", scope="project", severity=Severity.ERROR,
      mapper=T.project_fact)
def missing_return(facts: dict[str, dict]) -> Iterable[Diagnostic]:
    """Report a known path that reaches the end of a method with a declared value result."""
    for rel, typing in T.project_typings(facts).items():
        lines = None
        for method, offset in _missing(typing):
            if lines is None:
                lines = linemap(_TextSource(typing.text))
            line, col = lines.linecol(offset)
            yield Diagnostic(rel, line, col, RULE, Severity.ERROR,
                             i18n.t(f"{RULE}.found", name=method.name, type=method.return_type.text))
