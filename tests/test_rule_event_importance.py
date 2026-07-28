"""Checks of yaml/event-needs-importance (xbsl/rules/event_log.py)."""

from xbsl import engine
from xbsl.cli import discover

RULE = "yaml/event-needs-importance"

_EVENT = """ВидЭлемента: СобытиеЖурналаСобытий
Ид: 5b7b1f7c-0000-4000-8000-000000000001
Имя: ОшибкаЗагрузки
ОбластьВидимости: ВПодсистеме
ВидСобытия: Ошибка
{importance}ШаблонПредставления: Не удалось загрузить %{{Источник}}
"""


def _has(diags):
    return any(d.rule_id == RULE for d in diags)


def _event(tmp_path, importance=""):
    text = _EVENT.format(importance=f"Важность: {importance}\n" if importance else "")
    (tmp_path / "ОшибкаЗагрузки.yaml").write_text(text, encoding="utf-8")
    return engine.run(discover([str(tmp_path)]), select={RULE})


def test_event_without_importance_flagged(tmp_path):
    diags = _event(tmp_path)
    assert any(d.rule_id == RULE and "ОшибкаЗагрузки" in d.message for d in diags)


def test_event_with_importance_silent(tmp_path):
    assert not _has(_event(tmp_path, "Обычная"))


def test_explicit_from_constructor_silent(tmp_path):
    """`Importance: FromConstructor` is the platform's own word for that mode - a decision,
    and the way to switch the warning off for an event whose importance varies per write."""
    assert not _has(_event(tmp_path, "ИзКонструктора"))


def test_finding_points_at_the_kind_line(tmp_path):
    """The property is missing, so the anchor is the declaration that makes it required."""
    (tmp_path / "ОшибкаЗагрузки.yaml").write_text(
        "Ид: 5b7b1f7c-0000-4000-8000-000000000002\n"
        "Имя: ОшибкаЗагрузки\n"
        "ВидЭлемента: СобытиеЖурналаСобытий\n",
        encoding="utf-8",
    )
    diags = [d for d in engine.run(discover([str(tmp_path)]), select={RULE})]
    assert [(d.line, d.col) for d in diags] == [(3, 1)]


def test_english_spelling_flagged(tmp_path):
    (tmp_path / "LoadFailed.yaml").write_text(
        "ElementKind: EventLogEvent\n"
        "Ид: 5b7b1f7c-0000-4000-8000-000000000003\n"
        "Name: LoadFailed\n"
        "EventKind: Error\n",
        encoding="utf-8",
    )
    diags = engine.run(discover([str(tmp_path)]), select={RULE})
    assert any(d.rule_id == RULE and "LoadFailed" in d.message for d in diags)


def test_english_importance_silent(tmp_path):
    """The English key names the same property - the rule reads the pair from the metamodel."""
    (tmp_path / "LoadFailed.yaml").write_text(
        "ElementKind: EventLogEvent\n"
        "Ид: 5b7b1f7c-0000-4000-8000-000000000004\n"
        "Name: LoadFailed\n"
        "EventKind: Error\n"
        "Importance: Normal\n",
        encoding="utf-8",
    )
    assert not _has(engine.run(discover([str(tmp_path)]), select={RULE}))


def test_other_kinds_not_checked(tmp_path):
    """Only an event log event carries the property; a catalog has no importance at all."""
    (tmp_path / "Валюты.yaml").write_text(
        "ВидЭлемента: Справочник\n"
        "Ид: 5b7b1f7c-0000-4000-8000-000000000005\n"
        "Имя: Валюты\n",
        encoding="utf-8",
    )
    assert not _has(engine.run(discover([str(tmp_path)]), select={RULE}))


def test_fragment_without_element_kind_not_checked(tmp_path):
    """A file that describes no project object declares no event either - the word may well
    come from a piece of text."""
    (tmp_path / "Кусок.yaml").write_text(
        "Описание: см. СобытиеЖурналаСобытий\n", encoding="utf-8"
    )
    assert not _has(engine.run(discover([str(tmp_path)]), select={RULE}))
