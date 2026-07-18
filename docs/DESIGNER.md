# Visual form designer – specification and roadmap

Status: waves 1-3 delivered - stages 0-3 (ui schema, form model and operations,
structure view, palette, properties v2) plus hooks 1-12. The hook backlog is
closed; live-feedback refinements are in the "Refinement backlog" section below.
Russian counterpart: [DESIGNER.ru.md](DESIGNER.ru.md). Keep the two files in sync.

The toolkit grows a visual designer for 1C:Element interface components
(`ВидЭлемента: КомпонентИнтерфейса` – forms, custom components): a structure view,
a component palette and a typed properties panel inside VS Code, on top of the
existing wireframe preview. The designer edits the `.yaml` source; the text editor
remains the primary surface, the designer is a contextual lens over it.

## Why this shape

Research across IDE designers (Flutter Property Editor, Uno Hot Design, Android
Studio Layout Editor, Delphi Object Inspector, Qt Designer, Webflow, Figma; see
"Prior art") converges on one lesson: the durable, well-liked tools in code
editors are NOT free-positioning canvases but the triad "tree + typed properties
+ minimal text edits", with the canvas-style designers (XAML Designer,
storyboards) being the most abandoned – slow, crash-prone, unmergeable diffs.
An Element form is literally a yaml tree of containers, so the winning shape is
also the natural one here.

## Non-goals

- No free-positioning canvas and no pixel-accurate live rendering. Rendering is
  server-side in the platform; the local preview stays an honest wireframe that
  shows structure, not pixels.
- The designer never rewrites or reformats a file wholesale, and never touches
  a file without an explicit user action (opening a form in the designer must
  produce zero diff).
- No new write logic on the TypeScript side. Per the repository architecture
  rule, all model reads and edits are computed by the engine; the extension is
  a thin client that renders trees and applies `WorkspaceEdit`s.

## Clean-room policy

The platform ships its own web-based visual editor. This designer is an
independent reimplementation: the specification is written from the public
platform documentation, from the toolkit's own extracted datasets and from
black-box observation of designer behavior in general-purpose IDEs. Vendor
source code, minified bundles or extracted vendor assets are never read,
decompiled or reused. UI texts, icons and layouts are our own.

## Architecture

```
engine (Python)                        VS Code extension (TypeScript)
---------------                        ------------------------------
ui schema (per-component:              structure view   - native TreeView
  props, types, enums, events,         palette          - native TreeView
  defaults, packages, docs)     -----> properties panel - WebviewView
form model (yaml tree with             wireframe preview (existing)
  node spans) + operations                  |
  insert/move/remove/wrap/set  <----- one operation = one LSP request;
  each returns precise text edits      editor applies WorkspaceEdit
```

- **Engine owns the model.** A new form-model module parses a component's yaml
  into a node tree with source spans (slots included: `Команды`, `Содержимое`,
  `Подвал`, pages, columns) and computes operations as precise text edits –
  the same philosophy as `scaffold.py` (no round-trip serialization; comments,
  key order and formatting survive; diffs read as hand-made). Surfaces, like
  the `meta_*` family: LSP requests for the designer (compute only, dirty
  buffers via the injected reader; the editor applies edits, which keeps native
  undo/redo), MCP tools and CLI subcommands for agents and scripts.
- **Native TreeViews** for structure and palette: theme, keyboard, type-ahead
  filtering, multi-select and drag-and-drop between the two views
  (`TreeDragAndDropController`, shared MIME type) come for free.
- **WebviewView** only where forms are needed: the properties panel (one shared
  properties engine for form components and for metadata objects – it replaces
  both current ad-hoc panels). A shared webview helper (escape, nonce, CSP,
  JSON inlining with `<` escaped) replaces the per-panel copies.
- **Two-way cursor sync** is the spine: cursor in yaml selects the node in the
  structure view and fills the properties panel; selecting a node moves the
  cursor in yaml. The pattern users praise most in Flutter Property Editor.
- **DnD limitation accepted:** the VS Code tree API reports only the drop
  target, not a between-nodes position. Semantics: drop on a container inserts
  as its last child; drop on a leaf inserts after it. Precise ordering is
  keyboard-first (Alt+Up/Down and friends), which research shows is the more
  accurate tool for tree work anyway.

## Stage 0 – foundations (engine)

Two independent tracks.

**Track A – UI schema.** Extend the stdlib extractor to emit, per interface
component: package (`Стд::Интерфейс::*`), since-version, and for every
property: value type union (e.g. `Авто|Булево`, `Авто|Цвет|Url|Ссылка`),
enum values where the type is an enumeration, whether it is an event (with the
handler signature), a short doc snippet and the platform default where the docs
state one. Delivered through the existing versioned dataset mechanism (data
stays generated from the user's own distribution, never bundled). New LSP
request `xbsl/uiSchema` (and an MCP mirror) serves the palette catalog and the
per-component property schema. Graceful degradation without data: structure
view and text edits still work; the palette and typed editors need the dataset.

**Track B – form model and operations.** New engine module: parse a component
yaml into a node tree `{kind, name, type, span, slot, children, properties}`;
resolve a node by source offset; operations `insert_component`,
`move_node`, `remove_node`, `wrap_node` / `unwrap_node`, `duplicate_node`,
`rename_node`, `set_property` / `reset_property` – each returns text edits plus
the new node id/span. Insertion respects slot rules (what the target property
accepts – single component vs list). Exposed as LSP `xbsl/formTree`,
`xbsl/formNodeAt`, `xbsl/formEdit` and as MCP/CLI (`meta_add_component`,
`meta_move_component`, ...) in the same change – agents get the designer's
operations for free. Full pytest coverage; surface-parity tests like
`test_meta_surfaces.py`.

Acceptance (stage 0): round-trip guarantee (apply + revert = byte-identical);
operations on a real project corpus never touch lines outside the reported
edits; parity of the three surfaces.

## Stage 1 – structure view

Native TreeView "Structure" following the active editor:

- Tree = slots and components with icons by kind, badges from linter
  diagnostics on the node (hook 3), type-ahead filtering.
- Two-way selection sync with the yaml editor and the properties panel;
  Ctrl+click reveals the yaml without moving focus.
- Operations: context menu + keyboard – Alt+Up/Down move, wrap in
  Группа/Карточка (submenu of container types), unwrap, duplicate, Del, F2
  rename, cut/copy/paste of subtrees via the clipboard as plain yaml (works
  across forms and projects), multi-select for move/delete.
- DnD inside the tree with invalid targets rejected before the drop.
- "Focus on subtree" (temporary root) and a filter for named elements only.

Acceptance: every operation lands as one undo step; selection sync under
200 ms on a 1000-node form; no file writes without an explicit action.

## Stage 2 – component palette

Native TreeView "Palette", insertion into the current structure selection:

- Sections: Frequent (usage counter, workspace state), Favorites, Project
  (the project's own `КомпонентИнтерфейса` and inserts), then platform
  packages from the ui schema.
- Primary insertion = double click / Enter into the selected container
  (research: faster and more precise than DnD); DnD into the structure view
  as the secondary path.
- Tooltip with the doc snippet; "Open documentation" opens the docs panel
  (hook 4).

Acceptance: insert of any catalog component produces valid yaml that the
linter accepts; unknown-data state degrades to a hint, not an error.

## Stage 3 – properties panel v2

One properties engine (WebviewView) shared by form components and metadata
objects; replaces both current panels.

- "Set" section on top (keys present in yaml), then collapsible groups of all
  applicable properties; search filters by name AND current value.
- Set/default indicator per row + Reset (= delete the key from yaml) – the
  industry's most reinvented pattern (bold in WinForms, blue dot in Hot
  Design, set/default chips in Flutter PE, orange/blue in Webflow).
- Typed editors from the ui schema: enum -> dropdown only; `Авто|Булево` ->
  tri-state; numbers; color (hex + swatch); union types -> "Type + Value"
  pair editor (`Изображение`, `Фон`); nested structures (`Шрифт`) ->
  collapsible sub-groups; multiline strings; binding values (`=...`) shown
  as-is with an "Open in yaml" escape hatch until the binding editor hook.
- Value validation before the write (engine-side), error under the field.
- The selected property row survives switching to another component of the
  same type (serial editing, the Delphi trick).

Acceptance: composite union properties fully editable (the current panel's
main gap); every write is a minimal text edit; validation blocks a write the
linter would flag as an error.

## Hooks backlog (accepted, post-core)

| # | Hook | Size | Wave |
|---|------|------|------|
| 1 | Events in the properties panel: dropdown of existing compatible handlers; "create handler" generates a stub with the right signature into `.xbsl` and jumps to it | M | delivered (3) |
| 2 | "Data" panel: object attributes and component `Свойства:`; dragging an attribute into the tree creates the right input component with the binding | M | delivered (3) |
| 3 | Designer-side validation: linter badges on tree nodes, value checks before writes | S/M | folded into stages 1/3 |
| 4 | Hover docs in the palette and properties, jump to the docs panel | S | folded into stages 2/3 |
| 5 | Wireframe preview upgrades: selection highlight, follow structure selection (a click on a structure node moves the yaml cursor, the preview highlights the node and survives re-renders) | S/M | delivered |
| 6 | Binding editor: literal/binding toggle per property, autocomplete from the form's bindings and the owner object's attributes (via LSP) | M/L | delivered |
| 7 | Color editors with project palette presets (colors already used in the form plus recent picks, as one-click swatches) | S | delivered |
| 8 | Block presets: save a component subtree as a named preset (globalState) and insert it into any form (structure context menu + title button/QuickPick) | M | delivered |
| 9 | Multi-select mass property edit: one property (a key from the union of the selection's own, or a new one) set or cleared on all selected components at once - structure context menu on a multi-selection | S/M | delivered |
| 10 | Structural search across project forms: component type + `key=value` predicates; the `xbsl.forms.search` command (a button on the structure view + the command palette), the `xbsl/searchForms` engine endpoint, results in a quick pick that jumps to the node | M | delivered |
| 11 | Read-only designer view for library forms (`.xlib`): the panels detect a read-only source (a non-file git/diff scheme or a file flagged read-only) - the properties panel shows a banner with disabled editors plus a write backstop, structure edits are refused with a message. Viewing the `.xlib` archive itself (a virtual filesystem) is a separate prerequisite | S/M | delivered |
| 12 | Designer operations for agents via MCP/CLI | S | folded into stage 0 |

## Refinement backlog (from live feedback)

- ~~**The yaml active line misses the highlighted preview block.**~~ FIXED: selecting a node
  landed the yaml cursor on the list dash (`-`) BEFORE the node (`revealOffset` = `contentSpan.start`),
  while the preview keys its block on the `Тип:` line; the cursor sat left of the node's data-off and
  `selectionForCursor` picked the neighbouring block. Fix: `skipToNodeKey` moves the cursor past the
  dash/indent to the node's first key (matching the preview's `map.range[0]`).
- **Group properties by dependency in the properties panel.** Only the slot indicator (bar +
  badge) exists today; grouping dependent fields is not done.
- **Full dotted completion of binding expressions.** Done: enumeration values
  (`=Перечисление.Значение`), owner-object attributes (`=Объект.Реквизит`), bindings already
  used in the form. NOT done: `=Компоненты.<name>` and member chains
  (`=Компоненты.Кнопка.Значение`, type members) - that is a full binding-expression completer in
  the form context (owner object + components + the engine's type system), essentially porting the
  code editor's `chain_type_at` / `resolve_completions` to the binding mini-expressions. A separate
  larger task.

## Delivery plan

Parallel tracks; every stage ships as a normal minor release of the engine and
the extension together.

- Wave 1 (parallel): Track A (ui schema) + Track B (form model) – both engine,
  disjoint modules.
- Wave 2 (parallel, after A/B): structure view; palette; properties v2.
  Hooks 3 and 4 land inside these stages.
- Wave 3 (parallel): hook 1 (events) + hook 2 (data panel) – the two
  strongest RAD habits.
- Wave 4+: remaining hooks by demand.

## Risks

- **Dataset absent** (public install without generated data): palette and
  typed editors degrade; structure view and edits must keep working.
- **Tree DnD API** cannot express "between" positions – mitigated by
  keyboard-first ordering; do not fight the API with a webview tree.
- **Webview state costs**: the properties panel uses `getState`/`setState`,
  not `retainContextWhenHidden`.
- **Large forms**: tree building and node resolution must be incremental
  (reuse the LSP parse of the open buffer, debounce selection sync).
- **Two panels era**: until stage 3 replaces the metadata properties panel,
  the two coexist; do not grow features in the old one.

## Prior art (patterns adopted)

- Flutter Property Editor – cursor-driven selection, set/default chips,
  name+value search: https://docs.flutter.dev/tools/property-editor
- Uno Platform Hot Design – Smart/All properties, toolbox categories,
  double-click insertion: https://platform.uno/docs/articles/studio/Hot%20Design/hot-design-overview.html
- Android Studio Layout Editor – Declared Attributes, component tree badges,
  palette search: https://developer.android.com/studio/views/layout-editor
- Delphi Object Inspector – events workflow, sticky property selection:
  https://docwiki.embarcadero.com/RADStudio/Sydney/en/Setting_Properties_and_Events
- Dart Code wrap/remove refactorings (keyboard tree surgery):
  https://dartcode.org/docs/refactorings-and-code-fixes/
- Webflow Navigator / style labels – DnD expectations, override indicators:
  https://university.webflow.com/lesson/navigator
- VS Code APIs: [Tree View](https://code.visualstudio.com/api/guides/tree-view) and
  [Webview](https://code.visualstudio.com/api/extension-guides/webview)
