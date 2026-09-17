"""Translate XBSL code by token spans: keywords, identifiers, comments, interpolations.

The lexer keeps exact spans (`value == text[start:end]`), so the module text is rewritten
by span edits and everything between tokens - indentation, blank lines, operators - stays
byte-identical. What changes:

- a KEYWORD goes to its English form of the same case ("Если" -> `If`, "если" -> `if`);
- an IDENT resolves through the project dictionary first, then the platform tables, then
  (after a dot) the facet suffixes; an unresolved one stays as written and is reported.
  The dictionary wins on purpose: when a project names a method after a platform word, one
  spelling must keep meaning one thing after the rewrite, exactly as it did before;
- inside `Запрос{...}` blocks the query-language keywords use the query vocabulary (the
  flat dictionaries must not answer there: a reverse lookup over the general terms would
  pull in words that are not query keywords at all);
- a COMMENT is translated line by line through the phrase plane of the dictionary, and the
  block it belongs to is then re-split by width (rewrap.py): the English text is longer, and
  the line breaks it inherited from the Russian one no longer hold the width limit;
- a STRING is data and stays, except a literal the dictionary's LITERALS plane names by its
  exact text - part of the data is names written as strings and messages meant for a person,
  and only the project can say which literal is which - except the CODE inside its
  `%{...}`/`${...}` interpolations, which is re-tokenized and translated like any other code,
  and except a literal that spells a RESOURCE PATH: the tree renames resource files and
  directories, so a path written as data has to follow them (`"Языки/%Код.svg"` addresses the
  directory the pass just renamed). A string literal that equals a renamed token is reported
  as a warning: a method called by its name in a string breaks silently when only the
  declaration is renamed. A literal standing inside a QUERY block or a resolvable literal
  (`Ресурс{...}`, `Образец{...}`) is out of the literals plane's reach: there the text between
  the quotes is a program of another language - a path, a regular expression, a query - and
  replacing it would rewrite code, not a message. Out of reach is not out of sight: such a
  literal is listed as data KEPT, with its place, so the translator sees it and knows why no
  entry moves it.

An entry of the literals plane spells its key and its value the way the source spells the
text between the quotes, escaping and all (`\\"` for an inner quote): one escaping, and the
dictionary refuses a value that would not survive being pasted back between two quotes.
"""

from __future__ import annotations

import dataclasses
import re
from collections import Counter
from functools import lru_cache
from pathlib import Path

from xbsl import dataset, lexer, terms, typeinfer
from xbsl import parser as P
from xbsl.engine import RESOURCE_DIRS, SourceFile
from xbsl.rules import _syntax
from xbsl.translation import platform_map
from xbsl.translation.dictionary import Dictionary
from xbsl.translation.names import ModuleOwner
from xbsl.translation.reporting import FileReport
from xbsl.translation.rewrap import rewrap_comments

_CYRILLIC_RE = re.compile(r"[А-Яа-яЁё]")

#: What separates the names of a reference to a picture: the subsystem, the folders, the dots.
_PICTURE_PARTS_RE = re.compile(r"::|[/\\.]")

#: One span replacement in the decoded text: (start, end, new text).
Edit = tuple[int, int, str]

#: The plane of a platform TYPE read where only a type can stand - a type expression, the root
#: of a static call. The project gate does not hold there (see Resolver.platform_type), so the
#: answer becomes a gap only when the project declares a TYPE of that name.
PLATFORM_TYPE = "platform-type"


def has_cyrillic(text: str) -> bool:
    return _CYRILLIC_RE.search(text) is not None


def _one_type(written: str) -> str:
    """`written` when it names ONE type, "" when it is a UNION of several.

    `Авто|Булево`, `Байты|Строка|?`: such a link names no type at all - the value is one of the
    alternatives and the code does not say which. `dataset.member_type_head` answers it with the
    FIRST one, and a chain typed by that guess spells the word after it by half of the type:
    `Граница` came out Bound on a link that may just as well hold a spreadsheet area, where the
    same word is Border. A chain that reaches a union is given no owner, and the member is read
    the way it was before an owner was ever asked for. Only a bar OUTSIDE the generic brackets
    makes a union: `Массив<Строка|Число>` is one type - an array - and passes.
    """
    depth = 0
    for char in written:
        if char == "<":
            depth += 1
        elif char == ">":
            depth -= 1
        elif char == "|" and depth <= 0:
            return ""
    return written


def _typed_members(table: dict) -> dict[str, str]:
    """{name: its written type} with the links that name no single type left out (see _one_type)."""
    return {
        str(name): str(written) for name, written in table.items()
        if isinstance(written, str) and _one_type(written)
    }


class ProjectIndex:
    """What the project index of the editor knows that a member of a chain needs.

    A word after a dot is often spelled by its owner alone - `Граница` is Bound on an array and
    Border on a spreadsheet area - and the owner of `Объект.Товары.Граница()` is neither of
    the names written there: it is the type of the tabular section of the object the form
    edits. The index the editor completes with already reads that (xbsl/indexer.py): the object
    a form edits, the types of the attributes and tabular sections of a project object, the
    fields of the structures, the kinds of the elements. The translator reads the same facts
    and walks a chain with the same code the completion does (rules/_syntax.chain_type), so the
    two cannot type one chain differently.
    """

    def __init__(self, index: dict) -> None:
        from xbsl.lsp_nav import IndexLookup

        self.lookup = IndexLookup(index)
        try:
            catalog = dataset.load_json("stdlib.json") or {}
        except Exception:  # noqa: BLE001 - no data, the project half alone
            catalog = {}
        returns: dict[str, dict[str, str]] = {
            owner: _typed_members(members)
            for owner, members in (catalog.get("member_types") or {}).items()
            if isinstance(members, dict)
        }
        for owner, members in self.lookup.method_returns().items():
            returns[owner] = {**returns.get(owner, {}), **_typed_members(members)}
        #: {type: {member: its result type}} - the platform catalog joined with the project.
        self.returns = returns

    @classmethod
    def forget(cls) -> None:
        """Drop the kept index - the next `build` reads the project again."""
        global _KEPT
        _KEPT = None

    @classmethod
    def build(cls, root: Path) -> ProjectIndex | None:
        """The index of the project under `root`; None when it cannot be built.

        Kept for the sources it was built from and handed back while they stand still. The
        pass needs the index once, but the interactive tools run the pass again and again -
        `translate_status`, `translate_gaps`, the dictionary echo of the MCP server - and each
        of them used to pay for the same parse of the same unchanged files.

        The stamp is taken BEFORE the build on purpose. A file written while the index is
        being built lands in it half-read; taken afterwards, the stamp would call that state
        current and the next call would trust it.
        """
        from xbsl import indexer

        global _KEPT
        key = str(Path(root).resolve())
        stamp = indexer.sources_stamp(root)
        kept = _KEPT
        if kept is not None and kept[0] == key and kept[1] == stamp:
            return kept[2]
        try:
            built = cls(indexer.build_index(root))
        except Exception:  # noqa: BLE001 - no index: every chain stays read as before
            return None
        # One root at a time. A pass translates one project, the parse of a whole project is
        # megabytes, and holding the previous one would carry that weight for a second root
        # nobody asks about twice; a project switched to drops the one before it right here.
        _KEPT = (key, stamp, built)
        return built

    def element_kind(self, name: str) -> str:
        """The kind of the project element named `name` (`ПравоНаДействие`), or ""."""
        found = self.lookup.object_by_name(name)
        kind = found.get("kind") if found else None
        return kind if isinstance(kind, str) else ""

    def declares_method(self, module: str, name: str) -> bool:
        """Whether the module `module` of the project declares a method `name`."""
        return self.lookup.method(module, name) is not None

    def module_names(self, path: Path) -> dict[str, str]:
        """{bare name: its written type} a module reads without declaring it.

        The attributes and tabular sections of the object an object module belongs to, the
        properties of a component, and the object a form edits (see data_object). Only types the
        project describes in its metadata count: a structure some module declares under the name
        of this module is no owner of it. Which of these names a METHOD sees is not decided here
        (see ChainTypes.owner).
        """
        stem = path.name[: -len(".xbsl")] if path.name.endswith(".xbsl") else path.stem
        record = self.lookup.struct_by_name(stem) or {}
        described = (record.get("property_types") or {}) if record.get("kind") else {}
        types = _typed_members(described)
        pair = self.data_object(path)
        if pair:
            types.setdefault(pair[0], pair[1])
        return types

    def data_object(self, path: Path) -> tuple[str, str] | None:
        """(name, written type) of the object the form at `path` edits, or None.

        The base type of the form names it by its argument: `ФормаОбъекта<Заказы.Объект>` makes
        `Объект` a `Заказы.Объект`.
        """
        stem = path.name[: -len(".xbsl")] if path.name.endswith(".xbsl") else path.stem
        pair = self.lookup.form_data_object(stem)
        return (str(pair[0]), str(pair[1])) if pair else None

    def module_returns(self, path: Path) -> dict[str, str]:
        """{method: its written result} of the module at `path` - a bare call of its own code."""
        module = path.name[: -len(".xbsl")] if path.name.endswith(".xbsl") else path.stem
        return _typed_members({
            str(method["name"]): str(method.get("returns_written") or method["returns"])
            for method in self.lookup.methods_by_module(module) if method.get("returns")
        })


#: The index of ONE project root: (the root, the stamp of the sources it was built from, the
#: index itself). See `ProjectIndex.build` for why one root and why the stamp reads the bytes.
_KEPT: tuple[str, tuple, ProjectIndex] | None = None

# The index is parsed with the language data, and the type catalogue is read into it, so it
# must not outlive the pinned data root any more than the tables the rules build do.
dataset.register_reset(ProjectIndex.forget)


@dataclasses.dataclass(frozen=True)
class ChainTypes:
    """The types the chains of one module are walked with (see ProjectIndex)."""

    project: ProjectIndex
    #: The bare names the module reads without declaring them, with their written types.
    names: dict[str, str]
    #: The results of the module's own methods.
    returns: dict[str, str]
    #: The name of the object a form edits (`Объект`), "" for any other module.
    data_object: str = ""

    @classmethod
    def of(cls, project: ProjectIndex, path: Path) -> ChainTypes:
        pair = project.data_object(path)
        return cls(project, project.module_names(path), project.module_returns(path),
                   pair[0] if pair else "")

    def owner(self, module_owner: ModuleOwner | None) -> ModuleOwner:
        """The names of the module's element as a chain root reads them, method by method.

        The same owner the rest of the walk goes by (see owner_scopes), with the object a form
        edits added: that object is a property of the base type of the form, and nothing in the
        data marks it contextual, so it counts as any property that is not - an instance method
        sees it, a static method and a method compiled on the server alone do not.
        """
        base = module_owner if module_owner is not None else ModuleOwner()
        if not self.data_object or self.data_object in base.names:
            return base
        contextual = base.contextual if base.contextual is not None else frozenset()
        return ModuleOwner(base.names | {self.data_object}, contextual)

    def receiver(self, toks: list, index: int, local_names: dict[str, str],
                 method_types: MethodTypes | None, place: int,
                 visible: frozenset[str] = frozenset()) -> str:
        """The type of the receiver of the member at `index` - the chain before its dot - or "".

        The chain is read only when every link is one the walk consumes whole: a name, a member,
        a call of a member, a non-null assertion. Anything else before the dot - an index, a
        null-safe access, a literal - answers "" rather than the type of a part of the chain.
        A local of the method is the local, typed by what its declaration writes or holds. A
        name the module reads without declaring it is typed by the index only where the method
        sees it (`visible`, see ChainTypes.owner): in a static method, or in a method compiled on
        the server alone, the same word is not the property and may be a platform type, whose
        member the property's type must not spell. Any other root names nothing here.
        """
        start = _chain_start(toks, index - 1)
        if start is None:
            return ""
        root = toks[start]
        following = _next_code_token(toks, start)
        if following is not None and following.kind == "OP" and following.value == "(" \
                and root.value not in self.returns:
            return ""

        def resolve(name: str) -> str | None:
            if name in local_names:
                typed = local_names.get(name) or (
                    method_types.type_at(name, place) if method_types is not None else "")
                return typed or None
            written = self.names.get(name) if name in visible else None
            return dataset.member_type_head(written) if written else None

        def written(name: str) -> str | None:
            if name in local_names or name not in visible:
                return None
            return self.names.get(name)

        found = _syntax.chain_type(toks, start, resolve, self.project.returns,
                                   stop_offset=toks[index - 1].start,
                                   own_returns=self.returns, resolve_written=written)
        return found or ""


def _next_code_token(toks: list, index: int):
    """The token after `index`, comments skipped, or None."""
    position = index + 1
    while position < len(toks) and toks[position].kind == "COMMENT":
        position += 1
    return toks[position] if position < len(toks) else None


def _chain_start(toks: list, dot: int) -> int | None:
    """The index of the root of the chain that ends right before the dot at `dot`, or None.

    Walked back over names, member dots, the parentheses of calls and non-null assertions. A
    shape the chain walk does not read link by link ends the search with None.
    """
    if dot < 1 or toks[dot].kind != "OP" or toks[dot].value != ".":
        return None
    position = dot - 1
    while position >= 0:
        tok = toks[position]
        if tok.kind == "COMMENT" or (tok.kind == "OP" and tok.value == "!"):
            position -= 1
            continue
        if tok.kind == "OP" and tok.value == ")":
            depth = 0
            while position >= 0:
                if toks[position].kind == "OP" and toks[position].value == ")":
                    depth += 1
                elif toks[position].kind == "OP" and toks[position].value == "(":
                    depth -= 1
                    if depth == 0:
                        break
                position -= 1
            position -= 1
            if position < 0 or toks[position].kind != "IDENT":
                return None
            continue
        if tok.kind != "IDENT":
            return None
        before = position - 1
        while before >= 0 and toks[before].kind == "COMMENT":
            before -= 1
        if before >= 0 and toks[before].kind == "OP" and toks[before].value == ".":
            position = before - 1
            continue
        if before >= 0 and toks[before].kind == "OP" and toks[before].value in ("?.", "?", "::"):
            return None
        return position
    return None


class Resolver:
    """Identifier resolution shared by the code and yaml translators.

    `project_names` are the names the project itself declares (see names.py). They are
    answered by the project dictionary ALONE: a word the platform also knows would otherwise
    be renamed at its uses while its declaration waited for a dictionary entry, and the two
    halves would no longer meet.
    """

    def __init__(
        self,
        dictionary: Dictionary,
        project_names: frozenset[str] = frozenset(),
        dictionary_scopes: frozenset[str] = frozenset(),
        component_names: frozenset[str] = frozenset(),
        data_values: frozenset[str] = frozenset(),
        project_types: frozenset[str] = frozenset(),
        component_methods: dict[str, frozenset[str]] | None = None,
        resource_keys: frozenset[str] = frozenset(),
        project_component_types: frozenset[str] = frozenset(),
        project_index: ProjectIndex | None = None,
    ) -> None:
        self.dictionary = dictionary
        self.project_names = project_names
        #: The editor's index of the whole project (see ProjectIndex): the types a chain of
        #: members walks through and the kinds of the elements. None for a lone file - the
        #: chains are then read as before, name by name.
        self.project_index = project_index
        self.dictionary_scopes = dictionary_scopes
        self.component_names = component_names
        #: {interface component of the project: the methods its module declares} - what a form
        #: calls on a node of that component is the project's method (see names.component_methods).
        self.component_methods = component_methods or {}
        #: The files and folders below the resources of the project, as a reference addresses
        #: them (see names.resource_keys): a reference to anything else is not the project's file.
        self.resource_keys = resource_keys
        #: The top-level names of interface components declared by the project. Unlike
        #: component_names, this contains no nested node or property names and can therefore
        #: prove that a typed yaml node belongs to a project component.
        self.project_component_types = project_component_types
        #: Cyrillic string VALUES of the project's json resources. A code literal spelled
        #: exactly like one of them is usually COMPARED against that data, and translating
        #: the literal parts the comparison from values no translation ever touches.
        self.data_values = data_values
        #: The names the project declares as TYPES (see names.declared_types) - the only
        #: project names that can stand where the platform's type does.
        self.project_types = project_types
        #: {entry key: the platform's own spelling} for the entries that answered where the
        #: platform answers the same word, and the keys that answered where it does not.
        #: An entry is judged an echo only when every place it answered agrees, so a word the
        #: dictionary carries for a place of its own is never called redundant.
        self.echoed: dict[str, str] = {}
        self.needed: set[str] = set()

    # --- the judgement of the entries the pass used ----------------------------------------
    #
    # The mirror image of the shadow report (see _identifier_edit): there an entry the
    # platform OVERRULES, here one it merely REPEATS. Such an entry is a workaround nobody
    # can see - the tree comes out the same without it - and while it stands it hides a hole
    # in the engine that the platform data would fill: the languages of a project were
    # spelled by exactly such an entry, and the gap behind it was found by a test on an empty
    # dictionary, never by the live project.

    def _judge_entry(self, name: str, hit: str, platform: str | None, *scopes: str) -> None:
        """Compare an entry that answered with what the platform would have said instead.

        `platform` is the reading the pass would take WITHOUT the entry - taken from the same
        code the pass runs, never from a second reading of the tables, so the judgement cannot
        drift from the behaviour it describes. None means nothing else answers there, and the
        entry is what keeps the name translated.
        """
        key = name
        for scope in scopes:
            if scope and f"{scope}.{name}" in self.dictionary.tokens:
                key = f"{scope}.{name}"
                break
        if platform is not None and platform == hit:
            self.echoed.setdefault(key, platform)
        else:
            self.needed.add(key)

    def note_platform_win(self, name: str, spelling: str) -> None:
        """A place where the PLATFORM answered and the dictionary was not asked at all.

        An entry spelling the word the same way did nothing here; one spelling it otherwise is
        the shadow case, judged where it is reported.
        """
        entry = self.dictionary.tokens.get(name)
        if entry is not None and entry == spelling:
            self.echoed.setdefault(name, spelling)

    def note_entry_only(self, name: str, hit: str, *scopes: str) -> None:
        """A place where the dictionary answered and no platform table is consulted at all -
        a resource file name, a custom property of a component: the entry is load-bearing."""
        self._judge_entry(name, hit, None, *scopes)

    def echoes(self) -> dict[str, str]:
        """{entry key: the platform's own spelling} of the entries the platform answers itself."""
        return {key: value for key, value in sorted(self.echoed.items())
                if key not in self.needed}

    def dictionary_key(self, name: str, scope: str) -> tuple[str | None, str]:
        """A KEY of a localized-strings dictionary - the project dictionary answers alone.

        A key lives in the namespace of its dictionary, so the entry may be written qualified
        (`<Dictionary>.<Key>`). The platform tables are not consulted at all: a key named after
        an ordinary word would otherwise be renamed at its uses while its declaration waited
        for an entry, and a caption would inherit the spelling of a platform attribute.
        """
        hit = self.dictionary.token(name, scope)
        if hit is not None:
            # No platform table is consulted here at all, so the entry is what translates the
            # key - it is never one of those the platform answers itself.
            self.note_entry_only(name, hit, scope)
            return hit, "user"
        return None, "missing"

    def resource_name(self, name: str) -> tuple[str | None, str]:
        """A name of the project's resource tree: a file or a directory below the resources.

        The project named its files itself, and every place that spells such a name - the
        file of the tree, a value of a yaml property, a path in a string, the body of
        `Ресурс{...}` - asks this one question, so the places cannot part. The dictionary
        answers alone. A platform word that happens to spell the file is no name of it: the
        file of the tree once took `CreateCopy.svg` from the compiler dictionary while the form
        went on asking for the Russian file, and the build found no such resource.
        """
        hit = self.dictionary.token(name)
        if hit is not None:
            # No platform table is asked here, so the entry is what renames the file.
            self.note_entry_only(name, hit)
            return hit, "user"
        return None, "missing"

    def library_picture(self, reference: str) -> str | None:
        """The English spelling of a reference to a picture of the platform's library, or None.

        Every place that names a picture - a yaml value, the body of `Ресурс{...}`, a string
        literal - asks this one question. A file of the project answers first: a project may
        keep a file under the name of a picture of the library, the reference is then to that
        file, and its name is the project's (resource_name). Otherwise the library names its
        own picture (platform_map.resource_path_english), and the dictionary is not asked: an
        entry written for a word of the project must not rename a picture the English library
        calls otherwise. An entry that spells a part of the reference the way the library does
        is judged an echo.
        """
        key = reference.rpartition("::")[2]
        if key.replace("\\", "/") in self.resource_keys:
            return None
        english = platform_map.resource_path_english(reference)
        if english is None:
            return None
        written = _PICTURE_PARTS_RE.split(reference)
        spelled = _PICTURE_PARTS_RE.split(english)
        if len(written) == len(spelled):
            for name, spelling in zip(written, spelled):
                if name != spelling:
                    self.note_platform_win(name, spelling)
        return english

    def identifier(
        self, name: str, *, after_dot: bool = False, scope: str = "", type_scope: str = "",
        static_root: bool = False, reference: str = "",
    ) -> tuple[str | None, str]:
        """(the English spelling or None, which plane answered: user|platform|missing).

        The position matters: a name standing on its own is a TYPE or a variable, while a
        name after a dot is a MEMBER, and the two dictionaries answer the same word
        differently - one Russian word is the type `Strings` and the member `Rows`. So a root reads
        the type dictionary first and a member the compiler dictionary first. `scope` names
        a namespace of its own (a localized-strings dictionary), where the project may have
        entered a spelling for this one namespace; `type_scope` is the second namespace of a
        member - the TYPE the receiver was declared as, which is what a structure field
        answers to.

        `reference` says the member is the REFERENCE member and how the receiver told it (see
        _reference_reading): "facet" - the receiver holds a facet of a project object, and
        the facet word answers right after an entry qualified by the receiver or its type
        (written about that receiver) and before the plain entry (written about the project's
        own words); "load" - a receiver of no known type whose chain goes on to load the
        record, and the facet word answers after the whole dictionary and the project gate,
        in place of the flat reading.
        """
        if static_root:
            # `Strings.Join(...)` - a name with a dot after it that the platform knows as a
            # TYPE is the type, whatever else the project called by the same word: the gate
            # must not hold here. It once turned a static call into an undefined variable,
            # because a structure field elsewhere carried the same name. A TYPE the project
            # declares under that name is the exception (see platform_type).
            platform_type = self.platform_type(name)
            if platform_type:
                return platform_type, PLATFORM_TYPE
        if reference == "facet":
            scoped = self.dictionary.scoped_token(name, scope, type_scope)
            if scoped is not None:
                self._judge_entry(name, scoped, platform_map.facet_suffix_english(name),
                                  scope, type_scope)
                return scoped, "user"
            facet = platform_map.facet_suffix_english(name)
            if facet:
                return facet, "platform"
        hit = self.dictionary.token(name, scope, type_scope)
        if hit is not None:
            self._judge_entry(name, hit, self._platform_reading(name, after_dot, reference)[0],
                              scope, type_scope)
            return hit, "user"
        return self._platform_reading(name, after_dot, reference)

    def _platform_reading(self, name: str, after_dot: bool, reference: str
                          ) -> tuple[str | None, str]:
        """What `identifier` answers when the dictionary says nothing - its own tail.

        One body for two callers: the pass takes the reading from here, and the entry
        judgement asks it the counterfactual question - what would stand here without the
        entry - so a verdict about an entry cannot describe a resolution the pass never makes.
        """
        if name in self.project_names:
            # The project's own name: no platform fallback, so the declaration and every
            # use of it move together - or stay together, waiting for one dictionary entry.
            return None, "missing"
        if reference == "load":
            facet = platform_map.facet_suffix_english(name)
            if facet:
                return facet, "platform"
        platform = (
            platform_map.member_english(name) if after_dot
            else platform_map.ident_english(name)
        )
        if platform:
            return platform, "platform"
        if after_dot:
            facet = platform_map.facet_suffix_english(name)
            if facet:
                return facet, "platform"
            if platform_map.is_member_name(name):
                # A member the PLATFORM declares, spelled in English by no table of the data.
                # Not the project's gap: an invented English name for a platform member is
                # refused by the compiler, so no dictionary entry could be the right one. It
                # is reported apart, as what it is - a hole in the platform data.
                return None, "platform-gap"
        return None, "missing"

    def type_name(self, name: str, *, after_dot: bool = False) -> tuple[str | None, str]:
        """The same, for a name inside a TYPE expression.

        After a dot there stands a facet, not a member: `Задачи.Ссылка` is
        `Tasks.Reference`, while the very same word as a property is `Link`.
        """
        if after_dot:
            facet = platform_map.facet_suffix_english(name)
            if facet:
                self.note_platform_win(name, facet)
                return facet, "platform"
        else:
            platform_type = self.platform_type(name)
            if platform_type:
                self.note_platform_win(name, platform_type)
                return platform_type, PLATFORM_TYPE
        hit = self.dictionary.token(name)
        if hit is not None:
            self._judge_entry(name, hit, self._platform_type_reading(name, after_dot)[0])
            return hit, "user"
        return self._platform_type_reading(name, after_dot)

    def annotation_name(self, name: str) -> tuple[str | None, str]:
        """Resolve the name after `@` in the annotation namespace.

        A platform annotation is a type derived from `Annotation` in the catalog. Its
        spelling therefore stays the platform's even when the project declares an ordinary
        method or field under the same name. Any other annotation name remains a project name
        and follows the dictionary like its declaration and references do.
        """
        if name in _platform_annotation_names():
            spelling = platform_map.type_english(name)
            if spelling:
                self.note_platform_win(name, spelling)
                return spelling, PLATFORM_TYPE
        return self.identifier(name)

    def platform_type(self, name: str) -> str | None:
        """The English spelling of the platform TYPE `name` stands for where a type stands.

        A type expression, the root of a static call and the owner of a facet name a type, and
        the only project names that can mean one are the types the project declares. Any other
        name of the project spelled like a platform type - a field, an attribute, a method, a
        property - leaves the type to the platform: the users catalog of a type expression came
        out `Пользователи.Reference` in a project whose structure had a field spelled like the
        catalog, half of it gated, half of it translated, and the build knew neither. A project
        TYPE spelled like a platform one answers to the dictionary, as every name the project
        declares does, so its declaration and its uses move together.

        The platform's generic entity (`Entity`) is a type too, though no type pair spells it:
        the catalog knows it as the owner of facets, and the flat dictionary spells it.
        """
        if not name or name in self.project_types:
            return None
        return platform_map.type_english(name) or platform_map.facet_owner_english(name)

    def _platform_type_reading(self, name: str, after_dot: bool) -> tuple[str | None, str]:
        """What `type_name` answers when the dictionary says nothing - its own tail."""
        if after_dot:
            # The facet is the platform's own word even when the project declares a name
            # just like it - a type expression would break if `.Ссылка` stayed Russian.
            facet = platform_map.facet_suffix_english(name)
            if facet:
                return facet, "platform"
        if not after_dot:
            platform_type = self.platform_type(name)
            if platform_type:
                return platform_type, PLATFORM_TYPE
        if name in self.project_names:
            return None, "missing"
        platform = platform_map.ident_english(name)
        if platform:
            return platform, "platform"
        return None, "missing"


def apply_edits(text: str, edits: list[Edit]) -> str:
    """Apply span edits last-to-first, so earlier offsets stay valid."""
    for start, end, new in sorted(edits, key=lambda e: e[0], reverse=True):
        text = text[:start] + new + text[end:]
    return text


def translate_code(source: SourceFile, resolver: Resolver, report: FileReport,
                   owner: ModuleOwner | None = None,
                   form_nodes: dict[str, str] | None = None) -> str:
    """The translated text of one module (or standalone query file).

    `owner` is what the element of the module puts in scope of its methods (see
    names.module_owner); without it a bare name is a property of nothing. `form_nodes` are the
    nodes of the component tree the module pairs with and the components they are (see
    names.form_nodes).
    """
    edits: list[Edit] = []
    toks = lexer.tokens(source)
    ranges = _syntax.query_ranges(source)
    chains = (
        ChainTypes.of(resolver.project_index, Path(source.path))
        if resolver.project_index is not None else None
    )
    collect_token_edits(source.text, toks, 0, ranges, resolver, report, edits,
                        inferred_locals=inferred_locals(source, resolver.project_names),
                        type_ranges=type_ranges(source),
                        owner_scopes=owner_scopes(source, owner),
                        form_nodes=form_nodes, chains=chains,
                        chain_scopes=(owner_scopes(source, chains.owner(owner))
                                      if chains is not None else None))
    text = apply_edits(source.text, edits)
    # Span edits keep the author's line breaks, and an English sentence is the longer one:
    # a comment that fitted the width limit in Russian stops fitting it here. The blocks
    # that the translation pushed over are split again - see rewrap.py for what it spares.
    return rewrap_comments(text, source.text)


def collect_token_edits(
    text: str,
    toks: list,
    base: int,
    query_ranges: list[tuple[int, int]],
    resolver: Resolver,
    report: FileReport,
    edits: list[Edit],
    at: tuple[int, int] | None = None,
    root_scope: str = "",
    inferred_locals: dict[str, MethodTypes] | None = None,
    type_ranges: list[tuple[int, int]] | None = None,
    method: MethodScope | None = None,
    owner_scopes: list[tuple[int, int, frozenset[str]]] | None = None,
    form_nodes: dict[str, str] | None = None,
    query_aliases: frozenset[str] = frozenset(),
    chains: ChainTypes | None = None,
    chain_scopes: list[tuple[int, int, frozenset[str]]] | None = None,
) -> None:
    """Walk a token list and append the edits; `base` shifts spans into the outer text.

    `at` anchors the REPORT positions of a nested fragment (an interpolation, a yaml value)
    at the fragment's own place in the outer file - the token positions inside it count
    from the fragment start and would point nowhere. `inferred_locals` is what the type
    inference read off the whole module (see inferred_locals): the types of the locals whose
    declarations name none. A fragment has no methods and passes nothing. `type_ranges` are
    the spans of the TYPE expressions (see type_ranges): a name inside one is a type or a
    facet, never a member - `Заявки.Ссылка` as a type is `Tasks.Reference`, the very same
    words as a member access are `Tasks.Link`. `method` is the method a fragment of the module
    stands in (see MethodScope): an interpolation reads the names that method declares, and
    the walk over the fragment starts from what the walk over the module knew there.
    `owner_scopes` are the methods of the module with the names its element puts in scope of
    each (see owner_scopes). `form_nodes` are the nodes of the component tree the module pairs
    with (see names.form_nodes): a member reached through one of them is judged by its component.
    `chains` types the chain before a member whose receiver no declaration types (see
    ChainTypes); a fragment has none and reads such a member by its name alone. `chain_scopes`
    are the methods with the names a chain root may be typed by there (see ChainTypes.owner).
    """
    # The paths inside `Ресурс{...}` are spelled first, off the text: the tokens of such a path
    # are file names, and the walk below must not read them as code.
    resource_tokens = _resource_literal_edits(text, toks, base, resolver, report, edits, at)
    prev_dot = False
    prev_ident = ""
    #: The ROOT of the current dotted chain: `Components.Tags.Remove` is a member of a
    #: component two dots deep, and only the root says which vocabulary answers.
    chain_root = ""
    # A constructor call opens the namespace of the TYPE it builds: `new ServicePill(Caption =
    # ...)` names a property of that component, and the property may carry a spelling the same
    # word cannot carry globally. The stack follows nesting, so a constructor inside a
    # constructor keeps its own namespace.
    ctor_stack: list[tuple[str, int]] = []
    method_name = method.name if method is not None else ""
    pending_ctor = False
    depth = 0
    #: Words already rewritten as part of a query PHRASE - they must not be judged again.
    skip_until = 0
    #: Names DECLARED in the current method (parameters, locals, loop variables), each with
    #: the type its declaration names where it names one. A local may be named after a
    #: platform type, and then `Strings.Add(...)` is a call on the LOCAL, not a static call on
    #: the type - taking the type spelling there turns it into an undefined variable. The
    #: TYPE is what opens the namespace of a member: `Root.Услуги` where `Root: JsonRoot` is a
    #: field of that structure, and the dictionary may spell it for that structure alone.
    #: Cleared at every method boundary; a fragment starts from its method's (see MethodScope).
    local_names: dict[str, str] = dict(method.local_names) if method is not None else {}
    #: What the inference knows about the locals of the current method (see inferred_locals).
    method_types: MethodTypes | None = method.types if method is not None else None
    #: Where a fragment stands in the module text, when its own offsets do not say it.
    place = method.place if method is not None else None
    #: The names the element of the module puts in scope of the current method: a property
    #: named like a platform type is the property there, just as a local is the local.
    owner_names: frozenset[str] = method.owner_names if method is not None else frozenset()
    #: The names of the module a chain root may be typed by in the current method: the owner's
    #: names the method sees, the object a form edits among them (see ChainTypes.owner). A
    #: fragment has no method boundary to read them at and starts from its method's.
    chain_names: frozenset[str] = method.chain_names if method is not None else frozenset()
    if chains is None and method is not None:
        # An interpolation is code of the method around it, chains and all: walked without them
        # it read the same expression differently inside the quotes and outside.
        chains = method.chains
    #: The structure whose fields are being declared right now, and whether the next name
    #: belongs to it. The fields of one structure share a namespace: two Russian words
    #: translated into one English word are a structure the compiler refuses.
    struct_name = ""
    pending_field = False
    #: Bodies of the resolvable literals - a string inside one is code of another language.
    resolvable = _resolvable_ranges(toks)
    for index, tok in enumerate(toks):
        kind = tok.kind
        if kind == "EOF":
            break
        if kind == "KEYWORD" and tok.canonical in ("METHOD", "CONSTRUCTOR"):
            struct_name = ""
            pending_field = False
            local_places: dict[str, tuple[int, int]] = {}
            local_names = _method_locals(toks, index, resolver.project_names, local_places)
            owner_names = _owner_names_at(owner_scopes, base + tok.start)
            chain_names = _owner_names_at(chain_scopes, base + tok.start)
            method_token = _next_ident_token(toks, index)
            method_name = method_token.value if method_token is not None else ""
            method_types = (inferred_locals or {}).get(method_name)
            # A declaration that names no type is typed by its value, where the inference can
            # name one; a type the source writes stands as written.
            for local, typed in (method_types.plain.items() if method_types else ()):
                if local in local_names and not local_names[local]:
                    local_names[local] = typed
            # Every declared name of one method shares a namespace: two Russian words that
            # translate into ONE English word collide there, and the compiler refuses the
            # module ("variable is already defined"). Only the translator can see this - the
            # dictionary is global, the collision is local.
            for local in sorted(local_names):
                translated, _plane = resolver.identifier(local, scope=method_name)
                if translated:
                    line, col = at if at is not None else local_places.get(local, (0, 0))
                    report.note_name(f"method:{method_name}", local, translated, line, col)
            # A platform type the method reads as the root of a static access stands in the same
            # namespace: a local translated into the type's word hides the type, and the access
            # reads the local instead - a parameter named for a transfer encoding took the word
            # of the encoding type, and `Encoding.Iso8859_1` asked a string for a property.
            for root, spelling, line, col in _static_type_roots(
                    toks, index, local_names, owner_names, query_ranges, base, resolver):
                report.note_name(f"method:{method_name}", root, spelling,
                                 *(at if at is not None else (line, col)))
            # The METHODS of one module share a namespace of their own, and the language has
            # no overloading: two of them under one name is a module the compiler refuses.
            # Met live - two Russian words that English spells alike, and the tree went out
            # with two handlers named the same while every check called the translation done.
            if method_name:
                translated, _plane = resolver.identifier(method_name, scope=root_scope)
                if translated:
                    line, col = at if at is not None else (method_token.line, method_token.col)
                    report.note_name("module", method_name, translated, line, col)
        if kind == "OP" and tok.value == "@":
            # An ANNOTATION opens the namespace of its own arguments: `@ProjectUpdate(Number =
            # 20)` names a parameter of the annotation, not a word of the project.
            pending_ctor = True
        if kind == "KEYWORD" and tok.canonical == "NEW":
            pending_ctor = True
        elif pending_ctor and kind in ("IDENT", "KEYWORD"):
            ctor_stack.append((tok.value, depth))
            pending_ctor = False
        elif kind == "KEYWORD" and tok.canonical in ("STRUCTURE", "ENUMERATION"):
            struct_name = _next_ident(toks, index) if tok.canonical == "STRUCTURE" else ""
            pending_field = False
        elif kind == "KEYWORD" and tok.canonical in ("VAR", "VAL", "REQ") and struct_name:
            pending_field = True
        elif kind == "OP" and tok.value == ";":
            struct_name = ""
            pending_field = False
        elif kind == "OP" and tok.value in "([{":
            depth += 1
        elif kind == "OP" and tok.value in ")]}":
            depth -= 1
            while ctor_stack and ctor_stack[-1][1] >= depth:
                ctor_stack.pop()
        in_query = _inside(query_ranges, base + tok.start)
        if in_query and kind in ("KEYWORD", "IDENT"):
            phrase = _query_phrase_at(toks, index)
            if phrase is not None:
                length, words = phrase
                for offset, word in enumerate(words):
                    target = toks[index + offset]
                    if target.value != word:
                        edits.append((base + target.start, base + target.end, word))
                skip_until = index + length
        if index < skip_until:
            prev_dot = kind == "OP" and tok.value == "."
            if kind in ("IDENT", "KEYWORD"):
                prev_ident = tok.value
            continue
        if kind == "KEYWORD" and index not in resource_tokens:
            replacement = None
            if in_query:
                replacement = platform_map.query_keyword_english(tok.value)
            if replacement is None:
                replacement = platform_map.keyword_english().get(tok.value)
            if replacement and replacement != tok.value:
                edits.append((base + tok.start, base + tok.end, replacement))
        elif kind == "IDENT" and index not in resource_tokens:
            field_of = struct_name if pending_field else ""
            pending_field = False
            if field_of:
                # Every field of one structure, whatever language its name is written in: a
                # word already English collides with a Russian one translated into it just
                # as two Russian ones collide with each other.
                translated, _plane = resolver.identifier(tok.value, scope=field_of)
                line, col = at if at is not None else (tok.line, tok.col)
                report.note_name(f"structure:{field_of}", tok.value, translated or tok.value,
                                 line, col)
            annotation_name = (
                index > 0 and toks[index - 1].kind == "OP" and toks[index - 1].value == "@"
            )
            if not tok.value.isascii() and annotation_name:
                _annotation_identifier_edit(tok, base, resolver, report, edits, at)
            elif not tok.value.isascii() and not in_query and type_ranges and _inside(type_ranges, base + tok.start):
                _type_identifier_edit(tok, base, prev_dot, resolver, report, edits, at)
            elif not tok.value.isascii():
                query_receiver = _query_reference_receiver(toks, index, query_aliases)
                scope = field_of or query_receiver or (prev_ident if prev_dot else root_scope)
                # The type of the receiver, when its declaration names one: the SECOND
                # namespace a member answers to. The receiver as written stays the first -
                # an entry qualified by the variable a project reads its json into was
                # written about that variable, and it must keep answering.
                type_scope = local_names.get(prev_ident, "") if prev_dot and not field_of else ""
                if prev_dot and not field_of and not type_scope and method_types is not None:
                    # A local declared more than once in the method is typed by the place.
                    type_scope = method_types.type_at(
                        prev_ident, base + tok.start if place is None else place)
                if not prev_dot and ctor_stack and _is_named_argument(toks, index):
                    scope = ctor_stack[-1][0]
                elif not prev_dot and tok.value in local_names and method_name:
                    # A LOCAL name lives in the namespace of its method: two words that share
                    # one English spelling collide only there, and only there may the project
                    # need a different word for one of them.
                    scope = method_name
                nxt = toks[index + 1] if index + 1 < len(toks) else None
                static_root = (
                    not prev_dot and nxt is not None and nxt.kind == "OP" and nxt.value == "."
                    and tok.value not in local_names and tok.value not in owner_names
                )
                platform_facet = (
                    _platform_facet(toks, index, local_names, owner_names, resolver)
                    if prev_dot and not in_query else None
                )
                member_of_code = prev_dot and not in_query and not field_of
                facet_value = (
                    _platform_facet_value(toks, index, local_names, owner_names, resolver)
                    if member_of_code else None
                )
                # The owner a chain holds, where no declaration names the receiver's type:
                # `Объект.Товары.Граница()` asks the array of rows, not the flat dictionary.
                # Only a word some platform type declares as a member can be answered by an
                # owner, so the walk is spared for the project's own words.
                chain_owner = ""
                if (chains is not None and member_of_code and not type_scope
                        and chain_root not in _COMPONENT_ROOTS
                        and platform_map.is_member_name(tok.value)):
                    typed = chains.receiver(toks, index, local_names, method_types,
                                            base + tok.start if place is None else place,
                                            chain_names)
                    if typed and resolver.platform_type(typed):
                        chain_owner = typed
                manager_kind = (
                    _manager_kind(toks, index, local_names, owner_names, resolver)
                    if member_of_code else ""
                )
                _identifier_edit(tok, base, in_query, prev_dot or bool(query_receiver),
                                 resolver, report, edits, at,
                                 scope=scope, type_scope=type_scope, static_root=static_root,
                                 chain_root=_member_chain_root(toks, index, chain_root, form_nodes,
                                                               resolver),
                                 receiver_is_local=prev_dot and prev_ident in local_names,
                                 reference="query" if query_receiver else _reference_reading(
                                     toks, index, prev_dot, type_scope, chain_root,
                                     resolver.project_names),
                                 platform_facet=platform_facet, facet_value=facet_value,
                                 chain_owner=chain_owner, manager_kind=manager_kind)
        elif kind == "NUMBER":
            _duration_edit(tok, base, edits)
        elif kind == "PATTERN":
            # A pattern literal is a program of another language and nothing here reads it as
            # text - except the names of its named groups, which the code reads back by name.
            _named_group_edits(tok, base, resolver, report, edits, at)
        elif kind == "COMMENT":
            _comment_edits(tok, base, resolver, report, edits)
        elif kind == "STRING":
            _string_edits(tok, base, resolver, report, edits, at,
                          data=not in_query and not _inside(resolvable, tok.start),
                          group_argument=is_group_argument(toks, index),
                          method=MethodScope(method_name, local_names, method_types,
                                             base + tok.start if place is None else place,
                                             owner_names, chains, chain_names))
        if kind in ("IDENT", "KEYWORD"):
            if not prev_dot:
                chain_root = tok.value
            prev_ident = tok.value
        elif not (kind == "OP" and tok.value == "."):
            prev_ident = ""
            chain_root = ""
        prev_dot = kind == "OP" and tok.value == "."
    return


#: The letter parts of a duration literal and their English spellings. The Russian set is
#: the platform documentation of the Duration type (`[д][ч][м][с][мс]`); the English set is
#: confirmed by the platform compiler (a probe build accepts `2d14h30m5s6ms`).
_DURATION_SUFFIXES = {"д": "d", "ч": "h", "м": "m", "с": "s", "мс": "ms"}

_NUMBER_PARTS_RE = re.compile(r"([0-9]+)([^0-9]+)")


def _duration_edit(tok, base, edits) -> None:
    """Spell the suffixes of a duration literal in English (`300мс` -> `300ms`).

    Only a literal whose EVERY letter part is a duration suffix moves: a number glued to
    any other letters (a data-size value, a date-like tail) is left as written - the pass
    must never guess at what it cannot name.
    """
    value = tok.value
    if value.isascii():
        return
    parts = _NUMBER_PARTS_RE.findall(value)
    if not parts or any(letters not in _DURATION_SUFFIXES for _digits, letters in parts):
        return
    consumed = "".join(digits + letters for digits, letters in parts)
    if consumed != value:
        return
    replacement = "".join(digits + _DURATION_SUFFIXES[letters] for digits, letters in parts)
    edits.append((base + tok.start, base + tok.end, replacement))


def _is_named_argument(toks: list, index: int) -> bool:
    """Whether the token at `index` is the NAME of a named argument: `(Name = ...`.

    The name has to open an argument - it follows an opening parenthesis or a comma - and be
    followed by a single `=`. Anything else is an ordinary expression, where the word means
    what it means everywhere else.
    """
    nxt = toks[index + 1] if index + 1 < len(toks) else None
    if nxt is None or nxt.kind != "OP" or nxt.value != "=":
        return False
    prev = toks[index - 1] if index else None
    return prev is not None and prev.kind == "OP" and prev.value in ("(", ",")


def _next_ident(toks: list, index: int) -> str:
    """The identifier right after the token at `index`, or an empty string."""
    token = _next_ident_token(toks, index)
    return token.value if token is not None else ""


def _next_ident_token(toks: list, index: int):
    """The identifier token right after the token at `index`, or None - the place, not the word."""
    position = index + 1
    while position < len(toks):
        if toks[position].kind == "IDENT":
            return toks[position]
        if toks[position].kind != "KEYWORD":
            return None
        position += 1
    return None


def _method_locals(toks: list, start: int, project_names: frozenset[str] = frozenset(),
                   places: dict[str, tuple[int, int]] | None = None,
                   ) -> dict[str, str]:
    """{name: the type its declaration names} for the method that begins at `start`.

    `places`, when given, is filled with {name: (line, col)} of the DECLARATION of each name -
    the line a collision report sends the reader to, and the line to edit.

    Two things are read off one walk. The NAMES tell a local named after a platform type from
    the type itself. The TYPE opens the namespace a member is looked up in: `Root.Услуги`
    where `Root: JsonRoot` is a field of that structure, and one word may be spelled for that
    structure alone. A declaration with no type written down maps to an empty string - the
    name is known, the type is not, and the receiver then answers for itself as before - with
    one exception: a local that holds the LOAD of a reference to a project object holds the
    object facet of that object (see _loaded_facet), a type no declaration writes and the
    engine's inference cannot name, because the catalog knows the platform's facets alone.
    `project_names` tells such a facet from a namespace-qualified name (see _declared_type).

    The method ends at the `;` that closes it; a nested declaration inside it belongs to the
    same scope for this purpose - the variable of a `catch` section and the parameters of a
    lambda included. `Строка -> Строка.Длина()` reads the parameter, and a lambda often names
    its parameter after a platform type: left out of this table, the parameter took the
    dictionary's spelling where it is declared and the type's where it is read.
    """
    out: dict[str, str] = {}
    depth = 0
    index = start + 1
    # The parameters: everything between the parentheses of the signature.
    while index < len(toks):
        tok = toks[index]
        if tok.kind == "OP" and tok.value == "(":
            depth += 1
        elif tok.kind == "OP" and tok.value == ")":
            depth -= 1
            if depth == 0:
                index += 1
                break
        elif depth == 1 and tok.kind == "IDENT":
            prev = toks[index - 1]
            if prev.kind == "OP" and prev.value in ("(", ","):
                out[tok.value] = _declared_type(toks, index, project_names)
                if places is not None:
                    places.setdefault(tok.value, (tok.line, tok.col))
        index += 1
    # The body: declarations and loop variables, up to the closing `;` of the method.
    while index < len(toks):
        tok = toks[index]
        if tok.kind == "OP" and tok.value == ";" and toks[index - 1].kind != "OP":
            pass  # a statement separator - the method ends at a `;` on its own line
        if tok.kind == "KEYWORD" and tok.canonical in ("METHOD", "CONSTRUCTOR"):
            break
        if tok.kind == "KEYWORD" and tok.canonical in ("VAR", "VAL", "REQ", "USE", "FOR", "CATCH"):
            position = index + 1
            while position < len(toks) and toks[position].kind == "KEYWORD":
                position += 1
            if position < len(toks) and toks[position].kind == "IDENT":
                name = toks[position].value
                out[name] = (
                    _declared_type(toks, position, project_names)
                    or _loaded_facet(toks, position, out, project_names)
                )
                if places is not None:
                    places.setdefault(name, (toks[position].line, toks[position].col))
        if tok.kind == "OP" and tok.value == "->":
            for position in _lambda_parameters(toks, index):
                name = toks[position].value
                out[name] = _declared_type(toks, position, project_names)
                if places is not None:
                    places.setdefault(name, (toks[position].line, toks[position].col))
        index += 1
    return out


def _static_type_roots(toks: list, start: int, local_names: dict[str, str],
                       owner_names: frozenset[str], query_ranges: list[tuple[int, int]],
                       base: int, resolver: Resolver) -> list[tuple[str, str, int, int]]:
    """(name, the English spelling of its type, line, col) for every platform type the method
    that begins at `start` reads as the root of a static access (`Кодировка.Utf8`).

    The root is what the walk reads as a static root: a name opening a chain, followed by a
    dot, that is neither a name of the method nor a property the module's element puts in
    scope. A query block is left out - its roots are tables, not types. The type is the
    resolver's: a type the project declares under that name is not the platform's.
    """
    out: list[tuple[str, str, int, int]] = []
    for index in range(start + 1, len(toks)):
        tok = toks[index]
        if tok.kind == "KEYWORD" and tok.canonical in ("METHOD", "CONSTRUCTOR"):
            break
        if tok.kind != "IDENT" or tok.value.isascii():
            continue
        prev = toks[index - 1]
        nxt = toks[index + 1] if index + 1 < len(toks) else None
        if prev.kind == "OP" and prev.value == ".":
            continue
        if nxt is None or nxt.kind != "OP" or nxt.value != ".":
            continue
        if tok.value in local_names or tok.value in owner_names:
            continue
        if _inside(query_ranges, base + tok.start):
            continue
        spelling = resolver.platform_type(tok.value)
        if spelling:
            out.append((tok.value, spelling, tok.line, tok.col))
    return out


def _lambda_parameters(toks: list, arrow: int) -> list[int]:
    """The positions of the parameter names of the lambda whose `->` stands at `arrow`.

    A short lambda puts its one name right before the arrow (`Строка -> ...`); a parenthesized
    one lists them, each opening the list or following a comma and maybe carrying a type
    (`(Строка: Строка, Индекс) -> ...`).
    """
    if arrow == 0:
        return []
    before = toks[arrow - 1]
    if before.kind == "IDENT":
        return [arrow - 1]
    if before.kind != "OP" or before.value != ")":
        return []
    depth = 0
    position = arrow - 1
    while position >= 0:
        tok = toks[position]
        if tok.kind == "OP" and tok.value == ")":
            depth += 1
        elif tok.kind == "OP" and tok.value == "(":
            depth -= 1
            if depth == 0:
                break
        position -= 1
    out: list[int] = []
    depth = 0
    for inner in range(position, arrow - 1):
        tok = toks[inner]
        if tok.kind == "OP" and tok.value in "([{<":
            depth += 1
        elif tok.kind == "OP" and tok.value in ")]}>":
            depth -= 1
        elif depth == 1 and tok.kind == "IDENT":
            prev = toks[inner - 1]
            if prev.kind == "OP" and prev.value in ("(", ","):
                out.append(inner)
    return out


def _declared_type(toks: list, index: int, project_names: frozenset[str] = frozenset()) -> str:
    """The type named after `name:` at `index` - its LAST part, or "" when none is written.

    The last part is the type itself (`Seeding.JsonRoot` is the structure `JsonRoot`), and
    the parameters of a generic are not read: `Array<String>` is an Array, and what it holds
    says nothing about the name that follows a dot. A FACET of a project object keeps its
    owner (`Заявки.Ссылка`), the shape `_type_scope_of` gives an inferred one: the reference
    side of a project catalog is a facet of the project, not a bare platform word, and the
    reference member of such a receiver is spelled by the facet table, not by the property
    dictionary.
    """
    position = index + 1
    if position >= len(toks) or toks[position].kind != "OP" or toks[position].value != ":":
        return ""
    position += 1
    parts: list[str] = []
    while position < len(toks):
        tok = toks[position]
        if tok.kind == "IDENT":
            parts.append(tok.value)
            position += 1
            if (
                position < len(toks) and toks[position].kind == "OP"
                and toks[position].value == "."
            ):
                position += 1
                continue
        break
    if not parts:
        return ""
    return _project_facet(parts, project_names) or parts[-1]


def _project_facet(parts: list[str], project_names: frozenset[str]) -> str:
    """`Owner.Facet` when the name ends in a project object and a facet suffix, else ""."""
    if (
        len(parts) >= 2 and parts[-2] in project_names
        and platform_map.facet_suffix_english(parts[-1])
    ):
        return f"{parts[-2]}.{parts[-1]}"
    return ""


def _is_project_facet(type_scope: str, project_names: frozenset[str]) -> bool:
    """Whether a type scope names a facet of a project object - `Заявки.Ссылка` and kin."""
    owner, dot, suffix = type_scope.rpartition(".")
    return bool(dot) and bool(_project_facet([owner, suffix], project_names))


def _loaded_facet(toks: list, index: int, locals_so_far: dict[str, str],
                  project_names: frozenset[str]) -> str:
    """The object facet a local declared at `index` holds when its value is a LOAD.

    `знч Объект = Найденная.ЗагрузитьОбъект()!` where `Найденная` is a local typed by the
    reference facet of a project object: the platform's entity protocol answers the object
    facet of the same object for that call - the type catalog spells the load of a catalog
    reference as `Справочник.Ссылка.ЗагрузитьОбъект(): Справочник.Объект?` - and the
    project's facets follow the same protocol. Only that one shape is read - the receiver a
    local this method already typed, the call one the reference facets alone declare (see
    platform_map.reference_only_members); anything else keeps the empty type, as before.
    """
    position = index + 1
    if position >= len(toks) or toks[position].kind != "OP" or toks[position].value != "=":
        return ""
    position += 1
    if position >= len(toks) or toks[position].kind != "IDENT":
        return ""
    receiver = locals_so_far.get(toks[position].value, "")
    owner, dot, suffix = receiver.rpartition(".")
    if not dot or suffix != platform_map.REFERENCE_FACET or not _is_project_facet(receiver, project_names):
        return ""
    if not _load_follows(toks, position):
        return ""
    return f"{owner}.{platform_map.OBJECT_FACET}"


def _load_follows(toks: list, index: int) -> bool:
    """Whether the token at `index` is followed by a call of a member only a reference has.

    `X.ЗагрузитьОбъект(` right after the token, an unwrap or a null-safe mark in between
    allowed (`X!.ЗагрузитьОбъект(`, `X?.ЗагрузитьОбъект(`): the load of the record behind a
    reference, which no other type of the catalog declares.
    """
    position = index + 1
    if position < len(toks) and toks[position].kind == "OP" and toks[position].value in ("!", "?"):
        position += 1
    if position >= len(toks) or toks[position].kind != "OP" or toks[position].value != ".":
        return False
    position += 1
    if position >= len(toks) or toks[position].kind != "IDENT":
        return False
    if toks[position].value not in platform_map.reference_only_members():
        return False
    position += 1
    return position < len(toks) and toks[position].kind == "OP" and toks[position].value == "("


#: The chain roots that address the components of a form: a member there is a property of the
#: component, spelled by the ui vocabulary, whatever its name means elsewhere.
_COMPONENT_ROOTS = ("Компоненты", "Components")


def _query_reference_receiver(toks: list, index: int, aliases: frozenset[str]) -> str:
    """The direct query alias owning this reference field, ignoring comment trivia."""
    if not aliases or toks[index].value != platform_map.REFERENCE_FACET:
        return ""
    previous = []
    for position in range(index - 1, -1, -1):
        token = toks[position]
        if token.kind in ("COMMENT", "NEWLINE"):
            continue
        previous.append(token)
        if len(previous) == 3:
            break
    if len(previous) < 2 or previous[0].value != ".":
        return ""
    receiver = previous[1]
    if receiver.kind != "IDENT" or receiver.value not in aliases:
        return ""
    if len(previous) == 3 and previous[2].value in (".", "?.", "::"):
        return ""
    return receiver.value


def _reference_reading(toks: list, index: int, after_dot: bool, type_scope: str,
                       chain_root: str, project_names: frozenset[str]) -> str:
    """How the receiver tells the reference member at `index` from the link property.

    The reference member after a dot is two different words: the REFERENCE of the record
    behind a facet of a project object (`Строка.Ссылка.ЗагрузитьОбъект()`, `Объект.Ссылка`),
    which the facet table spells `Reference`, and the PROPERTY of a label, a picture, a
    favorites item or an open-by-link event - a hyperlink, spelled `Link` by the property
    dictionary. The flat compiler dictionary knows the property alone, so a receiver holding
    a project facet came out with a member no reference has, and the build refused it.

    The receiver decides. "facet": one typed by a facet of a project object - declared,
    inferred, or loaded from a reference (see _loaded_facet) - carries the facet word.
    "load": one of no known type carries it only when the chain goes on to load the record -
    `LoadObject` is a member the reference facets alone declare, so the word before it
    is a reference whatever the receiver. Everything else answers "" and keeps the flat
    reading, `Link`: a hyperlink is reached through an untyped local too, and a member
    standing alone - returned, compared, passed - tells the two apart by nothing the tokens
    carry. Where the dictionary stands in each case is Resolver.identifier's business. A
    chain rooted at the components of a form is not judged here at all - there the ui
    vocabulary answers. A receiver typed by a platform type is not judged here either: its
    own member table answers before this reading (`Событие.Ссылка` of an open-by-link event
    is `Link` by the table of that event).
    """
    tok = toks[index]
    if not after_dot or tok.value != platform_map.REFERENCE_FACET or chain_root in _COMPONENT_ROOTS:
        return ""
    if _is_project_facet(type_scope, project_names):
        return "facet"
    if not type_scope and _load_follows(toks, index):
        return "load"
    return ""


@dataclasses.dataclass
class MethodTypes:
    """The inferred types of one method's locals, for the declarations that write none.

    `plain` answers by name for a name the method declares once. A name declared more than
    once - in two loops, as a loop variable and later a local - is answered by PLACE: the
    platform scopes a declaration to its block, and `typeinfer.method_env` reads that rule
    when given the place. That reading walks the method again per question, so it is asked
    about such names only; everything else costs one walk per method. Types are reduced to
    their LAST part, the shape `_declared_type` keeps.
    """

    method: object
    returns: dict[str, typeinfer.Inferred]
    project_names: frozenset[str]
    plain: dict[str, str]
    repeated: frozenset[str]

    def type_at(self, name: str, offset: int) -> str:
        """The type of `name` as seen from `offset` in the module text, or "" when unknown."""
        known = self.plain.get(name)
        if known is not None:
            return known
        if name not in self.repeated:
            return ""
        env = typeinfer.method_env(self.method, returns=self.returns, at=offset)
        got = env.variables.get(name)
        return _type_scope_of(got, self.project_names) if got is not None else ""


@dataclasses.dataclass(frozen=True)
class MethodScope:
    """The method a code fragment stands in, as the walk over the module read it.

    A string interpolation is code of the method around the string: `"%{Надпись.Длина()}"`
    reads the local the method declared, even where a platform type carries the same name. The
    fragment is tokenized apart from the module, and on its own it knew nothing of the method -
    a local named like a type then read as a static call on the type, the platform pair came
    before the dictionary, and the declaration went out under the dictionary's word while the
    read inside the string took the type's: a variable nothing reads and a call of a member the
    type does not have. So the walk hands the fragment what it learned at the head of the
    method: the declared names with the types they hold (`local_names`, `types`), the method
    `name`, which qualifies a dictionary entry written for one method's local, and the names
    the element of the module puts in scope of the method (`owner_names`, see owner_scopes).

    `place` is where the string stands in the module text. A name declared twice in one method
    is typed by the block around its place, and an offset inside a fragment says nothing about
    that when the fragment is the text of a dictionary entry rather than a piece of the module.

    `chains` and `chain_names` are what types a chain whose receiver no declaration types (see
    ChainTypes). The fragment used to be walked without them, and the same expression came out
    two ways in one method: `Объект.Товары.Граница()` was Bound in the code and stayed Russian
    inside the quotes right below it.
    """

    name: str
    local_names: dict[str, str]
    types: MethodTypes | None
    place: int | None = None
    owner_names: frozenset[str] = frozenset()
    chains: ChainTypes | None = None
    chain_names: frozenset[str] = frozenset()


@lru_cache(maxsize=1)
def _annotation_forms() -> tuple[frozenset[str], frozenset[str]]:
    """Both spellings of the annotations that compile a method on the server and on the client."""
    server = frozenset(terms.key_forms("НаСервере"))
    return server, frozenset(terms.key_forms("НаКлиенте"))


dataset.register_reset(_annotation_forms.cache_clear)


@lru_cache(maxsize=1)
def _platform_annotation_names() -> frozenset[str]:
    """Both spellings of every catalog type derived from the platform Annotation type."""
    try:
        bases = (dataset.load_json("stdlib.json") or {}).get("bases") or {}
    except Exception:  # noqa: BLE001 - no data, no proven platform annotation
        return frozenset()
    annotation_bases = frozenset(terms.forms("Аннотация", "types"))
    out: set[str] = set()
    for name, ancestors in bases.items():
        if not isinstance(name, str) or not isinstance(ancestors, list):
            continue
        if annotation_bases.intersection(ancestors):
            out.add(name)
            out.update(terms.forms(name, "types"))
    return frozenset(out)


dataset.register_reset(_platform_annotation_names.cache_clear)


def owner_scopes(source: SourceFile, owner: ModuleOwner | None,
                 ) -> list[tuple[int, int, frozenset[str]]]:
    """[(start, end, names)] of the module's methods that see names of the module's element.

    Read off the parser's tree, which says what the tokens do not: whether a method is static
    (no instance, no names) and which side compiles it - a component method marked for the
    server alone sees the contextual properties only (see names.ModuleOwner). The methods of a
    local structure work on that structure and are not listed; neither is anything the parser
    gave up on - a method missing here keeps reading its names as it always did.
    """
    if owner is None or not owner.names:
        return []
    module, _errors = P.parse(source)
    server, client = _annotation_forms()
    out: list[tuple[int, int, frozenset[str]]] = []
    for member in module.members:
        if not isinstance(member, P.Method):
            continue
        marks = {annotation.name for annotation in member.annotations}
        names = owner.visible(static=member.is_static,
                              server_only=bool(marks & server) and not marks & client)
        if names:
            out.append((member.start, member.end, names))
    return out


def _owner_names_at(scopes: list[tuple[int, int, frozenset[str]]] | None, offset: int,
                    ) -> frozenset[str]:
    """The owner's names the method starting around `offset` sees; empty outside every scope."""
    for start, end, names in scopes or ():
        if start <= offset < end:
            return names
    return frozenset()


def _type_scope_of(inferred: typeinfer.Inferred, project_names: frozenset[str]) -> str:
    """The inferred type in the shape `local_names` keeps a written one.

    The last part of a namespace-qualified name - `Seeding.JsonRoot` is the structure
    `JsonRoot`, and the dictionary qualifies its entries by the structure - but the WHOLE of a
    facet of a project object: the object side of a catalog of the project is not the
    platform's `Object`, and read by its last part alone it would be.
    """
    head, dot, _tail = inferred.name.partition(".")
    if dot and head in project_names:
        return inferred.name
    return inferred.name.rsplit(".", 1)[-1]


def inferred_locals(source: SourceFile, project_names: frozenset[str] = frozenset(),
                    ) -> dict[str, MethodTypes]:
    """{method name: the inferred types of its locals} for one module.

    `_method_locals` reads the types a method WRITES. A local written without one is typed
    here by what it holds - the constructor, the cast, the literal, a call of a neighbouring
    method with a declared result - through the engine's own inference (typeinfer.py), and
    that type opens the namespace of a member exactly as a written one does: after
    `пер Индекс = новый Соответствие<...>()` the removal method of the local is a member of a
    map, spelled the way the map spells it, not the way the flat dictionary spells the word;
    after `знч Корень = Данные как КореньJson` an entry qualified by that structure answers
    for the fields read off the local. `project_names` tells a facet of a project object from
    a namespace-qualified name (see _type_scope_of).
    """
    module, _errors = P.parse(source)
    methods = [member for member in module.members if isinstance(member, P.Method)]
    returns: dict[str, typeinfer.Inferred] = {}
    for method in methods:
        declared = typeinfer.nominal(getattr(method.return_type, "text", None))
        if declared is not None:
            returns[method.name] = declared
    out: dict[str, MethodTypes] = {}
    for method in methods:
        env = typeinfer.method_env(method, returns=returns)
        times = Counter(_declared_names(method))
        repeated = frozenset(name for name, count in times.items() if count > 1)
        plain = {
            name: _type_scope_of(got, project_names)
            for name, got in env.variables.items() if name not in repeated
        }
        if plain or repeated:
            out[method.name] = MethodTypes(method, returns, project_names, plain, repeated)
    return out


def type_ranges(source: SourceFile) -> list[tuple[int, int]]:
    """[start, end) offsets of every TYPE expression of the module, as the parser read them.

    A parameter, a declaration, a return type, a structure field, a constructor, a cast, a
    type argument of a call or a literal: the parser keeps each as a TypeRef with its span,
    and a name inside such a span is resolved as a type, not as a member. Where the parser
    gave up on a file the list is what it managed to read - the rest keeps the member
    reading, as it always had.
    """
    cached = source.cache.get("type_ranges")
    if cached is not None:
        return cached
    module, _errors = P.parse(source)
    ranges: list[tuple[int, int]] = []

    def walk(node: object) -> None:
        if isinstance(node, (list, tuple)):
            for item in node:
                walk(item)
            return
        if not isinstance(node, P.Node):
            return
        if isinstance(node, P.TypeRef):
            if node.end > node.start:
                ranges.append((node.start, node.end))
            return
        for field in dataclasses.fields(node):
            walk(getattr(node, field.name, None))

    walk(module.members)
    ranges.sort()
    source.cache["type_ranges"] = ranges
    return ranges


def _declared_names(method: P.Method) -> list[str]:
    """Every name the method declares, once per declaration - parameters, locals, loop
    variables, lambda parameters - so that a name declared twice can be told apart."""
    names = [param.name for param in method.params or ()]

    def walk(node: object) -> None:
        if isinstance(node, (list, tuple)):
            for item in node:
                walk(item)
            return
        if not isinstance(node, P.Node):
            return
        if isinstance(node, P.VarDecl):
            names.append(node.name)
        elif isinstance(node, (P.ForEach, P.ForTo)):
            names.append(str(getattr(node, "var", "")))
        elif isinstance(node, P.Lambda):
            names.extend(param.name for param in node.params or ())
        for field in dataclasses.fields(node):
            walk(getattr(node, field.name, None))

    walk(method.body)
    return names


def _query_phrase_at(toks: list, index: int) -> tuple[int, tuple[str, ...]] | None:
    """(how many tokens, the English words) when a query phrase starts at `index`.

    The longest phrase wins: "СОЗДАТЬ ВРЕМЕННУЮ ТАБЛИЦУ" must not be read as "СОЗДАТЬ ИНДЕКС"
    plus something. A phrase is upper-case like any keyword of this language.
    """
    phrases = platform_map.query_phrases()
    if not phrases:
        return None
    for length in sorted({len(words) for words in phrases}, reverse=True):
        window = []
        for offset in range(length):
            position = index + offset
            if position >= len(toks) or toks[position].kind not in ("IDENT", "KEYWORD"):
                window = []
                break
            window.append(toks[position].value.upper())
        if not window:
            continue
        english = phrases.get(tuple(window))
        if english and len(english) == length:
            return length, english
    return None


def _member_by_owner(scope: str, type_scope: str, name: str) -> str | None:
    """The owner-scoped spelling of a member: the receiver as written, then its type."""
    return platform_map.member_of(scope, name) or platform_map.member_of(type_scope, name)


def _identifier_edit(tok, base, in_query, after_dot, resolver, report, edits, at=None,
                     scope: str = "", type_scope: str = "", static_root: bool = False,
                     chain_root: str = "", receiver_is_local: bool = False,
                     reference: str = "", platform_facet: str | None = None,
                     facet_value: str | None = None, chain_owner: str = "",
                     manager_kind: str = "") -> None:
    if reference == "query":
        # A table alias may itself match a UI root or a platform type name.
        receiver_is_local = True
        chain_root = ""
        reference = "facet"
    if in_query:
        keyword = platform_map.query_keyword_english(tok.value)
        if keyword:
            edits.append((base + tok.start, base + tok.end, keyword))
            return
    if after_dot and platform_facet:
        # `Сущность.Право.Чтение`: right after a platform type stands its FACET (see
        # _platform_facet), and the facet table spells it. The project gate does not hold
        # here: a project attribute spelled like the facet left it Russian after an English
        # entity, a type path neither language has, and every access check of the module
        # read an undefined variable.
        resolver.note_platform_win(tok.value, platform_facet)
        if platform_facet != tok.value:
            edits.append((base + tok.start, base + tok.end, platform_facet))
        return
    # The receiver as written is read as a platform TYPE only when it is not a local of the
    # method: a variable named like a type is the variable, and its members are those of ITS
    # type - declared or inferred - never the namesake's. A local holding a project object
    # and named after a component once took the component's spelling of a property. The
    # dictionary still sees the receiver as written: an entry qualified by the variable is
    # about that variable.
    owner = "" if receiver_is_local else scope
    # A local of a PROJECT type - a structure, an object of the project, one of its facets -
    # has the project's members, and the platform tables have nothing to say about them. For
    # every other receiver the checked spellings answer first, then the owner's own table. A
    # project type is a name the project declares and the platform does not know as a type:
    # a project also declares properties, and one spelled like the string type must not turn
    # every string into a project structure.
    head = type_scope.split(".", 1)[0] if type_scope else ""
    project_typed = (
        bool(head) and head in resolver.project_names and not platform_map.is_platform_type(head)
    )
    platform_member = None
    if after_dot and not project_typed:
        # The owner a chain holds answers before the receiver read as a type by its name. The
        # walk types the chain as a VALUE - from a local, or a name of the module the method
        # sees - so a root that is a static type gets no chain owner and keeps the reading by
        # name. The manager of a project element answers last: its receiver names no type.
        platform_member = (
            platform_map.verified_member(tok.value)
            or platform_map.member_of(chain_owner, tok.value)
            or _member_by_owner(owner, type_scope, tok.value)
            or platform_map.manager_member_of(manager_kind, tok.value)
        )
    replacement: str | None
    if after_dot and facet_value:
        # `Сущность.Право.Чтение`: a value of a facet of a platform type, spelled by the table of
        # the whole facet (see _platform_facet_value). Like the facet, it is the platform's word
        # whatever the project calls its own things.
        replacement, plane = facet_value, "platform"
        resolver.note_platform_win(tok.value, facet_value)
    elif after_dot and scope in resolver.dictionary_scopes:
        replacement, plane = resolver.dictionary_key(tok.value, scope)
    elif platform_member:
        # The receiver is a platform TYPE - named right before the dot, or the type a local
        # was declared as or inferred to hold: its own vocabulary wins over the flat one,
        # which keeps a single spelling for a word two types spell apart.
        replacement, plane = platform_member, "platform"
        entry = resolver.dictionary.token(tok.value, scope, type_scope)
        if entry is not None and entry == platform_member:
            # The entry says exactly what the platform says: it did nothing here, and if it
            # does nothing anywhere else either, it is a workaround masking whatever the
            # platform data would have answered on its own - see Resolver.note_platform_win.
            resolver.note_platform_win(tok.value, platform_member)
        elif entry is not None and entry != platform_member \
                and entry not in platform_map.member_spellings(tok.value):
            # The project dictionary spells this member as the platform spells it NOWHERE.
            # Here the platform wins and the tree is right; but a receiver whose type nothing
            # names gets the entry's word, and the compiler refuses it there - a real project
            # lost its English build to exactly this, twice. So the entry is reported as the
            # defect it is, with the place that proves the contradiction. An entry that
            # matches the spelling of ANOTHER owner of the same word (a word the platform
            # spells two ways) is not judged: there is no one spelling to ask for.
            line, col = at if at is not None else (tok.line, tok.col)
            report.note_shadow(tok.value, line, col, entry, platform_member, type_scope or owner)
    elif after_dot and platform_map.enum_value_of(owner, tok.value):
        # `InformationConnotation.Normal` - a value belongs to ITS enumeration: globally one
        # Russian word answers to several English ones, and the flat dictionary hands out
        # whichever came last (the compiler then refuses the item).
        replacement, plane = platform_map.enum_value_of(owner, tok.value), "platform"
        resolver.note_platform_win(tok.value, replacement)
    elif after_dot and chain_root in ("Компоненты", "Components"):
        # After `Components.` stands either a NODE of this form - a name the project gave -
        # or a built-in member of a component. The project's own name wins; for the rest the
        # ui vocabulary answers, because the general dictionary spells the built-in command
        # of a table the way a COLLECTION spells it, and the build refuses that.
        # The ui vocabulary answers FIRST here: a built-in command of a component keeps its
        # own spelling even when the project also declares a method of that name elsewhere
        # (the dictionary is global, this receiver is not). A name the ui does not know is
        # a node of the form, and that is the project's.
        component = (
            None if tok.value in resolver.component_names
            else platform_map.component_member_english(tok.value)
        )
        if component:
            replacement, plane = component, "platform"
            resolver.note_platform_win(tok.value, component)
        else:
            replacement, plane = resolver.identifier(
                tok.value, after_dot=True, scope=scope, type_scope=type_scope,
            )
    else:
        replacement, plane = resolver.identifier(
            tok.value, after_dot=after_dot, scope=scope, type_scope=type_scope,
            static_root=static_root, reference=reference,
        )
    if plane == "user":
        report.user_done += 1
    elif plane == "platform":
        report.note_platform_answer(tok.value, tok.line, tok.col)
    elif plane == PLATFORM_TYPE:
        report.note_platform_type_answer(tok.value, tok.line, tok.col)
    if replacement:
        if replacement != tok.value:
            edits.append((base + tok.start, base + tok.end, replacement))
        return
    if plane in ("missing", "platform-gap"):
        line, col = at if at is not None else (tok.line, tok.col)
        report.note_missing(tok.value, line, col, plane)


def _platform_facet(toks: list, index: int, local_names: dict[str, str],
                    owner_names: frozenset[str], resolver: Resolver) -> str | None:
    """The English facet word at `index` when a platform type stands right before the dot.

    `Сущность.Право` names the privilege facet of the generic entity, the way `Задачи.Ссылка`
    names a facet in a type expression. The owner has to open the chain and to BE the type:
    a local, or a property of the module's element, spelled like the entity is that name, and
    the word after it is its member; so is a type the project declares under the same name.
    Anything else answers None and keeps the member reading.
    """
    if index < 2:
        return None
    dot, owner = toks[index - 1], toks[index - 2]
    if dot.kind != "OP" or dot.value != "." or owner.kind != "IDENT":
        return None
    before = toks[index - 3] if index >= 3 else None
    if before is not None and before.kind == "OP" and before.value == ".":
        return None
    if owner.value in local_names or owner.value in owner_names:
        return None
    if not resolver.platform_type(owner.value):
        return None
    return platform_map.facet_of(owner.value, toks[index].value)


def _platform_facet_value(toks: list, index: int, local_names: dict[str, str],
                          owner_names: frozenset[str], resolver: Resolver) -> str | None:
    """The English spelling of the facet value at `index` - `Сущность.Право.Чтение` - or None.

    The two names before it pass the test of a facet (see _platform_facet): the root opens the
    chain and is the platform type, not a local, a property of the module's element or a type
    the project declares under that name. The value is then read by the table of the whole
    facet; a value the table does not list, or data extracted before the table existed, answers
    None, and the word is read the way it was.
    """
    if index < 4 or toks[index - 1].kind != "OP" or toks[index - 1].value != ".":
        return None
    if toks[index - 2].kind != "IDENT":
        return None
    if _platform_facet(toks, index - 2, local_names, owner_names, resolver) is None:
        return None
    return platform_map.facet_value_of(toks[index - 4].value, toks[index - 2].value,
                                       toks[index].value)


def _manager_kind(toks: list, index: int, local_names: dict[str, str],
                  owner_names: frozenset[str], resolver: Resolver) -> str:
    """The kind of the project element whose manager the member at `index` is called on, or "".

    `ПравоНаОтчеты.Проверить()`: the receiver opens the chain, the project index knows an
    element of that name, and nothing of the method shadows it - a local or a parameter, a
    property of the module's element. A method the element's own module declares under the same
    name is the project's, not the manager's. A name qualified by a namespace may name an
    element of another project, and is left alone.
    """
    project = resolver.project_index
    if project is None or index < 2:
        return ""
    dot, receiver = toks[index - 1], toks[index - 2]
    if dot.kind != "OP" or dot.value != "." or receiver.kind != "IDENT":
        return ""
    before = toks[index - 3] if index >= 3 else None
    if before is not None and before.kind == "OP" and before.value in (".", "?.", "::", "!"):
        return ""
    if receiver.value in local_names or receiver.value in owner_names:
        return ""
    kind = project.element_kind(receiver.value)
    if not kind or project.declares_method(receiver.value, toks[index].value):
        return ""
    return kind


def _member_chain_root(toks: list, index: int, chain_root: str,
                       form_nodes: dict[str, str] | None, resolver: Resolver) -> str:
    """The root the member at `index` is judged by: `chain_root`, or none for a method of the
    project reached through a node of the form.

    After `Компоненты.<Node>.` the ui vocabulary answers, because a built-in command of a
    platform component keeps its own spelling. A node whose component is the PROJECT's and
    declares the method (see names.component_methods) is the other case: the call names the
    project's method, and the ui vocabulary's command of the same spelling is not what it calls
    - a component of the project declared a method spelled like the refresh command, and the
    call went out as `Refresh` while the declaration waited for a dictionary entry. Such a
    member is read as a name after a dot like any other, which is the gate of the project's own
    names. Only a member of the node itself is judged, one step past the node: a deeper chain
    reads the value of that member.
    """
    if not form_nodes or index < 4 or chain_root not in _COMPONENT_ROOTS:
        return chain_root
    dot, node, root_dot, root = toks[index - 1], toks[index - 2], toks[index - 3], toks[index - 4]
    if not (dot.kind == "OP" and dot.value == "." and node.kind == "IDENT"
            and root_dot.kind == "OP" and root_dot.value == "."
            and root.kind == "IDENT" and root.value in _COMPONENT_ROOTS):
        return chain_root
    before = toks[index - 5] if index >= 5 else None
    if before is not None and before.kind == "OP" and before.value == ".":
        return chain_root
    methods = resolver.component_methods.get(form_nodes.get(node.value, ""), frozenset())
    return "" if toks[index].value in methods else chain_root


def _type_identifier_edit(tok, base, after_dot, resolver, report, edits, at=None) -> None:
    """A name inside a TYPE expression of the code, resolved the way a yaml type is.

    After a dot there stands a facet, and the facet is the platform's word: `Задачи.Ссылка`
    is `Tasks.Reference`. The member reading of the same token gave `Link` - the spelling of
    the property - and a parameter typed by a reference did not compile.
    """
    replacement, plane = resolver.type_name(tok.value, after_dot=after_dot)
    if plane == "user":
        report.user_done += 1
    elif plane == "platform":
        report.note_platform_answer(tok.value, tok.line, tok.col)
    elif plane == PLATFORM_TYPE:
        report.note_platform_type_answer(tok.value, tok.line, tok.col)
    if replacement:
        if replacement != tok.value:
            edits.append((base + tok.start, base + tok.end, replacement))
        return
    line, col = at if at is not None else (tok.line, tok.col)
    report.note_missing(tok.value, line, col, plane)


def _annotation_identifier_edit(tok, base, resolver, report, edits, at=None) -> None:
    """Resolve a name after `@` through the platform annotation namespace first."""
    replacement, plane = resolver.annotation_name(tok.value)
    if plane == "user":
        report.user_done += 1
    elif plane == PLATFORM_TYPE:
        report.note_platform_type_answer(tok.value, tok.line, tok.col)
    if replacement:
        if replacement != tok.value:
            edits.append((base + tok.start, base + tok.end, replacement))
        return
    line, col = at if at is not None else (tok.line, tok.col)
    report.note_missing(tok.value, line, col, plane)


def _inside(ranges: list[tuple[int, int]], offset: int) -> bool:
    return any(start <= offset < end for start, end in ranges)


def _resolvable_ranges(toks: list) -> list[tuple[int, int]]:
    """[start, end) of every resolvable literal body: `Ресурс{...}`, `Образец{...}` and kin.

    The body of such a literal is opaque to the language around it - the platform reads it as a
    resource path, a regular expression, a query - so a string standing there is not the data
    the literals plane speaks about. The brace has to TOUCH the name, which is exactly what
    tells a resolvable literal from a block that happens to follow a word.
    """
    out: list[tuple[int, int]] = []
    for index, tok in enumerate(toks):
        if tok.kind not in ("IDENT", "KEYWORD"):
            continue
        nxt = toks[index + 1] if index + 1 < len(toks) else None
        if nxt is None or nxt.kind != "OP" or nxt.value != "{" or nxt.start != tok.end:
            continue
        depth = 0
        for close in toks[index + 1:]:
            if close.kind != "OP":
                continue
            if close.value == "{":
                depth += 1
            elif close.value == "}":
                depth -= 1
                if depth == 0:
                    out.append((nxt.start, close.end))
                    break
    return out


# --- comments ---------------------------------------------------------------------------

#: The text of one physical comment line: the marker, the payload, the trailing decoration.
_LINE_COMMENT_RE = re.compile(r"^(/{2,}\s*)(.*?)(\s*)$")
_BLOCK_FIRST_RE = re.compile(r"^(/\*+\s*)(.*?)(\s*(?:\*+/)?\s*)$")
_BLOCK_LINE_RE = re.compile(r"^(\s*\*?\s*)(.*?)(\s*(?:\*+/)?\s*)$")


def comment_lines(text: str, first: re.Pattern, rest: re.Pattern
                  ) -> list[tuple[int, int, str]]:
    """(offset inside `text`, the line index, the payload) for the text of ONE comment.

    The payload is the text a `phrases` entry is keyed by - the marker and the decoration
    around it taken off. The two patterns say how the lines of this comment are written: the
    opening one carries the marker, the ones after it carry whatever decoration the shape
    uses. A comment of a resource file is read by the same function with its own pair, so
    one phrase key means the same thing in a module and in a stylesheet.
    """
    out: list[tuple[int, int, str]] = []
    offset = 0
    for index, line in enumerate(text.splitlines(keepends=True)):
        body = line.rstrip("\r\n")
        match = (first if index == 0 else rest).match(body)
        if match:
            out.append((offset + match.start(2), index, match.group(2)))
        offset += len(line)
    return out


def comment_payloads(tok) -> list[tuple[int, int, str]]:
    """The payloads of one comment TOKEN, read by the shape the lexer gave it.

    Shared rather than private, because a SECOND reading of the same thing is what the
    orphan pass needs, and two readings drift: an imitation that took one space off a `//`
    line answered a doc comment (`///`) with a slash glued to the text, and every pair
    written from such a comment would then have read as an orphan.
    """
    if tok.subkind == "line":
        return comment_lines(tok.value, _LINE_COMMENT_RE, _LINE_COMMENT_RE)
    return comment_lines(tok.value, _BLOCK_FIRST_RE, _BLOCK_LINE_RE)


def _comment_edits(tok, base, resolver, report, edits) -> None:
    if not has_cyrillic(tok.value):
        return
    for offset, index, payload in comment_payloads(tok):
        if not has_cyrillic(payload):
            continue
        start = base + tok.start + offset
        translated = resolver.dictionary.phrase(payload)
        if translated is not None:
            report.phrases_done += 1
            if translated != payload:
                edits.append((start, start + len(payload), translated))
        else:
            report.note_phrase(payload, tok.line + index, tok.col if index == 0 else 1)


# --- strings ----------------------------------------------------------------------------


#: A named group of a regular expression: a name of the PROJECT, written inside a pattern.
_NAMED_GROUP_RE = re.compile(r"\(\?<([^\W\d][\w]*)>")


@lru_cache(maxsize=1)
def _group_call_forms() -> frozenset[str]:
    """Both spellings of the method whose string argument is a group NAME, not a text."""
    return frozenset(terms.key_forms("Группа"))


def is_group_argument(toks: list, index: int) -> bool:
    """Whether the string at `index` is the first argument of `<match>.Group(...)`."""
    if index < 3:
        return False
    opening, method, dot = toks[index - 1], toks[index - 2], toks[index - 3]
    return (
        opening.kind == "OP" and opening.value == "("
        and method.kind in ("IDENT", "KEYWORD") and method.value in _group_call_forms()
        and dot.kind == "OP" and dot.value == "."
    )


def _name_edit(text: str, start: int, resolver, report, edits, at) -> None:
    """Translate one NAME standing inside a literal, reporting it when nothing names it.

    The literals plane is asked FIRST, and that is not a stray: a project that already spells
    a pattern by hand named its group there, and the two sides of a group name have to answer
    alike or the call asks for a group the pattern never declared. One order for both sides is
    what keeps them together - which spelling wins matters less than that one wins for both.
    """
    named = resolver.dictionary.literal(text)
    if named is not None:
        report.note_literal_named(text)
        if named != text:
            edits.append((start, start + len(text), named))
        return
    replacement, plane = resolver.identifier(text)
    if plane == "user":
        report.user_done += 1
    if replacement:
        if replacement != text:
            edits.append((start, start + len(text), replacement))
        return
    line, col = at
    report.note_token(text, line, col)


def group_names(text: str) -> list[tuple[int, str]]:
    """(offset inside `text`, name) of every named group a pattern written in `text` declares.

    Shared by the pass, which renames the groups in place, and by the orphan reading, which
    needs the very same names: the pass asks the literals plane about each of them.
    """
    return [(match.start(1), match.group(1)) for match in _NAMED_GROUP_RE.finditer(text)]


def _named_group_edits(tok, base, resolver, report, edits, at=None) -> None:
    """Translate the names of the named groups declared inside a pattern literal.

    A group name is read back by that name (`Match.Group("Name")`), and the two sides used to
    move apart: the call is a string the literals plane could name, the declaration inside the
    pattern nothing looked at. The tree then went out with a pattern declaring one name and a
    call asking for another, and the platform answered "no capture group with that name".
    Both sides are resolved by the SAME map now, so one entry moves them together.
    """
    position = at if at is not None else (tok.line, tok.col)
    for offset, name in group_names(tok.value):
        if name.isascii():
            continue
        _name_edit(name, base + tok.start + offset, resolver, report, edits, position)


def _string_edits(tok, base, resolver, report, edits, at=None, *, data: bool = True,
                  group_argument: bool = False, method: MethodScope | None = None) -> None:
    """The edits of one string literal; `method` is the method it stands in (see MethodScope)."""
    value = tok.value
    if group_argument:
        # The argument of Group() is a NAME, not prose: the literals plane must not answer for
        # it, or the call would take a spelling the pattern never got.
        body = _body_of(tok)
        if body is not None and not body.isascii():
            _name_edit(body, base + tok.start + 1, resolver, report, edits,
                       at if at is not None else (tok.line, tok.col))
        return
    if data and _literal_edit(tok, base, resolver, report, edits, at, method=method):
        # The whole literal is gone, and with it every span inside it - a group name included:
        # an entry that names a pattern spells its groups the way it wants them.
        return
    spans, shorts = _interpolations(value)
    for start, end in spans:
        inner = value[start:end]
        inner_tokens = lexer.tokenize(inner)
        collect_token_edits(inner, inner_tokens, base + tok.start + start, [], resolver, report,
                            edits, at=at or (tok.line, tok.col), method=method)
    for start, name in shorts:
        _short_name_edit(name, base + tok.start + start, resolver, report, edits,
                         at if at is not None else (tok.line, tok.col), method)
    _named_group_edits(tok, base, resolver, report, edits, at)
    if _resource_path_edits(tok, base, resolver, report, edits, at):
        # A picture of the platform's library, named whole by the library: nothing in the
        # literal is left for a person to name.
        return
    if has_cyrillic(value):
        bare = value.strip('"')
        if "{" not in bare and resolver.dictionary.token(bare) is not None:
            report.warnings.append(("string-equals-token", tok.line, tok.col, bare))
    _literal_left(tok, report, at, data=data)


def _body_of(tok) -> str | None:
    """The text between the quotes, or None when the token is not a closed string.

    An unterminated literal has no known end, and a replacement spanning it would eat the
    code that follows.
    """
    value = tok.value
    if len(value) < 2 or not value.startswith('"') or not value.endswith('"'):
        return None
    return value[1:-1]


def literal_keys(toks: list) -> set[str]:
    """Every text the literals plane may be asked about by a token list, nested strings included.

    The orphan pass counts a literal entry as live when its key is here, so the set has to
    cover every question the translating pass asks: the body of a string (`_body_of`), the
    names of the groups a string or a pattern declares (`group_names`), and the same for every
    string that stands inside an interpolation of another one, at any depth
    (`interpolated_literal_keys`). A regular expression over the raw text cannot find the inner
    strings: in `"%{Match.Group("Name")}"` the first inner quote closes the outer string for it.

    Every string is read, including those the pass leaves alone: a string of a query or of a
    resolvable literal, a name already in Latin, the inner strings of a literal the plane names
    whole. An extra key only keeps an entry in place, while a missed one offers a live entry for
    removal. The translations of named literals are questions too, and they live in the
    dictionary rather than in the sources, so the orphan pass reads their interpolations with
    `interpolated_literal_keys` on its own.
    """
    out: set[str] = set()
    for tok in toks:
        if tok.kind == "STRING":
            body = _body_of(tok)
            if body is not None:
                out.add(body)
            out |= interpolated_literal_keys(tok.value)
        elif tok.kind != "PATTERN":
            continue
        out.update(name for _offset, name in group_names(tok.value))
    return out


def interpolated_literal_keys(text: str) -> set[str]:
    """The texts the literals plane may be asked about by the strings inside the interpolations
    of `text` - a string token as written, or a yaml template. They are read the way the pass
    reads them: `_interpolations` finds the expressions, and the lexer reads each of them."""
    out: set[str] = set()
    for start, end in _interpolations(text)[0]:
        out |= literal_keys(lexer.tokenize(text[start:end]))
    return out


def _literal_edit(tok, base, resolver, report, edits, at=None, *,
                  method: MethodScope | None = None) -> bool:
    """Replace the WHOLE literal when the literals plane names it; True when it did.

    The key is the text between the quotes exactly as the source writes it - interpolations
    and escaping included - and so is the value: the person filling the dictionary writes the
    sentence they see, leaves the `%{...}` where it belongs and spells an inner quote `\\"`
    the one way the code already spells it. Nothing is escaped a second time here, and nothing
    needs to be: the dictionary refused on load any value that is not a literal body
    (`dictionary.literal_body_error`), so what arrives fits between two quotes as it stands.
    The code INSIDE the replacement is then translated by the ordinary interpolation pass, so
    an entry never has to spell out what the names inside it will be renamed to - in the method
    the literal stands in, the way the names of the key would have been.
    """
    body = _body_of(tok)
    if body is None:
        return False
    translated = resolver.dictionary.literal(body)
    if translated is None:
        return False
    report.note_literal_named(body)
    line, col = at if at is not None else (tok.line, tok.col)
    if translated != body and body in resolver.data_values \
            and not any(w[0] == "literal-data-value" and w[3] == body for w in report.warnings):
        # The literal doubles a VALUE of a json resource, and data is never translated: after
        # this replacement a comparison against that data goes silently dry (a seeding parse
        # loses every branch). If the literal really is data, give the entry a value equal to
        # its key - that keeps the coverage and the comparison alike. One note per text per
        # file: a wizard that checks its page code eight times is one place to look, not eight.
        report.warnings.append(("literal-data-value", line, col, body))
    replacement = translate_interpolations(translated, resolver, report, at=(line, col),
                                           method=method)
    check_placeholders(body, replacement, resolver, report, (line, col), method=method)
    if replacement != body:
        edits.append((base + tok.start + 1, base + tok.end - 1, replacement))
    return True


def placeholder_expressions(text: str) -> list[str]:
    """The substitutions of a literal, in order: the expression of every full-form
    interpolation with its whitespace collapsed, and every short-form name as it stands."""
    spans, shorts = _interpolations(text)
    out = [" ".join(text[start:end].split()) for start, end in spans]
    out.extend(name for _offset, name in shorts)
    return out


def check_placeholders(
    key: str, replacement: str, resolver: Resolver, report: FileReport, at: tuple[int, int],
    method: MethodScope | None = None,
) -> None:
    """A named literal must carry the substitutions of its key - translated or as written.

    The prose of an entry is a person's, the names inside `%{...}` are the code's: a template
    whose translation names `%{AccountCode}` while the field it stands for translates to
    `SubscriberCode` compiles nowhere (a variable of that name does not exist) or, in a
    presentation template, names a field the event does not have. The comparison is made on
    what the pass would WRITE for either side: the key's substitutions translated the ordinary
    way against the translation's after its own pass - so an entry may spell a name in either
    language, and only a name that ends up different is a mismatch. Order does not matter: a
    translation may put the substitutions where its grammar wants them. Both sides are read in
    the `method` the literal stands in, the one reading the pass gives the replacement.
    """
    if not any(sign in key or sign in replacement for sign in "%$"):
        return
    scratch = FileReport(path=report.path)  # the key's pass counts toward nothing
    expected = placeholder_expressions(
        translate_interpolations(key, resolver, scratch, at=at, method=method))
    found = placeholder_expressions(replacement)
    if sorted(expected) != sorted(found):
        report.note_placeholders(key, at[0], at[1], expected, found)


def prose_of(text: str) -> str:
    """The text with its interpolations blanked out - what a person actually reads in it.

    A template whose Cyrillic sits inside `%{...}` alone is already translated by the
    interpolation pass, and asking a person to name it would ask for nothing.
    """
    spans, shorts = _interpolations(text)
    masked = list(text)
    for start, end in spans:
        for position in range(start, min(end, len(masked))):
            masked[position] = " "
    for start, name in shorts:
        for position in range(start, min(start + len(name), len(masked))):
            masked[position] = " "
    return "".join(masked)


def _literal_left(tok, report, at=None, *, data: bool = True) -> None:
    """Report a Cyrillic literal the pass leaves in the source language.

    Two ways to leave one, and they are different facts. A literal the literals plane could
    name but does not is a GAP: an entry would move it, so the report asks for one. A literal
    standing inside a query or a resolvable literal is out of the plane's reach by design -
    there the text is a program of another language - so it is listed as data KEPT instead: a
    real project has hundreds of such blocks, the translator has to see them (invisible is the
    one thing they must not be), and no entry and no rule should ask anything of them.

    Only the PROSE counts either way. A literal whose Cyrillic sits inside its interpolations
    alone is a template the interpolation pass has already translated, and there is nothing in
    it left for a person to name; a resource path is likewise translated segment by segment,
    and its untranslated segments are reported as the names they are.
    """
    body = _body_of(tok)
    if body is None or not has_cyrillic(body):
        return
    if _looks_like_resource_path(body):
        return
    if not has_cyrillic(prose_of(tok.value)):
        return
    line, col = at if at is not None else (tok.line, tok.col)
    # A literal that spans lines cannot become an entry: a dictionary key is one line, and the
    # loader refuses a value carrying a break. Asking for an entry that cannot be written would
    # leave a gap open forever, so such a literal is listed as data kept instead.
    if data and "\n" not in body and "\r" not in body:
        report.note_literal(body, line, col)
    else:
        report.note_text_kept(body, line, col)


#: Suffixes that make a literal a resource path rather than a sentence.
_RESOURCE_SUFFIXES = frozenset(
    "svg png webp jpg jpeg gif ico json css html js txt md woff woff2 ttf eot mp4 pdf".split()
)

#: One segment of a path: a file name, possibly written as an interpolation.
_PATH_SEGMENT_RE = re.compile(r"^[%$]?\{?[\w][\w\-]*\}?(?:\.[A-Za-z0-9]+)?$", re.UNICODE)


def _looks_like_resource_path(bare: str) -> bool:
    """Does the text of a literal read as a path inside the resources?"""
    if not bare or " " in bare or "\n" in bare:
        return False
    last = re.split(r"[/\\]", bare)[-1]
    if "." not in last or last.rsplit(".", 1)[-1].lower() not in _RESOURCE_SUFFIXES:
        return False
    return all(_PATH_SEGMENT_RE.match(segment) for segment in re.split(r"[/\\]", bare))


def _resource_path_edits(tok, base, resolver, report, edits, at=None) -> bool:
    """Translate the name segments of a literal that spells a path inside the resources.

    A resource is addressed by its path, and the pass renames the files and directories of the
    tree - so a path left as data points at a name that no longer exists. Nothing says so: the
    platform raises "resource not found", the project catches it and shows an empty icon. The
    pilot found it that way, with 22 languages seeded and not one flag.

    Only a literal SHAPED like a path qualifies - it ends with a resource suffix and every
    segment reads as a file name - and inside it only the plain segments: a segment holding an
    interpolation is code and was already translated as code. The shape is what keeps a regular
    expression out: `"<a[^>]*>(?<Заголовок>.*?)</a>"` has slashes too, and its named groups are
    code the module reads by name, not files.

    A literal that names a picture of the platform's library whole - bare or by the subsystem
    of the library - takes the English name of the picture instead (Resolver.library_picture),
    the one the yaml and `Ресурс{...}` take; word by word the compiler dictionary spelled
    `Вход.svg` as `Enter.svg`, a picture the library does not have. True when it did.
    """
    value = tok.value
    if len(value) < 2 or not has_cyrillic(value):
        return False
    body = _body_of(tok)
    english = resolver.library_picture(body) if body is not None else None
    if english is not None:
        if english != body:
            edits.append((base + tok.start + 1, base + tok.end - 1, english))
        return True
    bare = value[1:-1]
    if not _looks_like_resource_path(bare):
        return False
    _resource_segment_edits(bare, base + tok.start + 1, resolver, report, edits,
                            at if at is not None else (tok.line, tok.col))
    return False


def _resource_segment_edits(path: str, start: int, resolver, report, edits,
                            at: tuple[int, int]) -> None:
    """The edits of the names in a path that addresses a resource, `path` standing at `start`.

    A segment is renamed the way the tree renames a part of a path: piece by piece between its
    dots, the extension left as it is. The segments up to the folder of resources, when the
    path spells it, name the structure of the project and go the way names go; everything below
    it is a file or a directory of the project's resources (Resolver.resource_name). A piece
    holding an interpolation is code, and the code was translated as code already.
    """
    segments = re.split(r"([/\\])", path)
    names_only = [segment for segment in segments if segment not in ("/", "\\")]
    last_dir = max((index for index, segment in enumerate(names_only) if segment in RESOURCE_DIRS),
                   default=-1)
    offset = 0
    position = -1
    for segment in segments:
        if segment in ("/", "\\"):
            offset += len(segment)
            continue
        position += 1
        # Below the folder a name is the project's when the project HAS such a file or folder
        # there; a picture of the platform's library keeps the reading it always had.
        resource = position > last_dir and (
            "/".join(names_only[last_dir + 1:position + 1]) in resolver.resource_keys
        )
        stem, dot, extension = segment.rpartition(".")
        if dot and extension.lower() in _RESOURCE_SUFFIXES:
            pieces = stem.split(".") + [extension]
        else:
            pieces = segment.split(".")
        piece_offset = offset
        for piece in pieces:
            if has_cyrillic(piece) and not (set("%${}") & set(piece)):
                if resource:
                    replacement, plane = resolver.resource_name(piece)
                else:
                    replacement, plane = resolver.identifier(piece)
                if plane == "user":
                    report.user_done += 1
                if replacement is None:
                    report.note_token(piece, *at, resource=resource)
                elif replacement != piece:
                    edits.append((start + piece_offset, start + piece_offset + len(piece),
                                  replacement))
            piece_offset += len(piece) + 1
        offset += len(segment)


def _resource_literal_edits(text: str, toks: list, base: int, resolver, report, edits,
                            at: tuple[int, int] | None) -> set[int]:
    """The edits of the paths inside `Ресурс{...}` literals; the indices of the tokens done.

    The body is read off the source text rather than glued back from tokens - a file name may
    hold characters the lexer splits (`adv-auto.svg`). A subsystem named before `::` is a name
    of the project's structure and is left to the walk; the path after it addresses the
    resources and is spelled here, the same way the file of the tree is. A picture of the
    platform's library is named whole, its subsystem included, by the English library
    (Resolver.library_picture).
    """
    done: set[int] = set()
    words = _resource_words()
    for index, tok in enumerate(toks):
        if tok.kind != "IDENT" or tok.value not in words or index + 1 >= len(toks):
            continue
        opener = toks[index + 1]
        if opener.kind != "OP" or opener.value != "{" or opener.start != tok.end:
            continue
        closer_index = next(
            (position for position in range(index + 2, len(toks))
             if toks[position].kind == "OP" and toks[position].value == "}"),
            None,
        )
        if closer_index is None or toks[closer_index].line != opener.line:
            continue
        body = text[opener.end:toks[closer_index].start]
        namespace_end = body.rfind("::")
        path_start = opener.end + (namespace_end + 2 if namespace_end >= 0 else 0)
        path = text[path_start:toks[closer_index].start]
        lead = len(path) - len(path.lstrip())
        path = path.strip()
        reference = body.strip()
        if not path or not has_cyrillic(reference):
            continue
        if path.replace("\\", "/") not in resolver.resource_keys:
            english = resolver.library_picture(reference)
            if english is not None:
                start = opener.end + len(body) - len(body.lstrip())
                if english != reference:
                    edits.append((base + start, base + start + len(reference), english))
                done.update(range(index + 2, closer_index))
            # Otherwise no file of the project and no picture of the library answers to the
            # path - a file the project does not have: the walk reads it the way it always did.
            continue
        if not has_cyrillic(path):
            continue
        place = at if at is not None else (opener.line, opener.col)
        _resource_segment_edits(path, base + path_start + lead, resolver, report, edits, place)
        done.update(position for position in range(index + 2, closer_index)
                    if toks[position].start >= path_start)
    return done


@lru_cache(maxsize=1)
def _resource_words() -> frozenset[str]:
    """Both spellings of the resource literal (`Ресурс{...}` and `Resource{...}`)."""
    return frozenset(terms.key_forms("Ресурс"))


dataset.register_reset(_resource_words.cache_clear)


_SHORT_NAME_RE = re.compile(r"[_\w][\w0-9]*", re.UNICODE)


def _interpolations(value: str) -> tuple[list[tuple[int, int]], list[tuple[int, str]]]:
    """The interpolations of a string token: full-form spans and short-form names.

    Full form (`%{...}` / `${...}`) holds an EXPRESSION and is returned as a span for
    re-tokenization; the balancing mirrors the lexer's - a nested string (with its own
    interpolations) and the braces of a collection literal live inside it. Short form
    (`%Имя` / `$Имя`, per the platform's interpolation docs) holds one NAME and is returned
    as (offset, name). An odd run of backslashes escapes the sign, and a sign followed by
    anything that cannot start an identifier is an ordinary character.
    """
    spans: list[tuple[int, int]] = []
    shorts: list[tuple[int, str]] = []
    i, n = 1 if value.startswith('"') else 0, len(value)
    while i < n:
        ch = value[i]
        if ch == "\\":
            i += 2
            continue
        if ch in "%$" and i + 1 < n:
            if value[i + 1] == "{":
                start = i + 2
                depth = 1
                j = start
                while j < n:
                    cj = value[j]
                    if cj == "\\":
                        j += 2
                        continue
                    if cj == '"':  # a nested string: skip to its closing quote
                        j += 1
                        while j < n and value[j] != '"':
                            j += 2 if value[j] == "\\" else 1
                        j += 1
                        continue
                    if cj == "{":
                        depth += 1
                    elif cj == "}":
                        depth -= 1
                        if depth == 0:
                            break
                    j += 1
                spans.append((start, min(j, n)))
                i = j + 1
                continue
            name = _SHORT_NAME_RE.match(value, i + 1)
            if name is not None and not name.group(0).isascii():
                shorts.append((name.start(), name.group(0)))
                i = name.end()
                continue
        i += 1
    return spans, shorts


# --- fragments (yaml expressions and type strings) ---------------------------------------


def translate_expression(
    text: str, resolver: Resolver, report: FileReport, at: tuple[int, int] | None = None,
    scope: str = "", query_aliases: frozenset[str] = frozenset(),
) -> str:
    """A code fragment out of a yaml value (an expression, a bare name, a chain).

    `scope` names the element the fragment is declared in, so a name may take the spelling the
    dictionary holds for that one namespace.
    """
    edits: list[Edit] = []
    collect_token_edits(text, lexer.tokenize(text), 0, [], resolver, report, edits, at=at,
                        root_scope=scope, query_aliases=query_aliases)
    return apply_edits(text, edits)


def translate_interpolations(
    text: str, resolver: Resolver, report: FileReport, at: tuple[int, int] | None = None,
    method: MethodScope | None = None,
) -> str:
    """Translate ONLY the code inside `%{...}` / `${...}`, leaving the prose untouched.

    A presentation template is text a person reads with expressions embedded in it: the prose
    is data (the localization dictionaries translate it), while the expression names a
    property that has just been renamed. The text of a named literal of a module is read in
    the `method` the literal stands in (see MethodScope); a yaml template has none.
    """
    edits: list[Edit] = []
    spans, shorts = _interpolations(text)
    for start, end in spans:
        inner = text[start:end]
        collect_token_edits(inner, lexer.tokenize(inner), start, [], resolver, report, edits, at=at,
                            method=method)
    for offset, name in shorts:
        _short_name_edit(name, offset, resolver, report, edits,
                         at if at is not None else (0, 0), method)
    return apply_edits(text, edits)


def _short_name_edit(name: str, start: int, resolver: Resolver, report: FileReport,
                     edits: list[Edit], at: tuple[int, int], method: MethodScope | None) -> None:
    """Translate the NAME of a short-form interpolation (`%Имя`) standing at `start`.

    The name is read the way the code reads a bare name: a local of the method answers to an
    entry written for that method first (`Метод.Имя`), and then to the plain one.
    """
    scope = method.name if method is not None and name in method.local_names else ""
    replacement, plane = resolver.identifier(name, scope=scope)
    if plane == "user":
        report.user_done += 1
    if replacement:
        if replacement != name:
            edits.append((start, start + len(name), replacement))
        return
    report.note_token(name, *at)


_TYPE_WORD_RE = re.compile(r"[_\w][\w0-9]*", re.UNICODE)


def translate_type_expression(
    text: str, resolver: Resolver, report: FileReport, at: tuple[int, int] | None = None,
) -> str:
    """A type written as a yaml value: `СтандартнаяКолонкаТаблицы<Задачи.Ссылка>` and kin.

    The structure (`<>`, `?`, `.`, `::`) stays; every name inside resolves like an
    identifier, with the facet suffixes tried after a dot (`.Ссылка` -> `.Reference`).
    """
    out: list[str] = []
    last = 0
    line, col = at if at is not None else (0, 0)
    for m in _TYPE_WORD_RE.finditer(text):
        word = m.group(0)
        out.append(text[last:m.start()])
        prev_end_char = text[m.start() - 1] if m.start() else ""
        if word.isascii():
            out.append(word)
        else:
            replacement, plane = resolver.type_name(word, after_dot=prev_end_char == ".")
            if plane == "user":
                report.user_done += 1
            if replacement is None:
                report.note_token(word, line, col)
                out.append(word)
            else:
                out.append(replacement)
        last = m.end()
    out.append(text[last:])
    return "".join(out)
