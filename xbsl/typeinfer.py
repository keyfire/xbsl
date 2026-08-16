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
from dataclasses import dataclass, field

from xbsl import dataset
from xbsl import parser as P

#: A plain type name or a one-dot facet (`ДвоичныйОбъект.Ссылка`), the shape the catalogs key by.
_NOMINAL_RE = re.compile(r"[А-Яа-яЁёA-Za-z0-9_]+(?:\.[А-Яа-яЁёA-Za-z0-9_]+)?")

#: The type a literal names, by the lexer's own kind. The empty value is a type of its own in the
#: platform, and it is exactly what makes an expression nullable. The catalog keys types by both
#: spellings, so the Russian name answers for an English source as it does everywhere else here.
_LITERAL_TYPES = {
    "STRING": "Строка",
    "NUMBER": "Число",
    "TRUE": "Булево",
    "FALSE": "Булево",
    "QUERY": "Запрос",
    "PATTERN": "Образец",
}
_UNDEFINED_KIND = "UNDEFINED"
#: A resolvable literal (`Ресурс{...}`) is not named by its kind: the identifier that OPENS it is
#: the type, and the lexer keeps it in the literal's own text.
_RESOLVABLE_KIND = "RESOLVABLE"

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
    """A type the module could name: the nominal name plus whether the empty value belongs to it.

    `args` carries the arguments of a generic as they were WRITTEN (`Array<String>` -> `String`),
    because the element of a loop is not in the head alone. It stays out of the comparison on
    purpose: the answer of this module is the nominal type, and a caller that already asks
    `== Inferred("Массив")` must not start missing a typed array over a detail it never named.
    """

    name: str
    nullable: bool = False
    args: tuple[str, ...] = field(default=(), compare=False)

    def without_null(self) -> "Inferred":
        return self if not self.nullable else Inferred(self.name, False, self.args)


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


def method_env(method: object, *, type_names: bool = False,
               returns: dict[str, Inferred] | None = None,
               this_type: Inferred | None = None,
               own_properties: dict[str, str] | None = None,
               at: int | None = None) -> TypeEnv:
    """The environment of one method: every declared name, typed where the source says so.

    Collecting this in one place is what keeps the type-name shortcut honest. A name DECLARED in
    the method is never a type, even when the catalog knows a type of that name and even when the
    declaration says nothing about its type: a live module holds `пер Список = ...`, and reading
    that name as the stdlib type answered "not nullable" for a value that plainly is.

    `at` is the offset of the place being judged, and with it the names are read the way the
    platform scopes them (docs, "Область видимости имен"): a declaration is visible from where
    it stands to the end of ITS BLOCK, blocks nest, and the innermost declaration wins. Without
    `at` the whole method is one bag of names, which is enough for a caller that asks about the
    method as a whole and wrong for one that asks about a place: a live module declares one
    name in two loops of a 160-line method, and the type of the first loop used to answer for
    the second - where the collection is a UNION and the cast is obligatory.

    `own_properties` is what the module's own type carries - the attributes of the PAIRED
    yaml, `{name: type as written}`. A form module reads them by a bare name, and without them
    such a name falls through to the type-name shortcut: an attribute spelled like the stdlib
    `File` type, declared in the yaml as a nullable binary-object reference, was read as that
    type - never empty - and the non-null operator the code needs looked redundant. They sit
    in the method scope, so any local declaration of the same name wins over them.

    `shadowed` stays method-wide either way. It answers "is this name a variable here at all",
    and a name that any block of the method declares must not be read as a stdlib type
    elsewhere in it - being generous there would reintroduce the very guess the set prevents.
    """
    import dataclasses

    variables: dict[str, Inferred] = {}
    declared: set[str] = set()
    env = TypeEnv(variables, returns=returns, this_type=this_type, type_names=False)
    # (block start, block end, position, name) -> type; filtered by `at` at the end.
    scoped: list[tuple[int, int, int, str, Inferred]] = []
    method_span = (int(getattr(method, "start", 0)), int(getattr(method, "end", 0)))

    def remember(name: str, tref: object, init: object = None,
                 block: tuple[int, int] | None = None, pos: int | None = None) -> None:
        declared.add(name)
        got = nominal(getattr(tref, "text", None))
        if got is None and init is not None:
            got = expression_type(init, env)
        if got is None:
            return
        variables[name] = got
        span = block or method_span
        scoped.append((span[0], span[1], pos if pos is not None else span[0], name, got))

    for name, written in (own_properties or {}).items():
        got = nominal(written)
        if got is not None:
            variables[name] = got
            scoped.append((method_span[0], method_span[1], method_span[0], name, got))
            declared.add(name)

    for param in getattr(method, "params", ()) or ():
        remember(getattr(param, "name", ""), getattr(param, "type", None))

    def walk(node: object, block: tuple[int, int]) -> None:
        if isinstance(node, (list, tuple)):
            # A list of statements IS a block: that is what `если`, `для` and `область` open,
            # and its span is the span of the statements it holds.
            inner = _statement_block(node) or block
            for item in node:
                walk(item, inner)
            return
        if not isinstance(node, P.Node):
            return
        if isinstance(node, P.VarDecl):
            remember(node.name, getattr(node, "type", None), getattr(node, "init", None),
                     block, int(getattr(node, "start", block[0])))
        elif isinstance(node, P.ForEach):
            # The loop names its variable without a type: it is one ELEMENT of the collection,
            # and the collection is typed by what stands to the left of this loop. The variable
            # lives in the loop, so its block is the loop node, not the block around it.
            name = getattr(node, "var", "")
            declared.add(name)
            element = _element_type(expression_type(getattr(node, "source", None), env))
            if element is not None:
                variables[name] = element
                span = (int(getattr(node, "start", block[0])), int(getattr(node, "end", block[1])))
                scoped.append((span[0], span[1], span[0], name, element))
        elif isinstance(node, P.ForTo):
            # `для Х = А по Б [шаг С]` counts, and the platform counts with numbers.
            name = getattr(node, "var", "")
            declared.add(name)
            counter = Inferred(_LITERAL_TYPES["NUMBER"])
            variables[name] = counter
            span = (int(getattr(node, "start", block[0])), int(getattr(node, "end", block[1])))
            scoped.append((span[0], span[1], span[0], name, counter))
        elif isinstance(node, P.Lambda):
            for param in getattr(node, "params", ()) or ():
                declared.add(getattr(param, "name", ""))
        for f in dataclasses.fields(node):
            walk(getattr(node, f.name, None), block)

    walk(getattr(method, "body", None), method_span)
    if at is not None:
        # The innermost block that holds the place wins, and among its declarations the last
        # one standing BEFORE the place: that is the platform rule read literally.
        visible: dict[str, tuple[int, int, Inferred]] = {}
        for start, end, pos, name, got in scoped:
            if not (start <= at <= end and pos <= at):
                continue
            best = visible.get(name)
            if best is None or (start, pos) >= (best[0], best[1]):
                visible[name] = (start, pos, got)
        variables = {name: got for name, (_s, _p, got) in visible.items()}
    return TypeEnv(variables, returns=returns, this_type=this_type,
                   type_names=type_names, shadowed=frozenset(declared) - set(variables))


def _statement_block(items: object) -> tuple[int, int] | None:
    """The span of a list of statements, or None when the list holds something else."""
    stmts = [x for x in (items or ()) if isinstance(x, P.Stmt)]
    if not stmts:
        return None
    return int(getattr(stmts[0], "start", 0)), int(getattr(stmts[-1], "end", 0))


def _element_type(collection: Inferred | None) -> Inferred | None:
    """One element of a collection: `Array<String>` -> `String`.

    Answered only for a collection written with a SINGLE argument, which is what an array, a set
    and a readable sequence are. A map has two, and its element is neither of them - the platform
    hands out `KeyAndValue<KeyType,ValueType>` - but nothing in the data pairs a two-argument
    collection with that type, and pairing them by name here would be a guess. So: silence.
    """
    if collection is None or len(collection.args) != 1:
        return None
    return nominal(collection.args[0])


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
    # A generic counts by its HEAD: the arguments type the members, they do not name them. They
    # are carried along all the same - the element of a loop over the collection is one of them.
    head = stripped.split("<", 1)[0].strip()
    if stripped.endswith(">") and _NOMINAL_RE.fullmatch(head):
        return Inferred(head, nullable, _type_arguments(stripped))
    return None


def _type_arguments(text: str) -> tuple[str, ...]:
    """The arguments of `Голова<А, Б>` as written, split at the TOP level only.

    An argument is itself a type and may be generic, so a comma inside its own angle brackets
    belongs to it: `Массив<Соответствие<Строка, Число>>` has ONE argument, not two.
    """
    inner = text[text.index("<") + 1 : -1]
    args: list[str] = []
    current: list[str] = []
    depth = 0
    for char in inner:
        if char == "<":
            depth += 1
        elif char == ">":
            depth -= 1
        elif char == "," and depth == 0:
            args.append("".join(current).strip())
            current = []
            continue
        current.append(char)
    tail = "".join(current).strip()
    if tail:
        args.append(tail)
    return tuple(arg for arg in args if arg)


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
        if not declared:
            continue
        got = nominal(declared)
        # The catalog states the result of a generic member by the TYPE PARAMETER name
        # (a data event answers with `DataType`), and that is a variable, not a type: the
        # answer depends on the argument the receiver was built with. Reading it as a type once
        # made an expression look non-empty when the data it stands for plainly is - so a name the
        # catalog does not know as a type is no answer at all.
        if got is None or not is_type_name(got.name):
            return None
        return got
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
        if kind == _RESOLVABLE_KIND:
            # The opening identifier is the type only if the catalog knows it as one: the shape
            # `Имя{...}` is open, and a name the data is silent about is no answer.
            opener = str(getattr(node, "text", ""))
            return Inferred(opener) if opener and is_type_name(opener) else None
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
        # `А ?? Б` answers Б when А is empty and А otherwise, so the two sides must agree for
        # the whole to have a name: the value is of one type or the other, and naming it by the
        # right-hand side alone is a guess the code then acts on. It stayed unnoticed while the
        # left side was rarely typed - `(Параметры.ПолучитьПараметр("К") ?? "") как Строка` read
        # as a String cast over a String, that is as a redundant cast, though the parameter is
        # of no such type and the cast is exactly what makes the value one.
        # Only the emptiness is settled here: `Б` non-empty makes the whole non-empty.
        left = expression_type(getattr(node, "left", None), env)
        right = expression_type(getattr(node, "right", None), env)
        if left is not None and right is not None and left.name == right.name:
            return Inferred(left.name, left.nullable and right.nullable)
        return None
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
