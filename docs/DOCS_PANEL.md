---
title: "Documentation panel"
description: "The 1C:Element help inside the editor: the contents tree, full-text search, the page for the symbol under the cursor and the jumps from the designer - all built from your own 1C:Element distribution."
sidebar:
  label: Documentation panel
  order: 9
---

The extension's documentation panel provides 1C:Element help in the editor. The
**Documentation (1C:Element)** container is on the activity bar. The reference is built from
the 1C:Element distribution, matches its version and is available offline.

## What is inside

- **The "Contents" tree** - a hand-curated table of contents that matches the site: the
  developer guide, the administrator guide, the language types (`Std`, `Std::Collections` →
  `Array`, ...), the properties of project elements and interface components (the keys of their
  yaml descriptions), the integration process schema, the query language and the glossary.
  Sections inside a page (`Type hierarchy`, `Examples`, `Literals`) sit under its node, so a
  click lands on the right spot straight away.
- **The page** opens as an editor tab beside the current one and **does not steal the focus**.
  It carries the article's code, tables and images, a **Copy** button on samples, and a
  **Primary source** link to the same page on the site. Internal links open other pages in the
  same tab, and the "Contents" tree follows the page you open.
- **Search** is available from the tree header and the *XBSL: search the documentation*
  command. Full-text search covers the reference and both guides. Selecting a result opens
  its page.

## How you get here

The panel can be opened from the following parts of the extension:

| From | What happens |
| --- | --- |
| Hovering a name in `.xbsl` | the hover shows the description and a **Documentation** link, and clicking it opens the page. Over a member of a type the hover shows that member's own block: its signature and what the call does. The link then opens the page at that member |
| Editor context menu, *XBSL: documentation for symbol* | the page of the type under the cursor. For a member, that page scrolled to the member. For a name several types declare, those types to choose from |
| The designer **Palette**, *Open documentation* | the page of the component you are about to insert. A short description also shows in the palette item's tooltip |
| The "Contents" tree and search | plain navigation through the reference |

A member is documented where it is declared. `Array.Size` opens the page of the ancestor that
declares it; the inherited member is not repeated on the descendant's page. When several unrelated types declare the same
name, those types are offered as the choice, each with that member's block as the line under it.
For everything else with no page of its own, the candidates are **ranked by the receiver before
the dot**: `ScheduledJob.Configure` prefers the scheduled-job pages over a guide topic of the same
name.

For a project name, the hover shows the project's own card, such as a method, its signature and file. The
project index identifies objects, module methods, form components, tabular sections and
enumeration values, so documentation for a built-in member of the same name is not added to the
card. For example, documentation for a built-in `Write` method is not substituted
for a project method with the same name. The panel still offers a documentation
search for that name.

## What you need

- **LSP mode** (`pip install "xbsl[lsp]"`): the server stores the documentation database, and the
  extension requests and displays its contents.
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
  1C:Element API without going online.
- **LSP** - the `xbsl/docsAvailable`, `xbsl/docsSearch`, `xbsl/docsPage`, `xbsl/docsTree`,
  `xbsl/docsForSymbol` and `xbsl/hoverDoc` requests. Any LSP-capable editor can build its own
  panel on top of them. The last two answer a member the way `docs_symbol` does: the page of the
  declaring type plus the member's name and the id of its heading.

`docs_symbol` also finds members generated for project interface components, such as
`SelfModified`, `ComputedModified`, and `TrackDataModification`. Their definitions live in
the component type guide. The response includes that page, the member block and its `section`.

## Related

- [Visual form designer](/DESIGNER) - the palette and the properties panel that link here.
- [VS Code extension](/vscode) - everything else the extension does.
