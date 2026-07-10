# xbsl-lint

**English** · [Русский](https://github.com/keyfire/xbsl-lint/blob/main/README.ru.md)

![CI](https://github.com/keyfire/xbsl-lint/actions/workflows/ci.yml/badge.svg)

A linter for 1C:Element sources — it checks `Name.yaml` (element description) and `Name.xbsl`
(code module) pairs before the server-side compilation that happens on deploy.

> Not affiliated with 1C. "1C:Element", "1C:Fresh" and related names are trademarks of their
> respective owners. Language data is generated from your own distribution. See [NOTICE](https://github.com/keyfire/xbsl-lint/blob/main/NOTICE).

## Why

1C:Element has no external linter: the only code check is the server-side compilation on deploy —
it is slow and knows nothing about project conventions. xbsl-lint gives fast local feedback and
catches what the compiler does not check at all.

## Step 1: generate the language data

The linter relies on language tables (bilingual keywords, operators), an stdlib type catalog, and
the configuration metamodel (element properties). XBSL is built on Eclipse Xtext + ANTLR; these are
extracted from **your** 1C:Element distribution (the `InternalBsl.g` grammar, the documentation, and
the `.xcore` metamodel) and are NOT bundled in this repository. Generate them locally:

```sh
python tools/extract_grammar.py   --dist "<path to the 1C:Element distribution>"
python tools/extract_stdlib.py    --dist "<path to the 1C:Element distribution>"
python tools/extract_metamodel.py --dist "<path to the 1C:Element distribution>"
```

The scripts auto-detect the platform version and place the data under
`xbsllint/data/element/<version>/` (this folder is gitignored). Without the data, the linter and
the tests will tell you to generate it. Pass `--data-dir` (or set `XBSLLINT_DATA_DIR`) to write the
data somewhere else – for instance into a private package that ships it, see
[Extending](#extending-your-own-rules-and-data).

## Step 2: install and run

```sh
pip install xbsllint            # or, from a clone: pip install -e .
xbsllint path/to/sources        # or: python -m xbsllint path/to/sources
```

The extractors from step 1 ship with the repository, not with the PyPI package — clone the
repository to generate the data.

Flags: `--list-rules`, `--select`/`--ignore` (by rule id, rule group — the part of the id before
`/` — or tier letter), `--element-version`, `--data-dir`.

## Rule tiers

- **A. Structure and YAML** — `.xbsl`/`.yaml` pairing, schema validity, `Ид` as a UUID,
  `Ид` uniqueness, `Имя` matching the file name.
- **B. Text and conventions** — typography (en dash, straight quotes),
  encoding/BOM/newlines/trailing whitespace, indentation and line length.
- **C. Code structure** — balance of blocks and `;`, brackets, unused local and loop variables,
  plus the platform's code style conventions (the `style/` group, see below).
- **D. Semantics** — against platform data: type existence (in `новый`, `как` casts, annotations,
  method signatures), form handlers (a yaml handler exists as a method in the paired module), and
  top-level object properties against the configuration metamodel.

## Code style conventions (the `style/` rules)

Twenty-one rules that follow the platform documentation ("Code style conventions" and "Language
idioms"): layout and expression wrapping, naming, type descriptions and signatures, collection
literals, string interpolation, and checks of boolean values and `Неопределено`.

Rules that clean code already satisfies are enabled by default (`warning`) — they guard against
regressions. Rules that typically fire on accumulated legacy debt are `info` and disabled; enable
them to measure the debt and pay it down:

```sh
xbsllint path/to/sources --select style     # all conventions, including the disabled ones
xbsllint path/to/sources --ignore style     # none of them
```

`Запрос{ ... }` blocks (the query DSL) and string literals (HTML/CSS/SVG in web views) are
excluded from these checks. Not covered, and left to the author and review: indentation being a
multiple of four, collection idioms, `Строки.Соединить()` for bulk concatenation, the `?.` / `??`
idioms, and `выбор` instead of an `иначе если` chain.

## Extending: your own rules and data

Two entry point groups let a separate package extend the linter without forking it. This exists for
teams whose rules or language data cannot be published: keep those in a private package that depends
on `xbsllint`.

```toml
# pyproject.toml of your package
dependencies = ["xbsllint>=0.3"]

[project.entry-points."xbsllint.rules"]
myproject = "myproject.rules"        # importing the module runs its @rule decorators

[project.entry-points."xbsllint.data"]
myproject = "myproject:data_root"    # a path, or a callable returning one
```

Install the package and the CLI, the MCP server and the web UI all pick both up – no flags, no
config file. A failing entry point raises instead of warning: a linter that silently drops a rule
stays green in CI and guarantees nothing. `XBSLLINT_NO_PLUGINS=1` ignores every external package
(built-in rules and bundled data only).

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
    <version>/{language.json, stdlib.json, metamodel.json}
```

Pick a version with `--element-version` / the `XBSLLINT_ELEMENT_VERSION` env var / the index
`default`; `--version` shows what is available. Add a new version by re-running the extractors with
a new `--dist`.

The data root itself is resolved in this order: `--data-dir` > `XBSLLINT_DATA_DIR` > a root supplied
by an installed `xbsllint.data` entry point > `xbsllint/data/element` inside the package.

## Tests

```sh
pip install -e ".[dev]"
pytest
```

Data-dependent tests are skipped automatically when the data has not been generated.

## License

MIT — see [LICENSE](https://github.com/keyfire/xbsl-lint/blob/main/LICENSE). Trademarks and data provenance — [NOTICE](https://github.com/keyfire/xbsl-lint/blob/main/NOTICE).
How to add a rule — [CONTRIBUTING.md](https://github.com/keyfire/xbsl-lint/blob/main/CONTRIBUTING.md).
