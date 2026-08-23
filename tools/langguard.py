"""Language guard for the repository's own sources: no NEW Russian in comments and names.

The repository is written in English - comments, docstrings and identifiers alike (see
CLAUDE.md). Russian stays only in the bilingual i18n messages, argparse help, user-facing
literals, generated-code templates, quotes of the platform documentation and citations of
XBSL in backticks - that is, inside string literals and inside quoted spans of a comment.

Until 31.07.2026 the rule was held by attention alone, and attention failed twice in one
day: a wave of new code shipped Russian section comments and test docstrings, plus a bare
`ШиринаВКолонках` in an English comment. Nothing looked at it - the English-document guard
reads documents, not sources.

The guard judges a DIFF, not the tree: the tree still carries some 1200 Russian comment
chunks over 166 files, and converting them wholesale is a separate job (they are rewritten
opportunistically, when the line is touched anyway). What must not happen is the debt
GROWING, and that is exactly what a diff answers.

    python tools/langguard.py                 # uncommitted work + untracked files
    python tools/langguard.py --base HEAD~1   # what a commit added
    python tools/langguard.py --base origin/main   # what a push would add
    python tools/langguard.py --all           # the whole tree: the size of the debt

Untracked files are judged whole under EVERY base: `git diff` does not see a file until
`git add`, against any base - a run with `--base` once answered "clean" over a new module
whose bare Cyrillic CI then found (2026-08-13, a full CI round).

Exit code 1 when something is found, 0 when clean - so CI and a pre-commit run can gate on
it. What counts as a find:

  * Cyrillic inside a COMMENT or a docstring, outside backticks and outside quotes
    ("Значение типа ..." - a quote of a platform message or of the documentation);
  * a QUOTED platform name that the compiler dictionary can spell in English: the citation
    exception is for what the dictionary does not know, not for names the repository has an
    English form for (`Обработчик` -> Handler). Needs the Element data; without it this half
    stays silent;
  * Cyrillic in an IDENTIFIER of a Python source - a Russian test name, variable or helper
    (in TypeScript a bare Cyrillic token is a platform key, see `_typescript_regions`).

String literals are not looked at at all: that is where the platform's own keys, the
Russian half of the i18n catalog and the yaml fixtures legitimately live.
"""

from __future__ import annotations

import argparse
import ast
import io
import json
import re
import subprocess
import sys
import tokenize
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SOURCE_SUFFIXES = (".py", ".ts")
#: Directories with no sources of ours - vendored code and build output.
SKIP_PARTS = frozenset({"node_modules", "dist", "build", "out", ".venv", "__pycache__", ".refs"})

_CYRILLIC = re.compile("[Ѐ-ӿԀ-ԯ]+")
#: Spans a comment may legitimately hold in Cyrillic: a citation and a quote.
_CITATION = re.compile(r"`[^`]*`|\"[^\"]*\"|«[^»]*»|'[^']{2,}'")
#: A citation of a NAME - the form judged against the dictionary (see _translatable).
_BACKTICKED = re.compile(r"`[^`]*`")
#: A file name the platform fixes in Russian whatever the project's language.
_PLATFORM_FILENAME = re.compile(r"[Ѐ-ӿ]+\.(yaml|xbsl|xbql)\b")


def _words(text: str) -> list[str]:
    """Cyrillic words of a comment line that no exception covers ([] when it is clean).

    A single letter is the subject itself rather than a name - the escape letters of a
    string literal, the letter `ё` that a rule is about - and is left alone.
    """
    rest = _PLATFORM_FILENAME.sub(" ", _CITATION.sub(" ", text))
    return sorted({word for word in _CYRILLIC.findall(rest) if len(word) > 1})


def _translatable(text: str) -> list[tuple[str, str]]:
    """(Russian name, its English spelling) for names quoted in a comment.

    A citation in backticks is how the rule ALLOWED a platform name to stay Russian - and
    that exception swallowed the rule: a comment saying `Обработчик` reads as legal while
    the name has a published English spelling and the repository writes it. So a quoted
    name is judged too, but only against the DICTIONARY: a word the compiler dictionary
    pairs must be written in its English form, a word it does not know (a documentation
    heading, a fixture) stays a citation and is left alone.

    Without the Element data (a clean public clone) there is no dictionary and the check
    answers empty - the wordless one still guards the prose.
    """
    try:
        from xbsl import terms
    except Exception:  # noqa: BLE001 - a guard must not fall over a missing dataset
        return []
    found: dict[str, str] = {}
    del terms  # the spellings are asked through _spellings, which imports it itself
    # Backticks only. A double-quoted span is a quote of a MESSAGE or of the documentation
    # ("Свойства" - the heading a parser matches), and rewriting it in English would misreport
    # what the code looks for; backticks are how this repository cites a NAME.
    for citation in _BACKTICKED.findall(text):
        body = citation[1:-1].strip()
        # Only a citation that is ONE name is judged. A longer one quotes CODE or a heading
        # ("метод Имя(П: Тип)", "Список унаследованных событий"): the generated stub really is
        # written in Russian, and rewriting the quote would misreport what the code produces.
        if not body or len(body.split()) > 1 or not body.replace("_", "").isalnum():
            continue
        for word in _CYRILLIC.findall(body):
            if len(word) < 2:
                continue
            try:
                english = _spellings(word)
            except Exception:  # noqa: BLE001 - same reason
                return []
            if english and english != word:
                found[word] = english
    return sorted(found.items())


#: The roles the dictionary splits its pairs by, in the order a reader should weigh them.
_ROLES = ("types", "facets", "properties", "enums", "query", "kinds")


def _spellings(word: str) -> str:
    """What to write instead of the quoted name - one spelling, or the choice with its roles.

    A name may answer to SEVERAL English words depending on the role it is used in, and the
    compiler dictionary answers with the most frequent one. Handed out as the single truth,
    that answer sends the reader the wrong way: a docstring about the localized-strings SECTION
    was told to write the component property instead, and following the advice would have named
    something the platform does not call that at all. So a name with more than one spelling is
    reported as a choice - every spelling with the role it belongs to - and the decision stays
    with whoever writes the sentence.
    """
    from xbsl import terms

    by_role: dict[str, str] = {}
    for role in _ROLES:
        spelling = terms.english(word, role)
        if spelling and spelling != word:
            by_role.setdefault(spelling, role)
    common = terms.common_english(word)
    if common and common != word:
        by_role.setdefault(common, "общий словарь")
    if not by_role:
        return ""
    if len(by_role) == 1:
        return next(iter(by_role))
    return "выберите по смыслу: " + " / ".join(
        f"{spelling} ({role})" for spelling, role in by_role.items()
    )


# -- where the comments and the identifiers are --------------------------------------------


def _python_regions(text: str) -> tuple[dict[int, str], dict[int, str]]:
    """(comment lines, identifier lines) of a Python source, both `line -> text`.

    Docstrings are comments here: the rule names them in the same breath. They are taken
    from the AST (module, class and function level) rather than guessed from the token
    stream, and judged by their raw source lines - the delimiters do not matter.
    """
    lines = text.splitlines()
    comments: dict[int, str] = {}
    identifiers: dict[int, str] = {}
    try:
        tokens = list(tokenize.generate_tokens(io.StringIO(text).readline))
    except (tokenize.TokenError, IndentationError, SyntaxError):
        return comments, identifiers
    for token in tokens:
        if token.type == tokenize.COMMENT:
            comments[token.start[0]] = comments.get(token.start[0], "") + " " + token.string
        elif token.type == tokenize.NAME and _CYRILLIC.search(token.string):
            identifiers[token.start[0]] = token.string
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return comments, identifiers
    for node in ast.walk(tree):
        if not isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        if ast.get_docstring(node, clean=False) is None:
            continue
        literal = node.body[0].value  # the docstring node itself, delimiters included
        for number in range(literal.lineno, (literal.end_lineno or literal.lineno) + 1):
            if 0 < number <= len(lines):
                comments[number] = comments.get(number, "") + " " + lines[number - 1]
    return comments, identifiers


#: After these, a `/` opens a regex literal rather than a division - the classic JavaScript
#: ambiguity, decided by the last significant character (and by the keywords below).
_BEFORE_REGEX = frozenset("(,=:[!&|?{};+-*%^~<>") | {""}
_REGEX_KEYWORDS = frozenset({
    "return", "typeof", "case", "in", "of", "new", "delete", "void", "instanceof",
    "do", "else", "yield", "await",
})


def _skip_regex(text: str, index: int) -> int:
    """Position just past a regex literal starting at `index`; `index + 1` when it is not one.

    Inside a character class `/` is literal, so `[/]` must not end the scan. A newline
    before the closing slash means this was a division after all.
    """
    position = index + 1
    in_class = False
    while position < len(text):
        char = text[position]
        if char == "\\":
            position += 2
            continue
        if char == "\n":
            return index + 1
        if char == "[":
            in_class = True
        elif char == "]":
            in_class = False
        elif char == "/" and not in_class:
            position += 1
            while position < len(text) and text[position].isalpha():  # the flags
                position += 1
            return position
        position += 1
    return index + 1


def _ts_comment_spans(text: str) -> list[tuple[int, int]]:
    """Character spans of `//` and `/* */` comments, scanned rather than matched.

    A regex over `//` would also match inside a string - `"https://..."`, a Russian UI
    literal with a slash - and the whole point of the guard is that literals are legitimate
    ground for Cyrillic. Regex LITERALS are skipped too, and that is not a nicety: caught
    on the first live run, `.replace(/"/g, "&quot;")` opened a "string" at the quote inside
    the regex and desynchronized everything after it - the scanner then walked past 700
    lines of comments, including the very defect this guard was written for.
    """
    spans: list[tuple[int, int]] = []
    index, size = 0, len(text)
    previous = ""  # last significant character seen outside comments and literals
    while index < size:
        char = text[index]
        if char in "\"'`":
            index += 1
            while index < size:
                if text[index] == "\\":
                    index += 2
                    continue
                if text[index] == char:
                    index += 1
                    break
                index += 1
            previous = char
            continue
        if char == "/" and index + 1 < size:
            if text[index + 1] == "/":
                end = text.find("\n", index)
                end = size if end < 0 else end
                spans.append((index, end))
                index = end
                continue
            if text[index + 1] == "*":
                end = text.find("*/", index + 2)
                end = size if end < 0 else end + 2
                spans.append((index, end))
                index = end
                continue
            if previous in _BEFORE_REGEX or _word_before(text, index) in _REGEX_KEYWORDS:
                index = _skip_regex(text, index)
                previous = "/"
                continue
        if not char.isspace():
            previous = char
        index += 1
    return spans


def _word_before(text: str, index: int) -> str:
    """The identifier ending just before `index` (`return /x/` and friends)."""
    end = index
    while end > 0 and text[end - 1].isspace():
        end -= 1
    start = end
    while start > 0 and (text[start - 1].isalpha() or text[start - 1] == "_"):
        start -= 1
    return text[start:end]


def _typescript_regions(text: str) -> tuple[dict[int, str], dict[int, str]]:
    """(comment lines, {}) of a TypeScript source - comments only.

    Identifiers are not judged here, and that is a measured decision: in TypeScript a bare
    Cyrillic token is almost always a platform key rather than a name of ours - an unquoted
    object key of an icon or kind table (`СтековаяГруппа: "layers"`), a property read off a
    parsed yaml node. A tree scan gives 231 such tokens and no Russian name among them, so
    the check would only teach the reader to ignore the guard.
    """
    comments: dict[int, str] = {}
    for start, end in _ts_comment_spans(text):
        first = text.count("\n", 0, start) + 1
        for offset, line in enumerate(text[start:end].splitlines()):
            comments[first + offset] = comments.get(first + offset, "") + " " + line
    return comments, {}


def regions(path: Path, text: str) -> tuple[dict[int, str], dict[int, str]]:
    """(comment lines, identifier lines) for a source of a supported kind."""
    if path.suffix == ".py":
        return _python_regions(text)
    return _typescript_regions(text)


#: The guard's own source AND its tests: both quote the very names the citation half judges -
#: the rule's examples and its planted defects. The same exemption the typography rule has.
_SELF = ("tools/langguard.py", "tests/test_langguard.py")


def check_file(path: Path, wanted: set[int] | None = None) -> list[tuple[int, str, str]]:
    """Finds in one file: `(line, kind, words)`, limited to `wanted` lines when given."""
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return []
    comments, identifiers = regions(path, text)
    found: list[tuple[int, str, str]] = []
    for number, line in sorted(comments.items()):
        if wanted is not None and number not in wanted:
            continue
        words = _words(line)
        if words:
            found.append((number, "comment", " ".join(words)))
        own = any(path.as_posix().endswith(name) for name in _SELF)
        quoted = [] if own else _translatable(line)
        if quoted:
            found.append((
                number, "citation",
                "; ".join(f"{word} -> {english}" for word, english in quoted),
            ))
    for number, line in sorted(identifiers.items()):
        if wanted is not None and number not in wanted:
            continue
        words = sorted({word for word in _CYRILLIC.findall(line) if len(word) > 1})
        if words:
            found.append((number, "identifier", " ".join(words)))
    return sorted(found)


# -- what a change added -------------------------------------------------------------------

_HUNK = re.compile(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,(\d+))? @@")


def added_lines(diff: str) -> dict[str, set[int]]:
    """Line numbers each file GAINED, parsed from a `--unified=0` diff."""
    added: dict[str, set[int]] = {}
    current = ""
    number = 0
    for line in diff.splitlines():
        if line.startswith("+++ "):
            name = line[4:].strip()
            current = "" if name == "/dev/null" else name[2:] if name.startswith("b/") else name
            continue
        match = _HUNK.match(line)
        if match:
            number = int(match.group(1))
            continue
        if current and line.startswith("+") and not line.startswith("+++"):
            added.setdefault(current, set()).add(number)
            number += 1
    return added


def _git(*arguments: str) -> str:
    result = subprocess.run(
        ["git", *arguments], cwd=ROOT, capture_output=True, text=True,
        encoding="utf-8", errors="replace",
    )
    return result.stdout if result.returncode == 0 else ""


def _is_source(name: str) -> bool:
    path = Path(name)
    return path.suffix in SOURCE_SUFFIXES and not (SKIP_PARTS & set(path.parts))


def scan_diff(base: str) -> list[tuple[str, int, str, str]]:
    """Finds among the lines added since `base`, untracked files included.

    Untracked files enter whole and under EVERY base, not only the default: a diff against
    any base is blind to a file until `git add`, so leaving them to the HEAD case made a
    `--base origin/main` run disagree with CI over a brand-new module (2026-08-13).
    """
    targets: dict[str, set[int] | None] = {
        name: None  # the whole file is an addition
        for name in _git("ls-files", "--others", "--exclude-standard").splitlines()
        if _is_source(name)
    }
    targets.update(added_lines(_git("diff", "--unified=0", "--no-color", base, "--", "*.py", "*.ts")))
    found = []
    for name, numbers in sorted(targets.items()):
        if not _is_source(name):
            continue
        path = ROOT / name
        if path.is_file():
            found.extend((name, *item) for item in check_file(path, numbers))
    return found


def _sources(directory: Path):
    """Our sources under a directory, with the foreign trees pruned as the walk goes.

    Pruned rather than filtered afterwards: `node_modules` alone holds tens of thousands of
    files, and walking into it costs seconds for nothing.
    """
    for child in sorted(directory.iterdir()):
        if child.name in SKIP_PARTS or child.name.startswith(".") and child.is_dir():
            continue
        if child.is_dir():
            yield from _sources(child)
        elif child.suffix in SOURCE_SUFFIXES:
            yield child


def scan_tree() -> list[tuple[str, int, str, str]]:
    """Finds over the whole tree - the size of the debt, not a gate."""
    found = []
    for path in _sources(ROOT):
        name = path.relative_to(ROOT).as_posix()
        found.extend((name, *item) for item in check_file(path))
    return found


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Сторож языка исходников: новый код не добавляет русского в комментарии и имена",
    )
    parser.add_argument("--base", default="HEAD",
                        help="ветка/коммит, относительно которого смотреть добавленные строки")
    parser.add_argument("--all", action="store_true", help="всё дерево (размер долга)")
    parser.add_argument("--format", choices=("text", "json"), default="text")
    options = parser.parse_args(argv)

    found = scan_tree() if options.all else scan_diff(options.base)
    if options.format == "json":
        print(json.dumps(
            [{"file": f, "line": n, "kind": k, "words": w} for f, n, k, w in found],
            ensure_ascii=False, indent=2,
        ))
    else:
        for name, number, kind, words in found:
            print(f"{name}:{number}: {kind}: {words}")
        scope = "во всём дереве" if options.all else f"в добавленных строках относительно {options.base}"
        print(f"{'найдено' if found else 'чисто'}: {len(found)} {scope}")
    return 1 if found else 0


if __name__ == "__main__":
    sys.exit(main())
