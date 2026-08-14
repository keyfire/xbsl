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

## Unreleased

### Added
- **Rule `style/shadow-own-property`: a local variable named like a property of its own
  element.** Inside the method the name resolves to the variable, so an assignment meant for
  the property never reaches it. Reconnaissance cut the slice twice: only the modules where
  such a property IS in scope are judged (an interface component and an object module - a
  catalog's manager module carries no record at all, and 58 of the 60 name coincidences on a
  live project live exactly there), and a PARAMETER of that name is left alone, being the
  ordinary way to pass a value in. Three corpora: one true finding, no false ones.
- **Rule `code/unused-import`: a module imports a subsystem its code never mentions.** The
  platform's own editor reports such imports; the linter did not, and they accumulate as the
  code that needed them is rewritten. A reference from the PAIRED yaml is not a use - the
  yaml carries an import section of its own, which is exactly the shape of the live case that
  prompted the rule. The check errs towards silence: a local name matching an element of the
  imported subsystem reads as a use, so an import is never reported on a doubt.

### Fixed
- **Three rules learned their exception.** All three were surfaced by a foreign reference
  project, and each has evidence of its own. `code/unknown-row-field` did not know that a dynamic
  list row has members OF ITS OWN: the key is the documented way to reach the reference behind
  the row, while the rule knew the data member alone; the set now comes from the type catalog.
  `yaml/ref-needs-nullable` ignored the required mark - such a field becomes a mandatory parameter
  of the constructor even when it has an implicit initialization value (docs of the structure
  element), so it needs no default; the same rule also stopped judging PARAMETERS, whose value
  arrives from whoever raises the event. `yaml/item-id-required` demanded an id for a standard
  attribute added by naming it: the published ASSEMBLY of the reference project carries that entry
  with no id, so the build accepts it. The mark comes from the metamodel - a class dispatched by
  name describes a built-in item of the collection rather than one the project declares.
- **`code/unknown-member` sees the EVENTS of a type.** Binding a handler to a component built in
  code (`Button.OnClick = &Handle`) is the documented form, and the type's page in the same
  distribution carries a "События" section. The events were always extracted; the rule read
  properties and methods alone and answered "the type has no member" to every such binding -
  nine findings on the reference project, the only class of its false findings that could hit our
  own code as well. A typo in an event name is still flagged.
- **Parser: a newline ends the statement, parentheses group a type.** Two holes, both surfaced
  by a foreign reference project. First: an opening parenthesis at the start of a line was read
  as a call of the preceding expression, so a loop source swallowed the next statement - casting
  the loop variable to write into it broke the parse. Second: parentheses around a type -
  `var Attempt: (()->Boolean)? = Undefined` - did not parse, because a function type demands
  the arrow right after the closing parenthesis; one such field broke the whole file (33
  suppressed reports). Both forms are legal - the server compiles that project - and all 13
  `code/parse-error` findings on it are gone.
- **Annotation parsing understands the English spellings.** Element sources are bilingual and a
  project mixes the forms freely - even within one declaration: `@OnServer` above `@InSubsystem`.
  The judges, however, matched the Russian spellings alone, so an English annotation read as NO
  annotation and the method was judged by the default: a run over a foreign reference project
  answered 602 false `code/local-method-cross-module` findings and three `code/query-needs-server`
  ones - 81% of every error in that run. Visibility, environment, the handler mark, the subsystem
  and library scopes, the deprecation prefix and the form event keys in yaml are bilingual now
  (`Handler`, `OnClick` and the other English names come from the component schema, never from a
  guess). The forms are read lazily and cleared along with the platform data - such a set used to
  freeze at module import.
- **The README links point at something again.** Splitting the guide into five pages left thirteen
  links per language reading `[text]((url)` - visibly broken on the Marketplace, Open VSX and PyPI
  pages. A link check (the target exists, the anchor exists) is now part of the tests: it is
  structural and needs no network.

### Changed
- **`code/unknown-member` reads a collection literal as a type declaration.** A variable
  initialized with `<String>[]` names its type no worse than a constructor does, yet the type
  used to come from an annotation or a `new Type(...)` alone - a member an array does not have
  went unnoticed after a literal. Array, map and set literals are covered, bare ones included: the
  arguments do not matter, since the members of an array are the same whatever it holds.
  Corpus runs over four projects: zero false findings.
- **The linter collects the query files of virtual tables (`.xbql`).** They were the only
  place where the query language lives outside a `Query{ ... }` block, and nothing looked at
  them: an unknown table in such a file was found by the server compiler alone. Now the query
  rules judge them - reconnaissance on a live project confirmed both halves of the change:
  `query/unknown-table` reports a table that is not an object of the project, and the two
  rules that would have been false there are exempt. A query file is not a module (the module
  parser meets it with "a module import, method... is expected" on line 1), and the
  ampersand parameter is the documented syntax of a virtual table's query rather than the
  literal's mistake - the platform documentation states that such a query takes its
  parameters the way an arbitrary query does (topics/virtual-table).

## 2026-08-14 – 0.64.0

### Added
- **Eight rules for platform behaviour the compiler accepts and the screen then contradicts**
  (142 → 150). Each one was cut by reconnaissance over four real projects, and every slice is
  as narrow as the evidence allowed:
  - `code/permission-handlers-need-recalc` – a module declares a permission handler while the
    project recomputes that entity's permissions nowhere: the platform never calls the handler
    by itself, so an edit of the algorithm silently does not act on existing data. Kinds are
    taken from the data (a kind with no recompute method is not judged), and the documented
    loop form of the recomputation stands the rule down instead of producing false positives.
  - `yaml/dynlist-row-editing` – an `OnRowEdit` handler on a list over a FLAT dynamic source:
    the event is declared for the node rows of a hierarchy, and on a flat list the platform
    never calls it, so a click opens the automatic form instead.
  - `yaml/localization-ref-to-template` – a `$Dictionary.Key` reference pointing at a key of
    the templates section: a reference resolves against the strings section alone, and the
    apply fails with a localized-string-not-found answer. A template key nobody references is
    left alone – code calls it legitimately.
  - `yaml/insert-row-needs-align` – a horizontal group holding an insert and no explicit
    vertical alignment: children are laid out on the baseline, and the element holding the
    insert slides down against its neighbours. The nearest horizontal ancestor answers.
  - `code/url-params-partial-encoding` (info, off) – the Url method that encodes a parameter
    value only partially: separators inside the value survive, and an address arrives cut.
  - `yaml/dynlist-column-sort-lost` (info, off) – a column of a table over a dynamic list
    whose value CALLS something: the header does not sort, the platform sorts by the field.
  - `yaml/matrix-group-max-width` (info, off) – a numeric width maximum on a group that lays
    out as a matrix: the maximum is also the AVAILABLE width, so a phone draws the page at
    desktop width and the content runs off the right edge.
  - `yaml/card-literal-stretch-weight` (info, off) – a literal stretch weight on a card or on
    a group inside one: the weight is a flex with a zero basis, which in a vertical column
    applies to the height and collapses the card on Safari while Chrome shows nothing.

### Fixed
- **The metamodel reset now clears the `key_aliases` cache as well.** Pinning another data
  root left that one answering from the previous root – the surfaces outside python (the
  editor's metadata tree) could get the pairs of a version they were not looking at.
- **The language guard judges untracked files under every base.** `git diff` is blind to a
  file until it is added, so a run against a branch answered "clean" over a brand-new module
  whose bare Cyrillic CI then found; untracked sources now enter the scan whole.

## 2026-08-13 – 0.63.0

### Added
- **Rule `yaml/binding-needs-auto`: a nullable binding on a property with no empty value.**
  "Not set" for a component property is the `Auto` value: the palette declares properties as
  unions without the empty value, and a binding whose method is declared `(): Color?` makes
  the client register "Неожиданное значение" on every recomputation - the records go to the
  server log, invisible in the browser console (a live project had accumulated 1866 before
  anyone noticed). Judged is the narrow slice with both sides known exactly: a bare local
  call bound to a typed palette property whose union carries `Auto` and no nullable flag,
  against the paired module's declared return types. A `?` inside a generic argument is not
  a nullable return - caught by the corpus run.
- **Rule `yaml/date-input-needs-plain-date`: a nullable date input is silently not rendered.**
  `Edit<Date?>` deploys cleanly, but the platform draws neither the field nor an
  apply-time error, and a group left without content disappears entirely - on a live project
  two such fields read as "the change did not apply". The cure is a plain type: the attribute
  `Type: Date`, the field `Edit<Date>`, "not set" expressed by the empty date. Only
  `Date` is judged - the `DateTime`/`Time` siblings are left alone until verified on a live
  stand.

### Fixed
- **`yaml/ref-needs-nullable` judges unions.** A compiler probe showed that a union carrying
  a reference member and no nullable member fails to apply - and a MIXED union
  (`String|Goods.Ref`) fails the same way, both in the attribute position and inside
  `Edit<...>`. The rule used to skip unions altogether; now it flags both shapes and
  suggests `|?`. A union with a nullable member (a trailing `?` on a member counts) or with
  a member outside the plain-chain shape stays silent. Corpus runs: zero false findings.

## 2026-08-11 – 0.62.0

### Added
- **Rule `code/component-in-server-context`: an interface component in a server environment.**
  A `Component.Member(...)` access from code compiled for the server – a `@OnServer` method
  anywhere, or an unannotated method of a server or client-and-server module. The component's
  type lives on the client, and the server compilation answers "Variable X is not defined" –
  the linter said nothing while the stand silently rolled back to the previous build. A
  namesake of the component among elements of other kinds and shadowed names are not judged;
  verified against the live case (the finding's position matches the compiler's) and by corpus
  runs with zero false positives.
- **The check gained `--out`: the report is written to a UTF-8 file without BOM.** Comparing
  findings before and after a change is an everyday scenario, and on Windows the shell
  redirection prefixes the output with a BOM that breaks JSON parsing. Works with every
  `--format` value (and together with `--fix`); the text-format summary stays on stderr.

### Fixed
- **An event-log event property gets its `Id`.** Adding a field now reconciles the `Id` line
  with the item's metamodel class BOTH ways: a class that declares `Id` gets one written
  (without it applying the build rejects the object, "ID required"), a class without it has
  the line dropped, as before. The judge is the same source the `yaml/item-id-required` rule
  uses; the hand-written section templates no longer have to know the exceptions. A sweep of
  every kind-section pair against the metamodel found exactly two divergences: the event
  property (the missing `Id`, this defect) and the processing attribute (a superfluous one,
  already dropped on the fly).

## 2026-08-09 – 0.58.0, 0.59.0, 0.59.1, 0.60.0, 0.61.0

### Added
- **A `.xbql` query file became a language.** Highlighting and completion: the grammar is built
  from the platform's own vocabulary, the whole file counts as the query, and a table alias is
  followed by its fields. The same vocabulary highlights a `Query{...}` block inside a module.
- **The variable of a `for X in Collection` loop gets its type** from the element type of the
  collection. For that a structure now carries the type of every field in the index; a collection
  with two type parameters names no element, and there completion stays silent.
- **The members of the kinds' singleton types reached the data: from 12 kinds of 41 to 31.** The
  map from a documentation template page to an element kind is now derived from the serializer's
  own kind enum instead of being hand-written; a template that cannot be named is reported.
- **A call of a kind's method is typed.** The result type comes from the signatures in the
  documentation (25 kinds of 31), so completion knows what `Get()` of a constants set,
  `FindByCode()` and `GetReference()` of a catalog answered with.
- **A kind manager's properties and methods are told apart** – completion inserts the parentheses
  of a method and withholds them from a property.
- **`code/unknown-structure-field`: a field of a project structure is checked against its
  declaration** (139 rules now). The receiver is typed by a variable's declaration, by a
  constructor and by the element type of a for-each loop; on any doubt the rule stays silent.
- **Stale baseline entries can be seen and pruned:** `--stale-baseline` lists the entries that no
  longer suppress anything, `--prune-baseline` removes them and leaves the live ones alone.
- **The linter finds the project's baseline by itself** – it looks for `.xbsllint-baseline` upwards
  from the checked files and names the path it found; `--no-baseline` switches the search off.
- **Tool answers name the data they speak for.** `--version`, the MCP `version_info` and the LSP
  startup line carry the data root and where it came from.
- **`conventions/untranslated-code-literal` – visible text left as a literal in a module.** What is
  judged is not the literal but where it goes: an argument of a message to the user, a property of
  an event log event, a wrapper method included. Off by default.

### Changed
- **The dot completion offers what the catalogue knows about the kind.** The generic safety net
  stays with the rules, where a name too many is milder than a name too few; for a kind the
  catalogue does not know, completion is now empty and the editor falls back to word completion
  instead of inventing names.
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
- **Types described in metadata offered nothing after the dot.** The indexer read `TabularParts`
  and `Attributes` but neither the `Fields` of a structure nor the `Constants` of a set; it does
  now, and a constants set reaches the index under the generated names `<Name>.Record` and
  `<Name>.Data`.
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
  `ReadOnlyArray<Subscriber>` are those of `ReadOnlyArray`, while a parameterized type used to be
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
