"""One-pass unreachable-resource candidates and their read-only CLI/MCP surfaces."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from xbsl import cli, dataset, resource_usage, terms


pytestmark = pytest.mark.needs_data


def _write(root: Path, files: dict[str, str]) -> Path:
    project = root / "acme" / "Demo"
    base = {
        "Project.yaml": (
            "Vendor: acme\nName: Demo\nVersion: 1.0.0\nCompatibilityMode: 9.0\n"
        ),
        "Main/Subsystem.yaml": "Name: Main\n",
    }
    for rel, content in {**base, **files}.items():
        path = project / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    return project


def _module(name: str, body: str) -> dict[str, str]:
    return {
        f"Main/{name}.yaml": (
            f"ElementKind: CommonModule\nName: {name}\nEnvironment: Server\n"
        ),
        f"Main/{name}.xbsl": body,
    }


def _by_key(answer: dict, section: str) -> dict[str, dict]:
    return {item["key"]: item for item in answer[section]}


def test_platform_words_come_from_terms_and_reset_with_the_dataset(monkeypatch):
    spelling = {"suffix": "One"}
    monkeypatch.setattr(
        terms, "key_forms",
        lambda name: (name, f"Literal{spelling['suffix']}"),
    )
    monkeypatch.setattr(
        terms, "forms",
        lambda name, section: (name, f"Package{spelling['suffix']}"),
    )
    monkeypatch.setattr(
        terms, "member_english_of",
        lambda owner, member: f"{member}{spelling['suffix']}",
    )
    resource_usage._platform_words.cache_clear()

    first = resource_usage._platform_words()
    spelling["suffix"] = "Two"
    assert resource_usage._platform_words() is first

    pinned = dataset.pinned_root()
    dataset.set_data_root(dataset.data_root())
    try:
        literal, package, current, get = resource_usage._platform_words()
        assert "LiteralTwo" in literal
        assert "PackageTwo" in package
        assert "ТекущийTwo" in current
        assert "ПолучитьTwo" in get
    finally:
        dataset.set_data_root(pinned)


def test_removing_the_only_static_reference_makes_a_candidate_on_the_next_pass(tmp_path):
    files = {
        "Main/Resources/used.svg": "<svg/>\n",
        **_module(
            "Caller",
            "method Probe(): Resource\n    return Resource{used.svg}\n;\n",
        ),
    }
    project = _write(tmp_path, files)
    first = resource_usage.analyze(project)
    assert "used.svg" not in _by_key(first, "unused")

    (project / "Main" / "Caller.xbsl").write_text(
        "method Probe(): Undefined\n    return Undefined\n;\n", encoding="utf-8",
    )
    second = resource_usage.analyze(project)

    candidate = _by_key(second, "unused")["used.svg"]
    assert candidate["confidence"] == "candidate"
    assert candidate["evidence"] == []


@pytest.mark.parametrize(("package", "current", "get"), [
    ("ResourcesPackage", "Current", "Get"),
    ("ПакетРесурсов", "Текущий", "Получить"),
])
def test_bounded_wrapper_parameter_protects_its_folder_without_project_names(
        tmp_path, package, current, get):
    files = {
        "Main/Resources/icons/a.svg": "<svg/>\n",
        "Main/Resources/icons/b.svg": "<svg/>\n",
        **_module(
            "ResourceApi",
            "method Load(Path: String): Resource\n"
            f"    return {package}.{current}().{get}(Path)\n;\n",
        ),
        **_module(
            "Caller",
            "method Probe(): Resource\n"
            "    return ResourceApi.Load(\"icons/%Name.svg\")\n;\n",
        ),
    }
    answer = resource_usage.analyze(_write(tmp_path, files))

    assert set(_by_key(answer, "dynamic")) == {"icons/a.svg", "icons/b.svg"}
    assert answer["summary"]["unused"] == 0


def test_unbounded_computed_lookup_is_uncertain_instead_of_unused(tmp_path):
    files = {
        "Main/Resources/a.svg": "<svg/>\n",
        "Main/Resources/b.svg": "<svg/>\n",
        **_module(
            "Caller",
            "method BuildName(): String\n    return \"runtime\"\n;\n"
            "method Load(): Resource\n"
            "    return ResourcesPackage.Current().Get(BuildName())\n;\n",
        ),
    }
    answer = resource_usage.analyze(_write(tmp_path, files))

    assert set(_by_key(answer, "uncertain")) == {"a.svg", "b.svg"}
    assert answer["summary"]["unused"] == 0


def test_unbounded_wrapper_argument_is_uncertain_instead_of_unused(tmp_path):
    files = {
        "Main/Resources/a.svg": "<svg/>\n",
        **_module(
            "ResourceApi",
            "method Load(Path: String): Resource\n"
            "    return ResourcesPackage.Current().Get(Path)\n;\n",
        ),
        **_module(
            "Caller",
            "method BuildName(): String\n    return \"runtime\"\n;\n"
            "method Load(): Resource\n"
            "    return ResourceApi.Load(BuildName())\n;\n",
        ),
    }
    answer = resource_usage.analyze(_write(tmp_path, files))

    assert set(_by_key(answer, "uncertain")) == {"a.svg"}
    assert answer["summary"]["unused"] == 0


def test_fully_qualified_reference_can_reach_another_loaded_project(tmp_path):
    local = _write(tmp_path, {
        **_module(
            "Caller",
            "method Probe(): Resource\n"
            "    return Resource{other::Shared::Assets::logo.svg}\n;\n",
        ),
    })
    external = tmp_path / "other" / "Shared"
    external_files = {
        "Project.yaml": (
            "Vendor: other\nName: Shared\nVersion: 1.0.0\nCompatibilityMode: 9.0\n"
        ),
        "Assets/Subsystem.yaml": "Name: Assets\n",
        "Assets/Resources/Resources.yaml": "VisibilityScope: InProject\n",
        "Assets/Resources/logo.svg": "<svg/>\n",
    }
    for rel, content in external_files.items():
        path = external / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")

    answer = resource_usage.analyze(tmp_path)

    logo = next(item for item in answer["referenced"] if item["key"] == "logo.svg")
    assert logo["project"] == str(external)
    assert logo["evidence"][0]["path"] == str(local / "Main" / "Caller.xbsl")


def test_reachable_json_and_css_edges_propagate_but_a_dead_cycle_stays_unused(tmp_path):
    files = {
        "Main/Resources/data.json": '{"icon": "json"}\n',
        "Main/Resources/json.svg": "<svg/>\n",
        "Main/Resources/main.css": "body{background:url(css.svg)}\n",
        "Main/Resources/css.svg": "<svg/>\n",
        "Main/Resources/a.json": '{"next": "b.json"}\n',
        "Main/Resources/b.json": '{"next": "a.json"}\n',
        **_module(
            "Caller",
            "method Probe(): Object\n"
            "    val Data = Resource{data.json}\n"
            "    val Style = Resource{main.css}\n"
            "    return Data\n;\n",
        ),
    }
    answer = resource_usage.analyze(_write(tmp_path, files))
    unused = _by_key(answer, "unused")

    assert {"data.json", "json.svg", "main.css", "css.svg"}.isdisjoint(unused)
    assert {"a.json", "b.json"} <= set(unused)


def test_yaml_image_value_is_a_static_reference(tmp_path):
    project = _write(tmp_path, {
        "Main/Resources/logo.svg": "<svg/>\n",
        "Main/Card.yaml": "ElementKind: Card\nImage: logo.svg\n",
    })

    answer = resource_usage.analyze(project)

    logo = _by_key(answer, "referenced")["logo.svg"]
    assert {item["kind"] for item in logo["evidence"]} == {"yaml-value"}


def test_resource_edges_cannot_escape_the_root_or_load_external_urls(tmp_path):
    outside = tmp_path / "outside.svg"
    outside.write_text("<svg/>\n", encoding="utf-8")
    files = {
        "Main/Resources/main.css": (
            "a{background:url(../../../outside.svg)}\n"
            "b{background:url(https://example.invalid/remote.svg)}\n"
        ),
        **_module("Caller", "method Probe(): Resource\n return Resource{main.css}\n;\n"),
    }
    answer = resource_usage.analyze(_write(tmp_path, files))

    assert answer["summary"]["resources"] == 1
    assert answer["summary"]["referenced"] == 1


def test_hidden_files_are_not_project_resources(tmp_path):
    project = _write(tmp_path, {
        "Main/Resources/.hidden.svg": "<svg/>\n",
        "Main/Resources/visible.svg": "<svg/>\n",
    })
    answer = resource_usage.analyze(project)

    assert answer["summary"]["resources"] == 1
    assert set(_by_key(answer, "unused")) == {"visible.svg"}


def test_empty_root_and_malformed_json_are_safe(tmp_path):
    empty = resource_usage.analyze(tmp_path / "missing")
    assert empty["summary"] == {
        "resources": 0, "referenced": 0, "dynamic": 0, "uncertain": 0, "unused": 0,
    }
    project = _write(tmp_path, {
        "Main/Resources/broken.json": "{broken",
        **_module("Caller", "method Probe(): Resource\n return Resource{broken.json}\n;\n"),
    })
    answer = resource_usage.analyze(project)
    assert answer["summary"]["resources"] == 1
    assert answer["summary"]["referenced"] == 1


def test_parse_error_protects_project_resources_from_unused_candidates(tmp_path):
    project = _write(tmp_path, {
        "Main/Resources/icon.svg": "<svg/>\n",
        **_module(
            "Caller",
            "method Probe(): Resource\n    return Resource{icon.svg}\n",
        ),
    })

    answer = resource_usage.analyze(project)

    assert answer["unused"] == []
    icon = _by_key(answer, "uncertain")["icon.svg"]
    assert {item["kind"] for item in icon["evidence"]} == {"parse-error"}


def _symlink_or_skip(link: Path, target: Path, *, directory: bool = False) -> None:
    try:
        link.symlink_to(target, target_is_directory=directory)
    except OSError as error:
        pytest.skip(f"symlinks are unavailable: {error}")


def test_external_resource_symlink_stays_lexical_and_uncertain(tmp_path):
    project = _write(tmp_path, {})
    outside = tmp_path / "outside.svg"
    outside.write_text("<svg/>\n", encoding="utf-8")
    link = project / "Main" / "Resources" / "linked.svg"
    link.parent.mkdir(parents=True, exist_ok=True)
    _symlink_or_skip(link, outside)

    def guarded_reader(path: Path) -> str:
        assert path != link
        return path.read_text(encoding="utf-8-sig")

    answer = resource_usage.analyze(project, reader=guarded_reader)

    assert answer["unused"] == []
    linked = _by_key(answer, "uncertain")["linked.svg"]
    assert linked["path"] == str(link)
    assert linked["evidence"][0]["kind"] == "external-symlink"


def test_internal_resource_symlink_keeps_alias_identity_and_relative_edges(tmp_path):
    project = _write(tmp_path, {
        "Main/Resources/source.css": "body{background:url(icon.svg)}\n",
        "Main/Resources/icon.svg": "<svg/>\n",
        **_module(
            "Caller",
            "method Probe(): Resource\n    return Resource{alias.css}\n;\n",
        ),
    })
    link = project / "Main" / "Resources" / "alias.css"
    _symlink_or_skip(link, link.parent / "source.css")

    answer = resource_usage.analyze(project)

    referenced = _by_key(answer, "referenced")
    assert {"alias.css", "icon.svg"} <= set(referenced)
    assert referenced["alias.css"]["path"] == str(link)
    assert "source.css" in _by_key(answer, "unused")


def test_external_resources_folder_symlink_does_not_read_outside_files(tmp_path):
    project = _write(tmp_path, {})
    outside = tmp_path / "outside-resources"
    outside.mkdir()
    (outside / "escape.svg").write_text("<svg/>\n", encoding="utf-8")
    link = project / "Main" / "Resources"
    _symlink_or_skip(link, outside, directory=True)

    def guarded_reader(path: Path) -> str:
        assert outside not in path.parents
        assert path != outside
        return path.read_text(encoding="utf-8-sig")

    answer = resource_usage.analyze(project, reader=guarded_reader)

    assert answer["unused"] == []
    assert all(Path(item["path"]).is_relative_to(project) for item in answer["uncertain"])


def test_generic_string_and_stem_mentions_are_uncertain_not_references(tmp_path):
    files = {
        "Main/Resources/icon.svg": "<svg/>\n",
        **_module(
            "Caller",
            "method Probe(): Array<String>\n    return [\"icon.svg\", \"icon\"]\n;\n",
        ),
    }
    answer = resource_usage.analyze(_write(tmp_path, files))
    item = _by_key(answer, "uncertain")["icon.svg"]

    assert {evidence["kind"] for evidence in item["evidence"]} == {"string", "stem"}
    assert answer["summary"]["referenced"] == 0


def test_compact_result_limits_lists_but_preserves_complete_totals(tmp_path):
    project = _write(tmp_path, {
        "Main/Resources/a.svg": "<svg/>\n",
        "Main/Resources/b.svg": "<svg/>\n",
        "Main/Resources/c.svg": "<svg/>\n",
    })
    answer = resource_usage.compact(resource_usage.analyze(project), limit=2)

    assert answer["summary"]["unused"] == 3
    assert len(answer["unused"]) == 2
    assert answer["hasMore"] is True
    assert "dynamic" not in answer and "uncertain" not in answer


def test_cli_unused_resources_is_read_only_and_compact(tmp_path, capsys):
    project = _write(tmp_path, {"Main/Resources/a.svg": "<svg/>\n"})

    code = cli.main(["unused-resources", str(project), "--limit", "1"])
    answer = json.loads(capsys.readouterr().out)

    assert code == 0
    assert answer["summary"]["unused"] == 1
    assert answer["unused"][0]["confidence"] == "candidate"
    assert (project / "Main" / "Resources" / "a.svg").is_file()


def test_mcp_unused_resources_limit_and_registration(mcp_module, tmp_path):
    project = _write(tmp_path, {
        "Main/Resources/a.svg": "<svg/>\n",
        "Main/Resources/b.svg": "<svg/>\n",
    })

    answer = mcp_module.meta_unused_resources(str(project), include_protected=True, limit=1)

    assert answer["summary"]["unused"] == 2
    assert len(answer["unused"]) == 1 and answer["hasMore"] is True
    assert "meta_unused_resources" in mcp_module.mcp.tools
