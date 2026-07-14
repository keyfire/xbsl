# xbsl-lint

**English** · [Русский](https://github.com/keyfire/xbsl-lint/blob/main/README.ru.md)

![CI](https://github.com/keyfire/xbsl-lint/actions/workflows/ci.yml/badge.svg)

A linter for 1C:Element sources – it checks `Name.yaml` (element description) and `Name.xbsl`
(code module) pairs before the server-side compilation that happens on deploy.

> Not affiliated with 1C. "1C:Element", "1C:Fresh" and related names are trademarks of their
> respective owners. Language data is generated from your own distribution. See [NOTICE](https://github.com/keyfire/xbsl-lint/blob/main/NOTICE).

Development notes and updates (in Russian): the [1C × AI: engineering workshop](https://t.me/ceh_1c_ai) Telegram channel.

## Why

1C:Element has no external linter: the only code check is the server-side compilation on deploy –
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

The extractors from step 1 ship with the repository, not with the PyPI package – clone the
repository to generate the data.

Flags: `--list-rules`, `--select`/`--enable`/`--ignore` (by rule id, rule group – the part of the id
before `/` – or tier letter), `--fix`, `--baseline`/`--write-baseline`, `--element-version`,
`--data-dir`, `--lang`, `--format text|json|codeclimate`.
`--fix` repairs the mechanical findings in place – trailing whitespace, typography characters
(em dash → en dash, `…` → `...`, curly quotes and comment guillemets → straight), and mixed
newlines (normalized to the dominant style) – then reports whatever is left. It only applies
unambiguous edits and only for rules active in the run (so `--fix --enable typography` also pays
down the em-dash/guillemets debt); anything needing judgment is never touched.
For editor integration, `--stdin --filename NAME` checks a single buffer read from stdin (per-file
rules only); the JSON payload (`{diagnostics, summary}`) is the same one the MCP server returns.
`xbsllint --index PATH` dumps a JSON index of the project to stdout instead of linting – the
objects (with tabular sections, module-declared local types and the member families for dot
completion), the method declarations with their annotations and the named form components, with
POSIX paths relative to the root and 1-based lines – for go-to-definition and completion in
editors.
`--format codeclimate` emits a GitLab Code Quality report (Code Climate issues) with paths relative
to the current directory – run it from the repository root and save the output as the
`codequality` artifact.

## Output language

Rule titles and diagnostic messages come in Russian and English. The language is picked by
`--lang ru|en` > the `XBSLLINT_LANG` env var > the system locale > Russian. Type names, keywords
and other XBSL text inside a message are never translated – only the wording around them. The MCP
server and the web panel follow the same setting (the web panel also has an in-page RU/EN toggle).

## Use in CI

`xbsllint` exits non-zero only when a run produces an **error-severity** finding, so it works as a
pipeline gate as-is – warnings and `info` do not fail the build. The one prerequisite is the
language data (see [Step 1](#step-1-generate-the-language-data)): generate it in the job (the
extractors ship with the repository, so check the repo out), or depend on a package that ships the
data via the `xbsllint.data` entry point (see [Extending](#extending-your-own-rules-and-data)) and
just `pip install` it.

### GitHub Actions

```yaml
lint:
  runs-on: ubuntu-latest
  steps:
    - uses: actions/checkout@v4
    - uses: actions/setup-python@v5
      with: { python-version: "3.12" }
    - run: pip install xbsllint
    # generate the data from your 1C:Element distribution (or install a package that ships it):
    - run: |
        python tools/extract_grammar.py  --dist "$ELEMENT_DIST"
        python tools/extract_stdlib.py   --dist "$ELEMENT_DIST"
        python tools/extract_metamodel.py --dist "$ELEMENT_DIST"
    - run: xbsllint e1c/          # fails the job on any error-severity finding
```

### GitLab CI (Code Quality widget)

`--format codeclimate` writes a Code Climate report that GitLab renders inline on the merge request.
Run it from the repository root and save the output as the `codequality` report. The command still
returns non-zero on error-severity findings, so `artifacts.when: always` keeps the report even when
the job gates the pipeline (drop the gate with a trailing `|| true` if you want the widget only):

```yaml
lint:
  script:
    - pip install xbsllint
    - xbsllint --format codeclimate e1c/ > gl-code-quality-report.json
  artifacts:
    when: always
    reports:
      codequality: gl-code-quality-report.json
```

## Rule tiers

- **A. Structure and YAML** – `.xbsl`/`.yaml` pairing, schema validity, `Ид` as a UUID,
  `Ид` uniqueness, `Имя` matching the file name.
- **B. Text and conventions** – typography (en dash, straight quotes),
  encoding/BOM/newlines/trailing whitespace, indentation and line length.
- **C. Code structure** – balance of blocks and `;`, brackets, unused local and loop variables,
  a structure reference field that must be `обз`, plus the platform's code style conventions
  (the `style/` group, see below).
- **D. Semantics** – against platform data and the project itself: types, enumeration values,
  cross-file consistency (see below).

The type rules of tier D cover every type position in code (`новый`, `как` casts, annotations,
signatures) and every `Тип:` value in yaml (unions `А|Б|?`, generics, nullable): the root must
be a known type – stdlib, a project object or a module-declared local type – and a dotted chain
rooted at a project object must stay within the family that object generates: the derived types
extracted from the distribution docs (`Ссылка`, `Объект`, `СоздатьОбъект`, the automatic
forms...), its tabular sections and module structures. Namespace-qualified references
(`Справочник.X.Ссылка`) also check that the object exists under that kind, and the values of
project enumerations are verified both in code and in yaml bindings.

The cross-file rules of tier D catch what the compiler reports late or not at all: a yaml
handler missing from the paired module, a foreign-subsystem type used without an `Импорт:`
entry, a dynamic list typed by the automatic list form that misses an attribute of its object,
a cross-component `Компоненты.X.Метод()` call to a method without a visibility annotation,
environment mismatches (`@НаСервере` called from a client handler without `@ДоступноСКлиента`,
a client-only module used from an HTTP service), reserved names (`Тип`/`type` as a field or
parameter, a component property named like a built-in one), methods that nothing references,
and top-level yaml properties against the configuration metamodel. The `query/` group
parses `Запрос{ ... }` blocks and verifies the tables of `ИЗ`/`СОЕДИНЕНИЕ` against the
project objects and their tabular sections; a block with constructs outside the supported
subset (temporary tables, unions, subqueries) is skipped whole rather than guessed.

## Names of project elements (the `naming/` rules)

Twelve rules from the platform standard "Names of project elements" – it is mandatory in new code,
so all of them are warnings. They read the descriptions (`.yaml`): the name of the element itself
and the names of its attributes, dimensions, resources, tabular sections and enumeration values.

The number of a name is checked against the kind: catalogs, documents, registers and tabular
sections are named in the plural, enumerations and structures in the singular (`naming/number`).
This is morphology, not a guess by the ending: `Номенклатура` is singular and the standard allows
it, while `Программы` and `Акции` without the case read as a genitive singular. Needs the `[morph]`
extra (`pip install "xbsllint[morph]"`); without it the rule stays silent.

The rest: the letter `ё` and underscores in names, an abbreviation written as one word (`Ндс`, not
`НДС`), an English term as the original (`Xml`, not `Хмл`), `Вид` rather than `Тип` for
enumerations, the kind inside its own name (`ОтчетЗависшиеЗадачи`), filler words (`Управление`,
`Менеджер`), an environment suffix on a common module (`ОбменДаннымиКлиентИСервер` – the
environment is a property, not a name), a boolean attribute named by a negation (`НетОшибок`
instead of `Успешно`), an empty `Представление`, and the prefixes required for certain kinds
(`КлючДоступа`, `ПравоНа`, `Навигация`).

## Code style conventions (the `style/` rules)

Twenty-one rules that follow the platform documentation ("Code style conventions" and "Language
idioms"): layout and expression wrapping, naming, type descriptions and signatures, collection
literals, string interpolation, and checks of boolean values and `Неопределено`.

Rules that clean code already satisfies are enabled by default (`warning`) – they guard against
regressions. Rules that typically fire on accumulated legacy debt are `info` and disabled; enable
them to measure the debt and pay it down:

```sh
xbsllint path/to/sources --select style     # ONLY these rules (replaces the default set)
xbsllint path/to/sources --enable style     # the default set PLUS these
xbsllint path/to/sources --ignore style     # the default set minus these
```

`--select`, `--enable` and `--ignore` accept a rule id, a group (the part before `/`) or a tier
letter, repeated or comma-separated. `--select` narrows to exactly the given rules; `--enable`
switches on off-by-default rules on top of the defaults.

`Запрос{ ... }` blocks (the query DSL) and string literals (HTML/CSS/SVG in web views) are
excluded from these checks. Not covered, and left to the author and review: indentation being a
multiple of four, collection idioms, `Строки.Соединить()` for bulk concatenation, the `?.` / `??`
idioms, and `выбор` instead of an `иначе если` chain.

## Baseline: adopt a rule on a legacy codebase

To enable a rule over code that already violates it without drowning in legacy findings, freeze the
current findings into a baseline and hold only new code to the rule:

```sh
xbsllint e1c/app --enable style --write-baseline baseline.json   # freeze the debt once
xbsllint e1c/app --enable style --baseline baseline.json         # only NEW findings surface
```

A finding's identity is `(file, rule, message)` with an allowed count, so moving a line keeps its
finding suppressed while a genuinely new violation surfaces. The summary reports how many findings
the baseline suppressed and how many of its entries are now stale (debt paid down) – a signal to
rewrite the file. Paths are stored relative to the baseline file, so commit it at the repository
root and run the linter from anywhere.

## Extending: your own rules, data and severities

Three entry point groups let a separate package extend the linter without forking it. This exists
for teams whose rules or language data cannot be published: keep those in a private package that
depends on `xbsllint`.

```toml
# pyproject.toml of your package
dependencies = ["xbsllint>=0.3"]

[project.entry-points."xbsllint.rules"]
myproject = "myproject.rules"        # importing the module runs its @rule decorators

[project.entry-points."xbsllint.data"]
myproject = "myproject:data_root"    # a path, or a callable returning one

[project.entry-points."xbsllint.severity"]
myproject = "myproject:severity_overrides"   # {rule id: "error"|"warning"|"info"|"off"}
```

The severity dict (or a zero-argument callable returning one) raises or lowers the default level
of any rule – built-in or plugin – for every run in this installation: a project may treat, say,
`style/abbreviation-case` as a warning while the published default stays info. `"off"` removes a
rule from the default set (an explicit `--select`/`--enable` still turns it on, at its base level).

Install the package and the CLI, the MCP server and the web UI all pick everything up – no flags,
no config file. A failing entry point raises instead of warning: a linter that silently drops a
rule stays green in CI and guarantees nothing; an override naming an unknown rule id or level
raises for the same reason. `XBSLLINT_NO_PLUGINS=1` ignores every external package (built-in
rules, bundled data and default severities only).

## LSP server (experimental)

`xbsllint-lsp` (the `[lsp]` extra: `pip install "xbsllint[lsp]"`) runs the linter as a
long-living Language Server over stdio: live per-file diagnostics as you type, project-wide
diagnostics on save, go to definition, completion and hover over a resident project index,
and quick-fix code actions - without paying the interpreter start-up cost per call. Flags:
`--project-root` (the sources root relative to the workspace folder), `--select`/`--ignore`/
`--enable`, `--data-dir`. Any LSP-capable editor (VS Code, Neovim, JetBrains) can spawn it.

## MCP server

A thin adapter over the same core: an agent (e.g. Claude Code) can call the checks as tools and
receive structured diagnostics.

```sh
pip install -e ".[mcp]"
claude mcp add xbsllint -- xbsllint-mcp
```

Tools: `lint_paths(paths)`, `lint_source(filename, content)`, `list_rules()`. The core and the CLI
do not require `mcp` – it lives only in the `[mcp]` extra.

## Web interface

A local page: point it at a project folder and see the diagnostics. Standard library only (no
external dependencies), binds to `127.0.0.1` only.

```sh
xbsllint-web            # then open http://127.0.0.1:8771/
```

Per-tier rule toggles, a data-version selector, severity/text filters, dark/light theme; clicking
a diagnostic opens the file in VS Code (`vscode://`).

## Editor support (VS Code)

A VS Code extension in [`editors/vscode`](editors/vscode) gives `.xbsl` syntax highlighting,
live diagnostics as you type (`--stdin`), workspace diagnostics on save (a full linter run in
the background brings the project-scope rules into the editor), index-based go-to-definition
and completion across the project (`xbsllint --index`), a form preview with a properties
panel, and a deploy button powered by [elemctl](https://github.com/keyfire/elemctl). It is
published on the [Marketplace](https://marketplace.visualstudio.com/items?itemName=keyfire.xbsl)
and [Open VSX](https://open-vsx.org/extension/keyfire/xbsl); its
[README](editors/vscode/README.md) covers settings, behavior and requirements. See also the
companion [XBSL Debug](https://marketplace.visualstudio.com/items?itemName=keyfire.xbsl-debug)
extension from the [elemctl](https://github.com/keyfire/elemctl) project.

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

MIT – see [LICENSE](https://github.com/keyfire/xbsl-lint/blob/main/LICENSE). Trademarks and data provenance – [NOTICE](https://github.com/keyfire/xbsl-lint/blob/main/NOTICE).
How to add a rule – [CONTRIBUTING.md](https://github.com/keyfire/xbsl-lint/blob/main/CONTRIBUTING.md).
