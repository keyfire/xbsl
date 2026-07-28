"""Tier D: a member access on a tabular section's row collection must exist on it.

The collection of a tabular section is an array - the compiler names it outright
(`Массив<Задачи.Шаги>`), so its members are the array members of the stdlib
catalog. Neither unknown-member rule sees the shape though: the receiver is typed by the
PROJECT's metadata, not by a declaration - `Объект.Шаги` in a form module (the
implicit data object of `ФормаОбъекта<Задачи.Объект>`), the bare section name or
`этот.Шаги` in the entity's own modules. That is how `.Количество()` (the array
member is called `Размер`) passed the linter and failed the server apply.

Narrow by design: only the middle link that IS a declared tabular section of the resolved
entity is judged - an attribute, a standard member or anything else is skipped, not
guessed. A method that binds the root name itself (`знч Объект = ...`) silences its uses.
"""

from __future__ import annotations

import difflib
import re
from collections.abc import Iterable

from xbsl import i18n, terms
from xbsl import parser as P
from xbsl.diagnostics import Diagnostic, Severity
from xbsl.engine import SourceFile, rule
from xbsl.lexer import linemap
from xbsl.parser import parse
from xbsl.rules.environment import _pair_stem
from xbsl.rules.unknown_members import _COMMON_MEMBERS, _is_latin, _stdlib_members
from xbsl.rules.yaml_schema import _HAVE_YAML, _parsed, object_kind, value_of

MESSAGES = {
    "code/unknown-tabular-member.title": {
        "ru": "Неизвестный член табличной части",
        "en": "Unknown member of a tabular section",
    },
    "code/unknown-tabular-member.found": {
        "ru": "У строк табличной части '{section}' нет члена {member} – их коллекция "
              "это {n[Массив]}<{owner}.{section}>",
        "en": "The rows of tabular section '{section}' have no member {member} - their "
              "collection is {n[Массив]}<{owner}.{section}>",
    },
    "code/unknown-tabular-member.found-hint": {
        "ru": "У строк табличной части '{section}' нет члена {member} – их коллекция "
              "это {n[Массив]}<{owner}.{section}>, возможно, имелся в виду {hint}",
        "en": "The rows of tabular section '{section}' have no member {member} - their "
              "collection is {n[Массив]}<{owner}.{section}>, did you mean {hint}",
    },
}
i18n.register(MESSAGES)

# The base type of an object form carries the entity: `ФормаОбъекта<Программы.Объект>`.
# Both spellings of the type name and of the Объект facet come from the platform's terms.
_FORM_BASE_RE = re.compile(
    r"^\s*(?P<base>[А-Яа-яЁёA-Za-z]+)\s*<\s*(?P<entity>[А-Яа-яЁёA-Za-z0-9_]+)\s*\.\s*"
    r"(?P<facet>[А-Яа-яЁёA-Za-z]+)\s*>\s*$"
)


def _object_form_bases() -> frozenset[str]:
    return frozenset(terms.forms("ФормаОбъекта", "types"))


def _object_facets() -> frozenset[str]:
    facet = {"Объект"}
    english = terms.english("Объект", "types")
    if english:
        facet.add(english)
    return frozenset(facet)


def _data_object_names() -> frozenset[str]:
    """The implicit name of the form's data object, in both spellings."""
    return _object_facets()


def _tabular_key_forms() -> frozenset[str]:
    return frozenset(terms.key_forms("ТабличныеЧасти"))


def _name_key_forms() -> frozenset[str]:
    return frozenset(terms.key_forms("Имя"))


class _Uses:
    """Member accesses of one method over the two judged roots, minus shadowed names."""

    def __init__(self) -> None:
        self.bound: set[str] = set()
        # (root is the data object or None for `этот`/bare, section name, member, position)
        self.found: list[tuple[str | None, str, str, int]] = []

    def bind(self, name: str | None) -> None:
        if name:
            self.bound.add(name)


def _walk_expr(expr: P.Expr | None, uses: _Uses, data_names: frozenset[str]) -> None:
    if expr is None:
        return
    if isinstance(expr, P.Member):
        base = expr.obj
        # Объект.Секция.Член and этот.Секция.Член - the member sits on the OUTER hop.
        if isinstance(base, P.Member):
            root = base.obj
            if isinstance(root, P.Name) and root.name in data_names:
                uses.found.append((root.name, base.name, expr.name, expr.start))
            elif isinstance(root, P.This):
                uses.found.append((None, base.name, expr.name, expr.start))
        elif isinstance(base, P.Name):
            # Голое имя секции в модуле сущности: Секция.Член.
            uses.found.append((None, base.name, expr.name, expr.start))
        _walk_expr(expr.obj, uses, data_names)
        return
    if isinstance(expr, P.Lambda):
        for p in expr.params:
            uses.bind(p.name)
        if isinstance(expr.body_expr, P.Expr):
            _walk_expr(expr.body_expr, uses, data_names)
        elif isinstance(expr.body_expr, P.Assign):
            _walk_expr(expr.body_expr.target, uses, data_names)
            _walk_expr(expr.body_expr.value, uses, data_names)
        if expr.body_stmts is not None:
            _walk_body(expr.body_stmts, uses, data_names)
        return
    if isinstance(expr, P.Call):
        _walk_expr(expr.callee, uses, data_names)
        for arg in expr.args:
            _walk_expr(arg.value, uses, data_names)
    elif isinstance(expr, P.Unary):
        _walk_expr(expr.operand, uses, data_names)
    elif isinstance(expr, P.Binary):
        _walk_expr(expr.left, uses, data_names)
        _walk_expr(expr.right, uses, data_names)
    elif isinstance(expr, P.Compare):
        _walk_expr(expr.first, uses, data_names)
        for _op, right in expr.rest:
            _walk_expr(right, uses, data_names)
    elif isinstance(expr, (P.IsType, P.AsType, P.NonNull)):
        _walk_expr(expr.operand, uses, data_names)
    elif isinstance(expr, P.Ternary):
        _walk_expr(expr.cond, uses, data_names)
        _walk_expr(expr.then, uses, data_names)
        _walk_expr(expr.otherwise, uses, data_names)
    elif isinstance(expr, P.Coalesce):
        _walk_expr(expr.left, uses, data_names)
        _walk_expr(expr.right, uses, data_names)
    elif isinstance(expr, P.Index):
        _walk_expr(expr.obj, uses, data_names)
        _walk_expr(expr.index, uses, data_names)
    elif isinstance(expr, P.New):
        if expr.args:
            for arg in expr.args:
                _walk_expr(arg.value, uses, data_names)
    elif isinstance(expr, P.ArrayLit):
        for item in expr.items:
            _walk_expr(item, uses, data_names)
    elif isinstance(expr, P.MapLit):
        for k, v in expr.entries:
            _walk_expr(k, uses, data_names)
            _walk_expr(v, uses, data_names)
    elif isinstance(expr, P.Throw):
        _walk_expr(expr.value, uses, data_names)


def _walk_body(stmts: list[P.Stmt], uses: _Uses, data_names: frozenset[str]) -> None:
    for st in stmts:
        if isinstance(st, P.VarDecl):
            uses.bind(st.name)
            _walk_expr(st.init, uses, data_names)
        elif isinstance(st, P.Assign):
            if isinstance(st.target, P.Name):
                uses.bind(st.target.name)
            else:
                _walk_expr(st.target, uses, data_names)
            _walk_expr(st.value, uses, data_names)
        elif isinstance(st, (P.ExprStmt, P.UseStmt)):
            _walk_expr(st.expr, uses, data_names)
        elif isinstance(st, P.If):
            for cond, body in st.branches:
                _walk_expr(cond, uses, data_names)
                _walk_body(body, uses, data_names)
            if st.else_body is not None:
                _walk_body(st.else_body, uses, data_names)
        elif isinstance(st, P.Case):
            if st.subject is not None:
                _walk_expr(st.subject, uses, data_names)
            for when in st.whens:
                for cond in when.conditions:
                    _walk_expr(cond, uses, data_names)
                _walk_body(when.body, uses, data_names)
            if st.else_body is not None:
                _walk_body(st.else_body, uses, data_names)
        elif isinstance(st, P.While):
            _walk_expr(st.cond, uses, data_names)
            _walk_body(st.body, uses, data_names)
        elif isinstance(st, P.ForEach):
            uses.bind(st.var)
            _walk_expr(st.source, uses, data_names)
            _walk_body(st.body, uses, data_names)
        elif isinstance(st, P.ForTo):
            uses.bind(st.var)
            _walk_expr(st.start_expr, uses, data_names)
            _walk_expr(st.to, uses, data_names)
            if st.step is not None:
                _walk_expr(st.step, uses, data_names)
            _walk_body(st.body, uses, data_names)
        elif isinstance(st, P.Try):
            _walk_body(st.body, uses, data_names)
            for var, _tref, body in st.catches:
                uses.bind(var)
                _walk_body(body, uses, data_names)
            if st.finally_body is not None:
                _walk_body(st.finally_body, uses, data_names)
        elif isinstance(st, P.Scope):
            _walk_body(st.body, uses, data_names)
        elif isinstance(st, P.Return):
            _walk_expr(st.value, uses, data_names)


def _tabular_mapper(source: SourceFile) -> dict | None:
    """The map phase.

    An entity yaml publishes its name and tabular sections; a form yaml publishes the
    entity its base type names (`ФормаОбъекта<X.Объект>`); a module publishes its member
    chains over the two roots. The reduce joins them: the middle link must be a section of
    the resolved entity, and only then the member is judged - against the array members.
    """
    if not _HAVE_YAML:
        return None
    if source.kind == "yaml":
        data, err = _parsed(source)
        if err is not None or not isinstance(data, dict) or not object_kind(data):
            return None
        kind = object_kind(data)
        if kind == "КомпонентИнтерфейса":
            inherits = next(
                (data[key] for key in terms.key_forms("Наследует") if key in data), None)
            base = None
            if isinstance(inherits, dict):
                base = next(
                    (inherits[key] for key in terms.key_forms("Тип") if key in inherits),
                    None)
            if not isinstance(base, str):
                return None
            m = _FORM_BASE_RE.match(base)
            if (m is None or m.group("base") not in _object_form_bases()
                    or m.group("facet") not in _object_facets()):
                return None
            return {"k": "form", "stem": _pair_stem(source.rel), "entity": m.group("entity")}
        name = value_of(data, "Имя", kind)
        if not isinstance(name, str):
            return None
        name_keys = _name_key_forms()
        sections: list[str] = []
        for key in _tabular_key_forms():
            items = data.get(key)
            if not isinstance(items, list):
                continue
            for item in items:
                if isinstance(item, dict):
                    for nk in name_keys:
                        section = item.get(nk)
                        if isinstance(section, str):
                            sections.append(section)
                            break
        if not sections:
            return None
        return {"k": "entity", "stem": _pair_stem(source.rel), "name": name,
                "tabulars": sorted(sections)}
    if source.kind != "xbsl":
        return None
    # The callable name of a module is its file stem (dotted stems are not reachable
    # bare); every module contributes its stem, so the reduce can tell a bare section
    # name from a same-named module - real projects keep modules called after a section.
    stem = _pair_stem(source.rel)
    callable_name = stem.rsplit("/", 1)[-1]
    if "." in callable_name:
        callable_name = ""
    module, errors = parse(source)
    if errors:
        return {"k": "x", "stem": stem, "name": callable_name, "chains": []}
    data_names = _data_object_names()
    methods: list[P.Method] = []
    for m in module.members:
        if isinstance(m, P.Method):
            methods.append(m)
        elif isinstance(m, P.Structure):
            methods.extend(sub for sub in m.members if isinstance(sub, P.Method))
        elif isinstance(m, P.Enum):
            methods.extend(m.methods)
    lm = None
    chains: list[list] = []
    for method in methods:
        uses = _Uses()
        for p in method.params:
            uses.bind(p.name)
            _walk_expr(p.default, uses, data_names)
        _walk_body(method.body, uses, data_names)
        for root, section, member, start in uses.found:
            if root is not None and root in uses.bound:
                continue  # the method rebinds the data-object name - it is a local now
            if section in uses.bound or _is_latin(member):
                continue
            if lm is None:
                lm = linemap(source)
            line, col = lm.linecol(start)
            chains.append([root or "", section, member, line, col])
    if not chains and not callable_name:
        return None
    return {"k": "x", "stem": stem, "name": callable_name, "chains": chains}


def _array_members() -> frozenset[str]:
    members = _stdlib_members()
    for form in terms.forms("Массив", "types"):
        found = members.get(form)
        if found:
            return found
    return frozenset()


# Habits from the other platform difflib cannot bridge: the member 1С:Предприятие calls
# Количество() is Размер() here - the very miss this rule exists for.
_HABIT_HINTS = {"Количество": "Размер"}


@rule(
    "code/unknown-tabular-member", "code/unknown-tabular-member.title", "D",
    scope="project", severity=Severity.ERROR, mapper=_tabular_mapper,
)
def unknown_tabular_member(facts: dict[str, dict]) -> Iterable[Diagnostic]:
    """A member access on a tabular section's rows must exist on the array type.

    `Объект.Секция.Член` in an object form module, and the bare `Секция.Член` or
    `этот.Секция.Член` in the entity's own modules (`X.xbsl`, `X.Объект.xbsl`). The middle
    link must be a DECLARED tabular section of the entity the module belongs to - anything
    else is not judged, so an attribute or a form component of the same name stays silent.
    """
    array_members = _array_members()
    if not array_members:
        return
    entities: dict[str, dict] = {}   # yaml stem -> {"name", "tabulars"}
    forms: dict[str, str] = {}       # form stem -> entity name
    modules: set[str] = set()        # bare-callable module names shadow section names
    for fact in facts.values():
        if fact["k"] == "entity":
            entities[fact["stem"]] = fact
        elif fact["k"] == "form":
            forms[fact["stem"]] = fact["entity"]
        elif fact["k"] == "x" and fact["name"]:
            modules.add(fact["name"])
    if not entities:
        return
    by_name = {fact["name"]: fact for fact in entities.values()}
    for rel, fact in facts.items():
        if fact["k"] != "x":
            continue
        stem = fact["stem"]
        # The entity's own modules: X.xbsl pairs the yaml outright, X.Объект.xbsl adds
        # one dotted suffix to the same stem.
        own = entities.get(stem) or entities.get(stem.rsplit(".", 1)[0])
        entity_of_form = by_name.get(forms.get(stem, ""))
        for root, section, member, line, col in fact["chains"]:
            owner = entity_of_form if root else own
            if owner is None or section not in owner["tabulars"]:
                continue
            if not root and section in modules:
                continue  # a module named after the section: the call is on the module
            if member in array_members or member in _COMMON_MEMBERS:
                continue
            habit = _HABIT_HINTS.get(member)
            hint = ([habit] if habit in array_members else
                    difflib.get_close_matches(member, array_members, n=1, cutoff=0.75))
            message = (
                i18n.t("code/unknown-tabular-member.found-hint",
                       section=section, member=member, owner=owner["name"], hint=hint[0])
                if hint
                else i18n.t("code/unknown-tabular-member.found",
                            section=section, member=member, owner=owner["name"])
            )
            yield Diagnostic(
                rel, line, col, "code/unknown-tabular-member", Severity.ERROR, message,
            )
