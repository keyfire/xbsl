---
title: "xbsl user guide"
description: "The complete guide to the toolkit – installation, CLI flags, CI setup, the baseline mechanism, and metadata scaffolding."
sidebar:
  label: Guide
  order: 2
---

The complete guide to the toolkit. The [README](https://github.com/keyfire/xbsl/blob/main/README.md)
is the short tour; everything it links to in depth lives here. The full rule list is a separate
document – [RULES.md](/RULES).

- [Language data](#language-data)
- [Installation details](#installation-details)
- [CLI flags](#cli-flags)
- [Output language](#output-language)
- [Use in CI](#use-in-ci)
- [Rules in depth](#rules-in-depth)
- [Baseline: adopt a rule on a legacy codebase](#baseline-adopt-a-rule-on-a-legacy-codebase)
- [Metadata scaffolding](#metadata-scaffolding)
- [Extending: your own rules, data and severities](#extending-your-own-rules-data-and-severities)
- [LSP server](#lsp-server)
- [Code templates](#code-templates)
- [Documentation search](#documentation-search)
- [MCP server](#mcp-server)
- [Web interface](#web-interface)
- [Element versions](#element-versions)

## Language data

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
`xbsl/data/element/<version>/` (this folder is gitignored). Without the data, the linter and
the tests will tell you to generate it. Pass `--data-dir` (or set `XBSL_DATA_DIR`) to write the
data somewhere else – for instance into a private package that ships it, see
[Extending](#extending-your-own-rules-data-and-severities).

The extractors ship with the repository, not with the PyPI package – clone the repository to
generate the data.

## Installation details

```sh
pip install xbsl            # or, from a clone: pip install -e .
xbsl path/to/sources        # or: python -m xbsl path/to/sources
xbsl self-update            # upgrade to the latest PyPI version
```

`self-update` upgrades the package by unpacking the wheel straight into site-packages – safe
even when `pip install --upgrade` fails with WinError 32 because an exe is busy (the typical
case: `xbsl-lsp.exe` held by the VS Code LSP server, `xbsl-mcp.exe` by an agent's MCP
session). The busy stubs are left alone and pick up the new code on the next start; restart
the long-living processes after the update. `--version X.Y.Z` installs a specific version.
In an editable install from a clone the command refuses – `git pull` updates that one.

The hot modules (the lexer and the parser) can be compiled by mypyc into C extensions:
`XBSL_MYPYC=1` at build time (needs mypy and a C compiler: MSVC Build Tools on Windows,
Xcode CLT on macOS, gcc on Linux). Users never need a compiler: the ready-made native
wheels are built by CI (`native-wheels.yml`), and without a matching wheel the package
runs as plain Python – no compiler, no loss of functionality.

## CLI flags

`--list-rules`, `--where` (data root, source and versions), `--select`/`--enable`/`--ignore` (by
rule id, rule group – the part of the id before `/` – or tier letter), `--fix`,
`--baseline`/`--write-baseline`, `--element-version`, `--data-dir`, `--lang`,
`--format text|json|codeclimate`.

`--fix` repairs the mechanical findings in place – trailing whitespace, typography characters
(em dash → en dash, `…` → `...`, curly quotes and comment guillemets → straight), and mixed
newlines (normalized to the dominant style) – then reports whatever is left. It only applies
unambiguous edits and only for rules active in the run (so `--fix --enable typography` also pays
down the em-dash/guillemets debt); anything needing judgment is never touched.

For editor integration, `--stdin --filename NAME` checks a single buffer read from stdin (per-file
rules only); the JSON payload (`{diagnostics, summary}`) is the same one the MCP server returns.

`xbsl --index PATH` dumps a JSON index of the project to stdout instead of linting – the
objects (with their `TabularParts`, module-declared local types and the member families for dot
completion), the method declarations with their annotations and the named form components, with
POSIX paths relative to the root and 1-based lines – for go-to-definition and completion in
editors.

`--format codeclimate` emits a GitLab Code Quality report (Code Climate issues) with paths relative
to the current directory – run it from the repository root and save the output as the
`codequality` artifact.

## Output language

Rule titles and diagnostic messages come in Russian and English. The language is picked by
`--lang ru|en` > the `XBSL_LANG` env var > the system locale > Russian. Type names, keywords
and other XBSL text inside a message are never translated – only the wording around them. The MCP
server and the web panel follow the same setting (the web panel also has an in-page RU/EN toggle).

## Use in CI

`xbsl` exits non-zero only when a run produces an **error-severity** finding, so it works as a
pipeline gate as-is – warnings and `info` do not fail the build. The one prerequisite is the
language data (see [Language data](#language-data)): generate it in the job (the extractors ship
with the repository, so check the repo out), or depend on a package that ships the data via the
`xbsl.data` entry point (see [Extending](#extending-your-own-rules-data-and-severities)) and
just `pip install` it.

### GitHub Actions

```yaml
lint:
  runs-on: ubuntu-latest
  steps:
    - uses: actions/checkout@v4
    - uses: actions/setup-python@v5
      with: { python-version: "3.12" }
    - run: pip install xbsl
    # generate the data from your 1C:Element distribution (or install a package that ships it):
    - run: |
        python tools/extract_grammar.py  --dist "$ELEMENT_DIST"
        python tools/extract_stdlib.py   --dist "$ELEMENT_DIST"
        python tools/extract_metamodel.py --dist "$ELEMENT_DIST"
    - run: xbsl acme/          # fails the job on any error-severity finding
```

### GitLab CI (Code Quality widget)

`--format codeclimate` writes a Code Climate report that GitLab renders inline on the merge request.
Run it from the repository root and save the output as the `codequality` report. The command still
returns non-zero on error-severity findings, so `artifacts.when: always` keeps the report even when
the job gates the pipeline (drop the gate with a trailing `|| true` if you want the widget only):

```yaml
lint:
  script:
    - pip install xbsl
    - xbsl --format codeclimate acme/ > gl-code-quality-report.json
  artifacts:
    when: always
    reports:
      codequality: gl-code-quality-report.json
```

## Rules in depth

**The full list of all 87 rules** (severity, default state, scope, links to platform
documentation sections) is in [RULES.md](/RULES);
at runtime – `xbsl --list-rules`. The tier overview is in the README; below is what the deeper
tiers actually verify.

The type rules of tier D cover every type position in code (`new`, `as` casts, annotations,
signatures) and every `Type:` key in yaml (unions `A|B|?`, generics, nullable): the root must
be a known type – stdlib, a project object, a module-declared local type or a global type of a
declared library (see below) – and a dotted chain
rooted at a project object must stay within the family that object generates: the derived types
extracted from the distribution docs (`Reference`, `Object`, `CreateObject`, the automatic
forms...), its `TabularParts` and module structures. Namespace-qualified references
(`Catalog.X.Reference`) also check that the object exists under that kind, and the values of
project enumerations are verified both in code and in yaml bindings.

The types of the declared libraries come from their archives. The project descriptor declares the
coordinates only – `Vendor`, `Name` and `Version` – so the names are read from the
`{Vendor}-{Name}-{Version}.xlib` archive, looked up in the project descriptor's directory and
above it (up to four levels) – where the archive sits when the sources are shipped. An element
becomes known when its `VisibilityScope` is `Global`; the rest is the library's own business.
With no archive next to the sources the library types stay unknown, exactly as they were before
libraries were understood at all.

The cross-file rules of tier D catch what the compiler reports late or not at all: a `Handler:`
in yaml with no method in the paired module, a foreign-subsystem type used without an `Import:`
entry, a `DynamicList` typed by the automatic list form that misses an attribute of its object,
a cross-component call `Components.X.Method()` that carries no visibility annotation,
environment mismatches (`@OnServer` called from a client handler without `@AvailableFromClient`,
a client module used from an `HttpService`), reserved names
(a field or parameter named `Type` in either language spelling, a component property named like
a built-in one), methods that nothing references,
and top-level yaml properties against the configuration metamodel. The `query/` group
parses `Query{ ... }` blocks and verifies the `FROM` / `JOIN` tables against the
project objects and their `TabularParts`; a block with constructs outside the supported
subset (temporary tables, unions, subqueries) is skipped whole rather than guessed.

Detailed group descriptions – `query/` (a composite type in `IN` with a subquery),
`project/` (project properties), `naming/` (the naming standard, the `[morph]` extra) and
`style/` (code-writing conventions and their on/off policy) – live in
[RULES.md](/RULES).

## Baseline: adopt a rule on a legacy codebase

To enable a rule over code that already violates it without drowning in legacy findings, freeze the
current findings into a baseline and hold only new code to the rule:

```sh
xbsl acme/app --enable style --write-baseline baseline.json   # freeze the debt once
xbsl acme/app --enable style --baseline baseline.json         # only NEW findings surface
```

A finding's identity is `(file, rule, message)` with an allowed count, so moving a line keeps its
finding suppressed while a genuinely new violation surfaces. The summary reports how many findings
the baseline suppressed and how many of its entries are now stale (debt paid down) – a signal to
rewrite the file. Paths are stored relative to the baseline file, so commit it at the repository
root and run the linter from anywhere.

The same file also records point exclusions with their reasons: an entry's value is either a
bare count or `{"count": N, "reason": "..."}` – the reason says why the code is right on
purpose. Reasons are written by the "Exclude the finding" lightbulb action of the
[VS Code extension](https://github.com/keyfire/xbsl/blob/main/editors/vscode/README.md#excluding-a-finding-the-baseline) (or by hand);
`--write-baseline` keeps the reasons of the identities that survive a rewrite. The LSP server
accepts the same `--baseline FILE` flag, so exclusions disappear in editors too. The identity
includes the message text: write and check the baseline under the same output language.

## Metadata scaffolding

The toolkit takes over the metadata mechanics: UUIDs, indentation, precise yaml insertions,
duplicate checks and section/kind compatibility. The same operations are exposed through the
CLI (subcommands, JSON output), MCP (the `meta_*` tools for agents) and LSP (the `xbsl/meta*`
custom requests that power the VS Code metadata tree).

33 kinds of project element are creatable – from `Catalog` and `Document` to `VirtualTable`
(paired with its mandatory `.xbql` query), `ScheduledJob`, contracts, rights and
commands. Each kind carries what the docs make mandatory: the platform's own default scope
(`InSubsystem` – widen it deliberately with `--scope`), a module stub for the handler the
kind cannot live without, and a note for whatever the generator must not invent for you. Kinds
whose content is drawn in the designer (`ReportPanel`, `IntegrationProcess`) are
deliberately absent.

![The VS Code tree, AI agents and the terminal call the same scaffolding core; it writes created and point-edited yaml/xbsl files, the linter checks what was written, and the response carries files, notes and the lint report; the LSP surface returns full texts for the editor to apply](https://raw.githubusercontent.com/keyfire/xbsl/main/images/scaffolding.png)

```sh
xbsl new-project . vendor App                          # descriptor + module + a subsystem
xbsl new-object <subsystem-dir> <kind> <name>          # kind: Catalog, Document, Enum, ... (--help spells them)
xbsl add-field <object>.yaml <section> <field> --type <type>
xbsl add-form . --name <object>                        # object + list forms, registered
xbsl add-form . --name <object> --forms list-cards     # list form as a card grid
xbsl new-object <subsystem-dir> <http-service-kind> <name> --routes "GET /, POST /, GET /{id}"
xbsl add-route  <service>.yaml "DELETE /{id}"          # url template + handler stub
xbsl add-method <module>.xbsl <method> --annotations <annotation> --after <existing-method>
xbsl add-subsystem vendor/App <name>
xbsl add-dependency . acme CurrencyConverter 2.0       # attach a library to the project
xbsl rename-object . <old-name> <new-name>             # rename files + update references
xbsl set-access . --name <object> --default <access-method>
xbsl object-info . --name <object>                     # fields, tabulars, forms, namespace
xbsl project-info .                                    # projects, subsystems, objects by kind
```

The kind, the section, the annotations, the access methods and every identifier reach the CLI in
the spelling the platform uses for the project's development language; the prose of this page
names them by their English equivalents (`Catalog`, `Attributes`, `OnServer`,
`PermitAuthenticated`), which is why the examples above use placeholders.
`xbsl new-object --help` lists the kinds a project can hold, spelled the way the command wants
them.

Forms are generated with real content: input fields per attribute (including the standard
`Name` / `Number` / `Date` fields and hierarchy support), `DynamicList` columns, `TabularParts`
tables, a report form with parameters; the form is registered in the `Interface` section of its
owner. `--dry-run` prints the changes (with full file texts) without writing – this is how
the VS Code extension applies them through its own undo-friendly edits.

`--forms list-cards` builds the list form as a card grid instead of a table: a `CustomList`
whose `RowsContainer` is a `MatrixGroup`, plus a generated `ListRow<Name>` row component named
after the object. The card takes a `Title`, a photo (an attribute of type `BinaryObject.Reference`
switches the card to `CustomCard`, with the image above the caption) and up to three more
fields, dates formatted; notes report what landed on the card and what did not.
`--card-min-width` sets the grid column width (default 400, 250 with a photo) and
`--card-placeholder` the image shown when the photo is empty.

`add-dependency` attaches a library – it writes the `Libraries` section of the project descriptor
(`Name`, `Vendor`, `Version`). The version is the library's **release** version: a release is issued
in the control panel, and a build version with a suffix (`1.0-42`) is rejected. Different
versions of one library within a project are not allowed, so attaching an already attached
library updates the version of the existing entry. What is attached now – `project-info`
(`projects[].libraries`). The vendor, name, version and the qualified type names of a library
come from parsing its archive: `elemctl inspect <file.xlib>`.

`set-access` edits `AccessControl.Permissions` of an object in place, aware of what each kind
allows: `--default` sets the `Default` right, `--permission Read=PermitEveryone` an individual
one (custom rights of a `PrivilegeOnElement` included), `--calc-by` fills `ComputePermissionsBy` –
mandatory for `PermissionsComputedForEachObject`.
Wrong methods, rights a kind does not have, and per-object rights on a `ConstantsSet` are
rejected; the computed-permission handlers stay yours to write (notes say which). `object-info`
reports the current permissions and the kind's rights, `project-info` the `Default` of every
object – no section there means the platform falls back to `PermitAdmins`.

`rename-object` renames the object's files (including its forms and the generated `ListRow<Name>`
component of a card list) and rewrites references context-aware across the whole project: the
reference-bearing yaml keys (`Type` / `Table` / `DataSource` / `Form` / `FormType`), `=` bindings
and .xbsl code. Attributes, components or dynamic-list
fields that merely share the old name are left alone, and so are string literals (UI text);
`--new-presentation`/`--old-presentation` update the `Title` / `Presentation` of the
object and its forms. The object's `Id` is untouched, so the platform keeps the stored
data.

## Extending: your own rules, data and severities

Three entry point groups let a separate package extend the linter without forking it. This exists
for teams whose rules or language data cannot be published: keep those in a private package that
depends on `xbsl`.

```toml
# pyproject.toml of your package
dependencies = ["xbsl>=0.16"]

[project.entry-points."xbsl.rules"]
myproject = "myproject.rules"        # importing the module runs its @rule decorators

[project.entry-points."xbsl.data"]
myproject = "myproject:data_root"    # a path, or a callable returning one

[project.entry-points."xbsl.severity"]
myproject = "myproject:severity_overrides"   # {rule id: "error"|"warning"|"info"|"off"}
```

Packages that declared the groups under the pre-rename name (`xbsllint.rules`/`xbsllint.data`/
`xbsllint.severity`) keep working: the legacy groups are scanned after the new ones.

The severity dict (or a zero-argument callable returning one) raises or lowers the default level
of any rule – built-in or plugin – for every run in this installation: a project may treat, say,
`style/abbreviation-case` as a warning while the published default stays info. `"off"` removes a
rule from the default set (an explicit `--select`/`--enable` still turns it on, at its base level).

Install the package and the CLI, the MCP server and the web UI all pick everything up – no flags,
no config file. A failing entry point raises instead of warning: a linter that silently drops a
rule stays green in CI and guarantees nothing; an override naming an unknown rule id or level
raises for the same reason. `XBSL_NO_PLUGINS=1` ignores every external package (built-in
rules, bundled data and default severities only).

## LSP server

`xbsl-lsp` (the `[lsp]` extra: `pip install "xbsl[lsp]"`) runs the linter as a
long-living Language Server over stdio: live per-file diagnostics as you type, project-wide
diagnostics on save, go to definition, completion and hover over a resident project index,
and quick-fix code actions – without paying the interpreter start-up cost per call. Flags:
`--project-root` (the sources root relative to the workspace folder), `--select`/`--ignore`/
`--enable`, `--data-dir`, `--baseline`, `--templates`. Any LSP-capable editor (VS Code, Neovim,
JetBrains) can spawn it.

## Code templates

A template is a short trigger plus a construct: type the first letters of `if`, press Ctrl+Space,
pick the template and get the whole statement with edit points to tab through. The mechanism
mirrors the one in 1C:EDT (the code-templates preference page), the file format included.

Templates are offered **ahead of the other completions** – the construct you are typing out ranks
above a name that merely starts the same. They need no Element data, only the LSP server
(`xbsl.lsp.enabled`, on by default): the CLI-index mode of the extension does not offer them.

The builtin set is 51 templates (`xbsl/templates_builtin.py`): the control statements, the
declarations (methods with their annotations, structures, enumerations, exception types), queries
and the applied idioms – walking a `Catalog`, register movements, an `HttpService` handler,
per-object access permissions, object events, form handlers. Every pattern is parsed by the same
parser the linter runs (`tests/test_templates.py`), so a template cannot insert code that does
not compile.

A pattern holds edit points and choices. The variables use the `${...}` syntax of 1C:EDT
templates; unlike the metadata vocabulary the platform gives them no English spelling, so the
table describes them instead of spelling them out:

| Variable | Expands to |
|---|---|
| edit point | an edit point; its argument is the pre-selected prompt text |
| choice | a dropdown of the fixed variants listed in its arguments |
| metadata name | a dropdown of **this project's** objects of the given kind (`Catalog`, `Enum`, ...), from the index |
| qualified metadata name | the same, inserted as `<Kind>.<Name>` |

Your own templates live in `.xbsl-templates.json` at the workspace root (`--file` / the
`xbsl.templates.file` setting): the file extends the builtin set, and a template with the same
name replaces the builtin one. Only what differs from the builtin set is stored, so the next
release still reaches you.

```sh
xbsl templates list                        # the whole set: builtin plus your own (* marks yours)
xbsl templates export --output my.json     # a dump (to carry your templates to another machine)
xbsl templates import dump.json            # merge a dump into your file
```

In VS Code the same thing is a panel – **XBSL: code templates** – laid out like the EDT dialog:
the list with the call context, the description and the pattern, and buttons to add, edit, delete,
import, export and restore the defaults. Saving re-reads the set in the running server, so the
next Ctrl+Space already offers the edited template.

## Documentation search

`tools/extract_docs.py` extracts the Element reference from a distribution (the server-with-IDE
`.car`) into a `docs.sqlite` next to the language data: the stdlib pages (a type, its methods,
properties, parameters) with cleaned HTML, a full-text index (SQLite FTS5, from the standard
library) and canonical links back to the primary source (`https://1cmycloud.com/docs/help/...`,
taken from the distribution's `sitemap.xml`). Page images are stored alongside. The 1C reference is
copyrighted, so the database is not shipped in the package – you generate it from your own
distribution, like the language data.

```sh
python tools/extract_docs.py --dist "$ELEMENT_DIST"
```

The runtime API `xbsl.docs` (`search`, `page`, `tree`, `for_symbol`, `asset`) reads
`docs.sqlite`; with no database the search is simply empty. It powers the MCP tools (below) and –
later – the reference panel in the VS Code extension.

## MCP server

A thin adapter over the same core: an agent (e.g. Claude Code) can call the checks as tools and
receive structured diagnostics.

```sh
pip install -e ".[mcp]"
claude mcp add xbsl -- xbsl-mcp
```

Tools: `lint_paths(paths)`, `lint_source(filename, content)`, `list_rules()`; documentation search –
`docs_search(query)`, `docs_page(id)`, `docs_symbol(name)` (needs the `docs.sqlite` database, see
above); `type_members(name)` – the members of a stdlib type with the return-type roots of its
methods in one compact answer (cheaper than a docs page when only the member list matters);
metadata scaffolding – `meta_new_project`, `meta_new_object`, `meta_add_field`,
`meta_add_route`, `meta_add_method`, `meta_add_form`, `meta_add_subsystem`,
`meta_add_dependency`,
`meta_rename_object` (with a `dry_run` plan mode), `meta_set_access`, `meta_object_info`,
`meta_project_info`.
Every writing `meta_*` tool applies the changes and returns the lint of the written files in the
same response – creation and validation in one round trip. The core and the CLI do not require
`mcp` – it lives only in the `[mcp]` extra.

## Web interface

A local page: point it at a project folder and see the diagnostics. Standard library only (no
external dependencies), binds to `127.0.0.1` only.

```sh
xbsl-web            # then open http://127.0.0.1:8771/
```

Per-tier rule toggles, a data-version selector, severity/text filters, dark/light theme; clicking
a diagnostic opens the file in VS Code (`vscode://`).

## Element versions

The data is versioned by platform version:

```
xbsl/data/element/
    index.json            # { available: [...], default: "<version>" }
    <version>/{language.json, stdlib.json, metamodel.json}
```

Pick a version with `--element-version` / the `XBSL_ELEMENT_VERSION` env var / the index
`default`; `--version` shows what is available. Add a new version by re-running the extractors with
a new `--dist`.

The data root itself is resolved in this order: `--data-dir` > `XBSL_DATA_DIR` > a root supplied
by an installed `xbsl.data` entry point > `xbsl/data/element` inside the package.
