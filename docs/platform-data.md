---
title: "Platform data"
description: "The generated datasets behind the checks: versions, the documentation index, and the diff between two platform releases."
sidebar:
  label: Platform data
  order: 11
---

The semantic rules, the completion and the documentation panel all read data extracted from a distribution. This page is about that data: what else can be built from it and how versions are kept apart.

## Documentation search

`tools/extract_docs.py` extracts the Element reference from a distribution (the server-with-IDE
`.car`) into a `docs.sqlite` next to the language data: the stdlib pages (a type, its methods,
properties, parameters) with cleaned HTML, a full-text index (SQLite FTS5, from the standard
library) and canonical links back to the primary source (`https://1cmycloud.com/docs/help/...`,
taken from the distribution's `sitemap.xml`). Page images are stored alongside. The 1C reference is
copyrighted, so the database is not shipped in the package – you generate it from your own
distribution, like the language data.

```sh
python tools/extract_docs.py --dist "$ELEMENT_DIST"
```

The runtime API `xbsl.docs` (`search`, `page`, `tree`, `for_symbol`, `asset`) reads
`docs.sqlite`; with no database the search is simply empty. It powers the MCP tools (below) and –
later – the reference panel in the VS Code extension.

## Element versions

The data is versioned by platform version:

```
xbsl/data/element/
    index.json            # { available: [...], default: "<version>" }
    <version>/{language.json, stdlib.json, metamodel.json}
```

Pick a version with `--element-version` / the `XBSL_ELEMENT_VERSION` env var / the index
`default`; `--version` shows what is available. Add a new version by re-running `xbsl extract`
with a new `--dist`; the index makes the newest version the default (regenerating an old
version does not move the default back).

`xbsl data-diff [old] [new]` shows what changed in the platform between two data versions
(default: the default version against the closest older one): stdlib types and members,
metamodel properties, components and their properties, terms, documentation pages.
`--format md` writes a full Markdown report, `--format json` a machine view; the text form
caps every list at `--limit`. Type members are compared with the inheritance expanded, and a
change is lifted to the hierarchy root - an addition to a base type is not repeated for every
descendant.

The data root itself is resolved in this order: `--data-dir` > `XBSL_DATA_DIR` > a root supplied
by an installed `xbsl.data` entry point > `xbsl/data/element` inside the package.
