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

## 2026-08-09 – 0.58.0, 0.59.0, 0.59.1

### Added
- **`code/unknown-structure-field` - a field of a project structure is checked against its
  declaration.** The compiler knows the shape of every structure declared in the project; the linter
  did not, because the member rules judge the stdlib catalogue and skip project types. A renamed
  field left its reader in ANOTHER module untouched, the whole-project run stayed clean, and the
  failure arrived with the server apply. The type comes from the variable's declaration, from a
  constructor call and - above all - from the element type of a for-each loop over a list, which is
  the shape the failure happened in. Silent on any doubt: a name declared with anything else in the
  method, a namesake of a stdlib type, the second hop of a chain, Latin member spellings. 139 rules
  now.
- **Stale baseline entries can be seen and pruned.** `--stale-baseline` lists the entries that no
  longer suppress anything (path, rule, how many suppressions each still holds, message);
  `--prune-baseline` removes them from the file, leaving the live ones and their reasons alone. The
  json report gained `baseline_stale` and `baseline_stale_entries`.
- **The linter finds the project's baseline by itself.** A run with no flag looks for
  `.xbsllint-baseline` upwards from the checked files, names the path it found and applies it;
  `--no-baseline` switches the search off, an explicit `--baseline` still wins. Before this a local
  run reported everything the project had deliberately frozen, which reads as a broken linter.
- **Tool answers name the data they speak for.** The environment snapshot (`--version`, the MCP
  `version_info`, the LSP startup line) carries the data root and where it came from; an empty
  `metadata_schema` answer adds that snapshot and the kinds the data does know - "the platform has
  no such kind" and "this data does not know it yet" became distinguishable.
- **`conventions/untranslated-code-literal` – visible text left as a literal in a MODULE.** The
  existing `conventions/untranslated-visible-literal` judges yaml alone, so prose written in code
  was checked by nobody: a message box built from a Russian string, or an event-log property that
  carries a ready phrase, stays Russian in every other language of the project. The new rule judges
  not the literal but the SINK it reaches - an argument of the platform's message call, a property
  of an event-log event constructor, or either of them one step away through a method that forwards
  its parameter whole. Forwarding is the point rather than a refinement: on the corpus that prompted
  the rule, seven of the nine findings reached the journal through a wrapper. When the text repeats
  a dictionary value, the message names the key whose translation is already written. Off by
  default (a project may legitimately build prose in code - seeding data, layout constants) and
  silent on a project whose descriptor lists fewer than two localization languages.

### Changed
- **`code/unused-method` judges the public API of common modules.** The rule silenced a method with
  ANY annotation, and a public method of a common module always carries one - so the check was
  silent exactly where dead code piles up. Now only the annotations that name a caller OUTSIDE the
  project code silence it: the platform, a contract, compatibility, and any annotation the
  dictionary does not know. Visibility and environment annotations leave the caller inside the
  project, so the method is judged.
- **The element-kind mapping is derived from the distribution instead of being hand-written.** The
  list of kinds comes from the serializer's own enum and the class from the suffix rule; five kinds
  whose class the rule cannot name are spelled out. 41 kinds instead of 35 - the data journal, the
  report panel and the integration process no longer look unknown to the platform, and a kind left
  without a class is reported rather than dropped.
- **`yaml/unknown-property` judges 18 kinds instead of 13.** The measure of a complete class is
  unchanged - live sources rather than a generated stub: the five kinds added are written with 6 to
  11 top-level keys in real projects, every one of them declared by the class.
- **The resource rules know both spellings of the folder.** The platform accepts `Resources` as
  readily as the Russian name (proved by compiling: a file in the English folder resolves, a missing
  one fails, the same file in a folder of any other name fails too). An English project used to look
  as if it had no resources at all.
- **Data-processor scaffolding.** An attribute no longer gets an `Id` - the line is written only
  when the class of the section item declares that property (a processor's attribute has none, and
  the apply failed on it); the PAIR of modules is created, and the operation's handler method is
  appended to the object module, where the attributes live.
- **English messages speak English.** Platform names and keywords in rule messages moved into the
  name substitution (a Russian project reads them in Russian, an English one in English), and the
  English CLI help now uses English spellings. Verbatim quotes of platform errors are left as they
  are.
- **The name whitelists were cleaned by the compiler.** Of 25 claims 12 turned out to be false: the
  standard attributes are available by bare name only when the yaml declares them (and then reach
  the module through the paired yaml anyway), four object names do not exist at all, and the fields
  of a register record belong to its data type. The entity-name table shrank from 15 entries to 4
  confirmed ones, so `code/undefined-name` no longer stays silent on code that cannot compile.

### Fixed
- **Types described IN METADATA offered nothing after the dot.** Navigation and completion read
  the members of a project type from one place of the index (`struct_members`), and only
  declarations IN CODE (`structure X` in a module) ever filled it: metadata objects reached the
  index with empty field lists, because the indexer read `TabularSections` and `Attributes` and
  never read `Fields` (Structure, StorableStructure) or `Constants` (ConstantsSet). Hence the
  empty hint after `new UpdateResult()` and after `SiteSettings.Get()`. The fields of those
  sections are now indexed: a structure under its own name, a constants set under the names the
  platform generates - `<Name>.Record` and `<Name>.Data` (docs "Types generated by a project
  element of the ConstantsSet kind"); the section is read in either spelling. The methods of the
  module extending the type (`<Name>.xbsl`, `<Name>.Record.xbsl`) join them. A `Get()` call on a
  constants set is typed through the new index key `generated_returns` - the stdlib member
  catalogue knows nothing about a project object, and without it the chain from such a call broke
  off. On the site corpus the index gained 10 types, and all four shapes (constructor, call,
  variable, declared parameter) answer.
- **`code/unknown-structure-field` crashed in the RELEASED wheel** (0.59.0): the tree walk read
  node fields through `vars()`, and in the native build the parser classes are compiled by
  mypyc and carry no instance dictionary at all - the rule took itself down on every module of
  a project. A pure-Python run cannot see this, so the local suites were green; the end-to-end
  check of the published package on a live project caught it. The fields now come from the
  dataclass declaration, as in the sibling rule where the same trap is documented from the
  previous time. A guard was added: a rule that reads a node through `vars()` fails the tests.
- The baseline summary line promises ENTRIES but printed the number of unspent suppressions - one
  entry may hold several. The former number stays in the json as `baseline_unused`.

## 2026-08-08 – 0.57.2

### Fixed
- **LSP navigation no longer waits out the lint of the whole project.** The project index was
  built at the very end of the background pass – after a lint an order of magnitude more
  expensive than the index itself – and until that pass finished, "find usages" and "go to
  definition" answered with nothing. The editor shows such an answer exactly like "no usages
  found", so a supported feature reads as missing. The background pass now starts with the
  index, and a navigation request that arrives earlier builds the index itself instead of
  answering empty. On a medium project navigation comes alive in 1.9 s instead of 7.2 s; on a
  tree holding several working copies, in 7.9 s instead of 37.0 s.

## 2026-08-07 – 0.54.0, 0.54.1, 0.55.0, 0.56.0, 0.57.0, 0.57.1

### Added
- **The properties of a section item are written by the tool, not by hand** (0.57.0). The
  object and its items were created by the tool, while `DefaultValue`, `Presentation` and
  `MaxLength` were finished by hand in the yaml: there was nothing to pass them in, and
  `meta_set_component_property` serves interface components alone. Now `meta_add_field`
  takes `props` (the properties of the new item) and its twin `meta_set_field_property`
  edits an item that already exists: a property already there is replaced in place, a new
  one is appended to the item. Names are checked against the item's metamodel class (both
  spellings accepted, the project's own is written); a value goes in as a scalar, quoted
  only where a bare one would lie (`DefaultValue: "https://..."`, but `client-code` bare). A
  property written as a nested block is refused rather than flattened into a scalar. The
  same in the CLI (`--prop KEY=VALUE`, the `set-field-property` command) and over LSP.
- **`Presentation` at creation time** (0.57.0): `meta_new_object` takes `presentation`
  (CLI `--presentation`). The property means different things depending on the kind, and
  the tool tells them apart: a report and the commands carry a CAPTION there, while a
  catalog, a document, an exchange plan and a settings storage carry the NAME of a string
  attribute whose value the platform shows for a record. A caption written into the second
  kind is rejected by the server ("Field specified as a presentation field is not found"),
  so such a call is refused with an explanation instead of handing over a file that will
  not compile.
- **Localization of a strings element** (0.57.0): `meta_add_localization` creates the
  translation file (`Localization/<Code>/<Name>.yaml`), repeating the `Strings`/`Templates`
  sections with the default-language values for the translator to replace in place;
  `meta_localization_info` answers which languages are declared, which of them is the
  default, which translations exist already and which languages a translation can still be
  added for. The language is taken in the project's spelling (`Russian`/`English`) or as
  the folder code (`Ru`/`En`). CLI - `add-localization` and `localization-info`, LSP -
  `xbsl/metaAddLocalization` and `xbsl/localizationInfo`.
- **The data processor form** (0.57.0): `meta_add_form` generates `ProcessingForm` - input
  fields per attribute and the operation commands through the `Commands` type
  (`MainCommand: =Commands.GetMain()`, `UsualCommands: =Commands.GetUsual()`), so new
  operations reach the form by themselves and no form module is needed. It is registered in
  `Interface.Form`, the way a report's form is.
- **The metadata schema answers to a descriptor class name too** (0.57.0):
  `metadata_schema` with `kind: "ConstantsSetConstantDescriptor"` returns the properties of
  that class. The class name is what the schema's own answers call things, so that is what
  callers asked with - and got an empty property list with no hint that the same properties
  live under `sections: ["Константы"]`.
- **The metadata schema names which attribute TYPE a property belongs to** (0.56.0). The
  metamodel describes an attribute as ONE class carrying the union of the properties of
  every type, so a schema consumer saw `IntegerPartLength` offered on a `String` attribute
  with no way to tell it does not apply. The per-type properties of a typed collection item
  (an attribute, a dimension, a resource) now carry `applies` - `"string"` (`MaxLength`,
  `Multiline`, `LengthControl`, `EmptyValue`), `"number"` (`IntegerPartLength`,
  `FractionalPartLength`, `MaxValue`, `MinValue`, both controls) or `"reference"`
  (`OnReferencedObjectDeletion`) - exactly as the documentation of every object kind spells
  the applicability. A property of a class that declares no `Type` of its own is never
  annotated: a namesake on an unrelated class must not inherit the table.
- **The English service file names resolve everywhere** (0.55.0). The platform accepts
  `Project.yaml` and `Subsystem.yaml` next to the Russian spellings (its converter checks
  both), while the toolkit knew only the Russian ones - an English-named project was not
  discovered at all. Project and subsystem discovery, the object's namespace, the rules
  reading the descriptor and the subsystem layout, the metadata tree and the project-root
  lookup of the CLI now take either spelling; what the scaffolding creates follows the
  project around it - a subsystem added next to a `Project.yaml` lands as
  `Subsystem.yaml`, and the demo of English spellings (`demo-en/`) carries the English
  file names itself now.
- **`meta_delete_object` / `xbsl delete-object`: delete a configuration object whole.**
  Removes the yaml+module pair, the object's forms `<Name>Form*` and the `ListRow<Name>`
  row component with their pairs (a subsystem is the folder the files live in, so the
  membership goes with them), and lists every REMAINING mention of the name by file and
  line - string literals and comments included, since a router opening a form by a name in
  a string is exactly the leftover that otherwise surfaces as a runtime error. The mentions
  are deliberately not edited. Deletion is irreversible, so the CLI answers with the plan
  until `--apply` and the MCP tool defaults to `dry_run=true`.
- **New rule `conventions/untranslated-visible-literal`** (tier D, project scope, on by
  default): visible text left as a Cyrillic literal where the project already references the
  same property into a localization dictionary. Self-tuning - only the keys the project
  itself localizes somewhere are judged, counted per element kind, and a project whose
  descriptor lists fewer than two localization languages is not judged at all.
- **A re-registered rule id replaces the earlier rule instead of duplicating it.** A rule
  migrating between a plugin and the engine exists in both for the transition (an updated
  engine next to a not-yet-updated plugin), and two rules under one id doubled every
  finding. The later registration wins; plugins load after the built-in modules, so a
  plugin's variant of a core rule keeps behaving exactly as before its removal.
- **`xbsl extract --keep-previous` snapshots the previous build's data.** The data directory
  is named by the product version while neighbouring BUILDS of one release land in the same
  directory - regenerating silently overwrote the previous build and left nothing to diff
  against; the workaround was a manual directory copy plus a hand-edit of the index. The
  extractor now records the build number of every run (the .car name carries it after the
  timestamp, so the version regex never captured it), and `--keep-previous` copies the
  existing directory to `<version>+<previous build>` and registers it, so
  `xbsl data-diff <version>+<N> <version>` works right away. A directory predating the
  record honestly answers that there is nothing to name the snapshot by.
- **The environment names itself.** `--version` lists the installed plugin packages with
  their versions, the new MCP tool `version_info` returns the same snapshot as data
  (engine, interpreter, Element data version, plugins), and the LSP writes that line into
  its start log. Two environments carrying diverged plugin versions answered differently
  on the same file, and nothing said so - the diagnosis went through site-packages of
  both.

### Fixed
- **A form module of an English project no longer drowns in false errors** (0.57.1). The
  `code/undefined-name` rule looked the component's base type up under the Russian key
  `Наследует`, while an English project spells the section `Inherits` - the base never
  resolved, the members of the base type never reached the module scope, and EVERY use of
  one was reported as an undefined name (an error-severity rule). The members now enter the
  scope under both spellings as well: the member catalogue is extracted from the
  documentation, and the documentation is Russian only, while an English project writes
  `WriteAndClose` and the compiler accepts it.
- **The rule stopped keeping quiet about commands that do not exist** (0.57.1). Its
  whitelist of "members the documentation does not carry" held `ВыполнитьЗаписать` and
  `ВыполнитьЗаписатьИЗакрыть`. They are not members of the platform: the compiler answers
  `Unknown method` to both, and no type of the shipped data declares such a member. A form's
  built-in command is a PROPERTY (`WriteAndClose` of type `Command`) and running it is
  `WriteAndClose.Execute()`; the whitelisted names belonged to handler methods of the
  author's own, declared in the form module - which the rule sees declared anyway. The
  exception kept two such calls alive in the demo project unnoticed for a long time; the
  demo now follows the shape of working sources.
- **`yaml/presentation-field` no longer judges a constants set** (0.57.0). The metamodel
  types its `Presentation` as an attribute name (the type is inherited from a shared base),
  but a constants set has no `Attributes` section at all - the rule demanded the impossible
  and condemned every constants set carrying a caption. The documentation of the kind calls
  the property the presentation OF THE SET, and the server accepts such a file (checked by
  compiling it); the rule now judges only the kinds that do have an attributes section. The
  negative control stays as it was: on a catalog a caption in that property is still an
  error, and even `Presentation: Name` is rejected by the server unless the attribute is
  written out in `Attributes`.
- **An insertion into a section no longer breaks a CRLF file** (0.57.0). The end of a
  section body was measured AFTER the `\r`, so the insertion landed between `\r` and `\n`:
  a lone `\r` was left in the file (a broken line), and git then normalized the newlines of
  the whole file, blowing the diff up from one edit to the entire file.
- **English help messages use the English spelling of names** (0.57.0): `Russian/English`
  instead of Cyrillic in the English help about the translation language, and likewise
  `LocalizedStrings`, `Localization`, `DefaultValue`, `Presentation` wherever the platform
  declares such a spelling. Cyrillic stays in English text only for names that have no
  English pair.
- **An English project's objects no longer fall out of the by-kind views**
  ([issue #1](https://github.com/keyfire/xbsl/issues/1)).
  Kinds were canonicalized through the type dictionary, which spells the stdlib TYPE
  (`Enum`), while the platform's serializer writes its own kind enum into `ElementKind:` -
  `Enumeration`, `IntegrationProcess`, `ReportPanel`, `DataJournal`,
  `IntegrableApplication` and `Project` did not resolve, and such objects landed under
  "Other" in the metadata tree. The extractor now reads the serializer's own kind table
  into the dataset (the `kinds` section of terms.json) and the resolution prefers it; a
  dataset generated before the section joined falls back to a built-in table read out of
  a current distribution. Every previously accepted spelling stays accepted.
- **The extractors' default data directory pointed inside the package twice.** The
  constant kept the layout the extractors had before they moved into the package, so a
  run without `--data-dir`/`XBSL_DATA_DIR` silently wrote to `xbsl/xbsl/data`; every
  documented run masked it with an explicit target. The default is the package's bundled
  root again.
- **Our own JSON files tolerate a BOM, and a parse failure names the file.** An `index.json`
  rewritten by PowerShell 5.1 (`Out-File -Encoding utf8` writes a BOM) failed every extractor
  step with the same bare `JSONDecodeError` and no path - the diagnosis took a run of its own.
  The version index, the datasets, the baseline and the diff inputs are now read with
  `utf-8-sig` (writing stays BOM-free), and a file that does not parse is reported by path.
- **`self-update` picks the wheel by the platform, not by the current install.** Deciding by
  the install made a ratchet out of one portable update: `is_native` answered False from then
  on, and every later update kept the portable wheel with no message - the demotion warning
  only fires on a native install. Caught live on the 0.53.0 release. The native wheel for
  this interpreter and platform is now preferred unconditionally, and healing a portable
  install is said out loud.

## 2026-08-03 – 0.53.0

### Added
- **Dictionary keys are indexed as the members they are.** A `LocalizedStrings` element has no
  module, so definition, references and completion knew nothing of `Dictionary.Key()`. The keys
  now sit with the module methods, the string itself becomes the hover description, and a
  template's arity follows its highest placeholder.
- **The documentation extractor reads the events section.** Newer type pages give events a
  section of their own; reading properties and methods alone made `type_members` claim a Button
  has no `OnClick` and turned a version diff into dozens of phantom removals. Events are a kind
  of their own now, `data-diff` calls a change of kind a MOVE, and a name the page also lists as
  a property is not taken for an event - some pages state inherited properties under the events
  heading. The datasets have to be regenerated for the effect.
- **A method stub for a handler that is not a form event.** `xbsl/addModuleMethod` writes the
  code half alone: a metadata handler sits at a yaml offset, so the editor writes the property
  itself. Nothing declares such a handler's signature, so the stub is shaped after a handler
  already bound to the same key nearby; with no neighbour it is parameterless and says so.
- **A route is added without composing its text.** `xbsl/metaAddRoute` and the MCP tool take a
  template with its methods next to the free-text form, and `xbsl/httpMethods` answers with the
  verbs a route may declare - an editor offers the engine's list instead of a copy.

### Changed
- **The language guard judges quoted names too.** A Russian name in a comment is a finding even
  in backticks when the compiler dictionary can spell it in English; the citation exception is
  left to what the dictionary does not know, to quotes of documentation and to code fragments.
## 2026-07-31 – 0.49.0, 0.50.0, 0.51.0, 0.52.0

### Added

- **The card of a platform method shows its parameters.** The dataset carried the result type
  alone, so a method read as `Name()`. The signatures the documentation prints are extracted
  next to the members (`member_signatures`, one string per overload), and inherited methods get
  the signature of the type that declares them. The data has to be regenerated for it.
- **The hover answers over the platform and over the global catalogue, not only over the
  project.** A member of a platform type had no card at all, and globals (`Message`, `Max`,
  `Execute`) never reached the member branch. The owner is now whatever the chain to the left of
  the dot evaluates to; a global's card names its kind and the environment it exists in.
- **A project method's card carries its signature and its description**, and a value it returns
  gets a type - `val P = Module.Method(...)` completes on the members of what it returns.
- **Rule `code/unclosed-resource`** (136 rules, tier D, `warning`, on by default): a query result
  bound to an ordinary variable is a `Closeable` descendant, and a `return` or `break` in the
  middle of the loop leaves it open - the log records it, nothing fails at that moment. The cure
  is the `use` modifier. False positives are bought off by narrowing: the type comes from the
  catalog by inheritance, the loop is joined to the nearest preceding declaration in the same
  method, a resource that arrived as a parameter or is returned to the caller is left alone.

### Fixed

- **`self-update` right after a release no longer claims there is no wheel.** The file list came
  from the JSON metadata of PyPI, a cache that lags an upload by minutes; it now comes from the
  SIMPLE index (PEP 691) with numeric ranking, and the JSON stays as the fallback.
- **The doc link of a member no longer lands on a random article.** A method is a section of its
  type's page, and the lookup by bare name matched any page carrying that qualifier - hovering
  `Add` offered an article about breakpoints. The page is resolved through the receiver now; the
  extraction no longer stores a quoted `Std::...` as a topic's own qualified name.

### Changed

- **The language of the sources is guarded, not remembered.** `tools/langguard.py` reads the
  lines a change ADDS and reports Cyrillic in comments, docstrings and Python identifiers; CI
  runs it on every push. The tree's legacy stays out of scope by design - a guard that can never
  be green teaches nothing.
- **Both English changelogs are guarded**, by the dictionary rule (a Russian name whose English
  twin is missing) and by a dictionary-free one (Russian prose outside citations), so a public
  checkout without the term dictionary is guarded too.
- **The MCP server runs on both majors of `mcp`, and the pin is gone** (`mcp>=1.2,<3`). `mcp 2.0`
  moved the ergonomic server class without leaving an alias, so a fresh install did not start at
  all; the import tries the new home first and falls back to the old one. Proven by talking
  JSON-RPC to a real server process on both: the same 30 tools, the same schemas.
## 2026-07-29 – 0.48.0

### Added

- **The "Variable and constant names" development standard as rules** (135 rules total). Six
  new `style/` rules cover the token-provable part of the standard: `style/abstract-name`
  (names like `Data`, `Item`, `Object` - exact or with a digit tail - say nothing about the
  variable; structure fields as a serialization contract are exempt), `style/single-letter-name`
  (one-letter names belong only to short lambda parameters - the standard's own exception, and
  lambdas declare nothing, so the rule never sees them), `style/negated-boolean-name`
  (`NotConnected` wants to be `Connected`; judged only where the boolean type is proven),
  `style/type-in-name` (a container type has no business inside a variable name),
  `style/numeral-in-const-name` (`TIMEOUT_ONE_MINUTE` spells its value - the wider half of the
  "abstract constant names" clause cannot be told from a legitimate enumeration-member constant
  and is left to review), and the project-scope `style/shadow-project-name` (a variable named
  like a project element hides that element for its scope; stdlib shadowing is deliberately NOT
  judged - platform handler signatures collide with type names en masse, a corpus run gave over
  900 forced hits). All six default to `warning`, matching the owner's decision that a documented
  standard is enforced.

### Changed

- **`style/abbreviation-case` reads Cyrillic abbreviations too.** The standard spells the
  accepted short words as one word each (`Ндс`, `Фио`, `Мчд`), so an all-caps Cyrillic run in a
  declared name is now reported with a suggestion, same as Latin ones. The abbreviation core
  logic is shared with the yaml naming rule: the trailing capital belongs to the next word, and
  a single-letter remainder is a glued conjunction, not an abbreviation - so compound names with
  one-letter unions stay clean, and constants stay out (ALL_CAPS is their law).

### Fixed

- **`self-update` of a native install can finally update itself.** Two defects, both met on
  a live update and both previously ending in a rollback (the insurance worked, the update
  did not happen). First, `--stop-holders` offered the command's OWN process tree for
  stopping - started via the installed shim, the command runs as a python child of an
  `xbsl.exe` launcher that looks exactly like a holder by name; stopping it cut the update
  short. Holders now exclude the command's ancestors and descendants; other live xbsl
  processes are still named and stopped. Second, the mypyc shared libraries that live in
  the site-packages ROOT (next to the package, not inside it) were overwritten in place by
  the extraction - and that fails with `Errno 13` while the running self-update itself
  keeps them loaded. They are now renamed aside like the package directory: a rename of a
  loaded module passes where an overwrite does not. The list of root files is read from
  the installed RECORD, not globbed - another mypyc-built distribution keeps its own
  library in the same root and must not be touched. A file backup the finished process
  still held is swept by the next run.

## 2026-07-28 – 0.47.0, 0.47.1, 0.47.2

### Changed

- **The texts of the two new rules speak in the demo project's vocabulary.** Docstrings,
  tests and the changelog entries of `code/unknown-tabular-member` and
  `code/global-unavailable` now take their examples from the demo project
  (`Задачи`/`Шаги`), like the rest of the documentation.

### Fixed

- **The `mcp` extra is pinned below 2.** `mcp 2.0.0` (released the same day) dropped
  `mcp.server.fastmcp`, which the MCP server imports: a fresh `pip install "xbsl[mcp]"`
  picked the new major and the server refused to start. The pin keeps 1.x until the
  server moves to the new API.

### Added

- **`code/unknown-tabular-member` - a member access on a tabular section's rows must exist
  on the array type.** The receiver is typed by the PROJECT's metadata, not by a declaration,
  so neither unknown-member rule saw the shape: `Object.Sections.Count()` in an object form
  module passed the linter and failed the live apply (the array member is called `Size`).
  The rule joins the form's base type (`ObjectForm<Entity.Object>`) or the entity's own
  modules to the declared tabular sections and judges the member against the array catalog,
  with the habitual `Count -> Size` hint difflib cannot bridge. A module named after a
  section shadows the bare name - real projects keep such modules - and an attribute is never
  judged.
- **`code/global-unavailable` - a global context name called outside its environment.** The
  docs print availability per member of the global context packages, and the stdlib extractor
  now stores it (`global_availability`): `Message` exists on the client only, the dynamic
  evaluation globals on the server only. A method executes in its module's environment - the
  standard one of the element kind (a catalog or register module and an HTTP service are
  server code) - unless `@OnServer` or `@OnClient` pins the side. `Message(...)` in a catalog
  module is the shape that passed the linter and failed the live apply with "the method is
  unavailable in the current environment"; the mirrored direction (a server-only global in a
  client method) names the fix - `@OnServer`.
- **`code/collection-field-needs-req` - a structure field whose generic type cannot be built
  empty.** `var texts: ReadableArray<String>` is refused by the apply ("cannot be initialized
  with a default value and is not marked as required for the constructor"): the type's only
  constructor is the copying one, so there is no default value to fall back on. `Array<String>`,
  `Set<String>` and `Map<String, Number>` are the opposite case and are left alone - each has an
  argument-less constructor, the platform documentation itself declares a variable that way, and
  on real code such fields are commonplace. Which is which is now a FACT IN THE CATALOG: the stdlib
  extractor reads the "Constructors" section of every type page and stores `type_ctors` -
  `empty` (callable with no arguments), `args` (all of them demand arguments) or `none` (none
  documented). The rule judges only a type written WITH a type argument: for a bare name the
  constructor alone would mislead, since `String` and `Boolean` take arguments and still have a
  default value of their own. File scope, so the editor reports it on every keystroke.

- **`code/var-needs-init` - a variable declared by a type that has neither a constructor nor a
  default value.** `var Response: HttpResponse` (declare first, assign inside the try) does not
  compile - the type is only ever handed out by the platform, and the compiler answers exactly
  that: no constructor and no default value. The rule flags a declaration whose type the catalog
  reports as `none`; a type with an argument-taking constructor is left alone, because a bare
  name may still be a primitive with a default of its own, and so are the hierarchies where a
  default is plausible - an enumeration, an annotation, a singleton. It is project-scope for one
  reason: a bare name may belong to a PROJECT type of the same name - real projects do declare a
  structure or an object named after a platform type with no constructor - and only the whole
  project can tell. The fix is `Type?` plus a check, or reading what is needed inside the try
  into plain variables.

## 2026-07-27 – 0.41.0, 0.42.0, 0.42.1, 0.43.0, 0.44.0, 0.45.0, 0.46.0

### Fixed

- **What the scaffolding WRITES now follows the language of the project.** Reading English
  sources was only half the job: a form generated into an English project arrived with Russian
  keys, Russian type names and a file name carrying the Russian form suffix, and a new service
  came with Russian route names and Russian code stubs - the very island the bilingual reading
  was fixed to avoid. Keys and platform type names come from the platform's own data (the
  metamodel classes for metadata keys, the compiler dictionary for component properties - the
  English demo project spells exactly those); the author's names are never touched, so an
  object named like a platform type keeps its name. The words the tool invents for itself (a
  row-data structure, route handler and template names) are its own vocabulary in both
  languages, and the code stubs of an English service are a second text rather than a
  translated one - keywords, stdlib names and comments together.
- **What the data cannot name is said out loud.** The value lists of the INTERFACE
  enumerations exist in English in the platform but are extracted in Russian only, so a
  generated English form keeps `WidthInColumns: Одинарная` - and the report names those values
  instead of inventing an English word for them.

- **The project-scope localization rule no longer ships whole source files between
  processes.** `code/compare-with-localized` needs the project's dictionary names before it
  can judge a module, and used to defer everything: the map phase put the source file into
  the fact and the parent re-tokenized every module of the project in the reduce. The token
  work now happens in the worker that already has the tokens, and the fact carries only the
  localized calls that stand NEXT TO a comparison - a module without comparisons contributes
  nothing at all. What travels between processes stops growing with the project, and the
  parallel run gets the time back.

- **`style/boolean-compare` no longer fires where the comparison is mandatory.** The rule stood on
  tokens alone and reported every `== True`, so on a real project all of its findings were false:
  the short form does not compile ("Boolean expression is expected") as soon as the value is
  nullable or composite - a component property is `Auto|Boolean`, `HtmlContainer.GetVariable`
  returns `Boolean|JsObject|Number|String|?`, `Form.OpenInModalWindow` returns `ResultType?`. The
  operand is now typed: by the catalog for a member access or a call, by the annotation for a
  parameter or a local, and by the initializer's last link for a variable. A comparison stays a
  violation only when the type is exactly `Boolean`; what the file cannot type at all is still
  reported, because an unknown name is the usual violation the rule exists for.

- **Scaffolding reads a project written with English metadata keys.** Only writing was bilingual:
  every yaml READER in the scaffolding matched Russian spellings, so `rename-object`, `object-info`,
  `add-field`, `set-access`, `add-form` and `add-route` answered "no such object" on an
  English-spelled project - and three operations were worse than that, answering successfully with
  the wrong result: `project-info` reported an empty object list, `add-dependency` appended a second
  library entry instead of updating the version in place, and `add-subsystem` wrote a Russian
  descriptor into an English project. `object-info` also invented a standard `Наименование`
  alongside the declared `Name`, which would have reached a generated form as a column. Readers now
  accept both spellings and write in the language of the file. The pairs come from the platform's
  own metamodel (`english_name`), never from a hand-written table: `terms` is the source for VALUES
  (kinds, enumerations) and the metamodel for KEYS, and they genuinely differ. A name the platform
  spells ambiguously across classes (`Элементы` is `Items` on an enumeration and `Elements`
  elsewhere) stays Russian on purpose - guessing costs more than staying silent. Without the
  platform data everything degrades to the previous Russian-only behaviour.

- **A parallel run of the released wheel no longer dies as `BrokenProcessPool`.** With `--jobs`
  left at its default the engine goes parallel on its own once a run has at least 120 files and the
  machine has at least 4 cores, so `xbsl lint` over a real project failed outright – no flag
  needed. The pool broke while the PARENT unpickled a worker's result: a fact carried a whole
  `SourceFile`, and with it the file's cache holding a `lexer._LineMap`. In the native build that
  class is a C extension: it pickles, but unpickling calls `cls.__new__(cls)` with no arguments and
  its generated constructor refuses. The exception surfaced only as a broken pool, and only in the
  wheel – a pure-Python run was never affected, which is why neither CI nor development saw it.
  Sources now leave their cache out of the pickle (derived, process-local data, rebuilt on demand),
  which closes the whole class rather than the one entry that tripped it, and shrinks a worker's
  result from 1.96 MB to 0.58 MB. Guarded by new tests that do not depend on the build.

- **An object rename that only changes letter case is no longer refused.** `xbsl rename-object` /
  `meta_rename_object` answered "Файл уже существует" to a rename of `Goods` into `goods`: a
  case-insensitive filesystem (Windows, macOS) addresses the old and the new name as one file, and
  the occupied-name check read it as a foreign one. Such a rename is now recognised (the names
  match case-insensitively AND it is the same file) and applied in two steps through a temporary
  name; a failure of the second step undoes the first, and no temporary name is left on disk. A
  name held by ANOTHER file is still refused. On a case-sensitive filesystem nothing changed -
  there the name is free, the rename runs in a single step and no intermediate name appears in the
  report.
- **A case-only rename warns about the version control system.** The tool renames the files
  itself, but git on a case-insensitive filesystem folds ASCII letters only: a Latin rename goes
  unnoticed (`git mv` is needed), while a Cyrillic one is recorded as a delete plus an add - and
  then every other clone on such a filesystem stops at "untracked working tree files would be
  overwritten by merge". A new note in the tool's answer says so.

### Changed

- **`self-update` no longer trades a working installation for an empty directory.** The
  command now renames the installed package aside FIRST – a rename fails while a file inside
  is open, and at that moment nothing has been removed – then names the holding processes by
  name and pid (`--stop-holders` ends them). The previous installation is kept until the new
  one is PROVEN to import in a separate process; a broken archive, a failed extraction or a
  package that does not import puts the old one back. This is the failure the command exists
  for: `pip install --upgrade` removes the old version, fails to unpack the new one over a
  held compiled module and says nothing about the empty space it leaves.
- **A native installation is updated from a native wheel.** `self-update` always took the
  portable `py3-none-any` wheel, so a compiled install silently became pure Python – several
  times slower parsing, with nothing said. The wheel is now chosen by the interpreter and
  platform tags; when there is no native wheel for the platform, the portable one is used and
  the command says so. Holders are recognized by their own executable name or by an
  interpreter running our modules – an editor or an agent that merely mentions `xbsl` in its
  arguments is never offered for stopping.
- **Everything the command prints goes through the message catalog** – `--lang en` answers in
  English, as the rest of the toolkit does.

- **The type catalog keeps the full spelling of a union result type.** The extractor cut a member's
  type at the head (`Auto` instead of `Auto|Boolean`, `Boolean` instead of
  `Boolean|JsObject|Number|String|?`), so the data could not tell "a boolean" from "a value that
  may be a boolean" - 438 members in the current dataset and 359 in the previous one were stored
  short. Consumers that
  work in nominal heads are unaffected: `dataset.member_type_head` cuts the union the same way it
  always did.

- **What the platform documents as a code-writing convention is now a standard: seven `style/`
  rules run by default and report at `warning`** – line length, comparing a boolean with
  `True`/`False`, UpperCamelCase, collection literals, string interpolation, a redundant
  `.ToString()` and the case of abbreviations. They used to be `info` and off, treated as
  accumulated debt; a convention that is documented and never enforced is not a convention.
  Existing debt belongs in a baseline, and new violations are visible from the first run.
  Off by default remain only the two checks whose finding may legitimately be a false positive:
  `code/unused-method` and `yaml/size-needs-no-stretch`.
- **A rule that is off by default says WHY, in the listing itself.** `--list-rules` prints the
  reason under the rule and the machine-readable listing carries it in `off_reason` – the
  reason used to live in the rule's docstring, a column of `docs/RULES.md` and nowhere the
  reader looks. A new `off_reason=` argument of `rule()` carries a catalog key, so the text is
  translated like everything else; a guard requires it from every disabled rule.

### Added

- **`code/bound-property-assign` – a property COMPUTED by an expression must not be assigned from
  code.** The platform refuses `Component.Property = value` when the markup computes that property
  (`Height: =Common.IsMobile()?820:528`) and answers "Cannot set the value of property ... specified
  by expression"; inside the usual `try/catch` cascade the refusal is invisible and the symptom is a
  layout that quietly ignores the code. A DATA BINDING is left alone: `Value: =Record.Value` is a
  bare path, the documentation calls such a link two-way for an editable component, and writing to
  it is how an editor gives the value back - so the rule judges the SHAPE of the expression, a path
  against anything computed. The paired yaml is read from the disk neighbour, so the rule stays
  file-scope and the editor reports it on every keystroke.

- `style/redundant-type` now sees the typed empty literal: `var Articles: Array<Number> =
  <Number>[]` states the type twice, and the platform's "Idioms" article documents the short
  form (`val Articles = <Number>[]`). Only the array spelling is recognised – the empty set and
  map forms are not in the documentation, and guessing at them would risk a false positive.

- **`xbsl/metaKeys` – the element key pairs for surfaces outside python** (`Attributes` ->
  `Реквизиты`), the metadata counterpart of `xbsl/formKeys`. The metadata tree of the editor
  parses the yaml itself, so an English object used to show empty branches: the sections were
  looked up by their Russian names while the file spells English ones. Pairs are collected from
  the `en` of the metamodel classes - the whole model, not one kind, because a section item is a
  class of its own and the tree descends into it. Without the data the request answers
  `{"available": false}` and the reader keeps working on Russian keys.

## 2026-07-26 – 0.36.1, 0.37.0, 0.37.1, 0.37.2, 0.37.3, 0.38.0, 0.39.0, 0.40.0

### Changed

- **A guard over the English documents.** Russian spellings of platform names in the English
  documents (`Группа` for `Group`, `Ид` for `Id`) drifted in with every wave of rules and were
  caught by eye alone. A test refuses them now, knowing the three legitimate cases: a file name the
  platform keeps Russian for projects of either language, a single letter that is the subject
  itself, and a link to the Russian twin. The divergences it found in the rule table and in the
  extension settings strings are fixed.
- **0.37.3: the last docstrings and the demo README state the facts too.** What the compiler
  accepts and what a rule guards against stay; the rest is gone. No rule changed its behaviour.
- **0.37.2: the texts state the facts, not how they were obtained.** The changelog, the rule
  docstrings and the test comments describe what the platform does and what a rule checks;
  the provenance of that knowledge is gone from them. No rule changed its behaviour.
- **0.37.1: the docstring of `code/property-since` no longer names a platform version.** The rule
  is unchanged - it still compares the version a property appeared in against the mode the project
  declares; only the example in the module docstring dropped the number.

### Added

- **0.40.0: four rules - per-object permissions and localization** (122 rules now).
  - `code/per-object-permissions-need-common` (warning): an object asks for its permissions to be
    decided per record while its module declares no common `ComputeAccessPermissions` handler. It
    is required even then, if only to return an empty array; without it the object has no general
    permissions at all and the per-object calculation is never reached.
  - `code/permission-field-not-declared` (warning): inside `ComputeAccessPermissionsForObjects` a
    field outside `ComputePermissionsBy` is read, or a declared field is reached through `Entity`
    instead of the record. The declared list is what tells the second shape apart: `Entity.Privilege`
    is a legitimate namespace and appears in the very same handler.
  - `yaml/placeholder-key-in-strings` (error): a key carrying the `$0` placeholder in the `Strings`
    section of a dictionary. The section compiles to a method WITHOUT parameters, so a call with an
    argument fails the apply - and the answer names the key but never the section, pointing away
    from the cause.
  - `code/compare-with-localized` (warning): a localized value compared against a literal or a
    second localized value - in another language the branch simply never runs. Branch on the value
    behind the presentation instead. A comparison against a variable is deliberately not judged.

- **0.39.0: `yaml/delete-current-needs-immediate`** (118 rules now). A reference attribute with
  `OnReferencedObjectDeletion: DeleteCurrent` whose owner has a `DeletionMode` that only marks the
  record brings the whole apply down: `Action DeleteCurrent cannot apply to object with a
  DeletionMark`. An object that never declares the mode is in the same trap - `DeletionMark` is the
  default, and the rule takes it from the metamodel rather than from its own text. Both facts live
  in one file, so the check is a file rule and highlights while you type; keys and values are read
  in either spelling.

- **0.38.0: two rules over the execution environment** (117 rules now). Both close an apply
  failure that leaves no line in a local build: `elemctl build` packs an archive, while the
  environment is checked only by the server-side compilation.
  - `code/client-available-needs-context` (error): `@AvailableFromClient` on a method of an
    interface component module that is declared neither `static` nor `@Contextual`. The component
    type is not a singleton, so the apply answers `Modifier "AvailableFromClient" can only be used
    in static methods, singleton-type methods, or methods with modifier "Contextual"`. Both
    documented forms pass in silence: the static method that hands execution from the client to the
    server, and the contextual one that keeps the instance context. The check is confined to
    interface components on purpose - `@Contextual` is available in their modules alone, while
    common modules, catalogs and information registers are singleton types, where the plain form is
    correct.
  - `code/server-module-in-client-context` (error): a `Module.Member(...)` access to a common
    module with `Environment: Server` from a method that runs on the client. The mirror of
    `code/client-module-in-http-service`, except that the failure here is not a runtime one but a
    compile-time one - `<Client> Type "X" is unavailable in the current environment`, and the
    application is never created; hence the error level. Only the bodies of methods without
    `@OnServer` are read: a method carrying that annotation runs on the server, where the type does
    exist. The modules judged are the ones that live in the Client environment - interface
    components, commands, storable structures and common modules with `Environment: Client`.

  Both rules read the platform names in either spelling (`terms.json`), so an English project is
  caught just like a Russian one.

- **Five rules over what the platform ACCEPTS but does not do** (115 rules now). The compiler is
  happy in every one of these cases and the defect surfaces later - on the screen, on the deploy or
  in the database.
  - `yaml/empty-group-sized` (warning): an empty `Group` with a fixed `Height`/`Width` is thrown
    out of the DOM entirely, so the spacer leaves no gap. The cure is a non-empty transparent insert
    of the same height.
  - `yaml/hint-too-long` (warning): the renderer cuts a `Tooltip` off at about 290 characters
    without a scroll or a "more" affordance - the tail is simply lost.
  - `code/close-in-before-close` (warning): a `Close()` call in the own flow of `BeforeClose`
    is ignored by the platform while the closing stays unfinished, and after that nothing closes the
    form. The recommended cure - the call handed to a one-shot timer inside a lambda - the rule
    passes over in silence.
  - `query/no-isnull` (error): the query language has no such function at all.
  - `project/path-matches-descriptor` (error): a build refuses a project whose directories diverge
    from the descriptor before the sources ever reach the compiler, and the case matters. The
    directories of the repository's demo projects are renamed to match their descriptors.

### Fixed

- **The sync guard looked at four places out of eight** - which is why the rule counters on the
  documentation pages had drifted unnoticed to 97 and 87. It now checks all eight (26 checks) and
  the counters are corrected; the messages of the new rules go through the `{n[...]}` name map like
  every other one.
- **The tree walk skipped everything inside a condition.** The branches of `если` hold (condition,
  body) TUPLES while the walker only descended into lists of nodes - a lambda inside a condition
  was invisible to it.
- **The 0.36.0 wheel checked NOTHING: every run died with `TypeError: vars() argument must have
  __dict__ attribute`.** The rule about the fields of a dynamic list row walked the tree through
  `vars(node)`, and in the released wheel the parser is compiled by mypyc - a compiled class has
  no `__dict__` at all. The walk now reads the fields declared by the dataclass
  (`dataclasses.fields`, the names remembered per class), and that was the only place depending
  on `__dict__`. In the tests `vars` is a landmine, so an attribute walk cannot come back
  unnoticed. The earlier explanation - "a mixed installation is
  to blame" - was wrong: every environment with the native wheel was broken.
- **A crashing rule no longer takes the run down.** A rule is code like any other, and its bug is
  now one finding (filed under the id of the rule at fault, so `--ignore` silences it) while the
  other rules do their work: the tool returns the report instead of a traceback. An environment
  failure is excluded from this - missing Element data breaks every rule at once and is still
  reported once, by its own message, rather than as a hundred identical findings.

## 2026-07-25 – 0.35.0, 0.36.0

### Added

- **Two rules about a static method** (`code/this-in-static-method`, `code/instance-call-from-static`).
  The documentation states both bans in one breath: a static method is common to the whole type,
  so it has no object context - `этот` in its body and a bare call of an instance method of the
  same owner are rejected by the compiler. The method boundaries come from the AST, the
  occurrences from the code tokens: a `этот` inside a lambda of a static method counts, one inside
  a comment does not. The call rule stays silent on a member call, on a shadowed name and on a
  name declared BOTH static and instance - the docs allow that pair when the signatures do not
  overlap.

- Rule **`code/local-method-cross-module`** (tier D, error, project-scoped; 101 rules now):
  `Module.Method(...)` must target a method that carries a visibility annotation. @Local is
  the DEFAULT visibility of a language construct, so a method with no annotation is reachable
  from its own module alone and the compiler rejects the call on build. The sibling
  `code/local-method-cross-component` covers the same invariant reached through a component
  INSTANCE (`Components.X.Method(...)`, a runtime failure); this one goes through the module
  name and resolves it by the file stem, the resolution of `code/call-arity-cross`.

### Fixed

- **The public CI had been red since the previous release** - and the imitation of a data-less
  clone, not GitHub, is what surfaced it. Three bilingual tests expect the English spellings from
  `terms.json`, which a checkout without the Element data does not have; they are marked
  `@pytest.mark.needs_data` one by one, because the modules also hold data-free tests. The second
  red job was mypy over the compiled modules: it follows the TRANSITIVE imports of the lexer and
  the parser, and `dict | None` was not narrowed in `metamodel.has_class` and
  `uischema._outside_component`.
- **The scaffolding writes in the language of the project.** A new object created in an
  English-spelled project used to land as a Russian island (`ВидЭлемента: Справочник` next to its
  `ElementKind: Catalog` neighbours). The language is decided by the sources themselves, by
  MAJORITY so one stray file cannot flip a project, and never by a setting: the tool has to match
  what is already there. Header keys and their values come from the metamodel and the term
  dictionary (`Ид` is `Id`, `ВПодсистеме` is `InSubsystem`).
- **A project written with the ENGLISH metadata spellings is judged like a Russian one.** The
  platform reads sources either way - a catalog spelled `ElementKind: Catalog` / `Name` /
  `Attributes` / `Length` compiles - but the rules looked for
  `ВидЭлемента`, did not find it and skipped the whole file: not even a typo in it was reported
  (`VisibilityScopeX` passed in silence while its Russian twin was caught at once). The element
  kind is now read in either spelling and answered in one, `allowed_keys` carries the English
  names, and a property is looked up by whichever spelling the file uses. The English key comes
  from the metamodel record itself: the `en` argument of the platform's annotation or, where it
  declares none, the model member's name capitalized - only 405 of the 1120 annotations carry
  `en=`, and `Реквизиты` (member `attributes`) is one of those that do not, yet `Attributes:`
  compiles. On Russian sources the findings stayed byte-identical.
- **Forms too: an English-spelled component is parsed and judged.** The form model reads its
  keys through the compiler's own dictionary (`Content` is `Содержимое`, `RowCommands` is
  `КомандыСтроки`), so the designer, the structure panel and the edit operations see the same
  tree whichever language the file is in; `yaml/unknown-enum-value` accepts both spellings of a
  component, of its property and of every value, and lists the allowed ones in the language the
  author typed. The pairs are always built FORWARD from the names we look for - the dictionary
  is many-to-one in reverse (`Type` is the English of both `Тип` and `ТипЭлементаПроекта`), so a
  plain reverse map would answer with whichever pair came last. `Шапка` has no English name in
  the dictionary and stays Russian-only - nothing proves one.
- **The demo project has an English twin (`demo-en/`), and it is a guard.** The same tiny
  application written with the English metadata spellings; a test asserts both twins report the
  SAME findings on the same lines, so a rule going blind on English sources shows up as a missing
  finding instead of as silence. The rules that read a component's own properties now do so in
  either spelling as well (`yaml/size-needs-no-stretch`, `yaml/choice-needs-static-list`,
  `yaml/dynlist-missing-field`, the reserved-name and undefined-name checks): a fixed `Height`
  without `VerticalStretch` used to pass in silence while its Russian twin was reported, and the
  advice now names the keys the way the file spells them. Where the platform has no English name
  of its own - the project and subsystem descriptors, the values `Двойная`/`Основная`, the form
  members `ВыполнитьЗаписать` - the Russian one stays; that is the platform's vocabulary, not an
  omission. The documentation shipped in the distribution is Russian only (both versions carry
  `data/docs/help/ru/` and nothing else), so hovers and the docs panel stay Russian in an English
  editor.

- An MCP tool called with a **misspelled argument name now fails** instead of silently running
  with its defaults: pydantic ignores unknown keys, so `lint_paths(rules=...)` (the filter is
  `select`) looked like a broken parameter rather than a wrong one. Every tool model is switched
  to `extra="forbid"` after registration.

### Changed

- `code/unknown-static-member` types a variable whose value comes from ANOTHER module: every
  module now publishes the return types of its own methods, and the project phase joins
  `Module.Method(...)` to them by the file stem. This closes the line the rule was written for -
  a value with no declared type asked for `Count()` where an array has `Size()`, and the build
  paid for it. A name the method binds itself is never read as a module (`var Sections =
  Sections.GetAll()` means both in one method), twin module names and methods declared twice are
  dropped, and an attribute of the paired form named like a module shadows it.
- The metadata scaffolding writes a **slot by its cardinality**: a first child of a slot the ui
  schema declares `Array<Component>` (`Group.Content` and friends) lands as a "-" list item, not
  as a single nested mapping. A singleton there compiles into "Значение типа ... не может быть
  присвоено в Массив<Компонент>" and takes the whole `Components.<Name>` resolution down with it -
  the trap `meta_move_components` fell into when a table moved into a fresh group. Slots declared
  with a single type keep the mapping spelling; an owner the schema cannot name (a page item
  carries no `Type`) keeps it too.

## 2026-07-24 – 0.32.0, 0.33.0, 0.34.0

### Added

- Rule **`yaml/unexpected-type-argument`** (tier D, error, file-scoped; 100 rules now): a type
  argument on a property the ui schema declares WITHOUT one is another type, and applying the
  build rejects it. The case it comes from: a form's `AdditionalCommands` takes
  `CommandInterfaceFragment`, and `CommandInterfaceFragment<UsualCommand>` broke the build
  ("не может быть присвоено в ФрагментКомандногоИнтерфейса?"); a table's `Commands` behaves
  the same, while `RowCommands` is declared parametrized and needs the argument. Only a match
  by the type name is judged - a subtype written in a collection slot is left alone.
- The ui schema carries a **`type_params`** section - the type parameters of the generics and
  the defaults the documentation states for them (`CommandInterfaceFragment<CommandType>`,
  CommandType defaulting to `Command`). Without it the check above produced false positives:
  an argument spelled out but equal to the default is the very same type. The section appears on a data regeneration: `xbsl extract --only uischema`
  (no distribution needed - the step reads docs.sqlite).
- `ui_schema` answers for names the palette does not carry - commands (`UsualCommand`,
  `CommandWithParameter`), command interface fragments and groups, `ValueListItem`. The
  properties come from the compiler's metamodel, and what has no class of its own there is
  taken from the stdlib type catalog; the record says `source`, and an element kind also says
  `metadata_kind`. A kind is resolved through `vid2class` - the same set `metadata_schema`
  serves: resolving the NAME would find the `UsualCommand` type with 8 properties instead of
  the descriptor's 13. Metamodel property types come back in the short spellings, and the
  close matches of a miss are searched beyond the palette too.

- `xbsl extract` – the dataset generator as a CLI command. The extractors moved into the
  `xbsl/extract` package, so an installed package generates the data without a repository
  clone; `tools/extract_*.py` remain as thin back-compat shims, and `python -m xbsl.extract`
  works too. The manager pins the version detected from the distribution for every step, so
  regenerating an OLD version no longer writes the docs-derived uischema into the current
  default one.
- `xbsl data-diff [old] [new]` – what changed in the platform between two generated data
  versions (default: the index default against the closest older version): stdlib types and
  members, member result types, metamodel classes/properties/enums, interface components and
  their properties, terms, documentation pages. Members are compared with the inheritance
  expanded and every change lifted to the hierarchy root, so how members split between a type
  and its bases – an artifact of extraction – does not read as a platform change.
  `--format text|md|json`; the text form caps each list at `--limit`.
- The version index only moves the default forward: regenerating an old version keeps the
  newest one the default.

- The `code/invalid-string-escape` rule (tier C, error): an escape sequence a string literal
  cannot carry (`\'`, the regex-style `\d`) is caught before the server-side compilation.
  Valid are `\н \в \т \\ \" \% \$`, `\ю` with a decimal character code and the Latin
  spellings; interpolation spans are skipped, and pattern literals (`'...'`) live by the
  regex syntax and are not judged.
- MCP `ui_schema`: the `brief` parameter answers one line per property (the type union,
  enum values inline, nullable/slot markers, event signatures) instead of the full
  component schema, and `property` returns the full record of a single property with the
  enumerations it references.
- The metadata schema resolves a closed data-type constraint of a property into the list
  of allowed values: for the standard `Code` attribute the panel offers exactly `String`
  and `Number`, not every type of the project.

### Fixed

- `code/unknown-member` judges a variable of a GENERIC type by its head: the arguments type
  the members and do not name them, so `ReadOnlyArray<Subscriber>` has the member set of
  `ReadOnlyArray`. A parameterized type used to be skipped whole, and `Count()` - a habit from
  another platform, where Element has `Size()` - reached the compiler. A variable with NO
  declared type whose value comes from another module is still invisible - that needs the callee's return types in the project phase.
- Documentation search no longer answers nothing to a multi-word query: when no page carries
  every word, the search relaxes to "any of them" and ranks by how many words matched, bm25
  breaking ties. A four-word query used to return zero hits; plain bm25, in turn, answers with
  a page repeating one word, leaving the page named after the query words far below.
- `xbsl extract --help` names the command instead of the interpreter path (`python.exe
  C:\...\Scripts\xbsl`): the extractors' parsers were built without `prog`. A step's own help
  names `python -m xbsl.extract.<step>`, the form that takes the step's own options, while a
  run through a `tools/extract_*.py` shim or `-m` keeps the name argparse printed - exactly
  what the user typed.

- The stdlib extractor recognizes interface components of newer distributions again. Their
  hierarchy sections list base types as links with unqualified texts, so the qualified-name
  marker matched nothing and the built-in property sets survived for one component out of
  dozens; the link target is now accepted as the marker as well.
- A variable named `Query` (the keyword spelling) was read as the query-literal keyword
  everywhere: the declaration dropped out of the token utilities, a `Query.Execute()`
  chain fell into the literal path, and the hover documented the database query type.
  Like the parser, the tokenizer now reads it as a plain name when no `{` follows.
- A single-file check (the way the editor lints a saved module) lost the paired yaml's
  shadow, so a form attribute named `Email` was judged as the same-named stdlib type.
  The pair's names are read from the disk neighbor when the module has finding candidates.
- The hover documents neither a declared variable with an uninferred type nor a name the
  paired yaml declares as a same-named stdlib type.

## 2026-07-23 – 0.31.0, 0.31.1

### Changed

- The generated stdlib type catalog records fuller member types and curates extra type surfaces
  from the platform's topic pages, so the linter's member checks and completion match what the
  platform actually exposes (0.31.0).

### Fixed

- `code/resource-bare-name` no longer treats an `inbase/...` reference as a folder path: a resource
  uploaded into the application base is a lookup key, not a disk path, so the rule leaves it alone
  (the compiler verifies its existence at apply) (0.31.0).
- A resource key is a path relative to the subsystem's `Resources` folder: `code/resource-bare-name`
  now flags only a key that spells the `Resources` folder out, and subdirectory references
  (`Subfolder/File.svg`) are legal instead of being reported (0.31.1).

## 2026-07-22 – 0.28.0, 0.29.0, 0.30.0, 0.30.1

### Added

- The documentation site ([docs.keyfire.ru/xbsl](https://docs.keyfire.ru/xbsl/)), a full command
  reference and CLI help – complete in English and Russian (0.29.0).
- The platform metamodel resolves the schema of a collection item – an enumeration value, an
  attribute, a dimension, a resource, a structure field, a tabular-section attribute – so the
  linter sees its full schema with defaults and documentation, not only what the yaml already
  sets (0.29.0).
- A new engine operation to remove a form handler (`xbsl/removeHandler`): it unbinds an event and
  deletes its method – with the annotations and the separating blank line – as a single edit
  (0.28.0).

### Changed

- Faster on large projects: caches for the data-binding layer, YAML parsed through libyaml
  (`compose`), and worker pools sized to the workload (0.30.0).
- A type's hover carries its description from the platform documentation above the page link, not
  the link alone (0.28.0).
- Completion follows a member chain past a property link, with a guard that stops at the edge of
  the stdlib closure instead of looping (0.30.1).

### Fixed

- `yaml/bare-object-value` accepts a `$`-reference to a localized string as a valid value where a
  literal is expected, instead of flagging it as a bare word (0.30.1).
- Regenerated language data is picked up without a restart – the freshness stamp drops the
  in-process caches when the data under the data root changes (0.30.1).
- The servers gated behind optional extras (MCP, LSP) skip cleanly on a minimal install instead of
  failing to import (0.30.1).

## 2026-07-21 – 0.25.0, 0.26.0, 0.26.1, 0.27.0

### Added

- Four linter rules: `yaml/bare-object-value` (a bare word where a quoted literal or an `=`
  binding is expected), `code/resource-bare-name` and `code/unknown-resource` (a resource by a
  bare file name that must exist in the project or the platform's image library), and
  `yaml/no-expression-in-literal` (an expression where the platform accepts only a literal)
  (0.26.0).
- Three engine rules: `yaml/ref-needs-nullable` (a reference type in a type position without `?`),
  `yaml/unknown-enum-value` (a component property value outside the ui-schema enumeration), and
  `yaml/standard-field-length` (a `Name` over 400 characters or a `Code` over 50) (0.25.0).
- A unified metamodel API – property types, enumerations and defaults through one interface; the
  linter and scaffolding resolve object schemas through it, including the properties an object has
  but the yaml leaves unset (0.27.0).

### Changed

- Scaffolding accepts the element kind spelled in any platform language (0.26.0).
- Language data comes from the compiler, not from constants: the terms dictionary covers every
  stdlib type's members, and the query-language keywords come from the parser's own dictionary
  (0.26.0).
- `code/undefined-name` also reads names inside string interpolation, so a substitution of a
  non-existent name is reported before the build (0.25.0).
- Completion follows the project's development language (0.26.1).

---

> Releases before 0.25.0 predate this changelog. The VS Code extension's
> [CHANGELOG](https://github.com/keyfire/xbsl/blob/main/editors/vscode/CHANGELOG.md) carries the
> product history back to 0.1.0.
