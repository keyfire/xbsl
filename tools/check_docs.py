"""Documentation guard: the site must describe what the toolkit actually has.

The reference pages name rules, tools, commands and settings by hand, and a hand-written
list drifts the moment a surface grows. That is not hypothetical: a review of the site found
a rule group missing from the settings table, eleven MCP tools described nowhere, a settings
row (`xbsl.linter.enable`) absent while being the only way to turn a disabled rule on, and a
list of creatable object classes that named eleven of the thirty-four the tree offers.

`docs/CLI.md` is the counter-example - generated from `--help` by scripts/gen-cli-docs.py, it
had not drifted in a single flag. Generating the rest is not the answer, though: the value of
the rules table and of the settings table is the prose in the last column, which no generator
can write. So the pages stay hand-written and this guard holds them to the code:

  * every rule of the base set (XBSL_NO_PLUGINS - a plugin's rules are not ours to document)
    has a row in both RULES pages, with the same severity and default state, and no page
    describes a rule that does not exist;
  * every MCP tool is named on some page other than the changelog (the changelog says what
    happened, not what the thing does);
  * every VS Code setting is named in both READMEs of the extension, and every command is
    named there by id or by its title from package.nls (a wildcard row - `xbsl.groups.*` -
    covers its family);
  * every CLI subcommand is described in both CLI pages;
  * every XBSL_* environment variable is mentioned somewhere;
  * every headline of "What is in the box" is named in the short annotations - the site
    description, the README lede, the PyPI summary - or is recorded here as one deliberately
    left out of them.

Run:

    python tools/check_docs.py            # report and exit 1 on any gap
    python tools/check_docs.py --quiet    # only the summary line

CI gates on the exit code, so a new surface is documented in the same change that adds it.
"""

from __future__ import annotations

import argparse
import ast
import json
import os
import re
import sys
from pathlib import Path

from docsguard import (
    Layout,
    PitchItem,
    box_headlines,
    front_description,
    lede,
    pitch_problems,
    pyproject_description,
    run,
    site_description,
)

ROOT = Path(__file__).resolve().parent.parent
DOCS = ROOT / "docs"
VSCODE = ROOT / "editors" / "vscode"

LAYOUT = Layout(
    root=ROOT,
    docs=DOCS,
    site_config=ROOT / "blume.config.ts",
    pyproject=ROOT / "pyproject.toml",
)

#: Pages that describe the toolkit. BACKLOG is a local note, the changelog is history.
#: A new page belongs here - otherwise what it describes reads as undocumented.
DESCRIPTIVE_PAGES = (
    "index", "GUIDE", "start", "linting", "RULES", "scaffolding", "servers",
    "platform-data", "CLI", "DESIGNER", "DOCS_PANEL", "vscode", "translation",
)


def _page(name: str) -> str:
    path = DOCS / f"{name}.md"
    return path.read_text(encoding="utf-8") if path.exists() else ""


def _pages(locale: str) -> str:
    """Every descriptive page of one locale, concatenated."""
    suffix = ".ru.md" if locale == "ru" else ".md"
    out = []
    for name in DESCRIPTIVE_PAGES:
        path = DOCS / f"{name}{suffix}"
        if path.exists():
            out.append(path.read_text(encoding="utf-8"))
    return "\n".join(out)


# --- rules --------------------------------------------------------------------------------

#: A row of a rules table: | `id` | <svg aria-label="level"> | default mark | scope | ... |
#: The words became icons when the table outgrew the page width; the level is read from the
#: aria-label, which is also what keeps the row readable in the source.
_RULE_ROW = re.compile(
    r"^\|\s*`([^`]+)`\s*\|\s*<svg[^>]*aria-label=\"(error|warning|info)\"[^>]*>.*?</svg>\s*"
    r"\|\s*(\S+)\s*\|",
    re.M,
)
_DEFAULTS = {"✓": "on", "–": "off"}


def base_rules() -> dict[str, dict[str, str]]:
    """The rules the toolkit itself ships, with no plugin in the way.

    Read from the registry rather than from `--list-rules`: the listing needs the generated
    language data, and CI has none (the data comes from a distribution, not from the repo).
    XBSL_NO_PLUGINS is set before the import - that is when plugin rules would register.
    """
    os.environ["XBSL_NO_PLUGINS"] = "1"
    sys.path.insert(0, str(ROOT))
    from xbsl.engine import RULES  # noqa: PLC0415 - after the env var and the path

    return {
        info.id: {
            "tier": info.tier,
            "default": "on" if info.enabled_by_default else "off",
            "severity": info.severity.value,
        }
        for info in RULES
    }


def check_rules(problems: list[str]) -> None:
    rules = base_rules()
    if not rules:
        problems.append("rules: `xbsl --list-rules` produced nothing - cannot check the tables")
        return
    for page in ("RULES.md", "RULES.ru.md"):
        text = (DOCS / page).read_text(encoding="utf-8")
        rows = {
            m.group(1): {
                "severity": m.group(2),
                "default": _DEFAULTS.get(m.group(3), m.group(3)),
            }
            for m in _RULE_ROW.finditer(text)
        }
        for rule_id in sorted(set(rules) - set(rows)):
            problems.append(f"{page}: rule `{rule_id}` has no row")
        for rule_id in sorted(set(rows) - set(rules)):
            problems.append(f"{page}: row for `{rule_id}`, which the engine does not have")
        for rule_id in sorted(set(rows) & set(rules)):
            row, rule = rows[rule_id], rules[rule_id]
            if row["severity"] != rule["severity"]:
                problems.append(
                    f"{page}: `{rule_id}` severity {row['severity']}, engine {rule['severity']}"
                )
            if row["default"] != rule["default"]:
                problems.append(
                    f"{page}: `{rule_id}` default {row['default']}, engine {rule['default']}"
                )


# --- MCP tools ----------------------------------------------------------------------------


def mcp_tools() -> list[str]:
    tree = ast.parse((ROOT / "xbsl" / "mcp_server.py").read_text(encoding="utf-8"))
    names = []
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for dec in node.decorator_list:
            target = dec.func if isinstance(dec, ast.Call) else dec
            if getattr(target, "attr", "") == "tool":
                names.append(node.name)
    return sorted(set(names))


def check_mcp(problems: list[str]) -> None:
    described = _pages("en") + _pages("ru")
    for tool in mcp_tools():
        if tool not in described:
            problems.append(f"MCP tool `{tool}` is described on no page")


# --- the VS Code extension ----------------------------------------------------------------


def _resolve(value: object, nls: dict[str, str]) -> str:
    if isinstance(value, dict):
        value = value.get("value", "")
    found = re.fullmatch(r"%(.+)%", str(value or ""))
    return nls.get(found.group(1), "") if found else str(value or "")


def check_extension(problems: list[str]) -> None:
    package = json.loads((VSCODE / "package.json").read_text(encoding="utf-8"))
    nls = {
        "en": json.loads((VSCODE / "package.nls.json").read_text(encoding="utf-8")),
        "ru": json.loads((VSCODE / "package.nls.ru.json").read_text(encoding="utf-8")),
    }
    readme = {
        "en": (VSCODE / "README.md").read_text(encoding="utf-8"),
        "ru": (VSCODE / "README.ru.md").read_text(encoding="utf-8"),
    }
    # The designer and the docs panel have pages of their own; a command may live there.
    extra = {
        "en": _page("DESIGNER") + _page("DOCS_PANEL"),
        "ru": (DOCS / "DESIGNER.ru.md").read_text(encoding="utf-8")
              + (DOCS / "DOCS_PANEL.ru.md").read_text(encoding="utf-8"),
    }

    sections = package["contributes"]["configuration"]
    sections = [sections] if isinstance(sections, dict) else sections
    settings = [key for section in sections for key in section.get("properties", {})]
    for locale, text in readme.items():
        for setting in settings:
            family = setting.rsplit(".", 1)[0] + ".*"
            if setting not in text and family not in text:
                problems.append(f"README.{locale}: setting `{setting}` is not described")

    hidden = {
        entry["command"]
        for entry in package["contributes"].get("menus", {}).get("commandPalette", [])
        if str(entry.get("when", "")).strip() == "false"
    }
    for command in package["contributes"]["commands"]:
        command_id = command["command"]
        if command_id in hidden:
            continue  # not offered to the user directly - it is an action of a panel
        for locale in ("en", "ru"):
            where = readme[locale] + extra[locale]
            title = _resolve(command.get("title"), nls[locale])
            title = re.sub(r"^XBSL:\s*", "", title).strip().rstrip(".")
            if command_id in where or (title and title.lower() in where.lower()):
                break
        else:
            problems.append(f"command `{command_id}` is described in neither language")


# --- the CLI and the environment ----------------------------------------------------------


def check_cli(problems: list[str]) -> None:
    source = (ROOT / "xbsl" / "cli.py").read_text(encoding="utf-8")
    subcommands = sorted(set(re.findall(r"add_parser\(\s*[\"']([a-z][a-z0-9-]+)[\"']", source)))
    for page in ("CLI.md", "CLI.ru.md"):
        text = (DOCS / page).read_text(encoding="utf-8")
        for name in subcommands:
            # `xbsl templates list` and the like are nested under their parent command.
            if not re.search(rf"`xbsl (?:\w+ )?{re.escape(name)}[`\s]", text):
                problems.append(f"{page}: subcommand `{name}` is not described")


def check_environment(problems: list[str]) -> None:
    names: set[str] = set()
    for source in (ROOT / "xbsl").rglob("*.py"):
        names |= set(re.findall(r"[\"'](XBSL_[A-Z_]+)[\"']", source.read_text(encoding="utf-8")))
    described = _pages("en") + _pages("ru")
    for name in sorted(names):
        if name not in described:
            problems.append(f"environment variable {name} is documented nowhere")


# --- the short annotations ------------------------------------------------------------------

#: A headline of "What is in the box" - the English page, the Russian page - and the word that
#: has to stand for it in the short annotations of that language. The block on the front page is
#: the full list, but a search engine, PyPI and an AI answer quote the one-liners instead, and
#: those drift on their own: `xbsl translate` shipped in August 2026 and every annotation still
#: named the six surfaces that existed before it. A row with no words is a headline deliberately
#: kept out of the one-liners - the reason belongs in a comment beside it.
PITCH_ITEMS = (
    PitchItem("Linter with autofixes", "Линтер с автоисправлениями", "linter", "линтер"),
    PitchItem("LSP server", "LSP-сервер", "LSP", "LSP"),
    PitchItem("Metadata scaffolding", "Создание метаданных", "scaffolding", "метаданных"),
    PitchItem("Translation into English spellings", "Перевод проекта на английские написания",
              "translation", "перевод"),
    PitchItem("Documentation search", "Поиск по документации", "documentation", "документаци"),
    PitchItem("MCP server", "MCP-сервер", "MCP", "MCP"),
    # The web panel is a local page a developer opens for the findings of one project, not a
    # surface anyone picks the toolkit by: it is described on the servers page and left out of
    # the annotations on purpose.
    PitchItem("Web panel", "Веб-панель", None, None),
    PitchItem("VS Code extension", "Расширение VS Code", "VS Code", "VS Code"),
)


def pitch_surfaces() -> dict[str, dict[str, str]]:
    """The short annotations by locale: what is quoted instead of the page being read."""
    return {
        # The PyPI summary is English: the card it heads carries the English README, and the
        # neighbouring packages are described in English too.
        "en": {
            "blume.config.ts": site_description(LAYOUT),
            "docs/index.md": front_description(LAYOUT, "index.md"),
            "README.md": lede(ROOT / "README.md"),
            "pyproject.toml": pyproject_description(LAYOUT),
        },
        "ru": {
            "docs/index.ru.md": front_description(LAYOUT, "index.ru.md"),
            "README.ru.md": lede(ROOT / "README.ru.md"),
        },
    }


def check_pitches(problems: list[str]) -> None:
    """The gaps between the front-page block, the table above and the annotations."""
    problems.extend(pitch_problems(
        PITCH_ITEMS,
        {"en": box_headlines(LAYOUT, "index.md", "What is in the box"),
         "ru": box_headlines(LAYOUT, "index.ru.md", "Что внутри")},
        pitch_surfaces(),
        pages={"en": "docs/index.md", "ru": "docs/index.ru.md"},
    ))


def _collect(check):
    """A check written as `check(problems)` seen as one that returns its findings.

    The engine's checks append in place - a shape older than the shared runner and not worth
    rewriting six of them for.
    """
    def wrapped():
        found: list[str] = []
        check(found)
        return found

    wrapped.__name__ = check.__name__
    return wrapped


CHECKS = tuple(_collect(check) for check in (
    check_rules, check_mcp, check_extension, check_cli, check_environment, check_pitches,
))


def problems() -> list[str]:
    """Every finding of every check - what the test suite asserts on."""
    found: list[str] = []
    for check in CHECKS:
        found.extend(check())
    return found


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--quiet", action="store_true", help="print the summary line only")
    args = parser.parse_args()
    return run(CHECKS, title="docsguard", quiet=args.quiet)


if __name__ == "__main__":
    raise SystemExit(main())
