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

- **Cursor sync.** Put the cursor on a node in the yaml – it highlights in the tree and in the
  frame and fills the Properties panel. Select a node in the tree – the cursor moves to its yaml;
  a double click moves the focus there too.
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
the frame theme (light, dark, editor) and the zoom.

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
- **Metadata objects, the same way.** For a selected object (`Catalog`, `Document`, `HttpService`,
  ...) the applicable properties come from the platform metamodel, so the **All properties**
  section also shows what the file does not set yet: `Presentation`, `Hierarchical`,
  `InputByString`, `AccessControl`. The editors are typed - a tri-state for a flag, a value list
  for an enumeration, a combobox for a data type; collections and nested blocks (`Attributes`,
  `TabularParts`) are listed for reference and edited in the metadata tree. For a field of an
  object, for a kind outside the metamodel and without generated data the panel stays the flat
  list of set properties it has always been.
- **Slot indicator.** A property that is a child slot is marked with a bar and a badge.
- **Serial editing.** The selected property row survives switching to another component of the
  same type, so you can walk a set of similar components changing one field.
- Values are validated before the write; an invalid value is reported under the field instead
  of being written.

## Documentation panel

The **Documentation (1C:Element)** container is a searchable tree of the platform's own
documentation, built from your 1C:Element distribution. **Search the documentation** (the search
button on its title bar) finds pages by name; **Documentation for the symbol** (the editor's
right-click menu on a type or a variable) and the **Open documentation** action in the palette
and the properties panel open the matching page here – this is where the designer answers "what
is this component or property".

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
