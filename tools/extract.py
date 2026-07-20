#!/usr/bin/env python3
"""Generate the whole language dataset from a 1C:Element distribution - one entry point.

    python tools/extract.py --dist "<path to the distribution>"

Runs every extractor in the order below. The order is not cosmetic: `uischema` reads the
documentation dataset that `docs` produces, so it can only run after it. That dependency is
also why the steps are listed here EXPLICITLY instead of being discovered by a glob over
`tools/extract_*.py` - a discovered set has no order, no way to tell a work-in-progress
script from a real step, and no place to say which steps need the distribution.

Each step is a module with `main(argv)`, so a single extractor stays runnable on its own
exactly as before; this file only decides what runs, in which order, and with which arguments.

    python tools/extract.py --dist ... --only stdlib,terms    # a subset, order preserved
    python tools/extract.py --dist ... --skip docs            # docs builds a large index
"""

from __future__ import annotations

import argparse
import importlib
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _distro  # noqa: E402

#: Steps in dependency order: (name, module, needs --dist, what it produces).
STEPS = (
    ("grammar", "extract_grammar", True, "language.json - ключевые слова и операторы"),
    ("stdlib", "extract_stdlib", True, "stdlib.json - каталог типов и их членов"),
    ("metamodel", "extract_metamodel", True, "metamodel.json - свойства элементов по видам"),
    ("terms", "extract_terms", True, "terms.json - пары русского и английского написания"),
    ("docs", "extract_docs", True, "docs.sqlite - полнотекстовый индекс документации"),
    ("uischema", "extract_uischema", False, "uischema.json - схема компонентов (читает docs)"),
)


def _selected(only: str, skip: str) -> list[tuple[str, str, bool, str]]:
    names = [step[0] for step in STEPS]
    chosen = [n.strip() for n in only.split(",") if n.strip()] if only else names
    dropped = {n.strip() for n in skip.split(",") if n.strip()}
    unknown = sorted(set(chosen) | dropped - set(names))
    unknown = [n for n in unknown if n not in names]
    if unknown:
        raise SystemExit(f"неизвестные шаги: {', '.join(unknown)}; доступны: {', '.join(names)}")
    return [step for step in STEPS if step[0] in chosen and step[0] not in dropped]


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--dist", help="каталог дистрибутива 1С:Элемент")
    ap.add_argument("--element-version", help="версия данных (по умолчанию - из дистрибутива)")
    ap.add_argument("--only", default="", help="только эти шаги, через запятую")
    ap.add_argument("--skip", default="", help="пропустить эти шаги, через запятую")
    _distro.add_data_dir_arg(ap)
    args = ap.parse_args(argv)

    steps = _selected(args.only, args.skip)
    if any(needs_dist for _, _, needs_dist, _ in steps) and not args.dist:
        raise SystemExit("нужен --dist: этим шагам требуется дистрибутив")

    common = []
    if args.element_version:
        common += ["--element-version", args.element_version]
    if args.data_dir:
        common += ["--data-dir", args.data_dir]

    failures: list[str] = []
    for index, (name, module_name, needs_dist, produces) in enumerate(steps, 1):
        print(f"\n=== [{index}/{len(steps)}] {name}: {produces}", flush=True)
        argv_step = (["--dist", args.dist] if needs_dist else []) + common
        started = time.monotonic()
        try:
            importlib.import_module(module_name).main(argv_step)
        except SystemExit as error:  # argparse/явный выход внутри шага
            if error.code:
                failures.append(name)
                print(f"--- {name}: прерван (код {error.code})")
        except Exception as error:  # noqa: BLE001 - шаг не должен ронять остальные
            failures.append(name)
            print(f"--- {name}: ошибка - {type(error).__name__}: {error}")
        print(f"--- {name}: {time.monotonic() - started:.1f} с")

    done = len(steps) - len(failures)
    print(f"\nГотово шагов: {done} из {len(steps)}")
    if failures:
        print(f"С ошибкой: {', '.join(failures)}")
        # uischema читает результат docs - о причине стоит сказать прямо.
        if "docs" in failures and any(s[0] == "uischema" for s in steps):
            print("uischema строится по данным docs - проверьте сначала его")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
