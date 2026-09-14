"""Tier D: code/unused-import - an import the module never uses, judged the way the compiler does.

A module declares `импорт <Пространство>`, and nothing in it resolves through that namespace. The
platform's editor warns about such a line, and it is the compiler that decides, not a text search. Its binder keeps a set of USED namespaces while it binds
the module, and warns about every import whose namespace never made it into the set. A namespace
enters the set whenever the binder asks for a type of that namespace - to resolve a name, to look
a member up, to check an argument - whether the type was written or merely inferred. So what counts
is where the types of the module come from, and the rule follows those sources rather than the
words of the module.

The earlier reading took every identifier of the module and kept an import alive when any of them
spelled an element of the namespace. It never reported a single one of the imports the editor
reports on a real project with packages: the word that kept them alive was the import line itself
(`импорт Б` next to `импорт Б::П`, with an element named like its subsystem), a member after a dot
(`Order.Goods`), a field declaration, a property of the paired yaml, a named argument, a column of
a query - none of which the compiler resolves as the element.

What the binder looks up, read off the compiler and checked against the editor's answer on several
projects (the name of each mechanism is what the tests and the notes call it):

- WRITTEN TYPES - every type position of the module: parameters, results, variables, fields,
  `новый`, `как`, `это`, `поймать`, type literals and generic arguments. A short name is looked up
  in every namespace that has a type of that name, and each of them is marked, not just the one
  that wins: the own subsystem shadowing the name does not stop the import from being used.
- BARE NAMES - a name that is neither a local of the method nor a name the module or the paired
  yaml declares is searched among the singletons (common modules, managers, enumerations,
  dictionaries).
- CHAIN ROOTS - `Root.member` with `Root` a plain name: before binding the root as a property
  the compiler tries the chain as a static access, so the root is looked up as a type even when it
  is a property of the paired yaml. Only a local (a variable, a parameter, a loop or catch variable,
  a lambda parameter) is exempt, and so is a chain that opens with `?.`.
- QUALIFIED NAMES - `Пространство::Элемент` marks the namespace it names; such a reference needs no
  import, yet it uses one that is there.
- QUERY TABLES - a table after FROM/JOIN of a query block.
- ENUMERATION VALUES in the `когда` branches of a `выбор`: the binder resolves them against the
  enumeration of the subject.
- RESOURCES - `Ресурс{ключ}` with a bare key reaches a file of an imported namespace when neither
  the package of the module nor the root of its subsystem has one: then that namespace is used. A
  qualified key (`Ресурс{Б::ключ}`) marks nothing.
- DECLARED TYPES - the types a value brings along without being written in the module: the type
  of a property the code names (a property of the paired yaml or of a base component of the
  project, a component under `Components.` included), the base type of the element, the result
  of a method or the type of a field of another element reached through a static chain
  (`Module.Method()`), what a member the platform gives a manager returns (a derived type of the
  element), the fields of the structures those types are, the attributes of an element whose
  derived type (`Element.Reference`) they are, and a query column that passes a field of its
  table on as it is. A declared type is followed only through the members the module names after
  a dot, and every root it holds is marked. That over-reads on purpose: a declared type the code
  merely passes along or compares is taken as touched, which keeps an import at worst.

The paired yaml is NOT a use in itself: its `Импорт:` section covers its own type positions, and
an import of the element does not reach its modules (docs, "Модульная разработка"). The yaml has
no warning of its own about an unused import either - the editor keeps that to modules.

A namespace is a placement key - a subsystem root (`импорт Б`) or a package (`импорт Б::П`) - and
the marks are exact: a type of a package marks the package, not its subsystem. So `импорт Б` next
to `импорт Б::П` is unused when the module reaches only the package, and the message names the
packages that carry the names instead. A namespace the project does not own (a library, another
project, a typo) is not judged. An import of the module's own namespace is judged like any other:
the editor reports it as well, and the type of the module itself counts as a use of it once the
module declares a local or reads a name that is not one (`этот` included) - that is when the binder
asks for that type; a module that does neither, a component module too, leaves it unused.

What keeps the rule quiet where it cannot follow the compiler: a module that does not parse, a
paired yaml that does not parse, an element the module reaches whose yaml or module is unreadable
(its declarations are unknown), and a bare resource key in a run whose resource folders are not on
disk. The removal of the line is mechanical, so the finding carries a fix when the line holds
nothing but the import.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from dataclasses import fields
from functools import lru_cache
from pathlib import Path

from xbsl import dataset, i18n, parser as P, terms
from xbsl.dataset import DatasetError
from xbsl.diagnostics import Diagnostic, Severity, TextEdit
from xbsl.engine import RESOURCE_DIRS, SourceFile, is_query_file, rule
from xbsl.layout import Layout, subsystem_of_key
from xbsl.lexer import Token, tokens
from xbsl.rules._syntax import (
    WORD_KINDS,
    _query_vocabulary,
    code_tokens,
    query_alias_intro,
    query_block_tokens,
    query_from_items,
    query_ranges,
    query_table_intro,
    query_tables,
    query_words,
)
from xbsl.rules.environment import _pair_stem
from xbsl.rules.resources import _resource_refs, _resource_words
from xbsl.rules.undefined_names import _interpolations, _section_names
from xbsl.rules.yaml_imports import _interpolation_bodies, _layout_fact, _layout_from, _module_imports
from xbsl.rules.yaml_schema import _HAVE_YAML, _parsed, object_kind, unreadable_object, value_of
from xbsl.rules.yaml_types import _key_spellings

MESSAGES = {
    "code/unused-import.title": {
        "ru": "Неиспользуемый импорт подсистемы",
        "en": "Unused subsystem import",
    },
    "code/unused-import.unused": {
        "ru": "Импорт пространства имён '{sub}' не используется: код модуля не обращается ни к "
              "одному типу этого пространства – ни по имени, ни через значения. Ссылки ПАРНОГО "
              "yaml импорт модуля не покрывает – у yaml своя секция Импорт. Строку можно снять.",
        "en": "The import of namespace '{sub}' is unused: the module code reaches no type of it - "
              "neither by name nor through a value. References of the PAIRED yaml are not "
              "covered by a module import - the yaml has an {n[Импорт]} section of its own. The "
              "line can go.",
    },
    "code/unused-import.packages": {
        "ru": "Импорт подсистемы '{sub}' не используется: код модуля обращается только к "
              "элементам её пакетов ({packages}), а они через 'импорт {sub}' не приходят – "
              "у пакета своя строка импорта. Строку можно снять.",
        "en": "The import of subsystem '{sub}' is unused: the module code reaches only "
              "elements of its packages ({packages}), and those do not come through "
              "`{n[импорт]} {sub}` - a package has an import line of its own. The line can go.",
    },
}
i18n.register(MESSAGES)

_RULE = "code/unused-import"

#: A name, the qualifiers of a qualified name, a dotted chain of names.
_NAME = r"[^\W\d]\w*"
_QUALIFIED_RE = re.compile(rf"((?:{_NAME}::)+)({_NAME})")
_QUALIFIED_CHAIN_RE = re.compile(rf"(?:{_NAME}::)+{_NAME}(?:\.{_NAME})*")
_CHAIN_RE = re.compile(rf"(?<![\w.:])({_NAME}(?:\.{_NAME})*)")
#: A word of a full interpolation `%{...}`: whether a dot stands before it, and the word.
_INTERPOLATION_WORD_RE = re.compile(rf"(?<![\w:$%&])(\.?)({_NAME})(?!\s*::)")

#: The prefix of a resource uploaded into the application base: not a file of a namespace.
_UPLOADED_PREFIX = "inbase/"


#: The kind of an enumeration, as object_kind spells it.
_ENUM_KIND = "Перечисление"


@lru_cache(maxsize=1)
def _components_words() -> frozenset[str]:
    """Both spellings of `Components`, the context root of the named components of a form."""
    return frozenset({"Компоненты", terms.common_english("Компоненты")} - {None})


dataset.register_reset(_components_words.cache_clear)


def _type_chains(text: str | None) -> tuple[set[str], set[str]]:
    """(the plain dotted chains, the qualified chains) a type expression spells.

    `Array<Goods.Reference>|Number?` gives `Array`, `Goods.Reference` and `Number`;
    `Stock::Batches::Goods.Reference` gives the qualified chain itself and no plain one.
    """
    if not text:
        return set(), set()
    qualified = {m.group(0) for m in _QUALIFIED_CHAIN_RE.finditer(text)}
    plain = _QUALIFIED_CHAIN_RE.sub(" ", text)
    return {m.group(1) for m in _CHAIN_RE.finditer(plain)}, qualified


def _qualified_name(chain: str) -> tuple[str, str, str]:
    """(the qualifiers, the element, the tail) of a qualified chain:
    `Stock::Batches::Goods.Reference` gives `Stock::Batches`, `Goods` and `Reference`."""
    head, _, tail = chain.partition(".")
    qualifiers, _, element = head.rpartition("::")
    return qualifiers, element, tail


# --- the map phase: what one module asks the binder for -------------------------------------


class _Walk:
    """One pass over the tree of a module, collecting what the binder would look up."""

    def __init__(self, text: str) -> None:
        self.text = text
        self.types: set[str] = set()          # dotted chains of written types
        self.bare: set[str] = set()           # names searched among the singletons
        self.roots: set[str] = set()          # roots of static chains
        self.qualified: set[str] = set()      # Namespace::Element
        self.when: set[str] = set()           # bare names of the `когда` branches
        self.named: set[str] = set()          # every name the code spells, bare or after a dot
        self.dotted: set[str] = set()         # names after a dot
        self.chains: set[tuple[str, str]] = set()  # (element, member) of a static chain
        self.methods: dict[str, list[str]] = {}    # declarations: method -> result type
        self.fields: dict[str, list[str]] = {}     # declarations: field -> type
        self.structures: dict[str, dict[str, list[str]]] = {}  # structure -> field -> type
        self.module_names: set[str] = set()
        self.locals = False                   # whether a method declares a local
        self.enum_values: set[str] = set()    # the values of the enumerations the module declares
        self.this = False                     # whether the code reads `этот`

    # --- types

    def type_text(self, text: str | None) -> None:
        chains, qualified = _type_chains(text)
        self.types |= chains
        self.qualified |= qualified

    def typeref(self, node: object) -> None:
        if isinstance(node, P.TypeRef):
            self.type_text(node.text)

    # --- expressions

    def string(self, raw: str, scope: set[str]) -> None:
        """The interpolations of a string literal: a short one names a value, a full one holds
        an expression. Its words are read without a tree, so each counts in every role it could
        play - a word too many keeps an import, it never reports one."""
        for _offset, _sign, name in _interpolations(raw):
            self.named.add(name)
            if name not in scope:
                self.bare.add(name)
        for _offset, body in _interpolation_bodies(raw, blank_strings=False):
            for match in _QUALIFIED_RE.finditer(body):
                self.qualified.add(match.group(1) + match.group(2))
            for match in _INTERPOLATION_WORD_RE.finditer(body):
                dot, name = match.groups()
                self.named.add(name)
                if dot:
                    self.dotted.add(name)
                else:
                    self.bare.add(name)
                    self.roots.add(name)

    def member(self, node: P.Member, scope: set[str]) -> None:
        """`Корень.член`: the member is a name of whatever the root is, and a plain root that is
        not a local is tried as a static access first - the first step decides, a `?.` there
        makes it a plain value."""
        self.dotted.add(node.name)
        self.named.add(node.name)
        root = node.obj.name if isinstance(node.obj, P.Name) else ""
        if root and not node.safe:
            if "::" in root:
                self.chains.add((root.rpartition("::")[2], node.name))
            elif root not in _components_words() and (
                    root not in scope or root in self.module_names):
                self.roots.add(root)
                self.chains.add((root, node.name))
        self.expr(node.obj, scope)

    def expr(self, node: object, scope: set[str], in_when: bool = False) -> None:
        if node is None:
            return
        if isinstance(node, P.Literal):
            if node.kind == "STRING":
                self.string(node.text, scope)
            elif node.kind == "TYPE":
                raw = self.text[node.start:node.end]
                self.type_text(raw[raw.find("<") + 1:raw.rfind(">")] if "<" in raw else "")
            return
        if isinstance(node, P.MethodRef):
            head = self.text[node.start:node.end].lstrip("&").split("(")[0]
            if "." in head:
                self.type_text(head.rpartition(".")[0])
            elif head:
                self.bare.add(head)
            return
        if isinstance(node, P.Name):
            if "::" in node.name:
                self.qualified.add(node.name)
            elif node.name:
                self.named.add(node.name)
                if node.name not in scope:
                    self.bare.add(node.name)
                    if in_when:
                        self.when.add(node.name)
            return
        if isinstance(node, P.Member):
            self.member(node, scope)
            return
        if isinstance(node, P.This):
            self.this = True
            return
        if isinstance(node, P.Lambda):
            for param in node.params:
                self.typeref(param.type)
            inner = scope | {param.name for param in node.params}
            if isinstance(node.body_expr, P.Assign):
                self.body([node.body_expr], inner)
            else:
                self.expr(node.body_expr, inner)
            if node.body_stmts is not None:
                self.body(node.body_stmts, set(inner))
            return
        if isinstance(node, (P.New, P.IsType, P.AsType)):
            self.typeref(node.type)
        if isinstance(node, (P.Call, P.ArrayLit, P.MapLit)):
            for arg in node.type_args:
                self.typeref(arg)
        for item in fields(node):
            if item.name not in ("start", "end", "type", "type_args"):
                self._child(getattr(node, item.name), scope)

    def _child(self, value: object, scope: set[str]) -> None:
        if isinstance(value, P.Expr):
            self.expr(value, scope)
        elif isinstance(value, P.CallArg):
            if value.name:
                self.named.add(value.name)
            self.expr(value.value, scope)
        elif isinstance(value, (list, tuple)):
            for item in value:
                self._child(item, scope)

    # --- statements

    def body(self, statements: list, scope: set[str]) -> None:
        """A block: a declaration introduces its name after its own initializer, a nested
        block sees a copy of the scope."""
        for st in statements:
            if isinstance(st, P.VarDecl):
                self.typeref(st.type)
                self.expr(st.init, scope)
                scope.add(st.name)
                self.locals = True
            elif isinstance(st, P.Assign):
                self.expr(st.target, scope)
                self.expr(st.value, scope)
            elif isinstance(st, (P.ExprStmt, P.UseStmt)):
                self.expr(st.expr, scope)
            elif isinstance(st, P.If):
                for condition, branch in st.branches:
                    self.expr(condition, scope)
                    self.body(branch, set(scope))
                if st.else_body is not None:
                    self.body(st.else_body, set(scope))
            elif isinstance(st, P.Case):
                self.expr(st.subject, scope)
                for when in st.whens:
                    for condition in when.conditions:
                        self.expr(condition, scope, in_when=True)
                    self.body(when.body, set(scope))
                if st.else_body is not None:
                    self.body(st.else_body, set(scope))
            elif isinstance(st, P.While):
                self.expr(st.cond, scope)
                self.body(st.body, set(scope))
            elif isinstance(st, P.ForEach):
                self.expr(st.source, scope)
                self.locals = True
                self.body(st.body, scope | {st.var})
            elif isinstance(st, P.ForTo):
                for part in (st.start_expr, st.to, st.step):
                    self.expr(part, scope)
                self.locals = True
                self.body(st.body, scope | {st.var})
            elif isinstance(st, P.Try):
                self.body(st.body, set(scope))
                for variable, caught, branch in st.catches:
                    self.typeref(caught)
                    self.locals = self.locals or bool(variable)
                    self.body(branch, scope | ({variable} if variable else set()))
                if st.finally_body is not None:
                    self.body(st.finally_body, set(scope))
            elif isinstance(st, P.Scope):
                self.body(st.body, set(scope))
            elif isinstance(st, P.Return):
                self.expr(st.value, scope)

    def method(self, method: P.Method, scope: set[str], sink: dict[str, list[str]]) -> None:
        for param in method.params:
            self.typeref(param.type)
        self.typeref(method.return_type)
        sink.setdefault(method.name, []).extend(
            [method.return_type.text] if method.return_type is not None else [])
        inner = scope | {param.name for param in method.params}
        for param in method.params:
            self.expr(param.default, inner)
        self.body(method.body, set(inner))

    def module(self, module: P.Module) -> None:
        names = {getattr(member, "name", "") for member in module.members
                 if isinstance(member, (P.Method, P.Structure, P.Enum, P.ObjectField))}
        self.module_names = names - {""}
        for member in module.members:
            if isinstance(member, P.Method):
                self.method(member, set(names), self.methods)
            elif isinstance(member, P.ObjectField):
                self.typeref(member.type)
                if member.type is not None:
                    self.fields.setdefault(member.name, []).append(member.type.text)
                self.expr(member.init, set(names))
            elif isinstance(member, P.Structure):
                table = self.structures.setdefault(member.name, {})
                inner = names | {f.name for f in member.members if isinstance(f, P.ObjectField)}
                for sub in member.members:
                    if isinstance(sub, P.Method):
                        self.method(sub, set(inner), table)
                    elif isinstance(sub, P.ObjectField):
                        self.typeref(sub.type)
                        table.setdefault(sub.name, []).extend(
                            [sub.type.text] if sub.type is not None else [])
                        self.expr(sub.init, set(inner))
            elif isinstance(member, P.Enum):
                self.structures.setdefault(member.name, {})
                self.enum_values.update(item.name for item in member.items if item.name)
                for sub in member.methods:
                    self.method(sub, set(names), {})


def _line_fix(text: str, toks: list[Token], index: int) -> tuple[int, int] | None:
    """The span of the whole line of the import at toks[index], when the line holds nothing
    else - the removal the editor's own quick fix makes. A comment or a statement on the same
    line leaves the finding without a fix."""
    keyword = toks[index]
    last = keyword
    j = index + 1
    while j < len(toks) and toks[j].kind == "IDENT":
        last = toks[j]
        if j + 2 < len(toks) and toks[j + 1].kind == "OP" and toks[j + 1].value == "::":
            j += 2
            continue
        break
    start = text.rfind("\n", 0, keyword.start) + 1
    end = text.find("\n", last.end)
    end = len(text) if end < 0 else end + 1
    if text[start:keyword.start].strip() or text[last.end:end].strip():
        return None
    return start, end


def _members(node: object, sink: dict[str, list[str]], name_keys: tuple, type_keys: tuple) -> None:
    """Every named item of a yaml tree with the type it declares: properties, attributes,
    parameters, components, columns."""
    if isinstance(node, dict):
        name = next((node[key] for key in name_keys if isinstance(node.get(key), str)), None)
        if name:
            declared = next((node[key] for key in type_keys if isinstance(node.get(key), str)), None)
            sink.setdefault(name, [])
            if declared:
                sink[name].append(declared)
        for value in node.values():
            _members(value, sink, name_keys, type_keys)
    elif isinstance(node, list):
        for item in node:
            _members(item, sink, name_keys, type_keys)


def _base_type(data: dict) -> str | None:
    inherits = value_of(data, "Наследует")
    base = value_of(inherits, "Тип") if isinstance(inherits, dict) else None
    return base if isinstance(base, str) else None


def _unused_import_mapper(source: SourceFile) -> dict | None:
    """The map phase: a descriptor contributes its place in the layout, an element yaml its name
    and the types its items declare, a module what it asks the binder for and what it declares
    for the modules that reach it."""
    if source.kind == "yaml":
        if not _HAVE_YAML:
            return None
        if (fact := _layout_fact(source)) is not None:
            return fact
        data, err = _parsed(source)
        if err is not None:
            # The element is still there, only unknowable: it keeps its subsystem known, and a
            # module that reaches it is not judged.
            name = unreadable_object(source)
            return {"k": "el", "path": str(source.path), "stem": _pair_stem(source.rel),
                    "name": name, "bad": True} if name else None
        kind = object_kind(data)
        if not isinstance(data, dict) or not kind:
            return None
        name = value_of(data, "Имя", kind)
        members: dict[str, list[str]] = {}
        name_keys, type_keys = _key_spellings("Имя"), _key_spellings("Тип")
        for key, value in data.items():
            if key not in name_keys:
                _members(value, members, name_keys, type_keys)
        return {
            "k": "el",
            "path": str(source.path),
            "stem": _pair_stem(source.rel),
            "name": name if isinstance(name, str) else source.path.stem,
            "kind": kind,
            "members": members,
            "base": _base_type(data),
            "enum": sorted(_section_names(data)) if kind == _ENUM_KIND else [],
        }
    if source.kind != "xbsl" or is_query_file(source.path):
        return None
    try:
        toks = tokens(source)
    except DatasetError:
        return None  # no language data - the module cannot be read
    imports = []
    for written, line, col in _module_imports(toks):
        index = next(i for i, tok in enumerate(toks) if tok.line == line and tok.col == col)
        imports.append([written, line, col, _line_fix(source.text, toks, index)])
    module, errors = P.parse(source)
    fact: dict = {"k": "mod", "path": str(source.path), "stem": _pair_stem(source.rel),
                  "imports": imports}
    if errors:
        fact["broken"] = True
        return fact
    walk = _Walk(source.text)
    walk.module(module)
    declared = {"methods": walk.methods, "fields": walk.fields, "structures": walk.structures,
                "enum": sorted(walk.enum_values)}
    if not imports:
        # Nothing to judge here: the module only tells the others what its element declares.
        fact.update(declared)
        return fact
    tables: set[str] = set()
    for qualifiers, segments in query_tables(source):
        if qualifiers:
            walk.qualified.add("::".join(t.value for t in qualifiers) + "::" + segments[0].value)
        else:
            tables.add(segments[0].value)
    resources = ()
    if any(word + "{" in source.text for word in _resource_words()):
        resources = {name for name, _line, _col in _resource_refs(code_tokens(source), source.text)}
    fact.update({
        "types": sorted(walk.types), "bare": sorted(walk.bare), "roots": sorted(walk.roots),
        "qualified": sorted(walk.qualified), "when": sorted(walk.when),
        "named": sorted(walk.named), "dotted": sorted(walk.dotted),
        "chains": sorted(walk.chains), "tables": sorted(tables),
        "columns": _query_columns(source) if query_ranges(source) else [],
        "resources": sorted(resources), "locals": walk.locals, "this": walk.this,
        **declared,
    })
    return fact


def _query_columns(source: SourceFile) -> list[list[str]]:
    """[column, element, field] of every select item that passes a field of a table on as it is
    (`T.Supplier AS S` gives `S`, the element of `T`, `Supplier`), and [``, element, `*`] of a
    star.

    The column carries the type of the field into the code: a row read as `Row.S.Member` makes
    the binder ask for the type of `П`, and that type may be the only thing of its namespace the
    module touches (checked on the editor's answer). A computed column is a value of its own and
    is not followed: the members a query reads inside itself mark nothing.
    """
    intro, alias_intro, vocabulary = query_table_intro(), query_alias_intro(), _query_vocabulary()
    select = query_words("SELECT")
    out: list[list[str]] = []
    for span in query_ranges(source):
        block = query_block_tokens(source, span)
        aliases: dict[str, str] = {}
        for (_qualifiers, segments), alias in query_from_items(block):
            element = segments[0].value
            aliases[segments[-1].value] = element
            if alias is not None:
                aliases[alias.value] = element
        for i, tok in enumerate(block):
            if not (tok.kind in WORD_KINDS and tok.value.upper() in select):
                continue
            items: list[list[Token]] = [[]]
            depth = 0
            for t in block[i + 1:]:
                if t.kind == "OP" and t.value in "([{":
                    depth += 1
                elif t.kind == "OP" and t.value in ")]}":
                    if depth == 0:
                        break
                    depth -= 1
                elif depth == 0 and t.kind in WORD_KINDS and t.value.upper() in intro:
                    break
                elif depth == 0 and t.kind == "OP" and t.value == ",":
                    items.append([])
                    continue
                items[-1].append(t)
            for item in items:
                words = list(item)
                while words and (words[0].kind == "NUMBER" or (
                        words[0].kind in WORD_KINDS and words[0].value.upper() in vocabulary)):
                    words.pop(0)  # DISTINCT, TOP 10 and the like open the first item
                name = ""
                for k in range(len(words) - 2, -1, -1):
                    if words[k].kind in WORD_KINDS and words[k].value.upper() in alias_intro:
                        name, words = words[k + 1].value, words[:k]
                        break
                shape = [t.value if t.kind == "OP" else "#" for t in words]
                if shape == ["#", ".", "#"] and words[0].value in aliases:
                    out.append([name or words[2].value, aliases[words[0].value], words[2].value])
                elif shape in (["#", ".", "*"], ["*"]):
                    targets = [aliases[words[0].value]] if len(words) == 3 and words[0].value in aliases \
                        else sorted(set(aliases.values()))
                    out.extend(["", element, "*"] for element in targets)
    return out


# --- the reduce: the namespaces each module uses --------------------------------------------


class _Project:
    """What the reduce knows about the run: the placement of the elements and their declarations."""

    def __init__(self, facts: Mapping[str, dict], layout: Layout) -> None:
        self.layout = layout
        self.owned: dict[str, set[str]] = {}       # placement key -> element names
        self.keys_of: dict[str, set[str]] = {}     # element name -> placement keys
        self.elements: dict[str, dict] = {}        # stem -> element fact
        self.stems_of: dict[str, set[str]] = {}    # element name -> stems
        self.unknowable: set[str] = set()          # element names whose declarations are unknown
        self.enum_owners: dict[str, set[str]] = {}
        self.modules: dict[str, list[dict]] = {}   # element stem -> facts of its modules
        self._declarations: dict[str, dict[str, dict]] = {}
        for fact in facts.values():
            if fact["k"] != "el":
                continue
            place = layout.place(Path(fact["path"]))
            if place is not None:
                self.owned.setdefault(place.key, set()).add(fact["name"])
                self.keys_of.setdefault(fact["name"], set()).add(place.key)
            self.elements[fact["stem"]] = fact
            self.stems_of.setdefault(fact["name"], set()).add(fact["stem"])
            if fact.get("bad"):
                self.unknowable.add(fact["name"])
            for value in fact.get("enum", ()):
                self.enum_owners.setdefault(value, set()).add(fact["name"])
        for fact in facts.values():
            if fact["k"] == "mod":
                stem = self.element_stem(fact["stem"])
                self.modules.setdefault(stem, []).append(fact)
                if stem in self.elements:
                    for value in fact.get("enum", ()):
                        self.enum_owners.setdefault(value, set()).add(self.elements[stem]["name"])
                if fact.get("broken") and stem in self.elements:
                    self.unknowable.add(self.elements[stem]["name"])
        self.subsystems = ({subsystem_of_key(key) for key in self.owned}
                           | set(layout.subsystem_names.values()))

    def element_stem(self, stem: str) -> str:
        """The stem of the element a module belongs to: `Товары.Объект` -> `Товары`."""
        if stem in self.elements or "." not in stem.rsplit("/", 1)[-1]:
            return stem
        return stem.rpartition(".")[0]

    def declarations(self, stem: str) -> dict[str, dict]:
        """What the modules of an element declare: {"methods": {name: [result type]},
        "fields": {name: [type]}, "structures": {name: {field: [type]}}}, merged over the
        modules of the element and computed once."""
        cached = self._declarations.get(stem)
        if cached is None:
            cached = {"methods": {}, "fields": {}, "structures": {}}
            for fact in self.modules.get(stem, ()):
                for part in ("methods", "fields"):
                    for name, value in (fact.get(part) or {}).items():
                        cached[part].setdefault(name, []).extend(value)
                for name, value in (fact.get("structures") or {}).items():
                    cached["structures"].setdefault(name, {}).update(value)
            self._declarations[stem] = cached
        return cached


def _resources_by_key(layout: Layout) -> tuple[dict[str, set[str]], bool]:
    """The keys of the resource files by the placement key of their folder, and whether any root
    of the run lies on disk at all (an in-memory run has no folders to read)."""
    roots = set(layout.projects) | {
        folder for folder in layout.subsystem_names if layout.project_dir_of(folder) is None}
    found: dict[str, set[str]] = {}
    on_disk = False
    for root in roots:
        if not root.is_dir():
            continue
        on_disk = True
        for name in RESOURCE_DIRS:
            for folder in root.rglob(name):
                place = layout.place(folder / "_")
                if place is None or not folder.is_dir():
                    continue
                keys = found.setdefault(place.key, set())
                keys.update(p.relative_to(folder).as_posix() for p in folder.rglob("*") if p.is_file())
    return found, on_disk


class _Reach:
    """The namespaces one module uses: the names it spells, then the types their values bring.

    The declared types are followed as a work list of (the stem of the declaring element, a type
    text): a short name in a declaration is looked up first among the structures of the module
    that declares it, then among the elements of the project. Only the members the module names
    after a dot are followed, each structure and element once.
    """

    def __init__(self, fact: dict, project: _Project) -> None:
        self.fact = fact
        self.project = project
        self.dotted = set(fact["dotted"])
        self.marked: set[str] = set()      # element names the module reaches by a short name
        self.qualified: set[str] = set()   # qualified chains, resolved by the place they name
        self.work: list[tuple[str, str]] = []
        self.seen: set[tuple[str, str]] = set()

    def run(self, owner: dict | None, stem: str) -> None:
        fact, project = self.fact, self.project
        owner_members: dict[str, list[str]] = (owner or {}).get("members") or {}
        spelled = set(fact["types"]) | set(fact["roots"]) | set(fact["tables"])
        spelled |= {name for name in fact["bare"] if name not in owner_members}
        self.marked |= {chain.split(".")[0] for chain in spelled}
        for value in fact["when"]:
            self.marked |= project.enum_owners.get(value, set())
        self.qualified |= set(fact["qualified"])
        self.work.extend((stem, chain) for chain in fact["types"])
        self.work.extend((stem, chain) for chain in fact["qualified"])
        named = set(fact["named"])
        for name, declared in owner_members.items():
            if name in named:
                self.work.extend((stem, text) for text in declared)
        if owner and owner.get("base"):
            self.work.append((stem, owner["base"]))
            # A component that inherits a component of the project reads the properties of the
            # base by their bare names, just as its own.
            plain, qualified = _type_chains(owner["base"])
            bases = {chain.split(".")[0] for chain in plain}
            bases |= {_qualified_name(chain)[1] for chain in qualified}
            for base in bases:
                for base_stem in project.stems_of.get(base, ()):
                    base_members = (project.elements.get(base_stem) or {}).get("members") or {}
                    for name, declared in base_members.items():
                        if name in named:
                            self.work.extend((base_stem, text) for text in declared)
        for element, member in fact["chains"]:
            declared_here = False
            for target in project.stems_of.get(element, ()):
                decl = project.declarations(target)
                for part in ("methods", "fields"):
                    self.work.extend((target, text) for text in decl[part].get(member, ()))
                    declared_here = declared_here or member in decl[part]
                if member in decl["structures"]:
                    self.structure(target, member)
                    declared_here = True
            if not declared_here:
                # A member the platform gives the element (`FindByCode`, `Load`): what it
                # returns is a derived type of the element itself.
                self.element(element, "")
        for column, element, field in fact.get("columns", ()):
            if field != "*" and column not in self.dotted:
                continue
            for target in project.stems_of.get(element, ()):
                members = (project.elements.get(target) or {}).get("members") or {}
                if field == "*":
                    for member, declared in members.items():
                        if member in self.dotted:
                            self.work.extend((target, text) for text in declared)
                elif field in members:
                    self.work.extend((target, text) for text in members[field])
                else:
                    self.element(element, field)  # a standard field: the element's own type
        while self.work:
            context, text = self.work.pop()
            chains, qualified = _type_chains(text)
            for chain in qualified:
                self.qualified.add(chain)
                _qualifiers, element, tail = _qualified_name(chain)
                self.element(element, tail)
            for chain in chains:
                head, _, tail = chain.partition(".")
                if head in project.declarations(context)["structures"]:
                    self.structure(context, head)
                    continue
                self.marked.add(head)
                self.element(head, tail)

    def element(self, name: str, tail: str) -> None:
        """A value typed by an element: a structure of its module, or the element itself (a
        derived type, a component, a structure element) with the attributes it declares."""
        facet = tail.partition(".")[0]
        for stem in self.project.stems_of.get(name, ()):
            decl = self.project.declarations(stem)
            if facet and facet in decl["structures"]:
                self.structure(stem, facet)
                continue
            if (stem, "") in self.seen:
                continue
            self.seen.add((stem, ""))
            members = (self.project.elements.get(stem) or {}).get("members") or {}
            for table in (members, decl["methods"], decl["fields"]):
                for member, declared in table.items():
                    if member in self.dotted:
                        self.work.extend((stem, text) for text in declared)

    def structure(self, stem: str, name: str) -> None:
        if (stem, name) in self.seen:
            return
        self.seen.add((stem, name))
        for member, declared in self.project.declarations(stem)["structures"][name].items():
            if member in self.dotted:
                self.work.extend((stem, text) for text in declared)


def _used(fact: dict, project: _Project, resources: dict[str, set[str]],
          resources_on_disk: bool) -> set[str] | None:
    """The placement keys the module uses, or None when the module cannot be judged."""
    stem = project.element_stem(fact["stem"])
    owner = project.elements.get(stem)
    if owner is not None and owner.get("bad"):
        return None
    reach = _Reach(fact, project)
    reach.run(owner, stem)
    reached = reach.marked | {_qualified_name(chain)[1] for chain in reach.qualified}
    if reached & project.unknowable:
        return None  # a reached element declares what cannot be read
    path = Path(fact["path"])
    project_dir = project.layout.project_dir_of(path)
    used: set[str] = set()
    for name in reach.marked:
        used |= project.keys_of.get(name, set())
    for chain in reach.qualified:
        qualifiers, element, _tail = _qualified_name(chain)
        keys = project.keys_of.get(element)
        if keys and qualifiers:
            key = project.layout.resolve(qualifiers.split("::"), project_dir, keys)
            if key:
                used.add(key)
    place = project.layout.place(path)
    if place is not None and owner is not None and (
            fact["locals"] or fact["bare"] or fact["roots"] or fact["this"]):
        # The type of the module itself: the binder asks for it to check a local against its
        # properties and to look up a name that is not a local among them, `этот` included. A
        # module that does neither leaves its own namespace unused, a component module as well.
        used.add(place.key)
    bare_keys = [key for key in fact["resources"]
                 if "::" not in key and not key.startswith(_UPLOADED_PREFIX)]
    if bare_keys:
        if not resources_on_disk:
            return None  # the files are not in the run: a bare key may be what an import serves
        own = {place.key, place.subsystem} if place is not None else set()
        for key in bare_keys:
            if not any(key in resources.get(k, ()) for k in own):
                used |= {k for k, files in resources.items() if key in files}
    return used


@rule(
    _RULE, "code/unused-import.title", "D",
    scope="project", severity=Severity.WARNING, mapper=_unused_import_mapper,
)
def unused_import(facts: dict[str, dict]) -> Iterable[Diagnostic]:
    """An import whose namespace the module never uses - see the module docstring."""
    layout = _layout_from(facts)
    if not layout.known:
        return  # no descriptor at all - the project layout is unknown, nothing to judge
    project = _Project(facts, layout)
    resources: dict[str, set[str]] | None = None
    resources_on_disk = False
    for rel, fact in facts.items():
        if fact["k"] != "mod" or not fact["imports"] or fact.get("broken"):
            continue
        if resources is None and fact.get("resources"):
            resources, resources_on_disk = _resources_by_key(layout)
        used = _used(fact, project, resources or {}, resources_on_disk)
        if used is None:
            continue
        path = Path(fact["path"])
        project_dir = layout.project_dir_of(path)
        for written, line, col, span in fact["imports"]:
            key = layout.local_name(written, project_dir)
            if key not in project.owned and key not in project.subsystems:
                continue  # an unknown namespace (a library, a typo) - not this rule's case
            if key in used:
                continue
            packages = sorted(other for other in used if other.startswith(key + "::"))
            if packages:
                message = i18n.t("code/unused-import.packages", sub=written,
                                 packages=", ".join(packages))
            else:
                message = i18n.t("code/unused-import.unused", sub=written)
            yield Diagnostic(
                rel, line, col, _RULE, Severity.WARNING, message,
                fix=TextEdit(span[0], span[1], "") if span else None,
                data={"namespace": key},
            )
