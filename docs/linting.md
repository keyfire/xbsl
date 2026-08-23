---
title: "Checking sources"
description: "Running the linter: flags, what the deeper rules rely on, the baseline for a legacy codebase, and CI."
sidebar:
  label: Checking
  order: 4
---

The default mode of the tool – checking sources. The full rule list is a separate page ([Rules](/RULES)); here is how the run is driven.

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
completion), the method declarations (annotations, the parameter list as written, the return type
and the description comment above the declaration) and the named form components, with
POSIX paths relative to the root and 1-based lines – for go-to-definition and completion in
editors.

`--format codeclimate` emits a GitLab Code Quality report (Code Climate issues) with paths relative
to the current directory – run it from the repository root and save the output as the
`codequality` artifact.

## Rules in depth

**The full list of all 160 rules of the base set** (severity, default state, scope, links to
platform documentation sections) is in [RULES.md](/RULES);
at runtime – `xbsl --list-rules`, which also counts in the rules and severity overrides of the
installed plugins. The tier overview is in the README; below is what the deeper
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

## Use in CI

`xbsl` exits non-zero only when a run produces an **error-severity** finding, so it works as a
pipeline gate as-is – warnings and `info` do not fail the build. The one prerequisite is the
language data (see [Language data](/start#language-data)): generate it in the job (the extractors ship
with the repository, so check the repo out), or depend on a package that ships the data via the
`xbsl.data` entry point (see [Extending](/servers#extending-your-own-rules-data-and-severities)) and
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
    - run: xbsl extract --dist "$ELEMENT_DIST"
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
