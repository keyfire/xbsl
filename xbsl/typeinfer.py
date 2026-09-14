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
from collections.abc import Iterator
from dataclasses import dataclass, field
from functools import cache, lru_cache

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
    # The walk reads the initializers with the type names ON: a local built by a static
    # member of a platform type (`ЖурналСобытий.Найти(...)`, the search result it answers, the
    # event read off that result) is typed by the catalog only when the receiver is read as
    # the type it names. Off, every such local stayed untyped, and a member read off it fell
    # to the flat vocabulary - which is how a project dictionary entry spelled against the
    # platform reached a translated tree unnoticed. What keeps the shortcut honest here is
    # the SAME method-wide rule the result obeys: every name the method declares anywhere is
    # collected first and kept off it, so a local named like a type is never read as one -
    # not even in an initializer standing before that local's own declaration.
    env = TypeEnv(variables, returns=returns, this_type=this_type, type_names=True,
                  shadowed=_declared_names(method, own_properties))
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


def _declared_names(method: object, own_properties: dict[str, str] | None = None) -> frozenset[str]:
    """Every name the method declares anywhere - parameters, locals, loop variables, lambda
    parameters - plus the own properties handed in: the set `method_env` keeps off the
    type-name shortcut while it walks the declarations (see there)."""
    import dataclasses

    names: set[str] = set(own_properties or ())
    for param in getattr(method, "params", ()) or ():
        names.add(getattr(param, "name", ""))

    def walk(node: object) -> None:
        if isinstance(node, (list, tuple)):
            for item in node:
                walk(item)
            return
        if not isinstance(node, P.Node):
            return
        if isinstance(node, P.VarDecl):
            names.add(node.name)
        elif isinstance(node, (P.ForEach, P.ForTo)):
            names.add(getattr(node, "var", ""))
        elif isinstance(node, P.Lambda):
            for param in getattr(node, "params", ()) or ():
                names.add(getattr(param, "name", ""))
        for f in dataclasses.fields(node):
            walk(getattr(node, f.name, None))

    walk(getattr(method, "body", None))
    names.discard("")
    return frozenset(names)


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


# =============================================================================================
# Type sets: the type the compiler compares, with the project it lives in
# =============================================================================================
#
# Everything above answers ONE nominal type with a nullable flag, and the platform catalog is its
# only source. That is enough for a hover and for the translator, and it is not enough to judge
# the checks the compiler makes itself. The compiler holds the type of an expression as a SET - a
# parameter declared `Материалы.Ссылка|Страницы.Ссылка` is two types, a query column read
# through a reference is its field type plus Null - and its warnings turn on that set: whether a
# cast adds anything (`cast_verdict`), whether a guard against the empty value guards anything,
# whether `это` can fail at all. And most of what the code handles comes from the PROJECT: a
# column of a query over a catalog, a field of a structure declared in another module, the value
# of a component the paired markup declares. So this half of the module answers a `TypeSet`, and
# it looks project names up in a `ProjectCatalog`.
#
# One reading serves every rule that asks, at two reaches. Over the whole project the facts of
# every file build the catalog (`project_fact`, `project_typings`); over one file only the module
# and its paired yaml are known (`file_typing`), which is what a check has on every keystroke of
# the editor. The file reach keeps a written name it cannot resolve as it is written - there only
# the empty value of a type is judged, not its relations - and reads no bare name as a type or an
# element of the project: an object of that name would be out of its sight.
#
# The rule of the upper half stands here too: what cannot be named answers None, and a caller
# that gets None stays silent. A set is never "probably" a type.


@dataclass(frozen=True)
class TypeSet:
    """A type as a set: the nominal types, the empty value and the Null of a query.

    `names` holds CANONICAL nominal texts: a platform name in the catalog's own (Russian)
    spelling, a project name as the project writes it (a structure qualified by its module),
    the arguments of a generic canonical too. Two sets are the same type exactly when they are
    equal, and that is what the comparisons of the rules turn on.
    """

    names: frozenset[str] = frozenset()
    undefined: bool = False
    null: bool = False

    @property
    def size(self) -> int:
        return len(self.names) + int(self.undefined) + int(self.null)

    @property
    def single(self) -> bool:
        return self.size == 1

    def without_undefined(self) -> "TypeSet":
        return TypeSet(self.names, False, self.null)

    def without_null(self) -> "TypeSet":
        return TypeSet(self.names, self.undefined, False)

    def with_undefined(self) -> "TypeSet":
        return TypeSet(self.names, True, self.null)

    def union(self, other: "TypeSet") -> "TypeSet":
        return TypeSet(self.names | other.names, self.undefined or other.undefined,
                       self.null or other.null)

    def text(self) -> str:
        """The canonical spelling: `Строка?`, `Строка|Число|?`, the names sorted."""
        names = sorted(self.names)
        if len(names) == 1 and self.undefined and not self.null:
            return names[0] + "?"
        parts = names + (["?"] if self.undefined else []) + (["Null"] if self.null else [])
        return "|".join(parts)

    @classmethod
    def of(cls, *names: str, undefined: bool = False) -> "TypeSet":
        return cls(frozenset(names), undefined)


# --- written types ----------------------------------------------------------------------------

#: The empty value spelled as a type (`Строка|Неопределено` is `Строка?`), both languages.
_UNDEFINED_NAMES = frozenset({"Неопределено", "Undefined"})

#: One token of a written type: a name (a namespace qualifier and a facet included), a bracket,
#: a separator or the nullable marker.
_TYPE_TOKEN_RE = re.compile(
    r"\s*(?:([#A-Za-zА-Яа-яЁё_][\wЁё]*(?:\s*(?:::|\.)\s*[A-Za-zА-Яа-яЁё_][\wЁё]*)*)|([<>,|?]))")


def split_nominal(text: str) -> tuple[str, tuple[str, ...]]:
    """`Map<String,Number>` -> (`Map`, (`String`, `Number`)): the head and the
    arguments of a canonical nominal text, split at the top level."""
    if not text.endswith(">") or "<" not in text:
        return text, ()
    return text.split("<", 1)[0], _type_arguments(text)


def parse_type(text: str | None, resolve, bindings: dict[str, TypeSet] | None = None,
               unbound: frozenset[str] = frozenset()) -> TypeSet | None:
    """The set a written type stands for, or None when a part of it cannot be named.

    `resolve(name)` answers the canonical head of one name (an English platform name -> the
    catalog's spelling, a structure of the module -> `Модуль.Структура`) or None; a single name
    it cannot resolve makes the whole type unknown - a union of a known and an unknown type is
    not the known one. `bindings` puts a set in place of a type parameter (`ValueType` of a
    `Map<String, Number>` receiver), and `unbound` names the parameters nothing binds:
    meeting one of them makes the whole type unknown, whatever `resolve` says about the word.
    """
    if not text or not text.strip():
        return None
    tokens: list[tuple[str, str]] = []
    pos = 0
    stripped = text.strip()
    while pos < len(stripped):
        match = _TYPE_TOKEN_RE.match(stripped, pos)
        if match is None or match.end() == pos:
            return None
        if match.group(1):
            tokens.append(("name", re.sub(r"\s+", "", match.group(1))))
        else:
            tokens.append(("op", match.group(2)))
        pos = match.end()
    parser = _TypeTextParser(tokens, resolve, bindings or {}, unbound)
    got = parser.union()
    if got is None or parser.pos != len(tokens):
        return None
    return got


class _TypeTextParser:
    """Recursive descent over the tokens of a written type (see parse_type)."""

    def __init__(self, tokens: list[tuple[str, str]], resolve, bindings: dict[str, TypeSet],
                 unbound: frozenset[str]) -> None:
        self.tokens = tokens
        self.pos = 0
        self.resolve = resolve
        self.bindings = bindings
        self.unbound = unbound

    def peek(self) -> tuple[str, str] | None:
        return self.tokens[self.pos] if self.pos < len(self.tokens) else None

    def union(self) -> TypeSet | None:
        got = self.alternative()
        if got is None:
            return None
        while self.peek() == ("op", "|"):
            self.pos += 1
            more = self.alternative()
            if more is None:
                return None
            got = got.union(more)
        return got

    def alternative(self) -> TypeSet | None:
        token = self.peek()
        if token is None:
            return None
        if token == ("op", "?"):
            self.pos += 1
            return TypeSet(undefined=True)
        if token[0] != "name":
            return None
        self.pos += 1
        word = token[1]
        if word in self.unbound:
            return None
        bound = self.bindings.get(word)
        if bound is not None:
            if self.peek() == ("op", "<"):
                return None  # a type parameter takes no arguments of its own
            got = bound
        elif word in _UNDEFINED_NAMES:
            got = TypeSet(undefined=True)
        else:
            head = self.resolve(word)
            if head is None:
                return None
            arguments: list[str] = []
            if self.peek() == ("op", "<"):
                self.pos += 1
                while True:
                    argument = self.union()
                    if argument is None:
                        return None
                    arguments.append(argument.text())
                    if self.peek() == ("op", ","):
                        self.pos += 1
                        continue
                    break
                if self.peek() != ("op", ">"):
                    return None
                self.pos += 1
            name = f"{head}<{','.join(arguments)}>" if arguments else head
            got = TypeSet.of(name)
        if self.peek() == ("op", "?"):
            self.pos += 1
            got = got.with_undefined()
        return got


def cast_verdict(source: TypeSet, target: TypeSet, assignable) -> str | None:
    """What the compiler says about `<операнд> как <тип>`: "redundant", "insistent" or None.

    The behaviour of the compiler, each branch shown on the probe project of the cast rules:

    - the cast is worth a word only when the target can hold every value of the operand. Each
      type of the operand must be assignable to some type of the target; the empty value of an
      operand of SEVERAL types is skipped there - the cast is what drops it;
    - and then, when the operand is several types, the empty value among them, and without it the
      operand is exactly the target, the only thing the cast does is to take the empty value
      away - the compiler advises `!`; otherwise the cast is redundant.

    `assignable(source_name, target_name)` answers for two canonical nominal texts and must say
    True only when it knows: an unknown relation reads as "not assignable", and a cast the
    module cannot prove redundant is never called redundant. An operand that is nothing but the
    empty value is left alone - the compiler judges its common inheritor first and reports an
    error rather than either warning.
    """
    if not source.names and not source.null:
        return None
    if source.undefined and not source.single and source.without_undefined() == target:
        return "insistent"
    if source.null and not target.null:
        return None
    if source.undefined and source.single and not target.undefined:
        return None
    for name in source.names:
        if not any(assignable(name, wanted) for wanted in target.names):
            return None
    return "redundant"


def always_holds(types: TypeSet, check: TypeSet, assignable) -> bool:
    """Whether every value of `types` passes `это <check>`: the result of the check is known.

    Each type of the set must be assignable to a checked one, and the empty value is checked for
    when the expression may hold it; Null, which no written type holds, fails the check. The
    relation is the one `cast_verdict` takes, and it says True only when it knows.
    """
    if not types.names or types.null:
        return False
    if types.undefined and not check.undefined:
        return False
    return all(any(assignable(name, wanted) for wanted in check.names) for name in types.names)


# --- the platform side of a type set ---------------------------------------------------------

#: The root of the type hierarchy: every value is an `Object`, and the catalog lists it as no
#: base of anything only because it is the base of everything.
_ROOT_TYPE = "Объект"

#: The collection every iterable inherits, and the name its element parameter carries.
_ITERABLE = "Обходимое"
_ELEMENT_PARAM = "ТипЭлемента"

#: A type-name word: an identifier with optional dotted facets (`Товары.Ссылка`).
_NAME_RE = re.compile(
    r"[A-Za-zА-Яа-яЁё_][0-9A-Za-zА-Яа-яЁё_]*(?:\.[A-Za-zА-Яа-яЁё_][0-9A-Za-zА-Яа-яЁё_]*)*"
)

#: Words of a written type that name no type a rule could compare: the unknown type, the result
#: of a procedure, the result of a method that never returns.
_NO_TYPE_WORDS = frozenset({"неизвестно", "unknown", "ничто", "void", "никогда", "never"})


def platform_head(name: str) -> str | None:
    """The canonical spelling of a platform type or facet, or None when the catalog has none.

    The catalog keys a type under both spellings, so an English name is known as well; the
    canonical form is the Russian one, the spelling every member result of the catalog uses.
    """
    catalog = _catalog()
    known = (name in (catalog.get("type_members") or {}) or name in (catalog.get("member_types") or {})
             or name in (catalog.get("bases") or {}) or name in (catalog.get("type_params") or {}))
    if not known:
        return None
    from xbsl import terms

    return terms.russian(name, "types") or terms.russian(name, "facets") or name


def _platform_bases(head: str) -> tuple[str, ...]:
    return tuple((_catalog().get("bases") or {}).get(head) or ())


def _platform_params(head: str) -> tuple[str, ...]:
    return tuple((_catalog().get("type_params") or {}).get(head) or ())


@lru_cache(maxsize=1)
def _facet_suffixes() -> dict[str, str]:
    """{English facet suffix: Russian}, built from the facet pairs (`BinaryObject.Reference`).

    A suffix two facets spell differently is dropped rather than guessed.
    """
    from xbsl import terms

    table: dict[str, str] = {}
    dropped: set[str] = set()
    for russian, english in terms._terms().get("facets", {}).items():
        if "." not in russian or "." not in english:
            continue
        ru_suffix, en_suffix = russian.rsplit(".", 1)[1], english.rsplit(".", 1)[1]
        if en_suffix in dropped:
            continue
        known = table.get(en_suffix)
        if known is not None and known != ru_suffix:
            del table[en_suffix]
            dropped.add(en_suffix)
            continue
        table[en_suffix] = ru_suffix
    return table


@lru_cache(maxsize=None)
def canonical_name(word: str) -> str | None:
    """One type-name word as written, in its canonical spelling; None when it names nothing.

    What the file reach keeps of a name the project would resolve: the platform reads a project
    in either language, so a type is one type in both spellings and must compare equal. The
    pairs come from the term dictionary (types and facets) and, for a component of a form, from
    the ui schema; a project name has one spelling and is kept.
    """
    from xbsl import terms, uischema

    if word in _NO_TYPE_WORDS or not _NAME_RE.fullmatch(word):
        return None
    whole = terms.russian(word, "types") or terms.russian(word, "facets")
    if whole:
        return whole
    head, dot, tail = word.partition(".")
    if not dot:
        return uischema.canonical_component(word)
    if "." in tail:
        return word
    return f"{terms.russian(head, 'types') or head}.{_facet_suffixes().get(tail, tail)}"


@lru_cache(maxsize=None)
def _member_names(head: str) -> dict[str, str]:
    """{a spelling of a member: the catalog's name} for the members of a platform type.

    The catalog keeps members in Russian while a translated module writes them in English. The
    English spellings come from the type's own vocabularies, and one spelling two members share
    is dropped: an ambiguous word answers nothing. A member the catalog types without listing it
    among the properties and methods of its type (the facets carry such) counts as well.
    """
    from xbsl import terms
    from xbsl.rules.unknown_members import _member_english

    catalog = _catalog()
    record = (catalog.get("type_members") or {}).get(head) or {}
    own = [*(record.get("properties") or ()), *(record.get("methods") or ())]
    listed = set(own)
    own += [name for name in ((catalog.get("member_types") or {}).get(head) or {}) if name not in listed]
    table: dict[str, str] = {name: name for name in own}
    english: dict[str, set[str]] = {}
    for name in own:
        for spelling in (terms.member_english_of(head, name), _member_english(head, name)):
            if spelling and spelling != name:
                english.setdefault(spelling, set()).add(name)
    for spelling, names in english.items():
        if len(names) == 1 and spelling not in table:
            table[spelling] = next(iter(names))
    return table


def _split_params(text: str) -> list[str] | None:
    """The parameters of a printed signature, split at the top level only.

    A default value may be a string with commas in it, and a parameter of a function type
    carries its own parentheses and angle brackets.
    """
    parts: list[str] = []
    depth, current, quoted = 0, "", False
    for index, char in enumerate(text):
        if quoted:
            current += char
            if char == '"':
                quoted = False
            continue
        if char == '"':
            quoted = True
        elif char in "(<":
            depth += 1
        elif char == ")" or (char == ">" and text[index - 1: index] != "-"):
            depth -= 1
        elif char == "," and depth == 0:
            parts.append(current.strip())
            current = ""
            continue
        current += char
    if depth != 0 or quoted:
        return None
    if current.strip():
        parts.append(current.strip())
    return parts


@lru_cache(maxsize=None)
def _signature(text: str) -> tuple[int, int, str | None, bool] | None:
    """(fewest arguments, most arguments, the written result, generic) of a printed signature."""
    open_at = text.find("(")
    if open_at <= 0:
        return None
    generic = "<" in text[:open_at]
    depth, close_at = 0, -1
    quoted = False
    for index in range(open_at, len(text)):
        char = text[index]
        if quoted:
            quoted = char != '"'
            continue
        if char == '"':
            quoted = True
        elif char == "(":
            depth += 1
        elif char == ")":
            depth -= 1
            if depth == 0:
                close_at = index
                break
    if close_at < 0:
        return None
    params = _split_params(text[open_at + 1: close_at])
    if params is None:
        return None
    tail = text[close_at + 1:].strip()
    result = tail[1:].strip() if tail.startswith(":") else None
    fewest = most = 0
    for param in params:
        if param.startswith("..."):
            most = 10_000
            continue
        most += 1
        if not _has_default(param):
            fewest += 1
    return fewest, most, result or None, generic


def _has_default(param: str) -> bool:
    depth, quoted = 0, False
    for index, char in enumerate(param):
        if quoted:
            quoted = char != '"'
            continue
        if char == '"':
            quoted = True
        elif char in "(<":
            depth += 1
        elif char == ")" or (char == ">" and param[index - 1: index] != "-"):
            depth -= 1
        elif char == "=" and depth == 0:
            return True
    return False


#: Properties the documentation itself prints as plain while the editor's language server does not
#: treat them as never empty. Every property and argument-less method the catalog calls plain was
#: put through the editor behind `??` (about 8,700 members), and with the struck forms of older
#: versions no longer read as current this one is the only disagreement left: no reading of the data
#: explains it. Pairs are (the declaring type, the member) in the catalog's spelling.
_DISPUTED_PROPERTIES = frozenset({("ОбсуждениеВзаимодействия", "ИдВнешнегоОбсуждения")})


def _trusted_plain(owner: str, member: str) -> bool:
    """Whether a property the catalog calls plain can be trusted to hold no empty value.

    A page that prints a property for several platform versions (`TableReflection?` for the
    current one, `TableReflection` under a struck heading for an old one) used to be folded into the
    bare head of the type, and the empty value of the current form got lost with it. The extractor
    reads the forms of the current version since `meta.member_forms` says "current"; a catalog
    without the marker is not trusted with plain properties at all.
    """
    if (_catalog().get("meta") or {}).get("member_forms") != "current":
        return False
    bases = (_catalog().get("bases") or {}).get(owner) or ()
    return not any((holder, member) in _DISPUTED_PROPERTIES for holder in (owner, *bases))


def _type_param_bindings(head: str, args: tuple[str, ...], resolve) -> dict[str, TypeSet] | None:
    """{type parameter: the set its argument names} for a generic written with its arguments.

    The own parameters bind by position. An inherited member speaks the language of the base
    that declares it - a query result answers `ПервыйИлиНеопределено(): ТипЭлемента?`, while
    the result type itself is written with `QueryResultRowType` - so a collection of
    ONE argument also binds the element parameter of the iterable it inherits. A collection of
    two arguments does not: the element of a map is a key-and-value pair, and nothing in the
    data says so, which leaves that parameter unbound and the member unknown. A generic written
    without its arguments binds nothing and types no member at all.
    """
    params = _platform_params(head)
    if not args:
        return {} if not params else None
    if len(params) != len(args):
        return None
    bindings: dict[str, TypeSet] = {}
    for param, argument in zip(params, args):
        got = parse_type(argument, resolve)
        if got is None:
            return None
        bindings[param] = got
    if len(params) == 1 and _ITERABLE in _platform_bases(head) and _ELEMENT_PARAM not in bindings:
        bindings[_ELEMENT_PARAM] = bindings[params[0]]
    return bindings


def _bound_by_default(component: TypeSet) -> bool:
    """Whether every argument of a component type is nullable or a type of the catalog.

    The type parameter of a value component must have a default value or hold the empty value
    (the documentation of the input field says so), and the editor refuses a markup that breaks
    it - then it warns about nothing in that module. A project type without `?` is the shape of
    that refusal, so such a component is left untyped rather than read as never empty.
    """
    types = _catalog().get("type_members") or {}
    for name in component.names:
        _head, args = split_nominal(name)
        for text in args:
            argument = parse_type(text, lambda word: word)
            if argument is None:
                return False
            if argument.undefined:
                continue
            if any(split_nominal(part)[0] not in types for part in argument.names):
                return False
    return True


# --- the project catalog ----------------------------------------------------------------------

#: The facets of an element whose values carry the element's own attributes.
_DATA_FACETS = frozenset({"Объект", "Данные", "Запись"})

#: Element kinds whose own name is a type carrying its fields (the structure itself).
_STRUCTURE_KINDS = frozenset({"Структура", "ХранимаяСтруктура"})

#: The fields an element carries WITHOUT declaring them, by kind; `{}` stands for the name of
#: the element. Filled only with what the compiler was shown to answer (see the probe project of
#: the cast rules); a field missing here stays unknown.
STANDARD_FIELDS: dict[str, dict[str, str]] = {
    "Справочник": {"Ссылка": "{}.Ссылка", "ПометкаУдаления": "Булево"},
    "Документ": {"Ссылка": "{}.Ссылка", "ПометкаУдаления": "Булево"},
    "КонтрактСущности": {"Ссылка": "{}.Ссылка"},
}

#: The type of a standard attribute DECLARED without one (`- Имя: Наименование` with a length
#: only). Undeclared, such an attribute does not exist at all - the compiler answers
#: `Реквизит ... не найден` for the code of an element that never declared it.
DECLARED_STANDARD_TYPES: dict[str, dict[str, str]] = {
    "Справочник": {"Наименование": "Строка"},
}

#: The key of a dynamic list row as the catalog spells it: by the row type parameter.
_ROW_KEY_RE = re.compile(r"([\wЁё]+)\.RowDataKeyType(\?)?")

#: The standard attributes of a tabular section row, `{}` standing for the owner element.
TABULAR_STANDARD_FIELDS: dict[str, str] = {"Владелец": "{}.Ссылка", "НомерСтроки": "Число"}


class ProjectCatalog:
    """The project names the type of an expression may need.

    Built from plain facts (see `element_fact` and `module_fact`, which read them off the
    sources):

    - `elements` - `{name: {"kind", "attributes", "tabular", "dimensions", "resources",
      "properties", "fields", "values", "contracts", "row_keys", "components"}}`, every member
      section `{name: written type or None}` (None: a standard attribute written without a type);
    - `modules` - `{module: {"methods": {name: [written result per overload]}, "structures":
      {name: {"fields": {...}, "methods": {...}}}, "enums": {name: [values]}, "fields": {...}}}`,
      the module named by its file (`Товары` for `Товары.xbsl`).

    `open_world` is the file reach: a written name the facts do not resolve is kept in its
    canonical spelling instead of making the type unknown (see `canonical_name`).

    Answers are canonical texts and TypeSets (see TypeSet); every lookup the facts do not settle
    answers None.
    """

    def __init__(self, elements: dict[str, dict] | None = None,
                 modules: dict[str, dict] | None = None, *, open_world: bool = False) -> None:
        self.elements: dict[str, dict] = dict(elements or {})
        self.modules: dict[str, dict] = dict(modules or {})
        self.open_world = open_world
        self.rows: dict[str, dict[str, TypeSet | None]] = {}
        self._members: dict[tuple, TypeSet | None] = {}
        # {row data type of a dynamic list (`Форма.ДанныеСтроки`): the list's main table}
        self.row_keys: dict[str, str] = {
            row: table
            for element in self.elements.values()
            for row, table in (element.get("row_keys") or {}).items()
        }
        self._written: dict[tuple[str, str | None], TypeSet | None] = {}

    # -- names -----------------------------------------------------------------------------

    def resolver(self, module: str | None, strict: bool = False):
        """The name resolver of written types as seen from `module` (None: from a yaml).

        `strict` keeps the open world out: a type the platform catalog prints names nothing but
        its own types and the parameters it binds, whatever reach reads it."""
        def resolve(name: str) -> str | None:
            got = self.head(name, module)
            if got is None and self.open_world and not strict:
                got = canonical_name(name.rsplit("::", 1)[-1])
            return got
        return resolve

    def head(self, name: str, module: str | None) -> str | None:
        """The canonical head of one name of a written type, or None."""
        if name.startswith("#"):
            return name if name in self.rows else None
        if "::" in name:
            name = name.rsplit("::", 1)[1]
        first, dot, rest = name.partition(".")
        if not dot:
            own = self.modules.get(module or "") or {}
            if name in (own.get("structures") or {}) or name in (own.get("enums") or {}):
                return f"{module}.{name}"
            if name in self.elements:
                return name
            return platform_head(name)
        if "." in rest:
            return None
        if first in self.elements or first in self.modules:
            return f"{first}.{_facet_russian(rest)}"
        return platform_head(name)

    def written(self, text: str | None, module: str | None) -> TypeSet | None:
        """The set a type written in `module` (or in a yaml, module None) stands for."""
        if not text:
            return None
        key = (text, module)
        if key not in self._written:
            self._written[key] = parse_type(text, self.resolver(module))
        return self._written[key]

    # -- relations -------------------------------------------------------------------------

    def assignable(self, source: str, target: str) -> bool:
        """Whether a value of the canonical type `source` is a value of `target` - True only
        when the catalog or the project says so."""
        if source == target or target == _ROOT_TYPE:
            return True
        source_head, source_args = split_nominal(source)
        target_head, target_args = split_nominal(target)
        owner, dot, facet = source_head.partition(".")
        if dot and not source_args and not target_args and owner in self.elements:
            contract, contract_dot, contract_facet = target_head.partition(".")
            if contract_dot and contract_facet == facet and contract in self.contracts_of(owner):
                return True
            return False
        if source_args != target_args:
            return False
        if target_head not in _platform_bases(source_head):
            return False
        return len(_platform_params(target_head)) == len(source_args)

    def contracts_of(self, element: str) -> frozenset[str]:
        """The entity contracts an element implements, by the contract's element name."""
        contracts = (self.elements.get(element) or {}).get("contracts") or ()
        return frozenset(written.split("::")[-1].partition(".")[0] for written in contracts)

    # -- members -----------------------------------------------------------------------------

    def member(self, owner: str, name: str, called: bool, argc: int | None = None) -> TypeSet | None:
        """The type of `<value of owner>.name` (a call of it when `called`).

        `argc` is the number of arguments of the call; None when they cannot be counted (a
        named argument) - then every overload must agree on the result."""
        key = (owner, name, called, argc)
        if key not in self._members:
            self._members[key] = self._member(owner, name, called, argc)
        return self._members[key]

    def _member(self, owner: str, name: str, called: bool, argc: int | None) -> TypeSet | None:
        head, _args = split_nominal(owner)
        if head in self.rows:
            return None if called else self.rows[head].get(name)
        first, dot, rest = head.partition(".")
        if dot and first in self.modules and rest in (self.modules[first].get("structures") or {}):
            structure = self.modules[first]["structures"][rest]
            if called:
                return self._overloads((structure.get("methods") or {}).get(name), first)
            written = (structure.get("fields") or {}).get(name)
            return self.written(written, first) if written else None
        element = self.elements.get(head)
        if element is not None and element.get("kind") in _STRUCTURE_KINDS:
            written = (element.get("fields") or {}).get(name)
            if written and not called:
                return self.written(written, None)
            return self._module_method_of(head, name) if called else None
        if dot and first in self.elements:
            return self._facet_member(first, rest, name, called)
        return self.platform_member(owner, name, called, argc)

    def platform_member(self, owner: str, name: str, called: bool,
                        argc: int | None = None) -> TypeSet | None:
        """A member of a platform type, the arguments of a generic receiver bound.

        A property is typed by the catalog; a call by the printed signatures of the overloads
        whose arity admits the arguments, and only when they agree on the result - a method the
        documentation prints no signature for is typed by the catalog like a property. A type
        parameter of the method itself binds nothing here, and a result that names one is
        unknown. A property the catalog calls plain is trusted only as far as its documentation
        catalog was extracted with the forms of the current version (see `_trusted_plain`)."""
        head, args = split_nominal(owner)
        member = _member_names(head).get(name)
        if member is None:
            return None
        catalog = _catalog()
        record = (catalog.get("type_members") or {}).get(head) or {}
        is_property = member in (record.get("properties") or ())
        is_method = member in (record.get("methods") or ())
        if called and is_property and not is_method:
            return None
        if not called and is_method and not is_property:
            return None
        # The arguments of the receiver are names the source wrote, read at the reach of the
        # catalog; the result the catalog prints names platform types and parameters only.
        bindings = _type_param_bindings(head, args, self.resolver(None))
        if bindings is None:
            return None
        resolve = self.resolver(None, strict=True)
        unbound = frozenset(((catalog.get("member_type_params") or {}).get(head) or {}).get(member) or ())
        signatures = ((catalog.get("member_signatures") or {}).get(head) or {}).get(member) or ()
        if called and signatures:
            results: set[str | None] = set()
            for signature in signatures:
                shape = _signature(signature)
                if shape is None:
                    return None
                fewest, most, result, _generic = shape
                if argc is not None and not fewest <= argc <= most:
                    continue
                results.add(result)
            if len(results) != 1:
                return None
            written = results.pop()
        else:
            written = ((catalog.get("member_types") or {}).get(head) or {}).get(member)
        if not written:
            return None
        key = _ROW_KEY_RE.fullmatch(written)
        if key is not None:
            return self._row_key(bindings.get(key.group(1)), bool(key.group(2)))
        got = parse_type(written, resolve, bindings, unbound)
        if got is not None and not got.undefined and not called and not _trusted_plain(head, member):
            return None
        return got

    def _row_key(self, row: TypeSet | None, nullable: bool) -> TypeSet | None:
        """The key of a dynamic list row: a reference of the list's main table.

        The catalog spells it by the row type (`ТипДанныхСтроки.RowDataKeyType`), and only the
        form that declares the row type says which table stands behind it. Answered for a
        catalog and a document - the tables whose key the compiler was shown to call a reference.
        """
        if row is None or row.size != 1 or not row.names:
            return None
        table = self.row_keys.get(next(iter(row.names)))
        element = self.elements.get(table or "")
        if element is None or element.get("kind") not in ("Справочник", "Документ"):
            return None
        return TypeSet(frozenset({f"{table}.Ссылка"}), nullable)

    def _facet_member(self, element_name: str, facet: str, name: str,
                      called: bool) -> TypeSet | None:
        element = self.elements[element_name]
        kind = element.get("kind") or ""
        if facet in _DATA_FACETS and not called:
            written = self.field_written(element_name, name)
            if written is not _MISSING_FIELD:
                return self.written(written, None) if written else None
        written = ((_catalog().get("member_types") or {}).get(f"{kind}.{facet}") or {}).get(name)
        if not written:
            return None
        return self.written(written.replace(kind, element_name, 1), None)

    def field_written(self, element_name: str, name: str):
        """The written type of an own field of an element (attribute, dimension, resource,
        property), None for a standard attribute written without a type, or _MISSING_FIELD."""
        element = self.elements.get(element_name) or {}
        for section in ("attributes", "dimensions", "resources", "properties"):
            fields = element.get(section) or {}
            if name in fields:
                written = fields[name]
                if written is None:
                    kind = element.get("kind") or ""
                    standard = (DECLARED_STANDARD_TYPES.get(kind, {}).get(name)
                                or STANDARD_FIELDS.get(kind, {}).get(name))
                    return standard.replace("{}", element_name) if standard else None
                return written
        standard = STANDARD_FIELDS.get(element.get("kind") or "", {}).get(name)
        if standard:
            return standard.replace("{}", element_name)
        return _MISSING_FIELD

    def static_member(self, name: str, member: str, called: bool,
                      module: str | None, argc: int | None = None) -> TypeSet | None:
        """`<name>.<member>` where the name itself is a project element or module."""
        own = self.modules.get(module or "") or {}
        if member in (own.get("enums") or {}).get(name, ()):
            return TypeSet.of(f"{module}.{name}")
        # an enumeration of a module, named with its module (`Module.Color.Red`, and the bare
        # `Color` inside that module resolves to the same qualified name)
        owner, dot, enum = name.partition(".")
        if dot and not called and member in ((self.modules.get(owner) or {}).get("enums") or {}).get(enum, ()):
            return TypeSet.of(name)
        element = self.elements.get(name)
        if element is not None and element.get("kind") == "Перечисление" and not called:
            if member in (element.get("values") or ()):
                return TypeSet.of(name)
        if name in self.modules:
            enums = self.modules[name].get("enums") or {}
            if not called and member in enums:
                return None
            if called:
                got = self._module_method_of(name, member)
                if got is not None:
                    return got
        if element is not None and called:
            generated = _manager_types().get(element.get("kind") or "", {}).get(member)
            if generated:
                return self.written(generated.replace("{}", name), None)
        return None

    def _module_method_of(self, module: str, method: str) -> TypeSet | None:
        return self._overloads(((self.modules.get(module) or {}).get("methods") or {}).get(method),
                               module)

    def own_method(self, module: str | None, method: str) -> TypeSet | None:
        return self._module_method_of(module or "", method)

    def _overloads(self, results, module: str | None) -> TypeSet | None:
        """The result of a method by its overloads: known only when they all agree."""
        if not results:
            return None
        distinct = set(results)
        if len(distinct) != 1:
            return None
        written = next(iter(distinct))
        return self.written(written, module) if written else None

    def structure_method(self, owner: TypeSet | None, method: str) -> tuple[bool, TypeSet | None]:
        """(whether the structure `owner` declares the method, its result) - a bare call inside
        a method of a structure reaches the structure's own methods first."""
        if owner is None or len(owner.names) != 1:
            return False, None
        first, dot, rest = next(iter(owner.names)).partition(".")
        structure = ((self.modules.get(first) or {}).get("structures") or {}).get(rest) if dot else None
        if structure is None or method not in (structure.get("methods") or {}):
            return False, None
        return True, self._overloads(structure["methods"][method], first)

    def indexed(self, collection: TypeSet) -> TypeSet | None:
        """`Массив<Т>[i]` is a `Т`, `Соответствие<К, З>[к]` a `З` - the two indexers the compiler was
        shown to type (not an empty value: the index of a map that has no such key throws)."""
        if collection.size != 1 or not collection.names:
            return None
        head, args = split_nominal(next(iter(collection.names)))
        if head == "Массив" and len(args) == 1:
            return parse_type(args[0], self.resolver(None))
        if head == "Соответствие" and len(args) == 2:
            return parse_type(args[1], self.resolver(None))
        return None

    def element_of(self, collection: TypeSet) -> TypeSet | None:
        """One element of a collection set: the rows of a query result, the items of an array.

        Answered for a type of the catalog whose only parameter is the element type and which is
        iterable (`Iterable` among its bases). A map hands out `KeyAndValue<...>`, and nothing in
        the data pairs the two - so a map, like anything else, answers None."""
        if collection.size != 1 or not collection.names:
            return None
        head, args = split_nominal(next(iter(collection.names)))
        if len(args) != 1:
            return None
        params = _platform_params(head)
        if len(params) != 1 or (head != _ITERABLE and _ITERABLE not in _platform_bases(head)):
            return None
        return parse_type(args[0], self.resolver(None))

    def register_row(self, key: str, columns: dict[str, TypeSet | None]) -> str:
        self.rows[key] = columns
        return key


_MISSING_FIELD = object()


def _facet_russian(suffix: str) -> str:
    """A facet suffix in the canonical spelling: the English `Reference` -> the Russian one."""
    from xbsl import terms

    for russian in ("Ссылка", "Объект", "Запись", "Данные", "КлючЗаписи", "НаборЗаписей"):
        if suffix == russian or terms.facet_suffix_english(russian) == suffix:
            return russian
    return suffix


def _manager_types() -> dict[str, dict[str, str]]:
    """{kind: {generated static method: result with `{}` for the element}} from the catalog."""
    return dict(_catalog().get("manager_member_types") or {})


# --- the facts of the sources -------------------------------------------------------------------

#: The project descriptor: its folder is the boundary of one catalog.
_PROJECT_FILES = frozenset({"Проект.yaml", "Project.yaml"})

#: The element kind whose yaml is the markup of a component, and both spellings of the root
#: through which a component module reaches the named nodes of that markup.
_COMPONENT_KIND = "КомпонентИнтерфейса"
COMPONENT_ROOTS = frozenset({"Компоненты", "Components"})


def _first_of(node: dict, *names: str):
    from xbsl import terms

    for name in terms.key_forms(*names):
        if name in node:
            return node[name]
    return None


def _typed_members(data: dict, key: str, kind: str | None) -> dict[str, str | None]:
    """{name: written type or None} of a list section of an element (`Attributes` and the like)."""
    from xbsl.rules.yaml_schema import value_of

    items = value_of(data, key, kind)
    out: dict[str, str | None] = {}
    if not isinstance(items, list):
        return out
    for item in items:
        if not isinstance(item, dict):
            continue
        name = _first_of(item, "Имя")
        if not isinstance(name, str) or not name:
            continue
        written = _first_of(item, "Тип")
        out[name] = written.strip() if isinstance(written, str) and written.strip() else None
    return out


def _contracts(data: dict, kind: str | None) -> list[str]:
    """The entity contracts the element lists under its type settings, as written."""
    from xbsl.rules.yaml_schema import value_of

    settings = value_of(data, "НастройкиТипов", kind)
    out: list[str] = []
    if not isinstance(settings, dict):
        return out
    for facet in settings.values():
        if not isinstance(facet, dict):
            continue
        listed = _first_of(facet, "Контракты")
        if isinstance(listed, list):
            out.extend(item.strip() for item in listed if isinstance(item, str) and item.strip())
    return out


def _row_keys(data: dict, element: str) -> dict[str, str]:
    """{row data type of a dynamic list: its main table} declared anywhere in the element.

    A form names the row type of its list (`RowDataTypeName`) next to the table the list
    reads (`MainTable.Table`), and the key of such a row is a reference of that table:
    `Параметр.Ключ как Задачи.Ссылка` in a row command is a redundant cast the compiler reports.
    """
    out: dict[str, str] = {}

    def walk(node) -> None:
        if isinstance(node, dict):
            row = _first_of(node, "ИмяТипаДанныхСтроки")
            main = _first_of(node, "ОсновнаяТаблица")
            if isinstance(row, str) and row.strip() and isinstance(main, dict):
                table = _first_of(main, "Таблица")
                if isinstance(table, str) and table.strip():
                    out[f"{element}.{row.strip()}"] = table.strip()
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for item in node:
                walk(item)

    walk(data)
    return out


def _yaml_names(node, out: set[str]) -> None:
    from xbsl import terms

    if isinstance(node, dict):
        for key in terms.key_forms("Имя"):
            value = node.get(key)
            if isinstance(value, str) and value:
                out.add(value)
        for value in node.values():
            _yaml_names(value, out)
    elif isinstance(node, list):
        for item in node:
            _yaml_names(item, out)


def _markup_nodes(node: object, name_keys: frozenset[str],
                  type_keys: frozenset[str]) -> Iterator[tuple[str, object]]:
    """(name, written type or None) of every named node of a markup tree."""
    if isinstance(node, dict):
        name = next((node[key] for key in name_keys if key in node), None)
        if isinstance(name, str) and name:
            yield name, next((node[key] for key in type_keys if key in node), None)
        for value in node.values():
            yield from _markup_nodes(value, name_keys, type_keys)
    elif isinstance(node, list):
        for item in node:
            yield from _markup_nodes(item, name_keys, type_keys)


def _markup_components(data: dict, kind: str | None) -> dict[str, list[str | None]] | None:
    """{component name: its written types} of the markup of a component, None for other kinds.

    Every named node of the markup is reachable through the root, at any depth (the evidence is
    in `form_components.py`). A node whose type is a binding (`=...`) or not written counts as
    None, and every spelling a name is met with is kept: a name met with different types names
    no type at all (see `ModuleTyper`)."""
    from xbsl import terms
    from xbsl.rules.yaml_schema import value_of

    if kind != _COMPONENT_KIND:
        return None
    name_keys = frozenset(terms.key_forms("Имя"))
    type_keys = frozenset(terms.key_forms("Тип"))
    properties = value_of(data, "Свойства", kind)
    components: dict[str, list[str | None]] = {}
    for value in data.values():
        if value is properties:
            continue
        for name, written in _markup_nodes(value, name_keys, type_keys):
            entry = written if isinstance(written, str) and not written.startswith("=") else None
            spellings = components.setdefault(name, [])
            if entry not in spellings:
                spellings.append(entry)
    return components


def element_fact(source) -> dict | None:
    """The catalog facts of one element yaml (see ProjectCatalog), or None for another yaml."""
    from xbsl.rules.yaml_schema import _HAVE_YAML, _parsed, object_kind, value_of

    if not _HAVE_YAML:
        return None
    data, err = _parsed(source)
    if err is not None or not isinstance(data, dict):
        return None
    kind = object_kind(data)
    name = value_of(data, "Имя", kind)
    if not kind or not isinstance(name, str) or not name:
        return None
    tabular: dict[str, dict[str, str | None]] = {}
    parts = value_of(data, "ТабличныеЧасти", kind)
    if isinstance(parts, list):
        for part in parts:
            if not isinstance(part, dict):
                continue
            part_name = _first_of(part, "Имя")
            if isinstance(part_name, str) and part_name:
                tabular[part_name] = _typed_members(part, "Реквизиты", kind)
    values = _typed_members(data, "Элементы", kind) if kind == "Перечисление" else {}
    names: set[str] = set()
    _yaml_names(data, names)
    return {
        "name": name,
        "kind": kind,
        "attributes": _typed_members(data, "Реквизиты", kind),
        "dimensions": _typed_members(data, "Измерения", kind),
        "resources": _typed_members(data, "Ресурсы", kind),
        "properties": _typed_members(data, "Свойства", kind),
        "fields": _typed_members(data, "Поля", kind),
        "tabular": tabular,
        "values": sorted(values),
        "contracts": _contracts(data, kind),
        "row_keys": _row_keys(data, name),
        "names": sorted(names),
        "components": _markup_components(data, kind),
    }


def _written_ref(type_ref) -> str | None:
    text = getattr(type_ref, "text", None)
    return text.strip() if isinstance(text, str) and text.strip() else None


def module_fact(rel: str, tree: object) -> dict:
    """The catalog facts of one parsed module: its methods, structures, enumerations and fields."""
    from pathlib import PurePosixPath

    methods: dict[str, list[str | None]] = {}
    structures: dict[str, dict] = {}
    enums: dict[str, list[str]] = {}
    fields: dict[str, str | None] = {}
    for member in getattr(tree, "members", ()) or ():
        if isinstance(member, P.Method):
            methods.setdefault(member.name, []).append(_written_ref(member.return_type))
        elif isinstance(member, P.Structure):
            own_methods: dict[str, list[str | None]] = {}
            for inner in member.members:
                if isinstance(inner, P.Method):
                    own_methods.setdefault(inner.name, []).append(_written_ref(inner.return_type))
            structures[member.name] = {
                "fields": {f.name: _written_ref(f.type) for f in member.members
                           if isinstance(f, P.ObjectField)},
                "methods": own_methods,
            }
        elif isinstance(member, P.Enum):
            enums[member.name] = [item.name for item in member.items]
        elif isinstance(member, P.ObjectField):
            fields[member.name] = _written_ref(member.type)
    return {
        "module": PurePosixPath(rel.replace("\\", "/")).stem,
        "methods": methods,
        "structures": structures,
        "enums": enums,
        "fields": fields,
    }


def _typed_sites_in(source) -> bool:
    """Whether the module casts or checks a type at all: the keyword in code outside the queries.

    Read off the code tokens the other code rules already hold, not off a walk over the AST -
    the walk visits every node of every module to find that most modules have neither.
    """
    from xbsl.rules._syntax import code_tokens

    return any(t.kind == "KEYWORD" and t.canonical in ("AS", "IS") for t in code_tokens(source))


#: Further reasons for a module to carry its text into the reduce, besides the casts and the type
#: checks: a project rule that types sites of its own registers a test of the module here
#: (`wants_text`), and every rule of the typing keeps reducing ONE set of facts - a second set
#: with other texts would miss the memo of `project_typings` and type the project twice.
_TEXT_WANTED: list = []


def wants_text(test) -> None:
    """Register `test(source) -> bool`: a module it answers True for carries its text."""
    if test not in _TEXT_WANTED:
        _TEXT_WANTED.append(test)


def _compatibility_mode(data: dict) -> list[int] | None:
    """The compatibility mode a project description declares, as numbers; None when it is not one."""
    value = data.get("РежимСовместимости", data.get("CompatibilityMode"))
    if not isinstance(value, (str, int, float)):
        return None
    parts = str(value).strip().split(".")
    if not parts or not all(part.isdigit() for part in parts):
        return None
    return [int(part) for part in parts]


def project_fact(source) -> dict | None:
    """The per-file half of the project reach: what one file contributes to the catalog.

    A yaml gives its element, a module its declarations and - only when it casts or checks a
    type, the sites the project rules judge, or when a rule asked for it (`wants_text`) - its
    text: the reduce types the module there. A project description gives its folder and the
    compatibility mode it declares. Shared by every project rule that reads the typing (they
    reduce one set of facts, see `project_typings`), and cached on the source.
    """
    from pathlib import PurePosixPath

    from xbsl.engine import is_query_file
    from xbsl.rules.environment import _pair_stem
    from xbsl.rules.yaml_schema import _HAVE_YAML, _parsed

    cached = source.cache.get("typeinfer_fact")
    if cached is not None:
        return cached or None
    fact: dict | None = None
    path = source.rel.replace("\\", "/")
    if source.kind == "yaml" and _HAVE_YAML:
        if PurePosixPath(path).name in _PROJECT_FILES:
            fact = {"k": "project", "root": str(PurePosixPath(path).parent)}
            data, err = _parsed(source)
            mode = _compatibility_mode(data) if err is None and isinstance(data, dict) else None
            if mode:
                fact["compat"] = mode
        else:
            element = element_fact(source)
            if element is not None:
                fact = {"k": "yaml", "stem": _pair_stem(source.rel), "element": element}
    elif source.kind == "xbsl" and not is_query_file(source.path):
        tree, errors = P.parse(source)
        fact = {"k": "xbsl", "stem": _pair_stem(source.rel), **module_fact(source.rel, tree)}
        if not errors and (_typed_sites_in(source) or any(test(source) for test in _TEXT_WANTED)):
            fact["text"] = source.text
    if fact is not None:
        # What the reduce keys its memo by: the same facts twice (every project rule of the
        # typing reduces one set of facts) are typed once.
        import hashlib

        fact["digest"] = hashlib.sha1(source.text.encode("utf-8")).hexdigest()
        if "text" in fact and len(_parsed_texts) <= 512:
            # A reduce in this very process (a sequential run, the editor) reads the tree and the
            # tokens the other rules already hold instead of parsing the text again.
            from xbsl.lexer import tokens

            _parsed_texts[fact["digest"]] = (P.parse(source)[0], tokens(source))
    source.cache["typeinfer_fact"] = fact or {}
    return fact


def _own_names(stem: str, pairs: dict[str, dict],
               ) -> tuple[dict[str, str], frozenset[str], dict[str, list[str | None]] | None]:
    """What a module reads from its paired yaml: ({typed bare name: type}, opaque, components).

    An object module (`Товары.Объект.xbsl`) reads the attributes of its element by a bare name;
    the module of a component reads its properties, and its markup through the component root.
    Every other name of the paired yaml is something of the module whose type is not read here,
    and it must not resolve to a namesake elsewhere.
    """
    base, dot, facet = stem.rpartition(".")
    is_object = bool(dot) and facet in ("Объект", "Object")
    element = pairs.get(base) if is_object else pairs.get(stem)
    if element is None:
        return {}, frozenset(), None
    typed: dict[str, str] = {}
    components: dict[str, list[str | None]] | None = None
    if is_object:
        for name, written in (element.get("attributes") or {}).items():
            if written:
                typed[name] = written
    elif element.get("kind") == _COMPONENT_KIND:
        for name, written in (element.get("properties") or {}).items():
            if written:
                typed[name] = written
        components = element.get("components")
        if components is None:
            components = {}
    opaque = frozenset(set(element.get("names") or ()) - set(typed) - {element.get("name")})
    return typed, opaque, components


# --- typing the code of a module ---------------------------------------------------------------

#: A bare name in a value position that stands for a project element, a module or a platform
#: type - not a value: its members are the static ones.
@dataclass(frozen=True)
class StaticName:
    name: str


#: Lexer kinds of the literals and the types they name (the empty value is a set of its own).
_SET_LITERALS = {
    "STRING": "Строка", "NUMBER": "Число", "TRUE": "Булево", "FALSE": "Булево",
    "PATTERN": "Образец",
}

#: Operators whose result is a Boolean whatever the operands are (compared in lower case).
_LOGICAL_OPS = frozenset({"и", "или", "and", "or"})

#: The text of the operations a site stands on, a cheap test before a method is walked.
_CAST_TEXT_RE = re.compile(r"(?<![\w.])(?:как|as)(?!\w)")
_GUARD_TEXT_RE = re.compile(r"\?\?|\?\.|!(?!=)")
_CHECK_TEXT_RE = re.compile(r"(?<![\w.])(?:это|is)(?!\w)")


def _arithmetic(op: str, left, right) -> TypeSet | None:
    """The result of `+ - * / %` over two known values: numbers give a number, and `+` with a string
    on either side gives a string - the combinations the compiler was shown to answer."""
    number, string = TypeSet.of("Число"), TypeSet.of("Строка")
    if not (isinstance(left, TypeSet) and isinstance(right, TypeSet)):
        return None
    if left == number and right == number and op in ("+", "-", "*", "/", "%"):
        return number
    if op == "+" and string in (left, right) and {left, right} <= {string, number}:
        return string
    return None


@dataclass
class ModuleScope:
    """What the code of one module sees besides its own declarations.

    `module` - the module name (the file stem), `text` - its source (a query literal is typed
    from its text), `catalog` - the project, `own_properties` - `{name: written type}` the module
    reads by a bare name (the attributes of the paired yaml), `opaque` - further bare names that
    are something of the module whose type is not known (a command, a handler): such a name
    answers None rather than a same-named project element or platform type. `components` -
    the named nodes of the paired markup, `{name: written types}`, or None for a module that
    has no markup (then the component root means nothing). `static_names` - whether a bare name
    the module does not declare may stand for an element, a module or a platform type; the file
    reach keeps it off, since a project object of that name would be out of its sight.
    """

    module: str | None
    text: str
    catalog: ProjectCatalog
    own_properties: dict[str, str] = field(default_factory=dict)
    opaque: frozenset[str] = frozenset()
    this_type: TypeSet | None = None
    #: The lexer output of `text` when the caller has it; a query literal is read from it
    #: instead of being tokenized again.
    tokens: list | None = None
    components: dict[str, list[str | None]] | None = None
    static_names: bool = True


@dataclass
class CastSite:
    """One `<операнд> как <тип>` with what the module could say about both sides.

    The operand is typed by what its declarations say, not by what the code checked before the
    cast: the compiler does the same. Its cast check reads the static type of the operand, and
    none of the shapes that could narrow it - a comparison with the empty value in a condition,
    an early return on that value, a type test in a condition or in a ternary, a `!` earlier in
    the method, an assignment of a non-empty value - changes the verdict (shown on the probe
    project of the cast rules: each of them still answers "use `!`" for a nullable parameter).
    """

    node: object                 # the P.AsType node
    source: TypeSet | None       # the operand
    target: TypeSet | None       # the written type


@dataclass
class GuardSite:
    """One guard against the empty value: `А ?? Б` ("coalesce"), `Х!` ("insist") or `Х?.Член`
    ("safe"), with the set of its operand and, for `??`, of the default on the right. No
    narrowing here either: the editor warns by the static type of the operand."""

    node: object
    kind: str
    operand: object
    types: TypeSet | None
    right: TypeSet | None = None


@dataclass
class CallSite:
    """One call of a member by name, `<получатель>.Имя(...)`, with what the module could say about
    the receiver - a TypeSet, a StaticName for a type or an element used by its name, or None - and
    about every argument (its name for a named one, and its set or None)."""

    node: object                 # the P.Call node
    owner: object
    args: list[tuple[str | None, "TypeSet | None"]]


@dataclass
class CheckSite:
    """One `Х это [не] Тип` with the set of `Х` and of the checked type. The predicate form of
    `выбор Х когда это Тип` is a site of its own, and its operand is the subject of the choice."""

    node: object                 # the P.IsType node
    operand: object
    types: TypeSet | None
    check: TypeSet | None


class _Missing:
    """The method does not declare the name at all."""


class _Unknown:
    """The method declares the name, but not so that the place can see a single declaration."""


_MISSING = _Missing()
_UNKNOWN = _Unknown()


@cache
def _field_names(cls: type) -> tuple[str, ...]:
    """Field names of a node class; declared ones, as the compiled parser has no `__dict__`."""
    import dataclasses

    return tuple(f.name for f in dataclasses.fields(cls))


def walk_nodes(node: object) -> list:
    """Every node of a subtree, parents before children, in source order.

    An explicit stack rather than nested generators: a method body is walked several times per
    judged method, and the generator chain was the largest cost of the typing on a live project.
    """
    out: list = []
    stack: list[object] = [node]
    while stack:
        current = stack.pop()
        if isinstance(current, (list, tuple)):
            stack.extend(reversed(current))
            continue
        if not isinstance(current, P.Node):
            continue
        out.append(current)
        children = [getattr(current, name, None) for name in _field_names(type(current))]
        stack.extend(child for child in reversed(children) if isinstance(child, (P.Node, list, tuple)))
    return out


def _method_names(method: object, nodes: list) -> frozenset[str]:
    """Every name the method declares anywhere: parameters, locals, loop and catch variables,
    lambda parameters."""
    names = {param.name for param in getattr(method, "params", ()) or ()}
    for node in nodes:
        if isinstance(node, P.VarDecl):
            names.add(node.name)
        elif isinstance(node, (P.ForEach, P.ForTo)):
            names.add(node.var)
        elif isinstance(node, P.Try):
            names.update(var for var, _tref, _body in node.catches if var)
        elif isinstance(node, P.Lambda):
            names.update(param.name for param in node.params)
    names.discard("")
    return frozenset(names)


class _Declared:
    """One declaration of a method: visible from `pos` to the end of `block`, typed on demand.

    `kind` says where the type comes from: "written" (the text of a type), "init" (the
    expression a declaration without a type is initialized by), "element" (the collection a
    loop walks) or "fixed" (a set known in advance)."""

    __slots__ = ("block", "pos", "kind", "payload", "done", "value")

    def __init__(self, block: tuple[int, int], pos: int, kind: str, payload: object) -> None:
        self.block = block
        self.pos = pos
        self.kind = kind
        self.payload = payload
        self.done = False
        self.value: TypeSet | None = None


class _MethodScope:
    """The declarations of one method, each visible from where it stands to the end of its block.

    The platform scopes a name to its block, blocks nest and the innermost declaration wins
    (docs, "Область видимости имен"). Every name the method declares ANYWHERE is kept off the
    names of the module: a place that sees no declaration of such a name answers unknown rather
    than falling through to a property or a field of the same name. The type of a declaration
    is computed the first time a place asks for it - most declarations never feed a site.
    """

    def __init__(self, method: object, nodes: list) -> None:
        self.entries: dict[str, list[_Declared]] = {}
        self.names = _method_names(method, nodes)
        span = (int(getattr(method, "start", 0)), int(getattr(method, "end", 0)))
        for param in getattr(method, "params", ()) or ():
            self._add(param.name, _Declared(span, span[0], "written", _written_ref(param.type)))
        body = getattr(method, "body", None)
        self._walk(body, _statement_block(body) or span)

    def _add(self, name: str, entry: _Declared) -> None:
        if name:
            self.entries.setdefault(name, []).append(entry)

    def lookup(self, name: str, at: int) -> "_Declared | _Missing | _Unknown":
        entries = self.entries.get(name)
        if not entries:
            return _UNKNOWN if name in self.names else _MISSING
        best: _Declared | None = None
        for entry in entries:
            if entry.block[0] <= at <= entry.block[1] and entry.pos <= at:
                if best is None or (entry.block[0], entry.pos) >= (best.block[0], best.pos):
                    best = entry
        return best if best is not None else _UNKNOWN

    def _walk(self, node: object, block: tuple[int, int]) -> None:
        if isinstance(node, (list, tuple)):
            inner = _statement_block(node) or block
            for item in node:
                self._walk(item, inner)
            return
        if not isinstance(node, P.Node):
            return
        if isinstance(node, P.VarDecl):
            self._walk(node.init, block)
            written = _written_ref(node.type)
            if written is not None:
                entry = _Declared(block, int(node.end), "written", written)
            elif node.type is None and node.init is not None:
                entry = _Declared(block, int(node.end), "init", node.init)
            else:
                entry = _Declared(block, int(node.end), "fixed", None)
            self._add(node.name, entry)
            return
        if isinstance(node, P.ForEach):
            self._walk(node.source, block)
            loop = (int(node.start), int(node.end))
            self._add(node.var, _Declared(loop, int(node.source.end), "element", node.source))
            self._walk(node.body, loop)
            return
        if isinstance(node, P.ForTo):
            loop = (int(node.start), int(node.end))
            for part in (node.start_expr, node.to, node.step):
                self._walk(part, block)
            after = node.step or node.to
            self._add(node.var, _Declared(loop, int(getattr(after, "end", node.start)), "fixed",
                                          TypeSet.of("Число")))
            self._walk(node.body, loop)
            return
        if isinstance(node, P.Try):
            self._walk(node.body, block)
            for var, tref, body in node.catches:
                span = _statement_block(body)
                if span is not None:
                    self._add(var, _Declared(span, span[0], "written", _written_ref(tref)))
                    self._walk(body, span)
            self._walk(node.finally_body, block)
            return
        if isinstance(node, P.Lambda):
            span = (int(node.start), int(node.end))
            for param in node.params:
                self._add(param.name, _Declared(span, span[0], "written", _written_ref(param.type)))
            self._walk(node.body_expr, span)
            self._walk(node.body_stmts, span)
            return
        for name in _field_names(type(node)):
            value = getattr(node, name, None)
            if isinstance(value, (P.Node, list, tuple)):
                self._walk(value, block)


class _Evaluator:
    """The set of an expression at its place, or None when the data cannot state it.

    One per judged method (or per module level): `scope` holds the declarations of the method,
    `this_type` is the type of `этот`, `owner_fields` the fields a method of a structure reads
    by a bare name. A result is remembered per node - the operand of one site is often a part of
    another's."""

    def __init__(self, typer: "ModuleTyper", scope: _MethodScope | None,
                 this_type: TypeSet | None = None, owner_fields: dict[str, str | None] | None = None) -> None:
        self.typer = typer
        self.scope = scope
        self.this_type = this_type
        self.owner_fields = owner_fields
        self.memo: dict[int, object] = {}

    def types(self, node: object) -> TypeSet | None:
        """The set of a value: a TypeSet, or None (a static name is no value)."""
        got = self.value(node)
        return got if isinstance(got, TypeSet) else None

    def declared(self, entry: _Declared) -> TypeSet | None:
        if not entry.done:
            entry.done = True  # a declaration read while it is being typed answers None
            got: object = None
            if entry.kind == "written":
                got = self.typer.written(entry.payload)
            elif entry.kind == "init":
                got = self.value(entry.payload)
            elif entry.kind == "element":
                collection = self.value(entry.payload)
                got = self.typer.catalog.element_of(collection) if isinstance(collection, TypeSet) else None
            elif entry.kind == "fixed":
                got = entry.payload
            entry.value = got if isinstance(got, TypeSet) else None
        return entry.value

    def value(self, node: object):
        """The type of an expression: a TypeSet, a StaticName, or None when it cannot be named."""
        if node is None or not isinstance(node, P.Node):
            return None
        key = id(node)
        if key in self.memo:
            return self.memo[key]
        handler = getattr(self, "_" + type(node).__name__, None)
        got = handler(node) if handler is not None else None
        self.memo[key] = got
        return got

    # -- names ----------------------------------------------------------------------------------

    def name_at(self, name: str, at: int):
        if self.scope is not None:
            entry = self.scope.lookup(name, at)
            if isinstance(entry, _Declared):
                return self.declared(entry)
            if entry is _UNKNOWN:
                return None
        return self.typer.outer_name(name, self.owner_fields)

    def _Name(self, node):
        return self.name_at(node.name, int(node.start))

    def _This(self, node):
        return self.this_type

    def components_root(self, node: object) -> bool:
        """Whether a bare name is the form's own component root, not something declared so."""
        typer = self.typer
        return (
            isinstance(node, P.Name) and node.name in COMPONENT_ROOTS
            and typer.scope.components is not None
            and (self.scope is None or self.scope.lookup(node.name, int(node.start)) is _MISSING)
            and node.name not in typer.fields and node.name not in typer.scope.own_properties
            and not (self.owner_fields is not None and node.name in self.owner_fields)
        )

    # -- literals -------------------------------------------------------------------------------

    def _Literal(self, node):
        kind = str(getattr(node, "kind", ""))
        if kind == "UNDEFINED":
            return TypeSet(undefined=True)
        if kind == "QUERY":
            from xbsl import querytypes

            key = querytypes.row_type(self.typer.scope, node.start, node.end,
                                      lambda name: self._query_parameter(name, int(node.start)))
            if key is None:
                return None
            return TypeSet.of(f"ТипизированныйЗапрос<{key}>")
        name = _SET_LITERALS.get(kind)
        return TypeSet.of(name) if name else None

    def _query_parameter(self, name: str, at: int) -> TypeSet | None:
        """The type of `%Имя` in a query literal: the code value of that name, when it is one type."""
        got = self.name_at(name, at)
        if isinstance(got, TypeSet) and got.single and got.names:
            return got
        return None

    def _ArrayLit(self, node):
        items = [self.value(item) for item in node.items]
        # `[1, 2]` is an array of the one type all its items have
        if items and not node.type_args and all(isinstance(item, TypeSet) for item in items):
            first = items[0]
            if all(item == first for item in items) and first.single and first.names:
                return TypeSet.of(f"Массив<{first.text()}>")
        return None

    # -- operators ------------------------------------------------------------------------------

    def _AsType(self, node):
        return self.typer.written(_written_ref(node.type))

    def _New(self, node):
        got = self.typer.written(_written_ref(node.type))
        return got if got is not None and got.names and not got.undefined else None

    def _NonNull(self, node):
        inner = self.types(node.operand)
        if inner is None or not inner.names:
            return None
        return inner.without_undefined()

    def _IsType(self, node):
        return TypeSet.of("Булево")

    def _Compare(self, node):
        return TypeSet.of("Булево")

    def _Unary(self, node):
        if node.op.lower() in ("не", "not"):
            return TypeSet.of("Булево")
        inner = self.types(node.operand)
        return inner if inner is not None and inner == TypeSet.of("Число") else None

    def _Binary(self, node):
        if node.op.lower() in _LOGICAL_OPS:
            return TypeSet.of("Булево")
        if node.right is None:
            return None
        return _arithmetic(node.op, self.types(node.left), self.types(node.right))

    def _Coalesce(self, node):
        # `А ?? Б` is А without the empty value, or Б
        left = self.types(node.left)
        right = self.types(node.right) if node.right is not None else None
        if left is None or right is None or left.null:
            return None
        return left.without_undefined().union(right)

    def _Ternary(self, node):
        then = self.types(node.then)
        otherwise = self.types(node.otherwise) if node.otherwise is not None else None
        if then is None or otherwise is None:
            return None
        return then.union(otherwise)

    def _Index(self, node):
        owner = self.types(node.obj)
        return self.typer.catalog.indexed(owner) if owner is not None else None

    # -- members and calls ----------------------------------------------------------------------

    def _Member(self, node):
        obj = node.obj
        if self.components_root(obj):
            return self.typer.component(node.name)
        if isinstance(obj, P.This) and self.this_type is None:
            # `этот` of a component module is the component: its typed properties are the own ones
            if self.typer.scope.components is None:
                return None
            written = self.typer.scope.own_properties.get(node.name)
            return self.typer.written(written) if written else None
        owner = self.value(obj)
        return self._reached(owner, node, False, None)

    def _reached(self, owner, node, called: bool, argc: int | None):
        typer = self.typer
        if isinstance(owner, StaticName):
            got = typer.catalog.static_member(owner.name, node.name, called, typer.scope.module, argc)
            if got is None and "." not in owner.name and owner.name not in typer.catalog.elements \
                    and owner.name not in typer.catalog.modules:
                got = typer.platform_static(owner.name, node.name, called, argc)
            return got
        if not isinstance(owner, TypeSet) or len(owner.names) != 1 or owner.null:
            return None
        got = typer.catalog.member(next(iter(owner.names)), node.name, called, argc)
        if got is not None and node.safe and owner.undefined:
            got = got.with_undefined()
        return got

    def _Call(self, node):
        callee = node.callee
        typer = self.typer
        # a named argument or an explicit type argument leaves the arguments uncounted
        argc = None if node.type_args or any(arg.name for arg in node.args) else len(node.args)
        if isinstance(callee, P.Member):
            obj = callee.obj
            if self.components_root(obj):
                return None
            if isinstance(obj, P.This) and self.this_type is None:
                return None
            return self._reached(self.value(obj), callee, True, argc)
        if isinstance(callee, P.Name):
            name = callee.name
            if self.scope is not None and self.scope.lookup(name, int(callee.start)) is not _MISSING:
                return None
            if self.owner_fields is not None and name in self.owner_fields:
                return None
            if name in typer.fields or name in typer.scope.own_properties:
                return None
            declared, got = typer.catalog.structure_method(self.this_type, name)
            if declared:
                return got
            return typer.catalog.own_method(typer.scope.module, name)
        return None


class ModuleTyper:
    """Types the sites of one module over type sets: casts, guards against the empty value and
    type checks.

    A method is walked only when its text holds the operation of a site; its declarations are
    read by the platform's scoping (a declaration is visible from its place to the end of its
    block), and a type is computed only for what a site needs - the operand of a site is typed
    at the site, not anywhere in the method.
    """

    def __init__(self, scope: ModuleScope) -> None:
        self.scope = scope
        self.catalog = scope.catalog
        self.fields: dict[str, object] = {}
        self._field_types: dict[str, object] = {}
        self._module: object = None
        self._module_level: _Evaluator | None = None

    # -- the module -----------------------------------------------------------------------------

    def _prepare(self, module: object) -> None:
        if self._module is module:
            return
        self._module = module
        self.fields = {member.name: member for member in getattr(module, "members", ()) or ()
                       if isinstance(member, P.ObjectField)}
        self._field_types = {}
        self._module_level = _Evaluator(self, None)

    def written(self, text: str | None) -> TypeSet | None:
        return self.catalog.written(text, self.scope.module) if text else None

    def outer_name(self, name: str, owner_fields: dict[str, str | None] | None):
        """A bare name the method does not declare: a field of the structure, a property of the
        paired yaml, a field of the module, or a name that stands for a type."""
        if owner_fields is not None and name in owner_fields:
            return self.written(owner_fields[name])
        scope = self.scope
        if name in scope.own_properties:
            return self.written(scope.own_properties[name])
        if name in self.fields:
            return self._field_type(name)
        if name in scope.opaque:
            return None
        own = self.catalog.modules.get(scope.module or "") or {}
        if name in (own.get("enums") or {}) or name in (own.get("structures") or {}):
            return StaticName(f"{scope.module}.{name}")
        if scope.static_names and (name in self.catalog.elements or name in self.catalog.modules
                                   or platform_head(name)):
            return StaticName(name)
        return None

    def _field_type(self, name: str) -> TypeSet | None:
        if name not in self._field_types:
            self._field_types[name] = None  # a field read while it is being typed answers None
            member = self.fields[name]
            written = _written_ref(getattr(member, "type", None))
            if written:
                got: object = self.written(written)
            elif getattr(member, "init", None) is not None and self._module_level is not None:
                # `конст Лимит = 10` is a number: a field written without a type is typed by
                # its value, the way a local is
                got = self._module_level.value(member.init)
            else:
                got = None
            self._field_types[name] = got if isinstance(got, TypeSet) else None
        return self._field_types[name]  # type: ignore[return-value]

    def component(self, name: str) -> TypeSet | None:
        """The type of a named node of the paired markup, when every mention of it writes one
        type that holds no empty value and binds its parameters (see `_bound_by_default`)."""
        spellings = (self.scope.components or {}).get(name)
        if not spellings or None in spellings:
            return None
        sets = {self.written(written) for written in spellings}
        if len(sets) != 1:
            return None
        got = next(iter(sets))
        if got is None or got.undefined or not _bound_by_default(got):
            return None
        return got

    def platform_static(self, type_name: str, member: str, called: bool,
                        argc: int | None = None) -> TypeSet | None:
        head = platform_head(type_name)
        if head is None or _platform_params(head):
            return None
        return self.catalog.platform_member(head, member, called, argc)

    def _methods(self, module: object, structures: bool):
        """(method, this type, fields of its structure) of the module; the methods of structures
        and enumerations only when asked - their bare names reach the owner's own fields."""
        for member in getattr(module, "members", ()) or ():
            if isinstance(member, P.Method):
                yield member, self.scope.this_type, None
            elif structures and isinstance(member, P.Structure):
                owner = self.catalog.written(member.name, self.scope.module)
                fields = {inner.name: _written_ref(inner.type) for inner in member.members
                          if isinstance(inner, P.ObjectField)}
                for inner in member.members:
                    if isinstance(inner, P.Method):
                        yield inner, owner, fields
            elif structures and isinstance(member, P.Enum):
                owner = self.catalog.written(member.name, self.scope.module)
                for inner in member.methods:
                    yield inner, owner, None

    def _judged(self, module: object, pattern: re.Pattern, structures: bool, wanted):
        """(evaluator, the nodes the method holds that `wanted` picks) for every method whose
        text may hold the operation."""
        self._prepare(module)
        text = self.scope.text
        for method, this_type, owner_fields in self._methods(module, structures):
            if pattern.search(text, int(method.start), int(method.end)) is None:
                continue
            nodes = walk_nodes(getattr(method, "body", None))
            picked = [node for node in nodes if wanted(node)]
            if not picked:
                continue
            try:
                scope = _MethodScope(method, nodes)
            except RecursionError:
                continue
            yield _Evaluator(self, scope, this_type, owner_fields), picked

    def run(self, module: object) -> list[CastSite]:
        """Every cast of the module (see `casts`)."""
        return self.casts(module)

    def casts(self, module: object) -> list[CastSite]:
        """Every `как` of the module, the methods of its structures and the fields included."""
        self._prepare(module)
        sites: list[CastSite] = []
        for evaluator, nodes in self._judged(module, _CAST_TEXT_RE, True,
                                             lambda node: isinstance(node, P.AsType)):
            for node in nodes:
                sites.append(CastSite(node, _typed(evaluator, node.operand),
                                      self.written(_written_ref(node.type))))
        level = self._module_level
        for member in self.fields.values():
            init = getattr(member, "init", None)
            if init is None or level is None:
                continue
            for node in walk_nodes(init):
                if isinstance(node, P.AsType):
                    sites.append(CastSite(node, _typed(level, node.operand),
                                          self.written(_written_ref(node.type))))
        return sites

    def guards(self, module: object) -> list[GuardSite]:
        """Every `??`, `!` and `?.` of the module's own methods - a structure's methods reach its
        fields by a bare name, and the rules that judge guards leave them alone."""
        sites: list[GuardSite] = []
        for evaluator, nodes in self._judged(module, _GUARD_TEXT_RE, False, _is_guard):
            for node in nodes:
                if isinstance(node, P.Coalesce):
                    sites.append(GuardSite(node, "coalesce", node.left, _typed(evaluator, node.left),
                                           _typed(evaluator, node.right)))
                elif isinstance(node, P.NonNull):
                    sites.append(GuardSite(node, "insist", node.operand, _typed(evaluator, node.operand)))
                else:
                    sites.append(GuardSite(node, "safe", node.obj, _typed(evaluator, node.obj)))
        return sites

    def calls(self, module: object, names: frozenset[str]) -> list[CallSite]:
        """Every call of a member named one of `names`, in the module's methods, the methods of its
        structures and the initializers of its fields."""
        if not names:
            return []
        self._prepare(module)
        # Comments may separate the dot and the name; the AST below decides whether it is a call.
        pattern = re.compile(r"(?<!\w)(?:%s)(?!\w)" % "|".join(sorted(map(re.escape, names))))

        def wanted(node: object) -> bool:
            return (isinstance(node, P.Call) and isinstance(node.callee, P.Member)
                    and node.callee.name in names)

        def site(evaluator: _Evaluator, node) -> CallSite:
            try:
                owner = evaluator.value(node.callee.obj)
            except RecursionError:
                owner = None
            return CallSite(node, owner, [(argument.name, _typed(evaluator, argument.value))
                                          for argument in node.args])

        sites: list[CallSite] = []
        for evaluator, nodes in self._judged(module, pattern, True, wanted):
            sites.extend(site(evaluator, node) for node in nodes)
        level = self._module_level
        for member in self.fields.values():
            init = getattr(member, "init", None)
            if init is None or level is None:
                continue
            sites.extend(site(level, node) for node in walk_nodes(init) if wanted(node))
        return sites

    def checks(self, module: object) -> list[CheckSite]:
        """Every `это` of the module's own methods, the predicate form of `выбор` included."""
        sites: list[CheckSite] = []
        for evaluator, nodes in self._judged(module, _CHECK_TEXT_RE, False, _is_check_holder):
            for node in nodes:
                if isinstance(node, P.IsType):
                    if isinstance(node.operand, P.Name) and not node.operand.name:
                        continue  # the predicate form: its operand is the subject of `выбор`
                    sites.append(CheckSite(node, node.operand, _typed(evaluator, node.operand),
                                           self.written(_written_ref(node.type))))
                    continue
                for when in node.whens:
                    for condition in when.conditions:
                        if (isinstance(condition, P.IsType) and isinstance(condition.operand, P.Name)
                                and not condition.operand.name):
                            sites.append(CheckSite(condition, node.subject,
                                                   _typed(evaluator, node.subject),
                                                   self.written(_written_ref(condition.type))))
        return sites


def _typed(evaluator: _Evaluator, node: object) -> TypeSet | None:
    try:
        return evaluator.types(node)
    except RecursionError:
        return None


def _is_guard(node: object) -> bool:
    return ((isinstance(node, P.Coalesce) and node.right is not None) or isinstance(node, P.NonNull)
            or (isinstance(node, P.Member) and node.safe))


def _is_check_holder(node: object) -> bool:
    return isinstance(node, P.IsType) or (isinstance(node, P.Case) and node.subject is not None)


# --- the two reaches -------------------------------------------------------------------------------


class ModuleTyping:
    """The typing of one module, at the reach it was built for: the parsed tree, its tokens, the
    catalog and the sites, each kind computed on the first request."""

    def __init__(self, rel: str, scope: ModuleScope, tree: object) -> None:
        self.rel = rel
        self.scope = scope
        self.tree = tree
        self.typer = ModuleTyper(scope)
        self._sites: dict[str, list] = {}

    @property
    def catalog(self) -> ProjectCatalog:
        return self.scope.catalog

    @property
    def text(self) -> str:
        return self.scope.text

    @property
    def tokens(self) -> list:
        return self.scope.tokens or []

    def casts(self) -> list[CastSite]:
        if "casts" not in self._sites:
            self._sites["casts"] = self.typer.casts(self.tree)
        return self._sites["casts"]

    def guards(self) -> list[GuardSite]:
        if "guards" not in self._sites:
            self._sites["guards"] = self.typer.guards(self.tree)
        return self._sites["guards"]

    def checks(self) -> list[CheckSite]:
        if "checks" not in self._sites:
            self._sites["checks"] = self.typer.checks(self.tree)
        return self._sites["checks"]

    def calls(self, names: frozenset[str]) -> list[CallSite]:
        key = "calls:" + "|".join(sorted(names))
        if key not in self._sites:
            self._sites[key] = self.typer.calls(self.tree, names)
        return self._sites[key]


def file_typing(source) -> ModuleTyping | None:
    """The file reach: one module, and the markup of the component it belongs to read from the
    disk; None for a module that does not parse. Cached on the source.

    The catalog knows the module itself and nothing else of the project - not even the element
    of an object module: its facets and attributes are the project's, and a check that runs on
    every keystroke judges without them. A written name the catalog cannot resolve is kept as
    written, and a bare name the module does not declare is never read as a type (see the head
    of this half)."""
    key = "typeinfer_file"
    if key in source.cache:
        return source.cache[key]
    from xbsl.lexer import tokens
    from xbsl.rules.environment import _pair_stem

    tree, errors = P.parse(source)
    got: ModuleTyping | None = None
    if not errors:
        fact = module_fact(source.rel, tree)
        stem = _pair_stem(source.rel)
        markup = _paired_component(source)
        pairs = {stem: markup} if markup is not None else {}
        catalog = ProjectCatalog({}, {fact["module"]: fact}, open_world=True)
        own, opaque, components = _own_names(stem, pairs)
        scope = ModuleScope(fact["module"], source.text, catalog, own, opaque, tokens=tokens(source),
                            components=components, static_names=False)
        got = ModuleTyping(source.rel, scope, tree)
    source.cache[key] = got
    return got


def _paired_component(source) -> dict | None:
    """The element facts of the yaml next to a module (`X.yaml` for `X.xbsl`), read from the
    disk, when that yaml describes an interface component."""
    from pathlib import Path

    from xbsl.engine import make_source
    from xbsl.rules.yaml_schema import _HAVE_YAML, _parsed, object_kind

    if not _HAVE_YAML:
        return None
    try:
        pair = Path(source.path).with_suffix(".yaml")
        if not pair.is_file():
            return None
        paired = make_source(pair, pair.read_bytes())
    except (OSError, ValueError):
        return None
    data, error = _parsed(paired)
    if error is not None or not isinstance(data, dict) or object_kind(data) != _COMPONENT_KIND:
        return None
    return element_fact(paired)


_last_project: tuple[object, dict[str, ModuleTyping]] | None = None
_parsed_texts: dict[str, tuple[object, list]] = {}


def _fingerprint(facts: dict[str, dict]) -> object:
    return tuple(sorted((rel, fact.get("digest") or "") for rel, fact in facts.items()))


def _projects(facts: dict[str, dict]) -> dict[str, dict[str, dict]]:
    """The facts split by project: a run over a folder of several projects keeps their names
    apart (two libraries may both declare a catalog of one name)."""
    roots = sorted({fact["root"] for fact in facts.values() if fact.get("k") == "project"},
                   key=len, reverse=True)
    groups: dict[str, dict[str, dict]] = {}
    for rel, fact in facts.items():
        path = rel.replace("\\", "/")
        owner = next((root for root in roots if path.startswith(root + "/")), "")
        groups.setdefault(owner, {})[rel] = fact
    return groups


def _parsed_module(fact: dict) -> tuple[object, list]:
    """(the module, its tokens) of a fact's text, tokenized once: the parser, the query rows and
    the fixes all read the same tokens, and a second save of an unchanged module parses nothing."""
    from xbsl import lexer

    digest = fact["digest"]
    parsed = _parsed_texts.get(digest)
    if parsed is None:
        tokens = lexer.tokenize(fact["text"])
        module, _errors = P.parse_tokens(tokens)
        if len(_parsed_texts) > 512:
            _parsed_texts.clear()
        parsed = (module, tokens)
        _parsed_texts[digest] = parsed
    return parsed


def project_typings(facts: dict[str, dict]) -> dict[str, ModuleTyping]:
    """The project reach: {rel: the typing of a module that carries its text} over the facts of
    `project_fact`. Every project rule of the typing reduces the same facts, so the result is
    remembered for the last set of them - the catalog is built and a module parsed once."""
    global _last_project
    key = _fingerprint(facts)
    if _last_project is not None and _last_project[0] == key:
        return _last_project[1]
    typings: dict[str, ModuleTyping] = {}
    for group in _projects(facts).values():
        elements: dict[str, dict] = {}
        duplicated: set[str] = set()
        pairs: dict[str, dict] = {}
        for fact in group.values():
            if fact.get("k") != "yaml":
                continue
            element = fact["element"]
            name = element["name"]
            if name in elements:
                duplicated.add(name)
            elements[name] = element
            pairs[fact["stem"]] = element
        for name in duplicated:
            elements.pop(name, None)
        modules: dict[str, dict] = {}
        for fact in group.values():
            if fact.get("k") == "xbsl":
                if fact["module"] in modules:
                    duplicated.add(fact["module"])
                modules[fact["module"]] = fact
        for name in duplicated:
            modules.pop(name, None)
        catalog = ProjectCatalog(elements, modules)
        for rel, fact in sorted(group.items()):
            if fact.get("k") != "xbsl" or "text" not in fact or fact["module"] in duplicated:
                continue
            tree, tokens = _parsed_module(fact)
            own, opaque, components = _own_names(fact["stem"], pairs)
            scope = ModuleScope(fact["module"], fact["text"], catalog, own, opaque, tokens=tokens,
                                components=components)
            typings[rel] = ModuleTyping(rel, scope, tree)
    _last_project = (key, typings)
    return typings


def _reset_sets() -> None:
    global _last_project
    _member_names.cache_clear()
    canonical_name.cache_clear()
    _facet_suffixes.cache_clear()
    _last_project = None


dataset.register_reset(_reset_sets)
