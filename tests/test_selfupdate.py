"""Self-update (`xbsl self-update`): wheel extraction with no network (urllib is mocked).

The command must replace both the xbsl package and the xbsllint alias package from the same
wheel, without touching the dist-info of the transitional xbsllint metapackage, and refuse
to run in an editable install (there git does the updating, and extraction would wreck the
repository).
"""

from __future__ import annotations

import io
import json
import zipfile

import pytest

import xbsl
from xbsl import cli, selfupdate


def _fake_wheel(version: str) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as archive:
        archive.writestr("xbsl/__init__.py", f'__version__ = "{version}"\n')
        archive.writestr("xbsllint/__init__.py", "import xbsl\n")
        archive.writestr(f"xbsl-{version}.dist-info/METADATA", f"Version: {version}\n")
    return buf.getvalue()


class _FakeResp:
    def __init__(self, data):
        self._data = data

    def read(self):
        return self._data

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


@pytest.fixture()
def fake_site(tmp_path, monkeypatch):
    """A fake site-packages with an old xbsl install + the xbsllint metapackage."""
    site = tmp_path / "site-packages"
    (site / "xbsl").mkdir(parents=True)
    (site / "xbsl" / "__init__.py").write_text('__version__ = "0.0.1"\n', encoding="utf-8")
    (site / "xbsllint").mkdir()
    (site / "xbsllint" / "__init__.py").write_text("import xbsl\n", encoding="utf-8")
    (site / "xbsl-0.0.1.dist-info").mkdir()
    # the dist-info of the transitional xbsllint METApackage is a foreign delivery, left alone.
    (site / "xbsllint-0.16.0.dist-info").mkdir()
    monkeypatch.setattr(selfupdate, "_site_packages", lambda: site)
    return site


def test_self_update_extracts_wheel(fake_site, monkeypatch):
    monkeypatch.setattr(selfupdate, "_wheel_url", lambda v: ("http://pypi/xbsl.whl", "9.9.9"))
    monkeypatch.setattr(
        selfupdate.urllib.request, "urlopen", lambda url, timeout=0: _FakeResp(_fake_wheel("9.9.9"))
    )

    old, new = selfupdate.self_update(log=lambda *a: None)

    assert new == "9.9.9" and old == xbsl.__version__
    text = (fake_site / "xbsl" / "__init__.py").read_text(encoding="utf-8")
    assert '__version__ = "9.9.9"' in text
    assert (fake_site / "xbsllint" / "__init__.py").is_file()  # the alias is replaced with the package
    assert not (fake_site / "xbsl-0.0.1.dist-info").exists()  # the old dist-info is removed
    assert (fake_site / "xbsl-9.9.9.dist-info").exists()
    assert (fake_site / "xbsllint-0.16.0.dist-info").exists()  # the metapackage is untouched


def test_self_update_noop_when_current(fake_site, monkeypatch):
    monkeypatch.setattr(selfupdate, "_wheel_url", lambda v: ("http://pypi/x.whl", xbsl.__version__))

    def boom(*a, **k):
        raise AssertionError("скачивание не должно происходить")

    monkeypatch.setattr(selfupdate.urllib.request, "urlopen", boom)
    old, new = selfupdate.self_update(log=lambda *a: None)
    assert old == new == xbsl.__version__


def test_self_update_refuses_editable(monkeypatch, tmp_path):
    # The package directory is not site-packages - so it is an editable install from the repo.
    monkeypatch.setattr(selfupdate, "_site_packages", lambda: tmp_path / "xbsl-lint-public")
    with pytest.raises(selfupdate.SelfUpdateError, match="editable"):
        selfupdate.self_update(log=lambda *a: None)


def test_cli_dispatch(fake_site, monkeypatch, capsys):
    monkeypatch.setattr(selfupdate, "_wheel_url", lambda v: ("http://pypi/xbsl.whl", "9.9.9"))
    monkeypatch.setattr(
        selfupdate.urllib.request, "urlopen", lambda url, timeout=0: _FakeResp(_fake_wheel("9.9.9"))
    )
    code = cli.main(["self-update"])
    assert code == 0
    out = json.loads(capsys.readouterr().out)
    assert out["updated"] is True and out["to"] == "9.9.9"


def test_cli_reports_error_as_json(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(selfupdate, "_site_packages", lambda: tmp_path / "repo")
    code = cli.main(["self-update"])
    assert code == 2
    assert "editable" in json.loads(capsys.readouterr().out)["error"]
