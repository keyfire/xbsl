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
expression keeps its shape and its facets (`.Ссылка` -> `.Reference`) - in yaml and in the code
alike, wherever the parser reads a type (a parameter, a declaration, a constructor, a cast, a
type argument), while the same word after a dot elsewhere is a member; inside `Query{ ... }`
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

Two places mix text and code, and the literals plane serves them apart. **The name of a named
group** of a pattern (`(?<Name>...)`) is a name of the project: the code reads the group back by it
(`Group("Name")`), and both sides take the spelling from ONE source - the literals plane first, the
ordinary name resolution after. Let them part, and the call asks for a group the pattern never
declared. **The presentation template** of an event kind is prose with expressions inside it: the
expressions are renamed as names, while the text itself comes from the literals plane by the whole
value; what the plane does not name goes into the gap report instead of staying in the source
language silently.

The suffixes of a duration literal in code move to their English spellings by themselves
(`300мс` -> `300ms`, `2д14ч30м5с6мс` -> `2d14h30m5s6ms`): the Russian set comes from the
type's documentation, the English one is confirmed by the platform compiler. A number glued
to any other letters is left alone.

The same plane serves every yaml value the metamodel declares a localizable text
(`Localizable`): the presentations of commands, access privileges and enumerations are read by a
person on the page, so each is either named whole by an entry or reported as a gap. The one
exception is the `Description` property: it is developer documentation, it stays data and never
enters the gaps.

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

A second warning of the same kind is `literal-data-value`: a literal that equals a VALUE from a
json resource of the project and was moved by a literals-plane entry. Such a literal is usually
compared against that data (a seeding parse), and data is never translated - after the move the
comparison goes silently dry. When the literal really is data, an entry whose value EQUALS its
key marks that explicitly: the coverage is counted, the text does not move, no warning is drawn.
The report prints the warnings as a list - file, line, kind and text.

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

The dictionary is discovered next to the project and above it – a root with none is refused,
the message naming the places looked at and a dictionary found below the root, if any;
`--dictionary` names it
explicitly (a file or a directory), and `--target` names the file NEW entries land in
(`090-manual.yaml` by default); `--comment` is the head line such a file is created with,
which is the place to say what the batch is about. `--format json` hands the whole report
to a machine.
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
place and the dictionary file - each record over two lines, the translation field itself stretched
under the rest at the full width of the row. The field is edited in place, a search box and an
"only empty" switch narrow the table, and a suggestion - the platform's own spelling first, an
external service's guess otherwise - stands grey inside an empty field and goes in on a click or
on `Enter`. The table reads `--table` - the entries, the gaps and the coverage out of one pass
over the project - and writes through `--set`; a written cell does not cost another pass, only a
re-read of the dictionary, and the header counters step forward by what that edit changed. The
"Re-read" button is what replaces them with freshly counted ones. The panel
needs **xbsl 0.72.0 or newer** - `--suggest`, the machine-translation run behind its
suggestions button, only arrived there. The **"Suggest via translation service"** button in
the same panel fills empty fields with an external service's guesses - details in
[Machine translation](#machine-translation) below.

## Filling the dictionary from the tools

The dictionary of a large project runs to thousands of entries, and reading those files to add
one word is both slow and error-prone. Every surface therefore works in PAGES, over the same
engine core.

**The CLI** answers the same questions the panel asks:

```sh
xbsl translate e1c/app --gaps --kind token --limit 20      # what is missing, most frequent first
xbsl translate e1c/app --entries --filter Задач            # what the dictionary already says
xbsl translate e1c/app --table --limit 0                   # all three: entries, gaps, totals
xbsl translate e1c/app --set правки.yaml                   # apply a batch file (see below)
xbsl translate e1c/app --unused                            # entries the project no longer uses
```

`--table` answers all three questions in one pass, and that is what it exists for: the editor table asks exactly those three, and asked apart they are two identical walks over the sources in two processes plus a third reading of the same dictionary.

`--set` takes the batch as a FILE in either shape: the dictionary's own yaml format
(`tokens`/`phrases`/`literals` sections, the same quoting as the dictionary files, an
empty value removes the entry) or the JSON list `[{key, value, kind}]` that scripts
produce. A batch of hundreds of entries is authored the way the dictionary itself is
written, not as inline JSON.

`--unused` answers the opposite question to `--gaps`: not what the project needs and the
dictionary lacks, but what the dictionary still says and the project no longer has. Deleting
code leaves its names and comment lines behind, and nothing else reports them - `--strict`
judges what is NOT covered, and `--entries` shows where a pair is declared, not whether
anything uses it. `--prune` removes exactly the rows it just listed, so `--kind`, `--filter`
and the page apply to the removal as well; a page cut by `--limit` is called out, because
removing "everything" while looking at fifty rows of three thousand is not what the flag looks
like it does.

The reading is textual, and the direction of its error is the point: a name that also occurs in
prose may be counted as used, which merely leaves an entry in place, but a LIVE entry is never
called an orphan. A qualified key (`<Owner>.<Name>`) is judged by both halves - the sources
spell them apart, and reading the dotted text as one name would call every such entry an orphan.

`--gaps` shows the count, the first places to look at and `suggestion` - the platform's own
spelling where it has one. A suggestion is a hint, never an answer: a name the project
declared may deliberately need a different word, and an INTERNAL platform name (a metadata
class such as `CodeAttrMd`) is never offered at all.

**The MCP tools** are the same four, for an agent that fills the dictionary:

- `translate_status` - coverage and what is left, the cheap check before deciding anything;
- `translate_gaps` - the untranslated entries by page (`kind`, `filter`, `limit`, `offset`),
  the answer naming the `dictionary` it read;
  `compact` returns only `{key, kind, count}` per row - the worklist shape that fits an
  answer when the full rows would not;
- `translate_entries` - what the dictionary already says, with the file and line of each
  entry, so a new word stays consistent with the accepted ones;
- `translate_set` - write entries back: add, correct in place, or remove by emptying a
  value; `edits_file` sends the batch as a file in the same two shapes `--set` reads.

A new entry lands in `090-manual.yaml` (or the file named by `target`), while an entry that
already exists is corrected where it lives - the writer never duplicates a key, and a
duplicate with a different value is refused when the dictionary loads.

## Machine translation

Filling a large remainder by hand is slow; `--suggest` fills the untranslated remainder through
an external translation service - as SUGGESTIONS, not writes: the dictionary does not change
until a suggestion is accepted (from the console with `--suggest-out`, in the editor with a
click or `Enter` on the hint in the table).

```sh
xbsl translate e1c/app --suggest                                  # report: what the service offered
xbsl translate e1c/app --suggest --provider yandex                # pick the service explicitly
xbsl translate e1c/app --suggest --suggest-out 080-machine.yaml   # write the plan next to the dictionary
xbsl translate e1c/app --suggest --plans tokens                   # fill names only, not comments
```

A run always covers the whole project: nothing caps it, nothing stops it midway, its size cannot
be estimated beforehand - and every batch it sends is a paid call to the service.

`--suggest-out` names the plan file the offered records are written to: the directory part of the
path is dropped, only the file name is kept, and the file lands inside the dictionary directory.
When the dictionary is a single FILE there is no separate plan to make - the records go into that
file itself.

Without `--provider` the engine takes the one service that is configured. With none configured,
the refusal names the missing environment variables. With more than one configured, the refusal
lists the services themselves (`google`, `yandex`) and asks for a choice with `--provider` -
neither case is a silent guess.

**Two services, and they are not interchangeable.**

- **Yandex Translate** - authorizes with a service-account key AND a folder id, both required;
  the batch limit is up to 10,000 characters per request; it understands a glossary - the
  project's term list travels with the request itself.
- **Google Translate** - authorizes with one key alone; the batch limit is up to 5,000
  characters; its API has no glossary at all - the term spelling is enforced afterward, when the
  engine builds a name out of the returned prose.

Whatever either service allows, one request carries at most 100 texts - the engine's own
conservative bound. A batch turned away for its size costs exactly as much as one that is
accepted, and the character sum alone would let six hundred one-word names ride in a single call.

**Keys live in the environment, never on a command line or in a setting.** Three variables,
named after the service each belongs to:

- `XBSL_TRANSLATE_YANDEX_KEY`, `XBSL_TRANSLATE_YANDEX_FOLDER` - the Yandex key and folder, both
  required;
- `XBSL_TRANSLATE_GOOGLE_KEY` - the Google key, alone.

The editor needs no environment variables of its own: the **XBSL: Set a machine-translation
key** command (`xbsl.translate.setKey`) asks which of the three to set and stores the value in
the extension's SecretStorage - it is passed to the engine in the environment of the `--suggest`
run itself, never in a setting and never on the command line. The `xbsl.translation.provider`
setting picks the service when both are configured; it never holds the key itself.

**The cache** is a `machine-cache.json` file next to the dictionary (inside the
`xbsl-translation` directory when the dictionary is one, otherwise next to the single dictionary
file). It stores the service's RAW answer, keyed by (service, language, glossary fingerprint,
text) - not the finished name, because the name-building rule and the term list still change,
and paying the service again for the same sentence over a rule change would be absurd. The
format is JSON, not yaml: the dictionary loader collects `*.yaml` recursively, and a yaml cache
file would be read as another dictionary plan with duplicate keys. An entry stays in the cache
whether or not the suggestion was ever accepted into the dictionary - a repeated `--suggest`
never pays twice for the same text, even one nobody accepted last time.

**The dictionary's `terms` section** is a short "Russian term -> English spelling" list - not a
translation plan and not counted toward coverage. It feeds two things: the glossary pairs sent
with the request (Yandex only), and the spelling used when a name is BUILT. The second half works
on the ANSWER: building an identifier, the engine matches every English word the service returned
against the term list, ignoring case, and puts the dictionary's spelling in its place wherever the
word stands in the phrase. Russian word forms are not analyzed at all, and a term the service
answered in another English word - a plural, a synonym - is not recognized and stays as it came.
Comment lines (`phrases`) are not touched by terms at all - a comment stays exactly what the
service answered.

**Names are built deterministically, never by the service.** The service answers in prose
("Site address"), and the `tokens` plan needs an identifier: the engine drops stop words (a,
the, of...), substitutes a term's spelling where one is known, and title-cases and glues the
rest. A name already taken by another dictionary key, or prose that yields no identifier at all,
is refused with a named reason - the service never guesses and never overwrites.

**Literals never reach the network.** `--suggest` sends the service only `tokens` and `phrases`
gaps (whole names and whole comment lines); a string literal is filled separately, and only when
its text matches an already-accepted name EXACTLY - locally, with no request at all.

**What is sent, said plainly.** The service sees only the gap's own text: a name as the project
wrote it, or a whole comment line. Never a file path, never the code around it, never the rest of
the project. Without a key the command sends no request at all, to either service - it refuses
immediately and names the variable that is missing.

The report prints the same way `--set` does: `cached` is how many answers came from the cache,
`requested` is how many were asked for again, `refused` is how many were turned down (each with
its reason).

In the editor the same three numbers stay in the panel's own summary line until the next run, not
only in a status-bar message that closes itself in a few seconds; a hover on that line names each
refusal's reason. When there was nothing left to ask, the line says so in words instead of three
zeroes, and when every offer came from a local literal match without a single request, it says
that too.
