"""The type of an EXPRESSION, as far as the platform data allows.

Rules of tier D judge names against the catalogs, and until now each of them typed what it
needed on its own: a variable by its declaration, a constructor by its type name, a collection
literal by its head. Three classes of the platform's own diagnostics stayed out of reach for the
same reason - a redundant cast, a non-null assertion the code does not need and a comparison
with the empty value are all questions about the type of an EXPRESSION, not of a name:

    (item as Card).Basket        the cast applies to a member access
    Catalog.FindByCode("1").Name  the receiver is the result of a call

This module answers that question from the same data the rules already trust: `member_types`
(the result type of a member, from the documentation of its type), `bases` (the inheritance
chain, so an inherited member resolves too) and the declared types of the module's own methods.
Nothing is guessed: an expression the data cannot type answers None, and a caller that gets None
must stay silent rather than assume.

The answer carries the NULLABLE flag alongside the name, because that is exactly what the two
remaining diagnostics turn on - `Х!` is redundant when Х is not nullable, and a comparison with
the empty value is impossible for a type that has none.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from xbsl import dataset
from xbsl import parser as P

#: A plain type name or a one-dot facet (`ДвоичныйОбъект.Ссылка`), the shape the catalogs key by.
_NOMINAL_RE = re.compile(r"[А-Яа-яЁёA-Za-z0-9_]+(?:\.[А-Яа-яЁёA-Za-z0-9_]+)?")

#: The type a literal names, by the lexer's own kind. The empty value is a type of its own in the
#: platform, and it is exactly what makes an expression nullable.
_LITERAL_TYPES = {
    "STRING": "Строка",
    "NUMBER": "Число",
    "TRUE": "Булево",
    "FALSE": "Булево",
}
_UNDEFINED_KIND = "UNDEFINED"

#: The head type of a collection literal - the arguments type the members, they do not name them.
_COLLECTION_TYPES = {"array": "Массив", "map": "Соответствие", "set": "Множество"}

_catalog_cache: dict | None = None


def _catalog() -> dict:
    global _catalog_cache
    if _catalog_cache is None:
        try:
            _catalog_cache = dataset.load_json("stdlib.json")
        except Exception:  # noqa: BLE001 - no data, no inference
            _catalog_cache = {}
    return _catalog_cache


def _reset() -> None:
    global _catalog_cache
    _catalog_cache = None


dataset.register_reset(_reset)


@dataclass(frozen=True)
class Inferred:
    """A type the module could name: the nominal name plus whether the empty value belongs to it."""

    name: str
    nullable: bool = False

    def without_null(self) -> "Inferred":
        return self if not self.nullable else Inferred(self.name, False)


@dataclass
class TypeEnv:
    """What the caller knows before the expression is looked at.

    `variables` is name -> declared type as the rule collected it (the same shape the member
    rules already build); `returns` is the declared result type of the module's OWN methods, so
    a call of a neighbouring method types its result; `this_type` is the type of `этот`.

    `type_names` says whether a BARE NAME may be read as the type itself (`ДатаВремя.Минимальная()`).
    It is off by default on purpose: a form attribute named like a stdlib type is a real shape -
    the rules met `Email` that way - so only a caller that has checked the project may turn it on,
    and `shadowed` lists the names it knows to be something else.
    """

    variables: dict[str, Inferred]
    returns: dict[str, Inferred] | None = None
    this_type: Inferred | None = None
    type_names: bool = False
    shadowed: frozenset[str] = frozenset()


def nominal(text: str | None) -> Inferred | None:
    """The declared type of a source annotation: `Goods.Ref?` -> (Goods.Ref, nullable).

    A union, a generic argument list and anything the catalogs do not key by come back None -
    the caller then knows only that the type is not a plain one.
    """
    if not text:
        return None
    stripped = text.strip()
    if "|" in stripped:
        return None
    nullable = stripped.endswith("?")
    if nullable:
        stripped = stripped[:-1].strip()
    if _NOMINAL_RE.fullmatch(stripped):
        return Inferred(stripped, nullable)
    # A generic counts by its HEAD: the arguments type the members, they do not name them.
    head = stripped.split("<", 1)[0].strip()
    if stripped.endswith(">") and _NOMINAL_RE.fullmatch(head):
        return Inferred(head, nullable)
    return None


def is_type_name(name: str) -> bool:
    """Does the platform catalog know a type of this name?"""
    catalog = _catalog()
    return name in (catalog.get("type_members") or {}) or name in (catalog.get("member_types") or {})


def member_type(owner: str, member: str) -> Inferred | None:
    """The result type of `<owner>.<member>`, following the inheritance chain."""
    catalog = _catalog()
    types = catalog.get("member_types") or {}
    bases = catalog.get("bases") or {}
    for holder in (owner, *(bases.get(owner) or ())):
        declared = (types.get(holder) or {}).get(member)
        if declared:
            return nominal(declared)
    return None


def expression_type(node: object, env: TypeEnv) -> Inferred | None:
    """The type of an expression, or None when the data cannot name it.

    Deliberately partial: only the shapes whose type follows from the catalogs are answered, and
    everything else - arithmetic, a ternary, a call of another module, a lambda - stays None.
    A caller must treat None as "unknown", never as "no type".
    """
    if isinstance(node, P.Name):
        known = env.variables.get(node.name)
        if known is not None:
            return known
        if env.type_names and node.name not in env.shadowed and is_type_name(node.name):
            # A bare TYPE in the value position: its members are the static ones, and for the
            # member lookup the holder is the type itself.
            return Inferred(node.name)
        return None
    if isinstance(node, P.This):
        return env.this_type
    if isinstance(node, P.Literal):
        kind = str(getattr(node, "kind", ""))
        if kind == _UNDEFINED_KIND:
            return Inferred("Неопределено", True)
        name = _LITERAL_TYPES.get(kind)
        return Inferred(name) if name else None
    if isinstance(node, P.ArrayLit):
        return Inferred(_COLLECTION_TYPES["array"])
    if isinstance(node, P.MapLit):
        name = _COLLECTION_TYPES.get(getattr(node, "kind", ""))
        return Inferred(name) if name else None
    if isinstance(node, P.New):
        return nominal(getattr(getattr(node, "type", None), "text", None))
    if isinstance(node, P.AsType):
        return nominal(getattr(getattr(node, "type", None), "text", None))
    if isinstance(node, P.NonNull):
        inner = expression_type(getattr(node, "operand", None), env)
        return inner.without_null() if inner else None
    if isinstance(node, P.Coalesce):
        # `А ?? Б` answers Б when А is empty, so the result cannot be empty when Б is not.
        left = expression_type(getattr(node, "left", None), env)
        right = expression_type(getattr(node, "right", None), env)
        if left is not None and right is not None and left.name == right.name:
            return Inferred(left.name, left.nullable and right.nullable)
        return right.without_null() if right is not None and left is not None else None
    if isinstance(node, P.Member):
        return _member_expression_type(node, env)
    if isinstance(node, P.Call):
        callee = getattr(node, "callee", None)
        if isinstance(callee, P.Member):
            return _member_expression_type(callee, env)
        if isinstance(callee, P.Name) and env.returns is not None:
            return env.returns.get(callee.name)
        return None
    return None


def _member_expression_type(node: object, env: TypeEnv) -> Inferred | None:
    """`<выражение>.Член`: the receiver is typed first, then the member is looked up on it."""
    owner = expression_type(getattr(node, "obj", None), env)
    if owner is None:
        return None
    return member_type(owner.name, getattr(node, "name", ""))
