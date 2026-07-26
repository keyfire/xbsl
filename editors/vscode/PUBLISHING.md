# Publishing the XBSL extension

Three channels: **VS Code Marketplace**, **Open VSX** (VSCodium / Cursor / Windsurf / Gitpod) and a
**GitHub Release** with the `.vsix`. The CI workflow
[`.github/workflows/vscode-publish.yml`](../../.github/workflows/vscode-publish.yml) does all three on a
`vscode-v*` tag; the manual commands below do the same by hand.

The `publisher` in `package.json` is `keyfire` – it must match your Marketplace publisher and your Open
VSX namespace. Change it in one place (`package.json`) if you use a different id.

## One-time setup

### VS Code Marketplace
1. Create a publisher at <https://marketplace.visualstudio.com/manage> (sign in with the Microsoft/Azure
   account that owns it). The publisher **ID** must equal `keyfire`.
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
Nothing to set up – CI uses the built-in `GITHUB_TOKEN`.

## Publish via CI (recommended)

1. Add the tokens as repository secrets (Settings → Secrets and variables → Actions): `VSCE_PAT`,
   `OVSX_PAT`. Omit either one to skip that marketplace – the GitHub Release still happens.
2. Bump `version` in `editors/vscode/package.json` and update `CHANGELOG.md`.
3. Commit, then tag and push:
   ```sh
   git tag vscode-v0.1.0
   git push origin vscode-v0.1.0
   ```
   The workflow builds the `.vsix`, attaches it to a GitHub Release, and publishes to both marketplaces
   (whichever secrets are present).

## Publish manually

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
