// The resource preview page: an svg is inlined into the webview so `currentColor` inherits
// the editor foreground - a standalone image viewer paints it black, which on a dark canvas
// reads as "the picture does not show".

import * as assert from "assert";
import { resourcePreviewHtml } from "../src/resourcePreviewCore";

const SVG = '<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" '
  + 'style="width: 20px; height: 20px;" fill="currentColor"><text>A</text></svg>';

{
  const html = resourcePreviewHtml(SVG, "Значки/Флаг.svg", "цвет темы редактора");
  // The svg is INLINED (an <img> would isolate currentColor back to black).
  assert.ok(html.includes("<text>A</text>"));
  // Scripts can never run: the policy allows inline styles only.
  assert.ok(html.includes("Content-Security-Policy"));
  assert.ok(html.includes("default-src 'none'"));
  // currentColor follows the theme through the body color.
  assert.ok(html.includes("--vscode-editor-foreground"));
  // The caption names the resource by its addressing key.
  assert.ok(html.includes("Значки/Флаг.svg"));
  assert.ok(html.includes("цвет темы редактора"));
}

// The inline width/height style of an icon (20 px) must not pin the preview to a thumbnail:
// the frame styles override it, so the declaration carries !important.
{
  const html = resourcePreviewHtml(SVG, "a.svg", "");
  assert.ok(/\.frame svg[^}]*!important/.test(html));
}

// A dangerous fragment stays inert: the markup is inlined as is, and the CSP is what keeps
// it from running - the builder must not silently drop content.
{
  const html = resourcePreviewHtml("<svg><script>alert(1)</script></svg>", "b.svg", "");
  assert.ok(html.includes("<script>alert(1)</script>"));
  assert.ok(!/script-src/.test(html));
}

console.log("resourcePreviewCore: ok");
