---
title: "Servers and plugins"
description: "The LSP server for editors, the MCP server for agents, the local web panel, and plugins that add rules, data and severities of their own."
sidebar:
  label: Servers and plugins
  order: 10
---

One engine, several ways to reach it: a long-living server for an editor, a tool surface for an agent, a page in a browser. There is also a way to extend all of them at once.

## LSP server

`xbsl-lsp` from the `[lsp]` extra (`pip install "xbsl[lsp]"`) runs the linter as a long-living
Language Server over stdio. Per-file diagnostics arrive as you type, project-wide ones on save.
Go to definition, completion and hover all come off a resident project index, and quick fixes
arrive as code actions. None of it pays the interpreter start-up cost per call. Flags:
`--project-root` (the sources root relative to the workspace folder), `--select`/`--ignore`/
`--enable`, `--data-dir`, `--baseline`, `--templates`. Any LSP-capable editor can spawn it:
VS Code, Neovim, JetBrains.

With `--project-root` the server also checks the project's translation dictionary. Other yaml files
outside the root are not checked.

The whole-project check reads only the root and the dictionary. Any other open file, such as a module
outside the root, keeps the findings of its own check until you close it.

Everything an editor needs for code is standard LSP, so a plain client works with no extra
wiring. On top of that the server answers private `xbsl/*` requests. The VS Code panels are built
on them, and another editor would use the same requests to reproduce those panels:

| Group | Requests |
|---|---|
| Diagnostics and hints | `xbsl/relint`, `xbsl/hoverDoc`, `xbsl/templatesReload` |
| Platform documentation | `xbsl/docsAvailable`, `xbsl/docsSearch`, `xbsl/docsPage`, `xbsl/docsTree`, `xbsl/docsAsset`, `xbsl/docsForSymbol`, `xbsl/docsByName` |
| Schemas and vocabularies | `xbsl/uiSchema`, `xbsl/metadataSchema`, `xbsl/formKeys`, `xbsl/metaKeys`, `xbsl/metaCapabilities`, `xbsl/httpMethods` |
| Metadata scaffolding | `xbsl/objectInfo`, `xbsl/metaNewObject`, `xbsl/metaAddField`, `xbsl/metaSetFieldProperty`, `xbsl/metaAddForm`, `xbsl/metaAddRoute`, `xbsl/metaAddSubsystem`, `xbsl/metaProjectInfo`, `xbsl/metaMoveObject`, `xbsl/metaDeleteObject`, `xbsl/metaRenamePackage`, `xbsl/metaMoveResource`, `xbsl/metaRenameResourceFolder`, `xbsl/metaDeleteResourceFolder`, `xbsl/metaResourceReferences`, `xbsl/metaAddLocalization`, `xbsl/localizationInfo` |
| Forms | `xbsl/formTree`, `xbsl/formNodeAt`, `xbsl/formEdit`, `xbsl/searchForms`, `xbsl/bindingComplete` |
| Event handlers | `xbsl/moduleHandlers`, `xbsl/addHandler`, `xbsl/addModuleMethod`, `xbsl/removeHandler` |

A scaffolding request returns a plan: the full text of every file it would write. The editor
applies that plan as one undoable edit, and the server writes nothing itself. The CLI and the MCP
server, running the same code, do write. `xbsl/metaCapabilities` answers with the server version
and the kinds it can create - of objects, of section items, of forms - so a client can build its
menus from the running engine instead of hardcoding them.

## MCP server

A thin adapter over the same core. An agent such as Claude Code calls the checks as tools and
receives structured diagnostics.

```sh
pip install -e ".[mcp]"
claude mcp add xbsl -- xbsl-mcp
```

Every writing `meta_*` tool applies the changes and returns the lint of the written files in the
same response: creation and validation in one round trip. The lint is short: the number of
files and findings, and up to ten findings one line each. `lint_paths` on the written files
gives the whole report. The core and the CLI do not need `mcp`
at all; it lives only in the `[mcp]` extra.

Every `meta_*` tool and `lint_paths` take `root`, the caller's project root. An agent working in
a git worktree does not share the server's working directory, which is why the parameter exists.
Relative `directory`, `yaml_path`, `module_path`, `paths` and `baseline` resolve against it, and
the answer carries absolute paths for the written files and the diagnostics plus the `root` they
were resolved from. Without it the server's own working directory is used, as before. A relative
path from a worktree then names the other checkout, and that checkout's clean answer looks like
yours.

**Checking and the environment**

| Tool | What it does |
|---|---|
| `lint_paths(paths, select, ignore, enable, baseline, no_baseline, root, as_ci, as_ci_job, compact, fix, as_ci_full)` | check files and directories on disk (relative paths – against `root`, the summary names it); the project's `.xbsllint-baseline` applies on its own, exactly as in the CLI (`summary.baselined` counts what it suppressed, `no_baseline` reports the frozen findings too; the stale entries are named in `summary.baseline_stale_entries`, not merely counted); `enable` adds a rule that is off by default on top of the defaults, the way a project asks for its translation gaps; `as_ci` takes the rule set and the baseline from the project's CI job (`.gitlab-ci.yml` or a GitHub workflow next to the project), so a preflight judges what the job judges and the summary carries `as_ci` – the file and the job, the include the command stands in, the root of the checkout, the set as data (`select`, `ignore`, `enable`, `baseline`) and as one sentence (`flags`), the other jobs that run the linter and the includes left unread; the CLI `--format json` answers with the same record; `as_ci_job` names which of them to take - a pipeline that checks a second tree (a translation) runs the linter twice, by two different sets; the summary counts the findings by rule, by file and by severity (`by_rule`, `by_file`, `by_severity`), and `compact` narrows the answer - the summary stays, with its baseline and CI-job records, `errors` holds the full records of the error-level findings, and up to 10 findings (`report.COMPACT_FINDINGS_LIMIT`) `findings` lists them one line each (`path:line rule – message`); past 10 `findings` is left out and `findings_hint` says how many there are and how to read them, because the text of every finding is what a full answer costs: several hundred characters each when the question was only whether the tree is clean. `compact=true` also omits `summary.by_file`, and narrows `summary.as_ci` to one line, `brief`: the file relative to the checkout, the job, the flags with a long list counted (`--enable ×10`), the other jobs while none was named, and the includes left unread. `as_ci_full=true` keeps the whole CI-job record, and `compact=false` gives the complete file map as well. `fix=true` applies available edits before returning the remaining findings; the default is read-only. Accepted baseline occurrences stay protected across passes, and the baseline file stays unchanged. `summary.fixed` counts applied edits and `summary.files_changed` counts changed files. |
| `lint_source(filename, content, select, ignore)` | check in-memory content, before the file is written |
| `baseline_prune(paths, select, ignore, enable, baseline, dry_run, root)` | remove the baseline entries this run no longer needs (the CLI `--prune-baseline`): the answer names every one of them – path, rule, message, count and the `reason` a human wrote – and the file keeps its order and format; entries of rules this server does not carry, and of files outside `paths`, are left alone; `dry_run` shows what would go |
| `list_rules(select, ignore, filter)` | the rules available here: id, title, tier, scope, severity – and `params` for a rule that judges by a number (the value in force, the default, the overriding environment variable); `select` answers about one rule instead of the whole registry, and `filter` narrows further: a word that IS a group (the part of an id before `/`) lists that group alone, while any other word is looked for as an id substring or as a word of the title or the description – every i18n text registered under the rule's id (the title and the message templates its diagnostics are built from), in either language, plus its English docstring; `docs/RULES.md` is not read, since it ships with neither the sdist nor the wheel. Matching is case-insensitive. A `filter` that matches nothing answers `{error, near_groups}` – the groups closest to it by spelling – instead of an empty list |
| `version_info()` | what the environment is made of: engine, interpreter, data version, plugins. It tells apart two environments that answer differently on the same file |

**Platform reference and schemas**

| Tool | What it does |
|---|---|
| `docs_search(query, limit)` | full-text search over the 1C:Element documentation |
| `docs_page(id, brief, section)` | a documentation page by the id returned by the two other tools; `brief` – the head alone: a summary and the section names instead of the text, `section` – the head plus one section of the article (Properties, Methods, Constructors, ...; an unknown name answers with the names to choose from) |
| `docs_symbol(name, brief, section)` | the documentation of a symbol by name, in either spelling: a type answers with its page and the same `brief` and `section` modes, a member (`Подстрока`, `Строка.Найти`) with the block of that member alone, every overload joined - a member has no page of its own. A member several types declare answers with their names and how to ask again |
| `type_members(name)` | the members of a stdlib type in one compact answer – what can follow the dot; cheaper than a page when only the member list matters |
| `ui_schema(component, brief, property)` | the ui schema of an interface component: the designer's palette and its typed properties |
| `metadata_schema(kind, sections, names)` | the properties an element of a given `ElementKind` may declare |

The three `docs_*` tools need the `docs.sqlite` database (see [Documentation search](/platform-data#documentation-search)), and the two schema tools read the generated language data. A type page runs to thousands of characters: the constructors, every property, the inherited lists. You want the whole article when you mean to read it. `brief` answers "which page is it and what is it about", and `section` answers one question about it.

**Translating the sources** (see [Translating a project](/translation))

| Tool | What it does |
|---|---|
| `translate_status(root, against)` | the coverage and what is left, the cheap check before deciding anything. A root without a dictionary is refused, and the answer names where a dictionary was looked for; `against` names a git ref and adds `collisions` - the keys the dictionary files of the working tree and of the ref translate differently or the same way, the report of `xbsl translate --check-duplicates` |
| `translate_gaps(root, kind, filter, limit, offset, compact)` | what the dictionary does not cover yet, by page: the count, the first places, the platform's own spelling as a hint; `compact` keeps only the key, the kind and the count per row; the answer names the `dictionary` it read |
| `translate_entries(root, kind, filter, limit, offset, compact)` | what the dictionary already says, with the file and line of each entry; ten rows a page by default, and `compact` keeps only the key, the kind and the value of each row |
| `translate_unused(root, kind, filter, since, limit, offset, prune, compact, budget_seconds)` | dictionary entries no longer used by the project; `filter` accepts a substring or a list, `since` scopes candidates to one change. Preview lists full rows by default; `compact=true` keeps only key, kind, file and line. `prune=true` removes every key the filters select, whatever the page, with all its declarations, and normally omits the list: `removed` counts occurrences, `pruned.keys` counts pairs, and `pruned.by_kind` / `pruned.by_file` group them. Explicit `compact=false` includes full rows after removal. `counts` covers the whole filtered candidate set, and so does `prune`: pagination shapes only the list. `budget_seconds` (300 by default) bounds scanning; a `partial` answer lists candidates and never removes entries. |
| `translate_set(root, edits, edits_file, target, comment)` | write entries back: add, correct in place (in every place the key is declared), or remove by emptying a value; `edits_file` is a batch file (the dictionary's own yaml format or the JSON list), `comment` is the head line a newly created file gets. Every plane is held to the spelling its pass reads: an entry that could not fire comes back in `refused`, and one with a single obvious reading - a phrase whose quote is escaped the literal way - is written by that reading and listed in `normalized` |

All four answer in pages over one engine core, so filling a dictionary of thousands of entries
never means reading the files.

**The project and its objects**

| Tool | What it does |
|---|---|
| `meta_project_info(root, kind, subsystem, brief, package, project, reference)` | map the sources under a root: projects, subsystems, packages, objects by kind; `kind`, `subsystem` and `package` narrow the list of objects, `project` walks only the named project, and the reference sections (the object kinds, the section kinds, the access methods) come with `reference` or `brief` |
| `meta_object_info(root, name, yaml_path)` | describe one object: everything needed to write its forms and code |
| `meta_new_project(...)` | scaffold a project: `Проект.yaml`, `Проект.xbsl` and the first subsystem |
| `meta_new_object(directory, kind, name, ...)` | create an object: `<Name>.yaml` plus `<Name>.xbsl` for kinds with a module |
| `meta_rename_object(..., dry_run, full)` | rename an object and update every reference across the sources. The answer is short: the renamed files, a note with the counts, and `outside_projects` – the edited files no project owns, such as a translation dictionary beside the project. `full=true` lists every edited file |
| `meta_delete_object(..., dry_run)` | delete an object whole: the yaml/module pair, its forms and the WSDL descriptions of a SOAP service client |
| `meta_move_object(root, yaml_path, target_dir, dry_run)` | move an object with its forms, modules, list row and list table into a package, another package, the subsystem root or another subsystem; the imports a reference needs at the new place, the qualified names of the old place and `Using` are repaired by the import rules run before and after the move, and a taken name or a non-public element another subsystem would reach is refused |
| `meta_rename_package(root, package_dir, new_name, dry_run)` | rename a package folder with all its files and rewrite `import Subsystem::Package`, the `Import` items and the qualified names across the project |
| `meta_move_resource(root, resource_path, target_dir, dry_run)` | move a resource file or a folder into another folder of the same `Resources` folder and rewrite the `Resource{...}` keys and image property values that lead to it; lookups by a string are listed in `notes`, a move into another `Resources` folder is refused |
| `meta_rename_resource_folder(root, folder_dir, new_name, dry_run)` | rename a folder inside a `Resources` folder with all its files and rewrite the keys that name them |
| `meta_delete_resource_folder(root, folder_dir, dry_run)` | delete a folder inside a `Resources` folder with its files and list the keys and string lookups that name them; `dry_run` defaults to true |
| `meta_resource_references(root, resource_path, limit)` | find the places that name a resource file or a folder: `Resource{...}` keys and image property values, keys two folders hold, strings with the path or with the file's key without its extension; each place has a file, a range, its line and a kind, and `limit` caps the list |
| `meta_add_subsystem(parent_dir, name, ...)` | create a subsystem folder with its `Подсистема.yaml` |
| `meta_add_dependency(root, vendor, name, version, ...)` | attach a library – the `Libraries` section of `Проект.yaml` |
| `meta_set_access(root, ..., default, permissions, calc_by)` | set `AccessControl.Permissions` on an object |

**Fields, routes, methods, forms, localization**

| Tool | What it does |
|---|---|
| `meta_add_field(yaml_path, field_kind, name, type, props, names, ...)` | add a section item: attribute, dimension, resource, enumeration value, parameter, field, tabular section. `names` adds several items of one kind in one call with the same type and properties, such as the values of an enumeration; the batch is planned whole, and a taken name refuses all of it. A built-in attribute (`Number`, `Date`, `Code`, `Name`, `Owner`) is judged by its own class, so `Length`, `Uniqueness` and the `Autonumbering` block are accepted and `type` may be omitted where the class fixes it; `props` takes a nested block as a dict or a dotted key (`Autonumbering.Prefix`) and a list as a sequence; a block of a class the metamodel does not describe (`Presentation`) is refused as a known limitation; a section the file lacks is created at the end of the file, and for a register `notes` say so and name the sibling kind that would have placed the item beside the existing fields (a resource where an attribute was asked, and the other way round) |
| `meta_set_field_property(yaml_path, field_kind, name, props, ...)` | set properties on a section item that already exists; the same value shapes as `meta_add_field`, a nested block replaces the old one whole |
| `meta_add_route(yaml_path, routes, template, methods)` | add url templates to an `HttpService` plus the handler stubs |
| `meta_add_method(module_path, name, params, returns, ...)` | insert a method into an `.xbsl` module without tearing annotation blocks apart |
| `meta_add_form(root, ..., forms, card_min_width, card_placeholder)` | generate forms for an object and register them in its `Interface` |
| `meta_add_localization(yaml_path, language)` | add a translation file to a localized-strings element |
| `meta_set_localization(yaml_path, name, values, entries, section, dry_run, full_text)` | write one or many localized strings into every language at once - the default-language text into the element, each other language into its own translation file; a language a key says nothing about still gets the row, with the default text and a note. `entries` writes many keys (`{key: values}`) in one pass, one read and one write per file however many keys touch it, and either fails as a whole before anything is planned or not at all. `dry_run` answers with `summary` (key, language, file, the text before and after) instead of the whole files; `full_text` adds the files back next to it |
| `meta_localization_info(yaml_path)` | the localization picture: declared languages and what is still untranslated |

**Form components – the designer, scripted**

| Tool | What it does |
|---|---|
| `meta_component_tree(yaml_path, node_id, name, max_depth, properties, brief)` | the node tree of an interface component; a big form can be taken in parts - a subtree (by node id or by its `Name`), a depth limit, without the property records, or as the skeleton alone (`brief` - ids, kinds, types, names and slots, a few kilobytes for a tree of hundreds); a big whole tree carries a hint naming these knobs |
| `meta_add_component(yaml_path, parent_id, slot, ...)` | insert a new component into a slot of the parent node |
| `meta_insert_fragment(yaml_path, parent_id, slot, fragment, ...)` | paste a ready yaml block of one component (a copied subtree) into a slot. A `#` note of the fragment goes where the development environment reads it: a comment above the component moves inside the node as `##` lines, and a note with no such place stays and is named in `notes`, see [Comments in yaml](yaml-comments) |
| `meta_move_component(yaml_path, node_id, new_parent_id, slot, ...)` | move a node into another (or the same) slot; the comments above it travel along |
| `meta_move_components(yaml_path, node_ids, ...)` | move several nodes in one operation, keeping their document order |
| `meta_remove_component(yaml_path, node_id)` | remove a node with its attached comments |
| `meta_remove_components(yaml_path, node_ids)` | remove several nodes in one operation |
| `meta_set_component_property(yaml_path, node_id, key, value, value_yaml)` | set, replace or remove a property of a node |
| `meta_add_handler(yaml_path, node_id, key, method, signature)` | bind an event property to a handler method of the paired module |

The same operations are available through the CLI ([Commands](/CLI)) and, for an editor, through
the `xbsl/meta*` LSP requests.

## Web interface

A local page: point it at a project folder and see the diagnostics. It is written on the
standard library alone, with no external dependencies, and it binds to `127.0.0.1` only.

```sh
xbsl-web            # then open http://127.0.0.1:8771/
```

The page has per-tier rule toggles, a data-version selector, severity and text filters, and a
dark and a light theme. Clicking a diagnostic opens the file in VS Code (`vscode://`).

## Extending: your own rules, data and severities

Three entry point groups let a separate package extend the linter without forking it. This is for
teams whose rules or language data cannot be published: keep those in a private package that
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
`xbsllint.severity`) keep working: the old groups are scanned after the new ones.

The severity dict, or a zero-argument callable returning one, raises and lowers the default level
of any rule, built-in or plugin, for every run in this installation. A project may treat, say,
`style/abbreviation-case` as a warning while the published default stays info. `"off"` removes a
rule from the default set; an explicit `--select` or `--enable` still turns it on, at its base
level.

Install the package and the CLI, the MCP server and the web UI all pick everything up. No flags,
no config file. A failing entry point raises rather than printing a warning, because a linter that
silently drops a rule stays green in CI and guarantees nothing. An override naming an unknown rule
id or level raises for the same reason. `XBSL_NO_PLUGINS=1` ignores every external package, so
only built-in rules, bundled data and default severities remain.
