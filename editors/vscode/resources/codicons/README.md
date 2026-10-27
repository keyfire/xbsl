# codicons

The icon font of VS Code, vendored from the [`@vscode/codicons`](https://github.com/microsoft/vscode-codicons)
package (version **0.0.45**): `codicon.css` and `codicon.ttf`, unchanged.

The form designer displays its structure and data trees in a webview, which does not inherit
the editor's icon font. A `$(name)` reference works in a TreeItem, but not in HTML. These files
provide the same icon for a component type in the panel and palette (see
`src/componentIconsCore.ts`) without an extra build step or dependency.

Licenses: the icons are CC BY 4.0 (`LICENSE-ICONS`), the accompanying code is MIT
(`LICENSE-CODE`); the attribution is in the repository's `NOTICE`.

To update: take `dist/codicon.css` and `dist/codicon.ttf` from a fresh package, replace both files
and bump the version above. `test/componentIconsCore.test.ts` reads the class names out of the
stylesheet, so an icon id that disappeared upstream fails the test instead of rendering as an
empty glyph.
