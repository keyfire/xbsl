"""Guard: the machine-translation feature is named where a reader would look for it.

Both language pages of the translation guide must mention the three environment variables the
machine-translation providers actually read (see `xbsl/translation/machine/yandex.py` and
`google.py`) - the names became per-service (`XBSL_TRANSLATE_YANDEX_KEY`,
`XBSL_TRANSLATE_YANDEX_FOLDER`, `XBSL_TRANSLATE_GOOGLE_KEY`) because a pair of shared names
could never express "only Yandex is configured" (its requirement is strictly wider than
Google's) or "both services have keys at once". Both pages must also say plainly what leaves the
machine for the external service - the whole point of naming the feature at all. And the home
page must point at the translation guide - the gap this task exists to close.
"""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def test_both_pages_name_the_environment_variables():
    for name in ("docs/translation.md", "docs/translation.ru.md"):
        text = (ROOT / name).read_text(encoding="utf-8")
        assert "XBSL_TRANSLATE_YANDEX_KEY" in text, name
        assert "XBSL_TRANSLATE_YANDEX_FOLDER" in text, name
        assert "XBSL_TRANSLATE_GOOGLE_KEY" in text, name


def test_both_pages_say_what_leaves_the_machine():
    ru = (ROOT / "docs/translation.ru.md").read_text(encoding="utf-8")
    en = (ROOT / "docs/translation.md").read_text(encoding="utf-8")
    assert "уходит" in ru
    assert "sent" in en


def test_home_page_points_at_the_translation_guide():
    """The page existed but the home page never named it - the reason this task exists."""
    for name in ("docs/index.md", "docs/index.ru.md"):
        text = (ROOT / name).read_text(encoding="utf-8")
        assert "/translation" in text, name
