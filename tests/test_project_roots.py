"""Paths of several project roots are checked each on its own, never as one project.

Two worktrees of one project given in one call used to be loaded as ONE project: every name
came twice and gave a finding of its own (`yaml/id-unique` on each `Id`), and the baseline
found above the first file judged the files of the other worktree too, matching none of them.
The MCP `lint_paths` answered hundreds of thousands of characters under `compact` where each
tree alone had a handful of findings. Every root is now a part of its own
(cli.split_by_project), checked by its own baseline and CI job, and the answer counts the
findings of all the parts with a record per root in `summary.projects`.

The worktrees are two copies of the demo project of the repository. `yaml/id-unique` and
`whitespace/trailing` need no Element data, so the tests of the split and of the MCP tool run
in a public checkout; the CLI gates every run on the data and its tests carry `needs_data`.
"""

import importlib
import json
import shutil
import sys
import types
from pathlib import Path

import pytest

from xbsl import cli, engine

ROOT = Path(__file__).resolve().parents[1]
DEMO = ROOT / "demo" / "Acme" / "Tasks"
CARD = Path("Основное") / "КарточкаЗадачи.xbsl"
# Tier A and B: no data needed. The demo card has one trailing whitespace; the descriptor, the
# catalog and the form carry an `Id` each, the same in both copies.
RULES = ["yaml/id-unique", "whitespace/trailing"]


@pytest.fixture
def trees(tmp_path):
    """Two checkouts of one project: `wtA` and `wtB`, each with the demo project inside."""
    roots = []
    for name in ("wtA", "wtB"):
        root = tmp_path / name / "Acme" / "Tasks"
        shutil.copytree(DEMO, root)
        roots.append(root)
    return roots


def _accept_everything(root: Path) -> Path:
    """A baseline at the checkout of `root` that accepts every finding of its tree."""
    checkout = root.parents[1]
    target = checkout / ".xbsllint-baseline"
    (part,) = cli.split_by_project([str(root)])
    from xbsl import baseline

    baseline.write(target, engine.run(part.files, select=set(RULES)))
    return target


# --- the split -------------------------------------------------------------------------------


def test_two_worktrees_are_two_parts(trees):
    parts = cli.split_by_project([str(root) for root in trees])
    assert [part.root for part in parts] == [root.resolve() for root in trees]
    assert [part.asked for part in parts] == [[str(root)] for root in trees]
    assert all(part.requested is None and len(part.files) == 5 for part in parts)


def test_a_folder_above_the_worktrees_stands_for_each_root(trees, tmp_path):
    parts = cli.split_by_project([str(tmp_path)])
    assert [part.root for part in parts] == [root.resolve() for root in trees]
    assert [part.asked for part in parts] == [[str(root.resolve())] for root in trees]


def test_a_file_of_one_tree_takes_its_own_project_as_context(trees):
    first, second = trees
    card = first / CARD
    parts = cli.split_by_project([str(card), str(second)])
    assert [part.root for part in parts] == [first.resolve(), second.resolve()]
    assert parts[0].requested == [card]
    assert {f.name for f in parts[0].files} == {f.name for f in parts[1].files}
    assert all(f.resolve().is_relative_to(first.resolve()) for f in parts[0].files)
    assert parts[1].requested is None


def test_one_project_is_one_part_with_the_paths_as_given(trees):
    asked = [str(trees[0] / "Основное"), str(trees[0] / CARD)]
    (part,) = cli.split_by_project(asked)
    assert part.root == trees[0].resolve()
    assert part.asked == asked
    assert {f.name for f in part.requested} == {
        "КарточкаЗадачи.xbsl", "КарточкаЗадачи.yaml", "Задачи.yaml", "Подсистема.yaml",
    }
    assert trees[0].resolve() / "Проект.yaml" in part.files  # the rest of the project


def test_sources_outside_every_project_are_a_part_of_their_own(trees, tmp_path):
    loose = tmp_path / "Одинокий.xbsl"
    loose.write_text("метод Ф()\n;\n", encoding="utf-8")
    parts = cli.split_by_project([str(tmp_path)])
    assert [part.root for part in parts] == [*(root.resolve() for root in trees), None]
    # The folder holds the projects too: the part outside them answers for its own file,
    # and the reach of its baseline does not take the projects in.
    assert parts[-1].asked == [str(loose)]
    assert parts[-1].files == [loose]


def test_a_nested_project_is_not_the_context_of_the_outer_one(tmp_path):
    outer = tmp_path / "Внешний"
    (outer / "Основное").mkdir(parents=True)
    (outer / "Проект.yaml").write_text("Имя: Внешний\n", encoding="utf-8")
    (outer / "Основное" / "Первый.yaml").write_text("Имя: Первый\n", encoding="utf-8")
    inner = outer / "Вложенный"
    (inner / "Основное").mkdir(parents=True)
    (inner / "Проект.yaml").write_text("Имя: Вложенный\n", encoding="utf-8")
    (inner / "Основное" / "Второй.yaml").write_text("Имя: Второй\n", encoding="utf-8")

    (part,) = cli.split_by_project([str(outer / "Основное" / "Первый.yaml")])
    assert part.root == outer.resolve()
    assert {f.name for f in part.files} == {"Проект.yaml", "Первый.yaml"}
    parts = cli.split_by_project([str(outer)])
    assert {part.root: ({f.name for f in part.files}, part.asked) for part in parts} == {
        outer.resolve(): ({"Проект.yaml", "Первый.yaml"}, [str(outer)]),
        inner.resolve(): ({"Проект.yaml", "Второй.yaml"}, [str(inner.resolve())]),
    }


def test_the_parts_see_no_duplicates_where_one_project_did(trees):
    asked = [str(root) for root in trees]
    merged, _ = cli.discover_with_context(asked)
    assert len(engine.run(merged, select={"yaml/id-unique"})) == 6  # three `Id`, twice each
    for part in cli.split_by_project(asked):
        assert engine.run(part.files, select={"yaml/id-unique"}) == []


# --- the MCP tool ----------------------------------------------------------------------------


class _StubMCP:
    """The FastMCP stand-in of tests/test_mcp.py: tools register as plain functions."""

    def __init__(self, name, version=None):
        self.name = name

    def tool(self):
        return lambda fn: fn


@pytest.fixture
def server(monkeypatch):
    fast = types.ModuleType("mcp.server.fastmcp")
    fast.FastMCP = _StubMCP
    monkeypatch.setitem(sys.modules, "mcp", types.ModuleType("mcp"))
    monkeypatch.setitem(sys.modules, "mcp.server", types.ModuleType("mcp.server"))
    monkeypatch.setitem(sys.modules, "mcp.server.fastmcp", fast)
    sys.modules.pop("xbsl.mcp_server", None)
    yield importlib.import_module("xbsl.mcp_server")
    sys.modules.pop("xbsl.mcp_server", None)


def test_lint_paths_counts_each_worktree_on_its_own(server, trees):
    alone = [server.lint_paths([str(root)], select=RULES) for root in trees]
    both = server.lint_paths([str(root) for root in trees], select=RULES)

    assert both["diagnostics"] == alone[0]["diagnostics"] + alone[1]["diagnostics"]
    assert [d["rule"] for d in both["diagnostics"]] == ["whitespace/trailing"] * 2
    summary = both["summary"]
    assert (summary["files"], summary["diagnostics"]) == (10, 2)
    projects = summary["projects"]
    assert [entry["project"] for entry in projects] == [str(root.resolve()) for root in trees]
    for entry, single in zip(projects, alone):
        for key in ("files", "diagnostics", "errors", "warnings", "by_rule", "by_severity"):
            assert entry[key] == single["summary"][key]
        assert "by_file" not in entry
    assert "projects" not in alone[0]["summary"]


def test_each_worktree_is_judged_by_its_own_baseline(server, trees):
    files = [_accept_everything(root) for root in trees]

    answer = server.lint_paths([str(root) for root in trees], select=RULES)

    assert answer["diagnostics"] == []
    for entry, own in zip(answer["summary"]["projects"], files):
        assert entry["baseline"] == str(own)
        assert (entry["baselined"], entry["baseline_stale"]) == (1, 0)
        assert "baseline_not_checked" not in entry
    assert "baseline" not in answer["summary"]  # a record of a root, not of the call


def test_each_worktree_takes_the_ci_job_of_its_own_checkout(server, trees):
    for root in trees:
        _accept_everything(root)
        (root.parents[1] / ".gitlab-ci.yml").write_text(
            "xbsl-lint:\n  script:\n"
            "    - xbsl Acme/Tasks --select yaml/id-unique,whitespace/trailing "
            "--baseline .xbsllint-baseline\n",
            encoding="utf-8",
        )

    answer = server.lint_paths([str(root) for root in trees], as_ci=True, compact=True)

    # The job of the other checkout would lend its baseline, which matches none of the files.
    assert answer["summary"]["diagnostics"] == 0
    for entry in answer["summary"]["projects"]:
        assert entry["baselined"] == 1
        assert entry["as_ci"]["adopted"] is True
        assert set(entry["as_ci"]) == {"adopted", "brief"}  # one line under compact


def test_two_roots_sharing_a_baseline_leave_no_entry_unchecked(server, tmp_path):
    """Two projects of one checkout keep one baseline: each spends its own entries, and an
    entry of the other project is not "not checked" for the call."""
    roots = []
    for name in ("Первый", "Второй"):
        root = tmp_path / "Acme" / name
        shutil.copytree(DEMO, root)
        roots.append(root)
    from xbsl import baseline

    parts = cli.split_by_project([str(root) for root in roots])
    baseline.write(tmp_path / ".xbsllint-baseline",
                   [d for part in parts for d in engine.run(part.files, select=set(RULES))])

    answer = server.lint_paths([str(root) for root in roots], select=RULES)

    assert answer["diagnostics"] == []
    for entry in answer["summary"]["projects"]:
        assert entry["baselined"] == 1
        assert "baseline_not_checked" not in entry


def test_the_entries_of_a_nested_project_are_never_stale_for_the_outer_one(server, tmp_path):
    """A baseline written over both: the outer project takes the nested one in by its folder,
    yet never saw its findings. Stale there, the entries would go with the next pruning."""
    outer = tmp_path / "Acme" / "Tasks"
    shutil.copytree(DEMO, outer)
    inner = outer / "Вложенный" / "Acme" / "Tasks"
    shutil.copytree(DEMO, inner)
    from xbsl import baseline

    parts = cli.split_by_project([str(outer)])
    assert {part.root for part in parts} == {outer.resolve(), inner.resolve()}
    baseline.write(tmp_path / ".xbsllint-baseline",
                   [d for part in parts for d in engine.run(part.files, select=set(RULES))])

    answer = server.lint_paths([str(outer)], select=RULES)

    assert answer["diagnostics"] == []
    for entry in answer["summary"]["projects"]:
        assert (entry["baselined"], entry["baseline_stale"], entry["baseline_unused"]) == (
            1, 0, 0)


def test_fix_repairs_each_worktree_and_counts_it_apart(server, trees):
    answer = server.lint_paths([str(root) for root in trees], select=RULES, fix=True)

    assert answer["diagnostics"] == []
    assert (answer["summary"]["fixed"], answer["summary"]["files_changed"]) == (2, 2)
    assert [(entry["fixed"], entry["files_changed"]) for entry in answer["summary"]["projects"]
            ] == [(1, 1), (1, 1)]
    for root in trees:
        assert "  \n" not in (root / CARD).read_text(encoding="utf-8")


def test_a_comparison_of_two_worktrees_finds_nothing_doubled(server, trees, tmp_path):
    state = tmp_path / "запуск.json"
    asked = [str(root) for root in trees]
    server.lint_paths(asked, select=RULES, compare=str(state))
    card = trees[1] / CARD
    card.write_text(card.read_text(encoding="utf-8") + "// хвост  \n", encoding="utf-8")

    answer = server.lint_paths(asked, select=RULES, compare=str(state), compact=True)

    assert (answer["compare"]["appeared"], answer["compare"]["disappeared"]) == (1, 0)
    assert [entry["diagnostics"] for entry in answer["summary"]["projects"]] == [1, 2]


def test_baseline_prune_refuses_two_baselines_and_names_them(server, trees):
    files = [_accept_everything(root) for root in trees]

    answer = server.baseline_prune([str(root) for root in trees], select=RULES)

    assert "error" in answer
    assert all(str(own) in answer["error"] for own in files)
    named = server.baseline_prune([str(trees[0])], select=RULES, dry_run=True)
    assert (named["baseline"], named["stale"]) == (str(files[0]), 0)


def test_compact_holds_many_findings_under_the_limit(server, tmp_path):
    """Four hundred catalogs, two by two under one `Id`: four hundred errors, each a record."""
    from xbsl import report

    project = tmp_path / "Acme" / "Tasks"
    shutil.copytree(DEMO, project)
    for index in range(400):
        (project / "Основное" / f"Каталог{index}.yaml").write_text(
            f"ВидЭлемента: Справочник\nИд: 11111111-2222-3333-4444-{index // 2:012d}\n"
            f"Имя: Каталог{index}\n",
            encoding="utf-8",
        )

    full = server.lint_paths([str(project)], select=RULES)
    answer = server.lint_paths([str(project)], select=RULES, compact=True)

    assert len(json.dumps(full, ensure_ascii=False)) > 10 * report.COMPACT_ANSWER_LIMIT
    assert len(json.dumps(answer, ensure_ascii=False)) <= report.COMPACT_ANSWER_LIMIT
    assert answer["summary"]["errors"] == full["summary"]["errors"] == 400
    cut = answer["truncated"]["errors"]
    assert cut["total"] == 400 and 0 < cut["shown"] == len(answer["errors"]) < 400
    assert answer["errors"] == [d for d in full["diagnostics"] if d["severity"] == "error"][
        :cut["shown"]]
    assert "compact" in answer["truncated_hint"] and "--out" in answer["truncated_hint"]


# --- the CLI ---------------------------------------------------------------------------------


@pytest.mark.needs_data
def test_cli_json_counts_each_worktree_on_its_own(trees, tmp_path):
    out = tmp_path / "report.json"
    code = cli.main([*(str(root) for root in trees), "--select", ",".join(RULES),
                     "--format", "json", "--out", str(out)])
    payload = json.loads(out.read_text(encoding="utf-8"))
    assert code == 0
    assert [d["rule"] for d in payload["diagnostics"]] == ["whitespace/trailing"] * 2
    projects = payload["summary"]["projects"]
    assert [entry["project"] for entry in projects] == [str(root.resolve()) for root in trees]
    assert [(entry["files"], entry["diagnostics"]) for entry in projects] == [(5, 1), (5, 1)]


@pytest.mark.needs_data
def test_cli_judges_each_worktree_by_its_own_baseline(trees, capsys):
    files = [_accept_everything(root) for root in trees]

    code = cli.main([*(str(root) for root in trees), "--select", ",".join(RULES)])

    err = capsys.readouterr().err
    assert code == 0
    assert all(str(own) in err for own in files)  # each found, each named
    assert "Проектов: 2, каждый проверен отдельно:" in err
    lines = [line for line in err.splitlines() if line.startswith("  ")]
    assert len(lines) == 2
    assert all("замечаний: 0" in line and "погашено списком принятых" in line for line in lines)


@pytest.mark.needs_data
def test_cli_baseline_add_refuses_two_baselines(trees, capsys):
    for root in trees:
        _accept_everything(root)
    code = cli.main(["baseline", "add", *(str(root) for root in trees),
                     "--rule", "whitespace/trailing"])
    assert code == 2
    assert "разными списками принятых замечаний" in capsys.readouterr().err


@pytest.mark.needs_data
def test_cli_as_ci_takes_the_job_of_each_checkout(trees, tmp_path):
    for root in trees:
        _accept_everything(root)
        (root.parents[1] / ".gitlab-ci.yml").write_text(
            "xbsl-lint:\n  script:\n"
            "    - xbsl Acme/Tasks --select yaml/id-unique,whitespace/trailing "
            "--baseline .xbsllint-baseline\n",
            encoding="utf-8",
        )
    out = tmp_path / "report.json"

    code = cli.main([*(str(root) for root in trees), "--as-ci", "--format", "json",
                     "--out", str(out)])

    payload = json.loads(out.read_text(encoding="utf-8"))
    assert code == 0 and payload["diagnostics"] == []
    for entry, root in zip(payload["summary"]["projects"], trees):
        assert entry["as_ci"]["file"] == str(root.parents[1] / ".gitlab-ci.yml")
        assert entry["baselined"] == 1
