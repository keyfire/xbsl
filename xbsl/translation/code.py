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

import re

from xbsl import lexer
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
    ) -> None:
        self.dictionary = dictionary
        self.project_names = project_names
        self.dictionary_scopes = dictionary_scopes
        self.component_names = component_names

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
        self, name: str, *, after_dot: bool = False, scope: str = "",
        static_root: bool = False,
    ) -> tuple[str | None, str]:
        """(the English spelling or None, which plane answered: user|platform|missing).

        The position matters: a name standing on its own is a TYPE or a variable, while a
        name after a dot is a MEMBER, and the two dictionaries answer the same word
        differently - one Russian word is the type `Strings` and the member `Rows`. So a root reads
        the type dictionary first and a member the compiler dictionary first. `scope` names
        a namespace of its own (a localized-strings dictionary), where the project may have
        entered a spelling for this one namespace.
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
        hit = self.dictionary.token(name, scope)
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
    collect_token_edits(source.text, toks, 0, ranges, resolver, report, edits)
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
) -> None:
    """Walk a token list and append the edits; `base` shifts spans into the outer text.

    `at` anchors the REPORT positions of a nested fragment (an interpolation, a yaml value)
    at the fragment's own place in the outer file - the token positions inside it count
    from the fragment start and would point nowhere.
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
    #: Names DECLARED in the current method (parameters, locals, loop variables). A local may
    #: be named after a platform type, and then `Strings.Add(...)` is a call on the LOCAL, not
    #: a static call on the type - taking the type spelling there turns it into an undefined
    #: variable. The set is cleared at every method boundary.
    local_names: set[str] = set()
    #: Bodies of the resolvable literals - a string inside one is code of another language.
    resolvable = _resolvable_ranges(toks)
    for index, tok in enumerate(toks):
        kind = tok.kind
        if kind == "EOF":
            break
        if kind == "KEYWORD" and tok.canonical in ("METHOD", "CONSTRUCTOR"):
            local_names = _method_locals(toks, index)
            method_name = _next_ident(toks, index)
            # Every declared name of one method shares a namespace: two Russian words that
            # translate into ONE English word collide there, and the compiler refuses the
            # module ("variable is already defined"). Only the translator can see this - the
            # dictionary is global, the collision is local.
            for local in sorted(local_names):
                translated, _plane = resolver.identifier(local)
                if translated:
                    report.note_name(f"method:{method_name}", local, translated)
        if kind == "OP" and tok.value == "@":
            # An ANNOTATION opens the namespace of its own arguments: `@ProjectUpdate(Number =
            # 20)` names a parameter of the annotation, not a word of the project.
            pending_ctor = True
        if kind == "KEYWORD" and tok.canonical == "NEW":
            pending_ctor = True
        elif pending_ctor and kind in ("IDENT", "KEYWORD"):
            ctor_stack.append((tok.value, depth))
            pending_ctor = False
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
            if not tok.value.isascii():
                scope = prev_ident if prev_dot else root_scope
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
                                 scope=scope, static_root=static_root, chain_root=chain_root)
        elif kind == "COMMENT":
            _comment_edits(tok, base, resolver, report, edits)
        elif kind == "STRING":
            _string_edits(tok, base, resolver, report, edits, at,
                          data=not in_query and not _inside(resolvable, tok.start))
        if kind in ("IDENT", "KEYWORD"):
            if not prev_dot:
                chain_root = tok.value
            prev_ident = tok.value
        elif not (kind == "OP" and tok.value == "."):
            prev_ident = ""
            chain_root = ""
        prev_dot = kind == "OP" and tok.value == "."
    return


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


def _method_locals(toks: list, start: int) -> set[str]:
    """Names declared inside the method that begins at `start`: parameters, locals, loop vars.

    Collected for ONE purpose - to tell a local named after a platform type from the type
    itself. The method ends at the `;` that closes it; a nested declaration inside it belongs
    to the same scope for this purpose.
    """
    out: set[str] = set()
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
                out.add(tok.value)
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
                out.add(toks[position].value)
        index += 1
    return out


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


def _identifier_edit(tok, base, in_query, after_dot, resolver, report, edits, at=None,
                     scope: str = "", static_root: bool = False, chain_root: str = "") -> None:
    if in_query:
        keyword = platform_map.query_keyword_english(tok.value)
        if keyword:
            edits.append((base + tok.start, base + tok.end, keyword))
            return
    if after_dot and scope in resolver.dictionary_scopes:
        replacement, plane = resolver.dictionary_key(tok.value, scope)
    elif after_dot and scope and platform_map.member_of(scope, tok.value):
        # The receiver is a platform TYPE named right before the dot: its own vocabulary wins
        # over the flat one, which keeps a single spelling for a word two types spell apart.
        replacement, plane = platform_map.member_of(scope, tok.value), "platform"
    elif after_dot and platform_map.enum_value_of(scope, tok.value):
        # `InformationConnotation.Normal` - a value belongs to ITS enumeration: globally one
        # Russian word answers to several English ones, and the flat dictionary hands out
        # whichever came last (the compiler then refuses the item).
        replacement, plane = platform_map.enum_value_of(scope, tok.value), "platform"
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
            replacement, plane = resolver.identifier(tok.value, after_dot=True, scope=scope)
    else:
        replacement, plane = resolver.identifier(
            tok.value, after_dot=after_dot, scope=scope, static_root=static_root,
        )
    if plane == "user":
        report.user_done += 1
    elif plane == "platform":
        report.note_platform_answer(tok.value, tok.line, tok.col)
    if replacement:
        if replacement != tok.value:
            edits.append((base + tok.start, base + tok.end, replacement))
        return
    if plane == "missing":
        line, col = at if at is not None else (tok.line, tok.col)
        report.note_token(tok.value, line, col)


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


def _string_edits(tok, base, resolver, report, edits, at=None, *, data: bool = True) -> None:
    value = tok.value
    if data and _literal_edit(tok, base, resolver, report, edits, at):
        return  # the whole literal is gone, and with it every span inside it
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
    replacement = translate_interpolations(translated, resolver, report, at=(line, col))
    if replacement != body:
        edits.append((base + tok.start + 1, base + tok.end - 1, replacement))
    return True


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
    spans, shorts = _interpolations(tok.value)
    masked = list(tok.value)
    for start, end in spans:
        for position in range(start, min(end, len(masked))):
            masked[position] = " "
    for start, name in shorts:
        for position in range(start, min(start + len(name), len(masked))):
            masked[position] = " "
    if not has_cyrillic("".join(masked)):
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
