// "Find All References" on a resource of the metadata tree, the part without vscode: the answer of
// the engine (xbsl/metaResourceReferences, or the CLI resource-references) arranged the way the
// References view shows it - the places grouped by file, the line of a place cut to a preview with
// the place marked, and the order F4 walks them in.

// What a place is, as the engine tells: a static reference that resolves to the file, a key two
// visible resources folders hold, a string that spells the path, a string with the folder and a
// computed name. An engine newer than the extension may add a kind, so the type stays open.
export type ResourceReferenceKind = "reference" | "ambiguous" | "string" | "computed";

export interface EnginePosition {
  line: number; // zero-based
  character: number; // zero-based, in UTF-16 code units - the way a JavaScript string counts
}

export interface EngineResourceReference {
  path: string;
  kind: ResourceReferenceKind | string;
  range: { start: EnginePosition; end: EnginePosition };
  text: string; // the whole line the place stands on
}

export interface ResourceReferencesAnswer {
  resource?: string;
  folder?: boolean;
  resourcesDir?: string;
  total?: number;
  references?: EngineResourceReference[];
  error?: string;
}

export interface ReferenceFile {
  path: string;
  references: EngineResourceReference[];
}

// The places by file: the files in the order the engine gave them (it sorts by path), the places of
// a file by position. Paths are compared as written - the engine spells a file the same way every
// time it names it.
export function groupByFile(references: readonly EngineResourceReference[]): ReferenceFile[] {
  const files: ReferenceFile[] = [];
  const byPath = new Map<string, ReferenceFile>();
  for (const reference of references) {
    let file = byPath.get(reference.path);
    if (!file) {
      file = { path: reference.path, references: [] };
      byPath.set(reference.path, file);
      files.push(file);
    }
    file.references.push(reference);
  }
  for (const file of files) {
    file.references.sort((a, b) => comparePositions(a.range.start, b.range.start));
  }
  return files;
}

export function comparePositions(a: EnginePosition, b: EnginePosition): number {
  return a.line - b.line || a.character - b.character;
}

export interface LinePreview {
  label: string;
  highlight: [number, number]; // the place within the label
}

// The line of a place as a row of the view shows it: without the indentation, with a long head cut
// down to at most `before` characters ahead of the place, from the start of a word, and a tail
// beyond `width` cut off. The place itself is never cut, however long.
export function linePreview(text: string, start: number, end: number, before = 24, width = 120): LinePreview {
  const placeStart = Math.max(0, Math.min(start, text.length));
  const placeEnd = Math.max(placeStart, Math.min(end, text.length));
  let from = 0;
  while (from < placeStart && /\s/.test(text[from])) {
    from++;
  }
  let head = "";
  if (placeStart - from > before) {
    from = placeStart - before;
    // The cut starts at a word: the tail of a word cut in two reads as noise.
    const space = text.slice(from, placeStart).search(/\s/);
    if (space >= 0) {
      from += space;
      while (from < placeStart && /\s/.test(text[from])) {
        from++;
      }
    }
    head = "...";
  }
  let to = text.length;
  let tail = "";
  const room = Math.max(width, placeEnd - from);
  if (to - from > room) {
    to = from + room;
    tail = "...";
  }
  const label = head + text.slice(from, placeEnd) + text.slice(placeEnd, to).trimEnd() + tail;
  const shift = head.length - from;
  return { label, highlight: [placeStart + shift, placeEnd + shift] };
}

// A place of the grouped answer: the file's index and the place's index in it.
export type PlaceIndex = readonly [file: number, place: number];

// The place after the given one, or before it, across the files - wrapping around at either end,
// the way F4 and Shift+F4 walk the results of a search.
export function stepPlace(files: readonly ReferenceFile[], at: PlaceIndex, forward: boolean): PlaceIndex {
  let [file, place] = at;
  if (forward) {
    if (place + 1 < files[file].references.length) {
      return [file, place + 1];
    }
    file = (file + 1) % files.length;
    return [file, 0];
  }
  if (place > 0) {
    return [file, place - 1];
  }
  file = (file - 1 + files.length) % files.length;
  return [file, files[file].references.length - 1];
}

// The place of a file nearest to a position: the one that covers it, or the first one after it,
// or the last one of the file when the position is past them all. A file without places - none.
export function nearestPlace(
  files: readonly ReferenceFile[],
  isFile: (path: string) => boolean,
  position: EnginePosition
): PlaceIndex | undefined {
  const file = files.findIndex((candidate) => isFile(candidate.path));
  if (file < 0) {
    return undefined;
  }
  const references = files[file].references;
  const place = references.findIndex((reference) => comparePositions(position, reference.range.end) <= 0);
  return [file, place < 0 ? references.length - 1 : place];
}

// The fragment an editor opens a dropped link at: `L<line>,<column>-<line>,<column>`, one-based.
export function rangeFragment(range: { start: EnginePosition; end: EnginePosition }): string {
  const { start, end } = range;
  return `L${start.line + 1},${start.character + 1}-${end.line + 1},${end.character + 1}`;
}
