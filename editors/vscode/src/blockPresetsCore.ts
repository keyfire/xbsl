// Block presets (docs/DESIGNER.md, hook 8): a named, persistent version of the structure
// view's copy/paste. A developer saves a component subtree (its yaml fragment) under a name and
// later inserts it into any form. The store is a plain list in globalState; these pure helpers
// keep it deduplicated by name, newest first, and capped. The extension side (formStructure.ts)
// extracts the fragment from the live buffer and inserts it through the engine's insert_fragment,
// so nothing here has to understand yaml.

export interface BlockPreset {
  name: string;
  fragment: string;
  // The component type of the fragment root, kept only for the pick list description.
  type?: string;
}

export const BLOCK_PRESETS_KEY = "xbsl.formStructure.blockPresets";
export const BLOCK_PRESETS_MAX = 50;

// Add or replace a preset by name (a re-save under an existing name overwrites it), moving it
// to the front; the list is capped. Names are compared trimmed - a blank name is rejected by
// returning the list unchanged.
export function addPreset(
  list: BlockPreset[],
  preset: BlockPreset,
  max = BLOCK_PRESETS_MAX
): BlockPreset[] {
  const name = preset.name.trim();
  if (!name) {
    return list;
  }
  const kept = list.filter((p) => p.name !== name);
  return [{ ...preset, name }, ...kept].slice(0, max);
}

export function removePreset(list: BlockPreset[], name: string): BlockPreset[] {
  return list.filter((p) => p.name !== name);
}

// Accepts only well-formed records - guards against a corrupted or foreign globalState value.
export function sanitizePresets(value: unknown): BlockPreset[] {
  if (!Array.isArray(value)) {
    return [];
  }
  const out: BlockPreset[] = [];
  const seen = new Set<string>();
  for (const item of value) {
    if (
      item &&
      typeof item.name === "string" &&
      typeof item.fragment === "string" &&
      item.name.trim() &&
      item.fragment.trim() &&
      !seen.has(item.name)
    ) {
      seen.add(item.name);
      out.push({
        name: item.name,
        fragment: item.fragment,
        type: typeof item.type === "string" ? item.type : undefined,
      });
    }
  }
  return out;
}
