"""Language of the linter output: message catalogs and lookup.

A rule module registers its own messages next to the rules that emit them, so that a rule
and its wording cannot drift apart:

    MESSAGES = {
        "code/brackets.unclosed": {
            "ru": "Не закрыта скобка '{ch}'.",
            "en": "Unclosed bracket '{ch}'.",
        },
    }
    i18n.register(MESSAGES)

Keys are `<rule id>.title` for a rule title and `<rule id>.<variant>` for its messages;
non-rule text uses a `<module>.<name>` key. Placeholders are `str.format` fields and must be
the same in every language – `tests/test_i18n.py` enforces that. A brace that is part of the
text – `() [] {{}}` – has to be doubled, because every template is formatted.

The language is chosen by: set_lang() (CLI --lang) > env XBSL_LANG (or the pre-rename
XBSLLINT_LANG) > system locale > ru.
An unknown key is returned as is, so a plugin written against 0.3 – which passed literal
strings rather than keys – keeps working.

The --help text is translated too (the `cli.help.*` keys), including argparse's own
`-h/--help` - see ArgumentParser at the bottom of this module. The check-mode parser is
built after the language is resolved: cli.main reads --lang out of argv with
lang_from_argv() before build_parser(), because argparse learns --lang only when it parses.
The scaffolding and `templates` sub-parsers take no --lang, so their language comes from the
env variable or the locale.
"""

from __future__ import annotations

import argparse as _argparse
import locale as _locale
import os

LANGS = ("ru", "en")
DEFAULT_LANG = "ru"
ENV_LANG = "XBSL_LANG"
_ENV_LANG_LEGACY = "XBSLLINT_LANG"

_catalog: dict[str, dict[str, str]] = {}
_selected: str | None = None

# Text of the adapters themselves (CLI summary, tool descriptions) – not tied to any one rule.
_CORE_MESSAGES = {
    "cli.summary": {
        "ru": "\nПроверено файлов: {files} ({xbsl} .xbsl, {yaml} .yaml); "
              "замечаний: {diags} (ошибок: {errors})",
        "en": "\nFiles checked: {files} ({xbsl} .xbsl, {yaml} .yaml); "
              "diagnostics: {diags} (errors: {errors})",
    },
    "cli.no-rules": {
        "ru": "(правила ещё не зарегистрированы)",
        "en": "(no rules registered yet)",
    },
    "cli.data-error": {
        "ru": "Ошибка данных Элемента: {error}",
        "en": "Element data error: {error}",
    },
    "cli.stdin-needs-filename": {
        "ru": "Режиму --stdin нужен --filename (напр. Форма.xbsl): по расширению определяется вид файла.",
        "en": "--stdin needs --filename (e.g. Form.xbsl): the extension sets the file kind.",
    },
    "cli.index-single-path": {
        "ru": "Режиму --index нужен ровно один путь – корень индексируемого проекта.",
        "en": "--index takes exactly one path – the root of the project to index.",
    },
    "cli.index-missing-path": {
        "ru": "Путь '{path}' не существует.",
        "en": "Path '{path}' does not exist.",
    },
    "cli.baseline-summary": {
        "ru": "Погашено базлайном: {suppressed}; устаревших записей базлайна: {unused}",
        "en": "Suppressed by the baseline: {suppressed}; stale baseline entries: {unused}",
    },
    "cli.baseline-written": {
        "ru": "Базлайн записан: {path} ({diags} замечаний в {files} файлах)",
        "en": "Baseline written: {path} ({diags} findings in {files} files)",
    },
    "cli.fix-summary": {
        "ru": "Исправлено замечаний: {fixed} в {files} файлах; осталось: {left}",
        "en": "Fixed findings: {fixed} in {files} files; remaining: {left}",
    },
    "cli.fix-needs-files": {
        "ru": "Режим --fix пишет файлы на диске и несовместим с --stdin.",
        "en": "--fix writes files on disk and is incompatible with --stdin.",
    },
    "cli.fix-conflicts-baseline": {
        "ru": "Режим --fix несовместим с --baseline / --write-baseline.",
        "en": "--fix is incompatible with --baseline / --write-baseline.",
    },
    # -- help: check-mode argparse help (cli.py build_parser / _commands_help) --
    "cli.help.usage": {
        "ru": "%(prog)s [пути] [опции]        (без команды: проверка исходников)\n"
              "       %(prog)s <команда> [опции]",
        "en": "%(prog)s [paths] [options]       (no command: check the sources)\n"
              "       %(prog)s <command> [options]",
    },
    "cli.help.description": {
        "ru": "Линтер исходников 1С:Элемент (пары .yaml/.xbsl).\n\n"
              "Без команды проверяет указанные пути – это режим по умолчанию.\n"
              "Команды ниже адресуют остальные части инструментария.",
        "en": "Linter for 1C:Element sources (.yaml/.xbsl pairs).\n\n"
              "With no command it checks the given paths – this is the default mode.\n"
              "The commands below address the other parts of the toolkit.",
    },
    "cli.help.paths": {
        "ru": "файлы или каталоги для проверки",
        "en": "files or directories to check",
    },
    "cli.help.select": {
        "ru": "проверять только эти правила (через запятую или повтором флага: id, группа – "
              "часть id до '/' (напр. style) – или буква тира A/B/C/D)",
        "en": "check only these rules (comma-separated or by repeating the flag: id, group – "
              "the part of the id before '/' (e.g. style) – or a tier letter A/B/C/D)",
    },
    "cli.help.ignore": {
        "ru": "исключить эти правила (через запятую или повтором флага: id, группа или буква тира)",
        "en": "exclude these rules (comma-separated or by repeating the flag: id, group or tier letter)",
    },
    "cli.help.enable": {
        "ru": "добавить выключенные по умолчанию правила ПОВЕРХ стандартного набора "
              "(--select набор заменяет); формы значений те же",
        "en": "add rules disabled by default ON TOP of the standard set "
              "(--select replaces the set); the value forms are the same",
    },
    "cli.help.baseline": {
        "ru": "гасить находки, замороженные в файле базлайна (создаётся --write-baseline); "
              "новые находки выводятся как обычно",
        "en": "suppress findings frozen in a baseline file (created by --write-baseline); "
              "new findings are reported as usual",
    },
    "cli.help.write-baseline": {
        "ru": "вместо отчёта записать все текущие находки в файл базлайна "
              "(заморозить долг; пути в файле – относительно его каталога)",
        "en": "instead of a report, write all current findings to a baseline file "
              "(freeze the debt; paths in the file are relative to its directory)",
    },
    "cli.help.fix": {
        "ru": "исправить механические находки на месте (хвостовые пробелы, типографские "
              "символы, переводы строк) и вывести оставшиеся; правит только однозначно",
        "en": "fix mechanical findings in place (trailing spaces, typographic "
              "characters, line endings) and report the rest; only unambiguous fixes",
    },
    "cli.help.jobs": {
        "ru": "процессов для файловых правил: 0 – авто (включается на больших прогонах), "
              "1 – последовательно, N – явное число воркеров",
        "en": "processes for file-scope rules: 0 – auto (kicks in on large runs), "
              "1 – sequential, N – an explicit worker count",
    },
    "cli.help.list-rules": {
        "ru": "вывести список правил и выйти",
        "en": "print the list of rules and exit",
    },
    "cli.help.where": {
        "ru": "показать корень данных Элемента (путь, источник, версии) и выйти",
        "en": "show the Element data root (path, source, versions) and exit",
    },
    "cli.help.element-version": {
        "ru": "версия данных Элемента (по умолчанию – последняя из бандла)",
        "en": "Element data version (default: the latest in the bundle)",
    },
    "cli.help.data-dir": {
        "ru": "корень данных Элемента (каталог с index.json); также env XBSL_DATA_DIR",
        "en": "Element data root (a directory with index.json); also env XBSL_DATA_DIR",
    },
    "cli.help.lang": {
        "ru": "язык вывода линтера (по умолчанию: env XBSL_LANG / локаль системы / ru)",
        "en": "linter output language (default: env XBSL_LANG / system locale / ru)",
    },
    "cli.help.format": {
        "ru": "формат вывода: text (по умолчанию), json (машиночитаемый: diagnostics + summary) "
              "или codeclimate (отчёт GitLab Code Quality – виджет в merge request)",
        "en": "output format: text (default), json (machine-readable: diagnostics + summary) "
              "or codeclimate (a GitLab Code Quality report – the merge request widget)",
    },
    "cli.help.stdin": {
        "ru": "проверить один буфер из stdin (для интеграции с редактором); "
              "вид файла и путь в позициях задаёт --filename",
        "en": "check a single buffer from stdin (for editor integration); "
              "--filename sets the file kind and the reported path",
    },
    "cli.help.index": {
        "ru": "вместо проверки вывести JSON-индекс проекта (объекты, методы, компоненты форм) "
              "для навигации в редакторе; путь – корень проекта",
        "en": "instead of checking, print a JSON project index (objects, methods, form components) "
              "for editor navigation; the path is the project root",
    },
    "cli.help.filename": {
        "ru": "имя проверяемого буфера при --stdin (напр. Форма.xbsl); расширение задаёт вид файла",
        "en": "name of the buffer checked with --stdin (e.g. Форма.xbsl); the extension sets the file kind",
    },
    "cli.help.meta.rule-selector": {
        "ru": "ID/ГРУППА/ТИР",
        "en": "ID/GROUP/TIER",
    },
    "cli.help.meta.file": {
        "ru": "ФАЙЛ",
        "en": "FILE",
    },
    "cli.help.meta.version": {
        "ru": "ВЕРСИЯ",
        "en": "VERSION",
    },
    "cli.help.meta.dir": {
        "ru": "КАТАЛОГ",
        "en": "DIR",
    },
    "cli.help.meta.name": {
        "ru": "ИМЯ",
        "en": "NAME",
    },
    "cli.help.server.lsp": {
        "ru": "сервер LSP для редактора",
        "en": "LSP server for the editor",
    },
    "cli.help.server.mcp": {
        "ru": "сервер MCP для агента",
        "en": "MCP server for the agent",
    },
    "cli.help.server.web": {
        "ru": "веб-панель",
        "en": "web panel",
    },
    # argparse always prints its own -h/--help in English (see i18n.ArgumentParser).
    "cli.help.group.positional": {
        "ru": "аргументы",
        "en": "positional arguments",
    },
    "cli.help.group.options": {
        "ru": "параметры",
        "en": "options",
    },
    "cli.help.help": {
        "ru": "показать эту справку и выйти",
        "en": "show this help message and exit",
    },
    "cli.help.version": {
        "ru": "показать версию и выйти",
        "en": "show the version and exit",
    },
    "cli.help.commands.header": {
        "ru": "команды:",
        "en": "commands:",
    },
    "cli.help.commands.lint-name": {
        "ru": "lint <пути>",
        "en": "lint <paths>",
    },
    "cli.help.commands.lint-desc": {
        "ru": "проверить исходники – то же, что без команды",
        "en": "check the sources – the same as with no command",
    },
    "cli.help.commands.templates": {
        "ru": "шаблоны кода: list, export, import, save",
        "en": "code templates: list, export, import, save",
    },
    "cli.help.commands.self-update": {
        "ru": "обновить xbsl распаковкой колеса с PyPI",
        "en": "update xbsl by unpacking the wheel from PyPI",
    },
    "cli.help.commands.scaffold-header": {
        "ru": "скаффолдинг метаданных (создание и правка исходников):",
        "en": "metadata scaffolding (create and edit sources):",
    },
    "cli.help.commands.footer": {
        "ru": "Опции команды: xbsl <команда> --help. Опции выше относятся к режиму проверки.",
        "en": "Command options: xbsl <command> --help. The options above apply to the check mode.",
    },
    # -- help: the lsp and web servers (their own entry points, xbsl-lsp / xbsl-web) --
    "cli.help.lsp.description": {
        "ru": "LSP-сервер xbsl (stdio)",
        "en": "The xbsl LSP server (stdio)",
    },
    "cli.help.lsp.project-root": {
        "ru": "корень исходников (абсолютный или относительно папки воркспейса)",
        "en": "the source root (absolute or relative to the workspace folder)",
    },
    "cli.help.lsp.select": {
        "ru": "только эти правила (через запятую)",
        "en": "these rules only (comma-separated)",
    },
    "cli.help.lsp.ignore": {
        "ru": "исключить правила (через запятую)",
        "en": "exclude these rules (comma-separated)",
    },
    "cli.help.lsp.enable": {
        "ru": "включить правила поверх набора по умолчанию",
        "en": "enable rules on top of the default set",
    },
    "cli.help.lsp.baseline": {
        "ru": "файл базлайна (абсолютный или относительно папки воркспейса) – исключённые "
              "находки гасятся; отсутствующий файл не ошибка, он появится с первым исключением",
        "en": "the baseline file (absolute or relative to the workspace folder) – the findings "
              "frozen there are suppressed; a missing file is not an error, it appears with the "
              "first exclusion",
    },
    "cli.help.lsp.templates": {
        "ru": "файл шаблонов кода (абсолютный или относительно папки воркспейса) – "
              "дополняет встроенный набор, одноимённые шаблоны замещает",
        "en": "the code templates file (absolute or relative to the workspace folder) – it "
              "extends the builtin set and replaces templates of the same name",
    },
    "cli.help.lsp.data-dir": {
        "ru": "корень данных Элемента (папка с index.json)",
        "en": "the Element data root (the folder with index.json)",
    },
    "cli.help.lsp.lang": {
        "ru": "язык текста замечаний",
        "en": "the language of the diagnostics text",
    },
    "cli.help.web.description": {
        "ru": "Веб-интерфейс линтера XBSL",
        "en": "The XBSL linter web interface",
    },
    "cli.help.web.host": {
        "ru": "адрес (по умолчанию 127.0.0.1)",
        "en": "the address (default 127.0.0.1)",
    },
    "cli.help.web.port": {
        "ru": "порт (по умолчанию 8771)",
        "en": "the port (default 8771)",
    },
    "cli.help.mcp.description": {
        "ru": "MCP-сервер xbsl (stdio): линт, документация Элемента и скаффолдинг метаданных "
              "как инструменты агента.",
        "en": "The xbsl MCP server (stdio): linting, the Element documentation and metadata "
              "scaffolding as agent tools.",
    },
    "cli.help.mcp.epilog": {
        "ru": "Флагов нет: сервер запускается без параметров и общается по stdio.\n"
              "Язык замечаний – переменная XBSL_LANG (иначе локаль системы, иначе ru).\n"
              "Регистрация в Claude Code: claude mcp add xbsl -- xbsl-mcp",
        "en": "No flags: the server starts without parameters and talks over stdio.\n"
              "The diagnostics language follows XBSL_LANG (then the system locale, then ru).\n"
              "Registration in Claude Code: claude mcp add xbsl -- xbsl-mcp",
    },
    # -- help: self-update, templates and scaffolding sub-parsers (cli.py) --
    # These take no --lang; the language comes from XBSL_LANG / locale via current_lang().
    # XBSL identifiers stay Russian (they are the actual spellings); literal braces are doubled.
    "cli.help.selfupdate-version": {
        "ru": "целевая версия (по умолчанию – последняя с PyPI)",
        "en": "target version (default: the latest from PyPI)",
    },
    "cli.help.tpl.list-format": {
        "ru": "формат вывода: text (по умолчанию) или json",
        "en": "output format: text (default) or json",
    },
    "cli.help.tpl.description": {
        "ru": "шаблоны кода: встроенный набор и файл пользователя (формат выгрузки EDT)",
        "en": "code templates: the builtin set and the user's file (EDT export format)",
    },
    "cli.help.tpl.list": {
        "ru": "перечислить шаблоны (встроенные и пользовательские)",
        "en": "list templates (builtin and user)",
    },
    "cli.help.tpl.export": {
        "ru": "выгрузить шаблоны в файл формата EDT",
        "en": "export templates to an EDT-format file",
    },
    "cli.help.tpl.export-output": {
        "ru": "куда писать выгрузку",
        "en": "where to write the export",
    },
    "cli.help.tpl.export-custom-only": {
        "ru": "только шаблоны пользователя, без встроенных",
        "en": "user templates only, without the builtin ones",
    },
    "cli.help.tpl.import": {
        "ru": "влить выгрузку в файл шаблонов пользователя",
        "en": "merge an export into the user's templates file",
    },
    "cli.help.tpl.import-source": {
        "ru": "выгрузка (наша или из 1С:EDT)",
        "en": "an export (ours or from 1C:EDT)",
    },
    "cli.help.tpl.save": {
        "ru": "заменить файл шаблонов пользователя (конверт JSON из stdin)",
        "en": "replace the user's templates file (a JSON envelope from stdin)",
    },
    "cli.help.tpl.file": {
        "ru": "файл шаблонов пользователя (по умолчанию {path}); "
              "дополняет встроенный набор, одноимённые шаблоны замещает",
        "en": "the user's templates file (default {path}); "
              "it extends the builtin set and overrides same-named templates",
    },
    "cli.help.scaf.description": {
        "ru": "Скаффолдинг метаданных 1С:Элемент (вывод – JSON)",
        "en": "1C:Element metadata scaffolding (output – JSON)",
    },
    "cli.help.scaf.new-project": {
        "ru": "создать проект: Проект.yaml + Проект.xbsl + подсистема",
        "en": "create a project: Проект.yaml + Проект.xbsl + a subsystem",
    },
    # -- scaffolding positionals and flags --
    "cli.help.scaf.arg.project-root": {
        "ru": "корень проекта – каталог с Проект.yaml (обычно .)",
        "en": "the project root – the folder with Проект.yaml (usually .)",
    },
    "cli.help.scaf.arg.form-yaml": {
        "ru": "yaml формы",
        "en": "the form yaml",
    },
    "cli.help.scaf.arg.object-name": {
        "ru": "имя объекта в проекте",
        "en": "the object name in the project",
    },
    "cli.help.scaf.np-root": {
        "ru": "каталог, в котором появится пара поставщик/имя (обычно .)",
        "en": "the directory where the vendor/name pair will appear (usually .)",
    },
    "cli.help.scaf.np-vendor": {
        "ru": "поставщик – первая часть пространства имён проекта",
        "en": "the vendor – the first part of the project namespace",
    },
    "cli.help.scaf.np-name": {
        "ru": "имя проекта; так же называется его каталог",
        "en": "the project name; its folder takes the same name",
    },
    "cli.help.scaf.np-representation": {
        "ru": "представление проекта в интерфейсе (по умолчанию – имя)",
        "en": "the project presentation in the interface (defaults to the name)",
    },
    "cli.help.scaf.np-version": {
        "ru": "версия проекта, три числа (по умолчанию 1.0.0)",
        "en": "the project version, three numbers (default 1.0.0)",
    },
    "cli.help.scaf.np-compatibility": {
        "ru": "версия платформы, с которой совместим проект (по умолчанию 9.0)",
        "en": "the platform version the project is compatible with (default 9.0)",
    },
    "cli.help.scaf.np-subsystem": {
        "ru": "имя первой подсистемы (по умолчанию Основное)",
        "en": "the name of the first subsystem (default Основное)",
    },
    "cli.help.scaf.np-library": {
        "ru": "создать библиотеку (ВидПроекта: Библиотека), а не приложение",
        "en": "create a library (ВидПроекта: Библиотека) rather than an application",
    },
    "cli.help.scaf.no-directory": {
        "ru": "каталог подсистемы, в котором создать объект",
        "en": "the subsystem folder to create the object in",
    },
    "cli.help.scaf.no-kind": {
        "ru": "вид объекта на языке проекта: Справочник, Документ, ВиртуальнаяТаблица, ...; "
              "неизвестный вид перечислит доступные",
        "en": "the object kind in the project language: Справочник, Документ, "
              "ВиртуальнаяТаблица, ...; an unknown kind lists what is available",
    },
    "cli.help.scaf.no-name": {
        "ru": "имя объекта",
        "en": "the object name",
    },
    "cli.help.scaf.no-scope": {
        "ru": "область видимости; по умолчанию платформенная ВПодсистеме",
        "en": "the visibility scope; the platform default is ВПодсистеме",
    },
    "cli.help.scaf.no-environment": {
        "ru": "окружение – для ОбщийМодуль и Структура",
        "en": "the environment – for ОбщийМодуль and Структура",
    },
    "cli.help.scaf.no-access": {
        "ru": "способ доступа: у HttpСервис пишется в Разрешения.Вызов, у объектов данных – "
              "в Разрешения.ПоУмолчанию (отдельные права ставит set-access)",
        "en": "the access method: for HttpСервис it goes to Разрешения.Вызов, for data "
              "objects to Разрешения.ПоУмолчанию (individual rights are set by set-access)",
    },
    "cli.help.scaf.af-yaml": {
        "ru": "yaml объекта, в который добавить поле",
        "en": "the yaml of the object to add the field to",
    },
    "cli.help.scaf.af-name": {
        "ru": "имя поля",
        "en": "the field name",
    },
    "cli.help.scaf.af-type": {
        "ru": "тип поля (по умолчанию Строка)",
        "en": "the field type (default Строка)",
    },
    "cli.help.scaf.ar-yaml": {
        "ru": "yaml HttpСервис, в который добавить маршруты",
        "en": "the yaml of the HttpСервис to add the routes to",
    },
    "cli.help.scaf.ar-routes": {
        "ru": 'маршруты через запятую: "DELETE /{{id}}, GET /health"',
        "en": 'the routes, comma-separated: "DELETE /{{id}}, GET /health"',
    },
    "cli.help.scaf.am-module": {
        "ru": "модуль .xbsl, в который добавить метод",
        "en": "the .xbsl module to add the method to",
    },
    "cli.help.scaf.am-name": {
        "ru": "имя метода",
        "en": "the method name",
    },
    "cli.help.scaf.af2-name": {
        "ru": "имя объекта, для которого создать формы",
        "en": "the object to create the forms for",
    },
    "cli.help.scaf.af2-overwrite": {
        "ru": "перезаписать формы, если они уже созданы",
        "en": "overwrite the forms if they already exist",
    },
    "cli.help.scaf.as-parent": {
        "ru": "каталог, внутри которого создать подсистему",
        "en": "the folder to create the subsystem inside",
    },
    "cli.help.scaf.as-name": {
        "ru": "имя подсистемы",
        "en": "the subsystem name",
    },
    "cli.help.scaf.as-representation": {
        "ru": "представление подсистемы в интерфейсе",
        "en": "the subsystem presentation in the interface",
    },
    "cli.help.scaf.as-no-auto-interface": {
        "ru": "не включать подсистему в автоинтерфейс",
        "en": "keep the subsystem out of the auto-interface",
    },
    "cli.help.scaf.ro-old": {
        "ru": "текущее имя объекта",
        "en": "the object's current name",
    },
    "cli.help.scaf.ro-new": {
        "ru": "новое имя – переименуются и файлы, и ссылки по проекту",
        "en": "the new name – both the files and the project-wide references are renamed",
    },
    "cli.help.scaf.meta.form-op": {
        "ru": "операция",
        "en": "operation",
    },
    "cli.help.scaf.new-object": {
        "ru": "создать объект конфигурации (yaml + модуль по виду)",
        "en": "create a configuration object (yaml + a module by kind)",
    },
    "cli.help.scaf.new-object-routes": {
        "ru": 'маршруты HttpСервис: "GET /, POST /, GET /{{id}}"',
        "en": 'HttpСервис routes: "GET /, POST /, GET /{{id}}"',
    },
    "cli.help.scaf.new-object-report": {
        "ru": "описание отчёта (JSON: source, rows, columns, measures)",
        "en": "report description (JSON: source, rows, columns, measures)",
    },
    "cli.help.scaf.add-field": {
        "ru": "добавить реквизит/измерение/ресурс/значение/ТЧ",
        "en": "add an attribute/dimension/resource/value/tabular section",
    },
    "cli.help.scaf.add-field-tabular": {
        "ru": "имя табличной части (реквизит добавляется в неё)",
        "en": "tabular section name (the attribute is added into it)",
    },
    "cli.help.scaf.add-route": {
        "ru": "добавить маршруты в существующий HttpСервис",
        "en": "add routes to an existing HttpСервис",
    },
    "cli.help.scaf.add-method": {
        "ru": "добавить метод в модуль .xbsl, не разрывая аннотации",
        "en": "add a method to an .xbsl module without breaking annotations",
    },
    "cli.help.scaf.add-method-params": {
        "ru": "список параметров как в сигнатуре",
        "en": "parameter list as in the signature",
    },
    "cli.help.scaf.add-method-returns": {
        "ru": "тип возвращаемого значения",
        "en": "return value type",
    },
    "cli.help.scaf.add-method-annotations": {
        "ru": "аннотации через пробел, например 'НаСервере ВПроекте'",
        "en": "annotations separated by spaces, e.g. 'НаСервере ВПроекте'",
    },
    "cli.help.scaf.add-method-after": {
        "ru": "вставить после этого метода",
        "en": "insert after this method",
    },
    "cli.help.scaf.add-method-before": {
        "ru": "вставить перед этим методом",
        "en": "insert before this method",
    },
    "cli.help.scaf.add-method-body": {
        "ru": "одна строка тела вместо заготовки // TODO",
        "en": "a one-line body instead of the // TODO stub",
    },
    "cli.help.scaf.add-form": {
        "ru": "создать формы объекта и зарегистрировать в Интерфейс",
        "en": "create the object's forms and register them in Интерфейс",
    },
    "cli.help.scaf.yaml-vs-name": {
        "ru": "yaml объекта (вместо --name)",
        "en": "the object's yaml (instead of --name)",
    },
    "cli.help.scaf.add-form-forms": {
        "ru": "подмножество object,list,list-cards,report через запятую "
              "(list-cards – список карточками, вместо list)",
        "en": "a subset object,list,list-cards,report comma-separated "
              "(list-cards – a card list, instead of list)",
    },
    "cli.help.scaf.add-form-card-min-width": {
        "ru": "ширина колонки сетки карточек (по умолчанию 400, с фото – 250)",
        "en": "card grid column width (default 400, 250 with a photo)",
    },
    "cli.help.scaf.add-form-card-placeholder": {
        "ru": 'выражение картинки-заглушки, напр. "Ресурс{{Аккаунт.svg}}.Ссылка"',
        "en": 'placeholder image expression, e.g. "Ресурс{{Аккаунт.svg}}.Ссылка"',
    },
    "cli.help.scaf.add-subsystem": {
        "ru": "создать подсистему (папка + Подсистема.yaml)",
        "en": "create a subsystem (a folder + Подсистема.yaml)",
    },
    "cli.help.scaf.add-subsystem-uses": {
        "ru": "имена подсистем через запятую",
        "en": "subsystem names, comma-separated",
    },
    "cli.help.scaf.add-dependency": {
        "ru": "подключить библиотеку к проекту (раздел Библиотеки Проект.yaml)",
        "en": "attach a library to the project (the Библиотеки section of Проект.yaml)",
    },
    "cli.help.scaf.add-dependency-vendor": {
        "ru": "поставщик библиотеки",
        "en": "library vendor",
    },
    "cli.help.scaf.add-dependency-name": {
        "ru": "имя библиотеки",
        "en": "library name",
    },
    "cli.help.scaf.add-dependency-version": {
        "ru": "версия релиза библиотеки, например 2.0",
        "en": "library release version, e.g. 2.0",
    },
    "cli.help.scaf.add-dependency-path": {
        "ru": "Проект.yaml (при нескольких проектах под корнем)",
        "en": "Проект.yaml (when there are several projects under the root)",
    },
    "cli.help.scaf.rename-object": {
        "ru": "переименовать объект (файлы, формы) и обновить ссылки по всему проекту",
        "en": "rename an object (files, forms) and update references across the whole project",
    },
    "cli.help.scaf.rename-new-presentation": {
        "ru": "новое Представление/Заголовок (по умолчанию – новое имя)",
        "en": "new Представление/Заголовок (default: the new name)",
    },
    "cli.help.scaf.rename-old-presentation": {
        "ru": "старое представление (для замены в Заголовок/Представление)",
        "en": "the old presentation (to replace in Заголовок/Представление)",
    },
    "cli.help.scaf.rename-path": {
        "ru": "yaml объекта (при нескольких объектах с одним именем)",
        "en": "the object's yaml (when several objects share one name)",
    },
    "cli.help.scaf.set-access": {
        "ru": "задать КонтрольДоступа.Разрешения объекта",
        "en": "set the object's КонтрольДоступа.Разрешения",
    },
    "cli.help.scaf.set-access-default": {
        "ru": "способ для права ПоУмолчанию",
        "en": "the method for the ПоУмолчанию right",
    },
    "cli.help.scaf.set-access-permission": {
        "ru": "способ отдельного права (повторяемый), напр. Чтение=РазрешеноВсем",
        "en": "the method for a single right (repeatable), e.g. Чтение=РазрешеноВсем",
    },
    "cli.help.scaf.set-access-calc-by": {
        "ru": "поля РасчетРазрешенийПо через запятую "
              "(обязательны для РазрешенияВычисляютсяДляКаждогоОбъекта)",
        "en": "РасчетРазрешенийПо fields, comma-separated "
              "(required for РазрешенияВычисляютсяДляКаждогоОбъекта)",
    },
    "cli.help.scaf.meta.right-method": {
        "ru": "ПРАВО=СПОСОБ",
        "en": "RIGHT=METHOD",
    },
    "cli.help.scaf.object-info": {
        "ru": "сводка объекта: реквизиты, ТЧ, формы, namespace",
        "en": "object summary: attributes, tabular sections, forms, namespace",
    },
    "cli.help.scaf.project-info": {
        "ru": "обзор исходников: проекты, подсистемы, объекты",
        "en": "sources overview: projects, subsystems, objects",
    },
    "cli.help.scaf.form-tree": {
        "ru": "дерево компонента интерфейса (узлы, слоты, свойства со спанами)",
        "en": "interface component tree (nodes, slots, properties with spans)",
    },
    "cli.help.scaf.form-tree-at": {
        "ru": "вместо дерева вернуть узел по смещению в файле (синхронизация курсора)",
        "en": "instead of the tree, return the node at a file offset (cursor sync)",
    },
    "cli.help.scaf.meta.offset": {
        "ru": "СМЕЩЕНИЕ",
        "en": "OFFSET",
    },
    "cli.help.scaf.form-edit": {
        "ru": "операция конструктора форм: точечная правка yaml компонента интерфейса",
        "en": "form-designer operation: a pinpoint edit of an interface component's yaml",
    },
    "cli.help.scaf.fe-parent": {
        "ru": "id узла-контейнера (insert/insert-fragment)",
        "en": "container node id (insert/insert-fragment)",
    },
    "cli.help.scaf.fe-slot": {
        "ru": "слот детей: Содержимое, Страницы, Колонки, ... (insert/move)",
        "en": "children slot: Содержимое, Страницы, Колонки, ... (insert/move)",
    },
    "cli.help.scaf.fe-type": {
        "ru": "Тип нового компонента (insert) или свойства (property-add)",
        "en": "Тип of the new component (insert) or property (property-add)",
    },
    "cli.help.scaf.fe-name": {
        "ru": "Имя нового компонента (insert), обёртки (wrap) или свойства секции Свойства (property-*)",
        "en": "Имя of the new component (insert), the wrapper (wrap) or a Свойства-section property (property-*)",
    },
    "cli.help.scaf.fe-node": {
        "ru": "id узла операции (move/remove/wrap/unwrap/duplicate/rename/set-property/reset-property)",
        "en": "operation node id (move/remove/wrap/unwrap/duplicate/rename/set-property/reset-property)",
    },
    "cli.help.scaf.fe-nodes": {
        "ru": "id узлов пачковой операции (move-nodes/remove-nodes): через "
              "запятую или повтором флага; порядок не важен",
        "en": "node ids of a batch operation (move-nodes/remove-nodes): comma-separated "
              "or by repeating the flag; order does not matter",
    },
    "cli.help.scaf.fe-new-parent": {
        "ru": "id нового контейнера (move/move-nodes)",
        "en": "new container id (move/move-nodes)",
    },
    "cli.help.scaf.fe-container": {
        "ru": "Тип контейнера-обёртки (wrap)",
        "en": "Тип of the wrapper container (wrap)",
    },
    "cli.help.scaf.fe-new-name": {
        "ru": "новое Имя узла (rename) или свойства (property-rename); "
              "для rename без флага Имя удаляется",
        "en": "the node's new Имя (rename) or property's (property-rename); "
              "for rename without the flag, Имя is removed",
    },
    "cli.help.scaf.fe-before": {
        "ru": "id соседа: вставить/переместить ПЕРЕД ним",
        "en": "sibling id: insert/move BEFORE it",
    },
    "cli.help.scaf.fe-after": {
        "ru": "id соседа: вставить/переместить ПОСЛЕ него",
        "en": "sibling id: insert/move AFTER it",
    },
    "cli.help.scaf.fe-key": {
        "ru": "имя свойства узла (set-property/reset-property)",
        "en": "node property name (set-property/reset-property)",
    },
    "cli.help.scaf.fe-value": {
        "ru": "скалярное значение или биндинг (set-property)",
        "en": "scalar value or binding (set-property)",
    },
    "cli.help.scaf.fe-value-yaml": {
        "ru": "составное значение готовым yaml-фрагментом (set-property)",
        "en": "a composite value as a ready yaml fragment (set-property)",
    },
    "cli.help.scaf.fe-fragment": {
        "ru": 'yaml-блок компонента или нескольких – список "-" или блоки подряд (insert-fragment)',
        "en": 'a yaml block of one component or several – a "-" list or blocks in a row (insert-fragment)',
    },
    "cli.help.scaf.fe-fragment-file": {
        "ru": "файл с yaml-блоком компонента (insert-fragment, вместо --fragment)",
        "en": "a file with a component's yaml block (insert-fragment, instead of --fragment)",
    },
    "cli.help.scaf.fe-new-type": {
        "ru": "новый Тип свойства (property-retype)",
        "en": "the property's new Тип (property-retype)",
    },
    "cli.help.scaf.form-handlers": {
        "ru": "обработчики парного модуля компонента: список методов или заготовка обработчика",
        "en": "handlers of the component's paired module: a method list or a handler stub",
    },
    "cli.help.scaf.fh-node": {
        "ru": "id узла (создание обработчика; без --node/--key – список методов модуля)",
        "en": "node id (handler creation; without --node/--key – the module's method list)",
    },
    "cli.help.scaf.fh-key": {
        "ru": "ключ события узла: ПриНажатии, ПослеСоздания, ...",
        "en": "node event key: ПриНажатии, ПослеСоздания, ...",
    },
    "cli.help.scaf.fh-method": {
        "ru": "имя метода-обработчика (по умолчанию <Имя узла><Ключ>; "
              "существующий метод – только привязка в yaml)",
        "en": "handler method name (default <Имя узла><Ключ>; "
              "an existing method – only the binding in yaml)",
    },
    "cli.help.scaf.fh-signature": {
        "ru": 'сигнатура события из ui-схемы, напр. '
              '"(Кнопка, СобытиеПриНажатии)->ничто" (без флага ищется в локальных данных)',
        "en": 'event signature from the ui schema, e.g. '
              '"(Кнопка, СобытиеПриНажатии)->ничто" (without the flag it is looked up in the local data)',
    },
    "cli.help.scaf.dry-run": {
        "ru": "показать изменения (с текстами файлов), ничего не записывая",
        "en": "show the changes (with file texts) without writing anything",
    },
}


class MessageError(RuntimeError):
    pass


def _register_core() -> None:
    """Register the adapters' own messages. Called on import; safe to call again."""
    register(_CORE_MESSAGES)


def register(messages: dict[str, dict[str, str]]) -> None:
    """Add messages to the catalog. Every key must carry every language of LANGS."""
    for key, per_lang in messages.items():
        missing = [lang for lang in LANGS if lang not in per_lang]
        if missing:
            raise MessageError(f"Message '{key}' has no translation for: {', '.join(missing)}")
        known = _catalog.get(key)
        if known is not None and known != per_lang:
            raise MessageError(f"Message '{key}' is already registered with a different wording")
        _catalog[key] = dict(per_lang)


def registered_keys() -> list[str]:
    return sorted(_catalog)


def translations(key: str) -> dict[str, str] | None:
    entry = _catalog.get(key)
    return dict(entry) if entry else None


def set_lang(lang: str | None) -> None:
    """Pin the output language for the process (CLI --lang). None restores the lookup order."""
    global _selected
    if lang is not None and lang not in LANGS:
        raise MessageError(f"Unknown language '{lang}'. Available: {', '.join(LANGS)}")
    _selected = lang


def lang_from_argv(argv) -> str | None:
    """Read --lang out of raw argv, before the parser is built.

    The parser is built with translated help=, but argparse learns --lang only when it parses –
    too late to choose the help language. So the value is scanned out of argv beforehand.
    Accepts "--lang en" and "--lang=en". A value outside LANGS returns None: the language stays
    at its default and argparse rejects the bad value with its own message. env / locale need no
    prescan – t() already reads them through current_lang() when the parser is built.
    """
    for i, arg in enumerate(argv):
        value = None
        if arg == "--lang" and i + 1 < len(argv):
            value = argv[i + 1]
        elif arg.startswith("--lang="):
            value = arg[len("--lang="):]
        if value is not None:
            return value if value in LANGS else None
    return None


def _system_lang() -> str | None:
    code = ""
    try:
        code = _locale.getlocale()[0] or ""
    except (ValueError, TypeError):
        pass
    code = (code or os.environ.get("LC_ALL") or os.environ.get("LANG") or "").lower()
    # "ru_RU.UTF-8" and Windows' "Russian_Russia" both start with the language code.
    for lang in LANGS:
        if code.startswith(lang):
            return lang
    return None


def current_lang() -> str:
    if _selected is not None:
        return _selected
    env = os.environ.get(ENV_LANG, os.environ.get(_ENV_LANG_LEGACY, "")).strip().lower()
    if env in LANGS:
        return env
    return _system_lang() or DEFAULT_LANG


def t(key: str, /, **fields) -> str:
    """Translate a key and substitute the fields. An unknown key is returned unchanged.

    A template is always run through str.format, so a literal brace must be doubled: `{{}}`.
    Formatting conditionally – only when fields are passed – would turn a literal brace into a
    field the day someone adds one, and the failure would surface as a crash in a rule.
    """
    entry = _catalog.get(key)
    if entry is None:
        return key
    template = entry.get(current_lang()) or entry[DEFAULT_LANG]
    return template.format(**fields)


class ArgumentParser(_argparse.ArgumentParser):
    """An ArgumentParser whose own `-h/--help` and group titles are translated.

    argparse takes those strings from its gettext catalog, i.e. always in English: in a
    Russian help screen the `-h, --help` line and the "options" / "positional arguments"
    headings stayed in the wrong language. Nested parsers inherit the parent's class
    (`add_subparsers` passes `parser_class=type(self)`), so building the root one with
    this class is enough.
    """

    def __init__(self, *, add_help: bool = True, **kwargs) -> None:
        # Keyword-only, and add_help is forced through kwargs: an explicit keyword next to
        # *args trips mypy's multiple-values check and fails the mypyc wheel build.
        kwargs["add_help"] = False
        super().__init__(**kwargs)
        self._positionals.title = t("cli.help.group.positional")
        self._optionals.title = t("cli.help.group.options")
        if add_help:
            self.add_argument("-h", "--help", action="help", help=t("cli.help.help"))


_register_core()
