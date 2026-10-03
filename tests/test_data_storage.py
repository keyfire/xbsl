"""Storage must preserve logical data while sharing immutable contents."""
import importlib
import importlib.util
import json
from pathlib import Path

import pytest


def storage():
    assert importlib.util.find_spec("xbsl.data_storage") is not None, "shared storage is not implemented"
    return importlib.import_module("xbsl.data_storage")


def source_tree(root):
    root.mkdir()
    versions = ["1.0+1", "1.1+2"]
    (root / "index.json").write_text(json.dumps({"available": versions, "default": versions[-1]}), encoding="utf-8")
    for version in versions:
        folder = root / version
        folder.mkdir()
        data = {"meta": {"element_version": version}, "values": {"z": [True, 1, None], "a": {"value": "shared"}}}
        (folder / "language.json").write_text(json.dumps(data), encoding="utf-8")
        (folder / "terms.json").write_text(json.dumps({"types": {"Строка": "String"}, "properties": {"Строка": "Row"}}), encoding="utf-8")
        (folder / "assets" / "images").mkdir(parents=True)
        (folder / "assets" / "images" / "one.png").write_bytes(b"same image")
        (folder / "assets" / "images" / "two.png").write_bytes(b"same image")
    return versions


def test_round_trip_preserves_order_values_and_term_roles(tmp_path):
    versions = source_tree(tmp_path / "source")
    api = storage()
    api.pack(tmp_path / "source", tmp_path / "packed")
    for version in versions:
        for name in ("language.json", "terms.json"):
            expected = json.loads((tmp_path / "source" / version / name).read_text(encoding="utf-8"))
            actual = api.raw_json(tmp_path / "packed", version, name)
            assert actual == expected
            assert json.dumps(actual) == json.dumps(expected)
    assert api.raw_json(tmp_path / "packed", versions[0], "missing.json") is None


def test_identical_assets_have_one_copy_and_keep_logical_names(tmp_path):
    versions = source_tree(tmp_path / "source")
    api = storage()
    api.pack(tmp_path / "source", tmp_path / "packed")
    physical = list((tmp_path / "packed" / "_shared" / "assets").rglob("*.bin"))
    assert len(physical) == 1
    for version in versions:
        for name in ("assets/images/one.png", "assets/images/two.png"):
            assert api.asset(tmp_path / "packed", version, name) == b"same image"
    assert api.asset(tmp_path / "packed", versions[0], "assets/../index.json") is None
    physical[0].unlink()
    with pytest.raises(RuntimeError, match="missing|Missing"):
        api.asset(tmp_path / "packed", versions[0], "assets/images/one.png")


def test_legacy_is_read_without_rewriting_and_objects_do_not_alias(tmp_path):
    versions = source_tree(tmp_path / "source")
    api = storage()
    before = (tmp_path / "source" / "index.json").read_bytes()
    expected = api.raw_json(tmp_path / "source", versions[0], "language.json")
    assert expected["values"]["z"] == [True, 1, None]
    assert api.asset(tmp_path / "source", versions[0], "assets/images/one.png") == b"same image"
    assert (tmp_path / "source" / "index.json").read_bytes() == before

def test_dataset_reads_both_formats_and_keeps_raw_view(tmp_path):
    from xbsl import dataset
    api = storage()
    versions = source_tree(tmp_path / "source")
    api.pack(tmp_path / "source", tmp_path / "packed")
    dataset.set_data_root(tmp_path / "packed")
    try:
        dataset.set_version(versions[0])
        assert dataset.load_json("language.json")["meta"]["element_version"] == versions[0]
        assert dataset.has_data_file("terms.json")
        assert not dataset.has_data_file("missing.json")
        assert dataset.raw_json("terms.json")["properties"]["Строка"] == "Row"
        dataset.set_version(versions[1])
        assert dataset.load_json("language.json")["meta"]["element_version"] == versions[1]
    finally:
        dataset.set_version(None)
        dataset.set_data_root(None)


def test_generation_update_invalidates_the_running_dataset(tmp_path):
    from xbsl import dataset
    api = storage()
    versions = source_tree(tmp_path / "source")
    api.pack(tmp_path / "source", tmp_path / "packed")
    dataset.set_data_root(tmp_path / "packed")
    try:
        assert dataset.load_json("terms.json")["types"]["Строка"] == "String"
        for version in versions:
            source = tmp_path / "source" / version / "terms.json"
            value = json.loads(source.read_text(encoding="utf-8"))
            value["types"]["Строка"] = "Text"
            source.write_text(json.dumps(value), encoding="utf-8")
        api.pack(tmp_path / "source", tmp_path / "packed")
        assert dataset.load_json("terms.json")["types"]["Строка"] == "Text"
        paths = {name for root, version, name in dataset.data_reads()}
        assert any("catalog/" in name or "catalog\\" in name for name in paths)
    finally:
        dataset.set_data_root(None)
def test_partial_update_keeps_other_version_and_export_preserves_views(tmp_path):
    api = storage()
    versions = source_tree(tmp_path / "source")
    api.pack(tmp_path / "source", tmp_path / "packed")
    value_path = tmp_path / "source" / versions[0] / "terms.json"
    value = json.loads(value_path.read_text(encoding="utf-8"))
    value["types"]["Строка"] = "Text"
    value_path.write_text(json.dumps(value), encoding="utf-8")
    api.pack(tmp_path / "source", tmp_path / "packed", versions=[versions[0]])
    assert api.index(tmp_path / "packed")["available"] == versions
    assert api.raw_json(tmp_path / "packed", versions[0], "terms.json")["types"]["Строка"] == "Text"
    assert api.raw_json(tmp_path / "packed", versions[1], "terms.json")["types"]["Строка"] == "String"
    api.export(tmp_path / "packed", tmp_path / "export")
    assert api.raw_json(tmp_path / "export", versions[1], "terms.json")["types"]["Строка"] == "String"
    assert api.asset(tmp_path / "export", versions[1], "assets/images/one.png") == b"same image"


def test_verified_pruning_preserves_reachable_shared_resources(tmp_path):
    api = storage()
    versions = source_tree(tmp_path / "source")
    api.pack(tmp_path / "source", tmp_path / "packed")
    stale = tmp_path / "packed" / "_shared" / "assets" / "00" / ("0" * 64 + ".bin")
    stale.parent.mkdir(exist_ok=True)
    stale.write_bytes(b"unused")
    result = api.prune(tmp_path / "packed")
    assert stale.exists()
    assert result["unused"]
    api.prune(tmp_path / "packed", apply=True)
    assert not stale.exists()
    assert api.verify(tmp_path / "packed")["valid"]
    assert api.asset(tmp_path / "packed", versions[1], "assets/images/one.png") == b"same image"


def test_failed_pack_does_not_publish_a_partial_generation(tmp_path, monkeypatch):
    api = storage()
    source_tree(tmp_path / "source")
    api.pack(tmp_path / "source", tmp_path / "packed")
    before = (tmp_path / "packed" / "index.json").read_bytes()
    original = api.Builder.write
    def broken(self, connection):
        original(self, connection)
        raise RuntimeError("probe failure")
    monkeypatch.setattr(api.Builder, "write", broken)
    with pytest.raises(RuntimeError, match="probe failure"):
        api.pack(tmp_path / "source", tmp_path / "packed")
    assert (tmp_path / "packed" / "index.json").read_bytes() == before
def test_cli_storage_commands_round_trip(tmp_path, capsys):
    from xbsl import cli
    assert any(command.name == "data-pack" for command in cli.COMMANDS), "storage commands are not registered"
    source_tree(tmp_path / "source")
    assert cli.main(["data-pack", str(tmp_path / "source"), str(tmp_path / "packed"), "--lang", "en"]) == 0
    assert json.loads(capsys.readouterr().out)["versions"] == ["1.0+1", "1.1+2"]
    assert cli.main(["data-verify", str(tmp_path / "packed"), "--lang", "en"]) == 0
    assert json.loads(capsys.readouterr().out)["valid"]
    assert cli.main(["data-export", str(tmp_path / "packed"), str(tmp_path / "export"), "--lang", "en"]) == 0
    capsys.readouterr()
    assert cli.main(["data-prune", str(tmp_path / "packed"), "--lang", "en"]) == 0
    assert not json.loads(capsys.readouterr().out)["deleted"]
def test_compiled_views_are_checked_against_canonical_objects(tmp_path):
    api = storage()
    source_tree(tmp_path / "source")
    api.pack(tmp_path / "source", tmp_path / "packed")
    path = api.catalog_path(tmp_path / "packed")
    connection = __import__("sqlite3").connect(path)
    tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_master")}
    assert "view_cache" in tables, "fast derived views are not implemented"
    connection.close()
    assert api.verify(tmp_path / "packed")["valid"]
def test_partial_extract_stages_legacy_files_before_publishing(tmp_path, monkeypatch):
    from xbsl import extract
    from xbsl.extract import _distro, grammar
    api = storage()
    versions = source_tree(tmp_path / "source")
    api.pack(tmp_path / "source", tmp_path / "packed")
    distribution = tmp_path / "dist"
    distribution.mkdir()
    (distribution / "sample-element-server-with-ide-1.0.0.car").write_bytes(b"probe")
    def extracted(argv):
        folder = _distro.data_root() / versions[0]
        path = folder / "language.json"
        value = json.loads(path.read_text(encoding="utf-8"))
        value["extracted"] = True
        path.write_text(json.dumps(value), encoding="utf-8")
    monkeypatch.setattr(grammar, "main", extracted)
    try:
        assert extract.main(["--data-dir", str(tmp_path / "packed"), "--element-version", versions[0], "--dist", str(distribution), "--only", "grammar"]) == 0
        assert api.raw_json(tmp_path / "packed", versions[0], "language.json")["extracted"]
        assert "extracted" not in api.raw_json(tmp_path / "packed", versions[1], "language.json")
        assert api.index(tmp_path / "packed")["storage"]["format"] == 1
    finally:
        _distro.set_data_root(None)
def test_export_rejects_version_paths_before_creating_directories(tmp_path):
    api = storage()
    root = tmp_path / "source"
    root.mkdir()
    (root / "index.json").write_text(json.dumps({"available": ["../outside"], "default": "../outside"}), encoding="utf-8")
    target = tmp_path / "result"
    with pytest.raises(RuntimeError, match="path|version"):
        api.export(root, target)
    assert not (tmp_path / "outside").exists()
def test_removing_one_version_keeps_shared_images_and_cleans_empty_directory(tmp_path):
    api = storage()
    versions = source_tree(tmp_path / "source")
    api.pack(tmp_path / "source", tmp_path / "packed")
    api.export(tmp_path / "packed", tmp_path / "remaining", versions=[versions[1]])
    api.pack(tmp_path / "remaining", tmp_path / "packed")
    api.prune(tmp_path / "packed", apply=True)
    assert api.index(tmp_path / "packed")["available"] == [versions[1]]
    assert api.asset(tmp_path / "packed", versions[1], "assets/images/one.png") == b"same image"
    assert not (tmp_path / "packed" / versions[0]).exists()


def test_same_inputs_produce_identical_generations(tmp_path):
    api = storage()
    source_tree(tmp_path / "source")
    api.pack(tmp_path / "source", tmp_path / "first")
    api.pack(tmp_path / "source", tmp_path / "second")
    first = {p.relative_to(tmp_path / "first").as_posix(): p.read_bytes() for p in api.referenced_files(tmp_path / "first")}
    second = {p.relative_to(tmp_path / "second").as_posix(): p.read_bytes() for p in api.referenced_files(tmp_path / "second")}
    assert first == second

def test_partial_update_keeps_build_numbers_of_other_versions(tmp_path):
    api = storage()
    versions = source_tree(tmp_path / "source")
    path = tmp_path / "source" / "index.json"
    initial = json.loads(path.read_text(encoding="utf-8"))
    initial["builds"] = {versions[0]: "11", versions[1]: "22"}
    path.write_text(json.dumps(initial), encoding="utf-8")
    api.pack(tmp_path / "source", tmp_path / "packed")
    initial["available"] = [versions[0]]
    initial["default"] = versions[0]
    initial["builds"] = {versions[0]: "12"}
    path.write_text(json.dumps(initial), encoding="utf-8")
    api.pack(tmp_path / "source", tmp_path / "packed", versions=[versions[0]])
    assert api.index(tmp_path / "packed")["builds"] == {versions[0]: "12", versions[1]: "22"}


def test_individual_grammar_extractor_updates_packed_view(tmp_path, monkeypatch):
    from xbsl.extract import grammar, _distro
    api = storage()
    versions = source_tree(tmp_path / "source")
    api.pack(tmp_path / "source", tmp_path / "packed")
    monkeypatch.setattr(grammar, "resolve_grammar", lambda *args: ("RULE_IF_KW : ('if');", "RULE_IF_KW=5"))
    try:
        assert grammar.main(["--data-dir", str(tmp_path / "packed"), "--element-version", versions[0]]) == 0
        result = api.raw_json(tmp_path / "packed", versions[0], "language.json")
        assert "keywords" in result
        assert "values" not in result
    finally:
        _distro.set_data_root(None)
