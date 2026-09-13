"""Type SETS of expressions: what the editor knows about a value, as far as the data allows.

Two warnings of the platform's own editor turn on the SET of types an expression may hold and on
whether the empty value belongs to it:

- a `??`, a postfix `!` or a `?.` applied to a value whose set has no empty value
  (`code/redundant-undefined-guard`);
- `Х это Тип` where every type of the set of `Х` fits the checked list, so the result is known in
  advance (`code/redundant-type-check`).

`xbsl/typeinfer.py` names ONE type per expression and keeps the empty value as a flag. It types
neither a member of a generic type by the argument the receiver was built with nor a component of
a form, and those two readings are exactly how the places of the first warning on a live project
are typed: the value of a component declared `ПолеВвода<Число>`, the new value of an event
parameter declared `СобытиеПриИзменении<Строка>`. This module keeps the whole set and adds both
readings; moving them into `typeinfer` is left to the change that owns that module.

How the editor computes the set, as probe projects put through its language server show:

- a parameter, a declaration, a cast and a constructor have the type they write, a declaration
  without a type has the type of its initializer;
- `А ?? Б` is the set of `А` without the empty value merged with the set of `Б`, and just `Б`
  when `А` is the empty literal; `Х!` is the set of `Х` without the empty value;
- a ternary merges its two branches, and an unknown part makes the whole merge unknown.

Nothing is guessed. An expression whose set the data cannot state answers None - a name the
method declares without a type, a union the reader cannot parse, a member the catalog types by a
parameter the receiver does not bind, a method whose overloads disagree about the result. A rule
that gets None stays silent.
"""

from __future__ import annotations

import dataclasses
import re
from collections.abc import Iterator
from dataclasses import dataclass, field
from functools import cache, lru_cache
from pathlib import Path

from xbsl import dataset, terms, uischema
from xbsl import parser as P
from xbsl.engine import SourceFile, make_source

#: The canonical name of the empty value inside a written type; it never lands in a set's names.
_UNDEFINED = "Неопределено"

#: A type-name word: an identifier with optional dotted facets (`Товары.Ссылка`).
_NAME_RE = re.compile(
    r"[A-Za-zА-Яа-яЁё_][0-9A-Za-zА-Яа-яЁё_]*(?:\.[A-Za-zА-Яа-яЁё_][0-9A-Za-zА-Яа-яЁё_]*)*"
)
_TYPE_TOKEN_RE = re.compile(r"\s*(::|->|[<>,|?()\[\]{}]|[^\s<>,|?()\[\]{}:]+)")
#: Words of a written type that name no type a rule could compare: the unknown type, the result
#: of a procedure, the result of a method that never returns.
_NO_TYPE_WORDS = frozenset({"неизвестно", "unknown", "ничто", "void", "никогда", "never"})

#: The literal kinds of the lexer and the types they name.
_LITERAL_TYPES = {"STRING": "Строка", "NUMBER": "Число", "TRUE": "Булево", "FALSE": "Булево"}
_BOOLEAN = "Булево"
_NUMBER = "Число"
_STRING = "Строка"
#: The operators whose result is a boolean whatever the operands are.
_BOOLEAN_OPERATORS = frozenset({"и", "или", "and", "or", "не", "not"})
_ARITHMETIC = frozenset({"+", "-", "*", "/", "%"})

#: Both spellings of the root through which a form reaches its own components.
COMPONENT_ROOTS = frozenset({"Компоненты", "Components"})


@dataclass(frozen=True)
class TypeSet:
    """The types a value may hold: canonical written names plus the empty value as a flag.

    A generic keeps its arguments in the name (`Массив<Строка>`), each written in the canonical
    form of `key()`, so two sets compare by their names alone.
    """

    names: frozenset[str]
    undefined: bool = False

    def without_undefined(self) -> "TypeSet":
        return TypeSet(self.names, False)

    def merge(self, other: "TypeSet") -> "TypeSet":
        return TypeSet(self.names | other.names, self.undefined or other.undefined)

    def key(self) -> str:
        """The canonical text of the set, the way an argument of a generic is kept."""
        text = "|".join(sorted(self.names))
        if self.undefined:
            text = f"{text}|?" if text else "?"
        return text

    def display(self) -> str:
        """The set the way the source writes it: `Строка?`, `Строка|Число|?`."""
        names = sorted(self.names)
        if not self.undefined:
            return "|".join(names)
        if len(names) == 1:
            return f"{names[0]}?"
        return "|".join([*names, "?"])


def single(name: str) -> TypeSet:
    return TypeSet(frozenset({name}))


# --- written types ----------------------------------------------------------------------------


@lru_cache(maxsize=1)
def _facet_suffixes() -> dict[str, str]:
    """{English facet suffix: Russian}, built from the facet pairs (`BinaryObject.Reference`).

    A suffix two facets spell differently is dropped rather than guessed.
    """
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
    """One type-name word in its canonical spelling, or None when it names nothing comparable.

    The platform reads a project in either language, so a type is one type in both spellings and
    must compare equal. The pairs come from the term dictionary (types and facets) and, for a
    component of a form, from the ui schema; a project name has one spelling and is kept.
    """
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


class _TypeReader:
    """A recursive reader of a written type: unions, `?` and generic arguments.

    `bindings` puts a set in place of a type parameter (`DataType` of `Edit<Number>`), and
    `unbound` lists the parameters nothing binds - meeting one makes the whole type unknown.
    """

    def __init__(self, tokens: list[str], bindings: dict[str, TypeSet],
                 unbound: frozenset[str]) -> None:
        self.tokens = tokens
        self.pos = 0
        self.bindings = bindings
        self.unbound = unbound

    def peek(self) -> str | None:
        return self.tokens[self.pos] if self.pos < len(self.tokens) else None

    def union(self) -> TypeSet | None:
        got = TypeSet(frozenset())
        while True:
            member = self.member()
            if member is None:
                return None
            got = got.merge(member)
            if self.peek() != "|":
                return got
            self.pos += 1

    def member(self) -> TypeSet | None:
        token = self.peek()
        if token == "?":
            self.pos += 1
            return TypeSet(frozenset(), True)
        if token is None or not _NAME_RE.fullmatch(token):
            return None
        self.pos += 1
        if token in self.unbound:
            return None
        bound = self.bindings.get(token)
        if bound is not None:
            return None if self.peek() == "<" else self._nullable(bound)
        name = canonical_name(token)
        if name is None:
            return None
        if name == _UNDEFINED:
            return self._nullable(TypeSet(frozenset(), True))
        if self.peek() == "<":
            self.pos += 1
            args: list[TypeSet] = []
            while True:
                arg = self.union()
                if arg is None:
                    return None
                args.append(arg)
                if self.peek() == ",":
                    self.pos += 1
                    continue
                if self.peek() != ">":
                    return None
                self.pos += 1
                break
            name = f"{name}<{','.join(arg.key() for arg in args)}>"
        return self._nullable(single(name))

    def _nullable(self, got: TypeSet) -> TypeSet:
        if self.peek() == "?":
            self.pos += 1
            return TypeSet(got.names, True)
        return got


def _type_tokens(text: str) -> list[str] | None:
    tokens: list[str] = []
    pos, text = 0, text.strip()
    while pos < len(text):
        match = _TYPE_TOKEN_RE.match(text, pos)
        if match is None or match.end() == pos:
            return None
        token = match.group(1)
        # A qualified name, a function type and a collection shape are no set a rule compares.
        if token in ("::", "->", "(", ")", "[", "]", "{", "}"):
            return None
        tokens.append(token)
        pos = match.end()
    return tokens


def parse_type(text: str | None, bindings: dict[str, TypeSet] | None = None,
               unbound: frozenset[str] = frozenset()) -> TypeSet | None:
    """The set a written type names, or None when the text is not a plain union of names."""
    if not text:
        return None
    tokens = _type_tokens(text)
    if not tokens:
        return None
    reader = _TypeReader(tokens, bindings or {}, unbound)
    got = reader.union()
    if got is None or reader.pos != len(tokens):
        return None
    return got


def split_generic(name: str) -> tuple[str, list[TypeSet]] | None:
    """`Map<String,Number|?>` -> ("Map", [String, Number?]); None on a bad name."""
    if "<" not in name:
        return name, []
    if not name.endswith(">"):
        return None
    head, inner = name[: name.index("<")], name[name.index("<") + 1: -1]
    parts: list[str] = []
    depth, current = 0, ""
    for char in inner:
        if char == "<":
            depth += 1
        elif char == ">":
            depth -= 1
        elif char == "," and depth == 0:
            parts.append(current)
            current = ""
            continue
        current += char
    parts.append(current)
    args = [parse_type(part) for part in parts]
    if any(arg is None for arg in args):
        return None
    return head, [arg for arg in args if arg is not None]


# --- the platform catalog ---------------------------------------------------------------------


@lru_cache(maxsize=1)
def _catalog() -> dict:
    try:
        return dataset.load_json("stdlib.json")
    except Exception:  # noqa: BLE001 - no data, no catalog types
        return {}


@lru_cache(maxsize=None)
def _member_names(owner: str) -> dict[str, str]:
    """{a spelling of a member: the catalog's name} for the properties and methods of a type.

    The catalog keeps members in Russian while a translated module writes them in English; an
    English spelling two members share is dropped, so an ambiguous word answers nothing.
    """
    from xbsl.rules.unknown_members import _member_english

    members = (_catalog().get("type_members") or {}).get(owner) or {}
    own = [*(members.get("properties") or ()), *(members.get("methods") or ())]
    table: dict[str, str] = {name: name for name in own}
    english: dict[str, set[str]] = {}
    for name in own:
        for spelling in (terms.member_english_of(owner, name), _member_english(owner, name)):
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


def _catalog_knows(written: str, bound: frozenset[str]) -> bool:
    """Whether every name the catalog wrote is a type it knows or a parameter being bound."""
    catalog = _catalog()
    types = catalog.get("type_members") or {}
    for word in _NAME_RE.findall(written):
        if word in bound or word in _NO_TYPE_WORDS:
            continue
        name = canonical_name(word)
        if name is None:
            return False
        if name != _UNDEFINED and name not in types:
            return False
    return True


def member_result(receiver: str, member: str, argc: int | None) -> TypeSet | None:
    """The set a member of a catalog type yields: a property when `argc` is None, else a call.

    A generic receiver binds the type parameters of its type (`Edit<Number>` binds
    `DataType`), a raw one binds none, and a member typed by an unbound parameter answers None.
    A call is typed by the overloads whose arity admits the arguments, and only when they agree
    on the result; a generic method is left alone - its own argument decides the result.
    """
    split = split_generic(receiver)
    if split is None:
        return None
    head, args = split
    catalog = _catalog()
    members = (catalog.get("type_members") or {}).get(head)
    if not members:
        return None
    name = _member_names(head).get(member)
    if name is None:
        return None
    params = tuple((catalog.get("type_params") or {}).get(head) or ())
    if args and len(args) != len(params):
        return None
    bindings = dict(zip(params, args))
    own_params = frozenset(((catalog.get("member_type_params") or {}).get(head) or {}).get(name) or ())
    unbound = (frozenset(params) - set(bindings)) | own_params
    property_of: tuple[str, str] | None = None
    if name in (members.get("properties") or ()):
        if argc is not None:
            return None
        written = ((catalog.get("member_types") or {}).get(head) or {}).get(name)
        property_of = (head, name)
    elif name in (members.get("methods") or ()):
        if argc is None:
            return None
        results: set[str | None] = set()
        for signature in ((catalog.get("member_signatures") or {}).get(head) or {}).get(name) or ():
            shape = _signature(signature)
            if shape is None:
                return None
            fewest, most, result, generic = shape
            if not fewest <= argc <= most:
                continue
            if generic:
                return None
            results.add(result)
        if len(results) != 1:
            return None
        written = results.pop()
    else:
        return None
    if not written or not _catalog_knows(written, frozenset(bindings) | unbound):
        return None
    got = parse_type(written, bindings, unbound)
    plain = got is not None and not got.undefined
    if plain and property_of is not None and not _documented_alike(*property_of):
        return None
    return got


_CODE_RE = re.compile(r"<pre><code>(.*?)</code></pre>", re.S)
_TAG_RE = re.compile(r"<[^>]+>")


@lru_cache(maxsize=None)
def _documented_types(owner: str, member: str) -> tuple[str, ...] | None:
    """The types the documentation page prints for a property, its current forms first.

    None when the documentation is not installed or does not document the member.
    """
    import html

    from xbsl import docs

    try:
        found = docs.member_doc(f"{owner}.{member}") if docs.available() else {}
    except Exception:  # noqa: BLE001 - no documentation, nothing to compare with
        return None
    block = (found or {}).get("block")
    if not block:
        return None
    current: list[str] = []
    replaced: list[str] = []
    for part in re.split(r"(?=<h3)", block):
        target = replaced if "<del>" in part[: part.find("</h3>") + 1] else current
        for code in _CODE_RE.findall(part):
            text = html.unescape(_TAG_RE.sub("", code)).strip()
            head, colon, written = text.partition(":")
            if colon and head.strip() == member:
                target.append(written.strip())
    return tuple(current or replaced) or None


#: Properties the documentation itself prints as plain while the editor's language server does not
#: treat them as never empty. Every property and argument-less method the catalog calls plain was
#: put through the editor behind `??` (about 8,700 members): the few disagreements were the folded
#: versions `_documented_alike` catches, and this one, which no reading of the data explains.
#: Pairs are (the declaring type, the member) in the catalog's spelling.
_DISPUTED_PROPERTIES = frozenset({("ОбсуждениеВзаимодействия", "ИдВнешнегоОбсуждения")})


def _documented_alike(owner: str, member: str) -> bool:
    """Whether the documentation agrees with the catalog about a property the catalog calls plain.

    The catalog keeps one type per member. A page that prints a property for several platform
    versions (`TableReflection?` for the current one, `TableReflection` for an old one) was
    folded into the bare head of the type, and the empty value of the current form got lost
    with it - a sweep of the catalog through the editor's language server found exactly such
    properties among its disagreements. So a property is trusted as plain only when every current
    form the page prints is the same text and none of them admits the empty value.
    """
    bases = (_catalog().get("bases") or {}).get(owner) or ()
    if any((holder, member) in _DISPUTED_PROPERTIES for holder in (owner, *bases)):
        return False
    documented = _documented_types(owner, member)
    if documented is None:
        return True
    if len(set(documented)) > 1:
        return False
    return not any("?" in text or _UNDEFINED in text for text in documented)


def element_of(collection: TypeSet | None) -> TypeSet | None:
    """The element of a loop over a one-argument collection: `Array<String>` -> `String`.

    Answered for a type of the catalog whose only parameter is the element type and which is
    iterable (`Iterable` among its bases). A map hands out `KeyAndValue<...>`, and nothing in
    the data pairs the two - so a map, like anything else, answers None.
    """
    if collection is None or collection.undefined or len(collection.names) != 1:
        return None
    split = split_generic(next(iter(collection.names)))
    if split is None or len(split[1]) != 1:
        return None
    head, (element,) = split
    catalog = _catalog()
    if list((catalog.get("type_params") or {}).get(head) or ()) != ["ТипЭлемента"]:
        return None
    if head != "Обходимое" and "Обходимое" not in ((catalog.get("bases") or {}).get(head) or ()):
        return None
    return element


def holds(check: str, name: str) -> bool:
    """Whether a value of type `name` fits the checked type `check`.

    The same type does, and so does a type whose catalog bases name the check - `String` fits
    `Object`. A generic base is left out: which argument it takes from the derived type is not
    in the data.
    """
    if check == name:
        return True
    if "<" in check:
        return False
    split = split_generic(name)
    if split is None:
        return False
    catalog = _catalog()
    if (catalog.get("type_params") or {}).get(check):
        return False
    return check in ((catalog.get("bases") or {}).get(split[0]) or ())


def _reset() -> None:
    _catalog.cache_clear()
    _member_names.cache_clear()
    _documented_types.cache_clear()
    canonical_name.cache_clear()
    _facet_suffixes.cache_clear()


dataset.register_reset(_reset)


# --- what a module knows without its method bodies --------------------------------------------


@dataclass
class ModuleFacts:
    """The names a module's methods reach without declaring them, typed where the source says so.

    `components` is None for a module without a markup pair: then `Компоненты.X` means nothing
    here, which is not the same as a markup that lacks the name.
    """

    structures: dict[str, dict[str, TypeSet | None]] = field(default_factory=dict)
    returns: dict[str, TypeSet | None] = field(default_factory=dict)
    variables: dict[str, TypeSet | None] = field(default_factory=dict)
    own: dict[str, TypeSet | None] = field(default_factory=dict)
    components: dict[str, TypeSet | None] | None = None


def _declared(tref: P.TypeRef | None) -> TypeSet | None:
    return parse_type(getattr(tref, "text", None))


def module_facts(source: SourceFile) -> tuple[P.Module, ModuleFacts] | None:
    """The parsed module and its facts, or None for a module that does not parse. Cached."""
    key = "typesets_module"
    if key in source.cache:
        return source.cache[key]
    module, errors = P.parse(source)
    got = None if errors else (module, _collect_facts(source, module))
    source.cache[key] = got
    return got


def _collect_facts(source: SourceFile, module: P.Module) -> ModuleFacts:
    facts = ModuleFacts()
    seen_methods: set[str] = set()
    for member in module.members:
        if isinstance(member, P.Structure):
            fields: dict[str, TypeSet | None] = {}
            for sub in member.members:
                if isinstance(sub, P.ObjectField):
                    fields[sub.name] = _declared(sub.type)
            facts.structures[member.name] = fields
        elif isinstance(member, P.Method):
            # An overloaded name has no single result.
            if member.name in seen_methods:
                facts.returns[member.name] = None
            else:
                facts.returns[member.name] = _declared(member.return_type)
            seen_methods.add(member.name)
        elif isinstance(member, P.ObjectField):
            declared = _declared(member.type)
            if declared is None and member.type is None and member.init is not None:
                declared = _literal_set(member.init)
            facts.variables[member.name] = declared
    _pair_facts(source, facts)
    return facts


def _literal_set(node: object) -> TypeSet | None:
    if isinstance(node, P.Literal):
        name = _LITERAL_TYPES.get(str(node.kind))
        return single(name) if name else None
    return None


def _pair_facts(source: SourceFile, facts: ModuleFacts) -> None:
    """The typed properties and the components of the paired component markup, read from disk."""
    from xbsl.rules.yaml_schema import _HAVE_YAML, _parsed, object_kind, value_of

    if not _HAVE_YAML:
        return
    try:
        pair = Path(source.path).with_suffix(".yaml")
        if not pair.is_file():
            return
        paired = make_source(pair, pair.read_bytes())
    except (OSError, ValueError):
        return
    data, error = _parsed(paired)
    if error is not None or not isinstance(data, dict):
        return
    kind = object_kind(data)
    if kind != "КомпонентИнтерфейса":
        return
    name_keys = frozenset(terms.key_forms("Имя"))
    type_keys = frozenset(terms.key_forms("Тип"))
    properties = value_of(data, "Свойства", kind)
    for item in properties if isinstance(properties, list) else ():
        if isinstance(item, dict):
            name = _first(item, name_keys)
            if isinstance(name, str) and name:
                written = _first(item, type_keys)
                facts.own[name] = parse_type(written) if isinstance(written, str) else None
    # Every named node of the markup is reachable through the root, at any depth (the evidence
    # is in `form_components.py`); a name met twice with different types answers nothing.
    components: dict[str, TypeSet | None] = {}
    for value in data.values():
        if value is properties:
            continue
        for name, written in _markup_nodes(value, name_keys, type_keys):
            got = None
            if isinstance(written, str) and not written.startswith("="):
                got = parse_type(written)
                if got is not None and (got.undefined or not _bound_by_default(got)):
                    got = None
            if name in components and components[name] != got:
                got = None
            components[name] = got
    facts.components = components


def _bound_by_default(component: TypeSet) -> bool:
    """Whether every argument of a component type is nullable or a type of the catalog.

    The type parameter of a value component must have a default value or hold the empty value
    (the documentation of the input field says so), and the editor refuses a markup that breaks
    it - then it warns about nothing in that module. A project type without `?` is the shape of
    that refusal, so such a component is left untyped rather than read as never empty.
    """
    types = _catalog().get("type_members") or {}
    for name in component.names:
        split = split_generic(name)
        if split is None:
            return False
        for arg in split[1]:
            if arg.undefined:
                continue
            if any((split_generic(part) or ("", []))[0] not in types for part in arg.names):
                return False
    return True


def _first(item: dict, keys: frozenset[str]) -> object:
    for key in keys:
        if key in item:
            return item[key]
    return None


def _markup_nodes(node: object, name_keys: frozenset[str],
                  type_keys: frozenset[str]) -> Iterator[tuple[str, object]]:
    """(name, written type or None) of every named node of a markup tree."""
    if isinstance(node, dict):
        name = _first(node, name_keys)
        if isinstance(name, str) and name:
            yield name, _first(node, type_keys)
        for value in node.values():
            yield from _markup_nodes(value, name_keys, type_keys)
    elif isinstance(node, list):
        for item in node:
            yield from _markup_nodes(item, name_keys, type_keys)


# --- the names of one method ------------------------------------------------------------------


class _Missing:
    """The method does not declare the name at all."""


class _Unknown:
    """The method declares the name, but not so that the place can see a single declaration."""


MISSING = _Missing()
UNKNOWN = _Unknown()


@dataclass(frozen=True)
class QueryRow:
    """A loop variable over the result of a query literal: [start, end) of the literal."""

    start: int
    end: int


@dataclass(frozen=True)
class Declaration:
    block: tuple[int, int]
    pos: int
    types: TypeSet | None
    row: QueryRow | None = None
    result: QueryRow | None = None


@cache
def _field_names(cls: type) -> tuple[str, ...]:
    """Field names of a node class; declared ones, as the compiled parser has no `__dict__`."""
    return tuple(f.name for f in dataclasses.fields(cls))


def walk_nodes(node: object) -> list[P.Node]:
    """Every node of a subtree, parents before children, in source order.

    An explicit stack rather than nested generators: a method body is walked several times per
    judged method, and the generator chain was the largest cost of both rules on a live project.
    """
    out: list[P.Node] = []
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


@lru_cache(maxsize=1)
def _execute_spellings() -> frozenset[str]:
    """Both spellings of the method that runs a query literal."""
    english = terms.member_english_of("ТипизированныйЗапрос", "Выполнить") or terms.common_english("Выполнить")
    return frozenset({"Выполнить", *([english] if english else [])})


dataset.register_reset(_execute_spellings.cache_clear)


def query_literal_run(node: object) -> QueryRow | None:
    """`Запрос{...}.Выполнить()` -> the span of the literal, else None."""
    if not isinstance(node, P.Call) or node.args or node.type_args:
        return None
    callee = node.callee
    if not isinstance(callee, P.Member) or callee.safe or callee.name not in _execute_spellings():
        return None
    literal = callee.obj
    if isinstance(literal, P.Literal) and literal.kind == "QUERY":
        return QueryRow(literal.start, literal.end)
    return None


class MethodScope:
    """The declarations of one method, each visible from where it stands to the end of its block.

    The platform scopes a name to its block, blocks nest and the innermost declaration wins
    (docs, "Область видимости имен"). Every name the method declares ANYWHERE is kept off the
    module's own names: a place that sees no declaration of such a name answers unknown rather
    than falling through to a property of the same name.
    """

    def __init__(self, method: P.Method, facts: ModuleFacts, nodes: list[P.Node] | None = None) -> None:
        self.facts = facts
        self.entries: dict[str, list[Declaration]] = {}
        nodes = walk_nodes(method.body) if nodes is None else nodes
        self.names = _method_names(method, nodes)
        self.evaluator = Evaluator(facts, self)
        span = (int(method.start), int(method.end))
        for param in method.params:
            self._add(param.name, Declaration(span, span[0], _declared(param.type)))
        self._walk(method.body, _block(method.body) or span)
        # A variable the method assigns again no longer holds for sure the query result it was
        # declared with; its type stays, since an assignment cannot change a declared type.
        assigned = {
            node.target.name for node in nodes
            if isinstance(node, P.Assign) and isinstance(node.target, P.Name)
        }
        for name in assigned & set(self.entries):
            self.entries[name] = [dataclasses.replace(entry, result=None) for entry in self.entries[name]]

    def _add(self, name: str, entry: Declaration) -> None:
        if name:
            self.entries.setdefault(name, []).append(entry)

    def lookup(self, name: str, at: int) -> Declaration | _Missing | _Unknown:
        entries = self.entries.get(name)
        if not entries:
            return UNKNOWN if name in self.names else MISSING
        best: Declaration | None = None
        for entry in entries:
            if entry.block[0] <= at <= entry.block[1] and entry.pos <= at:
                if best is None or (entry.block[0], entry.pos) >= (best.block[0], best.pos):
                    best = entry
        return best if best is not None else UNKNOWN

    def _walk(self, node: object, block: tuple[int, int]) -> None:
        if isinstance(node, (list, tuple)):
            inner = _block(node) or block
            for item in node:
                self._walk(item, inner)
            return
        if not isinstance(node, P.Node):
            return
        if isinstance(node, P.VarDecl):
            self._walk(node.init, block)
            types = _declared(node.type)
            result = None
            if node.type is None and node.init is not None:
                types = self.evaluator.types(node.init)
                result = query_literal_run(node.init)
            self._add(node.name, Declaration(block, int(node.end), types, result=result))
            return
        if isinstance(node, P.ForEach):
            self._walk(node.source, block)
            loop = (int(node.start), int(node.end))
            element = element_of(self.evaluator.types(node.source))
            self._add(node.var, Declaration(loop, int(node.source.end), element,
                                            row=self._row_of(node.source)))
            self._walk(node.body, loop)
            return
        if isinstance(node, P.ForTo):
            loop = (int(node.start), int(node.end))
            for part in (node.start_expr, node.to, node.step):
                self._walk(part, block)
            after = node.step or node.to
            self._add(node.var, Declaration(loop, int(getattr(after, "end", node.start)),
                                            single("Число")))
            self._walk(node.body, loop)
            return
        if isinstance(node, P.Try):
            self._walk(node.body, block)
            for var, tref, body in node.catches:
                span = _block(body)
                if span is not None:
                    written = getattr(tref, "text", None)
                    self._add(var, Declaration(span, span[0], parse_type(written)))
                    self._walk(body, span)
            self._walk(node.finally_body, block)
            return
        if isinstance(node, P.Lambda):
            span = (int(node.start), int(node.end))
            for param in node.params:
                self._add(param.name, Declaration(span, span[0], _declared(param.type)))
            self._walk(node.body_expr, span)
            self._walk(node.body_stmts, span)
            return
        for name in _field_names(type(node)):
            value = getattr(node, name, None)
            if isinstance(value, (P.Node, list, tuple)):
                self._walk(value, block)

    def _row_of(self, source: P.Expr) -> QueryRow | None:
        direct = query_literal_run(source)
        if direct is not None:
            return direct
        if isinstance(source, P.Name):
            entry = self.lookup(source.name, int(source.start))
            if isinstance(entry, Declaration):
                return entry.result
        return None


def _block(items: object) -> tuple[int, int] | None:
    """The span of a list of statements, or None when the list holds no statement."""
    statements = [item for item in (items or ()) if isinstance(item, P.Stmt)]
    if not statements:
        return None
    return int(statements[0].start), int(statements[-1].end)


def _method_names(method: P.Method, nodes: list[P.Node]) -> frozenset[str]:
    names = {param.name for param in method.params}
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


# --- the evaluator ----------------------------------------------------------------------------


class Evaluator:
    """The set of an expression at its place in a method, or None when the data cannot state it."""

    def __init__(self, facts: ModuleFacts, scope: MethodScope) -> None:
        self.facts = facts
        self.scope = scope

    def types(self, node: object) -> TypeSet | None:
        handler = getattr(self, "_" + type(node).__name__, None)
        return handler(node) if handler is not None else None

    def _Literal(self, node: P.Literal) -> TypeSet | None:
        if node.kind == "UNDEFINED":
            return TypeSet(frozenset(), True)
        name = _LITERAL_TYPES.get(str(node.kind))
        return single(name) if name else None

    def _Name(self, node: P.Name) -> TypeSet | None:
        entry = self.scope.lookup(node.name, int(node.start))
        if isinstance(entry, Declaration):
            return entry.types
        if entry is UNKNOWN:
            return None
        if node.name in self.facts.variables:
            return self.facts.variables[node.name]
        return self.facts.own.get(node.name)

    def root_is_components(self, node: object) -> bool:
        """Whether a bare name is the form's own component root, not something declared so."""
        return (
            isinstance(node, P.Name) and node.name in COMPONENT_ROOTS
            and self.facts.components is not None
            and self.scope.lookup(node.name, int(node.start)) is MISSING
            and node.name not in self.facts.variables and node.name not in self.facts.own
        )

    def _Member(self, node: P.Member) -> TypeSet | None:
        if self.root_is_components(node.obj):
            got = (self.facts.components or {}).get(node.name)
        elif isinstance(node.obj, P.This):
            # `этот` of a component module is the component: its typed properties are the own ones.
            got = self.facts.own.get(node.name) if self.facts.components is not None else None
        else:
            return self._reached(self.types(node.obj), node.name, None, node.safe)
        return got

    def _reached(self, receiver: TypeSet | None, member: str, argc: int | None,
                 safe: bool) -> TypeSet | None:
        """A member read through `.` or `?.`: the safe access adds the empty value only when the
        receiver may hold it - over a value that never does, `Х?.Длина()` is a plain number."""
        if receiver is None:
            return None
        if not safe:
            return self.member_of(receiver, member, argc)
        got = self.member_of(receiver.without_undefined(), member, argc)
        if got is None or not receiver.undefined:
            return got
        return TypeSet(got.names, True)

    def member_of(self, receiver: TypeSet | None, member: str, argc: int | None) -> TypeSet | None:
        if receiver is None or len(receiver.names) != 1:
            return None
        (name,) = receiver.names
        if name in self.facts.structures:
            return None if argc is not None else self.facts.structures[name].get(member)
        return member_result(name, member, argc)

    def _Call(self, node: P.Call) -> TypeSet | None:
        if node.type_args or any(arg.name for arg in node.args):
            return None
        callee = node.callee
        if isinstance(callee, P.Member):
            if self.root_is_components(callee.obj) or isinstance(callee.obj, P.This):
                return None
            return self._reached(self.types(callee.obj), callee.name, len(node.args), callee.safe)
        if isinstance(callee, P.Name):
            if self.scope.lookup(callee.name, int(callee.start)) is not MISSING:
                return None
            if callee.name in self.facts.variables or callee.name in self.facts.own:
                return None
            return self.facts.returns.get(callee.name)
        return None

    def _New(self, node: P.New) -> TypeSet | None:
        got = _declared(node.type)
        return got if got is not None and got.names and not got.undefined else None

    def _AsType(self, node: P.AsType) -> TypeSet | None:
        return _declared(node.type)

    def _NonNull(self, node: P.NonNull) -> TypeSet | None:
        inner = self.types(node.operand)
        if inner is None or not inner.names:
            return None
        return inner.without_undefined()

    def _Coalesce(self, node: P.Coalesce) -> TypeSet | None:
        left = self.types(node.left)
        right = self.types(node.right) if node.right is not None else None
        if left is None or right is None:
            return None
        if not left.names:
            return right
        return left.without_undefined().merge(right)

    def _Ternary(self, node: P.Ternary) -> TypeSet | None:
        then = self.types(node.then)
        otherwise = self.types(node.otherwise) if node.otherwise is not None else None
        if then is None or otherwise is None:
            return None
        return then.merge(otherwise)

    def _Compare(self, node: P.Compare) -> TypeSet | None:
        return single(_BOOLEAN) if node.rest else self.types(node.first)

    def _Binary(self, node: P.Binary) -> TypeSet | None:
        if node.op.lower() in _BOOLEAN_OPERATORS:
            return single(_BOOLEAN)
        if node.op not in _ARITHMETIC or node.right is None:
            return None
        left, right = self.types(node.left), self.types(node.right)
        if left is None or right is None or left.undefined or right.undefined:
            return None
        # Only the two shapes whose result does not depend on the table of the operations:
        # numbers give a number, and `+` of two strings is a string.
        if left.names == right.names == {_NUMBER}:
            return single(_NUMBER)
        if node.op == "+" and left.names == right.names == {_STRING}:
            return single(_STRING)
        return None

    def _Unary(self, node: P.Unary) -> TypeSet | None:
        return single(_BOOLEAN) if node.op.lower() in _BOOLEAN_OPERATORS else None

    def _IsType(self, node: P.IsType) -> TypeSet | None:
        return single(_BOOLEAN)


def module_methods(module: P.Module) -> list[P.Method]:
    """The methods of the module itself: a structure's methods reach its fields by a bare name,
    which the facts of the module do not describe, so they are not judged."""
    return [member for member in module.members if isinstance(member, P.Method)]
