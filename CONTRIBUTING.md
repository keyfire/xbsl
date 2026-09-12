# Contributing to xbsl

**English** · [Русский](CONTRIBUTING.ru.md)

Thanks for contributing. Below is the minimum you need to add a rule or update the data.

## Environment

You need Python 3.10 or newer. The language data is not part of the repository, so generate it
first from your own 1C:Element distribution. Without it neither the linter nor some of the tests
will run:

```sh
python tools/extract.py --dist "<path to the distribution>"   # the whole dataset

pip install -e ".[dev]"     # linter + pytest + PyYAML
pytest                      # tests (data-dependent ones are skipped without data)
python -m xbsl <path>   # run over sources
```

### Checking in the editor before a release

The VS Code extension can show an engine change live without reinstalling the package. Point the
`xbsl.lsp.command` setting at `tools/lsp-dev.cmd`, and the wrapper starts the LSP server from this
clone. PYTHONPATH comes before site-packages, so the clone wins from any working directory.
Reload the window after changing the setting, and the status bar reports the clone's engine
version. To go back to the installed package, remove the setting and reload again. The
interpreter needs the `[lsp]` and `[morph]` extras.

CLI subcommands run differently from the clone. `python -m xbsl` parses the check mode only: it
takes a subcommand for a path and lints 0 files. Write
`python -c "from xbsl.cli import main; main()" list-rules` instead.

### Which xbsl is actually running

`python -m xbsl` from the clone puts the working directory first on `sys.path`, so the sources
silently take over from an installed wheel. A probe then passes or fails depending on where it
was started, and the defect looks intermittent. Print where the module came from instead of
assuming it:

```sh
python -c "import xbsl.lexer as L; print(L.__file__)"
```

### Starting a process

Every call that reads a process as text names `encoding="utf-8"`, and a Python child started
here gets `PYTHONIOENCODING=utf-8` in its environment. Both are required. On Windows the child
writes in the console code page, cp1251 here, while the parent decodes utf-8. The reader thread
of `subprocess` dies inside itself, `stdout` comes back `None`, and the return code stays zero.
Nothing in the output hints that the text was lost. That is how the Russian half of a
documentation page, a help text, or a traceback with a Cyrillic path disappears.
`tests/test_conventions.py` holds the repository to both rules, reading the sources with `ast`.
The reading itself lives in the shared `docsguard` package, because three repositories have the
same failure waiting. CI installs that guard from a tag, so it cannot change a verdict here
without a commit here.

## How to add a rule

1. Create a module under `xbsl/rules/` (or extend an existing one).
2. Declare a rule function and decorate it:

   ```python
   from xbsl.diagnostics import Diagnostic, Severity
   from xbsl.engine import SourceFile, rule

   @rule("group/name", "Short title", "B", severity=Severity.WARNING)
   def my_rule(source: SourceFile):
       if source.kind != "xbsl":
           return
       # ... return/yield Diagnostic(path, line, col, rule_id, severity, message)
   ```

   - `tier`: `A` structure/YAML, `B` text/conventions, `C` code, `D` semantics.
   - `scope="project"` – for cross-file rules; the function then receives `list[SourceFile]`.
   - `enabled_by_default=False` – if the rule is noisy on legacy code (enable it via `--select`).
   - Line/column positions are 1-indexed. Use `xbsl.lexer.linemap` for positions.

3. Register the module in `xbsl/rules/__init__.py` (importing it registers the rule).
4. **The project's main rule:** run it on a real project's sources and reach **zero false
   positives**. If a rule fires massively on existing code, make it `info` and disabled by
   default. Do not make everyone clean up old code for it.
5. Add a test under `tests/` (see `tests/test_rules.py` for examples).
6. Update the accompanying metadata in the same change: the row in the tables of
   `docs/RULES.md` and `docs/RULES.ru.md` (id, severity, default, scope, one-line description,
   docs link), the rule count there and in both READMEs, the entry in
   `editors/vscode/src/ruleDocs.ts` – when a platform documentation section stands behind the
   rule, the per-level counts in the group descriptions (`editors/vscode/package.nls.json` and
   `.ru.json`), and for a new group the `xbsl.groups.<group>` setting in
   `editors/vscode/package.json` as well. All of it is checked against the registry by
   `tests/test_metadata_sync.py`, so a forgotten place shows up right away instead of at the
   next extension release.
7. **If the rule checks a name, seed it for bilingual parity** – see below.

The lexer and the language and type data are extracted from the platform itself: from the Xtext
and ANTLR grammar and from the documentation of the distribution. Stick to that principle and
verify against the primary source.

### Bilingual parity: every rule gets a seed

Element identifiers are bilingual, and the tables the rules judge by are extracted from
documentation that exists in Russian only. A rule matching source text against such a table reads
a translated project against a vocabulary that does not contain it. It misses real defects, or it
reports what the compiler accepts. The fix is to derive the English spelling from the platform
dictionaries, `xbsl/terms.py` and `xbsl/uischema.py`. Writing a second spelling by hand does not
help: a guess quietly matches nothing at all.

Linting a translated project and comparing the counts finds only the rules whose count moved. A
rule that stays silent on both sides is invisible to that measurement, whether it is broken or
the project simply carries no such construct. So the check plants its own case:

```
python tools/parity_seed.py                    # every seed
python tools/parity_seed.py --quiet            # only the seeds that disagree, and the summary
python tools/parity_seed.py --rule group/name  # one rule
python tools/parity_seed.py --uncovered        # rules no seed speaks for
```

A seed is a small Russian tree plus the verdict the rule owes it: a finding, or silence. The
English twin comes from the toolkit's own translator, not from a second fixture, so the spelling
under test is the one the toolkit really produces. The verdict names the side that is wrong and
what it did: `en-misses`, `en-invents`, and the same with an `ru-` prefix. A table lacking the
English spelling makes a rule miss, while one lacking the Russian reading makes it invent, and
the two need opposite fixes. A seed that stops planting its case reports `stale` instead of
passing quietly. `tests/test_parity_seed.py` runs the whole catalog, so seeds are checked on
every test run and not only when someone remembers the tool.

A rule that matches names against the platform's tables also gets its English twin written by
hand (`english=`), spelled from `terms.json`, `uiterms.json` and the ui schema. Never guess it.
The rule is then judged on the platform's own spelling, and the translator's output becomes a
third tree. There `translator-misses` and `translator-invents` name a gap of the translator, not
of the rule, and the files it wrote differently from the hand are listed next to the verdict.
Always seed a pair, one case for the finding and one for the silence: a seed catches only the
direction it plants.

A gap you cannot close today is still worth planting. Give the seed a `known=` reason and it
reports `known (...)` instead of failing. Deleting it would delete the evidence, and the next
reader would rediscover the same thing from scratch. The note cannot hide a failure for long:
the moment such a seed starts agreeing it reports `fixed!` and fails the run, which is the signal
to delete the note.

## Data for a new Element version

The data is versioned under `xbsl/data/element/<version>/`. To add a new version, take its
distribution and run the extractors. They detect the version themselves:

```sh
python tools/extract.py --dist "<path to the distribution>"   # the whole dataset
```

Files from the distribution itself are not committed; they are cached under `.refs/`. Only the
derived JSON goes into the repository.
