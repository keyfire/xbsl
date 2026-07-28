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

## 2026-07-28 – 0.47.1

### Fixed
- **The `mcp` extra is pinned below 2.** `mcp 2.0.0` (released the same day) dropped
  `mcp.server.fastmcp`, which the MCP server imports: a fresh `pip install "xbsl[mcp]"`
  picked the new major and the server refused to start. The pin keeps 1.x until the
  server moves to the new API.

## 2026-07-28 – 0.47.0

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

## 2026-07-27 – 0.46.0

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

### Fixed
- **The project-scope localization rule no longer ships whole source files between
  processes.** `code/compare-with-localized` needs the project's dictionary names before it
  can judge a module, and used to defer everything: the map phase put the source file into
  the fact and the parent re-tokenized every module of the project in the reduce. The token
  work now happens in the worker that already has the tokens, and the fact carries only the
  localized calls that stand NEXT TO a comparison - a module without comparisons contributes
  nothing at all. What travels between processes stops growing with the project, and the
  parallel run gets the time back.

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

## 2026-07-27 – 0.45.0

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

### Fixed
- **`style/boolean-compare` no longer fires where the comparison is mandatory.** The rule stood on
  tokens alone and reported every `== True`, so on a real project all of its findings were false:
  the short form does not compile ("Boolean expression is expected") as soon as the value is
  nullable or composite - a component property is `Auto|Boolean`, `HtmlContainer.GetVariable`
  returns `Boolean|JsObject|Number|String|?`, `Form.OpenInModalWindow` returns `ResultType?`. The
  operand is now typed: by the catalog for a member access or a call, by the annotation for a
  parameter or a local, and by the initializer's last link for a variable. A comparison stays a
  violation only when the type is exactly `Boolean`; what the file cannot type at all is still
  reported, because an unknown name is the usual violation the rule exists for.

### Changed
- **The type catalog keeps the full spelling of a union result type.** The extractor cut a member's
  type at the head (`Auto` instead of `Auto|Boolean`, `Boolean` instead of
  `Boolean|JsObject|Number|String|?`), so the data could not tell "a boolean" from "a value that
  may be a boolean" - 438 members in the current dataset and 359 in the previous one were stored
  short. Consumers that
  work in nominal heads are unaffected: `dataset.member_type_head` cuts the union the same way it
  always did.

## 2026-07-27 – 0.44.0

### Changed
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
- `style/redundant-type` now sees the typed empty literal: `var Articles: Array<Number> =
  <Number>[]` states the type twice, and the platform's "Idioms" article documents the short
  form (`val Articles = <Number>[]`). Only the array spelling is recognised – the empty set and
  map forms are not in the documentation, and guessing at them would risk a false positive.

## 2026-07-27 – 0.43.0

### Fixed
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

## 2026-07-27 – 0.42.1

### Fixed
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

## 2026-07-27 – 0.42.0

### Fixed
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


## 2026-07-27 – 0.41.0

### Added
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

### Added
- Rule **`code/local-method-cross-module`** (tier D, error, project-scoped; 101 rules now):
  `Module.Method(...)` must target a method that carries a visibility annotation. @Local is
  the DEFAULT visibility of a language construct, so a method with no annotation is reachable
  from its own module alone and the compiler rejects the call on build. The sibling
  `code/local-method-cross-component` covers the same invariant reached through a component
  INSTANCE (`Components.X.Method(...)`, a runtime failure); this one goes through the module
  name and resolves it by the file stem, the resolution of `code/call-arity-cross`.

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

### Fixed
- An MCP tool called with a **misspelled argument name now fails** instead of silently running
  with its defaults: pydantic ignores unknown keys, so `lint_paths(rules=...)` (the filter is
  `select`) looked like a broken parameter rather than a wrong one. Every tool model is switched
  to `extra="forbid"` after registration.

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
- `code/resource-bare-name` no longer treats an `inbase/…` reference as a folder path: a resource
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
