"""Tier B: typography in XBSL comments and string literals.

The typography rules:
- dash: en dash – (U+2013), NOT em dash — (U+2014);  scope: prose/comments;
- ellipsis: three dots ..., NOT the … character (U+2026);  scope: prose/comments;
- quotes: straight " (the widest rule – code and comments alike), neither curly nor guillemets;
  EXCEPTION: guillemets «» are fine inside UI strings shown to the user.

Hence:
- the em dash and the ellipsis character are checked in comments only (code strings are left alone);
- curly quotes “ ” ‘ ’ are checked in comments and in strings (allowed nowhere);
- guillemets « » are checked in comments only (they are legitimate in UI strings).

One more rule of the group reads yaml rather than code - typography/yo-in-text, the letter
"ё" in the text a user reads (labels and the dictionary of localized strings). Its own
section comment stands next to it, at the end of this module.
"""

from __future__ import annotations

import re
from collections.abc import Iterable

from xbsl import i18n, uischema
from xbsl.diagnostics import Diagnostic, Severity, TextEdit
from xbsl.engine import SourceFile, rule
from xbsl.lexer import linemap, tokens
from xbsl.rules.localization import _all_section_names
from xbsl.rules.yaml_schema import _composed, _HAVE_YAML, _mapping_nodes

if _HAVE_YAML:
    import yaml

MESSAGES = {
    "typography/em-dash.title": {
        "ru": "Длинное тире в комментарии",
        "en": "Em dash in a comment",
    },
    "typography/em-dash.found": {
        "ru": "Длинное тире U+2014 в комментарии – использовать среднее тире – (U+2013).",
        "en": "Em dash U+2014 in a comment – use an en dash – (U+2013).",
    },
    "typography/ellipsis.title": {
        "ru": "Символ многоточия в комментарии",
        "en": "Ellipsis character in a comment",
    },
    "typography/ellipsis.found": {
        "ru": "Символ многоточия U+2026 в комментарии – использовать три точки '...'.",
        "en": "Ellipsis character U+2026 in a comment – use three dots '...'.",
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
        for idx, ch in enumerate(tok.value):
            if ch in chars:
                offset = tok.start + idx
                line, col = lm.linecol(offset)
                yield ch, line, col, offset


# The em dash and guillemets are all over existing comments, so these two rules are off by
# default and carry severity=info (enable them with --select).
@rule(
    "typography/em-dash", "typography/em-dash.title", "B",
    severity=Severity.INFO, enabled_by_default=False, off_reason="typography/em-dash.off",
)
def em_dash(source: SourceFile) -> Iterable[Diagnostic]:
    if source.kind != "xbsl":
        return
    for _ch, line, col, offset in _hits(source, ("COMMENT",), _EM_DASH):
        yield Diagnostic(
            source.rel, line, col, "typography/em-dash", Severity.INFO,
            i18n.t("typography/em-dash.found"),
            fix=TextEdit(offset, offset + 1, "–"),  # em dash → en dash
        )


@rule("typography/ellipsis", "typography/ellipsis.title", "B", severity=Severity.WARNING)
def ellipsis_char(source: SourceFile) -> Iterable[Diagnostic]:
    if source.kind != "xbsl":
        return
    for _ch, line, col, offset in _hits(source, ("COMMENT",), _ELLIPSIS):
        yield Diagnostic(
            source.rel, line, col, "typography/ellipsis", Severity.WARNING,
            i18n.t("typography/ellipsis.found"),
            fix=TextEdit(offset, offset + 1, "..."),  # … → three dots
        )


@rule("typography/curly-quotes", "typography/curly-quotes.title", "B", severity=Severity.WARNING)
def curly_quotes(source: SourceFile) -> Iterable[Diagnostic]:
    if source.kind != "xbsl":
        return
    for ch, line, col, offset in _hits(source, ("COMMENT", "STRING"), _CURLY):
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
    if source.kind != "xbsl":
        return
    for ch, line, col, offset in _hits(source, ("COMMENT",), _GUILLEMETS):
        yield Diagnostic(
            source.rel, line, col, "typography/guillemets-comment", Severity.INFO,
            i18n.t("typography/guillemets-comment.found", code=f"{ord(ch):04X}"),
            fix=TextEdit(offset, offset + 1, _STRAIGHT[ch]),  # «» → straight " in a comment
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
        word = _word_at(raw, index)
        if word.lower() in _MEANING_BEARING:
            yield Diagnostic(
                source.rel, line, column, "typography/yo-in-text", Severity.INFO,
                i18n.t("typography/yo-in-text.meaning", word=word),
            )
            continue
        yield Diagnostic(
            source.rel, line, column, "typography/yo-in-text", Severity.INFO,
            i18n.t(
                "typography/yo-in-text.found",
                word=word, suggestion=word.replace("ё", "е").replace("Ё", "Е"),
            ),
            fix=TextEdit(start + index, start + index + 1, "е" if ch == "ё" else "Е"),
        )


@rule(
    "typography/yo-in-text", "typography/yo-in-text.title", "B",
    severity=Severity.INFO, enabled_by_default=False, off_reason="typography/yo-in-text.off",
)
def yo_in_text(source: SourceFile) -> Iterable[Diagnostic]:
    """The letter in the text a user reads - the labels and the dictionary of localized strings."""
    if source.kind != "yaml" or not _HAVE_YAML:
        return
    text = source.text
    if "ё" not in text and "Ё" not in text:
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
