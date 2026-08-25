// The editor of the one rules table (xbsl.rules). Everything the table can say is said here by
// hand: the level of a rule, of a whole group, and "back to the default". The table itself stays
// the only model - the panel writes into it and nowhere else, so a setup made here reads the same
// as one typed into settings.json.
//
// The scope is chosen explicitly (the user's settings or the workspace ones): VS Code otherwise
// picks it silently, and "why does my colleague see other findings" starts exactly there.

import * as vscode from "vscode";
import { CatalogueEntry, RuleLevel, ruleCatalogue } from "./ruleConfig";
import { ruleDoc } from "./ruleDocs";
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
  // The documentation page behind a rule backed by a standard - the same one the rule badge in
  // "Problems" opens. Without it the table names a requirement and leaves you to find its source.
  doc?: { page: string; anchor?: string };
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
      const doc = ruleDoc(id);
      row.doc = doc ? { page: doc.page, anchor: doc.anchor } : undefined;
      rows.push(row);
    }
    rows.sort((a, b) => (a.group === b.group ? a.id.localeCompare(b.id) : a.group.localeCompare(b.group)));
    return rows;
  }

  public async refresh(): Promise<void> {
    const table = tableOf(this.scope);
    this.panel.webview.html = this.html(await this.rows(table), table);
  }

  private async onMessage(
    msg: { type: string; key?: string; level?: string; scope?: Scope; page?: string; anchor?: string }
  ): Promise<void> {
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
    if (msg.type === "docs" && msg.page) {
      // The panel's own Documentation view, not the site: the same command the rule badge uses.
      await vscode.commands.executeCommand("xbsl.docs.open", msg.page, msg.anchor);
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
      docs: vscode.l10n.t("reference"),
    };
    // The level in force for a row: its own key, then what it inherits, then the rule's default.
    // The dot is painted by it, so a rule switched off reads as grey without opening the list.
    const effective = (r: Row): string => r.explicit ?? r.inherited?.level ?? r.own;
    // The level badge is the icon VS Code itself uses for a diagnostic, drawn inline: the panel
    // must not depend on the codicon font being shipped, and a shape reads faster than a colour
    // for anyone who does not tell red from green.
    const GLYPH: Record<string, string> = {
      error: "M8 1a7 7 0 100 14A7 7 0 008 1zm3 9.2-.8.8L8 8.8 5.8 11 5 10.2 7.2 8 5 5.8 5.8 5 8 7.2 10.2 5l.8.8L8.8 8z",
      warning: "M7.1 1.7.6 13.4c-.3.5.1 1.1.7 1.1h13.4c.6 0 1-.6.7-1.1L8.9 1.7a1 1 0 00-1.8 0zM8 11.9a.9.9 0 110-1.8.9.9 0 010 1.8zM8.8 9H7.2V5.2h1.6z",
      info: "M8 1a7 7 0 100 14A7 7 0 008 1zm.8 11H7.2V7h1.6zm0-6.4H7.2V4h1.6z",
      hint: "M8 2a6 6 0 100 12A6 6 0 008 2zm0 1.6a4.4 4.4 0 110 8.8 4.4 4.4 0 010-8.8z",
      off: "M8 1.5a6.5 6.5 0 100 13 6.5 6.5 0 000-13zm0 1.6c1.2 0 2.3.4 3.2 1.1l-7.6 7.6A5 5 0 018 3.1zm0 9.8c-1.2 0-2.3-.4-3.2-1.1l7.6-7.6A5 5 0 018 12.9z",
      default: "M8 2a6 6 0 100 12A6 6 0 008 2zm0 1.6a4.4 4.4 0 110 8.8 4.4 4.4 0 010-8.8z",
    };
    const dot = (level: string): string => {
      const path = GLYPH[level] ?? GLYPH.default;
      return `<svg class="lvl-icon ${escapeHtml(level)}" viewBox="0 0 16 16" width="15" height="15" ` +
        `aria-hidden="true"><path d="${path}"/></svg>`;
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
        const changed = inGroup.filter((r) => r.explicit).length;
        const head =
          `<tr class="group" data-group="${escapeHtml(group)}">` +
          `<td colspan="2"><span class="caret">&#9656;</span> <b>${escapeHtml(group)}</b> ` +
          `<span class="dim">${inGroup.length}${changed ? ` &middot; ${changed}` : ""}</span></td>` +
          `<td class="right dim">${escapeHtml(t.groupLevel)}</td>` +
          `<td class="lvl">${dot(table[group] ?? "default")}` +
          `<select class="level" data-key="${escapeHtml(group)}">${options(table[group])}</select></td></tr>`;
        const items = inGroup
          .map((r) => {
            const state = r.explicit
              ? `<span class="badge">${escapeHtml(r.explicit)}</span>`
              : r.inherited
                ? `<span class="dim">${escapeHtml(t.inherits)} ${escapeHtml(r.inherited.from)}: ${escapeHtml(r.inherited.level)}</span>`
                : `<span class="dim">${escapeHtml(r.own)}${r.offByDefault ? ", " + escapeHtml(t.offByDefault) : ""}</span>`;
            const doc = r.doc
              ? `<a class="doc" href="#" data-page="${escapeHtml(r.doc.page)}" ` +
                `data-anchor="${escapeHtml(r.doc.anchor ?? "")}">${escapeHtml(t.docs)}</a>`
              : "";
            return (
              `<tr class="rule" data-group="${escapeHtml(r.group)}" data-changed="${r.explicit ? "1" : "0"}" ` +
              `data-text="${escapeHtml((r.id + " " + r.title).toLowerCase())}">` +
              `<td class="tier">${escapeHtml(r.tier)}</td>` +
              `<td class="id">${escapeHtml(r.id)}</td>` +
              `<td class="title">${escapeHtml(r.title)} ${doc}<div class="state">${state}</div></td>` +
              `<td class="lvl">${dot(effective(r))}` +
              `<select class="level" data-key="${escapeHtml(r.id)}">${options(r.explicit)}</select></td></tr>`
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
  /* 90ch, not 78: the cap is there so one sentence does not stretch across a whole monitor, and
     it only has to be wider than half the text for the line to settle on two. This caption is 168
     characters in Russian and 148 in English, and at 78ch both took a third line. Not the 110ch
     of the dictionary panel either - that one carries a longer caption, and a cap far wider than
     half of this text would leave a ragged short second line. */
  p.lead { color: var(--vscode-descriptionForeground); margin: 0 0 12px; max-width: 90ch; }
  .bar { display: flex; gap: 12px; align-items: center; margin-bottom: 10px; flex-wrap: wrap; }
  input[type=search] { flex: 1 1 220px; padding: 4px 6px; background: var(--vscode-input-background);
    color: var(--vscode-input-foreground); border: 1px solid var(--vscode-input-border, transparent); }
  select, button { background: var(--vscode-dropdown-background); color: var(--vscode-dropdown-foreground);
    border: 1px solid var(--vscode-dropdown-border, transparent); padding: 3px 6px; }
  button { background: var(--vscode-button-secondaryBackground); color: var(--vscode-button-secondaryForeground);
    border: none; cursor: pointer; }
  table { border-collapse: collapse; width: 100%; }
  td { padding: 4px 8px; border-bottom: 1px solid var(--vscode-widget-border, rgba(128,128,128,.25)); vertical-align: top; }
  tr.group td { background: var(--vscode-editorWidget-background); cursor: pointer; user-select: none; }
  .caret { display: inline-block; width: 12px; color: var(--vscode-descriptionForeground); }
  tr.group.open .caret { transform: rotate(90deg); }
  .tier { width: 2ch; color: var(--vscode-descriptionForeground); }
  .id { font-family: var(--vscode-editor-font-family); white-space: nowrap; }
  .dim { color: var(--vscode-descriptionForeground); }
  .right { text-align: right; }
  .state { font-size: 11px; margin-top: 2px; }
  .badge { background: var(--vscode-badge-background); color: var(--vscode-badge-foreground); padding: 0 6px; border-radius: 8px; }
  td.lvl { white-space: nowrap; }
  .lvl-icon { vertical-align: middle; margin-right: 7px; fill: var(--vscode-descriptionForeground); }
  .lvl-icon.error { fill: var(--vscode-editorError-foreground, #f14c4c); }
  .lvl-icon.warning { fill: var(--vscode-editorWarning-foreground, #cca700); }
  .lvl-icon.info { fill: var(--vscode-editorInfo-foreground, #3794ff); }
  .lvl-icon.hint { fill: var(--vscode-editorHint-foreground, #969696); }
  /* a rule switched off is dimmed: the grey crossed circle reads before opening the list */
  .lvl-icon.off { fill: var(--vscode-descriptionForeground); opacity: 0.7; }
  .lvl-icon.default { fill: var(--vscode-descriptionForeground); opacity: 0.4; }
  a.doc { color: var(--vscode-textLink-foreground); text-decoration: none; font-size: 11px; white-space: nowrap; }
  a.doc:hover { text-decoration: underline; }
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
  document.querySelectorAll("a.doc").forEach((a) => {
    a.addEventListener("click", (e) => {
      e.preventDefault();
      vscodeApi.postMessage({ type: "docs", page: a.dataset.page, anchor: a.dataset.anchor || undefined });
    });
  });
  // Groups start collapsed: there are more than two hundred rules, and what you open is what you look for.
  // The panel rebuilds its html after every write, so the folded state lives in the webview state -
  // otherwise picking a level folded everything back and the list jumped under the cursor.
  const saved = vscodeApi.getState();
  const collapsed = new Set(
    saved && saved.collapsed
      ? saved.collapsed
      : Array.from(document.querySelectorAll("tr.group"), (g) => g.dataset.group)
  );
  const remember = () => vscodeApi.setState({ collapsed: Array.from(collapsed) });
  const apply = () => {
    const q = document.getElementById("q").value.trim().toLowerCase();
    const onlyChanged = document.getElementById("changed").checked;
    const searching = Boolean(q) || onlyChanged;
    const shown = new Set();
    document.querySelectorAll("tr.rule").forEach((tr) => {
      const matches = (!q || tr.dataset.text.includes(q)) && (!onlyChanged || tr.dataset.changed === "1");
      // a search shows its hits regardless of the collapsed state - otherwise searching looks broken
      const open = searching || !collapsed.has(tr.dataset.group);
      const visible = matches && open;
      tr.style.display = visible ? "" : "none";
      if (matches) { shown.add(tr.dataset.group); }
    });
    document.querySelectorAll("tr.group").forEach((head) => {
      const group = head.dataset.group;
      head.style.display = shown.has(group) ? "" : "none";
      head.classList.toggle("open", searching || !collapsed.has(group));
    });
  };
  document.querySelectorAll("tr.group").forEach((head) => {
    head.addEventListener("click", (e) => {
      if (e.target.closest("select")) { return; }   // picking the group level must not fold it
      const group = head.dataset.group;
      collapsed.has(group) ? collapsed.delete(group) : collapsed.add(group);
      remember();
      apply();
    });
  });
  document.getElementById("q").addEventListener("input", apply);
  document.getElementById("changed").addEventListener("change", apply);
  apply();
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
