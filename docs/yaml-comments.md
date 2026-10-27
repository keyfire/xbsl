---
title: "Comments in yaml"
description: "Which comments the visual editor retains, how to write them and how to check them."
sidebar:
  label: Comments in yaml
  order: 6.7
---

The 1C:Element development environment stores an element description in a model. When a file is
edited in the visual editor, the yaml is written again from that model. Documentation comments
marked `##` are retained where the model has a description field. Plain `#` comments and `##`
lines in other locations are removed when the file is written.

## Where a note has a place

- **The first lines of the file.** They describe the element itself: an interface component, a
  common module, an HTTP service, a catalog, an enumeration.
- **The first lines of a component node, before `Type:`.** This is how `Inherits:` and nested
  nodes are described.
- **The first line of a list item after the `-`**, when the model describes such records: the
  properties of a component in `Properties:`, the URL templates of an HTTP service in
  `UrlTemplates:`, the attributes and the tabular parts of a catalog in `Attributes:` and
  `TabularParts:`.

Description fields are unavailable for standard catalog attributes selected by name (`Code`,
`Name`), items in a URL template's `Methods:`, and individual node properties. A comment on a
project or library component instance in a list causes an error when building its metadata, so
the server does not apply the project. Put a note about such a node in the containing group's
comment.

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

The MCP tool `meta_insert_fragment` and the `insert-fragment` operation of `xbsl form-edit` apply
the same rules when inserting a fragment. A comment above a component is moved inside the node as
`##` lines. A note without a description field remains in place and is listed in the response
notes. Without the Element data, description locations cannot be determined: notes remain as
inserted and the response reports this.

## Folding notes that have no place

A note with no place of its own next to it is moved by `xbsl fold-comments`. It is a note about a
property of a component, an item of a list without a description, a key of the element. The
command gathers such blocks into the description of the nearest node that has a place, as an item
of a list named after the subject:

```yaml
Inherits:
    ## * `Visible`:
    ##   The group is always visible.
    Type: Group
```

The name of the subject stands on a line of its own, so the lines of the note keep their text
and their pairs in the translation dictionary. The new lines with the names need pairs of their
own, and `xbsl translate --gaps` shows them.

By default the command only shows the plan and the diff; `--write` writes. A move that may be
read two ways is proposed, not applied: the first block of the file above a key outside the head
(it may describe the element or only that key), the heading of a section, a block in a
localization file, an item of a list without a name, a block above a list. `--all` applies them
too. A note at the end of the file is left in place because it cannot be assigned to a node unambiguously.

A file is written only when the result passes the audit. The yaml parses to the same data, every
line of every comment is still there, the comment rules find nothing but the blocks left on
purpose, and a second pass has nothing to move. The byte order mark and the line ends of the file
are kept.

An agent gets the same through the MCP tool `meta_fold_comments`. It answers with the report of
`--format json` and writes nothing by default: `dry_run=false` writes, and `take_proposed`
applies the ambiguous moves. The report names every move, and over a whole tree it runs to
hundreds of kilobytes; `compact=true` answers with the counts, the files with the most moves and
the moves worth a look, and lists every file the audit stopped.
