// A small Markdown preview for documentation comments. It creates only known tags and
// escapes every source fragment before inserting it into HTML. Raw HTML remains text.

// The xbsl/docComment protocol uses Python Unicode code-point offsets. VS Code's document
// APIs use UTF-16 code units, so the adapter converts at both request and edit boundaries.
export function utf16ToCodePointOffset(text: string, offset: number): number {
  const limit = Math.min(Math.max(offset, 0), text.length);
  let codePoints = 0;
  for (let i = 0; i < limit; i++, codePoints++) {
    const unit = text.charCodeAt(i);
    if (unit >= 0xd800 && unit <= 0xdbff && i + 1 < limit) {
      const next = text.charCodeAt(i + 1);
      if (next >= 0xdc00 && next <= 0xdfff) {
        i++;
      }
    }
  }
  return codePoints;
}

export function codePointToUtf16Offset(text: string, offset: number): number {
  const limit = Math.max(offset, 0);
  let codePoints = 0;
  let i = 0;
  while (i < text.length && codePoints < limit) {
    const unit = text.charCodeAt(i);
    if (unit >= 0xd800 && unit <= 0xdbff && i + 1 < text.length) {
      const next = text.charCodeAt(i + 1);
      i += next >= 0xdc00 && next <= 0xdfff ? 2 : 1;
    } else {
      i++;
    }
    codePoints++;
  }
  return i;
}

/** A change of the comment field made by a toolbar button: the new text and its selection. */
export interface FieldEdit {
  text: string;
  start: number;
  end: number;
}

// The toolbar functions below run inside the inspector webview as their own source text
// (`fn.toString()`), so each one keeps its helpers inside its body.

/** Bold, italic or code around the selection: added, or taken off when the selection already
 *  has it - inside the selection (`**text**` selected whole) or around it. Spaces at the edges
 *  of the selection stay outside the markers: `**text **` is not bold in Markdown. A run of
 *  three stars is bold and italic at once, so each of the two markers can take its part off. */
export function toggleInline(
  text: string, start: number, end: number, marker: string, sample: string,
): FieldEdit {
  const size = marker.length;
  const mark = marker.charAt(0);
  const selected = text.slice(start, end);
  const lead = /^\s*/.exec(selected)![0].length;
  const trail = selected.length === lead ? 0 : /\s*$/.exec(selected)![0].length;
  const from = start + lead;
  const to = Math.max(end - trail, from);
  const run = (at: number, step: number): number => {
    let n = 0;
    for (let i = at; i >= 0 && i < text.length && text.charAt(i) === mark; i += step) { n++; }
    return n;
  };
  const carries = (count: number): boolean =>
    size === 2 ? count === 2 || count === 3 : mark === "*" ? count === 1 || count === 3 : count === 1;
  if (to - from > 2 * size) {
    const left = run(from, 1);
    const right = run(to - 1, -1);
    if (left < to - from && carries(left) && carries(right)) {
      const inner = text.slice(from + size, to - size);
      return { text: text.slice(0, from) + inner + text.slice(to), start: from, end: from + inner.length };
    }
  }
  if (carries(run(from - 1, -1)) && carries(run(to, 1))) {
    const inner = text.slice(from, to);
    return {
      text: text.slice(0, from - size) + inner + text.slice(to + size),
      start: from - size, end: from - size + inner.length,
    };
  }
  const inner = to > from ? text.slice(from, to) : sample;
  return {
    text: text.slice(0, from) + marker + inner + marker + text.slice(to),
    start: from + size, end: from + size + inner.length,
  };
}

/** The lines under the selection one heading level up: none, `#` and so on to `######`, then
 *  none again. The level of the first line decides for all of them. */
export function cycleHeading(text: string, start: number, end: number, sample: string): FieldEdit {
  const first = text.lastIndexOf("\n", start - 1) + 1;
  const stop = end > start && text.charAt(end - 1) === "\n" ? end - 1 : end;
  const next = text.indexOf("\n", stop);
  const last = next < 0 ? text.length : next;
  const lines = text.slice(first, last).split("\n");
  const current = /^(#{1,6})\s+/.exec(lines[0]);
  const level = current ? (current[1].length % 6) + 1 : 1;
  const wraps = current && current[1].length === 6;
  const prefix = wraps ? "" : "#".repeat(level) + " ";
  const changed = lines.map((line) => {
    const bare = line.replace(/^#{1,6}\s+/, "");
    return bare || lines.length > 1 ? prefix + bare : prefix + (wraps ? "" : sample);
  });
  const block = changed.join("\n");
  return { text: text.slice(0, first) + block + text.slice(last), start: first + prefix.length, end: first + block.length };
}

/** A list item of each line under the selection, or taken off when every line is one. */
export function toggleListItem(text: string, start: number, end: number, sample: string): FieldEdit {
  const first = text.lastIndexOf("\n", start - 1) + 1;
  const stop = end > start && text.charAt(end - 1) === "\n" ? end - 1 : end;
  const next = text.indexOf("\n", stop);
  const last = next < 0 ? text.length : next;
  const lines = text.slice(first, last).split("\n");
  const bullet = /^(\s*)[-*+]\s+/;
  const filled = lines.filter((line) => line.trim());
  const remove = filled.length > 0 && filled.every((line) => bullet.test(line));
  const changed = lines.map((line) => {
    if (remove) { return line.replace(bullet, "$1"); }
    if (bullet.test(line)) { return line; }
    return line.trim() || lines.length > 1 ? "- " + line : "- " + sample;
  });
  const block = changed.join("\n");
  return { text: text.slice(0, first) + block + text.slice(last), start: first, end: first + block.length };
}

/** A link around the selection, or its text alone again when the selection is a link. */
export function toggleLink(text: string, start: number, end: number, sample: string): FieldEdit {
  const selected = text.slice(start, end);
  const link = /^\[([^\]]*)\]\([^)]*\)$/.exec(selected);
  if (link) {
    return { text: text.slice(0, start) + link[1] + text.slice(end), start, end: start + link[1].length };
  }
  const label = selected || sample;
  const url = "https://example.com";
  const written = "[" + label + "](" + url + ")";
  return {
    text: text.slice(0, start) + written + text.slice(end),
    start: start + label.length + 3, end: start + label.length + 3 + url.length,
  };
}

/** Plain text for a Markdown document: every character Markdown could read as markup is
 *  escaped, so a namespace like `Vendor::Project` or a kind name shows exactly as written. */
export function escapeMarkdown(text: string): string {
  return text.replace(/[\\`*_{}\[\]()#+\-.!|<>~]/g, (ch) => `\\${ch}`);
}

export function renderDocMarkdown(source: string): string {
  const escape = (s: string): string => s.replace(/&/g, "&amp;").replace(/</g, "&lt;")
    .replace(/>/g, "&gt;").replace(/"/g, "&quot;").replace(/'/g, "&#39;");
  const inline = (line: string): string => {
    const pieces = line.split(/(`[^`\n]*`|\[[^\]\n]+\]\([^)\n]+\)|\*\*[^*\n]+\*\*|\*[^*\n]+\*)/g);
    return pieces.map((piece) => {
      if (piece.startsWith("`") && piece.endsWith("`") && piece.length >= 2) {
        return "<code>" + escape(piece.slice(1, -1)) + "</code>";
      }
      const link = /^\[([^\]]+)\]\(([^)]+)\)$/.exec(piece);
      if (link) {
        let safe = false;
        try {
          const url = new URL(link[2]);
          safe = ["https:", "http:", "mailto:"].includes(url.protocol);
        } catch { /* Keep an invalid URL as plain text. */ }
        return safe
          ? '<a href="' + escape(link[2]) + '" rel="noopener noreferrer">' + escape(link[1]) + "</a>"
          : escape(piece);
      }
      if (piece.startsWith("**") && piece.endsWith("**") && piece.length >= 4) {
        return "<strong>" + escape(piece.slice(2, -2)) + "</strong>";
      }
      if (piece.startsWith("*") && piece.endsWith("*") && piece.length >= 2) {
        return "<em>" + escape(piece.slice(1, -1)) + "</em>";
      }
      return escape(piece);
    }).join("");
  };
  const out: string[] = [];
  const lines = source.replace(/\r\n?/g, "\n").split("\n");
  let list: "ul" | "ol" | null = null;
  let fenced = false;
  const closeList = (): void => { if (list) { out.push("</" + list + ">"); list = null; } };
  for (const line of lines) {
    if (/^\s*```/.test(line)) {
      closeList();
      if (fenced) { out.push("</code></pre>"); } else { out.push("<pre><code>"); }
      fenced = !fenced;
      continue;
    }
    if (fenced) { out.push(escape(line) + "\n"); continue; }
    if (!line.trim()) { closeList(); continue; }
    const heading = /^(#{1,6})\s+(.+)$/.exec(line);
    if (heading) {
      closeList();
      const level = heading[1].length;
      out.push("<h" + level + ">" + inline(heading[2]) + "</h" + level + ">");
      continue;
    }
    const bullet = /^\s*[-*+]\s+(.+)$/.exec(line);
    const ordered = /^\s*\d+\.\s+(.+)$/.exec(line);
    if (bullet || ordered) {
      const kind = bullet ? "ul" : "ol";
      if (list !== kind) { closeList(); out.push("<" + kind + ">"); list = kind; }
      out.push("<li>" + inline((bullet || ordered)![1]) + "</li>");
      continue;
    }
    closeList();
    out.push("<p>" + inline(line) + "</p>");
  }
  closeList();
  if (fenced) { out.push("</code></pre>"); }
  return out.join("");
}
