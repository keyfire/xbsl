export interface ProjectCheckProgress {
  kind: "begin" | "report" | "end";
  title?: string;
  message?: string;
  percentage?: number;
}
export interface ProjectCheckResult { ok: boolean; error?: string; files?: number; diagnostics?: number }
interface ProjectCheckConnection {
  onProgress(token: string, handler: (event: ProjectCheckProgress) => void): { dispose(): void };
  sendRequest(method: string, params: { workDoneToken: string }): Promise<ProjectCheckResult>;
}
export async function requestProjectCheck(connection: ProjectCheckConnection, token: string,
  report: (event: ProjectCheckProgress) => void): Promise<ProjectCheckResult> {
  const listener = connection.onProgress(token, report);
  try {
    return await connection.sendRequest("xbsl/reindexProject", { workDoneToken: token });
  } finally {
    listener.dispose();
  }
}

// Extract the phase prefix of our RU/EN server messages; keep counts and rule titles in the tooltip.
export function projectCheckSummary(message: string): string | undefined {
  const match = /^(?:Stage|Этап) (\d+\/\d+): (.*?)(?: (\d{1,3})%| – \d+\/\d+;|$)/.exec(message);
  if (!match) { return undefined; }
  const percentage = match[3] === undefined ? "" : ` · ${Math.min(100, Number(match[3]))}%`;
  return `${match[1]} ${match[2]}${percentage}`;
}
