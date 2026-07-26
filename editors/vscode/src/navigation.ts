// VS Code glue for index-based navigation: a per-workspace-folder cache of the project index
// built by the linter (loaded on activation, refreshed on save with a delay, at most one
// build process at a time), plus go-to-definition and completion providers on top of the
// pure logic from navCore.ts. When the linter cannot build the index, navigation stays
// silent: details go to the output channel, no popups.

import * as vscode from "vscode";
import { spawn } from "child_process";
import * as fs from "fs";
import * as path from "path";
import { LinterConfig } from "./report";
import {
  CompletionKind,
  INDEX_COMMAND_VARIANTS,
  IndexLookup,
  parseIndex,
  RefLocation,
  resolveCompletions,
  resolveDefinition,
  resolveReferences,
  Target,
} from "./navCore";
import { parseInternals } from "./metadataCore";

const REFRESH_DELAY = 1500; // delay (ms) before rebuilding the index on save
const OUTPUT_LIMIT = 64 * 1024 * 1024; // safety net against a runaway process

const KIND_MAP: Record<CompletionKind, vscode.CompletionItemKind> = {
  object: vscode.CompletionItemKind.Class,
  enum: vscode.CompletionItemKind.Enum,
  family: vscode.CompletionItemKind.Class,
  field: vscode.CompletionItemKind.Field,
  tabular: vscode.CompletionItemKind.Field,
  localType: vscode.CompletionItemKind.Struct,
  enumMember: vscode.CompletionItemKind.EnumMember,
  method: vscode.CompletionItemKind.Method,
  component: vscode.CompletionItemKind.Variable,
};

interface RawRun {
  stdout: string;
  error?: string;
}

function runRaw(command: string, args: string[], cwd: string): Promise<RawRun> {
  return new Promise((resolve) => {
    let child;
    try {
      child = spawn(command, args, { cwd });
    } catch (e) {
      resolve({ stdout: "", error: e instanceof Error ? e.message : String(e) });
      return;
    }
    let out = "";
    let err = "";
    child.on("error", (e) => resolve({ stdout: "", error: e.message }));
    child.stdout.on("data", (d: Buffer) => {
      if (out.length < OUTPUT_LIMIT) {
        out += d.toString("utf8");
      }
    });
    child.stderr.on("data", (d: Buffer) => {
      err += d.toString("utf8");
    });
    child.on("close", (code) => {
      if (code === 0) {
        resolve({ stdout: out });
      } else {
        resolve({ stdout: out, error: (err || out || vscode.l10n.t("exit code {0}", code ?? -1)).trim().slice(0, 500) });
      }
    });
    if (child.stdin) {
      child.stdin.on("error", () => {
        /* ignore EPIPE when the child process exited prematurely */
      });
      child.stdin.end();
    }
  });
}

class IndexCache {
  lookup: IndexLookup | undefined;
  rootFsPath: string | undefined; // from meta.root; navigation targets resolve relative to it
  private timer: NodeJS.Timeout | undefined;
  private loading = false;
  private pending = false;

  constructor(
    private readonly folder: vscode.WorkspaceFolder,
    private readonly output: vscode.OutputChannel,
    private readonly getLinter: (resource?: vscode.Uri) => LinterConfig,
    private readonly getRoot: (folder: vscode.WorkspaceFolder) => string
  ) {}

  schedule(): void {
    if (this.timer) {
      clearTimeout(this.timer);
    }
    this.timer = setTimeout(() => {
      this.timer = undefined;
      void this.refresh();
    }, REFRESH_DELAY);
  }

  async refresh(): Promise<void> {
    if (this.loading) {
      this.pending = true; // one build process at a time; re-run after the current one
      return;
    }
    this.loading = true;
    try {
      await this.load();
    } finally {
      this.loading = false;
      if (this.pending) {
        this.pending = false;
        this.schedule();
      }
    }
  }

  private async load(): Promise<void> {
    const cfg = this.getLinter(this.folder.uri);
    const root = this.getRoot(this.folder);
    for (const variant of INDEX_COMMAND_VARIANTS) {
      const args = [...(cfg.usePython ? ["-m", "xbsl"] : []), ...variant(root)];
      const shown = `${cfg.command} ${args.join(" ")}`;
      const run = await runRaw(cfg.command, args, root);
      if (run.error) {
        this.output.appendLine(vscode.l10n.t('navigation: "{0}": {1}', shown, run.error));
        continue;
      }
      try {
        const index = parseIndex(run.stdout);
        this.lookup = new IndexLookup(index);
        this.rootFsPath = path.normalize(index.meta.root || root);
        this.output.appendLine(
          vscode.l10n.t(
            'navigation: index "{0}" loaded – objects: {1}, methods: {2}, components: {3}',
            this.folder.name, index.objects.length, index.methods.length, index.components.length
          )
        );
        return;
      } catch (e) {
        const reason = e instanceof Error ? e.message : String(e);
        this.output.appendLine(vscode.l10n.t('navigation: "{0}": {1}', shown, reason));
      }
    }
    // No variant worked: keep the previous index (if any) and stay silent.
    this.output.appendLine(
      vscode.l10n.t(
        'navigation: the project index "{0}" is unavailable – index-based navigation and completion stay silent',
        this.folder.name
      )
    );
  }

  dispose(): void {
    if (this.timer) {
      clearTimeout(this.timer);
      this.timer = undefined;
    }
  }
}

// Object attributes from its yaml (for completing fields in a query): attributes are not in the
// index, so the file is read by the path from the index and parsed. Silently returns undefined
// on any failure.
function objectAttributes(cache: IndexCache, name: string): string[] | undefined {
  const obj = cache.lookup?.objectByName(name);
  if (!obj || !cache.rootFsPath || !obj.path) {
    return undefined;
  }
  try {
    const fsPath = path.join(cache.rootFsPath, ...obj.path.split("/"));
    const raw = fs.readFileSync(fsPath, "utf8");
    const text = raw.charCodeAt(0) === 0xfeff ? raw.slice(1) : raw;
    return parseInternals(text)?.attributes.map((a) => a.name);
  } catch {
    return undefined;
  }
}

export function registerNavigation(
  context: vscode.ExtensionContext,
  output: vscode.OutputChannel,
  getLinter: (resource?: vscode.Uri) => LinterConfig,
  getRoot: (folder: vscode.WorkspaceFolder) => string
): void {
  const caches = new Map<string, IndexCache>();

  const enabled = (resource?: vscode.Uri): boolean =>
    vscode.workspace.getConfiguration("xbsl", resource ?? null).get<boolean>("navigation.enabled", true);

  // Keeps the cache set in sync with the workspace folders and the enablement flag.
  const syncCaches = (): void => {
    const alive = new Set<string>();
    for (const folder of vscode.workspace.workspaceFolders ?? []) {
      const key = folder.uri.toString();
      alive.add(key);
      if (enabled(folder.uri)) {
        if (!caches.has(key)) {
          const cache = new IndexCache(folder, output, getLinter, getRoot);
          caches.set(key, cache);
          void cache.refresh();
        }
      } else {
        caches.get(key)?.dispose();
        caches.delete(key);
      }
    }
    for (const key of [...caches.keys()]) {
      if (!alive.has(key)) {
        caches.get(key)?.dispose();
        caches.delete(key);
      }
    }
  };

  const cacheFor = (uri: vscode.Uri): IndexCache | undefined => {
    const folder = vscode.workspace.getWorkspaceFolder(uri);
    return folder ? caches.get(folder.uri.toString()) : undefined;
  };

  const fileStem = (uri: vscode.Uri): string => path.basename(uri.fsPath).replace(/\.[^.]*$/, "");

  // Document path (POSIX) relative to the index root (undefined when the document is outside).
  const relPath = (cache: IndexCache, uri: vscode.Uri): string | undefined => {
    if (!cache.rootFsPath || uri.scheme !== "file") {
      return undefined;
    }
    const rel = path.relative(cache.rootFsPath, uri.fsPath);
    if (rel === "" || rel.startsWith("..") || path.isAbsolute(rel)) {
      return undefined;
    }
    return rel.split(path.sep).join("/");
  };

  const toLocation = (cache: IndexCache, target: Target): vscode.Location | undefined => {
    if (!cache.rootFsPath || !target.path) {
      return undefined;
    }
    const fsPath = path.join(cache.rootFsPath, ...target.path.split("/"));
    return new vscode.Location(vscode.Uri.file(fsPath), new vscode.Position(Math.max(0, target.line - 1), 0));
  };

  const refToLocation = (cache: IndexCache, ref: RefLocation): vscode.Location | undefined => {
    if (!cache.rootFsPath || !ref.path) {
      return undefined;
    }
    const fsPath = path.join(cache.rootFsPath, ...ref.path.split("/"));
    const row = Math.max(0, ref.line - 1);
    const range = new vscode.Range(row, ref.col, row, ref.col + ref.length);
    return new vscode.Location(vscode.Uri.file(fsPath), range);
  };

  const definitionProvider: vscode.DefinitionProvider = {
    provideDefinition(doc, position) {
      if (!enabled(doc.uri)) {
        return undefined;
      }
      const cache = cacheFor(doc.uri);
      if (!cache || !cache.lookup) {
        return undefined;
      }
      const target = resolveDefinition(cache.lookup, {
        languageId: doc.languageId,
        lineText: doc.lineAt(position.line).text,
        character: position.character,
        fileStem: fileStem(doc.uri),
        filePath: relPath(cache, doc.uri),
      });
      return target ? toLocation(cache, target) : undefined;
    },
  };

  const referenceProvider: vscode.ReferenceProvider = {
    provideReferences(doc, position, refContext) {
      if (!enabled(doc.uri)) {
        return undefined;
      }
      const cache = cacheFor(doc.uri);
      if (!cache || !cache.lookup) {
        return undefined;
      }
      const refs = resolveReferences(cache.lookup, {
        languageId: doc.languageId,
        lineText: doc.lineAt(position.line).text,
        character: position.character,
        fileStem: fileStem(doc.uri),
        filePath: relPath(cache, doc.uri),
        includeDeclaration: refContext.includeDeclaration,
      });
      const out: vscode.Location[] = [];
      for (const ref of refs) {
        const loc = refToLocation(cache, ref);
        if (loc) {
          out.push(loc);
        }
      }
      return out;
    },
  };

  const completionProvider: vscode.CompletionItemProvider = {
    provideCompletionItems(doc, position) {
      if (!enabled(doc.uri)) {
        return undefined;
      }
      const cache = cacheFor(doc.uri);
      if (!cache || !cache.lookup) {
        return undefined;
      }
      const linePrefix = doc.lineAt(position.line).text.slice(0, position.character);
      // textBefore is computed only for member completion (after a dot) - to recognize a Запрос{...} block.
      const memberDot = /[A-Za-zА-Яа-яЁё_][A-Za-z0-9А-Яа-яЁё_]*\.[A-Za-z0-9А-Яа-яЁё_]*$/.test(linePrefix);
      const entries = resolveCompletions(cache.lookup, {
        languageId: doc.languageId,
        linePrefix,
        fileStem: fileStem(doc.uri),
        textBefore: memberDot ? doc.getText(new vscode.Range(new vscode.Position(0, 0), position)) : undefined,
        attributesOf: (name) => objectAttributes(cache, name),
      });
      if (!entries || entries.length === 0) {
        return undefined;
      }
      return entries.map((e) => {
        const item = new vscode.CompletionItem(e.label, KIND_MAP[e.kind]);
        item.detail = e.detail;
        return item;
      });
    },
  };

  const selector: vscode.DocumentSelector = [
    { language: "xbsl", scheme: "file" },
    { language: "yaml", scheme: "file" },
  ];

  context.subscriptions.push(
    vscode.languages.registerDefinitionProvider(selector, definitionProvider),
    vscode.languages.registerReferenceProvider(selector, referenceProvider),
    vscode.languages.registerCompletionItemProvider(selector, completionProvider, ".", ":"),
    vscode.workspace.onDidSaveTextDocument((doc) => {
      if (doc.uri.scheme !== "file") {
        return;
      }
      const ext = path.extname(doc.uri.fsPath).toLowerCase();
      if (ext !== ".xbsl" && ext !== ".yaml") {
        return;
      }
      cacheFor(doc.uri)?.schedule();
    }),
    vscode.workspace.onDidChangeWorkspaceFolders(() => syncCaches()),
    vscode.workspace.onDidChangeConfiguration((e) => {
      if (e.affectsConfiguration("xbsl.navigation")) {
        syncCaches();
      }
      if (e.affectsConfiguration("xbsl.linter")) {
        for (const cache of caches.values()) {
          cache.schedule();
        }
      }
    }),
    {
      dispose: () => {
        for (const cache of caches.values()) {
          cache.dispose();
        }
        caches.clear();
      },
    }
  );

  syncCaches();
}
