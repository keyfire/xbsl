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
`--format text|json|codeclimate`.

`--fix` repairs the mechanical findings in place, then reports whatever is left. It trims
trailing whitespace, corrects typography characters (em dash to en dash, `…` to `...`, curly
quotes and comment guillemets to straight ones) and normalizes mixed newlines to the dominant
style. It applies unambiguous edits only, and only for rules active in the run, so
`--fix --enable typography` also pays down the em-dash and guillemets debt. Anything that needs
judgment stays where it is.

For editor integration there is `--stdin --filename NAME`: it checks a single buffer read from
stdin and runs per-file rules only. The JSON payload (`{diagnostics, summary}`) is the same one
the MCP server returns.

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

**The full list of all 194 rules of the base set** - severity, default state, scope, links to
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
in yaml with no method in the paired module. A foreign-subsystem type used without an `Import:`
entry. A `DynamicList` typed by the automatic list form that misses an attribute of its object. A
cross-component call `Components.X.Method()` that carries no visibility annotation. Environment
mismatches: `@OnServer` called from a client handler without `@AvailableFromClient`, a client
module used from an `HttpService`. Reserved names: a field or parameter named `Type` in either
language spelling, a component property named like a built-in one. Methods that nothing
references. And top-level yaml properties measured against the configuration metamodel. The
`query/` group parses `Query{ ... }` blocks and verifies the `FROM` and `JOIN` tables against the
project objects and their `TabularParts`. A block with constructs outside the supported subset -
temporary tables, unions, subqueries - is skipped whole rather than guessed.

Detailed group descriptions live in [RULES.md](/RULES): `query/` (a composite type in `IN` with
a subquery), `project/` (project properties), `naming/` (the naming standard, the `[morph]`
extra) and `style/` (code-writing conventions and the policy on turning them on and off).

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
same output language.

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
