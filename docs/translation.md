---
title: "Translating a project"
description: "Rewriting a project into English spellings: what the platform data answers, what the project dictionary answers, how coverage is measured and how a CI job gates it."
sidebar:
  label: Translation
  order: 6.5
---

1C:Element is bilingual: every keyword, metadata key, type, member and enumeration value has an
English spelling, and a project written in those spellings compiles exactly like a Russian one.
`xbsl translate` rewrites a whole project into them - the platform half from the extracted
[platform data](platform-data), the project's own half from a dictionary the team fills.

```sh
xbsl translate e1c/app                          # report only: coverage and what is missing
xbsl translate e1c/app --coverage               # plus the breakdown per metadata object
xbsl translate e1c/app --missing gaps.yaml      # the untranslated remainder as a dictionary stub
xbsl translate e1c/app --out build/app-en       # write the translated tree
xbsl translate e1c/app --out build/app-en --strict   # non-zero exit unless it is complete
```

## What answers what

**The platform half comes from the dataset, never from a translation.** Keywords take the form
of the same case (`Если` -> `If`, `если` -> `if`); a yaml key takes the English spelling its
metamodel class declares, so the same word can differ by node; an enumeration value is looked up
inside its own enumeration (globally one Russian word answers to several English ones); a type
expression keeps its shape and its facets (`.Ссылка` -> `.Reference`); inside `Query{ ... }`
blocks the query vocabulary answers instead of the general one. A name the data cannot spell
stays as written and is reported as a data gap - the translator never guesses.

**The project half comes from the dictionary.** Everything the project itself named - objects,
methods, attributes, form components, dictionary keys, resource files - and every Cyrillic
comment line is translated by people. Three planes:

```yaml
version: 1
language: en

# tokens: one exact identifier to one exact identifier (a resource file by its stem)
tokens:
    Задачи: Tasks
    Значок: Icon

# phrases: one comment line to its translation
phrases:
    "Задача помечается выполненной.": "The task is marked done."
```

The indent is four spaces, the way the tool itself writes. Your own indent survives too: the
writer copies it from the entries already in the section, so a file started with two spaces stays
valid after an edit from the panel or from `--set`.

The third plane - `literals` - is about the string literals of the code:

```yaml
literals:
    "Файл не загружен": "The file was not uploaded"
    "Не заполнено поле \"Наименование\"": "The \"Name\" field is empty"
    "Не разобрано тело: %{Описание}": "Could not parse the body: %{Описание}"
```

A literal is data, and the translator never guesses data: it replaces exactly what the team listed.
The key and the value are written the way the text stands BETWEEN THE QUOTES in the source, with
the same escaping the code uses; a value that is not a valid literal body is refused when the
dictionary loads. An interpolation inside the value is written as in the source - the engine
translates the name inside it. A literal inside `Query{}`, `Pattern{}` and the other resolvable
literals is left alone: there it is code, not data.

Whole names, not words: the word order of an English name is the reverse of the Russian one and
the parts of a Russian name are declined, so gluing per-word translations produces calques.
Comments are translated line by line - an edit next to a line does not invalidate it, and one
entry serves every repetition. The finished comment block is re-wrapped to the project's width -
the same one `style/line-length` uses - because a translation that grew longer than its original
would otherwise run past the limit. Frames and separators, lists, tables and code samples, and
lines that were long in the source already, stay as they were.

The dictionary is a directory of yaml files (or one file) named `xbsl-translation`, discovered
next to the project or above it. Filling it is dropping a completed stub next to the ones
already there; two files disagreeing about one key is refused at load time.

**A qualified entry** (`Dictionary.Key: SignIn`) applies inside one namespace only - a key of a
localized-strings dictionary may need a spelling the same word cannot have in code.

## Names the project declares are the project's

A word the platform dictionaries also know may be what the project called its own thing: an
enumeration value, an attribute, a method, a dictionary key. Such names are answered by the
project dictionary ALONE. Without that gate a use would move to the English spelling while its
declaration waited for a dictionary entry - the yaml would still declare the Russian value while
the module already called the English one, and the build would refuse the tree. With the gate
both halves move together, or both wait for one entry.

The exceptions stay with the platform: the built-in items a collection dispatches by name (the
standard code, name and owner attributes) and the facet after a dot in a type expression.

## What is left alone

Data. Labels, descriptions and any other text a user reads stay as written - they are localized
by the platform's own mechanism, and the translated project keeps the same dictionaries. String
literals stay too, except the CODE inside their interpolations, which is re-tokenized and
translated like any other code. `Id` values never change: the translated tree is the same
project, not a copy of it.

A string literal that equals a renamed name is reported as a warning: a method called by its
name from a string breaks silently when only the declaration is renamed.

Two exceptions, both of them names written a SECOND time, outside the code.

**The keys of the project's own json resources that name a field of its structures.** A structure
reads json by field name, so such a key is the same name written again - rename the field, leave
the key, and the binding finds nothing. Silently: the reading options tolerate an unknown property
and initialize a missing field, so the project compiles, applies and starts with empty data. Those
keys go through the same dictionary as the fields; values, and keys no structure declares (a map
keyed by content, an external contract), stay as written. The number of renamed keys is part of
the run's summary.

**A literal that spells a RESOURCE PATH** (`"Значки/%Код.svg"`). The pass renames the resource
files and directories, and a path has to follow them or the platform stops finding the resource.
Only a literal SHAPED like a path qualifies: it ends with a known resource suffix and every
segment reads as a file name. A regular expression, with its slashes and named groups, does not
qualify and stays data.

## Localized strings turn around

A project that already carries the target language in its localization sections gets those
values as its BASE (with the keys translated), while the original values move under
`Localization/<Code>/` and the project descriptor's default and development languages follow. A
key with no value in the target language keeps the original one and is reported.

## Coverage and the gaps

`--coverage` prints the dictionary's share for every metadata object (the yaml/xbsl family that
shares one stem) and for the project as a whole. `--missing` writes what is left as a dictionary
stub - entries ordered by frequency, each annotated with its count and first location, values
empty and ready to fill.

Three counters are kept apart on purpose: the DICTIONARY's coverage (the number a team fills
towards 100%), the platform DATA gaps (nothing a dictionary entry should paper over) and the
Cyrillic scalars left alone as data (listed so a reviewer can confirm they really are data).

The dictionary is discovered next to the project and above it; `--dictionary` names it
explicitly (a file or a directory), and `--target` names the file NEW entries land in
(`090-manual.yaml` by default). `--format json` hands the whole report to a machine.
`--no-localization-swap` leaves the localized-strings layout as it is - for a project that
translates its sources but keeps its language layout.

`--strict` exits non-zero unless the coverage is complete and no problems were found - what a CI
job wants before it publishes a translated build. Name COLLISIONS are such a problem: two
different names of one namespace translated into one word is a build breaker (the platform
refuses a repeated name), and only the translator can see it.

## In the editor

The rule `conventions/missing-translation` (info, off by default, project scope) shows the same
gaps where they stand: a name or a comment line the dictionary does not cover, one finding at
its first occurrence in the file. It stays silent unless a dictionary is discovered, so it only
speaks in a project that translates its sources. Enable it with
`--enable conventions/missing-translation` (in the editor: the Linter: Enable setting).

The finding carries the dictionary key, its kind and the suggestion, so the **lightbulb** offers
to write the translation without leaving the file: "Translate as ..." takes the platform spelling
in one click, "Translate ..." asks for the word, and a third action opens the dictionary table
filtered by that key. The project is re-checked once the entry is written - no restart.

**The dictionary table** (the "XBSL: translation dictionary" command) lists the entries next to
what the sources do not cover yet: kind, key, translation, the number of occurrences, the first
place and the dictionary file. The translation cell is edited in place, a search box and an "only
empty" switch narrow the table, and the platform's own spelling stands greyed in an empty cell and
goes in on click. The panel needs xbsl 0.70.0 or newer: the table reads `--entries`/`--gaps`
and writes through `--set`.

## Filling the dictionary from the tools

The dictionary of a large project runs to thousands of entries, and reading those files to add
one word is both slow and error-prone. Every surface therefore works in PAGES, over the same
engine core.

**The CLI** answers the same questions the panel asks:

```sh
xbsl translate e1c/app --gaps --kind token --limit 20      # what is missing, most frequent first
xbsl translate e1c/app --entries --filter Задач            # what the dictionary already says
xbsl translate e1c/app --set edits.json                    # apply [{key, value, kind}]
```

`--gaps` shows the count, the first places to look at and `suggestion` - the platform's own
spelling where it has one. A suggestion is a hint, never an answer: a name the project
declared may deliberately need a different word, and an INTERNAL platform name (a metadata
class such as `CodeAttrMd`) is never offered at all.

**The MCP tools** are the same four, for an agent that fills the dictionary:

- `translate_status` - coverage and what is left, the cheap check before deciding anything;
- `translate_gaps` - the untranslated entries by page (`kind`, `filter`, `limit`, `offset`);
- `translate_entries` - what the dictionary already says, with the file and line of each
  entry, so a new word stays consistent with the accepted ones;
- `translate_set` - write entries back: add, correct in place, or remove by emptying a value.

A new entry lands in `090-manual.yaml` (or the file named by `target`), while an entry that
already exists is corrected where it lives - the writer never duplicates a key, and a
duplicate with a different value is refused when the dictionary loads.
