"""Cyclic YAML aliases must not trap the documentation comment request.

A walk over a node graph with a cycle never ends, so the check has to bound the request. It
counts steps, not seconds: a trace hook counts the Python calls made inside it and, past a
budget far above what a normal request makes, raises - the exception stops the walk where
it runs. A clock bounded a child process here before, and on a loaded machine the imports of
the child alone ate its three seconds: the test failed with nothing wrong.
"""

import sys

import pytest

from xbsl import doccomments, i18n, metamodel
from xbsl.rules import yaml_doc_comments

#: Python calls one request may make. A normal answer makes under a thousand; the walk of a
#: cycle reaches the budget in about half a second.
_CALL_BUDGET = 1_000_000


class _Runaway(Exception):
    """The request made more calls than any request needs: it walks without an end."""


def _within_budget(request):
    """`request()` under the call budget; past it the request is stopped by _Runaway."""
    made = 0

    def count(frame, event, arg):
        nonlocal made
        made += 1
        if made > _CALL_BUDGET:
            raise _Runaway(f"no answer after {_CALL_BUDGET} calls")
        return None  # the calls alone are counted, not the lines inside them

    previous = sys.gettrace()
    sys.settrace(count)
    try:
        return request()
    finally:
        sys.settrace(previous)


@pytest.fixture
def documentable(monkeypatch):
    """Every element kind documentable, with no data: the request reaches its tree walk."""
    monkeypatch.setattr(yaml_doc_comments, "_documentable_known", lambda: True)
    monkeypatch.setattr(metamodel, "class_for_kind", lambda kind: "Dummy")


def test_self_referential_alias_is_rejected_within_a_bounded_walk(documentable):
    text = "ВидЭлемента: Справочник\nExtra: &x {self: *x}\n"
    result = _within_budget(lambda: doccomments.inspect(text, 0))
    assert not result.supported
    assert result.reason == i18n.t("doc-comment.alias")
