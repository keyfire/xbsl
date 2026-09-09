// The rule catalogue of the engine, parsed. `xbsl --list-rules --format json` answers with the
// same records the MCP `list_rules` tool does - parameters and the off reason included. An engine
// older than that ignores --format here and prints the human listing, so the text form stays as a
// fallback: the extension talks to whatever version is installed, and a catalogue it cannot read
// must degrade to fewer columns, never to missing rules.

export interface RuleParam {
  name: string;
  value: string | number;
  default: string | number;
  env: string;
  doc: string;
}

export interface CatalogueEntry {
  tier: string;
  level: string;
  title: string;
  offByDefault: boolean;
  // Prose about a deliberate exclusion and the numbers the rule judges by: both are continuation
  // lines of the human listing, which the text parser drops - only the json form carries them.
  offReason?: string;
  params?: RuleParam[];
}

function fromJson(out: string): Map<string, CatalogueEntry> | undefined {
  let data: unknown;
  try {
    data = JSON.parse(out);
  } catch {
    return undefined;
  }
  if (!Array.isArray(data)) {
    return undefined;
  }
  const map = new Map<string, CatalogueEntry>();
  for (const item of data as Record<string, unknown>[]) {
    const id = typeof item?.id === "string" ? item.id : undefined;
    if (!id) {
      continue;
    }
    const params = Array.isArray(item.params) ? (item.params as RuleParam[]) : undefined;
    const reason = typeof item.off_reason === "string" ? item.off_reason : "";
    map.set(id, {
      tier: String(item.tier ?? ""),
      level: String(item.severity ?? ""),
      title: String(item.title ?? ""),
      offByDefault: item.enabled_by_default === false,
      offReason: reason || undefined,
      params: params && params.length ? params : undefined,
    });
  }
  return map.size ? map : undefined;
}

// "A  group/rule  warning  title", and a rule that is off by default carries an extra "off"
// column right after the tier: "D  off  group/rule  warning  title". Continuation lines are
// indented prose in the language of the run - they are skipped here on purpose.
function fromText(out: string): Map<string, CatalogueEntry> {
  const map = new Map<string, CatalogueEntry>();
  for (const line of out.split(/\r?\n/)) {
    const m = /^([A-Z])\s+(off\s+)?(\S+\/\S+)\s+(\S+)\s*(.*)$/.exec(line);
    if (m) {
      map.set(m[3], {
        tier: m[1],
        level: m[4],
        title: (m[5] || "").trim(),
        offByDefault: Boolean(m[2]),
      });
    }
  }
  return map;
}

export function parseRuleCatalogue(out: string): Map<string, CatalogueEntry> {
  return fromJson(out.trim()) ?? fromText(out);
}
