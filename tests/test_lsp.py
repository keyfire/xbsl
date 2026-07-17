"""Чистые помощники LSP-сервера (без pygls): слово под курсором и разбор параметров."""

from xbsl import lsp


def test_word_at():
    line = "знч Список = новый Массив()"
    assert lsp._word_at(line, 0) == "знч"
    assert lsp._word_at(line, 6) == "Список"      # середина слова
    assert lsp._word_at(line, 20) == "Массив"
    assert lsp._word_at(line, 10) == "Список"      # хвостовой край слова (курсор в конце)
    assert lsp._word_at(line, 11) == ""            # на операторе '='


def test_word_at_edges():
    assert lsp._word_at("", 0) == ""
    assert lsp._word_at("Массив", 100) == "Массив"  # курсор за концом строки
    assert lsp._word_at("A.Поле", 2) == "Поле"      # точка – граница слова
    assert lsp._word_at("Тип_1", 0) == "Тип_1"       # подчёркивание и цифра – часть имени


def test_param_dict_and_object():
    assert lsp._param({"query": "массив"}, "query") == "массив"
    assert lsp._param({"query": "x"}, "limit", 20) == 20
    assert lsp._param(None, "query", "def") == "def"

    class P:
        query = "z"

    assert lsp._param(P(), "query") == "z"
    assert lsp._param(P(), "missing", 5) == 5


def test_doc_key_meets_both_uri_spellings(tmp_path):
    """Редактор шлёт file:///d%3A/..., сервер строит file:///d:/... – ключ обязан совпасть.

    Пока сравнивались строки uri, project-находки открытого файла терялись: ключ,
    под который их клали, не находился по ключу от редактора.
    """
    import os
    import re
    from pathlib import Path

    import pytest

    uris = pytest.importorskip("pygls.uris")
    f = tmp_path / "М.yaml"
    f.write_text("ВидЭлемента: Справочник\n", encoding="utf-8")

    серверный = uris.from_fs_path(str(f))
    # ровно то, чем отличается запись редактора на Windows
    редакторский = re.sub(r"^file:///([A-Za-z]):", r"file:///\1%3A", серверный)
    if os.name == "nt":
        assert серверный != редакторский  # иначе тест ничего не проверяет

    ключ = lambda u: lsp._doc_key(Path(uris.to_fs_path(u)), u)
    assert ключ(серверный) == ключ(редакторский)


def test_doc_key_without_path_falls_back_to_uri():
    assert lsp._doc_key(None, "untitled:Untitled-1") == "untitled:Untitled-1"


def test_resolve_templates_path(tmp_path):
    """Without --templates the server falls back to the panel's file at the workspace
    root: what the panel saves, the next Ctrl+Space must see."""
    from pathlib import Path

    from xbsl.templates import DEFAULT_FILE

    assert lsp._resolve_templates_path(None, tmp_path) == tmp_path / DEFAULT_FILE
    assert lsp._resolve_templates_path(None, None) is None
    assert lsp._resolve_templates_path("own.json", tmp_path) == tmp_path / "own.json"
    absolute = str(tmp_path / "t.json")
    assert lsp._resolve_templates_path(absolute, tmp_path) == Path(absolute)
