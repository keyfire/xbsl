---
title: "Visual form designer"
description: "The in-editor visual designer for 1C:Element interface components - a form panel with structure, data and the form frame, plus the palette and properties panels over the .yaml source."
sidebar:
  label: Visual designer
  order: 4
---

The extension includes a visual designer for 1C:Element interface components
(`ElementKind: InterfaceComponent` - forms and custom components). The main workplace is the
**form panel**: the structure tree on the left, the form's data on the right, the form frame
under them. Next to it live the component palette in the sidebar and the typed properties panel.
The text editor stays the primary surface; the designer is a contextual lens over it.

![The form panel: structure on the left, data on the right, the form frame under them; the component palette is a section under the metadata tree](https://raw.githubusercontent.com/keyfire/xbsl/main/editors/vscode/images/form-designer.png)

Two things to keep in mind:

- **Every action is a minimal text edit.** The designer never rewrites or reformats the
  whole file; comments, key order and formatting survive, and each operation is a single
  undo step. Opening a form in the designer changes nothing until you act.
- **The preview is a wireframe, not a render.** Rendering is server-side in the platform;
  the local preview shows structure and layout, not pixels.

## What you need

- The **panels and text edits work anywhere.** Selecting nodes, moving and wrapping
  components, copy/paste and the wireframe all rely only on the yaml.
- The **palette and the typed property editors need the language dataset** (the ui schema,
  generated from your own 1C:Element distribution – see [Language data](/GUIDE#language-data))
  and the **LSP server** (`pip install "xbsl[lsp]"`). Without them the structure tree and edits
  still work; the palette and typed editors degrade to a hint instead of failing.

## Opening the designer

Open a `.yaml` of an interface component (a form or a custom `InterfaceComponent`) and press the
**form designer** button in the editor title bar (shown when a form yaml is active), or **Open in
the form designer** from the metadata tree's context menu. The form panel opens; while it is
open, the **Palette** shows up next to the metadata tree.

The remaining panels live in activity-bar containers and follow the active editor:

- **1C:Element** – the metadata tree and the **Palette** (the latter only while the form panel is open).
- **Properties (1C:Element)** – the **Properties** panel.
- **Documentation (1C:Element)** – the **Documentation** panel.

## The form panel

**Every form gets a panel of its own**, living as a normal editor tab: a second form opens next to
the first, each panel keeps its own tree, selection and expansion memory, and opening the same form
again brings its panel forward. A panel and its `.yaml` travel as a pair - picking a tab on one
side brings the other forward, closing the panel closes the form's yaml (unless it has unsaved
changes), and a new yaml joins the group where the sources already are.

The panel is three areas with draggable splitters (their position is remembered):

| Left | Right |
| --- | --- |
| **Structure** – the tree of slots and components | **Data** – component properties and object attributes |
| **The form frame** – a full-width wireframe under both ||

A form depends on its own properties, so its structure and its data are edited where the form is
shown; the Properties panel stays separate and follows the selection.

### Structure

The form as a tree of slots (`Content`, `Commands`, pages, columns, ...) and components, with an
icon per kind and linter badges on nodes.

- **Cursor sync.** The node under the yaml cursor lights up in the tree and in the frame, and
  selecting a node in the tree moves the cursor to its yaml – see
  [Following the cursor](#following-the-cursor).
- **Undo.** `Ctrl+Z` / `Ctrl+Y` work right in the panel: every designer operation is one undo step
  of the yaml document.
- **Arrange** (context menu + keys): **Move up / Move down** (`Alt+Up` / `Alt+Down`), **Wrap in
  a container** (pick the container type), **Unwrap container**, **Duplicate**, **Rename**
  (`F2`), **Delete component** (`Delete`).
- **Copy / paste as yaml.** **Copy yaml fragment** (`Ctrl+C`) and **Paste yaml from the
  clipboard** (`Ctrl+V`) move subtrees – across forms and across projects.
- **Multi-select** (`Ctrl`/`Shift` click): use **Edit selected together...** to set or clear one
  property on all of them at once.
- **Focus and filter.** **Focus on this subtree** narrows the tree to one branch (the button in
  the area header restores the whole form); the filter button toggles showing only named
  components.
- **Drag-and-drop** inside the area: dropping on a container inserts as its last child, dropping
  on a leaf inserts after it (invalid targets are rejected before the drop). For exact ordering
  use `Alt+Up` / `Alt+Down`.

### Data

The **Data** area binds input components to data. It has two sections: the component's own
`Properties:` and the attributes of the owner object.

- **Component properties**: **Add property** (the button in the area header), **Rename property**
  (`F2`), **Change property type**, **Remove property** (`Delete`).
- **Bind an input component**: drag an attribute (or a property) onto a node in the Structure
  area, or double click it – the designer creates the right input component with the binding
  already in place (`Boolean` -> a checkbox, otherwise an input with `Value: =...`).

### The form frame

The frame is an honest wireframe of the form structure, not a render. It highlights the selected
component and follows both the structure selection and the yaml cursor; a click on a block selects
the component, `Ctrl+click` jumps to its yaml. An `Image` component with `Image: file.svg` shows
the picture itself (resource images are resolved under `**/Resources/`). The area header carries
the frame theme (light, dark, editor) and the zoom - the buttons, the wheel over the control, or
`Ctrl+wheel` over the frame.

## Following the cursor

The text and the panels show ONE place of the form. The yaml cursor, the structure node, the
frame block and the contents of the properties panel are tied together both ways, so you can
switch between "type it" and "click it" at every step without hunting for the node again.

![The cursor sits on the Description field in the yaml – the same node is selected in the structure and highlighted in the form frame](https://raw.githubusercontent.com/keyfire/xbsl/main/editors/vscode/images/form-cursor.png)

**From the yaml cursor to the panels.** Put the cursor inside a node (or just walk the file with
the arrow keys):

- the **frame** highlights that component's block;
- the **structure** selects the node's row, expanding the collapsed groups on the way from the
  root – nothing to hunt for;
- the **properties panel** fills with the node under the cursor (while it is open);
- the focus stays in the editor: the follow is visual and never interrupts typing.

**From the panels to the yaml.**

| Action | What happens |
| --- | --- |
| Click a structure node | the cursor lands on the node's first property line, the focus stays in the panel |
| Double click a node | the same plus the focus moves to the yaml editor |
| Click a frame block | the component is selected: the structure row, the properties panel, the yaml cursor |
| `Ctrl+click` a frame block | jumps to that block's yaml |
| *Show in yaml* in the properties panel | jumps to the property's line |

The selected node is shared by the three areas and keeps its **full color wherever the focus
is** – losing focus (going to the palette, say) still leaves you looking at what you work on.

The same following covers metadata: the properties panel follows the cursor in an object's yaml
(`Catalog`, `Document`, ...), and the metadata tree reveals the element of the active editor.

## Palette panel

The **Palette** sits next to the metadata tree and shows up while the form panel is open. It
lists components you can insert into the current structure selection, in sections: **Frequent**,
**Favorites**, **Project** (your own components and inserts), then the platform packages from the
ui schema.

- **Insert** by double-clicking (or pressing `Enter` twice) a palette entry while a container is
  selected in the Structure area; or **Insert into the form** from the context menu.
- **A palette entry cannot be dragged into the form panel** – the platform does not carry a drag
  from its own tree into a webview. That is why insertion is click-driven; dragging works inside
  the panel itself.
- **Add to favorites** / **Remove from favorites** (the star) pins the components you use most.
- **Open documentation** opens the component's page in the Documentation panel; the tooltip
  carries a short doc snippet.

## Properties panel

The **Properties** panel edits the selected component (and, from the metadata tree's
**Properties**, metadata objects too – it is one shared panel).

![The properties panel of a button: the "Set" section, the "Events" section with the OnClick handler picked, the jump and reset buttons](https://raw.githubusercontent.com/keyfire/xbsl/main/editors/vscode/images/form-props.png)

- **Set on top, all below.** The **Set** section lists the keys present in the yaml; below it,
  collapsible groups hold every applicable property. Search filters by property name *and* by
  current value. A filled dot marks a value set in the yaml, a hollow dot the default;
  **Reset** deletes the key.
- **Typed editors** from the ui schema: enumerations as a dropdown; an `Auto|Boolean` union as a
  tri-state; numbers; color (hex plus a swatch, with one-click presets from the form's own
  colors and your recent picks); union types as a **Type + Value** pair (`Image`, `Background`);
  nested structures (`Font`) as sub-groups; multiline strings.
- **Bindings.** A per-property toggle switches a value between a literal and a binding (`=...`).
  Binding completion offers enumeration values (`=Enum.Value`), owner-object attributes
  (`=Object.Attribute`), components and their members (`=Components.Button.Value`)
  and bindings already used in the form.
- **Events.** An event property offers a dropdown of the module's compatible handlers;
  "create handler" writes a stub with the right signature into the `.xbsl` and jumps to it.
  Resetting an event asks what to do with the method - unbind only, or delete the handler from the
  module; the deletion takes the method with its annotations, and the yaml and the module change
  in one undo step.
- **Metadata objects, the same way.** For a selected object (`Catalog`, `Document`, `HttpService`,
  ...) the applicable properties come from the platform metamodel, so the **All properties**
  section also shows what the file does not set yet: `Presentation`, `Hierarchical`,
  `InputByString`, `AccessControl`. The editors are typed - a tri-state for a flag, a value list
  for an enumeration, a combobox for a data type; collections and nested blocks (`Attributes`,
  `TabularParts`) are listed for reference and edited in the metadata tree.
- **Collection items too.** An attribute, a dimension, a resource, a structure field, an attribute
  of a tabular part, a value of an enumeration, a parameter - each gets its own **All properties**
  section: the metamodel names the item class itself, and where a collection holds items of
  different classes it picks one by the name (the built-in `Code`, `Name` and `Owner` of a catalog
  are classes of their own with their own properties - `Code` has `Length`, `Uniqueness`,
  `AutoNumbering`). Without generated data, and for a nested block that is not a collection item,
  the panel stays the flat list of set properties it has always been.
- **Slot indicator.** A property that is a child slot is marked with a bar and a badge.
- **Serial editing.** The selected property row survives switching to another component of the
  same type, so you can walk a set of similar components changing one field.
- Values are validated before the write; an invalid value is reported under the field instead
  of being written.

## Documentation panel

The **Documentation (1C:Element)** container holds the platform help built from your 1C:Element
distribution. This is where the designer answers "what is this component": the **Open
documentation** action on a palette item opens the page right here, without leaving the editor.
In detail - [Documentation panel](/DOCS_PANEL).

## Structural search

**Search forms by structure** (the search button on the Palette panel's title bar, or the
command palette) finds components across the project's forms by type plus `key=value`
predicates; results open in a quick pick that jumps to the node.

## Block presets

**Save as block preset** stores a component subtree under a name; **Insert block preset...**
drops it into any form (from the Palette title bar or a structure node's context menu), and
**Manage block presets...** renames or removes them. Presets are per-user.

## Read-only forms

For a read-only source – a library form from an `.xlib`, a git/diff view, or a file flagged
read-only – the panels show a banner and disable the editors, and structure edits are refused
with a message, so browsing such a form never risks a stray write.

## Examples: what it looks like in practice

Short scenarios - from the task to the action. Each of them writes a minimal edit into the yaml
(or into the paired `.xbsl`) and rolls back with a single `Ctrl+Z`.

| Task | How |
| --- | --- |
| Put an object attribute on the form | In the **Data** area double click the attribute (or drag it onto a structure node): you get a `Checkbox` for `Boolean` and an `Input` with `Value: =Object.Attribute` for the rest |
| Add a component that is not there yet | Select a container in the structure and double click the component in the **Palette**; for an unfamiliar component start with **Open documentation** |
| Reorder fields | Select a node and press `Alt+Up` / `Alt+Down` - the yaml order changes line by line |
| Lay two fields out in a row | Select them (`Ctrl`-click), **Wrap in a container** → `Group`, then set `Layout: Horizontal` on the group |
| Attach a handler to a button | Select the button and pick **create handler** on the `OnClick` event: a stub with the right signature is written into the form module and the editor jumps to it |
| Drop a handler together with its method | Reset (`✕`) on the event asks whether to unbind or to delete the method from the module; the deletion takes its annotations too, and the yaml and the module change in one undo step |
| Align a dozen fields at once | Multi-select in the structure → **Edit selected together...** → the key (say `StretchHorizontally`) and the value for all of them |
| Move a block into another form | **Copy yaml fragment** (`Ctrl+C`) on the node, **Paste yaml from the clipboard** (`Ctrl+V`) in the other form; save a layout you rebuild often as a **block preset** |
| Find every table with a fixed height | **Search forms by structure**: type `Table` plus the `Height=200` predicate |
| Find your way around someone else's big form | Walk the yaml with the cursor - the structure and the frame follow; **Focus on this subtree** narrows the tree to one branch, the filter leaves only named components |
| Look at a library form | Open its yaml from the `.xlib`: the panels show the read-only banner and refuse edits |

## Scripting (agents, CLI, MCP)

The same operations are available outside the UI: the CLI (`xbsl form-tree`, `xbsl form-edit`),
the MCP tools (`meta_component_tree`, `meta_add_component`, `meta_move_component`, ...) and the
LSP requests (`xbsl/formTree`, `xbsl/formNodeAt`, `xbsl/formEdit`). See the
[Guide](/GUIDE#metadata-scaffolding).

## Provenance

The platform ships its own web-based visual editor; this designer is an independent
reimplementation written from the public platform documentation, the toolkit's own extracted
datasets and black-box observation of designers in general-purpose IDEs. UI texts, icons and
layouts are our own. See [NOTICE](https://github.com/keyfire/xbsl/blob/main/NOTICE).
