// "Is the installed extension the latest one?" - the half of the answer the editor does not
// give. The extension is installed from a vsix, and VS Code asks the Marketplace for updates,
// while the CI publishes to Open VSX; nobody asks Open VSX, so an installed build can lag any
// number of versions and the only signal is the version in the status bar.
//
// Rules this file follows:
//   - never block activation and never throw: the check runs in the background and any
//     network trouble ends in silence;
//   - ask rarely (once a day) - the point is to notice a version left behind for days, not to
//     poll a registry from an editor; the manual command ignores the schedule;
//   - the automatic check can be switched off (`xbsl.checkForUpdates`), the manual one always
//     works: the user asked for it explicitly.

import * as https from "https";
import * as vscode from "vscode";
import { publishedVersion, shouldCheck, updateAvailable } from "./updateCheckCore";

const OPEN_VSX_API = "https://open-vsx.org/api/keyfire/xbsl";
const OPEN_VSX_PAGE = "https://open-vsx.org/extension/keyfire/xbsl";
const LAST_CHECK_KEY = "xbsl.updateCheck.lastCheckedAt";
const LATEST_KEY = "xbsl.updateCheck.latest";
const SETTING = "xbsl.checkForUpdates";
export const CHECK_COMMAND = "xbsl.checkForUpdate";
const INTERVAL_MS = 24 * 60 * 60 * 1000;
const TIMEOUT_MS = 10_000;

function fetchLatest(): Promise<string | undefined> {
  return new Promise((resolve) => {
    let request: ReturnType<typeof https.get>;
    const done = (value?: string): void => {
      try {
        request?.destroy();
      } catch {
        // the request is already finished - nothing to close
      }
      resolve(value);
    };
    try {
      request = https.get(OPEN_VSX_API, { timeout: TIMEOUT_MS }, (response) => {
        if (response.statusCode !== 200) {
          response.resume();
          done(undefined);
          return;
        }
        let body = "";
        response.setEncoding("utf8");
        response.on("data", (chunk: string) => {
          body += chunk;
        });
        response.on("end", () => {
          try {
            done(publishedVersion(JSON.parse(body)));
          } catch {
            done(undefined); // a changed answer is not a reason to bother the user
          }
        });
      });
    } catch {
      resolve(undefined);
      return;
    }
    request.on("timeout", () => done(undefined));
    request.on("error", () => done(undefined));
  });
}

export interface UpdateCheck {
  /** Ask now, regardless of the schedule and of the setting (the manual command). */
  checkNow: () => Promise<void>;
}

export function registerUpdateCheck(
  context: vscode.ExtensionContext,
  onLatest: (latest: string | undefined) => void
): UpdateCheck {
  const installed = String(context.extension.packageJSON.version ?? "");
  // What was known at the previous startup: the status bar shows it before any request.
  onLatest(context.globalState.get<string>(LATEST_KEY));

  const remember = async (latest: string | undefined): Promise<void> => {
    await context.globalState.update(LAST_CHECK_KEY, Date.now());
    if (latest) {
      await context.globalState.update(LATEST_KEY, latest);
    }
    onLatest(latest ?? context.globalState.get<string>(LATEST_KEY));
  };

  const checkNow = async (): Promise<void> => {
    const latest = await fetchLatest();
    await remember(latest);
    if (!latest) {
      void vscode.window.showWarningMessage(
        vscode.l10n.t("Could not ask Open VSX for the latest version of the extension.")
      );
      return;
    }
    if (!updateAvailable({ installed, latest })) {
      void vscode.window.showInformationMessage(
        vscode.l10n.t("The extension is current: {0}.", installed)
      );
      return;
    }
    const open = vscode.l10n.t("Open the page");
    const answer = await vscode.window.showInformationMessage(
      vscode.l10n.t(
        "A newer extension is published: {0} (installed {1}). It is installed from a vsix, so the editor does not update it by itself.",
        latest,
        installed
      ),
      open
    );
    if (answer === open) {
      void vscode.env.openExternal(vscode.Uri.parse(OPEN_VSX_PAGE));
    }
  };

  context.subscriptions.push(vscode.commands.registerCommand(CHECK_COMMAND, () => void checkNow()));

  const enabled = vscode.workspace.getConfiguration().get<boolean>(SETTING, true);
  const schedule = {
    lastCheckedAt: context.globalState.get<number>(LAST_CHECK_KEY),
    intervalMs: INTERVAL_MS,
    now: Date.now(),
  };
  if (enabled && shouldCheck(schedule)) {
    // Deliberately quiet: the background check only lights up the status bar. A popup on
    // startup is exactly the kind of thing that gets an extension switched off.
    void fetchLatest().then(remember);
  }
  return { checkNow };
}
