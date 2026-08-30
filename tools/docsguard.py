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

    python tools/docsguard.py            # report and exit 1 on any gap
    python tools/docsguard.py --quiet    # only the summary line

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

ROOT = Path(__file__).resolve().parent.parent
DOCS = ROOT / "docs"
VSCODE = ROOT / "editors" / "vscode"

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
PITCH_ITEMS: tuple[tuple[str, str, str | None, str | None], ...] = (
    ("Linter with autofixes", "Линтер с автоисправлениями", "linter", "линтер"),
    ("LSP server", "LSP-сервер", "LSP", "LSP"),
    ("Metadata scaffolding", "Создание метаданных", "scaffolding", "метаданных"),
    ("Translation into English spellings", "Перевод проекта на английские написания",
     "translation", "перевод"),
    ("Documentation search", "Поиск по документации", "documentation", "документаци"),
    ("MCP server", "MCP-сервер", "MCP", "MCP"),
    # The web panel is a local page a developer opens for the findings of one project, not a
    # surface anyone picks the toolkit by: it is described on the servers page and left out of
    # the annotations on purpose.
    ("Web panel", "Веб-панель", None, None),
    ("VS Code extension", "Расширение VS Code", "VS Code", "VS Code"),
)


def _box_headlines(path: Path, heading: str) -> list[str]:
    """The bold headline of every bullet of one "What is in the box" block, in page order."""
    text = path.read_text(encoding="utf-8")
    section = re.search(rf"^## {re.escape(heading)}\s*$(.*?)^## ", text, re.M | re.S)
    headlines = []
    for line in (section.group(1) if section else "").splitlines():
        found = re.match(r"- \*\*(.+?)\*\*", line)
        if not found:
            continue
        label = found.group(1)
        link = re.fullmatch(r"\[(.+?)\]\(.*\)", label)  # the headline may be a link
        headlines.append(link.group(1) if link else label)
    return headlines


def _front_description(path: Path) -> str:
    found = re.search(r'^description:\s*"(.*)"\s*$', path.read_text(encoding="utf-8"), re.M)
    return found.group(1) if found else ""


def _site_description() -> str:
    """The `description` of blume.config.ts - the meta description of every page."""
    text = (ROOT / "blume.config.ts").read_text(encoding="utf-8")
    found = re.search(r"\n  description:\s*((?:\s*\"[^\"]*\"\s*\+?)+),", text)
    return "".join(re.findall(r'"([^"]*)"', found.group(1))) if found else ""


def _lede(path: Path) -> str:
    """The first paragraph of prose of a README - the part GitHub shows above the fold."""
    skip = ("#", ">", "!", "[", "**English**", "**Documentation", "**Документация")
    for block in re.split(r"\n\s*\n", path.read_text(encoding="utf-8")):
        if block.strip() and not block.strip().startswith(skip):
            return block.strip()
    return ""


def pitch_surfaces() -> dict[str, dict[str, str]]:
    """The short annotations by locale: what is quoted instead of the page being read."""
    return {
        # The PyPI summary is English: the card it heads carries the English README, and the
        # neighbouring packages (elemctl, edt-bridge-mcp) are described in English too.
        "en": {
            "blume.config.ts": _site_description(),
            "docs/index.md": _front_description(DOCS / "index.md"),
            "README.md": _lede(ROOT / "README.md"),
            "pyproject.toml": _pyproject_description(),
        },
        "ru": {
            "docs/index.ru.md": _front_description(DOCS / "index.ru.md"),
            "README.ru.md": _lede(ROOT / "README.ru.md"),
        },
    }


def _pyproject_description() -> str:
    """The `description` of pyproject.toml - the summary line of the PyPI card."""
    text = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    found = re.search(r'^description = "(.*)"\s*$', text, re.M)
    return found.group(1) if found else ""


def pitch_problems(
    headlines: dict[str, list[str]], surfaces: dict[str, dict[str, str]]
) -> list[str]:
    """The gaps between the front-page block, the table above and the annotations."""
    problems: list[str] = []
    for locale, column, page in (("en", 0, "docs/index.md"), ("ru", 1, "docs/index.ru.md")):
        listed = headlines[locale]
        known = [item[column] for item in PITCH_ITEMS]
        for headline in listed:
            if headline not in known:
                problems.append(
                    f'{page}: "{headline}" is in no PITCH_ITEMS row - add the word that stands '
                    f"for it in the annotations, or the reason it stays out of them"
                )
        for headline in known:
            if headline not in listed:
                problems.append(f'{page}: PITCH_ITEMS names "{headline}", the page does not')

    for english, _russian, *words in PITCH_ITEMS:
        for locale, word in zip(("en", "ru"), words):
            if not word:
                continue
            for where, text in surfaces[locale].items():
                if word.lower() not in text.lower():
                    problems.append(
                        f'{where}: the short annotation says nothing about "{english}" '
                        f'(expected "{word}")'
                    )
    return problems


def check_pitches(problems: list[str]) -> None:
    headlines = {
        "en": _box_headlines(DOCS / "index.md", "What is in the box"),
        "ru": _box_headlines(DOCS / "index.ru.md", "Что внутри"),
    }
    problems.extend(pitch_problems(headlines, pitch_surfaces()))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--quiet", action="store_true", help="print the summary line only")
    args = parser.parse_args()

    problems: list[str] = []
    check_rules(problems)
    check_mcp(problems)
    check_extension(problems)
    check_cli(problems)
    check_environment(problems)
    check_pitches(problems)

    if problems and not args.quiet:
        for problem in problems:
            print(problem)
        print()
    print(
        f"docsguard: {len(problems)} gap(s)" if problems
        else "docsguard: the documentation covers every surface"
    )
    return 1 if problems else 0


if __name__ == "__main__":
    raise SystemExit(main())
