# Changelog

[Русский](https://github.com/keyfire/xbsl/blob/main/editors/vscode/CHANGELOG.ru.md) · **English**

> The platform is bilingual: a metadata name has an English spelling of its own
> (`Attributes`, `TabularParts`, `VisibilityScope`) - the `en` argument of its metamodel
> annotation, or the model member's name capitalized - and this English changelog uses those.
> The Russian spellings - the ones that appear in the sources of a Russian-language project -
> are in the [Russian changelog](https://github.com/keyfire/xbsl/blob/main/editors/vscode/CHANGELOG.ru.md).
> See also the [note on names](README.md#navigation-and-completion).

## Unreleased

### Changed
- **A metadata handler is edited exactly like a form event.** A property the metamodel declares
  as `BslHandler` - the `Handler` of an HTTP method, of a job, of a log event - was a plain text
  box: no list of the module's methods, no jump, no way to create the one that does not exist.
  It now gets the very editor an event row has, and the kinds are covered by the declared type
  rather than by a list of property names. The two-file reset stays with events: a metadata
  handler is an ordinary property, so clearing it leaves the module alone.
- **The localization of an element sits right under it.** The "Localization" group held a single
  language and cost a click to open; the languages now hang under the element itself. Their icon
  is the one of localized strings - the globe stays where URLs are, so an HTTP service and a
  translation no longer read as the same thing in the tree.

## 0.47.0

- **F12 over a member of the platform opens its documentation instead of saying "no
  definition".** Go to Definition is answered from the project index, so a stdlib member -
  `HttpResponse.StatusCode`, `JsonSerialization.WriteObject` - had no source to jump to, and
  the page IS the definition of such a member. The key now asks the definition providers
  first: a real definition always wins, a member with no source opens the docs panel at its
  page, and with neither the command is passed on to VS Code so IT reports the miss in its own
  words.
- **The cards of engine 0.52.0 reach the editor.** A platform method shows the PARAMETERS of
  its signature (every overload, when the documentation prints more than one) instead of a
  bare `Name()`, and a name from the global catalogue - `Message`, `Max`, `Sqrt`,
  `FilesUpload` - has a card at all, naming its kind and the environment it exists in.
  Regenerated engine data is what carries the signatures.

## 0.46.0

- **The hovers of engine 0.51.0 reach the editor.** A member of a platform type
  (`HttpClient.RequestPost`, `HttpResponse.StatusCode`, `AccessContext.Privileged`) now has a
  hover card naming its kind and result type, a project method shows its signature and the
  description comment above its declaration, and the documentation link of a member points at
  the page of its type instead of an article that merely quotes the name. Completion follows a
  value returned by a project method - the dot after `val P = Module.Method(...)` offers the
  members of the structure it returns.

## 0.45.0

- **The column grid of the wireframe is measured, not invented.** `WidthInColumns` used to be
  drawn against a base of 220px picked to keep the ratios right, because the platform names the
  scale but never says what a column is. A probe of all five sizes on a deployed form, read at
  six viewport widths, shows the column is not a constant at all: the gap is always 24px, the
  number of columns is the largest n <= 4 whose column `(row - (n-1)*24) / n` is at least 250px,
  and a size of N columns is `N * column + (N-1) * 24`. Half a column is half of ONE column with
  the gap taken out of it, not half a track. The wireframe now lays the row out as that grid, so
  a size follows the width of the preview the way it follows the width of a form.

## 0.44.0

- **The new rule of engine 0.50.0 is wired into the editor.** `code/unclosed-resource` - a
  closeable resource left open by an early exit from the loop over it - gets its documentation
  link (`topics/closeable-type`, the article that describes the `use` modifier), and the rule
  counters of the `code` group are back in step with the engine.

## 0.43.0

- **The variable-and-constant-names standard is wired into the editor.** Engine 0.48.0 ships
  six new `style/` rules for the standard; the extension now opens the platform's naming
  section from each of their findings (the docs button in the Problems panel), and the
  `style` group description states the current default - 27 rules at warning.

## 0.42.0

- **A translation opens from the tree.** Translated strings live in a section of their own -
  `<where the element lies>/Localization/<language>/<Name>.yaml`, one file per language - and such
  a file carries the string sections alone, without `ElementKind`. The tree collects elements by
  that very key, so the translations were invisible in it and a translated text could only be
  opened as a file, by name. Now a LocalizedStrings element expands into **Localization** with a
  node per language folder: a click opens that file, and opening it in the editor selects the node
  back in the tree. The guess is confirmed by the owner - a file under a folder named after the
  section that translates nothing goes the regular way, as before. Both spellings of the section
  folder are accepted: a project written in English is legal code.

## 0.41.0

- **The extension says when a newer one is published.** It is installed from a vsix, and the
  editor asks the Marketplace for updates while the CI publishes to Open VSX - so nothing in
  the editor ever noticed a version left behind, and the only signal was the version in the
  status bar. Open VSX is now asked once a day; when a newer extension is out, an arrow lights
  up in the status bar and the tooltip names the version. The check is quiet on purpose (no
  popup on startup), can be switched off (`xbsl.checkForUpdates`), and the command
  "XBSL: Check for a newer extension" asks right away regardless of the setting. Anything
  unexpected - no network, a changed answer, an unreadable version - ends in silence: a false
  alarm here is worse than a missed update.

## 0.40.0

- **Dialog hints name a metadata key the way the PROJECT spells it.** The spelling followed the
  language of the editor, so an English window over a Russian project suggested a key the file does
  not contain - `Rename (Name)` where the yaml says `Имя`. The hints are parametric now and the
  English spellings come from the compiler's own dictionary. The predicate lived on the metadata
  tree only; an asynchronous twin was added, because the model is built lazily and a panel asking
  before the tree is first opened would have been told the wrong language. The new-project wizard is
  the exception in reverse: scaffolding writes a Russian development language into every new
  project, so the vendor key there is a constant rather than a choice. One contributed command that
  named a key in a static string - the manifest is substituted before the extension activates, so it
  cannot be parametric - was reworded to name the object instead.

## 0.39.0

- **The metadata tree fills its branches in an English project.** The reader knew the section keys
  by their Russian names only (`Реквизиты`/`Attributes`, `ТабличныеЧасти`/`TabularParts` ...), so an English
  object showed a bare node: on the demo catalog it reported 0 attributes and 0 tabular parts
  where the file declares 5 and 1. The pairs now come from the engine (`xbsl/metaKeys`), asked
  once per session, and nested collections use the same lookup - a tabular section spells its own
  `Attributes`. An engine that does not know the request answers nothing, and the tree behaves as
  before, Russian keys only.

## 0.38.0

- **The group descriptions in the settings name the rules of engine 0.40.0.** Four new rules
  changed the level counters: the `code` group is 25 error / 17 warning, the `yaml` group
  16 error, 11 warning, 1 info.
- **The codes of the new rules open their documentation from the Problems panel.** The per-object
  permission rules point at "Права элементов проекта и вычисление разрешений", the localization
  ones at the localization section.

## 0.37.0

- **The group descriptions in the settings name the rules of engine 0.39.0.** A new rule over
  deletion by reference changed the level counters of the `yaml` group - 15 error, 11 warning,
  1 info now.
- **The code of `yaml/delete-current-needs-immediate` in the Problems panel** opens the
  "Catalog properties" documentation section - the same one `query/deletion-mark-immediate`
  points at.
- **The settings strings speak English in the English locale.** The group descriptions and the
  rename command still carried Russian spellings of platform names (`Ид`, `Обработчик`, `Имя`);
  they are `Id`, `Handler` and `Name` now. The Russian locale is unchanged.

## 0.36.0

- **The group descriptions in the settings name the rules of engine 0.38.0.** Two new rules over
  the execution environment changed the level counters of the `code` group - 24 error / 14 warning
  now.
- **The rule code in the Problems panel opens its documentation section.** For
  `code/client-available-needs-context` and `code/server-module-in-client-context` that is
  "Module execution" - the same section the other environment checks point at.

## 0.35.1

- The changelog states the facts, not how they were obtained: what a rule checks and what the
  platform does stay, the provenance of that knowledge is gone. Nothing in the extension changed.

## 0.35.0

- **The group descriptions in the settings name the rules of engine 0.37.0.** Five new rules
  changed the level counts a settings page shows next to each group - `code` 23 error / 14 warning,
  `yaml` 14 / 11 / 1 info, `query` 2 warning / 3 error, `project` 3 warning / 1 error - and the
  `project` group now also mentions the directory path matching the descriptor. The counts live in
  both `package.nls` files and are kept honest by the sync guard, which now looks at all eight
  places instead of four.

## 0.34.0

- **The properties panel understands an English-spelled project.** `classifyEditor`, `metaKindOf`
  and the designer's own form test looked for `КомпонентИнтерфейса`/`ВидЭлемента` and never for
  `InterfaceComponent`/`ElementKind`, so an English form was not recognised as a component and
  the panel headed the card with "?" instead
  of the element kind. Both spellings are read now, and the metadata rows fall back to the English
  key pair (`Name`, `Type`, `Id`, `ElementKind`).
- **The English messages no longer name a kind in Russian**: "open a form yaml
  (InterfaceComponent)" - the platform has an English spelling of its own, and the message is
  what an English editor shows.
- **The screenshots were retaken** on the new layout and the new panel titles, in both languages.

- **The panels are named after their role** – "1C:Element • Project" (metadata and palette) and
  "1C:Element • Inspector" (properties and documentation). The old titles repeated the name of a view inside
  them ("Metadata" in "Metadata (1C:Element)"), so the *Open View* list read as duplicates; the
  documentation view kept a legacy title of its own and looked like a container there. Naming by
  content rather than by location survives dragging a container to the other bar.

- **The properties and documentation panel now opens in the secondary side bar** – the layout
  the screenshots show (metadata tree on the left, properties and documentation on the right)
  is the default and needs no dragging. It rests on the `secondarySidebar` contribution point,
  which VS Code added in 1.106, so the extension now requires **VS Code 1.106 or newer**; an
  older editor keeps installing the previous release from the marketplace. A container can
  still be dragged between the bars, and *View: Reset View Locations* restores the default.

- **The metadata tree sees an English-spelled project.** It recognized an object by
  `ВидЭлемента:` alone and never by `ElementKind:`, so an English project showed empty sections -
  and with every section empty
  the "hide empty categories" toggle looked broken too. Every key the tree reads is now matched in
  both spellings, and the kind is brought back to the one its tables are keyed by; the English
  spellings come from the platform's dictionary and a guard test keeps them from drifting.
- **The name offered for a new object follows the project**, not the editor: an English project is
  offered `NewCatalog`, a Russian one `НовыйСправочник`. The binding hint shows its sample the same
  way (`=Object.Field` / `=Объект.Поле`). The description of a kind stays Russian in any UI - the
  documentation shipped with the platform is Russian only.

- **The wireframe no longer bleeds out of a bounded group.** A group with a fixed `Height` (a
  wizard whose pages live in a 420px area) drew its children over whatever followed it - the
  footer buttons and the error bubble landed on top of the fields. A bounded box now clips:
  `VerticalScroll`/`HorizontalScroll` render as a scrollable area, a size or a maximum size
  without them clips, and a group with no size at all is left to grow as before.
  `MaximumHeight`/`MaximumWidth` reach the wireframe at all for the first time.

- **A group is spaced the way its yaml asks.** `VerticalItemsSpacing` /
  `HorizontalItemsSpacing` become the gap between children and `VerticalIndent` /
  `HorizontalIndent` the group's own padding; before this every group carried one hardcoded
  padding and no gap at all, so a dense group and a loose one looked the same. The scale is
  measured on a deployed application, not guessed: every gap the platform sets falls on
  0/8/16/24/32 pixels, and 16 - the documented default, "Авто равно Одинарный" - dominates.
- **A node the platform does not draw is dimmed.** `Visibility: False` used to render at full
  strength, so a wizard whose pages are all hidden but one looked like every page was on screen
  at once; the node stays in place (the wireframe and the yaml keep the same shape) but reads as
  switched off, and the tooltip says so.

- **The two alignments are told apart.** `ContentAlignment*` lays out the children of a container
  in bulk and `AlignmentInGroup*` places the component itself in its parent - the platform
  documents them as separate properties ("Размещение компонентов на экране"), and both are
  legitimately set on one group, which would be pointless if they meant the same. The wireframe
  used to read the second and apply it as the first: a group asking to sit at the end of its
  parent pushed its own content there instead.
- **`WidthInColumns` reaches the wireframe.** Half a column, one, two, three, four and unlimited
  are rendered in exact RATIOS against a base of the wireframe's own: the platform names the
  scale but never states the width of a column in pixels, and unlike the indent scale it could
  not be measured (the property only appears on forms behind a login). Calibrating the base
  against a deployed form is a note in the backlog.

- **All six layouts are laid out, not two.** `ByColumns` wraps by the form columns, `Matrix` and
  `Bento` become grids (the matrix one follows `MatrixLayoutSettings` - a described column list or
  the automatic columns with their minimum width), `Carousel` is a row that scrolls, and
  `Horizontal` is ONE row: the platform compresses or scrolls it, never wraps it. Everything but
  horizontal and vertical used to render as a plain column, so a row of four advantages showed up
  as four stacked cards and the site footer broke into two lines.
- **A computed visibility is marked apart from a switched-off one.** `Visibility: =expression` is
  decided at runtime - two such groups are often mutually exclusive (a desktop footer and a mobile
  one) - so the node is dimmed lightly, with the expression in the tooltip, while `False` stays
  dimmed hard.

- **Stretching beats alignment, and the column size applies where the platform applies it.**
  `HorizontalStretch: True` next to `AlignmentInGroupHorizontal: Center` used to collapse a
  full-width section into a narrow column - in CSS the alignment silently overrides the stretch,
  while the platform stretches "despite" it and aligns only what is smaller than its group.
  `WidthInColumns` is now read only inside a `ByColumns` layout, the one place the platform sizes
  by columns; applied everywhere it squeezed components that should have been left alone.
- **A horizontal group compresses instead of painting over its neighbours**, the way the platform
  describes it, and the caption of a project component the wireframe cannot draw goes in flow
  rather than hanging outside a 20-pixel placeholder. Measured on two deployed forms: the main
  page went from five overflowing boxes to none, the footer from a broken second line to seven
  single-line rows.

## 0.33.0

- **The diagnostics speak the language of the editor.** With `xbsl.linter.lang` left empty the
  engine used to fall back to the environment and then to the OS locale, so an English VS Code
  on a Russian system showed Russian messages next to an English UI. The empty setting now means
  "follow the display language of the editor"; an explicit `ru`/`en` still wins. Note that the
  METADATA names in the properties panel are a different matter - they are the names written in
  the sources, and a Russian-language project keeps them Russian in any UI.

## 0.32.0

- **The presentation of a data object is picked from its string attributes.** For a property
  typed "an attribute name" (the Presentation of a Catalog, a Document and the other kinds
  where the platform expects the name of a string attribute) the panel renders a closed list
  of the matching attributes instead of free text; the value written in the yaml stays visible
  as the first entry even when no such attribute exists - the panel does not hide what the
  file says. The judge of correctness is the engine's `yaml/presentation-field` rule.
- **Documentation links for the new rules.** The `yaml/presentation-field` and
  `yaml/unexpected-type-argument` codes in the Problems panel open their platform help
  sections; the group counters match engine 0.34.0 (100 rules now).

## 0.31.0

- **The form wireframe follows sizes, icons and action danger.** Explicit
  Width/Height/MinWidth reach the rendering (a 30x30 icon is no longer a 110x74 tile; a
  single given dimension frees the other for the image's aspect ratio), a button with
  TitleDisplayKind: Icon draws as a compact icon, an Image next to a text title draws
  beside the text, ActionSeverity tints the button (red for high, amber for medium), field
  commands (the `Commands` block) show as icons at the input's edge with the tooltip and the
  jump to yaml, an explicit image Color repaints the SVG through a mask, and an explicit
  "do not stretch" pins the component to the container start.
- **The True/False captions follow the UI locale.** In the English locale the tristate
  buttons read True/False; the yaml always keeps the platform spelling, and when the
  caption differs from it, the written value shows as the button's tooltip.
- **A deploy without an app id asks for one.** Instead of the elemctl "app id is not set"
  error in the terminal, an input box opens before the confirmation: the hint names
  `elemctl apps list` and the application card in the platform console, and the answer is
  saved to the folder's xbsl.deploy.appId setting.
- **A synthetic standard attribute shows the schema of its class.** Until Code or Name is
  written into the yaml, the panel used to show a handwritten row set without "All
  properties" - now the schema is requested by the would-be path, so Code shows every
  property of its class (auto-numbering included). A closed type constraint is a dropdown
  (String or Number), not every type of the project.

## 0.30.0

- **Read-only properties moved into a section of their own.** They used to be interleaved with
  the editable rows and shown twice - both under "Set" and under "All properties". Now the id,
  the tree-owned structures (Attributes, Items, AccessControl...) and everything else the panel
  cannot edit sits once in a collapsed "Read-only" section, while "Set" and "All properties"
  carry only what can be changed.
- **A filled collection no longer reads "(not set)".** For an enumeration with five values the
  Items row said "(not set)" - a collection written in yaml now shows its size (editing stays
  with the metadata tree).
- **The ElementKind row is gone from the panel.** The kind and the name already head the panel
  ("Enumeration · RegistrationPreviewKind") - a separate row only repeated them.

## 0.29.0

- **The "All properties" section now covers collection items.** For an enum value, an attribute,
  a dimension, a resource, a structure field or a tabular-section attribute the properties panel
  used to show only what was already set: the schema was resolved for the object root only. The
  item's class is now determined through the platform metamodel – the collection's dispatch key,
  its default implementation, and the built-in items with classes of their own (a catalog's Code,
  Description, Owner) – so nested nodes get the full schema with defaults and documentation too.

## 0.28.0

- **The form designer is one panel now.** A form depends on its own properties, so its structure
  and its data moved to where the form is shown: the structure tree on the left, the data on the
  right, the form frame under them, with draggable splitters between (their position is
  remembered). The separate "Structure" and "Data" sidebar views are gone, and so is the
  "Designer" container.
- **A panel per form.** A second form opens its own tab next to the first, and each panel keeps
  its own tree, selection and expansion memory; opening the same form again brings its panel
  forward instead of making a second one. A panel and its yaml travel as a pair: picking a tab on
  one side brings the other forward, and closing the panel closes the form's yaml (an unsaved one
  is left alone). A new yaml joins the group where the sources already are instead of splitting
  the layout.
- **The keyboard works inside the panel:** the arrows walk the tree, `Alt+Up`/`Alt+Down` move a
  component, `F2` renames, `Delete` removes, `Ctrl+C`/`Ctrl+V` carry a yaml fragment, and
  `Ctrl+Z`/`Ctrl+Y` undo and redo right from the panel (with the focus inside a webview the
  editor never saw the shortcut). The frame zoom follows the wheel over the zoom control and
  `Ctrl+wheel` over the frame itself.
- **The selection really follows the cursor.** A click on a frame block and a cursor move in the
  yaml expand whatever collapsed groups stand in the way and land on the node; the selected node
  keeps the full selection color wherever the focus is - it is shared by the three areas, the
  yaml cursor and the properties panel.
- **An event can be cleared for good.** The event row got its reset, and it asks what to do with
  the method: unbind only, or delete the handler from the module. The deletion takes the method
  with its annotations and the blank line that separated it, and the yaml and the module change
  in a single undo step (the new engine operation `xbsl/removeHandler`).
- **A type's hover carries a description,** not just a link: the sentence from the platform
  documentation on top, the page link under it.
- The reset "x" of the properties panel now sits next to the field in every editor - for color,
  font and long text it used to drift up into the row caption.
- **The palette moved next to the metadata tree** and shows up only while the form panel is open.
  Insertion is a double click on a palette component into the structure selection. Dragging from
  the palette into the panel is gone: the platform does not carry a native tree's drag into a
  webview - which is exactly why insertion became click-driven.
- **Inside the panel dragging works:** a structure node onto another node, and a record from the
  data pane onto a structure node (an attribute becomes an input component with its binding). The
  target rules are unchanged: a container takes the payload inside, a leaf places it after itself.
- **Keyboard and context menu live in the panel:** the arrows walk the tree, `Alt+Up`/`Alt+Down`
  move a component, `F2` renames, `Delete` removes, `Ctrl+C`/`Ctrl+V` carry a yaml fragment. The
  selection still follows the yaml cursor, the form frame and the "Properties" panel.
- The editor title button opens the form designer rather than a preview; the frame itself is the
  same wireframe with its own theme and zoom.
- **The documentation was reshot for the new layout:** the gifs of the old designer are gone,
  replaced by screenshots of the form panel (three areas, the palette as a section under the
  metadata tree), of the cursor following, and of the properties panel with events and reset. The
  designer page gained a "Following the cursor" section (both directions of the link) and an
  "Examples: what it looks like in practice" table, and the platform help got a page of its own -
  "Documentation panel".

## 0.27.1

- **Panels survive an editor restart.** The form preview, the documentation page and the
  templates panel were dropped whenever VS Code restarted and had to be opened by hand again.
  The tab now comes back on its own: the preview remembers the form it was showing and opens its
  document while restoring, the documentation returns to the page you were reading. A panel with
  nothing to show (the form was renamed or deleted) closes instead of lingering empty.
- The extension activates on window startup, so the trees and panels are ready regardless of
  which container was active when you closed the editor.

## 0.27.0

- **The properties panel now also shows what a metadata object does NOT set.** It used to list
  only the keys already written in the yaml, so there was no way to see that a catalog can have
  `Presentation`, `Hierarchical`, `InputByString` or `AccessControl`. It now has the same two
  sections as form components: set on top, every applicable one below.
- **Editors are typed from the platform metamodel:** a tri-state for a flag, a value list for an
  enumeration, a combobox for a data type; the platform default and the version a property
  appeared in are shown. Collections and nested blocks (`Attributes`, `TabularParts`) are listed
  for reference - the metadata tree edits those. Names follow the project's development language.
- The metamodel data was rebuilt: properties gained types, defaults and enumerations, and the
  parse no longer loses members over a string literal holding a comment marker.

## 0.26.1

- **Completion follows the language your project is written in.** The platform keeps both
  spellings of every stdlib member, and after the term dictionary grew the English half started
  showing up interleaved with the Russian one. The server now reads `ЯзыкРазработки`
  (`DevelopmentLanguage`) from the
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
  panel), the `code/undefined-name` rule (name typos, on by default as error), a ~2.3x
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
