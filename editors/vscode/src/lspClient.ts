// Experimental LSP mode (xbsl.lsp.enabled): instead of CLI calls on every event the
// extension starts a long-lived xbsl-lsp server (the [lsp] extra of the xbsl package) and
// hands diagnostics, navigation, completion, hover and quick fixes over to it. Element data
// and the project index live in the server's memory - typing feedback does not pay for
// interpreter startup.

import * as vscode from "vscode";
import {
  LanguageClient,
  LanguageClientOptions,
  ServerOptions,
} from "vscode-languageclient/node";
import { baselineForLint } from "./excludeAction";
import { pipInstallCommand, runInstallTask } from "./installer";
import { applyOverride, mergeOffRules } from "./ruleConfig";
import { docCode } from "./ruleDocs";

let client: LanguageClient | undefined;
let baselineArg: string | undefined;
// The shared "XBSL" output channel (created in extension.ts, handed over on LSP start):
// failed custom requests are logged there instead of vanishing without a trace.
let outputChannel: vscode.OutputChannel | undefined;

// Whether LSP mode is active (the server is up). The docs panel is a thin client to the server.
export function lspActive(): boolean {
  return client !== undefined;
}

// Whether --baseline was passed to the server at startup. If there was no baseline yet (the
// first exclusion just creates the file), the server needs a restart with new arguments, not
// an xbsl/relint.
export function lspBaselinePassed(): boolean {
  return baselineArg !== undefined;
}

// Custom request to the server (xbsl/docs*, xbsl/form* and friends). Returns undefined when
// the server is not up or the request failed - the consumer shows this as "data unavailable"
// instead of crashing. The failure itself is logged to the XBSL output channel: the callers'
// generic messages ("the engine does not answer") are undiagnosable without the real error.
export async function lspRequest<T>(method: string, params: unknown): Promise<T | undefined> {
  if (!client) {
    return undefined;
  }
  try {
    return await client.sendRequest<T>(method, params);
  } catch (e) {
    const msg = e instanceof Error ? e.message : String(e);
    outputChannel?.appendLine(vscode.l10n.t("XBSL LSP: the request {0} failed: {1}", method, msg));
    return undefined;
  }
}

interface SpawnPlan {
  command: string;
  args: string[];
}

// What to launch the server with: the explicit command from the setting, otherwise the
// interpreter from xbsl.linter.pythonPath (as a module), otherwise xbsl-lsp from PATH.
function spawnPlan(cfg: vscode.WorkspaceConfiguration): SpawnPlan {
  const explicit = (cfg.get<string>("lsp.command") || "").trim();
  if (explicit) {
    return { command: explicit, args: [] };
  }
  const python = (cfg.get<string>("linter.pythonPath") || "").trim();
  if (python) {
    return { command: python, args: ["-m", "xbsl.lsp"] };
  }
  return { command: "xbsl-lsp", args: [] };
}

// Builds a client from the CURRENT settings and disk state: a linter restart creates the
// client anew, so it picks up changed rule sets and a newly appeared baseline file
// (the old process's arguments cannot be rebuilt).
function buildClient(output: vscode.OutputChannel): { client: LanguageClient; plan: SpawnPlan; args: string[] } {
  const cfg = vscode.workspace.getConfiguration("xbsl");
  const folder = vscode.workspace.workspaceFolders?.[0];
  const plan = spawnPlan(cfg);
  const args = [...plan.args];
  const projectRoot = (cfg.get<string>("projectRoot") || "").trim();
  if (projectRoot) {
    args.push("--project-root", projectRoot);
  }
  for (const [flag, key] of [
    ["--select", "linter.select"],
    ["--data-dir", "linter.dataDir"],
    ["--lang", "linter.lang"],
    // A custom templates file: the server resolves a relative path from the workspace
    // folder. An empty setting is not passed - the server then defaults to
    // .xbsl-templates.json at the workspace root, the very file the panel writes.
    ["--templates", "templates.file"],
  ] as const) {
    const value = (cfg.get<string>(key) || "").trim();
    if (value) {
      args.push(flag, value);
    }
  }
  // Rules and groups disabled in the settings extend --ignore: the server does not run them.
  const ignore = mergeOffRules((cfg.get<string>("linter.ignore") || "").trim() || undefined);
  if (ignore) {
    args.push("--ignore", ignore);
  }
  // An existing baseline file: excluded findings are muted by the server. A missing one is
  // not passed - on an older server (< 0.15) an unknown key would break the startup.
  baselineArg = folder ? baselineForLint(folder.uri) : undefined;
  if (baselineArg) {
    args.push("--baseline", baselineArg);
  }

  const serverOptions: ServerOptions = {
    command: plan.command,
    args,
    options: { cwd: folder?.uri.fsPath },
  };
  // yaml is limited to the sources root so unrelated repository yamls are not linted.
  const yamlPattern = projectRoot ? `**/${projectRoot}/**/*.yaml` : "**/*.yaml";
  const clientOptions: LanguageClientOptions = {
    documentSelector: [{ language: "xbsl" }, { language: "yaml", pattern: yamlPattern }],
    outputChannel: output,
    diagnosticCollectionName: "xbsl-lsp",
    middleware: {
      // Per-rule xbsl.rules overrides on top of server diagnostics: hide off, replace
      // the severity; for a standard-backed rule the rule badge becomes a document link.
      handleDiagnostics: (uri, diagnostics, next) => {
        next(
          uri,
          diagnostics
            .map((d) => applyOverride(d, uri))
            .filter((d): d is vscode.Diagnostic => d !== null)
            .map((d) => {
              if (typeof d.code === "string") {
                d.code = docCode(d.code);
              }
              return d;
            })
        );
      },
    },
  };

  return { client: new LanguageClient("xbslLsp", "XBSL LSP", serverOptions, clientOptions), plan, args };
}

export async function activateLsp(
  context: vscode.ExtensionContext,
  output: vscode.OutputChannel,
  chosenExplicitly = true
): Promise<boolean> {
  outputChannel = output;
  const built = buildClient(output);
  client = built.client;
  try {
    await client.start();
  } catch (e) {
    const msg = e instanceof Error ? e.message : String(e);
    output.appendLine(vscode.l10n.t('XBSL LSP: the server failed to start ({0}): {1}', built.plan.command, msg));
    client = undefined;
    if (!chosenExplicitly) {
      return false;  // mode not chosen explicitly - keep working as before (CLI), details in the output panel
    }
    const install = vscode.l10n.t("Install xbsl[lsp]");
    void vscode.window
      .showErrorMessage(
        vscode.l10n.t(
          'XBSL: failed to start xbsl-lsp. Install the engine with the [lsp] extra (pip install "xbsl[lsp]") or set the command in the xbsl.lsp.command setting. The extension keeps working in the regular mode (CLI).'
        ),
        install
      )
      .then((pick) => {
        if (pick === install) {
          runInstallTask("xbsl[lsp]", pipInstallCommand("xbsl[lsp]"), "workbench.action.reloadWindow");
        }
      });
    return false;
  }
  output.appendLine(vscode.l10n.t('XBSL LSP: server started ({0} {1}).', built.plan.command, built.args.join(" ")));

  context.subscriptions.push(
    { dispose: () => void client?.stop() },
    // Commands keep their familiar identifiers in LSP mode too. A restart re-creates the
    // client instead of calling restart(): the server arguments are rebuilt from scratch.
    vscode.commands.registerCommand("xbsl.restartLinter", async () => {
      const old = client;
      client = undefined;
      if (old) {
        await old.stop().catch(() => undefined);
      }
      const fresh = buildClient(output);
      try {
        await fresh.client.start();
        client = fresh.client;
        void vscode.window.setStatusBarMessage(vscode.l10n.t("XBSL LSP: server restarted"), 3000);
      } catch (e) {
        const msg = e instanceof Error ? e.message : String(e);
        output.appendLine(vscode.l10n.t('XBSL LSP: the server failed to start ({0}): {1}', fresh.plan.command, msg));
        void vscode.window.showErrorMessage(vscode.l10n.t("XBSL LSP: the server did not restart – see the XBSL output panel."));
      }
    }),
    vscode.commands.registerCommand("xbsl.lintProject", () => {
      void vscode.window.showInformationMessage(
        vscode.l10n.t(
          'XBSL LSP: project-wide diagnostics run on the server on every save; force them with the "XBSL: restart the linter" command.'
        )
      );
    })
  );
  return true;
}
