"""Lazy standard-method documentation on synthetic reference pages."""

import json
import sqlite3

import pytest

from xbsl import dataset
from xbsl.extract.docs import _SCHEMA
from xbsl.lsp_nav import IndexLookup, resolve_completions


@pytest.mark.parametrize(
    "prefix, context",
    [
        ("Vessel.", {}),
        ("thing.", {"local_vars": {"thing": "Vessel"}}),
        ("thing.Make().", {"expr_type": "Vessel"}),
        ("Компоненты.Box.", {}),
        ("thing.Child.", {"expr_type": "ProjectChild"}),
    ],
)
def test_standard_method_completion_retains_its_owner(prefix, context):
    lookup = IndexLookup({
        "components": [{"form": "Form", "name": "Box", "type": "Vessel<Item>"}],
        "struct_members": {"ProjectChild": {"base": "Vessel", "methods": ["Local"]}},
    })
    entries = resolve_completions(
        lookup, language_id="xbsl", line_prefix=prefix, file_stem="Form",
        stdlib_members={"Vessel": {"methods": ["Gather"], "properties": ["Capacity"]}},
        **context,
    )
    method = next(entry for entry in entries if entry["label"] == "Gather")
    assert method.get("data") == {
        "xbsl_stdlib": {"owner": "Vessel", "member": "Gather", "language": "ru"},
    }
    assert "doc" not in method
    assert all("data" not in entry for entry in entries if entry["label"] != "Gather")

_VESSEL_BLOCK = (
    '<h3 id="gather">Собрать</h3><p><code>ClientAndServer</code></p>'
    '<p><pre><code>Собрать(Шаг: Число): Число</code></pre>'
    'Gathers <code>units</code> in a synthetic vessel.<p></p>'
    '<p><strong>Параметры</strong></p>'
    '<dl><dt>Шаг: <code>Число</code></dt><dd>Number of units per step.</dd></dl>'
    '<h4>Примеры</h4><pre><code>IgnoreThisExample()</code></pre>'
)
_MIX_BLOCK = (
    '<h3>Mix</h3><pre><code>Mix(left: Map&lt;String, Number&gt;, right: String = "a,b"): Number</code></pre>'
    '<p>Combines synthetic inputs.</p><h4>Examples</h4><p>Hidden example.</p>'
    '<h3>Mix</h3><pre><code>Mix(left: Number): Number</code></pre>'
    '<p>Combines one synthetic input.</p>'
)


@pytest.fixture
def reference_data(tmp_path):
    version = "9.9.9+0"
    directory = tmp_path / version
    directory.mkdir()
    (tmp_path / "index.json").write_text(
        json.dumps({"available": [version], "default": version}), encoding="utf-8",
    )
    catalog = {
        "meta": {"bilingual_keys": "expand"}, "bases": {"Резервуар": ["Сосуд"]},
        "type_members": {"Сосуд": {"methods": ["Собрать", "Mix"]},
                         "Резервуар": {"methods": ["Собрать"]}},
    }
    (directory / "stdlib.json").write_text(json.dumps(catalog), encoding="utf-8")
    (directory / "terms.json").write_text(json.dumps({
        "types": {"Сосуд": "Vessel", "Резервуар": "Reservoir", "Число": "Number", "Строка": "String"},
    }), encoding="utf-8")
    (directory / "terms_full.json").write_text(json.dumps({
        "common": {"Сосуд": "Vessel", "Резервуар": "Reservoir", "Число": "Number", "Строка": "String",
                   "Собрать": "Gather", "Шаг": "Step"},
        "members": {"Vessel": {"Собрать": "Gather"}},
    }), encoding="utf-8")
    with sqlite3.connect(directory / "docs.sqlite") as connection:
        connection.executescript(_SCHEMA)
        for page_id, title, block in (
            ("stdlib/demo/Vessel_ru", "Сосуд", _VESSEL_BLOCK + _MIX_BLOCK),
            ("stdlib/demo/Other_ru", "Other", '<h3>Собрать</h3><pre><code>Собрать(): Строка</code></pre>'
             '<p>Wrong receiver description.</p><h3>Evaporate</h3><pre><code>Evaporate(): Number</code></pre>'
             '<p>Another receiver alone declares this method.</p>'),
        ):
            connection.execute("INSERT INTO pages VALUES(?,?,?,?,?,?,?)", (
                page_id, "type", title, f"Std::{title}", "ClientAndServer", "https://example.test/help/",
                f"<h1>{title}</h1><h2>Методы</h2>{block}",
            ))
    dataset.set_data_root(tmp_path)
    yield tmp_path
    dataset.set_data_root(None)


def _resolved_item(data, documentation=None):
    pytest.importorskip("pygls")
    from xbsl import lsp

    server = lsp._make_server()
    manager = getattr(server.lsp, "fm", None) or getattr(server.lsp, "_features", None)
    features = getattr(manager, "features", manager)
    item = lsp.lsp.CompletionItem(label="Selected", data=data, documentation=documentation)
    return features[lsp.lsp.COMPLETION_ITEM_RESOLVE](item)


def _data(owner="Сосуд", member="Собрать", language="ru"):
    return {"xbsl_stdlib": {"owner": owner, "member": member, "language": language}}


def test_selected_standard_method_shows_signature_description_and_parameters(reference_data):
    item = _resolved_item(_data())
    assert item.documentation is not None
    text = item.documentation.value
    assert "```xbsl\nСобрать(Шаг: Число): Число\n```" in text
    assert "Gathers `units` in a synthetic vessel." in text
    assert "**Параметры**" in text and "`Шаг: Число`" in text
    assert "Number of units per step." in text
    assert "IgnoreThisExample" not in text and "ClientAndServer" not in text
    assert "Wrong receiver" not in text


def test_inherited_standard_method_uses_its_declaring_type(reference_data):
    item = _resolved_item(_data(owner="Резервуар"))
    assert item.documentation is not None
    assert "Gathers `units`" in item.documentation.value
    assert "Wrong receiver" not in item.documentation.value


def test_english_completion_shows_english_signature_with_the_same_description(reference_data):
    item = _resolved_item(_data(owner="Vessel", language="en"))
    assert item.documentation is not None
    text = item.documentation.value
    assert "Gather(Step: Number): Number" in text
    assert "**Parameters**" in text and "`Step: Number`" in text
    assert "Gathers `units`" in text


def test_overload_parameters_keep_nested_generics_and_quoted_defaults(reference_data):
    item = _resolved_item(_data(member="Mix", language="en"))
    assert item.documentation is not None
    text = item.documentation.value
    assert 'Mix(left: Map<String, Number>, right: String = "a,b"): Number' in text
    assert "Mix(left: Number): Number" in text
    assert "`left: Map<String, Number>`" in text
    assert '`right: String = "a,b"`' in text
    assert "Hidden example" not in text


def test_completion_documentation_is_not_borrowed_from_an_unrelated_type(reference_data):
    assert _resolved_item(_data(member="Evaporate")).documentation is None


@pytest.mark.parametrize("data", [None, {}, {"xbsl_stdlib": {}},
                                  {"xbsl_stdlib": {"owner": [], "member": "Gather"}}])
def test_invalid_or_project_completion_data_keeps_documentation_empty(reference_data, data):
    assert _resolved_item(data).documentation is None


def test_existing_project_documentation_is_preserved(reference_data):
    item = _resolved_item(_data(), documentation="Project author comment.")
    assert item.documentation == "Project author comment."


def test_absent_reference_database_keeps_completion_usable(tmp_path):
    dataset.set_data_root(tmp_path)
    try:
        item = _resolved_item(_data())
        assert item.label == "Selected" and item.documentation is None
    finally:
        dataset.set_data_root(None)


def test_completion_list_defers_docs_until_selection(reference_data, tmp_path, monkeypatch):
    from types import SimpleNamespace

    pytest.importorskip("pygls")
    from pygls import uris
    from pygls.workspace import Workspace
    from xbsl import docs, lsp

    path = tmp_path / "Probe.xbsl"
    path.write_text("Vessel.", encoding="utf-8")
    server = lsp._make_server()
    server.lsp._workspace = Workspace(uris.from_fs_path(str(tmp_path)))
    monkeypatch.setattr(lsp.STATE, "root", None)
    monkeypatch.setattr(lsp.STATE, "lookup", IndexLookup({}))
    manager = getattr(server.lsp, "fm", None) or getattr(server.lsp, "_features", None)
    features = getattr(manager, "features", manager)
    feature_options = getattr(manager, "feature_options", {})
    assert feature_options[lsp.lsp.TEXT_DOCUMENT_COMPLETION].resolve_provider is True
    calls = []
    original = docs.page

    def lookup_member(name, version=None):
        calls.append(name)
        return original(name, version)

    monkeypatch.setattr(docs, "page", lookup_member)
    answer = features[lsp.lsp.TEXT_DOCUMENT_COMPLETION](SimpleNamespace(
        text_document=SimpleNamespace(uri=uris.from_fs_path(str(path))),
        position=SimpleNamespace(line=0, character=7),
    ))
    item = next(entry for entry in answer.items if entry.label == "Собрать")
    assert item.data == _data(owner="Vessel")
    assert item.documentation is None and calls == []
    resolved = features[lsp.lsp.COMPLETION_ITEM_RESOLVE](item)
    assert resolved.documentation is not None
    assert calls == ["stdlib/demo/Vessel_ru"]


def test_corrupt_reference_lookup_keeps_completion_usable(reference_data, monkeypatch):
    from xbsl import docs

    def broken_lookup(*args, **kwargs):
        raise sqlite3.OperationalError("Synthetic broken database")

    monkeypatch.setattr(docs, "page", broken_lookup)
    item = _resolved_item(_data())
    assert item.label == "Selected" and item.documentation is None


def test_english_signature_keeps_the_written_string_default(reference_data):
    from xbsl import completion_docs

    block = ('<h3>Собрать</h3><pre><code>Собрать(Шаг: Строка = "Шаг"): Число</code></pre>'
             '<p>Synthetic default value.</p>')
    text = completion_docs._markdown(block, "Собрать", "en")
    assert 'Gather(Step: String = "Шаг"): Number' in text


def test_description_keeps_generic_inline_code(reference_data):
    from xbsl import completion_docs

    block = ('<h3>Mix</h3><pre><code>Mix(): Number</code></pre>'
             '<p>Returns <code>Map&lt;String, Number&gt;</code> values.</p>')
    text = completion_docs._markdown(block, "Mix", "en")
    assert "Returns `Map<String, Number>` values." in text


@pytest.mark.parametrize("annotation", [
    "@ПроверятьИспользованиеЗначения",
    '@Устарело(Сообщение = "Use a synthetic replacement")',
])
def test_documentation_annotations_do_not_hide_the_method_signature(reference_data, annotation):
    from xbsl import completion_docs

    block = f'<h3>Mix</h3><pre><code>{annotation} Mix(value: Number): Number</code></pre>'
    block += '<p>Synthetic annotated method.</p>'
    text = completion_docs._markdown(block, "Mix", "en")
    assert "```xbsl\nMix(value: Number): Number\n```" in text
    assert "Synthetic annotated method." in text


@pytest.fixture
def receiver_spelling_data(reference_data):
    path = reference_data / "9.9.9+0" / "terms_full.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    data["members"]["Vessel"]["Собрать"] = "Collect"
    path.write_text(json.dumps(data), encoding="utf-8")
    dataset.set_data_root(reference_data)
    return reference_data


@pytest.mark.parametrize("owner", ["Vessel", "Reservoir"])
def test_english_signature_uses_the_receivers_member_spelling(receiver_spelling_data, owner):
    item = _resolved_item(_data(owner=owner, language="en"))
    assert item.documentation is not None
    assert "Collect(Step: Number): Number" in item.documentation.value
    assert "Gather(Step: Number)" not in item.documentation.value


@pytest.mark.parametrize("owner", ["Vessel", "Reservoir"])
def test_english_completion_label_matches_the_receivers_signature(receiver_spelling_data, owner):
    entries = resolve_completions(
        IndexLookup({}), language_id="xbsl", line_prefix=f"{owner}.", file_stem="Probe",
        stdlib_members={owner: {"methods": ["Собрать"]}}, project_language="en",
    )
    assert entries[0]["label"] == "Collect"
    assert entries[0]["snippet"] == "Collect($0)"
    item = _resolved_item(entries[0]["data"])
    assert item.documentation is not None
    assert "Collect(Step: Number): Number" in item.documentation.value


def test_receiver_member_spelling_does_not_rename_a_parameter_of_the_same_name(receiver_spelling_data):
    path = receiver_spelling_data / "9.9.9+0" / "docs.sqlite"
    with sqlite3.connect(path) as connection:
        connection.execute("UPDATE pages SET html=? WHERE id=?", (
            '<h1>Сосуд</h1><h2>Методы</h2><h3>Собрать</h3>'
            '<pre><code>Собрать(Собрать: Число): Число</code></pre><p>Synthetic name collision.</p>',
            "stdlib/demo/Vessel_ru",
        ))
    item = _resolved_item(_data(owner="Vessel", language="en"))
    assert item.documentation is not None
    assert "Collect(Gather: Number): Number" in item.documentation.value
    assert "`Gather: Number`" in item.documentation.value


@pytest.mark.parametrize("owner", ["Vessel", "Reservoir"])
def test_selected_reference_method_does_not_build_the_global_member_index(reference_data, monkeypatch, owner):
    from xbsl import docs

    def forbidden_index(*args, **kwargs):
        raise AssertionError("A selected owner must not scan every reference page")

    monkeypatch.setattr(docs, "_member_index", forbidden_index)
    item = _resolved_item(_data(owner=owner, language="en"))
    assert item.documentation is not None
    assert "Gather(Step: Number): Number" in item.documentation.value


def test_missing_selected_method_does_not_scan_unrelated_reference_pages(reference_data, monkeypatch):
    from xbsl import docs

    calls = []

    def forbidden_index(*args, **kwargs):
        calls.append("global index")
        raise AssertionError("A missing selected method must stay a bounded lookup")

    monkeypatch.setattr(docs, "_member_index", forbidden_index)
    item = _resolved_item(_data(owner="Vessel", member="Evaporate"))
    assert item.documentation is None and calls == []


def test_inherited_method_prefers_the_nearest_declaring_type(reference_data):
    directory = reference_data / "9.9.9+0"
    path = directory / "stdlib.json"
    catalog = json.loads(path.read_text(encoding="utf-8"))
    catalog["bases"] = {"Резервуар": ["BaseRoot", "Сосуд"], "Сосуд": ["BaseRoot"]}
    path.write_text(json.dumps(catalog), encoding="utf-8")
    with sqlite3.connect(directory / "docs.sqlite") as connection:
        connection.execute("INSERT INTO pages VALUES(?,?,?,?,?,?,?)", (
            "stdlib/demo/BaseRoot_ru", "type", "BaseRoot", "Std::BaseRoot", "ClientAndServer",
            "https://example.test/root/", '<h1>BaseRoot</h1><h2>Методы</h2><h3>Собрать</h3>'
            '<pre><code>Собрать(Шаг: Число): Число</code></pre><p>Wrong distant ancestor.</p>',
        ))
    dataset.set_data_root(reference_data)
    item = _resolved_item(_data(owner="Reservoir", language="en"))
    assert item.documentation is not None
    assert "Gathers `units`" in item.documentation.value
    assert "Wrong distant ancestor" not in item.documentation.value


def test_fast_lookup_resolves_the_owner_specific_english_member_name(receiver_spelling_data):
    item = _resolved_item(_data(owner="Vessel", member="Collect", language="en"))
    assert item.documentation is not None
    assert "Collect(Step: Number): Number" in item.documentation.value


def test_fast_lookup_rejects_the_wrong_common_english_member_name(receiver_spelling_data):
    item = _resolved_item(_data(owner="Vessel", member="Gather", language="en"))
    assert item.documentation is None


def test_equally_near_declaring_bases_do_not_supply_an_arbitrary_description(reference_data):
    path = reference_data / "9.9.9+0" / "stdlib.json"
    catalog = json.loads(path.read_text(encoding="utf-8"))
    catalog["bases"] = {"Резервуар": ["Сосуд", "Other"]}
    path.write_text(json.dumps(catalog), encoding="utf-8")
    dataset.set_data_root(reference_data)
    assert _resolved_item(_data(owner="Reservoir", language="en")).documentation is None


@pytest.mark.parametrize("mixed_aliases", [False, True])
def test_incomparable_declaring_bases_remain_ambiguous_despite_different_ancestor_counts(reference_data, mixed_aliases):
    directory = reference_data / "9.9.9+0"
    path = directory / "stdlib.json"
    catalog = json.loads(path.read_text(encoding="utf-8"))
    receiver = "Reservoir" if mixed_aliases else "Резервуар"
    vessel = "Vessel" if mixed_aliases else "Сосуд"
    catalog["bases"] = {receiver: [vessel, "Other", "Grand"], "Other": ["Grand"]}
    path.write_text(json.dumps(catalog), encoding="utf-8")
    dataset.set_data_root(reference_data)
    item = _resolved_item(_data(owner="Reservoir", language="en"))
    assert item.documentation is None
