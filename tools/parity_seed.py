"""Seeded bilingual parity: plant a case in a Russian tree and demand the same verdict in English.

1C:Element is bilingual down to the identifiers, and the tables the rules judge by are
extracted from Russian-only documentation. A rule that matches source text against such a
table is blind on a translated project unless it derives the English spelling - what the
compiler accepts comes back as a finding, or a real defect goes unreported.

The measurement used so far was a COUNTING DIFF: lint the translated tree of a real project,
lint the Russian one, compare file by file. It finds a rule whose count moved, and it is blind
to a rule whose count is zero on both sides - either because the project happens to carry no
such construct, or because the rule fires on neither spelling. `structure/xbsl-pair` lived in
exactly that shadow: every English module of a generated type except the object module was
reported, and the diff saw nothing, because the measured English tree carries object modules
alone.

So this tool does not measure a project. It SEEDS one. A seed is a small Russian tree plus the
verdict the rule owes it - a finding, or silence. The English twin is not written by hand: the
seed is run through the project's own translator, the same path the real translated tree came
from, so the English spelling under test is the one the toolkit actually produces. Then the
rule runs on both trees and the two verdicts have to agree:

    ok           both trees answer as the seed says
    en-misses    the English tree stays silent where the seed plants a violation
    en-invents   the English tree reports where the seed plants legal code
    ru-misses    the same, on the Russian side
    ru-invents   the same, on the Russian side
    stale        NEITHER tree answers as the seed says - the seed no longer describes the
                 rule, and it is the catalog that needs the fix, not the engine

The verdict names the side that is wrong and what it did, because the two failures need
opposite fixes: a table that lacks the English spelling makes the rule miss, and one that
lacks the Russian reading of an English construct makes it invent.

A gap that cannot be closed today is still planted, with `known=` naming the reason: deleting
the seed would delete the evidence, and the next reader would rediscover the same thing from
scratch. Such a seed reports `known (...)` and does not fail the run - but the moment it
starts AGREEING it reports `fixed!` and fails, so a closed gap cannot keep a stale excuse.

Usage:

    python tools/parity_seed.py                  # every seed
    python tools/parity_seed.py --rule structure/xbsl-pair
    python tools/parity_seed.py --uncovered      # rules no seed speaks for
    python tools/parity_seed.py --json

Exit code 1 when any seed disagrees - the check is meant to be gateable.
"""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from xbsl import engine  # noqa: E402
import xbsl.rules  # noqa: F401,E402  - registers every rule
from xbsl.translation.dictionary import Dictionary  # noqa: E402
from xbsl.translation.project import translate_project  # noqa: E402

FINDING = "finding"
CLEAN = "clean"


@dataclass
class Seed:
    """One planted case: a Russian tree and the verdict the rule owes it in BOTH spellings."""

    rule: str
    #: What the rule must answer. FINDING - the seed is a violation and has to be reported;
    #: CLEAN - the seed is legal code and has to pass. Both directions are needed: a
    #: Russian-only table makes a rule miss a violation on one project and invent one on the
    #: next, and a seed can only catch the direction it plants.
    expect: str
    #: Why the seed exists - printed next to a disagreement, so the reader learns what broke
    #: rather than which fixture failed.
    note: str
    files: dict[str, str]
    #: The project names the translator needs. Platform names come from the shipped
    #: dictionaries; only the names this seed invents belong here.
    tokens: dict[str, str] = field(default_factory=dict)
    #: Why this disagreement is KNOWN and accepted for now. A gap that cannot be closed
    #: today is still worth planting: deleting the seed would delete the evidence, and the
    #: next reader would rediscover the same thing from scratch. A seed carrying a reason
    #: does not fail the run - but if it starts AGREEING, the run says so loudly, because
    #: that means the gap closed and this note is now a lie.
    known: str = ""


_REGISTER_RU = """\
ВидЭлемента: РегистрСведений
Ид: 1d1f5c60-0000-4000-8000-000000000f01
Имя: Цены
ОбластьВидимости: ВПроекте
"""
_CATALOG_RU = """\
ВидЭлемента: Справочник
Ид: 1d1f5c60-0000-4000-8000-000000000f02
Имя: Заявки
ОбластьВидимости: ВПроекте
"""

SEEDS: list[Seed] = [
    Seed(
        rule="structure/xbsl-pair",
        expect=CLEAN,
        note="a module extending a generated type is described by the element's own yaml",
        files={
            "Цены.yaml": _REGISTER_RU,
            "Цены.НаборЗаписей.xbsl": "метод Проба()\n;\n",
        },
        tokens={"Цены": "Prices", "Проба": "Probe"},
    ),
    Seed(
        rule="structure/xbsl-pair",
        expect=FINDING,
        note="a module whose tail is no generated type has no descriptor and is reported",
        files={
            "Цены.yaml": _REGISTER_RU,
            "Цены.Ерунда.xbsl": "метод Проба()\n;\n",
        },
        tokens={"Цены": "Prices", "Ерунда": "Nonsense", "Проба": "Probe"},
    ),
    Seed(
        rule="code/unknown-object-type",
        expect=CLEAN,
        note="a derived type of the kind that generates it",
        files={
            "Цены.yaml": _REGISTER_RU,
            "Цены.xbsl": "метод Проба(Ключ: Цены.КлючЗаписи)\n;\n",
        },
        tokens={"Цены": "Prices", "Проба": "Probe", "Ключ": "Key"},
    ),
    Seed(
        rule="code/unknown-object-type",
        expect=FINDING,
        note="a derived type of ANOTHER kind is reported - the family is per-kind",
        files={
            "Заявки.yaml": _CATALOG_RU,
            "Заявки.xbsl": "метод Проба(Схема: Заявки.СхемаДанных)\n;\n",
        },
        tokens={"Заявки": "Applications", "Проба": "Probe", "Схема": "Schema"},
    ),
    Seed(
        rule="code/undefined-name",
        expect=CLEAN,
        note="the entity protocol is in scope in an object module without being declared",
        files={
            "Заявки.yaml": _CATALOG_RU,
            "Заявки.Объект.xbsl": "метод Проба()\n    Записать()\n;\n",
        },
        tokens={"Заявки": "Applications", "Проба": "Probe"},
    ),
    Seed(
        rule="style/exception-prefix",
        expect=FINDING,
        note="an exception without the kind word in its name - a prefix in Russian, a suffix "
             "in English",
        files={"Модуль.xbsl": "исключение Авторизация\n;\n"},
        tokens={"Модуль": "Module", "Авторизация": "Authentication"},
    ),
    Seed(
        rule="query/unknown-table",
        expect=FINDING,
        note="a query over a table of neither the platform nor the project",
        files={
            "Заявки.yaml": _CATALOG_RU,
            "Заявки.xbsl": "метод Проба()\n    знч Итог = Запрос{\n"
                           "        ВЫБРАТЬ Ссылка ИЗ Пользователз\n    }\n;\n",
        },
        tokens={"Заявки": "Applications", "Проба": "Probe", "Итог": "Result"},
    ),
    Seed(
        rule="naming/prefix-by-kind",
        expect=CLEAN,
        note="an element named after its kind - the kind word leads in Russian and trails in "
             "English",
        files={
            "ФормаЗаявок.yaml": "ВидЭлемента: Форма\n"
                                "Ид: 1d1f5c60-0000-4000-8000-000000000f03\n"
                                "Имя: ФормаЗаявок\n"
                                "ОбластьВидимости: ВПроекте\n",
        },
        tokens={"ФормаЗаявок": "ApplicationsForm"},
    ),
    Seed(
        rule="yaml/unknown-property",
        expect=CLEAN,
        note="the properties a kind declares - the metamodel spells them Russian",
        files={"Заявки.yaml": _CATALOG_RU},
        tokens={"Заявки": "Applications"},
    ),
    Seed(
        rule="yaml/unknown-property",
        expect=FINDING,
        note="a property the kind does not declare is reported",
        files={
            "Заявки.yaml": _CATALOG_RU + "ЛишнееСвойство: Истина\n",
        },
        tokens={"Заявки": "Applications", "ЛишнееСвойство": "SpareProperty"},
    ),
    Seed(
        rule="code/unknown-member",
        expect=CLEAN,
        note="a member of a stdlib type - the catalog stores the members Russian",
        files={
            "Заявки.yaml": _CATALOG_RU,
            "Заявки.xbsl": "метод Проба()\n    знч Список = новый Массив<Строка>()\n"
                           "    Список.Добавить(\"a\")\n;\n",
        },
        tokens={"Заявки": "Applications", "Проба": "Probe", "Список": "List"},
    ),
    Seed(
        rule="code/unknown-member",
        expect=FINDING,
        note="a member no stdlib type has is reported",
        files={
            "Заявки.yaml": _CATALOG_RU,
            "Заявки.xbsl": "метод Проба()\n    знч Список = новый Массив<Строка>()\n"
                           "    Список.НетТакогоМетода()\n;\n",
        },
        tokens={"Заявки": "Applications", "Проба": "Probe", "Список": "List",
                "НетТакогоМетода": "NoSuchMethod"},
        known="the rule skips Latin member spellings on purpose, and the type catalog stores "
              "members in Russian alone: translating the member set would report every "
              "correct English member whose Russian name the dictionaries do not pair - 287 "
              "of them, mostly enumeration values, which live in the ui terms rather than in "
              "the compiler dictionary. Closing this needs the member vocabulary completed, "
              "not a change to the rule.",
    ),
    Seed(
        rule="code/unknown-type",
        expect=CLEAN,
        note="a stdlib type in a signature - the type catalog is keyed Russian",
        files={
            "Заявки.yaml": _CATALOG_RU,
            "Заявки.xbsl": "метод Проба(Значение: Строка)\n;\n",
        },
        tokens={"Заявки": "Applications", "Проба": "Probe", "Значение": "Value"},
    ),
    Seed(
        rule="code/unknown-type",
        expect=FINDING,
        note="a type of neither the platform nor the project is reported",
        files={
            "Заявки.yaml": _CATALOG_RU,
            "Заявки.xbsl": "метод Проба(Значение: НесуществующийТип)\n;\n",
        },
        tokens={"Заявки": "Applications", "Проба": "Probe", "Значение": "Value",
                "НесуществующийТип": "NonexistentType"},
    ),
]


def _lint(root: Path, rule: str) -> list:
    paths = engine.find_sources(root, "*.xbsl") + engine.find_sources(root, "*.yaml")
    return [d for d in engine.run(paths, select={rule}) if d.rule_id == rule]


def _verdict(fired: bool, expect: str) -> bool:
    """Did a tree answer the way the seed says it must?"""
    return fired if expect == FINDING else not fired


def run_seed(seed: Seed) -> dict:
    """Plant the seed, translate it, run the rule on both trees, judge the pair."""
    with tempfile.TemporaryDirectory() as tmp:
        base = Path(tmp)
        russian = base / "ru"
        russian.mkdir()
        for name, text in seed.files.items():
            path = russian / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text, encoding="utf-8")

        english = base / "en"
        report = translate_project(russian, Dictionary(tokens=dict(seed.tokens)), out=english)

        ru_found = _lint(russian, seed.rule)
        en_found = _lint(english, seed.rule)
        ru_ok = _verdict(bool(ru_found), seed.expect)
        en_ok = _verdict(bool(en_found), seed.expect)

        # The flavour follows the seed: on a planted violation a wrong tree MISSES it, on
        # legal code a wrong tree INVENTS one. Naming the side and the direction is what makes
        # the line actionable - the two call for opposite fixes.
        flavour = "misses" if seed.expect == FINDING else "invents"
        if ru_ok and en_ok:
            status = "ok"
        elif not ru_ok and not en_ok:
            status = "stale"
        elif ru_ok:
            status = f"en-{flavour}"
        else:
            status = f"ru-{flavour}"

        if seed.known:
            # A documented gap: not a failure, but its CLOSING is news worth shouting.
            status = "fixed!" if status == "ok" else f"known ({status})"

        return {
            "rule": seed.rule,
            "expect": seed.expect,
            "note": seed.note,
            "known": seed.known,
            "status": status,
            "russian": len(ru_found),
            "english": len(en_found),
            # A name the dictionary does not carry stays Russian in the translated tree, and a
            # seed that leans on such a name would be testing the dictionary, not the rule.
            "translation_problems": list(report.problems),
        }


def _uncovered() -> list[str]:
    """Registered rules no seed speaks for - the honest size of what this check does not say."""
    seeded = {seed.rule for seed in SEEDS}
    return sorted(info.id for info in engine.RULES if info.id not in seeded)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--rule", help="run only the seeds of this rule")
    parser.add_argument("--json", action="store_true", help="machine-readable output")
    parser.add_argument(
        "--uncovered", action="store_true", help="list the rules no seed speaks for and exit",
    )
    args = parser.parse_args(argv)

    if args.uncovered:
        names = _uncovered()
        if args.json:
            print(json.dumps({"uncovered": names}, ensure_ascii=False, indent=2))
        else:
            for name in names:
                print(name)
            print(f"\nno seed: {len(names)}")
        return 0

    seeds = [s for s in SEEDS if not args.rule or s.rule == args.rule]
    if not seeds:
        print(f"no seed for {args.rule!r}", file=sys.stderr)
        return 2

    results = [run_seed(seed) for seed in seeds]
    # A documented gap does not fail the run; a gap that CLOSED does, so the note gets removed.
    bad = [r for r in results
           if r["status"] != "ok" and not r["status"].startswith("known")]
    known = [r for r in results if r["status"].startswith("known")]

    if args.json:
        print(json.dumps(
            {"results": results, "uncovered": len(_uncovered())},
            ensure_ascii=False, indent=2,
        ))
        return 1 if bad else 0

    width = max(len(r["status"]) for r in results)
    for result in results:
        mark = result["status"].ljust(width)
        print(f"[{mark}] {result['rule']} ({result['expect']}): "
              f"ru={result['russian']} en={result['english']} - {result['note']}")
        if result["known"]:
            print(f"          known: {result['known']}")
        if result["translation_problems"]:
            print(f"          translation: {result['translation_problems']}")

    covered = len({s.rule for s in SEEDS})
    print(f"\nseeds: {len(results)}, disagreements: {len(bad)}, known gaps: {len(known)}; "
          f"rules with a seed: {covered}, without: {len(_uncovered())}")
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
