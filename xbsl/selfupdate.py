"""Safe update of an installed xbsl by unpacking the wheel (`xbsl self-update`).

A regular `pip install --upgrade` on Windows breaks the installation when one of the
package's exes is held by a running process (typical case: `xbsl-lsp.exe` is held by the
VS Code LSP server, `xbsl-mcp.exe` - by an agent's MCP session): pip cannot overwrite the
entry point, fails with WinError 32 and leaves the package half-removed. This command
updates ONLY the contents of site-packages (`.py` files are not locked, unlike `.exe`),
and the stubs in Scripts will invoke the new code on the next launch. Busy exes are left
alone.

The wheel ships both the xbsl package and the xbsllint alias package - both are removed
and replaced. The dist-info of the transitional `xbsllint` METApackage (a separate,
code-free distribution) is not touched. Only xbsl itself is updated, not its extras
([mcp]/[lsp] and their dependencies).

Download and unpack with the standard library (urllib + zipfile) - the command must work
even in an installation without extras.
"""

from __future__ import annotations

import json
import shutil
import urllib.error
import urllib.request
import zipfile
from io import BytesIO
from pathlib import Path

from xbsl import __version__

PYPI_VERSION = "https://pypi.org/pypi/xbsl/{version}/json"
PYPI_LATEST = "https://pypi.org/pypi/xbsl/json"

# What belongs to the xbsl wheel in site-packages. The xbsl-*.dist-info pattern will not
# touch the metapackage's xbsllint-*.dist-info: glob matches the prefix literally.
_OWNED_PATTERNS = ("xbsl", "xbsllint", "xbsl-*.dist-info")


class SelfUpdateError(RuntimeError):
    """Self-update error; the text is shown to the user as is."""


def _site_packages() -> Path:
    """Directory the package is installed into (site-packages in a production install)."""
    return Path(__file__).resolve().parent.parent


def _ensure_regular_install(site: Path) -> None:
    """Guard against an editable install: git updates it, and unpacking a wheel would corrupt the repository."""
    if site.name.lower() not in ("site-packages", "dist-packages"):
        raise SelfUpdateError(
            f"пакет импортируется из {site} – это editable-установка из репозитория; "
            "обновляйте её через git (pip install -e не требуется повторно)"
        )


def _fetch_json(url: str) -> dict:
    try:
        with urllib.request.urlopen(url, timeout=30) as resp:
            return json.load(resp)
    except urllib.error.HTTPError as error:
        if error.code == 404:
            raise SelfUpdateError("версия не найдена на PyPI") from error
        raise SelfUpdateError(f"PyPI ответил {error.code}") from error
    except OSError as error:
        raise SelfUpdateError(f"не удалось обратиться к PyPI: {error}") from error


def _wheel_url(version: str | None) -> tuple[str, str]:
    """URL and exact version of the py3-none-any wheel from PyPI (latest or the given one)."""
    data = _fetch_json(PYPI_VERSION.format(version=version) if version else PYPI_LATEST)
    resolved = data["info"]["version"]
    for entry in data["urls"]:
        if entry["filename"].endswith("-py3-none-any.whl"):
            return entry["url"], resolved
    raise SelfUpdateError(f"на PyPI нет wheel для xbsl {resolved}")


def self_update(version: str | None = None, log=print) -> tuple[str, str]:
    """Update xbsl in site-packages by unpacking the wheel. Return (old, new)."""
    site = _site_packages()
    _ensure_regular_install(site)

    url, target = _wheel_url(version)
    if version is None and target == __version__:
        log(f"уже актуально: xbsl {__version__}")
        return __version__, __version__

    log(f"скачиваю xbsl {target} с PyPI...")
    try:
        with urllib.request.urlopen(url, timeout=60) as resp:
            blob = resp.read()
    except OSError as error:
        raise SelfUpdateError(f"не удалось скачать колесо: {error}") from error

    # Remove the package, the alias and dist-info; exes in Scripts are left alone (they may be busy).
    for pattern in _OWNED_PATTERNS:
        for path in site.glob(pattern):
            if path.is_dir():
                shutil.rmtree(path, ignore_errors=True)

    log(f"распаковываю в {site}...")
    with zipfile.ZipFile(BytesIO(blob)) as archive:
        archive.extractall(site)

    _update_pipx_metadata(site, target, log)
    log(
        f"готово: xbsl {__version__} -> {target}. Перезапустите долгоживущие процессы "
        "(LSP-сервер VS Code, MCP-сессии) – они продолжают работать на старом коде."
    )
    return __version__, target


def _update_pipx_metadata(site: Path, version: str, log) -> None:
    """Fix package_version in pipx_metadata.json (otherwise pipx list shows the old version)."""
    meta = site.parent.parent / "pipx_metadata.json"  # <venv>/Lib/site-packages -> <venv>
    if not meta.is_file():
        return
    try:
        data = json.loads(meta.read_text(encoding="utf-8"))
        main = data.get("main_package") or {}
        if main.get("package") == "xbsl":
            main["package_version"] = version
            meta.write_text(json.dumps(data, indent=4), encoding="utf-8")
            log("обновлён pipx_metadata.json")
    except (OSError, ValueError):
        pass
