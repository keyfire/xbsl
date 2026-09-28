"""A list that never loads the tail (yaml/list-scroll-without-loading and its project half,
yaml/dynlist-scroll-without-loading).

A list takes its rows in portions and asks for the next one only when `Navigation` says so;
with `None` it never does, while `VerticalScroll` keeps scrolling the loaded portion alone.
The rule flags that pair, and a list over an array without a scroll of its own that keeps the
automatic portion of ten rows (no `PageSize`, or `Auto`). It leaves alone another navigation
value, an expression, a page size the author chose and a tree source (it always loads on
scroll).

A hierarchical dynamic list always loads on scroll too, and whether it is hierarchical is
said by its `UsedHierarchy`: the typed `Disabled` settles it in the file, `Auto` (or nothing
written) leaves it to the main table - the project half reads the catalog yaml for that. The
tests below build small projects: a catalog with and without a hierarchy, and a list with
each spelling of the property.

The rule reads which components are list-like from the ui schema, so the whole module needs
the data bundle (listed in conftest._DATA_DEPENDENT).
"""

import pytest

from xbsl import engine
from xbsl.cli import discover

RULE = "yaml/list-scroll-without-loading"
TABLE_RULE = "yaml/dynlist-scroll-without-loading"


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


def test_dynamic_list_declared_elsewhere_is_not_judged(tmp_path):
    """A hierarchical dynamic list loads on scroll anyway, and a list with no declaration in
    the file (built in code) says nothing about its hierarchy - neither half judges it."""
    for properties in (
        "        Навигация: Отсутствует",
        "        ПрокруткаПоВертикали: Истина\n        Навигация: Отсутствует",
    ):
        text = _FORM.replace(
            "ПроизвольныйСписок<ИсточникДанныхМассив<СтрокаПробы>>",
            "Таблица<ДинамическийСписок<ФормаПробы.ДанныеСтрокиСписка>>",
        ).format(properties=properties)
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


# --- a dynamic list: its hierarchy decides -----------------------------------------------

_SCROLLED = "        ПрокруткаПоВертикали: Истина\n        Навигация: Отсутствует\n"
_NOT_SCROLLED = "        Навигация: Отсутствует\n"


def _catalog(extra: str = "", name: str = "Склады", kind: str = "Справочник") -> str:
    """An element description; `extra` adds top-level lines (a hierarchy of a catalog)."""
    return (
        f"ВидЭлемента: {kind}\n"
        "Ид: 88888888-8888-8888-8888-888888888888\n"
        f"Имя: {name}\n"
        "ОбластьВидимости: ВПроекте\n"
        + extra
    )


def _bound_form(component: str = _SCROLLED, table: str = "Склады", declaration: str = "",
                row_type: str = "ФормаПробы.СтрокаСписка") -> str:
    """A form whose table binds its source to a property, the way a list form declares its
    list: `Source: =Список` and the declaration in the default value of that property."""
    return (
        "ВидЭлемента: КомпонентИнтерфейса\n"
        "Ид: 99999999-9999-9999-9999-999999999999\n"
        "Имя: ФормаПробы\n"
        "Наследует:\n"
        "    Тип: Форма\n"
        "    Содержимое:\n"
        f"        Тип: Таблица<ДинамическийСписок<{row_type}>>\n"
        "        Имя: ТаблицаПробы\n"
        "        Источник: =Список\n"
        + component
        + "Свойства:\n"
        "    -\n"
        "        Имя: Список\n"
        f"        Тип: ДинамическийСписок<{row_type}>\n"
        "        ЗначениеПоУмолчанию:\n"
        "            ИмяТипаДанныхСтроки: СтрокаСписка\n"
        "            ОсновнаяТаблица:\n"
        f"                Таблица: {table}\n"
        + declaration
    )


def _inline_form(component: str = _SCROLLED, table: str = "Склады") -> str:
    """A form whose table declares its dynamic list in place, in its own `Source`."""
    return (
        "ВидЭлемента: КомпонентИнтерфейса\n"
        "Ид: 99999999-9999-9999-9999-999999999999\n"
        "Имя: ФормаПробы\n"
        "Наследует:\n"
        "    Тип: Форма\n"
        "    Содержимое:\n"
        "        Тип: Таблица<ДинамическийСписок>\n"
        "        Имя: ТаблицаПробы\n"
        "        Источник:\n"
        "            ОсновнаяТаблица:\n"
        f"                Таблица: {table}\n"
        + component
    )


def _hierarchy(value: str) -> str:
    """`UsedHierarchy` inside the default value of the list property, a scalar as written."""
    return f"            ИспользуемаяИерархия: {value}\n"


#: The typed node of the platform's own examples - the one spelling that settles a flat list.
_TYPED_FLAT = (
    "            ИспользуемаяИерархия:\n"
    "                Тип: РежимИерархии\n"
    "                Значение: Выключено\n"
)
_HIERARCHICAL = "Иерархический: Истина\n"


def _run(tmp_path, files: dict[str, str]):
    """Both rules over a small project of its own - a fresh folder under `tmp_path` per call,
    so an element written for one case never answers for the next."""
    root = tmp_path / f"project{sum(1 for _ in tmp_path.iterdir())}"
    for name, text in files.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    root.mkdir(exist_ok=True)
    both = {RULE, TABLE_RULE}
    return [d for d in engine.run(discover([str(root)]), select=both) if d.rule_id in both]


def test_file_and_project_halves_keep_their_scopes():
    # The file half runs on every keystroke in the editor; only the table half waits for a save.
    scopes = {info.id: info.scope for info in engine.RULES}
    assert scopes[RULE] == "file"
    assert scopes[TABLE_RULE] == "project"


def test_list_over_a_catalog_without_hierarchy_is_reported(tmp_path):
    """`UsedHierarchy` not written is Auto: the catalog decides, and it declares no hierarchy."""
    diags = _run(tmp_path, {"Склады.yaml": _catalog(), "ФормаПробы.yaml": _bound_form()})
    assert [d.rule_id for d in diags] == [TABLE_RULE]
    assert "'Склады'" in diags[0].message and "ПодгрузкаПриПрокрутке" in diags[0].message
    assert diags[0].fix is not None and diags[0].fix.new == "ПодгрузкаПриПрокрутке"
    # The fix travels through the facts of the project rule; its offsets index the file text.
    written = next(tmp_path.rglob("ФормаПробы.yaml")).read_bytes().decode("utf-8")
    assert written[diags[0].fix.start:diags[0].fix.end] == "Отсутствует"


def test_list_over_a_hierarchical_catalog_is_silent(tmp_path):
    """The control of the test above: the same list over a catalog with a hierarchy always
    loads on scroll - the documentation of List.Navigation - and is not reported."""
    diags = _run(tmp_path, {
        "Склады.yaml": _catalog(_HIERARCHICAL), "ФормаПробы.yaml": _bound_form(),
    })
    assert diags == []


@pytest.mark.parametrize("extra", [
    _HIERARCHICAL,
    "ИерархияПоУмолчанию: СкладыПоВидам\n",
    "ДополнительныеИерархии:\n    -\n        Имя: СкладыПоВидам\n        ПолеРодителя: Вид\n",
    "Иерархия:\n    Вид: ИерархияЭлементов\n",
])
def test_any_declared_hierarchy_keeps_the_list_unjudged(tmp_path, extra):
    for component in (_SCROLLED, _NOT_SCROLLED):
        diags = _run(tmp_path, {
            "Склады.yaml": _catalog(extra), "ФормаПробы.yaml": _bound_form(component),
        })
        assert diags == [], extra


def test_hierarchical_flag_written_false_is_flat(tmp_path):
    diags = _run(tmp_path, {
        "Склады.yaml": _catalog("Иерархический: Ложь\n"), "ФормаПробы.yaml": _bound_form(),
    })
    assert [d.rule_id for d in diags] == [TABLE_RULE]


def test_list_the_page_scrolls_over_a_flat_catalog_keeps_ten_rows(tmp_path):
    diags = _run(tmp_path, {
        "Склады.yaml": _catalog(), "ФормаПробы.yaml": _bound_form(_NOT_SCROLLED),
    })
    assert [d.rule_id for d in diags] == [TABLE_RULE]
    assert "десять" in diags[0].message and "'Склады'" in diags[0].message
    assert diags[0].fix is None
    own_limit = _NOT_SCROLLED + "        РазмерСтраницы: 50\n"
    assert _run(tmp_path, {
        "Склады.yaml": _catalog(), "ФормаПробы.yaml": _bound_form(own_limit),
    }) == []


def test_file_alone_leaves_the_automatic_hierarchy_to_the_table(tmp_path):
    """Without the catalog the hierarchy is unknown: the file half no longer reports a scrolled
    dynamic list whose `UsedHierarchy` is left to the main table (it used to, whatever the
    table), and the project half does not guess either."""
    for declaration in ("", _hierarchy("Авто")):
        assert _run(tmp_path, {"ФормаПробы.yaml": _bound_form(declaration=declaration)}) == []


@pytest.mark.parametrize("value", ["Авто", "Выключено", "РежимИерархии.Выключено"])
def test_automatic_or_bare_value_is_left_to_the_table(tmp_path, value):
    """A bare word falls under the String member of the union and may be read as a hierarchy
    name; over a table without a hierarchy the list is flat whichever way it is read."""
    flat = _run(tmp_path, {
        "Склады.yaml": _catalog(), "ФормаПробы.yaml": _bound_form(declaration=_hierarchy(value)),
    })
    assert [d.rule_id for d in flat] == [TABLE_RULE]
    hierarchical = _run(tmp_path, {
        "Склады.yaml": _catalog(_HIERARCHICAL),
        "ФормаПробы.yaml": _bound_form(declaration=_hierarchy(value)),
    })
    assert hierarchical == []


def test_typed_disabled_hierarchy_is_judged_by_the_file(tmp_path):
    """The typed node settles the list flat in the file itself - even over a hierarchical
    catalog - so the file half reports it, with the fix, and the project half stays out."""
    for extra in ("", _HIERARCHICAL):
        diags = _run(tmp_path, {
            "Склады.yaml": _catalog(extra),
            "ФормаПробы.yaml": _bound_form(declaration=_TYPED_FLAT),
        })
        assert [d.rule_id for d in diags] == [RULE]
        assert diags[0].fix is not None and diags[0].fix.new == "ПодгрузкаПриПрокрутке"
    # Without any catalog at all, and on the half the page scrolls around.
    alone = _run(tmp_path, {"ФормаПробы.yaml": _bound_form(_NOT_SCROLLED, declaration=_TYPED_FLAT)})
    assert [d.rule_id for d in alone] == [RULE]
    assert "десять" in alone[0].message


@pytest.mark.parametrize("declaration", [
    _hierarchy("ПоУмолчанию"),
    _hierarchy("РежимИерархии.ПоУмолчанию"),
    _hierarchy("Подразделение"),
    _hierarchy('"Выключено"'),
    _hierarchy("=РежимСписка()"),
    "            ИспользуемаяИерархия:\n"
    "                Тип: РежимИерархии\n"
    "                Значение: ПоУмолчанию\n",
])
def test_hierarchy_asked_for_is_never_judged(tmp_path, declaration):
    diags = _run(tmp_path, {
        "Склады.yaml": _catalog(), "ФормаПробы.yaml": _bound_form(declaration=declaration),
    })
    assert diags == [], declaration


def test_inline_source_is_read_as_well(tmp_path):
    diags = _run(tmp_path, {"Склады.yaml": _catalog(), "ФормаПробы.yaml": _inline_form()})
    assert [d.rule_id for d in diags] == [TABLE_RULE]
    diags = _run(tmp_path, {
        "Склады.yaml": _catalog(_HIERARCHICAL), "ФормаПробы.yaml": _inline_form(),
    })
    assert diags == []


def test_list_built_in_code_is_not_judged(tmp_path):
    """No default value, or a source bound to a call: the file declares nothing to read."""
    text = _bound_form().split("        ЗначениеПоУмолчанию:\n", 1)[0]
    assert _run(tmp_path, {"Склады.yaml": _catalog(), "ФормаПробы.yaml": text}) == []
    called = _bound_form().replace("Источник: =Список", "Источник: =СоздатьСписок()")
    assert _run(tmp_path, {"Склады.yaml": _catalog(), "ФормаПробы.yaml": called}) == []


@pytest.mark.parametrize("kind, table", [
    ("Документ", "Склады"),
    ("РегистрСведений", "Склады"),
    ("РегистрНакопления", "Склады.Остатки"),
])
def test_kinds_without_hierarchies_are_flat(tmp_path, kind, table):
    diags = _run(tmp_path, {
        "Склады.yaml": _catalog(kind=kind), "ФормаПробы.yaml": _bound_form(table=table),
    })
    assert [d.rule_id for d in diags] == [TABLE_RULE]


@pytest.mark.parametrize("files, table", [
    ({}, "Склады"),  # a table outside the project - a system table, a library
    ({"Склады.yaml": _catalog()}, "Склады.Группы"),  # a table derived from a catalog
    ({"Склады.yaml": _catalog(kind="ЖурналДанных")}, "Склады"),  # a composite source
    ({"Склады.yaml": _catalog(kind="ВиртуальнаяТаблица")}, "Склады"),
    # The same name twice: every element under it has to agree.
    ({"Склады.yaml": _catalog(), "Прочие/Склады.yaml": _catalog(_HIERARCHICAL)}, "Склады"),
])
def test_table_that_may_be_hierarchical_is_not_judged(tmp_path, files, table):
    diags = _run(tmp_path, {**files, "ФормаПробы.yaml": _bound_form(table=table)})
    assert diags == [], table


def test_namespace_of_the_table_and_of_the_row_type_is_read(tmp_path):
    """A list form names its rows in full (`Vendor::Subsystem::Form.Row`): the type parser does
    not read a namespace, and the rule used to crash on such a list instead of judging it."""
    row_type = "Вендор::Склад::ФормаПробы.СтрокаСписка"
    diags = _run(tmp_path, {
        "Склады.yaml": _catalog(),
        "ФормаПробы.yaml": _bound_form(table="Вендор::Склад::Склады", row_type=row_type),
    })
    assert [d.rule_id for d in diags] == [TABLE_RULE]
    flat = _run(tmp_path, {
        "ФормаПробы.yaml": _bound_form(declaration=_TYPED_FLAT, row_type=row_type),
    })
    assert [d.rule_id for d in flat] == [RULE]
    assert "ПодгрузкаПриПрокрутке" in flat[0].message


_ENGLISH_CATALOG = """ElementKind: Catalog
Id: 88888888-8888-8888-8888-888888888888
Name: Склады
VisibilityScope: InProject
{extra}"""

_ENGLISH_FORM = """ElementKind: InterfaceComponent
Id: 99999999-9999-9999-9999-999999999999
Name: ФормаПробы
Inherits:
    Type: Form
    Content:
        Type: Table<DynamicList<ФормаПробы.СтрокаСписка>>
        Name: ТаблицаПробы
        Source: =Список
        VerticalScroll: True
        Navigation: None
Properties:
    -
        Name: Список
        Type: DynamicList<ФормаПробы.СтрокаСписка>
        DefaultValue:
            RowDataTypeName: СтрокаСписка
            MainTable:
                Table: Склады
{declaration}"""


def test_english_spelling_of_the_table_half(tmp_path):
    diags = _run(tmp_path, {
        "Склады.yaml": _ENGLISH_CATALOG.format(extra=""),
        "ФормаПробы.yaml": _ENGLISH_FORM.format(declaration=""),
    })
    assert [d.rule_id for d in diags] == [TABLE_RULE]
    assert diags[0].fix is not None and diags[0].fix.new == "LoadingOnScroll"
    for extra in ("Hierarchical: True\n", "DefaultHierarchy: СкладыПоВидам\n"):
        diags = _run(tmp_path, {
            "Склады.yaml": _ENGLISH_CATALOG.format(extra=extra),
            "ФормаПробы.yaml": _ENGLISH_FORM.format(declaration=""),
        })
        assert diags == [], extra
    assert [d.rule_id for d in _run(tmp_path, {
        "Склады.yaml": _ENGLISH_CATALOG.format(extra="Hierarchical: False\n"),
        "ФормаПробы.yaml": _ENGLISH_FORM.format(declaration="            UsedHierarchy: Auto\n"),
    })] == [TABLE_RULE]


def test_english_typed_disabled_hierarchy_is_judged_by_the_file(tmp_path):
    typed = (
        "            UsedHierarchy:\n"
        "                Type: HierarchyMode\n"
        "                Value: Disabled\n"
    )
    diags = _run(tmp_path, {
        "Склады.yaml": _ENGLISH_CATALOG.format(extra="Hierarchical: True\n"),
        "ФормаПробы.yaml": _ENGLISH_FORM.format(declaration=typed),
    })
    assert [d.rule_id for d in diags] == [RULE]
    assert diags[0].fix.new == "LoadingOnScroll"
    asked = typed.replace("Disabled", "Default")
    assert _run(tmp_path, {
        "Склады.yaml": _ENGLISH_CATALOG.format(extra=""),
        "ФормаПробы.yaml": _ENGLISH_FORM.format(declaration=asked),
    }) == []
