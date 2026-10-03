// Run the actual CLI activation and event handlers with editor/process boundaries replaced.
import * as assert from "assert";
import * as fs from "fs";
import * as path from "path";
import * as vm from "vm";
import { transformSync } from "esbuild";
import type { RawDiag } from "../src/report";
const flush = async () => { for (let i = 0; i < 12; i++) await Promise.resolve(); };
function pending() {
  let resolve!: (result: any) => void;
  const promise = new Promise<any>((done) => { resolve = done; });
  return { promise, resolve };
}
function harness() {
  const root = path.resolve("fixture-workspace");
  const uri = (file: string) => ({ scheme: "file", fsPath: path.resolve(file), toString() { return this.fsPath; } });
  const folder = { name: "Sample", uri: uri(root) };
  const folders = [folder];
  const settings: Record<string, any> = { projectRoot: "src", "lsp.enabled": false, "linter.run": "onType", "linter.debounce": 300, workspaceLint: false };
  const events: Record<string, Function> = {}, commands: Record<string, Function> = {};
  const documents: any[] = [], buffers: any[] = [], projects: any[] = [], actions: any[] = [];
  const statusItems: any[] = [], errors: string[] = [];
  const manualChecks: any[] = [];
  const progressMessages: string[] = [], intervals = new Map<number, Function>();
  const findings = new Map<string, any[]>(), timers = new Map<number, { fn: Function; delay: number }>();
  let timer = 0, lsp = false;
  const collection = {
    set: (key: any, value: any[]) => findings.set(key.toString(), value), delete: (key: any) => findings.delete(key.toString()),
    clear: () => findings.clear(), forEach: (fn: Function) => findings.forEach((value, key) => fn(uri(key), value)),
  };
  const editor = {
    env: { language: "en" }, Uri: { file: uri },
    l10n: { t: (text: string, ...values: any[]) => text.replace(/\{(\d+)\}/g, (_, index) => String(values[Number(index)])) },
    ProgressLocation: { Window: 10, Notification: 15 }, StatusBarAlignment: { Left: 1 },
    workspace: {
      workspaceFolders: folders, textDocuments: documents,
      getWorkspaceFolder: (key: any) => folders.find((entry) => key.fsPath.startsWith(entry.uri.fsPath + path.sep)),
      getConfiguration: () => ({ get: (key: string) => settings[key], inspect: (key: string) => ({ globalValue: settings[key] }) }),
      ...Object.fromEntries(["Open", "Change", "Save", "Close"].map((kind) => [`onDid${kind}TextDocument`, (fn: Function) => { events[kind] = fn; }])),
      onDidChangeWorkspaceFolders: (fn: Function) => { events.Folders = fn; },
      onDidChangeConfiguration: (fn: Function) => { events.Configuration = fn; },
    },
    window: {
      createOutputChannel: () => ({ appendLine() {}, show() {} }),
      showErrorMessage: async (message: string) => { errors.push(message); },
      withProgress: async (_options: any, work: Function) => work({ report: (value: any) => progressMessages.push(value.message) }),
      createStatusBarItem: () => {
        const item = { text: "", tooltip: "", command: undefined, show() {}, hide() {} };
        statusItems.push(item); return item;
      },
    },
    commands: { registerCommand: (name: string, fn: Function) => { commands[name] = fn; }, executeCommand() {} },
    languages: { createDiagnosticCollection: () => collection, registerCodeActionsProvider: (selector: any, provider: any) => { actions.push({ selector, provider }); } },
  };
  const noops = new Proxy({}, { get: () => () => ({}) });
  const dependencies: Record<string, any> = {
    vscode: editor, path,
    fs: { existsSync: (file: string) => [path.join(root, "src"), path.join(root, "xbsl-translation.yaml")].includes(file), statSync: (file: string) => ({ isDirectory: () => file === path.join(root, "src"), isFile: () => file === path.join(root, "xbsl-translation.yaml") }) },
    "./report": { ciSettings: () => ({}) },
    "./excludeAction": { baselineForLint: () => undefined, registerExcludeAction() {} },
    "./ruleConfig": { engineRuleArgs: () => ({}), ruleOverride: () => undefined, primeRuleCatalogue() {}, registerRuleConfig() {} },
    "./lspClient": { reindexProject: (report: Function) => { const request = pending(); manualChecks.push({ report, ...request }); return request.promise; }, lspActive: () => lsp, activateLsp: async () => lsp, setAfterServerStart() {} },
    "./uiSchemaClient": { metaKeyAliases: async () => ({}) },
    "./statusBar": { registerStatusBar: () => ({ setLspMode() {} }) },
    "./codeActions": { PROVIDED_KINDS: [], XbslCodeActionProvider: class { constructor(public lookup: Function) {} } },
    "./linter": {
      lintBuffer: (...args: any[]) => { const request = pending(); buffers.push({ args, ...request }); return request.promise; },
      lintPath: (...args: any[]) => {
        const request = pending();
        const entry = { args, ...request, canceled: 0 };
        projects.push(entry);
        return { result: request.promise, cancel() { entry.canceled++; request.resolve({ canceled: true }); } };
      },
      toDiagnostic: (raw: any) => raw, makeDiagnostic: (raw: any) => raw,
    },
  };
  function load(filename: string): any {
    const module = { exports: {} };
    const code = transformSync(fs.readFileSync(path.resolve("src", filename), "utf8"), { loader: "ts", format: "cjs" }).code;
    vm.runInNewContext(code, { module, exports: module.exports, console,
      require: (name: string) => ["./workspaceCore", "./projectCheck", "./projectCheckCore", "./projectCheckProgressCore"].includes(name)
        ? load(name.slice(2) + ".ts") : dependencies[name] ?? noops,
      setTimeout: (fn: Function, delay: number) => { timers.set(++timer, { fn, delay }); return timer; }, clearTimeout: (id: number) => timers.delete(id),
      setInterval: (fn: Function) => { intervals.set(++timer, fn); return timer; }, clearInterval: (id: number) => intervals.delete(id),
    });
    return module.exports;
  }
  const extension = load("extension.ts");
  const doc = (relative: string, languageId = "yaml") => {
    const value = { uri: uri(path.join(root, relative)), languageId, version: 1, isDirty: true, isClosed: false, getText: () => "unsaved: buffer\n" };
    documents.push(value); return value;
  };
  const tick = async (delay: number) => { for (const [id, value] of [...timers]) if (value.delay === delay) { timers.delete(id); value.fn(); } await flush(); };
  const finishProject = async (diags: any[]) => { projects[0].resolve({ report: { diagnostics: diags } }); projects[1]?.resolve({ report: { diagnostics: [] } }); await flush(); };
  return { root, uri, folders, doc, settings, events, commands, findings, buffers, projects, actions, statusItems, errors, manualChecks, progressMessages, intervals, tick, finishProject,
    setLsp: (value: boolean) => { lsp = value; }, start: () => extension.activate({ subscriptions: [], globalState: {} }) };
}
let failures = 0;
async function test(name: string, run: () => Promise<void>) {
  try { await run(); console.log(`ok   ${name}`); } catch (error) { failures++; console.error(`FAIL ${name}`, error); }
}
const raw = (file: string, rule: string): RawDiag => ({ path: file, rule, message: rule, severity: "warning", line: 1, col: 1, fix: { start: 0, end: 1, newText: "x" } });
async function main() {
  await test("manual LSP checking shows phase percentage beside the spinner without a popup", async () => {
    const h = harness(); h.setLsp(true); await h.start();
    const manual = h.commands["xbsl.reindexProject"](); await flush();
    assert.strictEqual(h.manualChecks.length, 1);
    const active = h.manualChecks[0];
    active.report({ kind: "report", message: "Stage 2/8: Index 80% – 8/10; 2 remaining" });
    assert.strictEqual(h.statusItems[0].text, "$(sync~spin) 2/8 Index · 80%");
    active.report({ kind: "report", message: "Stage 4/8: File rules 0% – 0/10; 10 remaining" });
    assert.strictEqual(h.statusItems[0].text, "$(sync~spin) 4/8 File rules · 0%", "a new phase starts its own percentage");
    assert.ok(h.statusItems[0].tooltip.includes("10 remaining"));
    assert.ok(h.statusItems[0].tooltip.includes("Elapsed:"));
    assert.strictEqual(h.progressMessages.length, 0);
    active.resolve({ ok: true, files: 10, diagnostics: 0 }); await manual;
    assert.strictEqual(h.statusItems[0].text, "$(refresh)");
    assert.strictEqual(h.intervals.size, 0);
    assert.deepStrictEqual(h.errors, []);
  });
  await test("project YAML uses unsaved text, a relative filename and registered quick fixes", async () => {
    const h = harness(); await h.start(); const doc = h.doc("src/Item.yaml"); h.events.Change({ document: doc, contentChanges: [{ text: "edit" }] }); await h.tick(300);
    assert.strictEqual(h.buffers.length, 1);
    assert.deepStrictEqual(h.buffers[0].args.slice(0, 3), ["unsaved: buffer\n", path.join("src", "Item.yaml"), h.root]);
    const finding = raw(doc.uri.fsPath, "yaml/unknown-property"); h.buffers[0].resolve({ report: { diagnostics: [finding] } }); await flush();
    assert.strictEqual(h.findings.get(doc.uri.toString())?.[0]?.rule, finding.rule);
    const registered = h.actions.find(({ selector }) => (Array.isArray(selector) ? selector : [selector]).some((entry: any) => entry.language === "yaml"));
    assert.ok(registered, "YAML quick fixes must be registered"); assert.strictEqual(registered.provider.lookup(doc.uri)?.version, doc.version);
  });
  await test("a narrowed root excludes unrelated YAML but keeps modules and the serving dictionary", async () => {
    const h = harness(); await h.start();
    for (const [name, language] of [["other/config.yaml", "yaml"], ["src-extra/Item.yaml", "yaml"], ["src/.cache/Item.yaml", "yaml"], ["other/Module.xbsl", "xbsl"], ["xbsl-translation.yaml", "yaml"]]) h.events.Change({ document: h.doc(name, language), contentChanges: [{ text: "edit" }] });
    await h.tick(300); assert.deepStrictEqual(h.buffers.map((entry) => entry.args[1]).sort(), [path.join("other", "Module.xbsl"), "xbsl-translation.yaml"].sort());
  });
  await test("a clean opened YAML preserves project findings and restores its fix snapshot", async () => {
    const h = harness(); await h.start(); h.settings.workspaceLint = true; const doc = h.doc("src/Item.yaml"); doc.isDirty = false;
    h.events.Save(doc); await h.tick(500); const finding = raw(doc.uri.fsPath, "structure/project-rule"); await h.finishProject([finding]);
    h.events.Close(doc); h.events.Open(doc); await flush();
    assert.strictEqual(h.buffers.length, 0); assert.strictEqual(h.findings.get(doc.uri.toString())?.[0]?.rule, finding.rule);
    assert.strictEqual(h.actions[0].provider.lookup(doc.uri)?.version, doc.version);
  });
  for (const running of [false, true]) await test(`saving invalidates a ${running ? "running" : "debounced"} buffer check before project publication`, async () => {
    const h = harness(); await h.start(); h.settings.workspaceLint = true; const doc = h.doc("src/Item.xbsl", "xbsl");
    h.events.Change({ document: doc, contentChanges: [{ text: "edit" }] }); if (running) await h.tick(300);
    doc.isDirty = false; h.events.Save(doc); await h.tick(500); const finding = raw(doc.uri.fsPath, "structure/project-rule"); await h.finishProject([finding]);
    await h.tick(300); if (running) { h.buffers[0].resolve({ report: { diagnostics: [] } }); await flush(); } else assert.strictEqual(h.buffers.length, 0);
    assert.strictEqual(h.findings.get(doc.uri.toString())?.[0]?.rule, finding.rule);
  });
  await test("project runs preserve dirty YAML findings", async () => {
    const h = harness(); await h.start(); const doc = h.doc("src/Item.yaml"); h.events.Change({ document: doc, contentChanges: [{ text: "edit" }] }); await h.tick(300); assert.strictEqual(h.buffers.length, 1);
    const finding = raw(doc.uri.fsPath, "yaml/unknown-property"); h.buffers[0].resolve({ report: { diagnostics: [finding] } }); await flush();
    h.settings.workspaceLint = true; const other = h.doc("src/Other.yaml"); other.isDirty = false; h.events.Save(other); await h.tick(500); await h.finishProject([raw(doc.uri.fsPath, "structure/project-rule")]);
    assert.strictEqual(h.findings.get(doc.uri.toString())?.[0]?.rule, finding.rule);
  });
  await test("changed and closed buffers discard stale results", async () => {
    for (const close of [false, true]) {
      const h = harness(); await h.start(); const doc = h.doc("src/Item.xbsl", "xbsl"); h.events.Change({ document: doc, contentChanges: [{ text: "edit" }] }); await h.tick(300);
      if (close) { doc.isClosed = true; h.events.Close(doc); } else doc.version++;
      h.buffers[0].resolve({ report: { diagnostics: [raw(doc.uri.fsPath, "style/example")] } }); await flush(); assert.ok(!h.findings.has(doc.uri.toString()));
    }
  });
  await test("LSP prevents delayed CLI checks and late CLI publication", async () => {
    for (const running of [false, true]) {
      const h = harness(); await h.start(); const doc = h.doc("src/Item.xbsl", "xbsl"); h.events.Change({ document: doc, contentChanges: [{ text: "edit" }] }); if (running) await h.tick(300);
      h.setLsp(true); await h.tick(300);
      if (running) { h.buffers[0].resolve({ report: { diagnostics: [raw(doc.uri.fsPath, "style/example")] } }); await flush(); } else assert.strictEqual(h.buffers.length, 0);
      assert.ok(!h.findings.has(doc.uri.toString()));
    }
  });
  await test("LSP activation registers no competing CLI handlers or quick fixes", async () => {
    const h = harness(); h.settings["lsp.enabled"] = true; h.setLsp(true); await h.start(); assert.strictEqual(h.events.Change, undefined); assert.strictEqual(h.actions.length, 0);
  });
  await test("onSave checks YAML once and off does not start buffer checks", async () => {
    for (const mode of ["onSave", "off"]) {
      const h = harness(); h.settings["linter.run"] = mode; await h.start();
      const doc = h.doc("src/Item.yaml"); h.events.Change({ document: doc, contentChanges: [{ text: "edit" }] }); await h.tick(300);
      assert.strictEqual(h.buffers.length, 0); doc.isDirty = false; h.events.Save(doc); await flush();
      assert.strictEqual(h.buffers.length, mode === "onSave" ? 1 : 0);
    }
  });
  await test("empty change events after a save cannot schedule another buffer check", async () => {
    const h = harness(); await h.start(); h.settings.workspaceLint = true;
    const doc = h.doc("src/Item.yaml"); doc.isDirty = false; h.events.Save(doc);
    h.events.Change({ document: doc, contentChanges: [] }); await h.tick(300);
    assert.strictEqual(h.buffers.length, 0);
  });
  await test("the newest same-version request wins and a reset invalidates earlier requests", async () => {
    const h = harness(); await h.start(); const doc = h.doc("src/Item.yaml");
    h.events.Open(doc); h.commands["xbsl.restartLinter"](); await flush(); assert.strictEqual(h.buffers.length, 2);
    const finding = raw(doc.uri.fsPath, "yaml/new-rule");
    h.buffers[1].resolve({ report: { diagnostics: [finding] } }); await flush();
    h.buffers[0].resolve({ report: { diagnostics: [] } }); await flush();
    assert.strictEqual(h.findings.get(doc.uri.toString())?.[0]?.rule, finding.rule);
  });
  await test("a clean project report clears a previous fix snapshot", async () => {
    const h = harness(); await h.start(); const doc = h.doc("src/Item.yaml"); h.events.Open(doc);
    h.buffers[0].resolve({ report: { diagnostics: [raw(doc.uri.fsPath, "yaml/unknown-property")] } }); await flush();
    assert.ok(h.actions[0].provider.lookup(doc.uri));
    h.settings.workspaceLint = true; doc.isDirty = false; h.events.Save(doc); await h.tick(500); await h.finishProject([]);
    assert.strictEqual(h.actions[0].provider.lookup(doc.uri), undefined); assert.ok(!h.findings.has(doc.uri.toString()));
  });
  await test("the manual project check waits for the save replacement without canceling it", async () => {
    const h = harness(); await h.start(); h.settings.workspaceLint = true;
    const manual = h.commands["xbsl.reindexProject"]();
    assert.strictEqual(h.commands["xbsl.reindexProject"](), manual, "duplicate clicks share the manual operation");
    await flush(); assert.strictEqual(h.projects.length, 2);
    assert.ok(h.statusItems[0].text.startsWith("$(sync~spin) "));
    assert.strictEqual(h.progressMessages.length, 0, "manual checking must not open a progress popup");
    assert.ok(h.statusItems[0].tooltip.includes("Elapsed:"));
    assert.strictEqual(h.intervals.size, 1);
    const doc = h.doc("src/Item.xbsl", "xbsl"); doc.isDirty = false;
    h.events.Save(doc); await h.tick(500);
    assert.strictEqual(h.projects.length, 4);
    let finished = false; void manual.then(() => { finished = true; }); await flush();
    assert.strictEqual(finished, false, "canceling the first run must not complete the manual operation");
    assert.ok(h.statusItems[0].text.startsWith("$(sync~spin) "));
    assert.strictEqual(h.projects[2].canceled, 0, "following a replacement must not cancel it");
    assert.strictEqual(h.projects[2].args[1], h.root, "replacement keeps the workspace cwd");
    h.projects[2].resolve({ report: { diagnostics: [] } }); h.projects[3].resolve({ report: { diagnostics: [] } });
    await manual; assert.strictEqual(h.statusItems[0].text, "$(refresh)");
    assert.strictEqual(h.intervals.size, 0, "completed or failed checks release the elapsed clock");
    assert.deepStrictEqual(h.errors, []);
  });
  await test("the manual project check follows successive save replacements", async () => {
    const h = harness(); await h.start(); h.settings.workspaceLint = true;
    const manual = h.commands["xbsl.reindexProject"](); await flush();
    const doc = h.doc("src/Item.xbsl", "xbsl"); doc.isDirty = false;
    h.events.Save(doc); await h.tick(500);
    h.events.Save(doc); await h.tick(500);
    assert.strictEqual(h.projects.length, 6);
    assert.ok(h.statusItems[0].text.startsWith("$(sync~spin) "));
    assert.strictEqual(h.projects[4].canceled, 0);
    h.projects[4].resolve({ report: { diagnostics: [] } }); h.projects[5].resolve({ report: { diagnostics: [] } });
    await manual; assert.strictEqual(h.statusItems[0].text, "$(refresh)");
    assert.strictEqual(h.intervals.size, 0, "completed or failed checks release the elapsed clock");
    assert.deepStrictEqual(h.errors, []);
  });
  await test("a failed replacement ends the manual operation with an error and no retry", async () => {
    const h = harness(); await h.start(); h.settings.workspaceLint = true;
    const manual = h.commands["xbsl.reindexProject"](); await flush();
    const doc = h.doc("src/Item.xbsl", "xbsl"); doc.isDirty = false;
    h.events.Save(doc); await h.tick(500);
    h.projects[2].resolve({ error: "synthetic CLI failure" }); h.projects[3].resolve({ report: { diagnostics: [] } });
    await manual; await h.tick(500);
    assert.strictEqual(h.projects.length, 4, "a failed run must not be enqueued again");
    assert.strictEqual(h.statusItems[0].text, "$(refresh)");
    assert.strictEqual(h.intervals.size, 0, "completed or failed checks release the elapsed clock");
    assert.strictEqual(h.errors.length, 1);
    assert.ok(h.errors[0].includes("synthetic CLI failure"));
  });
  await test("cancellation without a replacement is reported instead of claiming completion", async () => {
    const h = harness(); await h.start();
    const manual = h.commands["xbsl.reindexProject"](); await flush();
    h.commands["xbsl.restartLinter"]();
    await manual;
    assert.strictEqual(h.projects.length, 2);
    assert.strictEqual(h.statusItems[0].text, "$(refresh)");
    assert.strictEqual(h.intervals.size, 0, "completed or failed checks release the elapsed clock");
    assert.strictEqual(h.errors.length, 1);
    assert.ok(h.errors[0].includes("canceled"));
  });
  await test("a replacement dictionary failure is surfaced without retrying the project", async () => {
    const h = harness(); await h.start(); h.settings.workspaceLint = true;
    const manual = h.commands["xbsl.reindexProject"](); await flush();
    const doc = h.doc("src/Item.xbsl", "xbsl"); doc.isDirty = false;
    h.events.Save(doc); await h.tick(500);
    h.projects[2].resolve({ report: { diagnostics: [] } }); h.projects[3].resolve({ error: "synthetic dictionary failure" });
    await manual; await h.tick(500);
    assert.strictEqual(h.projects.length, 4);
    assert.strictEqual(h.statusItems[0].text, "$(refresh)");
    assert.strictEqual(h.intervals.size, 0, "completed or failed checks release the elapsed clock");
    assert.strictEqual(h.errors.length, 1);
    assert.ok(h.errors[0].includes("synthetic dictionary failure"));
  });
  await test("a manual multi-root check waits for every folder before reporting an error", async () => {
    const h = harness(); h.folders.push({ name: "Second", uri: h.uri(path.resolve("fixture-second-workspace")) }); await h.start();
    const manual = h.commands["xbsl.reindexProject"](); await flush();
    assert.strictEqual(h.projects.length, 2);
    h.projects[0].resolve({ error: "synthetic first-folder failure" }); h.projects[1].resolve({ report: { diagnostics: [] } });
    await flush(); await flush(); assert.strictEqual(h.projects.length, 3);
    assert.ok(h.statusItems[0].text.startsWith("$(sync~spin) "), "the second folder is still being checked");
    assert.strictEqual(h.errors.length, 0, "report failure after all folders finish");
    h.projects[2].resolve({ report: { diagnostics: [] } });
    await manual; assert.strictEqual(h.statusItems[0].text, "$(refresh)");
    assert.strictEqual(h.intervals.size, 0, "completed or failed checks release the elapsed clock");
    assert.strictEqual(h.errors.length, 1);
    assert.ok(h.errors[0].includes("synthetic first-folder failure"));
  });
  for (const failed of [false, true]) await test(`a manual check follows a save racing with a ${failed ? "failed" : "completed"} result`, async () => {
    const h = harness(); await h.start(); h.settings.workspaceLint = true;
    const manual = h.commands["xbsl.reindexProject"](); await flush();
    const doc = h.doc("src/Item.xbsl", "xbsl"); doc.isDirty = false;
    h.projects[0].resolve(failed ? { error: "superseded CLI failure" } : { report: { diagnostics: [] } });
    h.projects[1].resolve({ report: { diagnostics: [] } });
    h.events.Save(doc); await h.tick(500); await flush();
    assert.strictEqual(h.projects.length, 4);
    assert.ok(h.statusItems[0].text.startsWith("$(sync~spin) "), "a newer run is already pending");
    assert.strictEqual(h.errors.length, 0);
    h.projects[2].resolve({ report: { diagnostics: [] } }); h.projects[3].resolve({ report: { diagnostics: [] } });
    await manual; assert.strictEqual(h.statusItems[0].text, "$(refresh)");
    assert.strictEqual(h.intervals.size, 0, "completed or failed checks release the elapsed clock");
    assert.strictEqual(h.errors.length, 0);
  });
  if (failures) process.exitCode = 1;
}
void main();