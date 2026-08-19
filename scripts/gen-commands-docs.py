#!/usr/bin/env python
"""Generate the command reference of the extension README from package.json.

The prose sections describe what a feature is for; the command list is the opposite - pure
machine content (id, title, where it is invoked from), and a hand-written one drifts on every
release. It did: a review found 59 of the 110 commands named nowhere.

So the list is generated between the markers in editors/vscode/README.md (+ .ru.md):

    <!-- commands:start -->  ... generated table ...  <!-- commands:end -->

Titles come from package.nls.json / package.nls.ru.json - the very strings the Command Palette
shows, so the reference cannot disagree with the UI. Run after changing the command set:

    python scripts/gen-commands-docs.py

Then `npm run sync:docs` to carry the change onto the site page. tools/docsguard.py gates on
the result.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
VSCODE = ROOT / "editors" / "vscode"

START = "<!-- commands:start -->"
END = "<!-- commands:end -->"

#: Groups in the order they are shown; a command lands in the first group whose prefix matches.
GROUPS: list[tuple[str, tuple[str, ...], dict[str, str]]] = [
    ("project", ("xbsl.project.", "xbsl.lintProject", "xbsl.restartLinter", "xbsl.deploy",
                 "xbsl.checkForUpdate", "xbsl.choosePalette", "xbsl.goToDefinition",
                 "xbsl.forms.search", "xbsl.previewForm", "xbsl.openFormForModule"),
     {"en": "Project-wide", "ru": "По проекту"}),
    ("templates", ("xbsl.templates.",),
     {"en": "Code templates", "ru": "Шаблоны кода"}),
    ("metadata", ("xbsl.metadata.addObject.",),
     {"en": "Metadata tree: creating objects", "ru": "Дерево метаданных: создание объектов"}),
    ("metadata-rest", ("xbsl.metadata.",),
     {"en": "Metadata tree: the rest", "ru": "Дерево метаданных: остальное"}),
    ("form", ("xbsl.formStructure.", "xbsl.formPalette.", "xbsl.formData."),
     {"en": "Form designer", "ru": "Конструктор форм"}),
    ("docs", ("xbsl.docs.",),
     {"en": "Documentation", "ru": "Документация"}),
]

HEADERS = {
    "en": ("| Command | Id | Invoked from |", "| --- | --- | --- |"),
    "ru": ("| Команда | Идентификатор | Откуда вызывается |", "| --- | --- | --- |"),
}
WHERE = {
    "en": {"palette": "Command Palette", "menu": "panel / context menu"},
    "ru": {"palette": "палитра команд", "menu": "панель / контекстное меню"},
}
INTRO = {
    "en": "Every command of the extension. Generated from `package.json` – do not edit by hand.",
    "ru": "Все команды расширения. Собрано из `package.json` – не редактируйте вручную.",
}


def resolve(value: object, nls: dict[str, str]) -> str:
    if isinstance(value, dict):
        value = value.get("value", "")
    found = re.fullmatch(r"%(.+)%", str(value or ""))
    return nls.get(found.group(1), "") if found else str(value or "")


def build(locale: str) -> str:
    package = json.loads((VSCODE / "package.json").read_text(encoding="utf-8"))
    nls_file = "package.nls.json" if locale == "en" else f"package.nls.{locale}.json"
    nls = json.loads((VSCODE / nls_file).read_text(encoding="utf-8"))
    hidden = {
        entry["command"]
        for entry in package["contributes"].get("menus", {}).get("commandPalette", [])
        if str(entry.get("when", "")).strip() == "false"
    }

    buckets: dict[str, list[tuple[str, str, str]]] = {key: [] for key, _, _ in GROUPS}
    for command in package["contributes"]["commands"]:
        command_id = command["command"]
        title = resolve(command.get("title"), nls) or command_id
        where = WHERE[locale]["menu" if command_id in hidden else "palette"]
        for key, prefixes, _ in GROUPS:
            if command_id.startswith(prefixes):
                buckets[key].append((title, command_id, where))
                break

    head, rule = HEADERS[locale]
    out = [INTRO[locale], ""]
    for key, _, names in GROUPS:
        rows = buckets[key]
        if not rows:
            continue
        out += [f"**{names[locale]}**", "", head, rule]
        out += [f"| {title} | `{cid}` | {where} |" for title, cid, where in rows]
        out.append("")
    return "\n".join(out).rstrip()


for locale, name in (("en", "README.md"), ("ru", "README.ru.md")):
    path = VSCODE / name
    text = path.read_text(encoding="utf-8")
    if START not in text or END not in text:
        raise SystemExit(f"{name}: markers {START} / {END} not found")
    head, rest = text.split(START, 1)
    _, tail = rest.split(END, 1)
    # newline="" - keep the file's own line endings instead of translating \n to os.linesep
    # (a Windows run would otherwise rewrite every line of the file as a CRLF change).
    path.write_text(
        f"{head}{START}\n\n{build(locale)}\n\n{END}{tail}", encoding="utf-8", newline=""
    )
    print(f"generated the command table in editors/vscode/{name}")
