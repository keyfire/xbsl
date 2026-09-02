---
title: "Servers and plugins"
description: "The LSP server for editors, the MCP server for agents, the local web panel, and plugins that add rules, data and severities of their own."
sidebar:
  label: Servers and plugins
  order: 10
---

One engine, several ways to reach it: a long-living server for an editor, a tool surface for an agent, a page in a browser – and a way to extend all of them at once.

## LSP server

`xbsl-lsp` (the `[lsp]` extra: `pip install "xbsl[lsp]"`) runs the linter as a
long-living Language Server over stdio: live per-file diagnostics as you type, project-wide
diagnostics on save, go to definition, completion and hover over a resident project index,
and quick-fix code actions – without paying the interpreter start-up cost per call. Flags:
`--project-root` (the sources root relative to the workspace folder), `--select`/`--ignore`/
`--enable`, `--data-dir`, `--baseline`, `--templates`. Any LSP-capable editor (VS Code, Neovim,
JetBrains) can spawn it.

Everything an editor needs for code is standard LSP, so a plain client works with no extra
wiring. On top of that the server answers private `xbsl/*` requests – this is what the VS Code
panels are built on, and what another editor would use to reproduce them:

| Group | Requests |
|---|---|
| Diagnostics and hints | `xbsl/relint`, `xbsl/hoverDoc`, `xbsl/templatesReload` |
| Platform documentation | `xbsl/docsAvailable`, `xbsl/docsSearch`, `xbsl/docsPage`, `xbsl/docsTree`, `xbsl/docsAsset`, `xbsl/docsForSymbol`, `xbsl/docsByName` |
| Schemas and vocabularies | `xbsl/uiSchema`, `xbsl/metadataSchema`, `xbsl/formKeys`, `xbsl/metaKeys`, `xbsl/metaCapabilities`, `xbsl/httpMethods` |
| Metadata scaffolding | `xbsl/objectInfo`, `xbsl/metaNewObject`, `xbsl/metaAddField`, `xbsl/metaSetFieldProperty`, `xbsl/metaAddForm`, `xbsl/metaAddRoute`, `xbsl/metaAddSubsystem`, `xbsl/metaAddLocalization`, `xbsl/localizationInfo` |
| Forms | `xbsl/formTree`, `xbsl/formNodeAt`, `xbsl/formEdit`, `xbsl/searchForms`, `xbsl/bindingComplete` |
| Event handlers | `xbsl/moduleHandlers`, `xbsl/addHandler`, `xbsl/addModuleMethod`, `xbsl/removeHandler` |

A scaffolding request returns a plan – the full text of every file it would write – and the
editor applies it as one undoable edit; the server writes nothing itself (the CLI and the MCP
server, on the same code, do write). `xbsl/metaCapabilities` answers with the server version and
the kinds it can create – of objects, of section items, of forms – so a client can build its
menus from the running engine instead of hardcoding them.

## MCP server

A thin adapter over the same core: an agent (e.g. Claude Code) can call the checks as tools and
receive structured diagnostics.

```sh
pip install -e ".[mcp]"
claude mcp add xbsl -- xbsl-mcp
```

Every writing `meta_*` tool applies the changes and returns the lint of the written files in the
same response – creation and validation in one round trip. The core and the CLI do not require
`mcp` – it lives only in the `[mcp]` extra.

Every `meta_*` tool takes `root` – the caller's project root (an agent working in a git
worktree does not share the server's working directory): relative `directory`, `yaml_path`,
`module_path` and the like resolve against it, and the answer carries the absolute paths of the
written files plus the `root` they were resolved from. Without it the server's own working
directory is used, as before.

**Checking and the environment**

| Tool | What it does |
|---|---|
| `lint_paths(paths, select, ignore, enable, baseline, no_baseline)` | check files and directories on disk; the project's `.xbsllint-baseline` applies on its own, exactly as in the CLI (`summary.baselined` counts what it suppressed, `no_baseline` reports the frozen findings too); `enable` adds a rule that is off by default on top of the defaults, the way a project asks for its translation gaps |
| `lint_source(filename, content, select, ignore)` | check in-memory content, before the file is written |
| `list_rules()` | the rules available here: id, title, tier, scope, severity |
| `version_info()` | the environment answering: engine, interpreter, data version, plugins – tells apart two environments that answer differently on the same file |

**Platform reference and schemas**

| Tool | What it does |
|---|---|
| `docs_search(query, limit)` | full-text search over the 1C:Element documentation |
| `docs_page(id)` | a documentation page by the id returned by the two other tools |
| `docs_symbol(name)` | the page for a symbol by name (a type or a member) |
| `type_members(name)` | the members of a stdlib type in one compact answer – what can follow the dot; cheaper than a page when only the member list matters |
| `ui_schema(component, brief, property)` | the ui schema of an interface component: the designer's palette and its typed properties |
| `metadata_schema(kind, sections, names)` | the properties an element of a given `ElementKind` may declare |

The three `docs_*` tools need the `docs.sqlite` database (see [Documentation search](/platform-data#documentation-search)); the two schema tools read the generated language data.

**Translating the sources** (see [Translating a project](/translation))

| Tool | What it does |
|---|---|
| `translate_status(root)` | the coverage and what is left - the cheap check before deciding anything; a root without a dictionary is refused, the answer naming where one is looked for |
| `translate_gaps(root, kind, filter, limit, offset, compact)` | what the dictionary does not cover yet, by page: the count, the first places, the platform's own spelling as a hint; `compact` keeps only the key, the kind and the count per row; the answer names the `dictionary` it read |
| `translate_entries(root, kind, filter, limit, offset)` | what the dictionary already says, with the file and line of each entry |
| `translate_set(root, edits, edits_file, target, comment)` | write entries back: add, correct in place, or remove by emptying a value; `edits_file` is a batch file (the dictionary's own yaml format or the JSON list), `comment` is the head line a newly created file gets |

The four answer in PAGES over one engine core, so filling a dictionary of thousands of
entries never means reading the files.

**The project and its objects**

| Tool | What it does |
|---|---|
| `meta_project_info(root)` | map the sources under a root: projects, subsystems, objects by kind |
| `meta_object_info(root, name, yaml_path)` | describe one object: everything needed to write its forms and code |
| `meta_new_project(...)` | scaffold a project: `Проект.yaml`, `Проект.xbsl` and the first subsystem |
| `meta_new_object(directory, kind, name, ...)` | create an object: `<Name>.yaml` plus `<Name>.xbsl` for kinds with a module |
| `meta_rename_object(..., dry_run)` | rename an object and update every reference across the sources |
| `meta_delete_object(..., dry_run)` | delete an object whole: the yaml/module pair and its forms |
| `meta_add_subsystem(parent_dir, name, ...)` | create a subsystem folder with its `Подсистема.yaml` |
| `meta_add_dependency(root, vendor, name, version, ...)` | attach a library – the `Libraries` section of `Проект.yaml` |
| `meta_set_access(root, ..., default, permissions, calc_by)` | set `AccessControl.Permissions` on an object |

**Fields, routes, methods, forms, localization**

| Tool | What it does |
|---|---|
| `meta_add_field(yaml_path, field_kind, name, type, ...)` | add a section item: attribute, dimension, resource, enumeration value, parameter, field, tabular section |
| `meta_set_field_property(yaml_path, field_kind, name, props, ...)` | set properties on a section item that already exists |
| `meta_add_route(yaml_path, routes, template, methods)` | add url templates to an `HttpService` plus the handler stubs |
| `meta_add_method(module_path, name, params, returns, ...)` | insert a method into an `.xbsl` module without tearing annotation blocks apart |
| `meta_add_form(root, ..., forms, card_min_width, card_placeholder)` | generate forms for an object and register them in its `Interface` |
| `meta_add_localization(yaml_path, language)` | add a translation file to a localized-strings element |
| `meta_localization_info(yaml_path)` | the localization picture: declared languages and what is still untranslated |

**Form components – the designer, scripted**

| Tool | What it does |
|---|---|
| `meta_component_tree(yaml_path, node_id, name, max_depth, properties)` | the node tree of an interface component; a big form can be taken in parts - a subtree (by node id or by its `Name`), a depth limit and without the property records |
| `meta_add_component(yaml_path, parent_id, slot, ...)` | insert a new component into a slot of the parent node |
| `meta_insert_fragment(yaml_path, parent_id, slot, fragment, ...)` | paste a ready yaml block of one component (a copied subtree) into a slot |
| `meta_move_component(yaml_path, node_id, new_parent_id, slot, ...)` | move a node into another (or the same) slot; the comments above it travel along |
| `meta_move_components(yaml_path, node_ids, ...)` | move several nodes in one operation, keeping their document order |
| `meta_remove_component(yaml_path, node_id)` | remove a node with its attached comments |
| `meta_remove_components(yaml_path, node_ids)` | remove several nodes in one operation |
| `meta_set_component_property(yaml_path, node_id, key, value, value_yaml)` | set, replace or remove a property of a node |
| `meta_add_handler(yaml_path, node_id, key, method, signature)` | bind an event property to a handler method of the paired module |

The same operations are available through the CLI ([Commands](/CLI)) and, for an editor, through
the `xbsl/meta*` LSP requests.

## Web interface

A local page: point it at a project folder and see the diagnostics. Standard library only (no
external dependencies), binds to `127.0.0.1` only.

```sh
xbsl-web            # then open http://127.0.0.1:8771/
```

Per-tier rule toggles, a data-version selector, severity/text filters, dark/light theme; clicking
a diagnostic opens the file in VS Code (`vscode://`).

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
