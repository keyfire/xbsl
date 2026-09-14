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
  const settings: Record<string, any> = { projectRoot: "src", "lsp.enabled": false, "linter.run": "onType", "linter.debounce": 300, workspaceLint: false };
  const events: Record<string, Function> = {}, commands: Record<string, Function> = {};
  const documents: any[] = [], buffers: any[] = [], projects: any[] = [], actions: any[] = [];
  const findings = new Map<string, any[]>(), timers = new Map<number, { fn: Function; delay: number }>();
  let timer = 0, lsp = false;
  const collection = {
    set: (key: any, value: any[]) => findings.set(key.toString(), value), delete: (key: any) => findings.delete(key.toString()),
    clear: () => findings.clear(), forEach: (fn: Function) => findings.forEach((value, key) => fn(uri(key), value)),
  };
  const editor = {
    env: { language: "en" }, Uri: { file: uri }, l10n: { t: (text: string) => text },
    workspace: {
      workspaceFolders: [folder], textDocuments: documents,
      getWorkspaceFolder: (key: any) => key.fsPath.startsWith(root + path.sep) ? folder : undefined,
      getConfiguration: () => ({ get: (key: string) => settings[key], inspect: (key: string) => ({ globalValue: settings[key] }) }),
      ...Object.fromEntries(["Open", "Change", "Save", "Close"].map((kind) => [`onDid${kind}TextDocument`, (fn: Function) => { events[kind] = fn; }])),
      onDidChangeWorkspaceFolders: (fn: Function) => { events.Folders = fn; },
      onDidChangeConfiguration: (fn: Function) => { events.Configuration = fn; },
    },
    window: { createOutputChannel: () => ({ appendLine() {}, show() {} }), showErrorMessage: async () => undefined },
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
    "./lspClient": { lspActive: () => lsp, activateLsp: async () => lsp, setAfterServerStart() {} },
    "./uiSchemaClient": { metaKeyAliases: async () => ({}) },
    "./statusBar": { registerStatusBar: () => ({ setLspMode() {} }) },
    "./codeActions": { PROVIDED_KINDS: [], XbslCodeActionProvider: class { constructor(public lookup: Function) {} } },
    "./linter": {
      lintBuffer: (...args: any[]) => { const request = pending(); buffers.push({ args, ...request }); return request.promise; },
      lintPath: (...args: any[]) => { const request = pending(); projects.push({ args, ...request }); return { result: request.promise, cancel() {} }; },
      toDiagnostic: (raw: any) => raw, makeDiagnostic: (raw: any) => raw,
    },
  };
  function load(filename: string): any {
    const module = { exports: {} };
    const code = transformSync(fs.readFileSync(path.resolve("src", filename), "utf8"), { loader: "ts", format: "cjs" }).code;
    vm.runInNewContext(code, { module, exports: module.exports, console,
      require: (name: string) => name === "./workspaceCore" ? load("workspaceCore.ts") : dependencies[name] ?? noops,
      setTimeout: (fn: Function, delay: number) => { timers.set(++timer, { fn, delay }); return timer; }, clearTimeout: (id: number) => timers.delete(id),
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
  return { root, doc, settings, events, commands, findings, buffers, projects, actions, tick, finishProject,
    setLsp: (value: boolean) => { lsp = value; }, start: () => extension.activate({ subscriptions: [], globalState: {} }) };
}
let failures = 0;
async function test(name: string, run: () => Promise<void>) {
  try { await run(); console.log(`ok   ${name}`); } catch (error) { failures++; console.error(`FAIL ${name}`, error); }
}
const raw = (file: string, rule: string): RawDiag => ({ path: file, rule, message: rule, severity: "warning", line: 1, col: 1, fix: { start: 0, end: 1, newText: "x" } });
async function main() {
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
  if (failures) process.exitCode = 1;
}
void main();