"""Checks of yaml/delete-current-needs-immediate (xbsl/rules/yaml_deletion.py)."""

from xbsl import engine
from xbsl.cli import discover

RULE = "yaml/delete-current-needs-immediate"

_OWNER = """ВидЭлемента: Справочник
Ид: 77777777-7777-7777-7777-777777777777
Имя: Владельцы
{mode}Реквизиты:
    -
        Ид: 77777777-0000-0000-0000-000000000001
        Имя: Цель
        Тип: Справочник.Цели.Ссылка?
        {action}: {value}
"""


def _has(diags, rule_id):
    return any(d.rule_id == rule_id for d in diags)


def _owner(tmp_path, mode="", action="ПриУдаленииОбъектаПоСсылке", value="УдалятьТекущий"):
    text = _OWNER.format(
        mode=f"РежимУдаления: {mode}\n" if mode else "", action=action, value=value
    )
    (tmp_path / "Владельцы.yaml").write_text(text, encoding="utf-8")
    return engine.run(discover([str(tmp_path)]), select={RULE})


def test_delete_current_with_marking_mode_flagged(tmp_path):
    d = _owner(tmp_path, mode="ПометкаУдаления")
    assert any(x.rule_id == RULE and "Цель" in x.message for x in d)


def test_delete_current_without_declared_mode_flagged(tmp_path):
    """The metamodel default of РежимУдаления is ПометкаУдаления, so silence about the mode
    is the dangerous case rather than an unknown one."""
    d = _owner(tmp_path)
    assert any(x.rule_id == RULE and "умолчание" in x.message for x in d)


def test_delete_current_with_immediate_mode_ok(tmp_path):
    d = _owner(tmp_path, mode="Немедленно")
    assert not _has(d, RULE)


def test_other_actions_ok(tmp_path):
    """Only DeleteCurrent conflicts - the other three actions leave the record in place."""
    for value in ("Очищать", "НетДействия", "ЗапрещатьУдаление"):
        d = _owner(tmp_path, mode="ПометкаУдаления", value=value)
        assert not _has(d, RULE), value


def test_english_spelling_flagged(tmp_path):
    (tmp_path / "Owners.yaml").write_text(
        "ElementKind: Catalog\n"
        "Ид: 77777777-7777-7777-7777-777777777778\n"
        "Name: Owners\n"
        "DeletionMode: DeletionMark\n"
        "Attributes:\n"
        "    -\n"
        "        Ид: 77777777-0000-0000-0000-000000000002\n"
        "        Name: Target\n"
        "        OnReferencedObjectDeletion: DeleteCurrent\n",
        encoding="utf-8",
    )
    d = engine.run(discover([str(tmp_path)]), select={RULE})
    assert any(x.rule_id == RULE and "Target" in x.message for x in d)


def test_english_immediate_mode_ok(tmp_path):
    (tmp_path / "Owners.yaml").write_text(
        "ElementKind: Catalog\n"
        "Ид: 77777777-7777-7777-7777-777777777779\n"
        "Name: Owners\n"
        "DeletionMode: Immediately\n"
        "Attributes:\n"
        "    -\n"
        "        Ид: 77777777-0000-0000-0000-000000000003\n"
        "        Name: Target\n"
        "        OnReferencedObjectDeletion: DeleteCurrent\n",
        encoding="utf-8",
    )
    d = engine.run(discover([str(tmp_path)]), select={RULE})
    assert not _has(d, RULE)


def test_yaml_without_element_kind_not_checked(tmp_path):
    """A fragment that describes no project object has no deletion mode to judge against."""
    (tmp_path / "Кусок.yaml").write_text(
        "Реквизиты:\n    -\n        Имя: Цель\n"
        "        ПриУдаленииОбъектаПоСсылке: УдалятьТекущий\n",
        encoding="utf-8",
    )
    d = engine.run(discover([str(tmp_path)]), select={RULE})
    assert not _has(d, RULE)


_REGISTER = """ВидЭлемента: РегистрСведений
Ид: 77777777-7777-7777-7777-77777777777a
Имя: ОперацииОбновления
Измерения:
    -
        Ид: 77777777-0000-0000-0000-000000000004
        Имя: Задание
        Тип: Задания.Ссылка?
        ПриУдаленииОбъектаПоСсылке: УдалятьТекущий
Ресурсы:
    -
        Ид: 77777777-0000-0000-0000-000000000006
        Имя: Метка
        Тип: Метки.Ссылка?
        ПриУдаленииОбъектаПоСсылке: УдалятьТекущий
"""


def test_register_has_no_deletion_mode_and_is_not_judged(tmp_path):
    """An information register carries no deletion mode at all - neither the metamodel nor the
    page of its properties gives the kind one - so there is no mode to hold the action against.
    The compiler takes such a register, on a dimension and on a resource alike. The rule used to
    take the default of the first kind that records one, a catalog, and read a register by it."""
    (tmp_path / "ОперацииОбновления.yaml").write_text(_REGISTER, encoding="utf-8")
    d = engine.run(discover([str(tmp_path)]), select={RULE})
    assert not _has(d, RULE)


def test_document_keeps_its_own_default(tmp_path):
    """A kind that does record the property is still judged by the default written for it."""
    (tmp_path / "Заказы.yaml").write_text(
        "ВидЭлемента: Документ\n"
        "Ид: 77777777-7777-7777-7777-77777777777b\n"
        "Имя: Заказы\n"
        "Реквизиты:\n"
        "    -\n"
        "        Ид: 77777777-0000-0000-0000-000000000005\n"
        "        Имя: Цель\n"
        "        Тип: Цели.Ссылка?\n"
        "        ПриУдаленииОбъектаПоСсылке: УдалятьТекущий\n",
        encoding="utf-8",
    )
    d = engine.run(discover([str(tmp_path)]), select={RULE})
    assert _has(d, RULE)


def test_message_points_at_the_element_that_declares_the_attribute(tmp_path):
    """The restriction is on the element holding the attribute, not on the one referenced:
    "у владельца ссылки" was read the other way round."""
    d = _owner(tmp_path, mode="ПометкаУдаления")
    assert d
    assert all("владельца ссылки" not in x.message for x in d)
    assert any("объявляет реквизит" in x.message for x in d)


def test_message_quotes_the_compiler_word_for_word(tmp_path):
    """The compiler writes DeletionMark in double quotes, and the message used to drop them.
    The sentence is on no page of the shipped documentation, so the message says whose it is."""
    d = _owner(tmp_path, mode="ПометкаУдаления")
    assert d
    assert all('cannot apply to object with a "DeletionMark"' in x.message for x in d)
    assert all("Компилятор отвечает" in x.message for x in d)


def _without_recorded_default(monkeypatch):
    """The metamodel with the default of the deletion mode stripped from every record.

    Forty four of the sixty three enumeration records of the element kinds carry no default,
    so a record without one is the ordinary shape of the data rather than its edge.
    """
    from xbsl import metamodel
    from xbsl.rules import yaml_deletion

    original = metamodel.properties

    def stripped(kind: str) -> dict:
        props = dict(original(kind))
        record = props.get("РежимУдаления")
        if record:
            props["РежимУдаления"] = {k: v for k, v in record.items() if k != "default"}
        return props

    monkeypatch.setattr(metamodel, "properties", stripped)
    # The answer is cached per kind, so the patch has to start from an empty one - and the
    # caller empties it again afterwards, or the next test would read this one's metamodel.
    yaml_deletion._default_mode.cache_clear()


def test_a_kind_that_has_the_property_is_judged_without_a_recorded_default(
    tmp_path, monkeypatch
):
    """Two different noes, and only one of them silences the rule.

    A catalog holds a deletion mode whatever the metamodel spells, and an element that never
    names one is in the marking mode - the compiler refused exactly that shape. Reading a
    record without a default as "this kind has no mode" would put the miss this gate removes
    back, one border further along.
    """
    from xbsl.rules import yaml_deletion

    _without_recorded_default(monkeypatch)
    try:
        assert _has(_owner(tmp_path), RULE)
    finally:
        yaml_deletion._default_mode.cache_clear()


def test_a_kind_without_the_property_stays_unjudged_without_a_recorded_default(
    tmp_path, monkeypatch
):
    """The other half of the same pair: a register has no such property to begin with."""
    from xbsl.rules import yaml_deletion

    _without_recorded_default(monkeypatch)
    try:
        (tmp_path / "ОперацииОбновления.yaml").write_text(_REGISTER, encoding="utf-8")
        assert not _has(engine.run(discover([str(tmp_path)]), select={RULE}), RULE)
    finally:
        yaml_deletion._default_mode.cache_clear()
