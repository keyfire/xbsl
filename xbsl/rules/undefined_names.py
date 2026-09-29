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
- the module of a tabular-section row type (`Товары.Позиции.xbsl`) has the scope of the row:
  the attributes the section declares in the yaml of its owner and what every structure type
  has, never the attributes of the owner itself (see _row_owner); a method of the structure
  type answers only as the callee of a call (see _row_type_scope). The module of a `Structure`
  element and the object module of an entity (`Товары.Объект.xbsl`) split their type the same
  way: its properties are read bare, its methods (`Write`, `IsNew`) only called.

A spelling hint is the closest name of the whole scope - the module, the element, the project
and the global names compete, and a tie goes to the nearer group. A call is offered what can be
called, a bare name what holds a value, and a short name only a candidate one edit away (see
_ScopeHints and _SHORT_NAME).

Only the ROOT of a member chain is checked (`Х` in `Х.Поле[0].Метод()`): member names need
type inference (stage 3). Qualified roots (`Подсистема::Имя`) and method references are
skipped. Roots the file's module kind provides implicitly (`Компоненты` of a form module,
`Это`/`До` of an object module etc.) are collected in _IMPLICIT.

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
from collections.abc import Callable, Iterable
from functools import lru_cache

from xbsl import dataset, i18n, metamodel, parser as P, terms
from xbsl.diagnostics import Diagnostic, Severity
from xbsl.engine import SourceFile, rule
from xbsl.lexer import _IDENT_RE, _skip_interpolation, linemap
from xbsl.rules._syntax import OBJECT_MODULE_SUFFIXES, element_pair_stem
from xbsl.rules.semantics import _object_name_fast, _parsed, _stdlib_names
from xbsl.rules.yaml_schema import element_own_names, object_kind, value_of

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
    "code/undefined-name.found-method": {
        "ru": "Имя '{name}' – метод, а не значение: без скобок компилятор его не находит. "
              "Вызовите: '{name}()'.",
        "en": "Name '{name}' is a method, not a value: without the parentheses the compiler "
              "does not find it. Call it: '{name}()'.",
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

# Context roots the module kind itself provides (never declared in code), from the
# documentation of the module kinds.
_IMPLICIT = frozenset({
    "Компоненты", "Components",   # an interface-component module: access to the named form components
    # The record BEFORE the change, in the BeforeWrite handler of an object module. Its twin
    # (the record AFTER) was an assumption: the compiler refused that name outright, and the
    # control line of the same module errored too - so the module did compile.
    "До",
    "Сущность",     # the rights namespace in permission handlers (Сущность.Право.Чтение)
})

# Members that exist on the platform but are absent from the distribution docs.
# Kept deliberately tiny. English spellings are NOT listed: _both_spellings derives them from
# the compiler dictionary, the same way it does for the documented members.
_UNDOCUMENTED = frozenset({
    "СобственнаяМодифицированность",  # a form-component property
})
# `ВыполнитьЗаписать` and `ВыполнитьЗаписатьИЗакрыть` used to sit here as "commands of
# ObjectForm". They are nothing of the sort: the compiler answers `Unknown method` to
# both (checked by compiling them), and no type of any shipped dataset declares such a
# member. A
# form's built-in command is a PROPERTY of the form (WriteAndClose of type Command),
# and running it is `WriteAndClose.Execute()`. What carried those names was the
# author's own handler method, declared in the form module - so the rule sees it declared
# and needs no exception. Whitelisting them silenced this very rule on code that cannot
# compile, which is how the demo project kept two such calls unnoticed.

# Only what the COMPILER confirmed on a probe stand (tools/verify_claims.py): these four are
# available by bare name in an entity module with nothing declared for them.
#
# The table used to be four times longer, and the extra names were an assumption nobody had
# checked. The probe settled every one of them:
#
# - the standard attributes (Name and Code of a catalog, Number and Date of a document) work
#   ONLY when the yaml declares them - a standard attribute is an entry of the attributes
#   section with a name and no type. Declared, they reach the module through the paired yaml
#   like any other attribute, which the rule reads itself, so the table has nothing to add;
# - IsNew, DataLoadingMode, MarkForDeletion and ClearDeletionMark do not exist at all -
#   neither bare, nor on `this`, nor on the reference;
# - Period of a register record is a property of its DATA type (the before-record parameter),
#   not a name of the module; RecordKind and Recorder are not there either.
#
# Every one of those spellings compiled into an error, and the control line of each module
# errored too - so the answers were not the silence of an uncompiled module.
#
# The table is now the FALLBACK rather than the whole answer: the documentation describes the
# object type of every kind on a template page of its own, and the extractor keeps those
# members under `generated_members`. A dataset that carries the section answers for the kind at
# hand - the members of a catalog object are not those of a settings storage - and this table
# covers what it does not: an older dataset, and a kind whose object type the help omits.
#
# The probe and the documentation seemed to disagree on one name: the probe read IsNew as
# absent, while the help lists `IsNew` among the methods of the object type and a product in
# production calls it by a bare name. A later probe reconciled them - a method of the object
# type answers only to a CALL. Read as a value, `IsNew`, `CreateCopy`, `Write` and `Delete` all
# got "Variable ... is not defined", while `Write()` compiled and the properties
# (`Reference`, `DeletionMark`, `Presentation`) were read bare. So the methods go to the calls
# of the scope (_ENTITY_CALLS below, and the methods of the generated object type).
_ENTITY_COMMON = frozenset({
    "Ссылка", "ПометкаУдаления", "Записать", "Удалить",
})
#: The names of _ENTITY_COMMON that are methods: they answer only as the callee of a call.
_ENTITY_CALLS = frozenset({"Записать", "Удалить"})

#: The tail of the generated type an object module belongs to: `<Имя>.Объект.xbsl` is the
#: module of `<Имя>.Объект`, so its members sit under `<вид>.Объект` in generated_members.
_OBJECT_FACET = "Объект"

#: Both spellings of a boolean, as a yaml may carry it: the loader reads `True`/`true` as the
#: python value, a Russian file writes the word, and the metamodel writes its defaults in the
#: lower-case English form.
_TRUE_FORMS = frozenset({"Истина", "True", "true"})
_FALSE_FORMS = frozenset({"Ложь", "False", "false"})

#: The two module scopes a conditional row speaks about: the object module of an element
#: (`<Имя>.Объект.xbsl`, names from `<вид>.Объект`) and its manager module (`<Имя>.xbsl`, names
#: from `manager_members` of the kind). One setting can decide in both.
_OBJECT_SCOPE = "obj"
_MANAGER_SCOPE = "manager"

#: Names the platform gives to SOME elements of a kind only. The template pages the data is
#: read from describe ONE example element, and everything switched on in that example reaches
#: the data as the contract of the whole kind - so the help has to be read for each of them and
#: the element's own yaml asked.
#:
#: A row is (the property that decides, the value that switches the names ON, the names of the
#: object module, the names of the manager module). The kinds a row speaks for are the kinds
#: whose metamodel record declares that property, so no row carries a list of its own:
#: `Recompute` reaches an access key, which has `ManualGrant`, and leaves a privilege alone,
#: which recomputes too but has no such property. A kind that declares nothing of the sort is
#: not judged at all - a settings storage keeps every name it had.
_CONDITIONAL_MEMBERS = (
    # "Появляется только у иерархических справочников" - xbql/Std/CatalogName, which spells
    # out which ones: "справочник с установленным значением Истина для свойства Иерархический".
    # The default is `False`, so without the gate the name would be waved through on most
    # catalogs of a project.
    ("Иерархический", "Истина", ("Родитель",), ()),
    # "Поле присутствует только у справочников с режимом удаления ПометкаУдаления" - the same
    # sentence for both fields on the catalog, document and exchange-plan pages of xbql. The
    # `DeletionMark` of the fallback table above is the same fact and rides along.
    ("РежимУдаления", "ПометкаУдаления", ("МоментПометкиУдаления", "ПометкаУдаления"), ()),
    # An access key is granted by hand or computed, and the help keeps the two apart as two
    # types: `GrantableAccessKey` revokes, `ComputableAccessKey` recomputes, and so do their
    # instances. In yaml it is ONE kind, so both template pages fold into `КлючДоступа.Объект`
    # and into the manager members of the kind, and each flavour ends up carrying the methods
    # of the other. A probe on a stand measured all four corners: to the name of the other
    # flavour the compiler answers `Unknown method`, in either module. Which flavour a key is,
    # the help says nowhere - the probe settled that too, and the answer is this property and
    # nothing else.
    ("РучнаяВыдача", "Истина", ("Выдать", "Отозвать"), ("ОтозватьКлючи",)),
    ("РучнаяВыдача", "Ложь", ("Пересчитать",), ("ПересчитатьКлючи",)),
)


@lru_cache(maxsize=None)
def _on_forms(value: str) -> frozenset[str]:
    """Every spelling of the value that switches a row on.

    A boolean is spelled three ways at once; an enumeration value takes its English form from
    the term dictionary, so an English project is judged by the same row.
    """
    if value in _TRUE_FORMS:
        return _TRUE_FORMS
    if value in _FALSE_FORMS:
        return _FALSE_FORMS
    english = terms.english(value, "enums") or terms.common_english(value)
    return frozenset({value} | ({english} if english else set()))


dataset.register_reset(_on_forms.cache_clear)


def _withheld_members(data: dict, kind: str | None) -> dict[str, list[str]]:
    """Names THIS element's own settings do not give it, per module scope.

    Silence is the answer wherever nothing is settled: a kind without the property, a value the
    file spells in a way nothing recognises. Widening a scope costs a missed finding, narrowing
    it wrongly costs an error on code that compiles - and that is the defect being repaired.

    The branch that falls back on the default of the property is sound but rarely walked: under
    the current compatibility mode an access key that names no `ManualGrant` does not apply at
    all, and that refusal is a finding of another rule. Only a project held to an older mode
    reaches the default.
    """
    withheld: dict[str, set[str]] = {_OBJECT_SCOPE: set(), _MANAGER_SCOPE: set()}
    props = metamodel.properties(kind) if kind else {}
    for prop, on_value, own, manager in _CONDITIONAL_MEMBERS:
        record = props.get(prop)
        if not record:
            continue  # the kind has no such setting - nothing to judge by
        written = value_of(data, prop, kind)
        if written is None:
            written = record.get("default")
        if written is True:
            written = "Истина"
        elif written is False:
            written = "Ложь"
        if isinstance(written, str) and written not in _on_forms(on_value):
            withheld[_OBJECT_SCOPE].update(own)
            withheld[_MANAGER_SCOPE].update(manager)
    return {scope: sorted(names) for scope, names in withheld.items()}


# The yaml sections whose items become bare names in the object modules.
_FIELD_SECTIONS = (
    "Реквизиты", "Измерения", "Ресурсы", "Константы", "Свойства", "Параметры",
    "ТабличныеЧасти", "События", "Поля",
)


def _pair_key(rel: str) -> tuple[str, str, str]:
    """(directory, paired yaml file name, module file name): X.xbsl -> X.yaml,
    X.Объект.xbsl / X.Object.xbsl -> X.yaml."""
    parts = rel.replace("\\", "/").rsplit("/", 1)
    directory = parts[0] if len(parts) == 2 else ""
    return directory, element_pair_stem(parts[-1]) + ".yaml", parts[-1]


#: The kind whose module a row module is scoped like, beyond the fields. The help page on
#: tabular sections calls the row type of a section a structure type, and the catalog gives
#: every structure type the same members (`ToString`, `GetType`, `Presentation`).
#:
#: The standard fields the same page names - `Owner`, `Index`, `LineNumber`, and the
#: container of the stored row - are not added: the page gives them to the TABLES of a section,
#: the table of the query language and the one in the database, and the compiler dictionary
#: files them under the view of that table, not under a type of the code. A row built by
#: `new` is not in any section yet, so it has no number to answer with. The probe agrees: in
#: the module of a row all three got "Variable ... is not defined".
_ROW_TYPE_KIND = "Структура"


def _row_type_scope(object_members: dict, manager_members: dict) -> tuple[set[str], set[str]]:
    """What a row module sees of its structure type: (names read bare, methods called).

    A method of the type answers only in the position of a call. The probe compiled a row
    module with each name on a line of its own: `Presentation()` and `ToString()` passed, and
    a bare `Presentation` got "Variable ... is not defined" - the compiler looks a bare name up
    among the values, and a method is not one.

    Data generated before the manager members were split into properties and methods cannot
    tell the two apart. There every member stays a bare name, as before: narrowing blindly
    would cost errors on code that compiles, widening only a missed finding.

    The module of a `Structure` element gets the same split: a probe compiled such a module
    with a bare `Presentation`, `ToString` and `GetType` and got "Variable ... is not defined"
    for each, while the calls compiled.
    """
    entry = manager_members.get(_ROW_TYPE_KIND)
    names = set(object_members.get(_ROW_TYPE_KIND, ()))
    calls: set[str] = set()
    if isinstance(entry, dict):
        for member_kind in dataset.MEMBER_KINDS:
            (calls if member_kind == "methods" else names).update(entry.get(member_kind) or ())
    else:
        names.update(dataset.manager_member_names(entry))
    return _both_spellings(names), _both_spellings(calls)


def _row_attributes(data) -> dict[str, list[str]]:
    """The attributes of every tabular section of the element, by the name of the section.

    A section generates the row type `<element>.<section>`, and the module of that type sees
    the attributes of its section by bare name, the way an object module sees the attributes
    of its element. The keys are read in either spelling (`TabularParts`, `Attributes`).
    """
    rows: dict[str, list[str]] = {}
    sections = value_of(data, "ТабличныеЧасти")
    if not isinstance(sections, list):
        return rows
    for section in sections:
        name = value_of(section, "Имя")
        if not isinstance(name, str):
            continue
        attributes = value_of(section, "Реквизиты")
        rows[name] = sorted(
            value_of(item, "Имя") for item in attributes
            if isinstance(value_of(item, "Имя"), str)
        ) if isinstance(attributes, list) else []
    return rows


def _row_candidate(fname: str) -> list[str] | None:
    """[owner yaml file, tail] for a module named after an element and a tail, else None.

    `Товары.Позиции.xbsl` is the module of the row type of the section `Позиции` of `Товары`
    only when the yaml of `Товары` declares that section, and only the reduce sees that yaml.
    The tail is not matched against the types an element generates: a catalog may well call a
    section by a word that is a generated type of another kind, and the declaration decides.
    """
    owner, _, tail = fname[: -len(".xbsl")].rpartition(".")
    return [owner + ".yaml", tail] if owner and tail else None


def _row_owner(fact: dict, by_dir: dict[tuple[str, str], dict]) -> dict | None:
    """The yaml fact of the element whose tabular-section row type the module extends.

    The module of a row type is named after the element and the section, and it is one when
    the yaml of the element declares that section. The help page on tabular sections says the
    type may have a module, and a probe compiled one: the attributes of the row resolved by
    bare name, the methods became members of the row type.

    An owner that does not read answers for every module named after it: whether the tail is a
    section or a type the element generates is unknown, so the module is left unjudged, the way
    the modules of the element's own pair are, rather than judged as an orphan with no scope.
    """
    row = fact.get("row")
    if not row:
        return None
    owner = by_dir.get((fact["dir"], row[0]))
    if owner is None:
        return None
    return owner if owner["bad"] or row[1] in owner["rows"] else None


def _base_type_root(data: dict) -> str | None:
    # Both keys are read through value_of: an English project spells the section `Inherits`,
    # and a raw `data["Наследует"]` simply found nothing there - the base type went
    # unresolved, its members never reached the module scope, and every bare member name in
    # an English form module was reported as undefined.
    inherits = value_of(data, "Наследует")
    base = value_of(inherits, "Тип") if isinstance(inherits, dict) else None
    if not isinstance(base, str):
        return None
    return base.split("<", 1)[0].strip()


def _both_spellings(names: set[str]) -> set[str]:
    """The names plus their English spellings where the platform declares one.

    The member catalogue is extracted from the documentation, and the documentation is
    Russian only - so a form's WriteAndClose arrives Russian even though an English
    project spells the very same property `WriteAndClose` and the compiler accepts it. The
    pairs come from the compiler dictionary; a member it does not pair stays as it is.

    A name the compiler dictionary leaves unpaired is asked of the property vocabulary as
    well: `Ссылка` is the only word of the entity protocol the dictionary does not carry,
    and terms.json names it `Link` in that role. Only ever WIDENS a scope, so a pairing that
    misses costs a false negative, never a false positive.
    """
    out = set(names)
    for name in names:
        english = terms.common_english(name) or terms.english(name, "properties")
        if english:
            out.add(english)
        # The entity protocol speaks the FACET language, where the same word means something
        # else than as a property: an object module's built-in reference is `Reference`,
        # while the property vocabulary calls that word `Link`. Both spellings are added -
        # widening a scope can only cost a false negative, never a false positive.
        facet = terms.facet_suffix_english(name)
        if facet:
            out.add(facet)
    return out


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
        names |= _both_spellings(
            set(members.get("properties", ())) | set(members.get("methods", ()))
        )
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
                else set(stdlib) | set(catalog.get("globals", ()))
                | _both_spellings(set(_IMPLICIT) | set(_UNDOCUMENTED)),
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
        kind = object_kind(data)
        imports = value_of(data, "Импорт", kind)
        name = value_of(data, "Имя", kind)
        return {
            "k": "y",
            # The file did not parse: what it declares stays unknown, and a module judged
            # against an EMPTY scope drowns in phantom names - see yaml_schema.unreadable_object.
            "bad": err is not None,
            "dir": directory,
            "file": fname,
            "fast_name": fast_name,
            "name": name if isinstance(name, str) else None,
            "element_kind": kind if isinstance(kind, str) else None,
            "sections": sorted(element_own_names(data)),
            # The scope of the row modules of the element: the attributes of each section.
            "rows": _row_attributes(data),
            # Names of the kind that this element's own settings switch off, per module
            # scope - a catalog that is not hierarchical has no `Parent`. Read here, where
            # the parsed yaml is at hand, and subtracted where each scope is built.
            "withheld": _withheld_members(data, kind),
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
    methods = {m.name for m in module.members if isinstance(m, P.Method)}
    values, callables = _declared_values(module)
    lm = linemap(source)
    cands = [
        (*lm.linecol(offset), name, sign, call)
        for offset, name, sign, call in findings
    ]
    obj = source.rel.endswith(OBJECT_MODULE_SUFFIXES)
    return {
        "k": "x",
        "dir": directory,
        "pair": pair_file,
        "obj": obj,
        # A module that may extend the row type of a tabular section (see _row_owner).
        "row": None if obj else _row_candidate(fname),
        "cands": cands,
        # The hint for a bare name is looked for among the values of the module, the hint for a
        # call among what it can call: its methods and the values that hold a function (see
        # _ScopeHints). A name can be both: a method `Контракт` returns what its callers keep in
        # a variable `Контракт`.
        "pool": [name for name in hint_pool if name not in methods or name in values],
        "callables": sorted(methods | callables),
    }


def _module_candidates(
    module: P.Module, known_global: set[str],
) -> tuple[list[tuple[int, str, str, bool]], list[str]]:
    """Names unknown to the module and to `known_global`, plus the module's hint pool.

    A candidate is (offset, name, sign, call). The sign is the interpolation sign ("%"/"$")
    for a name found inside a string literal, and "" for an ordinary one - the reduce picks the
    message by it. `call` marks the callee of a call, the one position where a method of the
    scope may stand by its bare name.

    The walk collects everything unknown to the LOCAL scopes; the big static set filters
    afterwards. Hints are NOT computed here: most survivors are project names the reduce
    resolves and drops, and difflib per raw candidate dominates the whole run on a real
    project - the reduce runs difflib against the returned pool for the true findings only.
    """
    module_names: set[str] = set()
    for m in module.members:
        if isinstance(m, (P.Method, P.Structure, P.Enum, P.ObjectField)):
            module_names.add(m.name)
    findings: list[tuple[int, str, str, bool]] = []
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
    out = [finding for finding in findings if finding[1] not in known_global]
    if not out:
        return [], []
    return out, sorted(hint_pool)


def _collect_declared(module: P.Module, pool: set[str], callables: set[str] | None = None) -> None:
    """All names declared in statement bodies (пер/знч/исп, loop and catch variables) -
    the hint pool for the survivors; scoping does not matter for a spelling hint. `callables`
    also receives the variables that hold a function (_holds_callable)."""

    def body(stmts: list[P.Stmt]) -> None:
        for st in stmts:
            if isinstance(st, P.VarDecl):
                pool.add(st.name)
                if callables is not None and _holds_callable(st.type, st.init):
                    callables.add(st.name)
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


def _holds_callable(type_: P.TypeRef | None, init: P.Expr | None = None) -> bool:
    """A value that is called like a method: of a function type (`Проверка: (Строка)->Булево`),
    or set to a lambda or a method reference."""
    return (type_ is not None and "->" in type_.text) or isinstance(init, (P.Lambda, P.MethodRef))


def _declared_values(module: P.Module) -> tuple[set[str], set[str]]:
    """(values, callables): the names a module declares as values - its fields, structures and
    enumerations, the fields of its structures, the parameters of every method and what the
    bodies declare - and those of them that hold a function (_holds_callable)."""
    names = {m.name for m in module.members if isinstance(m, (P.Structure, P.Enum, P.ObjectField))}
    callables = {m.name for m in module.members
                 if isinstance(m, P.ObjectField) and _holds_callable(m.type, m.init)}
    methods: list[P.Method] = []
    for m in module.members:
        if isinstance(m, P.Method):
            methods.append(m)
        elif isinstance(m, P.Structure):
            for sub in m.members:
                if isinstance(sub, P.ObjectField):
                    names.add(sub.name)
                    if _holds_callable(sub.type, sub.init):
                        callables.add(sub.name)
                elif isinstance(sub, P.Method):
                    methods.append(sub)
        elif isinstance(m, P.Enum):
            methods.extend(m.methods)
    for method in methods:
        names.update(p.name for p in method.params)
        callables.update(p.name for p in method.params if _holds_callable(p.type))
    _collect_declared(module, names, callables)
    return names, callables


# On by default (severity error - the compiler rejects such code) since the stdlib
# catalog carries the global context (Сообщить, ПерейтиПоСсылке...) and the kind-manager
# methods. Map-reduce: the mappers run inside the file workers
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
    generated_members = catalog.get("generated_members", {})
    # What a row module sees beyond the attributes of its section (see _row_type_scope).
    row_names, row_calls = _row_type_scope(object_members, manager_members)

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

    hints = _Hints(project_names)
    for rel, fact in facts.items():
        if fact["k"] != "x":
            continue
        pair = by_dir.get((fact["dir"], fact["pair"]))
        owner = _row_owner(fact, by_dir) if pair is None else None
        extras: set[str] = set()
        # Names of the scope that answer only as the callee of a call.
        calls: set[str] = set()
        if owner is not None:
            if owner["bad"] or owner["ext"]:
                continue  # the blind spots of an element's own pair hold for its rows too
            # The attributes of the section and the members of a structure type. The attributes
            # of the owner stay out: the row is a type of its own, and they are not its fields.
            extras = set(owner["rows"][fact["row"][1]]) | row_names
            calls = row_calls
        elif pair is not None:
            if pair["bad"]:
                continue  # the pair is unreadable: its own yaml/valid is the finding to read
            if pair["ext"]:
                continue  # an external namespace in the yaml Импорт - the same blind spot
            kind = pair["element_kind"]
            if fact["obj"]:
                # An entity module: the attributes of the object, plus what the platform gives
                # the object type of this kind (the template page of `<вид>.Объект`), plus the
                # probe-confirmed table for a dataset or a kind the pages say nothing about.
                # A method of the type answers only to a call (see _ENTITY_COMMON); a name the
                # type has both ways (`Presentation`) stays a value.
                given = generated_members.get(f"{kind}.{_OBJECT_FACET}") or {}
                values = set(_ENTITY_COMMON - _ENTITY_CALLS) | set(given.get("properties", ()))
                methods = (set(_ENTITY_CALLS) | set(given.get("methods", ()))) - values
                # Withheld BEFORE the spellings are added, or the English form of a name the
                # element does not have would stay in scope on its own.
                withheld = set(pair["withheld"][_OBJECT_SCOPE])
                extras = set(pair["sections"]) | _both_spellings(values - withheld)
                calls = _both_spellings(methods - withheld)
            elif kind == "КомпонентИнтерфейса":
                extras = _component_scope_facts(pair, by_name, type_members, set())
            elif kind == _ROW_TYPE_KIND:
                # The module of a structure element extends the same structure type as the
                # module of a row, and the probe answered the same there: `Presentation()`
                # compiled, a bare `Presentation`, `ToString` and `GetType` got "Variable
                # ... is not defined". The fields of the element are values.
                extras = set(pair["sections"]) | row_names
                calls = row_calls
            else:
                # A manager module of a data kind, or a common module: the yaml fields plus the
                # manager members, less what this element's settings switch off - the manager of
                # an access key carries the methods of BOTH flavours, as its object type did.
                names = (set(object_members.get(kind, ()))
                         | set(dataset.manager_member_names(manager_members.get(kind))))
                extras = set(pair["sections"]) | _both_spellings(
                    names - set(pair["withheld"][_MANAGER_SCOPE]))
        # What the yaml declares is offered to either position: an attribute is a value, while
        # an event of a component is raised by a call (see _ScopeHints).
        declared = (set(owner["rows"][fact["row"][1]]) if owner is not None
                    else set(pair["sections"]) if pair is not None else set())
        scope = hints.module(fact.get("pool") or (), fact.get("callables") or (), extras, calls,
                             declared)
        for line, col, name, sign, call in fact["cands"]:
            if name in project_names or name in extras or call and name in calls:
                continue
            if sign:
                # Inside a string the fix is usually the escape, not a declaration - the
                # spelling hint would send the reader the wrong way.
                message = i18n.t("code/undefined-name.found-interp", name=name, sign=sign)
            elif name in calls:
                # The name is right and the parentheses are missing: a spelling hint would
                # offer the very same name.
                message = i18n.t("code/undefined-name.found-method", name=name)
            else:
                # difflib runs only for a true finding, over the whole scope at once.
                hint = scope.closest(name, call)
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


def _walk_name(expr: P.Name, scope: set[str], findings: list, call: bool) -> None:
    # Qualified roots (`Subsystem::Name`) are not checked: the contents of foreign namespaces
    # are not visible to this rule. No hints here: the walk sees many names that later turn
    # out known (project objects), and difflib per candidate would dominate the run - hints
    # are computed after the static filter.
    if "::" not in expr.name and expr.name and expr.name not in scope:
        findings.append((expr.start, expr.name, "", call))


def _walk_expr(expr: P.Expr | None, scope: set[str], findings: list) -> None:
    if expr is None:
        return
    if isinstance(expr, P.Literal):
        # A name can be spelled inside a string: only the short interpolation form is read,
        # and the sign travels with the finding so the message can offer the escape.
        if expr.kind == "STRING":
            for offset, sign, name in _interpolations(expr.text):
                if name not in scope:
                    findings.append((expr.start + offset, name, sign, False))
        return
    if isinstance(expr, P.Name):
        _walk_name(expr, scope, findings, call=False)
        return
    if isinstance(expr, P.Member):
        _walk_expr(expr.obj, scope, findings)  # the member name is a type-inference stage
        return
    if isinstance(expr, P.Call):
        # The callee of a call is marked: a method of the scope answers there and only there
        # (see _row_type_scope), while a bare name is looked up among the values.
        if isinstance(expr.callee, P.Name):
            _walk_name(expr.callee, scope, findings, call=True)
        else:
            _walk_expr(expr.callee, scope, findings)
        for arg in expr.args:
            _walk_expr(arg.value, scope, findings)
        return
    if isinstance(expr, P.Lambda):
        if expr.body_expr is not None or expr.body_stmts is not None:
            inner = set(scope) | {p.name for p in expr.params}
            if isinstance(expr.body_expr, P.Expr):
                _walk_expr(expr.body_expr, inner, findings)
            elif isinstance(expr.body_expr, P.Assign):
                _walk_expr(expr.body_expr.target, inner, findings)
                _walk_expr(expr.body_expr.value, inner, findings)
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


#: The least similarity (difflib's ratio) a spelling hint needs - the cutoff the hints were
#: taken with before they were ranked over the whole scope.
_HINT_CUTOFF = 0.75

#: Candidates of a hint by their length: (name, the mask of its distinct characters, the count
#: of its characters that repeat an earlier one).
_Table = dict[int, list[tuple[str, int, int]]]

#: The bit of every character met in a hint so far; the masks of all tables share it.
_CHAR_BITS: dict[str, int] = {}


def _char_mask(chars: Iterable[str]) -> int:
    mask = 0
    for char in chars:
        mask |= 1 << _CHAR_BITS.setdefault(char, len(_CHAR_BITS))
    return mask


def _hint_table(names: Iterable[str]) -> _Table:
    """The candidates by their length, each with the mask of its characters and its repeats."""
    table: _Table = {}
    for name in names:
        chars = set(name)
        table.setdefault(len(name), []).append((name, _char_mask(chars), len(name) - len(chars)))
    return table


def _least_shared(total: int) -> int:
    """The fewest matching characters that bring a pair `total` long to the cutoff.

    Settled by the very expression difflib compares with the cutoff, so the float rounding of
    the two agrees.
    """
    shared = int(_HINT_CUTOFF * total / 2)
    while shared > 0 and 2.0 * (shared - 1) / total >= _HINT_CUTOFF:
        shared -= 1
    while 2.0 * shared / total < _HINT_CUTOFF:
        shared += 1
    return shared


def _closest_in(name: str, table: _Table, one_edit: bool = False) -> tuple[float, str] | None:
    """The best (ratio, candidate) of a table, the one difflib.get_close_matches would pick.

    difflib scores the same candidates and orders them the same way: the ratio first, then the
    greater string. Two cheap bounds come first, and each only skips a candidate difflib turns
    down as well: the length (difflib's `real_quick_ratio`) and the characters the two can
    share - at most the distinct characters they have in common plus the repeats of the side
    that repeats less (a bound on its `quick_ratio`). Over the global names that leaves difflib
    a handful of candidates out of thousands.

    The name itself is no hint: declared out of reach (a local of another method), it would
    only be offered back to the reader.

    `one_edit` takes only a candidate one edit away - a character missing, extra, changed or
    swapped with its neighbour: every character of the longer of the two but one is matched
    (see _SHORT_NAME). The check is made on each candidate, not on the winner, so a closer
    candidate two edits away does not hide the one a single typo away.
    """
    length = len(name)
    chars = set(name)
    mask = _char_mask(chars)
    repeats = length - len(chars)
    matcher = difflib.SequenceMatcher()
    matcher.set_seq2(name)
    best: tuple[float, str] | None = None
    # The window only has to cover every length the bound below lets through.
    low = int(length * _HINT_CUTOFF / (2 - _HINT_CUTOFF))
    high = int(length * (2 - _HINT_CUTOFF) / _HINT_CUTOFF) + 1
    for size in range(max(low, 1), high + 1):
        if one_edit and abs(size - length) > 1:
            continue  # one edit changes the length by one at most
        bucket = table.get(size)
        if not bucket:
            continue
        need = _least_shared(length + size)
        if min(length, size) < need:
            continue
        for candidate, candidate_mask, candidate_repeats in bucket:
            shared = (mask & candidate_mask).bit_count()
            shared += candidate_repeats if candidate_repeats < repeats else repeats
            if shared < need or candidate == name:
                continue
            matcher.set_seq1(candidate)
            if matcher.quick_ratio() < _HINT_CUTOFF:
                continue
            score = matcher.ratio()
            if score < _HINT_CUTOFF:
                continue
            # The ratio is twice the matched characters over both lengths.
            if one_edit and round(score * (length + size) / 2) < max(length, size) - 1:
                continue
            if best is None or (score, candidate) > best:
                best = (score, candidate)
    return best


#: The longest name that is offered only a candidate one edit away (see _closest_in). The ratio of
#: two short names moves in coarse steps, and the cutoff lets two edits and more through: `Close`
#: and the function `Cos` score exactly 0.75, `Header` and `Handler` 0.77. Over the whole scope a
#: short word almost always has such a neighbour, while a typo in a short name is a single edit.
_SHORT_NAME = 7


def _stdlib_catalog() -> dict:
    """The stdlib catalog, empty without the data."""
    try:
        return dataset.load_json("stdlib.json")
    except dataset.DatasetError:
        return {}


@lru_cache(maxsize=1)
def _global_functions() -> frozenset[str]:
    """The global names that are called: the functions of the global context (`Message`, `Cos`).

    The catalog keeps the global context in one list; what the list shares with the type names
    (`HttpClient`) is reached as a value.
    """
    catalog = _stdlib_catalog()
    return frozenset(set(catalog.get("globals", ())) - set(catalog.get("names", ())))


@lru_cache(maxsize=1)
def _member_kinds() -> tuple[frozenset[str], frozenset[str]]:
    """(the methods, the properties) among the members of the platform types, both spellings.

    Only what the catalog documents as one kind and never as the other is counted: a name that
    is both (`Presentation` is a property of an object and a method of every type) belongs to
    neither set and is offered in either position.
    """
    methods: set[str] = set()
    properties: set[str] = set()
    catalog = _stdlib_catalog()
    for section in ("type_members", "generated_members", "manager_members"):
        for entry in (catalog.get(section) or {}).values():
            if isinstance(entry, dict):
                methods.update(entry.get("methods") or ())
                properties.update(entry.get("properties") or ())
    methods, properties = _both_spellings(methods), _both_spellings(properties)
    return frozenset(methods - properties), frozenset(properties - methods)


@lru_cache(maxsize=2)
def _global_table(call: bool) -> _Table:
    functions = _global_functions()
    names = _static_globals() or set()
    return _hint_table(names & functions if call else names - functions)


@lru_cache(maxsize=4096)
def _closest_global(name: str, call: bool) -> tuple[float, str] | None:
    """The best global candidate of a name - the same for every module, so kept per name."""
    return _closest_in(name, _global_table(call), len(name) <= _SHORT_NAME)


dataset.register_reset(_global_functions.cache_clear)
dataset.register_reset(_member_kinds.cache_clear)
dataset.register_reset(_global_table.cache_clear)
dataset.register_reset(_closest_global.cache_clear)

#: The groups of a scope, from the nearest to the farthest; a tie goes to the nearer one.
_MODULE_RANK, _ELEMENT_RANK, _PROJECT_RANK, _GLOBAL_RANK = range(4)


class _ScopeHints:
    """Spelling hints over the scope of one module, built for the first finding that needs one.

    Every group of the scope competes: the names of the module, what the element gives it, the
    objects of the project and the global names. The closest candidate wins whichever group it
    is in, and a tie goes to the nearer group. The hint used to stop at the first group that
    had any candidate at all, so a module name barely over the cutoff hid the attribute the typo
    was one letter away from (`Пасажир` got the parameter `Пассажиры` rather than the attribute
    `Пассажир`), and a misspelled global name got no hint at all.

    The position of the name narrows the candidates. A call (`Имя(...)`) is offered what can be
    called: the methods of the module and of the element and the functions of the global
    context - an object is created with `новый`, so a type never stands there. A bare name is
    offered what stands for a value: the variables, parameters, fields, structures and
    enumerations of the module, the attributes and properties of the element, the objects of
    the project, the platform types. Over the whole scope a variable used to be offered to a
    call and a method to a bare name, a hint that would not compile either. The methods the
    scope reaches only as callees (`calls`) compete for a bare name too, in the form of the call:
    for them the missing parentheses are the mistake the rule already names.

    The yaml of the element names attributes and properties next to the events of a component,
    which its module raises by a call, so what the yaml declares is offered in both positions.
    For the members of the platform types the documented kind decides (_member_kinds), and a
    name of both kinds or of none is offered in both, as every name used to be.

    The table of the project names is the same for every module and is built once per run
    (`project`); the global names are ranked per name, once per process (_closest_global).
    """

    def __init__(self, project: Callable[[], _Table], pool: Iterable[str],
                 callables: Iterable[str], extras: set[str], calls: set[str],
                 declared: set[str]) -> None:
        self._project = project
        self._names = (pool, callables, extras, calls, declared)
        self._tables: dict[bool, tuple[tuple[int, _Table, str], ...]] | None = None
        self._memo: dict[tuple[str, bool], str | None] = {}

    def _groups(self) -> dict[bool, tuple[tuple[int, _Table, str], ...]]:
        """(rank, table, tail) of every group but the global one, for a call and a bare name."""
        pool, callables, extras, calls, declared = self._names
        method_only, property_only = _member_kinds()
        element_calls = {n for n in extras if n in declared or n not in property_only}
        element_values = {n for n in extras if n in declared or n not in method_only}
        calls_table = _hint_table(calls)
        return {
            True: ((_MODULE_RANK, _hint_table(callables), ""),
                   (_ELEMENT_RANK, _hint_table(element_calls), ""),
                   (_ELEMENT_RANK, calls_table, "")),
            False: ((_MODULE_RANK, _hint_table(pool), ""),
                    (_ELEMENT_RANK, _hint_table(element_values), ""),
                    (_ELEMENT_RANK, calls_table, "()"),
                    (_PROJECT_RANK, self._project(), "")),
        }

    def closest(self, name: str, call: bool) -> str | None:
        """The hint for a name, or None.

        A method that answers only to a call competes for a bare name as well; offered there, it
        comes with its parentheses, so the hint is the code to write.
        """
        key = (name, call)
        if key in self._memo:
            return self._memo[key]
        if self._tables is None:
            self._tables = self._groups()
        one_edit = len(name) <= _SHORT_NAME
        best: tuple[float, int, str] | None = None
        written = ""
        for rank, table, tail in self._tables[call]:
            found = _closest_in(name, table, one_edit)
            if found is not None and (best is None or (found[0], -rank, found[1]) > best):
                best, written = (found[0], -rank, found[1]), found[1] + tail
        found = _closest_global(name, call)
        if found is not None and (best is None or (found[0], -_GLOBAL_RANK, found[1]) > best):
            best, written = (found[0], -_GLOBAL_RANK, found[1]), found[1]
        self._memo[key] = written or None
        return self._memo[key]


class _Hints:
    """The spelling hints of one run: the part shared by the modules is built once."""

    def __init__(self, project_names: set[str]) -> None:
        self._project_names = project_names
        self._project_table: _Table | None = None

    def _project(self) -> _Table:
        if self._project_table is None:
            self._project_table = _hint_table(self._project_names)
        return self._project_table

    def module(self, pool: Iterable[str], callables: Iterable[str], extras: set[str],
               calls: set[str], declared: set[str]) -> _ScopeHints:
        return _ScopeHints(self._project, pool, callables, extras, calls, declared)
