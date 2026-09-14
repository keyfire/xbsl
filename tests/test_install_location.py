"""The engine names the copy that answers, not only its version.

One machine carries several copies of the engine: a pipx venv, the interpreter's own
site-packages, an editable checkout and a worktree of it. Unreleased code prints the number of
the last release, so `xbsl --version` from a worktree, from the editable checkout and from pipx
read the same, and the MCP `version_info` of the first two differed in nothing - both run under
one interpreter. A version check made seconds before `self-update` reached the copy on PATH read
that copy's old number as a stale editable install, and the hunt went through install metadata.

`environment.location()` is the directory the engine is imported from. `--version` ends its
first line with it, `--where` names it with the interpreter, the MCP `version_info` carries it,
and so does the log line the LSP server writes on start. None of it needs the Element data.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

import xbsl
from xbsl import __version__, cli, environment

ROOT = Path(__file__).resolve().parents[1]


def _version_output(capsys, lang: str) -> list[str]:
    with pytest.raises(SystemExit) as done:
        cli.main(["--version", "--lang", lang])
    assert done.value.code == 0
    return capsys.readouterr().out.splitlines()


def test_the_location_is_the_folder_the_package_is_imported_from():
    location = Path(environment.location())
    assert location == Path(xbsl.__file__).resolve().parent.parent
    assert (location / "xbsl" / "environment.py").is_file()


def test_the_version_line_ends_with_the_location(capsys):
    location = environment.location()

    lines = _version_output(capsys, "ru")
    assert len(lines) == 1, "a reader takes the first line: the location belongs on it"
    assert lines[0].startswith(f"xbsl {__version__}")
    assert lines[0].endswith(f"; установка: {location}")

    (english,) = _version_output(capsys, "en")
    assert english.endswith(f"; location: {location}")


def test_where_names_the_location_and_the_interpreter_before_the_data(tmp_path, capsys):
    empty = tmp_path / "no-data"
    empty.mkdir()

    assert cli.main(["--where", "--data-dir", str(empty), "--lang", "ru"]) == 0

    lines = capsys.readouterr().out.splitlines()
    assert lines[:3] == [
        f"установка: {environment.location()}",
        f"интерпретатор: {sys.executable}",
        f"корень данных: {empty}",
    ]


def test_version_info_carries_the_location(mcp_module):
    answer = mcp_module.version_info()
    assert answer["location"] == environment.location()
    assert answer["python"] == sys.executable


def test_the_lsp_start_log_names_the_location():
    assert f"установка: {environment.location()};" in environment.note()


def test_the_location_follows_the_imported_code_past_install_metadata(tmp_path):
    """A child whose path lists stale metadata first still names the checkout it imports."""
    metadata = tmp_path / "stale" / "xbsl-0.1.0.dist-info"
    metadata.mkdir(parents=True)
    (metadata / "METADATA").write_bytes(b"Metadata-Version: 2.1\nName: xbsl\nVersion: 0.1.0\n")
    code = (
        "import importlib.metadata, sys\n"
        "from xbsl import environment\n"
        "sys.stdout.write(importlib.metadata.version('xbsl') + '\\n' + environment.location())\n"
    )
    done = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True, encoding="utf-8", timeout=120, stdin=subprocess.DEVNULL,
        cwd=str(tmp_path),
        env={
            **os.environ, "PYTHONIOENCODING": "utf-8",
            "PYTHONPATH": os.pathsep.join([str(tmp_path / "stale"), str(ROOT)]),
        },
    )
    assert done.returncode == 0, done.stderr
    claimed, location = done.stdout.splitlines()
    assert claimed == "0.1.0"
    assert Path(location) == ROOT
