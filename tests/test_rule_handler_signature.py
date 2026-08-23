"""The handler must match the event of the component (form/handler-signature).

The defect the rule was written for cost a full deploy cycle: a checkbox handler declared
`OnChangeEvent<Boolean>` where the component passes `OnChangeEvent<Boolean?>`, the linter
said nothing, and the server compilation refused the method as not satisfying the
signature - the project rolled back to the previous build.

The slice is narrow on purpose (reconnaissance over four corpora, 483 handlers): arity is
not judged (a standard column takes a documented extra parameter), a base type is not
judged (one handler serves several components), an unsubstituted type parameter is not
judged. What is left is the same type spelled with a different argument.
"""

from xbsl import engine
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
