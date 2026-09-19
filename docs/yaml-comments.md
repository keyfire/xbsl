---
title: "Comments in yaml"
description: "Where a note in an element description survives the visual editor, how to write it and what checks it."
sidebar:
  label: Comments in yaml
  order: 6.7
---

The 1C:Element development environment keeps an element description as a model. When you edit
the file in the visual editor, it writes the yaml again from that model. The only comments the
model keeps are documentation ones: `##` lines where the model has a field for a description. A
plain `#` and `##` lines in the wrong place are lost on the first such edit.

## Where a note has a place

- **The first lines of the file.** They describe the element itself: an interface component, a
  common module, an HTTP service, a catalog, an enumeration.
- **The first lines of a component node, before `Type:`.** This is how `Inherits:` and nested
  nodes are described.
- **The first line of a list item after the `-`**, when the model describes such records: the
  properties of a component in `Properties:`, the URL templates of an HTTP service in
  `UrlTemplates:` and the tabular parts of a catalog in `TabularParts:`.

There is no place on the items of `Attributes:` of a catalog, on the items of `Methods:` of a URL
template, and on a single property of a node. On an instance of a project or a library component
in a list a comment does harm: with it the server does not apply the project, because producing
the metadata of the instance fails. A note about such a node goes into the comment of the group
it stands in.

## How to write one

The marker is `## `, and the text is Markdown: bold and italics, headings, a quote, nested lists,
a link, a picture. Every `##` line is shown as a line of its own, and an empty `##` line
separates paragraphs.

```yaml
## The order panel: the recipient and the order lines.
ElementKind: InterfaceComponent
Id: 6f0b6a44-0000-4000-8000-000000000101
Name: OrderPanel
Inherits:
    ## The order form in two columns.
    Type: ObjectForm<Orders.Object>
    Content:
        -
            ## A hint above the input fields.
            Type: Label
            Name: Hint
```

In a `.xbsl` module the development environment reads the description above a declaration from
`///` lines. It does not show a `//` block or a `/* ... */` block in the same place in its hints.

## What checks it

- `yaml/plain-comment` finds every `#` in an element description. When the place for a note is
  near, its autofix changes the marker or moves the block inside the node.
- `yaml/doc-comment-misplaced` finds a `##` block where the development environment does not read
  it.
- `comment/doc-marker` finds a `//` block right above a declaration in a module and changes the
  marker to `///`.

All three rules are off by default and are turned on with `--enable`. In a project written before
the visual editor was in the picture they fire on almost every node.

Pasting a fragment places its notes by the same rules. This is what the MCP tool
`meta_insert_fragment` and the `insert-fragment` operation of `xbsl form-edit` do. A comment above
the component moves inside the node as `##` lines. A note with no place of its own stays as it
is, and the answer names it in the notes. Without the Element data the places are unknown: the
notes stay as pasted, and the answer says so.
