# Changelog

**English** · [Русский](CHANGELOG.ru.md)

Notable changes to the **xbsl toolkit** – the Python engine behind the linter, the LSP and MCP
servers, the documentation index and the metadata scaffolding. Entries are grouped by day; the
versions released that day are named in the heading. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and
[Semantic Versioning](https://semver.org/spec/v2.0.0.html). The VS Code extension keeps its own
history in
[editors/vscode/CHANGELOG.md](https://github.com/keyfire/xbsl/blob/main/editors/vscode/CHANGELOG.md).
Entries here use the English spelling of platform metadata names (`Name`, `Code`, `Attributes`);
the Russian spellings are in the [Russian changelog](https://github.com/keyfire/xbsl/blob/main/CHANGELOG.ru.md).

Every entry ends with a link to the pull request it came from -
`([#12](https://github.com/keyfire/xbsl/pull/12))`. That is why changes come in through pull
requests: an entry without such a link is unfinished, because the reader has no way from the line
to the code and the reasoning behind it. Internal identifiers of the platform have no place in an
entry either - say what the behaviour was, not which class name was compared.

## Unreleased

### Fixed

- **`self-update --version X` installs a release the simple index does not list yet.** After
  0.116.0 came out, the index kept serving the previous release for more than half an hour, and
  the command answered that the version did not exist, although its PyPI page already listed the
  files. A version named explicitly and missing from the index is now looked up on its own page.
  ([#133](https://github.com/keyfire/xbsl/pull/133))

## 2026-09-23 – 0.115.0, 0.116.0

### Added

- **`code/deprecated-project` finds uses of project declarations marked deprecated.** A method,
  property, constructor, parameter or enumeration value with `@Deprecated` is reported where it
  is used and the target is certain, as the platform IDE warns. The parser now keeps the
  annotations of an enumeration value. ([#132](https://github.com/keyfire/xbsl/pull/132))
- **`yaml/double-quoted-binding` finds a nonstring binding in double quotes.** The server rejects
  such a value, while a value without quotes or in single quotes compiles. The rule checks only
  properties that the UI schema declares nonstring, and its quick fix switches to single quotes.
  ([#131](https://github.com/keyfire/xbsl/pull/131))
- **`code/type-unavailable` finds a standard type used outside its environment.** A server-only
  type such as `Encodings` in a client method passed the linter and failed when the build was
  applied. The check needs data extracted again with `type_availability`; with older data it
  reports nothing. ([#131](https://github.com/keyfire/xbsl/pull/131))
- **`xbsl mcp-log` names the cause of a closed MCP connection.** The server writes its start and
  end to a journal, and `self-update --stop-holders` writes which servers it stopped. The journal
  shows whether the server failed, the client closed it or an update stopped it.
  ([#131](https://github.com/keyfire/xbsl/pull/131))
- **`unused-resources` finds resource candidates with no known uses.** The CLI and
  `meta_unused_resources` keep computed and uncertain uses separate and never delete files.
  ([#130](https://github.com/keyfire/xbsl/pull/130))
- **The language server supports precise documentation-comment edits.** The properties
  inspector can edit supported YAML node comments while retaining the surrounding source.
  ([#130](https://github.com/keyfire/xbsl/pull/130))

- **New checks catch project procedures used as values and mismatched contract parameter names.**
  They report only resolved project methods; uncertain targets stay unjudged.
  ([#129](https://github.com/keyfire/xbsl/pull/129))
- **A declaration that blocks a platform translation points to its missing dictionary pair.**
  The warning runs only in projects with a translation dictionary and excludes local names.
  ([#129](https://github.com/keyfire/xbsl/pull/129))

### Changed

- Library tests can use a local `.xlib` corpus to check exported and internal types
  through both YAML and XBSL. Proprietary archives remain outside the repository.
  ([#127](https://github.com/keyfire/xbsl/pull/127))
- Python comments and docstrings consistently use hyphens. Ordinary string literals remain unchanged.
  ([#127](https://github.com/keyfire/xbsl/pull/127))

### Fixed

- **`form-edit wrap` keeps a list where the slot is declared as an array.** Wrapping a single
  `Picture` in a `Group` wrote the content as one mapping, and the server rejected the form. The
  slot type from the UI schema now decides how the content is written.
  ([#131](https://github.com/keyfire/xbsl/pull/131))
- **`form-edit set-property` writes a typed binding without double quotes.** A width binding kept
  its quotes, and the server rejected it. A value that YAML accepts without quotes is written
  without them, otherwise in single quotes. ([#131](https://github.com/keyfire/xbsl/pull/131))
- **Resource checks follow namespace priority and visibility.** A resource in the current
  subsystem wins over an imported namesake. The linter reports hidden and ambiguous resources,
  and resource moves use the same resolution order.
  ([#129](https://github.com/keyfire/xbsl/pull/129))

- **SOAP client schemas stay with their object.** Move, rename and delete now include
  imported XSD files. Renaming updates local schema links while preserving external URLs.
  ([#129](https://github.com/keyfire/xbsl/pull/129))

- **`--check-duplicates --against` compares dictionaries through their common Git base.**
  One-sided removals and renames no longer recreate stale translations; competing key edits
  remain visible, with `merge_base` included in the JSON report.
  ([#128](https://github.com/keyfire/xbsl/pull/128))
- **Comment checks recognize an attached `////` frame.** Comment rewrapping also handles
  `/** ... */` and consistent star frames while preserving their kind, text and line endings.
  ([#128](https://github.com/keyfire/xbsl/pull/128))
- **Generic union checks use extracted variance and base-argument formulas.**
  Read-only covariant bases and nested mappings are recognized after re-extracting stdlib;
  old catalogs retain the conservative behavior. ([#128](https://github.com/keyfire/xbsl/pull/128))

- **`comment/unknown-name` retains readable declarations from malformed YAML.**
  A syntax error in an object description no longer makes its known names appear missing
  in comments. Text inside scalar values is excluded from this recovery.
  ([#127](https://github.com/keyfire/xbsl/pull/127))
- **`code/client-available-unused` keeps malformed client descriptions without a readable
  object name unjudged.** The readable element kind still identifies the client module
  in either language, so the YAML error does not cause an unrelated unused-method warning.
  ([#127](https://github.com/keyfire/xbsl/pull/127))

## 2026-09-22 – 0.114.0

### Added

- **`code/access-key-handler-flavour` checks the handler required by an access key's flavour.**
  A computed key needs `CheckHasAccessKeys` in its manager module. A manually granted key cannot
  declare it. Both rejected combinations are reported before compilation.
  ([#125](https://github.com/keyfire/xbsl/pull/125))

- **`lint_paths` compares with the previous call, like `--compare`.** The `compare` parameter
  names the file. The first call saves the run, and each later one answers with the findings that
  appeared and disappeared and a row per changed rule, all as data. The difference used to be
  available only in the CLI, and agents check projects through MCP more often. ([#122](https://github.com/keyfire/xbsl/pull/122))

### Fixed

- **The UI schema restores retired components from their runtime descriptions.** A tombstone
  help page is supplemented with known properties and the stated compatibility limit. Current
  help pages retain priority, and an older dataset without runtime descriptions works as before.
  ([#125](https://github.com/keyfire/xbsl/pull/125))

- **`translate --unused --since` includes pure resource renames.** Git emits no content
  hunk for an unchanged file moved to a new name. Its old path now contributes candidates,
  so a translation used only in the old filename can be removed.
  ([#124](https://github.com/keyfire/xbsl/pull/124))
- **`docs_symbol` finds members generated for interface components.** It reads member
  headings in the component type guide and returns the page, member block and section name.
  ([#124](https://github.com/keyfire/xbsl/pull/124))
- **Comment wrapping preserves deeper-indented list continuations.** Lines beneath a list
  item stay separate in both `//` and `/* ... */` comments when their translation grows.
  ([#124](https://github.com/keyfire/xbsl/pull/124))
- **Typed exception members keep their platform spelling during translation.** A catch
  declaration now recognizes `Exception` as a type. A project dictionary entry for the same
  member name no longer changes `Error.Cause` into an unknown property.
  ([#124](https://github.com/keyfire/xbsl/pull/124))
- **Method-qualified dictionary entries no longer rename query aliases.** A parameter
  entry applies to that method's locals. Query aliases and accesses to their result fields
  keep the same spelling. ([#124](https://github.com/keyfire/xbsl/pull/124))

- **`translate --unused --since` finds removed lines inside block comments.** It reads the
  old file from Git, including unchanged block delimiters. Removing a block opening no longer
  hides later comments, and removing a line inside an unchanged block finds its phrase.
  ([#123](https://github.com/keyfire/xbsl/pull/123))
- **`translate --since` reads dictionary changes when the project path is relative.** The
  dictionary path is resolved before Git is called from the project directory. Pairs added and
  left unused by the same change are included in the result.
  ([#123](https://github.com/keyfire/xbsl/pull/123))
- **`translate --set --target` rejects paths when writing to a dictionary directory.** It
  expects a filename such as `020-names.yaml`. The CLI and MCP report the error before writing
  any edits, instead of creating an unintended nested dictionary.
  ([#123](https://github.com/keyfire/xbsl/pull/123))

- **`--compare` pairs one folder typed relative and absolute.** The key of a finding took the
  path as typed, so two runs of one folder spelled two ways compared nothing and named both paths
  as left out. Paths are now paired by the folder they name, and by spelling when the folders
  differ, as with two worktrees of one repository. ([#122](https://github.com/keyfire/xbsl/pull/122))

## 2026-09-19 – 0.112.1, 0.113.0

### Added

- **`--summary` and `--compare`: counts by rule and the difference with the previous run.**
  `--summary` prints a row per rule with its files and findings instead of the findings.
  `--compare FILE` saves the run, and the next run with that file prints only the findings that
  appeared and disappeared. Comparing projects before and after a change used to go through
  `--format json` and a script, with the text of every finding in the output. ([#117](https://github.com/keyfire/xbsl/pull/117))
- **`meta_add_field` adds several items in one call.** `names` takes the names of one kind with
  the same type and properties, such as the values of an enumeration. The batch is planned whole:
  a taken or repeated name refuses all of it, and the file stays as it was. ([#114](https://github.com/keyfire/xbsl/pull/114))
- **The data now includes the members the platform generates for an element of each kind.**
  The extractor reads the help's template pages for types such as `Name.Object` and
  `Name.WriteParameters` in full: 152 types and 2161 members in the `generated_members` section.
  Before, the unknown-name rule relied on a hand-written table of four names and reported `IsNew`
  as undeclared in working code. Names that depend on the element's settings, such as `Parent` or
  `DeletionMark`, are accepted only when the element's yaml turns them on. ([#110](https://github.com/keyfire/xbsl/pull/110))

### Changed

- **The translator re-wraps `/* ... */` comments to the width as well.** The pass used to re-split
  only `//` lines, so a translated block ran past the limit: English runs longer than Russian. The
  block keeps `/*` at the head of its first line and `*/` at the end of its last one. ([#118](https://github.com/keyfire/xbsl/pull/118))
- **Pasting a fragment puts its notes where the development environment reads them.** A comment
  above the component moves inside the node as `##` lines and no longer stays before the `-`,
  where the visual editor drops it on the first save. A note with no place of its own stays, and
  the answer names it in the notes. The new page "Comments in yaml" says where and how to write
  comments in yaml. ([#116](https://github.com/keyfire/xbsl/pull/116))
- **The writing `meta_*` tools answer with a short lint.** The answer carries the number of files
  and findings and up to ten findings one line each; `lint_paths` on the written files gives the
  whole report. A clean file used to cost about twenty lines on every call. ([#114](https://github.com/keyfire/xbsl/pull/114))
- **`meta_rename_object` answers briefly.** It names the renamed files, counts the edits and lists
  the edited files no project owns, such as a translation dictionary; `full` lists every edited
  file. On a project with 63 edited files the answer went from 12.8 to 0.6 thousand characters. ([#114](https://github.com/keyfire/xbsl/pull/114))
- **The compact `lint_paths` answer names the CI rule set in one line.** The line carries the
  pipeline file relative to the checkout, the job and the flags, with a long list counted:
  `--enable ×10`. `as_ci_full` keeps the whole record. ([#114](https://github.com/keyfire/xbsl/pull/114))

### Fixed

- **A baseline entry keeps its finding when the rule rewords its message.** An entry frozen under
  the earlier text now holds a finding of the same rule in the same file if it names the same
  values in the same quotes and order. The run names such entries, and `--write-baseline` moves
  their reasons to the new text. ([#121](https://github.com/keyfire/xbsl/pull/121))
- **`prune` in `translate_unused` and `translate_redundant` removes everything the filters
  select.** It used to remove only the page shown in the answer, so a call with `limit: 5` left
  most orphans behind. The page now shapes only the list, and `pruned.keys` says how many pairs
  went. ([#120](https://github.com/keyfire/xbsl/pull/120))
- **`meta_rename_object` keeps comments and their translations together.** The name in a comment
  now changes whole, quoted text included, in a module and in yaml alike. The translation
  dictionary is not rewritten as a source: the translation of every changed comment line is
  carried to its new key, and a note names the `tokens` pairs of the old name. The phrase key used
  to change while the comment did not, and the pair lost its line. ([#119](https://github.com/keyfire/xbsl/pull/119))
- **`meta_resource_references` finds a file named without its extension.** Seed data names a
  picture by its code, and a module adds the extension at run time. For such a file the tool
  answered `total: 0`, as for a dead one. A string that spells the file's key without the
  extension in a module, a yaml or a JSON file of the project's resources now comes as a place of
  kind `stem`, and moving the file names it in the notes. ([#115](https://github.com/keyfire/xbsl/pull/115))
- **`self-update` no longer trips over the backup left by the previous run.** Windows does not
  let a backup be deleted while a running server still has it loaded, and the next update failed
  with a message about busy files. The current installation is now put aside under a free
  numbered name. ([#113](https://github.com/keyfire/xbsl/pull/113))
- **A member whose name starts with a lowercase letter now reaches the data.** The extractor
  dropped such names. The distribution has one of them, `iOS` among the client platform kinds, and
  the unknown-static-member rule flagged it in working code. ([#110](https://github.com/keyfire/xbsl/pull/110))
- **An object module now finds the yaml of its own element.** For `Name.Object.xbsl` the pair
  lookup searched for `Name.Object.yaml`, which never exists, instead of `Name.yaml`. As a result,
  a bare name in the module was read as foreign: an attribute named `Query` was taken for a
  platform type. ([#110](https://github.com/keyfire/xbsl/pull/110))
- **The `DeleteCurrent` rule checks the kind of the element that declares the attribute.** It used
  to take the document's deletion mode and apply it to every file. Only four kinds out of
  forty-one can declare a deletion mode, and the false findings fell on the rest, registers
  included. ([#110](https://github.com/keyfire/xbsl/pull/110))
- **The translation dictionary is read once per pass.** In 0.112.0 the dictionary freshness check
  moved to comparing bytes, and `code/translation-gaps` ran it for every file. On a project of
  1267 files that meant 234 395 reads and 83 extra seconds. ([#110](https://github.com/keyfire/xbsl/pull/110))
- **The yaml comment rules no longer put `##` on an instance of a project component in a list.**
  With a comment on such a node the server does not apply the project, although the development
  environment offers a place for it. The `yaml/plain-comment` autofix used to move a `#` block
  there, and that broke the build. The node now counts as a place without a comment:
  `yaml/doc-comment-misplaced` finds a `##` block on it and names the reason, and the note is to
  be moved into the comment of the group. ([#112](https://github.com/keyfire/xbsl/pull/112))

## 2026-09-18 – 0.111.0, 0.112.0

### Added

- **The `yaml/plain-comment` rule: a `#` comment is lost after an edit in the visual editor.** The
  development environment writes the file out again from the model and keeps documentation
  comments only: `##` lines at the head of the file, of a component node or of a declaration in a
  list. The rule finds every `#`. Where the place for the comment is next to it, the fix respells
  the marker or moves the block inside the node. Off by default. ([#111](https://github.com/keyfire/xbsl/pull/111))
- **The `yaml/doc-comment-misplaced` rule: a `##` block stands where the environment does not read
  it.** Before the `-` of a list item, above a single property, on a standard attribute or on a
  command such a block is lost the same way `#` is. Off by default. ([#111](https://github.com/keyfire/xbsl/pull/111))
- **The `comment/doc-marker` rule: the description above a declaration starts with `///`.** In a
  module the development environment shows in the hover only the `///` lines before a
  declaration. It does not read a `//` block or a `/* ... */` block in the same place. The rule
  finds a `//` block right above a method, a structure, a field or a constant and respells it with
  an autofix. Off by default. ([#111](https://github.com/keyfire/xbsl/pull/111))
- **`code/computed-property-server-call` – a server call inside a computed property.** The rule
  finds a form whose component property is recomputed through a server method without the
  platform's result cache, and shows the property lines and the proven call chain. One finding
  per form and server method. Events, deferred lambdas, client variants of a method and an
  enabled or unknown `CacheResult` are not reported; a platform component's `Image` stays with
  `code/image-binding-server-call`. Info level, off by default – turn it on with `--enable`.
  ([#105](https://github.com/keyfire/xbsl/pull/105))
- **`code/resource-read-without-cache` – a resource read without the cache.** A client-available
  server method that only returns the text of a file from the resource package
  (`ResourcesPackage.Current().Get(...).OpenReadableStream().ReadAsString()`) goes to the server
  for the same bytes on every call. The rule suggests `CacheResult = True` or passing the file
  through client work parameters; there is no autofix. Info level, on by default.
  ([#105](https://github.com/keyfire/xbsl/pull/105))
- **The extractor writes three optional data sections:** the values of the `Entity.Privilege`
  facet, the managers of element kinds, and English names of the platform image library (pairs
  are matched by file contents; pictures without a pair are listed in the report). Extract the
  data again to get them; data without these sections keeps working as before.
  ([#105](https://github.com/keyfire/xbsl/pull/105))
- **A button next to a picture in a row without an explicit vertical alignment is now reported.**
  Such a row lines its children up on the baseline. A `Button` keeps that line on its caption
  and a `Picture` on its bottom edge, so on a live row the button sank 19 px.
  `yaml/insert-row-needs-align` reports the pair when both stand in the row directly, and the
  new project rule `yaml/component-row-needs-align` reports it when project components draw the
  button and the picture. ([#106](https://github.com/keyfire/xbsl/pull/106))
- **`set-localization` and `meta_set_localization` take a batch of keys in one call.** The
  batch comes from a JSON or YAML file (`--entries-file`), from a repeated `--entry
  KEY=JSON` flag, or from an `entries` mapping on the MCP tool, and combines with the plain
  single-key form; naming the same key twice is refused. Each file the batch touches is
  read once and written once, only when a value in it actually changes, and a bad key
  anywhere in the batch stops the write before any file is touched.
  ([#106](https://github.com/keyfire/xbsl/pull/106))
- **`list_rules` and `--list-rules` accept a `filter`.** It matches a substring of a rule's
  id, a group name (the id segment before `/`), or a word from the rule's title, its
  message text in either language, or its English docstring. A word that exactly names a
  group narrows the answer to just that group - a plain substring search would answer
  `form` with 70 rules though `form/` holds only 2, and `code` with 120 though `code/`
  holds only 98; any other word still searches broadly and combines with `select`/`ignore`
  as before. A filter that matches nothing suggests the nearest group names.
  ([#106](https://github.com/keyfire/xbsl/pull/106))

### Changed

- **The passes standing next to the translation index are read once per state of the sources.**
  Names, types, components and dictionary scopes were recomputed on every call. They are now kept
  by the same digest as the index, which holds 2 MiB. The resource index is deliberately left out:
  it reads the names of picture and style files, and a picture dropped into a folder changes its
  answer without changing any digest. ([#109](https://github.com/keyfire/xbsl/pull/109))
- **The first translation call in a process costs more, the ones after it much less.** Six passes
  now take the digest where one did, so the first round over a 22 MB corpus grew from 2.9 to 4.3
  seconds while the second fell from 4.5 to 0.8 and the third to 0.5. A one-off command from the
  shell loses; a long-lived server and anything that translates repeatedly gain. ([#109](https://github.com/keyfire/xbsl/pull/109))
- **The caches build their answer once however the calls arrive.** Building the index reads the
  data, and the data reaches back into the cache's own reset on the same thread, so the lock has to
  be re-entrant – a plain one wedges there, which a test now holds. ([#109](https://github.com/keyfire/xbsl/pull/109))
- **`code/image-binding-server-call` uses the shared server-call facts.** Cached methods and
  client variants are no longer reported; a name a form inherits (`WriteAndClose`) is not
  mistaken for a common module; `Name.Method()` calls with an unknown base type and elements with
  a malformed metadata field are skipped. A few new findings through intermediate methods are
  possible. The message no longer claims a request on every redraw.
  ([#105](https://github.com/keyfire/xbsl/pull/105))
- **Translation builds the project index and takes longer** – 5 to 7 seconds more on a project of
  1,300–1,500 files. ([#105](https://github.com/keyfire/xbsl/pull/105))
- **`set-localization --dry-run` prints a summary instead of the whole file.** A run used to
  dump the full text of every changed file - one key came back as 103 KB, both localizations
  in full. It now lists, per key, the language and the old and new value, plus the file; the
  full text is still there, one flag away, behind the new `--full-text` (`full_text` on the
  MCP tool). ([#106](https://github.com/keyfire/xbsl/pull/106))
- **`lint_paths` with `compact` shows the findings, not just their count.** Up to ten
  findings, the answer now lists them under a new `findings` key as `file:line rule –
  message`; past that, `findings_hint` gives the count and how to see the list. The `as_ci`
  block shrinks to `enabled`, `adopted` and a one-line `flags` (plus `job` when the pipeline
  runs more than one lint job), but keeps `hint`, `note` and `unread_includes` when a config
  has any - a caller that compares the answer's key set for equality will see it change.
  ([#106](https://github.com/keyfire/xbsl/pull/106))
- **The rule tables on the documentation site fit the page, and the longest descriptions
  moved out of them.** The text column widened from Blume's 42rem default to 60rem, and a
  long code identifier in a table cell now wraps instead of forcing the table to scroll
  sideways. 101 rule descriptions over 200 characters, in both languages, were cut to about
  a third of their length; the detail they lost - exceptions, examples, platform history -
  moved to a note below each tier's table, linked from the row.
  ([#106](https://github.com/keyfire/xbsl/pull/106))
- **The project index behind translation is now kept for the life of the process, instead
  of being rebuilt on every call.** `ProjectIndex.build` itself falls from 8.4 s to 0.11 s,
  but that number is not what anyone feels: a bare `xbsl translate` from the command line is
  one process, builds the index once, and sees no speedup at all. Its first call is even
  about 0.19 s slower, because the cache now trusts a digest of every file's bytes rather
  than a timestamp. The win belongs to the long-lived MCP server and to anything that
  translates more than once without restarting: a second call in the same process falls from
  55.4 s to 47.1 s on a copy of the site, and from 35.4 s to 28.0 s on a second corpus. It is
  the same cost the changelog named when #105 added it ("Translation builds the project
  index and takes longer"): it has not gone away, only moved to once per process.
  ([#107](https://github.com/keyfire/xbsl/pull/107))
- **`code/unused-method` stops counting a comment as a use.** Until now, a name that appears
  only in a comment counted as a use and hid the method from the rule – in the module that
  declares it, in the paired yaml, or in another element entirely. None of those places
  count any more, and a finding that rests on a comment alone says so. Corpus findings rose
  from 216 to 237. A project running the rule in CI will see new findings the first time the
  pipeline checks its code after the upgrade: real dead methods, not false positives. The
  rule documents two remedies: an annotation naming a caller outside the project code, or
  the baseline with a reason for whatever stays invisible. Its table row is now the short
  form with a `[details]` link, the shape the sixth batch gave the documentation; the
  annotation list and the baseline route live behind that link, not in the row.
  ([#107](https://github.com/keyfire/xbsl/pull/107))
- **Writing a dictionary entry now reports the platform words it touches, in a new
  `platform_names` field.** `translate --set`, the MCP tool `translate_set` and the
  machine-translation write path (`--suggest-out`) all return the same list – one row per
  edit whose key clashes with a platform type or member, with the platform's own spelling
  and the reason. The field is additive – a caller that does not read it sees no difference.
  ([#108](https://github.com/keyfire/xbsl/pull/108))
- **Looking for platform data that is not installed now costs one lookup per lint pass
  instead of one per call.** The term and interface dictionaries, a component's inherited
  properties and the server-call catalogs used to re-read the data root on every call while
  it stayed missing. Measured on 400 dataless files, that fell from 403 lookups to 1 on a
  repeated pass. A language or MCP server started before the data exists still picks it up
  without a restart – just at the next pass rather than the next call.
  ([#108](https://github.com/keyfire/xbsl/pull/108))

### Fixed

- **A run no longer stops on the first file when the platform data is missing.** The picture rule
  is on by default, and the mapper the server-call rules share parsed every module before asking
  whether the data was there at all. A fresh install without data broke off with an unhandled
  error instead of answering. Nothing is parsed without data now, and the same gate takes the cost
  away: 800 parses become none, 120 ms become 1.7. ([#109](https://github.com/keyfire/xbsl/pull/109))
- **A dictionary key spelled like a YAML 1.1 word is written in quotes.** `On`, `No`, `Null` and
  the rest read back as a boolean or as nothing from a strict parser, so a key named after a toggle
  came back as `True`. The list of twenty-six words is taken from the specification pages. An
  ordinary key stays bare, and a key already written bare still reads and updates in place. ([#109](https://github.com/keyfire/xbsl/pull/109))
- **The dictionary is kept by a digest of its bytes, not by the time it was written.** Two writes in
  a row share one clock tick, so an edit of the same length went unnoticed and a lint run after
  `translate_set` could still answer from the dictionary as it was before the edit. The freshness
  check costs twice what it did – 20.8 ms against 10.2 – and `code/translation-gaps` takes it once
  per file, which is about ten seconds on a project of a thousand files. The rule is off by
  default; a pipeline that turns it on will feel it. ([#109](https://github.com/keyfire/xbsl/pull/109))
- **The extractor takes the fullest element-kind table from the distribution.** A
  server-with-IDE archive can carry several copies of that table; the first one often names
  only `HttpService` and `SoapService`, and kinds such as `Catalog`, `CommonModule` and
  `InterfaceComponent` then drop out of the metamodel. Form properties were reported as
  unknown. Seen at least on 9.2.9+12 and 9.3.1+4; the scan does not depend on the platform
  version. ([#102](https://github.com/keyfire/xbsl/pull/102))
- **Platform names next to project namesakes.** A platform annotation, the keys of a typed
  command node (`Handler`, `Presentation`, `Image`, `Items`) and a `Type<...>` argument are
  translated as platform names even when the project declares the same words.
  ([#105](https://github.com/keyfire/xbsl/pull/105))
- **A chain member is translated by the type that declares it:** `Bound`, `Remove` on arrays,
  maps and strings, `IsEmpty`, `Check` on an action privilege, `Entity.Privilege.Read` for the
  facet value. The type of a chain root is taken only where the method sees that name.
  Translating again can change the English tree, old data included.
  ([#105](https://github.com/keyfire/xbsl/pull/105))
- **Image-library pictures get English names** in yaml, in `Resource{...}` and in strings,
  written bare or with `Std::`, when the data carries the picture table; a project file with
  the same name wins. ([#105](https://github.com/keyfire/xbsl/pull/105))
- **`code/unknown-resource` knows the English image-library names** and no longer reports
  `Resource{Std::Account.svg}` in a translated or English-written project as an error.
  ([#105](https://github.com/keyfire/xbsl/pull/105))
- **The server-call rules do not remember that platform data was missing.** A language server or
  MCP server started before the data was installed finds them in a Russian-spelled project
  without a restart; an English-spelled project still needs one.
  ([#105](https://github.com/keyfire/xbsl/pull/105))
- **`translate --unused` no longer offers live literal entries for removal.** A yaml
  presentation or presentation template, a string nested inside another string's
  interpolation, and a group name of a pattern were read only by a regular expression over
  raw double-quoted text, so all three were missed and `--prune` took their entries out of
  the English build. The orphan search now asks the translating pass itself which texts it
  looks up, instead of keeping a separate copy of the same rules.
  ([#106](https://github.com/keyfire/xbsl/pull/106))
- **`translate --strict` fails when a localizable yaml text has no literal entry.** Until now
  a missing pair for a presentation, an application title, a permission message, an
  event-log template, or any other yaml value the metamodel marks `Localizable` was only
  listed, never failed - `Description` stays exempt as developer documentation, and other
  literal gaps (a string in code, an untyped `%{...}` value) still fail nothing. An `=`
  value holding a substitution is now translated as an expression, so the entry written for
  its string is found instead of missed. ([#106](https://github.com/keyfire/xbsl/pull/106))
- **`translate --set` and `translate_set` write a phrase entry by the spelling the
  translating pass will actually read.** A phrase key is one comment line with no escaping
  at all, but a key typed the way a string literal escapes its quotes used to be written
  verbatim and then matched nothing when translation ran: a working-looking entry that
  silently never fired. The quote and any leading or trailing padding are now stripped
  before the entry is written, and the correction is reported as `normalized`. The CLI and
  the MCP tool already printed it, and now the VS Code translation panel does too – it used
  to stay silent, leaving the author to search the dictionary for a key they would never
  find. A key or a translation that spans two lines cannot be repaired this way and is
  refused with an explanation, because the translating pass matches one comment line at a
  time. ([#107](https://github.com/keyfire/xbsl/pull/107))
- **`translate --set` and `translate_set` refuse an edit whose key is empty or blank, and
  the command exits 1.** Such an edit used to vanish with no word at all, and the command
  still exited 0. A script that checks the exit code after a batch of edits can newly fail
  on input it used to pass. ([#107](https://github.com/keyfire/xbsl/pull/107))
- **`terms_full.json` is written in a stable order.** Its `common` section used to keep the
  scan order of the distribution's classes rather than the alphabet, so a re-extraction that
  corrected no spelling still moved 5,708 of its 5,709 entries – noise that could hide a
  real content change inside it. The owner picked for a template at an exact tie used to
  come from `set(owners)`, whose iteration order follows Python's per-process hash
  randomization: the same distribution could name a different owner, and so a different
  member list, from one run to the next. Both are deterministic now: the section sorts by
  key, and a tie breaks alphabetically. Running the extractor twice on the same distribution
  now produces a byte-identical file. This is a fix to how the data is built, not to what it
  says: every entry keeps its previous meaning. ([#107](https://github.com/keyfire/xbsl/pull/107))
- **`translate --strict` can now fail on a dictionary key that spells a platform type.** It
  fails only when the project itself declares a type of that same spelling: the pair would
  rename the platform's own type everywhere a type expression reads it, including files that
  never mention the project's node, so the English build stops compiling there. Writing such
  a pair (`translate --set`, `translate_set`) only warns – the writer has the dictionary but
  not the project, and cannot tell a fatal clash from an ordinary one. `--strict` holds both,
  so that is where a pipeline can actually catch it, typically ahead of the platform compile
  step. A key spelled like a platform member rather than a type is not fatal the same way –
  the warning just names the member's correct English spelling. On a real 30,274-entry
  dictionary the fatal shape never occurred: 42 bare keys name a platform type, and 39 of
  them repeat its own spelling. But a pipeline that already runs `--strict` can fail on its
  very next run without a single code change. ([#108](https://github.com/keyfire/xbsl/pull/108))
- **A qualified library-picture reference now always means the library.** `Std::Save.svg`
  next to a project file named `Save.svg` used to resolve to the project file regardless of
  the `Std::` prefix. Now the prefix wins, the way it reads; an unqualified name still
  prefers the project file, unchanged. A plain string or a yaml value the schema treats as
  text is no longer matched against the library's picture names at all: the path such a
  string carries is read against the current namespace's own resource package at runtime,
  which the library is never part of. A string that happens to equal a library picture's
  name is therefore translated, or left alone, as ordinary text – the way it worked before
  the picture table existed. ([#108](https://github.com/keyfire/xbsl/pull/108))
- **`conventions/missing-translation` now considers the project's own resource files, not
  only the platform's picture library.** Built without them, the rule let the library answer
  for any name it carries, so a project resource file that happened to share a library
  picture's name was never flagged, even though translating the project left its reference
  in Russian. A project shaped that way can see new findings. None of the corpora used to
  check this batch have that shape, so the change is untested on real data.
  ([#108](https://github.com/keyfire/xbsl/pull/108))
- **Translation stops guessing an owner for a link whose type is a union of several types.**
  A member reached through such a link used to be translated as if only the first
  alternative typed it. Now the link ends the owner chain instead, and the member translates
  the way it did before owners existed at all. A translated fragment inside a string
  interpolation now reads the same chain of owners as the code around it, so the same
  expression no longer comes out translated outside the quotes and untranslated inside them.
  ([#108](https://github.com/keyfire/xbsl/pull/108))
- **`code/resource-read-without-cache` no longer misses a connected library's own element
  named like the resource root.** A project element with that name already turned the check
  off for the whole project. A library's global element of the same name reaches the project
  the same way, by its bare name, but the rule did not know library names at all and could
  still point at a cache for a method that was really calling into that type.
  ([#108](https://github.com/keyfire/xbsl/pull/108))
- **The term and interface dictionaries, and a component's inherited properties, stop
  holding an empty answer after a read that found no data.** A project written in English
  used to be read as if it had no platform vocabulary at all, until something reset the
  process. Now the next lint pass looks again, and an English-spelled project is analyzed
  correctly right away. ([#108](https://github.com/keyfire/xbsl/pull/108))
- **A broken data file now raises instead of being treated as if there were none.** These
  same caches used to catch any exception while reading their file and treat a failure as
  absence. Now only a missing file or one that fails to parse counts as no data, and
  anything else is a crash – a corrupted install surfaces immediately instead of linting
  silently with a partial catalogue. ([#108](https://github.com/keyfire/xbsl/pull/108))
- **The extractor now describes four components the platform's own help retired.** A help
  page for such a component only says it was replaced and lists no members, so the type
  kept no `type_members` entry, and a form built on it fell out of the server-call rules'
  analysis and out of `style/shadow-own-property`. The extractor now reads the component's
  own description instead – the platform still ships it for building forms – whenever help
  names a component but no longer describes it. This is a fix to the extractor, not new
  data by itself: the four components only gain a `type_members` entry after the extractor
  runs again over each platform version and the result is published through the data
  repository. The same run also stops pairing a picture path whose copies differ: such a path
  used to drop out before the grouping and left its group looking unambiguous.
  ([#108](https://github.com/keyfire/xbsl/pull/108))

## 2026-09-15 – 0.110.0

### Changed

- **Compact lint answers omit the per-file map.** Counts, full error records, baseline and
  CI-job details remain available; `compact=false` returns the complete report. ([#99](https://github.com/keyfire/xbsl/pull/99))
- **Pruning unused translations returns counts by default.** `removed` counts occurrences and
  `pruned` groups them by kind and file, including repeated declarations beyond the selected
  page. `compact=false` includes the full list; preview keeps its previous format. ([#99](https://github.com/keyfire/xbsl/pull/99))

### Fixed

- **New checks report missing returns, writes after lambda capture and discarded method results.** They follow the platform compiler and distinguish methods that change a value from methods that return a new one. Older language catalogs remain supported. ([#103](https://github.com/keyfire/xbsl/pull/103))
- **Ambiguous short type names are reported in code and YAML.** Root and package namespaces have equal priority; mixed qualified expressions and project namesakes of platform types are handled without interpreting YAML bindings as types. ([#103](https://github.com/keyfire/xbsl/pull/103))
- **A parse error no longer hides initializer and duplicate-declaration/branch findings in healthy sibling methods.** Damaged methods remain excluded, and fix offsets stay tied to the original source. ([#103](https://github.com/keyfire/xbsl/pull/103))
- **Rule reference pages format language keywords and code identifiers as inline code again,** including the recently added entries. ([#103](https://github.com/keyfire/xbsl/pull/103))

- **Named arguments are checked against resolved local and module signatures.** Unknown and repeated names, positional arguments after named ones and missing required parameters are reported. Structure methods take precedence over module methods; shadowed receivers and ambiguous overloads are left alone. ([#101](https://github.com/keyfire/xbsl/pull/101))
- **Structure fields with non-generic platform types are checked for a missing default value.** Types such as `TextPosition` need `req`, a nullable marker or an initializer; scalar default values and locally shadowed type names are respected. ([#101](https://github.com/keyfire/xbsl/pull/101))
- **Dynamic-list expressions translate an explicit table alias reference as `Reference`.** Main and joined table aliases share the source scope, including filters; UI links and unrelated receivers retain their own meaning. English expression keys are handled too. ([#101](https://github.com/keyfire/xbsl/pull/101))
- **Redundant `SkipUndefined()` calls are reported for known non-nullable collection elements.** The iterable fix uses `ToArray()` to preserve array materialization. Sequence calls receive a warning without an automatic rewrite. ([#101](https://github.com/keyfire/xbsl/pull/101))

- **Automatic fixes preserve accepted findings.** CLI `--fix` and MCP `lint_paths(fix=true)` fix new findings while keeping the baseline unchanged. Accepted occurrences stay protected when earlier edits shift the lines. ([#100](https://github.com/keyfire/xbsl/pull/100))
- **Removing a redundant cast also removes unnecessary parentheses at the start of a statement.** ([#100](https://github.com/keyfire/xbsl/pull/100))
- **Unknown query tables are checked throughout comma-separated source lists,** including sources following join conditions. ([#100](https://github.com/keyfire/xbsl/pull/100))
- **A loop declaration reusing an existing name no longer counts as an assignment to the original local.** Reads in its body follow the original binding; counted loops and letter case are handled consistently. ([#100](https://github.com/keyfire/xbsl/pull/100))

- **Older language data translates the enumeration kind as `Enumeration`.** The serializer
  spelling takes precedence over the stdlib type alias `Enum`. ([#99](https://github.com/keyfire/xbsl/pull/99))
- **Text output from `translate --set` names each rewritten location.** Repeated keys in one
  dictionary file or across files are distinguished by path and line number. ([#99](https://github.com/keyfire/xbsl/pull/99))

## 2026-09-14 – 0.107.0, 0.108.0, 0.109.0

### Added

- **Seven checks catch declaration errors and deprecated platform calls before deployment.** They
  report missing initializers, defaults on required fields, escaping scoped resources, repeated
  declarations, case values and catch types, and calls bound only to deprecated platform overloads.
  ([#98](https://github.com/keyfire/xbsl/pull/98))

- **An optional unused-constant check finds declarations the project never reads.** Enable
  `code/unused-constant` explicitly when cleaning up a project.
  ([#98](https://github.com/keyfire/xbsl/pull/98))

- **Five rules report assignments and jumps that roll the build back.** `code/self-assignment` and
  `code/assign-target` catch `X = X` and a left side such as `Obj?.Value`, `code/assign-readonly` a new
  value for a `val`, `use`, loop or `catch` variable, `code/unreachable-statement` code after `return`,
  and `code/misplaced-jump` a `break` outside a loop. ([#89](https://github.com/keyfire/xbsl/pull/89)) ([#90](https://github.com/keyfire/xbsl/pull/90)) ([#91](https://github.com/keyfire/xbsl/pull/91))
- **`style/boolean-ternary` and `style/redundant-scope` report what the platform IDE warns about.** A
  ternary with `True` and `False` branches is its own condition, and a `scope` that is the only
  statement of its block limits nothing. Both come with a fix. ([#86](https://github.com/keyfire/xbsl/pull/86))
- **`style/redundant-union-member` and `code/duplicate-import` report repeats the IDE warns about.** A
  union member another one covers and a namespace imported twice are removed by the fix;
  `yaml/duplicate-import` does the same for the `Import` section of an element. ([#87](https://github.com/keyfire/xbsl/pull/87))
- **`code/lambda-changes-outer-local` reports a lambda that assigns a local declared outside it.**
  The platform does not compile such code, and the linter let it through. Changing a member or an
  element of the captured value stays allowed. ([#84](https://github.com/keyfire/xbsl/pull/84))
- **`code/redundant-cast` and `code/cast-to-non-null` report the casts the platform IDE warns
  about.** A cast to the type a value already has, or one that only drops `Undefined`, passed the
  linter, and one project had 65 of them. The fix removes the cast or puts `!` in its place.
  ([#74](https://github.com/keyfire/xbsl/pull/74))
- **`code/redundant-undefined-guard` reports `??`, `!` or `?.` over a value that is never
  `Undefined`.** The platform IDE warns about such a guard, but the engine typed neither a
  component by its markup nor a generic member by its argument. The fix removes `?? ...` and `!`.
  ([#73](https://github.com/keyfire/xbsl/pull/73))
- **`code/redundant-type-check` reports an `is` check whose result is known in advance.** Such a
  check always passes, or never does for `is not`, and the platform IDE warns about it. A query
  column gets its type from the selected field. ([#73](https://github.com/keyfire/xbsl/pull/73))
- **`style/constructor-literal` reports a constructor call that a literal of the type replaces.**
  The platform IDE warns about `new Date("9999-12-31")` and `FindType("Std::String")`, and the
  linter let such calls through. The fix writes `Date{9999-12-31}` where the literal holds the same
  value. ([#71](https://github.com/keyfire/xbsl/pull/71))
- **`resource-references` finds the places that name a resource file or folder.** It reads the
  sources the way `move-resource` does. Every place comes with its file, range and line, and string
  lookups and a key that two folders hold are marked. MCP calls it `meta_resource_references`, LSP
  `xbsl/metaResourceReferences`. ([#67](https://github.com/keyfire/xbsl/pull/67))
- **`move-resource`, `rename-resource-folder` and `delete-resource-folder` work with resource
  folders.** A file moved by hand left its `Resource{...}` keys on the old path until a build
  failed. The commands move the files and rewrite the keys; lookups by a computed string are listed,
  not edited. ([#62](https://github.com/keyfire/xbsl/pull/62))

### Changed

- **Discarded expressions are reported as build errors even when they contain calls.**
  `code/statement-no-effect` now accepts only method calls and throws as expression statements.
  Read-only assignments also cover fields reached through a local structure receiver.
  ([#98](https://github.com/keyfire/xbsl/pull/98))
- **Version diagnostics identify the imported engine location.** `--version`, `--where`, MCP
  environment information and the LSP startup log distinguish installed copies and source checkouts
  that share a version number. ([#98](https://github.com/keyfire/xbsl/pull/98))

- **`comment/emphasis-caps` reads more than its list of function words.** It now catches a capital
  letter inside a sentence, a negation glued on, an ordinary word in capitals and the English line of a
  comment, and tells an abbreviation by the file itself. The comment walk no longer takes an HTML value
  with `\'` in a yaml for a comment. ([#92](https://github.com/keyfire/xbsl/pull/92))
- **`comment/first-person` reads the English line of a translated comment.** A `phrases` value such as
  "we build it from the name" passed while its Russian key was reported. Literals, often a text for
  the user, are not judged. ([#85](https://github.com/keyfire/xbsl/pull/85))
- **The guard, `is` check and cast rules read one type inference.** The first two kept their own copy
  of type sets and of the query-column reader, and each copy knew shapes the other did not. Now the
  type check also reads computed query columns and entity contracts, the guard an element of a typed
  array, and a cast the value of a component in the paired markup. ([#93](https://github.com/keyfire/xbsl/pull/93))
- **`xbsl/formKeys` also answers the values of enumerated properties.** The new `values` field pairs
  English and Russian values per property, and the answer names command classes and the members of
  inline fonts and colors. A client that reads an English form no longer has to guess. ([#83](https://github.com/keyfire/xbsl/pull/83))
- **`xbsl.typeinfer` answers with a set of types and knows the project's own names.** It used to
  name a single type from the platform catalog, so a query column, a union parameter or a structure
  from another module stayed unknown. ([#74](https://github.com/keyfire/xbsl/pull/74))
- **`code/unused-local` reports an unused `use` variable and a local that is only assigned.** The
  platform IDE warns about both, while the rule skipped `use` and took a write for a read. The fix
  drops the name of an unused `use`, and the resource still closes at the end of the scope.
  ([#69](https://github.com/keyfire/xbsl/pull/69))
- **With `--project-root`, the LSP server skips yaml outside the root, except the dictionary.** Such
  a file got findings when opened and lost them at the next save. Modules are still checked wherever
  they are opened. ([#59](https://github.com/keyfire/xbsl/pull/59))
- **`delete-object` and `delete-resource-folder` remove the folders their deletions empty.** A
  package whose last object was deleted used to stay behind as an empty folder, which git does not
  keep anyway. ([#62](https://github.com/keyfire/xbsl/pull/62))

### Fixed

- **Current property types retain their nullable alternatives.** The extractor separates historical
  member forms from current ones and resolves inherited members in order, so an older signature no
  longer erases the empty value from a current property type.
  ([#98](https://github.com/keyfire/xbsl/pull/98))

- **`code/ternary-and-or` no longer calls every `A and B ? X : Y` a compile error.** That ternary takes the whole
  condition and compiles; only a ternary right after `is Type` belongs to the check and breaks the line. The rule now
  reports that form alone, and the fix puts the condition in parentheses. ([#97](https://github.com/keyfire/xbsl/pull/97))
- **The parser reads `not Value is String` as `(not Value) is String`, as the platform does.** It used to put the
  whole check under `not`, so a redundant cast or a known-in-advance check of a negation went unreported.
  ([#97](https://github.com/keyfire/xbsl/pull/97))
- **A platform type keeps its spelling where only a type can stand.** A field, attribute or method
  named like a platform type held that type in type expressions and before a facet, so the English
  tree mixed spellings. A type expression, a static call root and a facet owner now take the
  platform's spelling unless the project declares a type of that name. ([#94](https://github.com/keyfire/xbsl/pull/94))
- **A resource file and a method of the project's own component are spelled alike everywhere.** The
  file could take a platform word while a form kept its own name, and a call through a form node took a
  built-in command. Both now follow the project dictionary; pictures of the platform library read as
  before. ([#95](https://github.com/keyfire/xbsl/pull/95))
- **A local that hides a platform type of the same English word is a collision.** With such a parameter
  the English tree read the parameter where the method meant the type, and `--strict` passed while the
  build failed. The report now names both places. ([#96](https://github.com/keyfire/xbsl/pull/96))
- **The import rules read more tables.** A joined table of the reference input settings and a table
  after a join condition (`FROM A LEFT JOIN B ON ..., C`) went unread, and `code/unused-import` could
  call such an import unused. The project module now needs `import Subsystem` for an element of a
  subsystem root as well. ([#88](https://github.com/keyfire/xbsl/pull/88))
- **The visibility rules read the tables of lists and queries.** A non-public table of another
  subsystem in a dynamic list, input settings, a `Query{...}` block or the query of a virtual table
  breaks the build, and `yaml/foreign-not-public` and `code/foreign-not-public` now report it. ([#88](https://github.com/keyfire/xbsl/pull/88))
- **`yaml/wrong-namespace` and `code/wrong-namespace` judge a partial name of an element kept in
  several places.** The compiler looks only where the name leads, so the finding lists the places and
  leaves the choice to the author. ([#88](https://github.com/keyfire/xbsl/pull/88))
- **A translation dictionary no longer hides dead methods.** It names every method it translates,
  and `code/unused-method` took those names for uses, so a check of the project together with its
  dictionary found nothing. ([#82](https://github.com/keyfire/xbsl/pull/82))
- **The "never used" rules count the words of a file that does not parse.**
  `code/client-available-unused` and `yaml/unused-component` dropped such a file whole, so a method
  or a component used only there was reported. ([#79](https://github.com/keyfire/xbsl/pull/79))
- **`--set` and `translate_set` write a key in every place the dictionary declares it.** A repeated
  key got the new value on one line only, so the next load refused the dictionary, and a removal left
  the copy translating. A key named twice in one batch no longer takes the neighbouring entry along.
  ([#81](https://github.com/keyfire/xbsl/pull/81))
- **An English SOAP service client keeps its kind without the kind table in the data.** The fallback
  spellings, used with no data or with data extracted before 0.54.1, lacked `SoapServiceClient`, so
  the project overview counted such a client apart and a filter by kind missed it. ([#80](https://github.com/keyfire/xbsl/pull/80))
- **The LSP server keeps the findings of a module opened outside the project root.** The
  whole-project check runs on every save and used to clear the findings of every open file it had
  not read. Now they stay until the file is closed. ([#78](https://github.com/keyfire/xbsl/pull/78))
- **`translate` keeps the spelling of a name's declaration.** A local, a parameter, a lambda
  parameter, a `catch` variable or a property of the module's own element named like a platform
  type took the type's spelling in `Name.Member` and inside `%{...}`. The English build then met a
  variable nothing reads and a member the type lacks. ([#76](https://github.com/keyfire/xbsl/pull/76))
- **A short lambda may assign in its body.** The platform compiles
  `List.ForEach(Item -> Item.Value = 1)`, but the parser reported syntax errors there, as it did
  for a lone parameter named `Type`, `Query` or `Method`. Rules that need the parse skipped such a
  module, and `code/client-available-unused` reported a method called only from it.
  ([#75](https://github.com/keyfire/xbsl/pull/75))
- **`style/shadow-own-property` finds a variable named like an inherited property.** The rule read
  only the element's own yaml and missed the properties a component inherits from its platform
  type, which were all seven IDE warnings on one project. As in the IDE, static methods and loop
  variables are no longer reported. ([#72](https://github.com/keyfire/xbsl/pull/72))
- **`code/unused-import` repeats the type lookups the compiler makes.** The rule took any word that
  spelled an element for a use, the import line itself included, and on a project with packages it
  missed every import the platform IDE reports. On every project checked the findings now match the
  IDE, and the fix removes the line. ([#70](https://github.com/keyfire/xbsl/pull/70))
- **`code/unused-local` and `code/unused-loop-var` no longer report a variable read below a batch
  query or the counter of `for X = A to B`.** A `;` inside the query ended the method early, and the
  IDE does not track the counter of a numeric loop. ([#69](https://github.com/keyfire/xbsl/pull/69))
- **`yaml/missing-import` reads the tables of a dynamic list.** A list whose main or joined table
  lay in a package of another subsystem passed the linter, and the server build refused it. Such a
  table now asks for the import like any other reference.
  ([#58](https://github.com/keyfire/xbsl/pull/58))
- **`yaml/wrong-namespace` and `code/wrong-namespace` check the partial name too.**
  `Subsystem::Name` goes stale after a move into a package just like the full name, and the build
  refuses it. The fix writes the package segment when the element lies in one place.
  ([#58](https://github.com/keyfire/xbsl/pull/58))
- **`code/package-resources-missing` checks the root of a subsystem as well.** A run on a server
  showed that without its own `Resources` folder `ResourcesPackage.Current()` finds nothing there,
  not even the files of the packages. ([#58](https://github.com/keyfire/xbsl/pull/58))
- **The dictionary load and `--check-duplicates` see a key repeated in one file.** The yaml parser
  keeps only the last value, so such a pair loaded with its second translation unnoticed. The repeat
  now counts as a conflict or a duplicate, named by file and line.
  ([#57](https://github.com/keyfire/xbsl/pull/57))
- **The LSP server keeps the dictionary findings next to a narrowed project root.** The project-wide
  check read only the files under `--project-root` and cleared the findings of other open files, so
  a dictionary file lost them at the first save. The check now covers the dictionary.
  ([#59](https://github.com/keyfire/xbsl/pull/59))
- **`move-object`, `rename-object` and `delete-object` no longer lose the WSDL descriptions of a
  SOAP service client.** The `<Name>.Wsdl.1.wsdl` file stayed behind, so a moved or renamed client
  failed to apply. A rename keeps the number of each description and updates a reference from one
  description to another by file name. ([#63](https://github.com/keyfire/xbsl/pull/63))

## 2026-09-13 – 0.106.0, 0.106.1

### Added
- **The documentation guard catches a sentence naming who asked for a change.** The repository has
  one author, so such a sentence makes the code look written for someone else. The guard reads both
  editions of the documents and source comments. ([#46](https://github.com/keyfire/xbsl/pull/46))
- **Five checks for the wording and characters of comments.** `typography/non-keyboard` is on by
  default and suggests the keyboard form of an arrow or a math sign. `typography/en-dash-comment`,
  `comment/subjunctive`, `comment/first-person` and `comment/emphasis-caps` turn on with `--enable`.
  ([#51](https://github.com/keyfire/xbsl/pull/51))
- **Two more comment checks, both off by default.** `comment/dash-condition` catches a dash used in
  place of "if". `comment/unknown-name` flags a name that neither the project nor the platform
  knows, such as a renamed method's old name. ([#55](https://github.com/keyfire/xbsl/pull/55))
- **`translation/english-shape` checks the English of the translation dictionary.** A mechanical
  edit like "a second icon onlies clutter the row" passed `xbsl translate --strict`, which only
  measures coverage. The rule is on by default. ([#52](https://github.com/keyfire/xbsl/pull/52))
- **`yaml/wrong-namespace` and `code/wrong-namespace` catch a full name that outlived a move.** Such
  a name points to the old place, and the build answers "Unknown type". If only one element has that
  name, the fix writes its namespace. ([#56](https://github.com/keyfire/xbsl/pull/56))
- **`code/package-resources-missing` reports `ResourcesPackage.Current()` in a package with no
  resources folder.** The call returns the resources of the package, so a module moved into it stops
  finding the subsystem's files without any error. ([#56](https://github.com/keyfire/xbsl/pull/56))
- **`move-object` moves an object between packages and subsystems without breaking references.** A
  move by hand left imports missing and full names stale, and only a server build showed it. The
  command moves the forms and modules along and repairs both by the linter's own rules.
  ([#54](https://github.com/keyfire/xbsl/pull/54), [#56](https://github.com/keyfire/xbsl/pull/56))
- **`rename-package` renames a package with every name that spells it.** It moves the folder and
  rewrites imports, `Import` items and qualified names across the project. In other projects only
  full names change. ([#54](https://github.com/keyfire/xbsl/pull/54))
- **The LSP server serves `project-info` as `xbsl/metaProjectInfo`.** The metadata tree of the
  editor uses it to place objects into subsystems and packages.
  ([#54](https://github.com/keyfire/xbsl/pull/54))
- **`lint_paths` can answer compactly, and every report counts findings in `by_rule`, `by_file` and
  `by_severity`.** A full MCP answer carried the text of every finding when the question was often
  just whether the tree is clean. `compact=True` keeps the summary and the errors in full.
  ([#49](https://github.com/keyfire/xbsl/pull/49))
- **`xbsl translate --check-duplicates` finds a key that two dictionary files translate.** Git
  merges such files cleanly, but differing translations break the load. `--against origin/master`
  shows a branch the collision before the merge. ([#48](https://github.com/keyfire/xbsl/pull/48))
- **`translate_unused` stops after `budget_seconds` and answers with what it has read.** A call with
  `since` over a large project used to stay silent until the client gave up. An answer cut short
  carries `partial: true`, and `prune` leaves it alone. `xbsl translate --unused` prints its
  progress to stderr. ([#47](https://github.com/keyfire/xbsl/pull/47))
- **`translate_unused` takes a list of filters and names the ones nothing matched.** Checking ten
  removed comment lines used to take ten calls. After a comment sweep, a filter in `unmatched` is a
  line the dictionary no longer holds. ([#47](https://github.com/keyfire/xbsl/pull/47))
- **`translate_entries` answers compactly and ten rows at a time.** Fifty full rows took about ten
  kilobytes per call, while the usual question is only how a word is translated. `compact` keeps
  `{key, kind, value}` per row. ([#47](https://github.com/keyfire/xbsl/pull/47))

### Changed
- **`project-info` answers the question asked and leaves out the reference sections.** They do not
  depend on the sources yet came with every answer. `--reference` or `--brief` brings them back.
  `--package` and `--project` narrow the answer. ([#53](https://github.com/keyfire/xbsl/pull/53))
- **The import and visibility rules put their namespaces into the `data` of a finding.** The message
  is prose in two languages, and `move-object` repairs imports from the data. The JSON report and
  the editor receive it too. ([#54](https://github.com/keyfire/xbsl/pull/54))
- **`add-subsystem` creates a subsystem only at the project root.** A folder inside a subsystem is a
  package, so a descriptor there changed nothing, and such a parent is now refused. `new-object`
  checks the name of a new package folder. ([#54](https://github.com/keyfire/xbsl/pull/54))
- **Metadata commands that move files no longer leave empty folders behind.** `delete-object` also
  finds the English-spelled forms of an object, `<Name>ObjectForm` and `ListRow<Name>`.
  ([#54](https://github.com/keyfire/xbsl/pull/54))
- **`--since` also judges the pairs the change itself wrote into the dictionary.** The first wording
  of a comment reworded within one branch never shows in the diff, so its pair stayed for good. The
  `--unused` help points at `--format json`. ([#47](https://github.com/keyfire/xbsl/pull/47))

### Fixed
- **Translation carries a package import of another subsystem into the English tree.** An
  `Import` list in yaml names such a package as `Subsystem::Package`, and the translator left that
  value in Russian. The strict run did not notice, and the translated build could not find the
  package's types. Each segment now comes from the dictionary, and the strict run treats a segment
  without an entry as a gap. ([#50](https://github.com/keyfire/xbsl/pull/50))
- **The import rules know the packages of a subsystem.** They took `import Subsystem` as enough for
  its packages, while another subsystem needs `import Subsystem::Package`. `code/missing-import` and
  `yaml/missing-import` now ask for it. ([#53](https://github.com/keyfire/xbsl/pull/53))
- **The import rules read the project module and queries.** The compiler resolves both against the
  imports, while the linter left them unchecked. The rules now ask for the imports there and in a
  `Type<...>` literal. ([#56](https://github.com/keyfire/xbsl/pull/56))
- **The import rules read the names inside a string interpolation.** `code/missing-import` did not
  see a name in `%{...}`, and `code/unused-import` called its import unused, though the build failed
  without it. ([#53](https://github.com/keyfire/xbsl/pull/53))
- **`code/unused-import` sees an import of a subsystem with an empty root.** Once every element
  moved into packages, the subsystem looked unknown and its import went unreported. A resource named
  by a bare key still counts as a use. ([#56](https://github.com/keyfire/xbsl/pull/56))
- **The metadata commands place an object of a package.** They looked for a subsystem only right
  above the object, so a generated list form got a wrong row type. `object-info` and `project-info`
  now answer the `package` and the full namespace. ([#53](https://github.com/keyfire/xbsl/pull/53))
- **`style/redundant-tostring` judges `ToString()` by its place in the expression.** It judged by
  the line and flagged `(A + B).ToString() + "px"`, where the call is needed. The call is redundant
  only after a string literal in the same sum. ([#49](https://github.com/keyfire/xbsl/pull/49))
- **The dictionary refusal names every key translated differently, not just the first.** A merge
  with four such keys used to take four rounds of "take one out, load again". One error now lists
  them all with the translation in each file. ([#48](https://github.com/keyfire/xbsl/pull/48))

## 2026-09-12 – 0.104.0, 0.105.0

### Added
- **`tests/test_conventions.py` catches a test shadowed by a namesake.** A test that arrives
  under the name of an existing one takes its place, and the count of tests goes up because the
  newcomer was added. Nothing in the run says the older one has stopped. The check reads
  `tests/` and names the line to rename. `tests/test_source_hygiene.py` has held every module to
  one definition per name since July; this one comes from the shared `docsguard` package and
  reads the inside of a class as well, where pytest collects a `test_` method just the same.
  ([#44](https://github.com/keyfire/xbsl/pull/44))
- **The conventions guard requires a process started from the engine to name its stdin.**
  Otherwise the child gets the stdin an MCP or LSP server speaks over, and on Windows it cannot
  finish. The check covers the `xbsl` folder alone: generators and tests run from a console,
  where stdin is a console.
  ([#42](https://github.com/keyfire/xbsl/pull/42))
- **The machine report of the CLI names the CI rule set it judged by.** `--format json` now
  carries `summary.as_ci`: the job and the file it came from, the set as data and as the
  sentence a terminal prints, the jobs not taken and the includes left unread. That answer was
  a line on stderr in text mode only, so a reader of the report had nowhere to take it from,
  and only the agent tool could see it. A refusal reaches the report too, under the same key
  and with no findings in it. ([#41](https://github.com/keyfire/xbsl/pull/41))
- **Typography now reaches the resource files of a project.** The em dash, the ellipsis
  character, curly quotes, guillemets and the letter "ё" are caught in the `.css`, `.js`,
  `.svg` and `.html` under the resources folder as well. Nobody looked there before, though
  the browser gets those files exactly as they are. The check reads comments and the text on
  the screen; code, selectors and attribute values stay out of it.
  ([#36](https://github.com/keyfire/xbsl/pull/36))
- **The translator reads the comments of a resource file.** A `.css`, `.js`, `.html` or `.svg`
  used to be copied byte for byte, so a Russian comment reached the English build and
  `--strict` called the file covered. Their text is now an ordinary dictionary phrase: the
  comments, plus `<title>` and `<desc>` in an `.svg`. A licence comment and a minified file
  are skipped. ([#34](https://github.com/keyfire/xbsl/pull/34))
- **The LSP server says which rule set it judges by (`xbsl/ciStatus`).** That used to be one
  line on stderr, in an output channel nobody reads. The request now answers whether the job's
  set was taken, which job it was and which file it came from, and the extension shows that in
  the status bar. ([#22](https://github.com/keyfire/xbsl/pull/22))
- **`translate --dry-run` shows what the pass would write and what it would delete.** Cleaning
  used to be a blind step: the count of removed files was printed after the removal. The pass
  now stops just short of writing, and the leftovers are named up front.
  ([#21](https://github.com/keyfire/xbsl/pull/21))
- **CI parity follows the `include:` files of GitLab.** The lint job often lives outside the
  root file, so the run answered "runs no xbsl command" about a pipeline that runs one. Local
  includes are read now; remote ones are still not fetched, but they are named, so a job that
  stays invisible comes with its reason. ([#19](https://github.com/keyfire/xbsl/pull/19))

### Changed
- **The shared guard is pinned to `docsguard@v0.9.0`.** In that release the source checks read a
  file as `utf-8-sig`. `xbsl/__init__.py` begins with a byte-order mark, `ast.parse` answered it
  with a `SyntaxError`, and one such file left the whole check with no findings from any file at
  all. The newline check reads whole folders again, and the workaround that opened them one by
  one is gone. ([#44](https://github.com/keyfire/xbsl/pull/44))
- **The conventions guard reads the Russian strings of the sources.** It read the documentation
  pages only, though a person reads the help of a command and the text of a refusal the same way
  as a page. The check names fourteen modules that hold messages. The rule modules stay out:
  their wording sits next to a table of English terms written in Cyrillic, and the guard would
  read a key of that table as prose.
  ([#39](https://github.com/keyfire/xbsl/pull/39))
- **The conventions guard reads the sources through the shared `docsguard` package.** The
  bridge and the console read theirs the same way, and what stays here is what is about this
  repository. The findings came out identical before and after the move. CI installs the
  package by tag, so a verdict cannot move without a commit.
  ([#23](https://github.com/keyfire/xbsl/pull/23))
- **The `xbsl --help` texts and the VS Code extension pages are written in plain words.** The
  wording read like a transliteration and the sentences ran long, so half of the text had to be
  translated back before it said anything. The Russian metavar of `--as-ci-job` changed with them.
  ([#28](https://github.com/keyfire/xbsl/pull/28))
- **The Russian messages of the engine are written in plain words.** The report, the
  refusals and the LSP log read like a transliteration. The English strings were already
  plain and did not change.
  ([#33](https://github.com/keyfire/xbsl/pull/33))
- **The Russian dry-run line of `translate` no longer shouts in capitals.** The English
  string is unchanged. The Russian pages caught up with the messages rewritten in #33: their
  examples quoted output the tool no longer prints.
  ([#35](https://github.com/keyfire/xbsl/pull/35))

### Fixed
- **`.gitattributes` holds the line ending for the whole repository.** The line
  `* text=auto eol=lf` stores and checks out every text file with line feeds, whatever the
  machine is set to. The file named only `diff` per extension before, so a clone made with
  `core.autocrlf=true` came out with 546 text files carrying carriage returns. `newline=""` in
  the Python generators does not reach that far: it says how a file is written, and
  `scripts/sync-docs.mjs` copies bytes when it mirrors `CHANGELOG.md` and the extension README
  onto site pages. ([#44](https://github.com/keyfire/xbsl/pull/44))
- **The table modes of the translation command refuse the flags of the writing pass.**
  `--gaps`, `--entries`, `--table`, `--unused`, `--redundant` and `--suggest` write no tree, yet
  they took `--out`, `--clean`, `--dry-run` and `--missing` without a word: a request to show
  what a run would do came back as a table. Such a run now names the flags it cannot read and
  exits with 2.
  ([#43](https://github.com/keyfire/xbsl/pull/43))
- **`translate --unused --since` no longer goes quiet inside the MCP server.** The child `git`
  got the server's stdin and could not reach its own exit: the work took four milliseconds, the
  read waited five minutes. The child now gets an empty stdin, and a git that has not answered
  within a minute is refused with a hint at another way to ask. On a live project it was 302 seconds
  and an error; it is 3-7 seconds now.
  ([#42](https://github.com/keyfire/xbsl/pull/42))
- **A pipeline reads its includes from the top of the repository.** The folder of the named
  file stood for that top, which is right for a `.gitlab-ci.yml` lying at the root and wrong
  for every other place. A pipeline kept in a subfolder looked for `include: /ci/base.yml`
  next to itself and answered that it runs no xbsl command. The root is now found by the
  `.git` above the file, a linked worktree included, where `.git` is a file. The baseline path
  starts at the same root. ([#40](https://github.com/keyfire/xbsl/pull/40))
- **A file the toolkit writes no longer comes back from Windows with every line changed.** A
  write in text mode turned `\n` into the platform's line ending, so the template export, the
  `datadiff --out` report, the language data of an extraction and the translation dictionary
  all came out CRLF there. In a checkout without `core.autocrlf=input` such a file went into
  the repository as one line-ending change nobody asked for. Twenty-two writes name `newline`
  now, and the convention is guarded the way the encoding of a started process already was.
  ([#37](https://github.com/keyfire/xbsl/pull/37))
- **A directory named after `--as-ci` is refused with the form that works.** The flag expects a
  pipeline file, so `xbsl --as-ci e1c` swallowed the path and the run linted the current
  directory instead. The refusal now names the working form, `xbsl e1c --as-ci`.
  ([#20](https://github.com/keyfire/xbsl/pull/20))

## 2026-09-11 – 0.102.0, 0.103.0

### Added
- **Changing the CI parity setting restarts the LSP server.** The flag reaches the server as an
  argument, and the list of settings that call for a restart did not know about it. Switched on
  in a live window, `xbsl.linter.asCi` did nothing until the next reload.
  ([#18](https://github.com/keyfire/xbsl/pull/18))
- **The Problems panel can judge by the job's rule set.** The terminal could already do it, the
  panel could not, and one tree got two verdicts. `xbsl.linter.asCi` turns it on and
  `xbsl.linter.asCiJob` names the job; the server reads the same pipeline file the CLI does.
  ([#14](https://github.com/keyfire/xbsl/pull/14))
- **`--as-ci-job` picks the job when the pipeline runs the linter twice.** `--as-ci` took the
  first `xbsl` command in the file, and there was no way to reach the second job. The job can
  now be named, `--as-ci` alongside it is not needed, and a run that was given no name prints
  which jobs it passed over.
  ([#13](https://github.com/keyfire/xbsl/pull/13))
- **`--as-ci` runs the linter with the rule set of the project's job.** The flag reads
  `--select`, `--ignore`, `--enable` and the baseline from the very `xbsl` command CI runs. The
  difference used to surface as a red job: on a live project a plain run found 2 findings where
  the job found 11. ([#10](https://github.com/keyfire/xbsl/pull/10))
- **The metadata tools point at each other.** `meta_add_field` adds the key of a localized
  string, the translations are written by `meta_set_localization`, and there was nowhere to
  learn that. Neighbouring tools now carry a "see also" line in the MCP descriptions and in the
  CLI help. ([#4](https://github.com/keyfire/xbsl/pull/4))
- **`translate --redundant` finds the dictionary entries the platform answers itself.** Such an
  entry translates nothing and hides a gap in the data behind it: half-translated project
  languages stayed invisible because of one. A live dictionary of 31 989 entries held 22, and
  `--prune` took all of them out with the English tree of 1 261 files unchanged to the byte.
  ([#3](https://github.com/keyfire/xbsl/pull/3))

### Changed
- **A name the project declares is no longer explained by a platform member spelled the same.**
  Over a module's own `Write` the hover showed the project's card and then added a platform
  member that had nothing to do with it. The project's answer now settles the question, and the
  panel offers a search over the word. ([#16](https://github.com/keyfire/xbsl/pull/16))
- **The hover and the documentation panel answer with the member's block, not with its type's
  page.** Over `Text.Substring` the hover explained what the type String is. It now shows the
  signature and what the call does, and the link opens the page at the member's heading.
  ([#9](https://github.com/keyfire/xbsl/pull/9))
- **A translation collision names where both names are declared.** The report said only which
  method or structure the two words met in, and finding them was then done by eye. Each name
  now carries the file, the line and the column of its own declaration, in all four namespaces
  the pass watches.
  ([#7](https://github.com/keyfire/xbsl/pull/7))
- **`docs_symbol` finds the members of a type and takes either spelling.** A member has no page
  of its own, so asking by name answered with an empty object, and English `Array` found
  nothing at all, the pages being written in Russian. A member now answers with its type's page
  and the block of that one member. ([#6](https://github.com/keyfire/xbsl/pull/6))
- **`translate --out` writes a repository rather than a loose pile of files.** A build takes a
  project only at `{repository}/{Vendor}/{Name}`, while the command laid the descriptor straight
  into the directory it was given, so a translated tree could not be deployed until someone
  moved it by hand. Both names now come from the translated descriptor.
  ([#5](https://github.com/keyfire/xbsl/pull/5))

### Fixed
- **A Python process started from here is told what to encode its output in.** Without
  `PYTHONIOENCODING` a child on Windows writes in the console code page while the parent
  decodes utf-8: the text is lost and the return code still says the run went well. Four calls
  were like that, and `tests/test_conventions.py` now watches every process start in the
  repository. ([#17](https://github.com/keyfire/xbsl/pull/17))
- **`translate --out --clean` takes the orphans of an earlier pass out of the output tree.** A
  file renamed in the source left its old translation standing, and the build shipped it with
  the rest of the tree. On a live corpus of 1261 files a rename left 1262, and with `--clean`
  the tree came back to 1261. ([#15](https://github.com/keyfire/xbsl/pull/15))
- **`translate --out`: a refused write says so, instead of an empty log and exit code 1.** The
  writing step stood before the report, so any trouble from the file system took the whole
  report with it. Every write error is now named with its file and reason, the report is
  printed whole, and a failed write exits non-zero even without `--strict`.
  ([#11](https://github.com/keyfire/xbsl/pull/11))
- **A test helper declared twice.** `_rule_findings` stood as two identical copies in a row in
  the translation tests: the second silently replaced the first, which had been dead since the
  day it was written. The duplicate is gone, and a walk of the whole checkout now watches for
  repeats. ([#8](https://github.com/keyfire/xbsl/pull/8))

## 2026-09-10 – 0.100.0, 0.101.0

### Added
- **`translate_unused --since`: the orphans of ONE change.** A dictionary that has lived a
  while answers the plain question with thousands of rows – a live project with 31 628 entries
  reported 3 297 orphans, every one of them somebody's old deletion – and picking one's own out
  of them took a call per name: nineteen calls for a single change. `--since <ref>` (`since` in
  the MCP tool) keeps only the keys the project no longer spells anywhere AND that occurred
  nowhere but in the lines the change removed, read from `git diff`; on that same change the
  answer is 18 rows in one call. A branch or a commit is read from the fork point with HEAD to
  the WORKING TREE, so work not committed yet counts; a range `A..B` is handed to git as
  written. `--prune` beside it removes exactly that list – the narrowing is an intersection
  with the orphans of the whole project, so a diff read generously cannot cost a live
  translation. An answer with neither a filter nor `since` now says what its reading is worth:
  the reading is textual, and the list describes the whole accumulated dictionary rather than
  the change at hand.
- **`translate_unused` answers compactly and counts the orphans by kind.** `compact=true`
  keeps only the key, the kind, the file and the line of each entry – a cleaning pass needs
  the places, not the translations, and a page of sixty full rows cost five thousand
  characters for nineteen needed keys – and every answer carries `counts` over the whole
  filtered set, so the size of the cleaning is known before a page is read.

### Fixed
- **The languages of a project translate as the enumeration they are.**
  `LocalizationLanguages: [Русский, Английский]` came out `[Russian, English]` only where the
  project's own dictionary had been taught the word: the enumeration branch recognised only part
  of the classes the distribution describes enumerations with, and the language properties are
  described by another of them - so the English value was answered by the identifier plane by
  accident (the platform knows the term) and the Russian one by nothing at all. `DefaultLanguage`
  stayed data for the same reason, invisible because the language flip rewrites that line
  afterwards. The branch now recognises every enumeration class of the distribution; the same
  silence covered
  the `SecurityProtocol` of a Kafka channel and the `Capabilities` of a mobile application.
  Verified whole-tree on a live project: the English tree comes out byte for byte as before.
- **A localized string says where the TEXT of a translation is written.** Adding a `строка`
  to a LocalizedStrings element echoes the key into every translation the element has, with
  the default-language text; the note said only "replace it", as if by hand, while
  `meta_set_localization` (`set-localization`) writes every language in one call - so the note
  names it now. And a call aimed at the translation FILE was refused with "the kind ? has no
  section for 'строка'": a translation carries neither a kind nor the sections of an element,
  and every check that asks it for one describes a file that does not exist. The refusal (of the
  property editor as well) now names what the file is, the element it translates and the
  call that writes the row.

## 2026-09-09 – 0.97.0, 0.98.0, 0.99.0

### Added
- **`translate` judges the dictionary itself: an entry against the platform, a literal
  against its key.** A dictionary entry that spells a platform member the way the platform
  spells it nowhere (`Severity` for the event's `Importance`) and a named literal whose
  `%{...}` substitutions differ from its key's now fail the strict gate, each with the
  spelling to put right; a word the platform spells two ways is not judged.
- **`tools/parity_seed.py --quiet`** prints only the seeds that disagree (known gaps included)
  and the summary line - a full run is hundreds of `[ok]` lines read for one number.
- **`code/dead-interpolation`: a doubled interpolation sign kills the expression.** The
  platform reads `"%%{Query}%"` as an escaped sign: the expression is never evaluated and
  the value carries its TEXT - `%{Query}%`. Neither the compiler nor the linter said a word,
  and a site's substring search silently matched nothing until reviewers of the platform read
  the code. Measured on a probe project compiled by the platform: the compiler names the
  unknown name inside `%{...}` and `${...}` (the control - the module did compile) and stays
  silent inside `%%{...}` and `$${...}`, for both signs. The rule is a file rule at error
  level, and its fix inserts the escape that was meant (`"\%%{Query}%"`); the correctly
  escaped spelling is not a finding.
- **`--list-rules --format json` answers with the rule catalogue as data.** The text
  listing carries the parameters and the off reason on continuation lines, which a client
  parsing the first line with a regex dropped - and that prose changes with the language of
  the run. The key prints the same records the MCP `list_rules` tool answers with (`id`,
  `tier`, `severity`, `off_reason`, `params`); the rules panel of the extension reads it.
- **The `xbsl new-object` command takes a `--base` key.** The base type of an interface
  component could only be given through MCP and the LSP; from the command line the
  component had to be finished by hand. The value goes through the same checks as on the
  other surfaces.
- **`yaml/property-shadows-module`: a component property named after a common module of
  the project.** The property name hides the module across the whole component, and the
  `Module.Method()` accesses written before it are read as members of the property value:
  the apply fails with an unknown-method error, the stand rolls back to the previous build,
  and the complaints point at the component file carrying the real method names - the module
  looks broken while it is merely hidden. The rule names the clash at the property
  declaration, in both spellings of the sources. Only a common module is judged, and only
  one reachable by the bare name - the component's own subsystem, or one its yaml imports;
  a namesake catalog, enumeration or component is left alone, because such a name is used
  in a TYPE position, which a property does not take over. There is no autofix on purpose:
  the cure is a rename, and the name is written in the markup, in the paired module and
  outside the component as well.
- **A rule now says the value it judges by, and the listing can be asked about one rule.**
  `--list-rules` and the MCP `list_rules` gave the id, the title, the tier, the severity and
  the "on by default" flag; the threshold itself lived as a constant in the sources, and
  learning it meant rewriting the code around a guess and re-running the linter over the whole
  project - a method body cut to six lines was reported, the same body at four was not, and two
  full runs bought a number the tool already knew. Seven parameters are declared where the rules
  use them - `code/duplicate-method-body` (min-lines), `yaml/duplicate-subtree` (min-nodes),
  `style/line-length` (max-length), `code/parse-error` (max-per-file), `yaml/hint-too-long`
  (limit, margin), `security/hardcoded-secret` (min-literal-length) - and travel with the rule:
  the value in force, the default, a one-line description and the environment variable that
  overrides it (`XBSL_` plus the rule id and the parameter name). `xbsl --list-rules --select
  code/duplicate-method-body` and `list_rules(select=...)` answer about one rule instead of the
  whole registry, an unreadable override keeps the default and says so, and a run whose
  parameters are off their defaults names them in its provenance - a threshold changed by the
  environment changes the findings. A selection that matches nothing now says so instead of
  claiming an empty registry - the old line sent the reader looking for a broken install.
- **The stale baseline entries are named in the MCP answer, and `baseline_prune` removes
  them.** The summary of `lint_paths` said `baseline_stale: 9` and stopped there: which nine
  could only be found by taking the file apart with a script of one's own, sorting the entries
  by the prose of their `reason`, and nothing in a session could remove them. The entries now
  travel with the count in `summary.baseline_stale_entries` (path, rule, message, count,
  reason), exactly as the CLI json carries them, and the new `baseline_prune` tool removes
  exactly those, keeping the file's order and format and answering with every entry it took
  (`dry_run` shows what would go). Removing stays a deliberate act: an ordinary check never
  touches the file.
- **`meta_set_localization` / `xbsl set-localization`: one localized string, every language
  at once.** `meta_add_localization` adds a LANGUAGE; a ROW had nothing, so a caption was
  typed into the `LocalizedStrings` element and again into its English twin, and the two
  files drifted apart with nothing but a pair of eyes to compare them. One call now writes
  the default-language text into the element and every other language into its own
  `Localization/<Code>/<Name>.yaml`, correcting a row that is already there in place. A
  language named without a translation file is refused, naming the tool that adds one; an
  existing language the call says nothing about still gets the row, with the default text
  and a note, so no translation is left a key short. The section is kept where the key
  already lives (`Rows` for a new one), and either spelling of it is accepted.
- **`translate_unused`: the orphan pass is an MCP tool, not only a flag.** What the
  dictionary still says and the project no longer has was reachable from the console alone;
  an agent that had just deleted a component had to shell out for it. `filter` narrows the
  answer to the names of THAT component rather than the whole history of the project, and
  `prune` - off by default, and named apart from the listing on purpose - removes exactly
  the page the tool answers with. `--stale` is accepted as the CLI spelling of `--unused`.
- **A page says what it left out.** `translate_gaps` answered `total: 72` beside exactly
  fifty rows and marked the cut nowhere; a dictionary built from that page was short by
  twenty-two entries, found by the strict pass after the merge. Every paged translation
  answer now carries `truncated`, `shown`, `remaining` and a `hint` naming the next
  `offset`, `limit=0` for the whole list and - for the gaps - `--missing`, which writes the
  entire remainder to a file.
- **Parity seeds cover 85 rules with 169 seeds (up from 120 seeds on 62 rules).** The batch
  went to the rules that match text against the platform's vocabularies: the joined tables,
  the fields and the filter of a dynamic list, the compatibility mode, an object-typed
  value, a list-typed slot, the hint length, a popup component in the markup, bindings and
  computed properties, the fields of a list row and of a project structure, the
  client-availability annotations, a parameter inside a query literal, and the names of
  enumerations, common modules and the kind inside a name. Every seed carries a
  hand-written English twin; the known gaps are three now - two behind the member catalog,
  the third behind the Russian words of the naming standard.

### Changed
- **The run summary names the keys that list and remove the stale baseline entries.**
  The "stale baseline entries: N" line was a count with nothing to do about it: finding
  out WHAT went stale meant calling the MCP `lint_paths` or subtracting the live findings
  from the keys of the file by hand. The run now prints `--stale-baseline` and
  `--prune-baseline` under that line; with nothing stale, or right after those keys have
  listed the entries, the hint stays silent.
- **The stale baseline entries are read out with their reasons.** An entry's `reason` is prose
  a human wrote about a deliberate exclusion, and the listing printed the path, the rule and
  the message without it. `--stale-baseline` and `--prune-baseline` now print the reason under
  the entry, and pruning says how many of the removed entries carried one - after the commit
  that text lives on only in the git history.

### Fixed
- **A local built by a static member of a platform type is typed.** `use Search =
  EventLog.Find(...)` and the event read off the result stayed untyped: the walk over the
  declarations read no bare name as a type, so a member of such a local fell to the flat
  vocabulary - and to any dictionary entry spelled against the platform. The walk now keeps
  every name the method declares off the type-name shortcut and reads the rest as the types
  they are; three corpora answer with the same findings as before.
- **`code/local-method-cross-component` sees an English tree**: the components collection was
  matched by its Russian name alone, and `Components.X.Y(...)` was never judged. The English
  spelling comes from the platform dictionary. Found by a parity seed.
- **`yaml/no-expression-in-literal` sees an English tree**: the literal-only types were listed
  in Russian alone, and `Type: AbsoluteFont` with an expression in `Size` passed. Both
  spellings now come from the type pairs. Found by a parity seed.
- **The translator renames a subsystem descriptor's `Name` with its directory.** The value was
  left as data while the directory took the token, and on the translated tree every import
  naming the subsystem stopped matching it (`yaml/localization-missing-import` reported a
  reference that was imported). Found by a parity seed.
- **Parity seeds: 74 more, 129 rules covered** - computed access control, references across a
  subsystem boundary, localized strings, resources, declarations, arity, conditions, names,
  identifiers, the project descriptor.
- **`yaml/choice-needs-static-list` sees an English tree.** The rule looked for the component
  and its primitive types by their Russian spellings (`ValueChoice<String>` in English) and for
  the list key by one name: on a translated project it stayed silent about the real finding and
  reported a node that does carry the list. The component, the primitives and `Array` now come
  from the platform dictionary, and the list key is canonized through the ui schema (`ChoiceList`).
- **The resource rules and the closeable one see an English tree.** Both blindnesses were found
  by parity seeds and both were of one kind - a platform word known in Russian only.
  `code/resource-bare-name` and `code/unknown-resource` looked for the literal `Ресурс{...}`
  verbatim while a translated module writes `Resource{...}`: the pair of spellings now comes from
  the platform's own dictionary. `code/unclosed-resource` ended its type inference at the first
  member (`.Выполнить()` against `.Execute()`), because the catalog stores members in Russian -
  the type name and the member name are now read in either spelling, and an unpaired member still
  ends the inference silently.
- **An English project gets English names where the tool invents them too.** A standard
  attribute (the `Name` of a catalog, the `Period` and `Recorder` of a register) used to be
  completed in Russian and reached the generated forms, because the language pass protects
  field names as the author's. The completion is now written in the spelling of the FILE,
  together with the hierarchy attribute and the facet of its type, and the value of an
  interface enumeration comes from its own dictionary (`WidthInColumns: Single`). The facet
  table also joined the shared translation of type expressions: after a dot stands a facet,
  and the property vocabulary calls the same word something else.
- **The type of a new item is read the way a component base is.** `meta_add_field` and
  `op_add_field` undo markup escapes in the type value, refuse what is not a type at
  all, and write the type in the spelling of the PROJECT (an English name lands in
  Russian inside a Russian project). A composite type with its alternatives still
  passes whole. The value of a mapping section (a localized string) is not put through
  this check: there an ampersand and a semicolon are legal text.
- **One unreadable yaml no longer buries the report under phantom findings.** A file that
  failed to parse used to drop out of the project model entirely, and the object it declares
  became an unknown name for every rule at once. Measured over a live project: a broken
  component gave 239 findings instead of 49 (175 of them `code/undefined-name`), a broken
  catalog 180 instead of 50 (63 `yaml/unknown-type`, 34 `code/undefined-name`, 31
  `query/unknown-table`, 2 `code/unused-import`). Such an object is now known by NAME and
  unreadable at the same time: `code/undefined-name` leaves the paired module alone (its
  scope is unknown, not empty), a type root and a query table built on it are not called
  unknown, the import of the subsystem holding it is not called unused, and the
  `@ClientAvailable` declarations of the paired module are not called unused either. One
  real finding remains – `yaml/valid` on the breakage itself.
- **The orphan pass reads a comment the way the translator writes it.** It used a regex of
  its own that took one space off the marker, so a doc comment (`///`) came back with a
  slash glued to the text, a `##` line with a hash, and a block comment was not read at
  all - every phrase written from such a comment would have been reported as an orphan,
  which is the one mistake `--prune` acts on. The payload now comes from
  `code.comment_payloads`, the function the translating pass itself calls. A name is also
  looked for in the FILE NAMES, since a folder and a file go through the same token plane.
- **The dictionary reader sees a key written in the explicit yaml form.** A dumper writes a
  long key as `? key` on one line and `: value` on the next, and nobody chooses that - the
  live dictionary of a real project holds two literals in the shape. They were invisible to
  the table, to the orphan pass and to the writer, which would have added a key that is
  already in the file; the writer now replaces and removes both lines as one entry.
- **`meta_add_form` writes the captions of a generated form through the project's
  dictionary.** A generated form used to arrive with its captions as literals – the form's
  own one plus every table column – and on a bilingual project that is eight findings of
  `conventions/untranslated-visible-literal` on one object, rewritten by hand right after
  generating. What is written instead comes from the sources rather than from a choice: of
  303 table columns of a live project 300 carry a caption (the three that do not are picture
  columns), every one of them is a `$Dictionary.Key` reference, and the key is the field's
  own name. So the reference goes in – and the keys it needs join the subsystem's dictionary
  in the same operation, echoed into the translations that dictionary already has, because a
  reference to a key nobody declares is worse than a literal: the apply fails and the stand
  rolls back. The dictionary has to be the one lying beside the object (another subsystem's
  would need an `Import` the form does not carry), the project has to declare two
  localization languages, and a name the dictionary spends on a TEMPLATE stays a literal – a
  reference resolves against the strings alone. Without such a dictionary nothing changes.
- **`meta_new_object` writes the base of a component the way the project spells its types.**
  The `base` key is documented in English words, so `base="Group"` is the natural thing to
  pass – and a Russian project got `Type: Group` in its yaml, a line rewritten by hand every
  time: the linter says nothing about it and the compiler only speaks at deploy. The base is
  now written in the language of the project both ways, and whether it names a FORM – the
  bases that need the form-template wrapper – is decided on one spelling, so an English form
  base no longer loses the wrapper either.
- **`meta_set_component_property` writes a one-entry composite as a block.** Only a FLOW
  collection now goes inline after the key; a fragment shaped `Key: value` becomes a nested
  block. Written inline it produced `EditingSettings: Type: SwitchEditingSettings`, which
  yaml refuses to read at all, and the whole edit came back with the parser's "mapping
  values are not allowed here" - the block had to be typed by hand. One entry is not an
  exotic case: the editing settings of a switch (a checkbox in a table cell) have no
  properties of their own, so that is the only form the value takes.
- **An escaped `base` is read as the brackets it stands for.** `base="Form&lt;Boolean?&gt;"`
  used to go into the yaml exactly as it arrived: the file looks finished, and the compiler
  meets the garbage only at deploy. The escaping comes from the CLIENT of the tool rather
  than from a person's hands, so it is undone instead of reported – and what is left of a
  mangled value afterwards, anything that is not a type expression, is refused rather than
  written into the file.
- **`yaml/bare-object-value` judges an English component too.** The table of components with
  object-typed properties was keyed by the Russian name, so `Type: Label` matched nothing
  and a bare word in the value was never reported on a translated tree. The component is
  keyed under both spellings now, the way the sibling table of the same module has long been.
- **`code/unknown-structure-field` judges a member written in Latin.** The exception was
  inherited from the sibling member rules, where it guards the platform catalog stored in
  Russian; here the member set comes from the project's own declaration - written in the
  same script as the access - and a translated project went unjudged entirely. A Latin
  member the declaration does not carry is reported now; a serialization-contract field
  (`access_token`) is in the declaration and stays silent.
- **The object protocol is recognised in both spellings.** `GetType`, `ToString` and
  `Presentation` were written in Russian alone, and `code/unknown-row-field` raised an error
  on the legal `Line.ToString()`; the English half comes from the dictionary. The row type's
  own members (`Data`, `Key`) are paired there as well - the catalog keeps them in Russian
  while a translated module writes `Key`.
- **`naming/enum-vid`, `naming/module-suffix` and `naming/kind-in-name` read an English
  name.** The kind word leads a Russian name and trails an English one (`ApplicationType`,
  `StuckTasksReport`), and a common module's environment suffix is spelled in English by
  the dictionary pair (`ExchangeClientAndServer`). All three rules looked for the Russian
  spelling alone and stayed silent on a translated tree; the English pair comes from the
  dictionary, and a form the dictionary does not name (the plural of the kind word, the
  word for a register) is left unjudged rather than invented. The messages have their own
  wording for the tail - "ends with" rather than "starts with".
- **`code/bound-property-assign` matches an English pair of files.** The markup keys are
  kept under the canonical name while the property from the module was looked up as the
  code spells it, so `Height: =...` in the yaml and `Components.Block.Height = 640` in the
  module never met and a translated pair went unjudged. The property from the code is
  folded to the canonical name before the lookup.

## 2026-09-08 – 0.95.0, 0.96.0

### Added
- **The `yaml/list-scroll-without-loading` finding comes with a quick fix.** The rule now
  carries an autofix: the value becomes `LoadingOnScroll` in the spelling of the one it
  replaces, a qualifier kept. Until now the editor offered only silencing it in the
  baseline.
- **`yaml/list-scroll-without-loading`: the list is scrolled, yet the scrolling loads
  nothing.** `Navigation: None` means not "no pagination" but "no loading": the rows come
  in a single `PageSize` portion and the tail of the data is unreachable - the
  `ListNavigation` documentation says so outright while the compiler stays silent. Judged
  is the pair "a scroll is promised (`VerticalScroll` other than `False`) and the
  navigation is `None`" on the components the ui schema gives a `Navigation` property to;
  an expression in the value and a list that promises no scroll are left alone.

## 2026-09-06 – 0.94.0

### Added
- **`code/param-redeclared`: a local `val` / `var` / `use` with the name of the method's own
  parameter.** The compiler answers "a variable named X is already defined" only at the server
  apply, and the stand rolls back; the linter reports the clash at the declaration, nested blocks
  included, in both spellings. Loop and catch variables, lambda parameters and lambda bodies are
  not judged: the corpora carry none.
- **`docs_symbol` and `docs_page` answer briefly or with one section.** A type page runs to ten
  thousand characters – the constructors, every property, the inherited lists – while "which page
  is it and what is it about" needs the head alone: `brief=True` returns the summary and the
  section names, `section="Properties"` the head plus that one section (the pages' own Russian
  headings work too); an unknown section answers with the names to choose from.
- **Parity seeds cover 62 rules with 120 seeds (41 seeds on 23 rules before).** The rules that
  judge text by the platform dictionaries – attribute properties, form components, module
  environments, the query language, sizes and layout – each carry a Russian case and a
  hand-written English twin now; four known gaps are marked with their reasons, two behind the
  member dictionary and two behind the translator.

### Changed
- **`meta_add_field` names a section it creates and points at the sibling one** (`add-field` and
  the LSP `xbsl/metaAddField` alike). A register keeps its data in `Dimensions` and `Resources`,
  and an attribute asked of a register holding resources and no attributes used to open a new
  `Attributes` section at the end of the file without a word – the field was then moved by hand,
  UUID and all. The section is still created, but `notes` say so and name the field kind (a
  resource here, and the other way round) that would have placed the item beside the existing
  fields; an item of an existing section still joins its end, which a test now holds.

### Fixed
- **The translator spells the reference member of a project facet `Reference`**
  (`Line.Reference.LoadObject()!`): a receiver typed by a facet of a project object – declared,
  inferred, or loaded from a reference – carries the facet word, and an untyped one carries it
  when the chain goes on to `LoadObject`; the link property of a label or a picture stays `Link`,
  and an entry qualified by the receiver still answers first.
- **A default qualified by its own enumeration moves in both halves** (`DefaultValue:
  States.Open`) where the sibling `Type` names a project enumeration – the shape
  `yaml/enum-default-value` reports, which the English tree could not carry while the value
  stayed Russian.
- **`Auto` on a union-typed property is translated** (`MaxWidth: Auto`, `Height: Auto`,
  `Tooltip: Auto`): a value spelling a member of the property's union is that member, spelled
  by the platform's type pairs, not data.
- **`yaml/ref-needs-nullable` recognizes a reference type by the English facet spelling too**
  (`Applications.Reference`): the yaml branch kept the Russian facet in its pattern and its gate,
  so a translated description passed without a finding.
- **`code/member-kind-mismatch` judges the member kind in the English spelling of the type and
  the member** (`TimeZone.Current` without brackets): the kind table is keyed by the catalog's
  Russian names, and both sides are now brought to them through the dictionary.

## 2026-09-05 – 0.93.0

### Added
- **`meta_add_form` makes an information register's record form (`forms=["record"]`).** A register
  has no object form - what gets edited is its RECORD, and the `RecordForm<Register.Record>` with
  fields for the dimensions and resources had to be written by hand; the object-form refusal now
  names the record form instead of the list form alone.
- **`meta_new_object` takes the base of an interface component (`base`).** The scaffold always
  inherited a form with a template, while the most common base in a live project is `Group`
  (31 against 7 for a bare form): the whole `Inherits` block was rewritten by hand.
- **`yaml/slot-needs-list` (tier D, error) - a slot declared as a list, holding a single
  component.** A component written under `Content:` without the dash is not a list of one:
  the yaml parses, every key exists, and the apply is what refuses the markup - on the server,
  rolling the project back to the previous build. The shape is judged by the ui schema rather
  than by the property name: on a form template the same slot legally holds one component.

## 2026-09-04 – 0.92.0

### Added
- **`code/member-kind-mismatch` (tier D, error) - a stdlib method read as a property, and a
  property called as a method.** The member exists; the form of the access is wrong, and the
  apply refuses the project with `Unknown constant` or `Unknown method`, neither of which
  names the kind or the cure.
- **`code/unknown-form-component` (tier D, error, file scope) - an access to a component the
  form markup does not declare.** `Components.X` is the static map the markup gives, so a name
  without a counterpart there does not exist: the apply refuses the project, and until then
  nothing sees it - the name outlives a component taken out of the markup.
- **`code/server-annotation-in-client-module` (tier D, error) - the mirror of the client
  annotation check.** A module with `Environment: Client` carrying `@OnServer` compiles for the
  server, where its own type does not exist, and the apply refuses every such method with a
  message that names neither the environment nor the module.
- **`xbsl translate --unused` names the entries the project no longer uses; `--prune` removes
  them.** Deleting code leaves its names and comment lines behind, and nothing reported them:
  the strict pass judges what is not covered, and the entries table shows where a pair is
  declared, not whether anything uses it.
- **The `xbsl translate` report says when the dictionary has fallen behind the sources** - how
  many files were changed after it and which is the newest (`dictionary_behind` in json).
  Modification times are what is compared, so the mark stays a note and never changes the
  verdict.

### Fixed
- **The project's name shadow was lost on CRLF files.** The pattern that collects the yaml
  names ended at the end-of-line anchor, and in multiline mode that matches before the line
  feed. An empty shadow means false findings from an error-level rule: a project object named
  like a platform type was reported as an unknown member.
- **An unknown `kind` is refused instead of answering with an empty list.** The section name in
  the plural matched nothing and the answer came back empty - indistinguishable from "the
  dictionary covers everything", and a run that trusted it left the gaps to the strict pass.
- **`translate --set` names the entries it overwrote.** The report carried only a count, and
  finding which existing keys got a new value meant diffing the dictionary.
- **A localized string carrying a character yaml reads specially no longer breaks the file.**
  What is quoted is what would not read back bare; an ordinary phrase stays unquoted. A new
  string also reaches the translation files with the default-language value.
- **The first dimension of a register takes the place of the placeholder instead of landing
  beside it**, and the `Length` of a standard field is checked by the tool: the platform limit
  used to be caught by the linter on the next run, over a file the tool had already written.
- **`yaml/valid` names a ternary written with spaces.** YAML reads that as the start of a
  nested mapping, and the complaint lands on a line that has no mapping in it.
- **A client common module is caught at any server-side consumer, not only an HTTP service**,
  and three environment checks became errors: the matrix was put through the compiler, and
  every miss is a compile failure that rolls the whole project back.
- **The build number is recorded only for the version it belongs to.** Extracting under a
  borrowed name recorded that the directory holds a build of a version it was never taken from.

## 2026-09-02 – 0.89.0, 0.90.0, 0.91.0

### Added
- **`meta_add_field` knows the built-in attributes.** `Number` and `Date` of a document, `Code`,
  `Name` and `Owner` of a catalog are judged by their own descriptor class - the way
  `metadata_schema` already dispatched them - so `Length`, `Uniqueness` and the `Autonumbering`
  block are accepted instead of being refused as unknown properties of a regular attribute,
  and `type` may be omitted where the class fixes it. Property values take a nested block as a
  dict or a dotted key and a list as a sequence (CLI `--prop`, LSP and MCP alike); a block of a
  class the metamodel does not describe is refused by name as a known limitation.
  `meta_set_field_property` takes the same shapes and replaces a nested block whole.
- **`lint_paths` takes `root` like the `meta_*` tools do.** Relative `paths` and `baseline`
  resolve against the caller's root rather than the server's working directory, so a session
  in a git worktree no longer checks the other checkout and reads its clean answer as its own;
  the diagnostics carry absolute paths and the summary names the `root`.
- **`code/foreign-not-public` (tier D, error, project-wide) – the code side of
  `yaml/foreign-not-public`.** A module reaching an element of another subsystem left at
  `VisibilityScope: InSubsystem` (or with no scope at all – the default) was refused by the
  compiler on deploy while the linter stayed silent: `code/missing-import` deliberately leaves a
  non-public target alone. Written type positions and the roots of `Module.Method()` chains are
  judged; the project module belongs to no subsystem and is foreign to every one.
- **`xbsl baseline add <paths> --rule <rule> [--reason ...]`** appends only the new findings of
  one rule: a new file takes its sorted place, nothing else moves, recorded reasons stay, a
  repeated call changes nothing; `--format json` answers `{baseline, added, findings, written}`.
  Saving keeps the file's line endings and BOM; a new file is written with LF.
- **Every `meta_*` MCP tool takes `root`** – the caller's root: relative paths resolve against
  it instead of the server's working directory, and answers carry absolute paths plus `root`.
- **Parity seeds: 27 new seeds over 14 rules** that judge by the platform vocabularies; a seed's
  English twin is written by hand from the data and the translator's output is checked as a
  third tree.

### Changed
- **The visibility rules read bindings and qualified names.** A probe applied on a server
  refused a binding to a non-public element of another subsystem, a qualified
  `Subsystem::Element` binding and a qualified call from code with the same
  `Type "..." is invisible due to visibility modifier` the type positions get, so
  `yaml/foreign-not-public` now judges the roots of binding chains (less what the paired
  module declares) and qualified names in bindings and type positions, and
  `code/foreign-not-public` judges qualified names too - by the subsystem they name.
  The import rules keep leaving the qualified form alone: it needs no import.
- **`xbsl translate` ends with a verdict line**, `READY` / `NOT READY: tokens N, phrases M` –
  the tail of a log no longer reads as success with hundreds of gaps; the json report carries
  `ready`, the exit code is unchanged.
- **The translation tools refuse a root without a dictionary** and name where one is looked for
  (and where it sits when below the root); `translate_gaps` reports `dictionary`. The CLI does
  the same: `--gaps` without a dictionary refuses, the report writes `dictionary` into its JSON.
- **The baseline is judged only within the requested paths:** entries of other files are not
  checked, never stale (an MCP request for two files answered "0 suppressed, 76 stale" on a
  clean project). `baseline_not_checked` splits into `_rules` and `_paths`.
- **The summary names what judged:** `engine`, `plugins` with versions, `rules {active, total,
  plugin}` in the CLI json and MCP answers, a "Run set" line in text.
- **The terms extractor files members declared by Constants classes under their type** and adds
  class-declared type pairs – the data needs regenerating to pick them up.

### Fixed
- **Two parity gaps closed: `yaml/unexpected-type-argument` and `yaml/enum-needs-nullable`
  judge an English tree as they judge a Russian one.** The first gated on the `Тип:` key alone
  and canonized neither the component nor the type head, and would have reported the English
  default as a stranger; now the key, the component, the property and the head are canonized
  and the argument is compared with the default name by name in either spelling. The second
  recognized the input field by a hand-written `InputField`, which no serializer writes: the
  platform spells it `Edit`, and the spellings come from the data. `code/reserved-name` now
  reports the capitalized `Type` too - a live apply refused it like `Тип` and `type`. 41 parity
  seeds, 0 disagreements, 1 known gap left (the member catalog).
- **The term extractor fills the gaps of the common table with the terms classes state.** The
  built-in code attribute had no common spelling: a dozen classes state the term `Code`, and
  the neighbourhood reading refuses `Code` as an English candidate because a class-file
  attribute is named so. With the pair absent, `yaml/unknown-attribute-property` tolerated the
  keys of the code attribute on every ASCII-named attribute of an English tree - `Length` on a
  number went unreported. A stated term answers only where the neighbourhood settled nothing,
  so the settled spellings stay; data rebuilt with the fix carries the pair.
- **A name inside a type expression of the code is translated as a type.** The token walk
  did not tell a type position from a member access, and `.Ссылка` typing a parameter, a
  declaration, a constructor, a cast or a type argument came out as the property `Link`
  instead of the facet `Reference` - the English tree did not compile, and a parity seed of
  `code/unknown-ns-object` had to be marked as known. The spans of the type expressions now
  come from the parser, and a name inside one resolves the way a yaml type does.
- **A member of a local declared without a type is spelled by the inferred type** (constructor,
  cast, literal), through the owner table walked up the base types (`Remove` on a map);
  `code/unknown-member` accepts the ancestor's spelling.
- **The default of a field typed by a project enumeration is translated inside interface
  component properties too**, the type read the way `yaml/enum-default-value` reads it.
- **Two English-tree blind spots:** `code/global-unavailable` did not recognize a global by its
  English spelling, `yaml/unknown-type` never read the `Type:` key.

## 2026-08-30 – 0.86.2, 0.87.0, 0.88.0, 0.88.1, 0.88.2

### Added
- **The type catalog is completed from what the reference pages never describe.** The
  distribution describes the stdlib twice, and the language server's markdown holds more types:
  16 Std types lived only there, the whole `Favorites` branch among them, whose every call read
  as an undefined name. The structure comes from the markdown, the Russian spellings of members
  from what the shipped classes declare.
- **`classcode.declared_terms` - a pair read together with the field it is stored into.** The
  NAME of the static field tells what kind of member it is (`LINK_PROPERTY_TERM`,
  `SWITCH_SCREEN_METHOD_TERM`); the pair alone tells neither property from method nor a method's
  parameter from a member.
- **`yaml/duplicate-key` (tier A, error) and `code/duplicate-annotation` (tier C, error) -
  duplicates only the server compilation used to show.** A scalar key set twice in one YAML
  mapping is silently collapsed by the loader - the last value wins, the merged node passes
  every schema check, and the deploy used to be the first to fail; the rule reads the composed
  tree where the duplicates are still visible, flags the repeat and names the line of the first
  occurrence (the `<<` merge key and non-scalar keys are not judged). A duplicate annotation on
  one declaration - the "Annotation ... is already placed" error - also used to surface only on
  deploy.
- **Three rules over the dynamic list declaration.** `yaml/dynlist-joined-table-param` (error) -
  parameters and bindings in the joined tables: the list fails at runtime while the compiler
  stays silent; `yaml/list-form-needs-dynlist` (error) - a `ListForm` with an array-sourced
  table and no dynamic list: the navigation item silently disappears;
  `yaml/dynlist-filter-disabled` (warning, project-wide) - a filter declared off and enabled by
  the paired module: the first-render race, the first frame shows the whole table.
- **Property combinations half of which the platform silently does not draw.**
  `yaml/badge-column-image` (warning) - an `Image` on a column with `Kind: Badge`: the value is
  drawn as tag pills, and the picture is documented only for `Kind: Picture`;
  `yaml/value-choice-title` (warning) - a `Title` on a `ValueChoice` with an explicit
  `Switcher` kind is not drawn and the field stays unlabeled; `yaml/popup-in-markup` (warning,
  project-wide) - a popup component, the raw type or a project descendant through the
  `Inherits` closure, placed in the yaml markup: the content is drawn in the form flow before
  the window opens, and the cure is to build the window in code (a new `PopupComponent` plus
  `OpenInPopupWindow`); `yaml/col-width-needs-no-stretch` (info, off by default) - a numeric
  table-column width without an explicit `HorizontalStretch`: when the column stretches the
  width acts as a share rather than pixels - a sibling of the `size-needs-no-stretch` family,
  switched on pointwise when the symptom shows on screen.
- **`yaml/enum-default-value` (tier D, error, project-wide) and `yaml/event-property-type`
  (tier D, error).** The `DefaultValue` of a field typed by a project enumeration must be the
  bare name of a declared value: the type-prefixed spelling (`LabelVisibility.Invisible`) and
  an unknown name used to slip past the linter and were refused only at apply time ("an unknown
  enumeration item"); on an English tree the rule also catches a Russian value a translator
  left next to English items. An `EventLogEvent` property type outside the platform's closed
  list is refused by the server compilation at the price of a deploy; the list comes from the
  metamodel, and the message names the allowed types and advises writing variant values as
  string codes listed in the property's `Description`.
- **`code/load-object-unwrap` (tier D, warning) and `code/image-binding-server-call` (tier D,
  info, project-wide) - data does not arrive the way the code reads.** A force-unwrap "!" of a
  `LoadObject()` result on a reference taken from a field of another record or of a
  tabular-section row - a dangling reference after a physical deletion fails the whole pass,
  and the result must be checked for Undefined. An `Image` property binding whose call
  resolves - directly or transitively - into a server method: the image arrives by its own
  server round-trip after the rows are drawn and is requested again on every redraw; the cure
  is a field of a joined table or client-side data.
- **`code/permission-right-not-computable` (tier D, error, project-wide).** A permission
  granted by the permission-computing handler must be declared computable in the entity's
  yaml - otherwise the build applies and the permission recomputation fails at runtime;
  permissions are collected from `AccessPermission` constructors transitively over project
  calls, and delegation into a shared rights module is shown bound to the entity.

### Changed
- **Rule fixtures and the examples in the documentation now speak the demo project's vocabulary**
  (0.88.1). Names in an example have to read on their own rather than point at someone else's
  solution; the rule tables of both editions were brought to the same vocabulary along the way.
- **The package description names translation, the MCP server and the extension - in English.**
  The PyPI summary listed the linter, LSP, documentation and scaffolding - a set the toolkit had
  outgrown - and was the only Russian one among the neighbouring packages, while heading an
  English README. The keywords gained `mcp` and `translation`.
- **`yaml/missing-import` now reads the chain roots in markup bindings.** A
  `=ForeignModule.Method()` call in a property binding reaches a foreign subsystem the way a
  type position does, but without an import line the refusal used to come only from the server
  compilation at the price of a deploy; everything that explains the name on its own - the
  declarations of this yaml, of the paired module, the implicit platform names - is subtracted.
- **`yaml/empty-group-sized` now also catches a size binding (`Height: =...`) on an empty group
  without a `Name`.** An unnamed spacer with a computed size reads as an empty group and used to
  stay silent; named empty containers filled from code are not flagged.

### Fixed
- **The default of an enumeration-typed field now moves with its enumeration** (0.88.2). The
  metamodel types `DefaultValue` as a plain object, so the element name stayed Russian next to a
  translated enumeration and the build refused the pair with "Неизвестный элемент перечисления" -
  visible only at apply time. Judged narrowly: the field's type has to be a bare project name and
  the value a word the dictionary knows.
- **`--data-dir` did not reach the parallel workers.** The pinned root lives in a process global,
  and a spawned worker starts without it and took the INSTALLED data: the run read a dataset
  other than the one it was asked for, and said nothing about it.

## 2026-08-28 – 0.83.0, 0.84.0, 0.85.0, 0.86.0, 0.86.1

### Added
- **`yaml/computed-binding-assigned` (tier D, warning, project-wide).** Every instance of a
  component binds a property with a computed expression while the component assigns that
  property in its own module - the platform crashes on the assignment
  (IllegalStateException) on every run of that code. Reconnaissance shaped the
  narrowings: a named argument is not an assignment, and a code-built instance, a bare-path
  binding, a literal or an unbound instance make the assignment legal - the guarded-component
  pattern the corpus carries stays silent.
- **`yaml/inline-command-name` (tier A, error).** A command declared inline in the markup
  (an inline command-interface fragment or a single-command property) must not carry a
  `Name`: the platform refuses the node at apply time - "a command name is allowed only in
  command-interface-fragment project elements" - and the stand rolls back, so the defect
  used to cost a deploy cycle. A fragment PROJECT ELEMENT is skipped whole: there the same
  key is the point. Both spellings of the command components are read from the platform
  dictionaries.
- **`yaml/localization-missing-import` (tier D, error, project-wide).** An unqualified
  `$Dictionary.Key` reference whose dictionary lives in another subsystem needs that
  subsystem in the `Import` section of THE SAME yaml - an import in the paired module does
  not cover the markup, and the apply refuses the node as a not-imported namespace. The
  rule mirrors the resolution rules of the documentation: a local dictionary wins, an
  imported subsystem resolves, the qualified `$Subsystem::Dictionary.Key` form needs no
  import and is left alone, and only public foreign dictionaries are candidates.
- **`translate_set` takes the batch as a file.** The new `edits_file` (MCP) sends hundreds
  of entries without inlining kilobytes of escaped JSON, and `--set` (CLI) now reads the
  same two shapes: the dictionary's own yaml format - `tokens`/`phrases`/`literals`
  sections, the dictionary's quoting, an empty value removes the entry - next to the JSON
  list `[{key, value, kind}]` scripts already produce. A file that yields no entries is
  refused rather than read as "nothing to change".
- **`translate_gaps` has a compact mode.** With `compact` every row is only
  `{key, kind, count}` - the worklist a translator actually needs; a full page of hundreds
  of gaps with places and suggestions did not fit a tool answer.
- **`tools/parity_seed.py` - the seeded bilingual parity check.** The measurement used so far
  was a counting diff between a Russian tree and its translation, and it is blind to a rule
  whose count is zero on both sides: `structure/xbsl-pair` lived in that shadow, reporting
  every English module of a generated type while no counted tree happened to carry one.
  The check plants its own case instead - a small Russian tree plus the verdict the rule owes
  it - and takes the English twin from the toolkit's own translator rather than a second
  fixture, so the spelling under test is the one the toolkit really produces. The verdict names
  the guilty side and its mistake (`en-misses`, `en-invents`), because a table lacking the
  English spelling makes a rule miss while one lacking the Russian reading makes it invent. A
  seed that stops planting its case reports `stale` rather than passing quietly, and
  `tests/test_parity_seed.py` runs the catalog on every test run. A gap that cannot be closed
  today is planted with a `known=` reason: it reports `known (...)` instead of failing, and
  the moment it starts agreeing it reports `fixed!` and fails, so the note cannot outlive the
  gap. The first such gap is already recorded - `code/unknown-member` skips Latin member
  spellings, and the member vocabulary is not complete enough to lift that yet.
- **The member names of the platform types are extracted in both spellings.** The reference
  documentation is Russian-only, so the catalog stored a type's members under their Russian
  names alone - and a rule judging a member of an ENGLISH project had nothing to compare
  against. The distribution itself states the pairs: 670 types, 5251 pairs, a new
  `member_names` section of `uiterms.json`. Kept per type rather than as one table, because
  the mapping is not a function - the same Russian word answers to more than one English one
  across types, and a flat table would have to drop a third of the section.

### Changed
- **A localization-swap problem names the key the SOURCE file spells.** The report used to
  say `'TaskCheckbox' has no en value` about a line the base file calls
  `ЗадачаФлажок`, sending the reader to the reverse dictionary; now the source name
  comes first and the translation follows in brackets.

### Fixed
- **The English spellings of members come from what the distribution DECLARES, not from how
  close two names stand to each other.** The former reading could take the name of a parameter
  for the name of a member: two pairs out of 2015 were wrong, and both named a method the type
  does not have (the `CharAt` of a string came out `Symbol`, the `Schedule` of the updating
  scheduled job came out `ScheduleWithoutTransaction`), so the translated tree would not
  compile. A name declared both as a method and as a property answers with the method
  spelling. The data has to be rebuilt (`xbsl extract --only terms,uiterms`), after which
  `code/unknown-member` stops reporting a legal call.
- **`meta_project_info` (and `project-info` in the CLI) can be asked narrowly: `kind`,
  `subsystem`, `brief`.** The whole tree in one answer did not fit a tool answer on a real
  project - 143 KB over a live corpus - and the question "what objects of kind X are here"
  cost two extra steps: save to a file and grep. The brief mode answers in 5 KB (381 objects,
  22 kinds), a kind filter in 24 KB. The counts by kind (`object_counts`) come with EVERY
  answer, filtered or not, so a filter that matched nothing does not read as an empty project,
  and `filter` states what was left out.
- **A baseline now travels between machines: a path INSIDE the text of a finding is read in
  the baseline's own form.** The cross-file rules name the second file the way the run
  received it - with the separators of the host, absolute when the root was absolute - while
  the identity of an entry is its text. A baseline frozen on Windows therefore suppressed
  nothing in a Linux CI and was announced stale on both sides (on one revision of a live
  corpus: "97 frozen, 2 stale" locally against "89 and 7" in CI). The path in a message is
  now read the way the path of the file is: POSIX, relative to the directory of the baseline.
  Existing files keep working without a rewrite - the common form is computed on both sides
  of the comparison.
- **The dictionary catalog is no longer counted as a source of the project.** A run rooted
  ABOVE the project (the repository root) finds the dictionary next to it, and its files are
  yaml of the same shape: their own comments came back as untranslated prose. On a live
  corpus such a run reported 871 phrase gaps and 99.19% coverage where the project itself is
  at 100% - a figure that looks trustworthy and sends the reader after a hole that is not
  there. The walk now skips the `xbsl-translation` catalog (and the file of the same name),
  along with a dictionary the caller named wherever it lies.
- **`translate_set` announced a removal that never happened.** A batch that removed an entry
  from a file and at the same time added a new one aimed at THAT file lost the removal: the
  addition rebuilt the text of the file from disk, overwriting the edits already planned,
  while the report still said `removed: 1`. Correcting an entry in the target file went the
  same way. New entries now go on top of the text already planned.
- **`code/unknown-member` judges English member spellings.** It used to skip every Latin
  member outright - with a Russian-only catalog, judging them would have reported correct
  code. Now a type whose WHOLE member set is stated by the vocabularies is judged in both
  spellings; one member without a stated pair keeps its type unjudged in English, so the rule
  keeps its zero-false-positive contract. Four in five types are covered.
- **A structure a module declares itself is no longer judged as a platform type of that
  name.** The rule is file-scope and cannot know project types, but the module's own
  declarations are in it - and a project structure that happens to carry a platform type's
  name had its own fields reported as unknown members.
- **A form tree covers a block sequence written at the column of its own key.** Yaml allows
  that spelling; the span of a node came from walking indentation, so such a sequence looked
  unindented and the node ended one line after it began. A node that no longer enclosed its
  children stopped `node_at` from descending, and every designer edit anchored below it was
  refused. The enclosing is an invariant now rather than a derivation: a node stretches to
  cover its children, whose bounds come from yaml's own marks.
- **A refused form edit says what it found.** The message named neither the place nor what
  stood there; it now names the line, the offset and the node the tree holds there.
- **A dictionary entry whose key holds `::` is no longer torn in two.** The entry reader
  ended a bare key at the first colon, while yaml ends it at a colon followed by a space -
  so a phrase citing a platform form by its `Std::Jobs::JobsForm` path was split mid-word,
  and the tail of the key was stored as part of the translation. Nothing complained: both
  halves are valid strings, and the damage surfaced only as a phrase missing from the
  coverage. Affects every writing surface - `translate_set`, the CLI `--set`, the editor
  panel.
- **`naming/prefix-by-kind` reads English names.** The head of an English compound is its
  last word, so a translated element carries the same kind word as a SUFFIX - the rule used
  to demand the Russian prefix literally and reported every such element of a translated
  tree; the expected spelling in the message follows the script of the name, and the
  English words come from the platform dictionary.
- **Three hand-written English spellings matched nothing and are data-driven now.** The
  stretch-weight property of `yaml/card-literal-stretch-weight` and the reference facet of
  `yaml/ref-input-auto-commands` and `code/ref-field-needs-req` were spelled by hand, and
  the serializer writes them differently - the rules went silent on a translated tree
  (one of the encoded tests asserted the wrong facet spelling and never could fire). The
  spellings come from the property and facet dictionaries; parity was measured by a full
  file-by-file run of the translated tree against the Russian one.
- **`structure/xbsl-pair` recognises an English module of a generated type.** A module
  extending a type an element generates carries the type's tail and has no descriptor of its
  own - `Prices.RecordSet.xbsl` is described by `Prices.yaml`. The tails came from a catalog
  that spells them Russian, patched with the single word `Object`, so every other English
  module was read as a module without a descriptor and reported - a finding its Russian
  twin never got. Both spellings are derived from the platform dictionaries now:
  the suffix set grew from 39 entries to 76, and no Russian tail is left without its English
  twin.
- **The hand-written English column of the derived-type tails is gone.** Nine of its thirteen
  names repeated what the dictionaries already answer, and four were guesses the platform
  does not support: `Ref`, `RecordManager` and `Selection` are 1C:Enterprise habits (Element
  spells those roles `Reference` and `Record`, and the dictionary reads `Selection` as a UI
  selection). Standing on the English side alone, they forgave on one spelling exactly what
  the rule reports on the other. What remains is one PAIR the dictionaries carry no entry
  for, kept whole so the two trees cannot disagree.
- **The catalog tables of the semantics rules drop on a data-root switch.** Four tables read
  the catalog of one version and cached it with no reset registered, so pinning another data
  root kept them answering from the version pinned before.

## 2026-08-27 – 0.81.0, 0.82.0

### Added
- **`naming/filler-word` and `naming/number` judge English names.** A translated tree used to
  pass both rules silently. The filler list carries both spellings, and a Russian filler
  prefix is caught where the translation puts it - at the end of the compound
  (`УправлениеСкладами` - `WarehouseManagement`). The head of an English compound is its last
  word (`BankAccounts` - `Accounts`), and its grammatical number comes from suffix heuristics
  with the irregular plurals listed - no morphology extra is needed for it; mass nouns and
  the ambiguous `-os` tail are left undecided rather than guessed. The standard's exempt
  heads (`TaskData`, `MessageQueue`) are known in both spellings too.
- **A translated description is parsed like the original.** The name key (`Name:`) and the
  section keys (`Attributes:`, `TabularParts:` and the rest) are read in either spelling by
  the naming rules and the indexer; the English spellings come from the metamodel, not from
  a hand-kept list.
- **Localizable yaml values are translated by the literals plane.** A value the metamodel
  declares a localizable text (`Localizable`) - the presentations of commands, access
  privileges and enumerations - is read by a person on the page: it is now either named whole
  by a literals-plane entry or reported as a gap, the way a presentation template already is.
  The `Description` property is developer documentation: it stays data and never enters the
  gaps.
- **The `literal-data-value` warning: a dictionary entry moved a literal that equals a value
  from a json resource of the project.** Such a literal is usually compared against that data
  (a seeding parse), and data is never translated - after the move the comparison goes silently
  dry; the class was found by an English-build review of the pilot project, where a full
  reseed lost the card layout. A data literal is marked by an entry whose value equals its
  key: the coverage is counted, the text does not move, no warning is drawn. The warning fires
  once per distinct text per file.
- **The translation report prints the warnings as a list** - file, line, kind and text (the
  first twenty) instead of a bare count: the details used to require the json mode.
- **The suffixes of a duration literal are translated** (`300мс` -> `300ms`,
  `2д14ч30м5с6мс` -> `2d14h30m5s6ms`). The Russian set comes from the documentation of the
  Duration type; the English spellings are confirmed by the platform compiler (a probe
  build accepts `2d14h30m5s6ms`). A number glued to letters outside the suffix set is left
  alone.

## 2026-08-26 – 0.79.0, 0.79.1, 0.79.2, 0.80.0

### Added
- **`yaml/duplicate-subtree` - a markup subtree copied into another file.** The shape is
  compared and the names and texts are left out: a new form is started by copying the
  neighbouring one, and the copy is renamed. The 40-node threshold and both exclusions are
  measured rather than chosen; off by default - how much sameness is too much is a decision of
  the project.
- **`yaml/toggle-command-pair` - a pair of usual commands with mirrored `Visible`.** Two
  adjacent commands of which exactly one is shown (`=X` against `=not X`) emulate one
  command with two states - the platform has the real thing: a `SwitchableCommand` carries
  the representations and images of both states, and the platform owns the state itself. A
  shared handler strengthens the case but is not required.

### Fixed
- **The presentation template of an event kind is translated whole, not by its expressions
  alone.** The prose a person reads in the log stayed in the source language silently; it now
  comes from the literals plane by the whole value, and what the plane does not name goes into
  the gap report.
- **The name of a named group and the call that reads it move together.** Both sides take the
  spelling from one source; the declaration inside the pattern used to be looked at by nobody
  while the argument of `Group("Name")` was translated, and the platform answered that no
  capture group carries that name.
- **Only the entries of the rules a run carried count as stale.** A rule left out of the set
  (a narrowing `--select`, off by default, unknown to the installed plugin) produces no
  findings by construction - and its entries were called stale, as if the debt had been paid.
  Two environments disagreed about one baseline because of it: an MCP server on an older
  plugin counted 48 stale entries on a tree CI called clean with the same rules. Such entries
  are counted apart ("baseline entries not checked", the `baseline_not_checked` key in json),
  and `--prune-baseline` no longer removes them.
- **The project's translation dictionary is no longer judged by the yaml schema rules.** A
  line of a dictionary file is a name and its translation, not a property of an object, and
  the one that translates a name into `Id` was read by `yaml/id-uuid` as a malformed id. A
  dictionary file is recognised by its own content - the format version and a translation
  plane - so the check stays file-scoped and does not walk the tree on every keystroke. The
  other rules of the module were already silent on a dictionary: it carries no ElementKind.
- **`code/duplicate-method-body`: which of the other places the message names no longer
  depends on the file walk order.** The CLI and the editor could name different places of
  one and the same copy, and a baseline entry keyed by the message stopped matching.

## 2026-08-25 – 0.76.0, 0.77.0, 0.78.0

### Added
- **`code/duplicate-method-body` - one body written twice in different files.** The
  normalized body of at least five lines is compared, so a reformatted copy is still a
  copy; a platform hook is told apart by its `@Handler` annotation. Off by default.
- **`code/client-available-unused` - a method open to the client that no client calls.**
  The annotation opens a surface nobody uses; the check counts a mention in a client
  module, in a client method of a server module, in a yaml and in a string literal as a
  use. Off by default, like `code/unused-method`.
- **`code/access-context-read-noop` - a context extension that grants a read everyone
  already has.** The type's yaml says `Read: PermitEveryone`, so the call hands out
  nothing and only suggests the data is guarded. The finding points at the privilege:
  alone it takes the whole line with it, among others only it goes.
- **`yaml/unused-component` - an interface component nothing places.** `code/unused-method`
  cannot see one in principle: its methods are called by its own yaml. A name written as the
  KEY of a dictionary is not a use; an entry point and a globally visible component are never
  judged, and the run has to cover a whole project.
- **`code/query-in-loop` - a query inside a `for` / `while` loop.** Every turn is a round trip of
  its own, so the cost of the method grows with the data and shows only under real volumes. The
  replacement is a single query over the whole set, the values of the turns passed as an array
  parameter of an `IN` condition.

### Fixed
- **`code/duplicate-method-body` names the FILE of the other copy, not the path it
  was reached by.** A run names its files however it was invoked, so the message -
  and a baseline entry keyed by it - differed between the CLI, the editor and
  another machine.
- **The table of a FROM clause counts as a usage of the object.** A bare identifier
  touches neither a dot nor a parenthesis, so `FROM Tasks AS T` - the very line a rename
  has to follow - was no usage at all: on a live project the index gained 374 of them.
- **An enumeration value of a block the ui schema does not describe now translates.**
  The sorting item of a list and an item of its filter are not in the schema, so the key
  beside the value turned English while the value stayed Cyrillic and the build refused
  it. Such a block names its property after its enumeration, and that table answers.
- **The editor now reads the query files of virtual tables, as the CLI already did.**
  The whole-project pass, the open buffer and the project index all skipped `.xbql`, so
  one and the same finding was visible or not depending on who asked, and the usages a
  query makes of an object stayed out of "find usages".

## 2026-08-24 – 0.74.0, 0.75.0

### Added
- **`translate --table` - the dictionary entries, the gaps and the totals out of ONE pass.** The
  editor table asks the engine exactly those three questions, and asked apart the answer cost two
  identical walks over the sources in two processes plus a third reading of the same dictionary:
  about nine seconds on a live project, repeated after every written cell.
- **A qualified dictionary entry now reaches a STRUCTURE field.** The fields of one structure
  share a namespace, so two Russian names translated into one English word make a structure the
  compiler refuses - and until now the only cure was renaming the Russian source. A qualified
  entry renames the declaration, every use through a receiver whose type is declared, and the key
  of the paired json resource together. The receiver as written still answers first: an entry
  qualified by a variable name keeps working.
- **The translator sees a collision between fields of one structure.** Only the compiler used to
  say anything about it - the same class as a collision of method names, but without a message of
  its own. It is now a reported problem, and it fails `--strict`.
- **Renaming and deleting an object take the virtual table of its list along.** The pair
  `<Name>ListTable` (a `.yaml` plus a `.xbql` query) belonged to no file family, and `.xbql` files
  were not walked at all - they name the object, so a renamed catalog left behind a query
  selecting from a table that no longer exists. Both spellings of the pair are known to the same
  rule.

### Changed
- **A platform member with no English spelling is the PLATFORM's gap, not the dictionary's.** The
  summary reported no platform gaps while the list of gaps named a method of the array type as a
  missing name: the counter contradicted the list. Writing such a name into the dictionary would
  mean inventing an English spelling for a platform member, which the compiler refuses. A name the
  platform declares as its own member and the data does not spell now goes to the platform gaps.
- **`--strict` fails on a platform gap too.** Such a name stays Cyrillic in the translated tree,
  so the build refuses it - a gate must not pass it. The cure is the platform data rather than a
  dictionary entry, which is why the report still names it apart.
- **The translation dictionary is read with the fast yaml loader.** On the dictionary of a live
  project (3.6 MB over 39 files) 1.4 s against 0.11 s; the pure-Python loader stays as the fallback for builds
  without libyaml.


### Fixed
- **The query literal of an undefined value translates to `UNDEFINED`, not to `NULL`.** The
  keyword table is extracted from the compiler data, and the literals are not in it at all, so
  the word fell through to the flat dictionary - which pairs it with `NULL`, a reserved word of
  its own that no Russian spelling maps to. The compiler takes both, so every check stayed
  green; on the running application a condition against `NULL` is never true, and the query came
  back empty. Met live on a translated corpus, where three places that depended on such a
  condition fell silent at once. The literals `TRUE`, `FALSE` and `UNDEFINED`
  are now stated by the engine, along with the single-word keywords the extractor pairs wrongly.

## 2026-08-23 – 0.73.0

### Added
- **`form/handler-signature` - a handler whose signature contradicts the event of the component.**
  The delegate comes from the ui schema with the component's own type arguments substituted, and
  is compared against the method of the paired module. The arity, a base type and an
  unsubstituted type parameter are not judged: reconnaissance over four corpora (483 handlers)
  showed each of them legitimate.
- **`typography/yo-in-text` - the letter "ё" in the text a user reads.** The visible properties
  of components and elements plus every entry of a localized-strings dictionary; a binding, a
  reference and a technical string are left alone. There is a fix, except where the letter
  carries the meaning. Off by default, like the other typography rules.

### Changed
- **A new dictionary file is created with a neutral head line.** It used to announce the editor
  panel whoever wrote it; `translate_set(..., comment=...)` and `xbsl translate --comment` name
  the batch's own subject. An existing file keeps its head line.

### Fixed
- **A collision of METHOD names is seen by the translator.** Two Russian names that English
  spells alike collide in the module they share, and the compiler refuses such a module - the
  check covered metadata names and the locals of a method, never the methods themselves. The
  collision now lands in `problems` (`translate_status` returns them, `--strict` fails on them),
  and `translate_set` answers with `collisions` when a value is already taken in the same scope.
- **The value a dispatched block is chosen by translates.** A schedule kind is neither a type,
  nor a property, nor an enumeration value, so no term dictionary pairs it. The metamodel
  annotation states both spellings all along - the extractor now carries the English one, and
  the hand-written pair for the standard code attribute is gone with it.
- **Seven enumerations whose English spellings were shifted by one value.** The values are
  constructor arguments, and the class declares them in the order of its own fields, which is
  not always the English name first. The pool states that order in plain sight.
- **Two query keywords the extractor read wrong.** A keyword the platform has no English
  spelling for is followed by a transliteration of itself, and adjacency read that as the next
  keyword's English. The pool is now read pair by pair; the workaround list on the translating
  side is gone.
- **Two rules an English project walked past.** `yaml/standard-field-length` read the attribute
  section by its Russian keys alone, and `yaml/presentation-field` compared the attribute type
  against the Russian spelling of the string type. The standard field names are taken in the
  spelling of the FILE, so a Russian source is unaffected.
- **The translation-gap rule no longer judges the dictionary itself.** Its own files are Russian
  by construction, and on a covered project the rule reported 826 "gaps", all of them the
  dictionary. It stays off by default (every file goes through the whole translation pass, which
  doubles the run), and the MCP lint tool takes an `enable` parameter now - the twin of `--enable`.
- **The MCP server applies the project's baseline, the way the CLI does.** The same folder read
  as clean in a terminal and as dirty through an agent. The file is discovered above the checked
  paths; `baseline` names another one, `no_baseline` asks for the frozen findings.
- **The first attribute of a fresh tabular part takes the placeholder's place.** The stub is
  recognized by both its name and its type, so an attribute the author renamed is left alone.

## 2026-08-21 – 0.72.0

### Added
- **Machine translation fills the dictionary's missing entries with suggestions.** `xbsl
  translate --suggest` asks an external service - Yandex Translate or Google Translate, picked by
  whichever credentials are set - about every entry the dictionary does not cover yet, and reports
  what came back for a human to accept rather than writing it in place. The project's own `terms`
  section rides along as a glossary, so a term the project already settled keeps its spelling
  inside a machine-translated sentence. An answer is cached by its source text and the glossary
  that produced it, so asking again over the same gaps makes no request at all - the report counts
  how many came from the cache. A key never reaches the command line: the engine reads it from the
  environment, and the VS Code panel gained a "Suggest via translation service" button that runs
  the same call over the open table and offers each guess a click away from being accepted, the
  way the platform's own spelling already was; its own key lives in SecretStorage rather than a
  setting.

## 2026-08-20 – 0.70.0, 0.71.0, 0.71.1

### Added
- **A third dictionary plane - `literals`.** The translator left string literals alone as data and
  said nothing about them, so a translated tree kept Cyrillic messages and the names written as
  strings (a parameter-store key, a contract field name). A team now lists such literals in the
  `literals` plane - the key and the value are written exactly as the text stands between the
  quotes in the source - and the engine replaces the literal as a whole. The code inside the
  value's interpolations is translated as usual, so whoever fills the dictionary needs no English
  spellings of names. A literal inside `Query{}`, `Pattern{}` and the other resolvable literals is
  left alone: there it is code. What the plane does not cover is reported honestly - in the run's
  summary, in `--gaps --kind literal`, in the MCP tools and in a `conventions/missing-translation`
  finding - and it never spoils the dictionary's coverage: those have a count of their own.
- **A comment is re-wrapped to the width after translation.** Translation keeps the line breaks one
  to one, so a comment that grew longer than its original ran past the width limit - on a real
  project that meant hundreds of `style/line-length` findings where the source tree is clean. A
  comment block is now re-wrapped to the same width the rule uses. Frames and separators, lists,
  tables and code samples, and lines that were long in the source already, are left untouched.

### Fixed
- **A route template carries its parameter names.** The template `/res/{код}` is data - a visitor
  types the path - but the name in braces DECLARES a parameter, and the handler reads it BY THAT
  NAME. Left as written it parted company with the translated call: the handler asked for a
  parameter the route does not declare, got nothing and answered something else - the static
  files arrived with a text/plain content type.
- **The rules judged a translated tree more harshly than its source.** The platform compiler
  accepted the tree while the linter found errors in it that the source does not have: an object's
  derived type, an exception name marker, a subsystem usage block, a member's nullability, an
  enumeration value and a built-in query table were recognized in the Russian spelling alone. Both
  spellings are now judged the same: on the six rules where the Russian and the translated tree
  of one project disagreed, the two now give one set of findings.
- **An enumeration value named `No` disappeared from its declaration.** The yaml reader parses the
  document as YAML 1.1, where `No` is false, so the item was lost and every use of it came back as
  a `code/unknown-enum-value` finding - while the platform accepted the very same file.
- **A dictionary key carrying a quote was read wrong and duplicated on write.** A comment line that
  cites something is an ordinary key here; the reader cut it at the first inner quote, the writer
  did not find such an entry and added it a second time, after which the dictionary refused to load
  over the duplicate.
- **The `xbsl translate` command** - source-to-source translation of a project into English
  spellings. Platform tokens go by the metamodel and the term dictionaries of the dataset
  (keywords by case-matched form, yaml keys by the class of their node, enumeration values
  within their enumeration, type expressions with facets, query keywords inside `Query{}`
  blocks, the code inside string interpolations); the project's OWN names and comment lines go
  by a project dictionary - a directory of yaml files (`xbsl-translation` next to or above the
  project) with two planes: `tokens` (one exact identifier to one exact identifier) and
  `phrases` (one comment line to its translation). Files and directories are renamed through
  the same token map, `Id` values never change, and the localized-strings layout turns around:
  the target-language section becomes the base, the original values move under
  `Localization/<Code>/`, the project's default and development languages follow. `--coverage`
  reports the dictionary's share per metadata object, `--missing` writes the untranslated
  remainder as a dictionary stub to fill, `--strict` gates a CI publish, and everything the
  dataset cannot spell honestly stays as written and is reported - never guessed.
- **Names the project declares are gated off the platform tables.** A word the platform
  dictionaries also know - an enumeration value, an attribute, a dictionary key - is
  translated by the project dictionary alone, so a declaration and every use of it move
  together or wait together. Without that gate the module already calls the English member
  while the yaml still declares the Russian value, and the build refuses the tree.
- **The dictionary answers as a TABLE, and the tools fill it.** `xbsl translate --gaps` lists
  what is missing (most frequent first, with places to look at and the platform's own spelling
  as a hint), `--entries` lists what the dictionary already says with the file and line of each
  entry, and `--set` writes entries back - adding, correcting in place, or removing by emptying
  a value. The same four questions are MCP tools (`translate_status`, `translate_gaps`,
  `translate_entries`, `translate_set`), so filling a dictionary of thousands of entries never
  means reading the files. The writer fits an entry into the file it edits, copying the indent
  from the neighbours of the section: a dictionary started with two spaces stays valid after an
  edit, and a comment on the section head does not hide it from the table. A finding of
  `conventions/missing-translation` now carries the facts
  a client needs to offer the repair - the exact key, its kind and the suggestion - in the new
  `Diagnostic.data`, which the language server and the machine-readable report pass through.
- **The keys of json resources follow their structure fields.** A structure reads its resource
  by FIELD NAME, so a key of the data is the same name written a second time; rename the field,
  leave the key, and the binding finds nothing - silently, because the reading options tolerate
  an unknown property and initialize a missing field, so the translated project compiles,
  applies and starts with empty data. Only keys that name a field of a project structure move;
  values, and keys no structure declares (a map keyed by content, an external contract), stay as
  written, and the rewrite is by span, so the file's formatting survives. The compiler has
  nothing to say about it: a name that drifted apart is data.
- **A resource path inside a string follows its file.** The pass renames the resource files
  and directories, so a literal that addresses a resource (a path shaped like
  `"<Directory>/%<Field>.svg"`) has to follow them; otherwise the platform does not find the
  resource, and the project, having caught the exception, draws an empty space. Only literals
  SHAPED like a path are translated - they end with a known resource suffix and every segment
  reads as a file name - so a regular expression with its slashes and named groups stays data.
- **Rule `conventions/missing-translation`** (info, off by default, project scope) - a name
  or a Cyrillic comment line the project's translation dictionary does not cover yet, one
  finding at its first occurrence in the file. Project-scoped because whether a word is the
  PROJECT's own is a project-wide fact: a word the platform tables also know is a gap when the
  project declares it, and a per-file check would stay silent exactly where the translated
  tree falls apart. Silent unless a dictionary is discovered, so only a project that
  translates its sources ever sees it.

## 2026-08-19 – 0.69.1, 0.69.2, 0.69.3

### Changed
- **The examples in the rule descriptions and the test fixtures now use the demo-project
  vocabulary.** No effect on the engine.

### Fixed
- **`yaml/dynlist-column-sort-lost` leaves alone a column that switches sorting off.** The rule
  did not read the `DisableSorting: True` property at all, so a computed status-badge column came
  out as a finding - although such a column has no header sorting by declaration and loses
  nothing.

## 2026-08-17 – 0.69.0

### Added
- **Rule `yaml/localization-key-unique`** (error, in the default set) - a key a localized-strings
  dictionary declares twice. The compiler settled the reach on a throwaway project of three
  dictionaries: the two sections share ONE namespace and a translation file is judged too, all
  three refusals answered "name is not unique". The refusal happens at apply time, so the whole
  project rolls back - one repeated key costs a full deploy cycle, and a dictionary of several
  hundred entries does not give the duplicate away by eye. A yaml loader keeps the LAST of the
  repeated keys, which is why no reader saw it before the apply; the check reads the composed
  nodes instead.
- **Rule `code/module-var-not-const`** (error, in the default set) - a `var` / `val` / `use`
  declaration at MODULE level, where only a constant may stand. A constant is initialized by an
  expression computed at compile time, while the other modifiers need a running method to
  evaluate their initializer in. The parser accepts all four there (the grammar rule is shared
  with an object field), which is why nothing caught this before the deploy.
- **Rule `code/use-needs-closeable`** (error, in the default set) - the `use` modifier over a
  type the catalog describes and that does not inherit `Closeable`. The modifier exists for the
  automatic `Close()` on leaving the scope, so the compiler refuses the declaration. A type the
  inference cannot reach, and one the catalog does not carry, are left alone.
- **The component tree can be asked for in parts** - `meta_component_tree` and the CLI
  `form-tree` take a subtree (by node id or by the component's name), a depth limit and a switch
  that drops the property records. A real form reached a quarter of a million characters, so
  reading one group meant paging through the lot; the same form answers an overview call in
  seven hundred characters. A node whose children were left out says so, and a component without
  its properties reports how many it has.

## 2026-08-16 – 0.68.0, 0.68.1, 0.68.2

### Added
- **Rule `yaml/missing-subsystem-usage`** (warning, in the default set) - a subsystem imports
  another one without declaring it as used in its own description. Such a project does not
  apply, and until now that only came out at deploy time.
- **Rule `code/missing-import`** (warning, in the default set) - a module uses a type or a module
  of another subsystem without importing it. Compilation fails at that line while the linter
  stayed silent: the check existed for yaml only.

### Changed
- **A line of nothing but whitespace is an info.** The indent of a blank line changes nothing
  for the compiler and nothing for the reader, and the platform states no rule about it. A tail
  after code stays a warning: there the line does have content.
- **Completion answers after the data object of a form.** The name `Object` is declared by the
  argument of the form's base type; it is typed now, and with it the loops over tabular sections.
- **Completion answers after a value of an enumeration and after a variable of that type.** A
  value is a member of its enumeration, and the members of a value are the methods of the module
  beside it.
- **A loop over a literal list types its variable.** `for Option in [Role.Admin, Role.Plain]`
  takes the type from the items themselves; items of different types leave the variable alone.
- **Completion answers after a caught exception and after the commands of a form.** The type of
  an exception stands in the clause itself, and commands such as `Write` come to a form from the
  type it inherits; the dot after such names used to stay silent.
- **Completion answers after the parameter of a lambda.** `List.Convert(E -> E.` offers the
  members of the collection's element, and a lambda over a query result offers the columns.
- **A tabular section in a query answers with its fields.** `FROM Goods.Lines AS L` reads the
  section as a table of its own, so `L.` offers its attributes and the standard row fields.
- **The dot after a form component answers** - with the methods of its own module and with the
  members of its type; a chain through a component reaches the end.
- **In an English project completion names platform members in English.** The list after a dot
  used to be Russian whatever the language of the project.
- **Expression type inference answers more often.** It learnt the query, pattern and resource
  literals, and a loop variable takes the element type of its collection.

### Fixed
- **A method accepted from completion inserts its parentheses.** The list of methods is built
  in two places and only one of them put them in - elsewhere a bare name was inserted.
- **A type was offered twice.** The member list of an object named its local types and tabular
  sections both by a generic "type" line and by an exact one; one exact line is left.
- **After `new Name.` only types are offered.** The methods of a module and the members of a
  manager cannot stand in a constructor and only pushed the types out of sight.
- **In 0.68.0 the dot after a form component stayed silent** whenever the component has no
  module of its own and its type is written with an argument - and most of them are.
- **The index lost the nullable marker of a method's return type,** so every value coming out of
  the project looked non-empty.
- **A method environment did not tell its blocks apart:** a name declared in one loop answered in
  another. Visibility now follows the platform rule - from the declaration to the end of a block.
- **The attributes of a module's own type were missing from the environment,** and an attribute
  named like a stdlib type was read as that type.
- **The `??` operator named the type by its right-hand side,** though the value may be the left
  one. Disagreeing sides now answer "unknown".
- **The term extractor lost the names spelled in two alphabets** (`FtpSource`, `SeoDescription`):
  they ended up without an English pair though the distribution has one. A few false pairs left
  the dictionary at the same time.

## 2026-08-15 – 0.66.0, 0.66.1, 0.67.0

### Added
- **Expression type inference (`xbsl.typeinfer`)** - the type of a receiver, a member, a
  constructor, a cast and a non-null operator, from the platform data. Where the data cannot
  name a type the module answers "unknown" rather than a guess.
- **Rule `yaml/ref-input-auto-commands`** (info, off) - a reference input with no `Commands` of
  its own: the platform draws a button that opens the value in a separate window next to it. That
  is usually what the author wants, so the rule answers "where did this button come from" rather
  than reports a mistake.
- **Request `xbsl/localizationStrings`:** the engine answers with every localized string of the
  project in the chosen language. A key with no translation keeps its default text - the same
  fallback the platform makes.

### Changed
- **Completion answers where it used to stay silent.** A quarter of the dots in a live project
  got no answer; the sweep is down by a third. The type of a variable now comes from a literal
  (`val Key = ""` is a `String`) and from a call with no qualifier - a method of the module
  itself, which is how a module calls its own code. A chain is no longer cut by a non-null
  operator, a loop variable takes its element out of the written type of the collection, and a
  declaration inside a loop leans on the loop variable. A value of an interface component
  answers with its own properties, the methods of its module and the members of the platform
  type it inherits. Inside `new Type(` the names of what the type carries are offered, with the
  `Name = ` written for you. A query held by a `use` declaration carries its columns to the loop.
- **A facet namespace answers after the dot.** A facet is named by two segments
  (`Entity.Privilege`), and the catalogue keys it that way - the first segment alone was not a
  type, so neither the completion nor the chain had anything to say. Now the namespace offers
  the facets that may follow, and the chain resolves the two-segment root.
- **The types an object generates carry its data.** `Goods.Object` answers with the attributes
  and the tabular sections of its yaml, a tabular section is a type of its own with its own
  attributes, and `Goods.Reference` answers what the kind gives a reference. The catalogue
  describes these by KIND, and the object's own data is joined with that.
- **A member of the type a module extends is addressed by a bare name.** In a module of
  `Goods.Object` a bare `Lines` is its tabular section, not an unknown name: the completion after
  it answers, and a loop over it takes the row type. The object type now carries the declared
  type of every member it holds.
- **A single-row query answers by column off the result.** The code reads such a query straight
  off the variable, without a loop; only the loop variable used to carry the columns.
- **A generic member resolves by the arguments the code wrote.** `Array<Catalog.Card>.First()`
  answers `Catalog.Card`, `Map<String, Number>.Get(...)` answers `Number`: the catalogue names
  such a result by the type PARAMETER, and the parameter lists of the types are now extracted
  alongside it.

### Fixed
- **A generic METHOD lost its signature and its result.** The parameters are printed between
  the name and the parenthesis (`ReadObject<ObjectType>(...)`), and the parser demanded the name
  followed by the parenthesis - so the method kept neither. A deprecated overload made it worse:
  its own result disagreed with the current one and the member was dropped altogether. Both are
  read now, the current form outranks the compatibility one, and the type parameters of a method
  are extracted - `JsonSerialization.ReadObject(Text, Type<Package>)` answers `Package`.
- **A collection knew the type of nothing it returns.** The base types of a generic are printed
  with their argument (`Collection<ItemType>`), and the extractor read the whole spelling as a
  name - so `Array` kept `Object` as its only ancestor and inherited no result types at all:
  779 types carried none. Both halves are fixed - the extractor reads the head, and the loader
  builds the inherited result types for a type that declares none of its own.
- **A project written in English is indexed** - the name of an element and its named sections
  were read in the Russian spelling alone, so an English project indexed to nothing at all: no
  tree, no navigation, no completion. The type an element generates is registered under both of
  its names, and the dot answers whichever the code writes.
- **The dot after an element offers what the element carries** - the parameters of a client work
  parameters element were absent from the completion, which listed the methods of the kind alone.
- **A loop over a parameter types its variable** - where the collection is a parameter typed
  `Array<...>`, the variable of the loop stayed untyped and the dot after it offered nothing.
- **A typo in a path no longer passes for a clean check.** A path that is not there is an error
  with a plain message instead of "0 files checked, 0 findings" and the exit code of success; a
  path that exists but holds no sources now gets a warning.

## 2026-08-14 – 0.64.0, 0.65.0

### Added
- **`style/shadow-own-property`** - a local variable named like a property of its own element:
  the assignment goes into the variable and the property stays as it was.
- **`code/unused-import`** - an import of a subsystem the code never turns to.
- **Eight rules for platform behaviour the compiler accepts and the screen then contradicts**
  (142 → 150):
  - `code/permission-handlers-need-recalc` – a permission handler is declared while nothing
    recomputes: an edit of the algorithm silently does not act on existing data.
  - `yaml/dynlist-row-editing` – a row-editing handler on a flat list: the platform never calls
    that event, and a click opens the automatic form instead.
  - `yaml/localization-ref-to-template` – a `$Dictionary.Key` reference pointing at a key of the
    templates section: the apply fails with a localized-string-not-found answer.
  - `yaml/insert-row-needs-align` – a horizontal group holding an insert with no explicit
    alignment: the element with the insert slides down against its neighbours.
  - `code/url-params-partial-encoding` (info, off) – the Url method encodes a parameter value
    only partially, and the address arrives cut.
  - `yaml/dynlist-column-sort-lost` (info, off) – a column whose value calls something: clicking
    the header sorts by something else.
  - `yaml/matrix-group-max-width` (info, off) – a numeric width maximum on a matrix group: a
    phone draws the page at desktop width.
  - `yaml/card-literal-stretch-weight` (info, off) – a stretch weight on a card: in a vertical
    column it collapses on Safari.

### Changed
- **A collection literal names the type.** `val Users = <String>[]` declares it no worse than a
  constructor, and a member an array does not have is now visible after such a literal.
- **The query files of virtual tables (`.xbql`) came under the checks.** An unknown table there
  used to be found by the server compiler alone.

### Fixed
- **The English spellings of annotations.** `@OnServer` and its siblings read as no annotation
  at all, so the method was checked by the default. Both forms are equal now - in annotations,
  in visibility scopes and in the form event keys.
- **Two holes in parsing.** A parenthesis starting a line no longer sticks to the preceding
  expression, and a declaration like `var Attempt: (()->Boolean)? = Undefined` parses: it used
  to bring the whole file down.
- **The events of a type.** Binding a handler to a component built in code no longer looks like
  a member that does not exist; a typo in an event name is still caught.
- **An id is unique within its owner.** The platform accepts the same identifier on attributes
  of DIFFERENT objects - its own demo project is written that way; object ids are compared across
  the project, item ids inside their own file. The rule also reads the English `Id` key now.
- **Three rules stopped arguing with lawful code:** the key of a dynamic list row, a required
  field and an event parameter of a reference type, a standard attribute added without an id.
- **The README links open again:** splitting the guide left thirteen broken ones per language.
  A test keeps them honest now.
- **The metamodel reset now clears the `key_aliases` cache as well** – after pinning another
  data root the editor's metadata tree could show the pairs of the previous one.
- **The language guard judges untracked files too** – a brand-new module with bare Cyrillic
  slipped past the local run and surfaced in CI.

## 2026-08-13 – 0.63.0

### Added
- **Rule `yaml/binding-needs-auto`: a binding with a nullable return on a property that has no
  empty value.** The client writes "unexpected value" into the server log on every
  recomputation - invisible in the browser; a live project had accumulated almost two thousand
  records.
- **Rule `yaml/date-input-needs-plain-date`: a nullable date input.** The apply passes cleanly,
  yet the field is not drawn and the group left empty disappears entirely. The cure is a plain
  type: "not set" is expressed by the empty date.

### Fixed
- **`yaml/ref-needs-nullable` judges unions too.** A union with a reference and no empty value
  fails to apply - a mixed one such as `String|Goods.Ref` included; the fix is to add `|?`.

## 2026-08-11 – 0.62.0

### Added
- **Rule `code/component-in-server-context`: an interface component in a server environment.**
  The component's type lives on the client, so the server compilation answers "Variable X is not
  defined" and the stand silently rolls back to the previous build.
- **The check gained `--out`: the report is written to a UTF-8 file without BOM.** On Windows
  the shell redirection prefixes the output with a BOM that breaks JSON parsing.

### Fixed
- **An event-log event property gets its `Id`.** Adding a field now reconciles the identifier
  with the metamodel both ways: where it is needed it is written, where it is superfluous it is
  dropped.

## 2026-08-09 – 0.58.0, 0.59.0, 0.59.1, 0.60.0, 0.61.0

### Added
- **A `.xbql` query file became a language.** Highlighting and completion: the grammar is built
  from the platform's own vocabulary, the whole file counts as the query, and a table alias is
  followed by its fields. The same vocabulary highlights a `Query{...}` block inside a module.
- **The variable of a `for X in Collection` loop gets its type** from the element type of the
  collection. For that a structure now carries the type of every field in the index; a collection
  with two type parameters names no element, and there completion stays silent.
- **The members of the kinds' singleton types reached the data: from 12 kinds of 41 to 31.**
- **A call of a kind's method is typed.** The result type comes from the signatures in the
  documentation (25 kinds of 31), so completion knows what `Get()` of a constants set,
  `FindByCode()` and `GetReference()` of a catalog answered with.
- **A kind manager's properties and methods are told apart** – completion inserts the parentheses
  of a method and withholds them from a property.
- **`code/unknown-structure-field`: a field of a project structure is checked against its
  declaration** (139 rules now).
- **Stale baseline entries can be seen and pruned:** `--stale-baseline` lists the entries that no
  longer suppress anything, `--prune-baseline` removes them and leaves the live ones alone.
- **The linter finds the project's baseline by itself** – it looks for `.xbsllint-baseline` upwards
  from the checked files and names the path it found; `--no-baseline` switches the search off.
- **Tool answers name the data they speak for.** `--version`, the MCP `version_info` and the LSP
  startup line carry the data root and where it came from.
- **`conventions/untranslated-code-literal` – text visible to the user left as a literal in a
  module** (off by default).

### Changed
- **The dot completion offers what the catalogue knows about the kind** - instead of a generic
  list that surfaced names which do not exist.
- **`code/unused-method` judges the public API of common modules.** Only annotations naming a
  caller outside the project silence a method; visibility and environment annotations no longer do.
- **The dictionary of element kinds is derived from the distribution:** 41 kinds instead of 35, and
  the data journal, the report panel and the integration process stopped looking unknown.
- **`yaml/unknown-property` judges 18 kinds instead of 13.**
- **The resource rules know both spellings of the folder** – the platform accepts `Resources` next
  to the Russian name.
- **Processing scaffolding:** an attribute is written without an `Id` (it has no such property), a
  PAIR of modules is created, and the operation handler goes into the object module.
- **English messages speak English** – platform names and keywords in rule messages and in the CLI
  help are substituted in the reader's language.
- **The name whitelists were cleared by the compiler:** 12 of 25 claims turned out to be false, and
  the entity name table shrank from 15 entries to 4 confirmed ones.

### Fixed
- **Types described in metadata offered nothing after the dot** - the indexer skipped the fields
  of a structure and the constants of a set.
- **`code/unknown-structure-field` crashed in the released wheel** (0.59.0): the tree walk read the
  fields of a node in a way the native build does not support. A test now keeps that walk out.
- **The baseline summary line counts entries,** not suppressions - one entry may hold several. The
  former number stays in the json.
- **Completion at the start of a session knew no project objects** - it waited for the background
  pass. A request that arrives earlier now builds the index itself.

## 2026-08-08 – 0.57.2

### Fixed
- **LSP navigation no longer waits for the whole-project lint.** The index is built first, and a
  request that arrives earlier builds it itself. On a mid-sized project navigation comes alive in
  1.9 s instead of 7.2 s.

## 2026-08-07 – 0.54.0, 0.54.1, 0.55.0, 0.56.0, 0.57.0, 0.57.1

### Added
- **The properties of section items are written by the tool** (0.57.0). `meta_add_field` takes
  `props`, its sibling `meta_set_field_property` edits an existing one; names are checked against
  the item's class, and a value is quoted only where it must be. The same in the CLI (`--prop`,
  `set-field-property`) and in the LSP.
- **A presentation when creating an object** (0.57.0): `meta_new_object` takes `presentation`. For
  a report and for commands it is a caption, for a catalog, a document, an exchange plan and a
  settings storage it is the NAME of a string attribute; a caption there is rejected with an
  explanation.
- **Localization of a strings element** (0.57.0): `meta_add_localization` creates the translation
  file with the default language's values, `meta_localization_info` answers which languages are
  declared and which translations already exist.
- **A processing form** (0.57.0): `meta_add_form` generates `ProcessingForm` - fields from the
  attributes and operation commands through the `Commands` type, so new operations reach the form
  by themselves.
- **The metadata schema answers to a descriptor class name too** (0.57.0): you may ask with the
  very name the schema itself reports.
- **The metadata schema names the attribute TYPE a property applies to** (0.56.0). Per-type
  properties carry `applies` - `string`, `number` or `reference` - exactly as the documentation of
  the kind records it.
- **English names of the service files are resolved everywhere** (0.55.0). The platform accepts
  `Project.yaml` and `Subsystem.yaml`; a project with those names used to be invisible.
- **`meta_delete_object` / `xbsl delete-object`: deleting an object whole** - the yaml with its
  module, the object forms and the list row component. Every remaining mention of the name is
  reported with its file and line but left alone; before `--apply` the command answers with a plan.
- **`conventions/untranslated-visible-literal`** - visible text left as a Cyrillic literal where
  the project has already moved the same property into a localization dictionary. Only the keys the
  project localizes somewhere are judged.
- **Registering a rule id again replaces the earlier rule** instead of doubling its findings: a
  rule moving between a plugin and the engine lives in both for a while.
- **`xbsl extract --keep-previous` keeps a snapshot of the previous build's data,** so
  `xbsl data-diff` works right after a regeneration.
- **The environment names itself:** `--version` lists the installed plugins with versions, the MCP
  `version_info` returns the same as data, and the LSP writes it into the startup log.

### Fixed
- **A form module of an English project no longer drowns in false errors** (0.57.1). The base type
  of a component was looked up by the Russian key, so in an English project every access to a
  member of the base type was declared an unknown name. Members of the base type are now accepted
  in both spellings.
- **The rule stopped being silent about form commands that do not exist** (0.57.1). A built-in form
  command is a PROPERTY, and running it is `WriteAndClose.Execute()`.
- **`yaml/presentation-field` no longer judges a constants set** (0.57.0): it has no attributes
  section, so the rule demanded the impossible. For a catalog a caption in that property is still
  an error.
- **Inserting into a section no longer breaks a CRLF file** (0.57.0) - a lone carriage return used
  to be left behind, and git then normalized the line endings of the whole file.
- **English help writes the English spellings of names** (0.57.0) where the platform declares them.
- **Objects of an English project no longer fall out of the by-kind views**
  ([issue #1](https://github.com/keyfire/xbsl/issues/1)). The kind is resolved through the
  serializer's own kind table; every former spelling is still accepted.
- **The extractors' default data folder pointed inside the package twice** - a run without
  `--data-dir` silently wrote to the wrong place.
- **The toolkit's own JSON files tolerate a BOM,** and a parse error names the file.
- **`self-update` picks a wheel by platform, not by the kind of installation** - one portable
  update used to make the installation portable forever.

## 2026-08-03 – 0.53.0

### Added
- **Dictionary keys are indexed as the members they are.** A `LocalizedStrings` element has no
  module, so go-to-definition, references and completion knew nothing of `Dictionary.Key()`; the
  string itself now becomes the description in the hint.
- **The documentation extractor reads the events section.** The catalogue used to claim a button
  has no `OnClick`, and a version comparison reported imaginary removals. Regenerate the data for
  this to take effect.
- **A method stub for a handler that is not a form event** - built from a neighbouring handler of
  the same key; with no neighbour the stub takes no parameters and says so.
- **A route is added without assembling its text:** `xbsl/metaAddRoute` takes the template together
  with the methods, and `xbsl/httpMethods` answers with the methods a route may declare.

### Changed
- **The language guard judges citations too:** a Russian name in a comment is a finding even in
  backticks when the compiler's dictionary knows the English spelling.

## 2026-07-31 – 0.49.0, 0.50.0, 0.51.0, 0.52.0

### Added
- **The card of a platform method shows its parameters.** Signatures are extracted from the
  documentation, and an inherited method takes the signature of the type that declares it.
  Regenerate the data for this to take effect.
- **Completion answers for the platform and for the global catalogue,** not for the project alone:
  a member of a platform type had no card at all, and global names never reached it.
- **The card of a project method carries its signature and description,** and its return value gets
  a type: after `val P = Module.Method(...)` the dot offers the members of what was returned.
- **`code/unclosed-resource`** (136 rules now): an early `return` or `break` in the middle of
  iterating a query result leaves it open. The cure is the `use` modifier.

### Changed
- **The language of the sources is guarded, not remembered:** `tools/langguard.py` reads the ADDED
  lines and reports Cyrillic in comments, docstrings and Python names; CI runs it on every push.
- **Both English changelogs are guarded** - by a dictionary rule and by a dictionary-free one, so a
  public clone without the term dictionary is covered too.
- **The MCP server runs on both majors of `mcp`, the pin is gone** (`mcp>=1.2,<3`): the import
  tries the new location of the class first, then the old one.

### Fixed
- **`self-update` right after a release no longer says there is no wheel:** the file list comes
  from the simple index instead of the lagging JSON metadata.
- **A member's documentation link no longer leads to a random article** - the page is resolved
  through the receiver rather than by a bare name search.

## 2026-07-29 – 0.48.0

### Added
- **The "Names of variables and constants" standard became rules** (135 rules now). Six new
  `style/` rules: an abstract name, a single-letter name, a negated boolean name, a type in a
  variable name, a numeral in a constant name and a variable named after a project element. All six
  are `warning`.

### Changed
- **`style/abbreviation-case` reads Cyrillic abbreviations too:** a run of capitals in a declared
  name is a finding with a hint, just as a Latin one is.

### Fixed
- **`self-update` of a native installation updates itself.** The command used to offer to stop its
  own process tree, and the shared mypyc libraries in the root of `site-packages` were overwritten
  in place, which fails while the running update holds them. Ancestors and descendants of the
  command are now excluded from the holders, and such libraries are set aside by renaming.

## 2026-07-28 – 0.47.0, 0.47.1, 0.47.2

### Added
- **`code/unknown-tabular-member` - a member called on the rows of a tabular section must exist on
  the array type.** The receiver is typed by the PROJECT's metadata, so the earlier member rules did
  not see this shape: `Object.Steps.Count()` passed the lint and broke the apply (an array has
  `Size`).
- **`code/global-unavailable` - a global name called outside its environment.** `Message` exists on
  the client only, `Eval` and `Execute` on the server only; a method's environment comes from the
  element kind until `@AtServer` or `@AtClient` fixes the side.
- **`code/collection-field-needs-req` - a structure field of a generic type that cannot be built
  empty.** `ReadOnlyArray<String>` is rejected by the apply while `Array<String>` is the opposite
  case; which is which is now a fact in the type catalogue.
- **`code/var-needs-init` - a variable declared with a type that has neither a constructor nor a
  default value.** The cure is either `Type?` with a check or reading what is needed inside the try.

### Changed
- **The texts of the two new rules speak the demo project's vocabulary** (`Tasks`/`Steps`), like
  the rest of the documentation.

### Fixed
- **The `mcp` extra is pinned below 2.** The `mcp 2.0.0` released the same day removed the module
  the MCP server imports, and a fresh installation would not start.

## 2026-07-27 – 0.41.0, 0.42.0, 0.42.1, 0.43.0, 0.44.0, 0.45.0, 0.46.0

### Added
- **`code/bound-property-assign` - a property COMPUTED by an expression is not assigned from code.**
  The platform rejects such an assignment, and inside the usual `try/catch` the refusal is invisible.
  A data binding is left alone: what is judged is the shape of the expression.
- **`style/redundant-type` sees a typed empty literal:** `var Codes: Array<Number> = <Number>[]`
  names the type twice. Only an array is recognized.
- **`xbsl/metaKeys` - the key pairs of an element for surfaces outside python.** The editor's
  metadata tree parses the yaml itself, and for an English object its branches were empty.

### Changed
- **What the platform describes as a code convention became a standard:** seven `style/` rules run
  by default and report at `warning` - line length, comparing a boolean with `True`/`False`,
  UpperCamelCase, collection literals, string interpolation, a redundant `.ToString()` and the case
  of abbreviations. Accumulated debt belongs in the baseline.
- **A disabled rule says WHY right in `--list-rules`;** the machine-readable list carries the reason
  in `off_reason`.
- **The type catalogue keeps the whole union** (`Auto|Boolean` instead of `Auto`), so the data tells
  a boolean from a value that MAY be boolean.
- **Every text of `self-update` moved into the message catalogue** - `--lang en` answers in English.

### Fixed
- **What the scaffolding WRITES is now in the project's language.** A form created in an English
  project used to arrive with Russian keys and Russian type names; keys and names come from the
  platform's own data, and the author's names are left alone.
- **The tool speaks up about what the data cannot name** - the English values of interface
  enumerations are absent from the distribution, and the report names such values instead of
  inventing them.
- **`style/boolean-compare` no longer fires where the comparison is required.** The short form does
  not compile as soon as the value is nullable or compound, so the operand is typed and only an
  exactly `Boolean` type is a violation.
- **The scaffolding reads a project written with English keys.** Some operations used to answer
  "object not found", and three answered with success and a wrong result.
- **A parallel run of the released wheel no longer breaks off.** A worker's result carried the
  file cache, which the native build cannot unpickle; the cache no longer crosses the process
  boundary, and the result shrank from 1.96 MB to 0.58 MB.
- **Renaming an object by case alone is no longer rejected** - on a case-insensitive file system it
  goes through a temporary name, and a failure rolls back.
- **A rename by case warns about version control:** git on such a file system shows a Cyrillic
  rename as a delete plus an add.
- **The project localization rule no longer ships whole sources between processes** - only the
  calls standing next to a comparison travel in the fact.

## 2026-07-26 – 0.36.1, 0.37.0, 0.37.1, 0.37.2, 0.37.3, 0.38.0, 0.39.0, 0.40.0

### Added
- **Four rules: per-object permissions and localization** (122 rules now).
  `code/per-object-permissions-need-common` - the common permissions handler is required even with
  per-object; `code/permission-field-not-declared` - a field outside the declared computation list;
  `yaml/placeholder-key-in-strings` - a placeholder in the `Strings` section, which compiles into a
  method without parameters; `code/compare-with-localized` - a comparison with a localized value
  that silently fails in another language.
- **`yaml/delete-current-needs-immediate`** (118 rules now): `DeleteCurrent` on an owner that only
  marks a record breaks the apply of the whole project.
- **Two rules about the execution environment** (117 rules now):
  `code/client-available-needs-context` - `@AvailableFromClient` on a method of an interface
  component that is neither `static` nor `@Contextual`; `code/server-module-in-client-context` - a
  call to a server-side common module from a client method. Both refusals are visible only to the
  server compilation.
- **Five rules about what the platform ACCEPTS but does not do** (115 rules now): an empty group
  with a size, an over-long hint, `Close()` inside its own `BeforeClose`, a query function that does
  not exist and project folders that diverged from the descriptor.

### Changed
- **A guard for the English documents:** Russian spellings of platform names in English texts are
  now rejected by a test rather than by an eye. It knows three legitimate cases - a file name, a
  single letter as the subject of the sentence and a link to the Russian twin.
- **The texts speak of facts, not of how the facts were obtained** (0.37.1-0.37.3). What the
  compiler accepts and what a rule guards against stayed; the rest is gone. Rule behaviour did not
  change.

### Fixed
- **The sync guard looked at four places of eight,** so the rule counts on the site pages drifted
  apart unnoticed. All eight are checked now.
- **The tree walk skipped everything inside a condition** - the branches of an `if` are stored in
  pairs, and the walk descended into lists of nodes only.
- **The 0.36.0 wheel checked nothing:** a tree walk in one rule relied on something the native
  build does not have. A mine in the tests now catches such a walk.
- **A crash in one rule no longer brings the run down** - it became a finding of its own under that
  rule's id, and the other rules do their work.

## 2026-07-25 – 0.35.0, 0.36.0

### Added
- **Two rules about a static method** (`code/this-in-static-method`,
  `code/instance-call-from-static`): it has no object context, so `this` in its body and a bare call
  of an ordinary method of the same owner are rejected by the compiler.
- **`code/local-method-cross-module`** (101 rules now): `Module.Method(...)` must call a method
  carrying a visibility annotation - without one the method is visible in its own module only.

### Changed
- **`code/unknown-static-member` types a value that came from ANOTHER module:** every module
  publishes the return types of its methods, and the project phase binds `Module.Method(...)` to
  them.
- **The scaffolding writes a slot by its cardinality:** the first child of an array slot becomes a
  list item rather than a single nested mapping, which the apply would reject.

### Fixed
- **A project written with English metadata spellings is judged like a Russian one.** The rules used
  to look for the Russian kind key, not find it and skip the file whole - not even a typo was caught
  in it. On Russian sources the findings are unchanged.
- **Forms too: an English component is parsed and judged.** The form model reads its keys through
  the compiler's meta-object dictionary, so the designer, the structure panel and the edit
  operations see one tree regardless of the file's language.
- **The demo project got an English twin (`demo-en/`), and it is a guard:** a test requires both
  twins to produce the same findings on the same lines.
- **The scaffolding writes in the project's language** - the language is decided by the majority of
  the files, never by a setting.
- **The public CI had been red since the previous release,** and a simulated clone without data
  found it: three bilingual tests expected spellings such a clone does not have.
- **An MCP tool called with a misspelled argument name now fails** instead of quietly running with
  the defaults.

## 2026-07-24 – 0.32.0, 0.33.0, 0.34.0

### Added
- **`yaml/unexpected-type-argument`** (100 rules now): a type argument on a property the ui schema
  declares WITHOUT one is a different type, and the apply rejects it.
- **The ui schema carries a `type_params` section** - the type parameters of generics and their
  defaults; without it the rule above produced false positives.
- **`ui_schema` answers for names outside the palette too** - commands, command interface fragments
  and groups, a value list item.
- **`xbsl extract` - generating the dataset from the CLI.** The extractors moved into the package,
  so an installed package generates the data without a clone of the repository.
- **`xbsl data-diff [old] [new]` - what changed in the platform between two data versions.** Members
  are compared with inheritance expanded; `--format text|md|json`.
- **The version index moves the default forward only:** regenerating an older version does not
  disturb it.
- **`code/invalid-string-escape`** - an invalid escape sequence in a string literal is caught before
  the server compilation.
- **MCP `ui_schema`: the `brief` and `property` parameters** - a line per property instead of a full
  component schema, and the full record of a single property.
- **The metadata schema expands a closed type restriction into the list of allowed values.**

### Fixed
- **`code/unknown-member` judges generic variables by the head of the type:** the members of
  `ReadOnlyArray<Task>` are those of `ReadOnlyArray`, while a parameterized type used to be
  skipped whole.
- **The documentation search no longer answers a multi-word query with nothing** - when no page
  carries every word, it relaxes to "any of the words".
- **`xbsl extract --help` names the command, not the path of the interpreter.**
- **The stdlib extractor recognizes the interface components of new distributions again** - the link
  target serves as the marker, not only the qualified name.
- **A variable named `Query` is no longer read as the keyword of a query literal** - without a `{`
  it is an ordinary name.
- **A single-file check no longer loses the shadow of the paired yaml,** so a form attribute is not
  judged as a stdlib type of the same name.
- **The hover documents neither a declared variable with no inferred type nor a name declared by the
  paired yaml as a stdlib type.**

## 2026-07-23 – 0.31.0, 0.31.1

### Changed
- **The generated stdlib type catalogue records fuller member types** and gathers additional
  surfaces from the platform's topic pages, so the member checks and completion match what the
  platform really provides (0.31.0).

### Fixed
- **`code/resource-bare-name` no longer treats an `inbase/...` reference as a path with a folder:** a
  resource loaded into the application database is a lookup key (0.31.0).
- **A resource key is a path relative to the subsystem's resources folder:** references to
  subfolders are legitimate (0.31.1).

## 2026-07-22 – 0.28.0, 0.29.0, 0.30.0, 0.30.1

### Added
- **A documentation site** ([docs.keyfire.ru/xbsl](https://docs.keyfire.ru/xbsl/)), a full command
  reference and help - entirely in Russian and English (0.29.0).
- **The metamodel resolves the schema of a collection item** - an enumeration value, an attribute, a
  dimension, a resource, a structure field - so the linter sees the full schema with its defaults
  (0.29.0).
- **An engine operation for removing a form handler** (`xbsl/removeHandler`): it unbinds the event
  and deletes its method in one change (0.28.0).

### Changed
- **Faster on large projects:** caches in the data layer, YAML parsing through libyaml and worker
  pools sized by the task (0.30.0).
- **A type hover carries its description from the documentation,** not a bare link (0.28.0).
- **Completion follows a chain of members past a reference property,** and a guard stops the walk at
  the boundary of the stdlib closure (0.30.1).

### Fixed
- **`yaml/bare-object-value` accepts a `$` reference to a localized string** where a literal is
  expected (0.30.1).
- **Regenerated data is picked up without a restart** (0.30.1).
- **The servers behind the optional extras are skipped gracefully on a minimal installation** rather
  than failing on import (0.30.1).

## 2026-07-21 – 0.25.0, 0.26.0, 0.26.1, 0.27.0

### Added
- **Four linter rules:** `yaml/bare-object-value` (a bare word where a quoted literal or an `=`
  binding is expected), `code/resource-bare-name` and `code/unknown-resource` (a resource given by a
  bare file name) and `yaml/no-expression-in-literal` (0.26.0).
- **Three engine rules:** `yaml/ref-needs-nullable`, `yaml/unknown-enum-value` and
  `yaml/standard-field-length` (0.25.0).
- **A single metamodel API** - property types, enumerations and defaults through one interface
  (0.27.0).

### Changed
- **The scaffolding accepts an element kind in either platform language** (0.26.0).
- **The language data comes from the compiler rather than from constants** (0.26.0).
- **`code/undefined-name` reads names inside string interpolation too** (0.25.0).
- **Completion follows the project's development language** (0.26.1).

---

> Releases before 0.25.0 predate this changelog. The VS Code extension's
> [CHANGELOG](https://github.com/keyfire/xbsl/blob/main/editors/vscode/CHANGELOG.md) carries the
> product history back to 0.1.0.
