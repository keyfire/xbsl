"""CLI: машиночитаемый вывод (--format json) и режим редактора (--stdin).

Зависит от данных Элемента: main() резолвит версию данных до разбора буфера (см. conftest –
модуль в списке пропускаемых, если данные не сгенерированы).
"""

import io
import json

from xbsllint import cli


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
    f.write_text("метод Ф()\n    возврат 1  \n;\n// хвост…\n", encoding="utf-8")

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
    f.write_text("метод Ф()\n    возврат 1  \n;\n", encoding="utf-8")  # хвостовой пробел

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
