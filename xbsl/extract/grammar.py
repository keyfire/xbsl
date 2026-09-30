#!/usr/bin/env python3
"""Extract the XBSL language data from the 1C:Element platform grammar.

XBSL is implemented on Eclipse Xtext + ANTLR, and the distribution carries the generated
grammar and token table of the language. The script reads them and builds xbsl/data/element/<version>/language.json: bilingual
keywords, operators/symbols, and the token identifier map.

The Element version is detected from the distribution automatically (or set via --element-version).
The grammar files are read from the distribution in memory and copied nowhere: the step
writes language.json and the index into the data root and nothing else, so with an external
--data-dir the clone and the installed package stay as they were. The linter itself works off
that JSON and needs no distribution at runtime.
"""

from __future__ import annotations

import argparse
import io
import json
import re
import zipfile
from pathlib import Path

from xbsl.extract import _distro

GRAMMAR_INNER_G = "InternalBsl.g"
GRAMMAR_INNER_TOKENS = "InternalBsl.tokens"

# Rules whose literals are not operators: whitespace, newline, BOM and the string delimiter.
_NON_OPERATOR_RULES = {"RULE_WS", "RULE_NL", "RULE_UTF8_BOM", "RULE_DQUOTE"}


# --- Unpacking the grammar from the distribution ------------------------------------------


def _read_from_dist(dist: Path) -> dict[str, str]:
    """{file name: text} of the grammar files found in the language jar of the .car.

    The files are read in memory. They used to be copied into a cache next to the package
    code, so every extraction wrote into the package - into an installed one as well -
    whatever --data-dir said, and the manager had no option to send them elsewhere.
    """
    car = _distro.find_car(dist)
    found: dict[str, str] = {}
    with zipfile.ZipFile(car) as z:
        lang_jars = [
            n for n in z.namelist()
            if re.search(r"com\.e1c\.g5rt\.xbsl\.language-[^/]*\.jar$", n)
        ]
        if not lang_jars:
            raise SystemExit("В .car не найден jar com.e1c.g5rt.xbsl.language-*")
        with zipfile.ZipFile(io.BytesIO(z.read(lang_jars[0]))) as jz:
            for inner in jz.namelist():
                base = inner.rsplit("/", 1)[-1]
                if base in (GRAMMAR_INNER_G, GRAMMAR_INNER_TOKENS):
                    found[base] = jz.read(inner).decode("utf-8")
    return found


def resolve_grammar(dist: Path | None, grammar_dir: Path | None) -> tuple[str, str]:
    """The texts of InternalBsl.g and InternalBsl.tokens: from --grammar-dir, else from the distribution.

    A directory that lacks either file gives way to the distribution, as it always did.
    Nothing is written anywhere: without a distribution or a directory there is no grammar.
    """
    if grammar_dir is not None:
        grammar, tokens = grammar_dir / GRAMMAR_INNER_G, grammar_dir / GRAMMAR_INNER_TOKENS
        if grammar.is_file() and tokens.is_file():
            return grammar.read_text(encoding="utf-8"), tokens.read_text(encoding="utf-8")
    if dist is not None:
        found = _read_from_dist(dist)
        if GRAMMAR_INNER_G in found and GRAMMAR_INNER_TOKENS in found:
            return found[GRAMMAR_INNER_G], found[GRAMMAR_INNER_TOKENS]
        raise SystemExit(f"В jar языка нет {GRAMMAR_INNER_G} и {GRAMMAR_INNER_TOKENS}")
    raise SystemExit("Грамматика не найдена. Укажите --dist (каталог дистрибутива) или --grammar-dir "
                     f"(каталог с {GRAMMAR_INNER_G} и {GRAMMAR_INNER_TOKENS}).")


# --- Parsing -------------------------------------------------------------------------

_UNESCAPE = {"n": "\n", "r": "\r", "t": "\t", "'": "'", '"': '"', "\\": "\\"}


def _unescape(lit: str) -> str:
    out: list[str] = []
    i = 0
    while i < len(lit):
        c = lit[i]
        if c == "\\" and i + 1 < len(lit):
            nxt = lit[i + 1]
            if nxt == "u" and i + 6 <= len(lit):
                out.append(chr(int(lit[i + 2 : i + 6], 16)))
                i += 6
                continue
            out.append(_UNESCAPE.get(nxt, nxt))
            i += 2
            continue
        out.append(c)
        i += 1
    return "".join(out)


_LIT_RE = re.compile(r"'((?:\\.|[^'\\])*)'")
_RULE_RE = re.compile(r"^(?:fragment\s+)?(RULE_\w+)\s*:\s*(.*?);\s*$")
_TOKEN_LIT_RE = re.compile(r"^'((?:\\.|[^'\\])*)'=(\d+)$")
_TOKEN_NAME_RE = re.compile(r"^(\w+)=(\d+)$")


def _is_pure_literal_body(body: str, literals: list[str]) -> bool:
    return set(_LIT_RE.sub("", body)) <= set("()| \t")


def _canonical(rule_name: str) -> str:
    name = rule_name[len("RULE_") :].lstrip("_")
    for suf in ("_KW_UP", "_KW", "_UP"):
        if name.endswith(suf):
            return name[: -len(suf)]
    return name


def parse_tokens(text: str) -> tuple[list[str], dict[str, int]]:
    """Operators and token ids from the text of InternalBsl.tokens."""
    operators: list[str] = []
    token_ids: dict[str, int] = {}
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        m = _TOKEN_LIT_RE.match(line)
        if m:
            operators.append(_unescape(m.group(1)))
            continue
        m = _TOKEN_NAME_RE.match(line)
        if m:
            token_ids[m.group(1)] = int(m.group(2))
    return operators, token_ids


def parse_grammar(text: str) -> tuple[dict[str, dict], list[str]]:
    """Keywords and symbols from the text of InternalBsl.g."""
    keywords: dict[str, dict] = {}
    symbols: list[str] = []
    for line in text.splitlines():
        m = _RULE_RE.match(line.strip())
        if not m:
            continue
        rule, body = m.group(1), m.group(2)
        lits = [_unescape(x) for x in _LIT_RE.findall(body)]
        if not lits or not _is_pure_literal_body(body, lits):
            continue
        if all(s.isalpha() for s in lits):
            entry = keywords.setdefault(_canonical(rule), {"forms": [], "rules": []})
            for s in lits:
                if s not in entry["forms"]:
                    entry["forms"].append(s)
            entry["rules"].append(rule)
        elif rule not in _NON_OPERATOR_RULES:
            symbols.extend(lits)
    return keywords, symbols


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        prog=_distro.prog_name("python -m xbsl.extract.grammar"),
        description="Извлечь языковые данные XBSL из грамматики Элемента",
    )
    ap.add_argument("--dist", help="каталог дистрибутива 1С:Элемент")
    ap.add_argument("--grammar-dir", help="каталог с InternalBsl.g и InternalBsl.tokens")
    ap.add_argument("--element-version", help="версия Элемента (если не определяется из дистрибутива)")
    ap.add_argument("--no-default", action="store_true", help="не делать эту версию версией по умолчанию")
    ap.add_argument("--out", help="переопределить путь language.json")
    _distro.add_data_dir_arg(ap)
    args = ap.parse_args(argv)
    _distro.set_data_root(args.data_dir)

    dist = Path(args.dist) if args.dist else None
    if dist is not None and not dist.is_dir():
        raise SystemExit(f"Каталог дистрибутива не найден: {dist}")
    if dist is None and not args.element_version:
        raise SystemExit("Без --dist укажите --element-version (версию для сохранения данных)")

    version = _distro.detect_version(dist, args.element_version) if dist else args.element_version
    grammar_text, tokens_text = resolve_grammar(
        dist, Path(args.grammar_dir) if args.grammar_dir else None)

    operators, token_ids = parse_tokens(tokens_text)
    keywords, symbols = parse_grammar(grammar_text)
    all_ops = sorted(set(operators) | set(symbols), key=lambda s: (-len(s), s))

    data = {
        "meta": {
            "element_version": version,
            "generated_from": "InternalBsl.g + InternalBsl.tokens",
            "keyword_groups": len(keywords),
            "keyword_forms": sum(len(v["forms"]) for v in keywords.values()),
            "operators": len(all_ops),
        },
        "keywords": dict(sorted(keywords.items())),
        "operators": all_ops,
        "token_ids": dict(sorted(token_ids.items(), key=lambda kv: kv[1])),
    }

    out = Path(args.out) if args.out else _distro.version_dir(version) / "language.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n"
    )
    if not args.out:
        _distro.update_index(version, make_default=not args.no_default)
    print(f"Записано: {out} (версия {version})")
    print(
        f"  ключевых слов (групп): {data['meta']['keyword_groups']}, "
        f"форм: {data['meta']['keyword_forms']}, операторов: {data['meta']['operators']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
