# XBSL for VS Code

**English** · [Русский](https://github.com/keyfire/xbsl-lint/blob/main/editors/vscode/README.ru.md)

Syntax highlighting and on-the-fly linting for **1C:Element** sources (`.xbsl`), powered by the
[xbsllint](https://github.com/keyfire/xbsl-lint) linter.

![XBSL: live diagnostics, Quick Fix and per-rule configuration](https://raw.githubusercontent.com/keyfire/xbsl-lint/main/editors/vscode/images/lint-quickfix.gif)

> Want to try everything on a toy project? Open the [`demo/`](https://github.com/keyfire/xbsl-lint/tree/main/demo)
> folder of the repository – a tiny 1C:Element app with a form and a handful of deliberate findings.

## Features

- **Syntax highlighting** for `.xbsl`: keywords (both Russian and English forms), declarations,
  operators, `@`-decorators, numbers, comments, and strings with `%name` / `${...}` interpolation.
- **Live diagnostics** as you type (debounced) and on save – brackets/blocks balance, unused
  locals, typography, code-style conventions, and everything else the linter reports. Squiggles
  carry the rule id (e.g. `code/brackets`) and severity.
- **Workspace diagnostics** – saving any `.xbsl`/`.yaml` file runs the linter over the whole
  workspace folder in the background, so project-scope rules (`code/unknown-type`,
  `yaml/unknown-type`, id (`Ид`) uniqueness) show up right in the editor, across all files.
  Controlled by `xbsl.workspaceLint` (on by default).
- **Whole-project check** – the command *XBSL: check the whole project* runs the same
  workspace-wide check on demand.
- **Go to definition and completion across the project** – powered by a project index built by
  the linter (`xbsllint --index`). See [Navigation and completion](#navigation-and-completion).
- **Quick Fix for mechanical findings** – a lightbulb on a fixable diagnostic (trailing
  whitespace, typography characters) applies the exact edit the linter reports; a *fix all*
  source action (`source.fixAll.xbsl`) fixes the whole file and can run on save via
  `editor.codeActionsOnSave`. Needs `xbsllint` ≥ 0.7.1. See [Quick Fix](#quick-fix).
- **Deploy to the stand** – the *XBSL: deploy the project (elemctl)* command (and a cloud
  button in the editor title of `.xbsl` files) runs `elemctl deploy` in a terminal task:
  build from sources → upload → apply → restart → verification that the apply actually took
  effect. See [Deploy](#deploy).
- **Form preview** – a wireframe of a form yaml in a side panel: groups, fields, buttons,
  tables, tabs, cards; follows the active editor and updates as you type. A click selects an
  element and opens its **properties panel** for editing (dropdowns and toggles write back
  into the yaml); Ctrl+click reveals the yaml node. See [Form preview](#form-preview).
- **Metadata explorer** – a dedicated Activity Bar view: a tree of the project objects grouped by
  kind, with subtrees (attributes, dimensions, forms, enum values ...), an editable properties
  panel, creation of objects/fields/subsystems and filtering by subsystem. See
  [Metadata explorer](#metadata-explorer).

`.yaml` element descriptions keep their built-in YAML highlighting.

## Requirements

The extension is a thin client over the `xbsllint` CLI – it does not bundle a checker. You need:

1. **Python 3.10+** and the linter: `pip install xbsllint`. If the linter is missing,
   the extension offers to install it right from the error message.
2. **Element language data** – generated once from your 1C:Element distribution, see
   [step 1 of the linter README](https://github.com/keyfire/xbsl-lint#step-1-generate-the-language-data).
   Without it most rules cannot run; the extension surfaces the linter's error once.

By default the extension calls `xbsllint` from `PATH`. Point it elsewhere with
`xbsl.linter.command` (an executable) or `xbsl.linter.pythonPath` (an interpreter – the linter is
then invoked as `<python> -m xbsllint`).

## Navigation and completion

The extension asks the linter for a project index once on activation and rebuilds it (debounced,
one process at a time) whenever a `.xbsl`/`.yaml` file is saved. The index command is probed as
`xbsllint index <root>` first, then `xbsllint --index <root>` as a fallback. If the installed
linter does not support the index yet, navigation silently stays off – details go to the *XBSL*
output channel, no popups.

**Go to definition** (F12 / Ctrl+Click), in `.xbsl` and `.yaml`:

- a project object name (bare, or the root of a dotted chain) → its `.yaml`;
- `<Object>.<LocalType>` → the type declaration; `<Object>.<TabularSection>` → the section in the
  object's yaml; `<Enum>.<Value>` → the value line;
- `<Module>.<Method>` (including manager modules named after the object), and a bare method name
  inside its own module → the method;
- `Компоненты.<Name>` → the component node in the current form's yaml; `Компоненты.<Name>.<Method>`
  → the method of that module;
- in yaml, the value of `Обработчик: <Name>` → the handler in the paired `.xbsl`.

> **A note on names.** Code keywords, literals and the names of stdlib types are bilingual, and this
> README spells them in English (`var`, `new`, `Query{}`, `Array<String>`, `True`). Metadata names are
> not – the platform documents them in Russian only – so yaml keys and type members appear here exactly
> as they are written in the yaml. The ones this README uses:
>
> | In the yaml | Means |
> | --- | --- |
> | `Реквизиты` · `Измерения` · `Ресурсы` · `ТабличныеЧасти` | attributes · dimensions · resources · tabular sections |
> | `Ид` · `Имя` · `Тип` · `Обработчик` | id · name · type · handler |
> | `Ссылка` · `Объект` | the reference / the object of a type family |
> | `Компоненты` | the components of a form |
> | `Многострочная` · `Компоновка` · `Растягивать*` · `Страницы` | multiline · layout · stretch flags · tabs |
> | `Истина` · `Ложь` | true · false |

**Completion** (triggered by `.` and `:`):

- after `<Object>.` – the type family (`Ссылка`, `Объект`, ...), tabular sections, local types and
  manager-module methods; for an enum – its values;
- after `Компоненты.` – components of the current form; after `Компоненты.<Name>.` – methods of
  that module;
- in yaml after `Тип:` – project object names (the object kind is shown as the detail).

**Type-aware completion** – in [LSP mode](#lsp-mode-default) only. The parsing runs over tokens, so
keywords are understood in both languages (`var`/`пер`, `new`/`новый`):

- inside `Query{ ... }`, after a table – its fields: the standard fields of the kind, the
  attributes and the tabular sections. Aliases resolve too: `FROM Product AS P` → `P.` gives the
  same fields;
- after the loop variable of a query result (`for Row in Result` → `Row.`) – the columns of the
  selection (the `SELECT ... AS` aliases; a plain field is named by its last segment);
- after a variable of a known type (`var List = new Array<String>()` → `List.`) – the members of
  that type. The type comes from the annotation or from `new`; method parameters count as well;
- after an stdlib type or global (`AccessContext.`) – its members. Properties and methods are
  listed apart: a method carries its own icon and is inserted with parentheses.

The members of stdlib types come from the Element data (the `--data-dir` root), everything else
from the project index. A name in scope beats a type of the same name: once a variable `List` is
declared, `List.` is about its type, not about the `List` component.

Known limits – by design: outside LSP mode the index knows declarations, not types (no completion
after variables). Type inference for arbitrary expressions and for dotted chains deeper than one
level is nowhere, and there is no rename. When the context is ambiguous the providers return
nothing rather than guessing.

## Quick Fix

Findings the linter can repair mechanically carry a fix; the extension turns it into a Quick Fix:

- A **lightbulb on the diagnostic** (`Ctrl+.`) – *Fix: `<rule>`* – applies the exact edit:
  trailing whitespace removed, em dash → en dash, `…` → `...`, curly quotes → straight.
- A **fix-all source action** – *Fix all (xbsllint)* – repairs every fixable finding in the
  file in one edit. Run it on save by adding to your settings:

  ```json
  "editor.codeActionsOnSave": { "source.fixAll.xbsl": "explicit" }
  ```

Fixes need a linter that emits them in its JSON (`xbsllint` ≥ 0.7.1). Only unambiguous edits are
offered, and only against the exact text they were computed on – a version-stamped snapshot guards
against applying an offset to text that changed since the last lint. Whole-file fixes (mixed
newlines) are left to `xbsllint --fix` on the command line.

## Settings

| Setting | Default | Meaning |
| --- | --- | --- |
| `xbsl.linter.run` | `onType` | When to lint: `onType` (debounced) / `onSave` / `off`. |
| `xbsl.linter.command` | `xbsllint` | Linter executable (PATH or absolute path). |
| `xbsl.linter.pythonPath` | – | Python interpreter; when set, runs `<python> -m xbsllint`. |
| `xbsl.linter.dataDir` | – | Element data root (folder with `index.json`); empty = auto-resolved. |
| `xbsl.linter.lang` | auto | Diagnostic language: ` ` (auto) / `ru` / `en`. |
| `xbsl.linter.select` | – | Only these rules (ids, groups, or tier letters `A`–`D`). |
| `xbsl.linter.ignore` | – | Exclude these rules. |
| `xbsl.rules` | `{}` | Per-rule levels and disabling: `{"style": "off", "code/brackets": "error"}`. See [Rules](#rules-levels-and-disabling). |
| `xbsl.linter.debounce` | `300` | Delay (ms) before linting while typing. |
| `xbsl.projectRoot` | – | Sources root for project-wide runs and the navigation index, relative to the workspace folder (or absolute). Empty – the whole folder. Set it when the repository holds examples or copies next to the project: otherwise project-scope rules (id (`Ид`) uniqueness etc.) cross-fire between directories. |
| `xbsl.workspaceLint` | `true` | Full workspace run on every save of a `.xbsl`/`.yaml` file. |
| `xbsl.workspaceLintTimeout` | `60000` | Kill a workspace run after this many ms (`0` – no limit). |
| `xbsl.navigation.enabled` | `true` | Index-based go-to-definition and completion. |
| `xbsl.groups.*` | `default` | A dropdown per rule group (code, yaml, style, typography, whitespace, encoding, structure, form): the rules' own levels, one level for the whole group, or `off`. See [Rules](#rules-levels-and-disabling). |
| `xbsl.deploy.*` | – | The deploy command settings – documented in the [XBSL Debug README](https://github.com/keyfire/elemctl/tree/main/editors/vscode#deploy-from-vs-code) of the elemctl project. |

## Rules: levels and disabling

**By group – in the Settings UI.** The **Rule groups** section (search for `xbsl.groups` in
the Settings editor, or browse Extensions → XBSL) has a dropdown per finding type – code,
yaml descriptions, style, typography, whitespace, encoding, structure, forms: keep the
group's own rule levels, report all its findings at one level (error / warning / info /
hint), or turn the group off entirely – `off` does not just hide the findings, it excludes
the rules from the run.

**Per rule – from the finding.** Every finding carries a **"Configure rule..."** action in
its lightbulb (`Ctrl+.`): disable the rule or override its level without leaving the line;
the check reruns right away. The choices land in the `xbsl.rules` setting – a map from a
rule id (`whitespace/trailing`) or a whole group (`style`) to a level or `off`. An exact id
beats its group, and any `xbsl.rules` key beats the group dropdowns. Works in both the CLI
and the LSP mode.

## LSP mode (default)

The extension runs everything through a long-living `xbsllint-lsp` server instead of spawning
the CLI per event: the Element language data and the project index stay resident, so
as-you-type diagnostics respond in milliseconds, **hover** appears (a card for a project
object, method or form component), and so does
[type-aware completion](#navigation-and-completion). Definition, project-wide diagnostics on
save and quick fixes work as before, just faster. Requires the linter installed with the
`[lsp]` extra (`pip install "xbsllint[lsp]"`); the server is found as `xbsllint-lsp` on
`PATH`, via `xbsl.linter.pythonPath` (run as a module), or by the explicit
`xbsl.lsp.command`.

Without the server the extension quietly keeps working in the former CLI mode (details go to
the *XBSL* output channel, and the status bar shows the mode actually in use). To switch the
server off entirely, set `"xbsl.lsp.enabled": false`; changing the setting needs a window
reload.

## Code palette

The command **XBSL: code palette** (`xbsl.choosePalette`) recolors XBSL syntax with one of
the popular palettes: the 1C:Element web IDE style (red keywords, blue strings), One Dark,
Monokai, Dracula, GitHub Dark – or resets back to the active editor theme. The choice is
applied via `editor.tokenColorCustomizations` rules addressing only `*.xbsl` scopes, so the
global theme and other languages stay untouched; the extension manages only its own rules
(prefixed `xbsl-palette`) and preserves any customizations of yours.

## Form preview

![Form preview: wireframe, themes and live updates](https://raw.githubusercontent.com/keyfire/xbsl-lint/main/editors/vscode/images/form-preview.gif)

The command **XBSL: form preview** (`xbsl.previewForm`, also a preview button in the editor
title of form yamls – files whose element kind is an interface component, `КомпонентИнтерфейса`)
renders a wireframe of a 1C:Element
form from its yaml: nested vertical/horizontal groups, labels, input fields with captions and
`=bindings`, buttons (the primary one filled), checkboxes, tables with their real columns,
switchable tabs (`Страницы`), cards, image and HTML-container placeholders, and the form's
command bar. Unknown and custom component types render as labeled boxes with their content
inside, so nothing disappears.

The panel follows the active yaml editor and re-renders as you type (debounced). The toolbar
has a zoom (−/+, 125% by default) and a theme picker: light (the platform web client look,
the default), dark, or the editor theme – the choice is remembered.

![Properties panel: select an element, edit via dropdowns, the yaml follows](https://raw.githubusercontent.com/keyfire/xbsl-lint/main/editors/vscode/images/props-panel.gif)

**Properties panel.** A click on an element selects it and opens a separate **Properties**
panel (its own tab – drag it below or aside, wherever suits), like the platform web editor:
enums as dropdowns (the layout `Компоновка`, alignments, spacings, widths, button kinds), the
stretch flags (`Растягивать*`) as Auto / `Истина` / `Ложь` toggles, everything else as text – the
component's standard set plus
every property present in the yaml (object values are shown read-only). Edits land in the
yaml document as precise text edits, so the regular undo works; an empty value / *(auto)*
removes the property. Selecting an element and every edit also position the yaml editor on
the affected line (without stealing focus); Ctrl+click or the *Show in yaml* button jumps
into the editor – handy for navigating large forms.

It is a layout skeleton, not the platform's rendering: composition, nesting and captions are
faithful, exact sizes and styles are not (explicit label colors and font sizes are applied).

## Metadata explorer

![Metadata explorer: the tree, the properties panel, grouping by subsystem](https://raw.githubusercontent.com/keyfire/xbsl-lint/main/editors/vscode/images/metadata-tree.gif)

A dedicated **1C:Element** icon in the Activity Bar opens a tree of the project metadata – like the
platform designer, but inside VS Code.

> **Experimental.** The metadata explorer is an experimental feature – expect bugs and rough edges.

**The tree.** The root is the project (the project file), with the vendor and name in grey; its
context menu opens the application module. Below are a **Subsystems** branch and categories by kind:
Catalogs, Documents, Information/Accumulation registers, Enumerations, Common modules, HTTP services,
Structures, Client events and so on – each with its own icon. The `.yaml` + `.xbsl` pair of an object
is one row; an object/list form is nested under its owner, forms with no owner go to a **Common
forms** section.

**Object subtrees.** A catalog/document expands into **Attributes**, **Tabular sections**, **Forms**;
a register into **Dimensions**, **Resources**, **Attributes**; an enumeration into **Values**; a
structure into **Fields**; client-work parameters into **Parameters**; an HTTP service into **URL
templates** with their methods.

**Clicks.** An object or a field opens the **properties panel** on the right (a field's **type** is a
combo of primitives, reference types (`<Object>.Ссылка?`) and the project enumerations, and still
accepts a typed-in value); a common module opens its `.xbsl`; a form opens the preview. The context
menu adds *Properties*, open description / module.

**Properties panel** (on the right, like the form preview). Scalar properties are edited in place:
dropdowns for the visibility and environment, a true/false toggle, text for the rest. The id and the
element kind are read-only; collections are edited in the tree. Edits are surgical (undo works); save
the file (Ctrl+S) to refresh the tree.

Composite (nested) properties – a content alignment, say (`ВыравниваниеСодержимогоПоГоризонтали
{ ... }`) – are shown but not editable: edit those in the yaml.

**Creating objects.** A category root has an **Add &lt;class&gt;** action (Add catalog, Add document,
Add enumeration, Add information/accumulation register, Add common module, Add HTTP service, Add
structure, Add client event, Add command-interface fragment, Add client-work parameters, Add common
form): it asks a name and a subsystem (folder), writes a minimal valid yaml (a fresh id; a paired
`.xbsl` for module kinds) and opens it. Classes are shown even when the project has none of them yet.
In the subtree groups a **"+"** adds an attribute / dimension / resource / value / parameter / field /
tabular section; a catalog/document has **Add object form** (creates the object form and registers it
in the object).

**Subsystems.** A **Subsystems** branch lists the subsystem folders (a click opens the subsystem
file); **Add subsystem** creates a folder with a subsystem file. The project root has **Filter by
subsystem** (multi-select) and **Clear filter**; the active filter is shown in grey.

**Git status.** Object, form, subsystem and project rows carry the file's SCM decoration (color and
badge) like the Explorer, while keeping their kind icon.

**Deletion.** Right-click an object – **Delete object** (with confirmation; removes the object files,
undoable; references are left as is – the linter flags dangling ones).

A created object is a scaffold in files – it does not deploy on its own; a broken one only surfaces
on the next deploy (elemctl catches the rollback) and never corrupts your working files.

### Example: a demo app from the tree, deployed to 1cmycloud.com

The tree can assemble a working app from scratch (the yaml is produced by the same templates the tree
uses):

1. Open a folder with a project file – the project root appears in the tree.
2. **Subsystems → "+" → Add subsystem** → `Main`.
3. **Catalogs → "+" → Add catalog** → `Products` (subsystem `Main`); the same for `Categories`.
4. Under `Products` → **Attributes → "+" → Add attribute** → `Price`, `SKU`.
5. **Enumerations → Add enumeration** → `ProductStatus`; in **Values** → `InStock`, `OnOrder`.
6. Deploy: `elemctl deploy --app-id <app> --project-dir <project folder> --output <tmp>`
   (create the app first: `elemctl apps ensure <app> --latest-build --wait`).

The deploy report on 1cmycloud.com (`ok: true` only on an actual apply):

```
built archive <project> 1.0-N.xasm (version 1.0-N)
build uploaded, apply started, waiting for the app to stabilize...
app is Running, verifying the actual applied version...
verification passed: the build is applied
{
  "uri": "https://<app-host>.1cmycloud.com/applications/<app>",
  "status": "Running",
  "applied-version": "1.0-N",
  "applied": true,
  "uri-status": 200,
  "problems": [],
  "ok": true
}
```

`applied: true` and `ok: true` mean the build actually took effect – the `Products` / `Categories`
catalogs and the `ProductStatus` enumeration built by the tree are then available in the standard UI
(the demo needs no OIDC/login).

## Deploy

The command **XBSL: deploy the project (elemctl)** (`xbsl.deploy`, also a cloud button in the
editor title of `.xbsl` files) runs `elemctl deploy` – build, upload, apply and verification
that the apply actually took effect – as a terminal task, after a confirmation dialog with
the exact command line. The `xbsl.deploy.*` settings, the deploy cycle and the `ELEMENT_*`
configuration are documented in the
[XBSL Debug README](https://github.com/keyfire/elemctl/tree/main/editors/vscode#deploy-from-vs-code)
of the [elemctl](https://github.com/keyfire/elemctl) project
([Marketplace](https://marketplace.visualstudio.com/items?itemName=keyfire.xbsl-debug)).

## Commands

- **XBSL: check the whole project** (`xbsl.lintProject`) – lint the whole workspace.
- **XBSL: restart the linter** (`xbsl.restartLinter`) – clear and re-lint open files.
- **XBSL: code palette** (`xbsl.choosePalette`) – pick a syntax palette for XBSL (see above).
- **Metadata explorer** commands (`xbsl.metadata.*`) are invoked from the tree and its context
  menus: properties, add object / field / subsystem, add object form, filter by subsystem, delete
  object, refresh. See [Metadata explorer](#metadata-explorer).
- **XBSL: deploy the project (elemctl)** (`xbsl.deploy`) – deploy to the stand (see above).
- **XBSL: form preview** (`xbsl.previewForm`) – a wireframe of the active form yaml (see above).

## How it works

Two producers feed one diagnostic collection, and the split is by buffer state:

- **While you type** (dirty buffer) the extension runs
  `xbsllint --stdin --filename <name> --format json` on the live text – per-file rules only,
  fast, debounced. Its result replaces the diagnostics of *that buffer only*.
- **When you save** any `.xbsl`/`.yaml` file, the extension runs
  `xbsllint <workspace folder> --format json` in the background (debounced, at most one run
  at a time; a save during a run cancels the now-stale run and starts over). The result covers
  per-file *and* project-scope rules, so it replaces the diagnostics of *every* file in the
  folder – except buffers that are dirty again by then: those stay with their live `--stdin`
  diagnostics until the next save.

This way there are no duplicates and no rule is lost: a clean file always shows the full
workspace-run picture, a file being edited shows the instant per-file picture, and each save
reconciles the two. Both runs speak the same `{diagnostics, summary}` JSON contract that the
linter's MCP server exposes.

A workspace run that fails or exceeds `xbsl.workspaceLintTimeout` is reported to the *XBSL*
output channel only – no popups on every save.

## Development

```sh
npm install
npm run compile          # esbuild bundle -> dist/extension.js
npm run check            # tsc type-check
npm test                 # unit tests for the navigation core (plain Node, no runner)
npm run package          # build the .vsix (via @vscode/vsce)
```

Press **F5** in VS Code to launch an Extension Development Host with the extension loaded.

## License

MIT – see the [repository](https://github.com/keyfire/xbsl-lint).
