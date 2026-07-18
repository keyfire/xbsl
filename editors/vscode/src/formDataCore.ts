// Pure core of the "Data" view (no vscode import), unit-tested under plain Node
// (test/formDataCore.test.ts): the shapes of the engine payloads the panel consumes
// (the componentProperties field of xbsl/formTree, the xbsl/objectInfo summary), the
// drag-and-drop payload of the panel and the yaml fragment a drop materializes into.
// The fragment mirrors the engine's own attribute-to-component mapping
// (xbsl/scaffold._form_field_component): Булево becomes a Флажок, everything else a
// ПолеВвода<Тип>; the multiline convention (Описание/Комментарий) is the engine's too.
// All EDIT logic lives in the engine (formedits.insert_fragment and the property_*
// operations); this module only shapes requests and payloads.

// --- engine payload shapes ------------------------------------------------------------------

export interface DataSpan {
  start: number;
  end: number;
}

// One record of the component's top-level Свойства section (formmodel.ComponentProperty
// serialized into the "componentProperties" field of xbsl/formTree). name/type are null
// for a malformed record (no Имя or Тип key).
export interface ComponentPropertyRecord {
  name: string | null;
  type: string | null;
  span: DataSpan;
  nameSpan?: DataSpan | null;
  typeSpan?: DataSpan | null;
}

// The slice of xbsl/formTree the Data panel needs: the component's own properties and the
// root component type (whose ui schema supplies the enum candidates for the type picker).
export interface DataFormTreeResponse {
  available: boolean;
  reason?: string;
  root?: { type?: string | null } | null;
  componentProperties?: ComponentPropertyRecord[];
}

// The slice of xbsl/objectInfo (the mirror of meta_object_info) the panel shows: the
// object's fields - standard attributes merged in by the engine - and its tabular parts.
export interface ObjectInfoField {
  name: string;
  type: string;
}

export interface ObjectInfoTabular {
  name: string;
  fields: ObjectInfoField[];
}

export interface ObjectInfoResponse {
  error?: string;
  kind?: string;
  name?: string;
  fields?: ObjectInfoField[];
  tabulars?: ObjectInfoTabular[];
}

// xbsl/formEdit response for the flat property_* operations: the pseudo node id
// ("Свойства/<Имя>") only carries the record span for the cursor jump; notes are
// user-facing warnings (e.g. binding usages left behind by property_rename).
export interface DataFormEditResponse {
  edits?: { start: number; end: number; newText: string }[];
  node?: { id: string; span: DataSpan } | null;
  notes?: string[];
  error?: string;
}

// --- drag-and-drop payload -------------------------------------------------------------------

// The Data panel's own tree MIME (VS Code derives "application/vnd.code.tree.<viewid
// lowercase>" from the view id xbslFormData); the structure view accepts it next to the
// palette MIME.
export const DATA_MIME = "application/vnd.code.tree.xbslformdata";

// A dragged record: an object attribute binds as =Объект.Имя, a component property as
// =Имя. multiline marks the fields the engine renders with a multiline input
// (Описание/Комментарий).
export interface DataDragPayload {
  kind: "attribute" | "componentProperty";
  name: string;
  type: string;
  multiline?: boolean;
}

export function encodeDataDrag(payload: DataDragPayload): string {
  return JSON.stringify(payload);
}

export function decodeDataDrag(raw: string): DataDragPayload | undefined {
  try {
    const data = JSON.parse(raw) as DataDragPayload;
    if (
      (data?.kind === "attribute" || data?.kind === "componentProperty") &&
      typeof data?.name === "string" &&
      data.name.length > 0 &&
      typeof data?.type === "string" &&
      (data.multiline === undefined || typeof data.multiline === "boolean")
    ) {
      return data;
    }
  } catch {
    // not our payload
  }
  return undefined;
}

// --- the input-component fragment ------------------------------------------------------------

// The engine's multiline convention (scaffold._form_field_component): a string-typed
// Описание/Комментарий gets a multiline input.
export function isMultilineText(name: string, type: string): boolean {
  return (type === "Строка" || type === "") && (name === "Описание" || name === "Комментарий");
}

// The yaml block of the input component a dropped record turns into - the payload of the
// engine's insert_fragment operation (one mapping with a top-level Тип key; the engine
// re-indents it to the destination). Mirrors scaffold._form_field_component with the
// designer's additions: Заголовок carries the record name, a ПолеВвода stretches
// horizontally. Types go into ПолеВвода<Тип> verbatim - generics, unions and reference
// types (Товары.Ссылка) as they are spelled on the record; an empty type means Строка.
export function buildFieldFragment(payload: DataDragPayload): string {
  const binding = payload.kind === "attribute" ? `=Объект.${payload.name}` : `=${payload.name}`;
  if (payload.type === "Булево") {
    return ["Тип: Флажок", `Заголовок: ${payload.name}`, `Значение: ${binding}`].join("\n");
  }
  const lines = [
    `Тип: ПолеВвода<${payload.type || "Строка"}>`,
    `Заголовок: ${payload.name}`,
    `Значение: ${binding}`,
    "РастягиватьПоГоризонтали: Истина",
  ];
  if (payload.multiline) {
    lines.push("НастройкиВводаСтроки:", "    Многострочная: Истина");
  }
  return lines.join("\n");
}

// --- property-name validation ------------------------------------------------------------------

// The identifier ranges deliberately EXCLUDE Ёё: the 1C:Element naming standard bans the
// letter ё in names (unlike the engine's own identifier check, which the platform allows).
const PROPERTY_NAME_RE = /^[A-Za-zА-Яа-я_][A-Za-zА-Яа-я0-9_]*$/;

export type PropertyNameError = "empty" | "yo" | "identifier" | "duplicate";

// Why a new/renamed property name is rejected, undefined when it is fine. The ё case is
// separated from the general identifier failure so the message can cite the standard.
export function propertyNameError(
  name: string,
  existing: readonly (string | null)[]
): PropertyNameError | undefined {
  if (!name) {
    return "empty";
  }
  if (/[Ёё]/.test(name)) {
    return "yo";
  }
  if (!PROPERTY_NAME_RE.test(name)) {
    return "identifier";
  }
  if (existing.includes(name)) {
    return "duplicate";
  }
  return undefined;
}

// The ready-made choices of the property type picker; anything else is entered manually
// (the engine validates the final spelling).
export const PROPERTY_PRIMITIVE_TYPES: readonly string[] = ["Строка", "Число", "Булево", "Дата"];
