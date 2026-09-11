---
title: "Documentation panel"
description: "The 1C:Element help inside the editor: the contents tree, full-text search, the page for the symbol under the cursor and the jumps from the designer - all built from your own platform distribution."
sidebar:
  label: Documentation panel
  order: 9
---

The extension shows the platform help **inside the editor** - as its own
**Documentation (1C:Element)** container in the activity bar. It is the same reference as on the
documentation site, but built from **your own 1C:Element distribution**: it matches the platform
version you actually use and works offline.

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
| Hovering a name in `.xbsl` | the hover shows the description and a **Documentation** link - a click opens the page; over a MEMBER of a type it is that member's own block (its signature and what the call does), and the link opens the page at it |
| Editor context menu, *XBSL: documentation for symbol* | the page of the type under the cursor, a member's page scrolled to the member; for a name several types declare - those types to choose from |
| The designer **Palette**, *Open documentation* | the page of the component you are about to insert (a short description also rides in the palette item's tooltip) |
| The "Contents" tree and search | plain navigation through the reference |

A member is documented where it is DECLARED: `Array.Size` opens the page of the ancestor that
declares it, not the page of the heir that says nothing about it. When several unrelated types
declare the same name, the choice is offered as those types, each with that member's block as
the line under it; for everything else with no page of its own the candidates are **ranked by
the receiver before the dot**: `ScheduledJob.Configure` prefers the scheduled job pages over a
guide topic of the same name.

## What you need

- **LSP mode** (`pip install "xbsl[lsp]"`): the server holds the documentation database, the
  extension only asks and displays.
- **The documentation dataset** built from your 1C:Element distribution - see
  [Language data](/start#language-data).

Without the data the panel does not fail - it reports that the documentation is unavailable, and
the rest of the extension keeps working.

## For scripts and agents

The same reference is available outside the editor:

- **MCP** - `docs_search` (full-text search), `docs_page` (an article by id), `docs_symbol` (the
  documentation of a type or of a MEMBER of one - a member has no page of its own and answers
  with its own block of the type's page); the two page tools also answer briefly (`brief` – the
  summary and the section names) or with one section (`section`) when the whole article is more
  than the question needs. This is how an AI agent verifies the platform API without going
  online.
- **LSP** - the `xbsl/docsAvailable`, `xbsl/docsSearch`, `xbsl/docsPage`, `xbsl/docsTree`,
  `xbsl/docsForSymbol` and `xbsl/hoverDoc` requests: any LSP-capable editor can build its own
  panel on top of them. The last two answer a member the way `docs_symbol` does - the page of
  the declaring type plus the member's name and the id of its heading.

## Related

- [Visual form designer](/DESIGNER) - the palette and the properties panel that link here.
- [VS Code extension](/vscode) - everything else the extension does.
