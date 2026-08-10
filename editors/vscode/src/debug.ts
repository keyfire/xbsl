// Debugging 1C:Element applications: a thin client for the platform's own debug adapter.
//
// The extension does not ship the platform debug adapter (1C's proprietary jars): it starts the
// stock Java adapter `com.e1c.g5rt.debugger.adapter.App` from the directory named by
// xbsl.debug.adapterPath (extracted from an Element distribution) and speaks DAP to it over
// stdio - exactly the way the Theia-based IDE does.
//
// The token and the address of the debug session come from the platform through
// `elemctl apps debug` (Console API /actions/debug). The session id is generated on the client
// side and goes BOTH into the attach config and into the debuggee's URL - the debug server
// stitches the two together by it.
//
// Breakpoint binding: a module id is the file path RELATIVE to the workspace with forward
// slashes, shaped `<Vendor>/<Name>/<path in project>.xbsl`. The workspace must therefore point at
// the directory holding `<Vendor>/<Name>/Проект.yaml`; the extension finds it itself
// (detectWorkspaceRoot) even when a subdirectory is what is open in VS Code.

import * as vscode from "vscode";
import { execFile, spawn, ChildProcess } from "child_process";
import { randomUUID } from "crypto";
import * as fs from "fs";
import * as path from "path";
import { askAppId } from "./deploy";

const DEBUG_TYPE = "xbsl";

// Installing elemctl as a terminal task; on success we suggest starting the session again.
function runInstallElemctl(): void {
  const name = "elemctl";
  const task = new vscode.Task(
    { type: "shell", task: name },
    vscode.TaskScope.Workspace,
    name,
    "xbsl",
    new vscode.ShellExecution('pip install --upgrade elemctl')
  );
  void vscode.tasks.executeTask(task);
  const sub = vscode.tasks.onDidEndTaskProcess((e) => {
    if (e.execution.task.name !== name) {
      return;
    }
    sub.dispose();
    if (e.exitCode === 0) {
      void vscode.window.showInformationMessage(vscode.l10n.t("elemctl is installed – start debugging again (F5)."));
    }
  });
}
const ADAPTER_MAIN_CLASS = "com.e1c.g5rt.debugger.adapter.App";

const output = vscode.window.createOutputChannel("XBSL Debug");

interface DebugInfo {
  "debug-token": string;
  "debug-address": string;
  "client-debug-address": string;
}

// Settings of the debugger live under `xbsl.debug.*`, while elemctl itself and the application
// id are SHARED with the deploy command (`xbsl.deploy.*`) - the same binary and the same
// application, asking for them twice is what the merge of the two extensions removed. The keys of
// the retired keyfire.xbsl-debug extension are still read as a fallback, so a setup made before
// the merge keeps working without being touched.
function cfg() {
  return vscode.workspace.getConfiguration("xbsl");
}

function legacyCfg() {
  return vscode.workspace.getConfiguration("xbslDebug");
}

/** A string setting: the new key, then the retired one, then the default. */
function textSetting(key: string, legacyKey: string, fallback = ""): string {
  const own = (cfg().get<string>(key) || "").trim();
  if (own) {
    return own;
  }
  return (legacyCfg().get<string>(legacyKey) || "").trim() || fallback;
}

/** A boolean setting: an explicitly SET value wins, whichever key carries it. */
function flagSetting(key: string, legacyKey: string, fallback: boolean): boolean {
  for (const [config, name] of [[cfg(), key], [legacyCfg(), legacyKey]] as const) {
    const state = config.inspect<boolean>(name);
    const set = state?.workspaceFolderValue ?? state?.workspaceValue ?? state?.globalValue;
    if (typeof set === "boolean") {
      return set;
    }
  }
  return fallback;
}

/** The elemctl binary - shared with the deploy command. */
function elemctlBinary(): string {
  return textSetting("deploy.elemctlPath", "elemctlPath", "elemctl");
}

function log(line: string): void {
  output.appendLine(`[${new Date().toLocaleTimeString()}] ${line}`);
}

// Runs elemctl and returns the parsed JSON stdout. cwd = the sources root (where .env lives).
function runElemctl(args: string[], cwd: string | undefined): Promise<any> {
  const bin = elemctlBinary();
  log(`elemctl ${args.join(" ")} (cwd: ${cwd ?? "-"})`);
  return new Promise((resolve, reject) => {
    execFile(bin, args, { cwd, maxBuffer: 8 * 1024 * 1024, windowsHide: true }, (err, stdout, stderr) => {
      if (err) {
        const enoent = (err as NodeJS.ErrnoException).code === "ENOENT";
        const hint = enoent
          ? vscode.l10n.t("elemctl not found. Install it (pipx install elemctl) or set the path in the xbsl.deploy.elemctlPath setting.")
          : (stderr || err.message);
        const failure: Error & { notFound?: boolean } = new Error(`${bin} ${args.join(" ")}: ${hint}`);
        failure.notFound = enoent;
        reject(failure);
        return;
      }
      const text = (stdout || "").trim();
      try {
        resolve(text ? JSON.parse(text) : {});
      } catch {
        reject(new Error(`${bin} ${args.join(" ")}: ${vscode.l10n.t("output is not JSON")}: ${text.slice(0, 200)}`));
      }
    });
  });
}

// Host and port out of client-debug-address (wss://host:port) for the debuggee's parameters.
function hostPort(wssUrl: string): { host: string; port: string } {
  const u = new URL(wssUrl);
  return { host: u.hostname, port: u.port || (u.protocol === "wss:" ? "443" : "80") };
}

function listSubdirs(dir: string, limit = 64): string[] {
  try {
    return fs
      .readdirSync(dir, { withFileTypes: true })
      .filter((e) => e.isDirectory() && !e.name.startsWith(".") && e.name !== "node_modules")
      .slice(0, limit)
      .map((e) => e.name);
  } catch {
    return [];
  }
}

// For a Проект.yaml laid out as <root>/<Vendor>/<Name>/Проект.yaml returns <root> - the workspace
// value at which module ids (`Vendor/Name/...` relative to the workspace) match what the debug
// server expects.
function rootFromProjectYaml(projectYaml: string): string | undefined {
  let text: string;
  try {
    text = fs.readFileSync(projectYaml, "utf8");
  } catch {
    return undefined;
  }
  const vendor = /^Поставщик:\s*["']?([\w.-]+)["']?\s*$/mu.exec(text)?.[1];
  const name = /^Имя:\s*["']?([\w.-]+)["']?\s*$/mu.exec(text)?.[1];
  if (!vendor || !name) {
    return undefined;
  }
  const projectDir = path.dirname(projectYaml);
  if (path.basename(projectDir) !== name || path.basename(path.dirname(projectDir)) !== vendor) {
    log(vscode.l10n.t("Project {0}: directories do not match the <root>/{1}/{2} layout – this Проект.yaml is skipped.", projectYaml, vendor, name));
    return undefined;
  }
  return path.dirname(path.dirname(projectDir));
}

// Looks for the sources root: the directory holding <Vendor>/<Name>/Проект.yaml. Checks the open
// folder itself, two levels up (a project subdirectory is open) and up to two levels down (the
// repository root is open). undefined when no project is found.
export function detectWorkspaceRoot(folder: string): string | undefined {
  const candidates: string[] = [
    path.join(folder, "Проект.yaml"),
    path.join(path.dirname(folder), "Проект.yaml"),
    path.join(path.dirname(path.dirname(folder)), "Проект.yaml"),
  ];
  for (const d1 of listSubdirs(folder)) {
    candidates.push(path.join(folder, d1, "Проект.yaml"));
    for (const d2 of listSubdirs(path.join(folder, d1))) {
      candidates.push(path.join(folder, d1, d2, "Проект.yaml"));
    }
  }
  for (const c of candidates) {
    if (fs.existsSync(c)) {
      const root = rootFromProjectYaml(c);
      if (root) {
        return root;
      }
    }
  }
  return undefined;
}

function standardConfig(): vscode.DebugConfiguration {
  return {
    type: DEBUG_TYPE,
    request: "attach",
    name: vscode.l10n.t("Debug 1C:Element application"),
  };
}

// Asks elemctl for the adapter path (the elemctl.debug_adapter plugin group).
// undefined when elemctl is unavailable or no plugin ships an adapter.
async function adapterPathFromElemctl(cwd: string | undefined): Promise<string | undefined> {
  try {
    const info = await runElemctl(["debug-adapter"], cwd);
    if (info && info.found && typeof info.path === "string" && info.path.trim()) {
      return info.path.trim();
    }
  } catch (e: any) {
    log(`elemctl debug-adapter: ${e?.message ?? e}`);
  }
  return undefined;
}

// Resolves the adapter directory: an explicit xbsl.debug.adapterPath wins, otherwise whatever
// `elemctl debug-adapter` reports.
async function resolveAdapterPath(cwd: string | undefined): Promise<string> {
  const configured = textSetting("debug.adapterPath", "adapterPath");
  if (configured) {
    return configured;
  }
  const fromPlugin = await adapterPathFromElemctl(cwd);
  if (fromPlugin) {
    log(vscode.l10n.t("Adapter directory reported by elemctl: {0}", fromPlugin));
  }
  return fromPlugin || "";
}

// A proxy adapter: it spawns the stock Java adapter as a stdio DAP and rewrites outgoing
// `variables` requests that carry no `filter` into the filtered form.
//
// Why: expanding a structure or an array on a CLIENT frame with a `variables` request without a
// `filter` (GetVariableInfo with filter=NONE in the platform protocol) hangs the debuggee's JS
// runtime and tears the session down. With `filter=named`/`indexed` the same expansion works at
// any depth. The VS Code Variables panel sends the request WITHOUT a filter for variables with
// few children - hence the crash; here the filter is added on its behalf.
// (Established experimentally; neither count nor the platform version matters. The counters
// namedVariables/indexedVariables are taken from the parent's answers.)
class FilterFixDebugAdapter implements vscode.DebugAdapter {
  private readonly child: ChildProcess;
  private readonly emitter = new vscode.EventEmitter<vscode.DebugProtocolMessage>();
  readonly onDidSendMessage: vscode.Event<vscode.DebugProtocolMessage> = this.emitter.event;
  private buffer = Buffer.alloc(0);
  // variablesReference -> the number of named/indexed children (from variables/evaluate answers).
  private readonly refInfo = new Map<number, { named: number; indexed: number }>();
  private synthSeq = 1_000_000; // seq of our own sub-requests (outside the seq range of VS Code)
  // sub-request seq -> { merge id, slot }
  private readonly subToMerge = new Map<number, { mergeId: number; slot: 0 | 1 }>();
  // merge id -> context (a mixed named+indexed node: two sub-requests -> one answer)
  private readonly merges = new Map<number, { origSeq: number; parts: [any[] | null, any[] | null]; remaining: number }>();
  private rewrites = 0;

  constructor(command: string, args: string[], cwd: string | undefined) {
    this.child = spawn(command, args, { cwd, stdio: ["pipe", "pipe", "pipe"], windowsHide: true });
    this.child.stdout?.on("data", (d: Buffer) => this.onChildData(d));
    this.child.stderr?.on("data", (d: Buffer) => log(`adapter: ${d.toString("utf8").trimEnd()}`));
    this.child.on("error", (e) => log(`adapter process error: ${e.message}`));
    this.child.on("exit", (code, sig) => log(`adapter exited (code=${code ?? "-"} signal=${sig ?? "-"}); variables-запросов переписано: ${this.rewrites}`));
  }

  // A message FROM VS Code -> to the adapter. This is where a filter-less `variables` is caught.
  handleMessage(message: vscode.DebugProtocolMessage): void {
    const m = message as any;
    if (m?.type === "request" && m.command === "variables" && m.arguments && !m.arguments.filter) {
      const ref: number = m.arguments.variablesReference;
      const info = this.refInfo.get(ref);
      if (info) {
        const { named, indexed } = info;
        if (named > 0 && indexed > 0) {
          // A mixed node: split into two sub-requests (indexed, then named) and join the answers.
          const mergeId = this.synthSeq++;
          const subIndexed = this.synthSeq++;
          const subNamed = this.synthSeq++;
          this.merges.set(mergeId, { origSeq: m.seq, parts: [null, null], remaining: 2 });
          this.subToMerge.set(subIndexed, { mergeId, slot: 0 });
          this.subToMerge.set(subNamed, { mergeId, slot: 1 });
          this.rewrites++;
          this.writeToChild({ seq: subIndexed, type: "request", command: "variables", arguments: { variablesReference: ref, filter: "indexed", start: 0, count: indexed } });
          this.writeToChild({ seq: subNamed, type: "request", command: "variables", arguments: { variablesReference: ref, filter: "named", start: 0, count: named } });
          return; // the original request is not forwarded - the merge answers it
        }
        if (named > 0 || indexed > 0) {
          // A uniform node: add the filter to the same request (same seq - the answer goes as is).
          m.arguments.filter = named > 0 ? "named" : "indexed";
          m.arguments.start = 0;
          m.arguments.count = named > 0 ? named : indexed;
          this.rewrites++;
        }
      }
      // An unknown reference (a frame scope, say) works without a filter - left alone.
    }
    this.writeToChild(m);
  }

  dispose(): void {
    try {
      this.child.kill();
    } catch {
      /* already gone */
    }
    this.emitter.dispose();
  }

  // --- talking to the child process (DAP over stdio: Content-Length + JSON) ---

  private writeToChild(msg: any): void {
    const body = Buffer.from(JSON.stringify(msg), "utf8");
    this.child.stdin?.write(`Content-Length: ${body.length}\r\n\r\n`);
    this.child.stdin?.write(body);
  }

  private onChildData(chunk: Buffer): void {
    this.buffer = Buffer.concat([this.buffer, chunk]);
    for (;;) {
      const sep = this.buffer.indexOf("\r\n\r\n");
      if (sep < 0) {
        return;
      }
      const header = this.buffer.subarray(0, sep).toString("ascii");
      const match = /content-length:\s*(\d+)/i.exec(header);
      if (!match) {
        this.buffer = this.buffer.subarray(sep + 4); // a broken header - skip it
        continue;
      }
      const len = parseInt(match[1], 10);
      const start = sep + 4;
      if (this.buffer.length < start + len) {
        return; // the body has not arrived in full yet
      }
      const body = this.buffer.subarray(start, start + len).toString("utf8");
      this.buffer = this.buffer.subarray(start + len);
      let msg: any;
      try {
        msg = JSON.parse(body);
      } catch {
        continue;
      }
      this.onChildMessage(msg);
    }
  }

  // A message FROM the adapter -> to VS Code. Merge sub-answers are intercepted, counters kept.
  private onChildMessage(msg: any): void {
    if (msg?.type === "response") {
      const sub = this.subToMerge.get(msg.request_seq);
      if (sub) {
        this.subToMerge.delete(msg.request_seq);
        const ctx = this.merges.get(sub.mergeId);
        if (ctx) {
          const list: any[] = msg.success ? (msg.body?.variables ?? []) : [];
          for (const v of list) {
            this.recordVar(v);
          }
          ctx.parts[sub.slot] = list;
          ctx.remaining -= 1;
          if (ctx.remaining === 0) {
            this.merges.delete(sub.mergeId);
            const merged = [...(ctx.parts[0] ?? []), ...(ctx.parts[1] ?? [])]; // indexed, then named
            this.emitter.fire({
              seq: this.synthSeq++,
              type: "response",
              request_seq: ctx.origSeq,
              success: true,
              command: "variables",
              body: { variables: merged },
            } as any);
          }
        }
        return; // sub-request answers are not passed outwards
      }
      this.trackCounts(msg);
    }
    this.emitter.fire(msg as vscode.DebugProtocolMessage);
  }

  // Remembers namedVariables/indexedVariables from answers carrying variables or a reference.
  private trackCounts(msg: any): void {
    const body = msg.body;
    if (!body) {
      return;
    }
    if (Array.isArray(body.variables)) {
      for (const v of body.variables) {
        this.recordVar(v);
      }
    }
    // evaluate / setVariable / setExpression: the reference and counters sit in the answer body.
    if (typeof body.variablesReference === "number" && body.variablesReference > 0) {
      this.refInfo.set(body.variablesReference, { named: body.namedVariables ?? 0, indexed: body.indexedVariables ?? 0 });
    }
  }

  private recordVar(v: any): void {
    if (v && typeof v.variablesReference === "number" && v.variablesReference > 0) {
      this.refInfo.set(v.variablesReference, { named: v.namedVariables ?? 0, indexed: v.indexedVariables ?? 0 });
    }
  }
}

// Starts the stock Java adapter as a stdio DAP.
class XbslDebugAdapterFactory implements vscode.DebugAdapterDescriptorFactory {
  async createDebugAdapterDescriptor(
    session: vscode.DebugSession
  ): Promise<vscode.DebugAdapterDescriptor> {
    const cwd =
      typeof session.configuration?.workspace === "string" && session.configuration.workspace
        ? session.configuration.workspace
        : undefined;
    const adapterPath = await resolveAdapterPath(cwd);
    if (!adapterPath) {
      void offerSetup(vscode.l10n.t("The platform debug adapter path is not set (xbsl.debug.adapterPath)."));
      throw new Error(
        vscode.l10n.t("xbsl.debug.adapterPath is not set – the platform debug adapter directory (a folder with the repo subdirectory from the Element distribution). The \"XBSL: Set up 1C:Element debugging\" command can help.")
      );
    }
    if (!isAdapterDir(adapterPath)) {
      void offerSetup(vscode.l10n.t("No adapter jars found in {0} (the repo subdirectory).", adapterPath));
      throw new Error(vscode.l10n.t("xbsl.debug.adapterPath: {0} has no repo subdirectory with the adapter jars", adapterPath));
    }
    const java = textSetting("debug.javaPath", "javaPath", "java");
    const classpath = path.join(adapterPath, "repo", "*");
    const args = [
      "-Dfile.encoding=UTF-8",
      "--add-opens",
      "java.base/java.lang=ALL-UNNAMED",
      "--add-opens",
      "java.base/jdk.internal.misc=ALL-UNNAMED",
      "-cp",
      classpath,
      ADAPTER_MAIN_CLASS,
    ];
    log(`${java} -cp ${classpath} ${ADAPTER_MAIN_CLASS}`);
    // Always through the proxy that adds a filter to variables requests: without it expanding a
    // structure on a client frame crashes the debuggee (see FilterFixDebugAdapter). There is no
    // setting for this - turning the workaround off only buys a broken session.
    return new vscode.DebugAdapterInlineImplementation(new FilterFixDebugAdapter(java, args, cwd));
  }
}

// Completes the attach config: pulls the token and address through elemctl, generates the
// sessionId, adds the fields the adapter expects and schedules opening the debuggee.
class XbslConfigurationProvider implements vscode.DebugConfigurationProvider {
  async resolveDebugConfiguration(
    folder: vscode.WorkspaceFolder | undefined,
    config: vscode.DebugConfiguration
  ): Promise<vscode.DebugConfiguration | undefined> {
    if (!config.type) {
      Object.assign(config, standardConfig());
    }
    const folderPath = folder?.uri.fsPath ?? vscode.workspace.workspaceFolders?.[0]?.uri.fsPath;

    // Sources root: an explicit workspace from launch.json > auto-detection > the open folder.
    let root: string | undefined = typeof config.workspace === "string" && config.workspace ? config.workspace : undefined;
    if (!root && folderPath) {
      root = detectWorkspaceRoot(folderPath);
      if (root && path.resolve(root) !== path.resolve(folderPath)) {
        log(vscode.l10n.t("Sources root detected automatically: {0}", root));
      }
    }
    if (!root) {
      root = folderPath;
      void vscode.window.showWarningMessage(
        vscode.l10n.t("XBSL Debug: <Vendor>/<Name>/Проект.yaml not found – breakpoints may not bind. Open the repository root with the sources or set \"workspace\" in launch.json.")
      );
    }

    try {
      const globalArgs: string[] = [];
      if (typeof config.envFile === "string" && config.envFile) {
        globalArgs.push("--env-file", config.envFile);
      }
      // app-id: launch.json > the setting > .env or the environment (elemctl reads those itself).
      // Without any of them elemctl would fail with a bare "no app-id" - we ask up front and
      // remember the answer in the setting so the next run does not ask again.
      let appId = config.appId ? String(config.appId) : textSetting("deploy.appId", "appId");
      if (!appId && !envProvidesAppId(root, typeof config.envFile === "string" ? config.envFile : undefined)) {
        // The same picker the deploy uses: the applications elemctl sees, by name.
        const workspaceFolder = folder ?? vscode.workspace.workspaceFolders?.[0];
        const entered = workspaceFolder
          ? await askAppId(workspaceFolder, undefined, vscode.l10n.t("Which application to debug"))
          : await promptForAppId();
        if (entered === undefined) {
          return undefined; // cancelled input cancels debugging, with no error message
        }
        appId = entered;
        await vscode.workspace
          .getConfiguration("xbsl", folder?.uri)
          .update("deploy.appId", appId, vscode.ConfigurationTarget.Workspace);
      }
      const appArgs = appId ? [appId] : [];
      const debugInfo: DebugInfo = await runElemctl([...globalArgs, "apps", "debug", ...appArgs], root);
      if (!debugInfo["debug-address"] || !debugInfo["debug-token"]) {
        throw new Error(
          vscode.l10n.t("elemctl apps debug returned no debug-address/debug-token. Check that debugging is enabled on the server and elemctl supports `apps debug`.")
        );
      }
      const app = await runElemctl([...globalArgs, "apps", "get", ...appArgs], root).catch(() => ({}));

      const sessionId = randomUUID();
      // The adapter expects `application` in camelCase; the elemctl map uses dashes.
      const application = {
        id: app?.id,
        name: app?.name,
        error: app?.error ?? null,
        status: app?.status,
        displayName: app?.["display-name"] ?? app?.name,
        uri: app?.uri,
        spaceId: app?.["space-id"],
      };

      Object.assign(config, {
        request: "attach",
        stopOnEntry: config.stopOnEntry ?? false,
        endSessionIfClientDisconnected: true,
        clientApplicationPath: config.clientApplicationPath ?? "",
        noDebug: config.noDebug ?? false,
        debugToken: debugInfo["debug-token"],
        uri: debugInfo["debug-address"],
        sessionId,
        workspace: root,
        // The source map for external libraries; for the project's own modules the right
        // workspace is enough (a module id is the relative path).
        projectLocations: config.projectLocations ?? {},
        locale: vscode.env.language?.startsWith("ru") ? "ru" : vscode.env.language || "ru",
        clientDebugAddress: debugInfo["client-debug-address"],
        application,
        authMode: config.authMode === "anonymous" || config.authMode === "another_user" ? config.authMode : undefined,
        retryTimeout: "60",
      });

      // The debuggee URL is opened after the session starts (see onDidStartDebugSession).
      // `uri` of the card is the application's address INSIDE the platform
      // (https://<space>.1cmycloud.com/applications/<name>); an application answering on a domain
      // of its own is opened there instead - that is what xbsl.debug.applicationUrl is for.
      const configured = typeof config.applicationUrl === "string" && config.applicationUrl
        ? String(config.applicationUrl)
        : textSetting("debug.applicationUrl", "applicationUrl");
      const appUrl: string | undefined = configured || application.uri;
      if (appUrl && debugInfo["client-debug-address"]) {
        const { host, port } = hostPort(debugInfo["client-debug-address"]);
        const authModeParam = config.authMode ? `&auth-mode=${config.authMode}` : "";
        const sep = appUrl.includes("?") ? "&" : "?";
        const debuggeeUrl = `${appUrl}${sep}debug-server-host=${host}&debug-server-port=${port}&debug-session-id=${sessionId}${authModeParam}`;
        log(vscode.l10n.t("Debuggee application URL: {0}", debuggeeUrl));
        if (flagSetting("debug.openApplicationOnStart", "openApplicationOnStart", true)) {
          pendingApp.set(sessionId, debuggeeUrl);
        }
      }
      return config;
    } catch (e: any) {
      const msg = `XBSL Debug: ${e?.message ?? e}`;
      log(msg);
      const wizard = vscode.l10n.t("Setup wizard");
      const install = e?.notFound ? vscode.l10n.t("Install elemctl") : undefined;
      const buttons = install ? [install, wizard] : [wizard];
      void vscode.window.showErrorMessage(msg, ...buttons).then((a) => {
        if (install && a === install) {
          runInstallElemctl();
        } else if (a) {
          void vscode.commands.executeCommand("xbsl.debug.setup");
        }
      });
      return undefined;
    }
  }
}

// APP_ID/ELEMENT_APP_ID in .env - the sources elemctl itself reads.
const ENV_APP_ID_RE = /^\s*(?:export\s+)?(?:ELEMENT_APP_ID|APP_ID)\s*=\s*\S/m;

function envProvidesAppId(root: string | undefined, envFile?: string): boolean {
  if (process.env.ELEMENT_APP_ID || process.env.APP_ID) {
    return true;
  }
  if (!root) {
    return false;
  }
  const file = envFile ? (path.isAbsolute(envFile) ? envFile : path.join(root, envFile)) : path.join(root, ".env");
  try {
    return ENV_APP_ID_RE.test(fs.readFileSync(file, "utf8"));
  } catch {
    return false; // no file, no app-id in it
  }
}

async function promptForAppId(): Promise<string | undefined> {
  const value = await vscode.window.showInputBox({
    title: vscode.l10n.t("Application id for debugging"),
    prompt: vscode.l10n.t(
      "elemctl needs the application id (APP_ID). Take it from `elemctl apps list` or from the application card in the platform console; the value is saved to the xbsl.deploy.appId setting."
    ),
    placeHolder: "0198c0de-xxxx-xxxx-xxxx-xxxxxxxxxxxx",
    ignoreFocusOut: true,
    validateInput: (v) => (v.trim() ? undefined : vscode.l10n.t("The application id must not be empty.")),
  });
  return value === undefined ? undefined : value.trim();
}

// sessionId -> the debuggee URL opened when the session starts.
const pendingApp = new Map<string, string>();

function isAdapterDir(dir: string): boolean {
  try {
    return fs
      .readdirSync(path.join(dir, "repo"))
      .some((f) => /com\.e1c\.g5rt\.debugger\.adapter.*\.jar$/i.test(f));
  } catch {
    return false;
  }
}

function execOk(bin: string, args: string[], cwd?: string): Promise<{ ok: boolean; text: string }> {
  return new Promise((resolve) => {
    execFile(bin, args, { cwd, windowsHide: true, maxBuffer: 1024 * 1024 }, (err, stdout, stderr) => {
      resolve({ ok: !err, text: (stdout || "") + (stderr || "") + (err && !stdout && !stderr ? String(err.message) : "") });
    });
  });
}

async function offerSetup(reason: string): Promise<void> {
  const run = vscode.l10n.t("Setup wizard");
  const a = await vscode.window.showWarningMessage(`XBSL Debug: ${reason}`, run);
  if (a === run) {
    void vscode.commands.executeCommand("xbslDebug.setup");
  }
}

// Setup wizard: java -> adapter -> elemctl (.env) -> launch.json. Every step is fixed on the
// spot; the outcome is a summary and an "F5" hint.
async function setupWizard(): Promise<void> {
  output.show(true);
  const results: string[] = [];
  const folderPath = vscode.workspace.workspaceFolders?.[0]?.uri.fsPath;
  const root = folderPath ? detectWorkspaceRoot(folderPath) ?? folderPath : undefined;

  // 1. Java.
  let java = textSetting("debug.javaPath", "javaPath", "java");
  let j = await execOk(java, ["-version"]);
  if (!j.ok) {
    const pick = vscode.l10n.t("Locate java...");
    const a = await vscode.window.showWarningMessage(
      vscode.l10n.t("Java not found ({0}). The adapter needs Java 17+.", java),
      pick
    );
    if (a === pick) {
      const f = await vscode.window.showOpenDialog({ canSelectFiles: true, canSelectFolders: false, title: vscode.l10n.t("Java executable (java / java.exe)") });
      if (f?.[0]) {
        java = f[0].fsPath;
        await cfg().update("debug.javaPath", java, vscode.ConfigurationTarget.Global);
        j = await execOk(java, ["-version"]);
      }
    }
  }
  results.push((j.ok ? "$(check) " : "$(error) ") + "Java: " + (j.ok ? j.text.split("\n")[0].trim() : vscode.l10n.t("not found")));

  // 2. The platform debug adapter: the setting > what elemctl reports > picking the folder.
  let adapterPath = textSetting("debug.adapterPath", "adapterPath");
  let adapterFromPlugin = false;
  if (!adapterPath || !isAdapterDir(adapterPath)) {
    const fromPlugin = await adapterPathFromElemctl(root);
    if (fromPlugin && isAdapterDir(fromPlugin)) {
      adapterPath = fromPlugin;
      adapterFromPlugin = true;
    }
  }
  if (!adapterPath || !isAdapterDir(adapterPath)) {
    const pick = vscode.l10n.t("Choose the adapter folder...");
    const a = await vscode.window.showWarningMessage(
      vscode.l10n.t("The platform debug adapter directory is needed (a folder with a repo subdirectory holding the adapter's jar files). Take it from your 1C:Element distribution: data/ide/theia/plugins/@1c-appengine-plugin/bin/debugger."),
      pick
    );
    if (a === pick) {
      const f = await vscode.window.showOpenDialog({ canSelectFiles: false, canSelectFolders: true, title: vscode.l10n.t("Adapter directory (contains repo/)") });
      if (f?.[0]) {
        adapterPath = f[0].fsPath;
        if (isAdapterDir(adapterPath)) {
          await cfg().update("debug.adapterPath", adapterPath, vscode.ConfigurationTarget.Global);
        } else {
          void vscode.window.showErrorMessage(vscode.l10n.t("No repo/ with adapter jars found in {0}.", adapterPath));
        }
      }
    }
  }
  const adapterOk = !!adapterPath && isAdapterDir(adapterPath);
  results.push(
    (adapterOk ? "$(check) " : "$(error) ") +
      (adapterOk && adapterFromPlugin
        ? vscode.l10n.t("Adapter (reported by elemctl): {0}", adapterPath)
        : vscode.l10n.t("Adapter: {0}", adapterOk ? adapterPath : vscode.l10n.t("not configured")))
  );

  // 3. elemctl and the Console API credentials (.env in the sources root).
  const elemctlBin = elemctlBinary();
  const e = await execOk(elemctlBin, ["apps", "get"], root);
  let appLine: string;
  if (e.ok) {
    try {
      const app = JSON.parse(e.text);
      appLine = vscode.l10n.t("Application: {0} ({1})", app["display-name"] ?? app.name ?? "?", app.uri ?? "");
    } catch {
      appLine = vscode.l10n.t("elemctl responds, but the output is not JSON");
    }
  } else {
    appLine = vscode.l10n.t("elemctl: {0}", e.text.trim().slice(0, 300) || vscode.l10n.t("not found (pipx install elemctl)"));
  }
  results.push((e.ok ? "$(check) " : "$(error) ") + appLine);
  if (!e.ok && /ENOENT/i.test(e.text)) {
    const install = vscode.l10n.t("Install elemctl");
    const a = await vscode.window.showWarningMessage(
      vscode.l10n.t("elemctl was not found on PATH. Install it now?"),
      install
    );
    if (a === install) {
      runInstallElemctl();
      results.push("    " + vscode.l10n.t("Installation started in the terminal; run the wizard again after it finishes."));
    }
  }
  if (!e.ok) {
    results.push("    " + vscode.l10n.t("Check: elemctl is installed and is version >= 0.5 (the apps debug and debug-adapter commands), and the sources root has a .env with ELEMENT_BASE_URL/CLIENT_ID/CLIENT_SECRET/APP_ID."));
  }

  // 4. launch.json.
  if (folderPath) {
    const launch = path.join(folderPath, ".vscode", "launch.json");
    if (!fs.existsSync(launch)) {
      const make = vscode.l10n.t("Create launch.json");
      const a = await vscode.window.showInformationMessage(
        vscode.l10n.t("Create .vscode/launch.json with a debug configuration? (Optional: F5 works without it.)"),
        make
      );
      if (a === make) {
        fs.mkdirSync(path.dirname(launch), { recursive: true });
        fs.writeFileSync(launch, JSON.stringify({ version: "0.2.0", configurations: [standardConfig()] }, null, 2), "utf8");
        results.push("$(check) " + vscode.l10n.t("Created {0}", launch));
      }
    }
  }

  for (const r of results) {
    log(r.replace(/\$\((check|error)\) /g, (m) => (m.includes("check") ? "[ok] " : "[X] ")));
  }
  const allOk = j.ok && adapterOk && e.ok;
  const summary = allOk
    ? vscode.l10n.t("All set. Open an .xbsl file, put a breakpoint and press F5 – the application opens in the browser and execution stops on your breakpoint.")
    : vscode.l10n.t("Setup is not complete – details are in the \"XBSL Debug\" output panel.");
  void (allOk ? vscode.window.showInformationMessage(summary) : vscode.window.showWarningMessage(summary));
}

/** Registers debugging in the extension: the config provider, the adapter factory and the wizard. */
export function registerDebug(context: vscode.ExtensionContext): void {
  const provider = new XbslConfigurationProvider();
  context.subscriptions.push(
    output,
    vscode.commands.registerCommand("xbsl.debug.setup", setupWizard),
    vscode.debug.registerDebugConfigurationProvider(DEBUG_TYPE, provider),
    vscode.debug.registerDebugConfigurationProvider(
      DEBUG_TYPE,
      {
        provideDebugConfigurations(): vscode.DebugConfiguration[] {
          return [standardConfig()];
        },
      },
      vscode.DebugConfigurationProviderTriggerKind.Dynamic
    ),
    vscode.debug.registerDebugAdapterDescriptorFactory(DEBUG_TYPE, new XbslDebugAdapterFactory()),
    vscode.debug.onDidStartDebugSession((session) => {
      if (session.type !== DEBUG_TYPE) {
        return;
      }
      const sid = session.configuration?.sessionId as string | undefined;
      const url = sid ? pendingApp.get(sid) : undefined;
      if (sid && url) {
        pendingApp.delete(sid);
        void vscode.env.openExternal(vscode.Uri.parse(url));
      }
    })
  );
}
