#!/usr/bin/env python
"""Generate the command reference (docs/CLI.md and docs/CLI.ru.md) from the CLI itself.

The source of truth is the output of `xbsl ... --help`, so the reference cannot drift from
the implementation: add a flag, regenerate the page. Run it after changing the set of
commands or their options:

    python scripts/gen-cli-docs.py

The result is committed to the repository: the site build needs no Python.

The --help output is not pasted onto the page as is: the usage line goes into a code block
(highlighting belongs there) while the flag and command lists are parsed into tables. Raw
text in a ```text block reads as a grey wall, and bash highlighting colors random words in
it, Russian descriptions included.
"""
from __future__ import annotations

import io
import os
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# The command set comes from the module itself rather than from parsing the main help:
# the scaffolding is listed there as prose (a comma-separated list inside a group), which
# the parser cannot see.
from xbsl import cli  # noqa: E402 - imported after sys.path is adjusted

TEXT = {
    "ru": {
        "title": "Команды",
        "desc": "Справочник команд и опций xbsl: проверка исходников, серверы LSP и MCP, веб-панель, шаблоны кода.",
        "label": "Команды",
        "intro": (
            "Справочник собран из самого инструмента – это то же, что показывает "
            "`xbsl --help`, только на одной странице и целиком.\n\n"
            "Без команды `xbsl` проверяет указанные пути: это режим по умолчанию, и его опции "
            "перечислены в первом блоке. Остальные команды адресуют другие части инструментария.\n\n"
            "Язык вывода переключается флагом `--lang`, переменной `XBSL_LANG` или берётся "
            "из локали системы."
        ),
        "common": "Без команды: проверка исходников",
        "scaffold": "Скаффолдинг метаданных",
        "scaffold_intro": (
            "Команды создают и правят исходники: объекты, поля, маршруты, методы, формы, "
            "подсистемы. Каждая печатает результат в JSON и проверяет линтером то, что "
            "записала; `--dry-run` считает изменения, не трогая файлы."
        ),
        "col_opt": "Параметр",
        "col_desc": "Описание",
        "col_cmd": "Команда",
        "sections": {"options": "Параметры", "positional arguments": "Аргументы"},
    },
    "en": {
        "title": "Commands",
        "desc": "Reference of xbsl commands and options: checking sources, the LSP and MCP servers, the web panel, code templates.",
        "label": "Commands",
        "intro": (
            "This reference is generated from the tool itself – the same text "
            "`xbsl --help` prints, gathered on one page.\n\n"
            "With no command `xbsl` checks the paths you give it: that is the default mode and "
            "its options are in the first block. The other commands address the rest of the toolkit.\n\n"
            "The output language follows `--lang`, the `XBSL_LANG` variable, or the system "
            "locale."
        ),
        "common": "No command: checking sources",
        "scaffold": "Metadata scaffolding",
        "scaffold_intro": (
            "These commands create and edit sources: objects, fields, routes, methods, forms, "
            "subsystems. Each prints its result as JSON and lints what it wrote; `--dry-run` "
            "computes the changes without touching the files."
        ),
        "col_opt": "Option",
        "col_desc": "Description",
        "col_cmd": "Command",
        "sections": {"options": "Options", "positional arguments": "Arguments"},
    },
}

SECTION_RE = re.compile(
    r"^(options|positional arguments|commands|параметры|аргументы|команды)\s*:\s*$", re.I)
ENTRY_RE = re.compile(r"^\s{2,4}(\S.*?)(?:\s{2,}(.*))?$")
CHOICES_RE = re.compile(r"^\{([\w,-]+)\}$")
SUBPARSERS_RE = re.compile(r"\{([\w,-]+)\}\s*\.\.\.")
FLAG_RE = re.compile(r"(?<![\w`-])(--?[a-zA-Z][\w-]*)")


def run(args: list[str], lang: str) -> str:
    # Both variable names: XBSL_LANG wins over the legacy XBSLLINT_LANG, so setting only
    # the legacy one loses to a caller's environment (a global XBSL_LANG=ru would quietly
    # make both language versions Russian).
    env = dict(os.environ, XBSL_LANG=lang, XBSLLINT_LANG=lang, COLUMNS="100")
    # The timeout is mandatory: a command that does not parse --help starts the server
    # instead of printing help and waits on stdin - without a limit the generation hangs.
    try:
        out = subprocess.run(
            [sys.executable, "-m", "xbsllint", *args, "--help"],
            capture_output=True, text=True, encoding="utf-8", env=env, cwd=ROOT,
            timeout=30,
        )
    except subprocess.TimeoutExpired:
        return ""          # справки нет – раздел такой команды просто не появится
    return (out.stdout or out.stderr).rstrip()


def parse(help_text: str) -> dict:
    """Parse argparse output: the usage line, the description and the entry sections."""
    lines = help_text.split("\n")
    usage, i = [], 0
    while i < len(lines) and (not usage or lines[i].startswith(" ")) and lines[i].strip():
        usage.append(lines[i]); i += 1
    while i < len(lines) and not lines[i].strip():
        i += 1
    description = []
    while i < len(lines) and lines[i].strip() and not SECTION_RE.match(lines[i].strip()):
        description.append(lines[i].strip()); i += 1

    sections, current, entries, epilog = [], None, [], []
    while i < len(lines):
        line = lines[i]
        if SECTION_RE.match(line.strip()):
            if current:
                sections.append((current, entries))
            current, entries = line.strip().rstrip(":"), []
        elif not line.strip():
            # A blank line inside the epilog is a paragraph break; without it a line wrap
            # inside one paragraph would turn a single sentence into two.
            if epilog and epilog[-1]:
                epilog.append("")
        elif current:
            m = ENTRY_RE.match(line)
            if m and not line.startswith(" " * 6):
                # The indent tells a group metavar (2) from the nested commands themselves (4).
                indent = len(line) - len(line.lstrip(" "))
                entries.append([m.group(1).strip(), (m.group(2) or "").strip(), indent])
            elif not line.startswith(" "):
                # Text at zero indent is already the parser's epilog, not a wrapped description:
                # otherwise it gets glued onto the last row of the table.
                if epilog and epilog[-1]:
                    epilog[-1] += " " + line.strip()
                else:
                    epilog.append(line.strip())
            elif entries:                                  # wrapped description of the previous entry
                prev, tail = entries[-1][1], line.strip()
                # argparse wraps a long word on its hyphen (`--write-\nbaseline`); such a wrap
                # is joined without a space, otherwise a flag in the description is torn apart.
                glue = "" if prev.endswith("-") and tail[:1].isalnum() else " "
                entries[-1][1] = (prev + glue + tail).strip()
        i += 1
    if current:
        sections.append((current, entries))
    return {"usage": "\n".join(usage), "description": " ".join(description),
            "sections": sections, "epilog": epilog}


def esc(s: str) -> str:
    """An option name - it goes inside backticks, so only the pipe needs escaping."""
    return s.replace("|", "\\|")


def esc_text(s: str) -> str:
    """Ordinary text: Markdown reads angle brackets as a tag and swallows them along with
    what is inside (`xbsl <command>` becomes `xbsl`), and the theme's typography glues a
    double hyphen into a dash - a flag mentioned in a description, `--select`, turns into an
    unusable `–select`. Inside backticks neither happens."""
    s = s.replace("|", "\\|").replace("<", "&lt;").replace(">", "&gt;")
    return FLAG_RE.sub(r"`\1`", s)


def children(entries: list, i: int) -> list[int]:
    """Indices of the entries nested under entry i: a larger indent, until the group ends.

    argparse prints a group of nested commands on two levels: the metavar itself
    (`{a,b}`, or whatever `metavar` sets) with no description and a smaller indent, and
    the subcommands under it.
    """
    out = []
    for j in range(i + 1, len(entries)):
        if entries[j][2] <= entries[i][2]:
            break
        out.append(j)
    return out


def stubs(entries: list) -> set[int]:
    """Indices of the housekeeping rows: a group metavar and the description-less rows under it.

    The first is an argparse stub, the second is continued prose (under a group heading the
    command names may run on as a comma-separated list broken across lines). A table needs
    neither.
    """
    skip = set()
    for i, e in enumerate(entries):
        kids = children(entries, i) if not e[1] else []
        if not kids:
            continue
        skip.add(i)
        skip.update(j for j in kids if not entries[j][1])
    return skip


def render(help_text: str, t: dict) -> str:
    p = parse(help_text)
    out = io.StringIO()
    if p["description"]:
        out.write(esc_text(p["description"]) + "\n\n")
    out.write("```bash\n" + p["usage"] + "\n```\n\n")
    for title, entries in p["sections"]:
        if not entries:
            continue
        is_cmds = title.lower() in ("команды", "commands")
        head = t["col_cmd"] if is_cmds else t["col_opt"]
        name = t["sections"].get(title.lower(), title.capitalize())
        out.write(f"**{name}**\n\n")
        out.write(f"| {head} | {t['col_desc']} |\n|---|---|\n")
        skip = stubs(entries)
        for k, (opt, desc, _) in enumerate(entries):
            if k in skip:
                continue
            out.write(f"| `{esc(opt)}` | {esc_text(desc)} |\n")
        out.write("\n")
    for paragraph in p["epilog"]:
        if paragraph:
            out.write(esc_text(paragraph) + "\n\n")
    return out.getvalue()


def subcommands(help_text: str) -> list[str]:
    """Names of the nested commands: from a named group, or from nesting under a metavar."""
    p = parse(help_text)
    named = [e for title, entries in p["sections"] if title.lower() in ("команды", "commands")
             for e in entries]
    if named:
        return [e[0].split()[0] for e in named if re.match(r"^[a-z][\w-]*$", e[0].split()[0])]
    # A group without its own heading: the subcommands sit under the metavar at a larger
    # indent. The ellipsis in usage tells nested parsers from a positional with a choice list.
    if "..." not in p["usage"]:
        return []
    for _, entries in p["sections"]:
        for i, e in enumerate(entries):
            kids = [entries[j][0].split()[0] for j in children(entries, i)] if not e[1] else []
            named = [n for n in kids if re.match(r"^[a-z][\w-]*$", n)]
            if named:
                return named
    return []


def section(out: io.StringIO, name: str, lang: str, t: dict, level: str = "##") -> None:
    cmd_help = run([name], lang)
    # A command without its own parser answers --help with the main text: its section would
    # be a copy of the top of the page, and the parser would find the whole command list in it
    # again (that is where sections like "xbsl lint lint" came from). The servers run as their
    # own entry points, so their usage carries a hyphen: xbsl-lsp.
    first = cmd_help.splitlines()[0] if cmd_help.strip() else ""
    if f"xbsl {name}" not in first and f"xbsl-{name}" not in first:
        return
    out.write(f"{level} `xbsl {name}`\n\n" + render(cmd_help, t))
    for sub in subcommands(cmd_help):
        out.write(f"{level}# `xbsl {name} {sub}`\n\n" + render(run([name, sub], lang), t))


def page(lang: str) -> str:
    t = TEXT[lang]
    root_help = run([], lang)
    out = io.StringIO()
    out.write(
        f'---\ntitle: "{t["title"]}"\ndescription: "{t["desc"]}"\n'
        f'sidebar:\n  label: {t["label"]}\n  order: 3\n---\n\n'
    )
    out.write("<!-- Собрано из вывода `xbsl --help` скриптом scripts/gen-cli-docs.py. "
              "Не редактировать вручную. -->\n\n")
    out.write(t["intro"] + "\n\n")
    out.write(f"## {t['common']}\n\n" + render(root_help, t))
    for name in (*cli._SERVER_COMMANDS, "templates", "self-update"):
        section(out, name, lang, t)
    out.write(f"## {t['scaffold']}\n\n{t['scaffold_intro']}\n\n")
    for name in cli._META_COMMANDS:
        section(out, name, lang, t, level="###")
    return out.getvalue()


def generate() -> dict[str, str]:
    """File name -> page text; assembly without writing to disk (tests need this)."""
    return {fname: page(lang) for lang, fname in (("en", "CLI.md"), ("ru", "CLI.ru.md"))}


def main() -> None:
    for fname, text in generate().items():
        (ROOT / "docs" / fname).write_text(text, encoding="utf-8", newline="")
        print(f"{fname}: {len(text.splitlines())} строк")


if __name__ == "__main__":
    main()
