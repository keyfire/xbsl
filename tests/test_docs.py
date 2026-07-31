"""Docs runtime API (xbsl/docs.py) on a tiny DB assembled in the test (no distribution needed)."""

import sqlite3
from pathlib import Path

import pytest

from xbsl import dataset, docs
from xbsl.extract import docs as ex


def _has_fts5() -> bool:
    try:
        c = sqlite3.connect(":memory:")
        c.execute("CREATE VIRTUAL TABLE t USING fts5(x)")
        return True
    except sqlite3.OperationalError:
        return False


pytestmark = pytest.mark.skipif(not _has_fts5(), reason="в этой сборке SQLite нет FTS5")

_VER = "9.9.9+0"
_ARRAY = "stdlib/element/xbsl/Std/Collections/Array_ru"
_QUERY = "stdlib/element/xbsl/Std/Database/Query_ru"
# id, kind, title, qualified, availability, url, html, text (for FTS)
_PAGES = [
    (_ARRAY, "type", "Массив", "Стд::Коллекции::Массив", "КлиентИСервер",
     f"https://host/docs/help/{_ARRAY}/",
     '<h1>Массив</h1><p>Динамический массив значений. <img src="assets/i.png"></p>',
     "Массив Динамический массив значений добавить элемент"),
    (_QUERY, "type", "Запрос", "Стд::БазаДанных::Запрос", "Сервер",
     f"https://host/docs/help/{_QUERY}/",
     "<h1>Запрос</h1><p>Выполнение запросов к базе данных.</p>",
     "Запрос Выполнение запросов к базе данных выборка"),
]
# node, parent, ord, label, page, anchor, kind
_TREE = [
    (1, None, 0, "Типы языка", None, None, "section"),
    (2, 1, 0, "Массив", _ARRAY, None, "link"),
    (3, 2, 0, "Иерархия", _ARRAY, "иерархия", "heading"),  # a page section under a link node
    (4, 1, 1, "Запрос", _QUERY, None, "link"),
]


def _write_docs(root: Path, pages, tree=()) -> Path:
    """Assemble a docs.sqlite (+ the version index) under `root`; returns the version directory."""
    ver_dir = root / _VER
    ver_dir.mkdir()
    con = sqlite3.connect(ver_dir / "docs.sqlite")
    con.executescript(ex._SCHEMA)
    for p in pages:
        con.execute("INSERT INTO pages VALUES(?,?,?,?,?,?,?)", p[:7])  # text - only in FTS
        con.execute("INSERT INTO pages_fts(id,title,qualified,text) VALUES(?,?,?,?)",
                    (p[0], p[2], p[3], p[7]))
    con.executemany("INSERT INTO tree VALUES(?,?,?,?,?,?,?)", tree)
    con.commit()
    con.close()
    (root / "index.json").write_text(
        '{"available": ["%s"], "default": "%s"}' % (_VER, _VER), encoding="utf-8"
    )
    return ver_dir


@pytest.fixture
def docs_root(tmp_path):
    """A data directory with a tiny docs.sqlite; docs.py reads it as if it were real."""
    ver_dir = _write_docs(tmp_path, _PAGES, _TREE)
    (ver_dir / "assets").mkdir()
    (ver_dir / "assets" / "i.png").write_bytes(b"\x89PNG\r\n\x1a\n")  # an image file next to the DB
    dataset.set_data_root(tmp_path)
    yield tmp_path
    dataset.set_data_root(None)


# A fixture set for the relaxed search: `_PAIR` carries two words of the query
# and both are COMMON (the fillers hold them too), while `_REPEAT` repeats the third, rare word. bm25
# alone answers with `_REPEAT` - a page matching one word of three - and that is the bug being fixed.
_PAIR = "topics/element/form-list_ru"
_REPEAT = "topics/element/streams_ru"
_RELAXED_QUERY = "закрытие формы список"
_RELAXED_PAGES = [
    (_PAIR, "topic", "Формы и списки", "", "КлиентИСервер", "https://host/form-list/",
     "<h1>Формы и списки</h1>", "формы список"),
    (_REPEAT, "topic", "Потоки", "", "Сервер", "https://host/streams/",
     "<h1>Потоки</h1>", "закрытие закрытие закрытие закрытие потока"),
] + [
    (f"topics/element/filler{i}_ru", "topic", f"Пример {i}", "", "Сервер", f"https://host/f{i}/",
     f"<h1>Пример {i}</h1>", "формы таблица данных" if i < 4 else "список значений выбор")
    for i in range(8)
]


@pytest.fixture
def relaxed_root(tmp_path):
    _write_docs(tmp_path, _RELAXED_PAGES)
    dataset.set_data_root(tmp_path)
    yield tmp_path
    dataset.set_data_root(None)


def test_available(docs_root):
    assert docs.available() is True


def test_available_false_without_data(tmp_path):
    dataset.set_data_root(tmp_path)  # empty, no index
    try:
        assert docs.available() is False
        assert docs.search("массив") == []
        assert docs.page(_ARRAY) is None
        assert docs.tree() == []
        assert docs.for_symbol("Массив") is None
    finally:
        dataset.set_data_root(None)


def test_search_ranks_and_returns_url(docs_root):
    hits = docs.search("массив")
    assert hits and hits[0]["id"] == _ARRAY
    assert hits[0]["url"].endswith("/Array_ru/")
    assert "title" in hits[0] and "snippet" in hits[0]


def test_search_multiword(docs_root):
    assert docs.search("выполнение запросов")[0]["id"] == _QUERY


def test_search_relaxes_when_no_page_carries_every_word(relaxed_root):
    """Answering nothing was the bug: no page carries all three words, so coverage decides."""
    hits = docs.search(_RELAXED_QUERY)
    ids = [h["id"] for h in hits]
    assert ids[0] == _PAIR  # two words of three beat one word, however often it is repeated
    assert _REPEAT in ids  # relaxing adds answers, it does not filter them out


def test_relaxed_order_is_not_plain_bm25(relaxed_root):
    """The control the previous test needs: bm25 alone puts the word-repeating page first."""
    con = docs._open()
    try:
        rows = docs._match(con, " OR ".join(docs._fts_terms(_RELAXED_QUERY)), 10)
    finally:
        con.close()
    assert rows[0]["id"] == _REPEAT


def test_search_keeps_strict_result_when_words_are_together(relaxed_root):
    """A page carrying every word is the answer - no relaxation, no page matching one word."""
    assert [h["id"] for h in docs.search("формы список")] == [_PAIR]


def test_search_empty_query(docs_root):
    assert docs.search("   ") == []
    assert docs.search("!!!") == []  # no word tokens


def test_page(docs_root):
    p = docs.page(_QUERY)
    assert p["title"] == "Запрос" and p["availability"] == "Сервер"
    assert p["url"].endswith("/Query_ru/") and "<h1>" in p["html"]
    assert "parent" not in p
    assert docs.page("нет") is None


def test_for_symbol_confident_only(docs_root):
    assert docs.for_symbol("Массив") == _ARRAY                      # exact title
    assert docs.for_symbol("Запрос") == _QUERY
    assert docs.for_symbol("выборка") is None                       # text-only match - do not guess
    assert docs.for_symbol("такого-нет-нигде") is None


def test_for_symbol_ignores_a_qualifier_borrowed_by_a_topic(tmp_path):
    """A topic's `qualified` is whatever `Std::...` its prose quotes first - matching on it
    documented `Add` with an article about breakpoints. Reference pages only."""
    pages = list(_PAGES) + [
        ("topics/set-method-breakpoint", "topic", "Как установить точку останова",
         "Стд::Массив::Добавить", "", "https://host/bp/", "<h1>Точка останова</h1>", "точка"),
    ]
    _write_docs(tmp_path, pages)
    dataset.set_data_root(tmp_path)
    try:
        assert docs.for_symbol("Добавить") is None
        assert docs.for_symbol("Массив") == _ARRAY  # the reference page still answers
    finally:
        dataset.set_data_root(None)


def test_type_pages(docs_root):
    # the bulk read for extract_uischema: type pages only, ordered by id
    pages = docs.type_pages()
    assert [p["title"] for p in pages] == ["Массив", "Запрос"]
    assert set(pages[0]) == {"id", "title", "qualified", "html"}
    dataset.set_data_root(docs_root.parent / "нет")
    try:
        assert docs.type_pages() == []
    finally:
        dataset.set_data_root(docs_root)


def test_tree(docs_root):
    nodes = {n["node"]: n for n in docs.tree()}
    assert set(nodes) == {1, 2, 3, 4}
    assert nodes[1]["parent"] is None and nodes[1]["kind"] == "section" and nodes[1]["page"] is None
    assert nodes[2]["parent"] == 1 and nodes[2]["label"] == "Массив" and nodes[2]["page"] == _ARRAY
    # a heading node: under a link node, carries the page and the section anchor
    assert nodes[3]["kind"] == "heading" and nodes[3]["parent"] == 2
    assert nodes[3]["page"] == _ARRAY and nodes[3]["anchor"] == "иерархия"


def test_asset(docs_root):
    a = docs.asset("assets/i.png")
    assert a["mime"] == "image/png" and a["bytes"].startswith(b"\x89PNG")
    assert docs.asset("assets/нет.png") is None
    assert docs.asset("../../secret.txt") is None   # escaping the directory is forbidden


def test_summarize_pure():
    # A reference page: the sentence after the availability marker.
    ref = (
        "<h1>Справочник</h1><p>Стд::Справочники::Справочник</p>"
        "<p>Доступность: КлиентИСервер</p>"
        "<p>Базовый тип для всех менеджеров справочников. Прочее.</p>"
    )
    assert docs._summarize(ref) == "Базовый тип для всех менеджеров справочников."
    # A topic page: the sentence after "Общее описание".
    topic = "<h1>Структура</h1><h2>Общее описание</h2><p>Структура имеет фиксированный набор полей. Ещё.</p>"
    assert docs._summarize(topic) == "Структура имеет фиксированный набор полей."
    # No marker: the first sentence, tags stripped.
    assert docs._summarize("<p>Просто первое предложение. Второе.</p>") == "Просто первое предложение."
    assert docs._summarize("") == ""
