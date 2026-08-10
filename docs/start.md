---
title: "Quick start"
description: "Install the toolkit, generate the language data from your 1C:Element distribution and get the first check running."
sidebar:
  label: Quick start
  order: 3
---

What it takes to get the linter answering on your sources: the package, the language data generated from your own distribution, and the language of the output.

## How the pieces fit

One engine, reached three ways: the editor talks to a long-living server, an agent calls the same
operations as MCP tools, and the terminal runs the CLI. The sources on disk are what all three read
and write.

![The whole path: the installation sources on top - Open VSX with the extension, PyPI with the engine and elemctl, the platform distribution that hands the reference and the types to the engine and the debug adapter to elemctl; below, the editor and the engine read the project sources while elemctl carries the deploy and the debugging to the platform stand](https://raw.githubusercontent.com/keyfire/xbsl/main/editors/vscode/images/install-to-debug.svg)

The rest of this page is about getting there: the package, the data, the language of the output.

## Installation details

```sh
pip install xbsl            # or, from a clone: pip install -e .
xbsl path/to/sources        # or: python -m xbsl path/to/sources
xbsl self-update            # upgrade to the latest PyPI version
```

`self-update` upgrades the package by unpacking the wheel straight into site-packages – safe
even when `pip install --upgrade` fails with WinError 32 because an exe is busy (the typical
case: `xbsl-lsp.exe` held by the VS Code LSP server, `xbsl-mcp.exe` by an agent's MCP
session). The busy stubs are left alone and pick up the new code on the next start; restart
the long-living processes after the update. `--version X.Y.Z` installs a specific version.
In an editable install from a clone the command refuses – `git pull` updates that one.

The hot modules (the lexer and the parser) can be compiled by mypyc into C extensions:
`XBSL_MYPYC=1` at build time (needs mypy and a C compiler: MSVC Build Tools on Windows,
Xcode CLT on macOS, gcc on Linux). Users never need a compiler: the ready-made native
wheels are built by CI (`native-wheels.yml`), and without a matching wheel the package
runs as plain Python – no compiler, no loss of functionality.

## Language data

The linter relies on language tables (bilingual keywords, operators), an stdlib type catalog, and
the configuration metamodel (element properties). XBSL is built on Eclipse Xtext + ANTLR; these are
extracted from **your** 1C:Element distribution (the `InternalBsl.g` grammar, the documentation, and
the `.xcore` metamodel) and are NOT bundled in this repository. Generate them locally:

```sh
xbsl extract --dist "<path to the 1C:Element distribution>"      # the whole dataset in one go
xbsl extract --dist ... --only stdlib,terms                      # a subset of the steps
xbsl extract --dist ... --skip docs                              # docs builds a large index
```

The command runs the six extractors in dependency order (uischema reads what docs produces);
from a repository clone the same entry points are `python tools/extract.py` and the individual
`tools/extract_<step>.py`. The extractors auto-detect the platform version and place the data
under `xbsl/data/element/<version>/` (this folder is gitignored). Without the data, the linter
and the tests will tell you to generate it. Pass `--data-dir` (or set `XBSL_DATA_DIR`) to write
the data somewhere else – for instance into a private package that ships it, see
[Extending](/servers#extending-your-own-rules-data-and-severities).

## Output language

Rule titles and diagnostic messages come in Russian and English. The language is picked by
`--lang ru|en` > the `XBSL_LANG` env var > the system locale > Russian. Type names, keywords
and other XBSL text inside a message are never translated – only the wording around them. The MCP
server and the web panel follow the same setting (the web panel also has an in-page RU/EN toggle).
