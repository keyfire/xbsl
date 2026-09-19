"""An entry whose text the rule reworded: the finding it froze stays frozen.

A baseline keys an entry on the text of the finding, and that text belongs to the rule. When a
release rewords a message, an entry frozen under the old wording stops matching: the finding
comes back as new, the reason written beside it goes unread, and the entry is called stale.

So an entry also holds a finding of the same rule in the same file when two things are true:
the text of the entry fits no current wording of the rule, and it carries the values the
finding names, each in its quotes, in the same order. A rewrite of the baseline carries the
reason over to the new text. A message without values is never matched this way - nothing
would tell two such findings apart.
"""

from __future__ import annotations

import json

import pytest

from xbsl import baseline, cli, i18n
from xbsl.diagnostics import Diagnostic, Severity

_RULE = "test/reworded"
_FILE = "Задачи.yaml"

i18n.register({
    f"{_RULE}.call": {
        "ru": "Свойство '{prop}' вызывает '{call}'. Текст правила сейчас такой.",
        "en": "Property '{prop}' calls '{call}'. This is the text of the rule now.",
    },
    f"{_RULE}.chain": {
        "ru": "Свойство '{prop}' вызывает '{call}', который доходит до '{endpoint}'.",
        "en": "Property '{prop}' calls '{call}', which reaches '{endpoint}'.",
    },
    f"{_RULE}.plain": {
        "ru": "Текст правила без значений сейчас такой.",
        "en": "This is the text of the rule without values now.",
    },
})

#: The wording of an earlier release: the same values in the same quotes, another sentence.
_OLD = "Свойство 'Картинка' вызывает 'Ресурсы.Путь' - так правило писало раньше."


def _now(key: str, **fields) -> str:
    return i18n.t(f"{_RULE}.{key}", **fields)


def _payload(message: str, count: int = 1, reason: str = "") -> dict:
    value: object = {"count": count, "reason": reason} if reason else count
    return {"meta": {"tool": "xbsl", "format": 1},
            "files": {_FILE: {_RULE: {message: value}}}}


def _finding(base_dir, message: str, line: int = 1) -> Diagnostic:
    return Diagnostic(str(base_dir / _FILE), line, 1, _RULE, Severity.WARNING, message)


def test_an_entry_the_rule_reworded_keeps_its_finding(tmp_path):
    reworded: list[dict] = []
    finding = _finding(tmp_path, _now("call", prop="Картинка", call="Ресурсы.Путь"))

    result = baseline.apply([finding], _payload(_OLD, reason="решение проекта"), tmp_path,
                            reworded=reworded)

    assert result == ([], 1, 0, [])
    assert reworded == [{"path": _FILE, "rule": _RULE, "message": _OLD, "count": 1,
                         "reason": "решение проекта"}]


@pytest.mark.parametrize("prop, call", [("Фон", "Ресурсы.Путь"), ("Ресурсы.Путь", "Картинка")])
def test_a_reworded_entry_leaves_a_finding_with_other_values(tmp_path, prop, call):
    finding = _finding(tmp_path, _now("call", prop=prop, call=call))

    kept, suppressed, _unused, stale = baseline.apply([finding], _payload(_OLD), tmp_path)

    assert kept == [finding] and suppressed == 0
    assert [entry["message"] for entry in stale] == [_OLD]


def test_an_entry_in_a_current_wording_holds_only_its_own_text(tmp_path):
    """The chain finding is gone and a direct one took its place: its values stand in the old
    entry in the same order, and still it is another finding."""
    entry = _now("chain", prop="Картинка", call="Ресурсы.Путь", endpoint="Сервер.Файл")
    finding = _finding(tmp_path, _now("call", prop="Картинка", call="Ресурсы.Путь"))

    kept, suppressed, _unused, stale = baseline.apply([finding], _payload(entry), tmp_path)

    assert kept == [finding] and suppressed == 0
    assert [row["message"] for row in stale] == [entry]


def test_a_message_without_values_is_matched_only_by_its_text(tmp_path):
    finding = _finding(tmp_path, _now("plain"))

    kept, suppressed, _unused, stale = baseline.apply(
        [finding], _payload("Текст правила без значений был другим."), tmp_path)

    assert kept == [finding] and suppressed == 0 and len(stale) == 1


def test_a_reworded_entry_holds_as_many_findings_as_its_count(tmp_path):
    message = _now("call", prop="Картинка", call="Ресурсы.Путь")
    first, second = _finding(tmp_path, message, line=1), _finding(tmp_path, message, line=5)

    kept, suppressed, unused, stale = baseline.apply([first, second], _payload(_OLD), tmp_path)

    assert kept == [second] and (suppressed, unused, stale) == (1, 0, [])


def test_an_entry_of_the_current_text_is_spent_first(tmp_path):
    """The reworded entry stays for a finding that nothing else holds."""
    message = _now("call", prop="Картинка", call="Ресурсы.Путь")
    data = _payload(message)
    data["files"][_FILE][_RULE][_OLD] = 1
    reworded: list[dict] = []

    kept, suppressed, _unused, stale = baseline.apply([_finding(tmp_path, message)], data,
                                                      tmp_path, reworded=reworded)

    assert kept == [] and suppressed == 1 and reworded == []
    assert [row["message"] for row in stale] == [_OLD]


def test_a_rewrite_carries_the_reason_to_the_new_text(tmp_path):
    target = tmp_path / "baseline.json"
    baseline.save(target, _payload(_OLD, reason="решение проекта"))
    message = _now("call", prop="Картинка", call="Ресурсы.Путь")

    data = baseline.write(target, [_finding(tmp_path, message)])

    assert data["files"][_FILE][_RULE] == {message: {"count": 1, "reason": "решение проекта"}}


# --- the command ------------------------------------------------------------------------------

_READONLY = "метод Ф()\n    знч Итог = 1\n    Итог = 2\n;\n"
_NO_PAIR = ["--ignore", "structure/xbsl-pair"]


def _reword(target) -> str:
    """Give the one entry of the file a wording no release of the rule has: the old text."""
    data = json.loads(target.read_text(encoding="utf-8-sig"))
    [(path, per_rule)] = data["files"].items()
    [(rule, per_message)] = per_rule.items()
    [(message, _count)] = per_message.items()
    old = message + " Так правило писало раньше."
    data["files"][path][rule] = {old: {"count": 1, "reason": "решение проекта"}}
    target.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    return old


@pytest.mark.needs_data
def test_the_run_names_the_reworded_entries_and_the_rewrite_keeps_the_reason(tmp_path, capsys):
    module = tmp_path / "Модуль.xbsl"
    module.write_text(_READONLY, encoding="utf-8")
    target = tmp_path / "baseline.json"
    cli.main(["--write-baseline", str(target), "--select", "code/assign-readonly", *_NO_PAIR,
              str(module)])
    capsys.readouterr()
    old = _reword(target)

    code = cli.main(["--baseline", str(target), "--select", "code/assign-readonly", *_NO_PAIR,
                     str(module)])
    err = capsys.readouterr().err
    assert code == 0
    assert i18n.t("cli.baseline-reworded", count=1) in err

    cli.main(["--format", "json", "--baseline", str(target), "--select", "code/assign-readonly",
              *_NO_PAIR, str(module)])
    summary = json.loads(capsys.readouterr().out)["summary"]
    assert summary["baselined"] == 1 and summary["baseline_stale"] == 0
    assert summary["baseline_reworded"] == 1
    assert [row["message"] for row in summary["baseline_reworded_entries"]] == [old]

    cli.main(["--write-baseline", str(target), "--select", "code/assign-readonly", *_NO_PAIR,
              str(module)])
    capsys.readouterr()
    rewritten = json.loads(target.read_text(encoding="utf-8-sig"))["files"]
    [per_rule] = rewritten.values()
    [(message, value)] = per_rule["code/assign-readonly"].items()
    assert message != old and value == {"count": 1, "reason": "решение проекта"}


@pytest.mark.needs_data
def test_lint_paths_names_the_reworded_entries(tmp_path, capsys, mcp_module):
    module = tmp_path / "Модуль.xbsl"
    module.write_text(_READONLY, encoding="utf-8")
    target = tmp_path / "baseline.json"
    cli.main(["--write-baseline", str(target), "--select", "code/assign-readonly", *_NO_PAIR,
              str(module)])
    capsys.readouterr()
    old = _reword(target)

    answer = mcp_module.lint_paths([str(module)], select=["code/assign-readonly"],
                                   ignore=["structure/xbsl-pair"], baseline=str(target))

    summary = answer["summary"]
    assert summary["baselined"] == 1 and summary["baseline_stale"] == 0
    assert summary["baseline_reworded"] == 1
    assert summary["baseline_reworded_entries"][0]["message"] == old
