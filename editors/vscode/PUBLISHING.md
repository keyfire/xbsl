# Publishing the XBSL extension

The extension is published through three channels: the VS Code Marketplace, Open VSX (VSCodium,
Cursor, Windsurf, Gitpod) and a GitHub Release carrying the `.vsix`. The CI workflow
[`.github/workflows/vscode-publish.yml`](../../.github/workflows/vscode-publish.yml) does all
three on a `vscode-v*` tag. The commands below also support manual publishing.

The `publisher` in `package.json` is `keyfire`, and it must match your Marketplace publisher and
your Open VSX namespace. For a different id, change it in `package.json` and nowhere else.

## One-time setup

### VS Code Marketplace
1. Create a publisher at <https://marketplace.visualstudio.com/manage>, signing in with the
   Microsoft or Azure account that owns it. The publisher id must equal `keyfire`.
2. Under **Trusted Publishing**, create a policy with these settings.

   | Field | Value |
   | --- | --- |
   | Policy name | `XBSL VS Code release` |
   | Provider | GitHub Actions |
   | Repository owner | `keyfire` |
   | Repository | `xbsl` |
   | Workflow | `vscode-publish.yml` |
   | Environment | Leave empty |

   GitHub Actions requests a short-lived Marketplace credential through OIDC. The workflow
   needs `id-token: write` and an OIDC-capable version of `vsce`. See the
   [VS Code publishing guide](https://code.visualstudio.com/api/working-with-extensions/publishing-extension#publish-with-github-actions-and-trusted-publishing).

### Open VSX
1. Sign in at <https://open-vsx.org> with GitHub, then create an access token (Settings → Access Tokens).
2. Sign the publisher agreement once, and create the namespace:
   ```sh
   npx ovsx create-namespace keyfire -p <OVSX_PAT>
   ```
3. Keep the token as `OVSX_PAT`.

### GitHub Release
Nothing to set up. CI uses the built-in `GITHUB_TOKEN`.

## Publishing through CI

1. For Open VSX, set `OVSX_PAT` in **Settings → Secrets and variables → Actions**.
2. Bump `version` in `editors/vscode/package.json` and update the extension changelogs.
3. Commit, then tag and push:
   ```sh
   git tag vscode-v1.0.0
   git push origin vscode-v1.0.0
   ```
   A tag that matches the manifest version builds one `.vsix` for the GitHub Release and
   both registries. A manual workflow run on a branch checks packaging without publishing.

## Publishing by hand

From `editors/vscode`:

```sh
npm install
npm run package                                   # -> xbsl-vscode.vsix

# VS Code Marketplace
# Upload xbsl-vscode.vsix in https://marketplace.visualstudio.com/manage/publishers/keyfire.

# Open VSX
npx ovsx publish xbsl-vscode.vsix -p <OVSX_PAT>

# GitHub Release (needs the gh CLI, run from the repo root)
gh release create vscode-v1.0.0 editors/vscode/xbsl-vscode.vsix -t "XBSL extension 1.0.0"
```

## Install (any channel)

```sh
# From the Marketplace / Open VSX, by name:
code --install-extension keyfire.xbsl

# Or straight from a .vsix file:
code --install-extension xbsl-vscode.vsix
```

## After publishing

- Marketplace listing: <https://marketplace.visualstudio.com/items?itemName=keyfire.xbsl>
- Open VSX listing: <https://open-vsx.org/extension/keyfire/xbsl>

Check that the icon, README and categories render, and that a fresh
`code --install-extension keyfire.xbsl` pulls the new version.
