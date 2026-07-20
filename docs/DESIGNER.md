---
title: "Visual form designer"
description: "The in-editor visual designer for 1C:Element interface components — structure, palette, properties, and binding panels over the .yaml source."
sidebar:
  label: Visual designer
  order: 4
---

The extension includes a visual designer for 1C:Element interface components
(`ВидЭлемента: КомпонентИнтерфейса` – forms and custom components). It is a set of panels
over the `.yaml` source: a structure tree, a component palette, a data panel, a typed
properties panel and a wireframe preview. The text editor stays the primary surface; the
designer is a contextual lens over it.

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

Open a `.yaml` of an interface component (a form or a custom `КомпонентИнтерфейса`). Three
activity-bar containers hold the panels, and all follow the active editor:

- **Designer (1C:Element)** – the **Structure**, **Palette** and **Data** panels.
- **Properties (1C:Element)** – the **Properties** panel.
- **Documentation (1C:Element)** – the **Documentation** panel.

For the wireframe, use the **form preview** button (the preview icon in the editor title bar,
shown when a form yaml is active) or **Form preview** from the metadata tree's context menu.

## Structure panel

The **Structure** panel is the form as a tree of slots (`Содержимое`, `Команды`, pages,
columns, ...) and components, with an icon per kind and linter badges on nodes.

- **Cursor sync.** Put the cursor on a node in the yaml – it highlights in the tree and fills
  the Properties panel. Select a node in the tree – the cursor moves to its yaml (**Go to
  yaml** in the context menu, or a click).
- **Arrange** (context menu + keys): **Move up / Move down** (`Alt+Up` / `Alt+Down`), **Wrap in
  a container** (pick the container type), **Unwrap container**, **Duplicate**, **Rename (Имя)**
  (`F2`), **Delete component** (`Delete`).
- **Copy / paste as yaml.** **Copy yaml fragment** (`Ctrl+C`) and **Paste yaml from the
  clipboard** (`Ctrl+V`) move subtrees – across forms and across projects.
- **Multi-select.** Select several components and use **Edit selected together...** to set or
  clear one property on all of them at once.
- **Focus and filter.** **Focus on this subtree** narrows the tree to one branch (**Show the
  whole form** restores it); the title-bar filter toggles **Show only named components** /
  **Show all components**.
- **Drag-and-drop** inside the tree: dropping on a container inserts as its last child,
  dropping on a leaf inserts after it (invalid targets are rejected before the drop). For exact
  ordering use `Alt+Up` / `Alt+Down`.

## Palette panel

The **Palette** lists components you can insert into the current structure selection, in
sections: **Frequent**, **Favorites**, **Project** (your own components and inserts), then the
platform packages from the ui schema.

- **Insert** by double-clicking (or `Enter`) a palette entry while a container is selected in
  the Structure panel; or **Insert into the form** from the context menu; or drag the entry
  into the Structure tree.
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
- **Typed editors** from the ui schema: enumerations as a dropdown; `Авто|Булево` as a
  tri-state; numbers; color (hex plus a swatch, with one-click presets from the form's own
  colors and your recent picks); union types as a **Type + Value** pair (`Изображение`, `Фон`);
  nested structures (`Шрифт`) as sub-groups; multiline strings.
- **Bindings.** A per-property toggle switches a value between a literal and a binding (`=...`).
  Binding completion offers enumeration values (`=Перечисление.Значение`), owner-object
  attributes (`=Объект.Реквизит`), components and their members (`=Компоненты.Кнопка.Значение`)
  and bindings already used in the form.
- **Events.** An event property offers a dropdown of the module's compatible handlers;
  "create handler" writes a stub with the right signature into the `.xbsl` and jumps to it.
- **Slot indicator.** A property that is a child slot is marked with a bar and a badge.
- **Serial editing.** The selected property row survives switching to another component of the
  same type, so you can walk a set of similar components changing one field.
- Values are validated before the write; an invalid value is reported under the field instead
  of being written.

## Data panel

The **Data** panel binds form inputs to data. It has two sections: the owner object's
attributes, and the component's own `Свойства:`.

- **Manage component properties**: **Add property**, **Rename property**, **Change property
  type**, **Remove property**.
- **Bind an input**: drag an attribute (or a property) into the Structure tree, or use **Insert
  into the form** – the designer creates the right input component already bound (`Булево` –>
  a checkbox, otherwise an input field with `Значение: =...`).

## Documentation panel

The **Documentation (1C:Element)** container is a searchable tree of the platform's own
documentation, built from your 1C:Element distribution. **Search the documentation** (the search
button on its title bar) finds pages by name; **Documentation for the symbol** (the editor's
right-click menu on a type or a variable) and the **Open documentation** action in the palette
and the properties panel open the matching page here – this is where the designer answers "what
is this component or property".

## Wireframe preview

The preview is an honest wireframe of the form's structure. It highlights the selected
component and follows the Structure selection; a `Картинка` with `Изображение: file.svg` shows
the actual image (resource images are resolved against `**/Ресурсы/`); a narrow panel scrolls
horizontally to the line content.

## Structural search

**Search forms by structure** (the search button on the Structure panel's title bar, or the
command palette) finds components across the project's forms by type plus `key=value`
predicates; results open in a quick pick that jumps to the node.

## Block presets

**Save as block preset** stores a component subtree under a name; **Insert block preset...**
drops it into any form (from the Structure title bar or a node's context menu), and **Manage
block presets...** renames or removes them. Presets are per-user.

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
