"""Missing language data must not break independent YAML checks."""
import pytest
from xbsl import dataset, engine
from xbsl.rules import ambiguous_types

@pytest.mark.parametrize("text", [
    "ElementKind: Catalog\nName: Example\nAttributes:\n    - Name: Value\n      Type: String\n",
    "ВидЭлемента: Справочник\nИмя: Example\nРеквизиты:\n    - Имя: Value\n      Тип: Строка\n",
])
def test_yaml_ambiguity_is_unavailable_without_language_data(monkeypatch, text):
    def unavailable(_text):
        raise dataset.DatasetError("No language dataset")
    monkeypatch.setattr(ambiguous_types, "tokenize", unavailable)
    source = engine.load_text("Example.yaml", text)
    assert list(engine.run_sources([source], select={"yaml/ambiguous-type"})) == []
