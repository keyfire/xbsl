"""GitLab Code Quality format (report.codeclimate + CLI --format codeclimate).

Does not depend on the Element data: the function itself works on ready-made Diagnostic
objects, and the CLI test relies on a tier-B rule (whitespace/trailing) that needs no data.
"""

import json
from pathlib import Path

import pytest

from xbsl import dataset, report
from xbsl.diagnostics import Diagnostic, Severity

REQUIRED_FIELDS = {"description", "check_name", "fingerprint", "severity", "location"}


def _d(path="X.xbsl", line=1, col=1, rule="whitespace/trailing",
       sev=Severity.WARNING, message="m"):
    return Diagnostic(path=path, line=line, col=col, rule_id=rule, severity=sev, message=message)


def test_issue_fields_and_severity_mapping(tmp_path):
    diags = [
        _d(line=3, rule="code/brackets", sev=Severity.ERROR, message="скобка"),
        _d(line=1, sev=Severity.WARNING, message="хвостовой пробел"),
        _d(line=7, rule="typography/em-dash", sev=Severity.INFO, message="тире"),
    ]
    issues = report.codeclimate(diags, base=tmp_path)

    assert len(issues) == 3
    for issue in issues:
        assert set(issue) == REQUIRED_FIELDS
        assert set(issue["location"]) == {"path", "lines"}
        assert issue["location"]["lines"]["begin"] >= 1

    by_rule = {i["check_name"]: i for i in issues}
    assert by_rule["code/brackets"]["severity"] == "major"
    assert by_rule["whitespace/trailing"]["severity"] == "minor"
    assert by_rule["typography/em-dash"]["severity"] == "info"
    assert by_rule["code/brackets"]["description"] == "скобка"
    assert by_rule["code/brackets"]["location"]["lines"]["begin"] == 3

    # Serializes to valid JSON without loss (including Cyrillic)
    assert json.loads(json.dumps(issues, ensure_ascii=False)) == issues


def test_paths_are_posix_relative(tmp_path):
    abs_path = str(tmp_path / "Подсистема" / "Форма.xbsl")
    issues = report.codeclimate([_d(path=abs_path)], base=tmp_path)

    path = issues[0]["location"]["path"]
    assert path == "Подсистема/Форма.xbsl"
    assert "\\" not in path
    assert not path.startswith("./")

    # A path outside the run root does not break the report - it stays whole, but in POSIX form
    outside = report.codeclimate([_d(path=abs_path)], base=tmp_path / "другой")
    assert "\\" not in outside[0]["location"]["path"]


def test_fingerprint_stable_and_unique():
    diags = [
        _d(line=1, message="а"),
        _d(line=2, message="а"),                       # different line
        _d(line=1, message="б"),                       # different message
        _d(line=1, rule="typography/em-dash", message="а"),  # different rule
        _d(path="Y.xbsl", line=1, message="а"),        # different file
    ]
    base = Path("К")

    first = [i["fingerprint"] for i in report.codeclimate(diags, base=base)]
    second = [i["fingerprint"] for i in report.codeclimate(list(diags), base=base)]

    assert first == second                 # stable across runs
    assert len(set(first)) == len(first)   # distinct for distinct findings
    assert all(len(f) == 32 for f in first)  # hex md5


def test_fingerprint_disambiguates_exact_duplicates():
    dup = _d(line=5, message="одно и то же")
    issues = report.codeclimate([dup, dup, dup], base=Path("К"))

    prints = [i["fingerprint"] for i in issues]
    assert len(set(prints)) == 3

    # The occurrence counter is deterministic: a repeat run yields the same prints in the same order
    again = [i["fingerprint"] for i in report.codeclimate([dup, dup, dup], base=Path("К"))]
    assert prints == again


def test_empty_report():
    assert report.codeclimate([]) == []


def test_cli_codeclimate_output(tmp_path, monkeypatch, capsys):
    from xbsl import cli

    # Tier-B rules need no data, but main() resolves the data version before the run
    if not dataset.available_versions():
        pytest.skip("нет данных Элемента – main() не пройдёт резолв версии")

    f = tmp_path / "Ч.xbsl"
    f.write_text("метод Ф()\n    возврат 1  \n;\n", encoding="utf-8")  # trailing whitespace
    monkeypatch.chdir(tmp_path)

    # A tier-B rule - no Element data needed; select only it
    code = cli.main(["--format", "codeclimate", "--select", "whitespace/trailing", "Ч.xbsl"])

    issues = json.loads(capsys.readouterr().out)
    assert code == 0  # warnings only
    assert isinstance(issues, list) and issues
    issue = next(i for i in issues if i["check_name"] == "whitespace/trailing")
    assert issue["severity"] == "minor"
    assert issue["location"]["path"] == "Ч.xbsl"
    assert issue["location"]["lines"]["begin"] == 2
