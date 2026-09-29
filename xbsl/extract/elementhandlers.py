"""The handlers the compiler declares for the modules of project elements.

A method under `@Handler` overrides a handler the platform calls by name. For an interface
component the distribution lists those handlers in the component's description (see
stdlib.component_handlers). For every other module - the object module of a catalog, the
record set of a register, the module of a scheduled job, of an access key, of a command -
no description lists them: the compiler DECLARES them in code. Each declaring class implements
one interface of the compiler, `ITypeHandlersProviderPart`, and its `getHandlers(type,
metadata, mode)` answers the handlers of a module built on `type`: it tests which project type
it was given (`instanceof CatalogObjectG5ProjectType` - the object module of a catalog), builds
a method description for each handler and hands it to `TypeHandlerInfo.builder`.

The name of such a method is a term, and the term comes from far away: the provider asks a
language model of the kind (`CatalogLanguageModel.onFillMethod`), the model builds the method
from a term constant (`CommonEntityNames$EventHandlers.ON_FILL`), and the constant is made of
its two spellings in the static initializer of its class. Reading the strings around the call
gives nothing - the provider holds no string at all. So this module runs the code: a small
abstract interpreter follows the provider's instructions, calls into the models and the
constants it meets, and at every `TypeHandlerInfo.builder` records the name the method was
built from, together with the branch it is on - the project type tested and the compatibility
modes compared (`mode.lt(CMODE_8_0)`).

Not every name is a constant. The operations of a processing come from its own description,
the operations of a SOAP client from its WSDL, the handlers of record-level security from the
access settings of the element: the provider reads such a name from metadata at build time.
The interpreter cannot know it, and says so - the module is recorded as DYNAMIC, and a
consumer must not judge it: any name may be a handler there.

Two answers of the compiler the interpreter models on purpose, since a branch explored both
ways there lands a handler in modules that never have it. The access-control provider asks the
access-control info for the TARGET of the module (`IAccessControlInfoProvider.getTargetType`)
and declares nothing when there is none; the info answers only for the own module of an element
some access-control part names as the MANAGER of its target (`getManagerTypeClass` of an
`IAccessControlInfoForTypeClassProvider`: the catalog for the items of a catalog, the HTTP
service for itself) - not for a common module, a command, an access key or the project. So a
path past that test stands for those managers alone, and a test of the target (`instanceof
IEntityType`) is a test of the target class the part names (see access_managers). And one
project type class stands for two kinds: the class of an access key serves the action privilege
too, and the item type of the key tells them apart (see _KIND_TESTS).

What the interpreter models is deliberately little: strings, terms, method descriptions (a
value that carries the term it was built from), lists of those, lambdas passed to a stream,
the tested type and the compatibility mode. Every other value is unknown, a condition on an
unknown value is explored both ways, and a loop body runs at most twice. A branch the
interpreter cannot finish within its budget makes its module dynamic rather than incomplete.
"""

from __future__ import annotations

import io
import re
import zipfile
from dataclasses import dataclass, field
from functools import lru_cache

from xbsl.extract import classcode

#: The interface every handler provider implements, and the call that states one handler.
PROVIDER_INTERFACE = "com/e1c/g5rt/appengine/core/bsl/compiletime/spi/ITypeHandlersProviderPart"
_SINK = "ITypeHandlersProviderPart$TypeHandlerInfo.builder"
_PROVIDER_METHOD = "getHandlers"
#: A term, a compatibility mode and the comparisons the providers make of it.
_TERM_CLASS = "com/e1c/g5rt/utils/common/Term"
_TERM_DESCRIPTOR = "L" + _TERM_CLASS + ";"
_MODE_CLASS = "com/e1c/g5rt/utils/common/G5CompatibilityMode"
_MODE_TESTS = ("ge", "gt", "le", "lt")
#: The classes whose instances describe a METHOD: a handler is one of them, and the value the
#: interpreter tracks for it is the term it is named by.
_METHOD_LIKE_RE = re.compile(
    r"(?:MethodSymbol|MethodSymbol\$Builder|Bsl(?:Ct)?Meta(?:Method|Procedure|Function)"
    r"|ICompileTimeMetaMethod|TypeHandlerInfo|TypeHandlerInfo\$Builder)$"
)
#: The jars of the platform itself: the providers and everything they call live there.
_PLATFORM_JAR_RE = re.compile(r"g5rt|_1c")
#: How a project type class spells its element: `<Kind><Facet>G5ProjectType`, the facet one of
#: the modules an element pairs with. `Node` is the object of an exchange plan (its facet is
#: `Object` in the reference).
_TYPE_SUFFIX = "G5ProjectType"
_FACET_ALIASES = {"Node": "Object"}
#: A project type class named apart from its kind: the project of an application (the project
#: description of the application kind, the default one) is the element of the kind `Project`,
#: and its module is the module of the project. A library and an extension project have classes
#: of their own and no handler.
_KIND_ALIASES = {"ApplicationProject": "Project"}
#: The kind whose modules the component descriptions cover, base by base (module_handlers):
#: its providers answer for every component at once and are left to that source.
COMPONENT_KIND = "КомпонентИнтерфейса"
#: The access-control info the access-control provider asks for the target of a module, and the
#: parts it answers from - each names a target type class and the type class of its manager.
_ACCESS_INFO = "com/e1c/g5rt/appengine/core/accesscontrol/common/IAccessControlInfoProvider"
_ACCESS_INFO_PART = ("com/e1c/g5rt/appengine/core/accesscontrol/common/spi/"
                     "IAccessControlInfoForTypeClassProvider")
_TYPE_CLASS_DESCRIPTOR = "()Lcom/e1c/g5rt/appengine/core/mdd/common/types/TypeClass;"
#: A project type class that stands for two element kinds, told apart by a test of its item
#: type: {(the class of the test, its method): (the class and the field of the term naming the
#: kind the test is FALSE for)}. The class of an access key serves the action privilege as well:
#: the build makes the item of an element of the privilege kind a non-key - the access-key
#: producer sets the kind `PRIVILEGE` for the element type `ACCESS_PRIVILEGE_TERM`, and `isKey()`
#: is that kind's negation - and the access-key provider declares the permissions handler for a
#: non-key and the key check for a key.
_KIND_TESTS = {
    ("com/e1c/g5rt/appengine/accesskeys/common/types/AccessKeyObjectG5ProjectType", "isKey"):
        ("com/e1c/g5rt/appengine/accesskeys/common/AccessKeysClassConstants",
         "ACCESS_PRIVILEGE_TERM"),
}
#: The budget of the interpreter: how deep calls go, how many paths one method may take, how
#: many times one instruction runs on one path (a loop body twice).
_MAX_DEPTH = 8
_MAX_PATHS = 20000
_MAX_VISITS = 2
_MAX_STEPS = 400000


# --- values ------------------------------------------------------------------------------
#
# A value is a tuple whose head says what it is; None is anything unknown.
#   ("str", text)                       a string constant
#   ("term", en, ru)                    a term with both spellings
#   ("dyn", source)                     a term (or a method named by one) read at build time
#   ("meth", name)                      a method description; name is a term or a dyn
#   ("list", items)                     a collection of values, items a tuple
#   ("stream", items) / ("iter", items) the same collection being streamed or iterated
#   ("lambda", owner, method, desc, captured)
#   ("obj", class)                      an object of a known class
#   ("new", class, serial)              an object between `new` and its constructor
#   ("param", index)                    the type parameter of the provider
#   ("mode",) / ("cmode", "8.0")        the compatibility mode and a mode constant
#   ("isinst", value, class)            the result of `instanceof`
#   ("modetest", op, "8.0")             the result of a mode comparison
#   ("instance", class)                 the `INSTANCE` singleton of a class
#   ("int", n)                          a small integer constant


def _is_term(value) -> bool:
    return isinstance(value, tuple) and value[0] in ("term", "dyn")


def _meths(value) -> list:
    """The method descriptions a value stands for: itself, or the items of a collection."""
    if not isinstance(value, tuple):
        return []
    if value[0] == "meth":
        return [value]
    if value[0] in ("list", "stream", "iter", "oneof"):
        return [item for part in value[1] for item in _meths(part)]
    return []


def _join(values: list):
    """One value for several paths: the value itself when they agree, else what they share."""
    known = [value for value in values if value is not None]
    if not known:
        return None
    if all(value == known[0] for value in known) and len(known) == len(values):
        return known[0]
    meths = [meth for value in known for meth in _meths(value)]
    if any(isinstance(value, tuple) and value[0] == "list" for value in known):
        # A collection on one path, another on the next: whatever any of them may hold.
        return ("list", tuple(dict.fromkeys(meths)))
    if meths:
        unique = tuple(dict.fromkeys(meths))
        return unique[0] if len(unique) == 1 else ("oneof", unique)
    return None


# --- descriptors -------------------------------------------------------------------------

_DESC_RE = re.compile(r"\[*(?:L[^;]+;|[BCDFIJSZ])")


def _arguments(descriptor: str) -> list[str]:
    """The parameter types of a method descriptor, one entry each."""
    inside = descriptor[descriptor.index("(") + 1:descriptor.index(")")]
    return _DESC_RE.findall(inside)


def _result(descriptor: str) -> str:
    return descriptor[descriptor.index(")") + 1:]


def _is_wide(kind: str) -> bool:
    return kind in ("J", "D")


def _class_of(kind: str) -> str:
    return kind[1:-1] if kind.startswith("L") else ""


def _method_like(kind: str) -> bool:
    return bool(kind.startswith("L") and _METHOD_LIKE_RE.search(kind[1:-1]))


# --- the class index ---------------------------------------------------------------------


@dataclass
class _Method:
    name: str
    descriptor: str
    static: bool
    code: bytes | None


@dataclass
class _Class:
    name: str
    super_name: str | None
    interfaces: list[str]
    pool: dict
    methods: list[_Method]
    access: int = 0

    def find(self, name: str, descriptor: str | None) -> _Method | None:
        for method in self.methods:
            if method.name == name and (descriptor is None or method.descriptor == descriptor):
                return method
        return None


def _parse_class(blob: bytes) -> _Class | None:
    if blob[:4] != b"\xca\xfe\xba\xbe":
        return None
    pool, at = classcode.constant_pool(blob)
    access = int.from_bytes(blob[at:at + 2], "big")
    this = classcode.text(pool, int.from_bytes(blob[at + 2:at + 4], "big")) or ""
    super_index = int.from_bytes(blob[at + 4:at + 6], "big")
    super_name = classcode.text(pool, super_index) if super_index else None
    count = int.from_bytes(blob[at + 6:at + 8], "big")
    interfaces = [
        classcode.text(pool, int.from_bytes(blob[at + 8 + 2 * i:at + 10 + 2 * i], "big")) or ""
        for i in range(count)
    ]
    at += 8 + 2 * count

    def skip_attributes(position: int) -> tuple[int, bytes | None]:
        found = None
        attributes = int.from_bytes(blob[position:position + 2], "big")
        position += 2
        for _ in range(attributes):
            name = classcode.text(pool, int.from_bytes(blob[position:position + 2], "big"))
            length = int.from_bytes(blob[position + 2:position + 6], "big")
            body = blob[position + 6:position + 6 + length]
            if name == "Code":
                size = int.from_bytes(body[4:8], "big")
                found = body[8:8 + size]
            position += 6 + length
        return position, found

    fields = int.from_bytes(blob[at:at + 2], "big")
    at += 2
    for _ in range(fields):
        at, _code = skip_attributes(at + 6)
    methods: list[_Method] = []
    count = int.from_bytes(blob[at:at + 2], "big")
    at += 2
    for _ in range(count):
        flags = int.from_bytes(blob[at:at + 2], "big")
        name = classcode.text(pool, int.from_bytes(blob[at + 2:at + 4], "big")) or ""
        descriptor = classcode.text(pool, int.from_bytes(blob[at + 4:at + 6], "big")) or ""
        at, code = skip_attributes(at + 6)
        methods.append(_Method(name, descriptor, bool(flags & 0x0008), code))
    return _Class(this, super_name, interfaces, pool, methods, access)


class ClassIndex:
    """The classes of the platform jars of one distribution, read on demand."""

    def __init__(self, car: zipfile.ZipFile):
        self._car = car
        self._where: dict[str, tuple[str, str]] = {}
        self._jars: dict[str, zipfile.ZipFile] = {}
        self._parsed: dict[str, _Class | None] = {}
        for entry in car.namelist():
            if not entry.endswith(".jar") or not _PLATFORM_JAR_RE.search(entry):
                continue
            try:
                jar = zipfile.ZipFile(io.BytesIO(car.read(entry)))
            except (zipfile.BadZipFile, KeyError):
                continue
            self._jars[entry] = jar
            for inner in jar.namelist():
                if inner.endswith(".class") and not inner.startswith("META-INF/"):
                    self._where.setdefault(inner[:-6], (entry, inner))

    def names(self) -> list[str]:
        return list(self._where)

    def raw(self, name: str) -> bytes | None:
        where = self._where.get(name)
        if where is None:
            return None
        return self._jars[where[0]].read(where[1])

    def get(self, name: str) -> _Class | None:
        if name not in self._parsed:
            blob = self.raw(name)
            try:
                self._parsed[name] = _parse_class(blob) if blob else None
            except (IndexError, UnicodeDecodeError):
                self._parsed[name] = None
        return self._parsed[name]

    @lru_cache(maxsize=None)
    def ancestors(self, name: str) -> frozenset[str]:
        """Every superclass and interface of a class, transitively."""
        found: set[str] = set()
        klass = self.get(name)
        if klass is None:
            return frozenset()
        for parent in [klass.super_name, *klass.interfaces]:
            if parent and parent not in found:
                found.add(parent)
                found |= self.ancestors(parent)
        return frozenset(found)

    def resolve(self, owner: str, name: str, descriptor: str) -> tuple[str, _Method] | None:
        """The method a call reaches, looked up from `owner` through its superclasses."""
        seen: set[str] = set()
        current: str | None = owner
        while current and current not in seen:
            seen.add(current)
            klass = self.get(current)
            if klass is None:
                return None
            method = klass.find(name, descriptor)
            if method is not None and method.code is not None:
                return current, method
            current = klass.super_name
        # A default method of an interface.
        for parent in self.ancestors(owner):
            klass = self.get(parent)
            method = klass.find(name, descriptor) if klass else None
            if method is not None and method.code is not None:
                return parent, method
        return None


# --- the interpreter ---------------------------------------------------------------------


@dataclass
class Found:
    """One handler a provider declares on one path."""

    tested: str            # the project type class the path tested the type against
    name: tuple            # ("term", en, ru) or ("dyn", source)
    low: tuple | None      # the first mode the path admits (inclusive), None - any
    high: tuple | None     # the first mode it no longer admits, None - any
    requires: frozenset = frozenset()  # instanceof tests of other values on the path
    managed: bool = False  # past the test for an access-control target (see access_managers)
    target_requires: frozenset = frozenset()  # instanceof tests of that target
    kind: tuple | None = None  # the term of the kind a kind test chose (see _KIND_TESTS)


@dataclass
class _Path:
    pc: int
    stack: list
    locals: dict
    visits: dict = field(default_factory=dict)
    tested: str | None = None
    low: tuple | None = None
    high: tuple | None = None
    requires: frozenset = frozenset()
    lists: dict = field(default_factory=dict)
    managed: bool = False
    target_requires: frozenset = frozenset()
    kind: tuple | None = None

    def fork(self, pc: int) -> _Path:
        return _Path(pc, list(self.stack), dict(self.locals), dict(self.visits), self.tested,
                     self.low, self.high, self.requires, dict(self.lists), self.managed,
                     self.target_requires, self.kind)

    def branch(self) -> _Path:
        """A fresh start on the facts of this branch: a helper or a lambda runs on it."""
        return _Path(0, [], {}, {}, self.tested, self.low, self.high, self.requires, {},
                     self.managed, self.target_requires, self.kind)


def _mode_key(text: str) -> tuple[int, ...]:
    return tuple(int(part) for part in text.split("."))


class Interpreter:
    """Runs provider code over abstract values; see the module docstring."""

    def __init__(self, index: ClassIndex):
        self.index = index
        self.found: list[Found] = []
        self.incomplete: set[str] = set()
        self._statics: dict[str, dict[str, object]] = {}
        self._initializing: dict[str, dict[str, list]] = {}
        self._summaries: dict[tuple, object] = {}
        self._serial = 0
        self._modes: list[tuple[int, ...]] | None = None

    # -- the modes the platform knows, for `le` and `gt` ---------------------------------
    def modes(self) -> list[tuple[int, ...]]:
        if self._modes is None:
            klass = self.index.get(_MODE_CLASS)
            names = set()
            if klass is not None:
                for tag, value in klass.pool.values():
                    if tag == 1 and isinstance(value, str) and value.startswith("CMODE_"):
                        parts = value[len("CMODE_"):].split("_")
                        if all(part.isdigit() for part in parts):
                            names.add(tuple(int(part) for part in parts))
            self._modes = sorted(names)
        return self._modes

    def _after(self, mode: tuple[int, ...]) -> tuple[int, ...] | None:
        later = [known for known in self.modes() if known > mode]
        return later[0] if later else None

    # -- static fields ---------------------------------------------------------------------
    def static(self, owner: str, name: str, depth: int):
        """The value a class initializer stores into one of its static fields."""
        live = self._initializing.get(owner)
        if live is not None:
            # The initializer reads a field it has already written.
            return _join(live[name]) if live.get(name) else None
        if owner not in self._statics:
            self._statics[owner] = {}
            klass = self.index.get(owner)
            init = klass.find("<clinit>", "()V") if klass else None
            if init is not None and init.code is not None:
                stores: dict[str, list] = {}
                self._initializing[owner] = stores
                try:
                    self._run(owner, init, [], depth + 1, stores=stores, record=False)
                finally:
                    del self._initializing[owner]
                self._statics[owner] = {key: _join(values) for key, values in stores.items()}
        return self._statics[owner].get(name)

    # -- calls -----------------------------------------------------------------------------
    def summary(self, owner: str, method: _Method, args: list, depth: int):
        """The value a method returns for these arguments, joined over its paths."""
        key = (owner, method.name, method.descriptor, repr(args))
        if key in self._summaries:
            return self._summaries[key]
        self._summaries[key] = None  # recursion answers unknown
        returned: list = []
        self._run(owner, method, args, depth + 1, returned=returned, record=False)
        value = _join(returned) if returned else None
        self._summaries[key] = value
        return value

    def run_provider(self, owner: str) -> None:
        klass = self.index.get(owner)
        if klass is None:
            return
        for method in klass.methods:
            if method.name == _PROVIDER_METHOD and method.code is not None \
                    and method.descriptor.startswith("(Lcom/e1c/g5rt/appengine/core/mdd/common/types/"):
                args = [("obj", owner), ("param", 1), None, ("mode",)]
                self._run(owner, method, args, 0, record=True, provider=owner)

    def _run(self, owner: str, method: _Method, args: list, depth: int, *,
             returned: list | None = None, stores: dict | None = None, record: bool,
             provider: str | None = None, start: _Path | None = None) -> None:
        if depth > _MAX_DEPTH or method.code is None:
            return
        klass = self.index.get(owner)
        if klass is None:
            return
        pool = klass.pool
        code = method.code
        locals_: dict[int, object] = {}
        slot = 0
        for value, kind in zip(args, (["L"] if not method.static else []) + _arguments(method.descriptor)):
            locals_[slot] = value
            slot += 2 if _is_wide(kind) else 1
        paths = [start or _Path(0, [], locals_)]
        explored = 0
        steps = 0
        while paths:
            path = paths.pop()
            explored += 1
            if explored > _MAX_PATHS:
                if provider:
                    self.incomplete.add(provider)
                return
            while True:
                steps += 1
                if steps > _MAX_STEPS:
                    if provider:
                        self.incomplete.add(provider)
                    return
                visits = path.visits.get(path.pc, 0)
                if visits >= _MAX_VISITS:
                    break
                path.visits[path.pc] = visits + 1
                outcome = self._step(owner, pool, code, path, depth, returned, stores, record,
                                     provider)
                if outcome is None:
                    break
                paths.extend(outcome[1:])
                if not outcome[0]:
                    break

    # -- one instruction -------------------------------------------------------------------
    def _step(self, owner, pool, code, path: _Path, depth, returned, stores, record, provider):
        """Execute the instruction at path.pc. Returns (continue?, *forked paths) or None."""
        at = path.pc
        op = code[at]
        stack = path.stack

        def pop(count: int = 1):
            taken = []
            for _ in range(count):
                taken.append(stack.pop() if stack else None)
            return taken[::-1] if count > 1 else taken[0]

        def advance(size: int):
            path.pc = at + 1 + size
            return (True,)

        def branch(target: int, fall: _Path, jump: _Path):
            fall.pc = at + 3
            jump.pc = target
            return (False, fall, jump)

        u2 = lambda: int.from_bytes(code[at + 1:at + 3], "big")  # noqa: E731
        s2 = lambda: int.from_bytes(code[at + 1:at + 3], "big", signed=True)  # noqa: E731

        if op == 0x00:
            return advance(0)
        if op == 0x01:
            stack.append(("null",))
            return advance(0)
        if 0x02 <= op <= 0x08:
            stack.append(("int", op - 0x03))
            return advance(0)
        if op in (0x09, 0x0A, 0x0E, 0x0F):
            stack.append(("wide",))
            return advance(0)
        if 0x0B <= op <= 0x0D:
            stack.append(None)
            return advance(0)
        if op == 0x10:
            stack.append(("int", int.from_bytes(code[at + 1:at + 2], "big", signed=True)))
            return advance(1)
        if op == 0x11:
            stack.append(("int", s2()))
            return advance(2)
        if op in (0x12, 0x13):
            index = code[at + 1] if op == 0x12 else u2()
            entry = pool.get(index)
            if entry and entry[0] == 8:
                stack.append(("str", classcode.text(pool, index)))
            else:
                stack.append(None)
            return advance(1 if op == 0x12 else 2)
        if op == 0x14:
            stack.append(("wide",))
            return advance(2)
        if 0x15 <= op <= 0x19:
            stack.append(path.locals.get(code[at + 1]) if op != 0x16 and op != 0x18 else ("wide",))
            return advance(1)
        if 0x1A <= op <= 0x2D:
            kind, index = divmod(op - 0x1A, 4)
            stack.append(("wide",) if kind in (1, 3) else path.locals.get(index))
            return advance(0)
        if 0x2E <= op <= 0x35:
            pop(2)
            stack.append(("wide",) if op in (0x2F, 0x31) else None)
            return advance(0)
        if 0x36 <= op <= 0x3A:
            path.locals[code[at + 1]] = pop()
            return advance(1)
        if 0x3B <= op <= 0x4E:
            _kind, index = divmod(op - 0x3B, 4)
            path.locals[index] = pop()
            return advance(0)
        if 0x4F <= op <= 0x56:
            pop(3)
            return advance(0)
        if op == 0x57:
            pop()
            return advance(0)
        if op == 0x58:
            top = pop()
            if top != ("wide",):
                pop()
            return advance(0)
        if op == 0x59:
            value = stack[-1] if stack else None
            stack.append(value)
            return advance(0)
        if op == 0x5A:
            first, second = pop(), pop()
            stack.extend([first, second, first])
            return advance(0)
        if op == 0x5B:
            first, second = pop(), pop()
            if second == ("wide",):
                stack.extend([first, second, first])
            else:
                third = pop()
                stack.extend([first, third, second, first])
            return advance(0)
        if op == 0x5C:
            first = pop()
            if first == ("wide",):
                stack.extend([first, first])
            else:
                second = pop()
                stack.extend([second, first, second, first])
            return advance(0)
        if op in (0x5D, 0x5E):
            first = pop()
            if first == ("wide",):
                second = pop()
                stack.extend([first, second, first])
            else:
                second, third = pop(), pop()
                stack.extend([second, first, third, second, first])
            return advance(0)
        if op == 0x5F:
            first, second = pop(), pop()
            stack.extend([first, second])
            return advance(0)
        if 0x60 <= op <= 0x73 or 0x78 <= op <= 0x83:
            pop(2)
            stack.append(("wide",) if op in (0x61, 0x63, 0x65, 0x67, 0x69, 0x6B, 0x6D, 0x6F,
                                             0x71, 0x73, 0x79, 0x7B, 0x7D, 0x7F, 0x81, 0x83)
                         else None)
            return advance(0)
        if 0x74 <= op <= 0x77:
            value = pop()
            stack.append(value if value == ("wide",) else None)
            return advance(0)
        if op == 0x84:
            return advance(2)
        if 0x85 <= op <= 0x93:
            pop()
            stack.append(("wide",) if op in (0x85, 0x87, 0x8A, 0x8C, 0x8D, 0x8F) else None)
            return advance(0)
        if 0x94 <= op <= 0x98:
            pop(2)
            stack.append(None)
            return advance(0)
        if 0x99 <= op <= 0x9E or op in (0xC6, 0xC7):
            value = pop()
            target = at + s2()
            return self._condition(path, op, value, target, at)
        if 0x9F <= op <= 0xA6:
            left, right = pop(2)
            target = at + s2()
            fall, jump = path.fork(at + 3), path.fork(target)
            if op in (0xA5, 0xA6):  # if_acmpeq / if_acmpne
                tested = _tested_by_equality(left, right)
                if tested:
                    same, other = (jump, fall) if op == 0xA5 else (fall, jump)
                    if same.tested not in (None, tested):
                        return (False, other)
                    same.tested = tested
            return (False, fall, jump)
        if op == 0xA7:
            path.pc = at + s2()
            return (True,)
        if op == 0xC8:
            path.pc = at + int.from_bytes(code[at + 1:at + 5], "big", signed=True)
            return (True,)
        if op in (0xA8, 0xA9, 0xC9):
            return None
        if op in (0xAA, 0xAB):
            pop()
            base = at + 1
            while base % 4:
                base += 1
            default = at + int.from_bytes(code[base:base + 4], "big", signed=True)
            targets = [default]
            if op == 0xAA:
                low = int.from_bytes(code[base + 4:base + 8], "big", signed=True)
                high = int.from_bytes(code[base + 8:base + 12], "big", signed=True)
                for i in range(high - low + 1):
                    offset = base + 12 + 4 * i
                    targets.append(at + int.from_bytes(code[offset:offset + 4], "big", signed=True))
            else:
                pairs = int.from_bytes(code[base + 4:base + 8], "big")
                for i in range(pairs):
                    offset = base + 8 + 8 * i + 4
                    targets.append(at + int.from_bytes(code[offset:offset + 4], "big", signed=True))
            forks = []
            for target in dict.fromkeys(targets):
                forks.append(path.fork(target))
            return (False, *forks)
        if 0xAC <= op <= 0xB0:
            value = pop()
            if returned is not None:
                if isinstance(value, tuple) and value[0] == "listref":
                    value = ("list", path.lists.get(value[1], ()))
                returned.append(value)
            return None
        if op == 0xB1:
            return None
        if op == 0xB2:
            ref = u2()
            field_owner, name, descriptor = _field_ref(pool, ref)
            stack.append(self._getstatic(field_owner, name, descriptor, depth))
            return advance(2)
        if op == 0xB3:
            ref = u2()
            field_owner, name, _descriptor = _field_ref(pool, ref)
            value = pop()
            if isinstance(value, tuple) and value[0] == "listref":
                value = ("list", path.lists.get(value[1], ()))
            if stores is not None and field_owner == owner:
                stores.setdefault(name, []).append(value)
            return advance(2)
        if op == 0xB4:
            ref = u2()
            pop()
            _field_owner, _name, descriptor = _field_ref(pool, ref)
            stack.append(("wide",) if _is_wide(descriptor) else None)
            return advance(2)
        if op == 0xB5:
            pop(2)
            return advance(2)
        if 0xB6 <= op <= 0xB9:
            forks = self._invoke(owner, pool, code, path, op, depth, record, provider)
            return (True, *forks) if forks else advance(4 if op == 0xB9 else 2)
        if op == 0xBA:
            index = u2()
            descriptor = _indy_descriptor(pool, index)
            count = len(_arguments(descriptor)) if descriptor else 0
            captured = pop(count) if count > 1 else ([pop()] if count == 1 else [])
            target = _indy_target(self.index, owner, pool, index)
            stack.append(("lambda", *target, tuple(captured)) if target else None)
            return advance(4)
        if op == 0xBB:
            self._serial += 1
            stack.append(("new", classcode.text(pool, u2()) or "", self._serial))
            return advance(2)
        if op in (0xBC, 0xBD):
            pop()
            stack.append(None)
            return advance(1 if op == 0xBC else 2)
        if op == 0xBE:
            pop()
            stack.append(None)
            return advance(0)
        if op == 0xBF:
            return None
        if op == 0xC0:
            return advance(2)
        if op == 0xC1:
            value = pop()
            stack.append(("isinst", value, classcode.text(pool, u2()) or ""))
            return advance(2)
        if op in (0xC2, 0xC3):
            pop()
            return advance(0)
        if op == 0xC4:
            widened = code[at + 1]
            index = int.from_bytes(code[at + 2:at + 4], "big")
            if 0x15 <= widened <= 0x19:
                stack.append(path.locals.get(index))
            elif 0x36 <= widened <= 0x3A:
                path.locals[index] = pop()
            path.pc = at + (6 if widened == 0x84 else 4)
            return (True,)
        if op == 0xC5:
            pop(code[at + 3])
            stack.append(None)
            return advance(3)
        return None

    # -- conditions ------------------------------------------------------------------------
    def _condition(self, path: _Path, op: int, value, target: int, at: int):
        fall, jump = path.fork(at + 3), path.fork(target)
        if op in (0xC6, 0xC7) and value == ("target",):
            # ifnonnull jumps when the module has an access-control target, ifnull when not.
            present = jump if op == 0xC7 else fall
            present.managed = True
            return (False, fall, jump)
        if op in (0x99, 0x9A) and isinstance(value, tuple):
            # ifeq jumps when the test is false, ifne when it is true.
            true, false = (fall, jump) if op == 0x99 else (jump, fall)
            if value[0] == "kindtest":
                term = self.static(*_KIND_TESTS[value[1]], 0)
                if isinstance(term, tuple) and term[0] == "term":
                    false.kind = term
                return (False, fall, jump)
            if value[0] == "isinst":
                subject, tested = value[1], value[2]
                if subject == ("param", 1):
                    if true.tested is not None and true.tested != tested:
                        # Already inside a branch of another type: both may hold (a subtype).
                        true.requires = true.requires | {tested}
                    else:
                        true.tested = tested
                elif subject == ("target",):
                    true.target_requires = true.target_requires | {tested}
                else:
                    true.requires = true.requires | {tested}
            elif value[0] == "modetest":
                operation, mode = value[1], _mode_key(value[2])
                after = self._after(mode)
                if operation == "ge":
                    _raise(true, mode), _lower(false, mode)
                elif operation == "lt":
                    _lower(true, mode), _raise(false, mode)
                elif operation == "gt":
                    _raise(true, after), _lower(false, after)
                elif operation == "le":
                    _lower(true, after), _raise(false, after)
                return (False, *[p for p in (fall, jump) if _feasible(p)])
        return (False, fall, jump)

    # -- static field reads ----------------------------------------------------------------
    def _getstatic(self, field_owner: str, name: str, descriptor: str, depth: int):
        if field_owner == _MODE_CLASS and name.startswith("CMODE_"):
            return ("cmode", name[len("CMODE_"):].replace("_", "."))
        if name == "INSTANCE":
            return ("instance", field_owner)
        if descriptor == _TERM_DESCRIPTOR or _method_like(descriptor) \
                or descriptor in ("Ljava/util/List;", "Ljava/util/Collection;"):
            value = self.static(field_owner, name, depth)
            if value is None and descriptor == _TERM_DESCRIPTOR:
                return ("dyn", f"{field_owner}.{name}")
            return value
        return None

    # -- calls -----------------------------------------------------------------------------
    def _invoke(self, owner, pool, code, path: _Path, op, depth, record, provider):
        stack = path.stack
        ref = int.from_bytes(code[path.pc + 1:path.pc + 3], "big")
        called = classcode.called_method(pool, ref) or ""
        descriptor = classcode.method_descriptor(pool, ref) or "()V"
        callee_owner, _dot, callee = called.rpartition(".")
        kinds = _arguments(descriptor)
        args = [stack.pop() if stack else None for _ in kinds][::-1]
        receiver = None
        if op != 0xB8:
            receiver = stack.pop() if stack else None
        result_kind = _result(descriptor)
        result = self._call(owner, path, op, callee_owner, callee, descriptor, kinds, args,
                            receiver, depth, record, provider)
        if callee == "<init>" and isinstance(receiver, tuple) and receiver[0] == "new":
            made = result if result is not None else ("obj", receiver[1])
            path.stack[:] = [made if item == receiver else item for item in path.stack]
            path.locals = {k: (made if v == receiver else v) for k, v in path.locals.items()}
        elif result_kind != "V":
            stack.append(("wide",) if _is_wide(result_kind) else result)
        return None

    def _call(self, owner, path, op, callee_owner, callee, descriptor, kinds, args, receiver,
              depth, record, provider):
        simple = callee_owner.rsplit("/", 1)[-1]
        result_kind = _result(descriptor)
        # The target of the module whose access the access-control info controls (see the
        # module docstring), and the test of an item type that picks one of two kinds.
        if callee_owner == _ACCESS_INFO and callee == "getTargetType" and args == [("param", 1)]:
            return ("target",)
        if (callee_owner, callee) in _KIND_TESTS:
            return ("kindtest", (callee_owner, callee))
        # The sink: the method a handler is declared by.
        if f"{simple}.{callee}".endswith(_SINK) or called_is(callee_owner, callee, _SINK):
            if record and provider:
                for meth in _meths(args[0] if args else None) or [("meth", ("dyn", "unknown"))]:
                    self._record(path, meth[1])
            return args[0] if args else None
        # Terms built of their two spellings.
        if callee_owner == _TERM_CLASS and result_kind == _TERM_DESCRIPTOR:
            strings = [a[1] for a in args if isinstance(a, tuple) and a[0] == "str"]
            if len(strings) >= 2 and strings[-2].isascii() and not strings[-1].isascii():
                return ("term", strings[-2], strings[-1])
            if callee == "term" and len(strings) >= 2:
                return ("term", strings[-2], strings[-1])
        if callee_owner.endswith("Term$TermWithHistory$Builder") and callee == "add":
            strings = [a[1] for a in args if isinstance(a, tuple) and a[0] == "str"]
            if isinstance(receiver, tuple) and receiver[0] == "twh":
                if receiver[1] is None and len(strings) >= 2:
                    return ("twh", ("term", strings[-2], strings[-1]))
                return receiver
        if callee_owner.endswith("Term$TermWithHistory") and callee == "builder":
            return ("twh", None)
        if callee_owner.endswith("Term$TermWithHistory$Builder") and callee == "build":
            if isinstance(receiver, tuple) and receiver[0] == "twh" and receiver[1]:
                return receiver[1]
            return ("dyn", "history")
        # The name of a method description, asked back (`symbol.getName()`).
        if result_kind == _TERM_DESCRIPTOR and isinstance(receiver, tuple) \
                and receiver[0] == "meth" and not args:
            return receiver[1]
        # The compatibility mode compared.
        if callee_owner == _MODE_CLASS and callee in _MODE_TESTS and receiver == ("mode",) \
                and args and isinstance(args[0], tuple) and args[0][0] == "cmode":
            return ("modetest", callee, args[0][1])
        # Collections of method descriptions: made, filled, streamed, iterated.
        if callee == "<init>" and callee_owner in ("java/util/ArrayList", "java/util/LinkedList"):
            self._serial += 1
            return ("listref", self._serial)
        if callee in ("add", "addAll") and isinstance(receiver, tuple) and receiver[0] == "listref":
            items = path.lists.get(receiver[1], ())
            value = args[-1] if args else None
            if isinstance(value, tuple) and value[0] == "listref":
                value = ("list", path.lists.get(value[1], ()))
            added = tuple(value[1]) if callee == "addAll" and isinstance(value, tuple) \
                and value[0] in ("list", "stream") else (value,)
            path.lists[receiver[1]] = items + tuple(item for item in added if item is not None)
            return None
        listed = receiver
        if isinstance(listed, tuple) and listed[0] == "listref":
            listed = ("list", path.lists.get(listed[1], ()))
        if callee in ("asList", "of", "listOf", "mutableListOf", "singletonList", "arrayListOf"):
            return ("list", tuple(a for a in args if a is not None))
        if callee == "stream" and _meths(listed):
            return ("stream", tuple(_meths(listed)))
        if callee == "iterator" and _meths(listed):
            return ("iter", tuple(_meths(listed)))
        if callee == "next" and isinstance(receiver, tuple) and receiver[0] == "iter":
            items = receiver[1]
            return _join(list(items)) if items else None
        if callee == "map" and isinstance(receiver, tuple) and receiver[0] == "stream":
            lambda_ = args[0] if args else None
            mapped = []
            for item in receiver[1]:
                mapped.append(self._apply(lambda_, item, path, depth, record, provider))
            return ("stream", tuple(mapped))
        if callee == "collect" and isinstance(receiver, tuple) and receiver[0] == "stream":
            return ("list", receiver[1])
        # A method description made from its name, or carried along a builder chain.
        made_here = _METHOD_LIKE_RE.search(callee_owner) and (
            callee == "<init>" or (op == 0xB8 and _method_like(result_kind)))
        carried = [value for value in [receiver, *args] if _meths(value)]
        if carried and _method_like(result_kind):
            return carried[0]
        if made_here and not carried:
            for value, kind in zip(args, kinds):
                if kind == _TERM_DESCRIPTOR:
                    return ("meth", value if _is_term(value) else ("dyn", "argument"))
            strings = [a[1] for a in args if isinstance(a, tuple) and a[0] == "str"]
            if len(strings) >= 2:
                return ("meth", ("term", strings[0], strings[1]))
        if callee == "<init>":
            return None
        # Anything else: run it, when the distribution has its code.
        return self._run_callee(owner, op, callee_owner, callee, descriptor, args, receiver,
                                depth, result_kind, path, record, provider)

    def _run_callee(self, owner, op, callee_owner, callee, descriptor, args, receiver, depth,
                    result_kind, path, record, provider):
        interesting = (_method_like(result_kind) or result_kind == _TERM_DESCRIPTOR
                       or result_kind in ("Ljava/util/List;", "Ljava/util/Collection;"))
        if not interesting:
            return None
        target_owner = callee_owner
        if op in (0xB6, 0xB9) and isinstance(receiver, tuple) and receiver[0] == "obj":
            target_owner = receiver[1]
        found = self.index.resolve(target_owner, callee, descriptor)
        if found is None:
            if result_kind == _TERM_DESCRIPTOR:
                return ("dyn", f"{callee_owner}.{callee}")
            if _method_like(result_kind):
                return ("meth", ("dyn", f"{callee_owner}.{callee}"))
            return None
        where, method = found
        call_args = ([] if method.static else [receiver]) + list(args)
        if record and provider and where == provider:
            # A helper of the provider itself may declare handlers: it runs on the caller's
            # branch, with the type and the modes the caller has tested.
            start = path.branch()
            slot = 0
            kinds = (["L"] if not method.static else []) + _arguments(method.descriptor)
            for value, kind in zip(call_args, kinds):
                start.locals[slot] = value
                slot += 2 if _is_wide(kind) else 1
            returned: list = []
            self._run(where, method, call_args, depth + 1, returned=returned, record=True,
                      provider=provider, start=start)
            return _join(returned) if returned else None
        value = self.summary(where, method, call_args, depth)
        if value is None and result_kind == _TERM_DESCRIPTOR:
            return ("dyn", f"{callee_owner}.{callee}")
        return value

    def _apply(self, lambda_, item, path, depth, record, provider):
        """Run a lambda of the provider over one item of a stream, sinks included."""
        if not (isinstance(lambda_, tuple) and lambda_[0] == "lambda"):
            return None
        _tag, owner, name, descriptor, captured = lambda_
        klass = self.index.get(owner)
        method = klass.find(name, descriptor) if klass else None
        if method is None:
            return None
        args = ([] if method.static else [None]) + list(captured) + [item]
        start = path.branch()
        slot = 0
        kinds = (["L"] if not method.static else []) + _arguments(method.descriptor)
        for value, kind in zip(args, kinds):
            start.locals[slot] = value
            slot += 2 if _is_wide(kind) else 1
        returned: list = []
        self._run(owner, method, args, depth + 1, returned=returned, record=record,
                  provider=provider, start=start)
        return _join(returned) if returned else None

    def _record(self, path: _Path, name) -> None:
        if path.tested is None:
            return
        self.found.append(Found(path.tested, name, path.low, path.high, path.requires,
                                path.managed, path.target_requires, path.kind))


def called_is(owner: str, name: str, suffix: str) -> bool:
    return f"{owner}.{name}".endswith(suffix)


def _raise(path: _Path, mode) -> None:
    if mode is not None and (path.low is None or mode > path.low):
        path.low = mode


def _lower(path: _Path, mode) -> None:
    if mode is None:
        path.low = (1 << 30,)  # below "no mode at all": the path is infeasible
        return
    if path.high is None or mode < path.high:
        path.high = mode


def _feasible(path: _Path) -> bool:
    return path.low is None or path.high is None or path.low < path.high


def _tested_by_equality(left, right) -> str | None:
    """`type == SomeType.INSTANCE`: the class the provider compares its type parameter with."""
    for one, other in ((left, right), (right, left)):
        if one == ("param", 1) and isinstance(other, tuple) and other[0] == "instance":
            return other[1]
    return None


def _field_ref(pool, index: int) -> tuple[str, str, str]:
    entry = pool.get(index)
    if not entry or entry[0] != 9:
        return "", "", ""
    class_index, name_and_type = entry[1]
    described = pool.get(name_and_type)
    if not described or described[0] != 12:
        return "", "", ""
    return (classcode.text(pool, class_index) or "", classcode.text(pool, described[1][0]) or "",
            classcode.text(pool, described[1][1]) or "")


def _indy_descriptor(pool, index: int) -> str | None:
    entry = pool.get(index)
    if not entry or entry[0] != 18:
        return None
    described = pool.get(entry[1][1])
    if not described or described[0] != 12:
        return None
    return classcode.text(pool, described[1][1])


def _indy_target(index: ClassIndex, owner: str, pool, at: int) -> tuple[str, str, str] | None:
    """(class, method, descriptor) a lambda of `owner` runs: its synthetic `lambda$` method.

    The bootstrap arguments that name the implementation are not kept by the pool reader, so
    the lambda is found by its shape: the one synthetic method of the class whose number is
    the order of the call site. A provider has one or two, and they all take the item last.
    """
    klass = index.get(owner)
    if klass is None:
        return None
    lambdas = [m for m in klass.methods if m.name.startswith("lambda$")]
    if len(lambdas) == 1:
        method = lambdas[0]
        return owner, method.name, method.descriptor
    for method in lambdas:
        if method.name.endswith("$0"):
            return owner, method.name, method.descriptor
    return None


# --- from the provider classes to the element kinds ----------------------------------------


def providers(index: ClassIndex) -> list[str]:
    """The classes that implement the provider interface, in name order."""
    found = []
    needle = PROVIDER_INTERFACE.encode()
    for name in index.names():
        blob = index.raw(name)
        if blob is None or needle not in blob:
            continue
        klass = index.get(name)
        if klass is not None and PROVIDER_INTERFACE in klass.interfaces:
            found.append(name)
    return sorted(found)


def implementors(index: ClassIndex, root: str) -> list[str]:
    """Every concrete class that implements or extends `root`, however deep, in name order.

    A class names its superclass and its interfaces in its constant pool, so each round reads
    the classes that mention a name found in the round before: the abstract bases first, then
    the classes that extend them.
    """
    found: set[str] = set()
    frontier = {root}
    names = index.names()
    while frontier:
        needles = [name.encode() for name in frontier]
        fresh: set[str] = set()
        for name in names:
            if name in found or name == root:
                continue
            blob = index.raw(name)
            if blob is None or not any(needle in blob for needle in needles):
                continue
            klass = index.get(name)
            if klass is not None and (klass.super_name in frontier
                                      or any(parent in frontier for parent in klass.interfaces)):
                fresh.add(name)
        found |= fresh
        frontier = fresh
    return sorted(name for name in found if not (index.get(name).access & 0x0600))


def _type_class_owner(index: ClassIndex, owner: str, method: str) -> str | None:
    """The project type class a `TypeClass` getter answers with, None for null or the unknown.

    Such a getter reads the `TYPE_CLASS` constant of the class (or its companion object, in
    Kotlin) right away: the class of the field it starts with is the answer.
    """
    found = index.resolve(owner, method, _TYPE_CLASS_DESCRIPTOR)
    if found is None:
        return None
    where, code = found[0], found[1].code
    if not code or code[0] != 0xB2:  # aconst_null, or code that is not a plain getter
        return None
    klass = index.get(where)
    field_owner, _name, _descriptor = _field_ref(klass.pool, int.from_bytes(code[1:3], "big"))
    return field_owner or None


def access_managers(index: ClassIndex) -> dict[str, str]:
    """{the project type class of a manager module: the target class it controls the access of}.

    What the access-control info answers `getTargetType` from: every part of it names a target
    type class and the type class of the module that manages it, and a part without a manager
    (the system actions, the records of a data journal, the objects of an entity contract) gives
    no module a target.
    """
    managers: dict[str, str] = {}
    for part in implementors(index, _ACCESS_INFO_PART):
        manager = _type_class_owner(index, part, "getManagerTypeClass")
        target = _type_class_owner(index, part, "getTargetTypeClass")
        if manager and target:
            managers[manager] = target
    return managers


def facet_words(car: zipfile.ZipFile) -> tuple[dict[str, str], dict[str, str]]:
    """({English facet word: Russian}, {English type: Russian}) from the facet pages of the help.

    A facet page lives under `<Type>.<Facet>_ru/` and its title spells both parts in Russian:
    the pair of the words a class name and a module file use (`Object` and its Russian twin).
    """
    words: dict[str, str] = {}
    types: dict[str, str] = {}
    title_re = re.compile(r"<title[^>]*>(.*?)</title>", re.S)
    path_re = re.compile(r"/([A-Za-z]+)\.([A-Za-z]+)_ru/index\.html$")
    for entry in car.namelist():
        if "/stdlib/element/xbsl/" not in entry:
            continue
        match = path_re.search(entry)
        if not match:
            continue
        found = title_re.search(car.read(entry).decode("utf-8", "replace"))
        title = found.group(1).split("|")[0].strip() if found else ""
        if title.count(".") != 1:
            continue
        russian_type, russian_facet = title.split(".")
        words.setdefault(match.group(2), russian_facet)
        types.setdefault(match.group(1), russian_type)
    return words, types


def element_of(class_name: str, kinds: dict[str, str], words: dict[str, str],
               types: dict[str, str]) -> tuple[str, str] | None:
    """(Russian element kind, Russian module facet or "") a project type class stands for."""
    simple = class_name.rsplit("/", 1)[-1].rsplit("$", 1)[-1]
    if not simple.endswith(_TYPE_SUFFIX):
        return None
    stem = simple[:-len(_TYPE_SUFFIX)]
    for alias, english in _KIND_ALIASES.items():
        if stem.startswith(alias):
            stem = english + stem[len(alias):]
    english_kinds = {english: russian for russian, english in kinds.items()}
    candidates = sorted((e for e in english_kinds if stem.startswith(e)), key=len, reverse=True)
    for english in candidates:
        rest = stem[len(english):]
        rest = _FACET_ALIASES.get(rest, rest)
        if not rest:
            return english_kinds[english], ""
        if rest in words:
            return english_kinds[english], words[rest]
    for english, russian in types.items():
        if stem.startswith(english):
            rest = _FACET_ALIASES.get(stem[len(english):], stem[len(english):])
            if rest in words:
                return russian, words[rest]
    return None


def controls(index, managers: dict[str, str], class_name: str, found: Found) -> bool:
    """Whether a path past the target test stands for the module of `class_name`.

    It does when the class manages a target (access_managers) and the target passes every test
    the path made of it; `index` answers the ancestors of the target class.
    """
    target = managers.get(class_name)
    return target is not None and all(
        required == target or required in index.ancestors(target)
        for required in found.target_requires)


def _merge_modes(spans: list[tuple]) -> tuple[tuple | None, tuple | None] | None:
    """One range for the spans a handler is declared on, or None when they leave a gap."""
    ordered = sorted(spans, key=lambda span: (span[0] or (), ))
    low, high = ordered[0]
    for start, end in ordered[1:]:
        if high is None:
            break
        if start is not None and start > high:
            return None
        if end is None or end > high:
            high = end
    if any(span[0] is None for span in spans):
        low = None
    return low, high


def _mode_text(mode: tuple | None) -> str:
    return ".".join(str(part) for part in mode) if mode else ""


def element_handlers(car: zipfile.ZipFile, kinds: dict[str, str]) -> tuple[dict, list[str]]:
    """({Russian kind: {facet: {"handlers": [rows], "dynamic": [sources]}}}, notes).

    `kinds` is the kind table of the distribution (Russian kind: English). A row is
    {"ru", "en"} plus `from`/`to` when the handler is declared in some compatibility modes
    only (a half-open range, as the component descriptions write it). `dynamic` names the
    places a handler name is read from at build time; a module with it is not to be judged.
    """
    index = ClassIndex(car)
    words, types = facet_words(car)
    interpreter = Interpreter(index)
    notes: list[str] = []
    found_providers = providers(index)
    for provider in found_providers:
        interpreter.run_provider(provider)
    notes.append(f"провайдеров обработчиков: {len(found_providers)}")

    # A branch may test an interface (every own module of an element is a singleton type):
    # it stands for every project type class that implements it.
    project_types = [name for name in index.names() if name.endswith(_TYPE_SUFFIX)]

    def expand(tested: str) -> list[str]:
        klass = index.get(tested)
        if klass is not None and not (klass.access & 0x0600):  # neither interface nor abstract
            return [tested]
        return [name for name in project_types
                if tested in index.ancestors(name) and not (index.get(name).access & 0x0600)]

    @lru_cache(maxsize=None)
    def kinds_with(required: str) -> frozenset[str]:
        return frozenset(element[0] for name in project_types if required in index.ancestors(name)
                         for element in [element_of(name, kinds, words, types)] if element)

    managers = access_managers(index)
    notes.append(f"модулей с целью контроля доступа: {len(managers)}")

    table: dict[str, dict[str, dict]] = {}
    spans: dict[tuple[str, str, str], list] = {}
    rows: dict[tuple[str, str, str], dict] = {}
    unmapped: set[str] = set()
    unknown: set[str] = set()
    for found in interpreter.found:
        for class_name in expand(found.tested):
            if found.managed and not controls(index, managers, class_name, found):
                continue
            element = element_of(class_name, kinds, words, types)
            if element is None:
                unmapped.add(class_name)
                continue
            kind, facet = element
            if found.kind is not None:
                if found.kind[2] not in kinds:
                    unknown.add(found.kind[2])
                    continue
                kind = found.kind[2]
            if kind == COMPONENT_KIND:
                continue  # the component descriptions list these, per base component
            if any(kind not in kinds_with(required) for required in found.requires):
                continue
            slot = table.setdefault(kind, {}).setdefault(facet, {"handlers": [], "dynamic": []})
            if found.name[0] != "term":
                source = found.name[1].rsplit("/", 1)[-1]
                if source not in slot["dynamic"]:
                    slot["dynamic"].append(source)
                continue
            _tag, english, russian = found.name
            key = (kind, facet, russian)
            spans.setdefault(key, []).append((found.low, found.high))
            rows.setdefault(key, {"ru": russian, "en": english})
    for provider in sorted(interpreter.incomplete):
        notes.append(f"провайдер не пройден до конца, его модули динамические: {provider}")
    for (kind, facet, russian), row in rows.items():
        merged = _merge_modes(spans[(kind, facet, russian)])
        entry = dict(row)
        if merged is not None:
            low, high = merged
            if low is not None:
                entry["from"] = _mode_text(low)
            if high is not None:
                entry["to"] = _mode_text(high)
        table[kind][facet]["handlers"].append(entry)
    for kind in table:
        for facet in table[kind]:
            slot = table[kind][facet]
            slot["handlers"].sort(key=lambda row: row["ru"])
            if not slot["dynamic"]:
                del slot["dynamic"]
    for name in sorted(unmapped):
        notes.append(f"тип проекта без вида элемента: {name}")
    for name in sorted(unknown):
        notes.append(f"вида по проверке типа нет в таблице видов: {name}")
    ordered = {kind: dict(sorted(facets.items())) for kind, facets in sorted(table.items())}
    return ordered, notes
