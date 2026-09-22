"""Generated component members documented by the interface component guide."""

import pytest


pytestmark = pytest.mark.needs_data


@pytest.mark.parametrize(
    ("russian", "english"),
    [
        ("СобственнаяМодифицированность", "SelfModified"),
        ("РассчитаннаяМодифицированность", "ComputedModified"),
        ("ОтслеживатьИзменениеДанных", "TrackDataModification"),
    ],
)
def test_docs_symbol_finds_generated_component_member_in_the_guide(mcp_module, russian, english):
    """The guide, rather than a type member table, is the source for these generated members."""
    russian_answer = mcp_module.docs_symbol(russian)
    english_answer = mcp_module.docs_symbol(english)

    for answer in (russian_answer, english_answer):
        assert answer["id"] == "topics/interface-component-types"
        assert answer["url"].endswith("/topics/interface-component-types/")
        assert answer["section"] == "Тип <ИмяКомпонента>"
        assert russian in answer["text"]
