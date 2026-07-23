---
title: "Changelog"
description: "What changed in the xbsl toolkit from release to release, grouped by day."
sidebar:
  label: "Changelog"
  order: 8
---

<!-- Generated from CHANGELOG.md; do not edit by hand.
     Edit CHANGELOG.md and run: npm run sync:docs -->

Notable changes to the **xbsl toolkit** – the Python engine behind the linter, the LSP and MCP
servers, the documentation index and the metadata scaffolding. Entries are grouped by day; the
versions released that day are named in the heading. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and
[Semantic Versioning](https://semver.org/spec/v2.0.0.html). The VS Code extension keeps its own
history in
[editors/vscode/CHANGELOG.md](https://github.com/keyfire/xbsl/blob/main/editors/vscode/CHANGELOG.md).
Entries here use the English spelling of platform metadata names (`Name`, `Code`, `Attributes`);
the Russian spellings are in the [Russian changelog](https://github.com/keyfire/xbsl/blob/main/CHANGELOG.ru.md).

## 2026-07-23 – 0.31.0, 0.31.1

### Changed
- The generated stdlib type catalog records fuller member types and curates extra type surfaces
  from the platform's topic pages, so the linter's member checks and completion match what the
  platform actually exposes (0.31.0).

### Fixed
- `code/resource-bare-name` no longer treats an `inbase/…` reference as a folder path: a resource
  uploaded into the application base is a lookup key, not a disk path, so the rule leaves it alone
  (the compiler verifies its existence at apply) (0.31.0).
- A resource key is a path relative to the subsystem's `Ресурсы` folder: `code/resource-bare-name`
  now flags only a key that spells the `Ресурсы` folder out, and subdirectory references
  (`Подкаталог/Файл.svg`) are legal instead of being reported (0.31.1).

## 2026-07-22 – 0.28.0, 0.29.0, 0.30.0, 0.30.1

### Added
- The documentation site ([docs.keyfire.ru/xbsl](https://docs.keyfire.ru/xbsl/)), a full command
  reference and CLI help – complete in English and Russian (0.29.0).
- The platform metamodel resolves the schema of a collection item – an enumeration value, an
  attribute, a dimension, a resource, a structure field, a tabular-section attribute – so the
  linter sees its full schema with defaults and documentation, not only what the yaml already
  sets (0.29.0).
- A new engine operation to remove a form handler (`xbsl/removeHandler`): it unbinds an event and
  deletes its method – with the annotations and the separating blank line – as a single edit
  (0.28.0).

### Changed
- Faster on large projects: caches for the data-binding layer, YAML parsed through libyaml
  (`compose`), and worker pools sized to the workload (0.30.0).
- A type's hover carries its description from the platform documentation above the page link, not
  the link alone (0.28.0).
- Completion follows a member chain past a property link, with a guard that stops at the edge of
  the stdlib closure instead of looping (0.30.1).

### Fixed
- `yaml/bare-object-value` accepts a `$`-reference to a localized string as a valid value where a
  literal is expected, instead of flagging it as a bare word (0.30.1).
- Regenerated language data is picked up without a restart – the freshness stamp drops the
  in-process caches when the data under the data root changes (0.30.1).
- The servers gated behind optional extras (MCP, LSP) skip cleanly on a minimal install instead of
  failing to import (0.30.1).

## 2026-07-21 – 0.25.0, 0.26.0, 0.26.1, 0.27.0

### Added
- Four linter rules: `yaml/bare-object-value` (a bare word where a quoted literal or an `=`
  binding is expected), `code/resource-bare-name` and `code/unknown-resource` (a resource by a
  bare file name that must exist in the project or the platform's image library), and
  `yaml/no-expression-in-literal` (an expression where the platform accepts only a literal)
  (0.26.0).
- Three engine rules: `yaml/ref-needs-nullable` (a reference type in a type position without `?`),
  `yaml/unknown-enum-value` (a component property value outside the ui-schema enumeration), and
  `yaml/standard-field-length` (a `Name` over 400 characters or a `Code` over 50) (0.25.0).
- A unified metamodel API – property types, enumerations and defaults through one interface; the
  linter and scaffolding resolve object schemas through it, including the properties an object has
  but the yaml leaves unset (0.27.0).

### Changed
- Scaffolding accepts the element kind spelled in any platform language (0.26.0).
- Language data comes from the compiler, not from constants: the terms dictionary covers every
  stdlib type's members, and the query-language keywords come from the parser's own dictionary
  (0.26.0).
- `code/undefined-name` also reads names inside string interpolation, so a substitution of a
  non-existent name is reported before the build (0.25.0).
- Completion follows the project's development language (0.26.1).

---

> Releases before 0.25.0 predate this changelog. The VS Code extension's
> [CHANGELOG](https://github.com/keyfire/xbsl/blob/main/editors/vscode/CHANGELOG.md) carries the
> product history back to 0.1.0.
