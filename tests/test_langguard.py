"""The language guard of the repository's own sources (`tools/langguard.py`).

The guard says "no NEW Russian in comments and names", so the tests are about the two ways
it can be useless: silence over a real defect, and noise over the Cyrillic the rule allows
(citations in backticks, quotes of the platform, string literals, platform keys in
TypeScript). The historical defects it was written for - a bare `ШиринаВКолонках` in an
English comment and Russian test docstrings - stand as the planted cases here.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
_spec = importlib.util.spec_from_file_location("langguard", ROOT / "tools" / "langguard.py")
langguard = importlib.util.module_from_spec(_spec)
sys.modules["langguard"] = langguard
_spec.loader.exec_module(langguard)


def _check(tmp_path: Path, name: str, source: str):
    path = tmp_path / name
    path.write_text(source, encoding="utf-8")
    return langguard.check_file(path)


# -- Python ---------------------------------------------------------------------------------


def test_a_russian_comment_is_caught(tmp_path):
    found = _check(tmp_path, "sample.py", "x = 1  # это остаток от прошлой правки\n")
    assert [(1, "comment", "остаток от правки прошлой это")] == [
        (n, k, " ".join(sorted(w.split()))) for n, k, w in found
    ]


def test_a_russian_docstring_is_caught(tmp_path):
    source = '"""Модуль про разбор.\n\nВторая строка тоже русская.\n"""\n'
    lines = {number for number, _kind, _words in _check(tmp_path, "sample.py", source)}
    assert lines == {1, 3}


def test_a_russian_identifier_is_caught(tmp_path):
    found = _check(tmp_path, "sample.py", "def test_проверка():\n    return 1\n")
    assert found and found[0][1] == "identifier"


def test_the_allowed_cyrillic_is_left_alone(tmp_path):
    source = (
        # A citation the dictionary cannot spell in English stays a citation; a name it CAN
        # (`ВидЭлемента` -> ElementKind) is a finding of its own - see the citation tests above.
        '"""A citation of a name of ours is legitimate: `ПробныйСправочник`.\n\n'
        'A quote of the platform message - "Значение типа не может быть присвоено" - too,\n'
        'and so are the descriptor Проект.yaml and the letter ё the rule is about.\n"""\n'
        'MESSAGE = "русский текст сообщения"  # a literal is not a comment\n'
        'KEYS = {"Реквизиты": "attributes"}\n'
    )
    assert _check(tmp_path, "sample.py", source) == []


def test_a_broken_source_is_skipped_rather_than_crashing(tmp_path):
    assert _check(tmp_path, "sample.py", "def (:\n  # русский комментарий\n") == []


# -- a quoted name the dictionary can spell ------------------------------------------------


@pytest.mark.needs_data
def test_a_backticked_name_with_an_english_spelling_is_caught(tmp_path):
    """The citation exception used to swallow the rule: `Обработчик` in a comment read as
    legal while the repository has an English spelling for it and writes it everywhere else."""
    source = "# the `Обработчик` of an HTTP method sits at a yaml offset\nX = 1\n"
    found = _check(tmp_path, "sample.py", source)
    assert found == [(1, "citation", "Обработчик -> Handler")]


@pytest.mark.needs_data
def test_a_quoted_document_heading_stays_a_citation(tmp_path):
    """Double quotes hold a QUOTE - the heading a parser matches, the text of a message.
    Rewriting it in English would misreport what the code looks for."""
    source = '# own members are the H3 headings of the "Свойства" section\nX = 1\n'
    assert _check(tmp_path, "sample.py", source) == []


@pytest.mark.needs_data
def test_a_code_citation_is_not_a_name(tmp_path):
    """A longer citation quotes generated CODE, and that code really is written in Russian."""
    source = "# the stub itself: `метод Имя(П: Тип)` plus a TODO body\nX = 1\n"
    assert _check(tmp_path, "sample.py", source) == []


# -- TypeScript -----------------------------------------------------------------------------


def test_a_russian_comment_in_typescript_is_caught(tmp_path):
    source = "// ШиринаВКолонках. The platform states the scale by name\nconst a = 1;\n"
    assert _check(tmp_path, "sample.ts", source) == [(1, "comment", "ШиринаВКолонках")]


def test_platform_keys_of_typescript_are_not_names_of_ours(tmp_path):
    """An icon table keyed by component kinds is the platform's vocabulary, not a name."""
    source = (
        "const ICONS: Record<string, string> = {\n"
        "  СтековаяГруппа: 'layers',\n"
        "  ПолеВвода: 'edit',\n"
        "};\n"
        "const title = node.Заголовок ?? 'нет заголовка';\n"
    )
    assert _check(tmp_path, "sample.ts", source) == []


def test_a_regex_literal_does_not_desynchronize_the_scanner(tmp_path):
    """The live failure of the first run: the quote inside `/"/g` opened a string.

    Everything after it - 700 lines of comments, the defect included - was then invisible.
    """
    source = (
        'export const esc = (s: string) => s.replace(/&/g, "&amp;").replace(/"/g, "&quot;");\n'
        "// Неограниченная - the whole row.\n"
    )
    assert _check(tmp_path, "sample.ts", source) == [(2, "comment", "Неограниченная")]


def test_a_url_inside_a_string_is_not_a_comment(tmp_path):
    source = 'const doc = "https://example.com/помощь";\nconst n = 10 / 2;\n'
    assert _check(tmp_path, "sample.ts", source) == []


# -- what a change added ---------------------------------------------------------------------


DIFF = """\
diff --git a/xbsl/sample.py b/xbsl/sample.py
--- a/xbsl/sample.py
+++ b/xbsl/sample.py
@@ -10,0 +11,2 @@ def helper():
+    # a fresh line
+    # one more
@@ -40 +41 @@ def other():
+    return 2
diff --git a/gone.py b/dev/null
--- a/gone.py
+++ /dev/null
@@ -1,2 +0,0 @@
"""


def test_added_lines_are_parsed_from_a_unified0_diff():
    assert langguard.added_lines(DIFF) == {"xbsl/sample.py": {11, 12, 41}}


def test_only_the_added_lines_are_judged(tmp_path):
    """The tree still carries the legacy debt - a guard over all of it would never be green."""
    path = tmp_path / "sample.py"
    path.write_text("# старый комментарий\nx = 1  # новый комментарий\n", encoding="utf-8")
    assert langguard.check_file(path, {2}) == [(2, "comment", "комментарий новый")]


def test_untracked_files_are_judged_under_every_base(tmp_path, monkeypatch):
    """A diff against any base is blind to a file until `git add` - so a `--base` run used
    to answer "clean" over a brand-new module whose bare Cyrillic CI then found."""
    (tmp_path / "fresh.py").write_text("x = 1  # свежий модуль\n", encoding="utf-8")
    replies = {
        ("ls-files", "--others", "--exclude-standard"): "fresh.py\n",
    }
    monkeypatch.setattr(langguard, "ROOT", tmp_path)
    monkeypatch.setattr(langguard, "_git", lambda *args: replies.get(args, ""))
    found = langguard.scan_diff("origin/main")
    assert [(name, kind) for name, _line, kind, _words in found] == [("fresh.py", "comment")]


@pytest.mark.parametrize("name", ["node_modules/pkg/index.ts", "dist/out.js", "docs/page.md"])
def test_foreign_and_generated_files_are_out_of_scope(name):
    assert not langguard._is_source(name)


def test_the_guard_runs_over_this_repository():
    """Non-vacuity: the debt is real, so a scan of the tree must find it - and its own
    sources must be clean, which is what the diff mode gates on."""
    assert len(langguard.scan_tree()) > 100
    assert langguard.check_file(ROOT / "tools" / "langguard.py") == []
