"""Tier B: typography in comments, in string literals and in the resource files.

The typography rules:
- dash: en dash - (U+2013), NOT em dash — (U+2014);  scope: prose/comments;
- ellipsis: three dots ..., NOT the … character (U+2026);  scope: prose/comments;
- quotes: straight " (the widest rule - code and comments alike), neither curly nor guillemets;
  EXCEPTION: guillemets «» are fine inside UI strings shown to the user.

Hence:
- the em dash and the ellipsis character are checked in comments only (code strings are left alone);
- curly quotes “ ” ‘ ’ are checked in comments and in strings (allowed nowhere);
- guillemets « » are checked in comments only (they are legitimate in UI strings).

One more rule of the group reads yaml rather than code - typography/yo-in-text, the letter
"ё" in the text a user reads (labels and the dictionary of localized strings). Its own
section comment stands next to it, at the end of this module.

Two rules judge the comments alone, an element description included: typography/non-keyboard
(an arrow, a comparison or a multiplication sign that is not on the keyboard) and
typography/en-dash-comment (the en dash, for a project that writes a hyphen in its code
comments). Their section comment explains the choice of characters.

THE RESOURCE FILES ARE JUDGED THE SAME WAY. A subsystem ships its `.css`, `.js`, `.svg` and
`.html` to the browser untouched, so the prose there reaches the reader as surely as the
prose of a module, and until now nobody looked at it (decided on 12.09.2026:
the typography of a project covers every file of it). `xbsl/restext.py` says which parts of
such a file are prose, and the mapping follows the three rules above with nothing invented:

    a comment of any of the four formats      = a comment of a module: all four rules;
    the text the user reads on the screen     = a UI string: the dash, the ellipsis, the
    (SVG <title>/<desc>/<text>, HTML text)      curly quotes and the letter "ё" - but NOT
                                                the guillemets, which belong there.

Code is left alone: selectors, property and tag names, identifiers, attribute names and
their values, and the string literals of a script or a stylesheet.
"""

from __future__ import annotations

import re
from collections.abc import Iterable

from xbsl import i18n, restext, uischema
from xbsl.diagnostics import Diagnostic, Severity, TextEdit
from xbsl.engine import SourceFile, rule
from xbsl.lexer import linemap, tokens
from xbsl.rules import _comments
from xbsl.rules.localization import _all_section_names
from xbsl.rules.yaml_schema import _composed, _HAVE_YAML, _mapping_nodes

if _HAVE_YAML:
    import yaml

MESSAGES = {
    "typography/em-dash.title": {
        "ru": "Длинное тире в комментарии или тексте",
        "en": "Em dash in a comment or in text",
    },
    "typography/em-dash.found": {
        "ru": "Длинное тире U+2014 в комментарии – использовать среднее тире – (U+2013).",
        "en": "Em dash U+2014 in a comment – use an en dash – (U+2013).",
    },
    "typography/em-dash.found-text": {
        "ru": "Длинное тире U+2014 в тексте, который читает пользователь – использовать "
              "среднее тире – (U+2013).",
        "en": "Em dash U+2014 in text the user reads – use an en dash – (U+2013).",
    },
    "typography/ellipsis.title": {
        "ru": "Символ многоточия в комментарии или тексте",
        "en": "Ellipsis character in a comment or in text",
    },
    "typography/ellipsis.found": {
        "ru": "Символ многоточия U+2026 в комментарии – использовать три точки '...'.",
        "en": "Ellipsis character U+2026 in a comment – use three dots '...'.",
    },
    "typography/ellipsis.found-text": {
        "ru": "Символ многоточия U+2026 в тексте, который читает пользователь – использовать "
              "три точки '...'.",
        "en": "Ellipsis character U+2026 in text the user reads – use three dots '...'.",
    },
    "typography/curly-quotes.title": {
        "ru": "Кудрявые кавычки",
        "en": "Curly quotes",
    },
    "typography/curly-quotes.found": {
        "ru": "Кудрявая кавычка U+{code} – использовать прямые кавычки \".",
        "en": "Curly quote U+{code} – use straight quotes \".",
    },
    "typography/guillemets-comment.title": {
        "ru": "Ёлочки в комментарии",
        "en": "Guillemets in a comment",
    },
    "typography/guillemets-comment.found": {
        "ru": "Ёлочка U+{code} в комментарии – в комментариях прямые кавычки \" "
              "(ёлочки допустимы только в UI-строках).",
        "en": "Guillemet U+{code} in a comment – comments use straight quotes \" "
              "(guillemets are allowed in UI strings only).",
    },
    "typography/yo-in-text.title": {
        "ru": "Буква \"ё\" в тексте интерфейса",
        "en": "Letter \"ё\" in interface text",
    },
    "typography/yo-in-text.found": {
        "ru": "Буква 'ё' в тексте, который читает пользователь – '{word}': в подписях она "
              "не используется, пишется '{suggestion}'.",
        "en": "The letter 'ё' in text the user reads – '{word}': labels do without it, "
              "write '{suggestion}'.",
    },
    "typography/yo-in-text.meaning": {
        "ru": "Буква 'ё' в тексте, который читает пользователь – '{word}': здесь она несёт "
              "смысл ('все' – не то же самое), поэтому замену делать вручную.",
        "en": "The letter 'ё' in text the user reads – '{word}': here it carries the meaning "
              "('все' is a different word), so the replacement is a manual decision.",
    },
    "typography/non-keyboard.title": {
        "ru": "Знак не с клавиатуры в комментарии",
        "en": "A character off the keyboard in a comment",
    },
    "typography/non-keyboard.found": {
        "ru": "Знак '{char}' (U+{code}) в комментарии – его нет на клавиатуре, пишется "
              "'{replacement}'.",
        "en": "The character '{char}' (U+{code}) in a comment – it is not on the keyboard, "
              "write '{replacement}'.",
    },
    "typography/non-keyboard.word": {
        "ru": "Знак '{char}' (U+{code}) в комментарии – его нет на клавиатуре, пишется словом "
              "('вверх', 'вниз').",
        "en": "The character '{char}' (U+{code}) in a comment – it is not on the keyboard, "
              "write the word ('up', 'down').",
    },
    "typography/en-dash-comment.title": {
        "ru": "Среднее тире в комментарии",
        "en": "En dash in a comment",
    },
    "typography/en-dash-comment.found": {
        "ru": "Среднее тире U+2013 в комментарии – в комментариях кода пишется дефис '-'.",
        "en": "En dash U+2013 in a comment – a code comment uses the hyphen '-'.",
    },
    "typography/en-dash-comment.off": {
        "ru": "соглашение ПРОЕКТА, а не платформы: одна команда пишет в комментариях кода "
              "только дефис, другая – среднее тире, и typography/em-dash называет его верным "
              "знаком прозы. Проект включает правило в своём CI (--enable typography/en-dash-comment)",
        "en": "a PROJECT convention rather than a platform one: one team writes only the hyphen "
              "in code comments, another writes the en dash, which typography/em-dash names the "
              "right character of prose. A project turns the rule on in its CI "
              "(--enable typography/en-dash-comment)",
    },
}
i18n.register(MESSAGES)

_EM_DASH = "—"  # U+2014
_ELLIPSIS = "…"  # U+2026
_CURLY = "“”‘’"  # U+201C..U+2019
_GUILLEMETS = "«»"  # U+00AB, U+00BB

# Unambiguous replacements for --fix: curly doubles/guillemets → straight ", curly singles → '.
_STRAIGHT = {"“": '"', "”": '"', "‘": "'", "’": "'", "«": '"', "»": '"'}


def _hits(source: SourceFile, kinds: tuple[str, ...], chars: str):
    # The vast majority of files contain none of the characters at all: a whole-text
    # check at C speed removes the per-character token walk (it was visible in the
    # whole-project profile).
    text = source.text
    if not any(ch in text for ch in chars):
        return
    lm = linemap(source)
    for tok in tokens(source):
        if tok.kind not in kinds:
            continue
        where = restext.COMMENT if tok.kind == "COMMENT" else restext.TEXT
        for idx, ch in enumerate(tok.value):
            if ch in chars:
                offset = tok.start + idx
                line, col = lm.linecol(offset)
                yield ch, line, col, offset, where


def _resource_hits(source: SourceFile, kinds: tuple[str, ...], chars: str):
    """The same walk over a resource file: the prose segments instead of the tokens."""
    text = source.text
    if not any(ch in text for ch in chars):
        return
    lm = linemap(source)
    for segment in restext.segments(source):
        if segment.kind not in kinds:
            continue
        for offset in range(segment.start, segment.end):
            ch = text[offset]
            if ch in chars:
                line, col = lm.linecol(offset)
                yield ch, line, col, offset, segment.kind


def _found(source: SourceFile, chars: str, *, token_kinds: tuple[str, ...],
           segment_kinds: tuple[str, ...]):
    """Occurrences of `chars` in the parts of THIS file the rule judges.

    A module is read by tokens, a resource file by the prose segments of `restext`; an empty
    tuple means the rule has nothing to say about that half of the project. Every occurrence
    says where it sits - in a comment or in the text a user reads - so a rule that judges
    both can word its message for the place.
    """
    if source.kind == "xbsl":
        return _hits(source, token_kinds, chars) if token_kinds else ()
    if source.kind in restext.KINDS:
        return _resource_hits(source, segment_kinds, chars) if segment_kinds else ()
    return ()


def _message(key: str, where: str) -> str:
    """The wording for the place the character was found in."""
    return i18n.t(key if where == restext.COMMENT else f"{key}-text")


#: A comment of a module and a comment of a resource file: the same prose, the same rules.
_COMMENTS = (restext.COMMENT,)
#: A comment plus the text the user reads on the screen.
_COMMENTS_AND_TEXT = (restext.COMMENT, restext.TEXT)


# The em dash and guillemets are all over existing comments, so these two rules are off by
# default and carry severity=info (enable them with --select).
@rule(
    "typography/em-dash", "typography/em-dash.title", "B",
    severity=Severity.INFO, enabled_by_default=False, off_reason="typography/em-dash.off",
)
def em_dash(source: SourceFile) -> Iterable[Diagnostic]:
    for _ch, line, col, offset, where in _found(
        source, _EM_DASH, token_kinds=("COMMENT",), segment_kinds=_COMMENTS_AND_TEXT,
    ):
        yield Diagnostic(
            source.rel, line, col, "typography/em-dash", Severity.INFO,
            _message("typography/em-dash.found", where),
            fix=TextEdit(offset, offset + 1, "–"),  # em dash → en dash
        )


@rule("typography/ellipsis", "typography/ellipsis.title", "B", severity=Severity.WARNING)
def ellipsis_char(source: SourceFile) -> Iterable[Diagnostic]:
    for _ch, line, col, offset, where in _found(
        source, _ELLIPSIS, token_kinds=("COMMENT",), segment_kinds=_COMMENTS_AND_TEXT,
    ):
        yield Diagnostic(
            source.rel, line, col, "typography/ellipsis", Severity.WARNING,
            _message("typography/ellipsis.found", where),
            fix=TextEdit(offset, offset + 1, "..."),  # … → three dots
        )


@rule("typography/curly-quotes", "typography/curly-quotes.title", "B", severity=Severity.WARNING)
def curly_quotes(source: SourceFile) -> Iterable[Diagnostic]:
    for ch, line, col, offset, _where in _found(
        source, _CURLY, token_kinds=("COMMENT", "STRING"), segment_kinds=_COMMENTS_AND_TEXT,
    ):
        yield Diagnostic(
            source.rel, line, col, "typography/curly-quotes", Severity.WARNING,
            i18n.t("typography/curly-quotes.found", code=f"{ord(ch):04X}"),
            fix=TextEdit(offset, offset + 1, _STRAIGHT[ch]),  # curly → straight " or '
        )


@rule(
    "typography/guillemets-comment", "typography/guillemets-comment.title", "B",
    severity=Severity.INFO, enabled_by_default=False, off_reason="typography/guillemets-comment.off",
)
def guillemets_in_comment(source: SourceFile) -> Iterable[Diagnostic]:
    # Comments alone, in a resource file too: on the screen the guillemets are the right
    # quotes, and a page of the site is full of them by design.
    for ch, line, col, offset, _where in _found(
        source, _GUILLEMETS, token_kinds=("COMMENT",), segment_kinds=_COMMENTS,
    ):
        yield Diagnostic(
            source.rel, line, col, "typography/guillemets-comment", Severity.INFO,
            i18n.t("typography/guillemets-comment.found", code=f"{ord(ch):04X}"),
            fix=TextEdit(offset, offset + 1, _STRAIGHT[ch]),  # «» → straight " in a comment
        )


# --- characters off the keyboard, in a comment ----------------------------------------------
#
# An arrow, a comparison sign or a multiplication sign is not on the keyboard: a reader
# cannot type it into a search, and the next author writes `->` next to it, so one idea gets
# two spellings in the same tree. Each of them has a spelling from the keyboard, and the fix
# writes it. The two vertical arrows are the exception: nothing from the keyboard stands for
# them, so the finding asks for the word and carries no fix.
#
# Comments alone - of a module, of an element description, of a resource file. A string
# literal keeps its characters: a label may well show an arrow. A currency sign in a comment
# is data ("подпись у суммы: ₽") and is not judged either. The two rules of this section
# read the comments through `_comments.lines` - the one walk shared with the `comment/`
# group - so they judge the comments of an element description as well; the rules above
# read a module and a resource file.

#: Character -> its spelling from the keyboard. `<>` is the inequality of the language.
_NON_KEYBOARD = {
    "→": "->", "←": "<-", "↔": "<->", "⇒": "=>", "⇐": "<=", "⇔": "<=>",
    "≥": ">=", "≤": "<=", "≠": "<>", "×": "x", "≈": "~", "±": "+-",
}
#: Characters with no spelling from the keyboard: the finding asks for the word.
_NON_KEYBOARD_WORD = "↑↓"
_NON_KEYBOARD_ALL = "".join(_NON_KEYBOARD) + _NON_KEYBOARD_WORD
_EN_DASH = "–"  # U+2013


def _comment_chars(source: SourceFile, chars: str):
    """(char, line, column, offset) of every listed character in a comment of the file."""
    text = source.text
    if not any(ch in text for ch in chars):
        return
    for cl in _comments.lines(source):
        for index, ch in enumerate(cl.text):
            if ch in chars:
                yield ch, cl.line, cl.column + index, cl.offset + index


@rule("typography/non-keyboard", "typography/non-keyboard.title", "B", severity=Severity.WARNING)
def non_keyboard(source: SourceFile) -> Iterable[Diagnostic]:
    """An arrow, a comparison or a multiplication sign in a comment; the fix spells it.

    The characters and what the fix writes instead:

        →  ->     ←  <-     ↔  <->    ⇒  =>     ⇐  <=     ⇔  <=>
        ≥  >=     ≤  <=     ≠  <>     ×  x      ≈  ~      ±  +-
        ↑  ↓      no fix: the finding asks for the word

    `<>` is how the language writes the inequality. The letter "ё", the em dash and the
    en dash have rules of their own (`typography/yo-in-text`, `typography/em-dash`,
    `typography/en-dash-comment`) and are not judged here.
    """
    text = source.text
    for ch, line, col, offset in _comment_chars(source, _NON_KEYBOARD_ALL):
        code = f"{ord(ch):04X}"
        replacement = _NON_KEYBOARD.get(ch)
        if replacement is None:
            yield Diagnostic(
                source.rel, line, col, "typography/non-keyboard", Severity.WARNING,
                i18n.t("typography/non-keyboard.word", char=ch, code=code),
            )
            continue
        yield Diagnostic(
            source.rel, line, col, "typography/non-keyboard", Severity.WARNING,
            i18n.t("typography/non-keyboard.found", char=ch, code=code, replacement=replacement),
            fix=TextEdit(offset, offset + 1, _spaced(text, offset, replacement)),
        )


def _spaced(text: str, offset: int, replacement: str) -> str:
    """The replacement of the character at `offset`, kept apart from a letter next to it.

    Only the multiplication sign needs it: its replacement is itself a letter, and
    "строка×столбец" written as "строкаxстолбец" reads as one word. Between digits
    ("2×3") nothing is added.
    """
    if replacement != "x":
        return replacement
    left = " " if offset > 0 and text[offset - 1].isalpha() else ""
    right = " " if offset + 1 < len(text) and text[offset + 1].isalpha() else ""
    return f"{left}{replacement}{right}"


@rule(
    "typography/en-dash-comment", "typography/en-dash-comment.title", "B",
    severity=Severity.INFO, enabled_by_default=False,
    off_reason="typography/en-dash-comment.off",
)
def en_dash_in_comment(source: SourceFile) -> Iterable[Diagnostic]:
    """The en dash in a comment, for a project that writes the hyphen there.

    Off by default: `typography/em-dash` names the en dash as the right character of prose,
    and which of the two a code comment follows is the choice of a project. The fix writes
    the hyphen.
    """
    for _ch, line, col, offset in _comment_chars(source, _EN_DASH):
        yield Diagnostic(
            source.rel, line, col, "typography/en-dash-comment", Severity.INFO,
            i18n.t("typography/en-dash-comment.found"),
            fix=TextEdit(offset, offset + 1, "-"),  # en dash → hyphen
        )


# --- the letter "ё" in the text a user reads ----------------------------------------------
#
# `naming/yo` judges NAMES (clause 1.2 of the platform standard) and never looks at the text on
# the screen, so a label written with that letter passed every check and reached the product.
# What the user reads lives in two places of a yaml, and both are judged here: the visible text
# properties listed below, and the entries of a localized-strings dictionary - the sections of
# such a dictionary are user-visible phrases by definition.
#
# The property set is CURATED. Neither the ui schema nor the metamodel marks a string as
# user-visible - both only say `String` - so the set was read off the schema by hand:
# everything a component or an element SHOWS (a title, a hint, a presentation, a placeholder,
# a message) is in, a technical string (a path, a link, a value field, a code) is out. The
# content property is out as well: on a container it holds markup rather than a phrase, and
# the script inside it is not text anybody reads.

#: Canonical (Russian) names of the properties whose value the user reads. A file may spell
#: them in English - the lookup goes through the schema's canonical form.
_VISIBLE_TEXT_PROPERTIES = frozenset({
    "АльтернативныйТекст", "ВыделенныйТекст",
    "Заголовок", "ЗаголовокАктивного", "ЗаголовокОси", "Заголовки",
    "ЗамещающийТекст", "ЗамещающийТекстПоляПоиска", "Значение",
    "Описание", "ОписаниеСтроки", "Подзаголовок",
    "Подсказка", "ПодсказкаАктивного", "СправочнаяПодсказка",
    "Представление", "ПредставлениеАктивного", "ПредставлениеНеактивного",
    "ПредставлениеГрупповойСтроки", "ПредставлениеОтмеченнойСтроки", "ПредставлениеПоставщика",
    "СообщениеИнформация", "СообщениеОшибка", "СообщениеПредупреждение", "СообщениеУспех",
    "Текст", "ТекстКнопкиЗагрузки", "ТекстНадписи",
    "ШаблонПредставления", "ШаблонПредставленияКонца",
    "ШаблонПредставленияНачала", "ШаблонПредставленияОшибки",
})

#: A value that is not a phrase at all: a binding, a reference to a localized string, an
#: interpolation standing for the whole value.
_NOT_TEXT_PREFIXES = ("=", "$", "%")

#: The word where the letter carries the meaning - "всё" (everything) against "все" (all).
#: Replacing it would change the phrase, so such a finding comes without a fix.
_MEANING_BEARING = frozenset({"всё"})

_WORD_RE = re.compile(r"[^\W\d_]+", re.UNICODE)


def _word_at(text: str, position: int) -> str:
    """The word the character at `position` belongs to - what the message quotes."""
    for m in _WORD_RE.finditer(text):
        if m.start() <= position < m.end():
            return m.group(0)
    return text[position]


def _yo_findings(source: SourceFile, node, judged: set[int]) -> Iterable[Diagnostic]:
    """Every occurrence in one scalar value, judged on the RAW text of the file.

    The raw slice rather than the parsed value: a quoted scalar carries its quotes and its
    escapes, and a fix has to land on the characters that are really in the file.
    """
    if not isinstance(node, yaml.ScalarNode):
        return
    if node.value.lstrip()[:1] in _NOT_TEXT_PREFIXES:
        return
    start = node.start_mark.index
    if start in judged:
        return
    judged.add(start)
    raw = source.text[start:node.end_mark.index]
    for index, ch in enumerate(raw):
        if ch not in "ёЁ":
            continue
        prefix = raw[:index]
        line = node.start_mark.line + 1 + prefix.count("\n")
        column = (
            index - prefix.rfind("\n") if "\n" in prefix
            else node.start_mark.column + 1 + index
        )
        yield _yo_diagnostic(source, raw, index, start + index, line, column)


def _yo_diagnostic(source: SourceFile, raw: str, index: int, offset: int,
                   line: int, column: int) -> Diagnostic:
    """One finding: the word it sits in, and the fix unless the letter carries the meaning."""
    word = _word_at(raw, index)
    if word.lower() in _MEANING_BEARING:
        return Diagnostic(
            source.rel, line, column, "typography/yo-in-text", Severity.INFO,
            i18n.t("typography/yo-in-text.meaning", word=word),
        )
    return Diagnostic(
        source.rel, line, column, "typography/yo-in-text", Severity.INFO,
        i18n.t(
            "typography/yo-in-text.found",
            word=word, suggestion=word.replace("ё", "е").replace("Ё", "Е"),
        ),
        fix=TextEdit(offset, offset + 1, "е" if raw[index] == "ё" else "Е"),
    )


def _yo_in_resource(source: SourceFile) -> Iterable[Diagnostic]:
    """The same letter in a resource file: the text of an SVG or of an HTML page.

    A comment of such a file is left alone - it is prose for the next developer, and there
    the letter is nobody's business; the rule is about what the user reads on the screen.
    """
    text = source.text
    lm = linemap(source)
    for segment in restext.segments(source):
        if segment.kind != restext.TEXT:
            continue
        raw = text[segment.start:segment.end]
        for index, ch in enumerate(raw):
            if ch not in "ёЁ":
                continue
            offset = segment.start + index
            line, column = lm.linecol(offset)
            yield _yo_diagnostic(source, raw, index, offset, line, column)


@rule(
    "typography/yo-in-text", "typography/yo-in-text.title", "B",
    severity=Severity.INFO, enabled_by_default=False, off_reason="typography/yo-in-text.off",
)
def yo_in_text(source: SourceFile) -> Iterable[Diagnostic]:
    """The letter in the text a user reads - the labels, the dictionary, the resource files."""
    text = source.text
    if "ё" not in text and "Ё" not in text:
        return
    if source.kind in restext.KINDS:
        yield from _yo_in_resource(source)
        return
    if source.kind != "yaml" or not _HAVE_YAML:
        return
    root = _composed(source)
    if root is None:
        return
    sections = _all_section_names()
    # One value, one finding: a dictionary entry may be keyed with a word that is also a
    # visible property (`Подсказка:` inside `Строки:`), and the two paths would both reach it.
    judged: set[int] = set()
    for mapping in _mapping_nodes(root):
        for key_node, value_node in mapping.value:
            if not isinstance(key_node, yaml.ScalarNode):
                continue
            if key_node.value in sections and isinstance(value_node, yaml.MappingNode):
                # A dictionary section: every entry of it is a phrase shown to the user.
                for _key, entry in value_node.value:
                    yield from _yo_findings(source, entry, judged)
                continue
            if uischema.canonical_property(key_node.value) in _VISIBLE_TEXT_PROPERTIES:
                yield from _yo_findings(source, value_node, judged)
