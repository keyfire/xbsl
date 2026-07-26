"""Tests of the pure binding-completion module (component references and their members).

The module works over the form's components (an IndexLookup or a plain list) and the stdlib
members map – no Element data is needed, so these run in a checkout without the data bundle.
"""

from xbsl.bindingcomplete import complete_binding
from xbsl.lsp_nav import IndexLookup

# A form with components of different types: two ordinary component types that carry members,
# one facet type (a dotted key in the members map) and – in a second form – a namesake that
# must not leak across forms.
INDEX = {
    "components": [
        {"form": "Карточка", "name": "КнопкаСохранить", "type": "Кнопка",
         "path": "Ф/Карточка.yaml", "line": 10},
        {"form": "Карточка", "name": "ПолеИмя", "type": "ПолеВвода",
         "path": "Ф/Карточка.yaml", "line": 20},
        {"form": "Карточка", "name": "Аватар", "type": "ДвоичныйОбъект.Ссылка",
         "path": "Ф/Карточка.yaml", "line": 30},
        {"form": "Другая", "name": "ЧужаяКнопка", "type": "Кнопка",
         "path": "Ф/Другая.yaml", "line": 5},
    ],
}

LOOKUP = IndexLookup(INDEX)

MEMBERS = {
    "Кнопка": {"properties": ["Заголовок", "Видимость"], "methods": ["Активировать"]},
    "ПолеВвода": {"properties": ["Значение", "ТолькоПросмотр"], "methods": ["Очистить"]},
    # a facet type keyed with a dot, exactly as facet_members stores it
    "ДвоичныйОбъект.Ссылка": {"properties": ["Существует"], "methods": []},
    # the old dataset shape – a flat list of member names – is understood too
    "Флажок": ["Пометка", "Доступность"],
}


def bind(prefix, form_stem="Карточка", components=LOOKUP, members=MEMBERS):
    return complete_binding(prefix, form_stem=form_stem, components=components, members=members)


# --- component references ----------------------------------------------------------------

def test_component_names_all():
    # =Компоненты. offers every component of the form, in declaration order, as full bindings
    assert bind("=Компоненты.") == [
        "=Компоненты.КнопкаСохранить",
        "=Компоненты.ПолеИмя",
        "=Компоненты.Аватар",
    ]


def test_component_names_filtered_by_substring():
    # a case-insensitive substring match on the last segment
    assert bind("=Компоненты.поле") == ["=Компоненты.ПолеИмя"]
    assert bind("=Компоненты.Кнопка") == ["=Компоненты.КнопкаСохранить"]


def test_component_names_scoped_to_the_form():
    # a component of another form is never offered
    assert "=Компоненты.ЧужаяКнопка" not in bind("=Компоненты.")


def test_component_names_no_match_is_empty():
    assert bind("=Компоненты.нетакого") == []


# --- component members -------------------------------------------------------------------

def test_member_names_all_properties_then_methods():
    assert bind("=Компоненты.КнопкаСохранить.") == [
        "=Компоненты.КнопкаСохранить.Заголовок",
        "=Компоненты.КнопкаСохранить.Видимость",
        "=Компоненты.КнопкаСохранить.Активировать",
    ]


def test_member_names_filtered_by_substring():
    assert bind("=Компоненты.ПолеИмя.знач") == ["=Компоненты.ПолеИмя.Значение"]


def test_member_names_of_a_facet_type():
    # a facet type is keyed with a dot in the members map and resolves whole
    assert bind("=Компоненты.Аватар.") == ["=Компоненты.Аватар.Существует"]


def test_member_names_from_a_flat_member_list():
    idx = {"components": [{"form": "Ф", "name": "Чек", "type": "Флажок", "path": "p", "line": 1}]}
    got = complete_binding(
        "=Компоненты.Чек.", form_stem="Ф", components=IndexLookup(idx), members=MEMBERS,
    )
    assert got == ["=Компоненты.Чек.Пометка", "=Компоненты.Чек.Доступность"]


def test_member_names_strip_generic_and_nullable():
    # the type root is used for the lookup: Таблица<...> and Кнопка? both resolve to their base
    idx = {"components": [
        {"form": "Ф", "name": "Т", "type": "Таблица<Строка>", "path": "p", "line": 1},
        {"form": "Ф", "name": "К", "type": "Кнопка?", "path": "p", "line": 2},
    ]}
    lookup = IndexLookup(idx)
    members = {"Таблица": {"properties": ["Колонки"]}, "Кнопка": {"methods": ["Активировать"]}}
    assert complete_binding("=Компоненты.Т.", form_stem="Ф", components=lookup, members=members) == [
        "=Компоненты.Т.Колонки",
    ]
    assert complete_binding("=Компоненты.К.", form_stem="Ф", components=lookup, members=members) == [
        "=Компоненты.К.Активировать",
    ]


def test_unknown_component_has_no_members():
    assert bind("=Компоненты.Нет.") == []
    assert bind("=Компоненты.Нет.Что") == []


def test_component_without_a_member_page_yields_nothing():
    # the type has no entry in the members map – no members, but not an error
    idx = {"components": [
        {"form": "Ф", "name": "Группа", "type": "АвтоматическаяГруппа", "path": "p", "line": 1},
    ]}
    assert complete_binding(
        "=Компоненты.Группа.", form_stem="Ф", components=IndexLookup(idx), members=MEMBERS,
    ) == []


# --- input shapes and edges --------------------------------------------------------------

def test_plain_component_list_is_accepted():
    comps = [
        {"name": "КнопкаСохранить", "type": "Кнопка"},
        {"name": "ПолеИмя", "type": "ПолеВвода"},
    ]
    assert complete_binding("=Компоненты.", components=comps, members=MEMBERS) == [
        "=Компоненты.КнопкаСохранить",
        "=Компоненты.ПолеИмя",
    ]
    assert complete_binding("=Компоненты.ПолеИмя.знач", components=comps, members=MEMBERS) == [
        "=Компоненты.ПолеИмя.Значение",
    ]


def test_prefix_without_leading_equals():
    assert bind("Компоненты.") == [
        "=Компоненты.КнопкаСохранить",
        "=Компоненты.ПолеИмя",
        "=Компоненты.Аватар",
    ]


def test_unrecognized_prefix_is_empty():
    assert bind("") == []
    assert bind("=") == []
    assert bind("=Объект.") == []
    assert bind("=Компоненты") == []  # no dot yet – nothing to complete
    assert bind("мусор") == []


def test_deeper_chain_is_out_of_scope():
    # a member's own members would need type inference – not this module's job
    assert bind("=Компоненты.КнопкаСохранить.Заголовок.") == []


def test_no_components_source_is_empty():
    assert complete_binding("=Компоненты.", components=None, members=MEMBERS) == []


def test_limit_caps_the_result():
    comps = [{"name": f"К{i}", "type": "Кнопка"} for i in range(50)]
    got = complete_binding("=Компоненты.", components=comps, members=MEMBERS, limit=5)
    assert len(got) == 5
    assert got[0] == "=Компоненты.К0"


def test_duplicate_names_collapse_to_one_binding():
    comps = [{"name": "К", "type": "Кнопка"}, {"name": "К", "type": "ПолеВвода"}]
    assert complete_binding("=Компоненты.", components=comps, members=MEMBERS) == ["=Компоненты.К"]
