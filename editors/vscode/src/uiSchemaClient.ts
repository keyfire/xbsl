// Thin cached client of the engine's xbsl/uiSchema LSP request, shared by the component
// palette (the catalog) and the structure view (wrap candidates, container detection). The
// engine is the only source of the data; this module merely caches responses for the session
// so the trees do not re-ask on every refresh. Everything degrades to "unavailable" when the
// LSP server is not up or the dataset has no generated ui schema.

import { lspRequest } from "./lspClient";
import {
  containersFromCatalog,
  containersFromRecords,
  UiCatalogResponse,
  UiComponentRecord,
} from "./formPaletteCore";
import { KNOWN_CONTAINER_TYPES, WRAP_FALLBACK_CONTAINERS } from "./formStructureCore";

interface UiComponentResponse {
  available: boolean;
  component?: UiComponentRecord | null;
  close_matches?: string[];
}

let catalogCache: UiCatalogResponse | undefined;
const recordCache = new Map<string, UiComponentRecord | undefined>();
let containersCache: Set<string> | undefined;
let containersPromise: Promise<Set<string>> | undefined;
const enumsCache = new Map<string, Record<string, string[]>>();

export function resetUiSchemaCache(): void {
  catalogCache = undefined;
  recordCache.clear();
  containersCache = undefined;
  containersPromise = undefined;
  enumsCache.clear();
}

export async function uiCatalog(): Promise<UiCatalogResponse> {
  if (!catalogCache) {
    const res = await lspRequest<UiCatalogResponse>("xbsl/uiSchema", {});
    catalogCache = res && typeof res.available === "boolean" ? res : { available: false };
  }
  return catalogCache;
}

export async function uiComponent(name: string): Promise<UiComponentRecord | undefined> {
  if (recordCache.has(name)) {
    return recordCache.get(name);
  }
  const res = await lspRequest<UiComponentResponse>("xbsl/uiSchema", { component: name });
  const record = res?.available && res.component ? res.component : undefined;
  recordCache.set(name, record);
  return record;
}

// The enumerations referenced by a component's property unions: the per-component
// xbsl/uiSchema response carries them as "enums" {name: [values]} (the LSP has no
// catalog-wide enum listing). The data panel feeds the form's root component type here
// to offer enumeration names as ready-made property types; {} without generated data.
export async function componentEnums(name: string): Promise<Record<string, string[]>> {
  const cached = enumsCache.get(name);
  if (cached) {
    return cached;
  }
  const res = await lspRequest<UiComponentResponse & { enums?: Record<string, string[]> }>(
    "xbsl/uiSchema",
    { component: name }
  );
  const enums = res?.available && res.enums ? res.enums : {};
  enumsCache.set(name, enums);
  return enums;
}

// Container types with a Содержимое slot. Newer datasets flag them right in the catalog
// ("container": true) - one request; older data without the flag falls back to fetching
// the full per-component records once per session; without the schema at all the static
// fallback list is returned.
export async function contentContainerTypes(): Promise<string[]> {
  const set = await ensureContainers();
  return [...set].sort((a, b) => a.localeCompare(b, "ru"));
}

// Synchronous view of the learned container set: undefined until the first
// contentContainerTypes()/warmContainers() call resolves. Used by the structure view's
// icon and drop planning predicates, which cannot await.
export function cachedContainerTypes(): ReadonlySet<string> | undefined {
  return containersCache;
}

// Synchronous view of a catalog component's package (the type->icon mapping input of the
// structure view, which cannot await inside getTreeItem): undefined until the catalog is
// cached (warmContainers/uiCatalog) or for a non-catalog (project) type.
export function cachedComponentPackage(type: string): string | undefined {
  if (!catalogCache?.available) {
    return undefined;
  }
  return catalogCache.components?.[type]?.package;
}

// Kick off the container scan in the background (e.g. when the palette loads); notify() runs
// once the set is learned so the structure view can repaint icons. The scan also fills the
// catalog cache that cachedComponentPackage reads.
export function warmContainers(notify?: () => void): void {
  void ensureContainers().then(() => notify?.());
}

async function ensureContainers(): Promise<Set<string>> {
  if (containersCache) {
    return containersCache;
  }
  if (!containersPromise) {
    containersPromise = (async () => {
      const catalog = await uiCatalog();
      if (!catalog.available || !catalog.components) {
        containersCache = new Set(WRAP_FALLBACK_CONTAINERS);
        return containersCache;
      }
      const fromCatalog = containersFromCatalog(catalog);
      if (fromCatalog) {
        containersCache = new Set(fromCatalog);
        return containersCache;
      }
      // Older generated data without the container flag: verify the full records.
      const names = Object.entries(catalog.components)
        .filter(([, rec]) => !rec.abstract)
        .map(([name]) => name);
      const records = new Map<string, UiComponentRecord | undefined>();
      for (const name of names) {
        records.set(name, await uiComponent(name));
      }
      containersCache = new Set(containersFromRecords(records, KNOWN_CONTAINER_TYPES));
      return containersCache;
    })();
  }
  return containersPromise;
}
