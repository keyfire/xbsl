"""A scrolled list that never loads the tail (yaml/list-scroll-without-loading).

A list takes its rows in portions and asks for the next one only when `Navigation` says so;
with `None` it never does, while `VerticalScroll` keeps scrolling the loaded portion alone.
The rule flags that pair and leaves alone the shapes where nothing promises a scroll: the
property absent, the scroll explicitly off, another navigation value, an expression.

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


def test_list_that_does_not_scroll_is_silent(tmp_path):
    assert not _lint(tmp_path, _form({"ПрокруткаПоВертикали": "Ложь", "Навигация": "Отсутствует"}))


def test_list_without_the_scroll_property_is_silent(tmp_path):
    assert not _lint(tmp_path, _form({"Навигация": "Отсутствует"}))


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
