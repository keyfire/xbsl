"""Prove by compilation the names the engine claims exist without data to back them.

Some rules carry tables that assert "the platform HAS this name, our data simply does not
carry it" (`_UNDOCUMENTED`, `_IMPLICIT`, `_ENTITY_COMMON`, `_COMMON_MEMBERS`). Such an
assertion has nothing behind it: the data is silent about it by construction, and a test
written for it repeats the very same assertion. That is how two names the platform does not
have at all lived in the whitelist of `code/undefined-name` for a long time - and kept that
rule silent on code that cannot compile.

Only the compiler can settle it. This tool builds ONE probe project where every claimed name
is used on its own line of its own module, compiles it (elemctl probe) and maps the answer
back onto the claims by line number.

**The control is mandatory.** Every module also uses a name that certainly does not exist. If
the compiler said nothing about it, the module was not compiled at all (the wrong context, an
earlier error, an empty run) - and then "everything is confirmed" must not be read: the tool
answers VOID rather than OK.

Run:

    python tools/verify_claims.py --out <dir> \\
        --probe-cmd "elemctl --env-file <path>/.agent/local.env probe --project-dir {dir}"

Without --probe-cmd the project is only written and the command to run is printed. A run takes
about a minute and a half and needs a stand, so this is a maintenance chore rather than a
test: run it when a table grows and after a platform build upgrade.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import uuid
from dataclasses import dataclass, field
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from xbsl.rules.undefined_names import _ENTITY_COMMON, _IMPLICIT, _UNDOCUMENTED  # noqa: E402
from xbsl.rules.unknown_members import _COMMON_MEMBERS  # noqa: E402

#: A name that certainly does not exist - the control of every module.
CONTROL = "ЗаведомоНетТакогоИмениВПлатформе"


@dataclass(frozen=True)
class Claim:
    """A claimed name and the way to exercise it.

    module - where the name is available (`object`, `form`, `common`, `rights`, ...);
    code - the line of code using it, the one that goes into the probe.
    """

    table: str
    name: str
    module: str
    code: str


@dataclass
class Module:
    """A module of the probe: its claims in line order plus the control line."""

    kind: str
    path: str
    header: str
    claims: list[Claim] = field(default_factory=list)
    #: line -> claim (filled while generating)
    lines: dict[int, Claim] = field(default_factory=dict)
    control_line: int = 0


# --- recipes ------------------------------------------------------------------------------
#
# Every claim has its own way of being exercised: a root name is enough to read, a method has
# to be called, a member needs a receiver. A recipe is part of the evidence: when the compiler
# objects, either the claim or the recipe is wrong, and a human has to tell which.

_READ = "    знч Прочитано{n} = {name}"
_CALL = "    {name}()"

RECIPES: dict[tuple[str, str], tuple[str, str]] = {
    # _IMPLICIT: roots the module kind itself provides.
    ("_IMPLICIT", "Компоненты"): ("form", _READ),
    ("_IMPLICIT", "Components"): ("form", _READ),
    ("_IMPLICIT", "Это"): ("object", _READ),
    ("_IMPLICIT", "До"): ("object", _READ),
    # The rights namespace lives in the permission handler, and that one sits in the plain
    # module of an entity rather than in its object module (the shape of working sources).
    ("_IMPLICIT", "Сущность"): ("rights", "    знч Право{n} = {name}.Право.Чтение"),
    # _UNDOCUMENTED: members the documentation does not carry.
    ("_UNDOCUMENTED", "СобственнаяМодифицированность"): ("form", _READ),
    ("_UNDOCUMENTED", "Message"): ("common", "    {name}(\"проба\")"),
    # _ENTITY_COMMON: names an entity module is said to get without a yaml declaration.
    ("_ENTITY_COMMON", "Наименование"): ("object", _READ),
    ("_ENTITY_COMMON", "Код"): ("object", _READ),
    ("_ENTITY_COMMON", "Ссылка"): ("object", _READ),
    ("_ENTITY_COMMON", "ЭтоНовый"): ("object", _READ),
    ("_ENTITY_COMMON", "ПометкаУдаления"): ("object", _READ),
    ("_ENTITY_COMMON", "РежимЗагрузкиДанных"): ("object", _READ),
    ("_ENTITY_COMMON", "Записать"): ("object", _CALL),
    ("_ENTITY_COMMON", "Удалить"): ("object", _CALL),
    ("_ENTITY_COMMON", "ПометитьНаУдаление"): ("object", _CALL),
    ("_ENTITY_COMMON", "СнятьПометкуУдаления"): ("object", _CALL),
    # Register record names: a catalog module has none of them by construction, and a
    # register's module carries no `.Объект` in its name (the shape of working sources).
    ("_ENTITY_COMMON", "Период"): ("record", _READ),
    ("_ENTITY_COMMON", "Регистратор"): ("record", _READ),
    ("_ENTITY_COMMON", "ВидЗаписи"): ("record", _READ),
    ("_ENTITY_COMMON", "Номер"): ("document", _READ),
    ("_ENTITY_COMMON", "Дата"): ("document", _READ),
    # _COMMON_MEMBERS: the object protocol - a member of any receiver.
    ("_COMMON_MEMBERS", "ПолучитьТип"): ("object", "    знч Тип{n} = Ссылка.{name}()"),
    ("_COMMON_MEMBERS", "ВСтроку"): ("object", "    знч Текст{n} = Ссылка.{name}()"),
    ("_COMMON_MEMBERS", "Представление"): ("object", "    знч Предст{n} = Ссылка.{name}()"),
}

TABLES = {
    "_IMPLICIT": _IMPLICIT,
    "_UNDOCUMENTED": _UNDOCUMENTED,
    "_ENTITY_COMMON": _ENTITY_COMMON,
    "_COMMON_MEMBERS": _COMMON_MEMBERS,
}


def claims() -> list[Claim]:
    """The claims of every table. A name without a recipe is refused: nothing can prove it."""
    out, missing = [], []
    for table, names in TABLES.items():
        for name in sorted(names):
            recipe = RECIPES.get((table, name))
            if recipe is None:
                missing.append(f"{table}.{name}")
                continue
            module, code = recipe
            out.append(Claim(table=table, name=name, module=module, code=code))
    if missing:
        raise SystemExit(
            "No recipe for: " + ", ".join(missing)
            + "\nAdd one to RECIPES: a name declared to exist has to be provable by the "
            "compiler."
        )
    return out


# --- the probe project ---------------------------------------------------------------------
#
# The yaml and the module text below are GENERATED CODE - platform sources, written in the
# platform's own vocabulary.

_UID = "6f0b6a44-0000-4000-8000-{:012d}"


def _uid(number: int) -> str:
    return _UID.format(number)


PROJECT = """\
Ид: {uid}
Имя: ПроверкаЗаявок
Поставщик: Acme
Версия: 1.0.0
Представление: Проверка заявок
ПредставлениеПоставщика: Acme
РежимСовместимости: 10.0
"""

SUBSYSTEM = """\
Интерфейс:
    ВключатьВАвтоИнтерфейс: Ложь
"""

# The standard attributes are deliberately NOT declared here: the claim says the platform
# provides them without a yaml declaration, and declaring them would test something else.
CATALOG = """\
ВидЭлемента: Справочник
Ид: {uid}
Имя: Задачи
ОбластьВидимости: ВПроекте
Реквизиты:
    -
        Ид: {attr}
        Имя: Пометка
        Тип: Строка
        МаксимальнаяДлина: 50
"""

DOCUMENT = """\
ВидЭлемента: Документ
Ид: {uid}
Имя: Отгрузка
ОбластьВидимости: ВПроекте
Реквизиты:
    -
        Имя: Дата
        Тип: ДатаВремя
"""

REGISTER = """\
ВидЭлемента: РегистрСведений
Ид: {uid}
Имя: Показатели
ОбластьВидимости: ВПроекте
Периодичность: Секунда
Измерения:
    -
        Ид: {dim}
        Имя: Ключ
        Тип: Строка
        МаксимальнаяДлина: 50
Ресурсы:
    -
        Ид: {res}
        Имя: Значение
        Тип: Число
"""

FORM = """\
ВидЭлемента: КомпонентИнтерфейса
Ид: {uid}
Имя: Карточка
ОбластьВидимости: ВПроекте
Наследует:
    Тип: ФормаОбъекта<Задачи.Объект>
    Содержимое:
        Тип: ПроизвольныйШаблонФормы
        Содержимое:
            Тип: Группа
            Компоновка: Вертикальная
"""

COMMON = """\
ВидЭлемента: ОбщийМодуль
Ид: {uid}
Имя: Проба
ОбластьВидимости: ВПроекте
Окружение: КлиентИСервер
"""

# The head of each module: the handler the claim lines go into. The signatures are the ones
# the platform declares - a wrong one costs the whole module (the control then reports VOID).
HEADERS = {
    "object": "@Обработчик\nметод ПередЗаписью(До: Задачи.Данные,"
              " ПараметрыЗаписи: Задачи.ПараметрыЗаписи)\n",
    "document": "@Обработчик\nметод ПередЗаписью(До: Отгрузка.Данные,"
                " ПараметрыЗаписи: Отгрузка.ПараметрыЗаписи)\n",
    "record": "@Обработчик\nметод ПередЗаписью(До: Показатели.Данные,"
              " ПараметрыЗаписи: Показатели.ПараметрыЗаписи)\n",
    "form": "@Обработчик\nметод ПослеСоздания()\n",
    "common": "@НаКлиенте\nметод Проверить()\n",
    "rights": "@Обработчик\nметод ВычислитьРазрешенияДоступа(): Массив<РазрешениеДоступа>\n",
}

MODULE_FILES = {
    "object": "Основное/Задачи.Объект.xbsl",
    "document": "Основное/Отгрузка.Объект.xbsl",
    "record": "Основное/Показатели.xbsl",
    "form": "Основное/Карточка.xbsl",
    "common": "Основное/Проба.xbsl",
    "rights": "Основное/Задачи.xbsl",
}

#: The compiler wants the layout {repository}/{vendor}/{name}/Проект.yaml.
VENDOR, PROJECT_NAME = "Acme", "ПроверкаЗаявок"


def project_dir(out: Path) -> Path:
    return out / VENDOR / PROJECT_NAME


def build(root: Path) -> dict[str, Module]:
    """Write the probe project; return its modules with the "line -> claim" map."""
    out = project_dir(root)
    out.mkdir(parents=True, exist_ok=True)
    (out / "Проект.yaml").write_text(PROJECT.format(uid=_uid(1)), encoding="utf-8")
    main = out / "Основное"
    main.mkdir(exist_ok=True)
    (main / "Подсистема.yaml").write_text(SUBSYSTEM, encoding="utf-8")
    (main / "Задачи.yaml").write_text(
        CATALOG.format(uid=_uid(2), attr=_uid(9)), encoding="utf-8"
    )
    (main / "Отгрузка.yaml").write_text(DOCUMENT.format(uid=_uid(3)), encoding="utf-8")
    (main / "Показатели.yaml").write_text(
        REGISTER.format(uid=_uid(4), dim=_uid(5), res=_uid(6)), encoding="utf-8"
    )
    (main / "Карточка.yaml").write_text(FORM.format(uid=_uid(7)), encoding="utf-8")
    (main / "Проба.yaml").write_text(COMMON.format(uid=_uid(8)), encoding="utf-8")

    modules = {
        kind: Module(kind=kind, path=path, header=HEADERS[kind])
        for kind, path in MODULE_FILES.items()
    }
    for claim in claims():
        modules[claim.module].claims.append(claim)

    for module in modules.values():
        lines = module.header.split("\n")[:-1]
        for number, claim in enumerate(module.claims, start=1):
            lines.append(claim.code.format(name=claim.name, n=number))
            module.lines[len(lines)] = claim
        lines.append(f"    знч Контроль = {CONTROL}")  # the control line
        module.control_line = len(lines)
        if module.kind == "rights":
            lines.append("    возврат []")  # the handler has to return something
        lines.append(";")
        (out / module.path).write_text("\n".join(lines) + "\n", encoding="utf-8")
    return modules


# --- the verdict ----------------------------------------------------------------------------


def verdict(modules: dict[str, Module], report: dict) -> int:
    """Map the compiler's answer back onto the claims; 0 - every claim confirmed."""
    errors = report.get("errors") or []
    by_file: dict[str, list[dict]] = {}
    for error in errors:
        by_file.setdefault(str(error.get("file", "")).replace("\\", "/"), []).append(error)

    failed: list[str] = []
    void: list[str] = []
    confirmed = 0
    for module in modules.values():
        found = by_file.get(module.path, [])
        control_said = any(
            error.get("line") == module.control_line or CONTROL in str(error.get("message", ""))
            for error in found
        )
        if not control_said:
            void.append(module.path)
        for line, claim in module.lines.items():
            said = [
                error for error in found
                if error.get("line") == line or claim.name in str(error.get("message", ""))
            ]
            if said:
                failed.append(f"{claim.table}.{claim.name} ({module.path}:{line}): "
                              f"{said[0].get('message', '')}")
            else:
                confirmed += 1

    print(f"claims checked: {confirmed + len(failed)}, confirmed: {confirmed}")
    for line in failed:
        print("  NOT CONFIRMED:", line)
    if void:
        print("VOID: the control line raised nothing in: " + ", ".join(void))
        print("  The module was not compiled - 'confirmed' must not be read.")
        return 2
    if failed:
        print("A claim is not confirmed: either the platform has no such name (drop it from "
              "the table) or the recipe is wrong (fix RECIPES).")
        return 1
    print("Every claim is confirmed by the compiler.")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="verify_claims", description=__doc__.split("\n", 1)[0],
    )
    parser.add_argument("--out", default="", help="directory of the probe project")
    parser.add_argument("--probe-cmd", default="",
                        help='the compile command, {dir} being the project directory '
                             '(e.g. "elemctl --env-file ... probe --project-dir {dir}")')
    parser.add_argument("--report", default="",
                        help="a probe report in JSON (instead of running one)")
    args = parser.parse_args(argv)

    root = Path(args.out or (Path.cwd() / f"claims-probe-{uuid.uuid4().hex[:8]}"))
    modules = build(root)
    out = project_dir(root)
    print(f"probe written: {out}")

    if args.report:
        return verdict(modules, json.loads(Path(args.report).read_text(encoding="utf-8-sig")))
    if not args.probe_cmd:
        print("Compile it and feed the JSON to --report, e.g.:")
        print(f'  elemctl --env-file <path>/.agent/local.env probe --project-dir "{out}"')
        return 0

    command = args.probe_cmd.format(dir=str(out))
    print("compiling:", command)
    run = subprocess.run(command, shell=True, capture_output=True, text=True, encoding="utf-8")
    text = run.stdout or ""
    start = text.find("{")
    if start < 0:
        print("The probe returned no JSON:", (run.stderr or text)[-400:])
        return 2
    return verdict(modules, json.loads(text[start:]))


if __name__ == "__main__":
    raise SystemExit(main())
