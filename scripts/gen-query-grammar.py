#!/usr/bin/env python3
"""Generate the TextMate grammar of the QUERY language from the platform's own vocabulary.

The paired file of a virtual table is a standalone query (`.xbql`), and a module carries the
same language inside a `Запрос{ ... }` block. Both are highlighted by one grammar, written here
rather than by hand so that a word added by a new platform build arrives with the data instead
of waiting for someone to notice.

Two sources, because neither is complete on its own:

* the compiler's own keyword table (`terms.json`, section `query`) - the widest list, and the
  only one that carries the multi-word forms (`СГРУППИРОВАТЬ ПО`, `СОЗДАТЬ ВРЕМЕННУЮ ТАБЛИЦУ`);
* the documentation page `topics/query-syntax` - it knows the words the table splits differently
  (`СОЗДАТЬ`, `ВРЕМЕННУЮ`, `ТАБЛИЦУ`, `ИНДЕКСИРОВАТЬ`), the literals (`ИСТИНА`, `ЛОЖЬ`,
  `НЕОПРЕДЕЛЕНО`), and it spells `ДЛЯ` as `FOR` where the table answers with the name of its own
  enum constant (`CREATE_INDEX`). On a disagreement the documentation wins: it describes the
  language, the table describes the compiler.

`NULL` and `TEMP` are added from the same page, which states they are the two keywords with no
Russian spelling at all.

Run: `python scripts/gen-query-grammar.py` (needs the Element data of a version - the same data
the linter uses). The result is committed; the public repository ships no data of its own.
"""

from __future__ import annotations

import io
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from xbsl import dataset, docs  # noqa: E402

OUT = Path(__file__).resolve().parent.parent / "editors" / "vscode" / "syntaxes" / "xbql.tmLanguage.json"
DOC_PAGE = "topics/query-syntax"

#: Keywords the documentation names as English-only (no Russian spelling exists).
ENGLISH_ONLY = ("NULL", "TEMP")
#: Words that read as operators rather than as sections - a separate scope colours them the way
#: an editor colours `and`/`or`/`not` instead of `select`/`from`.
OPERATOR_WORDS = {
    "И", "ИЛИ", "НЕ", "В", "МЕЖДУ", "ПОДОБНО", "ЕСТЬ", "ССЫЛКА", "СООТВЕТСТВУЕТ",
    "AND", "OR", "NOT", "IN", "BETWEEN", "LIKE", "IS", "REFS", "MATCHES",
}
#: Literals of the language.
CONSTANTS = {
    "ИСТИНА", "ЛОЖЬ", "НЕОПРЕДЕЛЕНО", "TRUE", "FALSE", "UNDEFINED", "NULL",
}
#: An English value of the compiler table that is not a keyword spelling but the name of an enum
#: constant - it carries an underscore, which no keyword does.
_NOT_A_SPELLING = re.compile(r"_")
_ROW_RE = re.compile(r"<tr><td><code>(.*?)</code></td><td><code>(.*?)</code></td>", re.S)
_TAG_RE = re.compile(r"<[^>]+>")


def _doc_pairs() -> dict[str, str]:
    """{Russian: English} from the keyword table of the documentation page."""
    page = docs.page(DOC_PAGE) or {}
    html = page.get("html") or ""
    return {
        _TAG_RE.sub("", ru).strip(): _TAG_RE.sub("", en).strip()
        for ru, en in _ROW_RE.findall(html)
    }


def keywords() -> list[str]:
    """Every spelling of every query keyword, both languages, deduplicated."""
    table = dataset.load_json("terms.json").get("query") or {}
    docs_table = _doc_pairs()
    words: set[str] = set()
    for ru, en in {**table, **docs_table}.items():
        words.add(ru)
        # The documentation's spelling wins over the table's own enum constant.
        english = docs_table.get(ru, en)
        if english and not _NOT_A_SPELLING.search(english):
            words.add(english)
    words.update(ENGLISH_ONLY)
    return sorted(words)


def _alternation(words: list[str]) -> str:
    """A case-insensitive alternation, longest first so a multi-word form wins over its head."""
    parts = [re.escape(w).replace("\\ ", r"\s+") for w in sorted(words, key=lambda w: (-len(w), w))]
    return r"(?i)\b(?:" + "|".join(parts) + r")\b"


def grammar() -> dict:
    words = keywords()
    control = [w for w in words if w not in OPERATOR_WORDS and w not in CONSTANTS]
    operators = [w for w in words if w in OPERATOR_WORDS]
    constants = [w for w in words if w in CONSTANTS]
    return {
        "$schema": "https://raw.githubusercontent.com/martinring/tmlanguage/master/tmlanguage.json",
        "name": "XBQL",
        "scopeName": "source.xbql",
        "patterns": [
            {"include": "#comments"},
            {"include": "#strings"},
            {"include": "#numbers"},
            {"include": "#parameters"},
            {"include": "#constants"},
            {"include": "#operator-words"},
            {"include": "#keywords"},
            {"include": "#type-literal"},
            {"include": "#function-call"},
            {"include": "#operators"},
        ],
        "repository": {
            "comments": {
                "patterns": [
                    {"name": "comment.block.xbql", "begin": "/\\*", "end": "\\*/"},
                    {"name": "comment.line.double-slash.xbql", "match": "//.*$"},
                ]
            },
            "strings": {
                "name": "string.quoted.double.xbql",
                "begin": "\"",
                "end": "\"",
                "patterns": [{"name": "constant.character.escape.xbql", "match": "\\\\."}],
            },
            "numbers": {"name": "constant.numeric.xbql", "match": "\\b[0-9]+(?:\\.[0-9]+)?\\b"},
            # A query parameter: `&КодЯзыка` - the value the caller passes in.
            "parameters": {
                "name": "variable.parameter.xbql",
                "match": "&[A-Za-zА-Яа-яЁё_][A-Za-z0-9А-Яа-яЁё_]*",
            },
            "constants": {"name": "constant.language.xbql", "match": _alternation(constants)},
            "operator-words": {"name": "keyword.operator.word.xbql", "match": _alternation(operators)},
            "keywords": {"name": "keyword.control.xbql", "match": _alternation(control)},
            # A typed literal of the language: `Ууид{...}`, `Дата{...}`.
            "type-literal": {
                "match": "\\b([A-Za-zА-ЯЁ][A-Za-z0-9А-Яа-яЁё_]*)\\s*(?=\\{)",
                "captures": {"1": {"name": "support.type.xbql"}},
            },
            "function-call": {
                "match": "\\b([A-Za-zА-Яа-яЁё_][A-Za-z0-9А-Яа-яЁё_]*)\\s*(?=\\()",
                "captures": {"1": {"name": "entity.name.function.xbql"}},
            },
            "operators": {
                "name": "keyword.operator.xbql",
                "match": "!=|<=|>=|==|[-+*/%<>=&|,.]",
            },
        },
    }


def main() -> int:
    data = grammar()
    OUT.parent.mkdir(parents=True, exist_ok=True)
    io.open(OUT, "w", encoding="utf-8", newline="\n").write(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n"
    )
    total = len(keywords())
    print(f"Записано: {OUT} (ключевых слов: {total})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
