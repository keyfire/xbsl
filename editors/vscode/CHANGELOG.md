# Changelog

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
