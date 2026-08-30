import json
from pathlib import Path

import pytest

from xbsl import i18n
from xbsl.translation import cli


@pytest.mark.needs_data
def test_suggest_needs_a_configured_provider(tmp_path: Path, monkeypatch, capsys):
    monkeypatch.delenv("XBSL_TRANSLATE_YANDEX_KEY", raising=False)
    monkeypatch.delenv("XBSL_TRANSLATE_YANDEX_FOLDER", raising=False)
    monkeypatch.delenv("XBSL_TRANSLATE_GOOGLE_KEY", raising=False)
    code = cli.cli_main([str(tmp_path), "--suggest", "--format", "json"])
    assert code != 0
    report = json.loads(capsys.readouterr().out)
    assert "XBSL_TRANSLATE_GOOGLE_KEY" in report["error"]


def test_the_help_names_the_new_flags(capsys):
    parser = cli._parser()
    text = parser.format_help()
    assert "--suggest" in text and "--suggest-out" in text and "--provider" in text


@pytest.mark.needs_data
def test_suggest_offers_no_glossary_or_terms_yet(tmp_path: Path, monkeypatch, capsys):
    """The dictionary has no `terms` section yet - the command must invent nothing to fill it."""
    monkeypatch.setenv("XBSL_TRANSLATE_GOOGLE_KEY", "fake-key")
    monkeypatch.delenv("XBSL_TRANSLATE_YANDEX_KEY", raising=False)
    monkeypatch.delenv("XBSL_TRANSLATE_YANDEX_FOLDER", raising=False)

    project = tmp_path / "project"
    project.mkdir()
    (project / "Project.yaml").write_text("version: 1\n", encoding="utf-8")
    dictionary = tmp_path / "xbsl-translation"
    dictionary.mkdir()

    from xbsl.translation.machine import dispatch as dispatch_module

    seen = {}

    def spy_suggest(gaps, provider, cache, glossary=(), transport=None, taken=None, terms=None):
        seen["glossary"] = glossary
        seen["terms"] = terms
        return dispatch_module.Result()

    monkeypatch.setattr(dispatch_module, "suggest", spy_suggest)

    code = cli.cli_main(
        [str(project), "--dictionary", str(dictionary), "--suggest", "--format", "json"])
    assert code == 0
    assert not seen["glossary"]
    assert seen["terms"] == {}


@pytest.mark.needs_data
def test_suggest_passes_the_terms_section_as_glossary_and_spelling(tmp_path: Path, monkeypatch, capsys):
    """A `terms` section hands the provider a glossary and the name builder a spelling map."""
    monkeypatch.setenv("XBSL_TRANSLATE_GOOGLE_KEY", "fake-key")
    monkeypatch.delenv("XBSL_TRANSLATE_YANDEX_KEY", raising=False)
    monkeypatch.delenv("XBSL_TRANSLATE_YANDEX_FOLDER", raising=False)

    project = tmp_path / "project"
    project.mkdir()
    (project / "Project.yaml").write_text("version: 1\n", encoding="utf-8")
    dictionary = tmp_path / "xbsl-translation"
    dictionary.mkdir()
    (dictionary / "terms.yaml").write_text(
        "terms:\n    Задача: Task\n    Исполнитель: Assignee\n", encoding="utf-8")

    from xbsl.translation.machine import dispatch as dispatch_module

    seen = {}

    def spy_suggest(gaps, provider, cache, glossary=(), transport=None, taken=None, terms=None):
        seen["glossary"] = glossary
        seen["terms"] = terms
        return dispatch_module.Result()

    monkeypatch.setattr(dispatch_module, "suggest", spy_suggest)

    code = cli.cli_main(
        [str(project), "--dictionary", str(dictionary), "--suggest", "--format", "json"])
    assert code == 0
    assert sorted(seen["glossary"]) == [("Задача", "Task"), ("Исполнитель", "Assignee")]
    assert seen["terms"] == {"task": "Task", "assignee": "Assignee"}


def test_suggest_out_help_states_the_directory_is_dropped():
    """An example alone does not tell the reader `output/x.yaml` loses `output/` on write."""
    texts = i18n.translations("translate.help.suggest-out")
    assert "director" in texts["en"] and "drop" in texts["en"]
    assert "каталог" in texts["ru"] and "отбрас" in texts["ru"]


@pytest.mark.needs_data
def test_refusal_reasons_are_visible_in_both_output_formats(tmp_path: Path, monkeypatch, capsys):
    monkeypatch.setenv("XBSL_TRANSLATE_GOOGLE_KEY", "fake-key")
    monkeypatch.delenv("XBSL_TRANSLATE_YANDEX_KEY", raising=False)
    monkeypatch.delenv("XBSL_TRANSLATE_YANDEX_FOLDER", raising=False)

    project = tmp_path / "project"
    project.mkdir()
    (project / "Project.yaml").write_text("version: 1\n", encoding="utf-8")
    dictionary = tmp_path / "xbsl-translation"
    dictionary.mkdir()

    from xbsl.translation.machine import dispatch as dispatch_module

    def spy_suggest(gaps, provider, cache, glossary=(), transport=None, taken=None, terms=None):
        return dispatch_module.Result(refused={("token", "Заказ"): "not an identifier: '42 %'"})

    monkeypatch.setattr(dispatch_module, "suggest", spy_suggest)

    code = cli.cli_main(
        [str(project), "--dictionary", str(dictionary), "--suggest", "--format", "json"])
    assert code == 0
    report = json.loads(capsys.readouterr().out)
    assert report["machine"]["refused"] == 1  # the count is unchanged
    assert report["machine"]["refusals"] == [
        {"kind": "token", "key": "Заказ", "reason": "not an identifier: '42 %'"}
    ]

    code = cli.cli_main(
        [str(project), "--dictionary", str(dictionary), "--suggest", "--format", "text"])
    assert code == 0
    text = capsys.readouterr().out
    assert "Заказ" in text and "not an identifier: '42 %'" in text


@pytest.mark.needs_data
def test_unknown_plan_name_is_refused_not_silently_dropped(tmp_path: Path, monkeypatch, capsys):
    monkeypatch.setenv("XBSL_TRANSLATE_GOOGLE_KEY", "fake-key")
    monkeypatch.delenv("XBSL_TRANSLATE_YANDEX_KEY", raising=False)
    monkeypatch.delenv("XBSL_TRANSLATE_YANDEX_FOLDER", raising=False)

    code = cli.cli_main(
        [str(tmp_path), "--suggest", "--plans", "tokens,bogus", "--format", "json"])
    assert code != 0
    report = json.loads(capsys.readouterr().out)
    assert "bogus" in report["error"]
    assert "tokens" in report["error"]
    assert "phrases" in report["error"]
    assert "literals" in report["error"]


def _only_google(monkeypatch):
    monkeypatch.setenv("XBSL_TRANSLATE_GOOGLE_KEY", "fake-key")
    monkeypatch.delenv("XBSL_TRANSLATE_YANDEX_KEY", raising=False)
    monkeypatch.delenv("XBSL_TRANSLATE_YANDEX_FOLDER", raising=False)


@pytest.mark.needs_data
def test_suggest_refuses_a_limit_it_would_silently_ignore(tmp_path: Path, monkeypatch, capsys):
    """`--limit` is what a person reaches for to cap a PAID run - silence there is expensive."""
    _only_google(monkeypatch)
    code = cli.cli_main([str(tmp_path), "--suggest", "--limit", "20", "--format", "json"])
    assert code == 2
    report = json.loads(capsys.readouterr().out)
    assert "--limit" in report["error"]


@pytest.mark.needs_data
def test_suggest_names_every_flag_it_does_not_read(tmp_path: Path, monkeypatch, capsys):
    _only_google(monkeypatch)
    code = cli.cli_main([
        str(tmp_path), "--suggest", "--filter", "Задач", "--kind", "token",
        "--limit", "20", "--offset", "5",
    ])
    assert code == 2
    text = capsys.readouterr().out
    for flag in ("--filter", "--kind", "--limit", "--offset"):
        assert flag in text


@pytest.mark.needs_data
def test_suggest_without_those_flags_is_not_refused_for_them(tmp_path: Path, monkeypatch, capsys):
    """The gate must catch the flags alone - a plain run still reaches the provider check."""
    monkeypatch.delenv("XBSL_TRANSLATE_GOOGLE_KEY", raising=False)
    monkeypatch.delenv("XBSL_TRANSLATE_YANDEX_KEY", raising=False)
    monkeypatch.delenv("XBSL_TRANSLATE_YANDEX_FOLDER", raising=False)
    code = cli.cli_main([str(tmp_path), "--suggest", "--format", "json"])
    assert code == 2
    report = json.loads(capsys.readouterr().out)
    assert "--limit" not in report["error"]
    assert "XBSL_TRANSLATE_GOOGLE_KEY" in report["error"]


@pytest.mark.needs_data
def test_table_mode_answers_all_three_questions_in_one_pass(tmp_path: Path, monkeypatch, capsys):
    """The panel's read: entries, gaps and totals out of a SINGLE walk over the project."""
    from xbsl.translation import project as project_module

    root = tmp_path / "Acme" / "Demo"
    root.mkdir(parents=True)
    (root / "Задачи.yaml").write_text(
        """ВидЭлемента: Справочник
Имя: Задачи
Реквизиты:
    -
        Имя: Заголовок
        Тип: Строка
""",
        encoding="utf-8",
    )
    (root / "Модуль.xbsl").write_text(
        """метод Подпись()
    возврат Задачи.Заголовок
;
""",
        encoding="utf-8",
    )
    folder = tmp_path / "xbsl-translation"
    folder.mkdir()
    (folder / "010-objects.yaml").write_text(
        """version: 1
language: en
tokens:
    Задачи: Tasks
""",
        encoding="utf-8",
    )

    passes = []
    original = project_module.translate_project

    def counted(*args, **kwargs):
        passes.append(1)
        return original(*args, **kwargs)

    monkeypatch.setattr(project_module, "translate_project", counted)
    code = cli.cli_main([str(root), "--table", "--limit", "0", "--format", "json"])
    assert code == 0
    data = json.loads(capsys.readouterr().out)

    # One pass - the whole point of the mode. Asked as `--gaps` plus a summary run it was two
    # passes, in two processes, over the same sources.
    assert len(passes) == 1
    assert any(entry["key"] == "Задачи" for entry in data["entries"])
    assert any(gap["key"] == "Заголовок" for gap in data["gaps"])
    assert data["entries_total"] == 1 and data["gaps_total"] >= 1
    assert data["totals"]["surfaces"] > 0


@pytest.mark.needs_data
def test_table_mode_honours_the_query_of_both_lists(tmp_path: Path, capsys):
    """`--kind` narrows the entries and the gaps alike, the way the separate modes do."""
    root = tmp_path / "Acme" / "Demo"
    root.mkdir(parents=True)
    (root / "Модуль.xbsl").write_text(
        """// пояснение
метод Подпись()
;
""",
        encoding="utf-8",
    )
    folder = tmp_path / "xbsl-translation"
    folder.mkdir()
    (folder / "010-objects.yaml").write_text(
        """version: 1
language: en
tokens:
    Задачи: Tasks
phrases:
    "строка": "a line"
""",
        encoding="utf-8",
    )
    code = cli.cli_main([str(root), "--table", "--kind", "token", "--limit", "0", "--format", "json"])
    assert code == 0
    data = json.loads(capsys.readouterr().out)
    assert [entry["key"] for entry in data["entries"]] == ["Задачи"]
    assert all(gap["kind"] == "token" for gap in data["gaps"])
