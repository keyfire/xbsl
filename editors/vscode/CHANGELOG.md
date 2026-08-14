# Changelog

[Русский](https://github.com/keyfire/xbsl/blob/main/editors/vscode/CHANGELOG.ru.md) · **English**

> The platform is bilingual: a metadata name has an English spelling of its own
> (`Attributes`, `TabularParts`, `VisibilityScope`) - the `en` argument of its metamodel
> annotation, or the model member's name capitalized - and this English changelog uses those.
> The Russian spellings - the ones that appear in the sources of a Russian-language project -
> are in the [Russian changelog](https://github.com/keyfire/xbsl/blob/main/editors/vscode/CHANGELOG.ru.md).
> See also the [note on names](README.md#navigation-and-completion).

## Unreleased

### Fixed
- **A project component named like a wireframe primitive is drawn from its own yaml.** One name
  was hardwired into the frame, so a project component carrying it was drawn by the extension
  instead of by its description.

## 0.61.1

### Fixed
- **Every documentation link of the rules was verified.** Three localization rules pointed at a
  page that does not exist, and `style/shadow-project-name` led to the naming conventions instead
  of the section on name overriding. The other 99 entries check out: pages and anchors exist.

## 0.61.0

### Changed
- **An edit of a nested component shows in the parent's wireframe at once** - the panel used to
  keep the previous version until a manual refresh.
- **The layout of the use site reaches a nested component** - stretching, width and alignment
  apply to it exactly as they do to any other component.
- **A long expression in the wireframe is cut in the middle,** the way the platform's designer
  cuts it: the head names the data, the tail names the field, and both matter. The whole text
  stays in the tooltip.
- **Inaccessible fields of the wireframe are drawn the way the platform draws them** - a gray
  fill with no border. An availability switched off, or computed, travels down the content until
  a node overrides it; the value shows in the tooltip.
- **The form wireframe shows the localized TEXT, not the key.** A `$Dictionary.Key` value is drawn
  as the words the user will see, in the editor's language, with the key kept in the tooltip. A key
  with no text behind it falls back to its last segment, as before.

## 0.60.2

### Changed
- **The "reference" link knows two new engine rules** (0.65.0) - the unused import and the local
  variable shadowing a property of its own element.

### Fixed
- **A changed setting reaches the LSP server.** The sources root, the rule set and the rest are
  given to the server at startup, so editing them did nothing until the window was reloaded -
  hence the impression that `xbsl.projectRoot` was ignored. Such an edit now restarts the server.

## 0.60.1

### Changed
- **The documentation links of the eight new engine rules.** A rule backed by a platform documentation section opens it right in the editor from the Problems panel; the rules added in engine 0.64.0 (permissions recomputation, the dynamic-list checks, the localization reference, the layout and mobile hints) now carry those links too.

## 0.60.0

### Added
- **The form wireframe looks like the platform's own web designer.** Fields, buttons, tabs,
  tables and cards are drawn from measurements taken on the real designer, and form commands sit
  where the platform puts them.
- **A device toolbar above the wireframe** - presets from iPhone SE to Full HD, a custom size,
  rotation and zoom; the choice is remembered.
- **Project components are drawn with their own content** instead of a dashed placeholder; a
  click on the block navigates to the use site.
- **A sectioned application draws its navigation panel** - the logo, items with their icons,
  the vertical or horizontal orientation by the property and the content area, instead of
  refusing with "not a form".
- **Localization references are readable**: a dollar-prefixed "dictionary.key" value shows the
  last segment of the key, with the full key in the tooltip.
- **The wireframe's own texts are localized** - the placeholders, the table strip and the
  search bar follow the editor language (Russian and English).

### Changed
- **The dark theme of the wireframe is the palette of the platform site's dark scheme**, not
  the editor's palette.
- **The "docs" link knows the `yaml/date-input-needs-plain-date` rule** (engine 0.63.0) - it
  opens the section on the edit component.

## 0.59.3

### Changed
- **The "How it works" section moved to the top of the README** - the extension page opens
  with the mechanism, not with the feature list.
- **The "docs" link knows the `code/component-in-server-context` rule** (engine 0.62.0) - the
  rules panel and the Problems view open the "Module execution" section, as the neighbouring
  environment rules do.

## 0.59.2

### Changed
- **The level in the rules panel is an icon, not a dot** - the one VS Code draws for a diagnostic:
  a circle with a cross for an error, a triangle for a warning, a crossed circle for a rule
  switched off. The icon is inline SVG, so it does not depend on the codicon font being shipped,
  and the state reads by shape and not by colour alone.

### Fixed
- **Collapsed groups sprang open as soon as a level was picked.** The panel rebuilds its markup
  after every write, and the folded state lived in that markup only. It now lives in the webview
  state and survives both a redraw and reopening the panel.

## 0.59.1

### Added
- **The rules panel got reference links and collapsible groups.** A rule backed by a standard
  carries a "reference" link, the level shows as a coloured dot, and groups start collapsed -
  there are more than two hundred rules.

## 0.59.0

### Added
- **The logo says what the extension does:** a deploy arrow and a breakpoint next to the "@" and
  the check mark. A vector source now sits beside it - the logo used to be a picture only.
- **The rules panel and the migration messages are translated.** The strings went through
  `vscode.l10n.t` but had no keys in the Russian bundle, so VS Code silently fell back to the
  English source and a Russian editor opened the panel in English. A guard now refuses a
  `l10n.t` string without a translation.
- **The rules panel: the "XBSL: rules" command.** Every rule of the engine by group with its
  current level; a dropdown changes it, and there is a search and a "changed only" filter. The
  scope - user or workspace settings - is chosen explicitly.
- **Rules are configured by one table, `xbsl.rules`.** The key is a rule, a group, a tier letter
  or `*`, the value is a level or `off`; the specific wins over the general. The table replaces the
  old lists, which still work, and the *XBSL: move the rule settings into one table* command
  rewrites them.

### Fixed
- **Debugging did not see the "Env File" setting and went to the wrong stand** - the .env was
  taken from `launch.json` alone. It now resolves the way the application id already did: a launch
  configuration wins over the setting.

### Changed
- **The settings sections are named after what they mean, not after a command:** "Stand" and
  "Debugger" instead of "Deploy" - the stand behind them is shared.
- **The "from install to debugging" diagram** on the start page: where the extension, the engine
  and elemctl come from, and what the platform distribution hands over.
- **The metadata tree's title bar keeps two buttons** - deploy and collapse; new project, grouping,
  refresh and hiding empty categories moved into the "..." menu. Six icons in a row read as a row
  with nothing leading.
- **Collapsing stops at the first level:** the list of metadata kinds stays visible. The built-in
  button collapsed the project root as well, leaving one line in the tree and two clicks back to
  the kinds.
- **The paths to the tools are collected in "General"** - the xbsl engine, elemctl and the Python
  interpreter lived in three different sections while answering one question: where things are
  installed.
- **The retired rule settings are gone from the forms** - the invitation now belongs to the table
  alone. The code still reads them, so an existing setup keeps working; move them with the command.
- **Inside a section the settings go by importance, not alphabetically** - the path to the tool no
  longer sinks between minor fields.

## 0.58.1

### Fixed
- **Four settings showed the "Details" link as raw markdown.** A description carrying a link has to
  live in `markdownDescription`; in a plain `description` VS Code prints it as text. Affected
  *Checking > Workspace Lint*, *Language server > Command* and both debugging paths. A test now
  refuses a description with a link outside `markdownDescription`.

## 0.58.0

### Added
- **The application to deploy to is picked from a list.** Where the deploy used to ask for a GUID
  in an empty box, it now offers the applications `elemctl apps list` can see – name, status,
  address. Debugging asks the same way. Typing the value by hand stays for an environment where
  the list is out of reach.
- **`xbsl.debug.applicationUrl`** – where to open the application under debug. Empty keeps the old
  behaviour (the `uri` of the application card, its address inside the platform); set it when the
  application answers on a domain of its own.

### Changed
- **The settings are split into sections** – General, Checking, Rule groups, Language server, Code
  templates, Deploy, Debugging – instead of one list of 39. The settings tree now opens on the
  section you need.
- **The descriptions are one sentence, with a "Details" link.** VS Code always renders a setting's
  description in full, so a long one turns the screen into a wall of text; the details moved to the
  documentation site.
- **The application id and the application address are told apart in the wording**: the deploy
  setting says plainly that it is an identifier or a name, not an address.

## 0.57.1

### Fixed
- **The settings table pointed at a README that no longer exists.** The `xbsl.deploy.*` row linked
  to the retired XBSL Debug extension in the elemctl repository; both settings families are now
  described here, in [Deploy](#deploy) and [Debugging](#debugging). The terminal task of an elemctl
  install is named after this extension too.

## 0.57.0

### Added
- **Debugging 1C:Element applications is now part of this extension** - it used to be a separate
  one, and the elemctl path with the application id were asked for twice. Breakpoints, the call
  stack, variable values and stepping go through the platform's own debug adapter; start with
  *XBSL: Set up 1C:Element debugging*.
- **The status bar shows the elemctl version** next to the engine one - deploy and debugging both
  depend on it, and until now nothing answered whether it was there at all.

### Changed
- **The deploy button moved to the metadata tree's title bar.** It used to sit in the editor title
  and only appear while an `.xbsl` file was open, although a deploy takes the whole project.
- **The workaround for the crash on expanding a structure on a client frame is unconditional.** Its
  setting could only buy a broken session, so it is gone.
- **The diagrams follow the reader's theme.** They carry a light and a dark palette now; the
  documentation site shows the SVG, this README keeps the PNG.

## 0.56.1

- **The changelog was rewritten: shorter and to the point.** Every entry says what changed for the
  reader, without the account of how it was done inside. Nothing changed in the extension itself.

## 0.56.0

### Added
- **The `.xbql` language and query highlighting.** The query file of a virtual table is no longer
  plain text: the extension declares the language, plugs in the grammar of the query language and
  subscribes the LSP server to such a file - the dot after a table alias now offers its fields. The
  same grammar highlights a `Query{...}` block inside a module.

## 0.55.0

### Added
- **The metadata tree opens a virtual table's query.** A virtual table has no module - its paired
  file is an `.xbql` query; the node now carries its path, the menu has an entry for opening it, and
  clicking the node leads to the query.

## 0.54.0

### Changed
- **The rule count in the "Code" group description caught up with the registry:** engine 0.59.0
  brought `code/unknown-structure-field`, so the group has 29 error rules instead of 28.

## 0.53.0

### Added
- **The "Enable" setting: rules disabled by default can be switched on from the editor.** There was
  no way to enable them at all - `xbsl.rules` and `xbsl.groups.*` work on top of findings the server
  has already sent, and `Select` replaces the set. A list of rules, groups or tier letters goes into
  `xbsl.linter.enable`.

## 0.52.0

### Added
- **Every kind the engine can create is offered by the metadata tree** - three times the former
  dozen: a storable structure, a constants set, a virtual table, a SOAP service, the contracts, an
  event log event, a scheduled job, a processing, an exchange plan, an access key, the privileges, a
  settings storage, localized strings and four kinds of commands. A report and a report panel are
  still not created - they need the designer.
- **"Add localization (translation)"** on a localized strings element: the language list comes from
  the engine, and the new node is selected right after it is created.
- **Forms are added for every owner the engine generates them for,** not only for a catalog and a
  document; which forms are offered depends on the owner's kind.
- **Subordinate forms nest under their owner** by every naming convention, and the list row
  component no longer settles in "Common forms".

### Fixed
- **The URL template menu never showed up** - in the `when` clause of four entries the word boundary
  was written so that the condition never matched.
- **The Russian localization caught up with the interface:** 21 strings were shown in English under
  a Russian editor.
- **English command titles write the service file names in English**
  (`Open object module (.Object.xbsl)`).

## 0.51.0

### Fixed
- **The properties panel no longer offers an attribute the properties of another type** - a string
  attribute was shown the numeric length limits. What is written in the yaml is never hidden.

## 0.50.0

### Fixed
- **English names of the service files are recognized by the metadata tree** - the project root, the
  subsystem nodes and the application module follow the project's spelling.
- **English element kinds are recognized by the metadata tree**
  ([issue #1](https://github.com/keyfire/xbsl/issues/1)). `ElementKind: Enumeration`, `HttpService`
  and `InterfaceComponent` used to land in "Other"; the kind is now resolved through the
  serializer's own kind table, and an English project is grouped exactly like a Russian one.

## 0.49.0

### Added
- **The `xbsl.groups.conventions` setting** - the level of the engine's new localization conventions
  group, the same switch the other groups have.

## 0.48.0

### Added
- **URL templates and HTTP methods are added from the metadata tree:** the engine writes the yaml
  and the handler stub in one operation, and completes an existing template with the missing methods
  only.
- **A colour for method names in the palettes, and the "Calm" palette** - it mutes the keywords so
  that the names stand out.

### Changed
- **A metadata handler is edited like a form event** - with the method list, navigation and creating
  a missing one. Clearing such a handler leaves the module alone.
- **An element's localization sits right under it** rather than in a separate group; the globe stays
  with the URL.

### Fixed
- **Method names are coloured deliberately** - a name used to take a random colour from the theme
  and looked different in a declaration and in a call.

### Removed
- **The second, TypeScript navigation is gone** together with the `xbsl.navigation.enabled` setting:
  it was a lagging copy of what the language server does. Navigation now comes from the engine only.

## 0.47.0

- **F12 on a platform member opens the documentation** instead of answering "definition not found":
  a stdlib member has nowhere to jump to, and its documentation page IS its definition. A real
  definition always wins.
- **The cards of engine 0.52.0 reached the editor:** a platform method shows the parameters of its
  signature and every overload, and a name from the global catalogue got a card at all - with its
  kind and the environment it exists in.

## 0.46.0

- **The hovers of engine 0.51.0 reached the editor.** A member of a platform type got a card with
  the member's kind and result type, a project method shows its signature and description, and
  completion follows the value a project method returned.

## 0.45.0

- **The column grid of the wireframe is measured, not invented.** Probing all five sizes on a
  deployed form showed that the gap is always 24px, the number of columns is the largest n ≤ 4 for
  which a column is no narrower than 250px, and a size of N columns is `N * column + (N-1) * 24`.
  The wireframe builds a row by exactly that grid.

## 0.44.0

- **The engine's new rule from 0.50.0 reached the editor:** `code/unclosed-resource` got a
  documentation link, and the rule counts of the `code` group match the engine again.

## 0.43.0

- **The variable naming standard reached the editor:** every finding of the six new `style/` rules
  opens the naming section of the documentation, and the group description names the current default
  - 27 warning rules.

## 0.42.0

- **A translation opens from the tree.** Translated strings live in separate per-language files and
  carry no element kind, so the tree never saw them. A `LocalizedStrings` element now expands into
  "Localization" with a node per language.

## 0.41.0

- **The extension says when a newer one is out.** Open VSX is asked once a day, and an arrow with
  the version lights up in the status bar. The check is quiet, is switched off by
  `xbsl.checkForUpdates`, and the command asks right away; anything unexpected ends in silence.

## 0.40.0

- **Dialog hints name a metadata key the way the PROJECT writes it,** not the way the editor is
  configured: an English window over a Russian project used to suggest a key the file does not have.
  The English spellings come from the compiler's own dictionary.

## 0.39.0

- **The metadata tree fills its branches in an English project too.** The reader knew the section
  keys in Russian only, so an English object had a bare node. The pairs now come from the engine
  (`xbsl/metaKeys`); an engine that does not know that request keeps the former behaviour.

## 0.38.0

- **The group descriptions in the settings name the rules of engine 0.40.0** - four new rules changed
  the level counts.
- **The codes of the new rules open the documentation** from the Problems panel.

## 0.37.0

- **The group descriptions in the settings name the rules of engine 0.39.0.**
- **`yaml/delete-current-needs-immediate` opens the "Catalog properties" section.**
- **The setting strings speak English in the English locale** - `Id`, `Handler` and `Name` instead of
  the Russian spellings.

## 0.36.0

- **The group descriptions in the settings name the rules of engine 0.38.0.**
- **A rule code in the Problems panel opens its documentation section** - for both environment checks
  that is "Module execution".

## 0.35.1

- **The changelog speaks of facts rather than of how they were obtained.** Nothing changed in the
  extension itself.

## 0.35.0

- **The group descriptions in the settings name the rules of engine 0.37.0** - five new rules changed
  the level counts, and the `project` group gained the folder-matches-descriptor check.

## 0.34.0

- **The properties and documentation panel opens in the secondary sidebar** - the layout from the
  screenshots became the default. It needs **VS Code 1.106 or newer**; an older editor is served the
  previous version.
- **The panels are named by their role** - "1C:Element • Project" and "1C:Element • Inspector": the
  former titles repeated the view name inside themselves.
- **The metadata tree and the properties panel understand a project with English spellings,** and the
  name offered to a new object follows the project (`NewCatalog`, not the Russian default).
- **English messages no longer name a kind in Russian** - the platform has an English spelling of its
  own.
- **The wireframe no longer spills out of a size-limited group:** such a block scrolls or clips,
  while a group without a size grows as before.
- **A group lays out its content the way its yaml asks:** the intervals become the gap between
  children, the paddings the group's own inner padding. The scale is measured on a deployed
  application: the platform uses gaps of exactly 0/8/16/24/32 pixels.
- **All six layouts are laid out, not two:** by columns, matrix, bento, carousel and horizontal in a
  single row. Everything but the vertical one used to be drawn as a plain column.
- **The two alignments no longer get confused:** one lays out the children of a container, the other
  places the component itself inside its parent - the platform documents them apart.
- **Stretching beats alignment,** as it does on the platform, and the column width is read only
  inside the by-columns layout - the only one where the platform measures in columns.
- **The column width reached the wireframe** - all six values are drawn in exact proportions of the
  wireframe's own base.
- **A horizontal group squeezes its content instead of overlapping its neighbours.**
- **A node the platform does not draw is dimmed,** and a computed visibility is dimmed more
  faintly - such groups are often mutually exclusive, and the expression is visible in the hint.
- **The screenshots were retaken** on the new layout and the new panel titles, in both languages.

## 0.33.0

- **Findings speak the language of the editor.** An empty `xbsl.linter.lang` now means "follow the
  editor's interface language"; an explicit `ru`/`en` still wins. Metadata names in the properties
  panel stay as they are written in the sources.

## 0.32.0

- **The presentation of a data object is picked from its string attributes** - a closed list instead
  of free input; what is written in the yaml stays visible as the first entry.
- **Documentation links for the new rules:** `yaml/presentation-field` and
  `yaml/unexpected-type-argument` open their help sections; the group counts match engine 0.34.0.

## 0.31.0

- **The form wireframe reflects sizes, icons and danger:** explicit sizes reach the drawing, a button
  with an icon caption is drawn compactly, the action danger colours the button, field commands
  become icons at the input's edge, and an explicit image colour paints the SVG through a mask.
- **The True/False captions follow the interface locale,** while the yaml always gets the platform
  spelling.
- **A deploy without an app id asks for it** in an input box instead of failing in the terminal; the
  answer is saved into `xbsl.deploy.appId`.
- **A synthetic standard attribute shows the schema of its class** - `Code` shows every property
  including auto-numbering, and a closed type restriction became a drop-down list.

## 0.30.0

- **Read-only properties are collected into a section of their own** - they used to be mixed with
  the editable ones and shown twice.
- **A filled collection is no longer marked "(not set)"** - it shows its size.
- **The element kind row is gone from the panel** - the kind and the name are already in the header.

## 0.29.0

- **The "All properties" section appeared for collection items** - an enumeration value, an
  attribute, a dimension, a resource and a structure field. The item's class is resolved through the
  platform metamodel, so nested nodes get the full schema with defaults and documentation too.

## 0.28.0

- **The form designer is collected into a single panel:** the structure tree on the left, the data on
  the right, the wireframe below and draggable splitters between them. The separate "Structure" and
  "Data" views are gone.
- **A panel per form:** each has its own tree, selection and expansion memory; the panel and its yaml
  travel as a pair.
- **Keys inside the panel:** the arrows walk the tree, `Alt+Up`/`Alt+Down` move a component, `F2`
  renames, `Delete` deletes, `Ctrl+C`/`Ctrl+V` carry a yaml fragment, and `Ctrl+Z`/`Ctrl+Y` undo and
  redo an edit.
- **The selection honestly follows the cursor** - it is shared by the wireframe, the tree, the yaml
  and the properties panel.
- **An event can be removed whole:** the reset asks whether to only unbind it or to delete the
  handler from the module; the yaml and the module are edited in one undo step.
- **A type hover shows a description,** not just a link.
- **The palette moved next to the metadata tree** and is shown only while a form panel is open;
  insertion is a double click - the platform does not carry a drag from its own tree into a webview.
- **Dragging works inside the panel:** a structure node onto another node, a record from the data
  panel onto a structure node.
- **The reset cross now sits next to the field in every editor.**
- **The documentation was retaken for the new layout,** and the designer description gained the
  "Following the cursor" and "Examples" sections.

## 0.27.1

- **The panels survive an editor restart** - the form card, the documentation page and the templates
  panel come back by themselves; a panel with nothing to show closes rather than hanging empty.
- **The extension starts with the window,** so the trees and panels are ready whichever container was
  active at closing time.

## 0.27.0

- **The properties panel shows the unset properties of a metadata object too** - the same two
  sections the form components have: the set ones on top, all applicable ones below.
- **The editors are typed by the platform metamodel:** a tri-state for a flag, a value list for an
  enumeration, a combo box for a data type; the platform default and the version the property
  appeared in are shown.
- **The metamodel data was rebuilt** - the properties gained types, defaults and enumerations.

## 0.26.1

- **Completion follows the project's development language** - the names of that language come first,
  nothing is hidden.
- **The rule table in the documentation gained a rule number,** the same in both locales.

## 0.26.0

- **Four new engine rules in the Problems panel:** `code/resource-bare-name` and
  `code/unknown-resource` (a resource given by a bare file name), `yaml/no-expression-in-literal` and
  `yaml/bare-object-value`.
- **The scaffolding accepts an element kind in either platform language** - `Catalog` works next to
  its Russian spelling.
- **The term dictionary grew fourfold** and covers the members of every stdlib type; the query
  language keywords arrived as data too.

## 0.25.0

- **Three new engine rules in the Problems panel:** `yaml/ref-needs-nullable` (a reference has no
  default value, and the apply fails), `yaml/unknown-enum-value` and `yaml/standard-field-length`.
- **Short interpolation inside a string literal is parsed,** so a substitution of a name that does
  not exist is found before the build.
- **The counts in the settings group descriptions follow the engine by themselves** - a guard in the
  engine's tests checks every count against the rule registry.

## 0.24.0

- **Documentation links for the new engine rules** - `code/query-needs-server` and
  `yaml/foreign-not-public` open the right section inside the editor.
- **The counts in the settings group descriptions were brought in line with the engine** in both
  locales.

## 0.23.0

- **A visual form designer** - a container with three panels above a form's yaml: "Structure" (a
  component tree synchronized with the cursor, with reordering, wrapping, duplication and copying
  subtrees between forms), "Palette" (insertion by double click or drag) and "Data" (dragging an
  attribute creates an input field with a binding).
- **A "Properties" panel** edits the selected component with typed editors: enumeration lists, a
  tri-state, a colour with the form's own presets, a literal/binding toggle with dot completion and
  an event editor that can create a handler stub.
- **A wireframe preview** highlights the selected component, shows resource images and scrolls to the
  content in a narrow panel.
- **Structural search over forms** - by component type and `key=value` predicates.
- **Block presets** - save a component subtree and paste it into any form.
- **A read-only designer** for library forms and other read-only sources.
- **A new 1C:Element project wizard.**
- **The metadata tree** remembers its expansion across reloads, its category hints link into the
  documentation, and enumerations and contracts got semantic colouring.
- The palette and the typed editors need engine 0.23.0 and the language data; the structure tree and
  the text edits work without them.

## 0.22.1

- **Custom code templates now really reach Ctrl+Space:** the extension passes `--templates` to the
  server, and the server takes `.xbsl-templates.json` from the workspace root by default - the very
  file the panel writes.
- **The templates panel no longer breaks Cyrillic on Windows** - the engine is started with
  `PYTHONUTF8=1`.

## 0.22.0

- **Code templates - the 1C:EDT mechanism together with its export file.** An abbreviation plus
  Ctrl+Space gives the whole construct with its tab stops, and an object-name variable expands into
  the catalogs of your project. There are 51 built-in templates, each parsed by the engine's parser.
- **The "XBSL: code templates" panel** is laid out like the EDT dialog - a list with the invocation
  context, the description and the text, plus add, edit, delete, import, export and restore.
- **Custom templates live in `.xbsl-templates.json`** (the `xbsl.templates.file` setting) and extend
  the built-in set.
- **Templates need the LSP mode;** in the CLI index mode they are not offered.
- **The engine's `security/hardcoded-secret` rule** - a key or a password written as a literal.

## 0.21.1

- **The properties panel follows the selection in the tree** when it is already open; the selection
  itself neither opens files nor takes the focus.

## 0.21.0

- **The object properties from the metadata tree became a sidebar view** rather than an editor tab:
  clicking a node no longer closes the code.
- **The status bar says "engine" instead of "lint"** for the engine version.
- **Engine 0.19.0:** a full XBSL parser following the platform grammar, the `code/parse-error` and
  `code/undefined-name` rules, a run about 2.3 times faster and the parallel `--jobs` mode.

## 0.20.0

- **Documentation links for every rule backed by a platform requirement** (54 of 78): the diagnostic
  code opens the right section inside VS Code.
- **Works with engine 0.18.0:** the scaffolding creates valid registers and documents, a SOAP
  service, processing operations, localized strings, indexes and report query parameters were added;
  libraries are plugged in with `add-dependency`.

## 0.19.1

- **README: the "How it works" diagram** - the extension's features on top of the long-lived
  `xbsl-lsp` server with the CLI fallback. No code changes.

## 0.19.0

- **The engine and the whole project were renamed: xbsl-lint → xbsl.** The engine command is `xbsl`,
  the server is `xbsl-lsp`; the old commands still work as aliases and the baseline file keeps its
  name.
- **The metadata tree creates through the engine:** "Add <class>", the "+" actions for fields, a
  subsystem and an object form are written by the engine's scaffolding, and the extension applies the
  changes in one undoable edit. Templates no longer live in the extension.
- **"Add object form" offers an object form or an object plus list pair,** and the engine registers
  them with the owner.
- **The same scaffolding is available to AI agents through the engine's `meta_*` MCP tools.**

## 0.18.2

- **README:** the baseline exclusion example in the English version quotes the English diagnostic
  text. No code changes.

## 0.18.1

- **A new icon:** a transparent background and a yellow central tile with braces.

## 0.18.0

- **"Exclude this finding (to the baseline)" in the lightbulb of every finding:** the reason and the
  finding's identity go into the baseline file. Only that one finding is excluded - the rule keeps
  checking the rest of the project.
- **The baseline applies to every run of the extension** - workspace, per-file and server.
- **Per-file runs pass the path relative to the workspace folder,** so `structure/xbsl-pair` sees the
  module's real neighbours.
- **"XBSL: restart the linter" recreates the server process with fresh arguments.**

## 0.17.0

- **"Find all references" for methods, objects and interface components** - on top of the project
  index it shows calls inside a module, calls through a module or a component and handlers in the
  yaml. Needs engine 0.13.0 or newer.

## 0.16.1

- **Code blocks in the documentation got a "Copy" button.**

## 0.16.0

- **The table of contents gained page sections:** a page expands into its headings, and a click opens
  the page at the right section.

## 0.15.2

- **Opening a document scrolls to the right section** instead of the top of the page.

## 0.15.1

- **A standard document link opens the section inside VS Code,** not an external site.

## 0.15.0

- **A standard document link straight from a diagnostic:** the rule badge in Problems became a link
  to the standard's page, and the lightbulb offers to open the document in the Documentation panel.

## 0.14.1

- **The README gained a section about the documentation panel.**

## 0.14.0

- **A new "Documentation" view in the 1C:Element container:** the table of contents of the platform
  help, a search and the page itself with images and a link to the source. A right click on a
  variable or a type opens the right page. Needs an engine with the documentation database; in the
  CLI mode the panel says so.

## 0.13.0

- **A new `project` rule group** - the project properties per the "Filling in the project
  properties" standard.
- **A new rule in the `query` group:** `In` with a subquery over a field of a compound type - the
  standard writes such a condition with `Exists`.
- **A new `naming` rule group** - project element names per the platform standard: the number by
  element kind, the letter `ё` and underscores, abbreviations, the element kind inside the name, the
  environment postfix and an empty presentation. All twelve are warnings.

## 0.12.0

- **A new "1C:Element" container in the activity bar:** the project elements are grouped by kind, an
  object form nests under its owner, and forms without an owner go to "Common forms". A yaml + xbsl
  pair is one row whose context menu opens the description, the module, the object module or the
  form preview.
- **The project is the root of the tree,** objects expand into "Attributes / Dimensions / Resources /
  Tabular parts / Forms", and the "+" action inserts a stub with a fresh id and shows it.
- **The tree shows the object classes it can create even when the project has none yet,** and each
  category root has its own "Add <class>" - it asks for a name and a subsystem and writes a minimal
  valid yaml.
- **Subsystems:** a branch of their own under the project, adding a subsystem, and a multi-select
  filter by subsystem.
- **An editable properties panel on the right:** scalar properties are edited in place, the id and
  the element kind are read-only, collections stay in the tree.
- **An attribute's type is edited with a combo box:** primitives, references and the project's
  enumerations are suggested; string-specific properties are shown for a string only.
- **The "Standard attributes" group shows the predefined attributes even when the yaml has none;**
  editing a property materializes the record.
- **The git status is shown on the tree rows,** as in the Explorer.
- **Inside a query block, completion after a table offers the table's fields** rather than the
  object's members.
- **The LSP mode is on by default:** it provides hovers and type-aware completion, and without the
  `[lsp]` extra the extension quietly continues in the CLI mode.
- **Type-aware completion:** a query table by its alias, the loop variable over a query result, a
  variable of a known type and the stdlib types offer their members. The parsing goes over tokens, so
  keywords are understood in both forms.
- **Clicking a node opens the source on the left and the properties or the preview on the right,**
  reusing the columns that are already open; the tree is synchronized with the editor.
- **The tree groups by object class or by subsystem** - a switch in the tree header, and the choice
  is remembered.

## 0.11.4

- **README only:** the deploy command details moved to the README of the XBSL Debug extension of the
  [elemctl](https://github.com/keyfire/elemctl) project.

## 0.11.3

- **A clean file opened after a workspace run offers a Quick Fix again** - the edit snapshot is
  restored from the saved report of the last run.
- **The "Deploy" section of the README refers the details to the elemctl project.**

## 0.11.2

- **README only:** animated demos of the diagnostics, the form preview and the properties panel.

## 0.11.1

- **A new `query` rule group in the settings:** the tables of query blocks are checked against the
  project's objects.
- One release combining the changes of 0.8.0-0.11.0 below.

## 0.11.0

- **The form preview got a properties panel,** like the platform's web editor: enumerations as lists,
  the stretch properties as a toggle, the rest as text. Edits are applied to the yaml as pinpoint
  replacements, an empty value clears the property, and a selection positions the yaml editor without
  taking the focus.

## 0.10.1

- **A new "XBSL: preview form" command** - the form wireframe in a webview: nested groups, fields
  with captions and bindings, buttons, tables with their columns, tabs, cards and the form command
  bar. The panel follows the active editor and redraws as you type.
- **The preview toolbar:** zoom and a theme choice - light, dark or the editor's theme; the choice is
  remembered.

## 0.9.0

- **A new "Rule groups" settings section:** a drop-down per finding kind - keep the rules' own
  levels, show the whole group at one level or switch it off. `xbsl.rules` stays a thin override and
  outranks the drop-downs.
- **The lightbulb gained a "Configure rule groups..." shortcut.**

## 0.8.0

- **A new "XBSL: deploy to a stand (elemctl)" command** - build, upload, apply and verification of
  the actual apply as a terminal task, after a confirmation dialog showing the exact command line.
  The target comes from the `.env` file or from the `xbsl.deploy.*` settings.
- **The English README shows the English command titles.**

## 0.7.1

- **Buttons that install the engine on the matching errors** - the installation runs as a terminal
  task, and the check restarts on success.

## 0.7.0

- **A new `xbsl.rules` setting** - levels and disabling per rule or per whole group, plus a
  "Configure rule..." action in the lightbulb of every finding.

## 0.6.1

- **A bilingual interface (en/ru):** the manifest and every runtime string follow the VS Code
  interface language.

## 0.6.0

- **An experimental LSP mode:** a long-lived server provides hovers, instant diagnostics as you type
  and index-based navigation; if the server fails to start, the extension falls back to the CLI mode
  by itself.

## 0.5.0

- **A new "XBSL: code palette" command** - recolour the syntax with one of the popular palettes or
  return to the editor's theme; only the `*.xbsl` scopes are affected.

## 0.4.1

- **A new `xbsl.projectRoot` setting** - the source root for project runs and for the navigation
  index.

## 0.4.0

- **A Quick Fix for mechanical findings:** the lightbulb applies exactly the edit the linter
  reported.
- **A "fix all" action** repairs every fixable finding of a file at once; an edit is applied only to
  the text it was computed on.

## 0.3.0

- **Go to definition and completion over the project index** - objects, tabular parts, local types,
  enumeration values, methods and form components. Silent when the installed linter has no index
  command.
- **A new `xbsl.navigation.enabled` setting.**

## 0.2.0

- **Workspace diagnostics:** saving any `.xbsl`/`.yaml` starts a full run over the workspace folder,
  bringing the project rules into the editor.
- **New `xbsl.workspaceLint` and `xbsl.workspaceLintTimeout` settings.**
- **The "XBSL: check the whole project" command reuses the same machinery.**

## 0.1.0

- **The first release.**
- **Syntax highlighting for `.xbsl`** - bilingual keywords, decorators, string interpolation,
  generics.
- **Diagnostics as you type,** with a debounce and on save.
- **The "XBSL: check the whole project" command** for a check over the whole workspace.
- **Settings:** the linter command, the Python interpreter, the data folder, the language, the rule
  select/ignore, the run mode and the debounce.
