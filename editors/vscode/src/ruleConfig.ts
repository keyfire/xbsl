// Finding level overrides from two settings. xbsl.groups.<group> - dropdowns in the
// settings UI by finding type (default = the rules' own levels, off = disable the group,
// otherwise a single level). xbsl.rules - a fine-grained overlay: the key is a rule id
// ("whitespace/trailing") or a whole group ("style"), the value is
// off | error | warning | info | hint. "off" hides the findings and excludes the rule from
// the run, a level replaces the rule's own severity. Priority: exact rule name >
// group in xbsl.rules > xbsl.groups. Plus a "Configure rule ..." action on every
// finding - management without leaving the line.

import * as vscode from "vscode";
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

// Override for a rule: the exact xbsl.rules key, then the group (the part before "/") -
// first in xbsl.rules, then in the group settings.
export function ruleOverride(rule: string, resource?: vscode.Uri): RuleLevel | undefined {
  const map = rulesMap(resource);
  const exact = map[rule];
  if (isLevel(exact)) {
    return exact;
  }
  const slash = rule.indexOf("/");
  if (slash > 0) {
    const group = rule.slice(0, slash);
    const inRules = map[group];
    if (isLevel(inRules)) {
      return inRules;
    }
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

// Rules and groups set to off extend the linter's ignore list - what is disabled does not
// run. A group from xbsl.groups does not go into ignore when xbsl.rules gave it an
// explicit level: that setting is stronger, the group's findings must stay.
export function mergeOffRules(ignore: string | undefined, resource?: vscode.Uri): string | undefined {
  const rules = rulesMap(resource);
  const off = Object.entries(rules)
    .filter(([, v]) => v === "off")
    .map(([k]) => k);
  for (const [group, v] of Object.entries(groupsMap(resource))) {
    if (v === "off" && !isLevel(rules[group])) {
      off.push(group);
    }
  }
  if (off.length === 0) {
    return ignore;
  }
  const base = (ignore ?? "").split(",").map((s) => s.trim()).filter(Boolean);
  return [...new Set([...base, ...off])].join(",");
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
    vscode.languages.registerCodeActionsProvider(
      [{ language: "xbsl" }, { language: "yaml" }],
      new ConfigureRuleProvider(),
      { providedCodeActionKinds: [vscode.CodeActionKind.QuickFix] }
    )
  );
}
