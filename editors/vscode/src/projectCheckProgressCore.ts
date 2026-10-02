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
