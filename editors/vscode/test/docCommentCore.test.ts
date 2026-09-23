import * as assert from "assert";
import {
  codePointToUtf16Offset, cycleHeading, escapeMarkdown, renderDocMarkdown, toggleInline,
  toggleLink, toggleListItem, utf16ToCodePointOffset,
} from "../src/docCommentCore";

// The toolbar buttons: a second press takes the markup off instead of adding more.
const cut = (edit: { text: string; start: number; end: number }): string =>
  edit.text.slice(0, edit.start) + "[" + edit.text.slice(edit.start, edit.end) + "]" + edit.text.slice(edit.end);
// A double-clicked word brings its space along; the space stays outside the markers.
assert.strictEqual(cut(toggleInline("Итог загрузки", 0, 5, "**", "text")), "**[Итог]** загрузки");
assert.strictEqual(cut(toggleInline("**Итог** загрузки", 2, 6, "**", "text")), "[Итог] загрузки");
assert.strictEqual(cut(toggleInline("**Итог** загрузки", 0, 8, "**", "text")), "[Итог] загрузки");
assert.strictEqual(cut(toggleInline("а *форма* б", 3, 8, "*", "text")), "а [форма] б");
// Italic inside bold gives three stars, and each button takes its own part off again.
assert.strictEqual(cut(toggleInline("**Итог**", 2, 6, "*", "text")), "***[Итог]***");
assert.strictEqual(cut(toggleInline("***Итог***", 3, 7, "*", "text")), "**[Итог]**");
assert.strictEqual(cut(toggleInline("***Итог***", 3, 7, "**", "text")), "*[Итог]*");
// Italic does not take a bold marker for its own.
assert.strictEqual(cut(toggleInline("**Итог**", 2, 6, "*", "text")), "***[Итог]***");
assert.strictEqual(cut(toggleInline("", 0, 0, "**", "text")), "**[text]**");
assert.strictEqual(cut(toggleInline("a `x` b", 3, 4, "`", "code")), "a [x] b");
// The heading goes one level up per press, and the last level takes it off.
let heading = { text: "Итог", start: 1, end: 1 };
const levels: string[] = [];
for (let i = 0; i < 7; i++) {
  heading = cycleHeading(heading.text, heading.start, heading.end, "Heading");
  levels.push(heading.text);
}
assert.deepStrictEqual(levels, [
  "# Итог", "## Итог", "### Итог", "#### Итог", "##### Итог", "###### Итог", "Итог",
]);
assert.strictEqual(cut(cycleHeading("a\n\nb", 2, 2, "Heading")), "a\n# [Heading]\nb");
assert.strictEqual(toggleListItem("a\nb", 0, 3, "Item").text, "- a\n- b");
assert.strictEqual(toggleListItem("- a\n- b", 0, 7, "Item").text, "a\nb");
assert.strictEqual(toggleListItem("- a\nb", 0, 5, "Item").text, "- a\n- b");
// A new link selects its address, ready to be typed over.
assert.strictEqual(cut(toggleLink("site", 0, 4, "link")), "[site]([https://example.com])");
assert.strictEqual(toggleLink("[site](https://x.org)", 0, 21, "link").text, "site");

// A namespace and a kind shown in a Markdown tooltip keep every character as written.
assert.strictEqual(escapeMarkdown("e1c::Проект::Подсистема"), "e1c::Проект::Подсистема");
assert.strictEqual(escapeMarkdown("*a* _b_ [c](d) #e `f` <g>"),
  "\\*a\\* \\_b\\_ \\[c\\]\\(d\\) \\#e \\`f\\` \\<g\\>");

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
