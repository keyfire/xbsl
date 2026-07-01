#!/usr/bin/env python3
"""Извлечь языковые данные XBSL из грамматики платформы 1С:Элемент.

XBSL реализован на Eclipse Xtext + ANTLR. Внутри дистрибутива (в jar
com.e1c.g5rt.xbsl.language-*.jar) лежат сгенерированные InternalBsl.g и InternalBsl.tokens.
Скрипт читает их и формирует xbsllint/data/element/<версия>/language.json: двуязычные
ключевые слова, операторы/символы, карту идентификаторов токенов.

Версия Элемента определяется из дистрибутива автоматически (или задаётся --element-version).
Вендорные файлы в репозиторий не коммитятся (кэшируются в .refs/, см. .gitignore) – только
производный JSON. Сам линтер работает от этого JSON и дистрибутив в рантайме не требует.
"""

from __future__ import annotations

import argparse
import io
import json
import re
import sys
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _distro  # noqa: E402

GRAMMAR_INNER_G = "InternalBsl.g"
GRAMMAR_INNER_TOKENS = "InternalBsl.tokens"

# Правила, чьи литералы не операторы: пробелы, перевод строки, BOM и ограничитель строки.
_NON_OPERATOR_RULES = {"RULE_WS", "RULE_NL", "RULE_UTF8_BOM", "RULE_DQUOTE"}


# --- Распаковка грамматики из дистрибутива ------------------------------------------


def _extract_from_dist(dist: Path, dest: Path) -> None:
    car = _distro.find_car(dist)
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
                    dest.mkdir(parents=True, exist_ok=True)
                    (dest / base).write_bytes(jz.read(inner))


def resolve_grammar(dist: Path | None, grammar_dir: Path | None) -> Path:
    """Вернуть каталог с InternalBsl.g/.tokens (из --grammar-dir, из дистрибутива или из кэша .refs)."""
    refs = _distro.REPO / ".refs" / "grammar"

    def has_both(d: Path) -> bool:
        return (d / GRAMMAR_INNER_G).is_file() and (d / GRAMMAR_INNER_TOKENS).is_file()

    if grammar_dir and has_both(grammar_dir):
        return grammar_dir
    if dist is not None:
        _extract_from_dist(dist, refs)
        if has_both(refs):
            return refs
    if has_both(refs):
        return refs
    raise SystemExit("Грамматика не найдена. Укажите --dist (каталог дистрибутива) или --grammar-dir.")


# --- Разбор -------------------------------------------------------------------------

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


def parse_tokens(path: Path) -> tuple[list[str], dict[str, int]]:
    operators: list[str] = []
    token_ids: dict[str, int] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
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


def parse_grammar(path: Path) -> tuple[dict[str, dict], list[str]]:
    keywords: dict[str, dict] = {}
    symbols: list[str] = []
    for line in path.read_text(encoding="utf-8").splitlines():
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


def main() -> int:
    ap = argparse.ArgumentParser(description="Извлечь языковые данные XBSL из грамматики Элемента")
    ap.add_argument("--dist", help="каталог дистрибутива 1С:Элемент")
    ap.add_argument("--grammar-dir", help="каталог с InternalBsl.g и InternalBsl.tokens")
    ap.add_argument("--element-version", help="версия Элемента (если не определяется из дистрибутива)")
    ap.add_argument("--no-default", action="store_true", help="не делать эту версию версией по умолчанию")
    ap.add_argument("--out", help="переопределить путь language.json")
    args = ap.parse_args()

    dist = Path(args.dist) if args.dist else None
    if dist is not None and not dist.is_dir():
        raise SystemExit(f"Каталог дистрибутива не найден: {dist}")
    if dist is None and not args.element_version:
        raise SystemExit("Без --dist укажите --element-version (версию для сохранения данных)")

    version = _distro.detect_version(dist, args.element_version) if dist else args.element_version
    gdir = resolve_grammar(dist, Path(args.grammar_dir) if args.grammar_dir else None)

    operators, token_ids = parse_tokens(gdir / GRAMMAR_INNER_TOKENS)
    keywords, symbols = parse_grammar(gdir / GRAMMAR_INNER_G)
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
    out.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
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
