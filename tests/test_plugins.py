"""Точки расширения: внешние правила и внешний корень данных.

Тесты не зависят от сгенерированных данных Элемента – корни собираются во временном каталоге.
Окружение чистится фикстурой: иначе прогон с выставленным XBSLLINT_DATA_DIR ломал бы проверки
приоритетов.
"""

import json
from importlib.metadata import EntryPoint
from pathlib import Path

import pytest

from xbsllint import dataset, i18n, plugins


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    monkeypatch.delenv("XBSLLINT_DATA_DIR", raising=False)
    monkeypatch.delenv("XBSLLINT_NO_PLUGINS", raising=False)
    dataset.set_data_root(None)
    yield
    dataset.set_data_root(None)
    i18n.set_lang("ru")  # cli.main(--where) сбрасывает язык на locale – вернуть для других модулей


def _make_root(path: Path, version="1.0.0", keyword="ПЕРВЫЙ") -> Path:
    (path / version).mkdir(parents=True)
    (path / version / "language.json").write_text(
        json.dumps({"keywords": {keyword: {"forms": [keyword]}}}), encoding="utf-8"
    )
    (path / "index.json").write_text(
        json.dumps({"available": [version], "default": version}), encoding="utf-8"
    )
    return path


class _StubEP:
    """Точка расширения с готовым объектом – без установки настоящего пакета."""

    value = "стаб"

    def __init__(self, name, group, target):
        self.name = name
        self.group = group
        self._target = target

    def load(self):
        return self._target


def _fake_entry_points(*eps):
    def fake(group):
        return [ep for ep in eps if ep.group == group]

    return fake


# --- Корень данных -------------------------------------------------------------------

def test_bundled_root_by_default(monkeypatch):
    monkeypatch.setattr(plugins, "data_roots", list)
    assert dataset.data_root() == dataset.BUNDLED_DATA_ROOT


def test_env_data_dir_used(tmp_path, monkeypatch):
    root = _make_root(tmp_path)
    monkeypatch.setenv("XBSLLINT_DATA_DIR", str(root))
    assert dataset.data_root() == root
    assert dataset.default_version() == "1.0.0"


def test_set_data_root_wins_over_env(tmp_path, monkeypatch):
    explicit = _make_root(tmp_path / "explicit")
    monkeypatch.setenv("XBSLLINT_DATA_DIR", str(tmp_path / "from-env"))
    dataset.set_data_root(explicit)
    assert dataset.data_root() == explicit


def test_plugin_data_root_used(tmp_path, monkeypatch):
    root = _make_root(tmp_path)
    monkeypatch.setattr(plugins, "data_roots", lambda: [root])
    assert dataset.data_root() == root


def test_plugin_data_root_without_index_ignored(tmp_path, monkeypatch):
    monkeypatch.setattr(plugins, "data_roots", lambda: [tmp_path])
    assert dataset.data_root() == dataset.BUNDLED_DATA_ROOT


def test_load_json_isolated_per_root(tmp_path, monkeypatch):
    """Смена корня без явного сброса кэша не должна отдавать данные прежнего корня."""
    first = _make_root(tmp_path / "first", keyword="ПЕРВЫЙ")
    second = _make_root(tmp_path / "second", keyword="ВТОРОЙ")

    monkeypatch.setenv("XBSLLINT_DATA_DIR", str(first))
    assert "ПЕРВЫЙ" in dataset.load_json("language.json")["keywords"]

    monkeypatch.setenv("XBSLLINT_DATA_DIR", str(second))
    assert "ВТОРОЙ" in dataset.load_json("language.json")["keywords"]


def test_missing_index_names_the_root(tmp_path, monkeypatch):
    monkeypatch.setenv("XBSLLINT_DATA_DIR", str(tmp_path))
    with pytest.raises(dataset.DatasetError, match="Нет индекса версий"):
        dataset.default_version()


# --- Загрузка точек расширения -------------------------------------------------------

def test_rule_plugin_is_imported(monkeypatch):
    # Значение точки – модуль; его импорт и есть регистрация правил.
    ep = EntryPoint("модуль-правил", "json", plugins.RULES_GROUP)
    monkeypatch.setattr(plugins, "entry_points", _fake_entry_points(ep))
    assert plugins.load_rules() == ["модуль-правил"]


def test_broken_rule_plugin_raises(monkeypatch):
    ep = EntryPoint("битая", "нет_такого_модуля", plugins.RULES_GROUP)
    monkeypatch.setattr(plugins, "entry_points", _fake_entry_points(ep))
    with pytest.raises(plugins.PluginError, match="битая"):
        plugins.load_rules()


def test_data_plugin_accepts_path_and_callable(tmp_path, monkeypatch):
    as_path = _StubEP("а-путь", plugins.DATA_GROUP, tmp_path)
    as_callable = _StubEP("б-функция", plugins.DATA_GROUP, lambda: tmp_path / "второй")
    monkeypatch.setattr(plugins, "entry_points", _fake_entry_points(as_path, as_callable))
    assert plugins.data_roots() == [tmp_path, tmp_path / "второй"]


def test_no_plugins_env_disables_both(monkeypatch):
    rules_ep = EntryPoint("битая", "нет_такого_модуля", plugins.RULES_GROUP)
    data_ep = _StubEP("данные", plugins.DATA_GROUP, Path("/нет"))
    monkeypatch.setattr(plugins, "entry_points", _fake_entry_points(rules_ep, data_ep))
    monkeypatch.setenv("XBSLLINT_NO_PLUGINS", "1")
    assert plugins.disabled()
    assert plugins.load_rules() == []
    assert plugins.data_roots() == []


@pytest.mark.parametrize("value,expected", [("", False), ("0", False), ("no", False), ("1", True)])
def test_disable_flag_parsing(monkeypatch, value, expected):
    monkeypatch.setenv("XBSLLINT_NO_PLUGINS", value)
    assert plugins.disabled() is expected


def test_data_root_source_reports_origin(tmp_path):
    """data_root_source различает --data-dir и встроенные данные (для --where)."""
    assert dataset.data_root_source() == "встроенные данные пакета"
    dataset.set_data_root(_make_root(tmp_path))
    assert dataset.data_root_source() == "--data-dir"


def test_cli_where_shows_root(tmp_path, capsys):
    """xbsllint --where печатает корень данных, источник и версию."""
    from xbsllint import cli

    root = _make_root(tmp_path)
    rc = cli.main(["--where", "--data-dir", str(root), "--lang", "ru"])
    assert rc == 0
    out = capsys.readouterr().out
    assert str(root) in out
    assert "--data-dir" in out
    assert "1.0.0" in out  # версия по умолчанию из index.json
