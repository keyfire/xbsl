// Thin cached client of the engine's xbsl/metadataSchema request - the metadata counterpart of
// uiSchemaClient. It answers "which properties may an element of this kind have", so the
// properties panel can offer the ones a file does not set yet (Представление, Иерархический,
// ВводПоСтроке ... of a Справочник). The engine is the only source: names, types, defaults and
// enumeration values all come from the platform metamodel. Everything degrades to "no schema"
// when the LSP server is down or the dataset has no generated metamodel - the panel then shows
// the set properties alone, exactly as before.

import { lspRequest } from "./lspClient";
import { MetaSchema } from "./propsModes";

interface MetaSchemaResponse {
  available?: boolean;
  kind?: string;
  class?: string;
  props?: MetaSchema["props"];
  enums?: Record<string, string[]>;
}

const cache = new Map<string, MetaSchema | undefined>();

export function resetMetaSchemaCache(): void {
  cache.clear();
}

// The schema of one element kind (ВидЭлемента) or of a collection item inside it, or undefined
// when unavailable. An item is addressed by its path - the collection keys from the root down
// and the `Имя` of the item on each level (the platform dispatches by it: `Код` of a Справочник
// is a class of its own). Cached for the session: the metamodel is generated data, it does not
// change while the editor runs.
export async function metaSchema(
  kind: string,
  path?: { sections: string[]; names: string[] }
): Promise<MetaSchema | undefined> {
  const sections = path?.sections ?? [];
  const names = path?.names ?? [];
  const key = [kind, ...sections.map((s, i) => `${s}:${names[i] ?? ""}`)].join("/");
  if (cache.has(key)) {
    return cache.get(key);
  }
  const res = await lspRequest<MetaSchemaResponse>("xbsl/metadataSchema", { kind, sections, names });
  const props = res?.available ? res.props : undefined;
  const schema = props && Object.keys(props).length
    ? { kind, props, enums: res?.enums ?? {} }
    : undefined;
  cache.set(key, schema);
  return schema;
}
