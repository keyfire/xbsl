"""Checks of the yaml/choice-needs-static-list rule (no platform data needed)."""

from xbsl import engine

_SELECT = {"yaml/choice-needs-static-list"}


def _lint(content, name="Форма.yaml"):
    return engine.run_sources([engine.load_text(name, content)], select=_SELECT)


def _wrap(*components):
    """A form object with the given components in Содержимое."""
    body = "".join(components)
    return (
        "ВидЭлемента: КомпонентИнтерфейса\n"
        "Ид: 11111111-2222-3333-4444-555555555555\n"
        "Имя: Форма\n"
        "Интерфейс:\n"
        "    Тип: Форма\n"
        "    Содержимое:\n" + body
    )


_CHOICE_WITH_LIST = (
    "        -\n"
    "            Тип: ВыборЗначения<Строка>\n"
    "            Имя: ВыборВариант\n"
    "            Значение: =ВариантТекст\n"
    "            СписокВыбора:\n"
    "                Тип: Массив<Строка|ЭлементСпискаЗначений<Строка>>\n"
    "                Значение:\n"
    "                    - Первый\n"
    "                    - Второй\n"
)

_CHOICE_WITHOUT_LIST = (
    "        -\n"
    "            Тип: ВыборЗначения<Строка>\n"
    "            Имя: ВыборРоль\n"
    "            Значение: =РольТекст\n"
)


def test_missing_list_flagged_with_position():
    d = _lint(_wrap(_CHOICE_WITHOUT_LIST))
    assert len(d) == 1
    assert d[0].rule_id == "yaml/choice-needs-static-list"
    # The position is the line of the `Тип: ВыборЗначения<Строка>` node (8th), the value column.
    assert d[0].line == 8
    assert "СписокВыбора" in d[0].message


def test_static_list_ok():
    assert _lint(_wrap(_CHOICE_WITH_LIST)) == []


def test_mixed_nodes_only_bare_one_flagged():
    # Two identical types: with a list and without - only the second is caught, at its own position.
    d = _lint(_wrap(_CHOICE_WITH_LIST, _CHOICE_WITHOUT_LIST))
    assert len(d) == 1
    assert d[0].line == 17  # the node without a list comes after the node with one


def test_binding_value_counts_as_present():
    # СписокВыбора as a binding - the key is present, the content is not checked.
    content = _wrap(
        "        -\n"
        "            Тип: ВыборЗначения<Строка>\n"
        "            СписокВыбора: =Варианты\n"
    )
    assert _lint(content) == []


def test_enum_and_project_types_skipped():
    # A non-primitive parameter (an enum/project type) - the platform builds the list itself.
    content = _wrap(
        "        -\n"
        "            Тип: ВыборЗначения<ВидТовара>\n"
        "        -\n"
        "            Тип: ВыборЗначения<Массив<ВидТовара>>\n"
    )
    assert _lint(content) == []


def test_bare_and_nullable_variants():
    # A bare ВыборЗначения is skipped (the type is unknown); a nullable primitive - a diagnostic.
    content = _wrap(
        "        -\n"
        "            Тип: ВыборЗначения\n"
        "        -\n"
        "            Тип: ВыборЗначения<Строка?>\n"
        "        -\n"
        "            Тип: ВыборЗначения<Число|?>\n"
    )
    d = _lint(content)
    assert [x.line for x in d] == [10, 12]


def test_array_primitive_flagged():
    d = _lint(_wrap(
        "        -\n"
        "            Тип: ВыборЗначения<Массив<Строка>>\n"
    ))
    assert len(d) == 1


def test_non_object_yaml_skipped():
    # A file without ВидЭлемента (structural) is not checked.
    content = "Имя: Проект\nСодержимое:\n    - Тип: ВыборЗначения<Строка>\n"
    assert _lint(content) == []


def test_crlf_position():
    content = _wrap(_CHOICE_WITHOUT_LIST).replace("\n", "\r\n")
    d = _lint(content)
    assert len(d) == 1 and d[0].line == 8


def test_off_when_not_selected_by_default_run():
    # The rule is on by default - it fires without select too.
    d = engine.run_sources([engine.load_text("Форма.yaml", _wrap(_CHOICE_WITHOUT_LIST))],
                           select={"yaml"})
    assert any(x.rule_id == "yaml/choice-needs-static-list" for x in d)
