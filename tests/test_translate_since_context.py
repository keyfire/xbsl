"""Change orphans retain old comment context and resolve dictionary paths from the caller."""

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from xbsl.translation import cli, entries


def _git(root, *args):
    result = subprocess.run(
        ["git", "-c", "user.name=test", "-c", "user.email=test@example.com",
         "-c", "commit.gpgsign=false", "-c", "core.autocrlf=false", *args],
        cwd=root, capture_output=True, stdin=subprocess.DEVNULL, timeout=30,
    )
    assert result.returncode == 0, result.stderr.decode("utf-8", "replace")
    return result.stdout.decode("utf-8", "replace").strip()


def _repo(tmp_path, source):
    if not shutil.which("git"):
        pytest.skip("git is not installed")
    project = tmp_path / "vendor" / "app"
    project.mkdir(parents=True)
    (project / "Проект.yaml").write_text(
        "ВидЭлемента: Проект\nИмя: app\nПоставщик: vendor\n", encoding="utf-8")
    module = project / "Модуль.xbsl"
    module.write_text(source, encoding="utf-8")
    folder = tmp_path / "vendor" / "xbsl-translation"
    folder.mkdir()
    dictionary = folder / "010-phrases.yaml"
    dictionary.write_text("version: 1\nlanguage: en\n", encoding="utf-8")
    _git(tmp_path, "init", "-q")
    _git(tmp_path, "add", "-A")
    _git(tmp_path, "commit", "-qm", "base")
    return project, module, dictionary, _git(tmp_path, "rev-parse", "HEAD")


@pytest.mark.needs_data
@pytest.mark.parametrize("revision", ["base", "range", "three-dot"])
def test_removed_block_opening_does_not_swallow_later_comments(tmp_path, revision):
    before = ("/* Первая строка блока.\n   Сохраненная строка блока.\n*/\n"
              "метод Первый()\n;\n\n/// Снятая документация.\nметод Второй()\n;\n"
              "// Снятое пояснение.\nметод Третий()\n;\n")
    project, module, dictionary, base = _repo(tmp_path, before)
    module.write_text(before.replace("Первая строка блока.", "Новая строка блока.")
                      .replace("/// Снятая документация.\n", "")
                      .replace("// Снятое пояснение.\n", ""), encoding="utf-8")
    since = base
    if revision != "base":
        _git(tmp_path, "add", "-A")
        _git(tmp_path, "commit", "-qm", "change")
        tip = _git(tmp_path, "rev-parse", "HEAD")
        since = base + ("..." if revision == "three-dot" else "..") + tip
    removed = entries.removed_surfaces(project, since, dictionary.parent)
    assert removed.lines == {"Первая строка блока.", "Снятая документация.", "Снятое пояснение."}


@pytest.mark.needs_data
def test_removed_block_body_uses_markers_from_unchanged_old_lines(tmp_path):
    before = "/* Сохраненная шапка.\n   Снятая строка внутри блока.\n*/\nметод А()\n;\n"
    project, module, _dictionary, base = _repo(tmp_path, before)
    module.write_text(before.replace("   Снятая строка внутри блока.\n", ""), encoding="utf-8")
    removed = entries.removed_surfaces(project, base)
    assert removed.lines == {"Снятая строка внутри блока."}


@pytest.mark.needs_data
def test_removed_text_that_looks_like_comment_inside_literal_is_not_a_phrase(tmp_path):
    before = 'метод А()\n    пер Текст = "/* Это строка */"\n;\n// Снятое пояснение.\n'
    project, module, _dictionary, base = _repo(tmp_path, before)
    module.write_text("метод А()\n;\n", encoding="utf-8")
    removed = entries.removed_surfaces(project, base)
    assert removed.lines == {"Снятое пояснение."}


@pytest.mark.needs_data
@pytest.mark.parametrize("operation", ["delete", "rename"])
def test_old_comment_context_survives_deleted_or_renamed_source(tmp_path, operation):
    source = "/* Снятая шапка.\n   Снятое пояснение.\n*/\nметод А()\n;\n"
    project, module, _dictionary, base = _repo(tmp_path, source)
    if operation == "delete":
        module.unlink()
    else:
        destination = module.with_name("Другой.xbsl")
        module.rename(destination)
        destination.write_text(source.replace("Снятое пояснение.", "Новое пояснение."), encoding="utf-8")
        _git(tmp_path, "add", "-A")
    removed = entries.removed_surfaces(project, base)
    assert "Снятое пояснение." in removed.lines
    assert "Новое пояснение." not in removed.lines


def test_resource_block_body_uses_unchanged_delimiters(tmp_path):
    project, _module, _dictionary, _base = _repo(tmp_path, "")
    resource = project / "style.css"
    resource.write_text("/* Сохраненная шапка.\n   Снятая строка.\n*/\na {}\n", encoding="utf-8")
    _git(tmp_path, "add", "-A")
    _git(tmp_path, "commit", "-qm", "resource")
    base = _git(tmp_path, "rev-parse", "HEAD")
    resource.write_text("/* Сохраненная шапка.\n*/\na {}\n", encoding="utf-8")
    removed = entries.removed_surfaces(project, base)
    assert removed.lines == {"Снятая строка."}


@pytest.mark.needs_data
def test_cli_since_reads_relative_dictionary_and_prunes_only_new_orphans(tmp_path, monkeypatch, capsys):
    project, _module, dictionary, base = _repo(tmp_path, "")
    dictionary.write_text("version: 1\nlanguage: en\nphrases:\n    Старый долг.: Old debt.\n", encoding="utf-8")
    _git(tmp_path, "add", "-A")
    _git(tmp_path, "commit", "-qm", "old orphan")
    base = _git(tmp_path, "rev-parse", "HEAD")
    dictionary.write_text(dictionary.read_text(encoding="utf-8")
                          + "    Новая сирота.: New orphan.\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    result = cli.cli_main([str(project.relative_to(tmp_path)), "--unused", "--since", base,
                           "--prune", "--format", "json"])
    output = json.loads(capsys.readouterr().out)
    assert result == 0
    assert output["since"]["dictionary_files"] == 1
    assert "Новая сирота." not in dictionary.read_text(encoding="utf-8")
    assert "Старый долг." in dictionary.read_text(encoding="utf-8")
