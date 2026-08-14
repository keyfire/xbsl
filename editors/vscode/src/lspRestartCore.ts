// Pure core of "does this settings change require a server restart" (no vscode import), so it
// can be unit-tested under plain Node.
//
// In LSP mode the settings that shape the run are passed as ARGUMENTS to the long-lived
// server, and a running process cannot be re-argued. The CLI mode re-reads them on every run
// and has a configuration listener for that; the LSP mode returned from activate() before that
// listener was ever registered, so a changed setting simply did nothing. That is how
// `xbsl.projectRoot` came to read as ignored: the sources root was narrowed to keep an
// examples/ copy out of the run, the panel stayed full of findings from it, and only a window
// reload made the setting take effect.

//: The settings that end up in the server's command line (see buildClient in lspClient.ts).
//: A change in any of them means the running server was started with the wrong arguments.
export const SERVER_ARG_SETTINGS = [
  "xbsl.projectRoot",
  "xbsl.lsp.command",
  "xbsl.linter.pythonPath",
  "xbsl.linter.lang",
  "xbsl.linter.dataDir",
  "xbsl.templates.file",
  // The rule set: xbsl.rules and the legacy string settings it is built from.
  "xbsl.rules",
  "xbsl.linter.select",
  "xbsl.linter.ignore",
  "xbsl.linter.enable",
] as const;

// `affects` is vscode's own event.affectsConfiguration, passed in so this stays vscode-free.
export function needsServerRestart(affects: (section: string) => boolean): boolean {
  return SERVER_ARG_SETTINGS.some((section) => affects(section));
}
