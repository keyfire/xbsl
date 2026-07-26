---
title: "Documentation panel"
description: "The 1C:Element help inside the editor: the contents tree, full-text search, the page for the symbol under the cursor and the jumps from the designer - all built from your own platform distribution."
sidebar:
  label: Documentation panel
  order: 7
---

The extension shows the platform help **inside the editor** - as its own
**Documentation (1C:Element)** container in the activity bar. It is the same reference as on the
documentation site, but built from **your own 1C:Element distribution**: it matches the platform
version you actually use and works offline.

![The documentation panel: the Contents tree on the left with the Std::Collections section expanded, the Array type page on the right with code samples and the Primary source link](https://raw.githubusercontent.com/keyfire/xbsl/main/editors/vscode/images/docs-panel.png)

## What is inside

- **The "Contents" tree** - a curated table of contents matching the site: the developer guide,
  the administrator guide, the language types (`Std`, `Std::Collections` → `Array`, ...) and the
  query language. Sections inside a page (`Type hierarchy`, `Examples`, `Literals`) are nested
  under its node, so a click lands on the right spot straight away.
- **The page** opens as an editor tab beside the current one and **does not steal the focus**:
  the article's code, tables and images, a **Copy** button on samples, and a **Primary source**
  link to the same page on the site. Internal links open other pages in the same tab, and the
  "Contents" tree follows the page you open.
- **Search** (the button in the tree header, the *XBSL: search the documentation* command) is
  full-text across the whole reference and both guides; picking a hit opens the page.

## How you get here

The panel is the single "what is this thing" answer for the whole extension:

| From | What happens |
| --- | --- |
| Hovering a name in `.xbsl` | the hover shows the type description and a **Documentation** link - a click opens the page |
| Editor context menu, *XBSL: documentation for symbol* | the page of the type under the cursor; for a method or an ambiguous name - a list of candidates |
| The designer **Palette**, *Open documentation* | the page of the component you are about to insert (a short description also rides in the palette item's tooltip) |
| The "Contents" tree and search | plain navigation through the reference |

For an ambiguous name the candidates are **ranked by the receiver before the dot**:
`ScheduledJob.Configure` prefers the scheduled job pages over a guide topic of the same name.

## What you need

- **LSP mode** (`pip install "xbsl[lsp]"`): the server holds the documentation database, the
  extension only asks and displays.
- **The documentation dataset** built from your 1C:Element distribution - see
  [Language data](/GUIDE#language-data).

Without the data the panel does not fail - it reports that the documentation is unavailable, and
the rest of the extension keeps working.

## For scripts and agents

The same reference is available outside the editor:

- **MCP** - `docs_search` (full-text search), `docs_page` (an article by id), `docs_symbol` (the
  page for a type or member name). This is how an AI agent verifies the platform API without
  going online.
- **LSP** - the `xbsl/docsAvailable`, `xbsl/docsSearch`, `xbsl/docsPage`, `xbsl/docsTree` and
  `xbsl/hoverDoc` requests: any LSP-capable editor can build its own panel on top of them.

## Related

- [Visual form designer](/DESIGNER) - the palette and the properties panel that link here.
- [VS Code extension](/vscode) - everything else the extension does.
