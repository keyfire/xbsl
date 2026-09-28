"""The tags of a documentation comment, judged against what the environment will show.

A `///` block before a declaration names the parameters, the result, the exceptions and the
related names of a method with four tags (`xbsl/doctags.py` reads them). The environment builds
its hover, its signature help and its completion from them, and it is strict in a way the
author does not see while writing: a tag with a misspelled keyword vanishes together with its
line, a tag on the first line becomes the description, a name with an underscore is cut, a
parameter the method no longer has is described all the same. The rules below report the
places where the hover would show something other than what the block says.

- `comment/doc-tag-unknown` - a line that starts with `@` and is none of the tags: `@param`,
  `@Параметр`, an annotation copied into the text. The line never reaches the hover, and
  neither do the lines that continue it. A keyword spelled in another case, or `@param`,
  `@return`, `@throw`, `@exception`, is respelled by the fix, in the language of the module.
- `comment/doc-tag-layout` - where the tags stand in the block: a tag on the first line (the
  environment takes it for the description), a paragraph after the last tag (glued to that
  tag), no blank line between the description and the tags (the fix inserts it - that is how
  the environment's own template writes a block), the kinds out of the order the hover shows
  them in, a tag without its text, a dash other than a hyphen-minus after a name (the fix
  puts a hyphen there).
- `comment/doc-tag-param` - `@параметр` against the signature below it: a name the method does
  not have, a name described twice or out of the order of the signature, a name the
  environment cuts, a tag above a declaration that takes no parameters, and a method whose
  parameters are described only in part - the section with gaps reads as an oversight, so
  they are described all or none, the way the environment's template lists them.
- `comment/doc-tag-result` - `@возвращает` above a method with no result, or twice (the hover
  glues the two texts without a blank), and `@выбрасывает` with a type name the environment
  cuts (a qualified name ends on its first dot); both above a declaration that is no method.
- `comment/doc-tag-target` - the names the tags point at, against the whole project and the
  platform: an `@см` reference written as a name or a chain of names (`Модуль.Метод`) that
  leads nowhere, and an `@выбрасывает` type nobody declares. A reference written as a phrase
  ("@см Раздел о ценах") is prose and is not judged, and neither is a single word in lowercase
  or in the other script of the project (a name of something outside it). The finding for an
  unknown exception lists the types the method body throws.

A structure, an exception and a constructor are not judged by the param and result rules:
what their tags would mean to the environment is not established, and a guess would be a
false finding.
"""

from __future__ import annotations

import dataclasses
import difflib
import re
from collections.abc import Iterable, Iterator
from functools import lru_cache

from xbsl import dataset, doctags, i18n, libs
from xbsl.diagnostics import Diagnostic, Severity, TextEdit
from xbsl.engine import SourceFile, rule
from xbsl.lexer import Token, tokens
from xbsl.parser import (
    Constructor, Enum, EnumItem, Method, New, ObjectField, Structure, Throw, parse,
)
from xbsl.rules.comment_doc_marker import documented_declarations
from xbsl.rules.comment_names import _platform_names
from xbsl.rules.semantics import _stdlib_names
from xbsl.rules.yaml_schema import (
    _HAVE_YAML, declaration_names_fast, is_translation_dictionary, object_name_fast,
)

MESSAGES = {
    "comment/doc-tag-unknown.title": {
        "ru": "Строка с @, которую среда разработки не читает как тег",
        "en": "A line starting with @ that the environment does not read as a tag",
    },
    "comment/doc-tag-unknown.case": {
        "ru": "Среда разработки узнает тег только в написании строчными буквами: \"@{written}\" "
              "для нее не тег, и эта строка вместе с продолжением в подсказку не попадет. "
              "Напишите \"@{right}\".",
        "en": "The environment recognizes a tag only in lowercase: \"@{written}\" is no tag to "
              "it, and this line with its continuation never reaches the hover. Write "
              "\"@{right}\".",
    },
    "comment/doc-tag-unknown.alias": {
        "ru": "Среда разработки не знает тега \"@{written}\": эта строка вместе с продолжением "
              "в подсказку не попадет. Здесь нужен \"@{right}\".",
        "en": "The environment knows no tag \"@{written}\": this line with its continuation "
              "never reaches the hover. Write \"@{right}\" here.",
    },
    "comment/doc-tag-unknown.found": {
        "ru": "Строка начинается с \"@{written}\", а такого тега среда разработки не знает: эта "
              "строка вместе с продолжением в подсказку не попадет. Теги - @параметр, "
              "@возвращает, @выбрасывает и @см (@parameter, @returns, @throws, @see). Если "
              "\"@\" - часть текста, уберите его из начала строки.",
        "en": "The line starts with \"@{written}\", and the environment knows no such tag: this "
              "line with its continuation never reaches the hover. The tags are @parameter, "
              "@returns, @throws and @see, or their Russian spellings. If \"@\" is part of the "
              "text, move it off the start of the line.",
    },
    "comment/doc-tag-layout.title": {
        "ru": "Теги документирующего комментария стоят не на своем месте",
        "en": "Documentation comment tags out of place",
    },
    "comment/doc-tag-layout.first-line": {
        "ru": "Блок начинается с тега \"@{keyword}\": первую строку блока среда разработки "
              "берет за описание, и в разделы подсказки этот тег не попадет. Начните блок "
              "строкой описания.",
        "en": "The block starts with the tag \"@{keyword}\": the environment takes the first "
              "line of a block for the description, and this tag never reaches the sections of "
              "the hover. Start the block with a line of description.",
    },
    "comment/doc-tag-layout.after-tags": {
        "ru": "Абзац после тегов среда разработки приклеит к тегу \"@{keyword}\": описанием "
              "считается только текст до первого тега. Перенесите абзац выше тегов.",
        "en": "The environment glues a paragraph after the tags to the tag \"@{keyword}\": only "
              "the text above the first tag is the description. Move the paragraph above the "
              "tags.",
    },
    "comment/doc-tag-layout.no-blank": {
        "ru": "Между описанием и тегами нет пустой строки \"///\": так блок пишет шаблон самой "
              "среды разработки, и так описание не сливается с тегами в тексте модуля.",
        "en": "No blank \"///\" line between the description and the tags: that is how the "
              "environment's own template writes a block, and it keeps the description apart "
              "from the tags in the module text.",
    },
    "comment/doc-tag-layout.order": {
        "ru": "Тег \"@{keyword}\" стоит после \"@{previous}\": теги пишутся в том порядке, в "
              "каком среда разработки показывает разделы подсказки, - параметры, результат, "
              "исключения, ссылки.",
        "en": "The tag \"@{keyword}\" follows \"@{previous}\": the tags go in the order the "
              "environment shows the sections of the hover - parameters, result, exceptions, "
              "references.",
    },
    "comment/doc-tag-layout.empty": {
        "ru": "У тега \"@{keyword}\" нет текста: среда разработки покажет пустой раздел или "
              "примет за его текст следующую строку с тегом. Допишите текст или уберите тег.",
        "en": "The tag \"@{keyword}\" has no text: the environment shows an empty section or "
              "takes the next tag line for its text. Write the text or remove the tag.",
    },
    "comment/doc-tag-layout.dash": {
        "ru": "Имя и текст тега разделяет \"{dash}\": среда разработки отделяет имя только "
              "дефисом-минусом, другой знак она покажет в тексте. Поставьте \"-\".",
        "en": "\"{dash}\" separates the name from the text of the tag: the environment takes "
              "only a hyphen-minus for the separator and shows any other dash in the text. Put "
              "\"-\" there.",
    },
    "comment/doc-tag-param.title": {
        "ru": "Тег @параметр не сходится с сигнатурой метода",
        "en": "An @parameter tag does not match the method signature",
    },
    "comment/doc-tag-param.not-method": {
        "ru": "Тег \"@{keyword}\" описывает параметр метода, а объявление ниже - не метод: "
              "параметров у него нет.",
        "en": "The tag \"@{keyword}\" describes a parameter of a method, and the declaration "
              "below is no method: it has no parameters.",
    },
    "comment/doc-tag-param.no-name": {
        "ru": "У тега \"@{keyword}\" нет имени параметра: среда разработки такой тег пропустит.",
        "en": "The tag \"@{keyword}\" names no parameter: the environment skips such a tag.",
    },
    "comment/doc-tag-param.unknown": {
        "ru": "У метода \"{method}\" нет параметра \"{name}\": его переименовали или удалили, "
              "либо в имени опечатка. Параметры метода: {params}.",
        "en": "The method \"{method}\" has no parameter \"{name}\": it was renamed or removed, or "
              "the name is misspelled. The parameters of the method: {params}.",
    },
    "comment/doc-tag-param.none": {
        "ru": "У метода \"{method}\" нет параметров, а тег описывает параметр \"{name}\".",
        "en": "The method \"{method}\" takes no parameters, and the tag describes a parameter "
              "\"{name}\".",
    },
    "comment/doc-tag-param.case": {
        "ru": "В сигнатуре параметр написан \"{right}\", а в теге - \"{name}\". Напишите имя так "
              "же, как в сигнатуре.",
        "en": "The signature spells the parameter \"{right}\", the tag - \"{name}\". Spell the "
              "name as the signature does.",
    },
    "comment/doc-tag-param.twice": {
        "ru": "Параметр \"{name}\" описан второй раз: в подсказке он окажется в списке дважды.",
        "en": "The parameter \"{name}\" is described a second time: the hover lists it twice.",
    },
    "comment/doc-tag-param.order": {
        "ru": "Параметр \"{name}\" описан раньше \"{previous}\", а в сигнатуре стоит после "
              "него: опишите параметры в порядке сигнатуры.",
        "en": "The parameter \"{name}\" is described before \"{previous}\" and comes after it "
              "in the signature: describe the parameters in the order of the signature.",
    },
    "comment/doc-tag-param.cut": {
        "ru": "Среда разработки прочитает имя как \"{cut}\": в имени \"{name}\" есть знак, "
              "которого ее шаблон имени не принимает (подчеркивание, точка или строчная "
              "\"ё\"), и остаток имени уйдет в текст.",
        "en": "The environment reads the name as \"{cut}\": the name \"{name}\" has a character "
              "its name pattern does not take (an underscore, a dot or a lowercase \"ё\"), and "
              "the rest of the name goes into the text.",
    },
    "comment/doc-tag-param.partial": {
        "ru": "Описана часть параметров метода \"{method}\", нет описания у: {missing}. "
              "Раздел \"Параметры\" с пропусками читается как недосмотр - опишите все "
              "параметры или уберите теги.",
        "en": "Only some parameters of the method \"{method}\" are described, missing: "
              "{missing}. A \"Parameters\" section with gaps reads as an oversight - describe "
              "every parameter or remove the tags.",
    },
    "comment/doc-tag-result.title": {
        "ru": "Тег результата или исключения не подходит к объявлению",
        "en": "A result or exception tag does not fit the declaration",
    },
    "comment/doc-tag-result.not-method": {
        "ru": "Тег \"@{keyword}\" описывает метод, а объявление ниже - не метод.",
        "en": "The tag \"@{keyword}\" describes a method, and the declaration below is no "
              "method.",
    },
    "comment/doc-tag-result.no-result": {
        "ru": "Метод \"{method}\" не возвращает значения, а тег \"@{keyword}\" описывает "
              "результат: уберите тег или объявите тип результата.",
        "en": "The method \"{method}\" returns no value, and the tag \"@{keyword}\" describes a "
              "result: remove the tag or declare the result type.",
    },
    "comment/doc-tag-result.twice": {
        "ru": "Второй тег \"@{keyword}\": среда разработки склеит тексты тегов результата в "
              "одну строку без пробела. Оставьте один тег.",
        "en": "A second \"@{keyword}\" tag: the environment glues the texts of the result tags "
              "into one line without a blank. Keep one tag.",
    },
    "comment/doc-tag-result.no-type": {
        "ru": "У тега \"@{keyword}\" нет типа исключения: среда разработки такой тег пропустит.",
        "en": "The tag \"@{keyword}\" names no exception type: the environment skips such a "
              "tag.",
    },
    "comment/doc-tag-result.cut": {
        "ru": "Среда разработки прочитает тип исключения как \"{cut}\": имя \"{name}\" она "
              "обрывает на первой точке, двоеточии, подчеркивании или строчной \"ё\", и "
              "остаток уйдет в текст. Напишите простое имя типа.",
        "en": "The environment reads the exception type as \"{cut}\": it cuts the name "
              "\"{name}\" at the first dot, colon, underscore or lowercase \"ё\", and the rest "
              "goes into the text. Write the simple name of the type.",
    },
    "comment/doc-tag-target.title": {
        "ru": "Тег ссылается на имя, которого нет",
        "en": "A tag refers to a name that does not exist",
    },
    "comment/doc-tag-target.see": {
        "ru": "Ссылка \"@{keyword} {target}\" никуда не ведет: имени \"{name}\" нет ни в "
              "проекте, ни у технологии. Его переименовали или удалили, либо в имени опечатка.",
        "en": "The reference \"@{keyword} {target}\" leads nowhere: the name \"{name}\" exists "
              "neither in the project nor on the platform. It was renamed or removed, or it is "
              "misspelled.",
    },
    "comment/doc-tag-target.member": {
        "ru": "Ссылка \"@{keyword} {target}\" никуда не ведет: у \"{owner}\" нет \"{name}\". Его "
              "переименовали или удалили, либо в имени опечатка.",
        "en": "The reference \"@{keyword} {target}\" leads nowhere: \"{owner}\" has no "
              "\"{name}\". It was renamed or removed, or it is misspelled.",
    },
    "comment/doc-tag-target.throws": {
        "ru": "Типа исключения \"{name}\" нет ни в проекте, ни у технологии: его переименовали "
              "или удалили, либо в имени опечатка.{thrown}",
        "en": "The exception type \"{name}\" exists neither in the project nor on the platform: "
              "it was renamed or removed, or it is misspelled.{thrown}",
    },
    "comment/doc-tag-target.thrown": {
        "ru": " Тело метода выбрасывает: {types}.",
        "en": " The method body throws: {types}.",
    },
}
i18n.register(MESSAGES)

#: Words after `@` that an author means as a tag but the environment does not know, by the
#: kind they stand for: the short forms of other documentation systems.
_ALIASES: dict[str, str] = {
    "param": "param",
    "return": "returns",
    "throw": "throws",
    "exception": "throws",
}
#: A reference to code: a name, or a chain of names joined by dots.
_CHAIN_RE = re.compile(r"^\w+(?:\.\w+)*$")


@lru_cache(maxsize=1)
def _no_result_forms() -> frozenset[str]:
    """Both spellings of the result types that mean "no value": `ничто` and `никогда`."""
    try:
        keywords = dataset.load_json("language.json")["keywords"]
    except (dataset.DatasetError, OSError, ValueError, KeyError):
        return frozenset()
    return frozenset(
        form for key in ("VOID", "NEVER") for form in (keywords.get(key) or {}).get("forms", ())
    )


dataset.register_reset(_no_result_forms.cache_clear)


def _language(source: SourceFile) -> str:
    """`en` for a module written with English keywords, `ru` otherwise."""
    latin = cyrillic = 0
    for tok in tokens(source):
        if tok.kind == "KEYWORD" and tok.value[:1].isalpha():
            if tok.value[:1].isascii():
                latin += 1
            else:
                cyrillic += 1
    return "en" if latin > cyrillic else "ru"


def _doc_tokens(group: list[Token]) -> list[Token]:
    """The `///` lines of a comment group, collected the way the environment collects them.

    Another comment before the first `///` line is passed over; one after it ends the block.
    """
    out: list[Token] = []
    for tok in group:
        if tok.subkind == "line" and tok.value.startswith("///"):
            out.append(tok)
        elif out:
            break
    return out


def doc_blocks(source: SourceFile) -> list[tuple[object, doctags.DocBlock]]:
    """(declaration, its `///` block read by `doctags.parse`) for every documented declaration."""
    key = "doc_blocks"
    if key not in source.cache:
        found: list[tuple[object, doctags.DocBlock]] = []
        if "///" in source.text:
            for decl, group in documented_declarations(source):
                lines = [
                    doctags.doc_line(tok.line, tok.col, tok.start, tok.value)
                    for tok in _doc_tokens(group)
                ]
                if lines:
                    found.append((decl, doctags.parse(lines)))
        source.cache[key] = found
    return source.cache[key]


def _tagged(source: SourceFile) -> Iterator[tuple[object, doctags.DocBlock]]:
    for decl, block in doc_blocks(source):
        if block.tags:
            yield decl, block


def _at(block: doctags.DocBlock, tag: doctags.Tag, position: int) -> tuple[int, int]:
    line = block.lines[tag.index]
    return line.line, line.column + max(position, 0)


def _finding(source: SourceFile, rule_id: str, block: doctags.DocBlock, tag: doctags.Tag,
             position: int, key: str, fix: TextEdit | None = None, **args) -> Diagnostic:
    line, col = _at(block, tag, position)
    return Diagnostic(source.rel, line, col, rule_id, Severity.WARNING, i18n.t(key, **args),
                      fix=fix)


def _eol(text: str, offset: int) -> str:
    end = text.find("\n", offset)
    return "\r\n" if end > 0 and text[end - 1] == "\r" else "\n"


def _judged(decl) -> str | None:
    """`method`, `other` for a declaration that takes no method tags, None when not judged."""
    if isinstance(decl, Method):
        return "method"
    if isinstance(decl, (ObjectField, Enum, EnumItem)):
        return "other"
    return None  # a structure, an exception, a constructor - see the module docstring


# --- comment/doc-tag-unknown ---------------------------------------------------------------

@rule(
    "comment/doc-tag-unknown", "comment/doc-tag-unknown.title", "B",
    severity=Severity.WARNING,
)
def doc_tag_unknown(source: SourceFile) -> Iterable[Diagnostic]:
    """A `///` line that starts with `@` and is none of the tags - see the module docstring."""
    rule_id = "comment/doc-tag-unknown"
    language = None
    for _decl, block in _tagged(source):
        for tag in block.tags:
            if tag.kind is not None or tag.index == 0:
                continue  # a first line is the description, whatever it starts with
            written = tag.keyword
            kind = doctags.KIND_OF.get(written.lower())
            key, right = "comment/doc-tag-unknown.found", ""
            if kind is not None:
                # The same word in another case: its own language, the right case.
                russian, english = doctags.TAGS[kind]
                right = english if written.lower() == english else russian
                key = "comment/doc-tag-unknown.case"
            elif written.lower() in _ALIASES:
                if language is None:
                    language = _language(source)
                right = doctags.keyword(_ALIASES[written.lower()], language)
                key = "comment/doc-tag-unknown.alias"
            fix = None
            if right:
                start = block.lines[tag.index].offset + tag.keyword_at + 1
                fix = TextEdit(start, start + len(written), right)
            yield _finding(source, rule_id, block, tag, tag.keyword_at, key, fix=fix,
                           written=written, right=right)


# --- comment/doc-tag-layout ----------------------------------------------------------------

@rule(
    "comment/doc-tag-layout", "comment/doc-tag-layout.title", "B",
    severity=Severity.WARNING,
)
def doc_tag_layout(source: SourceFile) -> Iterable[Diagnostic]:
    """The place of the tags inside a block - see the module docstring."""
    rule_id = "comment/doc-tag-layout"
    text = source.text
    for _decl, block in _tagged(source):
        known = [tag for tag in block.tags if tag.kind is not None]
        if not known:
            continue
        first = block.tags[0]
        if first.index == 0:
            if first.kind is not None:
                yield _finding(source, rule_id, block, first, first.keyword_at,
                               "comment/doc-tag-layout.first-line", keyword=first.keyword)
        elif block.lines[first.index - 1].text.strip():
            opening = block.lines[first.index]
            line_start = text.rfind("\n", 0, opening.offset) + 1
            head = text[line_start:opening.offset]
            indent = head[:head.find("///")] if "///" in head else ""
            fix = TextEdit(line_start, line_start, indent + "///" + _eol(text, opening.offset))
            yield _finding(source, rule_id, block, first, first.keyword_at,
                           "comment/doc-tag-layout.no-blank", fix=fix)
        last = block.tags[-1]
        tail = [line.text for line in block.lines[last.index + 1:last.last + 1]]
        for k in range(1, len(tail)):
            if tail[k].strip() and not tail[k - 1].strip():
                line = block.lines[last.index + 1 + k]
                yield Diagnostic(
                    source.rel, line.line, line.column, rule_id, Severity.WARNING,
                    i18n.t("comment/doc-tag-layout.after-tags", keyword=last.keyword),
                )
                break
        previous = None
        for tag in known:
            if previous is not None and (
                doctags.ORDER.index(tag.kind) < doctags.ORDER.index(previous.kind)
            ):
                yield _finding(source, rule_id, block, tag, tag.keyword_at,
                               "comment/doc-tag-layout.order",
                               keyword=tag.keyword, previous=previous.keyword)
                break
            previous = tag
        for tag in known:
            if tag.kind not in doctags.NAMED and not tag.text.strip():
                yield _finding(source, rule_id, block, tag, tag.keyword_at,
                               "comment/doc-tag-layout.empty", keyword=tag.keyword)
            if tag.dash and tag.dash != "-":
                start = block.lines[tag.index].offset + tag.dash_at
                yield _finding(source, rule_id, block, tag, tag.dash_at,
                               "comment/doc-tag-layout.dash",
                               fix=TextEdit(start, start + 1, "-"), dash=tag.dash)


# --- comment/doc-tag-param -----------------------------------------------------------------

def _listed(params: list[str], name: str) -> str:
    """The parameters of a method, the closest to a misspelled name first."""
    close = difflib.get_close_matches(name, params, n=1, cutoff=0.6)
    return ", ".join(close + [param for param in params if param not in close])


@rule(
    "comment/doc-tag-param", "comment/doc-tag-param.title", "C",
    severity=Severity.WARNING,
)
def doc_tag_param(source: SourceFile) -> Iterable[Diagnostic]:
    """`@параметр` tags against the signature below them - see the module docstring."""
    rule_id = "comment/doc-tag-param"
    for decl, block in _tagged(source):
        tags = [tag for tag in block.tags if tag.kind == "param"]
        judged = _judged(decl)
        if not tags or judged is None:
            continue
        if judged == "other":
            yield _finding(source, rule_id, block, tags[0], tags[0].keyword_at,
                           "comment/doc-tag-param.not-method", keyword=tags[0].keyword)
            continue
        params = [param.name for param in decl.params]
        by_lower = {name.lower(): name for name in params}
        described: list[str] = []
        order_reported = False
        for tag in tags:
            if not tag.name:
                yield _finding(source, rule_id, block, tag, tag.keyword_at,
                               "comment/doc-tag-param.no-name", keyword=tag.keyword)
                continue
            if tag.environment_name != tag.name:
                yield _finding(source, rule_id, block, tag, tag.name_at,
                               "comment/doc-tag-param.cut",
                               cut=tag.environment_name, name=tag.name)
            name = tag.name
            if name not in params:
                right = by_lower.get(name.lower())
                if right is None:
                    key = ("comment/doc-tag-param.unknown" if params
                           else "comment/doc-tag-param.none")
                    yield _finding(source, rule_id, block, tag, tag.name_at, key,
                                   method=decl.name, name=name, params=_listed(params, name))
                    continue
                start = block.lines[tag.index].offset + tag.name_at
                yield _finding(source, rule_id, block, tag, tag.name_at,
                               "comment/doc-tag-param.case",
                               fix=TextEdit(start, start + len(name), right),
                               right=right, name=name)
                name = right
            if name in described:
                yield _finding(source, rule_id, block, tag, tag.name_at,
                               "comment/doc-tag-param.twice", name=name)
                continue
            if described and not order_reported:
                previous = described[-1]
                if params.index(name) < params.index(previous):
                    order_reported = True
                    yield _finding(source, rule_id, block, tag, tag.name_at,
                                   "comment/doc-tag-param.order", name=name, previous=previous)
            described.append(name)
        missing = [name for name in params if name not in described]
        if described and missing:
            yield _finding(source, rule_id, block, tags[0], tags[0].keyword_at,
                           "comment/doc-tag-param.partial",
                           method=decl.name, missing=", ".join(missing))


# --- comment/doc-tag-result ----------------------------------------------------------------

@rule(
    "comment/doc-tag-result", "comment/doc-tag-result.title", "C",
    severity=Severity.WARNING,
)
def doc_tag_result(source: SourceFile) -> Iterable[Diagnostic]:
    """`@возвращает` and `@выбрасывает` against the declaration - see the module docstring."""
    rule_id = "comment/doc-tag-result"
    for decl, block in _tagged(source):
        judged = _judged(decl)
        returns = [tag for tag in block.tags if tag.kind == "returns"]
        throws = [tag for tag in block.tags if tag.kind == "throws"]
        if judged is None or not returns and not throws:
            continue
        if judged == "other":
            tag = (returns + throws)[0]
            yield _finding(source, rule_id, block, tag, tag.keyword_at,
                           "comment/doc-tag-result.not-method", keyword=tag.keyword)
            continue
        if returns:
            result = decl.return_type
            if result is None or result.text in _no_result_forms():
                yield _finding(source, rule_id, block, returns[0], returns[0].keyword_at,
                               "comment/doc-tag-result.no-result",
                               method=decl.name, keyword=returns[0].keyword)
            for tag in returns[1:]:
                yield _finding(source, rule_id, block, tag, tag.keyword_at,
                               "comment/doc-tag-result.twice", keyword=tag.keyword)
        for tag in throws:
            if not tag.name:
                yield _finding(source, rule_id, block, tag, tag.keyword_at,
                               "comment/doc-tag-result.no-type", keyword=tag.keyword)
            elif tag.environment_name != tag.name:
                yield _finding(source, rule_id, block, tag, tag.name_at,
                               "comment/doc-tag-result.cut",
                               cut=tag.environment_name, name=tag.name)


# --- comment/doc-tag-target ----------------------------------------------------------------

def _stem(rel: str) -> str:
    """The element a module belongs to: its file name up to the first dot."""
    return rel.replace("\\", "/").rsplit("/", 1)[-1].split(".", 1)[0]


def _declared(module) -> tuple[set[str], dict[str, list[str]]]:
    """The names a module declares, and the members of each type it declares."""
    names: set[str] = set()
    members: dict[str, list[str]] = {}
    for member in module.members:
        name = getattr(member, "name", "")
        if not name:
            continue
        names.add(name)
        if isinstance(member, Structure):
            members[name] = [sub.name for sub in member.members if getattr(sub, "name", "")]
        elif isinstance(member, Enum):
            members[name] = [item.name for item in member.items] + [m.name for m in member.methods]
    return names, members


def _thrown(body) -> list[str]:
    """The types the statements throw as `выбросить новый Тип(...)`."""
    out: set[str] = set()
    stack: list = [body]
    while stack:
        node = stack.pop()
        if isinstance(node, (list, tuple)):
            stack.extend(node)
            continue
        if not dataclasses.is_dataclass(node):
            continue
        if isinstance(node, Throw) and isinstance(node.value, New) and node.value.type:
            out.add(node.value.type.text)
        for item in dataclasses.fields(node):
            value = getattr(node, item.name)
            if isinstance(value, (list, tuple)) or dataclasses.is_dataclass(value):
                stack.append(value)
    return sorted(out)


def _script(word: str) -> str:
    letters = [ch for ch in word if ch.isalpha()]
    if all(ch.isascii() for ch in letters):
        return "latin"
    if not any(ch.isascii() for ch in letters):
        return "cyrillic"
    return "mixed"


def _target_mapper(source: SourceFile) -> dict | None:
    """The map phase: an element description gives its name and the names it declares, a module
    the names it declares and the references of its tags."""
    if source.kind == "yaml":
        if not _HAVE_YAML or is_translation_dictionary(source):
            return None
        library: list[str] = []
        if libs.project_coordinates(source.text) is not None:
            library = libs.project_library_types(source.path, source.text)
        return {
            "k": "y", "element": object_name_fast(source) or "",
            "names": sorted(declaration_names_fast(source)), "lib": library,
        }
    if source.kind != "xbsl":
        return None
    module, _errors = parse(source)
    if module is None:
        return None
    names, members = _declared(module)
    refs: list[tuple] = []
    for decl, block in _tagged(source):
        for tag in block.tags:
            if tag.kind == "see":
                target = tag.text.strip().rstrip(".")
                if _CHAIN_RE.match(target):
                    line, col = _at(block, tag, tag.text_at)
                    refs.append(("see", tag.keyword, target, line, col, []))
            elif tag.kind == "throws" and tag.name and tag.environment_name == tag.name:
                line, col = _at(block, tag, tag.name_at)
                body = decl.body if isinstance(decl, Method) else []
                refs.append(("throws", tag.keyword, tag.name, line, col, _thrown(body)))
    latin = cyrillic = 0
    for tok in tokens(source):
        if tok.kind == "IDENT":
            script = _script(tok.value)
            latin += script == "latin"
            cyrillic += script == "cyrillic"
    return {
        "k": "x", "stem": _stem(source.rel), "names": sorted(names), "members": members,
        "refs": refs, "latin": latin, "cyrillic": cyrillic,
    }


@rule(
    "comment/doc-tag-target", "comment/doc-tag-target.title", "D",
    scope="project", severity=Severity.WARNING, mapper=_target_mapper,
)
def doc_tag_target(facts: dict[str, dict]) -> Iterable[Diagnostic]:
    """The reduce: `@см` references and `@выбрасывает` types against the names of the project
    and of the platform - see the module docstring."""
    rule_id = "comment/doc-tag-target"
    judged = [(rel, fact) for rel, fact in facts.items() if fact.get("refs")]
    if not judged or not _stdlib_names():
        return  # nothing to judge, or no platform catalog to judge by
    platform = _platform_names()
    types: set[str] = set(_stdlib_names())
    elements: set[str] = set()
    by_owner: dict[str, set[str]] = {}
    anywhere: set[str] = set()
    latin = cyrillic = 0
    for fact in facts.values():
        if fact["k"] == "y":
            if fact["element"]:
                elements.add(fact["element"])
                by_owner.setdefault(fact["element"], set()).update(fact["names"])
            anywhere.update(fact["names"])
            anywhere.update(fact["lib"])
            types.update(fact["lib"])
            continue
        elements.add(fact["stem"])
        by_owner.setdefault(fact["stem"], set()).update(fact["names"])
        anywhere.update(fact["names"])
        for owner, owned in fact["members"].items():
            types.add(owner)
            by_owner.setdefault(owner, set()).update(owned)
            anywhere.update(owned)
        latin += fact["latin"]
        cyrillic += fact["cyrillic"]
    dominant = "latin" if latin > cyrillic else "cyrillic"
    for rel, fact in judged:
        own = by_owner.get(fact["stem"], set())
        for kind, keyword, target, line, col, thrown in fact["refs"]:
            parts = target.split(".")
            head = parts[0]
            if kind == "throws":
                if head in types or head in own or head in anywhere:
                    continue  # a type anywhere in the project: its module may stay unnamed
                extra = ""
                if thrown:
                    extra = i18n.t("comment/doc-tag-target.thrown", types=", ".join(thrown))
                yield Diagnostic(rel, line, col, rule_id, Severity.WARNING, i18n.t(
                    "comment/doc-tag-target.throws", name=head, thrown=extra))
                continue
            if len(parts) == 1:
                if not head[:1].isupper():
                    continue  # a word of prose rather than a name
                script = _script(head)
                if script != "mixed" and script != dominant:
                    continue  # a name of something outside the project, in the other script
                if head in own or head in elements or head in anywhere or head in platform:
                    continue
                yield Diagnostic(rel, line, col, rule_id, Severity.WARNING, i18n.t(
                    "comment/doc-tag-target.see", keyword=keyword, target=target, name=head))
                continue
            if head in by_owner:
                if parts[1] in by_owner[head]:
                    continue
                yield Diagnostic(rel, line, col, rule_id, Severity.WARNING, i18n.t(
                    "comment/doc-tag-target.member", keyword=keyword, target=target,
                    owner=head, name=parts[1]))
                continue
            if head in platform or head in anywhere:
                continue  # a platform type or a name of the project: its members are not judged
            yield Diagnostic(rel, line, col, rule_id, Severity.WARNING, i18n.t(
                "comment/doc-tag-target.see", keyword=keyword, target=target, name=head))
