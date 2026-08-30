"""Checks of yaml/event-property-type (xbsl/rules/event_log.py)."""

import pytest

from xbsl import engine
from xbsl.cli import discover

RULE = "yaml/event-property-type"

_HEAD = """ВидЭлемента: СобытиеЖурналаСобытий
Ид: 6c8c2f7c-0000-4000-8000-000000000001
Имя: СобытиеПроверки
ОбластьВидимости: ВПодсистеме
Важность: Обычная
"""


def _run(tmp_path):
    return engine.run(discover([str(tmp_path)]), select={RULE})


def _event(tmp_path, properties: str):
    text = _HEAD + "Свойства:\n" + properties
    (tmp_path / "СобытиеПроверки.yaml").write_text(text, encoding="utf-8")
    return _run(tmp_path)


def _has(diags):
    return any(d.rule_id == RULE for d in diags)


@pytest.mark.needs_data
def test_project_enum_type_flagged(tmp_path):
    diags = _event(tmp_path, "- Имя: Статус\n  Тип: СтатусЗаявки\n")
    assert any(
        d.rule_id == RULE and "Статус" in d.message and "СтатусЗаявки" in d.message
        for d in diags
    )


@pytest.mark.needs_data
def test_nullable_enum_type_flagged(tmp_path):
    """The `?` does not legalize an enumeration - the closed list has no such member."""
    diags = _event(tmp_path, "- Имя: Статус\n  Тип: СтатусЗаявки?\n")
    assert _has(diags)


@pytest.mark.needs_data
def test_enum_with_default_value_still_flagged(tmp_path):
    """A default value silences yaml/enum-needs-nullable but not the server's closed list."""
    diags = _event(
        tmp_path,
        "- Имя: Статус\n  Тип: СтатусЗаявки\n  ЗначениеПоУмолчанию:\n    Значение: Новая\n",
    )
    assert _has(diags)


@pytest.mark.needs_data
def test_allowed_types_silent(tmp_path):
    diags = _event(
        tmp_path,
        "- Имя: Код\n  Тип: Строка\n"
        "- Имя: Комментарий\n  Тип: Строка?\n"
        "- Имя: Ключ\n  Тип: Ууид\n",
    )
    assert not _has(diags)


@pytest.mark.needs_data
def test_qualified_allowed_type_silent(tmp_path):
    """A namespace qualification is stripped before the check, never flagged by itself."""
    assert not _has(_event(tmp_path, "- Имя: Начало\n  Тип: Стд::Момент\n"))


@pytest.mark.needs_data
def test_event_kind_type_silent(tmp_path):
    """`EventLogEventKind` is in the metamodel constraint (the docs page lags) - allowed."""
    assert not _has(_event(tmp_path, "- Имя: Вид\n  Тип: ВидСобытияЖурналаСобытий\n"))


@pytest.mark.needs_data
def test_property_without_type_silent(tmp_path):
    assert not _has(_event(tmp_path, "- Имя: Просто\n"))


@pytest.mark.needs_data
def test_union_type_flagged(tmp_path):
    """The constraint enumerates single types - a union is outside the list."""
    assert _has(_event(tmp_path, "- Имя: Смесь\n  Тип: Строка|Число\n"))


@pytest.mark.needs_data
def test_finding_points_at_the_type_value(tmp_path):
    diags = _event(
        tmp_path,
        "- Имя: Код\n  Тип: Строка\n- Имя: Статус\n  Тип: СтатусЗаявки\n",
    )
    assert [(d.line, d.col) for d in diags] == [(10, 8)]


@pytest.mark.needs_data
def test_english_spellings_flagged(tmp_path):
    (tmp_path / "CheckEvent.yaml").write_text(
        "ElementKind: EventLogEvent\n"
        "Ид: 6c8c2f7c-0000-4000-8000-000000000002\n"
        "Name: CheckEvent\n"
        "Importance: Normal\n"
        "Properties:\n"
        "- Name: Status\n"
        "  Type: RequestStatus\n"
        "- Name: Code\n"
        "  Type: String\n",
        encoding="utf-8",
    )
    diags = _run(tmp_path)
    assert [d.line for d in diags if d.rule_id == RULE] == [7]


@pytest.mark.needs_data
def test_other_kinds_not_checked(tmp_path):
    """A catalog attribute may be typed with a project enumeration - only events are judged."""
    (tmp_path / "Заявки.yaml").write_text(
        "ВидЭлемента: Справочник\n"
        "Ид: 6c8c2f7c-0000-4000-8000-000000000003\n"
        "Имя: Заявки\n"
        "Реквизиты:\n"
        "- Имя: Статус\n"
        "  Тип: СтатусЗаявки?\n",
        encoding="utf-8",
    )
    assert not _has(_run(tmp_path))
