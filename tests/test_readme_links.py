"""The links of the published README files point at something that exists.

The README of the repository is also the page the Marketplace, Open VSX and PyPI show, so
its links have to be absolute; relative ones would resolve against the store's own host.
Rewriting a batch of them by hand is where they break: a docs reshuffle once left thirteen
links per language reading `[text]((https://...)` - visibly broken on every store page, and
nothing failed until a reader reported it.

The check is deliberately structural (does the target file exist, does the anchor exist),
not a network fetch: it has to run in CI without a network.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
READMES = ("README.md", "README.ru.md")
_BLOB = "https://github.com/keyfire/xbsl/blob/main/"
_LINK_RE = re.compile(r"\[([^\]]{1,80})\]\(([^)\s]+)\)")
_HEADING_RE = re.compile(r"^#{1,6}\s+(.*?)\s*$", re.MULTILINE)


def _anchors(text: str) -> set[str]:
    """GitHub's heading slugs: lowercase, punctuation dropped, spaces to hyphens."""
    out = set()
    for title in _HEADING_RE.findall(text):
        slug = re.sub(r"[^\w\s-]", "", title.lower(), flags=re.UNICODE)
        out.add(slug.strip().replace(" ", "-"))
    return out


@pytest.mark.parametrize("name", READMES)
def test_no_doubled_parenthesis(name: str):
    text = (ROOT / name).read_text(encoding="utf-8")
    assert "]((" not in text, f"{name}: ссылка с лишней открывающей скобкой"


@pytest.mark.parametrize("name", READMES)
def test_repository_links_resolve(name: str):
    text = (ROOT / name).read_text(encoding="utf-8")
    broken: list[str] = []
    for label, url in _LINK_RE.findall(text):
        if not url.startswith(_BLOB):
            continue
        path, _, anchor = url[len(_BLOB):].partition("#")
        target = ROOT / path
        if not target.exists():
            broken.append(f"[{label}] -> {path}: файла нет")
        elif anchor and anchor not in _anchors(target.read_text(encoding="utf-8")):
            broken.append(f"[{label}] -> {path}#{anchor}: якоря нет")
    assert not broken, f"{name}: " + "; ".join(broken)


@pytest.mark.parametrize("name", READMES)
def test_docs_links_are_absolute(name: str):
    """A relative docs link would break on the store pages - they render the file alone."""
    text = (ROOT / name).read_text(encoding="utf-8")
    relative = [
        url for _, url in _LINK_RE.findall(text)
        if url.startswith(("docs/", "./docs/", "editors/", "./editors/"))
    ]
    assert not relative, f"{name}: относительные ссылки {relative}"
