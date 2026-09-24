"""Tier D: a name in a comment that exists nowhere in the project (comment/unknown-name).

A comment says "см. ПересчитатьОстатки" or 'форма объекта "ПартииТоваров"', the method was
renamed or the object replaced, and the comment kept the old word: the reader looks for a thing
that is not there. The rule catches the word by its shape - an identifier-like word, one with a
capital inside (`КарточкаСклада`, `SaveRow`) - and asks whether the project or the platform
knows it.

Judged are the comments of the modules and of the element descriptions (`_comments.lines`). An
element description names the handlers of its paired module and the components of its own
tree, and on the corpus of a project six of the eight names a style edit of the comments found
missing stood in the comments of the descriptions.

What "known" means is the map-reduce of the whole project:

- every module contributes its identifier tokens and the words of its string literals - a
  parameter key lives as a string and is a name of the project all the same;
- every element yaml contributes its keys and the words of its values - the names of objects,
  attributes, components, bindings; a translation dictionary contributes nothing, since it
  repeats the words of old comments;
- the project descriptor adds the global types of the libraries it declares, when their
  archives lie next to the sources (`xbsl/libs.py`);
- the platform adds every name of its data - types, members, globals, the term pairs in both
  spellings, the metamodel, the ui schema - once per process.

What is NOT judged, each narrowing measured on real projects:

- a line of commented-out code - a declaration, an assignment, a call, a statement (`возврат`,
  `если`, `новый`), a line with an operator of comparison, a line commented twice: the names in
  it are the local names of that dead code, and a finding would describe the wrong problem. On
  two foreign corpora such lines gave seventeen of the nineteen false findings;
- a word of the other script: in a project written in Russian a Latin word (`OpenAPI`, a JSON
  field, an XML element) names something outside the project, and the other way round;
- a word with a digit or an underscore (a base64 fragment, an OData entity);
- a fragment - the halves of a name hyphenated across a line break, a word after "...";
- an inflected name: prose declines a name ("из КарточкиСклада", "для НастроекОтчета"),
  so a candidate whose parts match those of a known name up to a case ending of three letters -
  or up to the fleeting vowel of a genitive plural - is that name in another case; a candidate
  in backticks is quoted verbatim and has to match exactly;
- a name of another system: a root of a chain (`Имя.Член`) the project does not know, followed
  by a member that neither the code of the project nor the platform has, is an object of
  another configuration or service, and the rule leaves its every mention alone. A member is
  judged only after a root the project or the platform knows, and never after a library type,
  whose members the archive does not list;
- a name standing next to another system of the ecosystem: within two words of
  `Менеджер сервиса`, `МС`, `1С:Предприятие`, `БСП`, `БТС` or their English names the name
  belongs to that system - "документ НедоступностиРесурсов Менеджера сервиса", "как в БТС РезервныеКопии".
  Only that mention is let go. On the history of a project the window removed seven of the
  seventeen names of other systems and none of the thirty-three stale ones; a wider window, or
  one decision for the whole project, lost more of the project's own names than it saved.
  English prose spends two words on "of the", so there the window lets fewer names go.

What stays is a name of another product written with no system beside it -
"документ ОстаткиДругойСистемы" reads exactly like a renamed object, and the rule reports it,
saying how to name the system. In a project written in English the same holds for a product
name of the prose: `PaaS`, `OpenAPI` and `YouTube` have the shape of a name and the script of
the project. That is the reason the rule is off by default.

One finding per name per file. A project without the platform catalog is not judged: there every
platform name would read as unknown.
"""

from __future__ import annotations

import bisect
import re
from collections.abc import Iterable
from functools import lru_cache

from xbsl import dataset, i18n, libs
from xbsl.diagnostics import Diagnostic, Severity
from xbsl.engine import SourceFile, rule
from xbsl.lexer import tokens
from xbsl.rules import _comments
from xbsl.rules.semantics import _stdlib_names
from xbsl.rules.yaml_schema import (
    _HAVE_YAML,
    _parsed,
    declaration_names_fast,
    is_translation_dictionary,
)

MESSAGES = {
    "comment/unknown-name.title": {
        "ru": "Имя в комментарии, которого нет в проекте",
        "en": "Name in a comment that the project does not have",
    },
    "comment/unknown-name.found": {
        "ru": "Имени \"{name}\" нет ни в проекте, ни у платформы: его переименовали или удалили, "
              "либо в имени опечатка. Если это имя другой системы, назовите её рядом "
              "(\"... Менеджера сервиса\") или запишите цепочкой \"Система.Имя\".",
        "en": "Name \"{name}\" exists neither in the project nor on the platform: it was renamed "
              "or removed, or it is misspelled. If it is a name of another system, name that "
              "system right beside it (\"Service Manager ...\") or write it as a chain "
              "\"System.Name\".",
    },
    "comment/unknown-name.off": {
        "ru": "имя судится по форме слова: имя другого продукта в прозе комментария неотличимо "
              "от переименованного метода. Проект включает правило в своём CI "
              "(--enable comment/unknown-name)",
        "en": "a name is judged by the shape of the word: the name of another product in the "
              "prose of a comment cannot be told from a renamed method. A project turns the rule "
              "on in its CI (--enable comment/unknown-name)",
    },
}
i18n.register(MESSAGES)

#: A word of letters, digits and underscores that starts with a letter.
_WORD = re.compile(r"[A-Za-zА-Яа-яЁё][A-Za-z0-9А-Яа-яЁё_]*")
#: The pieces of any string: what the known set is made of.
_PIECES = re.compile(r"\w+")
#: The parts of a camel-case name: `JSONСклада` -> `JSON`, `Склада`.
_PARTS = re.compile(r"[A-ZА-ЯЁ]+(?=[A-ZА-ЯЁ][a-zа-яё]|$)|[A-ZА-ЯЁ]?[a-zа-яё]+|[A-ZА-ЯЁ]+")
_LATIN = re.compile(r"^[A-Za-z]+$")
_CYRILLIC = re.compile(r"^[А-Яа-яЁё]+$")
#: Comment markers left at the start of the prose: a line commented twice (`// //пер ...`), a
#: `//` inside a block comment.
_NESTED_MARKERS = re.compile(r"^(?:(?://+|/\*+|\*+/?|#+)\s*)+")
#: A comment line that is code rather than prose, by its head.
_CODE_LINE = re.compile(
    r"(?:"
    # a declaration
    r"(?:@\w+\s+)*(?:статический\s+|static\s+)?"
    r"(?:метод|конструктор|пер|знч|конст|обз|импорт|структура|перечисление|исключение"
    r"|method|constructor|var|val|const|import|structure|enum|exception)\s+[\w.]+"
    # an assignment
    r"|[@&]?[\w.]+(?:<[^>]*>)?\s*(?:=(?!=)|\+=|-=)"
    # a call that takes the whole line, or opens its arguments at the end of the line
    r"|[\w.]+\((?:.*[),(;])?\s*$"
    # a statement that returns, throws or constructs
    r"|(?:возврат|return|выбросить|throw)(?:\s+\S|\s*;?\s*$)"
    r"|(?:новый|new)\s+[\w.]+\s*[(<{]"
    # a condition or a loop over a bare name, a loop head
    r"|(?:если|if|пока|while)\s+(?:не\s+|not\s+)?[\w.]+\s*$"
    r"|(?:для|for)\s+\w+\s+(?:из|in)\s+[\w.]+"
    # a string literal
    r"|\""
    # an argument line of a call spread over several lines
    r"|\w+(?:\.\w+)+\s*,\s*$"
    r")"
)
#: Other systems of the ecosystem a comment names. A name within `_FOREIGN_REACH` words of one
#: belongs to that system.
_FOREIGN_SYSTEM = re.compile(
    r"Менеджер\w*\s+сервис\w*|\bМС\b|1[СC]\s*:\s*Предприяти\w*|\bБСП\b|\bБТС\b"
    r"|Service\s+Manager|1[СC]\s*:\s*Enterprise|\bSSL\b|\bBTS\b"
)
#: The words the distance to a system name is counted in; `1С:Предприятие` is one word.
_MARKER_WORD = re.compile(r"[A-Za-zА-Яа-яЁё0-9_:]+")
_FOREIGN_REACH = 2
#: An operator of comparison or of logic anywhere on the line.
_CODE_OPERATOR = re.compile(r"==|!=|>=|<=|&&|\|\||\?\?")
#: A name hyphenated across a line break: the line ends with a letter and a hyphen.
_HYPHENATED_END = re.compile(r"[^\W\d_]-\s*$")
_ELLIPSIS_BEFORE = re.compile("(?:\\.\\.\\.|\u2026)\\s*$")
_ROOT_BEFORE = re.compile(r"([A-Za-zА-Яа-яЁё]\w*)((?:\.\w+)*)\.$")
_MEMBER_AFTER = re.compile(r"^\.([A-Za-zА-Яа-яЁё]\w*)")
#: What a Russian case ending is made of, up to three letters: `а`, `ого`, `ями`, `ах`, `ов`.
_ENDING = re.compile(r"^[аяуюоеёыиэйьмхвг]{0,3}$")
#: The fleeting vowel of a genitive plural: `Настроек` of `Настройки`, `Сводок` of `Сводка`.
_FLEETING = re.compile(r"[еоё]к$")


def _is_candidate(word: str) -> bool:
    if not word[0].isupper() or "_" in word or any(ch.isdigit() for ch in word):
        return False
    return any(a.islower() and b.isupper() for a, b in zip(word, word[1:]))


def _script(word: str) -> str:
    if _LATIN.match(word):
        return "latin"
    if _CYRILLIC.match(word):
        return "cyrillic"
    return "mixed"


def _strings_of(obj, out: set[str]) -> None:
    """Every word of every key and string of a parsed tree."""
    stack = [obj]
    while stack:
        item = stack.pop()
        if isinstance(item, dict):
            for key, value in item.items():
                if isinstance(key, str):
                    out.update(_PIECES.findall(key))
                stack.append(value)
        elif isinstance(item, list):
            stack.extend(item)
        elif isinstance(item, str):
            out.update(_PIECES.findall(item))


@lru_cache(maxsize=1)
def _platform_names() -> frozenset[str]:
    """Every word the platform data knows, in both spellings - read once per process.

    The whole of each file rather than chosen sections: a member, a global, a term, an
    enumeration value, a component property - a name the platform has is a name a comment may
    use, and a stray prose word in the set costs nothing (a candidate is identifier-like).
    """
    out: set[str] = set()
    for name in ("stdlib.json", "terms.json", "terms_full.json", "uiterms.json", "metamodel.json"):
        try:
            _strings_of(dataset.load_json(name), out)
        except (dataset.DatasetError, OSError, ValueError):
            continue
    try:
        _strings_of(dataset.load_ui_schema() or {}, out)
    except (dataset.DatasetError, OSError, ValueError):
        pass
    return frozenset(out)


dataset.register_reset(_platform_names.cache_clear)


def _is_code(prose: str) -> bool:
    """Whether the prose of a comment line is a line of commented-out code."""
    core = _NESTED_MARKERS.sub("", prose, count=1)
    return _CODE_LINE.match(core) is not None or _CODE_OPERATOR.search(core) is not None


def _next_to_other_system(prose: str, start: int, systems: list[re.Match]) -> bool:
    """Whether one of the `systems` found on the line starts within `_FOREIGN_REACH` words of
    the word at `start`."""
    words = [m.start() for m in _MARKER_WORD.finditer(prose)]

    def index(position: int) -> int:
        return bisect.bisect_right(words, position) - 1

    at = index(start)
    return any(
        abs(index(system.start()) - at) <= _FOREIGN_REACH
        for system in systems if not system.start() <= start < system.end()
    )


def _candidates(source: SourceFile) -> list[tuple]:
    """(name, line, col, verbatim, chain root before it, member after it, next to another
    system) for every identifier-like word of the comments."""
    out: list[tuple] = []
    previous_line = -1
    hyphenated = False
    for cl in _comments.lines(source):
        start = _comments.lead(cl.text)
        prose = cl.text[start:]
        continues = hyphenated and cl.line == previous_line + 1
        hyphenated = _HYPHENATED_END.search(prose) is not None
        previous_line = cl.line
        if not prose.strip() or _is_code(prose):
            continue
        systems = list(_FOREIGN_SYSTEM.finditer(prose))
        first = True
        for m in _WORD.finditer(prose):
            word = m.group(0)
            at_start, first = first, False
            if not _is_candidate(word):
                continue
            before, after = prose[:m.start()], prose[m.end():]
            if at_start and continues:
                continue  # the tail of a name hyphenated across the line break
            if (after.startswith("-") and not after[1:].strip()) or _ELLIPSIS_BEFORE.search(before):
                continue  # the head of such a name, or a fragment after "..."
            root = _ROOT_BEFORE.search(before)
            member = _MEMBER_AFTER.match(after)
            verbatim = before.endswith("`") and after.startswith("`")
            out.append((
                word, cl.line, cl.column + start + m.start(), verbatim,
                root.group(1) if root else None,
                member.group(1) if member else None,
                bool(systems) and _next_to_other_system(prose, m.start(), systems),
            ))
    return out


def _unknown_name_mapper(source: SourceFile) -> dict | None:
    """The map phase: a module gives its names and the candidates of its comments, a yaml its
    names and candidates (a dictionary nothing), the project descriptor the global types of
    its libraries."""
    if source.kind == "yaml":
        if not _HAVE_YAML or is_translation_dictionary(source):
            return None
        names: set[str] = set()
        library: list[str] = []
        if libs.project_coordinates(source.text) is not None:
            library = libs.project_library_types(source.path, source.text)
        data, err = _parsed(source)
        if err is None:
            _strings_of(data, names)
        else:
            names.update(declaration_names_fast(source))
        cands = _candidates(source) if _stdlib_names() else []
        if not names and not library and not cands:
            return None
        return {"k": "y", "names": sorted(names), "lib": library, "cands": cands}
    if source.kind != "xbsl":
        return None
    if not _stdlib_names():
        return None  # no platform catalog: every platform name would read as unknown
    names = set()
    latin = cyrillic = 0
    for tok in tokens(source):
        if tok.kind == "IDENT":
            names.add(tok.value)
            script = _script(tok.value)
            if script == "latin":
                latin += 1
            elif script == "cyrillic":
                cyrillic += 1
        elif tok.kind == "STRING":
            names.update(_PIECES.findall(tok.value))
    return {
        "k": "x", "names": sorted(names), "latin": latin, "cyrillic": cyrillic,
        "cands": _candidates(source),
    }


def _parts(name: str) -> tuple[str, ...]:
    return tuple(_PARTS.findall(name))


def _spellings(part: str) -> tuple[str, ...]:
    """A part of a name, plus its stem without a fleeting vowel when it has one."""
    if _FLEETING.search(part):
        return (part, part[:-2] + "к", part[:-2] + "йк")
    return (part,)


def _same_stem(a: str, b: str) -> bool:
    """Whether two parts of a name are one word, possibly in different cases.

    The differing tails must look like case endings (vowels and the few consonants endings
    carry): `Склада` is `Склад` and `Главного` is `Главный`, while `Заказчик` is another word
    than `Заказы`. A genitive plural drops or turns a vowel before its last consonant
    (`Настроек` of `Настройки`), so each part is also tried without it.
    """
    for x in _spellings(a):
        for y in _spellings(b):
            if x == y:
                return True
            prefix = 0
            for p, q in zip(x, y):
                if p != q:
                    break
                prefix += 1
            if prefix >= 3 and _ENDING.match(x[prefix:]) and _ENDING.match(y[prefix:]):
                return True
    return False


def _inflection_index(known: set[str]) -> dict[tuple[int, str], list[tuple[str, ...]]]:
    """Known camel-case names by (part count, first two letters), for the case match."""
    index: dict[tuple[int, str], list[tuple[str, ...]]] = {}
    for name in known:
        if not _is_candidate(name):
            continue
        parts = _parts(name)
        if parts:
            index.setdefault((len(parts), parts[0][:2]), []).append(parts)
    return index


def _inflected(name: str, index: dict) -> bool:
    parts = _parts(name)
    if not parts:
        return False
    return any(
        all(_same_stem(a, b) for a, b in zip(parts, known))
        for known in index.get((len(parts), parts[0][:2]), ())
    )


@rule(
    "comment/unknown-name", "comment/unknown-name.title", "D",
    scope="project", severity=Severity.WARNING, enabled_by_default=False,
    off_reason="comment/unknown-name.off", mapper=_unknown_name_mapper,
)
def unknown_name(facts: dict[str, dict]) -> Iterable[Diagnostic]:
    """The reduce: the union of every name, then each candidate against it."""
    judged = [(rel, fact) for rel, fact in facts.items() if fact.get("cands")]
    if not judged or not _stdlib_names():
        return
    platform = _platform_names()
    known: set[str] = set(platform)
    code: set[str] = set()
    library: set[str] = set()
    latin = cyrillic = 0
    for fact in facts.values():
        known.update(fact["names"])
        if fact["k"] == "x":
            code.update(fact["names"])
        library.update(fact.get("lib", ()))
        latin += fact.get("latin", 0)
        cyrillic += fact.get("cyrillic", 0)
    known |= library
    dominant = "latin" if latin > cyrillic else "cyrillic"
    # Objects of another system: an unknown chain root whose member neither the code nor the
    # platform has. A member known only from a yaml - a key of localized strings - is no
    # evidence: another configuration names its methods with the same words.
    outside = {
        cand[0] for _rel, fact in judged for cand in fact["cands"]
        if cand[5] is not None and cand[0] not in known
        and cand[5] not in code and cand[5] not in platform
    }
    index: dict | None = None
    for rel, fact in judged:
        reported: set[str] = set()
        for name, line, col, verbatim, root, _member, foreign in fact["cands"]:
            if name in known or name in reported or name in outside or foreign:
                continue
            if root is not None and (root not in known or root in library or root in outside):
                continue
            script = _script(name)
            if script != "mixed" and script != dominant:
                continue
            if not verbatim:
                if index is None:
                    index = _inflection_index(known)
                if _inflected(name, index):
                    continue
            reported.add(name)
            yield Diagnostic(
                rel, line, col, "comment/unknown-name", Severity.WARNING,
                i18n.t("comment/unknown-name.found", name=name),
            )
