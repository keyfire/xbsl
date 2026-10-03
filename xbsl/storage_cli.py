"""Management commands for shared platform data."""
from __future__ import annotations

import json
import sys
from pathlib import Path

from xbsl import data_storage, i18n

MESSAGES = {
    "storage.pack": {"ru": "Упаковать данные в общий каталог", "en": "Pack data into a shared catalog"},
    "storage.export": {"ru": "Выгрузить данные в прежний формат", "en": "Export data into the legacy format"},
    "storage.verify": {"ru": "Проверить целостность данных", "en": "Verify data integrity"},
    "storage.prune": {"ru": "Найти или удалить неиспользуемые общие объекты", "en": "Find or remove unused shared objects"},
    "storage.root": {"ru": "корень данных", "en": "data root"},
    "storage.target": {"ru": "каталог результата", "en": "destination directory"},
    "storage.version": {"ru": "версия; повторяемый ключ, при обновлении остальные версии сохраняются", "en": "version; repeatable, other destination versions are preserved on update"},
    "storage.apply": {"ru": "удалить найденные неиспользуемые объекты", "en": "remove the unused objects found"},
    "storage.failed": {"ru": "Операция с данными не выполнена: {error}", "en": "Data operation failed: {error}"},
}
i18n.register(MESSAGES)


def main(command, argv):
    i18n.set_lang(i18n.lang_from_argv(argv))
    action = command.removeprefix("data-")
    parser = i18n.ArgumentParser(prog="xbsl " + command, description=i18n.t("storage." + action))
    parser.add_argument("root", type=Path, help=i18n.t("storage.root"))
    if action in ("pack", "export"):
        parser.add_argument("target", type=Path, help=i18n.t("storage.target"))
        parser.add_argument("--version", action="append", help=i18n.t("storage.version"))
    if action == "prune":
        parser.add_argument("--apply", action="store_true", help=i18n.t("storage.apply"))
    parser.add_argument("--lang", choices=i18n.LANGS)
    args = parser.parse_args(argv)
    try:
        if action == "pack":
            result = data_storage.pack(args.root, args.target, versions=args.version)
        elif action == "export":
            result = data_storage.export(args.root, args.target, versions=args.version)
        elif action == "verify":
            result = data_storage.verify(args.root)
        else:
            result = data_storage.prune(args.root, apply=args.apply)
    except (data_storage.StorageError, OSError, ValueError) as error:
        print(i18n.t("storage.failed", error=str(error)), file=sys.stderr)
        return 2
    print(json.dumps(result, ensure_ascii=False))
    return 0
