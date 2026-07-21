// Синхронизация страницы расширения на сайте документации с README маркетплейса.
//
// Источник истины — editors/vscode/README.md (+ .ru.md), тот же файл, что публикуется
// в VS Code Marketplace. Здесь он превращается в docs/vscode.md (+ .ru.md): снимаем
// ведущий заголовок H1 и строку ручного переключателя языка (и то, и другое на сайте
// даёт сам Blume), добавляем frontmatter (title/description/sidebar). Тело — как есть:
// картинки и ссылки в README абсолютные, так что переносить нечего.
//
// Запуск: `npm run sync:docs` (также выполняется автоматически перед `npm run build`
// и `npm run dev`, а в CI — отдельным шагом перед `npx blume build`). После правки
// editors/vscode/README*.md перегенерируйте страницу этим скриптом и закоммитьте.
import { readFileSync, writeFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";

const root = join(dirname(fileURLToPath(import.meta.url)), "..");

const pages = [
  {
    src: "editors/vscode/README.md",
    dest: "docs/vscode.md",
    title: "XBSL for VS Code",
    description:
      "The VS Code extension for 1C:Element: syntax highlighting, live linting with Quick Fix, the visual form designer, the metadata explorer, and project-wide navigation – all on the xbsl engine.",
    sidebarLabel: "VS Code extension",
    order: 5,
    note: (src) =>
      `<!-- Generated from ${src}; do not edit by hand.\n` +
      `     Edit ${src} and run: npm run sync:docs -->\n`,
  },
  {
    src: "editors/vscode/README.ru.md",
    dest: "docs/vscode.ru.md",
    title: "XBSL для VS Code",
    description:
      "Расширение VS Code для 1С:Элемент: подсветка синтаксиса, линтинг на лету с Quick Fix, визуальный конструктор форм, обозреватель метаданных и навигация по проекту – всё на движке xbsl.",
    sidebarLabel: "Расширение VS Code",
    order: 5,
    note: (src) =>
      `<!-- Сгенерировано из ${src} – не редактируйте вручную.\n` +
      `     Правьте ${src} и выполните: npm run sync:docs -->\n`,
  },
];

// Строка ручного переключателя вида "**English** · [Русский](…)" или
// "[English](…) · **Русский**" — на сайте её заменяет встроенный переключатель Blume.
const isSwitcherLine = (line) =>
  /Русский/.test(line) && /(\*\*English\*\*|\[English\]\()/.test(line);

// Относительные пути в README заданы относительно editors/vscode/. На сайте страница
// живёт в docs/, поэтому переписываем их на абсолютные URL репозитория: картинки — на
// raw (для рендера), обычные ссылки — на blob (для просмотра на GitHub). Абсолютные
// (http/https), якоря (#…) и корневые (/…) не трогаем.
const RAW = "https://raw.githubusercontent.com/keyfire/xbsl/main/editors/vscode/";
const BLOB = "https://github.com/keyfire/xbsl/blob/main/editors/vscode/";
const absolutizeLinks = (md) =>
  md
    .replace(/!\[([^\]]*)\]\((?!https?:|\/|#)([^)]+)\)/g, `![$1](${RAW}$2)`)
    .replace(/(?<!!)\[([^\]]*)\]\((?!https?:|\/|#|mailto:)([^)]+)\)/g, `[$1](${BLOB}$2)`);

for (const page of pages) {
  const raw = readFileSync(join(root, page.src), "utf8");
  const lines = raw.split("\n");

  let i = 0;
  if (lines[i]?.startsWith("# ")) i++; // ведущий H1 → уходит в frontmatter title
  // Снять пустые строки и строку переключателя языка сразу под заголовком.
  while (i < lines.length && (lines[i].trim() === "" || isSwitcherLine(lines[i]))) i++;
  const body = absolutizeLinks(lines.slice(i).join("\n").replace(/^\n+/, "").trimEnd());

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
