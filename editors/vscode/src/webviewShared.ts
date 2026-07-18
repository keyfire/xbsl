// Shared helpers of the extension's webviews: HTML escaping, script nonces, the standard
// strict CSP meta tag and SAFE inline JSON for <script> blocks. New panels must use this
// module instead of growing per-panel copies (the older panels - formPreview, templatesPanel -
// are refactored onto it separately; see docs/DESIGNER.md, stage 3).
//
// Why inlineJson exists: raw JSON.stringify output pasted into a <script> block is NOT safe -
// a string value containing "</script>" terminates the block early and the rest of the data
// becomes markup (templatesPanel.ts carried exactly that trap with template bodies). Escaping
// every "<" as its \u-escape keeps the payload semantically identical JSON while making it inert
// inside HTML. U+2028/U+2029 are escaped too: they are valid JSON but illegal inside JS
// string literals, which is what an inline <script> ultimately is.

const NONCE_ALPHABET = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789";

export function escapeHtml(s: string): string {
  return s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");
}

export function makeNonce(): string {
  let s = "";
  for (let i = 0; i < 24; i++) {
    s += NONCE_ALPHABET.charAt(Math.floor(Math.random() * NONCE_ALPHABET.length));
  }
  return s;
}

// The strict CSP shared by the extension's webviews: no default sources, inline styles
// (the panels style themselves through --vscode-* variables), scripts only with the nonce.
export function cspMeta(nonce: string): string {
  return (
    '<meta http-equiv="Content-Security-Policy" ' +
    `content="default-src 'none'; style-src 'unsafe-inline'; script-src 'nonce-${nonce}';">`
  );
}

// JSON safe for inlining into a <script> block: "<" cannot open a tag, line/paragraph
// separators cannot break the literal. The result parses to exactly the same value.
export function inlineJson(value: unknown): string {
  return (JSON.stringify(value) ?? "null")
    .replace(/</g, "\\u003c")
    .replace(/\u2028/g, "\\u2028")
    .replace(/\u2029/g, "\\u2029");
}
