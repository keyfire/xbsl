"""List continuations survive comment re-wrapping."""

import pytest

from xbsl.translation.rewrap import rewrap_comments


pytestmark = pytest.mark.needs_data


@pytest.mark.parametrize(
    ("source", "translated", "continuation"),
    [
        (
            "// List:\n"
            "//   - short item\n"
            "//     short continuation\n"
            "//\n"
            "// Short paragraph after the list.\n",
            "// List:\n"
            "//   - translated item\n"
            "//     translated continuation that grows far beyond the line width and must keep its nesting\n"
            "//\n"
            "// The ordinary paragraph after the list is now long enough that it needs wrapping again.\n",
            "//     translated continuation that grows far beyond the line width and must keep its nesting\n",
        ),
        (
            "/* List:\n"
            "   - short item\n"
            "     short continuation\n"
            "\n"
            "   Short paragraph after the list. */\n",
            "/* List:\n"
            "   - translated item\n"
            "     translated continuation that grows far beyond the line width and must keep its nesting\n"
            "\n"
            "   The ordinary paragraph after the list is now long enough that it needs wrapping again. */\n",
            "     translated continuation that grows far beyond the line width and must keep its nesting\n",
        ),
    ],
)
def test_rewrap_keeps_deep_list_continuation_and_wraps_following_paragraph(
    source, translated, continuation,
):
    out = rewrap_comments(translated, source, limit=60)

    assert continuation in out
    assert "The ordinary paragraph after the list is now long enough" in out
    assert out != translated
