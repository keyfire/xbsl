# CLAUDE.md – xbsl

The XBSL (1C:Element) toolkit for `.yaml`/`.xbsl` source pairs: linting with autofixes, an LSP
server, a project index, documentation search, metadata scaffolding and an MCP server. It catches
what the server-side compilation on deploy does not, and gives fast local feedback. Overview and
usage: [README.md](README.md).

Before 0.16 the project was named xbsl-lint (package `xbsllint`). The old names stay as
compatibility aliases: the `xbsllint` package re-exports the `xbsl` modules (a meta-path finder,
same module objects – never duplicate the rule registry), the `xbsllint*` console commands map to
the new entry points, and the legacy env vars / entry-point groups are read after the new ones.

## Architecture

- Core `xbsl/engine.py`: source loading, the rule registry (`@rule`), `run() -> [Diagnostic]`.
- Thin adapters over the core: CLI (`xbsl/cli.py`), MCP (`xbsl/mcp_server.py`, FastMCP,
  optional `[mcp]` extra), and web (`xbsl/web.py`, standard library, binds to `127.0.0.1` only).
  The core does not depend on `mcp`.
- Machine-readable output: `xbsl/report.py` holds the shared `{diagnostics, summary}` shape used
  by the CLI `--format json`, the MCP server, and editors. `xbsl --stdin --filename NAME` checks
  one buffer (per-file rules only) – this is what the VS Code extension in `editors/vscode/` drives.
- Lexer `xbsl/lexer.py` – follows the platform grammar; rules live in `xbsl/rules/`.
- Metadata scaffolding `xbsl/scaffold.py`: the single source of yaml/xbsl templates and precise
  text edits (new objects, fields, routes, generated forms, subsystems, projects). Three surfaces
  expose it – CLI subcommands (`xbsl new-object ...`, JSON output, `--dry-run` computes without
  writing), MCP `meta_*` tools (apply to disk + lint the written files in the same response) and
  LSP `xbsl/meta*` custom requests (compute only; the editor applies via WorkspaceEdit, reading
  open buffers through the injected reader). The VS Code metadata tree is a thin client of these –
  never grow write logic on the TypeScript side.

## Language data (versioned, generated locally)

XBSL is built on Eclipse Xtext + ANTLR. The data is versioned by platform version:
`xbsl/data/element/<version>/{language.json, stdlib.json}` + `index.json` (default/available).
`language.json` – keywords/operators from the grammar (`InternalBsl.g`/`.tokens`); `stdlib.json` –
the type catalog from the distribution docs. Access is via `xbsl/dataset.py` (version choice:
`--element-version` / the `XBSL_ELEMENT_VERSION` env var / the index default).

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
blocks, type expressions, declarations, signatures) live in `xbsl/rules/_syntax.py`; the rules
themselves are split by the sections of the platform document: `style_layout` (layout and wrapping),
`style_naming` (naming), `style_types` (types and signatures), `style_strings` (collections and
strings), `style_conditions` (checks).

Where tokens cannot tell a violation from a forced form, narrow the rule instead of guessing, and say
so in the docstring:
- a nullable `Булево?` must be compared against `Истина` – so `style/boolean-compare` stays `info`;
- structure field names are dictated by the serialization contract (JSON keys) – `style/camel-case`
  skips them;
- string literals (HTML/CSS/SVG) are excluded from `style/line-length`.

When adding or renaming a rule, update in the same change: the rule table in `docs/RULES.md` and
`docs/RULES.ru.md` (id, severity, default, scope, one-line description, docs link) and its docs
mapping in `editors/vscode/src/ruleDocs.ts` (if a platform documentation section stands behind it).
`docs/RULES.*` and the rule-count numbers in it and in the READMEs must stay in sync with
`xbsl list-rules`.

`xbsl/lexer.py` and `xbsl/parser.py` are compiled by mypyc into C extensions
(`XBSL_MYPYC=1`, `.github/workflows/native-wheels.yml`): keep them clean under
`mypy xbsl/lexer.py xbsl/parser.py --ignore-missing-imports`, and avoid constructs mypyc
does not support in native classes (class-level mutable/collection attribute defaults go
to the module level). The modules must stay runnable as plain Python - the native build
is an optional accelerator, never a requirement.
