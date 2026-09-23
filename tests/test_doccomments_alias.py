"""Cyclic YAML aliases must not trap the documentation comment request."""

import os
import subprocess
import sys


def test_self_referential_alias_is_rejected_within_a_bounded_child():
    code = """
from xbsl import doccomments, metamodel
from xbsl.rules import yaml_doc_comments
yaml_doc_comments._documentable_known = lambda: True
metamodel.class_for_kind = lambda kind: "Dummy"
text = "ВидЭлемента: Справочник\\nExtra: &x {self: *x}\\n"
result = doccomments.inspect(text, 0)
assert not result.supported and "alias" in result.reason.lower(), result
print("alias rejected")
"""
    env = dict(os.environ, PYTHONIOENCODING="utf-8", XBSL_NO_PLUGINS="1", XBSL_LANG="en")
    done = subprocess.run(
        [sys.executable, "-c", code], cwd=os.getcwd(), env=env,
        capture_output=True, text=True, encoding="utf-8", timeout=3,
    )
    assert done.returncode == 0, done.stderr
    assert "alias rejected" in done.stdout
