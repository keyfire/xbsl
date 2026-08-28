# Contributing to xbsl

**English** · [Русский](CONTRIBUTING.ru.md)

Thanks for contributing. Below is the minimum needed to add a rule or update the data.

## Environment

Python 3.10+ is required. The language data is not part of the repository – generate it first
from your own 1C:Element distribution (otherwise the linter and some tests will not work):

```sh
python tools/extract.py --dist "<path to the distribution>"   # the whole dataset

pip install -e ".[dev]"     # linter + pytest + PyYAML
pytest                      # tests (data-dependent ones are skipped without data)
python -m xbsl <path>   # run over sources
```

### Checking in the editor before a release

The VS Code extension can show an engine change live without reinstalling the package:
point the `xbsl.lsp.command` setting at `tools/lsp-dev.cmd`, and the wrapper starts the
LSP server from this clone (PYTHONPATH outranks site-packages, so the clone wins from any
working directory). Reload the window after changing the setting - the status bar then
reports the clone's engine version; remove the setting and reload to return to the
installed package. The interpreter needs the `[lsp]` and `[morph]` extras.

CLI subcommands from the clone: `python -m xbsl` parses the check mode only (a subcommand
is taken for a path and lints 0 files); use
`python -c "from xbsl.cli import main; main()" list-rules`.

### Which xbsl is actually running

`python -m xbsl` from the clone puts the working directory first on `sys.path`, so the
sources silently take over from an installed wheel - a probe then passes or fails depending
on where it was started, and the defect looks intermittent. State the provenance instead of
assuming it:

```sh
python -c "import xbsl.lexer as L; print(L.__file__)"
```

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
   positives**. If a rule fires massively on existing code, make it `info` and disabled by default
   instead of forcing everyone to fix legacy code.
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
7. **If the rule judges a NAME, seed it for bilingual parity** – see below.

The lexer and the language/type data are extracted from the platform itself (the Xtext/ANTLR
grammar and the distribution docs), not made up – stick to this principle: verify against the
primary source.

### Bilingual parity: seed the rule, do not count its findings

Element identifiers are bilingual, and the tables the rules judge by are extracted from
Russian-only documentation. A rule that matches source text against such a table reads a
translated project against a vocabulary that does not contain it: it misses real defects, or
reports what the compiler accepts. Deriving the English spelling from the platform dictionaries
(`xbsl/terms.py`, `xbsl/uischema.py`) is the fix; writing a second spelling by hand is not –
a guess matches nothing, and nothing is what it silently keeps matching.

Measuring this by LINTING a translated project and comparing the counts finds only the rules
whose count moved. It is blind to a rule that fires on neither side, whether because the rule
is broken or because the project happens to carry no such construct. So the check plants its
own case instead:

```
python tools/parity_seed.py                    # every seed
python tools/parity_seed.py --rule group/name  # one rule
python tools/parity_seed.py --uncovered        # rules no seed speaks for
```

A seed is a small Russian tree plus the verdict the rule owes it – a finding, or silence. The
English twin comes from the toolkit's own translator rather than from a second fixture, so the
spelling under test is the one the toolkit really produces. The verdict names the side that is
wrong and what it did (`en-misses`, `en-invents`, and the same for `ru-`), because a table
lacking the English spelling makes a rule miss while one lacking the Russian reading makes it
invent, and the two need opposite fixes. A seed that stops planting its case reports `stale`
rather than passing quietly. `tests/test_parity_seed.py` runs the whole catalog, so seeds are
checked on every test run and not only when someone remembers the tool.

## Data for a new Element version

The data is versioned under `xbsl/data/element/<version>/`. To add a new version, take its
distribution and run the extractors – the version is detected automatically:

```sh
python tools/extract.py --dist "<path to the distribution>"   # the whole dataset
```

Vendor files from the distribution are not committed (cached under `.refs/`) – only the derived
JSON is.
