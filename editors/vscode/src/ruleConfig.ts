// One table decides everything about rules: xbsl.rules. The key is a rule id
// ("whitespace/trailing"), a whole group ("style"), a tier letter ("A".."D") or "*" for every
// rule; the value is off | error | warning | info | hint. "off" hides the findings and keeps
// the rule out of the run, a level replaces the rule's own severity AND turns the rule on when
// it is off by default. Priority runs from the specific to the general:
// rule > group > tier > "*", and the legacy settings below sit under all of them.
//
// Legacy, still read so that nobody's setup breaks: xbsl.groups.<group> (a dropdown per finding
// type) and the three strings xbsl.linter.select / .enable / .ignore. They said the same things
// in four different syntaxes - which is why they are deprecated in the manifest and the
// "XBSL: move the rule settings into one table" command rewrites them into xbsl.rules.
//
// Plus a "Configure rule ..." action on every finding - management without leaving the line.

import * as vscode from "vscode";
import { spawn } from "child_process";
import { isXbslSource } from "./report";

export type RuleLevel = "off" | "error" | "warning" | "info" | "hint";
const LEVELS: readonly RuleLevel[] = ["error", "warning", "info", "hint", "off"];

function isLevel(v: unknown): v is RuleLevel {
  return typeof v === "string" && (LEVELS as readonly string[]).includes(v);
}

function rulesMap(resource?: vscode.Uri): Record<string, unknown> {
  return vscode.workspace.getConfiguration("xbsl", resource ?? null).get<Record<string, unknown>>("rules") ?? {};
}

// xbsl.groups.* values as one {group: level} object. The "default" value does not pass
// isLevel and is therefore not counted as an override. Keys beyond those declared in the
// manifest are read too - a plugin rule's group written into settings.json by hand works
// the same way.
function groupsMap(resource?: vscode.Uri): Record<string, unknown> {
  return vscode.workspace.getConfiguration("xbsl", resource ?? null).get<Record<string, unknown>>("groups") ?? {};
}

// The rule catalogue of the engine: a rule id -> its tier letter. Needed to resolve a tier key
// in xbsl.rules the same way a group key is resolved; the engine itself understands the letters
// in its own arguments, but the overlay over already-received diagnostics happens here.
// Filled once by `xbsl --list-rules` (a line is "A  group/rule  warning  title"); if the run
// fails the map stays empty and tier keys simply do not colour anything - a missing catalogue
// must not turn into missing diagnostics.
const catalogue = new Map<string, { tier: string; level: string }>();

export function primeRuleCatalogue(command: string, baseArgs: string[] = []): void {
  if (catalogue.size > 0) {
    return;
  }
  let out = "";
  try {
    const child = spawn(command, [...baseArgs, "--list-rules"], { windowsHide: true });
    child.stdout?.on("data", (chunk) => (out += String(chunk)));
    child.on("error", () => undefined);
    child.on("close", () => {
      for (const line of out.split(/\r?\n/)) {
        const m = /^([A-Z])\s+(\S+\/\S+)\s+(\S+)/.exec(line);
        if (m) {
          catalogue.set(m[2], { tier: m[1], level: m[3] });
        }
      }
    });
  } catch {
    /* no catalogue - tier keys stay inert */
  }
}

// Override for a rule, from the specific to the general: the exact key, the group (the part
// before "/"), the tier of the rule, "*" - all four inside xbsl.rules - and only then the
// legacy per-group setting.
export function ruleOverride(rule: string, resource?: vscode.Uri): RuleLevel | undefined {
  const map = rulesMap(resource);
  const exact = map[rule];
  if (isLevel(exact)) {
    return exact;
  }
  const slash = rule.indexOf("/");
  const group = slash > 0 ? rule.slice(0, slash) : undefined;
  if (group) {
    const inRules = map[group];
    if (isLevel(inRules)) {
      return inRules;
    }
  }
  const tier = catalogue.get(rule)?.tier;
  if (tier) {
    const byTier = map[tier];
    if (isLevel(byTier)) {
      return byTier;
    }
  }
  const all = map["*"];
  if (isLevel(all)) {
    return all;
  }
  if (group) {
    const inGroups = groupsMap(resource)[group];
    if (isLevel(inGroups)) {
      return inGroups;
    }
  }
  return undefined;
}

export function severityFor(level: Exclude<RuleLevel, "off">): vscode.DiagnosticSeverity {
  switch (level) {
    case "error":
      return vscode.DiagnosticSeverity.Error;
    case "warning":
      return vscode.DiagnosticSeverity.Warning;
    case "info":
      return vscode.DiagnosticSeverity.Information;
    default:
      return vscode.DiagnosticSeverity.Hint;
  }
}

export interface RuleArgs {
  select?: string;
  enable?: string;
  ignore?: string;
}

// The engine side of the same table - what runs at all. An "off" key goes to --ignore; a key
// with a level goes to --enable, because a rule that is off by default never runs and leaves
// nothing for the overlay to recolour; and {"*": "off"} reads as "only the ones named here",
// which is exactly --select. The legacy strings are merged in, so a setup half-moved to the
// table keeps working.
export function engineRuleArgs(resource?: vscode.Uri): RuleArgs {
  const cfg = vscode.workspace.getConfiguration("xbsl", resource ?? null);
  const map = rulesMap(resource);
  const off: string[] = [];
  const on: string[] = [];
  let onlyListed = false;
  for (const [key, value] of Object.entries(map)) {
    if (!isLevel(value)) {
      continue;
    }
    if (key === "*") {
      onlyListed = value === "off";
      continue;
    }
    (value === "off" ? off : on).push(key);
  }
  for (const [group, value] of Object.entries(groupsMap(resource))) {
    if (value === "off" && !isLevel(map[group])) {
      off.push(group);
    }
  }
  const legacy = (key: string): string => (cfg.get<string>(key) || "").trim();
  const merge = (base: string, extra: string[]): string | undefined => {
    const parts = [...base.split(",").map((s) => s.trim()).filter(Boolean), ...extra];
    return parts.length > 0 ? [...new Set(parts)].join(",") : undefined;
  };
  return {
    select: onlyListed ? merge(legacy("linter.select"), on) : merge(legacy("linter.select"), []),
    enable: merge(legacy("linter.enable"), onlyListed ? [] : on),
    ignore: merge(legacy("linter.ignore"), off),
  };
}

function ruleOf(diag: vscode.Diagnostic): string | undefined {
  if (typeof diag.code === "string") {
    return diag.code;
  }
  if (diag.code && typeof diag.code === "object" && "value" in diag.code) {
    return String(diag.code.value);
  }
  return undefined;
}

// Applies an override to a ready diagnostic (LSP middleware): null = hide.
export function applyOverride(diag: vscode.Diagnostic, resource?: vscode.Uri): vscode.Diagnostic | null {
  const rule = ruleOf(diag);
  if (!rule) {
    return diag;
  }
  const over = ruleOverride(rule, resource);
  if (!over) {
    return diag;
  }
  if (over === "off") {
    return null;
  }
  diag.severity = severityFor(over);
  return diag;
}

const CONFIGURE_COMMAND = "xbsl.configureRule";

// A "Configure rule ..." entry on every xbsl finding (on top of quick-fix edits).
class ConfigureRuleProvider implements vscode.CodeActionProvider {
  provideCodeActions(
    document: vscode.TextDocument,
    _range: vscode.Range | vscode.Selection,
    context: vscode.CodeActionContext
  ): vscode.CodeAction[] {
    const actions: vscode.CodeAction[] = [];
    const seen = new Set<string>();
    for (const d of context.diagnostics) {
      if (!isXbslSource(d)) {
        continue;
      }
      const rule = ruleOf(d);
      if (!rule || seen.has(rule)) {
        continue;
      }
      seen.add(rule);
      const action = new vscode.CodeAction(vscode.l10n.t('Configure rule "{0}"...', rule), vscode.CodeActionKind.QuickFix);
      action.diagnostics = [d];
      action.command = {
        command: CONFIGURE_COMMAND,
        title: action.title,
        arguments: [rule, document.uri],
      };
      actions.push(action);
    }
    return actions;
  }
}

async function configureRule(rule: string, resource?: vscode.Uri): Promise<void> {
  const current = ruleOverride(rule, resource);
  type Item = vscode.QuickPickItem & { value: RuleLevel | "default" | "settings" | "groups" };
  const items: Item[] = [
    {
      label: "$(circle-slash) " + vscode.l10n.t("Disable the rule"),
      description: vscode.l10n.t("hide the findings and skip the rule"),
      value: "off",
    },
    ...(["error", "warning", "info", "hint"] as const).map((level) => ({
      label: "$(" + (level === "error" ? "error" : level === "warning" ? "warning" : "info") + ") " + level,
      description: current === level ? vscode.l10n.t("current override") : undefined,
      value: level as RuleLevel,
    })),
  ];
  if (current) {
    items.push({
      label: "$(discard) " + vscode.l10n.t("Reset the override"),
      description: vscode.l10n.t("back to the rule's own level"),
      value: "default",
    });
  }
  items.push({ label: "$(checklist) " + vscode.l10n.t("Configure rule groups..."), value: "groups" });
  items.push({ label: "$(gear) " + vscode.l10n.t("Open the XBSL rules settings"), value: "settings" });

  const picked = await vscode.window.showQuickPick(items, {
    title: vscode.l10n.t('Rule "{0}"', rule),
    placeHolder: vscode.l10n.t("Choose the level or an action"),
  });
  if (!picked) {
    return;
  }
  if (picked.value === "groups") {
    await vscode.commands.executeCommand("workbench.action.openSettings", "xbsl.groups");
    return;
  }
  if (picked.value === "settings") {
    await vscode.commands.executeCommand("workbench.action.openSettings", "xbsl.rules");
    return;
  }
  const cfg = vscode.workspace.getConfiguration("xbsl", resource ?? null);
  const map = { ...(cfg.get<Record<string, unknown>>("rules") ?? {}) };
  if (picked.value === "default") {
    delete map[rule];
  } else {
    map[rule] = picked.value;
  }
  const target = vscode.workspace.workspaceFolders?.length
    ? vscode.ConfigurationTarget.Workspace
    : vscode.ConfigurationTarget.Global;
  await cfg.update("rules", Object.keys(map).length > 0 ? map : undefined, target);
  void vscode.window.setStatusBarMessage(
    picked.value === "default"
      ? vscode.l10n.t('XBSL: the override of "{0}" is removed', rule)
      : vscode.l10n.t('XBSL: rule "{0}" is set to {1}', rule, picked.value),
    4000
  );
  // Re-check via the same familiar mechanism: in CLI mode this is resetAndRelint,
  // in LSP mode - a server restart (it also picks up off rules in --ignore).
  void vscode.commands.executeCommand("xbsl.restartLinter");
}

export function registerRuleConfig(context: vscode.ExtensionContext): void {
  context.subscriptions.push(
    vscode.commands.registerCommand(CONFIGURE_COMMAND, configureRule),
    vscode.commands.registerCommand(MIGRATE_COMMAND, () =>
      migrateRuleSettings(vscode.window.activeTextEditor?.document.uri)
    ),
    vscode.languages.registerCodeActionsProvider(
      [{ language: "xbsl" }, { language: "yaml" }],
      new ConfigureRuleProvider(),
      { providedCodeActionKinds: [vscode.CodeActionKind.QuickFix] }
    )
  );
}

// --- Moving the legacy settings into the one table -----------------------------------------
// Four syntaxes said the same thing; this rewrites whatever a scope holds into xbsl.rules and
// clears the old keys there. Scope by scope, because a user value and a workspace value mean
// different things and merging them would silently change what runs.
const MIGRATE_COMMAND = "xbsl.migrateRuleSettings";

const SCOPES: { target: vscode.ConfigurationTarget; value: (i: { globalValue?: unknown; workspaceValue?: unknown; workspaceFolderValue?: unknown } | undefined) => unknown }[] = [
  { target: vscode.ConfigurationTarget.Global, value: (i) => i?.globalValue },
  { target: vscode.ConfigurationTarget.Workspace, value: (i) => i?.workspaceValue },
  { target: vscode.ConfigurationTarget.WorkspaceFolder, value: (i) => i?.workspaceFolderValue },
];

// The level a rule carries by default - what "turn this one on" has to mean after the move.
// Without the catalogue (the engine did not answer) "warning" is the honest guess.
function ownLevel(key: string): string {
  return catalogue.get(key)?.level ?? "warning";
}

export async function migrateRuleSettings(resource?: vscode.Uri): Promise<void> {
  const cfg = vscode.workspace.getConfiguration("xbsl", resource ?? null);
  let movedScopes = 0;
  for (const scope of SCOPES) {
    const rules = { ...((scope.value(cfg.inspect("rules")) as Record<string, string>) ?? {}) };
    const groups = (scope.value(cfg.inspect("groups")) as Record<string, unknown>) ?? {};
    const list = (key: string): string[] =>
      String(scope.value(cfg.inspect(key)) ?? "")
        .split(",")
        .map((s) => s.trim())
        .filter(Boolean);
    let touched = false;
    for (const [group, value] of Object.entries(groups)) {
      if (typeof value === "string" && value !== "default" && rules[group] === undefined) {
        rules[group] = value;
        touched = true;
      }
    }
    for (const key of list("linter.enable")) {
      if (rules[key] === undefined) {
        rules[key] = ownLevel(key);
        touched = true;
      }
    }
    const select = list("linter.select");
    if (select.length > 0) {
      rules["*"] = "off";
      for (const key of select) {
        if (rules[key] === undefined) {
          rules[key] = ownLevel(key);
        }
      }
      touched = true;
    }
    // ignore goes last: an excluded rule stays excluded even if it was named above.
    for (const key of list("linter.ignore")) {
      rules[key] = "off";
      touched = true;
    }
    if (!touched) {
      continue;
    }
    await cfg.update("rules", rules, scope.target);
    for (const key of ["linter.select", "linter.enable", "linter.ignore"]) {
      await cfg.update(key, undefined, scope.target);
    }
    for (const group of Object.keys(groups)) {
      await cfg.update(`groups.${group}`, undefined, scope.target);
    }
    movedScopes += 1;
  }
  void vscode.window.showInformationMessage(
    movedScopes > 0
      ? vscode.l10n.t("XBSL: the rule settings now live in one table (xbsl.rules), {0} scope(s) moved.", movedScopes)
      : vscode.l10n.t("XBSL: nothing to move - the rules are already set in one table.")
  );
}
