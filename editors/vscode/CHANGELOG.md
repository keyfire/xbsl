# Changelog

[Русский](https://github.com/keyfire/xbsl/blob/main/editors/vscode/CHANGELOG.ru.md) · **English**

> The platform is bilingual: every metadata name has an English spelling of its own
> (`Attributes`, `TabularParts`, `VisibilityScope`), and this English changelog uses those.
> The Russian spellings - the ones that appear in the sources of a Russian-language project -
> are in the [Russian changelog](https://github.com/keyfire/xbsl/blob/main/editors/vscode/CHANGELOG.ru.md).
> See also the [note on names](README.md#navigation-and-completion).

## 0.26.1

- **Completion follows the language your project is written in.** The platform keeps both
  spellings of every stdlib member, and after the term dictionary grew the English half started
  showing up interleaved with the Russian one. The server now reads `ЯзыкРазработки` from the
  project file and offers the names of that language first; nothing is hidden, only reordered.
- The rule table in the documentation gained a leading column that numbers the rules 1-97, the
  same numbers in both locales.

## 0.26.0

- **Four new engine rules in the "Problems" panel.** `code/resource-bare-name` and
  `code/unknown-resource` - a resource is addressed by its bare file name, and the name must
  exist either in the project or in the platform's image library of 152 pictures (the rule reads
  that library from the documentation, so using a platform picture is never reported).
  `yaml/no-expression-in-literal` - a binding inside a node the platform wants spelled out
  literally (a font, a colour): compute the whole object instead. `yaml/bare-object-value` - a
  bare word where a quoted literal or an `=` binding is expected.
- **The metadata scaffolding takes an element kind in either language.** `Catalog` works exactly
  like its Russian spelling; the kinds are resolved through the term dictionary extracted from
  your own distribution.
- **The term dictionary got four times bigger** and now covers members of every stdlib type, so
  the tooling knows the English name of a metadata entity wherever the platform has one. The
  query language keywords come from the query parser's own vocabulary as well.

## 0.25.0

- **Three new engine rules in the "Problems" panel.** `yaml/ref-needs-nullable` – a reference type
  in a type position without `?` (`Goods.Reference`, `Edit<Goods.Reference>`): a reference has no
  default value, so applying the build fails; the id is clickable and opens the platform section on
  type description and initialization. `yaml/unknown-enum-value` – a component property value
  outside the enumeration of the ui schema, which also covers the alignment trap (the horizontal
  axis has `End`, the vertical one does not). `yaml/standard-field-length` – `Name` over
  400 characters or `Code` over 50, the limits the platform rejects.
- **A short interpolation inside a string literal is now resolved.** `code/undefined-name` reads
  names inside string literals as well, so `"...?$format=json"` – a substitution of the
  non-existent name `format` – is reported before the build instead of failing the compilation.
- **The group description counters follow the engine automatically.** A guard in the engine's test
  suite compares every counter, table row and documentation link against the rule registry, so the
  numbers shown in the settings can no longer drift away from what the engine actually ships.

## 0.24.0

- **Documentation links for the engine's new rules.** The `code/query-needs-server` and
  `yaml/foreign-not-public` ids in the "Problems" panel became clickable and open the relevant
  platform documentation section inside the editor.
- **The group description counters now follow the engine.** The `code` group claimed "4 rules at
  error, 12 at warning" against the actual 15 and 13, and `yaml` claimed 3 errors against 4. All
  the rules of a group are counted by their own level; both locales fixed.

## 0.23.0

- **Visual form designer.** A new **Designer (1C:Element)** container with three panels over a
  form's `.yaml`: **Structure** (the component tree – cursor sync with the editor, `Alt+Up`/`Alt+Down`
  to reorder, wrap/unwrap, duplicate, `F2` rename, copy/paste of yaml subtrees across forms,
  multi-select edit, focus on a subtree, filter), **Palette** (insert a component by double-click
  or drag, favorites, open its docs) and **Data** (drag an owner-object attribute or a component
  property to create a bound input). A new **Properties (1C:Element)** panel edits the selected
  component – and metadata objects – with typed editors: enum dropdowns, tri-state, color with
  presets from the form's own palette, union "type + value", nested groups, a literal/binding
  toggle with dotted completion (`=Components.Button.Value`, `=Object.Attribute`, enum values),
  and an events editor that can generate a handler stub in the `.xbsl`.
- **Wireframe preview**: highlights the selected component and follows the structure selection,
  shows real resource images (`Picture` with `Image:`), and scrolls to the content in a
  narrow panel.
- **Structural search across forms** (`XBSL: search forms by structure`) – by component type and
  `key=value` predicates.
- **Block presets** – save a component subtree and drop it into any form.
- **Read-only designer** for library forms (`.xlib`) and other read-only sources.
- **New 1C:Element project wizard** (`XBSL: new 1C:Element project`).
- **Metadata tree**: remembers its expanded state across refreshes and reloads, category
  tooltips with a link into the docs, all categories shown (including empty ones), and semantic
  coloring for enumerations and contracts.
- The designer's palette and typed editors need engine `xbsl` 0.23.0 and the language dataset;
  the structure tree and text edits work without them.

## 0.22.1

- Your own code templates now actually reach Ctrl+Space: the extension passes `--templates`
  to the LSP server, and the server itself (engine 0.22.1) defaults to
  `.xbsl-templates.json` at the workspace root - the very file the panel writes. Before the
  fix the saved file was never read back, so only the builtin set was offered.
- The templates panel no longer breaks Cyrillic on Windows: the engine is spawned with
  `PYTHONUTF8=1`, so the list renders correctly and saving no longer fails with a
  UnicodeError on non-UTF-8 stdio pipes.

## 0.22.0

- Code templates - the mechanism of 1C:EDT, with its export file. Type an abbreviation,
  press Ctrl+Space and get the whole construct with edit points; templates are offered
  ahead of the other completions. `${MetadataObjectName(Catalog)}` expands into the
  catalogs of your own project, from the index. 51 builtin templates, each one parsed by the
  engine's parser, so none of them inserts code that does not compile.
- The "XBSL: code templates" panel, laid out like the EDT dialog: the list with the call
  context, the description and the pattern, and buttons to add, edit, delete, import, export
  and restore the defaults. Saving re-reads the set in the running server - no restart.
- Your own templates live in `.xbsl-templates.json` (the `xbsl.templates.file` setting) and
  extend the builtin set; the file format is the one 1C:EDT exports.
- Templates need the LSP mode (`xbsl.lsp.enabled`, on by default); the CLI-index mode does
  not offer them.
- Engine rule `security/hardcoded-secret` (error, on): a key or a password written as a
  literal. Found live keys in real sources; the settings group `xbsl.groups.security`
  switches the group off.

## 0.21.1

- The properties view follows the tree selection (mouse, arrow keys, reveal from the
  active editor) when it is already open; opening it is still a click on a node or the
  "Properties" context-menu item. Selection alone never opens files or moves focus.

## 0.21.0

- Object properties from the metadata tree live in a sidebar view (below the tree and the
  documentation, like the property palette of the configurator) instead of an editor tab:
  clicking a node no longer covers the code. The editing mechanics are unchanged, undo works.
- Status bar: the engine version is labeled "engine" instead of "lint" (since 0.16 it is
  the whole toolkit; the tooltip already said "engine xbsl").
- Engine 0.19.0: the full XBSL parser against the platform grammar with the
  `code/parse-error` rule (syntax errors before a deploy, docs link from the Problems
  panel), the `code/undefined-name` rule (name typos: zero false findings on the real corpus, on by default as error), a ~2.3x
  faster run and the parallel `--jobs` mode.

## 0.20.0

- Documentation links on every rule backed by a platform requirement (54 of 78): the
  diagnostic code in the Problems panel opens the exact documentation section right inside
  VS Code (the Documentation panel + scroll to the anchor). Previously only some rules had links.
- Works with the xbsl 0.18.0 engine: scaffolding creates registers and `Document` valid
  (mandatory starter fields), adds `SoapService`, `DataProcessor` operations, `LocalizedStrings`,
  `Indexes`, report query parameters and a command with a component; library attachment –
  `add-dependency`; the full rule reference – docs/RULES.md in the engine repository.

## 0.19.1

- README: a "How it works" scheme – the extension features (diagnostics, metadata tree, form
  preview, docs panel) over the long-living `xbsl-lsp` server with the CLI fallback, the
  project sources and the baseline (an SVG source + a 2x PNG render, en/ru). No code changes.
## 0.19.0

- The engine (and the whole project) is renamed **xbsl-lint → xbsl**: the default engine
  command is now `xbsl` (`pip install xbsl`); the LSP server is `xbsl-lsp`, spawned as
  `<python> -m xbsl.lsp` when the interpreter is set. Diagnostics are labeled `xbsl`
  (findings from a pre-rename engine are still recognized); the legacy `xbsllint*` commands
  keep working as aliases, and the baseline file keeps its `.xbsllint-baseline` name.
- The metadata tree creates through the engine (0.16+): "Add <class>", "+" (attribute /
  dimension / resource / value / parameter / field / tabular section, including attributes
  of a tabular section), "Add subsystem" and "Add object form" call the engine's scaffolding
  (LSP `xbsl/meta*` requests, or the CLI subcommands in the CLI mode) and apply the returned
  changes through a single undoable edit. Templates no longer live in the extension.
- "Add object form" now offers the object form or the object + list pair, and the engine
  generates them populated from the object's attributes (standard `Name` / `Number` /
  `Date` included, hierarchy supported) and registers them in the owner's `Interface` itself.
- The same scaffolding is exposed to AI agents through the engine's `meta_*` MCP tools –
  creation and lint of the result in one call.
## 0.18.2

- README: the baseline-exclusion example now quotes the English diagnostic text (run the
  linter with `--lang en` to keep the baseline identities in English). No code changes.

## 0.18.1

- A new icon: a transparent background and a yellow center tile with the `{ }` braces
  (the corner tiles are unchanged).

## 0.18.0

- "Exclude this finding (to the baseline)" in every finding's lightbulb (`Ctrl+.`): type the
  reason, and the finding's identity (file + rule + message) is recorded in the baseline file
  (`.xbsllint-baseline` in the workspace folder, or the new `xbsl.baseline` setting) as
  `{"count": N, "reason": "..."}`. Only that one finding is excluded – the rule keeps
  checking the rest of the project; the finding disappears from the editor and from a CI
  gate over the same file. Works in both modes; the LSP suppression needs the engine 0.15.0+.
- The baseline is now applied to every run the extension makes: the workspace runs, the
  per-buffer `--stdin` runs, and the LSP server (`--baseline`).
- Buffer runs now pass the file's workspace-relative path instead of the bare name, so
  `structure/xbsl-pair` sees the module's real neighbours and baseline identities match.
- "XBSL: restart the linter" in the LSP mode rebuilds the server process with fresh
  arguments (rule sets, baseline path) instead of reusing the old command line.

## 0.17.0

- "Find All References" (Shift+F12, and "Go to References"/"Find All References" in the context menu)
  for methods, objects and interface components – built over the project index, it lists every usage:
  calls inside the module, `Module.Method` / `Components.Module.Method` calls, `Handler:` keys in
  yaml, object chain roots, and `Components.Name`. Needs the linter engine 0.13.0 or newer (the index now
  carries usage sites); with an older engine references stay silent.

## 0.16.1

- Code blocks in the documentation now have a "Copy" button in the top-right corner – it copies the
  snippet to the clipboard.

## 0.16.0

- The Contents tree now includes the sections of a page (its h2/h3 headings) – handy for navigating
  the large guide and reference documents: a page expands into its sections, and clicking one opens
  the page at that section. Heading nodes are colored to set them apart from pages and categories.

## 0.15.2

- Opening a document from a rule or a link now scrolls to the relevant section (anchor) instead of
  the top of the page: `naming/module-suffix` lands on the general naming rules, `project/version` on
  the `Version` section, and so on. Section headings in the documentation keep their anchors.

## 0.15.1

- The standard's document link from a diagnostic now opens the section **inside VS Code** (the
  Documentation view and the tree) instead of the external site.

## 0.15.0

- A link to the standard's document straight from a diagnostic. For the rules that implement
  platform standards (`naming/*`, `project/*`, `query/in-subquery-composite`), the rule code in the
  Problems panel is now a clickable link to the standard's page, and the lightbulb on a finding
  offers **XBSL: documentation for the rule** – it opens the document in the Documentation view and
  reveals it in the Contents tree.

## 0.14.1

- The README now documents the Documentation view (0.14.0 only mentioned it in the changelog): the
  "Contents" tree, search, the page view with images and the primary-source link, documentation for
  the symbol on right-click, and the `xbsl.docs.*` commands.

## 0.14.0

- New **Documentation** view in the 1C:Element container: a "Contents" tree of the Element
  reference, documentation search, and a page view (a type, its methods, properties, parameters)
  with images and a link to the primary source. Right-click a variable or type in `.xbsl` – "XBSL:
  documentation for the symbol" – to open the matching page. The data comes from the linter's LSP
  server (needs `xbsllint` >= 0.12.0 with the documentation database built by `extract_docs.py`); in
  the regular (CLI) mode the panel reports that the documentation is available in LSP mode.

## 0.13.0

- New **project** rule group in the settings: the project properties per the standard "Filling in the
  project properties" – `Vendor` and `Name` as identifiers starting with a capital letter, a
  filled-in `Presentation` and `VendorPresentation`, and a three-number version `A.B.C`.
- New rule in the **query** group (needs `xbsllint` >= 0.11.0): `IN` with a subquery over a field of
  a composite type (`String|Number`) – per the platform standard such a condition is written with
  `EXISTS`, because `IN` with a subquery is implemented inefficiently on most DBMSs.
- New **naming** rule group in the settings (needs `xbsllint` >= 0.11.0): names of project elements
  per the platform standard "Names of project elements" – the number by kind (catalogs in the plural,
  enumerations in the singular), the letter yo and underscores, abbreviations as one word, the kind
  inside its own name, an environment suffix on a common module, an empty presentation. All twelve
  rules are warnings; the whole group can be lowered or switched off from a dropdown, like the others.

## 0.12.0

- New **1C:Element** container in the Activity Bar (its own icon): the project elements grouped by
  kind – catalogs, common modules, HTTP services and so on, each group with its own icon (codicon).
  An object form / list form is nested under its owner object; forms with no owner go to a separate
  **Common forms** section. The yaml + xbsl pair of an object is one row: the context menu opens the
  description (yaml), the module (xbsl), the object module or the form preview.
- The tree root is the **project**; its context menu opens the application module. Objects expand
  into subtrees – **Attributes / Dimensions / Resources / Tabular sections / Forms**; a new field can
  be added to Attributes / Dimensions / Resources (the **+** action asks a name and inserts a minimal
  stub with a fresh id, then reveals it).
- Click behaviour: a common module opens its xbsl, a form opens the preview, a field is revealed in
  the yaml.
- More subtrees: enum **Values** (+ add), client-work **Parameters** (+ add), the HTTP service **URL
  templates** with their methods (read-only). The project root shows the vendor\name in grey.
- The tree shows the createable object classes even when the project has none of them yet (catalog,
  document, enumeration, information/accumulation register, common module, HTTP service, client-work
  parameters). The category root has a per-kind **Add &lt;class&gt;** action (Add catalog, Add
  document ...): asks a name and a subsystem (folder), writes a minimal valid yaml (a fresh id; a paired
  xbsl for module kinds) and opens it. The new object does not deploy until you complete it – a broken
  one only surfaces on deploy.
- **Subsystems**: a **Subsystems** branch under the project (open a subsystem, or **Add subsystem** –
  a folder with a subsystem file). The project root has **Filter by subsystem** (multi-select) and
  **Clear filter**; the active filter is shown in grey next to the project.
- More createable classes: **structure, client event, command-interface fragment** and a standalone
  **common form** (in the Common forms section) now have their own Add action too.
- Editable **properties panel** on the right: clicking an object or a field opens it (modules and
  forms via the **Properties** context item). Scalar properties are edited in place (undo works); the
  id and the element kind are read-only; collections stay in the tree.
- A **Fields** subtree with add for structures; **Add object form** for a catalog/document (creates
  the form and registers it in the object when it has none yet); **Delete object** (with confirmation;
  removes the object files, references are left as is).
- **Tabular sections** of a catalog/document are now an add group – **Add tabular section** creates
  the section with a starter attribute; a tabular section itself has **Add attribute to tabular
  section** to add a requisite to its columns.
- **Git status** is shown on the tree rows (like the Explorer): objects, forms, subsystems and the
  project carry the file's SCM decoration (color and badge) while keeping their kind icon.
- The form preview's primary button now uses the platform's native yellow (`#fd0`, dark text)
  instead of blue.
- The **type** of an attribute / dimension / resource / field is edited through a combo in the
  properties panel: primitives, reference types (`<Object>.Reference?`) and the project enumerations are
  offered as suggestions, and any other type can still be typed in.
- The `Multiline` flag shows in the properties panel only for the `String` type and is dropped
  when the type is changed to another one.
- A **Standard attributes** group for catalogs/documents lists the predefined attributes – name and
  code for a catalog, number and date for a document (`Name`/`Code`, `Number`/`Date`) – even when
  they are not in the yaml; editing a property in the panel materializes the entry into the attributes
  `Attributes` section, without an id, as a standard attribute.
- A **status bar** item shows the extension build time, the xbsllint version and the completion mode
  (CLI index / LSP) – handy for telling which build is actually running.
- In a `Query{...}` block, completion after `<Table>.` offers the table's **fields** (standard fields,
  attributes, tabular sections) instead of the object's members – in both the CLI index mode and the
  LSP server (the `xbsllint` index now carries object attributes).
- **LSP mode is on by default** (`xbsl.lsp.enabled`): it is what brings hover and type-aware completion.
  With the linter installed without the `[lsp]` extra the extension quietly keeps working in the former
  CLI mode – no error popup any more – and the status bar shows the mode actually in use.
- **Type-aware completion** (LSP mode): a query table can be addressed through its alias (`FROM Product
  AS P` → `P.` gives the fields of Product); the loop variable of a query result (`for Row in Result` →
  `Row.`) gives the columns of the selection; a variable of a known type (`var List = new Array<String>()`
  → `List.`) and stdlib types and globals (`AccessContext.`) give their members. The parsing runs over
  tokens, so keywords are understood in both spellings, English and Russian. Properties and
  methods are listed apart: a method carries its own icon and is inserted with parentheses. A name in
  scope beats a type of the same name (with `List` declared, `List.` is about its type, not about the
  `List` component). Requires `xbsllint` >= 0.10.0.
- The metadata tree labels (categories and subtrees) now follow the UI language – English or Russian
  – like the rest of the extension.
- Clicking an object, field, module or form in the tree opens its source on the left (the description
  yaml, or the `.xbsl` for code kinds) and the properties panel / form preview on the right, reusing
  the columns and panels already open instead of stacking new ones; the properties panel is brought to
  the front in its own column when you click around the tree.
- The tree stays in sync with the editor: the active object / module / form is selected in the tree
  (while the view is visible), and a freshly added object, field, subsystem or form is revealed and
  selected right after creation.
- The tree can be grouped **by object classes** (the default) or **by subsystems** (objects nested
  under their subsystem folders, subsystems nested by folder) – the tree-grouping button in the view
  title toggles it; the choice is remembered.

## 0.11.4

- README only: the deploy command details and the `xbsl.deploy.*` settings table moved to
  the XBSL Debug README in the [elemctl](https://github.com/keyfire/elemctl) project; this
  README keeps a short pointer.

## 0.11.3

- Fix: a clean file opened after a workspace run showed its diagnostics, but the lightbulb
  offered no Quick Fixes until the first edit. The fix snapshot is now rebuilt from the
  stored raw report of the last workspace run when such a file is opened.
- The Deploy section of the README now defers the tool details to the
  [elemctl](https://github.com/keyfire/elemctl) project; the two projects cross-link each
  other (README and Marketplace pages).

## 0.11.2

- README only: animated demos of the diagnostics with Quick Fix, the form preview and the
  properties panel, plus a pointer to the `demo/` toy project in the repository. No code
  changes.

## 0.11.1

- New rule group **query** in the settings (needs `xbsllint` with the `query/unknown-table`
  rule): tables of the `Query{...}` blocks (`FROM`/`JOIN`) are checked against the
  project objects.
- One release consolidating the 0.8.0–0.11.0 changes below.

## 0.11.0

- The form preview gained a **properties panel**, like the platform web editor: a click on an
  element selects it and opens a separate *Properties* tab (drag it wherever suits) – enums as
  dropdowns, the stretch flags (`Stretch*`) as `Auto` / `True` / `False` toggles, everything
  else as text; the
  curated standard set of the component plus every property present in the yaml. Edits are
  applied to the yaml document as precise text edits (undo works); an empty value / *(auto)*
  removes the property. Selecting and editing also position the yaml editor on the affected
  line without stealing focus; Ctrl+click or the *Show in yaml* button jumps into the editor
  (plain click selects). Long property names wrap – no horizontal scrolling; wide wireframe
  content scrolls within its own area.

## 0.10.1

- New command *XBSL: form preview* (`xbsl.previewForm`) with a preview button on form yamls:
  a wireframe of the 1C:Element form in a webview – nested groups, labels, fields with
  captions and bindings, buttons, checkboxes, tables with their columns, switchable tabs,
  cards, image/HTML placeholders, and the form command bar. The panel follows the active
  editor and re-renders as you type; clicking an element reveals its yaml node. Unknown and
  custom component types render as labeled boxes with their content.
- The preview toolbar: zoom (−/+, 125% by default) and a theme picker – light (the platform
  web client look, the default), dark, or the editor theme. The choice is remembered.

## 0.9.0

- New settings section **Rule groups**: a dropdown per finding type (code, yaml, style,
  typography, whitespace, encoding, structure, form) – keep the rules' own levels, report
  the whole group at one level, or turn the group off (the rules are then skipped, not just
  hidden). No more hand-typing ids into `xbsl.rules` for the common cases; `xbsl.rules`
  stays as the fine-grained override and beats the dropdowns.
- The "Configure rule..." lightbulb gained a "Configure rule groups..." shortcut into the
  new section.

## 0.8.0

- New command *XBSL: deploy the project (elemctl)* (`xbsl.deploy`), also a cloud button in the
  editor title of `.xbsl` files: runs `elemctl deploy` – build from sources, upload, apply,
  restart, and verification that the apply actually took effect – as a terminal task, after a
  confirmation dialog showing the exact command line. The target comes from the workspace
  folder's `.env` or the new settings `xbsl.deploy.elemctlPath` / `xbsl.deploy.envFile` /
  `xbsl.deploy.appId` / `xbsl.deploy.extraArgs`; a set `xbsl.projectRoot` is passed as
  `--project-dir`. Offers to install elemctl when it is missing.
- The English README now shows the English command titles (bilingual since 0.6.1).

## 0.7.1

- "Install xbsllint" / "Install xbsllint[lsp]" buttons on the corresponding errors: the install
  runs as a terminal task and the check restarts on success.

## 0.7.0

- New setting `xbsl.rules` – per-rule levels and disabling (`off | error | warning | info | hint`
  by rule id or whole group), plus a "Configure rule..." action in every finding's lightbulb.
  Works in both the CLI and the LSP mode.

## 0.6.1

- Bilingual UI (en/ru): the manifest and all runtime strings follow the VS Code display language.

## 0.6.0

- Experimental LSP mode (`xbsl.lsp.enabled`): a long-living `xbsllint-lsp` server brings hover,
  instant as-you-type diagnostics and index navigation; on a failed server start the extension
  falls back to the regular CLI mode by itself.

## 0.5.0

- New command *XBSL: code palette* – recolor XBSL syntax with one of the popular palettes
  (the 1C:Element web IDE style, One Dark, Monokai, Dracula, GitHub Dark) or reset to the
  editor theme; only `*.xbsl` scopes are touched.

## 0.4.1

- New setting `xbsl.projectRoot` – the sources root for project-wide runs and the navigation
  index, for repositories that hold examples or copies next to the project.

## 0.4.0

- Quick Fix for mechanical findings: a lightbulb on a fixable diagnostic (trailing whitespace,
  typography characters – em dash → en dash, `…` → `...`, curly quotes) applies the exact edit the
  linter reports. Needs a linter that emits fixes in its JSON (`xbsllint` ≥ 0.7.1).
- A *fix all* source action (`source.fixAll.xbsl`) fixes every fixable finding in the file at once;
  wire it into `editor.codeActionsOnSave` for fix-on-save. Fixes are applied only against the exact
  text they were computed on (a version-stamped snapshot), so a stale edit is never misplaced.

## 0.3.0

- Go to definition and completion powered by the project index (`xbsllint index`, with the
  `--index` spelling probed as a fallback): objects, tabular sections, local types, enum values,
  methods, form components, the yaml `Handler:` / `Type:` keys. Silent when
  the installed linter has no index command.
- New setting `xbsl.navigation.enabled` (default `true`).

## 0.2.0

- Workspace diagnostics: saving any `.xbsl`/`.yaml` file triggers a full linter run over the
  workspace folder (debounced, one at a time, stale runs cancelled), bringing project-scope
  rules (`code/unknown-type`, `yaml/unknown-type`, ...) into the editor. The workspace result
  replaces the diagnostics of every file; the fast `--stdin` lint owns only the dirty buffer
  being edited.
- New settings: `xbsl.workspaceLint` (on by default) and `xbsl.workspaceLintTimeout`
  (60000 ms; on expiry the run is stopped and logged to the XBSL output channel).
- The *XBSL: check the whole project* command reuses the same machinery and result store.
- Activation on `workspaceContains:**/*.xbsl`, so `.yaml`-only editing sessions get
  workspace diagnostics too.

## 0.1.0

- Initial release.
- Syntax highlighting for `.xbsl` (bilingual keywords, decorators, string interpolation, generics).
- On-the-fly diagnostics via `xbsllint --stdin --format json` (on type, debounced, and on save).
- Command *XBSL: check the whole project* for a workspace-wide check (including cross-file rules).
- Settings: linter command / Python interpreter, data dir, language, rule select/ignore, run mode,
  debounce.
