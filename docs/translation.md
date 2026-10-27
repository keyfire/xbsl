---
title: "Translating a project"
description: "Rewriting a project into English spellings: what the 1C:Element data provides, what the project dictionary answers, how coverage is measured and how a CI job checks it."
sidebar:
  label: Translation
  order: 6.5
---

The `xbsl translate` command converts 1C:Element project sources to English spellings.
1C:Element keywords, metadata keys, types, members and enumeration values have Russian and English
spellings. Translation uses the extracted [1C:Element data](platform-data) and a project dictionary
maintained by the development team.

```sh
xbsl translate e1c/app                          # report only: coverage and what is missing
xbsl translate e1c/app --coverage               # plus the breakdown per metadata object
xbsl translate e1c/app --missing gaps.yaml      # the untranslated remainder as a dictionary stub
xbsl translate e1c/app --out build            # write the translated tree (into build/e1c/app)
xbsl translate e1c/app --out build --strict   # non-zero exit unless it is complete
```

## What answers what

**Built-in names come from the 1C:Element dataset.** Keyword case is preserved: `Если` becomes
`If`, and `если` becomes `if`. A yaml key uses the English spelling declared by its metamodel
class. The same word can therefore have different spellings in different nodes. An enumeration
value is looked up within its own enumeration: one Russian value can have several English
spellings across enumerations.

A type expression retains its structure and facets: `.Ссылка` becomes `.Reference`. This applies
to yaml and code wherever the parser reads a type: parameters, declarations, constructors, casts
and type arguments. The same word after a dot in another position is a member. On a receiver
holding a project-object facet, or a chain that loads a record, the reference member also becomes
`Reference`. The link property of a label or picture is written as `Link`. A value matching a
member of a union-typed property, such as `Auto` in `Auto|Number`, uses that member's spelling
from the 1C:Element type name pairs.

`Query{ ... }` blocks use the query vocabulary. A name missing from the data remains unchanged
and is reported as a data gap. If a chain link is declared as `A|B`, its owner cannot be
determined: analysis stops at that link and the following word is read without an owner.
Expressions inside string interpolation are processed as code in the enclosing method, including
chains. For example, `"%{Объект.Товары.Граница()}"` is processed like the same expression outside
the quotes.

**Project names are translated using the dictionary.** The dictionary contains translations for names
declared by the project: objects, methods, attributes, form components, dictionary keys, resource files, and an
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

A phrase key is one comment line without its marker, indentation or escaping. In the `literals`
plane, keys and values retain the escaping used in the source code. If a phrase key is supplied
with an escaped quote by mistake, `--set` and `translate_set` normalize it and report the change
in `normalized`. They also remove whitespace around a value; the translator restores the line's
indentation. A rewrite that changes only a value's whitespace is marked `whitespace_only` in
`rewritten`. A multiline key is rejected because each comment line is translated separately.

A new file uses four-space indentation. When writing to an existing section, the tool copies the
indentation of adjacent entries, so a different indent, such as two spaces, is preserved. This
applies to edits from the panel and through `--set`.

The third plane - `literals` - is about the string literals of the code:

```yaml
literals:
    "Файл не загружен": "The file was not uploaded"
    "Не заполнено поле \"Наименование\"": "The \"Name\" field is empty"
    "Не разобрано тело: %{Описание}": "Could not parse the body: %{Описание}"
```

The translator replaces only literals listed in the dictionary. Keys and values are written as
the text between the source quotes, with the same escaping. A value that is not a valid literal
body is rejected when the dictionary loads. An interpolation in the value is written as in the
source; the engine translates the name inside it. Literals inside `Query{}`, `Pattern{}` and
other resolvable literals are left unchanged because they contain code.

The `literals` plane also applies to two cases where text is associated with code:

- **The name of a named group** in a pattern, `(?<Name>...)`. Code refers to the group by name,
  for example through `Group("Name")`. The group name and the call argument use the same source:
  the literals plane first, then ordinary name resolution. This keeps the declaration and the
  reference consistent.
- **The presentation template** of an event-log event kind. Expressions in the template are
  translated as names; its text uses a literals entry for the entire value. If there is no entry,
  the text is included in the gap report.

The suffixes of a duration literal in code move to their English spellings by themselves, so
`300мс` becomes `300ms` and `2д14ч30м5с6мс` becomes `2d14h30m5s6ms`. The Russian set comes from
the type's documentation, and the English one is confirmed by the 1C:Element compiler. A number
glued to any other letters is left alone.

The same plane serves every yaml value the metamodel types a localizable text (`Localizable`) -
every one of them, not the presentations of commands alone. `Presentation` is such a property on
some fifty classes: a catalog, a document, an attribute, a dimension, a resource, a command, an
access privilege, a value of an enumeration. Beside it stand the titles of the application
(`AppTitles`), the messages that ask the user for a permission (`PermissionRequestMessages`), the
presentations of a catalog's groups (`CatalogGroupPresentation`), the `ActivePresentation` and
`InactivePresentation` of a switchable command, and the presentation templates of an event-log
event - `PresentationTemplate` and the `BeginPresentationTemplate`, `EndPresentationTemplate` and
`ErrorPresentationTemplate` beside it. A person reads each of those on the page, so each is either
named whole by an entry or reported as a gap. The one exception is the `Description` property: it
is developer documentation, so it stays data. Only a description containing a `%{...}` substitution goes through the plane the way a template does, and then its gap is listed.

A gap in any of those texts fails `--strict`, because the English build would show that text in
Russian. Any other gap of the plane is listed and fails nothing: a string literal of a module or
of an `=` expression, a text with a `%{...}` inside a component tree, a description. Only the
project can tell its data from its messages there. An `=` value is code, so its string is keyed
between its own quotes, as in a module.

The engine translates the deprecation mark itself. The naming standard starts the caption of a
deprecated element with `(не используется)`, and `naming/presentation` asks an English project
for `(not used)`, so the English tree uses that mark instead. When a dictionary entry
leaves the mark out, the translator puts it in front of the entry's text. A text without an entry
changes only its mark and stays a gap. A report's presentation, which the translator keeps as
data, changes its mark the same way. An entry that starts with a bracket of its own is written as
it is, and the rule points at it in the English tree.

The prefix of a deprecated name is the engine's as well. The standard starts such a name with
`Устарело`, and a file of the English tree keeps nothing else of the Russian name: the rule recognizes a deprecated element there by the prefix `Deprecated`. So the translator keeps the prefix
regardless of the entry's translation. An entry that starts with `Deprecated` is written as it is, and any other
one gets the prefix in front: `УстарелоКурсы: Rates` and `УстарелоКурсы: ObsoleteRates` give
`DeprecatedRates` and `DeprecatedObsoleteRates`. The file of the element and every use of the name
follow. A name that only begins with the same letters, the head of a longer word, keeps its entry.

A text meant to read the same in both languages - a product name, a code, a word English borrowed
whole - is named by an entry whose value repeats its key:

```yaml
literals:
    "Цена товара": "Цена товара"
```

The pass writes the text back as it was, the plane counts it as named, and `--strict` has nothing
to report. Neither `--unused` nor `--redundant` touches such a pair: the pass uses it, and the
1C:Element data has no corresponding entry.

Names are translated whole rather than word by word. The word order of an English name is the
reverse of the Russian one, and the parts of a Russian name are declined, so gluing per-word
translations produces calques. Comments are translated line by line: an edit next to a line does
not invalidate it, and one entry serves every repetition. The finished comment block is re-wrapped
to the project's width, the same one `style/line-length` uses, because a translation that grew
longer than its original would otherwise run past the limit. This applies to `//` and `///` lines
and to a `/* ... */` comment alike. Such a comment keeps `/*` at the head of its first line and
`*/` at the end of its last one. Frames and separators, lists, tables and code samples stay as
they were, and so do lines that were long in the source already.

A line of a documentation comment that opens a tag - `@параметр Коды - Коды для проверки.` - is
looked up whole first, and a pair written for the whole line takes precedence. Without one the line is
translated by its parts: the tag word becomes the English one (`@parameter`, `@returns`,
`@throws`, `@see`), the name after `@параметр` or `@выбрасывает` is translated the way the code
translates it, a reference written as names (`@см Модуль.Метод`) is translated as names, and only
the text after the name is a phrase, keyed by that text alone. A parameter renamed in the tokens
section then moves in the tag together with the signature, and a name without a pair is a gap
like the same name in the code. The re-wrap never glues a tag to the line above: the environment
reads a tag from the start of a line, so a tag and the lines that continue it are re-flowed as a
paragraph of their own.

A line of code that the English names pushed past the limit is wrapped the way the style guide
wraps an expression: after a comma between arguments, parameters or collection items, after the
opening bracket of such a list, or before an operator, which then opens the next line. The places
come from the parse tree, so a comma between type arguments never becomes one. The continuation
is indented one step deeper. A line with a comment after the code stays as it is, and so does a
line that `style/line-length` reports in the source already. The pass checks its own result: the
tokens of the module and its parse tree must not change.

The dictionary is a directory of yaml files, or one file, named `xbsl-translation` and discovered
next to the project or above it. To fill it, drop a completed stub next to the ones already there.
Two files disagreeing about one key are refused at load time, and so is one file that declares a key
twice with two translations.

The refusal names every such key at once - the section, the key and the translation in each file -
rather than the first one it meets. Two branches once closed the same gaps in files of their own;
each pipeline was green, and the merged dictionary failed to load with ten keys translated twice,
four of them differently. Taken one at a time, that was four loads.

A place is a file and a line, which makes a key repeated inside one file a collision of the same
kind. The yaml parser keeps only the last value of a repeated key and does not report the earlier value,
so the dictionary files are read with the line of every key. A repeat with two values is refused
along with the other conflicts, and a repeat of the same value is a redundant copy. The same key in
two sections is not a repeat, and a section head written twice in one file reads as one section, the
way the entries table reads it. Measured on a live dictionary of 167 files: no key repeats inside a
file, and the load takes no longer than before.

`--check-duplicates` reports conflicting translations with exit code 1 and identical
duplicates with exit code 0. Every occurrence retains its file and line.

`--against REF` compares the working dictionary and the ref through their common Git base.
One-sided edits, removals and tracked renames do not resurrect an unchanged base copy.
Competing values for the same key and independent new duplicates are reported. Delete/edit
and ambiguous rename cases are refused. Stage a rename before comparing it: an untracked
destination is a new file, not proof of a rename. Unrelated histories are refused too.

`--format json` returns `conflicts` and `duplicates` as
`{section, key, places: [{file, line, value}]}`. The `against` object contains `ref`,
`merge_base`, `files` and `added`; `added` counts records selected from the ref. Such
records use `REF:file` labels and their original line numbers. This checks translated keys,
not all Git merge conflicts in file headers or comments.

`--strict` needs no separate flag: a conflicting working dictionary cannot be loaded.
Identical duplicates are counted in the ordinary summary.

**A qualified entry** (`Dictionary.Key: SignIn`) applies inside one namespace only. A key of a
localized-strings dictionary may need a spelling the same word cannot have in code.

A method-qualified entry applies to that method's locals, including its parameters. It does
not rename aliases inside `Query{...}`: the alias and an access to its result field use their
common spelling. A catch variable annotated with `Exception` also participates in typed member
resolution, so its `Cause` property keeps the 1C:Element spelling when a project field uses a
different dictionary entry for the same source name.

When translated comments are wrapped, deeper-indented lines under a list item stay separate.
This applies to both line comments and block comments. A blank comment line ends the list
continuation; ordinary prose after it can be wrapped again.

## Names the project declares are the project's

A project name may match a word in the 1C:Element dictionary. It can be an enumeration value,
attribute, method or dictionary key. Such names are translated only through the project dictionary.
The declaration and its references receive the same spelling or remain untranslated until an
entry is added. This prevents a mismatch between a yaml declaration and references in a module.

Exceptions are the built-in collection items identified by name: the standard code, name and
owner attributes. A facet after a dot in a type expression is also an exception.

An overridden 1C:Element handler uses its built-in name. A method under `@Handler` named
like a handler in the 1C:Element lists is not a name of the project: the compiler finds the override
by its 1C:Element name. In a module that declares that handler, the declaration and the calls in
the module take the English spelling from the lists in the data. The module of an interface
component overrides what its base declares (`AfterCreate` for the after-create override); the
module of another element overrides what the compiler declares for its kind and module:
`BeforeWrite` and `OnCreateOnBasis` in the object module of a catalog, `Handler` in the module of
a scheduled job, `CheckHasAccessKeys` in the module of an access key, and the record-level
security handlers, such as `ComputeAccessPermissionsForObjects`, in the module of an entity. In
other modules the 1C:Element dictionaries translate the name. A project dictionary entry that spells
it otherwise is reported as a dictionary defect, and one that spells it the same way as redundant.
Data without the lists leaves such a name to the dictionary, as before.

A built-in type name is recognized wherever only a type can stand: in a type expression, at the root of a
static call and right before a facet, as in `Entity.Privilege`. A field, an attribute or a method
the project spelled the same way holds nothing there. Only a type the project declares under that
name answers to the dictionary, so its declaration and its uses still move together.

A name in scope is not a type either. A local, a parameter, a loop or `catch` variable, a lambda
parameter and a property of the module's own element may be spelled like a built-in type, and then
`Name.Member` keeps the spelling of the declaration. Such a word still reads as the type in a static
method, which has no element, and in a component method compiled on the server alone, which sees
only the contextual properties. The code inside a string interpolation belongs to its method and
sees the same names, types and dictionary entries.

A resource file is the project's name at every place it stands. The file of the tree, a yaml
property, a path in a string and the body of `Resource{...}` take the dictionary's word together, or
keep the file's own name together.

Pictures of the standard 1C:Element library are not files of the project. Each picture exists under a
Russian and an English name, and the English one goes to a reference the compiler resolves: the
value of a picture property and the body of `Resource{...}`. The library namespace may be written
or left out: `Стд::Аккаунт.svg` becomes `Std::Account.svg`.

A name without a namespace is first looked up among the project files; a matching project file takes precedence. A name with the library namespace always refers to the library.

A string path does not address library resources. A path in a string is read by `ПакетРесурсов.Текущий()`, the
resource package of the current namespace. So a string literal and a yaml value the schema types
as text stay as they were written, even when they spell a name of the library letter for letter.

The translator takes the English names from `resource_paths` in `uiterms.json` in the 1C:Element data, and
on data without that section a reference does not get them.

A method a component of the project declares, called through a node of a form, is the project's
word too, while a command of a built-in component keeps the spelling of the ui vocabulary.

## What is left alone

Data. Labels, descriptions and any other text a user reads stay as written: the standard localization mechanism
localizes them, and the translated project keeps the same dictionaries. String literals
stay too. The exception is the code inside their interpolations, which is re-tokenized and
translated like any other code. `Id` values never change, because the translated tree is the same
project rather than a copy of it.

A string literal that equals a renamed name is reported as a warning. A call using a method name from a string stops working without a warning when only the declaration is renamed.

The `literal-data-value` warning identifies a literal that matches a value in a project json
resource and is changed by a `literals` entry. Such a literal can be compared with the data, for
example when parsing initial data. The data is not translated, so changing the literal makes the
comparison fail. To leave the literal unchanged and count it as covered, add an entry whose value
matches its key. The report lists each warning with its file, line, kind and text.

The `short-pair` warning concerns a short comment line. A phrase pair applies to one line, but the
translation of one or two words depends on context. For example, `нет.` may have been translated
as `timer.` at the end of a sentence about a timer. If a comment contains untranslated lines and a
short line in that comment uses such a pair, the report warns on the short line. Each gap in that
comment includes `neighbors` in `--gaps` and `translate_gaps`, with short lines and their
translations for checking context. Consecutive lines with the same marker count as one comment; in
yaml, consecutive comment lines form one comment. No warning is issued when all lines are covered.

There are two exceptions, and both are a name written a second time, outside the code.

**The keys of the project's own json resources that name a field of its structures.** A structure
reads json by field name, so such a key is the same name written again. If the field is renamed but the key is retained, the data no longer binds to the field: the reading options skip the unknown property without a warning and initialize the missing field. The project compiles, applies and starts with empty data.
Those keys go through the same dictionary as the fields. Values, and keys no structure declares
such as a map keyed by content or an external contract, stay as written. The number of renamed
keys is part of the run's summary.

**A literal that spells a resource path**, such as `"Значки/%Код.svg"`. The pass renames the
resource files and directories, and a path has to follow them or 1C:Element stops finding the
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
as `/[/*]/`. Markup is parsed by the standard library's html parser, so `<!--` inside an attribute value does not open a comment.

Two borders are drawn on purpose. A license comment is left unchanged: its wording is a legal text, and a translation could change its meaning. A minified `.css` or
`.js` is skipped whole: it is build output, a banner is all that is left of its comments, and
nobody edits a file like that. A file counts as minified when its longest line runs past five
hundred characters.

## The written tree is a repository

`--out DIR` makes DIR a repository root: the project lands in `DIR/{Vendor}/{Name}`, using the two names from the translated descriptor. That is the only layout a build accepts, since it packs the
files under `{vendor}/{name}` and refuses a directory named otherwise. So the tree that comes out
deploys as it is, with nothing moved by hand. The names are the translated ones: a project whose
own name is a Russian word changes it in the pass, and the directory follows.

An `out` that already ends in those two names (`--out build/acme/tasks`) is taken as the project
directory itself and is not nested a second time, so the path people wrote by hand before this
existed keeps working. A tree with no descriptor, meaning a fragment translated on its own, is
written where it was asked for. The log line names the directory the files actually went to.

A second run into the same directory simply rewrites the tree, and the directory is recognised by
its descriptor, `Project.yaml` or `Проект.yaml`. A directory holding unrelated files is not modified: the command identifies the directory and the required action. A single file that
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

The text report names the first twenty and counts the rest. The json payload contains `dry_run`,
`planned` (the size of the tree the pass would write) and `removals`, all of them. Without `--out`
there is no tree to describe, and the flag is refused rather than ignored.

The table modes - `--gaps`, `--entries`, `--table`, `--unused`, `--redundant`, `--drift`,
`--suggest` - do not write a tree. So they refuse `--out`, `--clean`, `--dry-run` and `--missing` as well, and name
the run that does write the tree.

## Localized strings turn around

A project that already has the target language in its localization sections gets those values
as its base, with the keys translated. The original values move under `Localization/<Code>/`, and
the project descriptor's default and development languages follow. A key with no value in the
target language keeps the original one and is reported.

Only the translation into the target language swaps places with the base. Its folder is found
by the language code whatever the case of the name, the way 1C:Element finds it. A
translation into any other language (`Localization/Vi` next to `Localization/En`) keeps its
place: its keys follow the base keys through the same dictionary, and its values stay in its
own language. The English names of the languages come from the 1C:Element data, so a descriptor
that lists Vietnamese needs no dictionary entry for it.

## Coverage and the gaps

`--coverage` prints the dictionary's share for every metadata object, meaning the yaml and xbsl
family that shares one stem, and for the project as a whole. `--missing` writes what is left as a
dictionary stub: entries ordered by frequency, each annotated with its count and first location,
values empty and ready to fill.

Three counters are kept apart on purpose. The first is the dictionary's coverage, the number a
team fills towards 100%. The second is the 1C:Element data gaps, which no dictionary entry should
paper over. The third is the Cyrillic scalars left alone as data, listed so a reviewer can confirm
they really are data.

The dictionary is discovered next to the project and above it. A root with none is refused, and
the message names the places looked at, plus a dictionary found below the root if there is one.
`--dictionary` names the dictionary explicitly, as a file or a directory. `--target` names the
file new entries land in, `090-manual.yaml` by default. For a dictionary directory, pass a
filename only: paths with `/`, `\` or a drive prefix are rejected before any edits are written.
The MCP `translate_set` tool applies the same check. `--comment` is the head line such a file
is created with, which is the place to say what the batch is about. `--format json` returns the complete report as JSON for automated processing. `--no-localization-swap` leaves the localized-strings layout as it is,
for a project that translates its sources but keeps its language layout.

`--strict` exits non-zero unless the coverage is complete and no problems were found, which is
what a CI job wants before it publishes a translated build. A name collision is one such problem.
Two different names of one namespace translated into one word break the build, because the
compiler rejects a repeated name, and only the translator can see it coming. Every colliding name
is reported with its own place, as in
`method:RolesString - 'Number' <- ... (Module.xbsl:2:9), ... (Module.xbsl:5:13)`. A namespace on
its own would leave the reader to find two words among the fifteen a method declares, and the two
are rarely neighbours.

A built-in type a method reads as the root of a static access stands in the same namespace. A local
translated into the type's word hides the type in the English tree, so the pair is reported with
both places, and an entry qualified by the method (`Method.Local`) separates them.

Three more problems come from the dictionary itself, and all three were found on a real project whose
English build failed while the coverage stood at 100%. The first is an entry that gives a built-in
member a spelling absent from the 1C:Element data, such as `Важность: Severity` against the event's
`Importance`. It is reported at the first place where a receiver of known type proves it. There the
spelling from the 1C:Element data is used, but a receiver whose type nothing names gets the entry's word, and the
compiler refuses it. Use the spelling from the 1C:Element data in the entry. If the 1C:Element data has two spellings, matching either is not an error: `Загрузить` is `Load` on a binary object and `Upload` on the object
storage, and an entry matching either names nothing wrong. The second problem is a named literal
whose substitutions differ from its key's after translation, such as `%{AccountCode}` where the
field translates to `SubscriberCode`. It is reported with both lists, because the names inside
`%{...}` must translate the same fields in either language.

The third is a type the project itself declares under the spelling of a built-in type, with an entry that
renames it to something else. A type expression normally takes the built-in name over any name of
the project, but a type the project declares is the exception - its declaration and its uses have to
move together - so the entry answers every type expression of that spelling, the built-in type among
them. A palette node called `Образец` and an entry `Образец: Swatch` turned `new Образец(...)` of a
file that had never heard of the palette into `new Swatch(...)`, and the build answered
`Type "Swatch" is not defined`. No value repairs it and the cure is not a value: the project's type
has to be renamed. An entry that repeats the spelling in the 1C:Element data does not change a built-in name
and is left alone.

A localizable yaml text without its literal entry fails `--strict` as well - any value the
metamodel types `Localizable`, `Description` aside: a `Presentation` wherever it stands, the titles
of the application, a permission-request message, the presentation of a catalog's group, the two
presentations of a switchable command, the presentation templates of an event-log event. The build
accepts such a tree, but its pages would show the text in Russian. The report lists these texts
with their places, and the verdict line counts them. A text that has to stay in Russian is named
by an entry that repeats it as its own value (see above). No other gap of the literals plane fails
the check.

## The English of the dictionary

Coverage tells whether every name and every comment line has a translation. It does not tell whether
the translation reads as English. A mechanical edit of the values, such as a replacement run over
thousands of lines or a sweep that rewrote the Russian keys, leaves traces that `--strict` cannot
see. The rule `translation/english-shape` - warning, on by default, file scope - reads the values of
the dictionary files and reports three of them:

- an ending glued onto a word that takes none: an adverb, an irregular participle or an auxiliary
  spelled like a verb or a plural (`onlies`, `gones`, `hases`), and a regular participle in the
  plural (`loadeds`);
- a passive followed straight by a noun phrase without `by` ("a variable is shadowed the
  parameter"), where the subject and the object kept the places of the Russian sentence;
- capitals the Russian key does not have, such as "does NOT narrow" for a key that stresses nothing.
  A stressed word in the Russian key excuses them, and so does the same Latin word in the key.
  Abbreviations (`MB`, `URL`) and constants are not checked.

The finding stands on the word in the dictionary file and has no automatic fix; the author must choose the intended word. Only the files of the discovered dictionary are checked. A project without a dictionary gets no such findings, and a lint run over the directory that holds both the project and its
`xbsl-translation` checks the sources and the dictionary together.

In VS Code the findings appear even when `xbsl.projectRoot` narrows the checks to the project
folder. The extension sends the dictionary files to the language server as you type, and the server
adds the dictionary to the project-wide check.

Two rules of the `comment/` group read the dictionary too, because a `phrases` value is the English
line of a comment. `comment/first-person` reports "we", "our" or "I" there, and
`comment/emphasis-caps` reports capitals of emphasis: those a stressed key passed on to its
translation, a prefix in capitals ("UNfilled") and the article of a phrase in capitals. The capitals
a key without stress does not have stay with `translation/english-shape`, so a word is reported
once. Literals, tokens and terms are not read by them. Both rules are off by default and come with
`--enable comment`.

## In the editor

The rule `conventions/missing-translation` - info, off by default, project scope - shows the same
gaps where they stand. A name or a comment line the dictionary does not cover gives one finding at
its first occurrence in the file. The rule reports findings only when a dictionary is found, so it
only produces findings in a project that translates its sources. Enable it with
`--enable conventions/missing-translation`, or in the editor with the Linter: Enable setting.

The finding contains the dictionary key, its kind and a suggestion. The Quick Fix menu offers to write the translation without leaving the file. "Translate as ..." uses the 1C:Element spelling
in one click. "Translate ..." asks for the word. A third action opens the dictionary table filtered
by that key. The project is re-checked once the entry is written, with no restart.

**The dictionary table** opens with the "XBSL: translation dictionary" command and lists the
entries next to what the sources do not cover yet: kind, key, translation, the number of
occurrences, the first place and the dictionary file. Each record takes two lines, with the
translation field stretched under the rest at the full width of the row. The field is edited in
place. A search box and an "only empty" switch narrow the table. A suggestion - the 1C:Element
spelling first, an external service's guess otherwise - stands grey inside an empty field and goes
in on a click or on `Enter`. The table reads `--table`, which yields the entries, the gaps and the
coverage out of one pass over the project, and it writes through `--set`. A written cell does not
cost another pass, only a re-read of the dictionary, and the header counters step forward by what
that edit changed. The "Re-read" button replaces them with freshly counted ones.
The **"Suggest via translation service"** button in the same panel
fills empty fields with suggestions from an external service; details are in
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
xbsl translate e1c/app --drift                             # phrases naming a name otherwise than its pair
```

`--table` answers all three questions in one pass, and that is what it exists for. The editor table asks exactly those three. Asked apart they are two identical walks over the sources in two processes, plus a third reading of the same dictionary.

`--set` takes the batch as a file in either shape. One is the dictionary's own yaml format:
`tokens`, `phrases` and `literals` sections, the same quoting as the dictionary files, and an
empty value removes the entry. The other is the JSON list `[{key, value, kind}]` that scripts
produce. A batch of hundreds of entries is authored the way the dictionary itself is written,
rather than as JSON on the command line. The yaml is read by the loader of the dictionary itself,
so a batch a script dumps with every key in quotes (`yaml.safe_dump(..., default_style='"')`)
reads as well as one written by hand. A batch with no entries is refused, and the refusal names
the top-level keys the file has.

Writing a dictionary entry reports two kinds of warning that can be detected without checking
the project. The first concerns a value already used by another key in the same namespace. The
second concerns a key that matches a 1C:Element name. When the key matches a type name, the
project node may need to be renamed. When it matches a type member, use the spelling from the
1C:Element data (`ЦветСсылок: LinksColor` against `DesignTheme.LinksColor`).

Both cases produce warnings when the entry is written. A strict project check detects an error
when the project declares its own type under a built-in type name and the entry assigns it a
different spelling. A qualified key
(`<Owner>.<Name>`) applies within one namespace, does not affect type expressions and is not
checked for this match. `translate_set` returns these details in `collisions` and
`platform_names`; `--set` prints them to stderr alongside the number of entries written.

Unlike `--gaps`, which lists missing translations, `--unused` lists dictionary entries no longer
used by the project, such as names and comment
lines from deleted code. `--strict` checks untranslated locations; `--entries` shows where entries
are declared without checking their use. `--prune` removes the listed entries, subject to `--kind`,
`--filter` and the selected page. When `--limit` truncates the list, the report indicates this:
only entries on the displayed page are removed.

`--stale` is another name for the same mode. Use `--filter` to narrow the list, for example to
names of a deleted component.

`--unused --since` limits the list to entries associated with one change. These include keys no longer
used by the project that appeared only in lines removed by the change, and entries added or
modified in the dictionary by that change. With `--prune`, the listed entries are removed.

For a branch or commit, the comparison runs from its fork point with HEAD to the working tree,
so uncommitted changes are included. A range `A..B` is passed to Git as written. In one project,
the unfiltered list had 3297 unused entries, of which 18 belonged to the change: nine names and
nine comment lines. One call found them instead of nineteen calls with `--filter` for individual
names.

Candidates come from removed source lines and dictionary entries added or modified in the diff.
For example, a comment added and reworded in one branch may not appear as a removed line in the
diff against its base. The first wording is also found through the dictionary diff. Each
candidate is checked against the working tree; only keys no longer used there are listed.
The header and the `since` block in `--format json` count changed files, dictionary files in the
diff and entries on added lines.

Removed lines come from `git diff`. Comments are parsed in the old Git version of the file, so
unchanged block delimiters are included. Relative project and dictionary paths resolve from the
command's working directory. If Git does not respond within one minute, the command fails and
suggests narrowing the list without Git using `--filter`.

The walk over the sources reports its progress on stderr every 200 files, so a long run is seen to
move; stdout stays the report, and `--format json` there is one document. In that shape every row of `unused` contains `kind`, `key`, `value`, `file`, `line` and `scope` - what a script reads instead of
splitting the text rows on double spaces, which a key may hold itself.

The narrowing is an intersection rather than a shortcut: a name the project still spells does not
become an orphan however generously the diff reads. So an answer with neither a filter nor
`--since` contains a caveat. The reading is textual, and the list describes the whole accumulated
dictionary, which makes it something to read through rather than to prune wholesale.

The reading is textual, and the direction of its error matters. A name that also occurs in prose
may be counted as used, which merely leaves an entry in place; a live entry is never called an
orphan. A comment line is keyed by the translator's own payload reading, with markers and
decoration taken off exactly as the writing pass takes them. A literal is keyed the way the pass
keys it too. A yaml file goes through the pass's own walk, which tells a presentation or a
template from a name. A module goes through the lexer, which reads a string inside an
interpolation of another string whole. A name is looked for in the file
names as well, since a folder and a file go through the same token plane. A qualified key
(`<Owner>.<Name>`) is checked by both halves: the sources spell them apart, and reading the dotted
text as one name would call every such entry an orphan.

`--redundant` lists dictionary entries that repeat spellings from the 1C:Element data. Removing
such an entry leaves the translated tree unchanged. These entries can hide gaps in the data or
the engine. For example, entries for project descriptor languages in one dictionary concealed an
incomplete enumeration translation; a test with an empty dictionary found it. The ordinary report
counts such entries, and `--prune` removes the listed entries.

Unlike `--unused`, this command checks the whole project. An entry is redundant only when every
use would have the same result without it. An entry needed at any use is retained: for example,
when the 1C:Element data has a spelling for one role of a word but not another. Entries unused
by the project are checked by `--unused`.

`--drift` looks at the phrases. A comment line is translated whole, names included, and nothing
ties a name inside the translation to the tokens section. A token renamed after the phrase was
written, or a line translated with its own idea of a name, leaves the English comment naming
something the English tree does not have, and the only trace used to be a `comment/unknown-name`
finding on the English tree - on the comment, not on the entry to fix. The mode lists every name
of a phrase key that has a pair, a token of the project or the 1C:Element English spelling, when
the translation contains neither spelling from the pair and names something unknown in its place:
`ОбщееСклада -> StockCommon, while the translation names WarehouseCommon`, with the file and line
of the entry. A translation that renders the name in plain words names nothing and is not listed.
A pair written for a whole tag line is also checked by the name after the tag, whatever its
shape - a parameter named with one plain word is still the name of the signature - and by the tag
word: `@возвращает -> @returns, while the translation names @return`.
The mode reads the dictionary alone, answers in seconds and stays out of `--strict`: the tree
builds either way, and the gate answers whether it builds. The plain report counts such phrases
in one line that points at `--drift` when there are any (`dictionary_drift` in json); the exit
code does not change over them.

`--gaps` shows the count, the first places to look at and `suggestion`, the 1C:Element
spelling where it has one. A suggestion stays a hint: a name the project declared may deliberately
need a different word. An internal 1C:Element name, such as the metadata class `CodeAttrMd`, is
not offered.

**The MCP tools** are the same six, for an agent that fills the dictionary:

- `translate_status` - coverage and what is left, the cheap check before deciding anything;
  `against` names a git ref and adds the collision report of `--check-duplicates` against it,
  where the duplicates the ref already has are counted rather than listed (`full` lists them);
  `drift` counts the phrases `translate_drift` lists;
- `translate_gaps` - the untranslated entries by page (`kind`, `filter`, `limit`, `offset`),
  the answer naming the `dictionary` it read;
  `compact` returns only `{key, kind, count}` per row - the worklist shape that fits an
  answer when the full rows would not;
- `translate_entries` - dictionary entries with the file and line of each entry, so a
  new word stays consistent with the accepted ones; ten rows by default, and `compact` keeps
  `{key, kind, value}` per row - the answer to "how is this term translated" without the places,
  which came to ten kilobytes per call on a common stem;
- `translate_unused` - entries the dictionary contains and the project no
  longer has; `filter` narrows it to the names of one deleted component - or to a list of substrings
  at once, and the answer names in `unmatched` the ones no orphan fell under; `since` narrows it to
  the orphans of one change (a branch, a commit or a range `A..B`): the keys on the lines it removed
  and the pairs it added to the dictionary, both sides sized in the `since` block; `prune` (off by
  default) removes every key the filters select, whatever the page, with all its declarations.
  After removal the default answer omits the list: `removed` counts occurrences, `pruned.keys`
  counts the pairs, and `pruned.by_kind` / `pruned.by_file` group them; `compact=false` includes full rows. Preview remains full by default,
  with `compact=true` keeping only key, kind, file and line. `counts` covers all filtered candidates; `budget_seconds` (300 by default)
  bounds the walk over the sources - past it the answer is what was read, marked `partial`, with
  `sources` counting the files read of the total and a `note` on how to go on, a list of candidates
  on which `prune` does nothing; an answer with neither `filter` nor `since` includes a `note` about the cost of reading it;
- `translate_redundant` - entries for which the 1C:Element data supplies the same spelling, which the pass would spell
  the same way without them: the workarounds that hide a gap in the 1C:Element data or in the
  engine. `filter` narrows it, `prune` (off by default) removes every entry `filter` selects,
  whatever the page, and `pruned.keys` counts them; unlike `translate_unused` it runs a full pass, because the verdict rests on the places
  the entry actually answered;
- `translate_drift` - the phrases whose translation names a name otherwise than its pair (the
  `--drift` listing): each row gives the name, the spellings of its pair, the names used in the translation instead and the file and line of the entry; `filter` narrows it by any of
  those texts;
- `translate_set` - write entries back: add, correct in place, or remove by emptying a
  value; `edits_file` sends the batch as a file in the same two shapes `--set` reads.

Every page states what it left out. `total: 72` beside exactly fifty rows reads as a complete
answer, and a dictionary built from one such page came out twenty-two entries short. The strict
pass found them after the merge. So a partial page contains `truncated: true`, `remaining` and a `hint`
naming the next `offset`. `limit=0` returns the whole list, and for the gaps there is also
`--missing`, which writes the entire remainder to a file as a dictionary stub.

A new entry lands in `090-manual.yaml`, or in the file named by `target`, while an entry that
already exists is corrected in every place where the dictionary declares the key
more than once. An emptied value removes every copy, and which copy to take out is left to a person,
the way `--check-duplicates` lists it. Writing an entry does not create duplicate keys. A key translated
differently in two places, two files or twice in one, is refused when the dictionary loads, and
`--check-duplicates` lists every such key without loading it.

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
lists the services themselves, `google` and `yandex`, and asks the user to choose one with `--provider`.

**Two services, and they are not interchangeable.**

- **Yandex Translate** - authorizes with a service-account key and a folder id, both required.
  The batch limit is 10,000 characters per request. It understands a glossary, so the project's
  term list travels with the request itself.
- **Google Translate** - authorizes with one key alone, and its batch limit is 5,000 characters.
  Its API does not support a glossary, so the term spelling is enforced afterward, when the engine
  builds a name out of the returned prose.

Whatever either service allows, one request contains at most 100 texts. That is the engine's own
conservative bound. A batch turned away for its size costs exactly as much as one that is
accepted, and the character sum alone would let six hundred one-word names ride in a single
call.

**Keys are stored in the environment, never on a command line or in a setting.** Three variables,
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
place wherever the word stands in the phrase. Russian word forms are not analyzed. A term
the service answered in another English word, a plural or a synonym, is not recognized and stays
as it came. Terms do not affect comment lines (`phrases`): a comment stays exactly what the
service answered.

**The engine builds the names, not the service, and it builds them by fixed rules.** The service
answers in prose, such as "Site address", while the `tokens` plan needs an identifier. The engine
drops stop words (a, the, of...), substitutes a term's spelling where one is known, then
title-cases and glues the rest. A name already taken by another dictionary key is refused with a
named reason, and so is text that yields no identifier. Existing entries are not overwritten.

**Literals never reach the network.** `--suggest` sends the service only `tokens` and `phrases`
gaps, meaning whole names and whole comment lines. A string literal is filled separately, and only
when its text matches an already-accepted name exactly. That happens locally, with no request at
all.

**What is sent.** The service sees only the gap's own text: a name as the project wrote it, or a
whole comment line. It never sees a file path, the code around it, or the rest of the project.
Without a key the command sends no request to either service. It refuses immediately and
names the variable that is missing.

The report prints the same way `--set` does. `cached` is how many answers came from the cache,
`requested` is how many were asked for again, and `refused` is how many were turned down, each
with its reason.

In the editor the same three numbers stay in the panel's own summary line until the next run.
Before, they lived only in a status-bar message that closes itself in a few seconds. A hover on
that line names each refusal's reason. When there is nothing left to request, the line displays a message instead of three zeroes. It also indicates when every suggestion came from a local literal match without a service request.

### Dynamic-list reference expressions

In a dynamic-list source, `Items.Ссылка` uses `Reference` when `Items` is an explicit
alias of the main or a joined table. This applies to expression properties in that source,
including filters. Unrelated receivers and UI link properties keep their ordinary reading.
A scoped project dictionary entry can override the reference spelling.
