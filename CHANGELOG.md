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
- **`yaml/unused-component` - an interface component nothing places.** `code/unused-method`
  cannot see one in principle: its methods are called by its own yaml. A name written as the
  KEY of a dictionary is not a use; an entry point and a globally visible component are never
  judged, and the run has to cover a whole project.
- **`code/query-in-loop` - a query inside a `for` / `while` loop.** Every turn is a round trip of
  its own, so the cost of the method grows with the data and shows only under real volumes. The
  replacement is a single query over the whole set, the values of the turns passed as an array
  parameter of an `IN` condition.

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
  back empty. Met live on a translated site: a register stopped being recalculated, a page block
  and a whole navigation menu went blank at once. The literals `TRUE`, `FALSE` and `UNDEFINED`
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
