// Keeps the mirrored pages of the documentation site in sync with their source files.
//
// Two sources live outside docs/ and are the source of truth for a site page each:
//   * editors/vscode/README.md (+ .ru.md) - the very file published to the VS Code Marketplace,
//     mirrored to docs/vscode.md (+ .ru.md);
//   * CHANGELOG.md (+ .ru.md) at the repository root - the toolkit's release history shown on
//     GitHub and PyPI, mirrored to docs/changelog.md (+ .ru.md).
//
// In each case the leading H1 and the hand-written language switcher line are dropped (Blume
// provides both), frontmatter (title/description/sidebar) is added, and relative links are
// rewritten to absolute repository URLs (relative to the source file's own directory).
//
// Run: `npm run sync:docs` (also runs automatically before `npm run build` and `npm run dev`,
// and in CI as its own step before `npx blume build`). After editing a source file regenerate
// its page with this script and commit it.
import { readFileSync, writeFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";

const root = join(dirname(fileURLToPath(import.meta.url)), "..");

// The "generated, do not edit" banner - one per locale, shared by every mirrored page.
const enNote = (src) =>
  `<!-- Generated from ${src}; do not edit by hand.\n` +
  `     Edit ${src} and run: npm run sync:docs -->\n`;
const ruNote = (src) =>
  `<!-- Сгенерировано из ${src} – не редактируйте вручную.\n` +
  `     Правьте ${src} и выполните: npm run sync:docs -->\n`;

const pages = [
  {
    src: "editors/vscode/README.md",
    dest: "docs/vscode.md",
    dir: "editors/vscode/",
    title: "XBSL for VS Code",
    description:
      "The VS Code extension for 1C:Element: syntax highlighting, live linting with Quick Fix, the visual form designer, the metadata explorer, and project-wide navigation – all on the xbsl engine.",
    sidebarLabel: "VS Code extension",
    order: 5,
    note: enNote,
  },
  {
    src: "editors/vscode/README.ru.md",
    dest: "docs/vscode.ru.md",
    dir: "editors/vscode/",
    title: "XBSL для VS Code",
    description:
      "Расширение VS Code для 1С:Элемент: подсветка синтаксиса, линтинг на лету с Quick Fix, визуальный конструктор форм, обозреватель метаданных и навигация по проекту – всё на движке xbsl.",
    sidebarLabel: "Расширение VS Code",
    order: 5,
    note: ruNote,
  },
  {
    src: "CHANGELOG.md",
    dest: "docs/changelog.md",
    dir: "",
    title: "Changelog",
    description:
      "What changed in the xbsl toolkit from release to release, grouped by day.",
    sidebarLabel: "Changelog",
    order: 8,
    note: enNote,
  },
  {
    src: "CHANGELOG.ru.md",
    dest: "docs/changelog.ru.md",
    dir: "",
    title: "История изменений",
    description:
      "Что менялось в инструментарии xbsl от версии к версии, с разбивкой по дням.",
    sidebarLabel: "История изменений",
    order: 8,
    note: ruNote,
  },
];

// The hand-written switcher line, "**English** · [Русский](...)" or
// "[English](...) · **Русский**" - on the site Blume's own switcher replaces it.
const isSwitcherLine = (line) =>
  /Русский/.test(line) && /(\*\*English\*\*|\[English\]\()/.test(line);

// Relative paths in a source file are relative to that file's directory (`dir`). On the site the
// page lives in docs/, so they are rewritten to absolute repository URLs: images to raw (so they
// render), ordinary links to blob (so they open on GitHub). Absolute (http/https), anchors (#...)
// and root-relative (/...) paths are left alone.
const RAW = "https://raw.githubusercontent.com/keyfire/xbsl/main/";
const BLOB = "https://github.com/keyfire/xbsl/blob/main/";
const absolutizeLinks = (md, dir) =>
  md
    .replace(/!\[([^\]]*)\]\((?!https?:|\/|#)([^)]+)\)/g, `![$1](${RAW}${dir}$2)`)
    .replace(/(?<!!)\[([^\]]*)\]\((?!https?:|\/|#|mailto:)([^)]+)\)/g, `[$1](${BLOB}${dir}$2)`);

for (const page of pages) {
  const raw = readFileSync(join(root, page.src), "utf8");
  const lines = raw.split("\n");

  let i = 0;
  if (lines[i]?.startsWith("# ")) i++; // the leading H1 becomes the frontmatter title
  // Drop blank lines and the language-switcher line right under the heading.
  while (i < lines.length && (lines[i].trim() === "" || isSwitcherLine(lines[i]))) i++;
  const body = absolutizeLinks(lines.slice(i).join("\n").replace(/^\n+/, "").trimEnd(), page.dir);

  const frontmatter =
    "---\n" +
    `title: ${JSON.stringify(page.title)}\n` +
    `description: ${JSON.stringify(page.description)}\n` +
    "sidebar:\n" +
    `  label: ${JSON.stringify(page.sidebarLabel)}\n` +
    `  order: ${page.order}\n` +
    "---\n";

  const note = page.note(page.src);

  writeFileSync(join(root, page.dest), `${frontmatter}\n${note}\n${body}\n`, "utf8");
  console.log(`synced ${page.src} -> ${page.dest}`);
}
