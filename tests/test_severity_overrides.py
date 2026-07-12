"""Переопределение уровней правил точкой расширения "xbsllint.severity".

Реестр правил и карта переопределений – глобальное состояние движка; фикстура
восстанавливает их после каждого теста, чтобы прогоны не влияли друг на друга.
"""

from importlib.metadata import EntryPoint

import pytest

from xbsllint import engine, plugins
from xbsllint.diagnostics import Diagnostic, Severity


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


@pytest.fixture(autouse=True)
def _restore_registry(monkeypatch):
    monkeypatch.delenv("XBSLLINT_NO_PLUGINS", raising=False)
    rules_before = list(engine.RULES)
    overrides_before = dict(engine.SEVERITY_OVERRIDES)
    yield
    engine.RULES[:] = rules_before
    engine.SEVERITY_OVERRIDES.clear()
    engine.SEVERITY_OVERRIDES.update(overrides_before)


def _register_probe(rule_id="probe/severity", severity=Severity.INFO, enabled=True):
    @engine.rule(rule_id, "probe title", "B", severity=severity, enabled_by_default=enabled)
    def probe(source):
        yield Diagnostic(source.rel, 1, 1, rule_id, severity, "нашлось")

    return probe


def _info_by_id(rule_id):
    return next(r for r in engine.RULES if r.id == rule_id)


# --- Сбор словаря из точек расширения --------------------------------------------------

def test_overrides_merge_by_name_order(monkeypatch):
    first = _StubEP("а-первый", plugins.SEVERITY_GROUP, {"x/one": "warning"})
    second = _StubEP("б-второй", plugins.SEVERITY_GROUP, lambda: {"x/one": "error", "x/two": "off"})
    monkeypatch.setattr(plugins, "entry_points", _fake_entry_points(first, second))
    assert plugins.severity_overrides() == {"x/one": "error", "x/two": "off"}


def test_overrides_reject_non_dict(monkeypatch):
    ep = _StubEP("кривая", plugins.SEVERITY_GROUP, ["не", "словарь"])
    monkeypatch.setattr(plugins, "entry_points", _fake_entry_points(ep))
    with pytest.raises(plugins.PluginError, match="кривая"):
        plugins.severity_overrides()


def test_overrides_disabled_by_env(monkeypatch):
    ep = _StubEP("данные", plugins.SEVERITY_GROUP, {"x/one": "warning"})
    monkeypatch.setattr(plugins, "entry_points", _fake_entry_points(ep))
    monkeypatch.setenv("XBSLLINT_NO_PLUGINS", "1")
    assert plugins.severity_overrides() == {}


# --- Применение к реестру и диагностикам -----------------------------------------------

def test_override_recolors_rule_and_diagnostics(monkeypatch):
    _register_probe()
    monkeypatch.setattr(
        engine._plugins, "severity_overrides", lambda: {"probe/severity": "warning"}
    )
    engine.apply_severity_overrides()

    assert _info_by_id("probe/severity").severity is Severity.WARNING
    src = engine.load_text("проба.xbsl", "// пусто")
    diags = engine.run_sources([src], select={"probe/severity"})
    assert [d.severity for d in diags] == [Severity.WARNING]


def test_override_off_removes_from_default_set(monkeypatch):
    _register_probe(rule_id="probe/off-target")
    monkeypatch.setattr(
        engine._plugins, "severity_overrides", lambda: {"probe/off-target": "off"}
    )
    engine.apply_severity_overrides()

    info = _info_by_id("probe/off-target")
    assert info.enabled_by_default is False
    assert "probe/off-target" not in engine.SEVERITY_OVERRIDES
    # Явный select всё ещё включает правило – с его базовым уровнем.
    src = engine.load_text("проба.xbsl", "// пусто")
    diags = engine.run_sources([src], select={"probe/off-target"})
    assert [d.severity for d in diags] == [Severity.INFO]


def test_override_unknown_rule_raises(monkeypatch):
    monkeypatch.setattr(
        engine._plugins, "severity_overrides", lambda: {"нет/такого": "warning"}
    )
    with pytest.raises(plugins.PluginError, match="нет/такого"):
        engine.apply_severity_overrides()


def test_override_unknown_level_raises(monkeypatch):
    _register_probe(rule_id="probe/bad-level")
    monkeypatch.setattr(
        engine._plugins, "severity_overrides", lambda: {"probe/bad-level": "fatal"}
    )
    with pytest.raises(plugins.PluginError, match="fatal"):
        engine.apply_severity_overrides()
