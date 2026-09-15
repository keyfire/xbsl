"""Checked platform results must be consumed; mutating and unknown receivers are left alone."""

import pytest

from xbsl import dataset, engine, parser

RULE = "code/unused-return-value"
pytestmark = pytest.mark.needs_data


@pytest.fixture(autouse=True)
def checked_catalog(monkeypatch):
    from xbsl.rules import unused_return_value as subject
    original = dataset.load_json
    checked = {
        "Строка": ["Заменить", "Вставить", "Удалить", "Перевернуть"],
        "Дата": ["ДобавитьДни"], "Число": ["Округлить"], "Url": ["СПутем"],
        "Массив": ["Сортировать", "Фильтровать"],
        "Последовательность": ["Фильтровать"],
    }
    def load(name):
        data = original(name)
        return {**data, "checked_return_methods": checked} if name == "stdlib.json" else data
    monkeypatch.setattr(dataset, "load_json", load)
    subject._checked_methods.cache_clear()
    subject._checked_names.cache_clear()
    yield checked
    subject._checked_methods.cache_clear()
    subject._checked_names.cache_clear()


def lint(text):
    source = engine.load_text("Sample.xbsl", text)
    _, errors = parser.parse(source)
    assert errors == []
    return list(engine.run_sources([source], select={RULE}))


@pytest.mark.parametrize("parameter, call", [
    ("Text: String", 'Text.Replace("a", "b")'),
    ("Day: Date", "Day.AddDays(1)"),
    ("Amount: Number", "Amount.Round(2)"),
    ("Address: Url", 'Address.WithPath("a")'),
    ("Items: Array<Number>", "Items.Sort()"),
    ("Items: Array<Number>", "Items.Filter(Item -> True)"),
    ("", '"text".Replace("a", "b")'),
    ("Текст: Строка", 'Текст.Заменить("а", "б")'),
    ("Числа: Массив<Число>", "Числа.Сортировать()"),
])
def test_dropped_checked_result_is_an_error(parameter, call):
    findings = lint(f"method Example({parameter})\n    {call}\n;\n")
    assert len(findings) == 1
    assert findings[0].severity.value == "error"
    assert findings[0].line == 2
    assert findings[0].fix is None


@pytest.mark.parametrize("body", [
    'var Result = Text.Replace("a", "b")',
    'Consume(Text.Replace("a", "b"))',
    'return Text.Replace("a", "b")',
    'var Mapper = (Value: String) -> Value.Replace("a", "b")',
    'Items.Insert(0, "a")', 'Items.Remove("a", True)', 'Items.Reverse(0, 1)',
    'Unknown.Replace("a", "b")',
])
def test_used_results_mutations_and_unknown_receivers_are_silent(body):
    assert lint(f"method Example(Text: String, Items: Array<String>): String\n    {body}\n;\n") == []


def test_project_method_named_like_a_checked_platform_method_is_silent():
    assert lint('structure Wrapper\n    method Replace(): String\n        return "a"\n    ;\n;\n'
                'method Example(Item: Wrapper)\n    Item.Replace()\n;\n') == []


def test_only_outer_dropped_call_is_reported_in_a_chain():
    findings = lint('method Example(Text: String)\n    Text.Replace("a", "b").Replace("b", "c")\n;\n')
    assert len(findings) == 1
    assert findings[0].col == 28


def test_a_full_lambda_body_contains_real_statements():
    findings = lint('method Example(Text: String)\n    var Action = method () ->\n        Text.Replace("a", "b")\n    ;\n;\n')
    assert len(findings) == 1 and findings[0].line == 3


def test_an_old_catalog_without_the_marker_stays_silent(checked_catalog):
    checked_catalog.clear()
    assert lint('method Example(Text: String)\n    Text.Replace("a", "b")\n;\n') == []


def test_dataset_reset_invalidates_the_checked_method_cache(checked_catalog):
    from xbsl.rules import unused_return_value as subject
    assert "Заменить" in subject._checked_methods()["Строка"]
    checked_catalog.clear()
    dataset._clear_caches()
    assert subject._checked_methods() == {}
