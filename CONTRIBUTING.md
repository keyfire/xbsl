# Contributing to xbsl

**English** · [Русский](CONTRIBUTING.ru.md)

Thanks for contributing. Below is the minimum needed to add a rule or update the data.

## Environment

Python 3.10+ is required. The language data is not part of the repository – generate it first
from your own 1C:Element distribution (otherwise the linter and some tests will not work):

```sh
python tools/extract_grammar.py   --dist "<path to the distribution>"
python tools/extract_stdlib.py    --dist "<path to the distribution>"
python tools/extract_metamodel.py --dist "<path to the distribution>"
python tools/extract_terms.py     --dist "<path to the distribution>"

pip install -e ".[dev]"     # linter + pytest + PyYAML
pytest                      # tests (data-dependent ones are skipped without data)
python -m xbsl <path>   # run over sources
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

The lexer and the language/type data are extracted from the platform itself (the Xtext/ANTLR
grammar and the distribution docs), not made up – stick to this principle: verify against the
primary source.

## Data for a new Element version

The data is versioned under `xbsl/data/element/<version>/`. To add a new version, take its
distribution and run the extractors – the version is detected automatically:

```sh
python tools/extract_grammar.py   --dist "<path to the distribution>"
python tools/extract_stdlib.py    --dist "<path to the distribution>"
python tools/extract_metamodel.py --dist "<path to the distribution>"
python tools/extract_terms.py     --dist "<path to the distribution>"
```

Vendor files from the distribution are not committed (cached under `.refs/`) – only the derived
JSON is.
