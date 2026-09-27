"""A list that never loads the tail (yaml/list-scroll-without-loading).

A list takes its rows in portions and asks for the next one only when `Navigation` says so;
with `None` it never does, while `VerticalScroll` keeps scrolling the loaded portion alone.
The rule flags that pair, and a list over an array without a scroll of its own that keeps the
automatic portion of ten rows (no `PageSize`, or `Auto`). It leaves alone another navigation
value, an expression, a page size the author chose, a tree source (it always loads on
scroll) and a dynamic list without a scroll (whether it is hierarchical is not in the file).

The rule reads which components are list-like from the ui schema, so the whole module needs
the data bundle (listed in conftest._DATA_DEPENDENT).
"""

from xbsl import engine
from xbsl.cli import discover

RULE = "yaml/list-scroll-without-loading"


def _lint(tmp_path, text: str, name: str = "ФормаПробы.yaml"):
    (tmp_path / name).write_text(text, encoding="utf-8")
    return [
        d for d in engine.run(discover([str(tmp_path)]), select={RULE}) if d.rule_id == RULE
    ]


_FORM = """ВидЭлемента: КомпонентИнтерфейса
Ид: 33333333-3333-3333-3333-333333333333
Имя: ФормаПробы
Наследует:
    Тип: Форма
    Содержимое:
        Тип: ПроизвольныйСписок<ИсточникДанныхМассив<СтрокаПробы>>
        Имя: СписокПробы
{properties}
"""


def _form(properties: dict[str, str]) -> str:
    body = "\n".join("        %s: %s" % pair for pair in properties.items())
    return _FORM.format(properties=body)


def test_scrolled_list_without_loading_is_reported(tmp_path):
    diags = _lint(tmp_path, _form({"ПрокруткаПоВертикали": "Истина", "Навигация": "Отсутствует"}))
    assert len(diags) == 1
    assert "ПодгрузкаПриПрокрутке" in diags[0].message


def test_qualified_navigation_value_is_reported(tmp_path):
    diags = _lint(
        tmp_path,
        _form({"ПрокруткаПоВертикали": "Истина", "Навигация": "НавигацияВСписке.Отсутствует"}),
    )
    assert len(diags) == 1


def test_scroll_by_binding_is_reported(tmp_path):
    # A form that scrolls on the desktop and lets the page scroll on a phone still scrolls.
    diags = _lint(
        tmp_path,
        _form({"ПрокруткаПоВертикали": "=не Общее.Мобильный()", "Навигация": "Отсутствует"}),
    )
    assert len(diags) == 1


def test_english_spelling_is_reported(tmp_path):
    text = """ElementKind: InterfaceComponent
Ид: 44444444-4444-4444-4444-444444444444
Name: ФормаПробы
Inherits:
    Type: Form
    Content:
        Type: Table<ArrayDataSource<СтрокаПробы>>
        Name: СписокПробы
        VerticalScroll: True
        Navigation: None
"""
    diags = _lint(tmp_path, text)
    assert len(diags) == 1


def test_loading_on_scroll_is_silent(tmp_path):
    assert not _lint(
        tmp_path,
        _form({"ПрокруткаПоВертикали": "Истина", "Навигация": "ПодгрузкаПриПрокрутке"}),
    )


def test_page_switcher_is_silent(tmp_path):
    # The tail stays reachable by the buttons - a different question from data loss.
    assert not _lint(
        tmp_path,
        _form({"ПрокруткаПоВертикали": "Истина", "Навигация": "ПереключательСтраниц"}),
    )


def test_list_that_does_not_scroll_keeps_ten_rows(tmp_path):
    """The page scrolls around one portion: the automatic page size is ten rows. The cure
    changes the layout or needs the limit of the data, so there is no fix."""
    diags = _lint(tmp_path, _form({"ПрокруткаПоВертикали": "Ложь", "Навигация": "Отсутствует"}))
    assert len(diags) == 1
    assert "РазмерСтраницы" in diags[0].message and "десять" in diags[0].message
    assert diags[0].fix is None


def test_list_without_the_scroll_property_keeps_ten_rows(tmp_path):
    diags = _lint(tmp_path, _form({"Навигация": "Отсутствует"}))
    assert len(diags) == 1
    assert "не прокручивается сам" in diags[0].message


def test_automatic_page_size_written_out_counts_as_none(tmp_path):
    for size in ("Авто", "0"):
        assert len(_lint(tmp_path, _form({"Навигация": "Отсутствует", "РазмерСтраницы": size}))) == 1


def test_page_size_of_the_author_is_silent(tmp_path):
    for size in ("50", "=ПределЛенты()"):
        assert not _lint(tmp_path, _form({"Навигация": "Отсутствует", "РазмерСтраницы": size}))


def test_list_without_scroll_and_another_navigation_is_silent(tmp_path):
    for value in ("ПодгрузкаПриПрокрутке", "КнопкаПодгрузки", "ПереключательСтраниц"):
        assert not _lint(tmp_path, _form({"Навигация": value}))


def test_list_without_navigation_is_silent(tmp_path):
    # The default of the property is not None: the standard list documents a page switcher.
    assert not _lint(tmp_path, _form({"ПрокруткаПоВертикали": "Ложь"}))


def test_dynamic_list_without_scroll_is_not_judged(tmp_path):
    """A hierarchical dynamic list loads on scroll anyway, and by default the hierarchy is
    decided by the metadata of its main table - not visible in this file."""
    text = _FORM.replace(
        "ПроизвольныйСписок<ИсточникДанныхМассив<СтрокаПробы>>",
        "Таблица<ДинамическийСписок<ФормаПробы.ДанныеСтрокиСписка>>",
    ).format(properties="        Навигация: Отсутствует")
    assert not _lint(tmp_path, text)


def test_tree_source_is_not_judged(tmp_path):
    # With a tree source the navigation is always loading on scroll, whatever is written.
    tree = "СтандартныйСписок<ИсточникДанныхДерево<УзелДереваСДанными<СтрокаПробы, СтрокаПробы>>>"
    for properties in (
        {"Навигация": "Отсутствует"},
        {"ПрокруткаПоВертикали": "Истина", "Навигация": "Отсутствует"},
    ):
        text = _form(properties).replace(
            "ПроизвольныйСписок<ИсточникДанныхМассив<СтрокаПробы>>", tree,
        )
        assert not _lint(tmp_path, text)


def test_english_list_without_scroll_is_reported(tmp_path):
    text = """ElementKind: InterfaceComponent
Ид: 77777777-7777-7777-7777-777777777777
Name: ФормаПробы
Inherits:
    Type: Form
    Content:
        Type: CustomList<ArrayDataSource<СтрокаПробы>>
        Name: СписокПробы
        VerticalScroll: False
        Navigation: None
        PageSize: Auto
"""
    diags = _lint(tmp_path, text)
    assert len(diags) == 1
    assert diags[0].fix is None


def test_navigation_by_expression_is_silent(tmp_path):
    # A file rule cannot know the value; guessing it would be a false positive.
    assert not _lint(
        tmp_path,
        _form({"ПрокруткаПоВертикали": "Истина", "Навигация": "=Оформление.Навигация()"}),
    )


def test_project_component_is_not_judged(tmp_path):
    text = """ВидЭлемента: КомпонентИнтерфейса
Ид: 55555555-5555-5555-5555-555555555555
Имя: ФормаПробы
Наследует:
    Тип: Форма
    Содержимое:
        Тип: МояЛента
        Имя: ЛентаПробы
        ПрокруткаПоВертикали: Истина
        Навигация: Отсутствует
"""
    assert not _lint(tmp_path, text)


def test_fix_writes_the_loading_value(tmp_path):
    diags = _lint(tmp_path, _form({"ПрокруткаПоВертикали": "Истина", "Навигация": "Отсутствует"}))
    assert diags[0].fix is not None
    assert diags[0].fix.new == "ПодгрузкаПриПрокрутке"


def test_fix_keeps_the_qualifier(tmp_path):
    diags = _lint(
        tmp_path,
        _form({"ПрокруткаПоВертикали": "Истина", "Навигация": "НавигацияВСписке.Отсутствует"}),
    )
    assert diags[0].fix.new == "НавигацияВСписке.ПодгрузкаПриПрокрутке"


def test_fix_follows_the_english_spelling(tmp_path):
    text = """ElementKind: InterfaceComponent
Ид: 66666666-6666-6666-6666-666666666666
Name: ФормаПробы
Inherits:
    Type: Form
    Content:
        Type: Table<ArrayDataSource<СтрокаПробы>>
        Name: СписокПробы
        VerticalScroll: True
        Navigation: None
"""
    diags = _lint(tmp_path, text)
    assert diags[0].fix.new == "LoadingOnScroll"


def test_fix_lands_on_the_value_span(tmp_path):
    diags = _lint(tmp_path, _form({"ПрокруткаПоВертикали": "Истина", "Навигация": "Отсутствует"}))
    fix = diags[0].fix
    # Offsets index the text as the engine decoded it, newlines kept as written on disk.
    written = (tmp_path / "ФормаПробы.yaml").read_bytes().decode("utf-8")
    assert written[fix.start:fix.end] == "Отсутствует"
