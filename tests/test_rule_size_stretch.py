"""Checks of the yaml/size-needs-no-stretch rule (a fixed size without Растягивать*: Ложь)."""

from xbsl import engine

RULE = "yaml/size-needs-no-stretch"


def _lint(name, content, **kw):
    return engine.run_sources([engine.load_text(name, content)], **kw)


def _form(body: str) -> str:
    """A minimal interface yaml object with the given content."""
    return (
        "ВидЭлемента: КомпонентИнтерфейса\n"
        "Ид: 1e0e26f1-1111-4111-8111-111111111111\n"
        "Имя: Ф\n"
        "Наследует:\n"
        "    Тип: Группа\n"
        "    Компоновка: Вертикальная\n"
        "    Содержимое:\n"
        + body
    )


def test_off_by_default():
    content = _form(
        "        -\n"
        "            Тип: КонтейнерHtml\n"
        "            Высота: 480\n"
    )
    d = _lint("Ф.yaml", content)
    assert not any(x.rule_id == RULE for x in d)


def test_height_without_stretch_flagged():
    content = _form(
        "        -\n"
        "            Тип: КонтейнерHtml\n"
        "            Высота: 480\n"
    )
    d = _lint("Ф.yaml", content, select={RULE})
    assert len(d) == 1
    assert d[0].severity.value == "info"
    assert "РастягиватьПоВертикали" in d[0].message
    assert (d[0].line, d[0].col) == (10, 13)  # the line of the 'Высота' key


def test_height_with_stretch_false_ok():
    content = _form(
        "        -\n"
        "            Тип: КонтейнерHtml\n"
        "            Высота: 480\n"
        "            РастягиватьПоВертикали: Ложь\n"
    )
    assert _lint("Ф.yaml", content, select={RULE}) == []


def test_explicit_stretch_value_is_deliberate():
    # An explicitly written Авто/Истина is the author's deliberate choice, no hint given
    content = _form(
        "        -\n"
        "            Тип: КонтейнерHtml\n"
        "            Высота: 480\n"
        "            РастягиватьПоВертикали: Авто\n"
    )
    assert _lint("Ф.yaml", content, select={RULE}) == []


def test_width_without_stretch_flagged_separately():
    # The axes are independent: Ширина without РастягиватьПоГоризонтали is caught,
    # Высота with РастягиватьПоВертикали: Ложь is not
    content = _form(
        "        -\n"
        "            Тип: КонтейнерHtml\n"
        "            Высота: 56\n"
        "            РастягиватьПоВертикали: Ложь\n"
        "            Ширина: 320\n"
    )
    d = _lint("Ф.yaml", content, select={RULE})
    assert len(d) == 1
    assert "РастягиватьПоГоризонтали" in d[0].message


def test_both_axes_flagged():
    content = _form(
        "        -\n"
        "            Тип: КонтейнерHtml\n"
        "            Высота: 48\n"
        "            Ширина: 48\n"
    )
    d = _lint("Ф.yaml", content, select={RULE})
    assert len(d) == 2


def test_non_fixed_sizes_skipped():
    # Авто, a binding and zero are not a fixed size
    content = _form(
        "        -\n"
        "            Тип: КонтейнерHtml\n"
        "            Высота: Авто\n"
        "        -\n"
        "            Тип: КонтейнерHtml\n"
        "            Высота: =Общий.ЭтоМобильный()?330:320\n"
        "        -\n"
        "            Тип: КонтейнерHtml\n"
        "            Высота: 0\n"
    )
    assert _lint("Ф.yaml", content, select={RULE}) == []


def test_other_component_types_skipped():
    # Картинка/Группа/Надпись have an intrinsic size - Авто is reliable, not checked
    content = _form(
        "        -\n"
        "            Тип: Картинка\n"
        "            Высота: 44\n"
        "            Ширина: 44\n"
        "        -\n"
        "            Тип: Надпись\n"
        "            Ширина: 88\n"
    )
    assert _lint("Ф.yaml", content, select={RULE}) == []


def test_same_value_in_two_nodes_positions_only_violator():
    # The same value in two nodes: the position goes to the violating node specifically
    content = _form(
        "        -\n"
        "            Тип: КонтейнерHtml\n"
        "            Высота: 480\n"
        "            РастягиватьПоВертикали: Ложь\n"
        "        -\n"
        "            Тип: КонтейнерHtml\n"
        "            Высота: 480\n"
    )
    d = _lint("Ф.yaml", content, select={RULE})
    assert len(d) == 1
    assert (d[0].line, d[0].col) == (14, 13)


def test_crlf_positions():
    content = _form(
        "        -\n"
        "            Тип: КонтейнерHtml\n"
        "            Высота: 480\n"
    ).replace("\n", "\r\n")
    d = _lint("Ф.yaml", content, select={RULE})
    assert len(d) == 1
    assert (d[0].line, d[0].col) == (10, 13)


def test_non_object_yaml_skipped():
    # A file without ВидЭлемента (structural) is not checked
    content = (
        "Имя: Фрагмент\n"
        "Содержимое:\n"
        "    -\n"
        "        Тип: КонтейнерHtml\n"
        "        Высота: 480\n"
    )
    assert _lint("Фрагмент.yaml", content, select={RULE}) == []


def test_xbsl_file_skipped():
    assert _lint("М.xbsl", "метод Ф()\n;\n", select={RULE}) == []


# --- yaml/matrix-group-max-width --------------------------------------------------------

MATRIX_RULE = "yaml/matrix-group-max-width"


def test_a_numeric_maximum_on_a_matrix_group_is_reported():
    """The live case: on a phone the row lays out by the maximum, and the root overflows."""
    body = (
        "        -\n"
        "            Тип: Группа\n"
        "            Компоновка: Матричная\n"
        "            МаксимальнаяШирина: 2000\n"
    )
    d = _lint("Ф.yaml", _form(body), select={MATRIX_RULE})
    assert [(x.rule_id, x.line) for x in d] == [(MATRIX_RULE, 11)]
    assert "2000" in d[0].message


def test_the_matrix_settings_block_marks_the_group_too():
    """A group may name the matrix layout through its settings rather than the value."""
    body = (
        "        -\n"
        "            Тип: Группа\n"
        "            МаксимальнаяШирина: 1200\n"
        "            НастройкиМатричнойКомпоновки:\n"
        "                ОписаниеАвтоматическихКолонок:\n"
        "                    МинимальнаяШирина: 260\n"
    )
    d = _lint("Ф.yaml", _form(body), select={MATRIX_RULE})
    assert len(d) == 1


def test_auto_and_bindings_are_the_cure_not_the_defect():
    for value in ("Авто", "=СтильСайта.ШиринаКонтента()"):
        body = (
            "        -\n"
            "            Тип: Группа\n"
            "            Компоновка: Матричная\n"
            f"            МаксимальнаяШирина: {value}\n"
        )
        assert _lint("Ф.yaml", _form(body), select={MATRIX_RULE}) == [], value


def test_a_plain_group_keeps_its_maximum():
    body = (
        "        -\n"
        "            Тип: Группа\n"
        "            Компоновка: Вертикальная\n"
        "            МаксимальнаяШирина: 720\n"
    )
    assert _lint("Ф.yaml", _form(body), select={MATRIX_RULE}) == []


# --- yaml/card-literal-stretch-weight ---------------------------------------------------

CARD_RULE = "yaml/card-literal-stretch-weight"


def test_a_literal_weight_on_a_card_is_reported():
    body = (
        "        -\n"
        "            Тип: СтандартнаяКарточка\n"
        "            ВесПриРастягивании: 1\n"
    )
    d = _lint("Ф.yaml", _form(body), select={CARD_RULE})
    assert [(x.rule_id, x.line) for x in d] == [(CARD_RULE, 10)]
    assert "СтандартнаяКарточка" in d[0].message


def test_an_inner_column_of_a_card_is_reported_as_well():
    """The cure had to cover the inner columns too - so they are judged."""
    body = (
        "        -\n"
        "            Тип: СтандартнаяКарточка\n"
        "            Содержимое:\n"
        "                Тип: Группа\n"
        "                Компоновка: Вертикальная\n"
        "                ВесПриРастягивании: 1\n"
    )
    d = _lint("Ф.yaml", _form(body), select={CARD_RULE})
    assert len(d) == 1 and d[0].line == 13


def test_a_label_inside_a_card_keeps_its_weight():
    """Reconnaissance: a live project carries literal weights on labels inside cards - a
    text sharing the width of its row, which the collapse does not touch."""
    body = (
        "        -\n"
        "            Тип: СтандартнаяКарточка\n"
        "            Содержимое:\n"
        "                Тип: Надпись\n"
        "                Значение: Текст\n"
        "                ВесПриРастягивании: 1\n"
    )
    assert _lint("Ф.yaml", _form(body), select={CARD_RULE}) == []


def test_a_group_outside_any_card_keeps_its_weight():
    body = (
        "        -\n"
        "            Тип: Группа\n"
        "            Компоновка: Вертикальная\n"
        "            ВесПриРастягивании: 1\n"
    )
    assert _lint("Ф.yaml", _form(body), select={CARD_RULE}) == []


def test_a_binding_weight_is_the_cure():
    body = (
        "        -\n"
        "            Тип: СтандартнаяКарточка\n"
        "            ВесПриРастягивании: =Общее.ЭтоМобильный()?Авто:1\n"
    )
    assert _lint("Ф.yaml", _form(body), select={CARD_RULE}) == []


def test_both_mobile_rules_are_off_by_default():
    for rule_id in (MATRIX_RULE, CARD_RULE):
        info = next(r for r in engine.RULES if r.id == rule_id)
        assert info.enabled_by_default is False, rule_id
        assert info.off_reason, rule_id
