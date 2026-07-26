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
