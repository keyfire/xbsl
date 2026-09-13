"""A call that a literal of the same type replaces (style/constructor-literal).

The platform IDE warns in two places that a literal would say the same, and the rule repeats
the condition the IDE applies, checked on probe projects variant by variant:

- a constructor call `new T(...)` whose type is one of the types with a literal - `Uuid`,
  `DateTime`, `Date`, `Time`, `Instant`, `TimeZone`, `Bytes`, `Version`, `Locale`, `Boolean`,
  `Duration`, `String`, `Number` - is reported when the call has arguments and EVERY argument
  is a constant literal: a string without interpolation, a number, `True`, `False`,
  `Undefined`, or a literal of its own (`Date{...}`, `Type<...>`, a pattern). A leading minus
  makes an expression, not a literal. The value is not looked at, so `new Date("31.01.2026")`
  is reported too, though no date literal can hold that text;
- a call of the global `FindType` with constant arguments is reported as well: the type is
  known when the code is written, and `Type<...>` says so.

The fix replaces the call with the literal, and only where the literal is proven to hold the
same value. The compiler reads a literal with the same parser the constructor uses at run time
for `Uuid`, `TimeZone`, `Version`, `Bytes` and `Time`; for `Date`, `DateTime` and `Instant`
the literal takes only the ISO form with hyphens, a subset of what the constructor reads. So
the text is carried over when it matches the literal form and its date and time parts are in
range. A string the literal cannot hold, an empty string (an empty literal is the default
value, while the constructor throws), escapes and comments inside the call leave the finding
without a fix. Numbers become the literal the platform writes itself: the date and time parts
of `Date`, `DateTime` and `Time`, and the duration parts in the order days, hours, minutes,
seconds, milliseconds (`0мс` for zero, the English units `d h m s ms` next to the English
keyword). A negative duration and a bare literal that a member access follows
(`new Number("5").ToString()`) are not rewritten: the unary minus and a member access after a
number would change how the line reads.

`FindType` gets no fix: its result is `Type?`, the literal's is the type itself, and a variable
declared from the call changes its inferred type with the rewrite.

Left alone on purpose: a type written with its namespace (`new Std::Time::Date(...)` - no such
call in the corpora, and the file does not show which namespace a qualifier names), a type the
module declares itself (`structure Version`), a `FindType` the module declares as a method, a
variable or a parameter, and a module with parse errors.
"""

from __future__ import annotations

import dataclasses
import datetime
import re
from collections.abc import Iterable
from functools import lru_cache

from xbsl import dataset, i18n, terms
from xbsl import parser as P
from xbsl.diagnostics import Diagnostic, Severity, TextEdit
from xbsl.engine import SourceFile, is_query_file, rule
from xbsl.lexer import linemap
from xbsl.parser import parse

RULE_ID = "style/constructor-literal"

MESSAGES = {
    "style/constructor-literal.title": {
        "ru": "Вызов вместо литерала",
        "en": "Call instead of a literal",
    },
    "style/constructor-literal.constructor": {
        "ru": "Конструктор '{type}' получает только постоянные значения – записать значение литералом.",
        "en": "The '{type}' constructor gets constant values only – write the value as a literal.",
    },
    "style/constructor-literal.constructor-fix": {
        "ru": "Конструктор '{type}' получает только постоянные значения – записать значение "
              "литералом: {literal}",
        "en": "The '{type}' constructor gets constant values only – write the value as a literal: "
              "{literal}",
    },
    "style/constructor-literal.find-type": {
        "ru": "Тип ищется по постоянному имени – записать его литералом типа.",
        "en": "The type is looked up by a constant name – write it as a type literal.",
    },
    "style/constructor-literal.find-type-literal": {
        "ru": "Тип ищется по постоянному имени – записать его литералом: {literal}",
        "en": "The type is looked up by a constant name – write it as a literal: {literal}",
    },
}
i18n.register(MESSAGES)

#: The types that have a literal, by the Russian name. `Type` has one as well, but no
#: constructor to call.
_LITERAL_TYPES = (
    "Ууид", "ДатаВремя", "Дата", "Время", "Момент", "ЧасовойПояс", "Байты", "Версия", "Локаль",
    "Булево", "Длительность", "Строка", "Число",
)
_FIND_TYPE = "НайтиТип"
_TYPE_LITERAL = "Тип"
_STD = "Стд"

#: The kinds of engine literals that count as constant arguments. A query literal counts
#: only without parameters and is judged by its text in `_is_constant`.
_CONSTANT_KINDS = frozenset({"NUMBER", "TRUE", "FALSE", "UNDEFINED", "PATTERN", "TYPE", "RESOLVABLE"})

#: A cheap gate over the whole text: no call that could be reported, no parse.
_GATE = re.compile(r"(?:новый|new)\s|НайтиТип|FindType")


@lru_cache(maxsize=1)
def _type_spellings() -> dict[str, str]:
    """{written name: Russian name} for the literal types, the English half from the dictionary."""
    table: dict[str, str] = {}
    for russian in _LITERAL_TYPES:
        for form in terms.forms(russian, "types"):
            table[form] = russian
    return table


@lru_cache(maxsize=1)
def _find_type_spellings() -> dict[str, str]:
    """{written name of the type search: the type literal keyword in the same language}."""
    table = {_FIND_TYPE: _TYPE_LITERAL}
    english = terms.common_english(_FIND_TYPE)
    if english:
        table[english] = terms.forms(_TYPE_LITERAL, "types")[-1]
    return table


@lru_cache(maxsize=1)
def _std_qualifiers() -> frozenset[str]:
    """How the global type search may be qualified: not at all, or with the standard namespace."""
    english = terms.common_english(_STD)
    return frozenset({"", _STD, english} if english else {"", _STD})


dataset.register_reset(_type_spellings.cache_clear)
dataset.register_reset(_find_type_spellings.cache_clear)
dataset.register_reset(_std_qualifiers.cache_clear)


def _walk(node: object, out: list[P.Node]) -> None:
    """Every node of a subtree; tuples too, since branches of `если` and `попытка` are tuples.

    Children come through `dataclasses.fields`: the native build compiles the AST classes and
    they carry no `__dict__` (see structure_fields._walk).
    """
    if isinstance(node, P.Node):
        out.append(node)
        for field in dataclasses.fields(node):
            _walk(getattr(node, field.name), out)
    elif isinstance(node, (list, tuple)):
        for item in node:
            _walk(item, out)


_SIGN = re.compile(r"[%$]")
_IDENT_START = re.compile(r"[_A-Za-zÀ-῿]")


def _interpolated(raw: str) -> bool:
    """Whether a string literal carries an interpolation: `%Имя`, `$Имя`, `%{...}`, `${...}`.

    A sign after an odd run of backslashes is escaped, and a sign before anything that cannot
    start a name is plain text (`100%`).
    """
    for match in _SIGN.finditer(raw):
        i = match.start()
        k = i
        while k > 0 and raw[k - 1] == "\\":
            k -= 1
        if (i - k) % 2:
            continue
        following = raw[i + 1: i + 2]
        if following == "{" or (following and _IDENT_START.match(following)):
            return True
    return False


def _is_constant(expr: P.Expr | None, text: str) -> bool:
    if not isinstance(expr, P.Literal):
        return False
    if expr.kind == "STRING":
        return not _interpolated(expr.text)
    if expr.kind == "QUERY":
        return not _interpolated(text[expr.start:expr.end])
    return expr.kind in _CONSTANT_KINDS


# --- literal forms ----------------------------------------------------------------------------

_DATE = r"(\d{4})-(\d{2})-(\d{2})"
_TIME = r"(\d{1,2}):(\d{1,2})(?::(\d{1,2})(?:\.\d{1,3})?)?"
_DATE_RE = re.compile(_DATE)
_TIME_RE = re.compile(_TIME)
_DATE_TIME_RE = re.compile(rf"{_DATE}(?:[ T]{_TIME})?")
_INSTANT_RE = re.compile(rf"{_DATE}(?:[ T]{_TIME})?(?: ?(?:[+-]?\d{{1,2}}(?::\d{{2}})?|[A-Za-z][\w/+\-]*))?")
_UUID_RE = re.compile(r"[0-9A-Fa-f]{8}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{12}")
_BYTES_RE = re.compile(r"(?:[0-9A-Fa-f]{2})+")
_VERSION_RE = re.compile(r"\d+(?:\.\d+)*(?:-[0-9A-Za-z][0-9A-Za-z.\-]*)?")
_LOCALE_RE = re.compile(r"[A-Za-z]{2,3}(?:-[A-Za-z0-9]{2,8})*")
#: A zone the way `ZoneId.of` reads it: `Z`, a region (`Europe/Moscow`), or an offset of at
#: most 18 hours, bare or after `UTC`/`GMT`/`UT`.
_ZONE_REGION_RE = re.compile(r"Z|UTC|GMT|UT|[A-Za-z][A-Za-z0-9_\-+]*(?:/[A-Za-z0-9_\-+]+)+")
_ZONE_OFFSET_RE = re.compile(r"(?:UTC|GMT|UT)?[+-](\d{1,2})(?::?([0-5]\d)(?::?([0-5]\d))?)?")
_NUMBER_RE = re.compile(r"(?:0|[1-9]\d*)(?:\.\d+)?")
_INTEGER_RE = re.compile(r"\d+")
_TYPE_NAME_RE = re.compile(r"[^\W\d]\w*(?:::[^\W\d]\w*)*(?:\.[^\W\d]\w*)*")

_TRUE_WORDS = frozenset({"true", "истина"})
_FALSE_WORDS = frozenset({"false", "ложь"})

#: Duration units in the order and spelling the platform itself writes a duration literal.
_DURATION_UNITS = {False: ("д", "ч", "м", "с", "мс"), True: ("d", "h", "m", "s", "ms")}
_DURATION_ZERO = {False: "0мс", True: "0ms"}
#: The largest duration the platform holds, in milliseconds.
_DURATION_MAX_MS = 999_999_999_999_999


def _valid_date(match: re.Match) -> bool:
    try:
        datetime.date(int(match.group(1)), int(match.group(2)), int(match.group(3)))
    except ValueError:
        return False
    return True


def _valid_time(hours: str | None, minutes: str | None, seconds: str | None) -> bool:
    if hours is None:
        return True
    return int(hours) < 24 and int(minutes or 0) < 60 and int(seconds or 0) < 60


def _string_form(canonical: str, content: str) -> bool:
    """Whether the literal of the type holds `content` exactly as the constructor reads it."""
    if canonical == "Дата":
        match = _DATE_RE.fullmatch(content)
        return match is not None and _valid_date(match)
    if canonical == "ДатаВремя":
        match = _DATE_TIME_RE.fullmatch(content)
        return match is not None and _valid_date(match) and _valid_time(*match.group(4, 5, 6))
    if canonical == "Момент":
        match = _INSTANT_RE.fullmatch(content)
        return match is not None and _valid_date(match) and _valid_time(*match.group(4, 5, 6))
    if canonical == "Время":
        match = _TIME_RE.fullmatch(content)
        return match is not None and _valid_time(*match.group(1, 2, 3))
    if canonical == "ЧасовойПояс":
        offset = _ZONE_OFFSET_RE.fullmatch(content)
        if offset is not None:
            return int(offset.group(1)) <= 18
        return _ZONE_REGION_RE.fullmatch(content) is not None
    pattern = {"Ууид": _UUID_RE, "Байты": _BYTES_RE, "Версия": _VERSION_RE, "Локаль": _LOCALE_RE}.get(canonical)
    return pattern is not None and pattern.fullmatch(content) is not None


def _string_content(expr: P.Expr) -> str | None:
    """The text of a plain one-line string literal, or None for anything that needs decoding."""
    if not (isinstance(expr, P.Literal) and expr.kind == "STRING"):
        return None
    raw = expr.text
    if len(raw) < 2 or raw[0] != '"' or raw[-1] != '"':
        return None
    content = raw[1:-1]
    if any(ch in content for ch in '\\"%${}\r\n'):
        return None
    return content


def _integers(args: list[P.CallArg]) -> list[int] | None:
    values = []
    for arg in args:
        if not (isinstance(arg.value, P.Literal) and arg.value.kind == "NUMBER"
                and _INTEGER_RE.fullmatch(arg.value.text)):
            return None
        values.append(int(arg.value.text))
    return values


def _duration(parts: list[int], english: bool) -> str | None:
    """The literal of a non-negative duration of (days, hours, minutes, seconds, milliseconds)."""
    days, hours, minutes, seconds, millis = parts
    total = ((((days * 24 + hours) * 60 + minutes) * 60 + seconds) * 1000) + millis
    if total > _DURATION_MAX_MS:
        return None
    if total == 0:
        return _DURATION_ZERO[english]
    amounts = (total // 86_400_000, total // 3_600_000 % 24, total // 60_000 % 60,
               total // 1000 % 60, total % 1000)
    return "".join(f"{amount}{unit}" for amount, unit in zip(amounts, _DURATION_UNITS[english]) if amount)


def _clock(hours: int, minutes: int, seconds: int, millis: int) -> str | None:
    if hours > 23 or minutes > 59 or seconds > 59 or millis > 999:
        return None
    text = f"{hours:02d}:{minutes:02d}:{seconds:02d}"
    return f"{text}.{millis:03d}" if millis else text


def _calendar(year: int, month: int, day: int) -> str | None:
    try:
        datetime.date(year, month, day)
    except ValueError:
        return None
    return f"{year:04d}-{month:02d}-{day:02d}"


def _braced_content(expr: P.Expr, text: str, written: tuple[str, ...]) -> str | None:
    """The content of a literal `Тип{...}` spelled with one of `written`, or None."""
    if not (isinstance(expr, P.Literal) and expr.kind == "RESOLVABLE" and expr.text in written):
        return None
    body = text[expr.start:expr.end]
    opener = body.find("{")
    if opener < 0 or not body.endswith("}"):
        return None
    return body[opener + 1:-1]


def _numeric_literal(canonical: str, written: str, args: list[P.CallArg], text: str,
                     english: bool) -> str | None:
    """The literal of a constructor whose arguments are the parts of the value."""
    if canonical == "Длительность":
        booleans = {"TRUE": True, "FALSE": False}
        negative = False
        numbers = args
        last = args[-1].value if args else None
        if isinstance(last, P.Literal) and last.kind in booleans:
            negative = booleans[last.kind]
            numbers = args[:-1]
        values = _integers(numbers)
        if values is None or negative or len(values) not in (4, 5):
            return None
        return _duration(([0] + values) if len(values) == 4 else values, english)
    if canonical == "ДатаВремя" and len(args) == 2:
        date = _braced_content(args[0].value, text, terms.forms("Дата", "types"))
        clock = _braced_content(args[1].value, text, terms.forms("Время", "types"))
        date_match = _DATE_RE.fullmatch(date or "")
        time_match = _TIME_RE.fullmatch(clock or "")
        if date_match is None or time_match is None or not _valid_date(date_match):
            return None
        if not _valid_time(*time_match.group(1, 2, 3)):
            return None
        return f"{written}{{{date} {clock}}}"
    values = _integers(args)
    if values is None:
        return None
    if canonical == "Дата" and len(values) == 3:
        day = _calendar(*values)
        return f"{written}{{{day}}}" if day else None
    if canonical == "ДатаВремя" and len(values) in (3, 6, 7):
        day = _calendar(*values[:3])
        clock = _clock(*(values[3:] + [0, 0, 0, 0])[:4])
        return f"{written}{{{day} {clock}}}" if day and clock else None
    if canonical == "Время" and len(values) in (3, 4):
        clock = _clock(*(values + [0])[:4])
        return f"{written}{{{clock}}}" if clock else None
    return None


_BARE_LITERALS = frozenset({"Число", "Булево", "Длительность"})


def _member_follows(text: str, end: int) -> bool:
    """Whether a member access, an index or the insistent `!` continues the value at `end`."""
    rest = text[end:end + 64].lstrip(" \t")
    if rest.startswith(("?.", ".", "[")):
        return True
    return rest.startswith("!") and not rest.startswith("!=")


def _literal_for(node: P.New, canonical: str, written: str, text: str, english: bool) -> str | None:
    args = node.args or []
    if any(arg.name for arg in args):
        return None
    literal: str | None = None
    content = _string_content(args[0].value) if len(args) == 1 and args[0].value is not None else None
    if content is not None and content:
        if canonical == "Булево":
            word = content.strip().lower()
            if word in _TRUE_WORDS or word in _FALSE_WORDS:
                keyword = "TRUE" if word in _TRUE_WORDS else "FALSE"
                literal = _keyword(keyword, english)
        elif canonical == "Число":
            literal = content if _NUMBER_RE.fullmatch(content) else None
        elif _string_form(canonical, content):
            literal = f"{written}{{{content}}}"
    elif content is None:
        literal = _numeric_literal(canonical, written, args, text, english)
    if literal is None:
        return None
    if canonical in _BARE_LITERALS and _member_follows(text, node.end):
        return None
    return literal


@lru_cache(maxsize=4)
def _keyword_forms(canonical: str) -> tuple[str, str]:
    """(Russian, English) spellings of a literal keyword, from the language data."""
    forms = dataset.load_json("language.json")["keywords"][canonical]["forms"]
    russian = next(f for f in forms if not f.isascii())
    english = next(f for f in forms if f.isascii())
    return russian, english


dataset.register_reset(_keyword_forms.cache_clear)


def _keyword(canonical: str, english: bool) -> str:
    russian, english_form = _keyword_forms(canonical)
    return english_form if english else russian


_COMMENT_RE = re.compile(r"//|/\*")


def _comment_inside(text: str, node: P.Node, args: list[P.CallArg]) -> bool:
    """Whether a comment sits inside the call - a rewrite of the span would drop it."""
    pieces = []
    cursor = node.start
    for arg in args:
        value = arg.value
        if isinstance(value, P.Literal) and value.kind == "STRING":
            pieces.append(text[cursor:value.start])
            cursor = value.end
    pieces.append(text[cursor:node.end])
    return any(_COMMENT_RE.search(piece) for piece in pieces)


def _declared_names(nodes: list[P.Node]) -> tuple[set[str], set[str]]:
    """(types, values) the module declares itself.

    A type of its own hides a platform type in `new T(...)`; a method, a variable or a
    parameter hides a global method in a call. The two spaces are apart: a variable named
    `Date` does not change what `new Date(...)` creates.
    """
    types: set[str] = set()
    values: set[str] = set()
    for node in nodes:
        if isinstance(node, (P.Structure, P.Enum)):
            types.add(node.name)
        elif isinstance(node, (P.Method, P.Param, P.VarDecl, P.ObjectField)):
            values.add(node.name)
        elif isinstance(node, (P.ForEach, P.ForTo)):
            values.add(node.var)
        elif isinstance(node, P.Try):
            values.update(var for var, _type, _body in node.catches if var)
    return types, values


@rule(RULE_ID, "style/constructor-literal.title", "C", severity=Severity.WARNING)
def constructor_literal(source: SourceFile) -> Iterable[Diagnostic]:
    """A constructor of a literal type (or `FindType`) called with constant arguments only."""
    if source.kind != "xbsl" or is_query_file(source.path):
        return
    text = source.text
    if _GATE.search(text) is None:
        return
    module, errors = parse(source)
    if errors:
        return
    nodes: list[P.Node] = []
    _walk(module, nodes)
    spellings = _type_spellings()
    find_type = _find_type_spellings()
    declared_types, declared_values = _declared_names(nodes)
    lm = None
    for node in nodes:
        if isinstance(node, P.New):
            written = node.type.text if node.type is not None else ""
            canonical = spellings.get(written)
            if canonical is None or written in declared_types or not node.args:
                continue
            if not all(_is_constant(arg.value, text) for arg in node.args):
                continue
            english = text.startswith("new", node.start)
            literal = None if _comment_inside(text, node, node.args) else \
                _literal_for(node, canonical, written, text, english)
            if literal is None:
                message = i18n.t("style/constructor-literal.constructor", type=written)
                fix = None
            else:
                message = i18n.t("style/constructor-literal.constructor-fix", type=written, literal=literal)
                fix = TextEdit(node.start, node.end, literal)
        elif isinstance(node, P.Call) and isinstance(node.callee, P.Name):
            qualifier, _sep, name = node.callee.name.rpartition("::")
            keyword = find_type.get(name)
            if keyword is None or qualifier not in _std_qualifiers() or name in declared_values:
                continue
            if not all(_is_constant(arg.value, text) for arg in node.args):
                continue
            content = _string_content(node.args[0].value) if len(node.args) == 1 else None
            if content and _TYPE_NAME_RE.fullmatch(content):
                message = i18n.t("style/constructor-literal.find-type-literal",
                                 literal=f"{keyword}<{content}>")
            else:
                message = i18n.t("style/constructor-literal.find-type")
            fix = None
        else:
            continue
        if lm is None:
            lm = linemap(source)
        line, col = lm.linecol(node.start)
        yield Diagnostic(source.rel, line, col, RULE_ID, Severity.WARNING, message, fix=fix)
