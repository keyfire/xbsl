// Pure core of the update check (no vscode import), unit-tested under plain Node.
//
// Why the extension needs one at all: it is installed from a vsix (side-loaded), and the
// editor asks the MARKETPLACE for updates, while the CI publishes to Open VSX. Nobody
// asks Open VSX, so an installed extension can lag any number of versions and the only
// signal is the version in the status bar - which is exactly how six minor versions went
// unnoticed. The engine has `xbsl --version` and `self-update`; this is the extension's
// half of the same answer.
//
// The comparison is deliberately simple and total: versions here are `major.minor.patch`
// with an optional suffix. A suffix means a pre-release and loses to the same numbers
// without it, an unparsable version never claims an update (silence beats a false alarm).

export interface Version {
  numbers: number[];
  suffix: string;
}

export function parseVersion(text: string): Version | undefined {
  const match = /^\s*v?(\d+)\.(\d+)(?:\.(\d+))?(.*)$/.exec(text ?? "");
  if (!match) {
    return undefined;
  }
  return {
    numbers: [Number(match[1]), Number(match[2]), Number(match[3] ?? 0)],
    suffix: (match[4] ?? "").trim(),
  };
}

// > 0 – the first is newer, < 0 – older, 0 – the same. Unparsable is treated as "not newer".
export function compareVersions(left: string, right: string): number {
  const a = parseVersion(left);
  const b = parseVersion(right);
  if (!a || !b) {
    return 0;
  }
  for (let i = 0; i < 3; i++) {
    if (a.numbers[i] !== b.numbers[i]) {
      return a.numbers[i] > b.numbers[i] ? 1 : -1;
    }
  }
  if (a.suffix === b.suffix) {
    return 0;
  }
  // A release beats its own pre-release: 0.46.0 is newer than 0.46.0-rc1.
  if (!a.suffix) {
    return 1;
  }
  if (!b.suffix) {
    return -1;
  }
  return a.suffix > b.suffix ? 1 : -1;
}

export function isNewer(candidate: string, installed: string): boolean {
  return compareVersions(candidate, installed) > 0;
}

// The published version out of the Open VSX answer; undefined when the shape is not what
// we expect - a changed API must go quiet, not throw inside activation.
export function publishedVersion(payload: unknown): string | undefined {
  if (!payload || typeof payload !== "object") {
    return undefined;
  }
  const version = (payload as { version?: unknown }).version;
  return typeof version === "string" && parseVersion(version) ? version : undefined;
}

export interface CheckSchedule {
  lastCheckedAt?: number;
  intervalMs: number;
  now: number;
}

// The automatic check is rare on purpose: the point is to notice a version left behind for
// days, not to poll a registry from an editor. A manual call ignores the schedule.
export function shouldCheck(schedule: CheckSchedule): boolean {
  if (!schedule.lastCheckedAt) {
    return true;
  }
  return schedule.now - schedule.lastCheckedAt >= schedule.intervalMs;
}

export interface UpdateState {
  installed: string;
  latest?: string;
}

export function updateAvailable(state: UpdateState): boolean {
  return Boolean(state.latest && isNewer(state.latest, state.installed));
}
