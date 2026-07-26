// Thin client to the linter's documentation: wrappers over the custom xbsl/docs* LSP requests.
// The server keeps the docs.sqlite database in memory; the extension only asks and displays.
// When the LSP server is not up or a request failed, the wrappers return emptiness - the panel
// shows "documentation unavailable" instead of crashing.

import { lspRequest } from "./lspClient";

export interface DocHit {
  id: string;
  title: string;
  qualified: string;
  kind: string;
  availability: string;
  url: string;
  snippet: string;
}

export interface DocPage {
  id: string;
  kind: string;
  title: string;
  qualified: string;
  availability: string;
  url: string;
  html: string;
}

// Node of the curated "Contents" tree: a tab section / a category / a page link / a section
// heading inside a page (kind "heading" - carries page + anchor).
export interface DocNode {
  node: number;
  parent: number | null;
  label: string;
  page: string | null;
  anchor: string | null;
  kind: string;
}

export interface DocAsset {
  id: string;
  mime: string;
  base64: string;
}

export async function docsAvailable(): Promise<boolean> {
  const r = await lspRequest<{ available: boolean }>("xbsl/docsAvailable", {});
  return !!r?.available;
}

export async function docsSearch(query: string, limit = 30): Promise<DocHit[]> {
  const r = await lspRequest<{ hits: DocHit[] }>("xbsl/docsSearch", { query, limit });
  return r?.hits ?? [];
}

export async function docsPage(id: string): Promise<DocPage | undefined> {
  const r = await lspRequest<DocPage>("xbsl/docsPage", { id });
  return r && r.id ? r : undefined;
}

export async function docsTree(): Promise<DocNode[]> {
  const r = await lspRequest<{ nodes: DocNode[] }>("xbsl/docsTree", {});
  return r?.nodes ?? [];
}

// Result of "documentation for a symbol": a confident page (page) or candidates to choose from.
export interface DocForSymbol {
  name: string;
  page: DocPage | null;
  candidates: DocHit[];
}

export async function docsForSymbol(
  uri: string,
  position: { line: number; character: number }
): Promise<DocForSymbol | undefined> {
  return await lspRequest<DocForSymbol>("xbsl/docsForSymbol", { uri, position });
}

export async function docsAsset(id: string): Promise<DocAsset | undefined> {
  const r = await lspRequest<DocAsset>("xbsl/docsAsset", { id });
  return r && r.id ? r : undefined;
}
