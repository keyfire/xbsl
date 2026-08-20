"""Naming (CODE_STYLE, section 2).

- 2.1 UpperCamelCase for names (except constants);
- 2.2 in abbreviations only the first letter is capital (`ТелоJson`, not `ТелоJSON`);
- 2.3 constants – ALL_CAPS_WITH_UNDERSCORES;
- 2.4 exception types – with the "Исключение" prefix;
- 2.5 enumeration names – "Вид", not "Тип".

Only names the module declares itself are checked (methods and their parameters, value/variable
declarations, structures, enumerations, exceptions). References to foreign names are left alone:
an abbreviation may come from the stdlib or from someone else's code, and we are not entitled to
rename it.
"""

from __future__ import annotations

import re
from collections.abc import Iterable

from xbsl import i18n
from xbsl.diagnostics import Diagnostic, Severity
from xbsl.engine import SourceFile, rule
from xbsl.lexer import Token
from xbsl.rules._syntax import code_tokens, declarations, signatures
from xbsl.rules.naming import _abbrev_core

MESSAGES = {
    "style/camel-case.title": {
        "ru": "Имя не в UpperCamelCase",
        "en": "Name is not in UpperCamelCase",
    },
    "style/camel-case.underscore": {
        "ru": "Подчёркивание в имени – '{name}': имена пишутся в UpperCamelCase.",
        "en": "Underscore in a name – '{name}': names are written in UpperCamelCase.",
    },
    "style/camel-case.lowercase": {
        "ru": "Имя со строчной буквы – '{name}': имена пишутся в UpperCamelCase.",
        "en": "Name starts with a lowercase letter – '{name}': names are written in UpperCamelCase.",
    },
    "style/const-case.title": {
        "ru": "Константа не БОЛЬШИМИ_БУКВАМИ",
        "en": "Constant is not in ALL_CAPS",
    },
    "style/const-case.not-upper": {
        "ru": "Имя константы '{name}' – константы пишутся БОЛЬШИМИ_БУКВАМИ_С_ПОДЧЁРКИВАНИЯМИ.",
        "en": "Constant name '{name}' – constants are written in ALL_CAPS_WITH_UNDERSCORES.",
    },
    # The marker of an exception type stands where the language of the name puts it: a Russian
    # name carries it as a PREFIX, a Latin one as the `Exception` suffix - so the title names
    # the marker, not one of its two positions.
    "style/exception-prefix.title": {
        "ru": "Имя исключения без пометки \"{n[Исключение]}\"",
        "en": "Exception name without the \"{n[Исключение]}\" marker",
    },
    "style/exception-prefix.missing": {
        "ru": "Имя исключения '{name}' – типы исключений пишутся с префиксом "
              "'{n[Исключение]}': '{n[Исключение]}{name}'.",
        "en": "Exception name '{name}' – exception types are written with the "
              "'{n[Исключение]}' prefix: '{n[Исключение]}{name}'.",
    },
    # A name written in Latin gets the English form of the same convention: there the marker is
    # a SUFFIX, and offering 'ИсключениеAuthentication' would be a suggestion nobody can take.
    "style/exception-prefix.missing-suffix": {
        "ru": "Имя исключения '{name}' – типы исключений пишутся с суффиксом "
              "'{suffix}': '{name}{suffix}'.",
        "en": "Exception name '{name}' – exception types are written with the "
              "'{suffix}' suffix: '{name}{suffix}'.",
    },
    "style/abbreviation-case.title": {
        "ru": "Аббревиатура заглавными буквами в имени",
        "en": "All-caps abbreviation in a name",
    },
    "style/abbreviation-case.caps": {
        "ru": "Аббревиатура заглавными в имени '{name}' – "
              "заглавной остаётся только первая буква: '{suggestion}'.",
        "en": "All-caps abbreviation in the name '{name}' – "
              "only the first letter stays capital: '{suggestion}'.",
    },
    "style/enum-name-vid.title": {
        "ru": "Имя перечисления начинается с \"{n[Тип]}\"",
        # Both spellings are matched (_ENUM_BAD_PREFIXES), so the title names both.
        "en": "Enumeration name starts with \"{n[Тип]}\"",
    },
    "style/enum-name-vid.bad-prefix": {
        "ru": "Имя перечисления '{name}' начинается с '{prefix}' – "
              "в именах перечислений используется '{n[Вид]}': '{n[Вид]}{rest}'.",
        "en": "Enumeration name '{name}' starts with '{prefix}' – "
              "enumeration names use '{n[Вид]}': '{n[Вид]}{rest}'.",
    },
}
i18n.register(MESSAGES)

# Two or more consecutive capitals (either script) inside a name – an all-caps abbreviation
# candidate. The core logic (naming._abbrev_core) hands the trailing capital to the next word
# and dismisses a single-letter remainder as a glued conjunction (СтрокаИЧисло is clean).
_ABBREV_RE = re.compile(r"[А-ЯЁA-Z]{2,}")
_LOCAL_TYPE_KEYWORDS = ("STRUCTURE", "ENUMERATION", "EXCEPTION")
_ENUM_BAD_PREFIXES = ("Тип", "Type")
# The word that marks an exception type, in both spellings. The two languages put it on
# opposite ends: Russian writes it as a PREFIX (`ИсключениеЧтенияФайла`), English as a SUFFIX
# (`FileReadException`) - so a name that ends with the English word obeys the very convention
# this rule exists for, and demanding a prefix of it produced the Cyrillic marker glued onto a
# Latin name, a spelling no project can adopt.
_EXCEPTION_PREFIXES = ("Исключение", "Exception")
_EXCEPTION_SUFFIX = "Exception"
_CYRILLIC_RE = re.compile(r"[А-Яа-яЁё]")


def _exception_name_is_marked(name: str) -> bool:
    """Does the name carry the exception marker NEXT TO a word of its own?

    A name that is ONLY the marker, in either spelling, marks nothing - it is the whole name
    rather than a mark on one - and such a name is reported like an unmarked one.
    """
    for prefix in _EXCEPTION_PREFIXES:
        if name.startswith(prefix) and name[len(prefix):]:
            return True
    return name.endswith(_EXCEPTION_SUFFIX) and bool(name[: -len(_EXCEPTION_SUFFIX)])


def _is_const_name(name: str) -> bool:
    """A constant name: a letter at the start, no lowercase letters (ВЕРСИЯ_СЕРВЕРА, API_URL)."""
    return name[:1].isalpha() and not any(ch.islower() for ch in name)


def _local_type_names(toks: list[Token], canonical: str | None = None) -> list[Token]:
    """Names of structures, enumerations and exceptions (or of a single kind only)."""
    wanted = (canonical,) if canonical else _LOCAL_TYPE_KEYWORDS
    names: list[Token] = []
    for i, tok in enumerate(toks[:-1]):
        if tok.kind == "KEYWORD" and tok.canonical in wanted and tok.value[:1].islower():
            if toks[i + 1].kind == "IDENT":
                names.append(toks[i + 1])
    return names


def _declared_names(source: SourceFile) -> list[Token]:
    """Names declared by the module: methods, their parameters, value/variable declarations, local types."""
    toks = code_tokens(source)
    names: list[Token] = []
    for sig in signatures(toks):
        names.append(sig.name)
        names.extend(p.name for p in sig.params)
    for decl in declarations(toks):
        if decl.keyword.canonical == "CONST":
            continue  # constants have their own rule (2.3)
        names.extend(decl.names)
    names.extend(_local_type_names(toks))
    return names


def _structure_ranges(toks: list[Token]) -> list[tuple[int, int]]:
    """Offsets [start, end) of structure bodies – the `структура ... ;` block (nesting-aware)."""
    from xbsl.rules.code_structure import _OPENERS

    ranges: list[tuple[int, int]] = []
    stack: list[tuple[bool, Token]] = []  # (is a structure, the opening token)
    for tok in toks:
        if tok.kind == "KEYWORD" and tok.canonical in _OPENERS and tok.value[:1].islower():
            stack.append((tok.canonical == "STRUCTURE", tok))
        elif tok.kind == "OP" and tok.value == ";" and stack:
            is_structure, opener = stack.pop()
            if is_structure:
                ranges.append((opener.start, tok.end))
    return ranges


@rule(
    "style/camel-case", "style/camel-case.title", "C",
    severity=Severity.WARNING,
)
def camel_case(source: SourceFile) -> Iterable[Diagnostic]:
    """2.1: `ВходящееСообщение`, not `входящееСообщение` and not `Степень_Важности`.

    Structure fields and method parameters are not checked: their names are often dictated by
    an external contract (Service Manager JSON keys – `access_token`, `Ref_Key`, `apptype_id`),
    and cannot be renamed – serialization goes by field names.
    """
    if source.kind != "xbsl":
        return
    toks = code_tokens(source)
    structures = _structure_ranges(toks)

    names: list[Token] = [sig.name for sig in signatures(toks)]
    names.extend(_local_type_names(toks))
    for decl in declarations(toks):
        if decl.keyword.canonical == "CONST":
            continue  # constants have their own rule (2.3)
        if any(start <= decl.keyword.start < end for start, end in structures):
            continue  # structure field – the name is set by the contract
        names.extend(decl.names)

    for tok in names:
        name = tok.value
        key = None
        if "_" in name:
            key = "style/camel-case.underscore"
        elif name[:1].islower():
            key = "style/camel-case.lowercase"
        if key is None:
            continue
        yield Diagnostic(
            source.rel, tok.line, tok.col, "style/camel-case", Severity.WARNING,
            i18n.t(key, name=name),
        )


@rule(
    "style/const-case", "style/const-case.title", "C",
    severity=Severity.WARNING,
)
def const_case(source: SourceFile) -> Iterable[Diagnostic]:
    """2.3: `конст ВЕРСИЯ_СЕРВЕРА`, not `конст ВерсияСервера`."""
    if source.kind != "xbsl":
        return
    for decl in declarations(code_tokens(source)):
        if decl.keyword.canonical != "CONST":
            continue
        for name in decl.names:
            if _is_const_name(name.value):
                continue
            yield Diagnostic(
                source.rel, name.line, name.col, "style/const-case", Severity.WARNING,
                i18n.t("style/const-case.not-upper", name=name.value),
            )


@rule("style/exception-prefix", "style/exception-prefix.title", "C",
      severity=Severity.WARNING)
def exception_prefix(source: SourceFile) -> Iterable[Diagnostic]:
    """2.4: `исключение ИсключениеЧтенияФайла`, not `исключение ЧтениеФайла`.

    The same convention in an English-spelled project reads `exception FileReadException`: the
    marker moves to the end, the way every English exception type is named. The suggestion
    follows the script of the NAME, not the language of the report - a Latin name is offered the
    suffix, a Cyrillic one the prefix.
    """
    if source.kind != "xbsl":
        return
    for tok in _local_type_names(code_tokens(source), "EXCEPTION"):
        if _exception_name_is_marked(tok.value):
            continue
        key, extra = "style/exception-prefix.missing", {}
        if not _CYRILLIC_RE.search(tok.value):
            key, extra = "style/exception-prefix.missing-suffix", {"suffix": _EXCEPTION_SUFFIX}
        yield Diagnostic(
            source.rel, tok.line, tok.col, "style/exception-prefix", Severity.WARNING,
            i18n.t(key, name=tok.value, **extra),
        )


def _suggest(name: str) -> str:
    """Bring all-caps abbreviations to a single-capital form: ТелоJSON -> ТелоJson,
    СуммаНДС -> СуммаНдс. A glued conjunction before a word is left alone."""
    def fix(m: re.Match) -> str:
        core = _abbrev_core(name, m)
        if len(core) < 2:
            return m.group(0)
        rest = m.group(0)[len(core):]
        return core[0] + core[1:].lower() + rest

    return _ABBREV_RE.sub(fix, name)


def _has_abbreviation(name: str) -> bool:
    """Whether the name carries an all-caps abbreviation (a core of 2+ capitals)."""
    return any(len(_abbrev_core(name, m)) >= 2 for m in _ABBREV_RE.finditer(name))


@rule(
    "style/abbreviation-case", "style/abbreviation-case.title", "C",
    severity=Severity.WARNING,
)
def abbreviation_case(source: SourceFile) -> Iterable[Diagnostic]:
    """2.2: in abbreviations only the first letter is capital (as in `Url`, `КлиентHttp`).

    Cyrillic abbreviations obey the same law - the variable-names standard spells the
    accepted short words as one word each (Ид, Ндс, Фио, Мчд, Мсфо), so СуммаНДС is
    reported with СуммаНдс suggested. Constants stay out (ALL_CAPS is their law, 2.3).
    """
    if source.kind != "xbsl":
        return
    for tok in _declared_names(source):
        if not _has_abbreviation(tok.value):
            continue
        yield Diagnostic(
            source.rel, tok.line, tok.col, "style/abbreviation-case", Severity.WARNING,
            i18n.t("style/abbreviation-case.caps", name=tok.value, suggestion=_suggest(tok.value)),
        )


@rule("style/enum-name-vid", "style/enum-name-vid.title", "C", severity=Severity.WARNING)
def enum_name_vid(source: SourceFile) -> Iterable[Diagnostic]:
    """2.5: enumeration names use "Вид", not "Тип" (`ВидКнопки`, not `ТипКнопки`)."""
    if source.kind != "xbsl":
        return
    toks = code_tokens(source)
    for i, tok in enumerate(toks[:-1]):
        if not (tok.kind == "KEYWORD" and tok.canonical == "ENUMERATION" and tok.value[:1].islower()):
            continue
        name = toks[i + 1]
        if name.kind != "IDENT":
            continue
        for prefix in _ENUM_BAD_PREFIXES:
            rest = name.value[len(prefix):]
            if name.value.startswith(prefix) and rest[:1].isupper():
                yield Diagnostic(
                    source.rel, name.line, name.col, "style/enum-name-vid", Severity.WARNING,
                    i18n.t("style/enum-name-vid.bad-prefix", name=name.value, prefix=prefix, rest=rest),
                )
                break
