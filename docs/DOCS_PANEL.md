---
title: "Documentation panel"
description: "The 1C:Element help inside the editor: the contents tree, full-text search, the page for the symbol under the cursor and the jumps from the designer - all built from your own platform distribution."
sidebar:
  label: Documentation panel
  order: 9
---

The extension shows the platform help **inside the editor**, in its own
**Documentation (1C:Element)** container in the activity bar. It is the same reference as on the
documentation site, only built from **your own 1C:Element distribution**. So it matches the
platform version you actually run, and it works offline.

## What is inside

- **The "Contents" tree** - a hand-curated table of contents that matches the site: the
  developer guide, the administrator guide, the language types (`Std`, `Std::Collections` →
  `Array`, ...) and the query language. Sections inside a page (`Type hierarchy`, `Examples`,
  `Literals`) sit under its node, so a click lands on the right spot straight away.
- **The page** opens as an editor tab beside the current one and **does not steal the focus**.
  It carries the article's code, tables and images, a **Copy** button on samples, and a
  **Primary source** link to the same page on the site. Internal links open other pages in the
  same tab, and the "Contents" tree follows the page you open.
- **Search** sits behind the button in the tree header and behind the *XBSL: search the
  documentation* command. It is full-text across the whole reference and both guides, and
  picking a hit opens the page.

## How you get here

One panel answers "what is this thing" for the whole extension:

| From | What happens |
| --- | --- |
| Hovering a name in `.xbsl` | the hover shows the description and a **Documentation** link, and clicking it opens the page. Over a member of a type the hover shows that member's own block: its signature and what the call does. The link then opens the page at that member |
| Editor context menu, *XBSL: documentation for symbol* | the page of the type under the cursor. For a member, that page scrolled to the member. For a name several types declare, those types to choose from |
| The designer **Palette**, *Open documentation* | the page of the component you are about to insert. A short description also shows in the palette item's tooltip |
| The "Contents" tree and search | plain navigation through the reference |

A member is documented where it is declared. `Array.Size` opens the page of the ancestor that
declares it; the heir's page says nothing about it. When several unrelated types declare the same
name, those types are offered as the choice, each with that member's block as the line under it.
For everything else with no page of its own, the candidates are **ranked by the receiver before
the dot**: `ScheduledJob.Configure` prefers the scheduled-job pages over a guide topic of the same
name.

A name the project declares is never explained by a platform member of the same spelling. The
project and the platform share a lot of words: a module of your own has a `Write` as readily as
the platform does. The main hover answers such a name with the project's own card - the method,
its signature, the file it lives in. The documentation block used to be added under that card, so
the reader got a platform member with no connection to the method in front of him. The project
index itself keeps that out. There is no second list of what counts as a project name: whatever
the hover answers with - an object, a method of the module, a component of the form, a tabular
section, a value of an enumeration - is the project's answer, and the block stays out of it. The
panel still offers a search over that word. The word may genuinely have a page; that page is
simply not the answer to "what is this name here".

## What you need

- **LSP mode** (`pip install "xbsl[lsp]"`): the server holds the documentation database, and the
  extension only asks and displays.
- **The documentation dataset** built from your 1C:Element distribution - see
  [Language data](/start#language-data).

Without the data the panel does not fail. It reports that the documentation is unavailable, and
the rest of the extension keeps working.

## For scripts and agents

The same reference is available outside the editor:

- **MCP** - `docs_search` for full-text search, `docs_page` for an article by id, and
  `docs_symbol` for the documentation of a type or of one of its members. A member has no page of
  its own, so it answers with its own block of the type's page. Both page tools can also answer
  briefly (`brief` gives the summary and the section names) or with one section (`section`), for
  when the whole article is more than the question needs. This is how an AI agent verifies the
  platform API without going online.
- **LSP** - the `xbsl/docsAvailable`, `xbsl/docsSearch`, `xbsl/docsPage`, `xbsl/docsTree`,
  `xbsl/docsForSymbol` and `xbsl/hoverDoc` requests. Any LSP-capable editor can build its own
  panel on top of them. The last two answer a member the way `docs_symbol` does: the page of the
  declaring type plus the member's name and the id of its heading.

## Related

- [Visual form designer](/DESIGNER) - the palette and the properties panel that link here.
- [VS Code extension](/vscode) - everything else the extension does.
