"""Documentation comment tags: the `///` block of a declaration, read as the environment reads it.

The development environment shows the `///` lines that stand right before a declaration in
its hover, in the signature help and in the completion (the documentation topic
`topics/documentation-comments`). Inside the block it knows four tags, each in two spellings:
`@параметр`/`@parameter`, `@возвращает`/`@returns`, `@выбрасывает`/`@throws` and `@см`/`@see`.
The text above the first tag is the description, and a tag runs to the next line that starts
with `@`.

Two readings of one block live here, and they answer different questions.

`environment_model` is a port of the parser of the environment itself: the marker `///` and
one space come off every line, the description is the text up to the first line that starts
with `@`, and then each kind of tag is cut out of the rest by its own regular expression,
parameters first. The port keeps the quirks, since a reader of the hover meets exactly them:

- a tag on the FIRST line of the block is taken for the description - the pattern of the
  description stops only at a line break followed by `@`;
- the name of a parameter or an exception is read with the class `[A-Za-zА-Яа-я0-9еЁ]`, so
  an underscore, a dot or a lowercase `ё` ends it, and the rest of the word lands in the text;
- a word after `@` that is none of the eight spellings is no tag: the description ends on
  its line, and the line itself shows nowhere;
- the dash between a name and its text is an optional hyphen-minus; any other dash stays in
  the text.

The editor renders this model (`render_markdown`), so the hover of the toolkit shows what the
environment would show.

`parse` reads the same lines one by one and keeps positions: which line a tag starts on,
where its name and its text begin, what the author evidently meant. The rules of
`comment/doc-tag-*` judge by it - a finding is a place where the environment would show
something other than what the author wrote.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

#: The tags by kind, each with its Russian and English keyword (without `@`), as the
#: environment spells them.
TAGS: dict[str, tuple[str, str]] = {
    "param": ("параметр", "parameter"),
    "returns": ("возвращает", "returns"),
    "throws": ("выбрасывает", "throws"),
    "see": ("см", "see"),
}
#: The order of the sections of the hover, which is also the order the tags are written in.
ORDER: tuple[str, ...] = ("param", "returns", "throws", "see")
#: A keyword -> the kind of its tag.
KIND_OF: dict[str, str] = {word: kind for kind, pair in TAGS.items() for word in pair}
#: The tags that take a name before their text: a parameter and the type of an exception.
NAMED: frozenset[str] = frozenset({"param", "throws"})
#: The characters of a name the environment reads after a naming tag.
NAME_CLASS = "A-Za-zА-Яа-я0-9еЁ"

#: The headings of the sections of the hover, by language.
_HEADINGS: dict[str, dict[str, str]] = {
    "ru": {"param": "Параметры", "returns": "Возвращает", "throws": "Выбрасывает",
           "see": "Смотреть также"},
    "en": {"param": "Parameters", "returns": "Returns", "throws": "Throws", "see": "See also"},
}


def keyword(kind: str, lang: str) -> str:
    """The keyword of a kind of tag in a language (`ru` or `en`), without `@`."""
    russian, english = TAGS[kind]
    return english if lang == "en" else russian


# --- the environment's reading -------------------------------------------------------------

#: `\s` of the environment's regular expressions: the six ASCII blanks, not the Unicode ones.
_S = r"[ \t\n\x0b\f\r]"
#: Any text up to a line break followed by `@` - the extent of the description and of a tag.
_UNTIL_TAG = r"(?s:(?!\r?\n" + _S + r"*@).)*"
_PREFIX_RE = re.compile(r"^" + _S + r"*///" + _S + r"?")
_DESCRIPTION_RE = re.compile(r"\A(" + _UNTIL_TAG + r")")


def _tag_re(kind: str) -> re.Pattern[str]:
    russian, english = TAGS[kind]
    head = "(@" + re.escape(english) + "|@" + re.escape(russian) + ")"
    if kind in NAMED:
        return re.compile(
            head + _S + "*([" + NAME_CLASS + "]+)" + _S + "*-?" + _S + "*(" + _UNTIL_TAG + ")"
        )
    return re.compile(head + _S + "+(" + _UNTIL_TAG + ")")


_TAG_RES: dict[str, re.Pattern[str]] = {kind: _tag_re(kind) for kind in ORDER}


@dataclass(frozen=True)
class EnvironmentDoc:
    """What the environment makes of a block: the parts its hover is built from."""

    description: str
    params: tuple[tuple[str, str], ...]
    returns: str
    throws: tuple[tuple[str, str], ...]
    see: tuple[str, ...]

    def param(self, name: str) -> str | None:
        """The text of the first `@параметр` with this name, or None."""
        return next((text for written, text in self.params if written == name), None)


def strip_marker(line: str) -> str:
    """A `///` line without the marker and one blank after it - the environment's own cut."""
    return _PREFIX_RE.sub("", line, count=1)


def environment_model(text: str) -> EnvironmentDoc:
    """The block as the environment reads it; `text` is its lines without the marker, joined
    by line breaks (`strip_marker` gives the lines)."""
    match = _DESCRIPTION_RE.match(text)
    description = match.group(1) if match else ""
    rest = text[match.end():] if match else text
    found: dict[str, list] = {kind: [] for kind in ORDER}
    for kind in ORDER:
        # Every match is cut out of the rest, the way the environment's replaceAll does, so a
        # later kind never sees what an earlier one took.
        def cut(m: re.Match[str], bucket: list = found[kind], named: bool = kind in NAMED) -> str:
            bucket.append((m.group(2), m.group(3)) if named else m.group(2))
            return ""
        rest = _TAG_RES[kind].sub(cut, rest.lstrip())
    return EnvironmentDoc(
        description, tuple(found["param"]), "".join(found["returns"]),
        tuple(found["throws"]), tuple(found["see"]),
    )


def render_markdown(model: EnvironmentDoc, lang: str = "ru") -> str:
    """The hover text of a block: the description, then a section per kind of tag.

    The layout follows the environment's own card: a bold heading per section, parameters and
    exceptions as a list of "**Name** - text". Empty when the block says nothing.
    """
    headings = _HEADINGS.get(lang, _HEADINGS["ru"])
    parts: list[str] = []
    if model.description.strip():
        parts.append(model.description.strip())

    def listed(pairs: tuple[tuple[str, str], ...]) -> str:
        return "\n".join(
            f"- **{name}**" + (f" - {text.strip()}" if text.strip() else "") for name, text in pairs
        )

    if model.params:
        parts.append(f"**{headings['param']}:**\n\n" + listed(model.params))
    if model.returns.strip():
        parts.append(f"**{headings['returns']}:** {model.returns.strip()}")
    if model.throws:
        parts.append(f"**{headings['throws']}:**\n\n" + listed(model.throws))
    seen = [text.strip() for text in model.see if text.strip()]
    if len(seen) == 1:
        parts.append(f"**{headings['see']}:** {seen[0]}")
    elif seen:
        parts.append(f"**{headings['see']}:**\n\n" + "\n".join(f"- {text}" for text in seen))
    return "\n\n".join(parts)


# --- the author's reading ------------------------------------------------------------------

#: The line of a tag: a blank or two, `@`, the keyword as written, the rest of the line.
_TAG_LINE_RE = re.compile(r"^(\s*)@(\S*)(.*)$", re.S)
#: A name as the author wrote it after a naming tag: a word, possibly qualified by dots or
#: colons (`Модуль.Ошибка`, `Пакет::Тип`), without the punctuation after it.
_WRITTEN_NAME_RE = re.compile(r"\w+(?:(?:\.|::)\w+)*")
_ENV_NAME_RE = re.compile("[" + NAME_CLASS + "]+")
#: The dashes an author may put between a name and its text; only the first one is the
#: environment's separator.
DASHES = "-\u2013\u2014"


@dataclass(frozen=True)
class DocLine:
    """One `///` line: where its text starts in the file and what the text is."""

    line: int  # 1-based line of the file
    column: int  # 1-based column of `text[0]`
    offset: int  # character offset of `text[0]` in the file
    text: str  # the line without the marker and one blank after it


@dataclass(frozen=True)
class Tag:
    """One line of a block that starts with `@`, with the lines that continue it."""

    kind: str | None  # a kind of TAGS; None for a word after `@` that is no tag
    keyword: str  # the word after `@`, as written
    index: int  # the index of the line of the tag in DocBlock.lines
    last: int  # the index of its last line: the continuation lines count
    keyword_at: int  # where `@` stands in the text of its line
    name: str = ""  # the name after a naming tag, as written; "" when there is none
    name_at: int = -1  # where the name stands in the text of the line of the tag
    dash: str = ""  # the dash between the name and the text, "" without one
    dash_at: int = -1  # where that dash stands in the text of the line
    text: str = ""  # the text of the tag, continuation lines joined by line breaks
    text_at: int = -1  # where the text starts in the line of the tag

    @property
    def environment_name(self) -> str:
        """The part of the written name the environment keeps as the name."""
        found = _ENV_NAME_RE.match(self.name)
        return found.group(0) if found else ""


@dataclass(frozen=True)
class DocBlock:
    """A `///` block: its lines and the tags written in it."""

    lines: tuple[DocLine, ...]
    tags: tuple[Tag, ...]

    @property
    def description_end(self) -> int:
        """The index of the first line of a tag, the number of lines when there is none."""
        return self.tags[0].index if self.tags else len(self.lines)

    def text(self) -> str:
        return "\n".join(line.text for line in self.lines)

    def model(self) -> EnvironmentDoc:
        return environment_model(self.text())


def is_tag_line(text: str) -> bool:
    """Whether a line of a block (marker off) opens a tag for the environment."""
    return text.lstrip(" \t\x0b\f").startswith("@")


def _tag(lines: tuple[DocLine, ...], index: int, last: int) -> Tag:
    text = lines[index].text
    head = _TAG_LINE_RE.match(text)
    assert head is not None  # only lines that is_tag_line accepts come here
    at = len(head.group(1))
    word = head.group(2)
    rest_at = at + 1 + len(word)
    kind = KIND_OF.get(word)
    continuation = [line.text for line in lines[index + 1:last + 1]]
    rest = text[rest_at:]
    if kind in NAMED:
        blanks = len(rest) - len(rest.lstrip())
        name_match = _WRITTEN_NAME_RE.match(rest, blanks)
        if name_match is None:
            body_at = rest_at + blanks
            return Tag(kind, word, index, last, at, text_at=body_at,
                       text="\n".join([text[body_at:], *continuation]))
        name = name_match.group(0)
        name_at = rest_at + name_match.start()
        after = name_match.end()
        tail = rest[after:]
        body = after + len(tail) - len(tail.lstrip())
        dash, dash_at = "", -1
        if body < len(rest) and rest[body] in DASHES:
            dash, dash_at = rest[body], rest_at + body
            body += 1
            tail = rest[body:]
            body += len(tail) - len(tail.lstrip())
        body_at = rest_at + body
        return Tag(kind, word, index, last, at, name=name, name_at=name_at, dash=dash,
                   dash_at=dash_at, text="\n".join([text[body_at:], *continuation]),
                   text_at=body_at)
    body_at = rest_at + len(rest) - len(rest.lstrip())
    return Tag(kind, word, index, last, at, text="\n".join([text[body_at:], *continuation]),
               text_at=body_at)


def parse(lines: list[DocLine] | tuple[DocLine, ...]) -> DocBlock:
    """The block of these lines, read line by line (see the module docstring)."""
    frozen = tuple(lines)
    starts = [i for i, line in enumerate(frozen) if is_tag_line(line.text)]
    tags = tuple(
        _tag(frozen, start, (starts[k + 1] if k + 1 < len(starts) else len(frozen)) - 1)
        for k, start in enumerate(starts)
    )
    return DocBlock(frozen, tags)


def doc_line(line: int, column: int, offset: int, raw: str) -> DocLine:
    """The DocLine of a comment line that starts at (line, column, offset) with `raw`."""
    cut = len(raw) - len(strip_marker(raw))
    return DocLine(line, column + cut, offset + cut, raw[cut:])
