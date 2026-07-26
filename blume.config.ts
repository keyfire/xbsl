// Configuration of the documentation site (Blume, an Astro + Vite engine). Published to
// GitHub Pages from .github/workflows/docs.yml. The content lives in docs/ as Name.md +
// Name.ru.md pairs (the suffix i18n mode, parser: "dot" - the same file layout mkdocs used).
// Check a build locally with: npx blume build.
import { defineConfig } from "blume";

export default defineConfig({
  title: "XBSL (1C:Element)",
  description:
    "A linter with autofixes, an LSP server, documentation search and metadata " +
    "scaffolding for 1C:Element (XBSL) sources, plus a VS Code extension built on " +
    "the same engine.",

  // All site content is in docs/. Two pages are mirrors of sources kept outside docs/: the
  // extension page (docs/vscode.md + .ru.md) mirrors editors/vscode/README.md (the marketplace
  // README), and the changelog page (docs/changelog.md + .ru.md) mirrors CHANGELOG.md (the
  // toolkit's release history). Both are synced by scripts/sync-docs.mjs (npm run sync:docs).
  content: {
    root: "docs",
    // BACKLOG is in .gitignore and lives only on the maintainer's disk - CI never has it,
    // so it could not reach the site anyway. Excluded explicitly all the same: an accidental
    // commit of that file would otherwise publish a working note full of local paths.
    exclude: ["**/_*", "**/.*", "BACKLOG*.md"],
  },

  // The site is served from the /xbsl/ subpath of the shared documentation domain: `base`
  // moves the whole site there and rewrites internal links and assets; `site` is the origin
  // for sitemap/canonical/OG. The domain itself is held by the keyfire.github.io repository.
  deployment: {
    base: "/xbsl",
    site: "https://docs.keyfire.ru",
  },

  // The repository: an "Edit on GitHub" link under every page and a repo icon in the header.
  github: {
    owner: "keyfire",
    repo: "xbsl",
  },

  // The "last modified" date comes from the git history (CI needs fetch-depth: 0).
  lastModified: true,

  // Bilingual: English by default (Name.md at the root of docs/), Russian by the .ru suffix
  // (Name.ru.md). parser: "dot" keeps the original pair layout without moving files. The
  // Russian UI pack (search, "On this page", "Edit on GitHub" and the rest) ships with Blume -
  // only the content is ours to translate.
  i18n: {
    defaultLocale: "en",
    locales: [
      { code: "en", label: "English" },
      { code: "ru", label: "Русский" },
    ],
    parser: "dot",
  },

  // The contributor guide lives on GitHub (it is not a site page), so it is pinned above the
  // sidebar. The VS Code extension is a site page of its own now (docs/vscode.md) and needs no
  // featured entry - it shows up in the sidebar by itself.
  navigation: {
    featured: [
    // The neighbouring tools: reachable from every page, not just the front one. They
    // point at the Russian versions - the receiving site carries a language switcher.
      {
        label: "Elemctl",
        href: "https://docs.keyfire.ru/elemctl/ru/",
        icon: "upload-cloud",
      },
      {
        label: "EDT-Bridge",
        href: "https://docs.keyfire.ru/edt-bridge/ru/",
        icon: "plug",
      },
      {
        label: "Contributing",
        href: "https://github.com/keyfire/xbsl/blob/main/CONTRIBUTING.md",
        icon: "git-pull-request",
      },
    ],
  },

  // Indigo - the accent the previous Material-themed site used.
  theme: {
    accent: "indigo",
  },
});
