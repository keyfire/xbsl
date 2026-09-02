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

from xbsl import lexer, terms, typeinfer
from xbsl import parser as P
from xbsl.engine import SourceFile
from xbsl.rules import _syntax
from xbsl.translation import platform_map
from xbsl.translation.dictionary import Dictionary
from xbsl.translation.reporting import FileReport
from xbsl.translation.rewrap import rewrap_comments

_CYRILLIC_RE = re.compile(r"[А-Яа-яЁё]")

#: One span replacement in the decoded text: (start, end, new text).
Edit = tuple[int, int, str]


def has_cyrillic(text: str) -> bool:
    return _CYRILLIC_RE.search(text) is not None


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
    ) -> None:
        self.dictionary = dictionary
        self.project_names = project_names
        self.dictionary_scopes = dictionary_scopes
        self.component_names = component_names
        #: Cyrillic string VALUES of the project's json resources. A code literal spelled
        #: exactly like one of them is usually COMPARED against that data, and translating
        #: the literal parts the comparison from values no translation ever touches.
        self.data_values = data_values

    def dictionary_key(self, name: str, scope: str) -> tuple[str | None, str]:
        """A KEY of a localized-strings dictionary - the project dictionary answers alone.

        A key lives in the namespace of its dictionary, so the entry may be written qualified
        (`<Dictionary>.<Key>`). The platform tables are not consulted at all: a key named after
        an ordinary word would otherwise be renamed at its uses while its declaration waited
        for an entry, and a caption would inherit the spelling of a platform attribute.
        """
        hit = self.dictionary.token(name, scope)
        if hit is not None:
            return hit, "user"
        return None, "missing"

    def identifier(
        self, name: str, *, after_dot: bool = False, scope: str = "", type_scope: str = "",
        static_root: bool = False,
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
        """
        if static_root:
            # `Strings.Join(...)` - a name with a dot after it that the platform knows as a
            # TYPE is the type, whatever else the project called by the same word. A project
            # cannot redefine a platform type, so the gate must not hold here: it once turned
            # a static call into an undefined variable, because a structure field elsewhere
            # carried the same name.
            platform_type = platform_map.type_english(name)
            if platform_type:
                return platform_type, "platform"
        hit = self.dictionary.token(name, scope, type_scope)
        if hit is not None:
            return hit, "user"
        if name in self.project_names:
            # The project's own name: no platform fallback, so the declaration and every
            # use of it move together - or stay together, waiting for one dictionary entry.
            return None, "missing"
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
        hit = self.dictionary.token(name)
        if hit is not None:
            return hit, "user"
        if after_dot:
            # The facet is the platform's own word even when the project declares a name
            # just like it - a type expression would break if `.Ссылка` stayed Russian.
            facet = platform_map.facet_suffix_english(name)
            if facet:
                return facet, "platform"
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


def translate_code(source: SourceFile, resolver: Resolver, report: FileReport) -> str:
    """The translated text of one module (or standalone query file)."""
    edits: list[Edit] = []
    toks = lexer.tokens(source)
    ranges = _syntax.query_ranges(source)
    collect_token_edits(source.text, toks, 0, ranges, resolver, report, edits,
                        inferred_locals=inferred_locals(source, resolver.project_names),
                        type_ranges=type_ranges(source))
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
) -> None:
    """Walk a token list and append the edits; `base` shifts spans into the outer text.

    `at` anchors the REPORT positions of a nested fragment (an interpolation, a yaml value)
    at the fragment's own place in the outer file - the token positions inside it count
    from the fragment start and would point nowhere. `inferred_locals` is what the type
    inference read off the whole module (see inferred_locals): the types of the locals whose
    declarations name none. A fragment has no methods and passes nothing. `type_ranges` are
    the spans of the TYPE expressions (see type_ranges): a name inside one is a type or a
    facet, never a member - `Заявки.Ссылка` as a type is `Tasks.Reference`, the very same
    words as a member access are `Tasks.Link`.
    """
    del text  # spans address the outer text through `base`; kept for symmetry of callers
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
    method_name = ""
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
    #: Cleared at every method boundary.
    local_names: dict[str, str] = {}
    #: What the inference knows about the locals of the current method (see inferred_locals).
    method_types: MethodTypes | None = None
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
            local_names = _method_locals(toks, index)
            method_name = _next_ident(toks, index)
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
                translated, _plane = resolver.identifier(local)
                if translated:
                    report.note_name(f"method:{method_name}", local, translated)
            # The METHODS of one module share a namespace of their own, and the language has
            # no overloading: two of them under one name is a module the compiler refuses.
            # Met live - two Russian words that English spells alike, and the tree went out
            # with two handlers named the same while every check called the translation done.
            if method_name:
                translated, _plane = resolver.identifier(method_name, scope=root_scope)
                if translated:
                    report.note_name("module", method_name, translated)
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
        if kind == "KEYWORD":
            replacement = None
            if in_query:
                replacement = platform_map.query_keyword_english(tok.value)
            if replacement is None:
                replacement = platform_map.keyword_english().get(tok.value)
            if replacement and replacement != tok.value:
                edits.append((base + tok.start, base + tok.end, replacement))
        elif kind == "IDENT":
            field_of = struct_name if pending_field else ""
            pending_field = False
            if field_of:
                # Every field of one structure, whatever language its name is written in: a
                # word already English collides with a Russian one translated into it just
                # as two Russian ones collide with each other.
                translated, _plane = resolver.identifier(tok.value, scope=field_of)
                report.note_name(f"structure:{field_of}", tok.value, translated or tok.value)
            if not tok.value.isascii() and not in_query and type_ranges and _inside(type_ranges, base + tok.start):
                _type_identifier_edit(tok, base, prev_dot, resolver, report, edits, at)
            elif not tok.value.isascii():
                scope = field_of or (prev_ident if prev_dot else root_scope)
                # The type of the receiver, when its declaration names one: the SECOND
                # namespace a member answers to. The receiver as written stays the first -
                # an entry qualified by the variable a project reads its json into was
                # written about that variable, and it must keep answering.
                type_scope = local_names.get(prev_ident, "") if prev_dot and not field_of else ""
                if prev_dot and not field_of and not type_scope and method_types is not None:
                    # A local declared more than once in the method is typed by the place.
                    type_scope = method_types.type_at(prev_ident, base + tok.start)
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
                    and tok.value not in local_names
                )
                _identifier_edit(tok, base, in_query, prev_dot, resolver, report, edits, at,
                                 scope=scope, type_scope=type_scope, static_root=static_root,
                                 chain_root=chain_root,
                                 receiver_is_local=prev_dot and prev_ident in local_names)
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
                          group_argument=is_group_argument(toks, index))
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
    position = index + 1
    while position < len(toks):
        if toks[position].kind == "IDENT":
            return toks[position].value
        if toks[position].kind != "KEYWORD":
            return ""
        position += 1
    return ""


def _method_locals(toks: list, start: int) -> dict[str, str]:
    """{name: the type its declaration names} for the method that begins at `start`.

    Two things are read off one walk. The NAMES tell a local named after a platform type from
    the type itself. The TYPE opens the namespace a member is looked up in: `Root.Услуги`
    where `Root: JsonRoot` is a field of that structure, and one word may be spelled for that
    structure alone. A declaration with no type written down maps to an empty string - the
    name is known, the type is not, and the receiver then answers for itself as before.

    The method ends at the `;` that closes it; a nested declaration inside it belongs to the
    same scope for this purpose.
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
                out[tok.value] = _declared_type(toks, index)
        index += 1
    # The body: declarations and loop variables, up to the closing `;` of the method.
    while index < len(toks):
        tok = toks[index]
        if tok.kind == "OP" and tok.value == ";" and toks[index - 1].kind != "OP":
            pass  # a statement separator - the method ends at a `;` on its own line
        if tok.kind == "KEYWORD" and tok.canonical in ("METHOD", "CONSTRUCTOR"):
            break
        if tok.kind == "KEYWORD" and tok.canonical in ("VAR", "VAL", "REQ", "USE", "FOR"):
            position = index + 1
            while position < len(toks) and toks[position].kind == "KEYWORD":
                position += 1
            if position < len(toks) and toks[position].kind == "IDENT":
                out[toks[position].value] = _declared_type(toks, position)
        index += 1
    return out


def _declared_type(toks: list, index: int) -> str:
    """The type named after `name:` at `index` - its LAST part, or "" when none is written.

    The last part is the type itself (`Seeding.JsonRoot` is the structure `JsonRoot`), and
    the parameters of a generic are not read: `Array<String>` is an Array, and what it holds
    says nothing about the name that follows a dot.
    """
    position = index + 1
    if position >= len(toks) or toks[position].kind != "OP" or toks[position].value != ":":
        return ""
    position += 1
    name = ""
    while position < len(toks):
        tok = toks[position]
        if tok.kind == "IDENT":
            name = tok.value
            position += 1
            if (
                position < len(toks) and toks[position].kind == "OP"
                and toks[position].value == "."
            ):
                position += 1
                continue
        return name
    return name


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
                     chain_root: str = "", receiver_is_local: bool = False) -> None:
    if in_query:
        keyword = platform_map.query_keyword_english(tok.value)
        if keyword:
            edits.append((base + tok.start, base + tok.end, keyword))
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
        platform_member = (
            platform_map.verified_member(tok.value)
            or _member_by_owner(owner, type_scope, tok.value)
        )
    if after_dot and scope in resolver.dictionary_scopes:
        replacement, plane = resolver.dictionary_key(tok.value, scope)
    elif platform_member:
        # The receiver is a platform TYPE - named right before the dot, or the type a local
        # was declared as or inferred to hold: its own vocabulary wins over the flat one,
        # which keeps a single spelling for a word two types spell apart.
        replacement, plane = platform_member, "platform"
    elif after_dot and platform_map.enum_value_of(owner, tok.value):
        # `InformationConnotation.Normal` - a value belongs to ITS enumeration: globally one
        # Russian word answers to several English ones, and the flat dictionary hands out
        # whichever came last (the compiler then refuses the item).
        replacement, plane = platform_map.enum_value_of(owner, tok.value), "platform"
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
        else:
            replacement, plane = resolver.identifier(
                tok.value, after_dot=True, scope=scope, type_scope=type_scope,
            )
    else:
        replacement, plane = resolver.identifier(
            tok.value, after_dot=after_dot, scope=scope, type_scope=type_scope,
            static_root=static_root,
        )
    if plane == "user":
        report.user_done += 1
    elif plane == "platform":
        report.note_platform_answer(tok.value, tok.line, tok.col)
    if replacement:
        if replacement != tok.value:
            edits.append((base + tok.start, base + tok.end, replacement))
        return
    if plane in ("missing", "platform-gap"):
        line, col = at if at is not None else (tok.line, tok.col)
        report.note_missing(tok.value, line, col, plane)


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


def _comment_edits(tok, base, resolver, report, edits) -> None:
    if not has_cyrillic(tok.value):
        return
    offset = 0
    for index, line in enumerate(tok.value.splitlines(keepends=True)):
        body = line.rstrip("\r\n")
        if tok.subkind == "line":
            match = _LINE_COMMENT_RE.match(body)
        elif index == 0:
            match = _BLOCK_FIRST_RE.match(body)
        else:
            match = _BLOCK_LINE_RE.match(body)
        if match:
            payload = match.group(2)
            if has_cyrillic(payload):
                start = base + tok.start + offset + match.start(2)
                translated = resolver.dictionary.phrase(payload)
                if translated is not None:
                    report.phrases_done += 1
                    if translated != payload:
                        edits.append((start, start + len(payload), translated))
                else:
                    report.note_phrase(payload, tok.line + index, tok.col if index == 0 else 1)
        offset += len(line)


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


def _named_group_edits(tok, base, resolver, report, edits, at=None) -> None:
    """Translate the names of the named groups declared inside a pattern literal.

    A group name is read back by that name (`Match.Group("Name")`), and the two sides used to
    move apart: the call is a string the literals plane could name, the declaration inside the
    pattern nothing looked at. The tree then went out with a pattern declaring one name and a
    call asking for another, and the platform answered "no capture group with that name".
    Both sides are resolved by the SAME map now, so one entry moves them together.
    """
    position = at if at is not None else (tok.line, tok.col)
    for match in _NAMED_GROUP_RE.finditer(tok.value):
        name = match.group(1)
        if name.isascii():
            continue
        _name_edit(name, base + tok.start + match.start(1), resolver, report, edits, position)


def _string_edits(tok, base, resolver, report, edits, at=None, *, data: bool = True,
                  group_argument: bool = False) -> None:
    value = tok.value
    if group_argument:
        # The argument of Group() is a NAME, not prose: the literals plane must not answer for
        # it, or the call would take a spelling the pattern never got.
        body = _body_of(tok)
        if body is not None and not body.isascii():
            _name_edit(body, base + tok.start + 1, resolver, report, edits,
                       at if at is not None else (tok.line, tok.col))
        return
    if data and _literal_edit(tok, base, resolver, report, edits, at):
        # The whole literal is gone, and with it every span inside it - a group name included:
        # an entry that names a pattern spells its groups the way it wants them.
        return
    spans, shorts = _interpolations(value)
    for start, end in spans:
        inner = value[start:end]
        inner_tokens = lexer.tokenize(inner)
        collect_token_edits(inner, inner_tokens, base + tok.start + start, [], resolver, report,
                            edits, at=at or (tok.line, tok.col))
    for start, name in shorts:
        replacement, plane = resolver.identifier(name)
        if plane == "user":
            report.user_done += 1
        if replacement:
            if replacement != name:
                edits.append((base + tok.start + start, base + tok.start + start + len(name),
                              replacement))
        else:
            line, col = at if at is not None else (tok.line, tok.col)
            report.note_token(name, line, col)
    _named_group_edits(tok, base, resolver, report, edits, at)
    _resource_path_edits(tok, base, resolver, report, edits, at)
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


def _literal_edit(tok, base, resolver, report, edits, at=None) -> bool:
    """Replace the WHOLE literal when the literals plane names it; True when it did.

    The key is the text between the quotes exactly as the source writes it - interpolations
    and escaping included - and so is the value: the person filling the dictionary writes the
    sentence they see, leaves the `%{...}` where it belongs and spells an inner quote `\\"`
    the one way the code already spells it. Nothing is escaped a second time here, and nothing
    needs to be: the dictionary refused on load any value that is not a literal body
    (`dictionary.literal_body_error`), so what arrives fits between two quotes as it stands.
    The code INSIDE the replacement is then translated by the ordinary interpolation pass, so
    an entry never has to spell out what the names inside it will be renamed to.
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
    replacement = translate_interpolations(translated, resolver, report, at=(line, col))
    if replacement != body:
        edits.append((base + tok.start + 1, base + tok.end - 1, replacement))
    return True


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


def _resource_path_edits(tok, base, resolver, report, edits, at=None) -> None:
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
    """
    value = tok.value
    if len(value) < 2 or not has_cyrillic(value):
        return
    bare = value[1:-1]
    if not _looks_like_resource_path(bare):
        return
    offset = 1
    for segment in re.split(r"([/\\])", bare):
        if segment in ("/", "\\"):
            offset += len(segment)
            continue
        stem, dot, extension = segment.rpartition(".")
        name = stem if dot and extension.lower() in _RESOURCE_SUFFIXES else segment
        if has_cyrillic(name) and not (set("%${}") & set(name)):
            replacement, plane = resolver.identifier(name)
            if plane == "user":
                report.user_done += 1
            if replacement is None:
                line, col = at if at is not None else (tok.line, tok.col)
                report.note_token(name, line, col)
                report.resource_tokens.add(name)
            elif replacement != name:
                start = base + tok.start + offset
                edits.append((start, start + len(name), replacement))
        offset += len(segment)


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
    scope: str = "",
) -> str:
    """A code fragment out of a yaml value (an expression, a bare name, a chain).

    `scope` names the element the fragment is declared in, so a name may take the spelling the
    dictionary holds for that one namespace.
    """
    edits: list[Edit] = []
    collect_token_edits(text, lexer.tokenize(text), 0, [], resolver, report, edits, at=at,
                        root_scope=scope)
    return apply_edits(text, edits)


def translate_interpolations(
    text: str, resolver: Resolver, report: FileReport, at: tuple[int, int] | None = None,
) -> str:
    """Translate ONLY the code inside `%{...}` / `${...}`, leaving the prose untouched.

    A presentation template is text a person reads with expressions embedded in it: the prose
    is data (the localization dictionaries translate it), while the expression names a
    property that has just been renamed.
    """
    edits: list[Edit] = []
    spans, shorts = _interpolations(text)
    for start, end in spans:
        inner = text[start:end]
        collect_token_edits(inner, lexer.tokenize(inner), start, [], resolver, report, edits, at=at)
    for offset, name in shorts:
        replacement, plane = resolver.identifier(name)
        if plane == "user":
            report.user_done += 1
        if replacement and replacement != name:
            edits.append((offset, offset + len(name), replacement))
        elif replacement is None:
            line, col = at if at is not None else (0, 0)
            report.note_token(name, line, col)
    return apply_edits(text, edits)


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
