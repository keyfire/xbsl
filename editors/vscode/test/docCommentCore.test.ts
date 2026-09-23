import * as assert from "assert";
import {
  codePointToUtf16Offset, renderDocMarkdown, utf16ToCodePointOffset,
} from "../src/docCommentCore";

const rendered = renderDocMarkdown("# Heading\n\n**Bold** *italic* `code`\n- one\n- two\n[site](https://example.com)");
assert.ok(rendered.includes("<h1>Heading</h1>"));
assert.ok(rendered.includes("<strong>Bold</strong> <em>italic</em> <code>code</code>"));
assert.ok(rendered.includes("<ul><li>one</li><li>two</li></ul>"));
assert.ok(rendered.includes('<a href="https://example.com"'));

for (const attack of [
  '<script>alert(1)</script>',
  '<img src=x onerror=alert(1)>',
  '[click](javascript:alert(1))',
  '[click](data:text/html,evil)',
  '[click](file:///secret)',
  '[click](vbscript:evil)',
]) {
  const html = renderDocMarkdown(attack);
  assert.ok(!/<script|<img|href="(?:javascript|data|file|vbscript)/i.test(html), html);
}
assert.ok(renderDocMarkdown('[ok](https://example.com/?q="evil"&x=1)').includes("&quot;evil&quot;&amp;x=1"));
const emoji = "A😀B\n  ## text";
assert.strictEqual(utf16ToCodePointOffset(emoji, emoji.indexOf("B")), 2);
assert.strictEqual(codePointToUtf16Offset(emoji, 2), emoji.indexOf("B"));
assert.strictEqual(utf16ToCodePointOffset(emoji, emoji.indexOf("##")), 6);
assert.strictEqual(codePointToUtf16Offset(emoji, 6), emoji.indexOf("##"));
console.log("docCommentCore: passed");
