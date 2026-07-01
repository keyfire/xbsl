# xbsl-lint

**English** · [Русский](README.ru.md)

![CI](https://github.com/keyfire/xbsl-lint/actions/workflows/ci.yml/badge.svg)

A linter for 1C:Element sources — it checks `Name.yaml` (element description) and `Name.xbsl`
(code module) pairs before the server-side compilation that happens on deploy.

> Not affiliated with 1C. "1C:Element", "1C:Fresh" and related names are trademarks of their
> respective owners. Language data is generated from your own distribution. See [NOTICE](NOTICE).

## Why

1C:Element has no external linter: the only code check is the server-side compilation on deploy —
it is slow and knows nothing about project conventions (typography, no issue numbers in code, and
so on). xbsl-lint gives fast local feedback and catches what the compiler does not check at all.

## Step 1: generate the language data

The linter relies on language tables (bilingual keywords, operators) and an stdlib type catalog.
XBSL is built on Eclipse Xtext + ANTLR; these tables are extracted from **your** 1C:Element
distribution (the `InternalBsl.g` grammar + the documentation) and are NOT bundled in this
repository. Generate them locally:

```sh
python tools/extract_grammar.py --dist "<path to the 1C:Element distribution>"
python tools/extract_stdlib.py  --dist "<path to the 1C:Element distribution>"
```

The scripts auto-detect the platform version and place the data under
`xbsllint/data/element/<version>/` (this folder is gitignored). Without the data, the linter and
the tests will tell you to generate it.

## Step 2: install and run

```sh
pip install -e .
xbsllint path/to/sources        # or: python -m xbsllint path/to/sources
```

Flags: `--list-rules`, `--select`/`--ignore` (by rule id or tier letter), `--element-version`.

## Rule tiers

- **A. Structure and YAML** — `.xbsl`/`.yaml` pairing, schema validity, `Ид` as a UUID,
  `Ид` uniqueness, `Имя` matching the file name.
- **B. Text and conventions** — typography (en dash, straight quotes), no issue numbers in code,
  encoding/BOM/newlines/trailing whitespace.
- **C. Code structure** — balance of blocks and `;`, brackets, unused local and loop variables.
- **D. Semantics** — existence of the type in `новый` against the stdlib catalog.

## MCP server

A thin adapter over the same core: an agent (e.g. Claude Code) can call the checks as tools and
receive structured diagnostics.

```sh
pip install -e ".[mcp]"
claude mcp add xbsllint -- xbsllint-mcp
```

Tools: `lint_paths(paths)`, `lint_source(filename, content)`, `list_rules()`. The core and the CLI
do not require `mcp` — it lives only in the `[mcp]` extra.

## Web interface

A local page: point it at a project folder and see the diagnostics. Standard library only (no
external dependencies), binds to `127.0.0.1` only.

```sh
xbsllint-web            # then open http://127.0.0.1:8771/
```

Per-tier rule toggles, a data-version selector, severity/text filters, dark/light theme; clicking
a diagnostic opens the file in VS Code (`vscode://`).

## Element versions

The data is versioned by platform version:

```
xbsllint/data/element/
    index.json            # { available: [...], default: "<version>" }
    <version>/{language.json, stdlib.json}
```

Pick a version with `--element-version` / the `XBSLLINT_ELEMENT_VERSION` env var / the index
`default`; `--version` shows what is available. Add a new version by re-running the extractors with
a new `--dist`.

## Tests

```sh
pip install -e ".[dev]"
pytest
```

Data-dependent tests are skipped automatically when the data has not been generated.

## License

MIT — see [LICENSE](LICENSE). Trademarks and data provenance — [NOTICE](NOTICE).
How to add a rule — [CONTRIBUTING.md](CONTRIBUTING.md).
