---
title: "XBSL (1C:Element)"
description: "A toolkit for 1C:Element: a linter with autofixes, an LSP server, documentation search, metadata scaffolding and translation into English spellings. Plus an MCP server and a VS Code extension on the same engine."
sidebar:
  label: Home
  order: 1
---

XBSL is a toolkit for working with **1C:Element** project sources. A project consists of file
pairs: `Name.yaml` describes an element and `Name.xbsl` contains its code. XBSL checks the
sources before server-side compilation during deployment. The toolkit includes a Python engine
and a VS Code extension built on it.

## What is in the box

- **Linter with autofixes** – 280 rules in four tiers: yaml structure, text and typography
  conventions, code structure, and semantics checked against the technology data and the project
  itself (a plugin can add rules of its own on top).
- **LSP server** – live diagnostics, go-to-definition and completion for any LSP-capable editor.
- **Metadata scaffolding** – creating objects, attributes, routes and forms without hand-writing
  yaml.
- **Translation into English spellings** – the project dictionary, the coverage and a CI check.
  What is left over comes back as suggestions from Yandex or Google.
- **Documentation search** – a local full-text index built from your own 1C:Element
  distribution.
- **MCP server** – linting, documentation search and every scaffolding operation exposed as
  tools for AI agents.
- **Web panel** – a local page with the project findings: rule settings by tier, filters and
  opening a file in the editor.
- **[VS Code extension](https://github.com/keyfire/xbsl/blob/main/editors/vscode/README.md)**
  (publisher `keyfire`, extension id `keyfire.xbsl`) – syntax highlighting, project-wide
  diagnostics, the form designer, a metadata tree, the 1C:Element documentation panel, debugging and a
  deploy button, all backed by the same engine.

## Where to go next

- **[Quick start](/start)** – install the package, generate the language data from your
  distribution, run the first check.
- **[Checking sources](/linting)** – the flags of a run, what the deeper rules rely on, the
  baseline for an old codebase, CI.
- **[Rules](/RULES)** – the full list of linter checks, with severities and scope.
- **[Metadata scaffolding](/scaffolding)** – objects, attributes, routes and forms through the
  engine instead of hand-written yaml; the code templates.
- **[Translating a project](/translation)** – the dictionary, the coverage, machine translation of
  what is missing, the CI check.
- **[Servers and plugins](/servers)** – the LSP server, the MCP server, the web panel, and
  rules, data and severities of your own.
- **[1C:Element data](/platform-data)** – the generated datasets, the documentation index, the
  diff between two 1C:Element versions.
- **[Commands](/CLI)** – every command and flag, generated from the tool itself.
- **[Visual designer](/DESIGNER)** – the form panel, the palette, the properties panel and
  following the cursor.
- **[Documentation panel](/DOCS_PANEL)** – the 1C:Element help inside the editor: contents,
  search, the page for a symbol.
- **[Guide](/GUIDE)** – the map of all of the above.
- **[README on GitHub](https://github.com/keyfire/xbsl/blob/main/README.md)** – the short
  project tour and quick-start commands.
- **[Contributing](https://github.com/keyfire/xbsl/blob/main/CONTRIBUTING.md)** – how to add a
  rule or update the language data.

## Nearby

The following tools are also available for 1C projects:

- **[Elemctl](https://docs.keyfire.ru/elemctl/)** builds an application from sources, uploads
  and applies the build, and verifies that the stand starts on the new version. The VS Code
  extension uses Elemctl for the *XBSL: deploy* command.
- **[EDT-Bridge](https://docs.keyfire.ru/edt-bridge/)** provides MCP access to 1C:EDT for the
  1C:Enterprise platform. An agent can use it to read configurations, edit modules and forms,
  build extensions and debug.

Language data (keywords, the stdlib type catalog, the configuration metamodel) is generated
from your own 1C:Element distribution and is not bundled with the project – see
[Language data](/start#language-data) in the guide.

Not affiliated with 1C. "1C:Element", "1C:Fresh" and related names are trademarks of their
respective owners – see [NOTICE](https://github.com/keyfire/xbsl/blob/main/NOTICE).
