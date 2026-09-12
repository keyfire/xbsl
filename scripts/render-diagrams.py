#!/usr/bin/env python
"""Render the README diagrams from their SVG sources.

A README cannot carry an SVG: vsce refuses to package one, so the marketplaces get a PNG while
the SVG stays the single source to edit. The site is the other way round - it shows the SVG, and
that one follows the reader's theme through `prefers-color-scheme`.

Which theme a PNG should carry is therefore a decision of its own. Headless Chrome renders with
the system preference, which would make the answer depend on the machine doing the release; the
script instead FORCES the palette by dropping the media query and inlining the requested branch,
so the same command produces the same file anywhere.

    python scripts/render-diagrams.py                     # every diagram, the dark palette
    python scripts/render-diagrams.py --theme light
    python scripts/render-diagrams.py --only debug-how-it-works.svg

Chrome is looked up in the usual install locations, or pass --chrome. The render is 2x for
sharpness, on a transparent canvas, and the result lands next to the source as <name>.png.
"""

from __future__ import annotations

import argparse
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
#: Both folders with diagrams. The root one feeds the README that GitHub and PyPI show, the
#: extension one feeds the Marketplace page. Only the second was rendered here until
#: 12.09.2026, and the README kept a PNG whose box carried a word the SVG no longer had.
IMAGE_DIRS = (ROOT / "images", ROOT / "editors" / "vscode" / "images")

CHROME_CANDIDATES = [
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    "/usr/bin/google-chrome",
    "/usr/bin/chromium",
]

#: The media query holding the dark palette, as written in the sources.
_DARK_BLOCK = re.compile(
    r"@media \(prefers-color-scheme: dark\) \{\s*(:root \{.*?\})\s*\}", re.S
)
_SIZE = re.compile(r'<svg[^>]*?width="(\d+)"[^>]*?height="(\d+)"')


def find_chrome(explicit: str | None) -> str:
    if explicit:
        return explicit
    for candidate in CHROME_CANDIDATES:
        if Path(candidate).exists():
            return candidate
    found = shutil.which("chrome") or shutil.which("chromium") or shutil.which("google-chrome")
    if found:
        return found
    raise SystemExit("Chrome не найден - укажите путь флагом --chrome")


def force_theme(svg: str, theme: str) -> str:
    """Make the requested palette unconditional: a render must not depend on the machine."""
    dark = _DARK_BLOCK.search(svg)
    if not dark:
        raise SystemExit("в схеме нет блока @media (prefers-color-scheme: dark)")
    if theme == "light":
        return _DARK_BLOCK.sub("", svg)          # what is left is the default palette
    # Dark: drop the media query and append its :root after the light one - the later one wins.
    return _DARK_BLOCK.sub("", svg).replace("</style>", dark.group(1) + "\n  </style>", 1)


def render(chrome: str, svg_path: Path, theme: str) -> Path:
    svg = svg_path.read_text(encoding="utf-8")
    size = _SIZE.search(svg)
    if not size:
        raise SystemExit(f"{svg_path.name}: не разобрать width/height")
    width, height = size.group(1), size.group(2)
    out = svg_path.with_suffix(".png")
    with tempfile.TemporaryDirectory() as tmp:
        staged = Path(tmp) / svg_path.name
        staged.write_text(force_theme(svg, theme), encoding="utf-8", newline="")
        subprocess.run(
            [
                chrome, "--headless=new", "--disable-gpu",
                "--force-device-scale-factor=2",
                f"--window-size={width},{height}",
                "--default-background-color=00000000",
                f"--screenshot={out}",
                staged.as_uri(),
            ],
            check=True, capture_output=True, timeout=120,
        )
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--theme", choices=("dark", "light"), default="dark",
                        help="палитра рендера (по умолчанию dark)")
    parser.add_argument("--only", help="имя одного файла .svg в любом из каталогов схем")
    parser.add_argument("--chrome", help="путь к Chrome/Chromium")
    args = parser.parse_args()

    chrome = find_chrome(args.chrome)
    if args.only:
        sources = [folder / args.only for folder in IMAGE_DIRS
                   if (folder / args.only).is_file()]
    else:
        sources = sorted(
            (found for folder in IMAGE_DIRS for found in folder.glob("*.svg")
             if _DARK_BLOCK.search(found.read_text(encoding="utf-8"))),
            key=lambda found: (found.parent.name, found.name),
        )
    if not sources:
        print("нечего рендерить: схем с палитрой в переменных не нашлось")
        return 0
    for source in sources:
        out = render(chrome, source, args.theme)
        print(f"{source.relative_to(ROOT).as_posix()} -> {out.name} "
              f"({out.stat().st_size // 1024} КБ, {args.theme})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
