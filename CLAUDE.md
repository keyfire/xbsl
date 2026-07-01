# CLAUDE.md — xbsl-lint

A linter for 1C:Element sources (`.yaml`/`.xbsl` pairs). It catches what the server-side
compilation on deploy does not, and gives fast local feedback. Overview and usage: [README.md](README.md).

## Architecture

- Core `xbsllint/engine.py`: source loading, the rule registry (`@rule`), `run() -> [Diagnostic]`.
- Thin adapters over the core: CLI (`xbsllint/cli.py`), MCP (`xbsllint/mcp_server.py`, FastMCP,
  optional `[mcp]` extra), and web (`xbsllint/web.py`, standard library, binds to `127.0.0.1` only).
  The core does not depend on `mcp`.
- Lexer `xbsllint/lexer.py` — follows the platform grammar; rules live in `xbsllint/rules/`.

## Language data (versioned, generated locally)

XBSL is built on Eclipse Xtext + ANTLR. The data is versioned by platform version:
`xbsllint/data/element/<version>/{language.json, stdlib.json}` + `index.json` (default/available).
`language.json` — keywords/operators from the grammar (`InternalBsl.g`/`.tokens`); `stdlib.json` —
the type catalog from the distribution docs. Access is via `xbsllint/dataset.py` (version choice:
`--element-version` / the `XBSLLINT_ELEMENT_VERSION` env var / the index default).

The data is NOT bundled in this repository — it is generated from the user's own distribution and is
gitignored. The distribution is needed only by the extractors; vendor files are not committed
(cached under `.refs/`). The extractors auto-detect the version and place the data in a new folder:

```sh
python tools/extract_grammar.py --dist "<path to the distribution>"
python tools/extract_stdlib.py  --dist "<path to the distribution>"
```

Invariant: never hardcode machine paths or a specific version — only via `--dist`/auto-detection.

## Rules and tiers

Tiers: A (structure/YAML), B (text/conventions), C (parser/code), D (stdlib semantics). Every rule
has an id, a tier, a severity, and an "enabled by default" flag. Rules that fire massively on legacy
code (e.g. an em dash in comments) are made `info` and disabled by default — enabled via `--select`.
Add a new rule only after running it on a real project's sources with zero false positives.
