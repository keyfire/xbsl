"""A member of a union type that another member already covers (style/redundant-union-member).

`String|String`, `String|Undefined|?` and `String|Object` name no more types than `String`,
`String?` and `Object`. The platform IDE warns about the member that adds nothing,
and the rule repeats what the IDE judges, checked on probe projects variant by variant:

- a union is judged wherever a type is written: a parameter (of a method and of a lambda), a
  result, a variable, a field of a structure, a constant of the module, `это`, `это не`, `как`,
  a `когда это` branch, the type list of `поймать`, the argument of a generic type
  (`новый Массив<Строка|Строка>()`, `<Строка|Строка>[]`);
- the members compare as the platform reads them: the two spellings of a type (`Строка|String`)
  are one type, `T?` is `T` and `Undefined`, `Undefined` and `?` are one empty value;
- a member is covered by an equal member, by `Object` (any type but the empty value, a type of
  the project too) and by a base type from the platform catalog - `Presentable` covers `String`,
  `Iterable<String>` and `ReadableArray<String>` cover `Array<String>`. The arguments of a
  generic type are matched to the base by the names of the type parameters and have to be
  equal: the IDE lets a read-only base take a wider argument (`ReadableArray<Object>` covers
  `Array<String>`, `Array<Object>` does not), and the catalog does not say which parameters
  those are, so a wider argument is left alone;
- the parameters and the result of a function type (`(Строка|Строка)->Число`) and a type
  written in yaml are not judged.

The IDE builds the union member by member, and the place it reports follows from that: a member
equal to an earlier one is reported at the EARLIER one, a member that an earlier one covers is
reported where it stands, a member that covers earlier ones is reported at each of them
(`String|Object|Number` - at `String` and at `Number`). The rule reports the same places.

The fix writes the union without the members that add nothing: the rest in their order, the
empty value once, as `Т?` after a single type and as `|?` after several (the forms
style/nullable-shorthand asks for). A union spread over lines or holding a comment keeps the
findings without a fix. What the rule leaves alone: a qualified name compares only with the same
text, a generic base whose parameters the catalog names differently (`Map` over
`Iterable<KeyAndValue<...>>`) is not matched, and a module that does not parse is not judged.
"""

from __future__ import annotations

import bisect
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from functools import lru_cache

from xbsl import dataset, i18n
from xbsl import parser as P
from xbsl.diagnostics import Diagnostic, Severity, TextEdit
from xbsl.engine import SourceFile, is_query_file, rule
from xbsl.lexer import Token, linemap, tokens
from xbsl.parser import parse
from xbsl.typeinfer import canonical_name, walk_nodes

RULE_ID = "style/redundant-union-member"

MESSAGES = {
    "style/redundant-union-member.title": {
        "ru": "Лишний член составного типа",
        "en": "A redundant member of a union type",
    },
    "style/redundant-union-member.repeated": {
        "ru": "Тип '{member}' повторяется в составном типе – записать тип без повтора: {fixed}",
        "en": "Type '{member}' repeats in the union type – write the type without the repeat: {fixed}",
    },
    "style/redundant-union-member.covered": {
        "ru": "Тип '{member}' уже входит в тип '{wider}' того же составного типа – записать тип без "
              "лишнего члена: {fixed}",
        "en": "Type '{member}' is already part of type '{wider}' in the same union – write the type "
              "without the redundant member: {fixed}",
    },
}
i18n.register(MESSAGES)

_OBJECT = "Объект"
_UNDEFINED = "Неопределено"
#: Keywords that tell the language of a module, which the empty value of the fix follows.
_LANGUAGE_KEYWORDS = frozenset({"METHOD", "VAL", "VAR", "CONST", "STRUCTURE", "RETURN", "IF"})


@dataclass
class _Entry:
    """One member of a union as the platform counts them: a type, or the empty value.

    `first`/`last` are token indices of the written type (the `?` of `Т?` is an entry of its own);
    `key` compares types, `head` and `args` feed the catalog, an `opaque` entry (a function type,
    a group, a qualified name) compares only by its text.
    """

    first: int
    last: int
    key: str
    head: str = ""
    args: list[list["_Entry"]] = field(default_factory=list)
    undefined: bool = False
    opaque: bool = False


@dataclass
class _Union:
    """A written union: its members in order and the token span of the whole of it."""

    entries: list[_Entry]
    first: int
    last: int


@lru_cache(maxsize=1)
def _catalog() -> tuple[dict[str, frozenset[str]], dict[str, tuple[str, ...]]]:
    """({type: its bases}, {type: its type parameters}) of the platform catalog, Russian names."""
    try:
        data = dataset.load_json("stdlib.json")
    except Exception:  # noqa: BLE001 - no data: equal members only
        return {}, {}
    bases = {name: frozenset(items) for name, items in (data.get("bases") or {}).items()}
    params = {name: tuple(items) for name, items in (data.get("type_params") or {}).items()}
    return bases, params


dataset.register_reset(_catalog.cache_clear)


def _is_op(tok: Token, *values: str) -> bool:
    return tok.kind == "OP" and tok.value in values


def _is_name(tok: Token) -> bool:
    return tok.kind == "IDENT" or (tok.kind == "KEYWORD" and tok.canonical in _NAME_KEYWORDS)


#: Keywords a type name may be spelled with (the grammar's names) and the empty value.
_NAME_KEYWORDS = frozenset({"UNDEFINED", "TYPE", "QUERY", "METHOD", "EXCEPTION", "STRUCTURE",
                            "ENUMERATION", "DEFAULT", "STATIC"})


class _Reader:
    """A reader of written types over tokens that collects every union it meets."""

    def __init__(self, text: str, toks: Sequence[Token], end: int) -> None:
        self.text = text
        self.toks = toks
        self.end = end  # the index past the last token of the type
        self.unions: list[_Union] = []

    def peek(self, k: int) -> Token | None:
        return self.toks[k] if k < self.end else None

    def union(self, k: int, judged: bool = True) -> tuple[list[_Entry], int] | None:
        """The members of a union starting at `k` and the index past it."""
        entries: list[_Entry] = []
        first = k
        while True:
            got = self.member(k, entries, judged)
            if got is None:
                return None
            k = got
            tok = self.peek(k)
            if tok is None or not _is_op(tok, "|"):
                break
            k += 1
        if judged and len(entries) > 1:
            self.unions.append(_Union(entries, first, k - 1))
        return entries, k

    def member(self, k: int, entries: list[_Entry], judged: bool = True) -> int | None:
        """One member at `k` appended to `entries`; the index past it. The unions inside a
        member are judged only when the member itself is."""
        tok = self.peek(k)
        if tok is None:
            return None
        if _is_op(tok, "?"):
            entries.append(_Entry(k, k, "?", undefined=True))
            return k + 1
        if _is_op(tok, "("):
            close = self._close(k)
            if close is None:
                return None
            after = close + 1
            nxt = self.peek(after)
            if nxt is not None and _is_op(nxt, "->"):
                # A function type: nothing inside it is judged, its parameters and its result alike.
                result = self.union(after + 1, judged=False)
                after = result[1] if result is not None else after + 1
            else:
                inner = self.union(k + 1, judged=False)
                if inner is None or inner[1] != close:
                    return None
            entries.append(_Entry(k, after - 1, self._text(k, after - 1), opaque=True))
            return self._suffix(after, entries)
        if not _is_name(tok):
            return None
        start = k
        qualified = False
        k += 1
        while True:
            tok = self.peek(k)
            nxt = self.peek(k + 1)
            if tok is not None and nxt is not None and _is_op(tok, "::") and _is_name(nxt):
                qualified = True
                k += 2
            elif tok is not None and nxt is not None and _is_op(tok, ".") and _is_name(nxt):
                k += 2
            else:
                break
        name = self._text(start, k - 1)
        args: list[list[_Entry]] = []
        tok = self.peek(k)
        if tok is not None and _is_op(tok, "<"):
            k += 1
            while True:
                nxt = self.peek(k)
                after = self.peek(k + 1)
                if nxt is not None and after is not None and _is_name(nxt) and _is_op(after, "="):
                    k += 2  # a named argument `Имя=Тип`
                arg = self.union(k, judged)
                if arg is None:
                    return None
                args.append(arg[0])
                k = arg[1]
                tok = self.peek(k)
                if tok is not None and _is_op(tok, ","):
                    k += 1
                    continue
                if tok is None or not _is_op(tok, ">"):
                    return None
                k += 1
                break
        last = k - 1
        canonical = None if qualified else canonical_name(name)
        if start == k - 1 and self.toks[start].kind == "KEYWORD" and self.toks[start].canonical == "UNDEFINED":
            canonical = _UNDEFINED
        if canonical == _UNDEFINED and not args:
            entries.append(_Entry(start, last, "?", undefined=True))
        elif canonical is None:
            entries.append(_Entry(start, last, self._text(start, last), opaque=True))
        else:
            key = canonical
            if args:
                if any(item.opaque for arg in args for item in arg):
                    entries.append(_Entry(start, last, self._text(start, last), opaque=True))
                    return self._suffix(k, entries)
                key = f"{canonical}<{','.join(_set_key(arg) for arg in args)}>"
            entries.append(_Entry(start, last, key, head=canonical, args=args))
        return self._suffix(k, entries)

    def _suffix(self, k: int, entries: list[_Entry]) -> int:
        tok = self.peek(k)
        if tok is not None and _is_op(tok, "?"):
            entries.append(_Entry(k, k, "?", undefined=True))
            return k + 1
        return k

    def _close(self, k: int) -> int | None:
        depth = 0
        for i in range(k, self.end):
            tok = self.toks[i]
            if _is_op(tok, "("):
                depth += 1
            elif _is_op(tok, ")"):
                depth -= 1
                if depth == 0:
                    return i
        return None

    def _text(self, first: int, last: int) -> str:
        return "".join(self.text[self.toks[first].start:self.toks[last].end].split())


def _set_key(entries: list[_Entry]) -> str:
    """The canonical text of a union: its types sorted, the empty value as `?`."""
    names = sorted({entry.key for entry in entries if not entry.undefined})
    if any(entry.undefined for entry in entries):
        names.append("?")
    return "|".join(names)


def _covers(wide: _Entry, narrow: _Entry) -> bool:
    """Whether every value of `narrow` is a value of `wide` (the relation the IDE judges by)."""
    if wide.undefined or narrow.undefined:
        return wide.undefined and narrow.undefined
    if wide.key == narrow.key:
        return True
    if wide.opaque or narrow.opaque:
        return False
    if wide.key == _OBJECT:
        return True
    bases, params = _catalog()
    if wide.head not in bases.get(narrow.head, ()):
        return False
    wide_params = params.get(wide.head, ())
    if not wide_params:
        return not wide.args
    narrow_params = params.get(narrow.head, ())
    if len(wide.args) != len(wide_params) or len(narrow.args) != len(narrow_params):
        return False
    narrow_by_name = dict(zip(narrow_params, narrow.args))
    for name, wide_arg in zip(wide_params, wide.args):
        narrow_arg = narrow_by_name.get(name)
        if narrow_arg is None or _set_key(narrow_arg) != _set_key(wide_arg):
            return False
    return True


@dataclass
class _Finding:
    entry: _Entry
    other: _Entry
    repeated: bool


def _judge(entries: list[_Entry]) -> tuple[list[_Finding], list[_Entry]]:
    """The members that add nothing, at the places the IDE reports, and the members that stay.

    The union is built member by member. A member an earlier one already covers adds nothing -
    reported at the earlier one when the two are equal and at itself otherwise; a member that
    covers earlier ones replaces them, and each of them is reported.
    """
    kept: list[_Entry] = []
    findings: list[_Finding] = []
    for entry in entries:
        wider = next((k for k in kept if _covers(k, entry)), None)
        if wider is not None:
            if _covers(entry, wider):
                findings.append(_Finding(wider, entry, True))
            else:
                findings.append(_Finding(entry, wider, False))
            continue
        covered = [k for k in kept if _covers(entry, k)]
        for k in covered:
            findings.append(_Finding(k, entry, False))
            kept.remove(k)
        kept.append(entry)
    return findings, sorted(kept, key=lambda item: item.first)


def _render(text: str, toks: Sequence[Token], kept: list[_Entry], english: bool) -> str:
    written = [text[toks[e.first].start:toks[e.last].end] for e in kept if not e.undefined]
    undefined = any(e.undefined for e in kept)
    if not written:
        return "Undefined" if english else _UNDEFINED
    if not undefined:
        return "|".join(written)
    if len(written) == 1:
        return f"{written[0]}?"
    return "|".join([*written, "?"])


def _type_spans(module: P.Module, text: str) -> Iterable[tuple[int, int, str]]:
    """Every written type of the module that may hold a union: (start, end, shape).

    The shape tells where the type begins inside the node: `type` - at once, `new` - after the
    keyword, `generic` - at `<` (a generic call, a typed collection literal), `literal` - after
    the name of `Тип<...>`.
    """
    for node in walk_nodes(module):
        if isinstance(node, (P.Param, P.ObjectField, P.VarDecl, P.AsType)):
            refs = [(node.type, "type")]
        elif isinstance(node, P.IsType):
            tref = node.type
            if tref is not None and "|" in text[tref.start:tref.end]:
                # `Х это Тип ? А : Б`: the node still spans the `?` the ternary took back.
                end = tref.end
                if text[tref.start:tref.end].rstrip().endswith("?") and not tref.text.endswith("?"):
                    end = text.rindex("?", tref.start, tref.end)
                yield tref.start, end, "type"
            continue
        elif isinstance(node, P.Method):
            refs = [(node.return_type, "type")]
        elif isinstance(node, P.New):
            refs = [(node.type, "new")]
        elif isinstance(node, P.Try):
            refs = [(tref, "type") for _var, tref, _body in node.catches]
        elif isinstance(node, (P.Call, P.ArrayLit, P.MapLit)):
            refs = [(tref, "generic") for tref in node.type_args]
        elif isinstance(node, P.Literal) and node.kind == "TYPE":
            if "|" in text[node.start:node.end]:
                yield node.start, node.end, "literal"
            continue
        else:
            continue
        for tref, shape in refs:
            if tref is not None and "|" in text[tref.start:tref.end]:
                yield tref.start, tref.end, shape


def _generic_list(reader: _Reader, k: int) -> None:
    """The arguments of `<...>` at `k`, each a union of its own."""
    k += 1
    while True:
        arg = reader.union(k)
        if arg is None:
            return
        k = arg[1]
        tok = reader.peek(k)
        if tok is None or not _is_op(tok, ","):
            return
        k += 1


def _shown(text: str, toks: Sequence[Token], entry: _Entry, english: bool) -> str:
    """A member the way the message names it: as written, the empty value of `?` by its name."""
    if entry.undefined and _is_op(toks[entry.first], "?"):
        return "Undefined" if english else _UNDEFINED
    return text[toks[entry.first].start:toks[entry.last].end]


def _unions(module: P.Module, text: str, toks: Sequence[Token]) -> list[_Union]:
    starts = [tok.start for tok in toks]
    found: list[_Union] = []
    for start, end, shape in sorted(set(_type_spans(module, text))):
        first = bisect.bisect_left(starts, start)
        stop = bisect.bisect_left(starts, end)
        if shape in ("new", "literal"):
            first += 1
        if first >= stop:
            continue
        reader = _Reader(text, toks, stop)
        if shape in ("generic", "literal"):
            if _is_op(toks[first], "<"):
                _generic_list(reader, first)
        else:
            reader.union(first)
        found.extend(reader.unions)
    return found


@rule(RULE_ID, "style/redundant-union-member.title", "D", severity=Severity.WARNING)
def redundant_union_member(source: SourceFile) -> Iterable[Diagnostic]:
    """A member of a union type that another member covers - see the module docstring."""
    if source.kind != "xbsl" or is_query_file(source.path) or "|" not in source.text:
        return
    module, errors = parse(source)
    if errors:
        return
    text = source.text
    raw = tokens(source)
    toks = [tok for tok in raw if tok.kind not in ("COMMENT", "BOM", "EOF")]
    comments = [tok.start for tok in raw if tok.kind == "COMMENT"]
    english = next((tok.value.isascii() for tok in toks if tok.kind == "KEYWORD"
                    and tok.canonical in _LANGUAGE_KEYWORDS), False)
    lm = linemap(source)
    seen: set[tuple[int, int]] = set()
    for union in _unions(module, text, toks):
        findings, kept = _judge(union.entries)
        if not findings:
            continue
        span_start, span_end = toks[union.first].start, toks[union.last].end
        k = bisect.bisect_left(comments, span_start)
        spread = any(char in text[span_start:span_end] for char in "\r\n") \
            or (k < len(comments) and comments[k] < span_end)
        fixed = _render(text, toks, kept, english)
        fix = None if spread else TextEdit(span_start, span_end, fixed)
        for finding in findings:
            place = (toks[finding.entry.first].start, toks[finding.entry.first].end)
            if place in seen:
                continue
            seen.add(place)
            member = _shown(text, toks, finding.entry, english)
            if finding.repeated:
                message = i18n.t("style/redundant-union-member.repeated", member=member, fixed=fixed)
            else:
                message = i18n.t("style/redundant-union-member.covered", member=member,
                                 wider=_shown(text, toks, finding.other, english), fixed=fixed)
            line, col = lm.linecol(place[0])
            yield Diagnostic(source.rel, line, col, RULE_ID, Severity.WARNING, message, fix=fix)
