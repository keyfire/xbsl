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
  generic type follow the variance and base-argument formulas extracted from the platform
  descriptors: a read-only base may take a wider argument (`ReadableArray<Object>` covers
  `Array<String>`), while a mutable `Array<Object>` does not cover `Array<String>`;
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
text, a generic relation whose variance or base-argument formula the catalog does not prove is
invariant, and a module that does not parse is not judged.
"""

from __future__ import annotations

import bisect
import re
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
def _catalog() -> tuple[
        dict[str, frozenset[str]], dict[str, tuple[str, ...]], dict[str, tuple[str, ...]],
        dict[str, dict[str, tuple[str, ...]]]]:
    """Hierarchy, parameters, variance and generic base formulas of the platform catalog."""
    try:
        data = dataset.load_json("stdlib.json")
    except Exception:  # noqa: BLE001 - no data: equal members only
        return {}, {}, {}, {}
    bases = {name: frozenset(items) for name, items in (data.get("bases") or {}).items()}
    params = {name: tuple(items) for name, items in (data.get("type_params") or {}).items()}
    variance: dict[str, tuple[str, ...]] = {}
    raw_variance = data.get("type_param_variance")
    if isinstance(raw_variance, dict):
        for name, items in raw_variance.items():
            if (isinstance(name, str) and name and isinstance(items, list) and items
                    and all(isinstance(item, str) and item in {"out", "in", "in_out"}
                            for item in items)):
                variance[name] = tuple(items)
    generic_bases: dict[str, dict[str, tuple[str, ...]]] = {}
    raw_generic_bases = data.get("generic_bases")
    if isinstance(raw_generic_bases, dict):
        for name, items in raw_generic_bases.items():
            if not isinstance(name, str) or not name or not isinstance(items, dict):
                continue
            valid = {
                base: tuple(args)
                for base, args in items.items()
                if isinstance(base, str) and base and isinstance(args, list) and args
                and all(isinstance(arg, str) and arg.strip() for arg in args)
            }
            if valid:
                generic_bases[name] = valid
    return bases, params, variance, generic_bases


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


def _split_top(text: str, separator: str) -> list[str]:
    """Split a type expression at top-level separators only."""
    parts: list[str] = []
    start = 0
    depth = 0
    for index, char in enumerate(text):
        if char == "<":
            depth += 1
        elif char == ">":
            depth -= 1
        elif char == separator and depth == 0:
            parts.append(text[start:index].strip())
            start = index + 1
    parts.append(text[start:].strip())
    return parts


def _nominal_key(text: str) -> tuple[str, tuple[str, ...]]:
    """A canonical key split into its head and top-level arguments."""
    text = text.strip()
    if "<" not in text or not text.endswith(">"):
        return text, ()
    head, tail = text.split("<", 1)
    return head.strip(), tuple(_split_top(tail[:-1], ","))


def _substitute(formula: str, values: dict[str, str]) -> str | None:
    """Substitute a supported base formula, leaving nullable shorthand unproven."""
    if any(marker in formula for marker in ("?", "|", "(", ")")):
        return None
    if re.search(r"\b(?:Undefined|Неопределено)\b", formula):
        return None
    return re.sub(
        r"[A-Za-zА-Яа-яЁё_][\wА-Яа-яЁё]*",
        lambda match: values.get(match.group(0), match.group(0)),
        formula,
    ).replace(" ", "")


def _base_arguments(
        head: str, args: tuple[str, ...], target: str, seen: frozenset[str] = frozenset(),
) -> tuple[str, ...] | None:
    """Arguments a written generic type supplies to one of its generic bases."""
    bases, params, variances, formulas = _catalog()
    if head == target:
        return args
    if head in seen or target not in bases.get(head, ()):
        return None
    own_params = params.get(head, ())
    if len(own_params) != len(args):
        return None
    values = dict(zip(own_params, args))
    for base, base_formulas in formulas.get(head, {}).items():
        substituted = [_substitute(formula, values) for formula in base_formulas]
        if any(formula is None for formula in substituted):
            if base == target:
                return None
            continue
        mapped = tuple(formula for formula in substituted if formula is not None)
        if base == target:
            return mapped
        found = _base_arguments(base, mapped, target, seen | {head})
        if found is not None:
            return found
    # Older catalogs had no formulas. Equal parameter names are the only mapping they prove.
    target_params = params.get(target, ())
    if not target_params:
        return ()
    if variances or formulas:
        return None
    if target_params and all(name in values for name in target_params):
        return tuple(values[name] for name in target_params)
    return None


def _arguments_cover(head: str, wide: tuple[str, ...], narrow: tuple[str, ...]) -> bool:
    """Compare arguments by declared variance, invariant when the catalog is silent."""
    _bases, params, variances, _formulas = _catalog()
    if len(wide) != len(narrow) or len(wide) != len(params.get(head, ())):
        return False
    kinds = variances.get(head)
    if kinds is None or len(kinds) != len(wide):
        kinds = ("in_out",) * len(wide)
    for kind, wide_arg, narrow_arg in zip(kinds, wide, narrow):
        if kind == "out":
            if not _union_key_covers(wide_arg, narrow_arg):
                return False
        elif kind == "in":
            if not _union_key_covers(narrow_arg, wide_arg):
                return False
        elif wide_arg != narrow_arg:
            return False
    return True


def _union_key_covers(wide: str, narrow: str) -> bool:
    wide_members = _split_top(wide, "|")
    narrow_members = _split_top(narrow, "|")
    return all(any(_key_covers(w, n) for w in wide_members) for n in narrow_members)


def _key_covers(wide: str, narrow: str) -> bool:
    """Coverage of two canonical, non-opaque type keys."""
    if wide == narrow:
        return True
    if wide == "?" or narrow == "?":
        return False
    wide_head, wide_args = _nominal_key(wide)
    narrow_head, narrow_args = _nominal_key(narrow)
    if wide_head == _OBJECT:
        return True
    bases, _params, _variance, _formulas = _catalog()
    if wide_head != narrow_head and wide_head not in bases.get(narrow_head, ()):
        return False
    mapped = _base_arguments(narrow_head, narrow_args, wide_head)
    return mapped is not None and _arguments_cover(wide_head, wide_args, mapped)


def _covers(wide: _Entry, narrow: _Entry) -> bool:
    """Whether every value of `narrow` is a value of `wide` (the relation the IDE judges by)."""
    if wide.undefined or narrow.undefined:
        return wide.undefined and narrow.undefined
    if wide.key == narrow.key:
        return True
    if wide.opaque or narrow.opaque:
        return False
    return _key_covers(wide.key, narrow.key)


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
