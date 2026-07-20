---
title: "XBSL (1C:Element)"
description: "A toolkit for 1C:Element: a linter with autofixes, an LSP server, documentation search, and metadata scaffolding — plus a VS Code extension on the same engine."
sidebar:
  label: Home
  order: 1
---

XBSL is a toolkit for **1C:Element** projects written as `Name.yaml` (element description) and
`Name.xbsl` (code module) pairs. It gives fast local feedback ahead of the slow server-side
compilation that runs on deploy – the only check the platform itself provides. The project
ships as a Python engine and a VS Code extension built on top of it.

## What is in the box

- **Linter with autofixes** – 87 rules in four tiers: yaml structure, text and typography
  conventions, code structure, and semantics checked against the platform data and the project
  itself.
- **LSP server** – live diagnostics, go-to-definition and completion for any LSP-capable editor.
- **Metadata scaffolding** – creating objects, attributes, routes and forms without hand-writing
  yaml.
- **Documentation search** – a local full-text index built from your own 1C:Element
  distribution.
- **MCP server** – linting, documentation search and every scaffolding operation exposed as
  tools for AI agents.
- **[VS Code extension](https://github.com/keyfire/xbsl/blob/main/editors/vscode/README.md)**
  (publisher `keyfire`, extension id `keyfire.xbsl`) – syntax highlighting, project-wide
  diagnostics, a form preview, a metadata tree and a deploy button, all backed by the same
  engine.

## Where to go next

- **[Guide](GUIDE.md)** – installation, CLI flags, CI setup, the baseline mechanism, metadata
  scaffolding, extending the linter with your own rules, and the LSP and MCP servers.
- **[Rules](RULES.md)** – the full list of linter checks, with severities and scope.
- **[Visual designer](DESIGNER.md)** – specification and roadmap for the in-editor form
  designer.
- **[README on GitHub](https://github.com/keyfire/xbsl/blob/main/README.md)** – the short
  project tour and quick-start commands.
- **[Contributing](https://github.com/keyfire/xbsl/blob/main/CONTRIBUTING.md)** – how to add a
  rule or update the language data.

Language data (keywords, the stdlib type catalog, the configuration metamodel) is generated
from your own 1C:Element distribution and is not bundled with the project – see
[Language data](/GUIDE#language-data) in the guide.

Not affiliated with 1C. "1C:Element", "1C:Fresh" and related names are trademarks of their
respective owners – see [NOTICE](https://github.com/keyfire/xbsl/blob/main/NOTICE).
