# Publishing the XBSL extension

The extension goes out through three channels: the VS Code Marketplace, Open VSX (VSCodium,
Cursor, Windsurf, Gitpod) and a GitHub Release carrying the `.vsix`. The CI workflow
[`.github/workflows/vscode-publish.yml`](../../.github/workflows/vscode-publish.yml) does all
three on a `vscode-v*` tag. The manual commands below do the same by hand.

The `publisher` in `package.json` is `keyfire`, and it must match your Marketplace publisher and
your Open VSX namespace. For a different id, change it in `package.json` and nowhere else.

## One-time setup

### VS Code Marketplace
1. Create a publisher at <https://marketplace.visualstudio.com/manage>, signing in with the
   Microsoft or Azure account that owns it. The publisher id must equal `keyfire`.
2. Create an Azure DevOps Personal Access Token: <https://dev.azure.com> → User settings → Personal access
   tokens → New. Organization: **All accessible organizations**; Scope: **Marketplace → Manage**.
3. Keep the token as `VSCE_PAT`.

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

This is the usual way.

1. Add the tokens as repository secrets (Settings → Secrets and variables → Actions): `VSCE_PAT`,
   `OVSX_PAT`. Leave one out to skip that marketplace; the GitHub Release still happens.
2. Bump `version` in `editors/vscode/package.json` and update `CHANGELOG.md`.
3. Commit, then tag and push:
   ```sh
   git tag vscode-v0.1.0
   git push origin vscode-v0.1.0
   ```
   The workflow builds the `.vsix`, attaches it to a GitHub Release, and publishes to whichever
   marketplaces have their secrets in place.

## Publishing by hand

From `editors/vscode`:

```sh
npm install
npm run package                                   # -> xbsl-vscode.vsix

# VS Code Marketplace
npx @vscode/vsce publish -p <VSCE_PAT>            # or: vsce login keyfire && vsce publish

# Open VSX
npx ovsx publish xbsl-vscode.vsix -p <OVSX_PAT>

# GitHub Release (needs the gh CLI, run from the repo root)
gh release create vscode-v0.1.0 editors/vscode/xbsl-vscode.vsix -t "XBSL extension 0.1.0"
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
