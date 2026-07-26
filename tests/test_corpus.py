"""Invariant: the real corpus passes the linter with no findings by default.

The test is skipped when the corpus is unavailable (portability).
The path is set via the XBSL_CORPUS environment variable.
"""

import os
from pathlib import Path

import pytest

from xbsl import engine
from xbsl.cli import discover

_CORPUS = os.environ.get("XBSL_CORPUS")


# Rules whose findings on the corpus are acceptable: these are REAL findings, not false ones.
# code/unused-loop-var - server-side compilation reports the same. Any hit of a DIFFERENT
# rule on the corpus is a sign of a false positive and must be caught by this test.
_KNOWN_FINDING_RULES = {"code/unused-loop-var"}


@pytest.mark.skipif(not (_CORPUS and Path(_CORPUS).exists()), reason="корпус недоступен (задайте XBSL_CORPUS)")
def test_corpus_no_errors_and_only_known_warnings():
    # The corpus is valid deployed code: there must be no linter errors.
    diags = engine.run(discover([str(_CORPUS)]))
    errors = [d for d in diags if d.severity.value == "error"]
    assert not errors, f"неожиданные ошибки: {[d.format() for d in errors[:5]]}"
    unexpected = [d for d in diags if d.rule_id not in _KNOWN_FINDING_RULES]
    assert not unexpected, f"неожиданные замечания: {[d.format() for d in unexpected[:5]]}"
