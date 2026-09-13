// Packages of a subsystem in the metadata tree - the pure half, no vscode (node tests run it).
//
// The engine places every object: xbsl/metaProjectInfo (the CLI `xbsl project-info`) answers
// the subsystem, the package and the namespace of each object, the packages with their folders
// and the subsystems of every project. This module arranges that answer into the hierarchy the
// tree draws - subsystem, package, nested package - and decides nothing about placement itself:
// a folder is matched against a folder only for what the engine does not place (resource files,
// an object created after the answer was given). It also plans how a scaffolding result that
// renames files lands in one WorkspaceEdit.

export interface EngineObject {
  kind: string;
  name: string;
  path: string;
  subsystem: string | null;
  package?: string | null;
  namespace?: string;
}

export interface EnginePackage {
  subsystem: string;
  package: string;
  dir: string;
  objects: number;
}

export interface EngineProject {
  vendor: string;
  name: string;
  dir: string;
  subsystems: string[];
}

export interface EngineProjectInfo {
  projects?: EngineProject[];
  packages?: EnginePackage[];
  objects?: EngineObject[];
  error?: string;
}

// Where the engine placed one object.
export interface Placement {
  subsystem: string | null;
  package: string | null;
  namespace: string;
}

export interface PackageGroup {
  name: string; // the last segment of the path - the label of the node
  key: string; // the path under the subsystem: `Партии` or `Партии::Архив`
  dir: string;
  namespace: string; // `Поставщик::Проект::Подсистема::Партии::Архив`
  children: PackageGroup[];
}

export interface SubsystemGroup {
  name: string;
  dir: string;
  namespace: string;
  packages: PackageGroup[]; // the top-level packages, each with its nested ones
}

export interface ProjectPlacement {
  dir: string; // "" - the sources carry no project descriptor
  subsystems: SubsystemGroup[];
}

export interface EnginePlacement {
  objects: Map<string, Placement>; // keyed by pathKey of the object's yaml
  projects: ProjectPlacement[];
}

// A path as a map key: one separator, no trailing one, one letter case. The engine answers
// with the separators of its platform, the editor with its own, and Windows ignores the case.
export function pathKey(p: string): string {
  return p.replace(/[\\/]+/g, "/").replace(/\/$/, "").toLowerCase();
}

export function isUnder(child: string, dir: string): boolean {
  return pathKey(child).startsWith(pathKey(dir) + "/");
}

// The folder `levels` steps above a path, in the separators the path is written with.
export function parentDir(p: string, levels = 1): string {
  let out = p.replace(/[\\/]+$/, "");
  for (let i = 0; i < levels; i++) {
    const cut = Math.max(out.lastIndexOf("\\"), out.lastIndexOf("/"));
    if (cut <= 0) {
      return out;
    }
    out = out.slice(0, cut);
  }
  return out;
}

export function baseName(p: string): string {
  const trimmed = p.replace(/[\\/]+$/, "");
  return trimmed.slice(Math.max(trimmed.lastIndexOf("\\"), trimmed.lastIndexOf("/")) + 1);
}

export function joinDir(dir: string, name: string): string {
  const sep = dir.includes("\\") ? "\\" : "/";
  return dir.replace(/[\\/]+$/, "") + sep + name;
}

function fullName(...parts: Array<string | null | undefined>): string {
  return parts.filter((p): p is string => !!p).join("::");
}

/** Read the placement out of an engine answer, or undefined when it carries none.
 *
 * An error, a missing list or an engine older than the packages model (its objects have no
 * `package` field) all mean the same to the tree: draw it the old way, without packages.
 * `descriptorDirs` are the folders of the subsystem descriptors the tree found itself: a
 * subsystem with a descriptor and no object yet still needs a folder, and the answer names such
 * a subsystem without one.
 */
export function readPlacement(
  info: EngineProjectInfo | undefined,
  descriptorDirs: string[] = []
): EnginePlacement | undefined {
  if (!info || info.error || !Array.isArray(info.objects) || !Array.isArray(info.projects)) {
    return undefined;
  }
  if (info.objects.some((o) => o.package === undefined)) {
    return undefined;
  }
  const objects = new Map<string, Placement>();
  for (const o of info.objects) {
    objects.set(pathKey(o.path), {
      subsystem: o.subsystem ?? null,
      package: o.package ?? null,
      namespace: o.namespace ?? "",
    });
  }
  const packages = info.packages ?? [];
  // The nearest project above a path; "" for sources without a project descriptor.
  const byDepth = [...info.projects].sort((a, b) => b.dir.length - a.dir.length);
  const projectOf = (p: string): EngineProject | undefined => byDepth.find((pr) => isUnder(p, pr.dir));

  // The folder of a subsystem: its root objects lie in it, a package folder lies below it by
  // the depth of the package path - the shortest candidate wins (an object in a service folder
  // of the subsystem would otherwise read as the subsystem itself).
  const dirs = new Map<string, Map<string, string>>();
  const consider = (project: string, subsystem: string, dir: string): void => {
    const known = dirs.get(project) ?? new Map<string, string>();
    const current = known.get(subsystem);
    if (current === undefined || dir.length < current.length) {
      known.set(subsystem, dir);
    }
    dirs.set(project, known);
  };
  for (const o of info.objects) {
    if (o.subsystem && o.package === null) {
      consider(projectOf(o.path)?.dir ?? "", o.subsystem, parentDir(o.path));
    }
  }
  for (const p of packages) {
    consider(projectOf(p.dir)?.dir ?? "", p.subsystem, parentDir(p.dir, p.package.split("::").length));
  }

  const projects: ProjectPlacement[] = [];
  const projectEntries: Array<{ dir: string; vendor: string; name: string; names: string[] }> = info.projects.map((p) => ({
    dir: p.dir,
    vendor: p.vendor,
    name: p.name,
    names: p.subsystems ?? [],
  }));
  if (dirs.has("")) {
    projectEntries.push({ dir: "", vendor: "", name: "", names: [] });
  }
  for (const project of projectEntries) {
    const known = dirs.get(project.dir) ?? new Map<string, string>();
    const names = [...new Set([...project.names, ...known.keys()])].sort((a, b) => a.localeCompare(b, "ru"));
    const subsystems: SubsystemGroup[] = names.map((name) => {
      const descriptor = descriptorDirs.find(
        (d) => baseName(d) === name && pathKey(parentDir(d)) === pathKey(project.dir)
      );
      const dir = known.get(name) ?? descriptor ?? joinDir(project.dir, name);
      const namespace = fullName(project.vendor, project.name, name);
      const own = packages
        .filter((p) => p.subsystem === name && (projectOf(p.dir)?.dir ?? "") === project.dir)
        .sort((a, b) => a.package.localeCompare(b.package, "ru"));
      return { name, dir, namespace, packages: packageTree(own, namespace) };
    });
    projects.push({ dir: project.dir, subsystems });
  }
  return { objects, projects };
}

// The packages of one subsystem as a tree: `П1::П2` under `П1`. An enclosing package is in the
// engine's list whenever a nested one is; should it be missing, the nested one is not lost - it
// hangs on the subsystem.
function packageTree(packages: EnginePackage[], subsystemNamespace: string): PackageGroup[] {
  const byKey = new Map<string, PackageGroup>();
  const top: PackageGroup[] = [];
  for (const p of packages) {
    const segments = p.package.split("::");
    const group: PackageGroup = {
      name: segments[segments.length - 1],
      key: p.package,
      dir: p.dir,
      namespace: fullName(subsystemNamespace, p.package),
      children: [],
    };
    byKey.set(p.package, group);
    const parent = byKey.get(segments.slice(0, -1).join("::"));
    (segments.length > 1 && parent ? parent.children : top).push(group);
  }
  return top;
}

// The project placement a path belongs to - the deepest project folder above it.
export function projectPlacementOf(placement: EnginePlacement, p: string): ProjectPlacement | undefined {
  let best: ProjectPlacement | undefined;
  for (const project of placement.projects) {
    if ((project.dir === "" || isUnder(p, project.dir)) && (!best || project.dir.length > best.dir.length)) {
      best = project;
    }
  }
  return best;
}

export interface Buckets<T> {
  outside: T[]; // outside every subsystem
  subsystems: Map<SubsystemGroup, { root: T[]; packages: Map<string, T[]> }>;
}

/** Where one item of a project lies: its subsystem and package, undefined outside every subsystem.
 *
 * An object the engine placed goes where the engine said. Anything else - a resource file, an
 * object the answer does not know yet - goes by its folder: into the deepest package folder of
 * the answer that holds it, else to the root of the subsystem whose folder holds it. The tree
 * sorts its nodes by this and the filter judges an item by it, so the two never disagree.
 */
export function placeOf(
  p: string,
  project: ProjectPlacement,
  placement: EnginePlacement
): { subsystem: SubsystemGroup; packageKey: string | null } | undefined {
  const placed = placement.objects.get(pathKey(p));
  if (placed) {
    const group = placed.subsystem ? project.subsystems.find((s) => s.name === placed.subsystem) : undefined;
    if (group) {
      return { subsystem: group, packageKey: placed.package };
    }
    if (!placed.subsystem) {
      return undefined;
    }
  }
  return folderPlace(project, p);
}

/** Sort the items of one project into its subsystems and packages (placeOf decides each). */
export function bucketItems<T>(
  items: T[],
  pathOf: (item: T) => string,
  project: ProjectPlacement,
  placement: EnginePlacement
): Buckets<T> {
  const buckets: Buckets<T> = { outside: [], subsystems: new Map() };
  const slot = (group: SubsystemGroup) => {
    const existing = buckets.subsystems.get(group);
    if (existing) {
      return existing;
    }
    const created = { root: [] as T[], packages: new Map<string, T[]>() };
    buckets.subsystems.set(group, created);
    return created;
  };
  const push = (group: SubsystemGroup, packageKey: string | null, item: T): void => {
    const target = slot(group);
    if (!packageKey) {
      target.root.push(item);
      return;
    }
    target.packages.set(packageKey, [...(target.packages.get(packageKey) ?? []), item]);
  };
  for (const item of items) {
    const where = placeOf(pathOf(item), project, placement);
    if (where) {
      push(where.subsystem, where.packageKey, item);
    } else {
      buckets.outside.push(item);
    }
  }
  return buckets;
}

// The subsystem and the deepest known package whose folder holds a path.
export function folderPlace(
  project: ProjectPlacement,
  p: string
): { subsystem: SubsystemGroup; packageKey: string | null } | undefined {
  const subsystem = project.subsystems.find((s) => isUnder(p, s.dir));
  if (!subsystem) {
    return undefined;
  }
  let packageKey: string | null = null;
  let level = subsystem.packages;
  for (;;) {
    const holder = level.find((g) => isUnder(p, g.dir));
    if (!holder) {
      break;
    }
    packageKey = holder.key;
    level = holder.children;
  }
  return { subsystem, packageKey };
}

// Every package group of a subsystem, outermost first.
export function allPackages(groups: PackageGroup[]): PackageGroup[] {
  return groups.flatMap((g) => [g, ...allPackages(g.children)]);
}

// --- applying a scaffolding result with renames ------------------------------------------

export interface ScaffoldRename {
  from: string;
  to: string;
}

export interface ScaffoldFileChange {
  path: string;
  created: boolean;
  content: string;
}

export type EditStep =
  | { kind: "rename"; from: string; to: string }
  | { kind: "create"; path: string; content: string }
  // `readFrom` is where the text to replace is read BEFORE the edit: a renamed file is still at
  // its old path then, while the replacement lands at the new one.
  | { kind: "replace"; path: string; readFrom: string; content: string }
  | { kind: "delete"; path: string };

/** The steps of one WorkspaceEdit, in the order the engine applies them (scaffold.apply_result):
 * renames first - the edits of a renamed file address its new path - then the files, then the
 * deletions. */
export function scaffoldSteps(result: {
  renames?: ScaffoldRename[];
  files?: ScaffoldFileChange[];
  deletes?: string[];
}): EditStep[] {
  const steps: EditStep[] = [];
  const renamedFrom = new Map<string, string>();
  for (const r of result.renames ?? []) {
    steps.push({ kind: "rename", from: r.from, to: r.to });
    renamedFrom.set(pathKey(r.to), r.from);
  }
  for (const f of result.files ?? []) {
    steps.push(
      f.created
        ? { kind: "create", path: f.path, content: f.content }
        : { kind: "replace", path: f.path, readFrom: renamedFrom.get(pathKey(f.path)) ?? f.path, content: f.content }
    );
  }
  for (const d of result.deletes ?? []) {
    steps.push({ kind: "delete", path: d });
  }
  return steps;
}

/** The folders the renamed files left, deepest first - removed afterwards when they are empty.
 *
 * The parents of every old path up to the first folder a renamed file still lands in (a rename
 * inside one folder vacates nothing); the twin of scaffold.vacated_dirs.
 */
export function vacatedDirs(renames: ScaffoldRename[]): string[] {
  const kept = new Set<string>();
  for (const r of renames) {
    for (let dir = parentDir(r.to), prev = ""; dir !== prev; prev = dir, dir = parentDir(dir)) {
      kept.add(pathKey(dir));
    }
  }
  const out = new Map<string, string>();
  for (const r of renames) {
    for (let dir = parentDir(r.from), prev = ""; dir !== prev; prev = dir, dir = parentDir(dir)) {
      if (kept.has(pathKey(dir))) {
        break;
      }
      out.set(pathKey(dir), dir);
    }
  }
  return [...out.values()].sort((a, b) => b.split(/[\\/]/).length - a.split(/[\\/]/).length);
}
