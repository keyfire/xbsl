"""The access-key handler follows the ManualGrant flavour."""

from __future__ import annotations

import pytest

from xbsl import engine, i18n

pytestmark = pytest.mark.needs_data

RULE = "code/access-key-handler-flavour"


def _yaml(manual: str | None, *, english: bool = False, parameters: bool = False) -> str:
    if english:
        lines = ["ElementKind: AccessKey", "Id: a1000000-0000-4000-8000-000000000001", "Name: Key"]
        if manual is not None:
            lines.append(f"ManualGrant: {manual}")
        if parameters:
            lines.extend(["Parameters:", "    -", "        Id: a1000000-0000-4000-8000-000000000002", "        Name: Item", "        Type: String"])
    else:
        lines = ["ВидЭлемента: КлючДоступа", "Ид: a1000000-0000-4000-8000-000000000001", "Имя: Ключ"]
        if manual is not None:
            lines.append(f"РучнаяВыдача: {manual}")
        if parameters:
            lines.extend(["Параметры:", "    -", "        Ид: a1000000-0000-4000-8000-000000000002", "        Имя: Элемент", "        Тип: Строка"])
    return "\n".join(lines) + "\n"


def _handler(*, english: bool = False, annotation: bool = True) -> str:
    prefix = "@Handler\n" if english else "@Обработчик\n"
    declaration = "method CheckHasAccessKeys()\n;\n" if english else "метод ПроверитьНаличиеКлючейДоступа()\n;\n"
    return (prefix if annotation else "") + declaration


def _lint(files: dict[str, str]) -> list:
    sources = [engine.load_text(name, text) for name, text in files.items()]
    return [d for d in engine.run_sources(sources) if d.rule_id == RULE]


def test_computed_key_without_manager_module_needs_handler():
    found = _lint({"Key.yaml": _yaml("Ложь")})
    assert len(found) == 1
    assert (found[0].line, found[0].col) == (1, 1)


def test_computed_key_without_physical_manager_module_needs_handler(tmp_path):
    key = tmp_path / "Key.yaml"
    key.write_text(_yaml("Ложь"), encoding="utf-8")
    found = [d for d in engine.run([key]) if d.rule_id == RULE]
    assert len(found) == 1


def test_computed_key_with_unloaded_physical_manager_module_is_not_reported(tmp_path):
    key = tmp_path / "Key.yaml"
    key.write_text(_yaml("Ложь"), encoding="utf-8")
    (tmp_path / "Key.xbsl").write_text(_handler(), encoding="utf-8")
    assert [d for d in engine.run([key]) if d.rule_id == RULE] == []


@pytest.mark.parametrize("english, manual", [(False, "Ложь"), (True, "False")])
def test_computed_key_with_loaded_manager_without_handler_is_reported(tmp_path, english, manual):
    key = tmp_path / "Key.yaml"
    key.write_text(_yaml(manual, english=english), encoding="utf-8")
    manager = tmp_path / "Key.xbsl"
    manager.write_text("method Other()\n;\n", encoding="utf-8")
    found = [d for d in engine.run([key, manager]) if d.rule_id == RULE]
    assert len(found) == 1
    assert found[0].path == str(key)


def test_computed_key_with_handler_in_manager_module_is_clean():
    assert _lint({"Key.yaml": _yaml("Ложь"), "Key.xbsl": _handler()}) == []


def test_computed_key_accepts_qualified_handler_annotation():
    handler = "@Стд::Обработчик\nметод ПроверитьНаличиеКлючейДоступа()\n;\n"
    assert _lint({"Key.yaml": _yaml("Ложь"), "Key.xbsl": handler}) == []


def test_manual_key_rejects_annotated_handler_in_english_module():
    i18n.set_lang("en")
    found = _lint({"Key.yaml": _yaml("True", english=True), "Key.xbsl": _handler(english=True)})
    assert len(found) == 1
    assert (found[0].line, found[0].col) == (2, 8)
    assert "CheckHasAccessKeys" in found[0].message


def test_unannotated_method_and_comment_are_not_a_handler():
    source = "// ПроверитьНаличиеКлючейДоступа\n" + _handler(annotation=False)
    assert _lint({"Key.yaml": _yaml("Истина"), "Key.xbsl": source}) == []


def test_object_module_handler_does_not_satisfy_computed_key():
    found = _lint({"Key.yaml": _yaml("False", english=True), "Key.Object.xbsl": _handler()})
    assert len(found) == 1
    assert found[0].path == "Key.yaml"


def test_default_computed_key_with_parameter_needs_manager_handler():
    found = _lint({"Key.yaml": _yaml(None, parameters=True)})
    assert len(found) == 1


def test_invalid_yaml_is_not_judged():
    assert _lint({"Key.yaml": "ВидЭлемента: КлючДоступа\n  РучнаяВыдача: Ложь\n"}) == []


def test_invalid_manual_grant_value_is_not_judged():
    assert _lint({"Key.yaml": _yaml(None) + "РучнаяВыдача: {}\n"}) == []
