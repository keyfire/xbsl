"""Comments of an element description the visual editor keeps or drops.

yaml/plain-comment reports a `#` comment: the environment writes the file out again from the
model and only a `##` documentation comment at the head of a documentable node survives.
yaml/doc-comment-misplaced reports a `##` block that stands where the reader does not look.

Which node is documentable comes from the metamodel (`IDocumentable`), which `Type` names a
component - from the ui schema and the type catalog, so the whole module needs the data bundle
(listed in conftest._DATA_DEPENDENT).
"""

import yaml

from xbsl import engine
from xbsl.cli import discover
from xbsl.rules import yaml_doc_comments

PLAIN = "yaml/plain-comment"
MISPLACED = "yaml/doc-comment-misplaced"


def _lint(tmp_path, text: str, rule: str = PLAIN, name: str = "КарточкаПробы.yaml"):
    (tmp_path / name).write_bytes(text.encode("utf-8"))
    return [d for d in engine.run(discover([str(tmp_path)]), select={rule}) if d.rule_id == rule]


def _fixed(text: str, diags) -> str:
    """The text with every offered fix applied, last first so the offsets stay valid."""
    for diag in sorted((d for d in diags if d.fix), key=lambda d: d.fix.start, reverse=True):
        text = text[: diag.fix.start] + diag.fix.new + text[diag.fix.end:]
    return text


_COMPONENT = """ВидЭлемента: КомпонентИнтерфейса
Ид: 33333333-3333-3333-3333-333333333333
Имя: КарточкаПробы
ОбластьВидимости: ВПодсистеме
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


def test_clean_component_is_silent(tmp_path):
    assert _lint(tmp_path, _COMPONENT) == []
    assert _lint(tmp_path, _COMPONENT, MISPLACED) == []


def test_head_of_file_comment_is_respelled(tmp_path):
    text = "# Карточка с заголовком.\n# Вторая строка.\n" + _COMPONENT
    diags = _lint(tmp_path, text)
    assert len(diags) == 1 and (diags[0].line, diags[0].col) == (1, 1)
    assert "замените `#` на `##`" in diags[0].message
    fixed = _fixed(text, diags)
    assert fixed.startswith("## Карточка с заголовком.\n## Вторая строка.\nВидЭлемента:")
    assert _lint(tmp_path, fixed) == [] and _lint(tmp_path, fixed, MISPLACED) == []


def test_comment_at_the_head_of_a_component_node_is_respelled(tmp_path):
    text = _COMPONENT.replace("    Тип: Группа\n", "    # Группа держит отступ.\n    Тип: Группа\n")
    diags = _lint(tmp_path, text)
    assert len(diags) == 1 and "замените `#` на `##`" in diags[0].message
    assert "    ## Группа держит отступ.\n    Тип: Группа\n" in _fixed(text, diags)


def test_comment_before_the_dash_steps_inside_the_item(tmp_path):
    text = _COMPONENT.replace(
        "        -\n            Тип: Надпись\n",
        "        # Заголовок карточки.\n        # Вторая строка.\n        -\n            Тип: Надпись\n",
    )
    diags = _lint(tmp_path, text)
    assert len(diags) == 1 and "внутрь узла" in diags[0].message
    fixed = _fixed(text, diags)
    assert (
        "        -\n            ## Заголовок карточки.\n            ## Вторая строка.\n"
        "            Тип: Надпись\n"
    ) in fixed
    assert yaml.safe_load(fixed) == yaml.safe_load(_COMPONENT)
    assert _lint(tmp_path, fixed) == [] and _lint(tmp_path, fixed, MISPLACED) == []


def test_comment_before_a_key_that_holds_a_component_steps_inside(tmp_path):
    text = _COMPONENT.replace(
        "    Содержимое:\n        -\n", "    Содержимое:\n        -\n"
    ).replace(
        "Наследует:\n    Тип: Группа\n    Содержимое:\n        -\n            Тип: Надпись\n"
        "            Значение: =Заголовок\n",
        "Наследует:\n    Тип: Группа\n    # Подвал группы.\n    Подвал:\n        Тип: Группа\n",
    )
    diags = _lint(tmp_path, text)
    assert len(diags) == 1 and diags[0].fix is not None
    assert "    Подвал:\n        ## Подвал группы.\n        Тип: Группа\n" in _fixed(text, diags)


def test_block_above_a_key_of_the_element_names_the_head_of_the_file(tmp_path):
    # What stands above `Inherits` describes the element, not the component under it.
    text = _COMPONENT.replace("Наследует:\n", "# Карточка с заголовком.\nНаследует:\n")
    diags = _lint(tmp_path, text)
    assert len(diags) == 1 and diags[0].fix is None
    assert "в первые строки файла" in diags[0].message


def test_comment_on_a_single_property_names_its_node(tmp_path):
    text = _COMPONENT.replace(
        "            Значение: =Заголовок\n",
        "            # Заголовок приходит свойством.\n            Значение: =Заголовок\n",
    )
    diags = _lint(tmp_path, text)
    assert len(diags) == 1 and diags[0].fix is None
    assert "в строке 9" in diags[0].message  # the first key of the label node


def test_property_declaration_holds_a_comment(tmp_path):
    text = _COMPONENT.replace(
        "        Имя: Заголовок\n", "        # Текст заголовка.\n        Имя: Заголовок\n"
    )
    diags = _lint(tmp_path, text)
    assert len(diags) == 1 and "замените `#` на `##`" in diags[0].message


def test_command_has_no_slot(tmp_path):
    text = _COMPONENT.replace(
        "    Содержимое:\n",
        "    Команды:\n        Тип: ФрагментКомандногоИнтерфейса\n        Элементы:\n"
        "            -\n                # Команда обновления.\n"
        "                Тип: ОбычнаяКоманда\n                Обработчик: Обновить\n"
        "    Содержимое:\n",
    )
    diags = _lint(tmp_path, text)
    assert len(diags) == 1 and diags[0].fix is None
    assert "в строке 6" in diags[0].message  # the enclosing group, the fragment has no slot either


def test_project_component_is_a_slot(tmp_path):
    # A name the platform does not know is a component the project declares.
    text = _COMPONENT.replace(
        "            Тип: Надпись\n", "            # Строка пробы.\n            Тип: СтрокаПробы\n"
    )
    diags = _lint(tmp_path, text)
    assert len(diags) == 1 and "замените `#` на `##`" in diags[0].message


def test_trailing_comment_is_reported_without_a_fix(tmp_path):
    text = _COMPONENT.replace("    Тип: Группа\n", "    Тип: Группа  # корневая группа\n")
    diags = _lint(tmp_path, text)
    assert len(diags) == 1 and diags[0].fix is None


_CATALOG = """ВидЭлемента: Справочник
Ид: 44444444-4444-4444-4444-444444444444
Имя: ТоварыПробы
ОбластьВидимости: ВПроекте
Реквизиты:
    -
        Имя: Наименование
        Длина: 150
    -
        Ид: 44444444-4444-4444-4444-444444444445
        Имя: Артикул
        Тип: Строка
ТабличныеЧасти:
    -
        Ид: 44444444-4444-4444-4444-444444444446
        Имя: Упаковки
        Реквизиты:
            -
                Ид: 44444444-4444-4444-4444-444444444447
                Имя: Вес
                Тип: Число
"""


def test_ordinary_catalog_attribute_holds_a_comment(tmp_path):
    text = _CATALOG.replace(
        "    -\n        Ид: 44444444-4444-4444-4444-444444444445\n",
        "    # Артикул поставщика.\n    -\n        Ид: 44444444-4444-4444-4444-444444444445\n",
    )
    diags = _lint(tmp_path, text, name="ТоварыПробы.yaml")
    assert len(diags) == 1 and diags[0].fix is not None
    fixed = _fixed(text, diags)
    assert "    -\n        ## Артикул поставщика.\n        Ид: 44444444-4444-4444-4444-444444444445\n" in fixed
    assert _lint(tmp_path, fixed, name="ТоварыПробы.yaml") == []


def test_standard_catalog_attribute_has_no_slot(tmp_path):
    # The built-in item is picked by its name: that class holds no documentation comment.
    text = _CATALOG.replace(
        "    -\n        Имя: Наименование\n",
        "    # Название товара в каталоге.\n    -\n        Имя: Наименование\n",
    )
    diags = _lint(tmp_path, text, name="ТоварыПробы.yaml")
    assert len(diags) == 1 and diags[0].fix is None
    assert "в первые строки файла" in diags[0].message
    inside = _CATALOG.replace(
        "        Имя: Наименование\n", "        ## Название товара.\n        Имя: Наименование\n"
    )
    assert len(_lint(tmp_path, inside, MISPLACED, name="ТоварыПробы.yaml")) == 1


def test_tabular_section_and_its_attribute_hold_comments(tmp_path):
    text = _CATALOG.replace(
        "    -\n        Ид: 44444444-4444-4444-4444-444444444446\n",
        "    # Упаковки товара.\n    -\n        Ид: 44444444-4444-4444-4444-444444444446\n",
    ).replace(
        "                Ид: 44444444-4444-4444-4444-444444444447\n",
        "                # Вес брутто.\n                Ид: 44444444-4444-4444-4444-444444444447\n",
    )
    diags = _lint(tmp_path, text, name="ТоварыПробы.yaml")
    assert len(diags) == 2 and all(d.fix for d in diags)
    fixed = _fixed(text, diags)
    assert "    -\n        ## Упаковки товара.\n        Ид: 44444444-4444-4444-4444-444444444446\n" in fixed
    assert "                ## Вес брутто.\n" in fixed
    assert yaml.safe_load(fixed) == yaml.safe_load(_CATALOG)


def test_doc_comment_in_its_slot_is_silent(tmp_path):
    text = "## Карточка с заголовком.\n" + _COMPONENT.replace(
        "    Тип: Группа\n", "    ## Группа держит отступ.\n    Тип: Группа\n"
    )
    assert _lint(tmp_path, text, MISPLACED) == []
    assert _lint(tmp_path, text) == []


def test_doc_comment_before_the_dash_is_misplaced(tmp_path):
    text = _COMPONENT.replace(
        "        -\n            Тип: Надпись\n",
        "        ## Заголовок карточки.\n        -\n            Тип: Надпись\n",
    )
    diags = _lint(tmp_path, text, MISPLACED)
    assert len(diags) == 1 and "внутрь узла" in diags[0].message
    fixed = _fixed(text, diags)
    assert "        -\n            ## Заголовок карточки.\n            Тип: Надпись\n" in fixed
    assert _lint(tmp_path, fixed, MISPLACED) == []


def test_doc_comment_on_a_single_property_is_misplaced(tmp_path):
    text = _COMPONENT.replace(
        "            Значение: =Заголовок\n",
        "            ## Заголовок приходит свойством.\n            Значение: =Заголовок\n",
    )
    diags = _lint(tmp_path, text, MISPLACED)
    assert len(diags) == 1 and diags[0].fix is None


def test_english_spelling_is_judged_the_same(tmp_path):
    text = (
        "# A card with a title.\n"
        "ElementKind: InterfaceComponent\n"
        "Id: 33333333-3333-3333-3333-333333333333\n"
        "Name: ProbeCard\n"
        "Inherits:\n"
        "    Type: Group\n"
        "    Content:\n"
        "        # The title of the card.\n"
        "        -\n"
        "            Type: Label\n"
        "            # The value comes as a property.\n"
        "            Value: =Title\n"
        "Properties:\n"
        "    -\n"
        "        # The text of the title.\n"
        "        Name: Title\n"
        "        Type: String\n"
    )
    diags = _lint(tmp_path, text, name="ProbeCard.yaml")
    assert [(d.line, d.fix is not None) for d in diags] == [(1, True), (8, True), (11, False), (15, True)]


def test_crlf_file_keeps_its_line_ends(tmp_path):
    text = _COMPONENT.replace(
        "        -\n            Тип: Надпись\n",
        "        # Заголовок карточки.\n        -\n            Тип: Надпись\n",
    ).replace("\n", "\r\n")
    diags = _lint(tmp_path, text)
    fixed = _fixed(text, diags)
    assert "\n" not in fixed.replace("\r\n", "")
    assert "        -\r\n            ## Заголовок карточки.\r\n            Тип: Надпись\r\n" in fixed


def test_silent_when_the_metamodel_knows_no_documentation_comments(tmp_path, monkeypatch):
    monkeypatch.setattr(yaml_doc_comments, "_documentable_known", lambda: False)
    assert _lint(tmp_path, "# Карточка с заголовком.\n" + _COMPONENT) == []
