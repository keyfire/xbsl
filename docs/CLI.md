---
title: "Commands"
description: "Reference of xbsl commands and options: checking sources, the LSP and MCP servers, the web panel, code templates."
sidebar:
  label: Commands
  order: 3
---

<!-- Собрано из вывода `xbsl --help` скриптом scripts/gen-cli-docs.py. Не редактировать вручную. -->

This reference is generated from the tool itself – the same text `xbsl --help` prints, gathered on one page.

With no command `xbsl` checks the paths you give it: that is the default mode and its options are in the first block. The other commands address the rest of the toolkit.

The output language follows `--lang`, the `XBSL_LANG` variable, or the system locale.

## No command: checking sources

Linter for 1C:Element sources (.yaml/.xbsl pairs).

```bash
usage: xbsl [paths] [options]       (no command: check the sources)
       xbsl <command> [options]
```

**Arguments**

| Option | Description |
|---|---|
| `paths` | files or directories to check |

**Options**

| Option | Description |
|---|---|
| `-h, --help` | show this help message and exit |
| `--select ID/GROUP/TIER` | check only these rules (comma-separated or by repeating the flag: id, group – the part of the id before '/' (e.g. style) – or a tier letter A/B/C/D) |
| `--ignore ID/GROUP/TIER` | exclude these rules (comma-separated or by repeating the flag: id, group or tier letter) |
| `--enable ID/GROUP/TIER` | add rules disabled by default ON TOP of the standard set (`--select` replaces the set); the value forms are the same |
| `--baseline FILE` | suppress findings frozen in a baseline file (created by `--write-baseline`); new findings are reported as usual |
| `--write-baseline FILE` | instead of a report, write all current findings to a baseline file (freeze the debt; paths in the file are relative to its directory) |
| `--stale-baseline` | list the baseline entries that no longer suppress anything (together with `--baseline`) |
| `--prune-baseline` | list the stale baseline entries and remove them from the file (together with `--baseline`; the counts of live entries are left alone) |
| `--fix` | fix mechanical findings in place (trailing spaces, typographic characters, line endings) and report the rest; only unambiguous fixes |
| `--jobs N` | processes for file-scope rules: 0 – auto (kicks in on large runs), 1 – sequential, N – an explicit worker count |
| `--list-rules` | print the list of rules and exit |
| `--where` | show the Element data root (path, source, versions) and exit |
| `--element-version VERSION` | Element data version (default: the latest in the bundle) |
| `--data-dir DIR` | Element data root (a directory with index.json); also env XBSL_DATA_DIR |
| `--lang {ru,en}` | linter output language (default: env XBSL_LANG / system locale / ru) |
| `--format {text,json,codeclimate}` | output format: text (default), json (machine-readable: diagnostics + summary) or codeclimate (a GitLab Code Quality report – the merge request widget) |
| `--stdin` | check a single buffer from stdin (for editor integration); `--filename` sets the file kind and the reported path |
| `--index` | instead of checking, print a JSON project index (objects, methods, form components) for editor navigation; the path is the project root |
| `--filename NAME` | name of the buffer checked with `--stdin` (e.g. Форма.xbsl); the extension sets the file kind |
| `--version` | show the version and exit |

**Commands**

| Command | Description |
|---|---|
| `lint <paths>` | check the sources – the same as with no command |
| `lsp` | LSP server for the editor |
| `mcp` | MCP server for the agent |
| `web` | web panel |
| `templates` | code templates: list, export, import, save |
| `extract` | generate the language data from an Element distribution (`--dist`) |
| `data-diff` | compare two data versions: what changed in the platform |
| `self-update` | update xbsl by unpacking the wheel from PyPI |

Command options: xbsl &lt;command&gt; `--help`. The options above apply to the check mode.

## `xbsl lsp`

The xbsl LSP server (stdio)

```bash
usage: xbsl-lsp [-h] [--project-root PROJECT_ROOT] [--select SELECT] [--ignore IGNORE]
                [--enable ENABLE] [--baseline BASELINE] [--templates TEMPLATES]
                [--data-dir DATA_DIR] [--lang {ru,en}]
```

**Options**

| Option | Description |
|---|---|
| `-h, --help` | show this help message and exit |
| `--project-root PROJECT_ROOT` | the source root (absolute or relative to the workspace folder) |
| `--select SELECT` | these rules only (comma-separated) |
| `--ignore IGNORE` | exclude these rules (comma-separated) |
| `--enable ENABLE` | enable rules on top of the default set |
| `--baseline BASELINE` | the baseline file (absolute or relative to the workspace folder) – the findings frozen there are suppressed; a missing file is not an error, it appears with the first exclusion |
| `--templates TEMPLATES` | the code templates file (absolute or relative to the workspace folder) – it extends the builtin set and replaces templates of the same name |
| `--data-dir DATA_DIR` | the Element data root (the folder with index.json) |
| `--lang {ru,en}` | the language of the diagnostics text |

## `xbsl mcp`

The xbsl MCP server (stdio): linting, the Element documentation and metadata scaffolding as agent tools.

```bash
usage: xbsl-mcp [-h]
```

**Options**

| Option | Description |
|---|---|
| `-h, --help` | show this help message and exit |

No flags: the server starts without parameters and talks over stdio. The diagnostics language follows XBSL_LANG (then the system locale, then ru). Registration in Claude Code: claude mcp add xbsl -- xbsl-mcp

## `xbsl web`

The XBSL linter web interface

```bash
usage: xbsl-web [-h] [--host HOST] [--port PORT]
```

**Options**

| Option | Description |
|---|---|
| `-h, --help` | show this help message and exit |
| `--host HOST` | the address (default 127.0.0.1) |
| `--port PORT` | the port (default 8771) |

## `xbsl templates`

code templates: the builtin set and the user's file (EDT export format)

```bash
usage: xbsl templates [-h] {list,export,import,save} ...
```

**Arguments**

| Option | Description |
|---|---|
| `list` | list templates (builtin and user) |
| `export` | export templates to an EDT-format file |
| `import` | merge an export into the user's templates file |
| `save` | replace the user's templates file (a JSON envelope from stdin) |

**Options**

| Option | Description |
|---|---|
| `-h, --help` | show this help message and exit |

### `xbsl templates list`

```bash
usage: xbsl templates list [-h] [--format {text,json}] [--file FILE]
```

**Options**

| Option | Description |
|---|---|
| `-h, --help` | show this help message and exit |
| `--format {text,json}` | output format: text (default) or json |
| `--file FILE` | the user's templates file (default .xbsl-templates.json); it extends the builtin set and overrides same-named templates |

### `xbsl templates export`

```bash
usage: xbsl templates export [-h] --output OUTPUT [--custom-only] [--file FILE]
```

**Options**

| Option | Description |
|---|---|
| `-h, --help` | show this help message and exit |
| `--output OUTPUT` | where to write the export |
| `--custom-only` | user templates only, without the builtin ones |
| `--file FILE` | the user's templates file (default .xbsl-templates.json); it extends the builtin set and overrides same-named templates |

### `xbsl templates import`

```bash
usage: xbsl templates import [-h] [--file FILE] source
```

**Arguments**

| Option | Description |
|---|---|
| `source` | an export (ours or from 1C:EDT) |

**Options**

| Option | Description |
|---|---|
| `-h, --help` | show this help message and exit |
| `--file FILE` | the user's templates file (default .xbsl-templates.json); it extends the builtin set and overrides same-named templates |

### `xbsl templates save`

```bash
usage: xbsl templates save [-h] [--file FILE]
```

**Options**

| Option | Description |
|---|---|
| `-h, --help` | show this help message and exit |
| `--file FILE` | the user's templates file (default .xbsl-templates.json); it extends the builtin set and overrides same-named templates |

## `xbsl self-update`

update xbsl by unpacking the wheel from PyPI

```bash
usage: xbsl self-update [-h] [--version VERSION] [--stop-holders]
```

**Options**

| Option | Description |
|---|---|
| `-h, --help` | show this help message and exit |
| `--version VERSION` | target version (default: the latest from PyPI) |
| `--stop-holders` | stop the processes holding the installation (the editor's LSP server, MCP sessions) and update; without the flag the command only names them |

## Metadata scaffolding

These commands create and edit sources: objects, fields, routes, methods, forms, subsystems. Each prints its result as JSON and lints what it wrote; `--dry-run` computes the changes without touching the files.

### `xbsl new-project`

```bash
usage: xbsl new-project [-h] [--representation REPRESENTATION] [--version VERSION]
                        [--compatibility COMPATIBILITY] [--subsystem SUBSYSTEM] [--library]
                        [--dry-run]
                        root vendor name
```

**Arguments**

| Option | Description |
|---|---|
| `root` | the directory where the vendor/name pair will appear (usually .) |
| `vendor` | the vendor – the first part of the project namespace |
| `name` | the project name; its folder takes the same name |

**Options**

| Option | Description |
|---|---|
| `-h, --help` | show this help message and exit |
| `--representation REPRESENTATION` | the project presentation in the interface (defaults to the name) |
| `--version VERSION` | the project version, three numbers (default 1.0.0) |
| `--compatibility COMPATIBILITY` | the platform version the project is compatible with (default 9.0) |
| `--subsystem SUBSYSTEM` | the name of the first subsystem (default Основное) |
| `--library` | create a library (ВидПроекта: Библиотека) rather than an application |
| `--dry-run` | show the changes (with file texts) without writing anything |

### `xbsl new-object`

```bash
usage: xbsl new-object [-h] [--scope SCOPE] [--environment ENVIRONMENT] [--access ACCESS]
                       [--routes ROUTES] [--report REPORT] [--presentation PRESENTATION]
                       [--dry-run]
                       directory kind name
```

**Arguments**

| Option | Description |
|---|---|
| `directory` | the subsystem folder to create the object in |
| `kind` | the object kind in the project language: Справочник, Документ, ВиртуальнаяТаблица, ...; an unknown kind lists what is available |
| `name` | the object name |

**Options**

| Option | Description |
|---|---|
| `-h, --help` | show this help message and exit |
| `--scope SCOPE` | the visibility scope; the platform default is ВПодсистеме |
| `--environment ENVIRONMENT` | the environment – for ОбщийМодуль and Структура |
| `--access ACCESS` | the access method: for HttpСервис it goes to Разрешения.Вызов, for data objects to Разрешения.ПоУмолчанию (individual rights are set by set-access) |
| `--routes ROUTES` | HttpСервис routes: "GET /, POST /, GET /{id}" |
| `--report REPORT` | report description (JSON: source, rows, columns, measures) |
| `--presentation PRESENTATION` | Presentation – the element caption (without it the very first lint answers naming/presentation) |
| `--dry-run` | show the changes (with file texts) without writing anything |

### `xbsl add-field`

```bash
usage: xbsl add-field [-h] [--type TYPE] [--tabular TABULAR] [--prop КЛЮЧ=ЗНАЧЕНИЕ] [--dry-run]
                      yaml_path field_kind name
```

**Arguments**

| Option | Description |
|---|---|
| `yaml_path` | the yaml of the object to add the field to |
| `field_kind` | реквизит, измерение, ресурс, значение, параметр, поле, табличная-часть |
| `name` | the field name |

**Options**

| Option | Description |
|---|---|
| `-h, --help` | show this help message and exit |
| `--type TYPE` | the field type (default Строка) |
| `--tabular TABULAR` | tabular section name (the attribute is added into it) |
| `--prop КЛЮЧ=ЗНАЧЕНИЕ` | an item property (repeatable): DefaultValue=https://example.com, Presentation=Service address |
| `--dry-run` | show the changes (with file texts) without writing anything |

### `xbsl add-route`

```bash
usage: xbsl add-route [-h] [--dry-run] yaml_path routes
```

**Arguments**

| Option | Description |
|---|---|
| `yaml_path` | the yaml of the HttpСервис to add the routes to |
| `routes` | the routes, comma-separated: "DELETE /{id}, GET /health" |

**Options**

| Option | Description |
|---|---|
| `-h, --help` | show this help message and exit |
| `--dry-run` | show the changes (with file texts) without writing anything |

### `xbsl add-method`

```bash
usage: xbsl add-method [-h] [--params PARAMS] [--returns RETURNS] [--annotations ANNOTATIONS]
                       [--after AFTER] [--before BEFORE] [--body BODY] [--dry-run]
                       module_path name
```

**Arguments**

| Option | Description |
|---|---|
| `module_path` | the .xbsl module to add the method to |
| `name` | the method name |

**Options**

| Option | Description |
|---|---|
| `-h, --help` | show this help message and exit |
| `--params PARAMS` | parameter list as in the signature |
| `--returns RETURNS` | return value type |
| `--annotations ANNOTATIONS` | annotations separated by spaces, e.g. 'НаСервере ВПроекте' |
| `--after AFTER` | insert after this method |
| `--before BEFORE` | insert before this method |
| `--body BODY` | a one-line body instead of the // TODO stub |
| `--dry-run` | show the changes (with file texts) without writing anything |

### `xbsl add-form`

```bash
usage: xbsl add-form [-h] [--name NAME] [--path PATH] [--forms FORMS]
                     [--card-min-width CARD_MIN_WIDTH] [--card-placeholder CARD_PLACEHOLDER]
                     [--overwrite] [--dry-run]
                     root
```

**Arguments**

| Option | Description |
|---|---|
| `root` | the project root – the folder with Проект.yaml (usually .) |

**Options**

| Option | Description |
|---|---|
| `-h, --help` | show this help message and exit |
| `--name NAME` | the object to create the forms for |
| `--path PATH` | the object's yaml (instead of `--name`) |
| `--forms FORMS` | a subset object,list,list-cards,report,processing comma-separated (list-cards – a card list, instead of list; processing – a data processor form) |
| `--card-min-width CARD_MIN_WIDTH` | card grid column width (default 400, 250 with a photo) |
| `--card-placeholder CARD_PLACEHOLDER` | placeholder image expression, e.g. "Ресурс{Аккаунт.svg}.Ссылка" |
| `--overwrite` | overwrite the forms if they already exist |
| `--dry-run` | show the changes (with file texts) without writing anything |

### `xbsl add-subsystem`

```bash
usage: xbsl add-subsystem [-h] [--representation REPRESENTATION] [--no-auto-interface]
                          [--uses USES] [--dry-run]
                          parent_dir name
```

**Arguments**

| Option | Description |
|---|---|
| `parent_dir` | the folder to create the subsystem inside |
| `name` | the subsystem name |

**Options**

| Option | Description |
|---|---|
| `-h, --help` | show this help message and exit |
| `--representation REPRESENTATION` | the subsystem presentation in the interface |
| `--no-auto-interface` | keep the subsystem out of the auto-interface |
| `--uses USES` | subsystem names, comma-separated |
| `--dry-run` | show the changes (with file texts) without writing anything |

### `xbsl add-dependency`

```bash
usage: xbsl add-dependency [-h] [--path PATH] [--dry-run] root vendor name version
```

**Arguments**

| Option | Description |
|---|---|
| `root` | the project root – the folder with Проект.yaml (usually .) |
| `vendor` | library vendor |
| `name` | library name |
| `version` | library release version, e.g. 2.0 |

**Options**

| Option | Description |
|---|---|
| `-h, --help` | show this help message and exit |
| `--path PATH` | Проект.yaml (when there are several projects under the root) |
| `--dry-run` | show the changes (with file texts) without writing anything |

### `xbsl add-localization`

```bash
usage: xbsl add-localization [-h] [--dry-run] yaml_path language
```

**Arguments**

| Option | Description |
|---|---|
| `yaml_path` | the yaml of the LocalizedStrings element |
| `language` | the translation language: Russian/English or the Ru/En code |

**Options**

| Option | Description |
|---|---|
| `-h, --help` | show this help message and exit |
| `--dry-run` | show the changes (with file texts) without writing anything |

### `xbsl set-field-property`

```bash
usage: xbsl set-field-property [-h] --prop КЛЮЧ=ЗНАЧЕНИЕ [--tabular TABULAR] [--dry-run]
                               yaml_path field_kind name
```

**Arguments**

| Option | Description |
|---|---|
| `yaml_path` | the yaml of the object to add the field to |
| `field_kind` | реквизит, измерение, ресурс, значение, параметр, поле, константа |
| `name` | the name of the item in the section |

**Options**

| Option | Description |
|---|---|
| `-h, --help` | show this help message and exit |
| `--prop КЛЮЧ=ЗНАЧЕНИЕ` | an item property (repeatable): DefaultValue=https://example.com, Presentation=Service address |
| `--tabular TABULAR` | tabular section name (the attribute is added into it) |
| `--dry-run` | show the changes (with file texts) without writing anything |

### `xbsl rename-object`

```bash
usage: xbsl rename-object [-h] [--new-presentation NEW_PRESENTATION]
                          [--old-presentation OLD_PRESENTATION] [--path PATH] [--dry-run]
                          root old_name new_name
```

**Arguments**

| Option | Description |
|---|---|
| `root` | the project root – the folder with Проект.yaml (usually .) |
| `old_name` | the object's current name |
| `new_name` | the new name – both the files and the project-wide references are renamed |

**Options**

| Option | Description |
|---|---|
| `-h, --help` | show this help message and exit |
| `--new-presentation NEW_PRESENTATION` | new Представление/Заголовок (default: the new name) |
| `--old-presentation OLD_PRESENTATION` | the old presentation (to replace in Заголовок/Представление) |
| `--path PATH` | the object's yaml (when several objects share one name) |
| `--dry-run` | show the changes (with file texts) without writing anything |

### `xbsl delete-object`

```bash
usage: xbsl delete-object [-h] [--name NAME] [--path PATH] [--apply] [--dry-run] root
```

**Arguments**

| Option | Description |
|---|---|
| `root` | the project root – the folder with Проект.yaml (usually .) |

**Options**

| Option | Description |
|---|---|
| `-h, --help` | show this help message and exit |
| `--name NAME` | the object name in the project |
| `--path PATH` | the object's yaml (instead of `--name`) |
| `--apply` | perform the deletion (without the flag the plan is printed: deletion is irreversible) |
| `--dry-run` | show the changes (with file texts) without writing anything |

### `xbsl set-access`

```bash
usage: xbsl set-access [-h] [--name NAME] [--path PATH] [--default DEFAULT]
                       [--permission RIGHT=METHOD] [--calc-by CALC_BY] [--dry-run]
                       root
```

**Arguments**

| Option | Description |
|---|---|
| `root` | the project root – the folder with Проект.yaml (usually .) |

**Options**

| Option | Description |
|---|---|
| `-h, --help` | show this help message and exit |
| `--name NAME` | the object name in the project |
| `--path PATH` | the object's yaml (instead of `--name`) |
| `--default DEFAULT` | the method for the ПоУмолчанию right |
| `--permission RIGHT=METHOD` | the method for a single right (repeatable), e.g. Чтение=РазрешеноВсем |
| `--calc-by CALC_BY` | РасчетРазрешенийПо fields, comma-separated (required for РазрешенияВычисляютсяДляКаждогоОбъекта) |
| `--dry-run` | show the changes (with file texts) without writing anything |

### `xbsl object-info`

```bash
usage: xbsl object-info [-h] [--name NAME] [--path PATH] root
```

**Arguments**

| Option | Description |
|---|---|
| `root` | the project root – the folder with Проект.yaml (usually .) |

**Options**

| Option | Description |
|---|---|
| `-h, --help` | show this help message and exit |
| `--name NAME` | the object name in the project |
| `--path PATH` | the object's yaml (instead of `--name`) |

### `xbsl project-info`

```bash
usage: xbsl project-info [-h] root
```

**Arguments**

| Option | Description |
|---|---|
| `root` | the project root – the folder with Проект.yaml (usually .) |

**Options**

| Option | Description |
|---|---|
| `-h, --help` | show this help message and exit |

### `xbsl localization-info`

```bash
usage: xbsl localization-info [-h] yaml_path
```

**Arguments**

| Option | Description |
|---|---|
| `yaml_path` | the yaml of the LocalizedStrings element |

**Options**

| Option | Description |
|---|---|
| `-h, --help` | show this help message and exit |

### `xbsl form-tree`

```bash
usage: xbsl form-tree [-h] [--at OFFSET] yaml_path
```

**Arguments**

| Option | Description |
|---|---|
| `yaml_path` | the form yaml |

**Options**

| Option | Description |
|---|---|
| `-h, --help` | show this help message and exit |
| `--at OFFSET` | instead of the tree, return the node at a file offset (cursor sync) |

### `xbsl form-edit`

```bash
usage: xbsl form-edit [-h] [--parent PARENT] [--slot SLOT] [--type TYPE] [--name NAME]
                      [--node NODE] [--nodes ID[,ID...]] [--new-parent NEW_PARENT]
                      [--container CONTAINER] [--new-name NEW_NAME] [--before BEFORE]
                      [--after AFTER] [--key KEY] [--value VALUE] [--value-yaml VALUE_YAML]
                      [--fragment FRAGMENT] [--fragment-file FILE] [--new-type NEW_TYPE]
                      [--dry-run]
                      yaml_path operation
```

**Arguments**

| Option | Description |
|---|---|
| `yaml_path` | the form yaml |
| `operation` | insert, insert-fragment, move, move-nodes, remove, remove-nodes, wrap, unwrap, duplicate, rename, set-property, reset-property, property-add, property-retype, property-remove, property-rename |

**Options**

| Option | Description |
|---|---|
| `-h, --help` | show this help message and exit |
| `--parent PARENT` | container node id (insert/insert-fragment) |
| `--slot SLOT` | children slot: Содержимое, Страницы, Колонки, ... (insert/move) |
| `--type TYPE` | Тип of the new component (insert) or property (property-add) |
| `--name NAME` | Имя of the new component (insert), the wrapper (wrap) or a Свойства-section property (property-*) |
| `--node NODE` | operation node id (move/remove/wrap/unwrap/duplicate/rename/set-property/reset-property) |
| `--nodes ID[,ID...]` | node ids of a batch operation (move-nodes/remove-nodes): comma-separated or by repeating the flag; order does not matter |
| `--new-parent NEW_PARENT` | new container id (move/move-nodes) |
| `--container CONTAINER` | Тип of the wrapper container (wrap) |
| `--new-name NEW_NAME` | the node's new Имя (rename) or property's (property-rename); for rename without the flag, Имя is removed |
| `--before BEFORE` | sibling id: insert/move BEFORE it |
| `--after AFTER` | sibling id: insert/move AFTER it |
| `--key KEY` | node property name (set-property/reset-property) |
| `--value VALUE` | scalar value or binding (set-property) |
| `--value-yaml VALUE_YAML` | a composite value as a ready yaml fragment (set-property) |
| `--fragment FRAGMENT` | a yaml block of one component or several – a "-" list or blocks in a row (insert-fragment) |
| `--fragment-file FILE` | a file with a component's yaml block (insert-fragment, instead of `--fragment`) |
| `--new-type NEW_TYPE` | the property's new Тип (property-retype) |
| `--dry-run` | show the changes (with file texts) without writing anything |

### `xbsl form-handlers`

```bash
usage: xbsl form-handlers [-h] [--node NODE] [--key KEY] [--method METHOD] [--signature SIGNATURE]
                          [--dry-run]
                          yaml_path
```

**Arguments**

| Option | Description |
|---|---|
| `yaml_path` | the form yaml |

**Options**

| Option | Description |
|---|---|
| `-h, --help` | show this help message and exit |
| `--node NODE` | node id (handler creation; without `--node`/`--key` – the module's method list) |
| `--key KEY` | node event key: ПриНажатии, ПослеСоздания, ... |
| `--method METHOD` | handler method name (default &lt;Имя узла&gt;&lt;Ключ&gt;; an existing method – only the binding in yaml) |
| `--signature SIGNATURE` | event signature from the ui schema, e.g. "(Кнопка, СобытиеПриНажатии)-&gt;ничто" (without the flag it is looked up in the local data) |
| `--dry-run` | show the changes (with file texts) without writing anything |

