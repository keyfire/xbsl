---
title: "Translating a project"
description: "Rewriting a project into English spellings: what the platform data answers, what the project dictionary answers, how coverage is measured and how a CI job checks it."
sidebar:
  label: Translation
  order: 6.5
---

1C:Element is bilingual. Every keyword, metadata key, type, member and enumeration value has an
English spelling, and a project written in those spellings compiles exactly like a Russian one.
`xbsl translate` rewrites a whole project into them. The platform half comes from the extracted
[platform data](platform-data), the project's own half from a dictionary the team fills.

```sh
xbsl translate e1c/app                          # report only: coverage and what is missing
xbsl translate e1c/app --coverage               # plus the breakdown per metadata object
xbsl translate e1c/app --missing gaps.yaml      # the untranslated remainder as a dictionary stub
xbsl translate e1c/app --out build            # write the translated tree (into build/e1c/app)
xbsl translate e1c/app --out build --strict   # non-zero exit unless it is complete
```

## What answers what

**The platform half comes from the dataset, never from a translation.** Keywords take the form of
the same case: `Если` becomes `If`, `если` becomes `if`. A yaml key takes the English spelling its
metamodel class declares, so the same word can differ from node to node. An enumeration value is
looked up inside its own enumeration, since across the whole dataset one Russian word answers to
several English ones. A type expression keeps its shape and its facets (`.Ссылка` becomes
`.Reference`), in yaml and in the code alike, wherever the parser reads a type: a parameter, a
declaration, a constructor, a cast, a type argument. The same word after a dot elsewhere is a
member. On a receiver that holds a facet of a project object, or whose chain goes on to load the
record, the reference member is the facet word too, `Reference`; the link property of a label or a
picture is `Link`. A value of a union-typed property that spells a member of the union, such as
`Auto` of `Auto|Number`, becomes that member, spelled by the platform's type pairs. Inside
`Query{ ... }` blocks the query vocabulary answers instead of the general one. A name the data
cannot spell stays as written and is reported as a data gap: the translator never guesses.

**The project half comes from the dictionary.** People translate everything the project named
itself: objects, methods, attributes, form components, dictionary keys, resource files, and an
enumeration default either bare or qualified by its enumeration (`States.Open`). Every Cyrillic
comment line goes the same way, in a module and in a resource file alike. There are three planes:

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

A literal is data, and the translator never guesses data: it replaces exactly what the team
listed. The key and the value are written the way the text stands between the quotes in the
source, with the same escaping the code uses. A value that is not a valid literal body is refused
when the dictionary loads. An interpolation inside the value is written as in the source, and the
engine translates the name inside it. A literal inside `Query{}`, `Pattern{}` and the other
resolvable literals is left alone: there it is code, not data.

Two places mix text and code, and the literals plane serves them apart. The first is **the name
of a named group** of a pattern, `(?<Name>...)`. That is a name of the project: the code reads the
group back by it, with `Group("Name")`. Both sides take the spelling from one source, the literals
plane first and the ordinary name resolution after. Let them part, and the call asks for a group
the pattern never declared. The second is **the presentation template** of an event kind, prose
with expressions inside it. The expressions are renamed as names, while the text itself comes from
the literals plane by the whole value. What the plane does not name goes into the gap report
instead of staying in the source language silently.

The suffixes of a duration literal in code move to their English spellings by themselves, so
`300мс` becomes `300ms` and `2д14ч30м5с6мс` becomes `2d14h30m5s6ms`. The Russian set comes from
the type's documentation, and the English one is confirmed by the platform compiler. A number
glued to any other letters is left alone.

The same plane serves every yaml value the metamodel declares a localizable text
(`Localizable`). The presentations of commands, access privileges and enumerations are read by a
person on the page, so each is either named whole by an entry or reported as a gap. The one
exception is the `Description` property: it is developer documentation, so it stays data and never
enters the gaps.

Names are translated whole rather than word by word. The word order of an English name is the
reverse of the Russian one, and the parts of a Russian name are declined, so gluing per-word
translations produces calques. Comments are translated line by line: an edit next to a line does
not invalidate it, and one entry serves every repetition. The finished comment block is re-wrapped
to the project's width, the same one `style/line-length` uses, because a translation that grew
longer than its original would otherwise run past the limit. Frames and separators, lists, tables
and code samples stay as they were, and so do lines that were long in the source already.

The dictionary is a directory of yaml files, or one file, named `xbsl-translation` and discovered
next to the project or above it. To fill it, drop a completed stub next to the ones already there.
Two files disagreeing about one key are refused at load time.

**A qualified entry** (`Dictionary.Key: SignIn`) applies inside one namespace only. A key of a
localized-strings dictionary may need a spelling the same word cannot have in code.

## Names the project declares are the project's

A word the platform dictionaries also know may be what the project called its own thing: an
enumeration value, an attribute, a method, a dictionary key. Only the project dictionary answers
such names. Without that check a use would move to the English spelling while its declaration
waited for a dictionary entry. The yaml would still declare the Russian value, the module would
already call the English one, and the build would refuse the tree. With the check both halves move
together, or both wait for one entry.

The exceptions stay with the platform: the built-in items a collection dispatches by name, which
are the standard code, name and owner attributes, and the facet after a dot in a type
expression.

## What is left alone

Data. Labels, descriptions and any other text a user reads stay as written: the platform's own
mechanism localizes them, and the translated project keeps the same dictionaries. String literals
stay too. The exception is the code inside their interpolations, which is re-tokenized and
translated like any other code. `Id` values never change, because the translated tree is the same
project rather than a copy of it.

A string literal that equals a renamed name is reported as a warning. A method called by its name
from a string breaks silently when only the declaration is renamed.

A second warning of the same kind is `literal-data-value`. It marks a literal that equals a value
from a json resource of the project and was moved by a literals-plane entry. Such a literal is
usually compared against that data, in a seeding parse, and data is never translated. After the
move the comparison silently stops matching. When the literal really is data, mark that explicitly
with an entry whose value equals its key: the coverage is counted, the text does not move, and no
warning is drawn. The report prints the warnings as a list: file, line, kind and text.

There are two exceptions, and both are a name written a second time, outside the code.

**The keys of the project's own json resources that name a field of its structures.** A structure
reads json by field name, so such a key is the same name written again. Rename the field, leave
the key, and the binding finds nothing - silently, because the reading options tolerate an unknown
property and initialize a missing field. The project compiles, applies and starts with empty data.
Those keys go through the same dictionary as the fields. Values, and keys no structure declares
such as a map keyed by content or an external contract, stay as written. The number of renamed
keys is part of the run's summary.

**A literal that spells a resource path**, such as `"Значки/%Код.svg"`. The pass renames the
resource files and directories, and a path has to follow them or the platform stops finding the
resource. Only a literal shaped like a path qualifies: it ends with a known resource suffix and
every segment reads as a file name. A regular expression, with its slashes and named groups, does
not qualify and stays data.

## Prose inside a resource file

A comment in a `.css`, `.js`, `.html` or `.svg` is a phrase like a comment in a module. Such files
used to be copied byte for byte: Russian prose reached the English build untouched, and `--strict`
called the file covered, because there was nothing in it to count.

What the pass reads in them:

- `/* */` and `//` comments in `.css` and `.js`;
- `<!-- -->` comments in `.html` and `.svg`;
- the text of `<title>` and `<desc>` in an `.svg`: a screen reader speaks those words and a
  browser shows them in a tooltip;
- the comments of an embedded `<style>` or `<script>`.

A phrase is keyed the way a module comment is keyed: the marker and the decoration come off, and a
block is read line by line. One sentence written both in a module and in a stylesheet takes one
entry. The gap shows up under `--gaps`, counts towards the coverage, and fails `--strict`.

Selectors, property names and their values, attributes, identifiers and the text of the page stay
as written. The file is scanned character by character, so a marker inside data opens no comment:
`content: "/*"`, an unquoted address in `url(...)`, a template literal, a regular expression such
as `/[/*]/`. Markup goes through the standard library's html parser, which knows
that `<!--` inside an attribute value opens nothing.

Two borders are drawn on purpose. A comment that carries a licence is left alone: its wording is a
legal text, and a translation of it says something the original does not. A minified `.css` or
`.js` is skipped whole: it is build output, a banner is all that is left of its comments, and
nobody edits a file like that. A file counts as minified when its longest line runs past five
hundred characters.

## The written tree is a repository

`--out DIR` makes DIR a repository root: the project lands in `DIR/{Vendor}/{Name}`, the two names
its translated descriptor carries. That is the only layout a build accepts, since it packs the
files under `{vendor}/{name}` and refuses a directory named otherwise. So the tree that comes out
deploys as it is, with nothing moved by hand. The names are the translated ones: a project whose
own name is a Russian word changes it in the pass, and the directory follows.

An `out` that already ends in those two names (`--out build/acme/tasks`) is taken as the project
directory itself and is not nested a second time, so the path people wrote by hand before this
existed keeps working. A tree with no descriptor, meaning a fragment translated on its own, is
written where it was asked for. The log line names the directory the files actually went to.

A second run into the same directory simply rewrites the tree, and the directory is recognised by
its descriptor, `Project.yaml` or `Проект.yaml`. A directory holding someone else's files is not
touched at all: the run says which directory it is and what to do about it. A single file that
could not be written is named in the report with its reason rather than killing the pass. Usually
the obstacle is a leftover of an earlier run: a directory where a file goes, a read-only file, a
file held by another program. The report is printed whole, with the first five such files named
and the rest counted. A run that failed to write the tree exits non-zero even without `--strict`,
because the tree is its job.

**`--clean`: the leftovers of an earlier pass.** The rewrite covers the files this pass produces
and touches nothing else, so a source file that was renamed or removed leaves its old translation
standing in the output tree. A build takes the directory whole, and the orphan ships with
everything else. Worse, the leftover can stand exactly where a file now goes: a directory in the
place of a file is the write error above. Before writing, `--clean` takes out everything this pass
is not about to write:

```sh
xbsl translate e1c/app --out build --clean
```

It is opt-in because it removes files. Writing into a temporary directory and swapping would not
replace it: the swap has to delete the old tree anyway, it costs a second full copy of the
project, and it breaks on the very conditions the write errors come from, another volume or a
directory held open by a build. The refusal of a directory holding someone else's files stays the
safety net above it. The cleaning happens only inside a directory that already is a translated
project, so `--clean` cannot become "erase whatever you were pointed at". A removal that fails is
a named problem, exactly as a failed write is. The count of what was removed appears in the report,
and in `removed` of the json, only when something was, and every leftover is named under it: a
count answers nothing about what a build just lost.

**`--dry-run`: see it before it happens.** The first clean of a translated tree is otherwise a
blind step. The flag takes the pass up to the writing and stops. The tree is built, the
destination is judged - an occupied directory is refused here as it would be for real - and the
leftovers are listed. Nothing is written and nothing is removed.

```sh
xbsl translate e1c/app --out build --clean --dry-run
```

```
DRY RUN: nothing written and nothing removed
files to be written: 1261 -> build/Acme/TaskBook
leftovers of earlier passes to be removed: 2
  Forms/OldForm.yaml
  Main/Resources/percent.svg
```

The text report names the first twenty and counts the rest. The json payload carries `dry_run`,
`planned` (the size of the tree the pass would write) and `removals`, all of them. Without `--out`
there is no tree to describe, and the flag is refused rather than ignored.

## Localized strings turn around

A project that already carries the target language in its localization sections gets those values
as its base, with the keys translated. The original values move under `Localization/<Code>/`, and
the project descriptor's default and development languages follow. A key with no value in the
target language keeps the original one and is reported.

## Coverage and the gaps

`--coverage` prints the dictionary's share for every metadata object, meaning the yaml and xbsl
family that shares one stem, and for the project as a whole. `--missing` writes what is left as a
dictionary stub: entries ordered by frequency, each annotated with its count and first location,
values empty and ready to fill.

Three counters are kept apart on purpose. The first is the dictionary's coverage, the number a
team fills towards 100%. The second is the platform data gaps, which no dictionary entry should
paper over. The third is the Cyrillic scalars left alone as data, listed so a reviewer can confirm
they really are data.

The dictionary is discovered next to the project and above it. A root with none is refused, and
the message names the places looked at, plus a dictionary found below the root if there is one.
`--dictionary` names the dictionary explicitly, as a file or a directory. `--target` names the
file new entries land in, `090-manual.yaml` by default. `--comment` is the head line such a file
is created with, which is the place to say what the batch is about. `--format json` hands the
whole report to a machine. `--no-localization-swap` leaves the localized-strings layout as it is,
for a project that translates its sources but keeps its language layout.

`--strict` exits non-zero unless the coverage is complete and no problems were found, which is
what a CI job wants before it publishes a translated build. A name collision is one such problem.
Two different names of one namespace translated into one word break the build, because the
platform refuses a repeated name, and only the translator can see it coming. Every colliding name
is reported with its own place, as in
`method:RolesString - 'Number' <- ... (Module.xbsl:2:9), ... (Module.xbsl:5:13)`. A namespace on
its own would leave the reader to find two words among the fifteen a method declares, and the two
are rarely neighbours.

Two more problems come from the dictionary itself, and both were found on a real project whose
English build failed while the coverage stood at 100%. The first is an entry that spells a platform
member as the platform spells it nowhere, such as `Важность: Severity` against the event's
`Importance`. It is reported at the first place where a receiver of known type proves it. There the
platform spelling is taken, but a receiver whose type nothing names gets the entry's word, and the
compiler refuses it. The cure is the platform spelling in the entry. A word the platform itself
spells two ways is not judged: `Загрузить` is `Load` on a binary object and `Upload` on the object
storage, and an entry matching either names nothing wrong. The second problem is a named literal
whose substitutions differ from its key's after translation, such as `%{AccountCode}` where the
field translates to `SubscriberCode`. It is reported with both lists, because the names inside
`%{...}` must translate the same fields in either language.

## In the editor

The rule `conventions/missing-translation` - info, off by default, project scope - shows the same
gaps where they stand. A name or a comment line the dictionary does not cover gives one finding at
its first occurrence in the file. The rule stays silent unless a dictionary is discovered, so it
only speaks in a project that translates its sources. Enable it with
`--enable conventions/missing-translation`, or in the editor with the Linter: Enable setting.

The finding carries the dictionary key, its kind and the suggestion, so the **lightbulb** offers
to write the translation without leaving the file. "Translate as ..." takes the platform spelling
in one click. "Translate ..." asks for the word. A third action opens the dictionary table filtered
by that key. The project is re-checked once the entry is written, with no restart.

**The dictionary table** opens with the "XBSL: translation dictionary" command and lists the
entries next to what the sources do not cover yet: kind, key, translation, the number of
occurrences, the first place and the dictionary file. Each record takes two lines, with the
translation field stretched under the rest at the full width of the row. The field is edited in
place. A search box and an "only empty" switch narrow the table. A suggestion - the platform's own
spelling first, an external service's guess otherwise - stands grey inside an empty field and goes
in on a click or on `Enter`. The table reads `--table`, which yields the entries, the gaps and the
coverage out of one pass over the project, and it writes through `--set`. A written cell does not
cost another pass, only a re-read of the dictionary, and the header counters step forward by what
that edit changed. The "Re-read" button replaces them with freshly counted ones. The panel needs
**xbsl 0.72.0 or newer**, because `--suggest`, the machine-translation run behind its suggestions
button, only arrived there. The **"Suggest via translation service"** button in the same panel
fills empty fields with an external service's guesses; details are in
[Machine translation](#machine-translation) below.

## Filling the dictionary from the tools

The dictionary of a large project runs to thousands of entries, and reading those files to add
one word is both slow and error-prone. Every surface therefore works in pages, over the same
engine core.

**The CLI** answers the same questions the panel asks:

```sh
xbsl translate e1c/app --gaps --kind token --limit 20      # what is missing, most frequent first
xbsl translate e1c/app --entries --filter Задач            # what the dictionary already says
xbsl translate e1c/app --table --limit 0                   # all three: entries, gaps, totals
xbsl translate e1c/app --set правки.yaml                   # apply a batch file (see below)
xbsl translate e1c/app --unused                            # entries the project no longer uses
xbsl translate e1c/app --stale --filter ПодсказкаТарифа     # the same, about the names of one deleted component
xbsl translate e1c/app --redundant                         # entries the platform answers itself
```

`--table` answers all three questions in one pass, and that is what it exists for. The editor table asks exactly those three. Asked apart they are two identical walks over the sources in two processes, plus a third reading of the same dictionary.

`--set` takes the batch as a file in either shape. One is the dictionary's own yaml format:
`tokens`, `phrases` and `literals` sections, the same quoting as the dictionary files, and an
empty value removes the entry. The other is the JSON list `[{key, value, kind}]` that scripts
produce. A batch of hundreds of entries is authored the way the dictionary itself is written,
rather than as JSON on the command line.

`--unused` answers the question opposite to `--gaps`. That one shows what the project needs and
the dictionary lacks; this one shows what the dictionary still says and the project no longer has.
Deleting code leaves its names and comment lines behind, and nothing else reports them. `--strict`
judges what is not covered, and `--entries` shows where a pair is declared rather than whether
anything uses it. `--prune` removes exactly the rows it just listed, so `--kind`, `--filter` and
the page apply to the removal as well. A page cut by `--limit` is called out, because removing
"everything" while looking at fifty rows of three thousand is not what the flag looks like it
does.

`--stale` is the same flag under the name the question is usually asked by. `--filter` is what
makes the answer a worklist: after a deletion the question is about the names of that one
component, not about the whole history of the project.

`--since` answers the question a task asks at its end: what its own change left behind, rather
than what the dictionary has accumulated over the life of the project. The answer holds the keys
the project no longer spells anywhere and that occurred nowhere but in the lines that change
removed. `--prune` beside it removes exactly those. A branch or a commit is read from the fork
point with HEAD to the working tree, so work not committed yet counts as part of the change. A
range `A..B` is handed to git as written, which is how a change already merged is examined.
Measured on a live project: 3297 orphans without a filter, 18 of them the change's own, nine names
and nine comment lines. One call instead of nineteen calls with `--filter` a name at a time.

The narrowing is an intersection rather than a shortcut: a name the project still spells does not
become an orphan however generously the diff reads. So an answer with neither a filter nor
`--since` carries a caveat. The reading is textual, and the list describes the whole accumulated
dictionary, which makes it something to read through rather than to prune wholesale.

The reading is textual, and the direction of its error matters. A name that also occurs in prose
may be counted as used, which merely leaves an entry in place; a live entry is never called an
orphan. A comment line is keyed by the translator's own payload reading, with markers and
decoration taken off exactly as the writing pass takes them. A name is looked for in the file
names as well, since a folder and a file go through the same token plane. A qualified key
(`<Owner>.<Name>`) is judged by both halves: the sources spell them apart, and reading the dotted
text as one name would call every such entry an orphan.

`--redundant` is the other mirror of `--gaps`. It shows a word the dictionary spells exactly as
the platform spells it anyway. Such an entry breaks nothing: the tree comes out word for word the
same without it. It is worth listing for another reason - it answers in place of the platform
data, so a hole in that data, or in this engine, stays hidden behind it. One live dictionary
spelled the languages of its own project descriptor that way, and the half-translated enumeration
behind that pair was found by a test on an empty dictionary, never by the project. The plain
report says how many there are without being asked, and `--prune` removes exactly the rows the
flag just listed.

Unlike `--unused`, this one runs the full pass, and its verdict rests on evidence rather than on a
second reading of the tables. An entry is listed only when every place it answered would have come
out the same without it. So a pair that carries one position of its own is never called redundant;
that happens with a word the platform spells in one role and not in another. An entry the project
never uses is not listed here at all, because that is the orphan question and `--unused` answers
it.

`--gaps` shows the count, the first places to look at and `suggestion`, the platform's own
spelling where it has one. A suggestion stays a hint: a name the project declared may deliberately
need a different word. An internal platform name, such as the metadata class `CodeAttrMd`, is
never offered at all.

**The MCP tools** are the same six, for an agent that fills the dictionary:

- `translate_status` - coverage and what is left, the cheap check before deciding anything;
- `translate_gaps` - the untranslated entries by page (`kind`, `filter`, `limit`, `offset`),
  the answer naming the `dictionary` it read;
  `compact` returns only `{key, kind, count}` per row - the worklist shape that fits an
  answer when the full rows would not;
- `translate_entries` - what the dictionary already says, with the file and line of each
  entry, so a new word stays consistent with the accepted ones;
- `translate_unused` - the opposite question: what the dictionary still says and the
  project no longer has; `filter` narrows it to the names of one deleted component, `since`
  to the orphans of one change (a branch, a commit or a range `A..B`), `prune` (off by
  default) removes exactly the page the tool answers with, `compact` keeps only the key, the
  kind, the file and the line, and `counts` sizes the orphans by kind; an answer with neither
  `filter` nor `since` carries a `note` saying what its reading is worth;
- `translate_redundant` - the entries the platform answers itself, which the pass would spell
  the same way without them: the workarounds that hide a gap in the platform data or in the
  engine. `filter` narrows it, `prune` (off by default) removes exactly the page it answers
  with; unlike `translate_unused` it runs a full pass, because the verdict rests on the places
  the entry actually answered;
- `translate_set` - write entries back: add, correct in place, or remove by emptying a
  value; `edits_file` sends the batch as a file in the same two shapes `--set` reads.

Every page states what it left out. `total: 72` beside exactly fifty rows reads as a complete
answer, and a dictionary built from one such page came out twenty-two entries short. The strict
pass found them after the merge. So a cut page carries `truncated: true`, `remaining` and a `hint`
naming the next `offset`. `limit=0` returns the whole list, and for the gaps there is also
`--missing`, which writes the entire remainder to a file as a dictionary stub.

A new entry lands in `090-manual.yaml`, or in the file named by `target`, while an entry that
already exists is corrected where it lives. The writer never duplicates a key, and a duplicate
with a different value is refused when the dictionary loads.

## Machine translation

Filling a large remainder by hand is slow, so `--suggest` takes the untranslated remainder to an
external translation service. What comes back are suggestions, not writes: the dictionary does not
change until a suggestion is accepted. From the console `--suggest-out` accepts them; in the
editor a click or `Enter` on the hint in the table does.

```sh
xbsl translate e1c/app --suggest                                  # report: what the service offered
xbsl translate e1c/app --suggest --provider yandex                # pick the service explicitly
xbsl translate e1c/app --suggest --suggest-out 080-machine.yaml   # write the plan next to the dictionary
xbsl translate e1c/app --suggest --plans tokens                   # fill names only, not comments
```

A run always covers the whole project. Nothing caps it, nothing stops it midway, and its size
cannot be estimated beforehand. Meanwhile every batch it sends is a paid call to the service.

`--suggest-out` names the plan file the offered records are written to. The directory part of the
path is dropped, only the file name is kept, and the file lands inside the dictionary directory.
When the dictionary is a single file there is no separate plan to make, and the records go into
that file itself.

Without `--provider` the engine takes the one service that is configured. With none configured,
the refusal names the missing environment variables. With more than one configured, the refusal
lists the services themselves, `google` and `yandex`, and asks for a choice with `--provider`. The
engine does not guess silently in either case.

**Two services, and they are not interchangeable.**

- **Yandex Translate** - authorizes with a service-account key and a folder id, both required.
  The batch limit is 10,000 characters per request. It understands a glossary, so the project's
  term list travels with the request itself.
- **Google Translate** - authorizes with one key alone, and its batch limit is 5,000 characters.
  Its API has no glossary at all, so the term spelling is enforced afterward, when the engine
  builds a name out of the returned prose.

Whatever either service allows, one request carries at most 100 texts. That is the engine's own
conservative bound. A batch turned away for its size costs exactly as much as one that is
accepted, and the character sum alone would let six hundred one-word names ride in a single
call.

**Keys live in the environment, never on a command line or in a setting.** Three variables,
named after the service each belongs to:

- `XBSL_TRANSLATE_YANDEX_KEY`, `XBSL_TRANSLATE_YANDEX_FOLDER` - the Yandex key and folder, both
  required;
- `XBSL_TRANSLATE_GOOGLE_KEY` - the Google key, alone.

The editor needs no environment variables of its own. The **XBSL: Set a machine-translation key**
command (`xbsl.translate.setKey`) asks which of the three to set and stores the value in the
extension's SecretStorage. From there it is passed to the engine in the environment of the
`--suggest` run itself, never in a setting and never on the command line. The
`xbsl.translation.provider` setting picks the service when both are configured, and it never holds
the key itself.

**The cache** is a `machine-cache.json` file next to the dictionary: inside the `xbsl-translation`
directory when the dictionary is one, otherwise next to the single dictionary file. It stores the
service's raw answer, keyed by service, language, glossary fingerprint and text. It does not store
the finished name, because the name-building rule and the term list still change, and paying the
service again for the same sentence over a rule change would be absurd. The format is JSON rather
than yaml for a reason: the dictionary loader collects `*.yaml` recursively, and a yaml cache file
would be read as another dictionary plan with duplicate keys. An entry stays in the cache whether
or not the suggestion was ever accepted into the dictionary, so a repeated `--suggest` never pays
twice for the same text, even one nobody accepted last time.

**The dictionary's `terms` section** is a short "Russian term -> English spelling" list. It is not
a translation plan and it does not count toward coverage. It feeds two things: the glossary pairs
sent with the request, which only Yandex takes, and the spelling used when a name is built. The
second half works on the answer. Building an identifier, the engine matches every English word the
service returned against the term list, ignoring case, and puts the dictionary's spelling in its
place wherever the word stands in the phrase. Russian word forms are not analyzed at all. A term
the service answered in another English word, a plural or a synonym, is not recognized and stays
as it came. Terms do not touch comment lines (`phrases`) at all: a comment stays exactly what the
service answered.

**The engine builds the names, not the service, and it builds them by fixed rules.** The service
answers in prose, such as "Site address", while the `tokens` plan needs an identifier. The engine
drops stop words (a, the, of...), substitutes a term's spelling where one is known, then
title-cases and glues the rest. A name already taken by another dictionary key is refused with a
named reason, and so is prose that yields no identifier at all. The engine never guesses and never
overwrites.

**Literals never reach the network.** `--suggest` sends the service only `tokens` and `phrases`
gaps, meaning whole names and whole comment lines. A string literal is filled separately, and only
when its text matches an already-accepted name exactly. That happens locally, with no request at
all.

**What is sent.** The service sees only the gap's own text: a name as the project wrote it, or a
whole comment line. It never sees a file path, the code around it, or the rest of the project.
Without a key the command sends no request at all, to either service. It refuses immediately and
names the variable that is missing.

The report prints the same way `--set` does. `cached` is how many answers came from the cache,
`requested` is how many were asked for again, and `refused` is how many were turned down, each
with its reason.

In the editor the same three numbers stay in the panel's own summary line until the next run.
Before, they lived only in a status-bar message that closes itself in a few seconds. A hover on
that line names each refusal's reason. When there was nothing left to ask, the line says so in
words instead of three zeroes, and when every offer came from a local literal match without a
single request, it says that too.
