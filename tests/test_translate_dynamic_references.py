"""Dynamic-list expressions resolve direct table aliases without changing UI links."""
import pytest
import yaml

from xbsl import engine
from xbsl.translation.code import Resolver
from xbsl.translation.dictionary import Dictionary
from xbsl.translation.reporting import FileReport
from xbsl.translation.yamlfile import translate_yaml

pytestmark = pytest.mark.needs_data


def translated(source, tokens=None):
    data = {"ВидЭлемента": "КомпонентИнтерфейса", "Имя": "SamplePanel",
            "Наследует": {"Тип": "ФормаСписка<Неопределено>", "Содержимое": source}}
    text = yaml.safe_dump(data, allow_unicode=True, sort_keys=False)
    resolver = Resolver(Dictionary(tokens=tokens or {}, phrases={}, literals={}))
    return translate_yaml(engine.load_text("SamplePanel.yaml", text), resolver,
                          FileReport(path="SamplePanel.yaml"))


def table(expression, alias="Items"):
    return {"Тип": "Таблица<ДинамическийСписок>", "Источник": {
        "ОсновнаяТаблица": {"Таблица": "SampleRecords", "Псевдоним": alias},
        "Поля": [{"Тип": "ПолеДинамическогоСписка", "Выражение": expression}]}}


def test_direct_main_table_reference_uses_the_query_field_spelling():
    assert "Items.Reference" in translated(table("Items.Ссылка"))


def test_joined_table_and_filter_share_the_source_alias_scope():
    source = table("Others.Ссылка")
    source["Источник"]["ПрисоединенныеТаблицы"] = [{"Тип": "ПрисоединеннаяТаблица",
        "Таблица": "OtherRecords", "Псевдоним": "Others", "Фильтр": {"Элементы": [
            {"Тип": "ЭлементФильтраВыражение", "Выражение": "Others.Ссылка == Items.Ссылка"}]}}]
    out = translated(source)
    assert "Others.Reference == Items.Reference" in out


@pytest.mark.parametrize("expression", ["Widget.Ссылка", "Items.Owner.Ссылка", '"Items.Ссылка"'])
def test_unrelated_receivers_and_literal_text_are_not_table_references(expression):
    out = translated(table(expression))
    assert "Reference" not in out


def test_aliases_do_not_escape_to_a_sibling_table_or_an_ordinary_expression():
    source = {"Тип": "Группа", "Содержимое": [table("Items.Ссылка"), table("Items.Ссылка", "Others"),
        {"Тип": "ПолеДинамическогоСписка", "Выражение": "Items.Ссылка"}]}
    out = translated(source)
    assert out.count("Items.Reference") == 1
    assert out.count("Items.Link") == 2


def test_a_scoped_dictionary_override_keeps_priority():
    assert "Items.SelectedRecord" in translated(table("Items.Ссылка"), {"Items.Ссылка": "SelectedRecord"})


def test_flat_link_override_does_not_change_a_known_table_reference():
    assert "Items.Reference" in translated(table("Items.Ссылка"), {"Ссылка": "Link"})


def test_english_dynamic_list_keys_keep_the_same_expression_context():
    source = {"Type": "Table<DynamicList>", "Source": {
        "MainTable": {"Table": "SampleRecords", "Alias": "Items"},
        "Fields": [{"Type": "DynamicListField", "Expression": "Items.Ссылка"}]}}
    assert "Items.Reference" in translated(source)


@pytest.mark.parametrize("expression", [
    "Widget?.Items.Ссылка", "Компоненты?.Items.Ссылка",
    "Widget /* note */ . Items.Ссылка", "Widget. /* note */ Items.Ссылка",
])
def test_nested_receivers_never_borrow_the_alias_reference_scope(expression):
    assert "Reference" not in translated(table(expression))


@pytest.mark.parametrize("written_type", [
    "CustomTable<DynamicList>", "Acme::Table<DynamicList>",
    "Acme::Таблица<ДинамическийСписок>", "Table<Acme::DynamicList>",
    "DynamicList<String>", "Table<DynamicList<String>>", "Table<DynamicList, String>",
])
def test_only_exact_standard_dynamic_list_types_open_alias_scope(written_type):
    source = table("Items.Ссылка")
    source["Тип"] = written_type
    assert "Items.Link" in translated(source)


@pytest.mark.parametrize("expression", [
    "Items /* note */ . Ссылка", "Items. /* note */ Ссылка",
    "Items /* note */ . /* note */ Ссылка",
])
def test_comments_between_alias_and_field_preserve_reference_and_dictionary_scope(expression):
    out = translated(table(expression))
    assert "Reference" in out
    assert out.count("/* note */") == expression.count("/* note */")
    overridden = translated(table(expression), {"Items.Ссылка": "SelectedRecord"})
    assert "SelectedRecord" in overridden
    assert "Reference" not in overridden


def test_reference_text_in_comments_and_literals_stays_unchanged():
    expression = 'Items.Ссылка + "Items.Ссылка" /* Items.Ссылка */'
    assert 'Items.Reference + "Items.Ссылка" /* Items.Ссылка */' in translated(table(expression))
