"""The handler must match the event of the component (form/handler-signature).

The defect the rule was written for cost a full deploy cycle: a checkbox handler declared
`OnChangeEvent<Boolean>` where the component passes `OnChangeEvent<Boolean?>`, the linter
said nothing, and the server compilation refused the method as not satisfying the
signature - the project rolled back to the previous build.

The second defect cost another one: a hover handler of a label took `Label` as the source,
while `OnHover` is declared on the base `Component` and passes any component. The click
handler of the same label takes `Label` legally - its delegate names the label itself. So a
parameter may repeat the type of the delegate or take its ancestor, never a descendant.

The slice is narrow on purpose: arity is not judged (a standard column takes a documented
extra parameter), a base type is legal (one handler serves several components), a type the
catalog does not relate to the delegate's is not judged, an unsubstituted type parameter is
not judged. What is left is a narrowed type and the same type spelled with a different
argument.
"""

from xbsl import engine, i18n
from xbsl.cli import discover

RULE = "form/handler-signature"

_FORM = """ВидЭлемента: КомпонентИнтерфейса
Ид: aaaaaaaa-1111-2222-3333-444444444444
Имя: Форма
Тип: Форма
Содержимое:
    Тип: Группа
    Содержимое:
        -
{component}
"""


def _lint(tmp_path, component: str, module: str):
    (tmp_path / "Форма.yaml").write_text(
        _FORM.format(component=component), encoding="utf-8",
    )
    (tmp_path / "Форма.xbsl").write_text(module, encoding="utf-8")
    return [
        d for d in engine.run(discover([str(tmp_path)]), select={RULE}) if d.rule_id == RULE
    ]


_CHECKBOX = """            Тип: Флажок
            Имя: Флажок
            ПриИзменении: ФлажокИзменён"""


def _handler(params: str) -> str:
    return f"@Обработчик\nметод ФлажокИзменён({params})\n;\n"


def test_a_narrower_event_argument_is_reported(tmp_path):
    """The live case: the component passes a nullable value, the handler demands a plain one."""
    diags = _lint(
        tmp_path, _CHECKBOX,
        _handler("Источник: Флажок, Событие: СобытиеПриИзменении<Булево>"),
    )

    assert len(diags) == 1
    assert "ФлажокИзменён" in diags[0].message
    assert "СобытиеПриИзменении<Булево?>" in diags[0].message
    assert "ПриИзменении" in diags[0].message


def test_the_declared_signature_is_accepted(tmp_path):
    diags = _lint(
        tmp_path, _CHECKBOX,
        _handler("Источник: Флажок, Событие: СобытиеПриИзменении<Булево?>"),
    )

    assert diags == []


def test_a_base_type_is_legal(tmp_path):
    """One handler for several components declares the base types - the platform accepts it."""
    diags = _lint(
        tmp_path, _CHECKBOX,
        _handler("Источник: Компонент, Событие: СобытиеКомпонента"),
    )

    assert diags == []


def test_the_english_spelling_of_a_type_is_the_same_type(tmp_path):
    """Sources may be written in English: the comparison folds both spellings into one."""
    diags = _lint(
        tmp_path, _CHECKBOX,
        _handler("Источник: Флажок, Событие: СобытиеПриИзменении<Boolean?>"),
    )

    assert diags == []


def test_an_extra_parameter_is_not_a_finding(tmp_path):
    """Arity is not judged: a standard column legitimately takes the row data third."""
    diags = _lint(
        tmp_path, _CHECKBOX,
        _handler("Источник: Флажок, Событие: СобытиеПриИзменении<Булево?>, Данные: Строка"),
    )

    assert diags == []


_INPUT_STRING = """            Тип: ПолеВвода<Строка>
            Имя: Поле
            ПриИзменении: ПолеИзменено"""


def test_the_type_argument_of_the_component_is_substituted(tmp_path):
    """`ПолеВвода<Строка>` passes `СобытиеПриИзменении<Строка>`, not the raw type parameter."""
    diags = _lint(
        tmp_path, _INPUT_STRING,
        "@Обработчик\nметод ПолеИзменено(Источник: ПолеВвода<Строка>, "
        "Событие: СобытиеПриИзменении<Строка>)\n;\n",
    )

    assert diags == []


def test_a_wrong_argument_after_substitution_is_reported(tmp_path):
    diags = _lint(
        tmp_path, _INPUT_STRING,
        "@Обработчик\nметод ПолеИзменено(Источник: ПолеВвода<Строка>, "
        "Событие: СобытиеПриИзменении<Число>)\n;\n",
    )

    assert len(diags) == 1 and "СобытиеПриИзменении<Строка>" in diags[0].message


def test_an_unsubstituted_type_parameter_is_not_judged(tmp_path):
    """The yaml named no argument: what the compiler sees is not visible in the file."""
    component = """            Тип: ПолеВвода
            Имя: Поле
            ПриИзменении: ПолеИзменено"""
    diags = _lint(
        tmp_path, component,
        "@Обработчик\nметод ПолеИзменено(Источник: ПолеВвода<Строка>, "
        "Событие: СобытиеПриИзменении<Число>)\n;\n",
    )

    assert diags == []


def test_a_handler_the_module_does_not_have_is_another_rules_finding(tmp_path):
    diags = _lint(tmp_path, _CHECKBOX, "метод Другой()\n;\n")

    assert diags == []


_LABEL = """            Тип: Надпись
            Имя: Отметка
            {event}: Отметить"""


def _label(tmp_path, event: str, params: str):
    return _lint(
        tmp_path, _LABEL.format(event=event),
        f"@Обработчик\nметод Отметить({params})\n;\n",
    )


def test_a_narrowed_source_of_a_base_event_is_reported(tmp_path):
    """The live case: the hover of a label is declared on the base component and passes any."""
    diags = _label(tmp_path, "ПриНаведении", "Источник: Надпись, Событие: СобытиеКомпонента")

    assert len(diags) == 1
    message = diags[0].message
    assert "Отметить" in message
    assert "ПриНаведении(Источник: Компонент, Событие: СобытиеКомпонента)" in message
    assert "'Надпись' – наследник 'Компонент'" in message


def test_the_base_component_as_the_source_of_a_base_event_is_accepted(tmp_path):
    diags = _label(tmp_path, "ПриНаведении", "Источник: Компонент, Событие: СобытиеКомпонента")

    assert diags == []


def test_the_label_as_the_source_of_its_own_click_is_accepted(tmp_path):
    """The click of a label is declared on the label: its delegate passes the label itself."""
    diags = _label(tmp_path, "ПриНажатии", "Источник: Надпись, Событие: СобытиеПриНажатии")

    assert diags == []


def test_a_narrowed_event_parameter_is_reported(tmp_path):
    """The event object is narrowed the same way: a click event where any event is passed."""
    diags = _label(tmp_path, "ПриНаведении", "Источник: Компонент, Событие: СобытиеПриНажатии")

    assert len(diags) == 1
    assert "Параметр 2" in diags[0].message
    assert "'СобытиеПриНажатии' – наследник 'СобытиеКомпонента'" in diags[0].message


def test_a_nullable_narrowed_source_is_reported_by_its_head(tmp_path):
    """The mark of nullability does not widen the label into a component."""
    diags = _label(tmp_path, "ПриНаведении", "Источник: Надпись?, Событие: СобытиеКомпонента")

    assert len(diags) == 1
    assert "объявлен как 'Надпись?'" in diags[0].message
    assert "'Надпись' – наследник 'Компонент'" in diags[0].message


_FORM_EN = """ElementKind: InterfaceComponent
Id: aaaaaaaa-1111-2222-3333-444444444444
Name: Form
Type: Form
Content:
    Type: Group
    Content:
        -
{component}
"""


def _lint_en(tmp_path, component: str, module: str):
    (tmp_path / "Form.yaml").write_text(_FORM_EN.format(component=component), encoding="utf-8")
    (tmp_path / "Form.xbsl").write_text(module, encoding="utf-8")
    i18n.set_lang("en")
    return [
        d for d in engine.run(discover([str(tmp_path)]), select={RULE}) if d.rule_id == RULE
    ]


def test_an_english_narrowed_source_is_reported_in_the_english_spelling(tmp_path):
    """`Group` is read as the type: the compiler dictionary alone answers it with an adjective.

    The message spells the signature the way an English project writes it.
    """
    diags = _lint_en(
        tmp_path,
        "            Type: Group\n            Name: Panel\n            OnHover: Highlight",
        "method Highlight(Source: Group, Event: ComponentEvent)\n;\n",
    )

    assert len(diags) == 1
    assert "OnHover(Source: Component, Event: ComponentEvent)" in diags[0].message
    assert "'Group' is a descendant of 'Component'" in diags[0].message


def test_an_english_mismatch_names_the_event_the_component_and_the_type_in_english(tmp_path):
    """The schema keeps the event, the component and the delegate in Russian, and an English
    message printed them as they were: the reader of an English project met words their own
    sources do not use."""
    diags = _lint_en(
        tmp_path,
        "            Type: Checkbox\n            Name: Flag\n            OnChange: FlagChanged",
        "method FlagChanged(Source: Checkbox, Event: OnChangeEvent<Boolean>)\n;\n",
    )

    assert len(diags) == 1
    assert ("the 'OnChange' event of 'Checkbox' passes 'OnChangeEvent<Boolean?>'"
            in diags[0].message)
