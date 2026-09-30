---
title: "Platform data"
description: "The generated datasets behind the checks: versions, the documentation index, and the diff between two platform releases."
sidebar:
  label: Platform data
  order: 11
---

The semantic rules, the completion and the documentation panel all read data extracted from a distribution. This page is about that data: what else can be built from it and how versions are kept apart.

## Generic variance and base arguments

Two optional `stdlib.json` sections describe generic type relationships:
`type_param_variance` stores an ordered list of `out`, `in` or `in_out` modes per type;
`generic_bases` maps a type to its bases and their argument formulas. The extractor reads
formulas from the documented hierarchy and accepts only proven uniform variance from
runtime descriptors. Unsupported descriptors are omitted.

Re-extract stdlib to obtain these fields. `style/redundant-union-member` substitutes the
formulas and uses the declared variance, including nested base arguments. An old catalog
or a missing/malformed entry keeps the conservative invariant comparison.

## Documentation search

`tools/extract_docs.py` pulls the Element reference out of a distribution, from the
server-with-IDE `.car`, into a `docs.sqlite` next to the language data. The database holds the
stdlib pages with cleaned HTML: a type, its methods, properties and parameters. Beside them go a
full-text index (SQLite FTS5, from the standard library) and canonical links back to the primary
source, `https://1cmycloud.com/docs/help/...`, taken from the distribution's `sitemap.xml`. Page
images are stored alongside. The 1C reference is copyrighted, so the database does not ship in the
package: you generate it from your own distribution, like the language data. Besides the type
reference, the database takes the other sections of the site menu: the developer and administrator
guides, the properties of project elements and interface components, the integration process
schema, the query language and the glossary.

```sh
python tools/extract_docs.py --dist "$ELEMENT_DIST"
```

`docs.sqlite` is read by the `xbsl.docs` API: `search`, `page`, `tree`, `for_symbol`, `asset`,
plus the pure `sections` and `summarize` over a page's HTML. With no database the search is simply
empty. `for_symbol` never answers with a page of the property references or of the glossary: their
titles repeat the names of types, members and variables, so search and the tree reach those pages
instead. The MCP tools run on this API, and later the reference panel of the VS Code extension will
too.

## Retired interface components

The optional `retired_components` section of `stdlib.json` retains runtime descriptions
for components whose help page is a tombstone. Each record carries `term`, `namespace`,
`baseType`, the compatibility limit `to`, typed properties, and named events from the
distribution. The UI schema uses it only when the term matches a retired help page and the
limit is stated. It marks the result with `source: runtime`, `retired: true`, and `until`.
Known property types and inherited properties become `props`; a known key whose type or
event signature is unavailable remains in `yaml_props` without a guessed type.

Re-extract both stdlib and uischema to obtain these records. The uischema step reads the
`stdlib.json` of the version it builds; in a root without one it builds the schema without the
retired components and says so. A dataset without the optional section keeps the previous
behavior, and a current help page is never replaced by a runtime description.

Component and property queries retain these definitions for existing compatibility markup.
Catalog entries preserve `retired` and `until`. The insertion palette excludes retired
components and containers; it does not assume that the active project's mode permits them.

## Enumeration values of the metamodel

`metamodel.json` lists the values of every enumeration its properties are typed by: `enums` keeps
the Russian values in the order the platform declares them, and `enum_items` keeps a record of
each value - an item of the enumeration, as the platform calls it.

```json
"enum_items": {
  "<enumeration>": {
    "<Russian value>": {"en": "<English value>", "since": "<mode>", "until": "<mode>"}
  }
}
```

`en` is the English spelling the way this very enumeration writes it. A flat table of pairs cannot
hold every word: one Russian value is `Normal` for the importance of a command and `Usual` for the
importance of a favorite. `translate` and the properties panel of an English project spell a value
by the record of its own enumeration.

`since` is the compatibility mode the value appeared in, `until` the last mode that still has it;
a value with neither is there in every mode. The modes come from the compiled classes of the
platform and from its table of languages, since the model files date no value. The properties
panel offers only the values the mode of the project allows, and a value the file already holds
stays shown whatever its mode. MCP `metadata_schema` returns the limits in `enum_modes`.

Data extracted before the section appeared keeps working: a value is then spelled from the flat
table of pairs, and no value is limited by a mode. Re-extract the metamodel to get the records.

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

A combined set that a data package may build from several versions is not produced by
`xbsl extract`. If the package has one, rebuild it after the versions it is based on are
regenerated: otherwise it keeps the data of the previous run.

`xbsl data-diff [old] [new]` shows what changed in the platform between two data versions. With
no arguments it compares the default version against the closest older one. The report covers
every file of the version: the stdlib catalog (types and members, and the rest of it too – module
handlers, signatures, availability, constructors, type parameters, deprecations, retired
components), metamodel properties, components and their properties, the term pairs, the interface
spellings (`uiterms.json`), the compiler dictionary (`terms_full.json`) and the documentation
pages that came, went, got another title or another content, compared by a hash of the page. A
section without a comparison of its own is compared entry by entry, so a section a newer
extractor adds is not passed over. `--format md` writes a full Markdown report and
`--format json` a machine view; the text form shows the count and the first entries of every
list, at most `--limit` of them, and `--limit 0` prints them all. Type members are compared with
the inheritance expanded, and a change is lifted to the hierarchy root, so an addition to a base
type is not repeated for every descendant. Signatures, bases and the other sections kept per type
are compared the same way.

The data root itself is resolved in this order: the `--data-dir` flag, the `XBSL_DATA_DIR`
environment variable, a root supplied by an installed `xbsl.data` entry point, then
`xbsl/data/element` inside the package.
