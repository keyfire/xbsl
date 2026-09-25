"""`self-update` without a version: the latest release is asked of every PyPI source.

Caught live on 24.09.2026: two minutes after 0.118.0 was published the command answered
"already current: xbsl 0.117.0", while `--version 0.118.0` installed the release at once. The
latest version came from the simple index alone, and the index still listed the previous
release. Both listings - the simple index and the JSON summary - are cached on the CDN, and
either of them may lag; the page of the new version is the fresh one. So the command reads both
listings, takes the newer, asks the pages of the next versions, and says so when the sources
disagree. No network here: urlopen is replaced by a router over canned answers.

Needs no Element data - runs in the public CI.
"""

from __future__ import annotations

import io
import json
import zipfile

import pytest

from xbsl import i18n, selfupdate

PLATFORM = ("cp314", ("win_amd64",))


class _Answer:
    def __init__(self, data: bytes):
        self._data = data

    def read(self):
        return self._data

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def _wheels(version: str) -> list[dict]:
    """The files of one release: the native wheel for the test platform, the portable one."""
    return [
        {"filename": f"xbsl-{version}-py3-none-any.whl", "url": f"http://pypi/{version}/pure.whl"},
        {"filename": f"xbsl-{version}-cp314-cp314-win_amd64.whl",
         "url": f"http://pypi/{version}/native.whl"},
    ]


def _index(*versions: str) -> dict:
    """A PEP 691 answer of the simple index listing these releases."""
    return {"meta": {"api-version": "1.1"},
            "files": [item for version in versions for item in _wheels(version)]}


def _page(version: str, *, yanked: bool = False) -> dict:
    """The JSON page of one version - the same shape the summary has."""
    return {"info": {"version": version, "yanked": yanked}, "urls": _wheels(version)}


def _wheel_archive(version: str) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("xbsl/__init__.py", f'__version__ = "{version}"\n')
        archive.writestr(f"xbsl-{version}.dist-info/METADATA", f"Version: {version}\n")
    return buffer.getvalue()


def _route(monkeypatch, answers: dict) -> list[str]:
    """urlopen over canned answers: a dict is JSON, bytes are a download, an exception is raised.

    A URL the test does not name answers 404, as PyPI does for a version it does not have.
    Returns the list of the URLs asked, in order.
    """
    asked: list[str] = []

    def urlopen(target, timeout=0):
        url = getattr(target, "full_url", target)
        asked.append(url)
        answer = answers.get(url)
        if answer is None:
            raise selfupdate.urllib.error.HTTPError(url, 404, "Not Found", {}, None)
        if isinstance(answer, Exception):
            raise answer
        if isinstance(answer, bytes):
            return _Answer(answer)
        return _Answer(json.dumps(answer).encode("utf-8"))

    monkeypatch.setattr(selfupdate.urllib.request, "urlopen", urlopen)
    monkeypatch.setattr(selfupdate, "platform_tags", lambda: PLATFORM)
    return asked


def _page_url(version: str) -> str:
    return selfupdate.PYPI_VERSION.format(version=version)


@pytest.fixture()
def site(tmp_path, monkeypatch):
    """An installed xbsl 0.117.0 in a fake site-packages; the import check always passes."""
    root = tmp_path / "site-packages"
    (root / "xbsl").mkdir(parents=True)
    (root / "xbsl" / "__init__.py").write_text('__version__ = "0.117.0"\n', encoding="utf-8")
    (root / "xbsl-0.117.0.dist-info").mkdir()
    monkeypatch.setattr(selfupdate, "_site_packages", lambda: root)
    monkeypatch.setattr(selfupdate, "__version__", "0.117.0")
    monkeypatch.setattr(selfupdate, "verify_install", lambda where, expected: expected)
    return root


def test_a_release_both_listings_miss_is_found_on_its_page(monkeypatch):
    """The case of 24.09.2026: the index and the summary still say 0.117.0."""
    asked = _route(monkeypatch, {
        selfupdate.PYPI_SIMPLE: _index("0.116.0", "0.117.0"),
        selfupdate.PYPI_LATEST: _page("0.117.0"),
        _page_url("0.118.0"): _page("0.118.0"),
    })
    said: list[str] = []

    url, version, kind = selfupdate._wheel_url(None, log=said.append)

    assert (url, version, kind) == ("http://pypi/0.118.0/native.whl", "0.118.0", selfupdate.NATIVE)
    assert len(said) == 1
    assert "0.117.0" in said[0] and "0.118.0" in said[0] and "расходятся" in said[0]
    # The look past the listings goes on from the release it found, and stops at nothing new.
    assert asked[:2] == [selfupdate.PYPI_SIMPLE, selfupdate.PYPI_LATEST]
    assert _page_url("0.119.0") in asked and _page_url("0.118.1") in asked


def test_the_update_goes_through_where_it_used_to_say_current(site, monkeypatch):
    """End to end: the command downloads 0.118.0 instead of answering "already current"."""
    _route(monkeypatch, {
        selfupdate.PYPI_SIMPLE: _index("0.117.0"),
        selfupdate.PYPI_LATEST: _page("0.117.0"),
        _page_url("0.118.0"): _page("0.118.0"),
        "http://pypi/0.118.0/native.whl": _wheel_archive("0.118.0"),
    })
    said: list[str] = []

    old, new = selfupdate.self_update(log=said.append)

    assert (old, new) == ("0.117.0", "0.118.0")
    assert not any(i18n.t("selfupdate.up-to-date", version="0.117.0") == line for line in said)
    assert '"0.118.0"' in (site / "xbsl" / "__init__.py").read_text(encoding="utf-8")


def test_a_lagging_index_gives_way_to_a_fresh_summary(monkeypatch):
    asked = _route(monkeypatch, {
        selfupdate.PYPI_SIMPLE: _index("0.117.0"),
        selfupdate.PYPI_LATEST: _page("0.118.0"),
    })
    said: list[str] = []

    url, version, _kind = selfupdate._wheel_url(None, log=said.append)

    assert (url, version) == ("http://pypi/0.118.0/native.whl", "0.118.0")
    assert len(said) == 1 and "0.117.0" in said[0] and "0.118.0" in said[0]
    assert _page_url("0.118.1") in asked  # the pages are asked past the newer listing


def test_a_lagging_summary_gives_way_to_a_fresh_index(monkeypatch):
    """The other order, seen on 31.07.2026: the summary lags, the index is fresh."""
    _route(monkeypatch, {
        selfupdate.PYPI_SIMPLE: _index("0.117.0", "0.118.0"),
        selfupdate.PYPI_LATEST: _page("0.117.0"),
    })
    said: list[str] = []

    url, version, _kind = selfupdate._wheel_url(None, log=said.append)

    assert (url, version) == ("http://pypi/0.118.0/native.whl", "0.118.0")
    assert len(said) == 1


def test_sources_that_agree_say_nothing(site, monkeypatch):
    """The negative control: no disagreement, no extra line, and "already current" stands."""
    asked = _route(monkeypatch, {
        selfupdate.PYPI_SIMPLE: _index("0.116.0", "0.117.0"),
        selfupdate.PYPI_LATEST: _page("0.117.0"),
    })
    said: list[str] = []

    old, new = selfupdate.self_update(log=said.append)

    assert old == new == "0.117.0"
    assert said == [i18n.t("selfupdate.up-to-date", version="0.117.0")]
    assert asked == [selfupdate.PYPI_SIMPLE, selfupdate.PYPI_LATEST,
                     *(_page_url(v) for v in ("0.117.1", "0.118.0", "1.0.0"))]


def test_two_releases_in_one_lag_window_give_the_newer(monkeypatch):
    _route(monkeypatch, {
        selfupdate.PYPI_SIMPLE: _index("0.117.0"),
        selfupdate.PYPI_LATEST: _page("0.117.0"),
        _page_url("0.118.0"): _page("0.118.0"),
        _page_url("0.118.1"): _page("0.118.1"),
    })

    assert selfupdate._wheel_url(None)[1] == "0.118.1"


def test_a_yanked_release_on_its_page_does_not_count(monkeypatch):
    _route(monkeypatch, {
        selfupdate.PYPI_SIMPLE: _index("0.117.0"),
        selfupdate.PYPI_LATEST: _page("0.117.0"),
        _page_url("0.118.0"): _page("0.118.0", yanked=True),
    })
    said: list[str] = []

    assert selfupdate._wheel_url(None, log=said.append)[1] == "0.117.0"
    assert said == []


def test_a_page_that_names_another_version_does_not_count(monkeypatch):
    """A proxy answering one canned document for every URL must not invent a release."""
    _route(monkeypatch, {
        selfupdate.PYPI_SIMPLE: _index("0.117.0"),
        selfupdate.PYPI_LATEST: _page("0.117.0"),
        _page_url("0.118.0"): _page("0.117.0"),
    })

    assert selfupdate._wheel_url(None)[1] == "0.117.0"


def test_listings_behind_the_installed_release_never_downgrade(site, monkeypatch):
    """Installed by its number a minute ago, the release is newer than both listings say.

    Without the guard the plain command "updated" back to the previous release.
    """
    monkeypatch.setattr(selfupdate, "__version__", "0.118.0")

    def untouched(where):
        raise AssertionError("the installation must not be touched")

    _route(monkeypatch, {
        selfupdate.PYPI_SIMPLE: _index("0.117.0"),
        selfupdate.PYPI_LATEST: _page("0.117.0"),
        "http://pypi/0.117.0/native.whl": AssertionError("nothing must be downloaded"),
    })
    monkeypatch.setattr(selfupdate, "_move_aside", untouched)
    said: list[str] = []

    old, new = selfupdate.self_update(log=said.append)

    assert old == new == "0.118.0"
    assert said[-1] == i18n.t("selfupdate.newer-installed", installed="0.118.0", latest="0.117.0")


def test_an_unreachable_summary_does_not_stop_the_index(monkeypatch):
    _route(monkeypatch, {
        selfupdate.PYPI_SIMPLE: _index("0.117.0"),
        selfupdate.PYPI_LATEST: OSError("connection reset"),
    })
    said: list[str] = []

    assert selfupdate._wheel_url(None, log=said.append)[1] == "0.117.0"
    assert said == []


def test_a_summary_that_is_not_json_does_not_stop_the_index(monkeypatch):
    _route(monkeypatch, {
        selfupdate.PYPI_SIMPLE: _index("0.117.0"),
        selfupdate.PYPI_LATEST: b"<html>maintenance</html>",
    })

    assert selfupdate._wheel_url(None)[1] == "0.117.0"


def test_both_listings_down_is_reported_in_words(monkeypatch):
    _route(monkeypatch, {
        selfupdate.PYPI_SIMPLE: OSError("index down"),
        selfupdate.PYPI_LATEST: OSError("summary down"),
    })

    with pytest.raises(selfupdate.SelfUpdateError, match="не удалось обратиться к PyPI"):
        selfupdate._wheel_url(None)


def test_an_explicit_version_asks_neither_the_summary_nor_the_next_pages(monkeypatch):
    """The path of `--version` stays as it was: the index, then the page of that version."""
    asked = _route(monkeypatch, {
        selfupdate.PYPI_SIMPLE: _index("0.117.0"),
        _page_url("0.118.0"): _page("0.118.0"),
    })

    assert selfupdate._wheel_url("0.118.0")[1] == "0.118.0"
    assert asked == [selfupdate.PYPI_SIMPLE, _page_url("0.118.0")]


def test_next_versions_step_every_position():
    assert selfupdate._next_versions("0.117.0") == ["0.117.1", "0.118.0", "1.0.0"]
    assert selfupdate._next_versions("0.86.2") == ["0.86.3", "0.87.0", "1.0.0"]
    assert selfupdate._next_versions("0.51.0.post1") == ["0.51.1", "0.52.0", "1.0.0"]
    assert selfupdate._next_versions("0.52.0rc1") == []
    assert selfupdate._next_versions("") == []


def test_the_disagreement_is_said_in_english_too(monkeypatch):
    _route(monkeypatch, {
        selfupdate.PYPI_SIMPLE: _index("0.117.0"),
        selfupdate.PYPI_LATEST: _page("0.117.0"),
        _page_url("0.118.0"): _page("0.118.0"),
    })
    said: list[str] = []
    i18n.set_lang("en")
    try:
        selfupdate._wheel_url(None, log=said.append)
        guard = i18n.t("selfupdate.newer-installed", installed="0.118.0", latest="0.117.0")
    finally:
        i18n.set_lang("ru")

    assert said and "disagree" in said[0]
    for line in (*said, guard):
        assert not any("а" <= char <= "я" for char in line.lower()), line
