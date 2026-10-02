import * as assert from "node:assert/strict";
import { requestProjectCheck, ProjectCheckProgress } from "../src/projectCheckProgressCore";

async function main(): Promise<void> {
  const handlers = new Map<string, (event: ProjectCheckProgress) => void>();
  let disposed = 0;
  const seen: string[] = [];
  const connection = {
    onProgress(token: string, handler: (event: ProjectCheckProgress) => void) {
      handlers.set(token, handler);
      return { dispose() { disposed++; handlers.delete(token); } };
    },
    async sendRequest(_method: string, params: { workDoneToken: string }) {
      assert.ok(handlers.has(params.workDoneToken), "progress is subscribed before the request");
      handlers.get(params.workDoneToken)?.({ kind: "begin", title: "Project check" });
      handlers.get("other")?.({ kind: "report", message: "unrelated" });
      handlers.get(params.workDoneToken)?.({ kind: "report", message: "Files 2/4" });
      handlers.get(params.workDoneToken)?.({ kind: "end", message: "Done" });
      return { ok: true };
    },
  };
  await requestProjectCheck(connection, "manual", (event) => seen.push(event.message || event.title || ""));
  assert.deepEqual(seen, ["Project check", "Files 2/4", "Done"]);
  assert.equal(disposed, 1);
  assert.equal(handlers.size, 0, "a completed pass must not leave a progress listener");
  const failing = { ...connection, async sendRequest() { throw new Error("server stopped"); } };
  await assert.rejects(requestProjectCheck(failing, "failed", () => undefined), /server stopped/);
  assert.equal(disposed, 2, "a failed pass must release its token listener");
  process.stdout.write("projectCheckProgressCore: 3 checks passed\n");
}
void main().catch((error) => { process.stderr.write(String(error)); process.exitCode = 1; });