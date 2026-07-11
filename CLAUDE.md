# CLAUDE.md – xbsl-lint

A linter for 1C:Element sources (`.yaml`/`.xbsl` pairs). It catches what the server-side
compilation on deploy does not, and gives fast local feedback. Overview and usage: [README.md](README.md).

## Architecture

- Core `xbsllint/engine.py`: source loading, the rule registry (`@rule`), `run() -> [Diagnostic]`.
- Thin adapters over the core: CLI (`xbsllint/cli.py`), MCP (`xbsllint/mcp_server.py`, FastMCP,
  optional `[mcp]` extra), and web (`xbsllint/web.py`, standard library, binds to `127.0.0.1` only).
  The core does not depend on `mcp`.
- Machine-readable output: `xbsllint/report.py` holds the shared `{diagnostics, summary}` shape used
  by the CLI `--format json`, the MCP server, and editors. `xbsllint --stdin --filename NAME` checks
  one buffer (per-file rules only) – this is what the VS Code extension in `editors/vscode/` drives.
- Lexer `xbsllint/lexer.py` – follows the platform grammar; rules live in `xbsllint/rules/`.

## Language data (versioned, generated locally)

XBSL is built on Eclipse Xtext + ANTLR. The data is versioned by platform version:
`xbsllint/data/element/<version>/{language.json, stdlib.json}` + `index.json` (default/available).
`language.json` – keywords/operators from the grammar (`InternalBsl.g`/`.tokens`); `stdlib.json` –
the type catalog from the distribution docs. Access is via `xbsllint/dataset.py` (version choice:
`--element-version` / the `XBSLLINT_ELEMENT_VERSION` env var / the index default).

The data is NOT bundled in this repository – it is generated from the user's own distribution and is
gitignored. The distribution is needed only by the extractors; vendor files are not committed
(cached under `.refs/`). The extractors auto-detect the version and place the data in a new folder:

```sh
python tools/extract_grammar.py   --dist "<path to the distribution>"
python tools/extract_stdlib.py    --dist "<path to the distribution>"
python tools/extract_metamodel.py --dist "<path to the distribution>"
```

Invariant: never hardcode machine paths or a specific version – only via `--dist`/auto-detection.

## Rules and tiers

Tiers: A (structure/YAML), B (text/conventions), C (parser/code), D (stdlib/metamodel semantics). Every rule
has an id, a tier, a severity, and an "enabled by default" flag. Rules that fire massively on legacy
code (e.g. an em dash in comments) are made `info` and disabled by default – enabled via `--select`.
Add a new rule only after running it on a real project's sources with zero false positives.

`--select`/`--ignore` accept a rule id, a rule group (the part of the id before `/`), or a tier letter.

The `style/` group implements the platform's code style conventions. Everything is token-based, with
no full AST – an ambiguous construct is skipped rather than guessed. Shared helpers (`Запрос{...}`
blocks, type expressions, declarations, signatures) live in `xbsllint/rules/_syntax.py`; the rules
themselves are split by the sections of the platform document: `style_layout` (layout and wrapping),
`style_naming` (naming), `style_types` (types and signatures), `style_strings` (collections and
strings), `style_conditions` (checks).

Where tokens cannot tell a violation from a forced form, narrow the rule instead of guessing, and say
so in the docstring:
- a nullable `Булево?` must be compared against `Истина` – so `style/boolean-compare` stays `info`;
- structure field names are dictated by the serialization contract (JSON keys) – `style/camel-case`
  skips them;
- string literals (HTML/CSS/SVG) are excluded from `style/line-length`.
