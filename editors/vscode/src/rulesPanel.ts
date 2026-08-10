// The editor of the one rules table (xbsl.rules). Everything the table can say is said here by
// hand: the level of a rule, of a whole group, and "back to the default". The table itself stays
// the only model - the panel writes into it and nowhere else, so a setup made here reads the same
// as one typed into settings.json.
//
// The scope is chosen explicitly (the user's settings or the workspace ones): VS Code otherwise
// picks it silently, and "why does my colleague see other findings" starts exactly there.

import * as vscode from "vscode";
import { CatalogueEntry, RuleLevel, ruleCatalogue } from "./ruleConfig";
import { cspMeta, escapeHtml, inlineJson, makeNonce } from "./webviewShared";

const VIEW_TYPE = "xbsl.rulesPanel";
const LEVELS: readonly RuleLevel[] = ["error", "warning", "info", "hint", "off"];

type Scope = "user" | "workspace";

interface Row {
  id: string;
  group: string;
  tier: string;
  title: string;
  own: string; // the level the rule carries by default
  offByDefault: boolean;
  explicit?: string; // the value written in the table of the chosen scope
  inherited?: { from: string; level: string }; // what a group / tier / "*" key gives it
}

function target(scope: Scope): vscode.ConfigurationTarget {
  return scope === "user" ? vscode.ConfigurationTarget.Global : vscode.ConfigurationTarget.Workspace;
}

// The table as the chosen scope holds it - not the merged value: editing has to change the scope
// the user is looking at, and a merged map would silently copy the other scope's keys into it.
function tableOf(scope: Scope): Record<string, string> {
  const info = vscode.workspace.getConfiguration("xbsl").inspect<Record<string, string>>("rules");
  const value = scope === "user" ? info?.globalValue : info?.workspaceValue;
  return { ...(value ?? {}) };
}

// What a rule inherits from the wider keys of the same table, in the order the engine and the
// overlay use: group, then the tier, then "*".
function inheritedFor(rule: Row, table: Record<string, string>): { from: string; level: string } | undefined {
  for (const key of [rule.group, rule.tier, "*"]) {
    const level = table[key];
    if (level) {
      return { from: key, level };
    }
  }
  return undefined;
}

export class RulesPanel {
  private static current: RulesPanel | undefined;
  private scope: Scope = vscode.workspace.workspaceFolders?.length ? "workspace" : "user";

  private constructor(private readonly panel: vscode.WebviewPanel) {
    panel.onDidDispose(() => (RulesPanel.current = undefined));
    panel.webview.onDidReceiveMessage((msg) => void this.onMessage(msg));
  }

  public static async show(): Promise<void> {
    if (RulesPanel.current) {
      RulesPanel.current.panel.reveal(vscode.ViewColumn.Active);
      await RulesPanel.current.refresh();
      return;
    }
    const panel = vscode.window.createWebviewPanel(
      VIEW_TYPE,
      vscode.l10n.t("XBSL: rules"),
      vscode.ViewColumn.Active,
      { enableScripts: true, retainContextWhenHidden: true }
    );
    RulesPanel.current = new RulesPanel(panel);
    await RulesPanel.current.refresh();
  }

  private async rows(table: Record<string, string>): Promise<Row[]> {
    const catalogue = await ruleCatalogue();
    const rows: Row[] = [];
    for (const [id, entry] of catalogue as Map<string, CatalogueEntry>) {
      const slash = id.indexOf("/");
      const row: Row = {
        id,
        group: slash > 0 ? id.slice(0, slash) : id,
        tier: entry.tier,
        title: entry.title,
        own: entry.level,
        offByDefault: entry.offByDefault,
        explicit: table[id],
      };
      row.inherited = row.explicit ? undefined : inheritedFor(row, table);
      rows.push(row);
    }
    rows.sort((a, b) => (a.group === b.group ? a.id.localeCompare(b.id) : a.group.localeCompare(b.group)));
    return rows;
  }

  public async refresh(): Promise<void> {
    const table = tableOf(this.scope);
    this.panel.webview.html = this.html(await this.rows(table), table);
  }

  private async onMessage(msg: { type: string; key?: string; level?: string; scope?: Scope }): Promise<void> {
    if (msg.type === "scope" && msg.scope) {
      this.scope = msg.scope;
      await this.refresh();
      return;
    }
    if (msg.type === "set" && msg.key) {
      const table = tableOf(this.scope);
      if (!msg.level) {
        delete table[msg.key]; // "by default" = no key at all, not a level equal to the default one
      } else {
        table[msg.key] = msg.level;
      }
      await this.update(table);
      return;
    }
    if (msg.type === "reset") {
      await this.update({});
    }
  }

  private async update(table: Record<string, string>): Promise<void> {
    const value = Object.keys(table).length > 0 ? table : undefined;
    try {
      await vscode.workspace.getConfiguration("xbsl").update("rules", value, target(this.scope));
    } catch (e) {
      void vscode.window.showErrorMessage(
        vscode.l10n.t("XBSL: the rules table could not be saved: {0}", String(e))
      );
    }
    await this.refresh();
  }

  private html(rows: Row[], table: Record<string, string>): string {
    const nonce = makeNonce();
    const hasWorkspace = Boolean(vscode.workspace.workspaceFolders?.length);
    const t = {
      title: vscode.l10n.t("Rules"),
      lead: vscode.l10n.t(
        "One table, xbsl.rules: a level on a rule also switches it on when it is off by default; on a group or a tier it only recolours what already runs."
      ),
      search: vscode.l10n.t("Search by name or id"),
      changedOnly: vscode.l10n.t("changed only"),
      scopeUser: vscode.l10n.t("user settings"),
      scopeWorkspace: vscode.l10n.t("workspace settings"),
      reset: vscode.l10n.t("Reset the table"),
      byDefault: vscode.l10n.t("by default"),
      offByDefault: vscode.l10n.t("off by default"),
      groupLevel: vscode.l10n.t("the whole group"),
      empty: vscode.l10n.t("The rule catalogue is empty - the engine did not answer `xbsl --list-rules`."),
      inherits: vscode.l10n.t("inherited from"),
    };
    const groups = [...new Set(rows.map((r) => r.group))];
    const options = (selected: string | undefined): string =>
      [`<option value=""${selected ? "" : " selected"}>${escapeHtml(t.byDefault)}</option>`]
        .concat(
          LEVELS.map(
            (level) => `<option value="${level}"${selected === level ? " selected" : ""}>${level}</option>`
          )
        )
        .join("");
    const body = groups
      .map((group) => {
        const inGroup = rows.filter((r) => r.group === group);
        const head =
          `<tr class="group" data-group="${escapeHtml(group)}">` +
          `<td colspan="2"><b>${escapeHtml(group)}</b> <span class="dim">${inGroup.length}</span></td>` +
          `<td class="right dim">${escapeHtml(t.groupLevel)}</td>` +
          `<td><select class="level" data-key="${escapeHtml(group)}">${options(table[group])}</select></td></tr>`;
        const items = inGroup
          .map((r) => {
            const state = r.explicit
              ? `<span class="badge">${escapeHtml(r.explicit)}</span>`
              : r.inherited
                ? `<span class="dim">${escapeHtml(t.inherits)} ${escapeHtml(r.inherited.from)}: ${escapeHtml(r.inherited.level)}</span>`
                : `<span class="dim">${escapeHtml(r.own)}${r.offByDefault ? ", " + escapeHtml(t.offByDefault) : ""}</span>`;
            return (
              `<tr class="rule" data-changed="${r.explicit ? "1" : "0"}" ` +
              `data-text="${escapeHtml((r.id + " " + r.title).toLowerCase())}">` +
              `<td class="tier">${escapeHtml(r.tier)}</td>` +
              `<td class="id">${escapeHtml(r.id)}</td>` +
              `<td class="title">${escapeHtml(r.title)}<div class="state">${state}</div></td>` +
              `<td><select class="level" data-key="${escapeHtml(r.id)}">${options(r.explicit)}</select></td></tr>`
            );
          })
          .join("");
        return head + items;
      })
      .join("");
    return `<!DOCTYPE html><html><head><meta charset="utf-8">${cspMeta(nonce)}
<style nonce="${nonce}">
  body { font-family: var(--vscode-font-family); color: var(--vscode-foreground); padding: 12px 16px; }
  h1 { font-size: 15px; margin: 0 0 4px; }
  p.lead { color: var(--vscode-descriptionForeground); margin: 0 0 12px; max-width: 78ch; }
  .bar { display: flex; gap: 12px; align-items: center; margin-bottom: 10px; flex-wrap: wrap; }
  input[type=search] { flex: 1 1 220px; padding: 4px 6px; background: var(--vscode-input-background);
    color: var(--vscode-input-foreground); border: 1px solid var(--vscode-input-border, transparent); }
  select, button { background: var(--vscode-dropdown-background); color: var(--vscode-dropdown-foreground);
    border: 1px solid var(--vscode-dropdown-border, transparent); padding: 3px 6px; }
  button { background: var(--vscode-button-secondaryBackground); color: var(--vscode-button-secondaryForeground);
    border: none; cursor: pointer; }
  table { border-collapse: collapse; width: 100%; }
  td { padding: 4px 8px; border-bottom: 1px solid var(--vscode-widget-border, rgba(128,128,128,.25)); vertical-align: top; }
  tr.group td { background: var(--vscode-editorWidget-background); }
  .tier { width: 2ch; color: var(--vscode-descriptionForeground); }
  .id { font-family: var(--vscode-editor-font-family); white-space: nowrap; }
  .dim { color: var(--vscode-descriptionForeground); }
  .right { text-align: right; }
  .state { font-size: 11px; margin-top: 2px; }
  .badge { background: var(--vscode-badge-background); color: var(--vscode-badge-foreground); padding: 0 6px; border-radius: 8px; }
</style></head><body>
<h1>${escapeHtml(t.title)}</h1>
<p class="lead">${escapeHtml(t.lead)}</p>
<div class="bar">
  <input type="search" id="q" placeholder="${escapeHtml(t.search)}">
  <label><input type="checkbox" id="changed"> ${escapeHtml(t.changedOnly)}</label>
  <select id="scope">
    <option value="workspace"${this.scope === "workspace" ? " selected" : ""}${hasWorkspace ? "" : " disabled"}>${escapeHtml(t.scopeWorkspace)}</option>
    <option value="user"${this.scope === "user" ? " selected" : ""}>${escapeHtml(t.scopeUser)}</option>
  </select>
  <button id="reset">${escapeHtml(t.reset)}</button>
</div>
${rows.length === 0 ? `<p class="dim">${escapeHtml(t.empty)}</p>` : `<table>${body}</table>`}
<script nonce="${nonce}">
  const vscodeApi = acquireVsCodeApi();
  const state = ${inlineJson({ scope: this.scope })};
  document.querySelectorAll("select.level").forEach((el) => {
    el.addEventListener("change", () => vscodeApi.postMessage({ type: "set", key: el.dataset.key, level: el.value }));
  });
  document.getElementById("scope").addEventListener("change", (e) =>
    vscodeApi.postMessage({ type: "scope", scope: e.target.value }));
  document.getElementById("reset").addEventListener("click", () => vscodeApi.postMessage({ type: "reset" }));
  const filter = () => {
    const q = document.getElementById("q").value.trim().toLowerCase();
    const onlyChanged = document.getElementById("changed").checked;
    document.querySelectorAll("tr.rule").forEach((tr) => {
      const hit = (!q || tr.dataset.text.includes(q)) && (!onlyChanged || tr.dataset.changed === "1");
      tr.style.display = hit ? "" : "none";
    });
    document.querySelectorAll("tr.group").forEach((head) => {
      let next = head.nextElementSibling, visible = false;
      while (next && next.classList.contains("rule")) {
        if (next.style.display !== "none") { visible = true; break; }
        next = next.nextElementSibling;
      }
      head.style.display = visible ? "" : "none";
    });
  };
  document.getElementById("q").addEventListener("input", filter);
  document.getElementById("changed").addEventListener("change", filter);
  void state;
</script></body></html>`;
  }
}

export function registerRulesPanel(context: vscode.ExtensionContext): void {
  context.subscriptions.push(
    vscode.commands.registerCommand("xbsl.rules.panel", () => RulesPanel.show()),
    vscode.window.registerWebviewPanelSerializer(VIEW_TYPE, {
      // A panel VS Code restored after a restart is rebuilt from the settings, not from its state.
      async deserializeWebviewPanel() {
        await RulesPanel.show();
      },
    })
  );
}
