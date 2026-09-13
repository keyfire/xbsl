"""Tier B: a condition written with a dash instead of a word of condition (comment/dash-condition).

A comment says "Склад не задан - берется основной склад", and the reader has to work out whether
the dash joins a condition to its consequence or explains a value: "Пусто - склад свободен" is
the legend of an empty value, the line before it is a condition in disguise. A condition is said
with its own word - "Если склад не задан, берется основной склад".

The shape the rule judges, each narrowing measured on real projects:

- the sentence splits on its FIRST dash - a hyphen, an en dash or an em dash - with spaces
  around it;
- the left part is short - up to six words outside brackets - carries no verb of its own and
  ENDS with a state: not set, empty, absent, not found, expired, equal, changed, arrived,
  ready and the like (`NEGATIVE_STATES`, `POSITIVE_STATES`). A switch - "включен", "выключен",
  "отключен" - is not a state here: on the corpus of a project every sentence with one before
  the dash described a setting of the object ("Автонумерация отключена - код задает импорт");
- the left part names a SUBJECT before the state. A bare "Не задан - берется основной" is the
  legend of one value in a list of values ("Задан - ...; не задан - ..."), and a project that
  went through a style edit of its comments kept every such legend while it rewrote the
  conditions around them;
- the right part carries a verb - a personal or a reflexive form by its ending; an infinitive,
  a participle and a short adjective ("свободен", "занят") do not count - or says "нет"
  ("Склад не задан - остатка нет") or "иначе". The two words are where the task of the rule
  and the letter of a verb part ways: the same style edit rewrote such sentences as conditions;
- "нет" closing the left part counts only with "иначе" on the right. Without the other branch
  "У склада адреса нет - ..." describes the design far more often than it opens a condition;
- the sentence is not conditional already - no "если", "когда", "пока", "в случае" in the left
  part - and states nothing that holds always ("всегда", "тоже", "также");
- the left part carries no quotes, code operators, paths or placeholders, and the right part
  no `=`: "ничего не выбрано - слот 1 = ..." is the legend of an encoding.

Judged are the comments of a module, of an element description and of a resource file, the
lines `_comments.lines` gives. The lines are joined into paragraphs first, because a condition
often starts on one comment line and meets its dash on the next: line comments on consecutive
lines of their own, a block comment, one comment of a resource file.

No fix is attached. Whether the dash follows a condition or states a fact of the design ("the
numbering is off - the import sets the code") is a matter of meaning, while `--fix` applies
every attached edit at once; the engine attaches only unambiguous edits (see `xbsl/fixer.py`).
The finding carries the suggested wording instead.
"""

from __future__ import annotations

import re
from bisect import bisect_right
from collections.abc import Iterable
from dataclasses import dataclass, field

from xbsl import i18n, restext
from xbsl.diagnostics import Diagnostic, Severity
from xbsl.engine import SourceFile, rule
from xbsl.lexer import linemap
from xbsl.rules import _comments

MESSAGES = {
    "comment/dash-condition.title": {
        "ru": "Условие через тире в комментарии",
        "en": "Condition written with a dash in a comment",
    },
    "comment/dash-condition.found": {
        "ru": "Условие записано через тире: \"{left} - ...\" читается как пояснение к значению. "
              "Перепишите со словом условия (\"если\", \"когда\"): \"{suggestion}\".",
        "en": "A condition written with a dash: \"{left} - ...\" reads as the legend of a value. "
              "Rewrite it with a word of condition (if, when): \"{suggestion}\".",
    },
    "comment/dash-condition.off": {
        "ru": "соглашение ПРОЕКТА о слоге комментариев, а не ошибка кода: условие перед тире "
              "или пояснение к значению, решает смысл фразы. Проект включает группу `comment` "
              "в своём CI (--enable comment)",
        "en": "a PROJECT convention about the wording of comments rather than a code error: "
              "whether the dash follows a condition or explains a value is a matter of meaning. "
              "A project turns the `comment` group on in its CI (--enable comment)",
    },
}
i18n.register(MESSAGES)


# --- the comments of a file, as paragraphs -------------------------------------------------

#: A list item at the start of a comment line: a bullet or a number.
_BULLET = re.compile(r"^[-*\u2022]\s+")
_NUMBERED = re.compile(r"^\d+[.)]\s+")
#: What ends a sentence at the end of a line.
_LINE_END_TERMINATOR = re.compile(r"[.:;!?)]$")
#: The marker a comment line opens with - `//`, `/*`, the `*` of a block comment, `#` - with the
#: spaces after it. A list bullet is kept: it tells a list item from a wrapped sentence.
_OPEN = re.compile(r"^\s*(?://+|/\*+|#+|\*+(?!/))?[ \t]*")
#: The marker a block comment closes with, and the spaces around it.
_CLOSE = re.compile(r"[ \t]*(?:\*+/)?\s*$")


@dataclass
class Paragraph:
    """The prose of one comment block: its lines joined with a space, plus the map back.

    Piece i covers `text[starts[i]:...]` and begins at `offsets[i]` in the file. `breaks` holds
    the indexes of `text` where a list item starts, so that a sentence never runs into it.
    """

    text: str
    starts: list[int]
    offsets: list[int]
    breaks: list[int] = field(default_factory=list)

    def offset(self, index: int) -> int:
        """The file offset of `text[index]`."""
        i = max(0, bisect_right(self.starts, index) - 1)
        return self.offsets[i] + (index - self.starts[i])


def _paragraph(pieces: list[tuple[int, str]]) -> Paragraph | None:
    """One paragraph out of (file offset, text) pieces; None when there is no prose.

    A bullet line is a list item when the line before it has ended its sentence or when the
    paragraph already is a list; otherwise the bullet is a dash moved to the start of the line
    by the wrapping, and the two lines stay one sentence.
    """
    pieces = [(offset, text) for offset, text in pieces if text]
    if not pieces:
        return None
    starts: list[int] = []
    offsets: list[int] = []
    breaks: list[int] = []
    parts: list[str] = []
    position = 0
    in_list = False
    for offset, text in pieces:
        if parts:
            numbered = _NUMBERED.match(text) is not None
            bullet = _BULLET.match(text) is not None
            if numbered or (bullet and (in_list or _LINE_END_TERMINATOR.search(parts[-1]))):
                breaks.append(position)
                in_list = True
        starts.append(position)
        offsets.append(offset)
        parts.append(text)
        position += len(text) + 1
    return Paragraph(" ".join(parts), starts, offsets, breaks)


def _prose(line: _comments.CommentLine) -> tuple[int, str]:
    """(file offset, text) of the prose of a comment line: the markers and the edge spaces cut."""
    raw = line.text
    start = _OPEN.match(raw).end()
    end = max(start, _CLOSE.search(raw).start())
    return line.offset + start, raw[start:end]


def _blocks(source: SourceFile) -> list[list[tuple[int, str]]]:
    """The comment lines of the file grouped into the pieces of paragraphs.

    Line comments of a module and `#` comments of an element description on consecutive lines
    of their own form one block; a comment after code or after a value stands alone. A block
    comment is a block, and so is one comment of a resource file.
    """
    text = source.text
    resource = source.kind in restext.KINDS
    segment_starts: list[int] = []
    if resource:
        segment_starts = [s.start for s in restext.segments(source) if s.kind == restext.COMMENT]
    blocks: list[list[tuple[int, str]]] = []
    run: list[tuple[int, str]] = []
    run_end_line = -1  # the line a run of own-line comments has reached; -1 when none goes on
    run_segment = -1
    in_block = False  # inside a block comment of a module
    for line in _comments.lines(source):
        piece = _prose(line)
        if resource:
            segment = bisect_right(segment_starts, line.offset) - 1
            if run and segment != run_segment:
                blocks.append(run)
                run = []
            run.append(piece)
            run_segment = segment
            continue
        head = line.text.lstrip()
        if in_block or (source.kind == "xbsl" and head.startswith("/*")):
            if not in_block and run:
                blocks.append(run)
                run = []
            run.append(piece)
            in_block = not line.text.rstrip().endswith("*/")
            if not in_block:
                blocks.append(run)
                run = []
            run_end_line = -1
            continue
        line_start = text.rfind("\n", 0, line.offset) + 1
        own_line = not text[line_start:line.offset].strip()
        if run and not (own_line and line.line == run_end_line + 1):
            blocks.append(run)
            run = []
        run.append(piece)
        run_end_line = line.line if own_line else -1
    if run:
        blocks.append(run)
    return blocks


def comment_paragraphs(source: SourceFile) -> list[Paragraph]:
    """The comments of the file as paragraphs of prose - a module, a yaml or a resource file."""
    paragraphs = (_paragraph(block) for block in _blocks(source))
    return [p for p in paragraphs if p is not None]


# --- the verb heuristic --------------------------------------------------------------------

#: Endings only a verb has: the reflexive present, the present of the productive classes in the
#: third person and in the first person plural, the reflexive past.
_STRONG_VERB = re.compile(
    r"(?:[её]тся|[ая]тся|ится|утся|ются|ает|яет|ует|еет|ают|яют|уют|еют|аем|яем|уем"
    r"|лся|лась|лось|лись)$"
)
#: Endings a verb shares with nouns, pronouns and short participles (`берет`/`макет`,
#: `стоит`/`лимит`, `занят`): a word with one of them counts outside the stop list only.
_WEAK_VERB = re.compile(r"(?:[её]т|ит|ат|ят|ут|ют)$")
#: First person plural forms with an ending shared by instrumental nouns (`берем`/`полем`):
#: listed rather than guessed.
_FIRST_PERSON_VERBS = frozenset("""
берем берём идем идём ждем ждём ведем ведём несем несём кладем кладём шлем шлём зовем зовём
пишем ищем режем ставим храним выводим уходим переходим находим проходим
""".split())
#: Words with a verb-like ending that are not verbs.
_NOT_A_VERB = frozenset("""
объект субъект пакет кабинет бюджет билет комплект сюжет проект аспект эффект дефект макет
отчет отчёт учет учёт счет счёт расчет расчёт пересчет пересчёт подсчет подсчёт зачет запрет
секрет интернет планшет виджет гаджет сокет тикет бакет приоритет паритет комитет иммунитет
авторитет университет факультет предмет силуэт скелет портрет трафарет паркет букет свет цвет
ответ совет привет лет нет полет полёт самолет самолёт переплет переплёт анкет газет монет
кассет ракет примет планет конфет котлет карет
лимит кредит визит транзит реквизит аудит дефицит композит магнит гранит алфавит колорит
бит плит орбит защит элит
формат результат автомат плакат сертификат штат адресат аппарат дубликат кандидат агрегат
делегат мандат предикат квадрат чат аромат концентрат суррогат адвокат салат халат брат
пират домкрат примат
занят взят принят снят понят поднят отнят сжат нажат зажат ребят котят опят
маршрут институт минут атрибут абсолют парашют батут статут лоскут мазут редут тут
валют салют уют приют кают
""".split())

#: A word of a sentence: letters only, so that a hyphen and an apostrophe split words.
_WORD = re.compile(r"[А-Яа-яЁё]+")


def _identifier_like(word: str) -> bool:
    return any(a.islower() and b.isupper() for a, b in zip(word, word[1:]))


def _is_verb(word: str) -> bool:
    if _identifier_like(word) or (len(word) > 1 and word[:2].isupper()):
        return False  # a name from the code, an abbreviation
    low = word.lower()
    if low in _NOT_A_VERB:
        return False
    if low in _FIRST_PERSON_VERBS or _STRONG_VERB.search(low):
        return True
    # A shared ending is trusted on a lowercase word of some length only: a capitalised one is a
    # name more often than a verb, and a three-letter word is `нет` or `тут`.
    return len(low) >= 4 and word.islower() and _WEAK_VERB.search(low) is not None


def _has_verb(text: str) -> bool:
    return any(_is_verb(word) for word in _WORD.findall(text))


# --- the condition shape -------------------------------------------------------------------

#: States of absence and failure: what the left part of a dashed condition ends with.
NEGATIVE_STATES = (
    r"не задан[аоы]?", r"не указан[аоы]?", r"не заполнен[аоы]?", r"не найден[аоы]?",
    r"не выбран[аоы]?", r"не установлен[аоы]?", r"не определ[её]н[аоы]?", r"не получен[аоы]?",
    r"не загружен[аоы]?", r"не передан[аоы]?", r"не прочитан[аоы]?", r"не записан[аоы]?",
    r"не создан[аоы]?", r"не подтвержд[её]н[аоы]?", r"не отмечен[аоы]?",
    r"не пуст(?:[аоы]|ой|ая|ое|ые)?", r"пуст(?:[аоы]|ой|ая|ое|ые)?", r"снят[аоы]?",
    r"отсутству(?:ет|ют)", r"недоступ(?:ен|на|но|ны)",
    r"не ответил[аио]?", r"не отвеча(?:ет|ют)", r"не совпада(?:ет|ют)", r"не совпал[аио]?",
    r"не удал(?:ся|ась|ось|ись)", r"не удалось", r"не сработал[аио]?", r"не прош(?:[её]л|л[аио])",
    r"не приш(?:[её]л|л[аио])", r"ист[её]к(?:ла|ло|ли)?", r"не изменил(?:ся|ась|ось|ись)",
    r"не готов[аоы]?", r"не рав(?:ен|на|но|ны)", r"не нашл(?:ось|ся|ась|ись)",
)
#: States of presence and change - a value that is set, has arrived, has changed.
POSITIVE_STATES = (
    r"задан[аоы]?", r"указан[аоы]?", r"заполнен[аоы]?", r"найден[аоы]?", r"выбран[аоы]?",
    r"есть", r"рав(?:ен|на|но|ны)", r"больше", r"меньше", r"совпада(?:ет|ют)",
    r"изменил(?:ся|ась|ось|ись)", r"приш[её]л", r"пришл[аио]", r"готов[аоы]?",
    r"загружен[аоы]?", r"получен[аоы]?",
)
#: The word "нет" at the end of the left part. Judged only with "иначе" on the right: without
#: the other branch "X нет - Y" describes the design far more often than it opens a condition.
ABSENCE = (r"нет",)


def _state_pattern(states: Iterable[str]) -> re.Pattern[str]:
    return re.compile(r"(?:^|\s)(" + "|".join(states) + r")$", re.I)


_STATE_AT_END = _state_pattern(NEGATIVE_STATES + POSITIVE_STATES)
_ABSENCE_AT_END = _state_pattern(ABSENCE)
#: The sentence is conditional already - the dash is a matter of punctuation, not of the form.
_CONDITIONAL = re.compile(
    r"(?:^|\s)(?:если|когда|пока|коли|раз|иначе|случа[а-я]*)(?=\s|$)", re.I
)
#: A state that holds always, or in addition to something, is a fact rather than a condition.
_STATEMENT = re.compile(r"(?:^|\s)(?:всегда|тоже|также)(?=\s|$)", re.I)
#: A right part without a verb still names a consequence when it says "нет" or "иначе".
_PREDICATE = re.compile(r"(?:^|\s)(?:нет|иначе)(?=[\s,.;:!?]|$)", re.I)
_ELSE = re.compile(r"(?:^|\s)иначе(?=[\s,.;:!?]|$)", re.I)
#: The dash the sentence splits on: a hyphen, an en dash or an em dash, spaces around it.
_DASH = re.compile("[ \\t]+[-\u2013\u2014][ \\t]+")
#: Where a sentence ends inside a paragraph: a terminator followed by a space.
_SENTENCE_END = re.compile(r"[.;:!?](?=\s)")
#: What a left part must not carry: quotes, code operators, a path, a placeholder.
_NOT_PROSE = re.compile("[=<>\"'`\u00ab\u00bb{}/\\\\|]")
#: Words that do not make a subject on their own.
_NOT_A_SUBJECT = frozenset({"не", "и", "а", "или", "но", "то", "же", "уже", "еще", "ещё", "все", "всё"})
_BRACKETED = re.compile(r"\([^()]*\)")
#: Quoted text: a value or a name, whose words say nothing about the sentence around them.
_QUOTED = re.compile("\"[^\"]*\"|\u00ab[^\u00bb]*\u00bb|`[^`]*`")

MAX_LEFT_WORDS = 6


def _sentences(paragraph: Paragraph) -> Iterable[tuple[int, int, str]]:
    """(start, end, what precedes it) of every sentence of the paragraph."""
    text = paragraph.text
    cuts = [(m.end(), m.group(0)) for m in _SENTENCE_END.finditer(text)]
    cuts += [(index, "\n") for index in paragraph.breaks]
    start, before = 0, ""
    for end, mark in sorted(cuts):
        if end > start:
            yield start, end, before
        start, before = end, mark
    if len(text) > start:
        yield start, len(text), before


def _lower_first(left: str) -> str:
    """The left part after the word of condition: a capital of the sentence start goes down, a
    name from the code keeps its case."""
    first = left.split()[0]
    if _identifier_like(first) or (len(first) > 1 and first[:2].isupper()):
        return left
    return left[0].lower() + left[1:]


def judge(sentence: str) -> tuple[str, str, int] | None:
    """(left, right, left start in the sentence) when the sentence is a dashed condition."""
    body = sentence.lstrip()
    marker = _NUMBERED.match(body) or _BULLET.match(body)
    if marker:
        body = body[marker.end():]
    if body.startswith("("):
        body = body[1:].lstrip()
    lead = len(sentence) - len(body)
    dash = _DASH.search(body)
    if dash is None:
        return None
    left = body[:dash.start()].rstrip(",")
    right = body[dash.end():].strip()
    if not left or not right or _NOT_PROSE.search(left) or left.count("(") != left.count(")"):
        return None
    if len(_BRACKETED.sub(" ", left).split()) > MAX_LEFT_WORDS:
        return None
    if _CONDITIONAL.search(left) or _STATEMENT.search(left):
        return None
    state = _STATE_AT_END.search(left)
    absence = state is None
    if absence:
        state = _ABSENCE_AT_END.search(left)
        if state is None:
            return None
    subject = _BRACKETED.sub(" ", left[:state.start()]).strip()
    words = subject.split()
    if not words or all(w.lower() in _NOT_A_SUBJECT for w in words):
        return None
    if not subject[0].isalpha() or _has_verb(subject):
        return None
    # The consequence is read outside brackets and quotes; a value written with `=` makes the
    # sentence the legend of an encoding ("ничего не выбрано - слот 1 = ...").
    consequence = _QUOTED.sub(" ", _BRACKETED.sub(" ", right))
    if "=" in consequence:
        return None
    if absence:
        if not _ELSE.search(consequence):
            return None
    elif not (_has_verb(consequence) or _PREDICATE.search(consequence)):
        return None
    return left, right, lead


def findings(source: SourceFile) -> Iterable[tuple[int, str, str, str]]:
    """(file offset, left, right, what precedes the sentence) of every dashed condition."""
    for paragraph in comment_paragraphs(source):
        for start, end, before in _sentences(paragraph):
            verdict = judge(paragraph.text[start:end])
            if verdict is not None:
                left, right, lead = verdict
                yield paragraph.offset(start + lead), left, right, before


def _short(text: str, limit: int = 120) -> str:
    return text if len(text) <= limit else text[:limit].rstrip() + "..."


@rule(
    "comment/dash-condition", "comment/dash-condition.title", "B",
    severity=Severity.WARNING, enabled_by_default=False, off_reason="comment/dash-condition.off",
)
def dash_condition(source: SourceFile) -> Iterable[Diagnostic]:
    """A dashed condition in a comment; see the module docstring for the shape."""
    if _DASH.search(source.text) is None:
        return
    lm = linemap(source)
    for offset, left, right, before in findings(source):
        line, col = lm.linecol(offset)
        # A new sentence takes a capital; after a colon or a semicolon the clause goes on in
        # lower case, as the author's own text does.
        word = "если" if before in (":", ";") else "Если"
        yield Diagnostic(
            source.rel, line, col, "comment/dash-condition", Severity.WARNING,
            i18n.t(
                "comment/dash-condition.found",
                left=_short(left, 60), suggestion=_short(f"{word} {_lower_first(left)}, {right}"),
            ),
        )
