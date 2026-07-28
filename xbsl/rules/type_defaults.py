"""Tier D: a declaration must not rely on a default value the type does not have.

The code/collection-field-needs-req rule reads the `type_ctors` section of the type catalog
(how the documentation says the type is constructed: `empty` - a constructor callable with no
arguments, `args` - constructors that all demand arguments, `none` - no constructor at all).

A declaration with no initializer is initialized with the DEFAULT VALUE of its type, and a
type that has none makes it a compile error (topics/variable-declaration-statement). For a
structure field the failure reads "cannot be initialized with a default value and is not
marked as required for the constructor" - an apply-time failure the linter can see locally:
the catalog knows which types are constructible.

A field typed `ReadableArray<String>`
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

The rule quotes the fix in the SPELLING THE MODULE USES: the keyword form is taken from the
language data, so an English module is never advised of a keyword that is not in its sources
(`req`, not its Russian twin).

The rule is file-scoped, instant in the editor: a project type cannot be generic, so a type
WRITTEN with an argument is always the catalog's, and no project index is needed. Without the
platform data (or with a dataset generated before `type_ctors` existed) the rule stays silent.
"""

from __future__ import annotations

from collections.abc import Iterable
from functools import lru_cache

from xbsl import dataset, i18n, terms
from xbsl.diagnostics import Diagnostic, Severity
from xbsl.engine import SourceFile, rule
from xbsl.lexer import Token
from xbsl.rules._syntax import code_tokens, type_expr
from xbsl.rules.ref_fields import _decl_names, structure_field_decls

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
}
i18n.register(MESSAGES)

_CTOR_EMPTY = "empty"
#: The keyword quoted in the advice; the form is chosen to match the module (see _keyword_like).
_REQ = "REQ"


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
    for canonical in (_REQ,):
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
