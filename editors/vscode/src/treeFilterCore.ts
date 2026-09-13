// The filter of the metadata tree by subsystems and packages - the pure half, no vscode (node
// tests run it).
//
// A choice is a set of placement keys per project. `Склад` is the root of a subsystem - the
// objects lying right in its folder - and `Склад::Партии` is a package with the objects lying
// right in its folder. A key ending in `::*` takes the place whole, with everything nested in
// it: a checked subsystem stays checked when a package appears in it later, and a package
// created from the tree under a checked subsystem does not vanish from the tree the moment it is
// made. An item passes when its own key is chosen or a whole key covers it. The key of an item is
// the engine's placement (packagesCore.placeOf), never computed here.
//
// The form draws the same choice as a tree of checkboxes: a project, its subsystems, their
// packages with the nesting, and an "objects outside packages" item where a subsystem or a
// package holds both objects of its own and packages. The state of a node is derived from the
// choice and never stored. The choice written back from the states is canonical: a node whose
// items are all checked is written as its whole key, and a key no checkbox stands for is dropped -
// which is how a renamed or deleted package leaves the stored filter.
//
// Without the engine's answer the packages are unknown. The form then lists the subsystems found
// by their descriptors, and nothing is dropped: a key that cannot be checked is kept as it is.

import {
  EnginePlacement,
  isUnder,
  PackageGroup,
  pathKey,
  placeOf,
  ProjectPlacement,
  SubsystemGroup,
} from "./packagesCore";

export type CheckState = "checked" | "unchecked" | "mixed";

// `loose` - the objects lying right in a subsystem or a package that has packages as well.
export type FilterNodeKind = "project" | "subsystem" | "package" | "loose";

export interface FilterNode {
  id: string; // unique across the tree and stable between answers
  kind: FilterNodeKind;
  name: string; // the label: a project, a subsystem, the last segment of a package; "" for loose
  project: string; // the project key (pathKey of its folder, "" without a descriptor)
  place: string; // the placement key: `Склад`, `Склад::Партии`; "" for a project
  count: number; // objects under the node, nested places included
  title?: string; // a tooltip: the namespace of a subsystem or a package
  packagesKnown?: boolean; // project: the engine placed it, so its packages are listed
  children: FilterNode[];
}

export interface FilterTree {
  projects: FilterNode[];
}

// Project key -> the chosen keys of that project.
export type Selection = Map<string, Set<string>>;

const SEPARATOR = "::";
const WHOLE = "::*";

export function placeKey(subsystem: string, pkg?: string | null): string {
  return pkg ? subsystem + SEPARATOR + pkg : subsystem;
}

export function wholeKey(place: string): string {
  return place + WHOLE;
}

// The subsystem a key belongs to - its first segment.
export function subsystemOfKey(key: string): string {
  const cut = key.indexOf(SEPARATOR);
  return cut < 0 ? key : key.slice(0, cut);
}

/** Is the place taken whole - by its own whole key or by the whole key of a place enclosing it? */
export function covers(keys: ReadonlySet<string>, place: string): boolean {
  const segments = place.split(SEPARATOR);
  for (let i = 1; i <= segments.length; i++) {
    if (keys.has(wholeKey(segments.slice(0, i).join(SEPARATOR)))) {
      return true;
    }
  }
  return false;
}

/** Does an item lying at the place pass: its own key chosen, or a whole key covering it. */
export function placePasses(keys: ReadonlySet<string>, place: string): boolean {
  return keys.has(place) || covers(keys, place);
}

/** Is anything under the place chosen - the place whole, its own objects or a place inside it?
 * The tree grouped by subsystems keeps a subsystem or a package node exactly when this holds. */
export function touches(keys: ReadonlySet<string>, place: string): boolean {
  if (covers(keys, place)) {
    return true;
  }
  for (const key of keys) {
    if (key === place || key.startsWith(place + SEPARATOR)) {
      return true;
    }
  }
  return false;
}

// --- the tree of checkboxes -----------------------------------------------------------------

export interface FilterProjectInput {
  dir: string; // "" - the sources carry no project descriptor
  name: string;
  title?: string; // `Поставщик::Проект`
}

// A subsystem folder the tree found by its descriptor: what the form lists without the engine.
export interface FilterSubsystemDir {
  name: string;
  dir: string;
}

export interface FilterInput<T> {
  projects: FilterProjectInput[]; // empty - the sources carry no project descriptor
  items: T[]; // the objects the tree shows; counted, never placed here
  pathOf: (item: T) => string;
  projectOf: (p: string) => string; // the folder of the project an item is drawn under
  count: (items: T[]) => number; // how many of these items the tree shows at the top of a category
  placement?: EnginePlacement;
  subsystems: FilterSubsystemDir[];
}

const byName = (a: { name: string }, b: { name: string }): number => a.name.localeCompare(b.name, "ru");

function nodeId(project: string, kind: FilterNodeKind, place: string): string {
  return `${project}|${kind}|${place}`;
}

function pushTo<T>(map: Map<string, T[]>, key: string, item: T): void {
  const list = map.get(key);
  if (list) {
    list.push(item);
  } else {
    map.set(key, [item]);
  }
}

// The subsystems of a project the tree found by descriptors: a descriptor below another one of
// the same project is a package with a descriptor it does not need, not a subsystem.
function topSubsystems(
  subsystems: FilterSubsystemDir[],
  project: string,
  projectOf: (p: string) => string
): FilterSubsystemDir[] {
  const own = subsystems.filter((s) => pathKey(projectOf(s.dir)) === project);
  return own.filter((s) => !own.some((other) => other !== s && isUnder(s.dir, other.dir)));
}

function looseNode(project: string, place: string, count: number): FilterNode {
  return { id: nodeId(project, "loose", place), kind: "loose", name: "", project, place, count, children: [] };
}

/** The tree of checkboxes: a node per project, its subsystems, packages and loose items.
 *
 * With the engine's answer the subsystems and packages are the engine's and every item is counted
 * where the engine placed it. A project the answer does not know yet - and every project without
 * an answer at all - lists the subsystems found by their descriptors, with no packages.
 */
export function buildFilterTree<T>(input: FilterInput<T>): FilterTree {
  const projects = input.projects.length ? input.projects : [{ dir: "", name: "" }];
  const itemsByProject = new Map<string, T[]>();
  for (const item of input.items) {
    pushTo(itemsByProject, pathKey(input.projectOf(input.pathOf(item))), item);
  }
  const nodes = projects.map((p) => {
    const project = pathKey(p.dir);
    const items = itemsByProject.get(project) ?? [];
    const placed = input.placement?.projects.find((candidate) => pathKey(candidate.dir) === project);
    const children = input.placement && placed
      ? placedSubsystems(project, items, input, placed, input.placement)
      : describedSubsystems(project, items, input);
    const node: FilterNode = {
      id: nodeId(project, "project", ""),
      kind: "project",
      name: p.name,
      project,
      place: "",
      count: children.reduce((sum, child) => sum + child.count, 0),
      title: p.title,
      packagesKnown: Boolean(input.placement && placed),
      children,
    };
    return node;
  });
  return { projects: nodes };
}

function placedSubsystems<T>(
  project: string,
  items: T[],
  input: FilterInput<T>,
  placed: ProjectPlacement,
  placement: EnginePlacement
): FilterNode[] {
  const byPlace = new Map<string, T[]>();
  for (const item of items) {
    const where = placeOf(input.pathOf(item), placed, placement);
    if (where) {
      pushTo(byPlace, placeKey(where.subsystem.name, where.packageKey), item);
    }
  }
  const countAt = (place: string): number => input.count(byPlace.get(place) ?? []);

  // A place with objects of its own and places nested in it gets the loose item after them; a
  // place with only one of the two needs no item - its own checkbox says it all.
  const withLoose = (place: string, own: number, nested: FilterNode[]): FilterNode[] =>
    nested.length && own > 0 ? [...nested, looseNode(project, place, own)] : nested;

  const packageNode = (subsystem: SubsystemGroup, group: PackageGroup): FilterNode => {
    const place = placeKey(subsystem.name, group.key);
    const own = countAt(place);
    const nested = [...group.children].sort(byName).map((child) => packageNode(subsystem, child));
    return {
      id: nodeId(project, "package", place),
      kind: "package",
      name: group.name,
      project,
      place,
      count: own + nested.reduce((sum, n) => sum + n.count, 0),
      title: group.namespace,
      children: withLoose(place, own, nested),
    };
  };

  return [...placed.subsystems].sort(byName).map((subsystem) => {
    const own = countAt(subsystem.name);
    const packages = [...subsystem.packages].sort(byName).map((group) => packageNode(subsystem, group));
    return {
      id: nodeId(project, "subsystem", subsystem.name),
      kind: "subsystem" as const,
      name: subsystem.name,
      project,
      place: subsystem.name,
      count: own + packages.reduce((sum, n) => sum + n.count, 0),
      title: subsystem.namespace,
      children: withLoose(subsystem.name, own, packages),
    };
  });
}

function describedSubsystems<T>(project: string, items: T[], input: FilterInput<T>): FilterNode[] {
  return topSubsystems(input.subsystems, project, input.projectOf)
    .sort(byName)
    .map((subsystem) => ({
      id: nodeId(project, "subsystem", subsystem.name),
      kind: "subsystem" as const,
      name: subsystem.name,
      project,
      place: subsystem.name,
      count: input.count(items.filter((item) => isUnder(input.pathOf(item), subsystem.dir))),
      children: [],
    }));
}

/** Every project of the tree has its packages listed (the engine placed it). */
export function packagesKnown(tree: FilterTree): boolean {
  return tree.projects.every((p) => p.packagesKnown);
}

// --- states -------------------------------------------------------------------------------

function aggregate(states: CheckState[]): CheckState {
  if (states.every((s) => s === "checked")) {
    return "checked";
  }
  return states.every((s) => s === "unchecked") ? "unchecked" : "mixed";
}

function projectStates(projectNode: FilterNode, keys: ReadonlySet<string>, out: Map<string, CheckState>): void {
  const known = projectNode.packagesKnown !== false;
  const visit = (node: FilterNode): CheckState => {
    const childStates = node.children.map(visit);
    let state: CheckState;
    if (node.kind === "loose") {
      state = placePasses(keys, node.place) ? "checked" : "unchecked";
    } else if (node.kind !== "project" && covers(keys, node.place)) {
      state = "checked";
    } else if (childStates.length) {
      state = aggregate(childStates);
    } else if (node.kind === "project") {
      state = "unchecked";
    } else if (known && keys.has(node.place)) {
      state = "checked";
    } else if (!known && touches(keys, node.place)) {
      // A subsystem the engine has not unfolded while a part of it is chosen: the part is real,
      // the form just cannot show which one.
      state = "mixed";
    } else {
      state = "unchecked";
    }
    out.set(node.id, state);
    return state;
  };
  visit(projectNode);
}

/** The state of every node of the tree under the choice. */
export function nodeStates(tree: FilterTree, selection: Selection): Map<string, CheckState> {
  const out = new Map<string, CheckState>();
  for (const projectNode of tree.projects) {
    projectStates(projectNode, selection.get(projectNode.project) ?? new Set(), out);
  }
  return out;
}

// The key a checked node is written as.
function selectionKey(node: FilterNode): string {
  return node.kind === "loose" ? node.place : wholeKey(node.place);
}

function keysInside(keys: ReadonlySet<string>, place: string): string[] {
  return [...keys].filter((key) => key === place || key.startsWith(place + SEPARATOR));
}

/** The choice written back from the states of the tree - see the head of the file.
 *
 * A project the tree does not list keeps its keys: it may come back. A project without the
 * engine's answer keeps the keys of the subsystems the form does not list, and a subsystem shown
 * as partly chosen keeps its keys unchanged.
 */
export function canonicalSelection(tree: FilterTree, selection: Selection): Selection {
  const out: Selection = new Map();
  const listed = new Set(tree.projects.map((p) => p.project));
  for (const [project, keys] of selection) {
    if (!listed.has(project) && keys.size) {
      out.set(project, new Set(keys));
    }
  }
  for (const projectNode of tree.projects) {
    const keys = selection.get(projectNode.project) ?? new Set<string>();
    const states = new Map<string, CheckState>();
    projectStates(projectNode, keys, states);
    const kept = new Set<string>();
    const emit = (node: FilterNode): void => {
      const state = states.get(node.id);
      if (state === "unchecked") {
        return;
      }
      if (state === "checked" && node.kind !== "project") {
        kept.add(selectionKey(node));
        return;
      }
      if (!node.children.length) {
        keysInside(keys, node.place).forEach((key) => kept.add(key));
        return;
      }
      node.children.forEach(emit);
    };
    emit(projectNode);
    if (projectNode.packagesKnown === false) {
      const shown = new Set(projectNode.children.map((child) => child.place));
      for (const key of keys) {
        if (!shown.has(subsystemOfKey(key))) {
          kept.add(key);
        }
      }
    }
    if (kept.size) {
      out.set(projectNode.project, kept);
    }
  }
  return out;
}

// --- editing the choice -------------------------------------------------------------------

function findPath(nodes: FilterNode[], id: string): FilterNode[] | undefined {
  for (const node of nodes) {
    if (node.id === id) {
      return [node];
    }
    const below = findPath(node.children, id);
    if (below) {
      return [node, ...below];
    }
  }
  return undefined;
}

// Check or uncheck one node in the keys of its project. `path` runs from the project down to it.
function setNode(path: FilterNode[], keys: Set<string>, checked: boolean): void {
  const node = path[path.length - 1];
  if (node.kind === "project") {
    node.children.forEach((child) => setNode([...path, child], keys, checked));
    return;
  }
  if (checked) {
    if (node.kind !== "loose") {
      keysInside(keys, node.place).forEach((key) => keys.delete(key));
    }
    keys.add(selectionKey(node));
    return;
  }
  // A whole key above the node covers it: open that key - and any whole key further down the way -
  // up into the keys of everything along the way except the node itself, so the rest stays chosen.
  const coveredAt = path.findIndex((n) => n.kind !== "project" && n.kind !== "loose" && keys.has(wholeKey(n.place)));
  if (coveredAt >= 0) {
    for (let i = coveredAt; i < path.length - 1; i++) {
      keys.delete(wholeKey(path[i].place));
      for (const sibling of path[i].children) {
        if (sibling !== path[i + 1]) {
          keys.add(selectionKey(sibling));
        }
      }
    }
  }
  if (node.kind === "loose") {
    keys.delete(node.place);
  } else {
    keysInside(keys, node.place).forEach((key) => keys.delete(key));
  }
}

function copySelection(selection: Selection): Selection {
  return new Map([...selection].map(([project, keys]) => [project, new Set(keys)]));
}

/** A click on a node: a checked node is unchecked with everything under it, an unchecked or a
 * partly checked one is checked with everything under it. */
export function toggleNode(tree: FilterTree, selection: Selection, id: string): Selection {
  const path = findPath(tree.projects, id);
  if (!path) {
    return selection;
  }
  const checked = nodeStates(tree, selection).get(id) !== "checked";
  const next = copySelection(selection);
  const project = path[0].project;
  const keys = next.get(project) ?? new Set<string>();
  setNode(path, keys, checked);
  next.set(project, keys);
  return canonicalSelection(tree, next);
}

/** Every node of the tree checked. */
export function selectAll(tree: FilterTree, selection: Selection): Selection {
  const next = copySelection(selection);
  for (const projectNode of tree.projects) {
    const keys = next.get(projectNode.project) ?? new Set<string>();
    setNode([projectNode], keys, true);
    next.set(projectNode.project, keys);
  }
  return canonicalSelection(tree, next);
}

/** How many objects the choice keeps: the counts of the checked nodes, each counted once. */
export function selectedCount(tree: FilterTree, selection: Selection): number {
  const states = nodeStates(tree, selection);
  const walk = (node: FilterNode): number => {
    const state = states.get(node.id);
    if (state === "checked") {
      return node.count;
    }
    return state === "mixed" ? node.children.reduce((sum, child) => sum + walk(child), 0) : 0;
  };
  return tree.projects.reduce((sum, p) => sum + walk(p), 0);
}

// --- the filter of the tree ---------------------------------------------------------------

export function hasChoice(selection: Selection, projects: string[]): boolean {
  const keys = projects.length ? projects.map(pathKey) : [""];
  return keys.some((project) => (selection.get(project)?.size ?? 0) > 0);
}

export interface PredicateInput {
  selection: Selection;
  projects: string[]; // the folders of the projects the tree draws; empty - no descriptor
  projectOf: (p: string) => string; // the folder of the project an item is drawn under
  placement?: EnginePlacement;
  subsystems: FilterSubsystemDir[]; // descriptor folders, for a project the engine has not placed
}

/** The test an item of the tree passes, or undefined when nothing is chosen - no filter at all.
 *
 * With a choice, an item of a project with nothing chosen does not pass, and neither does an item
 * lying outside every subsystem. An item of a project the engine has not placed is judged by the
 * subsystem folder holding it, and only a whole subsystem lets it through: which package the item
 * is in, nothing here knows.
 */
export function filterPredicate(input: PredicateInput): ((p: string) => boolean) | undefined {
  if (!hasChoice(input.selection, input.projects)) {
    return undefined;
  }
  const placedByProject = new Map<string, ProjectPlacement | undefined>();
  const describedByProject = new Map<string, FilterSubsystemDir[]>();
  return (p: string): boolean => {
    const project = pathKey(input.projectOf(p));
    const keys = input.selection.get(project);
    if (!keys?.size) {
      return false;
    }
    if (!placedByProject.has(project)) {
      placedByProject.set(project, input.placement?.projects.find((candidate) => pathKey(candidate.dir) === project));
    }
    const placed = placedByProject.get(project);
    if (input.placement && placed) {
      const where = placeOf(p, placed, input.placement);
      return !!where && placePasses(keys, placeKey(where.subsystem.name, where.packageKey));
    }
    if (!describedByProject.has(project)) {
      describedByProject.set(project, topSubsystems(input.subsystems, project, input.projectOf));
    }
    const holder = describedByProject.get(project)?.find((s) => isUnder(p, s.dir));
    return !!holder && keys.has(wholeKey(holder.name));
  };
}

export interface FilterSummary {
  items: Array<{ name: string; partial: boolean }>;
  more: number; // subsystems left out of `items`
}

/** What the label of a project says about its choice: the subsystems in the order of their names,
 * a partly chosen one marked, cut after `maxItems` names or `maxChars` characters. */
export function summarize(keys: ReadonlySet<string>, maxItems = 3, maxChars = 48): FilterSummary {
  const names = [...new Set([...keys].map(subsystemOfKey))].sort((a, b) => a.localeCompare(b, "ru"));
  const items: FilterSummary["items"] = [];
  let length = 0;
  for (const name of names) {
    if (items.length >= maxItems || (items.length > 0 && length + name.length > maxChars)) {
      break;
    }
    items.push({ name, partial: !keys.has(wholeKey(name)) });
    length += name.length + 2;
  }
  return { items, more: names.length - items.length };
}

// --- storage ------------------------------------------------------------------------------

/** The choice out of the workspace state; anything malformed reads as nothing chosen. */
export function readSelection(raw: unknown): Selection {
  const out: Selection = new Map();
  if (!raw || typeof raw !== "object" || Array.isArray(raw)) {
    return out;
  }
  for (const [project, keys] of Object.entries(raw as Record<string, unknown>)) {
    if (!Array.isArray(keys)) {
      continue;
    }
    const valid = keys.filter((key): key is string => typeof key === "string" && key.trim() !== "");
    if (valid.length) {
      out.set(project, new Set(valid));
    }
  }
  return out;
}

/** The choice as the workspace state keeps it: the keys of every project, sorted. */
export function writeSelection(selection: Selection): Record<string, string[]> {
  const out: Record<string, string[]> = {};
  for (const [project, keys] of [...selection].sort(([a], [b]) => a.localeCompare(b))) {
    if (keys.size) {
      out[project] = [...keys].sort();
    }
  }
  return out;
}

export function sameSelection(a: Selection, b: Selection): boolean {
  return JSON.stringify(writeSelection(a)) === JSON.stringify(writeSelection(b));
}
