"""CLI: machine-readable output (--format json) and editor mode (--stdin).

Depends on the Element data: main() resolves the data version before parsing the buffer
(see conftest - the module is in the skip list when the data has not been generated).
"""

import io
import json

from xbsl import cli, engine


def _feed_stdin(monkeypatch, data: bytes):
    # main() reads sys.stdin.buffer.read(); TextIOWrapper.buffer yields the raw bytes.
    monkeypatch.setattr("sys.stdin", io.TextIOWrapper(io.BytesIO(data), encoding="utf-8"))


def test_stdin_json_reports_buffer_diagnostics(monkeypatch, capsys):
    buf = "метод Ф()\n    пер Икс = (1 + 2\n    возврат Икс\n;\n".encode("utf-8")
    _feed_stdin(monkeypatch, buf)

    code = cli.main(["--stdin", "--filename", "Test.xbsl", "--format", "json"])

    payload = json.loads(capsys.readouterr().out)
    rules = {d["rule"] for d in payload["diagnostics"]}
    assert "code/brackets" in rules            # unclosed bracket
    assert payload["summary"]["errors"] >= 1
    assert code == 1                           # there is an error - non-zero exit code


def test_stdin_requires_filename(monkeypatch, capsys):
    _feed_stdin(monkeypatch, b"x\n")

    code = cli.main(["--stdin", "--format", "json"])

    assert code == 2
    assert "--filename" in capsys.readouterr().err


def test_select_flags_accumulate(tmp_path, capsys):
    # Repeated --select flags accumulate (rather than the last value clobbering the others);
    # the comma-separated list form keeps working.
    f = tmp_path / "Ч.xbsl"
    f.write_text("метод Ф(): Число\n    возврат 1  \n;\n// хвост…\n", encoding="utf-8")

    cli.main(["--format", "json", "--select", "whitespace/trailing",
              "--select", "typography/ellipsis", str(f)])
    payload = json.loads(capsys.readouterr().out)
    assert {d["rule"] for d in payload["diagnostics"]} == {
        "whitespace/trailing", "typography/ellipsis"}

    cli.main(["--format", "json", "--select", "whitespace/trailing,typography/ellipsis", str(f)])
    payload = json.loads(capsys.readouterr().out)
    assert {d["rule"] for d in payload["diagnostics"]} == {
        "whitespace/trailing", "typography/ellipsis"}


def test_json_and_text_on_disk(tmp_path, capsys):
    f = tmp_path / "Ч.xbsl"
    f.write_text("метод Ф(): Число\n    возврат 1  \n;\n", encoding="utf-8")  # trailing whitespace

    # json: there is a finding, warnings only - exit code 0
    code = cli.main(["--format", "json", str(f)])
    payload = json.loads(capsys.readouterr().out)
    assert any(d["rule"] == "whitespace/trailing" for d in payload["diagnostics"])
    assert code == 0

    # text: findings go to stdout, the summary to stderr
    cli.main([str(f)])
    cap = capsys.readouterr()
    assert "whitespace/trailing" in cap.out
    assert "Проверено файлов" in cap.err


def test_out_writes_the_report_to_a_file_without_bom(tmp_path, capsys):
    """--out: comparing reports before and after a change is an everyday scenario, and
    on Windows the shell redirection prefixes the output with a BOM that breaks json.load."""
    f = tmp_path / "Ч.xbsl"
    f.write_text("метод Ф(): Число\n    возврат 1  \n;\n", encoding="utf-8")
    target = tmp_path / "отчёт.json"

    code = cli.main(["--format", "json", "--out", str(target), str(f)])
    raw = target.read_bytes()
    assert not raw.startswith(b"\xef\xbb\xbf")  # no BOM
    payload = json.loads(raw.decode("utf-8"))
    assert any(d["rule"] == "whitespace/trailing" for d in payload["diagnostics"])
    assert capsys.readouterr().out == ""  # the report went to the file, stdout is empty
    assert code == 0

    # The text format honours the same switch; the summary stays on stderr.
    text_target = tmp_path / "отчёт.txt"
    cli.main(["--out", str(text_target), str(f)])
    cap = capsys.readouterr()
    assert "whitespace/trailing" in text_target.read_text(encoding="utf-8")
    assert cap.out == ""
    assert "Проверено файлов" in cap.err


def test_discover_skips_hidden_directories(tmp_path):
    # Hidden directories (a git worktree under .claude, .git) hold copies of the sources: their
    # files must not be picked up by discovery, or cross-file rules would see duplicates.
    visible = tmp_path / "acme" / "app" / "А.yaml"
    visible.parent.mkdir(parents=True)
    visible.write_text("Ид: 1\n", encoding="utf-8")
    hidden = tmp_path / ".claude" / "worktrees" / "T-1" / "acme" / "app" / "А.yaml"
    hidden.parent.mkdir(parents=True)
    hidden.write_text("Ид: 1\n", encoding="utf-8")
    dotfile = tmp_path / "acme" / "app" / ".служебный.yaml"
    dotfile.write_text("мусор\n", encoding="utf-8")

    found = cli.discover([str(tmp_path)])

    assert visible in found
    assert all(".claude" not in f.parts for f in found)
    assert all(not f.name.startswith(".") for f in found)


def test_discover_scans_root_inside_hidden_directory(tmp_path):
    # The root itself may live inside a hidden directory (an opened worktree) - that is fine,
    # the filter only applies to components BELOW the root.
    root = tmp_path / ".claude" / "worktrees" / "T-1"
    f = root / "acme" / "app" / "А.yaml"
    f.parent.mkdir(parents=True)
    f.write_text("Ид: 1\n", encoding="utf-8")

    found = cli.discover([str(root)])

    assert f in found



# --- query files of virtual tables (.xbql) ------------------------------------------------

_QUERY_TABLE = """ВЫБРАТЬ
    З.Ссылка КАК Ссылка,
    З.Наименование КАК Наименование
ИЗ
    {table} КАК З
ГДЕ
    З.Шаг == &Шаг
"""

_CATALOG = """ВидЭлемента: Справочник
Ид: 7a7a7a7a-1111-2222-3333-444444444444
Имя: Задачи
Реквизиты:
    -
        Имя: Шаг
        Тип: Строка
"""


def _query_project(tmp_path, table: str):
    """A project of one catalog plus a virtual table whose query names `table`."""
    (tmp_path / "Задачи.yaml").write_text(_CATALOG, encoding="utf-8")
    (tmp_path / "ЗадачиТаблица.yaml").write_text(
        "ВидЭлемента: ВиртуальнаяТаблица\n"
        "Ид: 7b7b7b7b-1111-2222-3333-444444444444\n"
        "Имя: ЗадачиТаблица\n"
        "Параметры:\n    -\n        Имя: Шаг\n        Тип: Строка\n",
        encoding="utf-8",
    )
    (tmp_path / "ЗадачиТаблица.xbql").write_text(
        _QUERY_TABLE.format(table=table), encoding="utf-8"
    )
    return cli.discover([str(tmp_path)])


def test_discover_collects_query_files(tmp_path):
    """Until they were collected, an unknown table in a virtual table's query was found by
    nobody but the server compiler."""
    found = _query_project(tmp_path, "Задачи")
    assert any(f.suffix == ".xbql" for f in found), [f.name for f in found]


def test_a_single_query_file_is_accepted_as_a_path(tmp_path):
    _query_project(tmp_path, "Задачи")
    found = cli.discover([str(tmp_path / "ЗадачиТаблица.xbql")])
    assert [f.name for f in found] == ["ЗадачиТаблица.xbql"]


def test_an_unknown_table_in_a_query_file_is_reported(tmp_path):
    paths = _query_project(tmp_path, "НетТакой")
    found = engine.run(paths)
    assert [x.rule_id for x in found if x.path.endswith(".xbql")] == ["query/unknown-table"]


def test_a_query_file_is_not_judged_as_a_module(tmp_path):
    """It lexes as code and loads with kind `xbsl`, but it is one query expression: the module
    parser would meet it with "a module import, method... is expected" on line 1, and the
    ampersand parameter is the documented syntax there rather than the literal's mistake."""
    paths = _query_project(tmp_path, "Задачи")
    found = engine.run(paths)
    in_query = [x.rule_id for x in found if x.path.endswith(".xbql")]
    assert in_query == [], in_query


# --- a path that is not there ---------------------------------------------------------------


def test_a_missing_path_is_an_error(tmp_path, capsys):
    """A typo in a path used to answer "0 files checked" with the exit code of a clean run.

    In CI that is a green step which checked nothing: `xbsl e1c/sit` passes for the whole
    project. The same shape covers a mistyped subcommand - an unknown name is parsed as a path.
    """
    code = cli.main([str(tmp_path / "нет-такого")])
    assert code == 2
    assert "нет-такого" in capsys.readouterr().err


def test_a_missing_path_among_good_ones_is_an_error(tmp_path, capsys):
    (tmp_path / "М.xbsl").write_text("метод Ф()\n;\n", encoding="utf-8")
    code = cli.main([str(tmp_path), str(tmp_path / "нет-такого")])
    assert code == 2


def test_an_empty_directory_warns_but_passes(tmp_path, capsys):
    """An empty directory is a legitimate state of a fresh project - a warning, not an error."""
    code = cli.main([str(tmp_path)])
    assert code == 0
    assert "исходник" in capsys.readouterr().err


def test_a_directory_with_sources_says_nothing_extra(tmp_path, capsys):
    (tmp_path / "М.xbsl").write_text("метод Ф()\n;\n", encoding="utf-8")
    code = cli.main([str(tmp_path)])
    assert code == 0
    assert "исходник" not in capsys.readouterr().err
