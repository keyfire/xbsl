"""Tier D: a declaration must not rely on a default value the type does not have.

Two rules of one family, both reading the `type_ctors` section of the type catalog (how the
documentation says the type is constructed: `empty` - a constructor callable with no
arguments, `args` - constructors that all demand arguments, `none` - no constructor at all):

- code/collection-field-needs-req - a structure field with a generic type;
- code/var-needs-init - a variable declared by type alone.

A declaration with no initializer is initialized with the DEFAULT VALUE of its type, and a
type that has none makes it a compile error (topics/variable-declaration-statement). For a
structure field the failure reads "cannot be initialized with a default value and is not
marked as required for the constructor", for a variable - "has neither a constructor nor a
default value". Both are apply-time failures the linter can see locally: the catalog knows
which types are constructible.

The collection side (code/collection-field-needs-req). A field typed `ReadableArray<String>`
is rejected: the type's only constructor is the copying one (it takes an `Iterable`), so
nothing can build an empty one. `Array<String>`, `Set<String>`, `Map<String, Number>` are the
opposite case - each has an argument-less constructor, the platform documentation itself
declares a variable of such a type with no initializer (topics/array-type), and on real code
such fields are commonplace and apply cleanly. So the catalog, not the shape, decides. The
correct forms mirror the reference-field rule:

- `req var texts: ReadableArray<String>` - the field becomes a constructor argument;
- `var texts: ReadableArray<String>?` - a nullable type defaults to `Undefined`;
- `var texts: ReadableArray<String> = <String>[]` - an explicit initializer.

Deliberate narrowing: only a type WRITTEN WITH A TYPE ARGUMENT (`Head<...>`) is judged. For a
bare name the constructor fact alone would mislead - `String`, `Boolean` and `Date` are `args`
(their constructors parse a value) and yet have a default value of their own. A generic head
has no such exception in the catalog.

The variable side (code/var-needs-init). `var response: HttpResponse` (declare first, assign
inside a `try`) does not compile - the type is only ever obtained from the platform. Flagged
is a declaration whose type has NO constructor at all (`none`) - the case the compiler names
in so many words; a type that has a constructor but needs arguments is left alone here,
because a bare name may still be a primitive with a default. Types whose hierarchy makes a
default plausible are skipped as well: an enumeration (a `default` element is one), an
annotation, a singleton (`Auto`, `Null` - one instance is all there is). The fix is either a
nullable type plus a check, or reading what is needed inside the `try` into plain variables.

Structure fields are not this rule's business (the two field rules above cover them), and
neither is a `const`/`catch` declaration - a constant always carries a value, and the
exception of a catch is bound by the runtime.

Scope differs, and for one reason - a namesake. A bare name may belong to a project type
rather than to the catalog, and real projects do declare a structure or an object whose name
is also that of a platform type without a constructor. So code/var-needs-init is project-wide
(it does not run in single-file mode): the reduce drops a candidate shadowed by a project
object or by a type declared in any module. The field rule needs no such check and stays
file-scoped, instant in the editor: a project type cannot be generic, so a type WRITTEN with
an argument is always the catalog's.

Both rules quote the fix in the SPELLING THE MODULE USES: the keyword forms are taken from
the language data, so an English module is never advised of a keyword that is not in its
sources (`req`, not its Russian twin).

Without the platform data (or with a dataset generated before `type_ctors` existed) both
rules stay silent.
"""

from __future__ import annotations

from collections.abc import Iterable
from functools import lru_cache

from xbsl import dataset, i18n, terms
from xbsl.diagnostics import Diagnostic, Severity
from xbsl.engine import SourceFile, rule
from xbsl.lexer import Token
from xbsl.rules._syntax import code_tokens, declarations, type_expr
from xbsl.rules.ref_fields import _decl_names, structure_field_decls
from xbsl.rules.semantics import _file_local_types, _object_name_fast

MESSAGES = {
    "code/collection-field-needs-req.title": {
        "ru": "Поле-коллекция структуры без 'обз'",
        "en": "Structure collection field without 'req'",
    },
    "code/collection-field-needs-req.missing": {
        "ru": "Поле структуры '{name}' имеет тип '{type}', у которого нет конструктора без "
              "аргументов, значит нет и значения по умолчанию – применение сборки падает с "
              "'не может быть проинициализировано значением по умолчанию'. Правильно: "
              "'{req} {kw} {name}: {type}' либо '{type}?'.",
        "en": "Structure field '{name}' has the type '{type}', which has no argument-less "
              "constructor and therefore no default value – applying the build fails with "
              "'cannot be initialized with a default value'. Correct: '{req} {kw} {name}: "
              "{type}' or '{type}?'.",
    },
    "code/var-needs-init.title": {
        "ru": "Переменная типа без конструктора и значения по умолчанию",
        "en": "Variable of a type with no constructor and no default value",
    },
    "code/var-needs-init.missing": {
        "ru": "Переменная '{name}' объявлена типом '{type}', у которого нет ни конструктора, "
              "ни значения по умолчанию – компиляция падает с 'Тип \"{type}\" не имеет "
              "конструктора и значения по умолчанию'. Объявите '{type}?' либо читайте нужное "
              "внутри '{try}' в простые переменные.",
        "en": "The variable '{name}' is declared with the type '{type}', which has neither a "
              "constructor nor a default value – the compilation fails with 'has no "
              "constructor and no default value'. Declare '{type}?' or read what you need "
              "inside the '{try}' into plain variables.",
    },
}
i18n.register(MESSAGES)

#: Bases that make a default value plausible: an enumeration may carry a default element, an
#: annotation is not a value at all, and a singleton has exactly one instance. The catalog
#: reports all three as `none` (they have no constructor), so they are skipped by hierarchy.
#: Named in Russian here because that is the spelling the catalog stores in `bases`; the
#: English twin of each is added from the platform dictionary, never guessed.
_DEFAULTABLE_BASE_NAMES = ("Перечисление", "Аннотация", "Одиночка")
_CTOR_EMPTY = "empty"
_CTOR_NONE = "none"
#: A `const` always carries a value and a `catch` name is bound by the runtime - only a plain
#: variable declaration can ask for a default value that is not there.
_DECL_KEYWORDS = ("VAR", "VAL")
#: Keywords quoted in the advice; the form is chosen to match the module (see _keyword_like).
_REQ, _TRY = "REQ", "TRY"


@lru_cache(maxsize=1)
def _catalog() -> dict:
    """The type catalog, or an empty one when the data is not generated on this machine."""
    try:
        return dataset.load_json("stdlib.json")
    except (dataset.DatasetError, ValueError):
        return {}


@lru_cache(maxsize=1)
def _ctor_kinds() -> dict[str, str]:
    """{type name: how it is constructed} from the catalog, both name forms.

    Empty when the data is missing or predates the section - the rules then say nothing.
    """
    return dict(_catalog().get("type_ctors") or {})


@lru_cache(maxsize=1)
def _defaultable_bases() -> frozenset[str]:
    """The bases of _DEFAULTABLE_BASE_NAMES under both spellings, the English from the data."""
    out = set(_DEFAULTABLE_BASE_NAMES)
    for name in _DEFAULTABLE_BASE_NAMES:
        english = terms.english(name, "types")
        if english:
            out.add(english)
    return frozenset(out)


@lru_cache(maxsize=1)
def _no_default_types() -> frozenset[str]:
    """Types with no constructor whose hierarchy gives no default value either."""
    data = _catalog()
    bases = data.get("bases") or {}
    skip = _defaultable_bases()
    return frozenset(
        name for name, kind in (data.get("type_ctors") or {}).items()
        if kind == _CTOR_NONE and not any(base in skip for base in bases.get(name, ()))
    )


@lru_cache(maxsize=1)
def _keyword_pairs() -> dict[str, tuple[str, str]]:
    """{canonical keyword: (Latin form, Cyrillic form)} out of the language data.

    The advice quotes a keyword, and a module written in English must be advised of the
    spelling ITS sources use - the pair is read from the grammar data, never guessed.
    """
    try:
        keywords = dataset.load_json("language.json").get("keywords") or {}
    except (dataset.DatasetError, ValueError):
        keywords = {}
    pairs: dict[str, tuple[str, str]] = {}
    for canonical in (_REQ, _TRY):
        forms = [f for f in (keywords.get(canonical) or {}).get("forms", ()) if f.islower()]
        latin = next((f for f in forms if f.isascii()), canonical.lower())
        other = next((f for f in forms if not f.isascii()), latin)
        pairs[canonical] = (latin, other)
    return pairs


def _keyword_like(canonical: str, sample: str) -> str:
    """The form of `canonical` written in the same alphabet as `sample`."""
    latin, other = _keyword_pairs()[canonical]
    return latin if sample.isascii() else other


dataset.register_reset(_catalog.cache_clear)
dataset.register_reset(_ctor_kinds.cache_clear)
dataset.register_reset(_defaultable_bases.cache_clear)
dataset.register_reset(_no_default_types.cache_clear)
dataset.register_reset(_keyword_pairs.cache_clear)


def _head_and_generic(alternative: list[Token]) -> tuple[str, bool] | None:
    """(head type name, whether a type argument is written) for a one-name type, else None.

    A dotted chain (`Catalog.Reference`, `Catalog.Object` and the rest of the facets an
    object generates) is not this family's business - the reference rule owns it - and a
    nullable type carries its own default.
    """
    if not alternative or alternative[0].kind != "IDENT":
        return None
    head = alternative[0].value
    rest = alternative[1:]
    if not rest:
        return head, False
    if rest[0].kind == "OP" and rest[0].value == "<" and rest[-1].value == ">":
        return head, True
    return None  # a dotted chain, a nullable marker or anything else


@rule(
    "code/collection-field-needs-req", "code/collection-field-needs-req.title", "D",
    severity=Severity.ERROR,
)
def collection_field_needs_req(source: SourceFile) -> Iterable[Diagnostic]:
    if source.kind != "xbsl":
        return []
    kinds = _ctor_kinds()
    if not kinds:
        return []
    toks = code_tokens(source)
    n = len(toks)
    diags: list[Diagnostic] = []

    for i, has_req in structure_field_decls(source):
        if has_req:
            continue
        names, j = _decl_names(toks, i + 1)
        if not names or j >= n or not (toks[j].kind == "OP" and toks[j].value == ":"):
            continue
        te = type_expr(toks, j + 1)
        if te is None or len(te.alternatives) != 1:
            continue  # no type, or a union - the platform's rules for those are not encoded
        if te.end < n and toks[te.end].kind == "OP" and toks[te.end].value == "=":
            continue  # an explicit initializer
        parsed = _head_and_generic(te.alternatives[0])
        if parsed is None:
            continue
        head, generic = parsed
        if not generic or kinds.get(head, _CTOR_EMPTY) == _CTOR_EMPTY:
            continue
        type_text = "".join(t.value for t in te.alternatives[0])
        for name in names:
            diags.append(Diagnostic(
                source.rel, name.line, name.col, "code/collection-field-needs-req",
                Severity.ERROR,
                i18n.t(
                    "code/collection-field-needs-req.missing",
                    name=name.value, type=type_text, kw=toks[i].value,
                    req=_keyword_like(_REQ, toks[i].value),
                ),
            ))
    return diags


def _var_needs_init_mapper(source: SourceFile) -> dict | None:
    """The map phase: a yaml contributes the object name it declares, an xbsl its local
    types and its bare declarations of catalog types with no default value. Which of those
    names a project type of its own shadows is the reduce's call."""
    if source.kind == "yaml":
        name = _object_name_fast(source)
        return {"k": "y", "name": name} if name else None
    if source.kind != "xbsl":
        return None
    without_default = _no_default_types()
    if not without_default:
        return None  # no data (or a dataset older than type_ctors) - the rule says nothing
    toks = code_tokens(source)
    # Structure fields are the field rules' business; a declaration is identified by the
    # position of its keyword - the token lists of both helpers are one and the same.
    fields = {(toks[i].line, toks[i].col) for i, _req in structure_field_decls(source)}
    cands: list[tuple[str, str, str, int, int, str]] = []

    for decl in declarations(toks, keywords=_DECL_KEYWORDS):
        if decl.assign is not None or decl.type_start is None:
            continue
        if (decl.keyword.line, decl.keyword.col) in fields:
            continue
        te = type_expr(toks, decl.type_start)
        if te is None or len(te.alternatives) != 1:
            continue
        parsed = _head_and_generic(te.alternatives[0])
        if parsed is None or parsed[0] not in without_default:
            continue
        type_text = "".join(t.value for t in te.alternatives[0])
        for name in decl.names:
            cands.append((name.value, type_text, parsed[0], name.line, name.col,
                          _keyword_like(_TRY, decl.keyword.value)))
    local = _file_local_types(source)
    if not cands and not local:
        return None
    return {"k": "x", "cands": cands, "local_types": sorted(local)}


@rule(
    "code/var-needs-init", "code/var-needs-init.title", "D",
    scope="project", severity=Severity.WARNING, mapper=_var_needs_init_mapper,
)
def var_needs_init(facts: dict[str, dict]) -> Iterable[Diagnostic]:
    shadowed: set[str] = set()
    for fact in facts.values():
        if fact["k"] == "y":
            shadowed.add(fact["name"])
        else:
            shadowed.update(fact["local_types"])
    for rel, fact in facts.items():
        if fact["k"] != "x":
            continue
        for name, type_text, head, line, col, try_form in fact["cands"]:
            if head in shadowed:
                continue  # a project type of the same name - the catalog says nothing about it
            yield Diagnostic(
                rel, line, col, "code/var-needs-init", Severity.WARNING,
                i18n.t("code/var-needs-init.missing", name=name, type=type_text, **{"try": try_form}),
            )
