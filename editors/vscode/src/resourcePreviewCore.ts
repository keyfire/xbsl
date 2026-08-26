// The resource preview page (pure - no vscode - so plain node tests cover it; the panel
// wiring lives in metadataTree.ts).
//
// Why a preview of our own: the project's icons are `fill="currentColor"` - they take the
// text color of wherever they stand. A standalone image viewer renders them BLACK, and on a
// dark editor canvas that reads as "the picture does not show". Inlining the svg into a
// webview lets currentColor inherit the editor foreground, so the icon is visible in both
// themes; an <img> would isolate the color context back to black.

// The svg markup is inlined AS IS - dropping content silently would misrepresent the file.
// What keeps a hostile fragment inert is the policy: nothing may load or run, inline styles
// are the only allowance.
const POLICY = "default-src 'none'; style-src 'unsafe-inline'";

export function resourcePreviewHtml(svgText: string, key: string, colorNote: string): string {
  return `<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<meta http-equiv="Content-Security-Policy" content="${POLICY}">
<style>
  html, body { height: 100%; margin: 0; }
  body {
    display: flex; flex-direction: column; align-items: center; justify-content: center;
    gap: 12px;
    color: var(--vscode-editor-foreground);
    background: var(--vscode-editor-background);
    font-family: var(--vscode-font-family);
  }
  /* The checkerboard shows transparency the way image viewers do. */
  .frame {
    display: flex; align-items: center; justify-content: center;
    padding: 24px; border-radius: 6px;
    background:
      repeating-conic-gradient(rgba(128, 128, 128, 0.18) 0% 25%, transparent 0% 50%)
      0 0 / 16px 16px;
  }
  /* Icons carry inline width/height of 16-24 px - without !important the preview would
     stay a thumbnail. The viewBox keeps the proportions when we scale up. */
  .frame svg {
    width: auto !important; height: auto !important;
    min-width: 96px; min-height: 96px;
    max-width: 70vw; max-height: 60vh;
  }
  .caption { font-size: 13px; opacity: 0.85; }
  .note { font-size: 11px; opacity: 0.6; }
</style>
</head>
<body>
  <div class="frame">${svgText}</div>
  <div class="caption">${escapeHtml(key)}</div>
  ${colorNote ? `<div class="note">${escapeHtml(colorNote)}</div>` : ""}
</body>
</html>`;
}

function escapeHtml(text: string): string {
  return text
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}
