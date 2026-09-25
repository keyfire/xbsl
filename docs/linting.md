---
title: "Checking sources"
description: "Running the linter: flags, what the deeper rules rely on, the baseline for a legacy codebase, and CI."
sidebar:
  label: Checking
  order: 4
---

The default mode of the tool is checking sources. The full rule list lives on a separate page ([Rules](/RULES)); this one is about driving the run.

## CLI flags

`--list-rules`, `--where` (data root, source and versions), `--select`/`--enable`/`--ignore` (by
rule id, rule group – the part of the id before `/` – or tier letter), `--fix`,
`--baseline`/`--write-baseline`, `--element-version`, `--data-dir`, `--lang`,
`--format text|json|codeclimate`, `--summary`/`--compare`.

`--fix` repairs the mechanical findings in place, then reports whatever is left. It trims trailing
whitespace, corrects typography characters (em dash to en dash, `…` to `...`, curly quotes and
comment guillemets to straight ones, a character off the keyboard in a comment to its keyboard
spelling: `→` to `->`) and normalizes mixed newlines to the dominant style. It applies unambiguous
edits only, and only for rules active in the run, so `--fix --enable typography` also pays down the
em-dash and guillemets debt. The group holds `typography/en-dash-comment` too, so the same run turns
the en dash of a comment into a hyphen; a project that writes the en dash there adds
`--ignore typography/en-dash-comment`. Anything that needs judgment stays where it is.

Code fixes are included too: redundant casts, unused imports and local names, non-null
assertions, redundant guards and constructor literals. The sources are checked again between
passes, so each edit uses current offsets. `--fix --baseline <file>` protects the occurrences
accepted at the start of the run and never rewrites the baseline. Newly introduced lookalike
findings do not take over that protection. Edits overlapping a protected occurrence are skipped;
remaining findings are reported. At most ten passes run. `--fix` cannot be combined with
`--write-baseline` or `--prune-baseline`.

The `comment/` group judges how a comment is worded rather than which characters it holds:
`comment/subjunctive` (the particle `бы` - the finding asks for a word of condition, because
dropping the particle alone turns a hypothesis into a statement about the code),
`comment/first-person` ("we", "our" and first-person plural verbs, and the English line of a
comment that the translation dictionary keeps), `comment/emphasis-caps` (a word in capitals for
emphasis: a function word, any word the file also writes in small letters, a one-letter word
inside a sentence, a negation glued on, and the capitals of the English line of a comment in the
dictionary) and `comment/dash-condition` (a
condition written with a dash, as in "the store is not set - the main one is taken"; the finding
suggests the wording with a word of condition). The rules read the comments of
modules, element descriptions and resource files. They are off by default - on code that never
adopted the convention they fire in bulk - and a project that did turns the group on in its CI with
`--enable comment`. `--fix --enable comment/emphasis-caps` restores the case of a stressed word; the
others have no fix, the rephrase is the author's. A project that writes a hyphen in its code
comments adds `--enable typography/en-dash-comment`.

For editor integration there is `--stdin --filename NAME`: it checks a single buffer read from
stdin and runs per-file rules only. The JSON payload (`{diagnostics, summary}`) is the same one
the MCP server returns.

The summary of that payload counts the findings by rule, by file and by severity - `by_rule`,
`by_file` and `by_severity`, the last naming all three levels even at zero - so a run can be weighed
without reading its list: which rules fire, in which files, and whether an error is among them. The
MCP `lint_paths` tool carries the same keys, and with `compact` it answers with the summary, the
error-level findings whole and - while there are no more than ten findings in all - the list itself,
one line each. Past that the list gives way to the count and a word on how to read the rest.

`--summary` prints the counts instead of the findings: a row per rule with the files it reached
and its findings, and a line of totals below. `--compare FILE` prints the same on its first run
and saves the run to the file. The next run with that file prints only what changed. The table
keeps the rules whose findings moved, with their files and findings now and the number of
findings that appeared and disappeared. The changed findings follow one per line while there are
no more than ten of them. The full list of changes always stays in the file, ahead of the
findings. When nothing changed, the report is a single line. Use it to compare the findings of a
set of projects before and after a change to the rules:

```sh
xbsl demo-en --compare runs.json      # the first run saves the counts
# ...a change...
xbsl demo-en --compare runs.json
# rule                 files  findings  appeared  disappeared
# typography/ellipsis      0         0         0            1
# whitespace/trailing      1         2         1            0
# - demo-en/Acme/TasksEn/Main/TaskCard.xbsl:7:56: [typography/ellipsis] Ellipsis character U+2026 in a comment – use three dots '...'.
# + demo-en/Acme/TasksEn/Main/TaskCard.xbsl:8:49: [whitespace/trailing] Trailing whitespace at the end of the line.
# Against runs.json: 1 appeared, 1 disappeared. Findings: 4; rules with findings: 3; files with findings: 1 of 5
```

A finding is matched by the path given on the command line, the file under it, the line, the
column, the rule and the text. The paths of the two runs are paired by the folder they name, so
`demo` and its absolute path are one path. A path whose folder the other run did not check is
paired by its spelling: `xbsl demo` run from two worktrees of a repository compares the two
checkouts. A path with no pair is left out of the comparison. So is a rule that only one of the runs
selected, when the two runs got different `--select`, `--ignore` or `--enable` flags. A separate
line names each part left out and counts its findings. A run saved in another output language is
refused, because the text of every finding would differ. When the projects keep a baseline of
their own, `--no-baseline` keeps it from hiding a change. The MCP tool `lint_paths` takes the same
file in its `compare` parameter and answers with the same comparison as data.

`xbsl --index PATH` dumps a JSON index of the project to stdout instead of linting. The index
holds the objects, with their `TabularParts`, module-declared local types and the member families
for dot completion. It also holds the method declarations - annotations, the parameter list as
written, the return type and the description comment above the declaration - and the named form
components. Paths are POSIX and relative to the root, lines are 1-based. Editors use all of this
for go-to-definition and completion.

`--format codeclimate` emits a GitLab Code Quality report as Code Climate issues, with paths
relative to the current directory. Run it from the repository root and save the output as the
`codequality` artifact.

## Rules in depth

**The full list of all 253 rules of the base set** - severity, default state, scope, links to
platform documentation sections - is in [RULES.md](/RULES). On the spot it is printed by
`xbsl --list-rules`, which also counts in the rules and severity overrides of the installed
plugins. The tier overview is in the README; below is what the deeper tiers actually verify.

A rule that judges by a number prints that number. `--list-rules` narrows the same way a run
does, so you can ask about one rule on its own:

```sh
xbsl --list-rules --select code/duplicate-method-body
# D     code/duplicate-method-body     warning The method body is repeated in another file
#        parameter min-lines = 5 (default 5, env XBSL_CODE_DUPLICATE_METHOD_BODY_MIN_LINES) - ...
```

The parameter is declared where the rule uses it, so the listing cannot drift from the value the
rule works with. Every parameter can be overridden by an environment variable named after it:
`XBSL_` plus the rule id and the parameter name, with everything but letters and digits turned
into `_`. The listing prints both the value in force and the default. A value it cannot read
keeps the default and says so. A run whose parameters are off their defaults names them in its
provenance, under the `params` key of the json summary and on a line of the text summary, because
a threshold changed by the environment changes the findings. The MCP `list_rules(select=...)`
answers with the same records under `params`.

The type rules of tier D cover every type position in code - `new`, `as` casts, annotations,
signatures - and every `Type:` key in yaml, unions `A|B|?`, generics and nullable included. The
root must be a known type: stdlib, a project object, a module-declared local type or a global type
of a declared library (see below). A dotted chain rooted at a project object must stay within the
family that object generates. That family is the derived types extracted from the distribution
docs (`Reference`, `Object`, `CreateObject`, the automatic forms...), its `TabularParts` and its
module structures. Namespace-qualified references (`Catalog.X.Reference`) also check that the
object exists under that kind, and the values of project enumerations are verified both in code
and in yaml bindings.

The types of the declared libraries come from their archives. The project descriptor declares the
coordinates only - `Vendor`, `Name` and `Version` - so the names are read from the
`{Vendor}-{Name}-{Version}.xlib` archive. It is looked up in the project descriptor's directory
and above it, up to four levels, which is where the archive sits when the sources are shipped. An
element becomes known when its `VisibilityScope` is `Global`; the rest is the library's own
business. With no archive next to the sources the library types stay unknown, exactly as they were
before libraries were understood at all.

The cross-file rules of tier D catch what the compiler reports late or not at all. A `Handler:`
in yaml with no method in the paired module. A foreign-subsystem type used without an import of its
namespace - of the subsystem for an element at its root, of `Subsystem::Package` for an element of a
package, since importing a subsystem does not bring its packages. The project module is judged for
the elements of packages and of subsystem roots, and the tables of a query count as references too - of a `Query{...}`
block against the imports of the module, of the `.xbql` of a virtual table against the `Import`
section of its yaml. A full name of the project that leads to a namespace where its element does not
lie is reported with a fix. The tables of a dynamic list count as references of its yaml too, and a
partial name `Subsystem::Name` is checked against the placement of its element the way a full name
is. The joined tables of the reference input settings count as references too, and a table must be
public wherever a list or a query names it. A `DynamicList` typed by the automatic list form that misses an
attribute of its object. A cross-component call `Components.X.Method()` that carries no visibility
annotation. Environment mismatches: `@OnServer` called from a client handler without
`@AvailableFromClient`, a client module used from an `HttpService`. Reserved names: a field or
parameter named `Type` in either language spelling, a component property named like a built-in one.
Methods that nothing references; a file that does not parse still counts as a mention there, and
the translation dictionary does not. And top-level yaml properties measured against the configuration
metamodel. The `query/` group parses `Query{ ... }` blocks and verifies the `FROM` and `JOIN` tables
against the project objects and their `TabularParts`. A block with constructs outside the supported
subset - temporary tables, unions, subqueries - is skipped whole rather than guessed.

The comments are read too. The `comment/` group judges their wording, and one of its rules looks
across files: `comment/unknown-name` collects the identifiers of every module, the names of every
element description and the platform catalog, and reports a word of a comment that looks like an
identifier and that none of them knows - a method that was renamed while its mention stayed. A case
form of a known name, a line of commented-out code and a name with another system named beside it
are not reported. A system only this project knows is declared with `--other-system` in the same
CI line. The name of another product mentioned in prose with no system beside it has the same
shape, which is why the rule is off by default and a project turns it on with
`--enable comment/unknown-name`.

Several rules repeat warnings of the platform IDE, so those places show up before anyone opens the
code there, and each rule follows the condition the compiler applies. `code/unused-local` and
`code/unused-loop-var` resolve names through block scopes the way the compiler binds them. They
report a `val`, `var` or `use` the method never reads and the variable of a `for X in` loop; a local
that is only ever assigned gets a message of its own. Reads inside a closure and inside the
interpolation of a string or a query literal count. A named argument `Name = value`, a member
`.Name` and a same-named variable of a sibling block are not reads. The counter of `for X = A to B`
is not reported, as in the IDE, and neither are a `catch` variable or a parameter. An unused `use`
name is fixed by dropping it, since `use Expression` holds the resource until the end of the same
scope.

`code/lambda-changes-outer-local` walks the same block scopes and reports an error the compiler
finds only when the build is applied. A lambda body may not assign a local variable declared outside
the lambda: a `var` variable or a parameter of the method or of an outer lambda. A member or an
element of the captured value may change, and so may a variable or a parameter of the lambda itself.
A `val`, `use`, loop or catch variable is read-only everywhere and gets a compiler error of its own,
so the rule does not report it.

Five tier C rules repeat compile errors the server answers with a rolled-back build: an assignment to
itself (`code/self-assignment`), a left side that cannot hold a value (`code/assign-target`), an assignment
to a read-only name (`code/assign-readonly`), code after a statement that always ends its block
(`code/unreachable-statement`) and a `break`/`continue`/`return` with nowhere to go (`code/misplaced-jump`).
They read one file and run on every keystroke; where the verdict needs a type the file does not tell - the
receiver of `Obj.Field = ...`, the type of a value switched by `case` - they stay silent and leave the case
to the compiler.

Six more file checks cover missing initializers, required fields with defaults, resources returned
as their scope closes, repeated declarations, case values and catch types. Assignments to read-only
fields are checked through receivers whose structure or exception type is known from the same file.
Unknown receiver types and constant expressions that require evaluation remain the compiler's
responsibility. `code/statement-no-effect` reports any expression statement other than a call or
throw as an error, even if an inner expression calls a method. Assigned values and short lambda
results are consumed and remain valid.

`code/unused-import` asks whether the compiler ever looked up a type in the imported namespace. A
word of the module keeps nothing by itself: the import line, a member after a dot and a local named
like an element are not uses. A value can be one. A property of the paired yaml or the result of a
method of another subsystem brings its type along, and so does a query column; reading a member of
such a value uses the namespace of that type. Where the rule cannot follow the compiler, because a
module or a paired yaml does not parse or the declarations of an element cannot be read, it stays
silent. The fix removes the import line.

`style/constructor-literal` reports a call like `new Date("9999-12-31")` or
`new Duration(1, 30, 0, 0)`: a constructor of a type that has a literal, with constant arguments
only. `FindType` with a constant name is reported too. The compiler's condition does not look at the
value, so a string no literal can hold is a finding as well. `--fix` writes the literal where it
holds the same value, as in `Date{9999-12-31}`, `1h30m` or `True`, and leaves the call alone
otherwise. `FindType` is never rewritten: the call returns `Type?` while the literal names the type
itself, so a variable declared from the call would change its type.

Four more warnings of the platform IDE need no type of an expression. `style/boolean-ternary`
reports a ternary with `True` and `False` branches, in a module, a string interpolation or a yaml
binding; the fix writes the condition or its negation, and the negation follows the platform:
`not` covers a comparison but not `is`, `and` or `or`, so `X is T` becomes `X is not T`.
`style/redundant-scope` reports a `scope` that is the only statement of its block and removes it.
`style/redundant-union-member` drops a union member that repeats another, a second `Undefined` and a
member that `Object` or a base type of the catalog covers; a generic base covers only with the same
arguments, because the catalog does not say which type parameters accept a wider one.
`code/duplicate-import` reports a repeated `import`, the short and the full name of a namespace
counted as one, and `yaml/duplicate-import` reads the `Import` section of an element the same way,
although the IDE does not check it.

Four rules of tier D judge the type of an expression, where the rules above judge a written type.
`code/redundant-cast` reports a cast to a type the value already has, and `code/cast-to-non-null` a
cast that only drops `Undefined` and could be `!`. `code/redundant-undefined-guard` reports `??`,
`!` or `?.` over a value whose type has no `Undefined`, and `code/redundant-type-check` reports
`X is Type` whose result the types decide. A type comes from what the sources write. A declaration,
a cast or a constructor names it. A component of the paired markup has the type its declaration
gives, so `Components.Field.Value` of an `Edit<Number>` is a number. A generic member takes the
arguments of its receiver: `OnChangeEvent<String>.NewValue` is a string. A structure or a method
gets its type from the module that declares it. A row of `Query{...}` is typed by its select list
and the yaml of the tables it reads; a field through a reference and the joined side of a left join
carry `Null`, which `ReplaceNull` removes. The comparison is the compiler's, and a condition checked
earlier narrows nothing. All four read one inference: over the whole project for the cast rules and
the type check, over the module and the markup of its component for the guard, which runs on every
keystroke. What the inference cannot name is not judged: a lambda parameter without a type, a union
with an unknown part, a method whose overloads for the given arguments disagree, a column of a query
the compiler would refuse. The rules therefore miss some of the IDE's warnings and add none of their own.

`code/row-field-null` reads the same inference for the row of a query. A column that reads a field
through a reference or from the joined side of an outer join may hold `Null`, and the rule reports
where such a column goes to a structure field, a parameter of a project method, a variable or a
method result whose declared type has no `Null`; a `?` type refuses it too. A lambda of `Transform`,
`Filter` or `ForEach` gets its parameter type from the signature of the platform method, a reading
only this rule uses so far. A computed column is not judged: the compiler narrows
`CASE WHEN X IS NULL THEN ... ELSE X END` itself.

`code/deprecated-api` checks calls of deprecated platform methods. It selects overloads using the
project compatibility mode and the number, names and inferred types of arguments, and reports only
when every matching form is deprecated. Unknown types keep ambiguous calls silent. This requires a
catalog with extracted deprecation metadata; project-defined deprecated declarations are not
checked.

Detailed group descriptions live in [RULES.md](/RULES): `query/` (a composite type in `IN` with
a subquery), `project/` (project properties), `naming/` (the naming standard, the `[morph]`
extra) and `style/` (code-writing conventions and the policy on turning them on and off).

### Server calls in computed properties

Enable `code/computed-property-server-call` to inspect properties whose expressions reach
a server method. The rule groups findings by form and endpoint and includes the property
lines and complete call paths. It is informational and disabled by default: a statically
reachable server call may be intentional.

Only declared methods available from the client are reported. A client variant takes
priority over a server variant. Event handlers, deferred lambdas, ambiguous targets and
methods with enabled or unknown `CacheResult` are skipped. The rule does not predict how
often the platform evaluates a property. Consider loading the required data in advance;
caching arbitrary mutable data is not an automatic fix.

The existing `code/image-binding-server-call` still covers platform `Image` properties.
Those sites are excluded from the general rule. A project's own property named `Image`
is eligible for the general check. The image rule also accepts a server module described
only by metadata for compatibility; the general rule requires a resolved method body.

A form inherits properties from its base type, such as the `WriteAndClose` command. Both
rules read `WriteAndClose.Execute()` as a call of that property, even when a common module
has the same name. If the base type is unknown, the rules skip every `Name.Method()` call in
that form and still follow calls of the form's own methods. Both rules also skip an element
whose metadata has a field of the wrong type, such as a date in `Name`.

### Sequential server calls

Enable `code/sequential-server-calls` to find a client method that calls the server several
times in a row on one path of execution. Each call is a round trip of its own, where one server
method with a typed result would make a single one. By default the rule judges the methods an
opening handler may run: `AfterCreate`, `AfterRead` and `OnOpenByLink`, followed through the
module's own methods, client modules, `Components.X.M(...)` and timer lambdas. The `scope`
parameter set to `all` (`XBSL_CODE_SEQUENTIAL_SERVER_CALLS_SCOPE=all`) judges every client
method, and `min-calls` sets the shortest run. The check is informational and disabled by
default: a mature project gets dozens of findings, and the fix is a new composite server method.

A call counts when it reaches a client-available server method without `CacheResult = True`: a
bare call of the module's own method, `Module.Method(...)`, or a client method of another
module or of a child component whose main path calls the server before any early exit. The
module's own client methods are walked in place. A branch of `if`/`case`, the right operand of
`and`/`or`/`?:`/`??` and a loop split the path, and a loop body is not judged at all; a lambda
and a method reference run in another tick. A run inside `catch` and a run whose calls stand in
different `try` statements are skipped: such a split may be deliberate error handling.

One finding per run sits on the line of its first call and lists the calls with their lines.
When the arguments of a call are computed from the result of an earlier one, the message says
so: that computation moves to the server as well. Merging changes transaction boundaries and
error handling, so the rule suggests one server call rather than running the calls in parallel.

### Resource text read without the result cache

`code/resource-read-without-cache` looks for a method available from the client whose body is a
single `return` of `ResourcesPackage.Current().Get(...).OpenReadableStream().ReadAsString()`.
Such a method runs on the server, and without the cache each call from the client is a server
call. The text of a resource changes only with a new build. The rule suggests
`CacheResult = True` in the `@AvailableFromClient` annotation, or passing the text to the client
through a `ClientWorkParameters` element. Which one fits depends on how long the result may
live, so there is no automatic fix.

Only this shape is reported. The arguments of `Get` and `ReadAsString` must be string literals
without interpolation or parameters of the method. A member access, a call or a computed default
value can depend on the user, the settings or other data - the cache would keep an answer that
was true once - and the rule skips such a method. An operator and an interpolation are skipped
for a narrower reason. `"styles/" + FileName` and `"styles/%FileName"` look as if they read the
arguments and nothing else, and for two strings they do, but a value of another type joins a
string through `ToString()`, and the `$` form of an interpolation through `Presentation()`,
which the platform allows to depend on the locale. Both are declared on the `Object` type and a
project type may define them, so proving the path would mean proving the operand is the platform
string first. The narrowing is deliberate. The root must be the platform type: a parameter,
declaration or import of the module with that name skips the method, and so does a `Name` in the
paired description. A project element with that name turns the check off for the whole project,
and so does a global element of an attached library - the project sees it by the bare name.
Environment, availability and caching are the facts `code/computed-property-server-call` uses.
The rule also skips client variants, handlers, an enabled or unknown `CacheResult`, duplicated
methods and modules without valid metadata.

## Baseline: adopt a rule on a legacy codebase

To enable a rule over code that already violates it without drowning in old findings, freeze the
current findings into a baseline and hold only new code to the rule:

```sh
xbsl acme/app --enable style --write-baseline baseline.json   # freeze the debt once
xbsl acme/app --enable style --baseline baseline.json         # only NEW findings surface
```

A finding is identified by `(file, rule, message)` with an allowed count, so moving a line keeps
its finding suppressed while a genuinely new violation surfaces. The summary reports how many
findings the baseline suppressed and how many of its entries are now stale, meaning the debt was
paid down. That is the signal to rewrite the file. Paths are stored relative to the baseline file,
so commit it at the repository root and run the linter from anywhere.

The same file also records point exclusions with their reasons. An entry's value is either a bare
count or `{"count": N, "reason": "..."}`, where the reason says why the code is right on purpose.
Reasons come from the "Exclude the finding" lightbulb action of the
[VS Code extension](https://github.com/keyfire/xbsl/blob/main/editors/vscode/README.md#excluding-a-finding-the-baseline),
or you write them by hand. `--write-baseline` keeps the reasons of the identities that survive a
rewrite. The LSP server accepts the same `--baseline FILE` flag, so exclusions disappear in
editors too. The identity includes the message text, so write and check the baseline under the
same output language. References to source line numbers in known diagnostic templates are
excluded from the identity, so moving an accepted finding does not make it new. Names and
semantic numbers still distinguish findings; the displayed message keeps the current line
number. Existing baseline files use the same matching without being rewritten.

A new release may reword the message of a rule. An entry frozen under the earlier wording still
holds its finding when its text fits no current wording of the rule and names the same values in
the same quotes and order, in the same file. A message without such values is matched only by
its text. The run names these entries: a line in the text report, `baseline_reworded` and
`summary.baseline_reworded_entries` in json and in the MCP `lint_paths` answer. A rewrite with
`--write-baseline` brings their text up to date and keeps their reasons.

Only the entries of the rules the run actually carried count as stale. A rule left out of the set
- by a narrowing `--select`, by being off by default, by being unknown to the installed plugin -
produces no findings by construction. Calling its entries stale would declare the debt paid
without looking. Those are counted apart, as "baseline entries not checked" and the
`baseline_not_checked` key in json, and `--prune-baseline` leaves them alone.

The stale entries are named, not just counted. `--stale-baseline` lists them with path, rule,
count, message and, on a line of its own, the `reason` the entry carries. `--format json` carries
the same records in `summary.baseline_stale_entries`, and so does the MCP `lint_paths` answer.
`--prune-baseline` lists them and removes them from the file, keeping its order and format. The
file is committed, and a re-sorted rewrite is an unreadable diff. It also says how many of the
removed entries carried a reason, since after the commit that text lives on only in the git
history. The MCP side of the same act is the `baseline_prune` tool, with `dry_run` to see what
would go. Removing is never a by-product of an ordinary check. An ordinary run that counted stale
entries names both keys under its summary line, because a count with no pointer used to send
people looking by hand, rewriting the baseline and diffing the files.

`xbsl baseline add <paths> --rule <rule> [--reason ...]` freezes one finding at a time. It runs
the named rule over the given paths and appends only the findings the baseline does not cover yet.
A new file takes its sorted place, nothing else moves, recorded reasons stay, and a repeated call
changes nothing; `--format json` answers `{baseline, added, findings, written}`. The baseline is
judged only within the requested paths: entries of files outside them count as not checked rather
than stale, and `baseline_not_checked` splits into `_rules` and `_paths`. The summary names what
judged the run - `engine`, `plugins` with versions and `rules {active, total, plugin}` in json,
a "Run set" line in text - so two environments disagreeing about one tree show their difference at
once.

## Use in CI

`xbsl` exits non-zero only when a run produces an **error-severity** finding, so it works as a
pipeline gate as it is: warnings and `info` do not fail the build. The one prerequisite is the
language data (see [Language data](/start#language-data)). Generate it in the job itself - the
extractors ship with the repository, so check the repo out - or depend on a package that ships the
data via the `xbsl.data` entry point
(see [Extending](/servers#extending-your-own-rules-data-and-severities)) and just `pip install`
it.

### Locally - with the set the job runs

A job's rule set is almost never the default one: a project turns its own rules on with
`--enable` right in the pipeline. A local run knows nothing about them, so you learn the
difference from a red job, a round trip one push long.

`--as-ci` settles it. The `--select`, `--ignore` and `--enable` flags and the baseline are taken
from the `xbsl` command in the pipeline file next to the project: `.gitlab-ci.yml` or a GitHub
workflow. The file is looked up above the checked paths, or named outright as
`--as-ci path/to/file`. The agreement holds by construction, because it is the same list of rules,
with no second list to keep in step.

```sh
xbsl e1c --as-ci            # the rule set of the job
```

The run opens by saying what it took:

```
Rule set as in CI: /repo/.gitlab-ci.yml, job xbsl-lint - --enable code/unused-method, ... --baseline .xbsllint-baseline
```

Flags add up: `--as-ci --enable style/line-length` is the job's set plus the rule being tried
before it goes into the pipeline. The baseline path is resolved against the root of the checkout,
so a run started in a subdirectory opens the same file the job does. How the run is carried out -
`--jobs`, `--format`, the paths - stays its own business, because one folder is checked far more
often than the whole tree.

With no pipeline file, or no `xbsl` command in it, the run refuses with a message. It will not
quietly check a narrower set, because that silent difference is what cost the red job.

The name after the flag is the pipeline file, and the optional value is a trap worth knowing.
`xbsl --as-ci e1c` hands the flag the tree that was meant to be checked, and the run then lints
the current directory instead. A directory named there is refused with the form that works,
`xbsl e1c --as-ci` with the flag after the paths, rather than with the file system's "is a
directory".

**A pipeline is rarely one file.** GitLab's `include:` brings the jobs in from elsewhere, and a
project on a shared template keeps the lint job exactly there. Reading the root file alone once
answered "runs no xbsl command" about a pipeline that runs one. Now the local files of the
repository are followed: `include: ci/lint.yml`, `include: {local: /ci/lint.yml}`, lists of
either, and the patterns GitLab expands there (`ci/*.yml`). Include paths start at the root of the
checkout, the way GitLab starts them, and a nested include repeats that. The root is the folder
above the pipeline file that carries `.git`, so a pipeline kept in `ci/sub/lint.yml` finds
`include: /ci/base.yml` at the top of the repository. A linked worktree counts as a checkout like
any other - `git worktree add` writes `.git` as a file, and the kind is not checked. With no `.git`
above the file, say a pipeline copied into a folder of its own, that folder stands for the root.
A job defined both in the root file and in an
include is taken from the root file, the same precedence the pipeline itself has. The adopted line
then names the file the command actually stands in:

```
Rule set as in CI: /repo/.gitlab-ci.yml (include /repo/ci/lint.yml), job xbsl-lint - --enable code/unused-method
```

Everything outside the checkout is left alone: a remote URL, a GitLab template, a file of another
project, a component. That needs the network and usually a token, and a linter downloading a URL
out of a config file behind the caller's back is a surprise, not a feature. Such an include is
simply named, and a local include the checkout does not have is named the same way. So a job that
stays invisible has its reason printed next to it, and the refusal above carries the list as
well:

```
Includes left unread (they need the network or another repository): template: Jobs/SAST.gitlab-ci.yml
```

**Which job, when the pipeline runs the linter twice.** A project that builds a second tree checks
it in a second job: the sources in one, what `translate` wrote in another. The two judge by
different sets, since the translated tree has no baseline of its own and switches a rule off.
Without a name the first command wins, and the run says out loud that there was a choice:

```
The linter also runs in: English to S3 - choose one with --as-ci-job <name>
```

`--as-ci-job` takes that one, and it implies `--as-ci`, so it is enough on its own. A part of the
name is accepted while only one job fits, because a name with spaces is tedious to quote:

```sh
xbsl build/en --as-ci-job english      # the set of the "English to S3" job
```

A half that fits two jobs is refused rather than guessed, and a name the file does not have is
answered with the names it does.

**In a machine report.** With `--format json` the same answer stands in `summary.as_ci`: whether
the job's set was taken (`adopted`), which job of which file (`job`, `file`, plus `source` when an
`include:` brought the command in), the root of the checkout, the set as data (`select`, `ignore`,
`enable`, `baseline`, `no_baseline`) and as the sentence printed above it (`flags`), the jobs not
taken (`jobs`) and the includes left unread. A refusal still returns 2, and the payload carries the
reason under the same key. Such a payload has no `diagnostics` in it, because the run never
happened and an empty list of findings reads as a clean tree. The MCP `lint_paths` tool takes
`as_ci` and `as_ci_job` and answers with the same record. The editor asks for it with
`xbsl/ciStatus`.

**And in the editor.** The status bar says which set the panel judges by. While the job's set is
in force it reads `CI: <job>`; when the set was asked for and could not be taken, it shows a
warning. The server does not refuse over a missing pipeline file, because that would cost the
whole editing session, so it goes on judging by the settings. Until now the only trace of that was
one line in the output channel. The answer comes from the server itself, through the
`xbsl/ciStatus` request, rather than from the settings: the settings say what was requested, and
only the server knows what came of it. A click opens the pipeline file the job stands in.

`xbsl.linter.asCi`, with `xbsl.linter.asCiJob` for the job, makes the Problems panel judge by the
same set. The extension passes the flag, and the LSP server reads the same pipeline file. Nothing
of the rule set is copied into the settings, because a copy is the second list this whole feature
exists to avoid. The editor's own `xbsl.rules` stay on top of the job's set, so a rule being tried
out is not lost. One difference from the terminal: with no pipeline file the server does not
refuse. A refusal costs a run in the terminal and the whole session in an editor, so the server
writes the reason to the XBSL output channel and keeps the settings' set.

### GitHub Actions

```yaml
lint:
  runs-on: ubuntu-latest
  steps:
    - uses: actions/checkout@v4
    - uses: actions/setup-python@v5
      with: { python-version: "3.12" }
    - run: pip install xbsl
    # generate the data from your 1C:Element distribution (or install a package that ships it):
    - run: xbsl extract --dist "$ELEMENT_DIST"
    - run: xbsl acme/          # fails the job on any error-severity finding
```

### GitLab CI (Code Quality widget)

`--format codeclimate` writes a Code Climate report that GitLab renders inline on the merge
request. Run it from the repository root and save the output as the `codequality` report. The
command still returns non-zero on error-severity findings, so `artifacts.when: always` keeps the
report even when the job gates the pipeline. If you want the widget only, drop the gate with a
trailing `|| true`:

```yaml
lint:
  script:
    - pip install xbsl
    - xbsl --format codeclimate acme/ > gl-code-quality-report.json
  artifacts:
    when: always
    reports:
      codequality: gl-code-quality-report.json
```

### Resolved signatures and collection types

`code/call-arity` and `code/call-arity-cross` bind named arguments to a known signature,
including required parameters after optional ones. Overloads, generated manager methods
and unresolved receivers are not guessed. `code/collection-field-needs-req` also covers
non-generic platform types without a default value, while honoring scalar defaults and
local type declarations; it does not resolve bare project types across files.

`code/redundant-skip-undefined` warns only when file-level inference knows that the
collection element excludes `Undefined`. Its iterable fix calls `ToArray()` so that the
result is still a materialized array. Sequence calls have no automatic rewrite.

### Incomplete syntax and missing compile-time checks

The initializer and duplicate-declaration/branch checks preserve findings in healthy
methods when another method in the file has a parse error. A damaged method is skipped
in full; a structure with a damaged header is skipped too. Filtering does not alter the
cached syntax tree or the source offsets used by fixes.

`code/missing-return` needs project signatures and enumeration values, so it runs with
project checks. `code/captured-local-write` and `code/unused-return-value` use file facts.
The latter requires `checked_return_methods` in the extracted standard-library catalog;
old catalogs remain supported and leave that check silent. Re-extract the standard
library from the matching platform distribution to enable it.

`code/ambiguous-type` and `yaml/ambiguous-type` judge written type positions against the
project placement model. They do not infer a type from arbitrary strings or value names,
and they do not combine declarations from separate project roots.
