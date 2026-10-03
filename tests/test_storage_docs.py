"""Shared documentation keeps version-specific search and logical page records."""
import json
import sqlite3

from xbsl import data_storage, dataset, docs
from xbsl.extract.docs import _SCHEMA


def source(root):
    root.mkdir()
    versions = ["1.0+1", "1.1+2"]
    (root / "index.json").write_text(json.dumps({"available": versions, "default": versions[-1]}), encoding="utf-8")
    for version in versions:
        folder = root / version
        folder.mkdir()
        (folder / "terms.json").write_text(json.dumps({"types": {"Массив": "Array"}}), encoding="utf-8")
        connection = sqlite3.connect(folder / "docs.sqlite")
        connection.executescript(_SCHEMA)
        pages = [("types/Array", "type", "Массив", "Std::Array", "Client", "https://example.org/Array", "<h1>Массив</h1><p>Общая коллекция значений.</p>"),
                 ("guide", "guide", version, "", "", "https://example.org/guide", "<h1>" + version + "</h1><p>Коллекция специальная.</p>")]
        for rowid, record in zip((11, 37), pages):
            connection.execute("INSERT INTO pages(rowid,id,kind,title,qualified,availability,url,html) VALUES(?,?,?,?,?,?,?,?)", (rowid, *record))
            connection.execute("INSERT INTO pages_fts(rowid,id,title,qualified,text) VALUES(?,?,?,?,?)", (rowid, record[0], record[2], record[3], docs.plain_text(record[6])))
        connection.execute("INSERT INTO tree VALUES(1,NULL,0,'Types','types/Array',NULL,'type')")
        connection.commit()
        connection.close()
    return versions


def responses(root, version):
    dataset.set_data_root(root)
    dataset.set_version(version)
    return {"tree": docs.tree(), "types": docs.type_pages(), "guides": docs.guide_pages(),
            "search": docs.search("коллекция"), "page": docs.page("guide"), "symbol": docs.for_symbol("Массив")}


def test_shared_pages_keep_search_results_and_versions(tmp_path):
    versions = source(tmp_path / "old")
    try:
        expected = {v: responses(tmp_path / "old", v) for v in versions}
        data_storage.pack(tmp_path / "old", tmp_path / "new")
        for version in versions:
            assert responses(tmp_path / "new", version) == expected[version]
        catalog = data_storage.catalog_path(tmp_path / "new")
        connection = sqlite3.connect(catalog)
        assert connection.execute("SELECT COUNT(*) FROM docs_content").fetchone()[0] == 3
        assert not connection.execute("SELECT name FROM sqlite_master WHERE name LIKE 'fts_%_content'").fetchall()
        connection.close()
    finally:
        dataset.set_version(None)
        dataset.set_data_root(None)


def test_repacking_and_export_keep_legacy_page_rowids(tmp_path):
    versions = source(tmp_path / "old")
    data_storage.pack(tmp_path / "old", tmp_path / "packed")
    connection = data_storage.open_docs(tmp_path / "packed", versions[0])
    try:
        assert [row[0] for row in connection.execute("SELECT rowid FROM pages ORDER BY rowid")] == [11, 37]
    finally:
        connection.close()
    data_storage.pack(tmp_path / "packed", tmp_path / "repacked")
    data_storage.export(tmp_path / "repacked", tmp_path / "exported")
    connection = sqlite3.connect(tmp_path / "exported" / versions[0] / "docs.sqlite")
    assert [row[0] for row in connection.execute("SELECT rowid FROM pages ORDER BY rowid")] == [11, 37]
    connection.close()


def test_missing_shared_page_lookup_has_bounded_work(tmp_path, monkeypatch):
    """An indexed page miss must not walk all canonical page contents."""
    versions = source(tmp_path / "old")
    connection = sqlite3.connect(tmp_path / "old" / versions[0] / "docs.sqlite")
    connection.executemany(
        "INSERT INTO pages(id,kind,title,qualified,availability,url,html) VALUES(?,?,?,?,?,?,?)",
        [(f"filler/{i}", "guide", f"Page {i}", "", "", "", "<p>Filler</p>") for i in range(1000)],
    )
    connection.commit()
    connection.close()
    data_storage.pack(tmp_path / "old", tmp_path / "packed")
    shared = data_storage.open_docs(tmp_path / "packed", versions[0])
    steps = 0

    def budget():
        nonlocal steps
        steps += 100
        return steps > 5000

    shared.set_progress_handler(budget, 100)
    monkeypatch.setattr(docs, "_open", lambda version=None: shared)
    # The VM budget detects a table scan without depending on wall-clock timing.
    assert docs.page("not-present") is None