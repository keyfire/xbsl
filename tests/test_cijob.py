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
    - python tools/check-docs.py

build:
  stage: build
  script:
    - elemctl build
"""

# A pipeline of a project that builds a SECOND tree: the sources in one job, what `translate`
# wrote in another - and the second one judges a different set (no baseline of its own, a rule
# switched off). Taking the first command describes the wrong tree.
BILINGUAL = """xbsl-lint:
  script:
    - xbsl e1c --baseline .xbsllint-baseline --enable code/unused-method

English to S3:
  script:
    - xbsl translate e1c --out build/en --strict
    - xbsl build/en --no-baseline --ignore code/undefined-name
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


# --- which job, when the file runs the linter more than once ------------------------------------


def test_without_a_name_the_first_job_wins_and_the_other_is_named(tmp_path: Path):
    """The old behaviour stands - but the run stops pretending there was only one job."""
    ci = cijob.read(_write(tmp_path / ".gitlab-ci.yml", BILINGUAL))
    assert ci.job == "xbsl-lint" and ci.enable == ("code/unused-method",)
    assert ci.alternatives == ("English to S3",)
    assert "English to S3" in ci.hint() and "--as-ci-job" in ci.hint()


def test_the_named_job_is_the_one_read(tmp_path: Path):
    """Its literal command: no baseline, one rule off - nothing of the first job's set."""
    ci = cijob.read(_write(tmp_path / ".gitlab-ci.yml", BILINGUAL), "English to S3")
    assert ci.job == "English to S3"
    assert ci.ignore == ("code/undefined-name",) and ci.no_baseline is True
    assert ci.enable == () and ci.baseline is None
    assert ci.paths == ("build/en",)  # the translated tree, not the sources
    assert ci.alternatives == ("xbsl-lint",)


def test_a_part_of_the_name_is_enough_while_it_fits_one_job(tmp_path: Path):
    """A job name with spaces is tedious to quote; a half that fits two is refused, not guessed."""
    path = _write(tmp_path / ".gitlab-ci.yml", BILINGUAL)
    assert cijob.read(path, "english").job == "English to S3"
    assert cijob.read(path, "ENGLISH TO S3").job == "English to S3"
    with pytest.raises(cijob.CiLintError) as exc:
        cijob.read(path, "s")  # both "xbsl-lint" and "English to S3" carry it
    assert "xbsl-lint" in str(exc.value) and "English to S3" in str(exc.value)


def test_a_job_the_file_does_not_have_names_the_ones_it_does(tmp_path: Path):
    with pytest.raises(cijob.CiLintError) as exc:
        cijob.read(_write(tmp_path / ".gitlab-ci.yml", BILINGUAL), "нет-такой")
    assert "xbsl-lint" in str(exc.value) and "English to S3" in str(exc.value)


def test_a_single_job_file_offers_no_alternatives(tmp_path: Path):
    """Nothing to choose from - and nothing said about choosing."""
    ci = cijob.read(_write(tmp_path / ".gitlab-ci.yml", GITLAB))
    assert ci.alternatives == () and ci.hint() == ""


def test_a_pipeline_that_runs_no_linter_says_so(tmp_path: Path):
    path = _write(tmp_path / ".gitlab-ci.yml", "build:\n  script:\n    - elemctl build\n")
    with pytest.raises(cijob.CiLintError) as exc:
        cijob.read(path)
    assert str(path) in str(exc.value)


def test_a_directory_named_as_the_pipeline_file_is_told_what_the_flag_takes(tmp_path: Path):
    """`--as-ci` takes an OPTIONAL file name, so the tree meant for checking lands in it."""
    (tmp_path / "e1c").mkdir()

    with pytest.raises(cijob.CiLintError) as exc:
        cijob.read(tmp_path / "e1c")

    said = str(exc.value)
    assert "--as-ci" in said and str(tmp_path / "e1c") in said
    assert "Is a directory" not in said and "каталог" in said  # not the file system's word


# --- include: the pipeline is rarely one file ----------------------------------------------------


def test_a_job_declared_in_an_included_file_is_found(tmp_path: Path):
    """The shape a project on a shared template has: the root file only includes."""
    _write(tmp_path / ".gitlab-ci.yml", "include:\n  - local: /ci/lint.yml\nstages:\n  - lint\n")
    _write(tmp_path / "ci" / "lint.yml",
           "xbsl-lint:\n  script:\n    - xbsl e1c --enable code/unused-method\n")

    ci = cijob.read(tmp_path / ".gitlab-ci.yml")

    assert ci.job == "xbsl-lint" and ci.enable == ("code/unused-method",)
    assert ci.source == tmp_path / "ci" / "lint.yml"
    assert str(ci.source) in ci.describe()  # the file to open is not the one that was read


def test_the_baseline_of_an_included_job_is_resolved_against_the_checkout(tmp_path: Path):
    """The job runs in the checkout of the ROOT file - its baseline lies there, not in ci/."""
    _write(tmp_path / ".gitlab-ci.yml", "include: ci/lint.yml\n")
    _write(tmp_path / "ci" / "lint.yml",
           "lint:\n  script:\n    - xbsl e1c --baseline .xbsllint-baseline\n")

    assert cijob.read(tmp_path / ".gitlab-ci.yml").baseline_file() == \
        str(tmp_path / ".xbsllint-baseline")


def test_a_nested_include_is_resolved_against_the_same_root(tmp_path: Path):
    """GitLab resolves every local include against the repository root, however deep."""
    _write(tmp_path / ".gitlab-ci.yml", "include:\n  - local: /ci/base.yml\n")
    _write(tmp_path / "ci" / "base.yml", "include:\n  - local: /ci/jobs/lint.yml\n")
    _write(tmp_path / "ci" / "jobs" / "lint.yml",
           "lint:\n  script:\n    - xbsl e1c --enable yaml/duplicate-subtree\n")

    assert cijob.read(tmp_path / ".gitlab-ci.yml").enable == ("yaml/duplicate-subtree",)


def test_a_pattern_include_takes_every_file_it_matches(tmp_path: Path):
    """`ci/*.yml` is how a project that keeps a job per file writes it."""
    _write(tmp_path / ".gitlab-ci.yml", "include:\n  - local: ci/*.yml\n")
    _write(tmp_path / "ci" / "build.yml", "build:\n  script:\n    - elemctl build\n")
    _write(tmp_path / "ci" / "lint.yml", "lint:\n  script:\n    - xbsl e1c --select code\n")

    ci = cijob.read(tmp_path / ".gitlab-ci.yml")

    assert ci.job == "lint" and ci.select == ("code",)


def test_the_root_file_wins_over_what_it_includes(tmp_path: Path):
    """GitLab's own precedence, and the first command is what an unnamed run takes."""
    _write(tmp_path / ".gitlab-ci.yml",
           "include:\n  - local: /ci/lint.yml\nlint:\n  script:\n    - xbsl e1c --select a/own\n")
    _write(tmp_path / "ci" / "lint.yml",
           "lint:\n  script:\n    - xbsl e1c --select b/template\n")

    ci = cijob.read(tmp_path / ".gitlab-ci.yml")

    assert ci.select == ("a/own",) and ci.source is None


def test_a_job_of_an_included_file_can_be_named(tmp_path: Path):
    """Everything the reader learned is one list: --as-ci-job does not care where a job lay."""
    _write(tmp_path / ".gitlab-ci.yml",
           "include: ci/english.yml\nxbsl-lint:\n  script:\n    - xbsl e1c\n")
    _write(tmp_path / "ci" / "english.yml",
           "English to S3:\n  script:\n    - xbsl build/en --no-baseline\n")

    ci = cijob.read(tmp_path / ".gitlab-ci.yml", "english")

    assert ci.job == "English to S3" and ci.no_baseline is True
    assert ci.alternatives == ("xbsl-lint",)


def test_an_include_that_needs_the_network_is_named_not_fetched(tmp_path: Path):
    """A linter that downloads a URL out of a config file is a surprise, not a feature."""
    _write(tmp_path / ".gitlab-ci.yml",
           "include:\n"
           "  - remote: https://example.test/ci.yml\n"
           "  - template: Jobs/SAST.gitlab-ci.yml\n"
           "  - project: group/templates\n"
           "    ref: main\n"
           "    file: /lint.yml\n"
           "  - local: /ci/lint.yml\n")
    _write(tmp_path / "ci" / "lint.yml", "lint:\n  script:\n    - xbsl e1c\n")

    ci = cijob.read(tmp_path / ".gitlab-ci.yml")

    assert ci.job == "lint"
    assert ci.unread == (
        "remote: https://example.test/ci.yml",
        "template: Jobs/SAST.gitlab-ci.yml",
        "project: group/templates@main /lint.yml",
    )
    assert "https://example.test/ci.yml" in ci.note()


def test_a_pipeline_whose_jobs_all_live_elsewhere_says_what_it_could_not_read(tmp_path: Path):
    """The refusal used to blame the file; the reason is that nobody fetched the template."""
    path = _write(tmp_path / ".gitlab-ci.yml",
                  "include:\n  - template: Jobs/Lint.gitlab-ci.yml\nstages:\n  - lint\n")

    with pytest.raises(cijob.CiLintError) as exc:
        cijob.read(path)

    assert "Jobs/Lint.gitlab-ci.yml" in str(exc.value)


def test_a_local_include_the_checkout_does_not_have_is_named_too(tmp_path: Path):
    """The likeliest reason a job cannot be found - and not a reason to lose the rest."""
    _write(tmp_path / ".gitlab-ci.yml",
           "include:\n  - local: /ci/missing.yml\nlint:\n  script:\n    - xbsl e1c\n")

    ci = cijob.read(tmp_path / ".gitlab-ci.yml")

    assert ci.job == "lint"
    assert len(ci.unread) == 1 and "missing.yml" in ci.unread[0]


def test_an_include_loop_does_not_hang_the_reader(tmp_path: Path):
    """Two templates including each other is a mistake to survive, not to spin on."""
    _write(tmp_path / ".gitlab-ci.yml", "include: ci/one.yml\n")
    _write(tmp_path / "ci" / "one.yml",
           "include: ci/two.yml\nlint:\n  script:\n    - xbsl e1c\n")
    _write(tmp_path / "ci" / "two.yml", "include: ci/one.yml\n")

    assert cijob.read(tmp_path / ".gitlab-ci.yml").job == "lint"


def test_a_file_without_includes_carries_nothing_new(tmp_path: Path):
    """The plain case stays plain: no source, no unread line, no extra noise."""
    ci = cijob.read(_write(tmp_path / ".gitlab-ci.yml", GITLAB))

    assert ci.source is None and ci.unread == () and ci.note() == ""


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
def test_as_ci_job_picks_the_second_job_and_implies_as_ci(tmp_path: Path, capsys):
    """`--as-ci-job` alone is enough: naming a job is asking for the job's set."""
    root = _project_with_a_copied_subtree(tmp_path)
    _write(tmp_path / ".gitlab-ci.yml",
           "xbsl-lint:\n  script:\n    - xbsl project\n"
           "English to S3:\n  script:\n    - xbsl project --enable yaml/duplicate-subtree\n")

    assert cli.main([str(root), "--no-baseline", "--as-ci"]) == 0
    first = capsys.readouterr()
    assert "yaml/duplicate-subtree" not in first.out  # the first job enables nothing
    assert "--as-ci-job" in first.err  # ...but the run says the choice existed

    assert cli.main([str(root), "--no-baseline", "--as-ci-job", "english"]) == 0
    second = capsys.readouterr()
    assert "yaml/duplicate-subtree" in second.out
    assert "English to S3" in second.err


@pytest.mark.needs_data
def test_a_run_takes_the_set_of_a_job_that_lives_in_an_included_file(tmp_path: Path, capsys):
    """End to end: the root file only includes, and the local pass still judges as the job."""
    root = _project_with_a_copied_subtree(tmp_path)
    _write(tmp_path / ".gitlab-ci.yml",
           "include:\n  - local: /ci/lint.yml\n  - template: Jobs/SAST.gitlab-ci.yml\n")
    _write(tmp_path / "ci" / "lint.yml",
           "xbsl-lint:\n  script:\n    - xbsl project --enable yaml/duplicate-subtree\n")

    assert cli.main([str(root), "--no-baseline", "--as-ci"]) == 0

    out = capsys.readouterr()
    assert "yaml/duplicate-subtree" in out.out
    assert "ci" in out.err and "lint.yml" in out.err  # the file the job actually stands in
    assert "Jobs/SAST.gitlab-ci.yml" in out.err  # ...and the blind spot of the reader


@pytest.mark.needs_data
def test_the_flag_that_ate_the_path_answers_with_the_form_that_works(tmp_path: Path, capsys):
    """`xbsl --as-ci e1c` - the shape the flag invites, and the message it used to give."""
    root = _project_with_a_copied_subtree(tmp_path)

    assert cli.main(["--as-ci", str(root)]) == 2

    said = capsys.readouterr().err
    assert f"xbsl {root} --as-ci" in said  # the command to run instead, spelled out


@pytest.mark.needs_data
def test_a_job_that_is_not_in_the_file_refuses_by_name(tmp_path: Path, capsys):
    root = _project_with_a_copied_subtree(tmp_path)
    assert cli.main([str(root), "--as-ci-job", "no-such-job"]) == 2
    assert "no-such-job" in capsys.readouterr().err


@pytest.mark.needs_data
def test_the_named_file_wins_over_discovery(tmp_path: Path, capsys):
    root = _project_with_a_copied_subtree(tmp_path)
    other = _write(tmp_path / "other-ci.yml",
                   "другая:\n  script:\n    - xbsl project\n")
    assert cli.main([str(root), "--no-baseline", "--as-ci", str(other)]) == 0
    out = capsys.readouterr()
    assert "yaml/duplicate-subtree" not in out.out  # that job enables nothing
    assert "другая" in out.err
