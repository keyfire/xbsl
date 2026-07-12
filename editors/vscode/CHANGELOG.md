# Changelog

## 0.11.2

- README only: animated demos of the diagnostics with Quick Fix, the form preview and the
  properties panel, plus a pointer to the `demo/` toy project in the repository. No code
  changes.

## 0.11.1

- New rule group **query** in the settings (needs `xbsllint` with the `query/unknown-table`
  rule): tables of the `Запрос{...}` blocks (`ИЗ`/`СОЕДИНЕНИЕ`) are checked against the
  project objects.
- One release consolidating the 0.8.0–0.11.0 changes below.

## 0.11.0

- The form preview gained a **properties panel**, like the platform web editor: a click on an
  element selects it and opens a separate *Properties* tab (drag it wherever suits) – enums as
  dropdowns, `Растягивать*` as Auto / Истина / Ложь toggles, everything else as text; the
  curated standard set of the component plus every property present in the yaml. Edits are
  applied to the yaml document as precise text edits (undo works); an empty value / *(auto)*
  removes the property. Selecting and editing also position the yaml editor on the affected
  line without stealing focus; Ctrl+click or the *Show in yaml* button jumps into the editor
  (plain click selects). Long property names wrap – no horizontal scrolling; wide wireframe
  content scrolls within its own area.

## 0.10.1

- New command *XBSL: form preview* (`xbsl.previewForm`) with a preview button on form yamls:
  a wireframe of the 1C:Element form in a webview – nested groups, labels, fields with
  captions and bindings, buttons, checkboxes, tables with their columns, switchable tabs,
  cards, image/HTML placeholders, and the form command bar. The panel follows the active
  editor and re-renders as you type; clicking an element reveals its yaml node. Unknown and
  custom component types render as labeled boxes with their content.
- The preview toolbar: zoom (−/+, 125% by default) and a theme picker – light (the platform
  web client look, the default), dark, or the editor theme. The choice is remembered.

## 0.9.0

- New settings section **Rule groups**: a dropdown per finding type (code, yaml, style,
  typography, whitespace, encoding, structure, form) – keep the rules' own levels, report
  the whole group at one level, or turn the group off (the rules are then skipped, not just
  hidden). No more hand-typing ids into `xbsl.rules` for the common cases; `xbsl.rules`
  stays as the fine-grained override and beats the dropdowns.
- The "Configure rule..." lightbulb gained a "Configure rule groups..." shortcut into the
  new section.

## 0.8.0

- New command *XBSL: deploy the project (elemctl)* (`xbsl.deploy`), also a cloud button in the
  editor title of `.xbsl` files: runs `elemctl deploy` – build from sources, upload, apply,
  restart, and verification that the apply actually took effect – as a terminal task, after a
  confirmation dialog showing the exact command line. The target comes from the workspace
  folder's `.env` or the new settings `xbsl.deploy.elemctlPath` / `xbsl.deploy.envFile` /
  `xbsl.deploy.appId` / `xbsl.deploy.extraArgs`; a set `xbsl.projectRoot` is passed as
  `--project-dir`. Offers to install elemctl when it is missing.
- The English README now shows the English command titles (bilingual since 0.6.1).

## 0.7.1

- "Install xbsllint" / "Install xbsllint[lsp]" buttons on the corresponding errors: the install
  runs as a terminal task and the check restarts on success.

## 0.7.0

- New setting `xbsl.rules` – per-rule levels and disabling (`off | error | warning | info | hint`
  by rule id or whole group), plus a "Configure rule..." action in every finding's lightbulb.
  Works in both the CLI and the LSP mode.

## 0.6.1

- Bilingual UI (en/ru): the manifest and all runtime strings follow the VS Code display language.

## 0.6.0

- Experimental LSP mode (`xbsl.lsp.enabled`): a long-living `xbsllint-lsp` server brings hover,
  instant as-you-type diagnostics and index navigation; on a failed server start the extension
  falls back to the regular CLI mode by itself.

## 0.5.0

- New command *XBSL: code palette* – recolor XBSL syntax with one of the popular palettes
  (the 1C:Element web IDE style, One Dark, Monokai, Dracula, GitHub Dark) or reset to the
  editor theme; only `*.xbsl` scopes are touched.

## 0.4.1

- New setting `xbsl.projectRoot` – the sources root for project-wide runs and the navigation
  index, for repositories that hold examples or copies next to the project.

## 0.4.0

- Quick Fix for mechanical findings: a lightbulb on a fixable diagnostic (trailing whitespace,
  typography characters – em dash → en dash, `…` → `...`, curly quotes) applies the exact edit the
  linter reports. Needs a linter that emits fixes in its JSON (`xbsllint` ≥ 0.7.1).
- A *fix all* source action (`source.fixAll.xbsl`) fixes every fixable finding in the file at once;
  wire it into `editor.codeActionsOnSave` for fix-on-save. Fixes are applied only against the exact
  text they were computed on (a version-stamped snapshot), so a stale edit is never misplaced.

## 0.3.0

- Go to definition and completion powered by the project index (`xbsllint index`, with the
  `--index` spelling probed as a fallback): objects, tabular sections, local types, enum values,
  methods, form components, yaml `Обработчик:` / `Тип:`. Silent when the installed linter has no
  index command.
- New setting `xbsl.navigation.enabled` (default `true`).

## 0.2.0

- Workspace diagnostics: saving any `.xbsl`/`.yaml` file triggers a full linter run over the
  workspace folder (debounced, one at a time, stale runs cancelled), bringing project-scope
  rules (`code/unknown-type`, `yaml/unknown-type`, ...) into the editor. The workspace result
  replaces the diagnostics of every file; the fast `--stdin` lint owns only the dirty buffer
  being edited.
- New settings: `xbsl.workspaceLint` (on by default) and `xbsl.workspaceLintTimeout`
  (60000 ms; on expiry the run is stopped and logged to the XBSL output channel).
- The *XBSL: проверить весь проект* command reuses the same machinery and result store.
- Activation on `workspaceContains:**/*.xbsl`, so `.yaml`-only editing sessions get
  workspace diagnostics too.

## 0.1.0

- Initial release.
- Syntax highlighting for `.xbsl` (bilingual keywords, decorators, string interpolation, generics).
- On-the-fly diagnostics via `xbsllint --stdin --format json` (on type, debounced, and on save).
- Command *XBSL: проверить весь проект* for a workspace-wide check (including cross-file rules).
- Settings: linter command / Python interpreter, data dir, language, rule select/ignore, run mode,
  debounce.
