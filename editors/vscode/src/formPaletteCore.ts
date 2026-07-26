// Pure core of the "Component palette" view (no vscode import), unit-tested under plain
// Node (test/formPaletteCore.test.ts): builds the section model from the engine's
// xbsl/uiSchema catalog, the project's own interface components, the favorites list and the
// insertion usage counters. Decisions encoded here:
//   - abstract components (no current constructor - nothing to insert) are NOT shown;
//   - sections go Frequent, Favorites, Project, then platform packages sorted by the last
//     segment of their package path (ОбщиеКомпоненты, Списки, Формы, ...);
//   - without ui-schema data the palette degrades to a hint node plus the sections that do
//     not need the schema (Frequent/Favorites restricted to project components, Project).

export interface UiCatalogComponent {
  package?: string;
  abstract?: boolean;
  // The props carry a slot Содержимое (a wrap/drop container). Newer datasets emit the
  // flag right in the catalog; older ones lack it and the container set is learned from
  // the full per-component records instead (containersFromRecords).
  container?: boolean;
  since?: string;
  doc?: string;
}

export interface UiCatalogResponse {
  available: boolean;
  version?: string | null;
  components?: Record<string, UiCatalogComponent>;
  // {Russian package: its English spelling} - the schema is derived from the Russian
  // documentation, the pairs come from the distribution (uiterms). Absent on older engines.
  packages?: Record<string, string>;
}

// One insertable palette entry. origin tells where the type comes from: the platform catalog
// or the workspace (a project КомпонентИнтерфейса used as a component type by its name).
export interface PaletteItemModel {
  name: string;
  origin: "platform" | "project";
  doc?: string;
  since?: string;
  packageName?: string;
}

export type PaletteSectionKind = "frequent" | "favorites" | "project" | "package" | "hint";

export interface PaletteSectionModel {
  kind: PaletteSectionKind;
  // Stable section id for tree-item identity: "frequent", "favorites", "project",
  // "package:<segment>" or "hint".
  id: string;
  // The package segment for kind "package"; empty otherwise (the glue localizes the rest).
  packageLabel: string;
  items: PaletteItemModel[];
}

export const FREQUENT_LIMIT = 8;

const RU = "ru";

// The last segment of a package path ("Стд::Интерфейс::ОбщиеКомпоненты" - "ОбщиеКомпоненты").
export function packageSegment(pkg: string | undefined): string {
  if (!pkg) {
    return "";
  }
  const parts = pkg.split("::").filter(Boolean);
  return parts[parts.length - 1] ?? "";
}

// Concrete (insertable) catalog components: the abstract ones have no constructor, so there
// is nothing to write into yaml - they are dropped rather than shown disabled.
export function concreteCatalog(catalog: UiCatalogResponse): Map<string, UiCatalogComponent> {
  const out = new Map<string, UiCatalogComponent>();
  for (const [name, rec] of Object.entries(catalog.components ?? {})) {
    if (!rec.abstract) {
      out.set(name, rec);
    }
  }
  return out;
}

export function buildPalette(
  catalog: UiCatalogResponse,
  projectComponents: string[],
  favorites: string[],
  usage: Record<string, number>,
  // The language the group titles follow. In an English editor the palette used to stay
  // Russian: the packages of the schema are Russian and there was nothing to translate them
  // with. `english` switches to the pairs the engine now ships (absent pair - Russian stays).
  english = false
): PaletteSectionModel[] {
  const platform = catalog.available ? concreteCatalog(catalog) : new Map<string, UiCatalogComponent>();
  const project = [...new Set(projectComponents)].sort((a, b) => a.localeCompare(b, RU));
  const projectSet = new Set(project);

  const itemOf = (name: string): PaletteItemModel | undefined => {
    const rec = platform.get(name);
    if (rec) {
      return { name, origin: "platform", doc: rec.doc, since: rec.since, packageName: rec.package };
    }
    if (projectSet.has(name)) {
      return { name, origin: "project" };
    }
    return undefined;
  };

  const sections: PaletteSectionModel[] = [];
  if (!catalog.available) {
    sections.push({ kind: "hint", id: "hint", packageLabel: "", items: [] });
  }

  const frequent = Object.entries(usage)
    .filter(([name, count]) => count > 0 && itemOf(name))
    .sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0], RU))
    .slice(0, FREQUENT_LIMIT)
    .map(([name]) => itemOf(name) as PaletteItemModel);
  if (frequent.length) {
    sections.push({ kind: "frequent", id: "frequent", packageLabel: "", items: frequent });
  }

  const favoriteItems = [...new Set(favorites)]
    .sort((a, b) => a.localeCompare(b, RU))
    .map(itemOf)
    .filter((i): i is PaletteItemModel => !!i);
  if (favoriteItems.length) {
    sections.push({ kind: "favorites", id: "favorites", packageLabel: "", items: favoriteItems });
  }

  if (project.length) {
    sections.push({
      kind: "project",
      id: "project",
      packageLabel: "",
      items: project.map((name) => ({ name, origin: "project" as const })),
    });
  }

  const label = (pkg: string | undefined): string => {
    const pair = english && pkg ? catalog.packages?.[pkg] : undefined;
    return packageSegment(pair ?? pkg);
  };
  const byPackage = new Map<string, PaletteItemModel[]>();
  for (const [name, rec] of platform) {
    const segment = label(rec.package);
    const bucket = byPackage.get(segment);
    const item: PaletteItemModel = { name, origin: "platform", doc: rec.doc, since: rec.since, packageName: rec.package };
    if (bucket) {
      bucket.push(item);
    } else {
      byPackage.set(segment, [item]);
    }
  }
  const packages = [...byPackage.entries()].sort((a, b) => a[0].localeCompare(b[0], RU));
  for (const [segment, items] of packages) {
    items.sort((a, b) => a.name.localeCompare(b.name, RU));
    sections.push({ kind: "package", id: `package:${segment}`, packageLabel: segment, items });
  }
  return sections;
}

// --- container candidates ------------------------------------------------------------------

// Container types straight from the catalog "container" flags. undefined - no record
// carries the flag (older generated data without it): the caller falls back to verifying
// the full per-component records. Abstract components cannot be written as a wrapper
// type, so they are dropped; a catalog where every flagged container is abstract counts
// as no data too.
export function containersFromCatalog(catalog: UiCatalogResponse): string[] | undefined {
  const flagged = Object.entries(catalog.components ?? {}).filter(([, rec]) => rec.container === true);
  if (!flagged.length) {
    return undefined;
  }
  const names = flagged
    .filter(([, rec]) => !rec.abstract)
    .map(([name]) => name)
    .sort((a, b) => a.localeCompare(b, RU));
  return names.length ? names : undefined;
}

// --- container candidates from full component records (older data) --------------------------

export interface UiComponentRecord {
  name?: string;
  props?: Record<string, { slot?: boolean } & Record<string, unknown>>;
}

// Whether a full ui-schema record describes a component the wrap operation can use: the
// engine always wraps into a Содержимое slot, so exactly that slot must exist.
export function hasContentSlot(record: UiComponentRecord | undefined): boolean {
  return !!record?.props?.["Содержимое"]?.slot;
}

// Container types (Содержимое slot) picked out of fetched records; falls back to the static
// list when the schema yielded nothing.
export function containersFromRecords(
  records: ReadonlyMap<string, UiComponentRecord | undefined>,
  fallback: readonly string[]
): string[] {
  const verified = [...records.entries()]
    .filter(([, rec]) => hasContentSlot(rec))
    .map(([name]) => name)
    .sort((a, b) => a.localeCompare(b, RU));
  return verified.length ? verified : [...fallback];
}

// --- usage counters -----------------------------------------------------------------------

export function bumpUsage(usage: Record<string, number>, name: string): Record<string, number> {
  return { ...usage, [name]: (usage[name] ?? 0) + 1 };
}
