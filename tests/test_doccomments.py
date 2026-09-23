"""Documentation comment edits target only platform-supported YAML node heads."""

import pytest

from xbsl import doccomments

pytestmark = pytest.mark.needs_data


ROOT = """ВидЭлемента: КомпонентИнтерфейса
Наследует:
    Тип: Группа
    Содержимое:
        -
            Тип: Надпись
            Значение: =Заголовок
Свойства:
    -
        Имя: Заголовок
        Тип: Строка
"""

CATALOG = """ВидЭлемента: Справочник
Ид: 44444444-4444-4444-4444-444444444444
Имя: ТоварыПробы
Реквизиты:
    -
        Имя: Наименование
        Длина: 150
    -
        Ид: 44444444-4444-4444-4444-444444444445
        Имя: Артикул
        Тип: Строка
"""


def _apply(text: str, result: dict) -> str:
    assert not result.get("error"), result
    for edit in reversed(result["edits"]):
        text = text[:edit["start"]] + edit["newText"] + text[edit["end"]:]
    return text


def test_root_edit_preserves_bom_crlf_and_other_comments():
    text = "\ufeff" + ROOT.replace("\n", "\r\n").replace("Наследует:", "# Ordinary\r\nНаследует:")
    current = doccomments.inspect(text, 1)
    assert current.supported and current.text == ""
    out = _apply(text, doccomments.plan(text, 1, "# Heading\n\nText"))
    assert out.startswith("\ufeff## # Heading\r\n##\r\n## Text\r\nВидЭлемента:")
    assert "# Ordinary\r\nНаследует:" in out
    assert doccomments.inspect(out, 1).text == "# Heading\n\nText"
    assert _apply(out, doccomments.plan(out, 1, "", "# Heading\n\nText")) == text


def test_component_and_named_declaration_round_trip():
    form_offset = ROOT.index("    Тип: Группа")
    form = _apply(ROOT, doccomments.plan(ROOT, form_offset, "Group **bold**"))
    assert "Наследует:\n    ## Group **bold**\n    Тип: Группа" in form
    item_offset = form.index("        Имя: Заголовок")
    edited = _apply(form, doccomments.plan(form, item_offset, "A [link](https://example.com)"))
    assert "    -\n        ## A [link](https://example.com)\n        Имя: Заголовок" in edited
    assert doccomments.inspect(edited, edited.index("        Имя: Заголовок")).text == "A [link](https://example.com)"


def test_unsupported_property_and_stale_value():
    offset = ROOT.index("            Значение:")
    assert not doccomments.inspect(ROOT, offset).supported
    assert doccomments.plan(ROOT, 0, "new", "old")["error"]


def test_inline_list_entry_moves_first_key_after_dash():
    source = ROOT.replace("        -\n            Тип: Надпись\n            Значение:", "        - Тип: Надпись\n          Значение:")
    offset = source.index("Тип: Надпись")
    edited = _apply(source, doccomments.plan(source, offset, "Label"))
    assert "        -\n          ## Label\n          Тип: Надпись" in edited
    assert doccomments.inspect(edited, edited.index("Тип: Надпись")).text == "Label"


def test_metadata_named_item_is_supported_but_built_in_item_is_not():
    built_in = CATALOG.index("Имя: Наименование")
    named = CATALOG.index("Ид: 44444444-4444-4444-4444-444444444445")
    assert not doccomments.inspect(CATALOG, built_in).supported
    assert doccomments.inspect(CATALOG, named).supported
    edited = _apply(CATALOG, doccomments.plan(CATALOG, named, "Supplier identifier"))
    assert "        ## Supplier identifier\n        Ид: 44444444-4444-4444-4444-444444444445" in edited


def test_emoji_in_root_comment_and_before_nested_comment():
    root = "## 😀 original\n" + ROOT
    change = doccomments.plan(root, root.index("ВидЭлемента:"), "Updated")
    assert change["offsetEncoding"] == "unicode-codepoint"
    assert _apply(root, change) == "## Updated\n" + ROOT

    nested = ROOT.replace("Наследует:", "Имя: 😀 Card\nНаследует:").replace(
        "    Тип: Группа", "    ## Earlier\n    Тип: Группа",
    )
    offset = nested.index("    Тип: Группа")
    edit = doccomments.plan(nested, offset, "Later")
    assert _apply(nested, edit) == nested.replace("    ## Earlier", "    ## Later")
