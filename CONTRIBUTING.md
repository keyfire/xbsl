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

The lexer and the language/type data are extracted from the platform itself (the Xtext/ANTLR
grammar and the distribution docs), not made up – stick to this principle: verify against the
primary source.

## Data for a new Element version

The data is versioned under `xbsl/data/element/<version>/`. To add a new version, take its
distribution and run the extractors – the version is detected automatically:

```sh
python tools/extract.py --dist "<path to the distribution>"   # the whole dataset
```

Vendor files from the distribution are not committed (cached under `.refs/`) – only the derived
JSON is.
