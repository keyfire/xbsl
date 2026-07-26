"""The command reference (docs/CLI*.md) and its generator.

Defects that lived on the finished pages at the same time and were only caught by
proof-reading: arguments with no help at all, English argparse strings on the Russian
page, sections lost by the parsing (the scaffolding is listed as prose in the main help),
`xbsl mcp --help` starting the server instead of printing help, and a page that quietly
goes stale after a flag is edited. Each defect class keeps its own test.
"""

from __future__ import annotations

import argparse
import importlib.util
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

from xbsl import cli, i18n

ROOT = Path(__file__).resolve().parent.parent
DOCS = ROOT / "docs"

CYRILLIC_RE = re.compile(r"[А-Яа-яЁё]")
# The one legitimate Latin-only help shape on the Russian page: a comma-separated list of
# literal values (form-edit operations, object kinds) - the values ARE the documentation.
LITERAL_LIST_RE = re.compile(r"[a-z][\w-]*(?:,\s*[a-z][\w-]*)*")


def walk(parser: argparse.ArgumentParser, path: str):
    yield path, parser
    for action in parser._actions:
        if isinstance(action, argparse._SubParsersAction):
            for name, sub in action.choices.items():
                yield from walk(sub, f"{path} {name}")


def parsers():
    """(command path, parser) for every argparse tree the CLI dispatches to."""
    yield from walk(cli.build_parser(), "xbsl")
    yield from walk(cli._templates_parser(), "xbsl templates")
    yield from walk(cli._scaffold_parser(), "xbsl <scaffold>")
    yield from walk(cli._selfupdate_parser(), "xbsl self-update")


def actions_with_help(parser: argparse.ArgumentParser):
    """Help entries of one parser: arguments and subcommand list items alike."""
    for action in parser._actions:
        if action.help == argparse.SUPPRESS:
            continue
        if isinstance(action, argparse._SubParsersAction):
            for choice in action._choices_actions:
                yield choice.dest, choice.help
        else:
            yield action.dest, action.help


def test_every_argument_has_help():
    # 42 arguments once carried no help at all - an empty cell in the reference table
    for path, parser in parsers():
        for dest, help_text in actions_with_help(parser):
            assert help_text and help_text.strip(), f"{path}: argument {dest} has no help"


def test_russian_help_is_russian():
    # built-in argparse strings (-h, group titles) arrive in English unless translated
    i18n.set_lang("ru")
    try:
        for path, parser in parsers():
            for dest, help_text in actions_with_help(parser):
                text = (help_text or "").strip()
                if LITERAL_LIST_RE.fullmatch(text):
                    continue  # a list of literal values documents itself
                assert CYRILLIC_RE.search(text), (
                    f"{path}: {dest} is not Russian in the ru build: {text!r}"
                )
    finally:
        i18n.set_lang("ru")


def test_parser_shapes_match_between_languages():
    # a language switches texts, never the set of commands and arguments
    def shape() -> dict[str, list[str]]:
        return {p: [d for d, _ in actions_with_help(parser)] for p, parser in parsers()}

    i18n.set_lang("en")
    try:
        english = shape()
    finally:
        i18n.set_lang("ru")
    assert shape() == english


def command_sections() -> set[str]:
    """The sections both pages must carry: servers, templates, self-update, scaffolding."""
    return {f"xbsl {name}" for name in (*cli._SERVER_COMMANDS, "templates", "self-update",
                                        *cli._META_COMMANDS)}


def page_sections(fname: str) -> set[str]:
    text = (DOCS / fname).read_text(encoding="utf-8")
    return {m.group(1) for m in re.finditer(r"^#{2,3} `(xbsl[^`]*)`", text, re.M)}


def test_pages_cover_every_command():
    # the scaffolding is prose in the main help, so parsing it found 3 sections of 20 -
    # the command set must come from the module, and every command must have its section
    for fname in ("CLI.md", "CLI.ru.md"):
        sections = page_sections(fname)
        missing = {
            s for s in command_sections()
            if s not in sections and not any(p.startswith(s + " ") for p in sections)
        }
        assert not missing, f"{fname}: sections missing for {sorted(missing)}"


def test_page_sections_match_between_languages():
    assert page_sections("CLI.md") == page_sections("CLI.ru.md")


# The server commands dispatch to entry points with optional dependencies (extras mcp/lsp);
# without those installed --help cannot answer, which is a fact of the minimal install, not
# a hang. The public CI installs [dev] only - skip what cannot run there.
_SERVER_DEPS = {("mcp",): "mcp", ("lsp",): "pygls"}


@pytest.mark.parametrize(
    "command",
    [(), ("mcp",), ("lsp",), ("web",), ("templates",), ("self-update",), ("new-object",)],
)
def test_help_answers_within_timeout(command):
    # `xbsl mcp --help` used to start the MCP server and wait on stdin instead of answering
    dep = _SERVER_DEPS.get(tuple(command))
    if dep and importlib.util.find_spec(dep) is None:
        pytest.skip(f"optional dependency {dep} is not installed")
    out = subprocess.run(
        [sys.executable, "-m", "xbsllint", *command, "--help"],
        capture_output=True, text=True, encoding="utf-8", timeout=30,
        cwd=ROOT, env=dict(os.environ, XBSL_LANG="ru", COLUMNS="100"),
    )
    assert out.returncode == 0 and (out.stdout or "").strip()


@pytest.fixture(scope="module")
def generator():
    spec = importlib.util.spec_from_file_location(
        "gen_cli_docs", ROOT / "scripts" / "gen-cli-docs.py"
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.mark.needs_data
def test_committed_pages_are_current(generator):
    # the generator is the source of truth; a mismatch means the committed page went
    # stale after a flag was edited. The canonical pages are generated WITH the Element
    # data (parts of the scaffolding help come from it), so a data-less clone must skip
    # rather than compare against a poorer rendering.
    for fname, text in generator.generate().items():
        committed = (DOCS / fname).read_text(encoding="utf-8")
        assert committed == text, f"{fname} is stale: rerun python scripts/gen-cli-docs.py"
