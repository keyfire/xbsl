"""Проверки правила yaml/size-needs-no-stretch (фикс. размер без Растягивать*: Ложь)."""

from xbsllint import engine

RULE = "yaml/size-needs-no-stretch"


def _lint(name, content, **kw):
    return engine.run_sources([engine.load_text(name, content)], **kw)


def _form(body: str) -> str:
    """Минимальный yaml-объект интерфейса с заданным содержимым."""
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
    assert (d[0].line, d[0].col) == (10, 13)  # строка ключа 'Высота'


def test_height_with_stretch_false_ok():
    content = _form(
        "        -\n"
        "            Тип: КонтейнерHtml\n"
        "            Высота: 480\n"
        "            РастягиватьПоВертикали: Ложь\n"
    )
    assert _lint("Ф.yaml", content, select={RULE}) == []


def test_explicit_stretch_value_is_deliberate():
    # Явно записанные Авто/Истина – осознанный выбор автора, не подсказываем
    content = _form(
        "        -\n"
        "            Тип: КонтейнерHtml\n"
        "            Высота: 480\n"
        "            РастягиватьПоВертикали: Авто\n"
    )
    assert _lint("Ф.yaml", content, select={RULE}) == []


def test_width_without_stretch_flagged_separately():
    # Оси независимы: Ширина без РастягиватьПоГоризонтали ловится,
    # Высота с РастягиватьПоВертикали: Ложь – нет
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
    # Авто, привязка и ноль – не фиксированный размер
    content = _form(
        "        -\n"
        "            Тип: КонтейнерHtml\n"
        "            Высота: Авто\n"
        "        -\n"
        "            Тип: КонтейнерHtml\n"
        "            Высота: =ОбщееКлиент.ЭтоМобильный()?330:320\n"
        "        -\n"
        "            Тип: КонтейнерHtml\n"
        "            Высота: 0\n"
    )
    assert _lint("Ф.yaml", content, select={RULE}) == []


def test_other_component_types_skipped():
    # У Картинка/Группа/Надпись собственный размер – Авто надёжен, не проверяем
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
    # Одинаковое значение в двух узлах: позицию получает именно узел-нарушитель
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
    # Файл без ВидЭлемента (структурный) не проверяется
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
