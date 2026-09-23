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
