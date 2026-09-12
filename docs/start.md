---
title: "Quick start"
description: "Install the toolkit, generate the language data from your 1C:Element distribution and get the first check running."
sidebar:
  label: Quick start
  order: 3
---

What it takes to get the linter answering on your sources: the package, the language data generated from your own distribution, and the language of the output.

## How the pieces fit

One engine, reached three ways. An editor keeps a long-living server open. An agent calls the same
operations as MCP tools. A terminal runs the CLI. All three read and write the same sources on
disk.

![The whole path: the installation sources on top - Open VSX with the extension, PyPI with the engine and elemctl, the platform distribution that hands the reference and the types to the engine and the debug adapter to elemctl; below, the editor and the engine read the project sources while elemctl carries the deploy and the debugging to the platform stand](https://raw.githubusercontent.com/keyfire/xbsl/main/editors/vscode/images/install-to-debug.svg)

The rest of this page is about getting there: the package, the data, the language of the output.

## Installation details

```sh
pip install xbsl            # or, from a clone: pip install -e .
xbsl path/to/sources        # or: python -m xbsl path/to/sources
xbsl self-update            # upgrade to the latest PyPI version
```

`self-update` unpacks the new wheel straight into site-packages. That works even when
`pip install --upgrade` fails with WinError 32 over a busy exe. Usually the busy one is
`xbsl-lsp.exe`, held by the VS Code LSP server, or `xbsl-mcp.exe`, held by an agent. The command
leaves busy stubs alone, and they call the new code the next time they start. Restart the
long-living processes yourself after the update. `--version X.Y.Z` installs a specific version.
In an editable install from a clone the command refuses: `git pull` updates that one.

The lexer and the parser are the hot modules, and mypyc can compile them into C extensions. Set
`XBSL_MYPYC=1` at build time; you need mypy and a C compiler for that, which means MSVC Build
Tools on Windows, Xcode CLT on macOS, gcc on Linux. Users never need a compiler. CI builds the
native wheels (`native-wheels.yml`), and where no wheel matches, the package runs as plain
Python. Nothing is lost but speed.

## Language data

The linter judges by the language tables (bilingual keywords, operators), an stdlib type catalog
and the configuration metamodel with the properties of each element. XBSL is built on Eclipse
Xtext and ANTLR, and all of that comes out of **your** 1C:Element distribution: the
`InternalBsl.g` grammar, the documentation and the `.xcore` metamodel. None of it is bundled in
this repository, so generate it locally:

```sh
xbsl extract --dist "<path to the 1C:Element distribution>"      # the whole dataset in one go
xbsl extract --dist ... --only stdlib,terms                      # a subset of the steps
xbsl extract --dist ... --skip docs                              # docs builds a large index
```

The command runs the six extractors in dependency order: uischema reads what the docs step
produced. From a repository clone the same entry points are `python tools/extract.py` and the
individual `tools/extract_<step>.py`. The extractors detect the platform version themselves and
place the data under `xbsl/data/element/<version>/`, a folder listed in `.gitignore`. Without the
data the linter and the tests will tell you to generate it. To write the data elsewhere, pass
`--data-dir` or set `XBSL_DATA_DIR` – for instance into a private package that ships it, see
[Extending](/servers#extending-your-own-rules-data-and-severities).

## Output language

Rule titles and diagnostic messages come in Russian and English. The language is picked in this
order: the `--lang ru|en` flag, then the `XBSL_LANG` environment variable, then the system locale,
otherwise Russian. Type names, keywords and other XBSL text inside a message stay as they are;
only the wording around them is translated. The MCP server and the web panel follow the same
setting, and the web panel adds an RU/EN toggle on the page itself.
