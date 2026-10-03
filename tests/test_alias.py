"""The retired Python import is gone; existing environment and plugin settings still work."""

import os
import subprocess
import sys
from pathlib import Path

from xbsl import dataset, i18n, plugins


def test_retired_python_import_is_unavailable():
    name = "xbsllint"
    root = Path(__file__).resolve().parent.parent
    code = "import importlib, sys; sys.path.insert(0, sys.argv[1]); importlib.import_module(sys.argv[2])"
    result = subprocess.run(
        [sys.executable, "-I", "-S", "-B", "-c", code, str(root), name],
        cwd=root, capture_output=True, text=True, encoding="utf-8", timeout=30,
        env={**os.environ, "PYTHONIOENCODING": "utf-8"},
    )
    assert result.returncode != 0
    assert "No module named 'xbsllint'" in result.stderr


def test_legacy_lang_env(monkeypatch):
    monkeypatch.delenv("XBSL_LANG", raising=False)
    monkeypatch.setenv("XBSLLINT_LANG", "en")
    i18n.set_lang(None)
    try:
        assert i18n.current_lang() == "en"
    finally:
        i18n.set_lang("ru")  # tests in other modules assert against Russian text


def test_new_lang_env_wins(monkeypatch):
    monkeypatch.setenv("XBSL_LANG", "ru")
    monkeypatch.setenv("XBSLLINT_LANG", "en")
    i18n.set_lang(None)
    try:
        assert i18n.current_lang() == "ru"
    finally:
        i18n.set_lang("ru")


def test_legacy_data_dir_env(tmp_path, monkeypatch):
    monkeypatch.delenv("XBSL_DATA_DIR", raising=False)
    monkeypatch.setenv("XBSLLINT_DATA_DIR", str(tmp_path))
    dataset.set_data_root(None)
    assert dataset.data_root() == tmp_path


def test_legacy_no_plugins_env(monkeypatch):
    monkeypatch.delenv("XBSL_NO_PLUGINS", raising=False)
    monkeypatch.setenv("XBSLLINT_NO_PLUGINS", "1")
    assert plugins.disabled()
    # The new name takes precedence: an explicit "0" in it overrides the legacy "1".
    monkeypatch.setenv("XBSL_NO_PLUGINS", "0")
    assert not plugins.disabled()


class _StubEP:
    def __init__(self, name, group, value="stub"):
        self.name = name
        self.group = group
        self.value = value

    def load(self):
        return lambda: None


def test_legacy_entry_point_group_scanned(monkeypatch):
    monkeypatch.delenv("XBSL_NO_PLUGINS", raising=False)
    monkeypatch.delenv("XBSLLINT_NO_PLUGINS", raising=False)
    new_ep = _StubEP("а-новый", "xbsl.rules")
    legacy_ep = _StubEP("б-старый", "xbsllint.rules")
    monkeypatch.setattr(
        plugins, "entry_points", lambda group: [ep for ep in (new_ep, legacy_ep) if ep.group == group]
    )
    assert [ep.name for ep in plugins._points(plugins.RULES_GROUP)] == ["а-новый", "б-старый"]


def test_legacy_group_deduplicated(monkeypatch):
    # A transition-period package declares the same target in both groups - load it once.
    monkeypatch.delenv("XBSL_NO_PLUGINS", raising=False)
    monkeypatch.delenv("XBSLLINT_NO_PLUGINS", raising=False)
    new_ep = _StubEP("пакет", "xbsl.rules", value="pkg.rules")
    legacy_ep = _StubEP("пакет", "xbsllint.rules", value="pkg.rules")
    monkeypatch.setattr(
        plugins, "entry_points", lambda group: [ep for ep in (new_ep, legacy_ep) if ep.group == group]
    )
    assert plugins._points(plugins.RULES_GROUP) == [new_ep]
