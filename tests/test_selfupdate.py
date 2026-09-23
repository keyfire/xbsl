"""Self-update (`xbsl self-update`): wheel extraction with no network (urllib is mocked).

The command must replace both the xbsl package and the xbsllint alias package from the same
wheel, without touching the dist-info of the transitional xbsllint metapackage, and refuse
to run in an editable install (there git does the updating, and extraction would wreck the
repository).

The rest of the module is about the failure this command exists for: a held installation.
Whatever goes wrong - a locked file, a broken archive, a package that does not import -
the previous installation must still be there afterwards. That is checked by looking at
the disk, not at the return value.
"""

from __future__ import annotations

import io
import json
import os
import zipfile

import pytest

import xbsl
from xbsl import cli, selfupdate


def _fake_wheel(version: str) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as archive:
        archive.writestr("xbsl/__init__.py", f'__version__ = "{version}"\n')
        archive.writestr("xbsllint/__init__.py", "import xbsl\n")
        archive.writestr(f"xbsl-{version}.dist-info/METADATA", f"Version: {version}\n")
    return buf.getvalue()


class _FakeResp:
    def __init__(self, data):
        self._data = data

    def read(self):
        return self._data

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


@pytest.fixture()
def fake_site(tmp_path, monkeypatch):
    """A fake site-packages with an old xbsl install + the xbsllint metapackage."""
    site = tmp_path / "site-packages"
    (site / "xbsl").mkdir(parents=True)
    (site / "xbsl" / "__init__.py").write_text('__version__ = "0.0.1"\n', encoding="utf-8")
    (site / "xbsllint").mkdir()
    (site / "xbsllint" / "__init__.py").write_text("import xbsl\n", encoding="utf-8")
    (site / "xbsl-0.0.1.dist-info").mkdir()
    # the dist-info of the transitional xbsllint METApackage is a foreign delivery, left alone.
    (site / "xbsllint-0.16.0.dist-info").mkdir()
    monkeypatch.setattr(selfupdate, "_site_packages", lambda: site)
    return site


def test_self_update_extracts_wheel(fake_site, monkeypatch):
    monkeypatch.setattr(selfupdate, "_wheel_url",
                        lambda v, native=False: ("http://pypi/xbsl.whl", "9.9.9", selfupdate.PORTABLE))
    monkeypatch.setattr(
        selfupdate.urllib.request, "urlopen", lambda url, timeout=0: _FakeResp(_fake_wheel("9.9.9"))
    )

    old, new = selfupdate.self_update(log=lambda *a: None)

    assert new == "9.9.9" and old == xbsl.__version__
    text = (fake_site / "xbsl" / "__init__.py").read_text(encoding="utf-8")
    assert '__version__ = "9.9.9"' in text
    assert (fake_site / "xbsllint" / "__init__.py").is_file()  # the alias is replaced with the package
    assert not (fake_site / "xbsl-0.0.1.dist-info").exists()  # the old dist-info is removed
    assert (fake_site / "xbsl-9.9.9.dist-info").exists()
    assert (fake_site / "xbsllint-0.16.0.dist-info").exists()  # the metapackage is untouched


def test_self_update_noop_when_current(fake_site, monkeypatch):
    monkeypatch.setattr(selfupdate, "_wheel_url",
                        lambda v, native=False: ("http://pypi/x.whl", xbsl.__version__, selfupdate.PORTABLE))

    def boom(*a, **k):
        raise AssertionError("скачивание не должно происходить")

    monkeypatch.setattr(selfupdate.urllib.request, "urlopen", boom)
    old, new = selfupdate.self_update(log=lambda *a: None)
    assert old == new == xbsl.__version__


def test_self_update_refuses_editable(monkeypatch, tmp_path):
    # The package directory is not site-packages - so it is an editable install from the repo.
    monkeypatch.setattr(selfupdate, "_site_packages", lambda: tmp_path / "xbsl-lint-public")
    with pytest.raises(selfupdate.SelfUpdateError, match="editable"):
        selfupdate.self_update(log=lambda *a: None)


def test_cli_dispatch(fake_site, monkeypatch, capsys):
    monkeypatch.setattr(selfupdate, "_wheel_url",
                        lambda v, native=False: ("http://pypi/xbsl.whl", "9.9.9", selfupdate.PORTABLE))
    monkeypatch.setattr(
        selfupdate.urllib.request, "urlopen", lambda url, timeout=0: _FakeResp(_fake_wheel("9.9.9"))
    )
    code = cli.main(["self-update"])
    assert code == 0
    out = json.loads(capsys.readouterr().out)
    assert out["updated"] is True and out["to"] == "9.9.9"


def test_cli_reports_error_as_json(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(selfupdate, "_site_packages", lambda: tmp_path / "repo")
    code = cli.main(["self-update"])
    assert code == 2
    assert "editable" in json.loads(capsys.readouterr().out)["error"]


# -- занятая установка: что бы ни случилось, прежняя версия остаётся на месте ---------------


def _stub_download(monkeypatch, payload=None):
    monkeypatch.setattr(
        selfupdate, "_wheel_url",
        lambda v, native=False: ("http://pypi/xbsl.whl", "9.9.9", selfupdate.PORTABLE),
    )
    monkeypatch.setattr(
        selfupdate.urllib.request, "urlopen",
        lambda url, timeout=0: _FakeResp(_fake_wheel("9.9.9") if payload is None else payload),
    )


def test_busy_installation_is_refused_before_anything_is_removed(fake_site, monkeypatch):
    """Переименование - ворота процедуры: файл занят, а удалять ещё нечего."""
    _stub_download(monkeypatch)
    original = selfupdate.Path.rename

    def refuse(self, target):
        if self.name == "xbsl":
            raise OSError(13, "Файл занят другим процессом")
        return original(self, target)

    monkeypatch.setattr(selfupdate.Path, "rename", refuse)
    monkeypatch.setattr(selfupdate, "holders", lambda: [{"pid": 4242, "name": "xbsl-lsp.exe"}])

    with pytest.raises(selfupdate.SelfUpdateError) as error:
        selfupdate.self_update(log=lambda *a: None)

    message = str(error.value)
    assert "xbsl-lsp.exe" in message and "4242" in message
    assert "--stop-holders" in message and "НЕ ТРОНУТА" in message
    # Главное: старая установка на месте и работоспособна.
    assert (fake_site / "xbsl" / "__init__.py").read_text(encoding="utf-8").strip() == '__version__ = "0.0.1"'
    assert (fake_site / "xbsl-0.0.1.dist-info").exists()


def test_unknown_holders_still_produce_an_honest_message(fake_site, monkeypatch):
    """Имён может не быть - тогда так и сказано, а не молчание."""
    _stub_download(monkeypatch)
    monkeypatch.setattr(selfupdate.Path, "rename",
                        lambda self, target: (_ for _ in ()).throw(OSError("занято")))
    monkeypatch.setattr(selfupdate, "holders", list)
    with pytest.raises(selfupdate.SelfUpdateError, match="определить держателей не удалось"):
        selfupdate.self_update(log=lambda *a: None)


def test_broken_archive_rolls_back(fake_site, monkeypatch):
    _stub_download(monkeypatch, payload=b"not a zip archive")
    with pytest.raises(selfupdate.SelfUpdateError, match="возвращена на место"):
        selfupdate.self_update(log=lambda *a: None)
    assert (fake_site / "xbsl" / "__init__.py").read_text(encoding="utf-8").strip() == '__version__ = "0.0.1"'
    assert not list(fake_site.glob("*" + selfupdate._BACKUP_SUFFIX))


def test_install_that_does_not_import_rolls_back(fake_site, monkeypatch):
    """Проверка идёт ОТДЕЛЬНЫМ процессом: текущий держит старый код в памяти."""
    _stub_download(monkeypatch)
    monkeypatch.setattr(selfupdate, "verify_install", lambda site, expected: "")
    with pytest.raises(selfupdate.SelfUpdateError, match="не импортируется"):
        selfupdate.self_update(log=lambda *a: None)
    assert (fake_site / "xbsl" / "__init__.py").read_text(encoding="utf-8").strip() == '__version__ = "0.0.1"'


def test_successful_update_leaves_no_backup(fake_site, monkeypatch):
    _stub_download(monkeypatch)
    selfupdate.self_update(log=lambda *a: None)
    assert not list(fake_site.glob("*" + selfupdate._BACKUP_SUFFIX))


# -- нативная установка обновляется нативным колесом ----------------------------------------


WHEELS = [
    {"filename": "xbsl-0.45.0-py3-none-any.whl", "url": "http://pypi/pure.whl"},
    {"filename": "xbsl-0.45.0-cp314-cp314-win_amd64.whl", "url": "http://pypi/win.whl"},
    {"filename": "xbsl-0.45.0-cp313-cp313-win_amd64.whl", "url": "http://pypi/win313.whl"},
    {"filename": "xbsl-0.45.0-cp314-cp314-manylinux_2_17_x86_64.whl", "url": "http://pypi/linux.whl"},
]


def test_the_wheel_of_this_platform_is_preferred(monkeypatch):
    """Переносимое колесо поверх нативной установки молча съело бы скорость разбора."""
    monkeypatch.setattr(selfupdate, "platform_tags", lambda: ("cp314", ("win_amd64",)))
    assert selfupdate._pick_wheel(WHEELS) == ("http://pypi/win.whl", selfupdate.NATIVE)
    monkeypatch.setattr(selfupdate, "platform_tags", lambda: ("cp314", ("linux", "x86_64")))
    assert selfupdate._pick_wheel(WHEELS)[0] == "http://pypi/linux.whl"


def test_portable_install_is_healed_with_the_native_wheel(fake_site, monkeypatch):
    """Install-kind selection was a ratchet: one portable update made it permanent.

    Found in release 0.53.0: an installation made portable during the cache_tag defect updated
    with a portable wheel while a native wheel was available, without any notice. The platform
    selects the wheel; the previous install kind only controls the message.
    """
    monkeypatch.setattr(selfupdate, "platform_tags", lambda: ("cp314", ("win_amd64",)))
    url, kind = selfupdate._pick_wheel(WHEELS)
    assert (url, kind) == ("http://pypi/win.whl", selfupdate.NATIVE)

    # Сквозной контроль сообщения: установка в fake_site переносимая (без .pyd), колесо
    # нативное - об исцелении говорится вслух.
    monkeypatch.setattr(selfupdate, "_wheel_url",
                        lambda v: ("http://pypi/xbsl.whl", "9.9.9", selfupdate.NATIVE))
    monkeypatch.setattr(
        selfupdate.urllib.request, "urlopen", lambda url, timeout=0: _FakeResp(_fake_wheel("9.9.9"))
    )
    messages = []
    selfupdate.self_update(log=messages.append)
    from xbsl import i18n
    assert i18n.t("selfupdate.native-restored") in messages


def test_platform_without_a_native_wheel_falls_back(monkeypatch):
    """Отрицательный контроль: чужая платформа - переносимое колесо, и об этом говорят."""
    monkeypatch.setattr(selfupdate, "platform_tags", lambda: ("cp312", ("macosx", "arm64")))
    assert selfupdate._pick_wheel(WHEELS) == ("http://pypi/pure.whl", selfupdate.PORTABLE)


def test_native_install_is_recognized_by_compiled_modules(tmp_path):
    site = tmp_path / "site-packages"
    (site / "xbsl").mkdir(parents=True)
    assert selfupdate.is_native(site) is False
    (site / "xbsl" / "lexer.cp314-win_amd64.pyd").write_bytes(b"")
    assert selfupdate.is_native(site) is True


# -- держатели ------------------------------------------------------------------------------


def test_holders_are_our_own_processes_only(monkeypatch):
    """Getting this wrong means offering to kill somebody else's process.

    Caught on a live run: the agent client mentions xbsl in its arguments (the project
    path, the baseline file) and used to land in the list of holders.
    """
    monkeypatch.setattr(
        selfupdate, "_process_listing",
        lambda: [
            (11, 1, "xbsl-lsp.exe", "xbsl-lsp --project-root app"),
            (12, 1, "python.exe", "python.exe -m xbsl.mcp_server"),
            (13, 1, "python.exe", "python.exe -m http.server"),
            (14, 1, "claude.exe", "claude.exe --baseline /repo/.xbsllint-baseline"),
            (15, 1, "Code.exe", "Code.exe --folder-uri file:///d:/repo/xbsl"),
        ],
    )
    monkeypatch.setitem(__import__("sys").modules, "psutil", None)
    found = {item["pid"] for item in selfupdate.holders()}
    assert found == {11, 12}


def test_holders_exclude_own_process_tree(monkeypatch):
    """The command wrapper and its process tree are not holders.

    A live 28 July failure: `--stop-holders` stopped its own parent `xbsl.exe`, aborted the
    update, and left the old version. Own processes are ancestors (the wrapper and what started
    it) and descendants; a foreign process with the same name remains a holder.
    """
    own = os.getpid()
    monkeypatch.setattr(
        selfupdate, "_process_listing",
        lambda: [
            (70, 1, "explorer.exe", "explorer.exe"),      # предок-не-держатель
            (77, 70, "xbsl.exe", "xbsl self-update"),     # наша обёртка
            (own, 77, "python.exe", "python -m xbsl self-update"),
            (88, own, "xbsl-lsp.exe", "xbsl-lsp child"),  # наш потомок
            (11, 1, "xbsl-lsp.exe", "xbsl-lsp --project-root app"),  # чужой LSP
        ],
    )
    monkeypatch.setitem(__import__("sys").modules, "psutil", None)
    assert {item["pid"] for item in selfupdate.holders()} == {11}


def test_family_pids_survives_a_parent_loop():
    """Кольцо в ppid (битый листинг или переиспользованный pid) не должно зациклить обход."""
    own = os.getpid()
    rows = [
        (own, 50, "python.exe", "python -m xbsl self-update"),
        (50, 51, "xbsl.exe", "xbsl self-update"),
        (51, 50, "cmd.exe", "cmd"),  # кольцо 50 <-> 51
    ]
    assert selfupdate._family_pids(rows) == {own, 50, 51}


# -- корневые нативные модули mypyc ---------------------------------------------------------
#
# mypyc puts its shared library beside the package, at the site-packages root, with a name
# shared across versions. A live 28 July failure overwrote it in place and raised Errno 13:
# the self-update process imports the file. Renaming an occupied module works; overwriting does
# not. Own root files come from RECORD, since a bare glob would catch another package's library.

_MYPYC = "0155c65d__mypyc.cp314-win_amd64.pyd"


def _native_site(fake_site):
    """Дополнить fake_site корневой mypyc-библиотекой, её RECORD и ЧУЖИМ соседом."""
    (fake_site / _MYPYC).write_bytes(b"old native payload")
    (fake_site / "xbsl-0.0.1.dist-info" / "RECORD").write_text(
        f"{_MYPYC},sha256=abc,18\n"
        "xbsl/__init__.py,sha256=def,25\n"
        "xbsl/lexer.cp314-win_amd64.pyd,sha256=ghi,10\n",
        encoding="utf-8",
    )
    foreign = fake_site / "ada92cb5__mypyc.cp314-win_amd64.pyd"
    foreign.write_bytes(b"another distribution's library")
    return foreign


def test_root_native_modules_come_from_record(fake_site):
    _native_site(fake_site)
    assert selfupdate._native_root_modules(fake_site) == [fake_site / _MYPYC]


def test_update_replaces_the_root_native_module_and_spares_the_foreign_one(fake_site, monkeypatch):
    foreign = _native_site(fake_site)
    wheel = io.BytesIO()
    with zipfile.ZipFile(wheel, "w") as archive:
        archive.writestr("xbsl/__init__.py", '__version__ = "9.9.9"\n')
        archive.writestr("xbsllint/__init__.py", "import xbsl\n")
        archive.writestr(_MYPYC, "new native payload")  # то же имя - тот самый случай перезаписи
        archive.writestr(f"xbsl-9.9.9.dist-info/RECORD", f"{_MYPYC},sha256=new,18\n")
    _stub_download(monkeypatch, payload=wheel.getvalue())

    selfupdate.self_update(log=lambda *a: None)

    assert (fake_site / _MYPYC).read_bytes() == b"new native payload"
    assert foreign.read_bytes() == b"another distribution's library"
    assert not list(fake_site.glob("*" + selfupdate._BACKUP_SUFFIX))


def test_busy_root_native_module_rolls_back_whole(fake_site, monkeypatch):
    """Отказ на корневом модуле возвращает на место ВСЁ уже отложенное."""
    _native_site(fake_site)
    _stub_download(monkeypatch)
    original = selfupdate.Path.rename

    def refuse(self, target):
        if "__mypyc" in self.name and not self.name.endswith(selfupdate._BACKUP_SUFFIX):
            raise OSError(13, "Файл занят другим процессом")
        return original(self, target)

    monkeypatch.setattr(selfupdate.Path, "rename", refuse)
    monkeypatch.setattr(selfupdate, "holders", list)

    with pytest.raises(selfupdate.SelfUpdateError):
        selfupdate.self_update(log=lambda *a: None)

    assert (fake_site / _MYPYC).read_bytes() == b"old native payload"
    assert (fake_site / "xbsl" / "__init__.py").read_text(encoding="utf-8").strip() == '__version__ = "0.0.1"'


def test_stale_file_backup_is_swept_by_the_next_run(fake_site, monkeypatch):
    """A backup file held by the updating process itself is not removed right away.

    A loaded module cannot be deleted, only renamed - so _drop_backups leaves it behind
    and the next run sweeps it up.
    """
    stale = fake_site / (_MYPYC + selfupdate._BACKUP_SUFFIX)
    stale.write_bytes(b"held by the previous run")
    _stub_download(monkeypatch)

    selfupdate.self_update(log=lambda *a: None)

    assert not stale.exists()


def test_a_held_leftover_backup_does_not_block_the_next_update(fake_site, monkeypatch):
    """A backup left by the previous run may still be loaded by a live server.

    Windows lets such a file be renamed but not deleted, so the leftover keeps the backup
    name. The update then has to put the current files aside under another name instead of
    failing on the taken one and blaming a busy installation.
    """
    _native_site(fake_site)
    held_dir = fake_site / ("xbsl" + selfupdate._BACKUP_SUFFIX)
    held_dir.mkdir()
    (held_dir / "lexer.cp314-win_amd64.pyd").write_bytes(b"loaded by a live server")
    held_file = fake_site / (_MYPYC + selfupdate._BACKUP_SUFFIX)
    held_file.write_bytes(b"loaded by a live server")
    held = {held_dir, held_file}
    remove = selfupdate._remove_any
    monkeypatch.setattr(selfupdate, "_remove_any", lambda path: None if path in held else remove(path))
    rename = selfupdate.Path.rename

    def rename_like_windows(self, target):
        # Windows refuses to rename onto an existing name (WinError 183); POSIX replaces it.
        if os.path.lexists(target):
            raise FileExistsError(183, "Cannot create a file when that file already exists", str(target))
        return rename(self, target)

    monkeypatch.setattr(selfupdate.Path, "rename", rename_like_windows)
    monkeypatch.setattr(selfupdate, "holders", list)
    _stub_download(monkeypatch)

    _old, new = selfupdate.self_update(log=lambda *a: None)

    assert new == "9.9.9"
    assert (fake_site / "xbsl" / "__init__.py").read_text(encoding="utf-8").strip() == '__version__ = "9.9.9"'
    leftovers = sorted(path.name for path in fake_site.glob("*" + selfupdate._BACKUP_SUFFIX))
    assert leftovers == sorted([held_dir.name, held_file.name])


# -- the file list comes from the simple index ---------------------------------------------
#
# Caught live on 31.07.2026: right after a release `self-update --version 0.51.0` answered
# "no suitable wheel" while the wheel was already served by the index - the JSON metadata
# catches up minutes later, and naming the version did not help because the files were read
# from that same lagging document.


def _simple_payload(*names: str, yanked: tuple[str, ...] = ()) -> bytes:
    """A PEP 691 answer of the simple index for the given file names."""
    return json.dumps({
        "meta": {"api-version": "1.1"},
        "files": [
            {"filename": name, "url": f"http://pypi/{name}", "yanked": name in yanked}
            for name in names
        ],
    }).encode("utf-8")


def _serve(monkeypatch, index: bytes | None, meta: dict | None = None,
           missing: bool = False) -> list[str]:
    """Answer the index and the JSON metadata separately; returns the list of asked urls.

    `missing` makes the JSON metadata answer 404, as PyPI does for an unknown version.
    """
    asked: list[str] = []

    def urlopen(target, timeout=0):
        url = getattr(target, "full_url", target)
        asked.append(url)
        if url == selfupdate.PYPI_SIMPLE:
            accept = getattr(target, "headers", {}).get("Accept")
            assert accept == selfupdate.SIMPLE_ACCEPT, "without the header the index answers HTML"
            if index is None:
                raise OSError("index unreachable")
            return _FakeResp(index)
        if missing:
            raise selfupdate.urllib.error.HTTPError(url, 404, "Not Found", {}, None)
        assert meta is not None, "the JSON metadata must not be asked at all"
        return _FakeResp(json.dumps(meta).encode("utf-8"))

    monkeypatch.setattr(selfupdate.urllib.request, "urlopen", urlopen)
    return asked


def test_wheel_url_reads_the_simple_index(monkeypatch):
    monkeypatch.setattr(selfupdate, "platform_tags", lambda: ("cp314", ("win_amd64",)))
    asked = _serve(monkeypatch, _simple_payload(
        "xbsl-0.50.0-py3-none-any.whl",
        "xbsl-0.51.0-py3-none-any.whl",
        "xbsl-0.51.0-cp314-cp314-win_amd64.whl",
        "xbsl-0.51.0.tar.gz",
    ))

    url, version, kind = selfupdate._wheel_url(None)

    assert (version, kind) == ("0.51.0", selfupdate.NATIVE)
    assert url.endswith("cp314-cp314-win_amd64.whl")
    assert asked == [selfupdate.PYPI_SIMPLE]


def test_a_fresh_release_is_installable_while_the_json_still_lags(monkeypatch):
    """The live failure: the index already serves 0.51.0, the JSON still says 0.50.0."""
    lagging = {"info": {"version": "0.50.0"},
               "urls": [{"filename": "xbsl-0.50.0-py3-none-any.whl", "url": "http://pypi/old.whl"}]}
    asked = _serve(monkeypatch, _simple_payload("xbsl-0.51.0-py3-none-any.whl"), meta=lagging)

    url, version, _kind = selfupdate._wheel_url("0.51.0")

    assert version == "0.51.0" and url.endswith("xbsl-0.51.0-py3-none-any.whl")
    assert asked == [selfupdate.PYPI_SIMPLE]


def test_yanked_and_pre_release_files_never_win_the_latest_race(monkeypatch):
    _serve(monkeypatch, _simple_payload(
        "xbsl-0.50.0-py3-none-any.whl",
        "xbsl-0.51.0-py3-none-any.whl",
        "xbsl-0.52.0rc1-py3-none-any.whl",
        yanked=("xbsl-0.51.0-py3-none-any.whl",),
    ))
    assert selfupdate._wheel_url(None)[1] == "0.50.0"


def test_release_ranking_is_numeric_not_lexicographic():
    files = [{"filename": f"xbsl-{v}-py3-none-any.whl", "version": v}
             for v in ("0.9.0", "0.51.0", "0.51.0.post1")]
    assert selfupdate._latest_release(files) == "0.51.0.post1"
    assert selfupdate._release_key("0.52.0rc1") is None
    assert selfupdate._version_of("xbsl-0.51.0.tar.gz") == "0.51.0"


def test_an_index_without_pep691_falls_back_to_the_json(monkeypatch):
    """A mirror that answers HTML (or is unreachable) must not break the update."""
    meta = {"info": {"version": "0.50.0"},
            "urls": [{"filename": "xbsl-0.50.0-py3-none-any.whl", "url": "http://pypi/pure.whl"}]}
    asked = _serve(monkeypatch, None, meta=meta)

    url, version, kind = selfupdate._wheel_url(None)

    assert (url, version, kind) == ("http://pypi/pure.whl", "0.50.0", selfupdate.PORTABLE)
    assert asked == [selfupdate.PYPI_SIMPLE, selfupdate.PYPI_LATEST]


def test_a_version_missing_from_a_lagging_index_comes_from_its_page(monkeypatch):
    """The live failure of 23.09.2026: the index still served the previous release for half
    an hour, while the version page already listed the new files."""
    monkeypatch.setattr(selfupdate, "platform_tags", lambda: ("cp314", ("win_amd64",)))
    page = {"info": {"version": "0.52.0"},
            "urls": [{"filename": "xbsl-0.52.0-py3-none-any.whl", "url": "http://pypi/pure.whl"},
                     {"filename": "xbsl-0.52.0-cp314-cp314-win_amd64.whl",
                      "url": "http://pypi/native.whl"}]}
    asked = _serve(monkeypatch, _simple_payload("xbsl-0.51.0-py3-none-any.whl"), meta=page)

    url, version, kind = selfupdate._wheel_url("0.52.0")

    assert (url, version, kind) == ("http://pypi/native.whl", "0.52.0", selfupdate.NATIVE)
    assert asked == [selfupdate.PYPI_SIMPLE, selfupdate.PYPI_VERSION.format(version="0.52.0")]


def test_a_version_missing_everywhere_is_named_as_such(monkeypatch):
    """Only a 404 of the version page means the version does not exist."""
    asked = _serve(monkeypatch, _simple_payload("xbsl-0.51.0-py3-none-any.whl"), missing=True)
    with pytest.raises(selfupdate.SelfUpdateError, match="версия не найдена"):
        selfupdate._wheel_url("9.9.9")
    assert asked == [selfupdate.PYPI_SIMPLE, selfupdate.PYPI_VERSION.format(version="9.9.9")]


def test_interpreter_tag_is_the_wheel_spelling():
    """cache_tag пишет тот же интерпретатор как cpython-314 - колёс с таким именем нет."""
    interpreter, keywords = selfupdate.platform_tags()
    assert interpreter.startswith(("cp", "pp")) and interpreter[2:].isdigit()
    assert "-" not in interpreter and keywords


def test_stop_holders_reports_what_it_ended(monkeypatch):
    calls = []
    monkeypatch.setattr(selfupdate.subprocess, "run",
                        lambda *a, **k: calls.append(a[0]) or None)
    monkeypatch.setattr(selfupdate.os, "kill", lambda pid, sig: calls.append(("kill", pid)))
    said = []
    alive = selfupdate.stop_holders([{"pid": 11, "name": "xbsl-lsp.exe"}], said.append)
    assert alive == [] and calls and "11" in said[0]


def test_every_message_is_translated(monkeypatch, fake_site, capsys):
    """A public package must answer in English for `--lang en`.

    The test checks output rather than key presence: the held-install refusal and completion
    line are the command's longest texts, and both are assembled from several keys.
    """
    from xbsl import i18n

    i18n.set_lang("en")
    try:
        message = selfupdate._holders_message([{"pid": 7, "name": "xbsl-lsp.exe"}])
        assert "holding the installation" in message and "держ" not in message
        assert "could not tell" in selfupdate._holders_message([])
        _stub_download(monkeypatch)
        said = []
        selfupdate.self_update(log=said.append)
        text = " ".join(said)
        assert "extracting into" in text and "done: xbsl" in text
        assert not any("а" <= ch <= "я" for ch in text), "в английском выводе кириллица"
    finally:
        i18n.set_lang("ru")
