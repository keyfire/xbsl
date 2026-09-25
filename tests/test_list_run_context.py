"""A list run inside a project checks every file under one path form.

discover_with_context loads the rest of the project around a file (or a folder) passed on its
own, and the context comes from the RESOLVED project root. A requested path typed relative to
the working directory used to stay relative in the run, and the placement model, reading the
subsystems off the resolved root, found none for it: code/foreign-not-public took a module of a
subsystem for the project module and reported the non-public elements of its own subsystem as
foreign, code/unknown-resource lost the resources of the project. A list of four files got ten
false findings that the run over the whole tree did not have. The run now resolves every file,
and the report names the requested ones the way they were typed.

The context files feed the project rules only: the file rules skip them, their findings would
be narrowed away anyway.

The mechanics need no Element data; the rule runs parse modules and carry `needs_data`.
"""

import json
from pathlib import Path

import pytest

from xbsl import baseline, cli, engine, fixer
from xbsl.diagnostics import Diagnostic, Severity

RULE = "code/foreign-not-public"
_DUP_ID = "11111111-2222-3333-4444-555555555555"

PROJECT_YAML = "Ид: ffeacdec-02d6-4f08-bcfa-be89e9a1861a\nИмя: Проба\n"
STOCK_YAML = "ВидЭлемента: ОбщийМодуль\nИмя: Остатки\nОбластьВидимости: ВПодсистеме\n"
STOCK_XBSL = "@ВПроекте\nметод Пересчитать()\n;\n"
RECEIPT_YAML = "ВидЭлемента: ОбщийМодуль\nИмя: Приемка\nОбластьВидимости: ВПодсистеме\n"
RECEIPT_XBSL = "метод Провести()\n    Остатки.Пересчитать()\n;\n"
ORDERS_YAML = "ВидЭлемента: ОбщийМодуль\nИмя: Заявки\nОбластьВидимости: ВПодсистеме\n"
ORDERS_XBSL = "импорт Склады\n\nметод Отправить()\n    Остатки.Пересчитать()\n;\n"


def _catalog(name, ident=_DUP_ID):
    return f"ВидЭлемента: Справочник\nИд: {ident}\nИмя: {name}\n"


def _write(root: Path, files: dict[str, str]) -> None:
    for rel, text in files.items():
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")


@pytest.fixture
def workspace(tmp_path, monkeypatch):
    """A project `Проба` one folder below the working directory: the subsystem `Склады` with
    a non-public common module and a module of its own calling it, and the subsystem `Закупки`
    whose module calls the same non-public module across the boundary."""
    _write(tmp_path / "Проба", {
        "Проект.yaml": PROJECT_YAML,
        "Склады/Подсистема.yaml": "Интерфейс:\n    ВключатьВАвтоИнтерфейс: Ложь\n",
        "Склады/Остатки.yaml": STOCK_YAML,
        "Склады/Остатки.xbsl": STOCK_XBSL,
        "Склады/Приемка.yaml": RECEIPT_YAML,
        "Склады/Приемка.xbsl": RECEIPT_XBSL,
        "Закупки/Подсистема.yaml": "Использование:\n    - Склады\n",
        "Закупки/Заявки.yaml": ORDERS_YAML,
        "Закупки/Заявки.xbsl": ORDERS_XBSL,
    })
    monkeypatch.chdir(tmp_path)
    return tmp_path


def test_a_relative_request_runs_on_resolved_paths(workspace):
    typed = Path("Проба/Склады/Приемка.xbsl")
    files, requested = cli.discover_with_context([str(typed)])
    assert requested == [typed]
    assert all(f.is_absolute() and f == f.resolve() for f in files)
    assert (workspace / typed).resolve() in files
    names = {f.name for f in files}
    assert {"Проект.yaml", "Подсистема.yaml", "Остатки.xbsl", "Заявки.xbsl"} <= names


def test_a_run_without_context_keeps_the_typed_paths(workspace):
    files, requested = cli.discover_with_context(["Проба"])
    assert requested is None
    assert all(not f.is_absolute() for f in files)


def test_the_narrowing_names_a_file_as_it_was_typed(workspace):
    typed = Path("Проба/Склады/Приемка.xbsl")
    files, requested = cli.discover_with_context([str(typed)])
    own = Diagnostic(str(typed.resolve()), 2, 5, "x/y", Severity.ERROR, "own")
    other = Diagnostic(str((workspace / "Проба/Склады/Остатки.xbsl").resolve()), 1, 1, "x/y",
                       Severity.ERROR, "context")
    narrowed = cli._filter_requested([own, other], requested)
    assert [(d.path, d.message) for d in narrowed] == [(str(typed), "own")]


def test_the_context_is_everything_but_the_request(workspace):
    typed = Path("Проба/Склады/Приемка.xbsl")
    files, requested = cli.discover_with_context([str(typed)])
    context = cli._context_of(files, requested)
    assert typed.resolve() not in context
    assert set(files) - context == {typed.resolve()}
    assert cli._context_of(files, None) is None


def test_file_rules_skip_the_context(monkeypatch):
    """A file rule sees the requested file and nothing else; a project rule sees them all."""
    by_file, by_project = [], []
    probes = [
        engine.RuleInfo("probe/file", "probe.title", "B", "file", Severity.INFO,
                        lambda src: by_file.append(src.rel) or ()),
        engine.RuleInfo("probe/project", "probe.title", "B", "project", Severity.INFO,
                        lambda sources: by_project.extend(s.rel for s in sources) or ()),
    ]
    monkeypatch.setattr(engine, "RULES", [*engine.RULES, *probes])
    asked = engine.load_text("Склады/Приемка.xbsl", RECEIPT_XBSL)
    context = engine.load_text("Склады/Остатки.xbsl", STOCK_XBSL)
    engine.run_sources([asked, context], select={"probe"}, context={context.path})
    assert by_file == [asked.rel]
    assert by_project == [asked.rel, context.rel]


def test_duplicate_ids_across_the_context_are_reported_under_the_typed_path(workspace):
    _write(workspace / "Проба", {
        "Склады/Первый.yaml": _catalog("Первый"),
        "Склады/Второй.yaml": _catalog("Второй"),
    })
    typed = Path("Проба/Склады/Первый.yaml")
    files, requested = cli.discover_with_context([str(typed)])
    diags = cli._filter_requested(
        engine.run(files, select={"yaml/id-unique"}, context=cli._context_of(files, requested)),
        requested,
    )
    assert [d.path for d in diags] == [str(typed)]


def test_fix_paths_reports_and_pins_under_the_typed_path(workspace):
    _write(workspace / "Проба", {
        "Склады/Первый.yaml": _catalog("Первый"),
        "Склады/Второй.yaml": _catalog("Второй"),
    })
    typed = Path("Проба/Склады/Первый.yaml")
    files, requested = cli.discover_with_context([str(typed)])
    diags, _summary, accepted = fixer.fix_paths(
        files, select={"yaml/id-unique"}, requested=requested,
    )
    assert [d.path for d in diags] == [str(typed)] and accepted == []
    # Frozen in a baseline, the finding is pinned; the pinned pair points at the reported one.
    target = workspace / "baseline.json"
    baseline.write(target, diags)
    diags, _summary, accepted = fixer.fix_paths(
        files, select={"yaml/id-unique"}, requested=requested, baseline_path=target,
    )
    assert [d.path for d in diags] == [str(typed)]
    assert len(accepted) == 1 and accepted[0][0] is diags[0]


def _json_run(args, capsys):
    cli.main(["--format", "json", "--no-baseline", *args])
    return json.loads(capsys.readouterr().out)


@pytest.mark.needs_data  # the mapper parses the module: the lexer needs language.json
def test_a_relative_list_places_the_module_in_its_subsystem(workspace, capsys):
    typed = ["Проба/Склады/Приемка.xbsl", "Проба/Склады/Приемка.yaml"]
    payload = _json_run(["--select", RULE, *typed], capsys)
    assert payload["diagnostics"] == []
    assert payload["summary"]["files"] == 2
    # The same verdict as the tree: the module calls a module of its own subsystem.
    tree = _json_run(["--select", RULE, "Проба"], capsys)
    assert [d["path"] for d in tree["diagnostics"]] == [str(Path("Проба/Закупки/Заявки.xbsl"))]


@pytest.mark.needs_data
def test_a_relative_list_still_reports_a_call_across_the_boundary(workspace, capsys):
    payload = _json_run(["--select", RULE, "Проба/Закупки/Заявки.xbsl"], capsys)
    found = payload["diagnostics"]
    assert [(d["path"], d["line"]) for d in found] == [(str(Path("Проба/Закупки/Заявки.xbsl")), 4)]
    assert "Остатки.Пересчитать" in found[0]["message"]
    assert "вне подсистем" not in found[0]["message"]


@pytest.mark.needs_data
def test_a_relative_list_agrees_with_an_absolute_one(workspace, capsys):
    typed = ["Проба/Склады/Приемка.xbsl", "Проба/Закупки/Заявки.xbsl"]
    relative = _json_run(["--select", RULE, *typed], capsys)
    absolute = _json_run(["--select", RULE, *(str(workspace / p) for p in typed)], capsys)
    assert [(d["line"], d["message"]) for d in relative["diagnostics"]] == [
        (d["line"], d["message"]) for d in absolute["diagnostics"]
    ]
    assert len(relative["diagnostics"]) == 1
