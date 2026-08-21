"""Guard: the rule metadata restated outside the registry must not drift away from it.

Four places repeat what `engine.RULES` already knows, and every one of them was kept in sync
by hand until a release caught them lying: the group descriptions in the extension claimed
"4 rules at error, 12 at warning" for `code` while the registry held 15 and 13, and `yaml`
claimed 3 errors against 4.

  * `docs/RULES.md` / `RULES.ru.md` - the rule count in the intro and a table row per rule
    (severity, default, scope) inside the tier sections; the count is repeated in both READMEs;
  * `editors/vscode/package.nls.json` / `.ru.json` - the per-level counts in the group
    descriptions shown in the VS Code settings UI;
  * `editors/vscode/package.json` - a `xbsl.groups.<group>` setting per rule group, plus the
    published version, which both CHANGELOGs must describe;
  * `editors/vscode/src/ruleDocs.ts` - which rules link to a documentation page.

The registry is read in a SUBPROCESS with XBSL_NO_PLUGINS=1 on purpose. An installed plugin
adds its own rules and rewrites the severity of built-in ones at import time, so an in-process
`len(RULES)` would depend on what is installed next to the engine: green in a public CI,
red on a machine with the internal plugin (or the other way round). Published metadata
describes the built-in set, and only a plugin-free process shows it.

The counts cover ALL rules of a group by their own severity, disabled-by-default ones
included - that is what the published sentences state.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from collections import Counter, defaultdict
from functools import lru_cache
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
DOCS = ROOT / "docs"
VSCODE = ROOT / "editors" / "vscode"

# A snapshot of the registry: no titles (they are translated) and no functions - only the
# metadata the four sources restate.
_SNAPSHOT = """
import json
import xbsl.rules  # noqa: F401  - importing the package registers the built-in rules
from xbsl.engine import RULES
print(json.dumps([
    {"id": r.id, "tier": r.tier, "scope": r.scope,
     "severity": r.severity.value, "default": r.enabled_by_default}
    for r in RULES
], ensure_ascii=False))
"""

_LEVELS = "error|warning|info|hint"


@lru_cache(maxsize=1)
def _registry() -> tuple[dict, ...]:
    env = dict(os.environ, XBSL_NO_PLUGINS="1", PYTHONIOENCODING="utf-8", PYTHONUTF8="1")
    run = subprocess.run(
        [sys.executable, "-c", _SNAPSHOT], cwd=ROOT, env=env,
        capture_output=True, text=True, encoding="utf-8",
    )
    assert run.returncode == 0, f"снимок реестра не собрался:\n{run.stderr}"
    return tuple(json.loads(run.stdout))


@lru_cache(maxsize=1)
def _by_id() -> dict[str, dict]:
    return {r["id"]: r for r in _registry()}


@lru_cache(maxsize=1)
def _levels_by_group() -> dict[str, Counter]:
    groups: dict[str, Counter] = defaultdict(Counter)
    for r in _registry():
        groups[r["id"].split("/")[0]][r["severity"]] += 1
    return dict(groups)


# --- docs/RULES.* ------------------------------------------------------------------------

# Rule ids may carry digits (encoding/utf8) - a stricter pattern silently drops such a row
# and the guard goes blind exactly where it should look.
#: The table shows the level as a Material Symbols icon and the default state as a mark - words
#: per column did not fit the page, and the column that matters ("what it checks") was the one
#: being squeezed out. The level is read from the alt text of the picture.
_ICON_DEFAULT = {"✓": "on", "–": "off"}

_ROW = re.compile(
    r"^\|\s*`([a-z0-9-]+/[a-z0-9-]+)`\s*\|\s*<svg[^>]*aria-label=\"(error|warning|info)\"[^>]*>"
    r".*?</svg>\s*\|\s*(\S+)\s*\|\s*(\S+)\s*\|(.*)\|\s*$"
)
_ANY_ROW = re.compile(r"^\|\s*`")
_TIER_HEADING = re.compile(r"^###\s+(?:Тир|Tier)\s+([A-D])")
_DOC_LINK = re.compile(r"\[(?:доки|docs)\]\((\S+?)\)")

# Every sentence in the repository stating how many rules there are, keyed by file. Each
# pattern is anchored on its own wording: a bare \d+ would match an unrelated number and
# keep the guard green while the sentence lies.
# Every place that states the number of rules in prose. The documentation site pages belong
# here as much as the READMEs: their counters had drifted to 97 and 87 unnoticed exactly
# because the guard did not look at them.
_COUNTS = {
    "docs/RULES.ru.md": re.compile(r"Сейчас правил:\s*(\d+)"),
    "docs/RULES.md": re.compile(r"Currently there are\s+(\d+)\s+rules"),
    "README.ru.md": re.compile(r"\*\*Правила\.\*\*\s*(\d+)\s+правил"),
    "README.md": re.compile(r"\*\*Rules\.\*\*\s*(\d+)\s+rules"),
    # The Russian counters accept the case endings the numeral dictates ("правило",
    # "правила", "правил") - the count must not be hostage to grammar.
    "docs/index.ru.md": re.compile(r"(\d+)\s+правил[оа]? в четырёх тирах"),
    "docs/index.md": re.compile(r"(\d+)\s+rules in four tiers"),
    # "Rules in depth" moved out of the guide when it was split by task.
    "docs/linting.ru.md": re.compile(r"Полный перечень все(?:х|го)\s+(\d+)\s+правил[оа]?"),
    "docs/linting.md": re.compile(r"The full list of all\s+(\d+)\s+rules"),
}

# Locale-specific spellings of the "Default" and "Scope" columns.
_TABLES = {
    "RULES.ru.md": {"on": "вкл", "off": "выкл", "file": "файл", "project": "проект"},
    "RULES.md": {"on": "on", "off": "off", "file": "file", "project": "project"},
}


def _parse_table(name: str) -> dict[str, dict]:
    """Rule rows of a documentation table, keyed by rule id (tier taken from the heading)."""
    rows: dict[str, dict] = {}
    tier = None
    for number, line in enumerate((DOCS / name).read_text(encoding="utf-8").splitlines(), 1):
        heading = _TIER_HEADING.match(line)
        if heading:
            tier = heading.group(1)
            continue
        match = _ROW.match(line)
        if not match:
            assert not _ANY_ROW.match(line), (
                f"{name}:{number} – строка таблицы правил не разобрана сторожем: {line!r}. "
                "Либо формат строки изменился, либо в столбцах опечатка; сторож не должен "
                "молча пропускать строки."
            )
            continue
        rule_id, severity, default, scope, tail = match.groups()
        assert default in _ICON_DEFAULT, (
            f"{name}:{number} – неизвестный значок включённости {default!r}; "
            f"допустимы {sorted(_ICON_DEFAULT)}"
        )
        link = _DOC_LINK.search(tail)
        rows[rule_id] = {
            "tier": tier,
            "severity": severity,
            "default": _ICON_DEFAULT[default],
            "scope": scope,
            "link": link.group(1) if link else None,
            "line": number,
        }
    return rows


@pytest.mark.parametrize("name", sorted(_COUNTS))
def test_stated_rule_count(name: str):
    text = (ROOT / name).read_text(encoding="utf-8")
    match = _COUNTS[name].search(text)
    assert match, f"{name}: не найдено предложение со счётчиком правил"
    stated = int(match.group(1))
    assert stated == len(_registry()), (
        f"{name}: заявлено правил {stated}, в реестре {len(_registry())} – поправьте счётчик"
    )


@pytest.mark.parametrize("name", sorted(_TABLES))
def test_docs_table_lists_every_rule(name: str):
    rows = _parse_table(name)
    missing = sorted(set(_by_id()) - set(rows))
    unknown = sorted(set(rows) - set(_by_id()))
    assert not missing, f"{name}: нет строки таблицы для правил {missing}"
    assert not unknown, (
        f"{name}: строки для несуществующих правил {unknown} – правило удалено или переименовано"
    )


@pytest.mark.parametrize("name", sorted(_TABLES))
def test_docs_table_matches_registry(name: str):
    words = _TABLES[name]
    problems = []
    for rule_id, row in sorted(_parse_table(name).items()):
        info = _by_id().get(rule_id)
        if info is None:
            continue  # reported by test_docs_table_lists_every_rule
        # Level and default state come back from the icons already normalized; the scope is
        # still a word, and that one is spelled per locale.
        expected = {
            "severity": info["severity"],
            "default": "on" if info["default"] else "off",
            "scope": words[info["scope"]],
            "tier": info["tier"],
        }
        for column, want in expected.items():
            if row[column] != want:
                problems.append(
                    f"{name}:{row['line']} {rule_id}: {column} – в таблице {row[column]!r}, "
                    f"в реестре {want!r}"
                )
    assert not problems, "таблица правил разошлась с реестром:\n" + "\n".join(problems)


# --- documentation of the rule groups -----------------------------------------------------
# Until 0.59 every group had its own xbsl.groups.<group> setting carrying a description and the
# level counters, and the guards checked those against the registry. The settings are retired - a
# group is now a key of the single xbsl.rules table - so the documentation is checked instead:
# without it there is nowhere to read about a new group.

_RULES_PAGES = ["RULES.ru.md", "RULES.md"]


@pytest.mark.parametrize("name", _RULES_PAGES)
def test_rules_page_mentions_every_group(name: str):
    text = (ROOT / "docs" / name).read_text(encoding="utf-8")
    missing = [group for group in sorted(_levels_by_group()) if f"{group}/" not in text]
    assert not missing, f"docs/{name}: группы {missing} не описаны на странице правил"


def _manifest() -> dict:
    return json.loads((VSCODE / "package.json").read_text(encoding="utf-8"))


def test_every_runtime_string_has_a_russian_translation():
    """A string shown at runtime goes through vscode.l10n.t and needs a key in the ru bundle.

    Without the key VS Code silently falls back to the English source, and a Russian editor gets
    an English panel - which is exactly what shipped with the rules panel until this guard.
    """
    bundle = json.loads((VSCODE / "l10n" / "bundle.l10n.ru.json").read_text(encoding="utf-8"))
    literal = re.compile(r'l10n\.t\(\s*"((?:[^"\\]|\\.)*)"')
    missing = []
    for path in sorted((VSCODE / "src").glob("*.ts")):
        for match in literal.finditer(path.read_text(encoding="utf-8")):
            text = json.loads('"' + match.group(1) + '"')
            if text not in bundle:
                missing.append(f"{path.name}: {text}")
    assert not missing, "нет перевода в bundle.l10n.ru.json:\n" + "\n".join(missing)


def test_settings_do_not_offer_the_retired_rule_keys():
    """The forms must not offer what the one table replaced.

    xbsl.groups.<group> and the three linter.select/enable/ignore strings said the same things in
    four syntaxes; the code still READS them, so nobody's setup breaks, but a setting shown in the
    UI is an invitation to use it - and the invitation now belongs to xbsl.rules alone.
    """
    package = _manifest()
    sections = package["contributes"]["configuration"]
    sections = [sections] if isinstance(sections, dict) else sections
    retired = {
        key
        for section in sections
        for key in section.get("properties", {})
        if key.startswith("xbsl.groups.") or key in {"xbsl.linter.select", "xbsl.linter.enable", "xbsl.linter.ignore"}
    }
    assert not retired, f"настройки расширения снова предлагают снятое: {sorted(retired)}"


def test_extension_settings_with_a_link_use_markdown():
    """A description carrying a link belongs in markdownDescription.

    In a plain `description` VS Code prints the markdown as it is, and the settings screen shows
    a raw "[Details](https://...)" instead of a link - which is exactly what shipped in 0.58.0
    for four settings.
    """
    package = _manifest()
    sections = package["contributes"]["configuration"]
    sections = [sections] if isinstance(sections, dict) else sections
    catalogs = [
        json.loads((VSCODE / name).read_text(encoding="utf-8"))
        for name in ("package.nls.json", "package.nls.ru.json")
    ]
    link = re.compile(r"\[[^\]]+\]\(https?://")

    offenders = []
    for section in sections:
        for key, entry in section.get("properties", {}).items():
            raw = entry.get("description")
            if not raw:
                continue
            found = re.fullmatch(r"%(.+)%", raw)
            texts = [c.get(found.group(1), "") for c in catalogs] if found else [raw]
            if any(link.search(text) for text in texts):
                offenders.append(key)
    assert not offenders, (
        "описание со ссылкой лежит в description – VS Code покажет сырой markdown; "
        f"перенесите в markdownDescription: {sorted(offenders)}"
    )


@pytest.mark.parametrize("name", ["CHANGELOG.ru.md", "CHANGELOG.md"])
def test_extension_version_is_described_in_changelog(name: str):
    """The published version needs its own section; 0.24.0 shipped without one and nobody saw it."""
    version = _manifest()["version"]
    text = (VSCODE / name).read_text(encoding="utf-8")
    assert re.search(rf"^##\s+{re.escape(version)}\s*$", text, re.M), (
        f"{name}: нет раздела '## {version}' – версия расширения поднята, "
        "а история изменений о ней молчит"
    )


# --- editors/vscode/src/ruleDocs.ts ------------------------------------------------------

# The predicates are a closed set of two shapes; anything else must break the guard loudly
# rather than be counted as "no coverage".
_MATCH_BODY = re.compile(r"match:\s*\(r\)\s*=>(.*?),\s*\n?\s*page:", re.S)
_EXACT = re.compile(r'r\s*===\s*"([^"]+)"')
_PREFIX = re.compile(r'r\.startsWith\("([^"]+)"\)')
_DOCS_ORIGIN = "https://1cmycloud.com/docs/help/"


@lru_cache(maxsize=1)
def _rule_docs() -> tuple[frozenset[str], frozenset[str]]:
    """(exact rule ids, group prefixes) linked to a documentation page."""
    text = (VSCODE / "src" / "ruleDocs.ts").read_text(encoding="utf-8")
    bodies = _MATCH_BODY.findall(text)
    assert bodies, "ruleDocs.ts: не найдено ни одного предиката match – формат файла изменился"
    exact, prefixes, leftovers = set(), set(), []
    for body in bodies:
        exact.update(_EXACT.findall(body))
        prefixes.update(_PREFIX.findall(body))
        rest = _PREFIX.sub("", _EXACT.sub("", body)).replace("||", "").strip()
        if rest:
            leftovers.append(rest)
    assert not leftovers, (
        "ruleDocs.ts: предикаты неизвестной формы " + repr(leftovers) + " – сторож умеет "
        'только r === "id" и r.startsWith("группа/"); научите его или верните прежнюю форму'
    )
    return frozenset(exact), frozenset(prefixes)


def _has_doc_link(rule_id: str) -> bool:
    exact, prefixes = _rule_docs()
    return rule_id in exact or any(rule_id.startswith(p) for p in prefixes)


def test_rule_docs_entries_are_known_rules():
    exact, prefixes = _rule_docs()
    unknown = sorted(rule_id for rule_id in exact if rule_id not in _by_id())
    assert not unknown, (
        f"ruleDocs.ts: ссылки для несуществующих правил {unknown} – правило переименовано "
        "или удалено, ссылка потеряна молча"
    )
    groups = set(_levels_by_group())
    stray = sorted(p for p in prefixes if p.rstrip("/") not in groups)
    assert not stray, f"ruleDocs.ts: префиксы несуществующих групп {stray}"


@pytest.mark.parametrize("name", sorted(_TABLES))
def test_docs_table_links_agree_with_extension(name: str):
    """The Docs column of the table and ruleDocs.ts are the same statement in two places.

    A rule with no documentation page is legitimate (typography, whitespace, existence checks
    over the catalog); what must not happen is the two sources disagreeing on which rules
    those are. The failure message lists the current no-link set, so adding a rule forces a
    decision instead of a silent omission.
    """
    rows = _parse_table(name)
    problems = []
    for rule_id, row in sorted(rows.items()):
        if rule_id not in _by_id():
            continue
        in_table = row["link"] is not None
        in_extension = _has_doc_link(rule_id)
        if in_table != in_extension:
            problems.append(
                f"{name}:{row['line']} {rule_id}: в таблице "
                f"{'ссылка' if in_table else 'прочерк'}, в ruleDocs.ts "
                f"{'запись есть' if in_extension else 'записи нет'}"
            )
        if in_table and not row["link"].startswith(_DOCS_ORIGIN):
            problems.append(f"{name}:{row['line']} {rule_id}: ссылка не на {_DOCS_ORIGIN}")
    without = sorted(r["id"] for r in _registry() if not _has_doc_link(r["id"]))
    assert not problems, (
        "столбец Документация разошёлся с ruleDocs.ts:\n" + "\n".join(problems)
        + f"\n\nсейчас без ссылки на доки {len(without)} правил: {', '.join(without)}"
    )


def test_table_order_matches_across_locales():
    """A rule sits in the same place in both locales, so the tables can be read side by side.

    The numbering column is gone - it cost width the "what it checks" column needed - and the
    order itself is what is left to keep in step.
    """
    ru = list(_parse_table("RULES.ru.md"))
    en = list(_parse_table("RULES.md"))
    assert ru == en, (
        "порядок правил разошёлся между локалями; первое расхождение: "
        f"{next((pair for pair in zip(en, ru) if pair[0] != pair[1]), '?')}"
    )


@pytest.mark.needs_data
def test_extension_kind_table_matches_the_platform_dictionary():
    """The English spelling of every element kind in the metadata tree comes from the platform.

    The tree recognizes an English-spelled project by this table (`ElementKind: Catalog`), so a
    wrong or stale spelling there means an empty section rather than a visible error.
    """
    from xbsl import terms

    text = (ROOT / "editors" / "vscode" / "src" / "metadataTree.ts").read_text(encoding="utf-8")
    rows = re.findall(r'\["([А-ЯЁ][^"]*)", "[^"]+", "[^"]+", "([A-Za-z]+)"\]', text)
    assert rows, "таблица видов не разобралась - изменился её формат?"
    wrong = {
        kind: (english, terms.english(kind, "types") or terms.common_english(kind))
        for kind, english in rows
        if (terms.english(kind, "types") or terms.common_english(kind)) != english
    }
    assert not wrong, f"английские написания видов разошлись со словарём платформы: {wrong}"


def test_every_tree_menu_command_is_registered_and_titled():
    """A context-menu command of the metadata tree must exist on all three sides.

    The menu entry lives in package.json and the caption in both package.nls files. Miss one and
    the user sees either a menu item that no command backs or a raw `%cmd...%` key instead of a
    caption. The handler is NOT checked here: the per-kind "Add ..." commands are registered in a
    loop, so a name-by-name search would only produce noise.
    """
    import json

    ext = ROOT / "editors" / "vscode"
    manifest = json.loads((ext / "package.json").read_text(encoding="utf-8"))
    titles = {
        lang: json.loads((ext / name).read_text(encoding="utf-8"))
        for lang, name in (("en", "package.nls.json"), ("ru", "package.nls.ru.json"))
    }
    declared = {c["command"]: c["title"] for c in manifest["contributes"]["commands"]}
    problems = []
    for entry in manifest["contributes"]["menus"].get("view/item/context", []):
        command = entry["command"]
        if not command.startswith("xbsl.metadata."):
            continue
        if command not in declared:
            problems.append(f"{command}: нет в contributes.commands")
            continue
        key = declared[command].strip("%")
        for lang, table in titles.items():
            if key not in table:
                problems.append(f"{command}: нет подписи [{lang}] для ключа {key}")
    assert not problems, "команды меню дерева рассогласованы: " + "; ".join(problems)


# --- the day sections of the toolkit changelog ---------------------------------------------

#: The section kinds a day may carry, in the order Keep a Changelog prescribes.
_SECTION_ORDER = {
    "Добавлено": 0, "Added": 0,
    "Изменено": 1, "Changed": 1,
    "Устарело": 2, "Deprecated": 2,
    "Удалено": 3, "Removed": 3,
    "Исправлено": 4, "Fixed": 4,
    "Безопасность": 5, "Security": 5,
}


def _day_sections(name: str) -> list[tuple[str, list[str]]]:
    """(day heading, its section kinds in order) for every day of the changelog."""
    days: list[tuple[str, list[str]]] = []
    for line in (ROOT / name).read_text(encoding="utf-8").splitlines():
        if line.startswith("## "):
            days.append((line[3:].strip(), []))
        elif line.startswith("### ") and days:
            days[-1][1].append(line[4:].strip())
    return days


@pytest.mark.parametrize("name", ["CHANGELOG.ru.md", "CHANGELOG.md"])
def test_a_day_carries_each_section_once(name: str):
    """One day, one section of each kind. Several releases of a day share the day's sections,
    so a second `### Added` under the same heading is an append that lost its way - it splits
    what a reader expects to see in one place (the owner caught exactly that)."""
    problems = [
        f"{day}: {kind} встречается {kinds.count(kind)} раза"
        for day, kinds in _day_sections(name)
        for kind in sorted(set(kinds))
        if kinds.count(kind) > 1
    ]
    assert not problems, f"{name}: разделы дня задвоены – " + "; ".join(problems)


@pytest.mark.parametrize("name", ["CHANGELOG.ru.md", "CHANGELOG.md"])
def test_day_sections_are_named_by_the_standard(name: str):
    """A section kind outside the standard set is a typo or an invention - both are caught
    here rather than by a reader."""
    unknown = [
        f"{day}: {kind}"
        for day, kinds in _day_sections(name)
        for kind in kinds
        if kind not in _SECTION_ORDER
    ]
    assert not unknown, f"{name}: неизвестные разделы – " + "; ".join(unknown)


def test_the_translation_provider_setting_is_the_users_choice_not_the_projects():
    """Which paid service to call is a person's decision, so the setting stops at the window.

    With a `resource` scope an opened project could name the service in its own settings file,
    and a `.vscode/settings.json` arriving with a clone would redirect the run.
    """
    properties = {}
    for section in _manifest()["contributes"]["configuration"]:
        properties.update(section["properties"])
    assert properties["xbsl.translation.provider"]["scope"] == "window"
