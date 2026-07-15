"""Рантайм-API документации (xbsllint/docs.py) на крошечной БД, собранной в тесте (без дистрибутива)."""

import sqlite3
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))
import extract_docs as ex  # noqa: E402
from xbsllint import dataset, docs  # noqa: E402


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
# id, kind, title, qualified, availability, url, html, text(для FTS)
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
    (3, 2, 0, "Иерархия", _ARRAY, "иерархия", "heading"),  # раздел страницы под узлом-ссылкой
    (4, 1, 1, "Запрос", _QUERY, None, "link"),
]


@pytest.fixture
def docs_root(tmp_path):
    """Каталог данных с крошечной docs.sqlite; docs.py читает её как настоящую."""
    ver_dir = tmp_path / _VER
    ver_dir.mkdir()
    con = sqlite3.connect(ver_dir / "docs.sqlite")
    con.executescript(ex._SCHEMA)
    for p in _PAGES:
        con.execute("INSERT INTO pages VALUES(?,?,?,?,?,?,?)", p[:7])  # text – только в FTS
        con.execute("INSERT INTO pages_fts(id,title,qualified,text) VALUES(?,?,?,?)",
                    (p[0], p[2], p[3], p[7]))
    con.executemany("INSERT INTO tree VALUES(?,?,?,?,?,?,?)", _TREE)
    con.commit()
    con.close()
    (ver_dir / "assets").mkdir()
    (ver_dir / "assets" / "i.png").write_bytes(b"\x89PNG\r\n\x1a\n")  # картинка файлом рядом с базой
    (tmp_path / "index.json").write_text(
        '{"available": ["%s"], "default": "%s"}' % (_VER, _VER), encoding="utf-8"
    )
    dataset.set_data_root(tmp_path)
    yield tmp_path
    dataset.set_data_root(None)


def test_available(docs_root):
    assert docs.available() is True


def test_available_false_without_data(tmp_path):
    dataset.set_data_root(tmp_path)  # пусто, индекса нет
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


def test_search_empty_query(docs_root):
    assert docs.search("   ") == []
    assert docs.search("!!!") == []  # нет словных токенов


def test_page(docs_root):
    p = docs.page(_QUERY)
    assert p["title"] == "Запрос" and p["availability"] == "Сервер"
    assert p["url"].endswith("/Query_ru/") and "<h1>" in p["html"]
    assert "parent" not in p
    assert docs.page("нет") is None


def test_for_symbol_confident_only(docs_root):
    assert docs.for_symbol("Массив") == _ARRAY                      # точный заголовок
    assert docs.for_symbol("Запрос") == _QUERY
    assert docs.for_symbol("выборка") is None                       # только в тексте – не угадываем
    assert docs.for_symbol("такого-нет-нигде") is None


def test_tree(docs_root):
    nodes = {n["node"]: n for n in docs.tree()}
    assert set(nodes) == {1, 2, 3, 4}
    assert nodes[1]["parent"] is None and nodes[1]["kind"] == "section" and nodes[1]["page"] is None
    assert nodes[2]["parent"] == 1 and nodes[2]["label"] == "Массив" and nodes[2]["page"] == _ARRAY
    # узел-заголовок: под узлом-ссылкой, несёт страницу и якорь раздела
    assert nodes[3]["kind"] == "heading" and nodes[3]["parent"] == 2
    assert nodes[3]["page"] == _ARRAY and nodes[3]["anchor"] == "иерархия"


def test_asset(docs_root):
    a = docs.asset("assets/i.png")
    assert a["mime"] == "image/png" and a["bytes"].startswith(b"\x89PNG")
    assert docs.asset("assets/нет.png") is None
    assert docs.asset("../../secret.txt") is None   # выход за каталог запрещён
