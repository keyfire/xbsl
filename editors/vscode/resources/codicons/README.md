# codicons

The icon font of VS Code, vendored from the [`@vscode/codicons`](https://github.com/microsoft/vscode-codicons)
package (version **0.0.45**): `codicon.css` and `codicon.ttf`, unchanged.

Why it is here. The form designer paints its structure and data trees inside a webview, and a
webview does not inherit the editor's own icon font - a `$(name)` reference works in a TreeItem,
not in HTML. Vendoring the two files keeps the SAME icon for a component type in both the panel
and the palette (see `src/componentIconsCore.ts`) without adding a build step or a dependency.

Licenses: the icons are CC BY 4.0 (`LICENSE-ICONS`), the accompanying code is MIT
(`LICENSE-CODE`); the attribution is in the repository's `NOTICE`.

To update: take `dist/codicon.css` and `dist/codicon.ttf` from a fresh package, replace both files
and bump the version above. `test/componentIconsCore.test.ts` reads the class names out of the
stylesheet, so an icon id that disappeared upstream fails the test instead of rendering as an
empty glyph.
