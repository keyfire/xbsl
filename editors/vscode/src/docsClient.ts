// Тонкий клиент к документации линтера: обёртки над кастомными LSP-запросами xbsl/docs*.
// Сервер держит базу docs.sqlite в памяти; расширение только спрашивает и показывает.
// Если LSP-сервер не поднят или запрос упал, обёртки возвращают пусто – панель показывает
// "документация недоступна", а не падает.

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

// Узел курируемого дерева "Содержание": раздел-вкладка / категория / ссылка на страницу.
export interface DocNode {
  node: number;
  parent: number | null;
  label: string;
  page: string | null;
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

// Результат "документация по символу": уверенная страница (page) либо кандидаты на выбор.
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
