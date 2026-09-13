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
# only source. That is enough for a hover and for the translator, and it is not enough to judge a
# cast the way the compiler does. The compiler holds the type of an expression as a SET - a
# parameter declared `Материалы.Ссылка|Страницы.Ссылка` is two types, a query column read
# through a reference is its field type plus Null - and it compares the sets member by member
# (see `cast_verdict`). And most of what the code casts comes from the PROJECT: a column of a
# query over a catalog, a field of a structure declared in another module, the result of a
# method of a common module. So this half of the module answers a `TypeSet`, and it looks
# project names up in a `ProjectCatalog` the caller builds from the whole project.
#
# The rule of the upper half stands here too: what cannot be named answers None, and a caller
# that gets None stays silent. A set is never "probably" a type.


@dataclass(frozen=True)
class TypeSet:
    """A type as a set: the nominal types, the empty value and the Null of a query.

    `names` holds CANONICAL nominal texts (`String`, `Array<String>`, `Goods.Ref` in English
    terms): a platform name in the catalog's own (Russian) spelling, a project name as the project writes it, the
    arguments of a generic canonical too. Two sets are the same type exactly when they are
    equal, and that is what the comparison of a cast turns on.
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


def parse_type(text: str | None, resolve) -> TypeSet | None:
    """The set a written type stands for, or None when a part of it cannot be named.

    `resolve(name)` answers the canonical head of one name (an English platform name -> the
    catalog's spelling, a structure of
    the module -> `Модуль.Структура`) or None; a single name it cannot resolve makes the whole
    type unknown - a union of a known and an unknown type is not the known one.
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
    parser = _TypeTextParser(tokens, resolve)
    got = parser.union()
    if got is None or parser.pos != len(tokens):
        return None
    return got


class _TypeTextParser:
    """Recursive descent over the tokens of a written type (see parse_type)."""

    def __init__(self, tokens: list[tuple[str, str]], resolve) -> None:
        self.tokens = tokens
        self.pos = 0
        self.resolve = resolve

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
        if token[1] in _UNDEFINED_NAMES:
            got = TypeSet(undefined=True)
        else:
            head = self.resolve(token[1])
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

    The logic of the compiler read literally (`BslBinder.BindingVisitor.endVisit(CastExpression)`
    and `IG5Type.canHoldValueWithUndef` of the platform compiler):

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


# --- the platform side of a type set ---------------------------------------------------------

#: The root of the type hierarchy: every value is an `Object`, and the catalog lists it as no
#: base of anything only because it is the base of everything.
_ROOT_TYPE = "Объект"

#: The collection every iterable inherits, and the name its element parameter carries.
_ITERABLE = "Обходимое"
_ELEMENT_PARAM = "ТипЭлемента"


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


def _signature_results(head: str, member: str) -> set[str]:
    """The result types the overloads of a member declare (`Найти(...): Т?`), as written."""
    signatures = ((_catalog().get("member_signatures") or {}).get(head) or {}).get(member) or ()
    out: set[str] = set()
    for signature in signatures:
        depth = 0
        close = -1
        for index, char in enumerate(signature):
            if char == "(":
                depth += 1
            elif char == ")":
                depth -= 1
                if depth == 0:
                    close = index
        tail = signature[close + 1:].strip() if close >= 0 else ""
        out.add(tail[1:].strip() if tail.startswith(":") else "")
    return out


def _russian_member(head: str, member: str) -> str | None:
    """The member name the catalog keys by (Russian) for a member written in either language.

    An English member is taken only when the type itself spells the Russian one that way: the
    flat dictionary keeps one spelling per word, and a word two types spell apart would type
    the member of one by the member of the other.
    """
    members = (_catalog().get("member_types") or {}).get(head) or {}
    if member in members:
        return member
    from xbsl import terms

    russian = terms.common_russian(member)
    if russian and russian in members and terms.member_english_of(head, russian) == member:
        return russian
    return None


def _member_kind(head: str, member: str) -> str | None:
    """"method" or "property" for a platform member, None when the catalog does not say."""
    record = (_catalog().get("type_members") or {}).get(head) or {}
    if member in (record.get("methods") or ()):
        return "method"
    if member in (record.get("properties") or ()):
        return "property"
    return None


def _type_param_bindings(head: str, args: tuple[str, ...], resolve) -> dict[str, TypeSet] | None:
    """{type parameter: the set its argument names} for a generic written with its arguments.

    The own parameters bind by position. An inherited member speaks the language of the base
    that declares it - a query result answers `ПервыйИлиНеопределено(): ТипЭлемента?`, while
    the result type itself is written with `QueryResultRowType` - so a collection of
    ONE argument also binds the element parameter of the iterable it inherits. A collection of
    two arguments does not: the element of a map is a key-and-value pair, and nothing in the
    data says so, which leaves that parameter unbound and the member unknown.
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


def parse_type_with(text: str | None, resolve, bindings: dict[str, TypeSet]) -> TypeSet | None:
    """`parse_type` where a name of `bindings` stands for the set it is bound to."""
    if not bindings:
        return parse_type(text, resolve)

    marker = "#bound:"

    def bound(name: str) -> str | None:
        if name in bindings:
            return marker + name
        return resolve(name)

    got = parse_type(text, bound)
    if got is None:
        return None
    names: set[str] = set()
    undefined, null = got.undefined, got.null
    for name in got.names:
        if name.startswith(marker):
            value = bindings[name[len(marker):]]
            names |= value.names
            undefined = undefined or value.undefined
            null = null or value.null
        elif marker in name:
            # a bound parameter INSIDE the arguments of a generic: spliced as its text
            for param, value in bindings.items():
                name = name.replace(marker + param, value.text())
            names.add(name)
        else:
            names.add(name)
    return TypeSet(frozenset(names), undefined, null)


# --- the project catalog ----------------------------------------------------------------------

#: The facets of an element whose values carry the element's own attributes.
_DATA_FACETS = frozenset({"Объект", "Данные", "Запись"})

#: Element kinds whose own name is a type carrying its fields (the structure itself).
_STRUCTURE_KINDS = frozenset({"Структура", "ХранимаяСтруктура"})

#: The standard attributes an element carries without a declared type, by kind; `{}` stands for
#: the name of the element. Filled only with what the compiler was shown to answer (see the
#: probe project of the cast rules); an attribute missing here stays unknown.
STANDARD_FIELDS: dict[str, dict[str, str]] = {
    "Справочник": {"Ссылка": "{}.Ссылка", "Наименование": "Строка", "ПометкаУдаления": "Булево"},
    "Документ": {"Ссылка": "{}.Ссылка", "ПометкаУдаления": "Булево"},
    "КонтрактСущности": {"Ссылка": "{}.Ссылка"},
}

#: The key of a dynamic list row as the catalog spells it: by the row type parameter.
_ROW_KEY_RE = re.compile(r"([\wЁё]+)\.RowDataKeyType(\?)?")

#: The standard attributes of a tabular section row, `{}` standing for the owner element.
TABULAR_STANDARD_FIELDS: dict[str, str] = {"Владелец": "{}.Ссылка", "НомерСтроки": "Число"}


class ProjectCatalog:
    """The project names the type of an expression may need, gathered from the whole project.

    Built by the caller from plain facts (the cast rules collect them per file in their mapper):

    - `elements` - `{name: {"kind", "attributes", "tabular", "dimensions", "resources",
      "properties", "fields", "values", "contracts"}}`, every member section `{name: written
      type or None}` (None: a standard attribute written without a type);
    - `modules` - `{module: {"methods": {name: [written result per overload]}, "structures":
      {name: {"fields": {...}, "methods": {...}}}, "enums": {name: [values]}, "fields": {...}}}`,
      the module named by its file (`Товары` for `Товары.xbsl`).

    Answers are canonical texts and TypeSets (see TypeSet); every lookup the facts do not settle
    answers None.
    """

    def __init__(self, elements: dict[str, dict] | None = None,
                 modules: dict[str, dict] | None = None) -> None:
        self.elements: dict[str, dict] = dict(elements or {})
        self.modules: dict[str, dict] = dict(modules or {})
        self.rows: dict[str, dict[str, TypeSet | None]] = {}
        # {row data type of a dynamic list (`Форма.ДанныеСтроки`): the list's main table}
        self.row_keys: dict[str, str] = {
            row: table
            for element in self.elements.values()
            for row, table in (element.get("row_keys") or {}).items()
        }
        self._written: dict[tuple[str, str | None], TypeSet | None] = {}

    # -- names -----------------------------------------------------------------------------

    def resolver(self, module: str | None):
        """The name resolver of written types as seen from `module` (None: from a yaml)."""
        def resolve(name: str) -> str | None:
            return self.head(name, module)
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

    def member(self, owner: str, name: str, called: bool) -> TypeSet | None:
        """The type of `<value of owner>.name` (a call of it when `called`)."""
        head, args = split_nominal(owner)
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
        return self.platform_member(owner, name, called)

    def platform_member(self, owner: str, name: str, called: bool) -> TypeSet | None:
        head, args = split_nominal(owner)
        member = _russian_member(head, name)
        if member is None:
            return None
        kind = _member_kind(head, member)
        if (kind == "method") != called and kind is not None:
            return None
        results = _signature_results(head, member)
        if len(results) > 1:
            return None
        written = ((_catalog().get("member_types") or {}).get(head) or {}).get(member)
        resolve = self.resolver(None)
        bindings = _type_param_bindings(head, args, resolve)
        if bindings is None:
            return None
        key = _ROW_KEY_RE.fullmatch(written or "")
        if key is not None:
            return self._row_key(bindings.get(key.group(1)), bool(key.group(2)))
        return parse_type_with(written, resolve, bindings)

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
                    standard = STANDARD_FIELDS.get(element.get("kind") or "", {}).get(name)
                    return standard.replace("{}", element_name) if standard else None
                return written
        standard = STANDARD_FIELDS.get(element.get("kind") or "", {}).get(name)
        if standard:
            return standard.replace("{}", element_name)
        return _MISSING_FIELD

    def static_member(self, name: str, member: str, called: bool,
                      module: str | None) -> TypeSet | None:
        """`<name>.<member>` where the name itself is a project element or module."""
        own = self.modules.get(module or "") or {}
        if member in (own.get("enums") or {}).get(name, ()):
            return TypeSet.of(f"{module}.{name}")
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

    def element_of(self, collection: TypeSet) -> TypeSet | None:
        """One element of a collection set: the rows of a query result, the items of an array."""
        if collection.size != 1 or not collection.names:
            return None
        head, args = split_nominal(next(iter(collection.names)))
        if len(args) != 1:
            return None
        params = _platform_params(head)
        if len(params) != 1 or _ITERABLE not in _platform_bases(head):
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

#: Operators whose result is a Boolean whatever the operands are.
_LOGICAL_OPS = frozenset({"и", "или", "and", "or", "И", "ИЛИ", "AND", "OR"})


@dataclass
class ModuleScope:
    """What the code of one module sees besides its own declarations.

    `module` - the module name (the file stem), `text` - its source (a query literal is typed
    from its text), `catalog` - the project, `own_properties` - `{name: written type}` the module
    reads by a bare name (the attributes of the paired yaml), `opaque` - further bare names that
    are something of the module whose type is not known (a form component, a command): such a
    name answers None rather than a same-named project element or platform type.
    """

    module: str | None
    text: str
    catalog: ProjectCatalog
    own_properties: dict[str, str] = field(default_factory=dict)
    opaque: frozenset[str] = frozenset()
    this_type: TypeSet | None = None


class _Scopes:
    """Nested blocks of one method: name -> TypeSet, or None for a name declared untyped."""

    def __init__(self) -> None:
        self.stack: list[dict[str, TypeSet | None]] = [{}]

    def push(self) -> None:
        self.stack.append({})

    def pop(self) -> None:
        self.stack.pop()

    def declare(self, name: str, got: TypeSet | None) -> None:
        if name:
            self.stack[-1][name] = got

    def lookup(self, name: str):
        for block in reversed(self.stack):
            if name in block:
                return block[name]
        return _NOT_DECLARED


_NOT_DECLARED = object()


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


class ModuleTyper:
    """Types the expressions of one module over type sets, method by method.

    The walk follows the platform's scoping (a declaration is visible from its place to the end
    of its block) and calls back for every cast it meets with the scope of that place - the
    type of an operand is the type at the cast, not the type anywhere in the method.
    """

    def __init__(self, scope: ModuleScope) -> None:
        self.scope = scope
        self.catalog = scope.catalog
        self.scopes = _Scopes()
        self.module_fields: dict[str, TypeSet | None] = {}
        self.casts: list[CastSite] = []

    # -- the module ---------------------------------------------------------------------------

    def run(self, module: object) -> list[CastSite]:
        members = list(getattr(module, "members", ()) or ())
        for member in members:
            if isinstance(member, P.ObjectField):
                written = getattr(getattr(member, "type", None), "text", None)
                self.module_fields[member.name] = (
                    self.catalog.written(written, self.scope.module) if written else None)
        for member in members:
            if isinstance(member, P.Method):
                self.method(member, self.scope.this_type)
            elif isinstance(member, P.Structure):
                owner = self.catalog.written(member.name, self.scope.module)
                for inner in member.members:
                    if isinstance(inner, P.Method):
                        self.method(inner, owner)
            elif isinstance(member, P.Enum):
                owner = self.catalog.written(member.name, self.scope.module)
                for inner in member.methods:
                    self.method(inner, owner)
            elif isinstance(member, P.ObjectField) and member.init is not None:
                self.expression(member.init)
        return self.casts

    def method(self, method: object, this_type: TypeSet | None) -> None:
        self.scopes = _Scopes()
        self._this = this_type
        for param in getattr(method, "params", ()) or ():
            written = getattr(getattr(param, "type", None), "text", None)
            self.scopes.declare(param.name,
                                self.catalog.written(written, self.scope.module) if written else None)
        self.statements(getattr(method, "body", ()) or ())

    # -- statements -----------------------------------------------------------------------------

    def statements(self, items) -> None:
        self.scopes.push()
        try:
            for item in items or ():
                self.statement(item)
        finally:
            self.scopes.pop()

    def statement(self, node: object) -> None:
        if isinstance(node, P.VarDecl):
            got = None
            if node.init is not None:
                got = self.expression(node.init)
            written = getattr(getattr(node, "type", None), "text", None)
            if written:
                got = self.catalog.written(written, self.scope.module)
            self.scopes.declare(node.name, got if isinstance(got, TypeSet) else None)
        elif isinstance(node, P.Assign):
            self.expression(node.value)
            self.expression(node.target)
        elif isinstance(node, P.ExprStmt):
            self.expression(node.expr)
        elif isinstance(node, P.UseStmt):
            self.expression(node.expr)
        elif isinstance(node, P.Return):
            self.expression(node.value)
        elif isinstance(node, P.If):
            for condition, body in node.branches:
                self.expression(condition)
                self.statements(body)
            if node.else_body is not None:
                self.statements(node.else_body)
        elif isinstance(node, P.Case):
            self.expression(node.subject)
            for when in node.whens:
                for condition in when.conditions:
                    self.expression(condition)
                self.statements(when.body)
            if node.else_body is not None:
                self.statements(node.else_body)
        elif isinstance(node, P.While):
            self.expression(node.cond)
            self.statements(node.body)
        elif isinstance(node, P.ForEach):
            collection = self.expression(node.source)
            element = self.catalog.element_of(collection) if isinstance(collection, TypeSet) else None
            self.scopes.push()
            try:
                self.scopes.declare(node.var, element)
                self.statements(node.body)
            finally:
                self.scopes.pop()
        elif isinstance(node, P.ForTo):
            self.expression(node.start_expr)
            self.expression(node.to)
            self.expression(node.step)
            self.scopes.push()
            try:
                self.scopes.declare(node.var, TypeSet.of("Число"))
                self.statements(node.body)
            finally:
                self.scopes.pop()
        elif isinstance(node, P.Try):
            self.statements(node.body)
            for name, type_ref, body in node.catches:
                written = getattr(type_ref, "text", None)
                self.scopes.push()
                try:
                    self.scopes.declare(name, self.catalog.written(written, self.scope.module)
                                        if written else None)
                    self.statements(body)
                finally:
                    self.scopes.pop()
            if node.finally_body is not None:
                self.statements(node.finally_body)
        elif isinstance(node, P.Scope):
            self.statements(node.body)

    # -- expressions -----------------------------------------------------------------------------

    def expression(self, node: object):
        """The type of an expression: a TypeSet, a StaticName, or None when it cannot be named.

        Every sub-expression is visited even when the whole stays unknown - a cast may sit
        anywhere inside.
        """
        if node is None or not isinstance(node, P.Node):
            return None
        if isinstance(node, P.Name):
            return self.name(node.name)
        if isinstance(node, P.This):
            return self._this
        if isinstance(node, P.Literal):
            return self.literal(node)
        if isinstance(node, P.AsType):
            source = self.expression(node.operand)
            written = getattr(getattr(node, "type", None), "text", None)
            target = self.catalog.written(written, self.scope.module) if written else None
            self.casts.append(CastSite(node, source if isinstance(source, TypeSet) else None,
                                       target))
            return target
        if isinstance(node, P.NonNull):
            inner = self.expression(node.operand)
            return inner.without_undefined() if isinstance(inner, TypeSet) else None
        if isinstance(node, P.IsType):
            self.expression(node.operand)
            return TypeSet.of("Булево")
        if isinstance(node, P.Compare):
            parts = [node.first] + [right for _op, right in node.rest]
            for part in parts:
                self.expression(part)
            return TypeSet.of("Булево")
        if isinstance(node, P.Unary):
            inner = self.expression(node.operand)
            if node.op.lower() in ("не", "not"):
                return TypeSet.of("Булево")
            return inner if isinstance(inner, TypeSet) and inner == TypeSet.of("Число") else None
        if isinstance(node, P.Binary):
            left = self.expression(node.left)
            right = self.expression(node.right)
            if node.op in _LOGICAL_OPS:
                return TypeSet.of("Булево")
            return None
        if isinstance(node, P.Coalesce):
            self.expression(node.left)
            self.expression(node.right)
            return None
        if isinstance(node, P.Ternary):
            self.expression(node.cond)
            self.expression(node.then)
            self.expression(node.otherwise)
            return None
        if isinstance(node, P.New):
            for argument in node.args or ():
                self.expression(argument.value)
            written = getattr(getattr(node, "type", None), "text", None)
            return self.catalog.written(written, self.scope.module) if written else None
        if isinstance(node, P.Member):
            return self.member(node, called=False)
        if isinstance(node, P.Call):
            for argument in node.args:
                self.expression(argument.value)
            callee = node.callee
            if isinstance(callee, P.Member):
                return self.member(callee, called=True)
            if isinstance(callee, P.Name):
                if self.scopes.lookup(callee.name) is not _NOT_DECLARED:
                    return None
                return self.catalog.own_method(self.scope.module, callee.name)
            self.expression(callee)
            return None
        if isinstance(node, P.Index):
            self.expression(node.obj)
            self.expression(node.index)
            return None
        if isinstance(node, P.Lambda):
            self.scopes.push()
            try:
                for param in node.params:
                    self.scopes.declare(param.name, None)
                if node.body_expr is not None:
                    if isinstance(node.body_expr, P.Assign):
                        self.statement(node.body_expr)
                    else:
                        self.expression(node.body_expr)
                if node.body_stmts is not None:
                    self.statements(node.body_stmts)
            finally:
                self.scopes.pop()
            return None
        if isinstance(node, (P.ArrayLit,)):
            for item in node.items:
                self.expression(item)
            return None
        if isinstance(node, P.MapLit):
            for key, value in node.entries:
                self.expression(key)
                self.expression(value)
            return None
        if isinstance(node, P.Throw):
            self.expression(node.value)
            return None
        return None

    def name(self, name: str):
        found = self.scopes.lookup(name)
        if found is not _NOT_DECLARED:
            return found
        if name in self.scope.own_properties:
            return self.catalog.written(self.scope.own_properties[name], self.scope.module)
        if name in self.module_fields:
            return self.module_fields[name]
        if name in self.scope.opaque:
            return None
        catalog = self.catalog
        own = catalog.modules.get(self.scope.module or "") or {}
        if name in (own.get("enums") or {}) or name in (own.get("structures") or {}):
            return StaticName(f"{self.scope.module}.{name}")
        if name in catalog.elements or name in catalog.modules or platform_head(name):
            return StaticName(name)
        return None

    def literal(self, node: object):
        kind = str(getattr(node, "kind", ""))
        if kind == _UNDEFINED_KIND:
            return TypeSet(undefined=True)
        if kind == "QUERY":
            from xbsl import querytypes

            key = querytypes.row_type(self.scope, node.start, node.end)
            if key is None:
                return None
            return TypeSet.of(f"ТипизированныйЗапрос<{key}>")
        name = _SET_LITERALS.get(kind)
        return TypeSet.of(name) if name else None

    def member(self, node: object, called: bool):
        owner = self.expression(node.obj)
        if isinstance(owner, StaticName):
            got = self.catalog.static_member(owner.name, node.name, called, self.scope.module)
            if got is None and "." not in owner.name and owner.name not in self.catalog.elements \
                    and owner.name not in self.catalog.modules:
                got = self._platform_static(owner.name, node.name, called)
            return got
        if not isinstance(owner, TypeSet) or len(owner.names) != 1 or owner.null:
            return None
        got = self.catalog.member(next(iter(owner.names)), node.name, called)
        if got is not None and node.safe and owner.undefined:
            got = got.with_undefined()
        return got

    def _platform_static(self, type_name: str, member: str, called: bool) -> TypeSet | None:
        head = platform_head(type_name)
        if head is None or _platform_params(head):
            return None
        return self.catalog.platform_member(head, member, called)
