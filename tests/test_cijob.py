"""The rule set of a project's CI job, and running locally with it (`--as-ci`, `as_ci`).

The pain this answers: a project turns rules on in its pipeline with `--enable`, a local run
knows nothing about them, and the difference shows up as a red job one push later.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from xbsl import cijob, cli

GITLAB = """\
stages:
  - lint

xbsl-lint:
  stage: lint
  image: python:3.12
  before_script:
    - pip install --quiet xbsl
  script:
    - >
      xbsl e1c --baseline .xbsllint-baseline --jobs 1
      --enable code/unused-method
      --enable conventions/missing-translation
      --enable yaml/duplicate-subtree
    - python tools/check-agent-docs.py

build:
  stage: build
  script:
    - elemctl build
"""


def _write(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def test_the_flags_of_the_job_are_read_from_the_pipeline_file(tmp_path: Path):
    """Everything that shapes the verdict - and nothing about transport."""
    ci = cijob.read(_write(tmp_path / ".gitlab-ci.yml", GITLAB))
    assert ci.job == "xbsl-lint"
    assert ci.enable == (
        "code/unused-method", "conventions/missing-translation", "yaml/duplicate-subtree",
    )
    assert ci.select == () and ci.ignore == () and ci.no_baseline is False
    assert ci.baseline == ".xbsllint-baseline"
    assert ci.paths == ("e1c",)  # reported, never imposed


def test_the_baseline_is_resolved_against_the_pipeline_file(tmp_path: Path):
    """The job names it relative to the checkout root - a run from elsewhere must still open it."""
    ci = cijob.read(_write(tmp_path / ".gitlab-ci.yml", GITLAB))
    assert ci.baseline_file() == str(tmp_path / ".xbsllint-baseline")


def test_the_line_a_run_prints_names_the_file_the_job_and_the_flags(tmp_path: Path):
    ci = cijob.read(_write(tmp_path / ".gitlab-ci.yml", GITLAB))
    line = ci.describe()
    assert "xbsl-lint" in line and str(ci.path) in line
    assert "--enable code/unused-method" in line and "--baseline .xbsllint-baseline" in line


def test_both_spellings_of_a_flag_and_a_comma_list_are_read(tmp_path: Path):
    text = (
        "lint:\n"
        "  script:\n"
        "    - xbsl . --enable=a/one --select b/two,c/three --ignore d/four --no-baseline\n"
    )
    ci = cijob.read(_write(tmp_path / ".gitlab-ci.yml", text))
    assert ci.enable == ("a/one",)
    assert ci.select == ("b/two", "c/three")
    assert ci.ignore == ("d/four",)
    assert ci.no_baseline is True and ci.baseline is None


def test_a_subcommand_is_not_the_check_run(tmp_path: Path):
    """`xbsl translate` runs no rules - taking its flags would describe another job entirely."""
    text = (
        "translate:\n"
        "  script:\n"
        "    - xbsl translate e1c --out build --enable nonsense/rule\n"
        "    - python -m xbsl e1c --enable code/unused-method\n"
    )
    ci = cijob.read(_write(tmp_path / ".gitlab-ci.yml", text))
    assert ci.enable == ("code/unused-method",)


def test_commands_chained_in_one_line_are_split(tmp_path: Path):
    text = (
        "lint:\n"
        "  script:\n"
        "    - pip install xbsl && xbsl e1c --enable code/unused-method\n"
    )
    assert cijob.read(_write(tmp_path / ".gitlab-ci.yml", text)).enable == ("code/unused-method",)


def test_a_github_workflow_is_read_by_the_same_code(tmp_path: Path):
    text = (
        "name: CI\n"
        "on: [push]\n"
        "jobs:\n"
        "  lint:\n"
        "    runs-on: ubuntu-latest\n"
        "    steps:\n"
        "      - uses: actions/checkout@v4\n"
        "      - run: pip install xbsl\n"
        "      - run: xbsl src --enable yaml/duplicate-subtree\n"
    )
    ci = cijob.read(_write(tmp_path / ".github" / "workflows" / "ci.yml", text))
    assert ci.job == "lint" and ci.enable == ("yaml/duplicate-subtree",)


def test_a_pipeline_tag_does_not_cost_the_rule_set(tmp_path: Path):
    """GitLab's own `!reference` is not a reason to fall back to a narrower set."""
    text = (
        "lint:\n"
        "  before_script: !reference [.setup, script]\n"
        "  script:\n"
        "    - xbsl . --enable code/unused-method\n"
    )
    assert cijob.read(_write(tmp_path / ".gitlab-ci.yml", text)).enable == ("code/unused-method",)


def test_the_pipeline_file_is_found_above_the_checked_path(tmp_path: Path):
    _write(tmp_path / ".gitlab-ci.yml", GITLAB)
    deep = tmp_path / "e1c" / "site" / "Проект"
    deep.mkdir(parents=True)
    assert cijob.discover(deep) == tmp_path / ".gitlab-ci.yml"
    assert cijob.find([str(deep)]).job == "xbsl-lint"


def test_a_project_without_a_pipeline_says_so(tmp_path: Path):
    with pytest.raises(cijob.CiLintError) as exc:
        cijob.find([str(tmp_path)])
    assert ".gitlab-ci.yml" in str(exc.value)


def test_a_pipeline_that_runs_no_linter_says_so(tmp_path: Path):
    path = _write(tmp_path / ".gitlab-ci.yml", "build:\n  script:\n    - elemctl build\n")
    with pytest.raises(cijob.CiLintError) as exc:
        cijob.read(path)
    assert str(path) in str(exc.value)


# --- the run itself: what the project checks and what a local pass used to miss ------------------

_FORM = """\
ВидЭлемента: КомпонентИнтерфейса
Ид: 11111111-2222-3333-4444-55555555555{n}
Имя: {name}
Наследует:
    Тип: Группа
    Содержимое:
{rows}"""


def _rows(count: int = 15) -> str:
    return "".join(
        "        - Тип: Поле\n"
        f"          Имя: Поле{index}\n"
        f"          Заголовок: Подпись{index}\n"
        f"          Ширина: {10 + index}\n"
        for index in range(count)
    )


def _project_with_a_copied_subtree(tmp_path: Path) -> Path:
    """Two forms carrying the same subtree - a finding of a rule that is OFF by default."""
    root = tmp_path / "project"
    for index, name in enumerate(("ФормаОдин", "ФормаДва")):
        _write(root / f"{name}.yaml", _FORM.format(n=index, name=name, rows=_rows()))
    _write(tmp_path / ".gitlab-ci.yml",
           "xbsl-lint:\n  script:\n    - xbsl project --enable yaml/duplicate-subtree\n")
    return root


@pytest.mark.needs_data
def test_as_ci_finds_what_a_plain_local_run_calls_clean(tmp_path: Path, capsys):
    """The whole point: the same tree, the same engine, two verdicts - now one."""
    root = _project_with_a_copied_subtree(tmp_path)

    assert cli.main([str(root), "--no-baseline"]) == 0
    assert "yaml/duplicate-subtree" not in capsys.readouterr().out

    assert cli.main([str(root), "--no-baseline", "--as-ci"]) == 0
    captured = capsys.readouterr()
    assert "yaml/duplicate-subtree" in captured.out
    assert "xbsl-lint" in captured.err and ".gitlab-ci.yml" in captured.err


@pytest.mark.needs_data
def test_as_ci_adds_to_what_the_caller_asked_for(tmp_path: Path, capsys):
    """`--as-ci --enable X` is the job's set PLUS X - how a rule is tried before the pipeline."""
    root = _project_with_a_copied_subtree(tmp_path)
    assert cli.main([str(root), "--no-baseline", "--as-ci", "--enable", "typography/yo-in-text"]) == 0
    assert "yaml/duplicate-subtree" in capsys.readouterr().out


@pytest.mark.needs_data
def test_as_ci_without_a_pipeline_file_refuses_instead_of_checking_a_narrower_set(
    tmp_path: Path, capsys,
):
    """Silently running a different set is exactly the failure this flag exists to prevent."""
    root = tmp_path / "project"
    _write(root / "ФормаОдин.yaml", _FORM.format(n=0, name="ФормаОдин", rows=_rows(3)))
    assert cli.main([str(root), "--as-ci"]) == 2
    assert ".gitlab-ci.yml" in capsys.readouterr().err


@pytest.mark.needs_data
def test_the_named_file_wins_over_discovery(tmp_path: Path, capsys):
    root = _project_with_a_copied_subtree(tmp_path)
    other = _write(tmp_path / "other-ci.yml",
                   "другая:\n  script:\n    - xbsl project\n")
    assert cli.main([str(root), "--no-baseline", "--as-ci", str(other)]) == 0
    out = capsys.readouterr()
    assert "yaml/duplicate-subtree" not in out.out  # that job enables nothing
    assert "другая" in out.err
