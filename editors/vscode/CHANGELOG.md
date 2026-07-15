# Changelog

[Русский](https://github.com/keyfire/xbsl-lint/blob/main/editors/vscode/CHANGELOG.ru.md) · **English**

> Metadata names (yaml keys such as `Реквизиты` or `Многострочная`) exist in Russian only – the platform
> documents them that way – so they are written here as they appear in the yaml; code keywords and stdlib
> types use their English forms. See the [note on names](README.md#navigation-and-completion).

## 0.16.0

- The Contents tree now includes the sections of a page (its h2/h3 headings) – handy for navigating
  the large guide and reference documents: a page expands into its sections, and clicking one opens
  the page at that section. Heading nodes are colored to set them apart from pages and categories.

## 0.15.2

- Opening a document from a rule or a link now scrolls to the relevant section (anchor) instead of
  the top of the page: `naming/module-suffix` lands on the general naming rules, `project/version` on
  the "Версия" section, and so on. Section headings in the documentation keep their anchors.

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
  project properties" – `Поставщик` and `Имя` as identifiers starting with a capital letter, a
  filled-in `Представление` and `ПредставлениеПоставщика`, and a three-number version `A.B.C`.
- New rule in the **query** group (needs `xbsllint` >= 0.11.0): `IN` with a subquery over a field of
  a composite type (`Строка|Число`) – per the platform standard such a condition is written with
  `EXISTS`, because `IN` with a subquery is implemented inefficiently on most DBMSs.
- New **naming** rule group in the settings (needs `xbsllint` >= 0.11.0): names of project elements
  per the platform standard "Names of project elements" – the number by kind (catalogs in the plural,
  enumerations in the singular), the letter `ё` and underscores, abbreviations as one word, the kind
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
  properties panel: primitives, reference types (`<Object>.Ссылка?`) and the project enumerations are
  offered as suggestions, and any other type can still be typed in.
- The multiline flag (`Многострочная`) shows in the properties panel only for the string type
  (`Строка`) and is dropped when the type is changed to another one.
- A **Standard attributes** group for catalogs/documents lists the predefined attributes – name and
  code for a catalog, number and date for a document (`Наименование`/`Код`, `Номер`/`Дата`) – even when
  they are not in the yaml; editing a property in the panel materializes the entry into the attributes
  section (`Реквизиты`), without an id, as a standard attribute.
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
  tokens, so keywords are understood in both languages (`var`/`пер`, `new`/`новый`). Properties and
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
  dropdowns, the stretch flags (`Растягивать*`) as Auto / `Истина` / `Ложь` toggles, everything
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
  methods, form components, the yaml handler and type keys (`Обработчик:` / `Тип:`). Silent when
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
