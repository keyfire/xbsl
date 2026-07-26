"""Single-file runs pick up the project context (discover_with_context).

A file (or a subfolder) passed to the CLI or to the MCP lint_paths lives inside a project whose
other objects the project-scope rules need: without them yaml/unknown-type reported false
unknowns on the project's own types, and cross-file rules like yaml/id-unique could not see a
duplicate at all. The context is found by walking up to the folder holding Проект.yaml; the
diagnostics are then narrowed back to what was explicitly requested.

The module needs no Element data (yaml/id-unique is a tier-A rule); the original unknown-type
pain is closed by the same mechanism and needs no data-bound test here. The one exception is
the end-to-end CLI test: cli.main gates every run on a resolvable data version, so that single
test carries `needs_data` and skips in a public checkout.
"""

import json

import pytest

from xbsl import cli, engine

_PROJECT = "Ид: ffeacdec-02d6-4f08-bcfa-be89e9a1861a\nИмя: Проба\n"
_DUP_ID = "11111111-2222-3333-4444-555555555555"


def _object(name, ident=_DUP_ID):
    return f"ВидЭлемента: Справочник\nИд: {ident}\nИмя: {name}\n"


@pytest.fixture
def project(tmp_path):
    """A tiny project: Проект.yaml at the root, two catalogs with a DUPLICATED Ид inside
    a subsystem folder."""
    (tmp_path / "Проект.yaml").write_text(_PROJECT, encoding="utf-8")
    sub = tmp_path / "Основное"
    sub.mkdir()
    (sub / "Первый.yaml").write_text(_object("Первый"), encoding="utf-8")
    (sub / "Второй.yaml").write_text(_object("Второй"), encoding="utf-8")
    return tmp_path


def test_single_file_pulls_the_whole_project(project):
    one = project / "Основное" / "Первый.yaml"
    files, requested = cli.discover_with_context([str(one)])
    assert requested == [one]
    names = {f.name for f in files}
    assert names == {"Проект.yaml", "Первый.yaml", "Второй.yaml"}


def test_project_root_needs_no_filter(project):
    files, requested = cli.discover_with_context([str(project)])
    assert requested is None
    assert {f.name for f in files} == {"Проект.yaml", "Первый.yaml", "Второй.yaml"}


def test_subfolder_pulls_the_rest_of_the_project(project):
    files, requested = cli.discover_with_context([str(project / "Основное")])
    assert requested is not None
    assert {f.name for f in requested} == {"Первый.yaml", "Второй.yaml"}
    assert {f.name for f in files} == {"Проект.yaml", "Первый.yaml", "Второй.yaml"}


def test_file_outside_a_project_stays_alone(tmp_path):
    lone = tmp_path / "Одинокий.yaml"
    lone.write_text(_object("Одинокий"), encoding="utf-8")
    files, requested = cli.discover_with_context([str(lone)])
    assert requested is None
    assert files == [lone]


def test_filter_keeps_only_requested_files(project):
    one = project / "Основное" / "Первый.yaml"
    files, requested = cli.discover_with_context([str(one)])
    diags = engine.run(files, select={"yaml/id-unique"})
    # The duplicate is visible in both files of the full run...
    assert {d.path for d in diags} == {str(f) for f in files if f.name != "Проект.yaml"}
    # ...and the filter narrows it down to the requested one.
    narrowed = cli._filter_requested(diags, requested)
    assert narrowed and all(d.path == str(one) for d in narrowed)


@pytest.mark.needs_data
def test_cli_single_file_sees_the_duplicate(project, capsys):
    # The original pain: linting one file used to run project rules over that file alone,
    # so a duplicated Ид (or an unknown project type) never surfaced.
    one = project / "Основное" / "Первый.yaml"
    cli.main(["--format", "json", "--select", "yaml/id-unique", str(one)])
    payload = json.loads(capsys.readouterr().out)
    assert [d["rule"] for d in payload["diagnostics"]] == ["yaml/id-unique"]
    assert all(d["path"] == str(one) for d in payload["diagnostics"])
    # The summary speaks of the requested file, not of the loaded context.
    assert payload["summary"]["files"] == 1
