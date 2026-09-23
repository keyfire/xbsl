// An in-process drag ticket: VS Code serializes DataTransferItem.value as JSON.
// Tree nodes contain parent/children cycles, so only stable ids cross that boundary.

import { randomUUID } from "node:crypto";

// `application/vnd.code.tree.*` is reserved for VS Code's own tree item handles.
export const METADATA_DRAG_MIME = "application/vnd.xbsl.metadata-items";

const MAX_AGE_MS = 30_000;

export class MetadataDragTickets {
  private issued = new Map<string, { ids: string[]; at: number }>();

  constructor(
    private readonly now: () => number = Date.now,
    private readonly token: () => string = randomUUID,
  ) {}

  issue(ids: readonly string[]): string | undefined {
    this.prune();
    if (!ids.length || ids.some((id) => typeof id !== "string" || !id)
      || new Set(ids).size !== ids.length) {
      return undefined;
    }
    const ticket = this.token();
    this.issued.set(ticket, { ids: [...ids], at: this.now() });
    return JSON.stringify({ ticket, ids });
  }

  consume(raw: string): string[] | undefined {
    let parsed: unknown;
    try { parsed = JSON.parse(raw); } catch { return undefined; }
    if (!parsed || typeof parsed !== "object") return undefined;
    const payload = parsed as { ticket?: unknown; ids?: unknown };
    const ids = payload.ids;
    if (typeof payload.ticket !== "string" || !Array.isArray(ids)
      || !ids.length || ids.some((id) => typeof id !== "string" || !id)
      || new Set(ids).size !== ids.length) {
      return undefined;
    }
    const issued = this.issued.get(payload.ticket);
    if (!issued) return undefined;
    if (this.now() - issued.at > MAX_AGE_MS) {
      this.issued.delete(payload.ticket);
      return undefined;
    }
    if (issued.ids.length !== ids.length
      || issued.ids.some((id, index) => id !== ids[index])) {
      return undefined;
    }
    this.issued.delete(payload.ticket);
    return issued.ids;
  }

  clear(): void {
    this.issued.clear();
  }

  private prune(): void {
    for (const [ticket, data] of this.issued) {
      if (this.now() - data.at > MAX_AGE_MS) this.issued.delete(ticket);
    }
  }
}
