# xbsl

**English** · [Русский](https://github.com/keyfire/xbsl/blob/main/README.ru.md)

![CI](https://github.com/keyfire/xbsl/actions/workflows/ci.yml/badge.svg)

The XBSL (1C:Element) toolkit: a linter with autofixes, an LSP server, a project index,
platform documentation search, metadata scaffolding and an MCP server for AI agents.
It works on `Name.yaml` (element description) and `Name.xbsl` (code module) pairs –
before the server-side compilation that happens on deploy.

> Before 0.16 the project was named **xbsl-lint** (the `xbsllint` package); the old commands,
> imports, env vars and entry-point groups keep working as aliases.

> Not affiliated with 1C. "1C:Element", "1C:Fresh" and related names are trademarks of their
> respective owners. Language data is generated from your own distribution. See [NOTICE](https://github.com/keyfire/xbsl/blob/main/NOTICE).

Development notes and updates (in Russian): the [1C × AI: engineering workshop](https://t.me/ceh_1c_ai) Telegram channel.

## Why

1C:Element has no external tooling: the only code check is the server-side compilation on deploy –
it is slow and knows nothing about project conventions. xbsl gives fast local feedback, catches
what the compiler does not check at all, and takes over the metadata mechanics – creating
objects, attributes and forms.

## How it works

One engine, four surfaces. The core reads the `Имя.yaml` + `Имя.xbsl` pairs, and the scaffolding
writes them back; the CLI, the LSP server, the MCP server and the web UI are thin adapters over
the same core, so every surface sees the same rules, data and templates:

![The engine core (linter, autofixes, project index, docs search) and the metadata scaffolding read and write the project sources; a private plugin adds Element language data and custom rules via entry points; the CLI, the LSP server (VS Code), the MCP server (AI agents) and the web UI are surfaces over the same core](https://raw.githubusercontent.com/keyfire/xbsl/main/images/how-it-works.png)

## Quick start

**Step 1 – generate the language data.** The linter relies on tables extracted from **your**
1C:Element distribution (keywords, the stdlib type catalog, the configuration metamodel); they
are NOT bundled in this repository. From a clone of the repository:

```sh
python tools/extract_grammar.py   --dist "<path to the 1C:Element distribution>"
python tools/extract_stdlib.py    --dist "<path to the 1C:Element distribution>"
python tools/extract_metamodel.py --dist "<path to the 1C:Element distribution>"
```

The scripts auto-detect the platform version and place the data under `xbsl/data/element/`
(gitignored). Details – data location, private data packages –
in the [guide](https://github.com/keyfire/xbsl/blob/main/docs/GUIDE.md#language-data).

**Step 2 – install and run.**

```sh
pip install xbsl            # or, from a clone: pip install -e .
xbsl path/to/sources        # or: python -m xbsl path/to/sources
xbsl self-update            # upgrade to the latest PyPI version, safe with busy exe stubs
```

The main flags: `--list-rules`, `--fix`, `--select`/`--enable`/`--ignore`,
`--baseline`/`--write-baseline`, `--format text|json|codeclimate`, `--lang ru|en`. The full
flag reference, the `--stdin`/`--index` editor modes, native mypyc wheels and the `self-update`
mechanics – in the [guide](https://github.com/keyfire/xbsl/blob/main/docs/GUIDE.md#cli-flags).

## What it does

**Rules.** 87 rules in four tiers: **A** – structure and yaml schema, **B** – text and
typography conventions, **C** – code structure (blocks, brackets, unused locals, the `style/`
code conventions), **D** – semantics against the platform data and the project itself: every
type position in code and yaml, enumeration values, `Запрос{...}` tables, cross-file
consistency, the types of attached `.xlib` libraries. The full list with severities and
documentation links – [docs/RULES.md](https://github.com/keyfire/xbsl/blob/main/docs/RULES.md);
at runtime – `xbsl --list-rules`; what tier D verifies in depth –
[the guide](https://github.com/keyfire/xbsl/blob/main/docs/GUIDE.md#rules-in-depth).

**Autofixes.** `--fix` repairs the mechanical findings in place – trailing whitespace,
typography characters, mixed newlines – and only them: anything needing judgment is never
touched.

**Baseline.** Adopt a rule on a legacy codebase without drowning: freeze the current findings
once, hold only new code to the rule; the same file records point exclusions with reasons.
[Details](https://github.com/keyfire/xbsl/blob/main/docs/GUIDE.md#baseline-adopt-a-rule-on-a-legacy-codebase).

**Metadata scaffolding.** Creating objects, attributes, routes and forms without hand-writing
yaml: 33 element kinds, forms generated with real content, context-aware `rename-object`,
access-control editing. The same operations through the CLI, MCP and LSP:

```sh
xbsl new-object vendor/App/Основное Справочник Товары
xbsl add-field vendor/App/Основное/Товары.yaml реквизит Цвет --type Строка
xbsl add-form . --name Товары            # object + list forms, registered
xbsl rename-object . Товары Номенклатура # rename files + update references
```

All subcommands with their options –
[the guide](https://github.com/keyfire/xbsl/blob/main/docs/GUIDE.md#metadata-scaffolding).

**Editors.** The [VS Code extension](https://github.com/keyfire/xbsl/blob/main/editors/vscode/README.md)
([Marketplace](https://marketplace.visualstudio.com/items?itemName=keyfire.xbsl),
[Open VSX](https://open-vsx.org/extension/keyfire/xbsl)): syntax highlighting, live and
project-wide diagnostics, go-to-definition and completion, a form preview, a metadata tree and
a deploy button. Under the hood is `xbsl-lsp` – a Language Server any LSP-capable editor can
spawn ([details](https://github.com/keyfire/xbsl/blob/main/docs/GUIDE.md#lsp-server)).

**Code templates.** Type `есл`, press Ctrl+Space – get the whole construct with edit points.
51 builtin templates (each one parsed by the linter's own parser, so it cannot insert broken
code), your own in `.xbsl-templates.json`, a management panel in VS Code; the mechanism and
file format mirror 1C:EDT.
[Details](https://github.com/keyfire/xbsl/blob/main/docs/GUIDE.md#code-templates).

**Documentation search.** `tools/extract_docs.py` turns the distribution's Element reference
into a local full-text `docs.sqlite`; the `xbsl.docs` API and the MCP tools search it.
[Details](https://github.com/keyfire/xbsl/blob/main/docs/GUIDE.md#documentation-search).

**MCP server.** `claude mcp add xbsl -- xbsl-mcp`: linting, documentation search,
`type_members` and every scaffolding operation as `meta_*` tools – an agent creates an object
and gets the lint of the written files in one round trip.
[Details](https://github.com/keyfire/xbsl/blob/main/docs/GUIDE.md#mcp-server).

**Web interface.** `xbsl-web` – a local page over the same engine: rule toggles, filters,
themes. [Details](https://github.com/keyfire/xbsl/blob/main/docs/GUIDE.md#web-interface).

**CI.** The exit code is non-zero only on error-severity findings, so `xbsl` gates a pipeline
as-is; `--format codeclimate` feeds the GitLab Code Quality widget. Ready-made GitHub
Actions and GitLab CI jobs –
[the guide](https://github.com/keyfire/xbsl/blob/main/docs/GUIDE.md#use-in-ci).

**Extending.** Entry points let a private package add rules, ship language data and override
severities without forking; `XBSL_NO_PLUGINS=1` turns every plugin off.
[Details](https://github.com/keyfire/xbsl/blob/main/docs/GUIDE.md#extending-your-own-rules-data-and-severities).

Output language (RU/EN), Element data versions and the data root resolution order are also
covered in the [guide](https://github.com/keyfire/xbsl/blob/main/docs/GUIDE.md#output-language).

## Tests

```sh
pip install -e ".[dev]"
pytest
```

Data-dependent tests are skipped automatically when the data has not been generated.

## License

MIT – see [LICENSE](https://github.com/keyfire/xbsl/blob/main/LICENSE). Trademarks and data provenance – [NOTICE](https://github.com/keyfire/xbsl/blob/main/NOTICE).
How to add a rule – [CONTRIBUTING.md](https://github.com/keyfire/xbsl/blob/main/CONTRIBUTING.md).
