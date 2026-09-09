// Renders the rules panel HTML outside the editor host: the panel's own html() over the real
// catalogue of the engine. Not part of `npm test` - a probe run by hand when the panel's look
// has to be shown (see the live-check skill).

import * as fs from "fs";
import { RulesPanel } from "../src/rulesPanel";
import { primeRuleCatalogue, ruleCatalogue } from "../src/ruleConfig";

async function main(): Promise<void> {
  const python = process.argv[2];
  const out = process.argv[3];
  primeRuleCatalogue(python, ["-m", "xbsl"]);
  const catalogue = await ruleCatalogue();
  const panel = Object.create(RulesPanel.prototype) as Record<string, unknown>;
  panel.scope = "user";
  const table = { "style/line-length": "info" };
  const rows = await (panel as unknown as { rows(t: unknown): Promise<unknown[]> }).rows(table);
  const html = (panel as unknown as { html(r: unknown, t: unknown): string }).html(rows, table);
  fs.writeFileSync(out, html, "utf-8");
  console.log(`rules: ${catalogue.size}, html: ${html.length} bytes -> ${out}`);
}

void main();
