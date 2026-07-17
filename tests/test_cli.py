"""CLI: машиночитаемый вывод (--format json) и режим редактора (--stdin).

Зависит от данных Элемента: main() резолвит версию данных до разбора буфера (см. conftest –
модуль в списке пропускаемых, если данные не сгенерированы).
"""

import io
import json

from xbsl import cli


def _feed_stdin(monkeypatch, data: bytes):
    # main() читает sys.stdin.buffer.read(); TextIOWrapper.buffer отдаёт исходные байты.
    monkeypatch.setattr("sys.stdin", io.TextIOWrapper(io.BytesIO(data), encoding="utf-8"))


def test_stdin_json_reports_buffer_diagnostics(monkeypatch, capsys):
    buf = "метод Ф()\n    пер Икс = (1 + 2\n    возврат Икс\n;\n".encode("utf-8")
    _feed_stdin(monkeypatch, buf)

    code = cli.main(["--stdin", "--filename", "Test.xbsl", "--format", "json"])

    payload = json.loads(capsys.readouterr().out)
    rules = {d["rule"] for d in payload["diagnostics"]}
    assert "code/brackets" in rules            # незакрытая скобка
    assert payload["summary"]["errors"] >= 1
    assert code == 1                           # есть ошибка – ненулевой код


def test_stdin_requires_filename(monkeypatch, capsys):
    _feed_stdin(monkeypatch, b"x\n")

    code = cli.main(["--stdin", "--format", "json"])

    assert code == 2
    assert "--filename" in capsys.readouterr().err


def test_select_flags_accumulate(tmp_path, capsys):
    # Повторённые --select суммируются (а не затирают друг друга последним значением);
    # форма со списком через запятую продолжает работать.
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
    f.write_text("метод Ф(): Число\n    возврат 1  \n;\n", encoding="utf-8")  # хвостовой пробел

    # json: замечание есть, только warning – код 0
    code = cli.main(["--format", "json", str(f)])
    payload = json.loads(capsys.readouterr().out)
    assert any(d["rule"] == "whitespace/trailing" for d in payload["diagnostics"])
    assert code == 0

    # text: замечания в stdout, сводка в stderr
    cli.main([str(f)])
    cap = capsys.readouterr()
    assert "whitespace/trailing" in cap.out
    assert "Проверено файлов" in cap.err


def test_discover_skips_hidden_directories(tmp_path):
    # Скрытые каталоги (git worktree в .claude, .git) держат копии исходников: их файлы
    # не должны попадать в обход, иначе межфайловые правила видят дубли.
    visible = tmp_path / "e1c" / "app" / "А.yaml"
    visible.parent.mkdir(parents=True)
    visible.write_text("Ид: 1\n", encoding="utf-8")
    hidden = tmp_path / ".claude" / "worktrees" / "T-1" / "e1c" / "app" / "А.yaml"
    hidden.parent.mkdir(parents=True)
    hidden.write_text("Ид: 1\n", encoding="utf-8")
    dotfile = tmp_path / "e1c" / "app" / ".служебный.yaml"
    dotfile.write_text("мусор\n", encoding="utf-8")

    found = cli.discover([str(tmp_path)])

    assert visible in found
    assert all(".claude" not in f.parts for f in found)
    assert all(not f.name.startswith(".") for f in found)


def test_discover_scans_root_inside_hidden_directory(tmp_path):
    # Сам корень может лежать в скрытом каталоге (открытый worktree) – это нормально,
    # фильтр действует только на компоненты НИЖЕ корня.
    root = tmp_path / ".claude" / "worktrees" / "T-1"
    f = root / "e1c" / "app" / "А.yaml"
    f.parent.mkdir(parents=True)
    f.write_text("Ид: 1\n", encoding="utf-8")

    found = cli.discover([str(root)])

    assert f in found

