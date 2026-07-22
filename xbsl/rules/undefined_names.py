r"""Tier D: undefined names in expressions - the first pass of the symbol table over the AST.

Catches the classic typo the compiler rejects but no token heuristic can see:

    метод ТелоПравки(Адреса: Массив<Строка>): Строка
        для Адрес из Адресар   // <- 'Адресар' is not declared anywhere

Scope model (per the platform semantics):
- the module level contributes its methods, structures/enums/exceptions and module
  fields/constants;
- a method contributes its parameters; statements introduce names as they go (пер/знч/исп,
  loop variables, поймать variables); a lambda opens a nested scope with its parameters;
- the project contributes object and common-module names (from the yaml sources of the run),
  the stdlib contributes its global names - both via the helpers of rules/semantics.py.

Only the ROOT of a member chain is checked (`Х` in `Х.Поле[0].Метод()`): member names need
type inference (stage 3). Qualified roots (`Подсистема::Имя`) and method references are
skipped. Roots the file's module kind provides implicitly (`Компоненты` of a form module,
`Это`/`До` of an object module etc.) are collected in _IMPLICIT - verified on the corpus.

String literals are walked too, because a name can be spelled inside one: per the platform
docs (Стд::Строка, "Интерполяция") `%Имя` and `$Имя` are SHORT interpolations of a name, and
only a sign followed by something that cannot start an identifier is an ordinary character.
That is what turns a forgotten escape into a compile error - `"...?$format=json"` reads as a
substitution of the name `format`, and the fix is `\$format`, not a declaration. The full
form (`%{Выражение}` / `${Выражение}`) is skipped whole: its contents are an expression that
would need parsing, no such breakage has been seen, and a rule that stays silent there costs
nothing.

The rule needs the stdlib catalog (tier D): without the data it is silent - a name unknown
to an incomplete world is not evidence.
"""

from __future__ import annotations

import difflib
import re
from collections.abc import Iterable

from xbsl import dataset, i18n, parser as P
from xbsl.diagnostics import Diagnostic, Severity
from xbsl.engine import SourceFile, rule
from xbsl.lexer import _IDENT_RE, _skip_interpolation, linemap
from xbsl.rules.semantics import _object_name_fast, _parsed, _stdlib_names

MESSAGES = {
    "code/undefined-name.title": {
        "ru": "Неизвестное имя",
        "en": "Undefined name",
    },
    "code/undefined-name.found": {
        "ru": "Имя '{name}' нигде не объявлено – компилятор откажет.",
        "en": "Name '{name}' is not declared anywhere - the compiler will reject it.",
    },
    "code/undefined-name.found-hint": {
        "ru": "Имя '{name}' нигде не объявлено – возможно, имелось в виду '{hint}'.",
        "en": "Name '{name}' is not declared anywhere - did you mean '{hint}'?",
    },
    "code/undefined-name.found-interp": {
        "ru": "'{sign}{name}' в строке – интерполяция имени '{name}', а оно нигде не "
              "объявлено. Если знак должен остаться символом, экранируйте: '\\{sign}{name}'.",
        "en": "'{sign}{name}' inside the string is an interpolation of the name '{name}', "
              "which is not declared anywhere. To keep the sign a plain character, escape "
              "it: '\\{sign}{name}'.",
    },
}
i18n.register(MESSAGES)

# Context roots the module kind itself provides (never declared in code): collected by
# running over the corpus and from the documentation of the module kinds.
_IMPLICIT = frozenset({
    "Компоненты", "Components",   # an interface-component module: access to the named form components
    "Это", "До",    # an object module: the record after/before the change in ПередЗаписью/ПослеЗаписи
    "Сущность",     # the rights namespace in permission handlers (Сущность.Право.Чтение)
})

# Standard attributes available by bare name in an entity module (X.Объект.xbsl): the
# platform provides them without a yaml declaration (Наименование/Код of a catalog,
# Номер/Дата of a document, Период/Регистратор/ВидЗаписи of register records) plus
# Ссылка and the write methods.
# Members that exist on the platform but are absent from the distribution docs -
# verified against real shipped code (a large real project and the demo). Kept deliberately tiny.
_UNDOCUMENTED = frozenset({
    "ВыполнитьЗаписать", "ВыполнитьЗаписатьИЗакрыть",  # ФормаОбъекта commands
    "СобственнаяМодифицированность",                   # a form-component property
    "Message",                                          # the English form of Сообщить
})

_ENTITY_COMMON = frozenset({
    "Наименование", "Код", "Номер", "Дата", "Ссылка",
    "Период", "Регистратор", "ВидЗаписи",
    "Записать", "Удалить", "ПометитьНаУдаление", "СнятьПометкуУдаления",
    "ЭтоНовый", "ПометкаУдаления", "РежимЗагрузкиДанных",
})

# The yaml sections whose items become bare names in the object modules.
_FIELD_SECTIONS = (
    "Реквизиты", "Измерения", "Ресурсы", "Константы", "Свойства", "Параметры",
    "ТабличныеЧасти", "События", "Поля",
)


def _pair_key(rel: str) -> tuple[str, str, str]:
    """(directory, paired yaml file name, module file name): X.xbsl -> X.yaml,
    X.Объект.xbsl -> X.yaml."""
    parts = rel.replace("\\", "/").rsplit("/", 1)
    directory = parts[0] if len(parts) == 2 else ""
    stem = parts[-1]
    for suffix in (".Объект.xbsl", ".xbsl", ".yaml"):
        if stem.endswith(suffix):
            stem = stem[: -len(suffix)]
            break
    return directory, stem + ".yaml", parts[-1]


def _section_names(data: dict) -> set[str]:
    names: set[str] = set()
    for section in _FIELD_SECTIONS:
        items = data.get(section)
        if isinstance(items, list):
            for item in items:
                if isinstance(item, dict) and isinstance(item.get("Имя"), str):
                    names.add(item["Имя"])
    return names


def _base_type_root(data: dict) -> str | None:
    inherits = data.get("Наследует")
    base = inherits.get("Тип") if isinstance(inherits, dict) else None
    if not isinstance(base, str):
        return None
    return base.split("<", 1)[0].strip()


def _component_scope_facts(
    fact: dict, by_name: dict, type_members: dict, seen: set[str],
) -> set[str]:
    """The names a component gives its module: Свойства plus the base members up the chain.

    The base is either a platform type (members from type_members) or a project component
    (its sections and its base, recursively); an inheritance cycle is cut by `seen`.
    """
    names = set(fact["sections"])
    root = fact["base"]
    if not root or root in seen:
        return names
    seen.add(root)
    members = type_members.get(root)
    if members:
        names |= set(members.get("properties", ())) | set(members.get("methods", ()))
    parent = by_name.get(root)
    if parent is not None:
        names |= _component_scope_facts(parent, by_name, type_members, seen)
    return names


_static_cache: tuple[set[str] | None] | None = None


def _static_globals() -> set[str] | None:
    """The project-independent part of the global scope (stdlib + context globals)."""
    global _static_cache
    if _static_cache is None:
        stdlib = _stdlib_names()
        if not stdlib:
            _static_cache = (None,)  # without the stdlib catalog "unknown" cannot be proven
        else:
            try:
                catalog = dataset.load_json("stdlib.json")
            except dataset.DatasetError:
                catalog = None
            _static_cache = (
                None if catalog is None
                else set(stdlib) | set(catalog.get("globals", ())) | _IMPLICIT | _UNDOCUMENTED,
            )
    return _static_cache[0]


def _undef_mapper(source: SourceFile) -> dict | None:
    """The map phase. A yaml file contributes its slice of the project model (object
    name, sections, the Наследует base, the external-import flag). An xbsl file
    contributes candidates: names unknown both locally and to the static globals -
    the reduce subtracts the project names and the paired-yaml scope."""
    directory, pair_file, fname = _pair_key(source.rel)
    if source.kind == "yaml":
        fast_name = _object_name_fast(source)
        data, err = _parsed(source)
        if err is not None or not isinstance(data, dict):
            data = {}
        imports = data.get("Импорт")
        name = data.get("Имя")
        kind = data.get("ВидЭлемента")
        return {
            "k": "y",
            "dir": directory,
            "file": fname,
            "fast_name": fast_name,
            "name": name if isinstance(name, str) else None,
            "element_kind": kind if isinstance(kind, str) else None,
            "sections": sorted(_section_names(data)),
            "base": _base_type_root(data),
            "ext": isinstance(imports, list)
                   and any(isinstance(i, str) and "::" in i for i in imports),
        }
    if source.kind != "xbsl":
        return None
    static = _static_globals()
    if static is None:
        return None
    module, errors = P.parse(source)
    if errors:
        return None  # a broken file has its own diagnostics (code/parse-error)
    if any("::" in i.name for i in module.imports):
        # an import of an external namespace (a library): its contents are not
        # visible to the rule, any bare name may come from there - skip the file
        return None
    findings, hint_pool = _module_candidates(module, static)
    if not findings:
        return None
    lm = linemap(source)
    cands = [
        (*lm.linecol(offset), name, sign)
        for offset, name, sign in findings
    ]
    return {
        "k": "x",
        "dir": directory,
        "pair": pair_file,
        "obj": source.rel.endswith(".Объект.xbsl"),
        "cands": cands,
        "pool": hint_pool,
    }


def _module_candidates(
    module: P.Module, known_global: set[str],
) -> tuple[list[tuple[int, str, str]], list[str]]:
    """Names unknown to the module and to `known_global`, plus the module's hint pool.

    The last element of a candidate is the interpolation sign ("%"/"$") for a name found
    inside a string literal, and "" for an ordinary one - the reduce picks the message by it.

    The walk collects everything unknown to the LOCAL scopes; the big static set filters
    afterwards. Hints are NOT computed here: most survivors are project names the reduce
    resolves and drops, and difflib per raw candidate dominates the whole run on a real
    project - the reduce runs difflib against the returned pool for the true findings only.
    """
    module_names: set[str] = set()
    for m in module.members:
        if isinstance(m, (P.Method, P.Structure, P.Enum, P.ObjectField)):
            module_names.add(m.name)
    findings: list[tuple[int, str]] = []
    hint_pool: set[str] = set(module_names)
    for m in module.members:
        if isinstance(m, P.Method):
            scope = set(module_names) | {p.name for p in m.params}
            hint_pool.update(p.name for p in m.params)
            for p in m.params:
                if p.default is not None:
                    _walk_expr(p.default, scope, findings)
            _walk_body(m.body, set(scope), findings)
        elif isinstance(m, P.ObjectField) and m.init is not None:
            _walk_expr(m.init, set(module_names), findings)
        elif isinstance(m, (P.Structure, P.Enum)):
            inner = set(module_names) | {
                f.name for f in m.members if isinstance(f, P.ObjectField)
            } if isinstance(m, P.Structure) else set(module_names)
            hint_pool |= inner
            members = m.members if isinstance(m, P.Structure) else m.methods
            for sub in members:
                if isinstance(sub, P.Method):
                    sub_scope = set(inner) | {p.name for p in sub.params} | {"этот"}
                    hint_pool.update(p.name for p in sub.params)
                    _walk_body(sub.body, sub_scope, findings)
                elif isinstance(sub, P.ObjectField) and sub.init is not None:
                    _walk_expr(sub.init, set(inner), findings)
    if not findings:
        return [], []
    _collect_declared(module, hint_pool)
    out: list[tuple[int, str, str]] = [
        (offset, name, sign)
        for offset, name, sign in findings
        if name not in known_global
    ]
    if not out:
        return [], []
    return out, sorted(hint_pool)


def _collect_declared(module: P.Module, pool: set[str]) -> None:
    """All names declared in statement bodies (пер/знч/исп, loop and catch variables) -
    the hint pool for the survivors; scoping does not matter for a spelling hint."""

    def body(stmts: list[P.Stmt]) -> None:
        for st in stmts:
            if isinstance(st, P.VarDecl):
                pool.add(st.name)
            elif isinstance(st, P.If):
                for _cond, b in st.branches:
                    body(b)
                if st.else_body is not None:
                    body(st.else_body)
            elif isinstance(st, P.Case):
                for when in st.whens:
                    body(when.body)
                if st.else_body is not None:
                    body(st.else_body)
            elif isinstance(st, (P.While, P.Scope)):
                body(st.body)
            elif isinstance(st, (P.ForEach, P.ForTo)):
                pool.add(st.var)
                body(st.body)
            elif isinstance(st, P.Try):
                body(st.body)
                for var, _type, b in st.catches:
                    if var:
                        pool.add(var)
                    body(b)
                if st.finally_body is not None:
                    body(st.finally_body)

    for m in module.members:
        if isinstance(m, P.Method):
            body(m.body)
        elif isinstance(m, P.Structure):
            for sub in m.members:
                if isinstance(sub, P.Method):
                    body(sub.body)
        elif isinstance(m, P.Enum):
            for sub in m.methods:
                body(sub.body)


# On by default (severity error - the compiler rejects such code) since the stdlib
# catalog carries the global context (Сообщить, ПерейтиПоСсылке...) and the kind-manager
# methods: the whole real-world corpus (several real projects and the demo - 1600+ modules)
# runs with zero false findings. Map-reduce: the mappers run inside the file workers
# (the static globals filter most names there), the reduce below only knows the
# project-wide names and the paired-yaml scopes.
@rule(
    "code/undefined-name", "code/undefined-name.title", "D",
    scope="project", severity=Severity.ERROR, mapper=_undef_mapper,
)
def undefined_name(facts: dict[str, dict]) -> Iterable[Diagnostic]:
    if _static_globals() is None:
        return
    try:
        catalog = dataset.load_json("stdlib.json")
    except dataset.DatasetError:
        return
    type_members = catalog.get("type_members", {})
    object_members = catalog.get("object_members", {})
    manager_members = catalog.get("manager_members", {})

    # The project model from the yaml facts: names, the (directory, file) map for the
    # module pairing, the by-name map for the Наследует chain of interface components.
    project_names: set[str] = set()
    by_dir: dict[tuple[str, str], dict] = {}
    by_name: dict[str, dict] = {}
    for fact in facts.values():
        if fact["k"] != "y":
            continue
        if fact["fast_name"]:
            project_names.add(fact["fast_name"])
        by_dir[(fact["dir"], fact["file"])] = fact
        if fact["name"]:
            by_name[fact["name"]] = fact

    for rel, fact in facts.items():
        if fact["k"] != "x":
            continue
        pair = by_dir.get((fact["dir"], fact["pair"]))
        extras: set[str] = set()
        if pair is not None:
            if pair["ext"]:
                continue  # an external namespace in the yaml Импорт - the same blind spot
            kind = pair["element_kind"]
            if fact["obj"]:
                # an entity module: the attributes plus the standard fields and write methods
                extras = set(pair["sections"]) | _ENTITY_COMMON
            elif kind == "КомпонентИнтерфейса":
                extras = _component_scope_facts(pair, by_name, type_members, set())
            else:
                # a data-kind manager module / common module: the yaml fields plus the manager members
                extras = set(pair["sections"])
                extras |= set(object_members.get(kind, ()))
                extras |= set(manager_members.get(kind, ()))
        for line, col, name, sign in fact["cands"]:
            if name in project_names or name in extras:
                continue
            if sign:
                # Inside a string the fix is usually the escape, not a declaration - the
                # spelling hint would send the reader the wrong way.
                message = i18n.t("code/undefined-name.found-interp", name=name, sign=sign)
            else:
                # difflib runs only for a true finding: the module's own pool first
                # (a local typo), then the project-wide names.
                hint = _closest(name, fact.get("pool") or ())
                if hint is None:
                    hint = _closest(name, project_names | extras)
                message = (
                    i18n.t("code/undefined-name.found-hint", name=name, hint=hint)
                    if hint else i18n.t("code/undefined-name.found", name=name)
                )
            yield Diagnostic(rel, line, col, "code/undefined-name", Severity.ERROR, message)


def _walk_body(stmts: list[P.Stmt], scope: set[str], findings: list) -> None:
    """A block body: statements in order, a declaration introduces its name AFTER its expression."""
    for st in stmts:
        if isinstance(st, P.VarDecl):
            if st.init is not None:
                _walk_expr(st.init, scope, findings)
            scope.add(st.name)
        elif isinstance(st, P.Assign):
            _walk_expr(st.target, scope, findings)
            if st.value is not None:
                _walk_expr(st.value, scope, findings)
        elif isinstance(st, P.ExprStmt):
            _walk_expr(st.expr, scope, findings)
        elif isinstance(st, P.UseStmt):
            _walk_expr(st.expr, scope, findings)
        elif isinstance(st, P.If):
            for cond, body in st.branches:
                _walk_expr(cond, scope, findings)
                _walk_body(body, set(scope), findings)
            if st.else_body is not None:
                _walk_body(st.else_body, set(scope), findings)
        elif isinstance(st, P.Case):
            if st.subject is not None:
                _walk_expr(st.subject, scope, findings)
            for when in st.whens:
                for cond in when.conditions:
                    _walk_expr(cond, scope, findings)
                _walk_body(when.body, set(scope), findings)
            if st.else_body is not None:
                _walk_body(st.else_body, set(scope), findings)
        elif isinstance(st, P.While):
            _walk_expr(st.cond, scope, findings)
            _walk_body(st.body, set(scope), findings)
        elif isinstance(st, P.ForEach):
            _walk_expr(st.source, scope, findings)
            inner = set(scope)
            inner.add(st.var)
            _walk_body(st.body, inner, findings)
        elif isinstance(st, P.ForTo):
            _walk_expr(st.start_expr, scope, findings)
            _walk_expr(st.to, scope, findings)
            if st.step is not None:
                _walk_expr(st.step, scope, findings)
            inner = set(scope)
            inner.add(st.var)
            _walk_body(st.body, inner, findings)
        elif isinstance(st, P.Try):
            _walk_body(st.body, set(scope), findings)
            for var, _type, body in st.catches:
                inner = set(scope)
                if var:
                    inner.add(var)
                _walk_body(body, inner, findings)
            if st.finally_body is not None:
                _walk_body(st.finally_body, set(scope), findings)
        elif isinstance(st, P.Scope):
            _walk_body(st.body, set(scope), findings)
        elif isinstance(st, P.Return):
            if st.value is not None:
                _walk_expr(st.value, scope, findings)


_SIGN_RE = re.compile(r"[%$]")


def _interpolations(raw: str) -> list[tuple[int, str, str]]:
    """Short interpolations of a string literal: (offset inside the literal, sign, name).

    The full form (`%{...}` / `${...}`) is skipped whole with the lexer's balancing - nested
    strings and collection literals live inside it. A sign after a backslash is an escaped
    character (`\\$`), and so is a sign followed by anything that cannot start an identifier
    (`100% готово`, `$<число>` of a regex replacement) - both per the platform docs.
    """
    if "%" not in raw and "$" not in raw:
        return []  # the common case: character-by-character scanning of long HTML literals costs
    out: list[tuple[int, str, str]] = []
    pos = 0
    while True:
        found = _SIGN_RE.search(raw, pos)
        if found is None:
            return out
        i = found.start()
        backslashes = i
        while backslashes > 0 and raw[backslashes - 1] == "\\":
            backslashes -= 1
        if (i - backslashes) % 2:  # an odd run of backslashes escapes the sign
            pos = i + 1
            continue
        if raw[i + 1: i + 2] == "{":
            pos = _skip_interpolation(raw, i + 2)
            continue
        ident = _IDENT_RE.match(raw, i + 1)
        if ident is None:
            pos = i + 1
            continue
        out.append((i, found.group(0), ident.group(0)))
        pos = ident.end()


def _walk_expr(expr: P.Expr | None, scope: set[str], findings: list) -> None:
    if expr is None:
        return
    if isinstance(expr, P.Literal):
        # A name can be spelled inside a string: only the short interpolation form is read,
        # and the sign travels with the finding so the message can offer the escape.
        if expr.kind == "STRING":
            for offset, sign, name in _interpolations(expr.text):
                if name not in scope:
                    findings.append((expr.start + offset, name, sign))
        return
    if isinstance(expr, P.Name):
        # Qualified roots (Подсистема::Имя) are not checked: the contents of foreign
        # namespaces are not visible to this rule. No hints here: the walk sees many
        # names that later turn out known (project objects), and difflib per candidate
        # would dominate the run - hints are computed after the static filter.
        if "::" not in expr.name and expr.name and expr.name not in scope:
            findings.append((expr.start, expr.name, ""))
        return
    if isinstance(expr, P.Member):
        _walk_expr(expr.obj, scope, findings)  # the member name is a type-inference stage
        return
    if isinstance(expr, P.Call):
        _walk_expr(expr.callee, scope, findings)
        for arg in expr.args:
            _walk_expr(arg.value, scope, findings)
        return
    if isinstance(expr, P.Lambda):
        if expr.body_expr is not None or expr.body_stmts is not None:
            inner = set(scope) | {p.name for p in expr.params}
            if isinstance(expr.body_expr, P.Expr):
                _walk_expr(expr.body_expr, inner, findings)
            if expr.body_stmts is not None:
                _walk_body(expr.body_stmts, inner, findings)
        return
    if isinstance(expr, P.Index):
        _walk_expr(expr.obj, scope, findings)
        _walk_expr(expr.index, scope, findings)
        return
    if isinstance(expr, P.Binary):
        _walk_expr(expr.left, scope, findings)
        _walk_expr(expr.right, scope, findings)
        return
    if isinstance(expr, P.Compare):
        _walk_expr(expr.first, scope, findings)
        for _op, right in expr.rest:
            _walk_expr(right, scope, findings)
        return
    if isinstance(expr, P.Unary):
        _walk_expr(expr.operand, scope, findings)
        return
    if isinstance(expr, (P.IsType, P.AsType)):
        _walk_expr(expr.operand, scope, findings)
        return
    if isinstance(expr, P.Ternary):
        _walk_expr(expr.cond, scope, findings)
        _walk_expr(expr.then, scope, findings)
        _walk_expr(expr.otherwise, scope, findings)
        return
    if isinstance(expr, P.Coalesce):
        _walk_expr(expr.left, scope, findings)
        _walk_expr(expr.right, scope, findings)
        return
    if isinstance(expr, P.NonNull):
        _walk_expr(expr.operand, scope, findings)
        return
    if isinstance(expr, P.New):
        if expr.args:
            for arg in expr.args:
                _walk_expr(arg.value, scope, findings)
        return
    if isinstance(expr, P.ArrayLit):
        for item in expr.items:
            _walk_expr(item, scope, findings)
        return
    if isinstance(expr, P.MapLit):
        for key, value in expr.entries:
            _walk_expr(key, scope, findings)
            _walk_expr(value, scope, findings)
        return
    if isinstance(expr, P.Throw):
        _walk_expr(expr.value, scope, findings)
        return
    # Literal, This, GlobalAccess, MethodRef are atoms (method references - stage 3)


def _closest(name: str, scope: Iterable[str]) -> str | None:
    hits = difflib.get_close_matches(name, scope, n=1, cutoff=0.75)
    return hits[0] if hits else None
