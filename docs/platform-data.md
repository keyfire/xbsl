---
title: "Platform data"
description: "The generated datasets behind the checks: versions, the documentation index, and the diff between two platform releases."
sidebar:
  label: Platform data
  order: 11
---

The semantic rules, the completion and the documentation panel all read data extracted from a distribution. This page is about that data: what else can be built from it and how versions are kept apart.

## Documentation search

`tools/extract_docs.py` pulls the Element reference out of a distribution, from the
server-with-IDE `.car`, into a `docs.sqlite` next to the language data. The database holds the
stdlib pages with cleaned HTML: a type, its methods, properties and parameters. Beside them go a
full-text index (SQLite FTS5, from the standard library) and canonical links back to the primary
source, `https://1cmycloud.com/docs/help/...`, taken from the distribution's `sitemap.xml`. Page
images are stored alongside. The 1C reference is copyrighted, so the database does not ship in the
package: you generate it from your own distribution, like the language data.

```sh
python tools/extract_docs.py --dist "$ELEMENT_DIST"
```

`docs.sqlite` is read by the `xbsl.docs` API: `search`, `page`, `tree`, `for_symbol`, `asset`,
plus the pure `sections` and `summarize` over a page's HTML. With no database the search is simply
empty. The MCP tools run on this API, and later the reference panel of the VS Code extension will
too.

## Element versions

The data is versioned by platform version:

```
xbsl/data/element/
    index.json            # { available: [...], default: "<version>" }
    <version>/{language.json, stdlib.json, metamodel.json}
```

Pick a version with the `--element-version` flag, the `XBSL_ELEMENT_VERSION` environment
variable, or the `default` field of the index. `--version` shows what is available. A new version
arrives when you re-run `xbsl extract` with a new `--dist`. The index makes the newest version the
default, and regenerating an old version does not move the default back.

`xbsl data-diff [old] [new]` shows what changed in the platform between two data versions. With
no arguments it compares the default version against the closest older one. The report covers
stdlib types and members, metamodel properties, components and their properties, terms and
documentation pages. `--format md` writes a full Markdown report and `--format json` a machine
view; the text form caps every list at `--limit`. Type members are compared with the inheritance
expanded, and a change is lifted to the hierarchy root, so an addition to a base type is not
repeated for every descendant.

The data root itself is resolved in this order: the `--data-dir` flag, the `XBSL_DATA_DIR`
environment variable, a root supplied by an installed `xbsl.data` entry point, then
`xbsl/data/element` inside the package.
