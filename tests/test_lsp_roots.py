"""The LSP server and the open documents its whole-project pass never reads.

The pass reads the files under the source root and the translation dictionary that serves it,
then publishes its findings over every document that had any. A module opened outside the root -
a copy of the sources under `examples/`, a file from another checkout - gets the file findings on
open, and the pass used to publish an empty list over it: the findings were gone after the first
save of any file. What the pass did not read, it must leave alone while the document is open, and
clear once the document is closed, since nothing refreshes those findings after that.
"""

import threading
from pathlib import Path
from types import SimpleNamespace

import pytest

from xbsl import lsp

TRAILING = "whitespace/trailing"

#: A module with trailing spaces: `whitespace/trailing` needs no Element data, so the tests run
#: in a public clone too.
MODULE_WITH_FINDING = "@НаСервере\nметод ПересчитатьОстатки()   \n    возврат\n;\n"
CLEAN_MODULE = "@НаСервере\nметод ПересчитатьОстатки()\n    возврат\n;\n"


class _RightAway:
    """A timer or a thread that runs its function on `start()`: the debounce made synchronous."""

    def __init__(self, *args, target=None, **kwargs):
        self.function = target if target is not None else args[1]
        self.daemon = kwargs.get("daemon", False)

    def start(self):
        self.function()

    def cancel(self):
        pass


class _Deferred:
    """A timer that runs only when the test fires it, and never after `cancel()`."""

    started: list["_Deferred"] = []

    def __init__(self, _interval, function):
        self.function = function
        self.daemon = False
        self.cancelled = False

    def start(self):
        _Deferred.started.append(self)

    def cancel(self):
        self.cancelled = True

    @classmethod
    def fire_all(cls):
        pending, cls.started = cls.started, []
        for timer in pending:
            if not timer.cancelled:
                timer.function()


@pytest.fixture
def editor(tmp_path, monkeypatch):
    """A server over tmp_path driven the way the editor drives it, with its publications kept.

    `published` holds the rule ids each document got last, by the canonical key of its path; a
    document nothing was published for has no entry. The debounce runs synchronously, and the
    state singleton is given back as it was found.
    """
    pytest.importorskip("pygls", reason="the LSP handlers need the [lsp] extra")
    from pygls import uris
    from pygls.workspace import Workspace

    saved = dict(vars(lsp.STATE))
    lsp.STATE.__init__()
    lsp.STATE.select = {TRAILING}
    fake_threading = SimpleNamespace(Timer=_RightAway, Thread=_RightAway, Lock=threading.Lock)
    monkeypatch.setattr(lsp, "threading", fake_threading)
    server = lsp._make_server()
    server.lsp._workspace = Workspace(uris.from_fs_path(str(tmp_path)))
    fm = getattr(server.lsp, "fm", None) or getattr(server.lsp, "_features", None)
    features = getattr(fm, "features", fm)

    def key(path):
        return lsp._doc_key(Path(path), "")

    published: dict[str, list[str]] = {}

    def publish(uri, diagnostics=None, *args, **kwargs):
        published[key(uris.to_fs_path(uri))] = sorted({d.code for d in diagnostics or []})

    monkeypatch.setattr(server, "publish_diagnostics", publish)
    monkeypatch.setattr(server, "show_message_log", lambda *args, **kwargs: None)

    def uri(path):
        return uris.from_fs_path(str(path))

    def notify(feature, path):
        features[feature](SimpleNamespace(text_document=SimpleNamespace(uri=uri(path))))

    def put(path, text, version):
        server.workspace.put_text_document(lsp.lsp.TextDocumentItem(
            uri=uri(path), language_id="xbsl", version=version, text=text,
        ))

    def open_document(path):
        put(path, path.read_text(encoding="utf-8"), 1)
        notify(lsp.lsp.TEXT_DOCUMENT_DID_OPEN, path)

    def change(path, text):
        # the whole text at once: what the buffer holds matters here, not the incremental sync
        put(path, text, 2)
        notify(lsp.lsp.TEXT_DOCUMENT_DID_CHANGE, path)

    def save(path, text=None):
        if text is not None:
            path.write_text(text, encoding="utf-8")
        notify(lsp.lsp.TEXT_DOCUMENT_DID_SAVE, path)

    def close(path):
        # pygls drops the document from its workspace before the handler of the notification runs
        server.workspace.remove_text_document(uri(path))
        notify(lsp.lsp.TEXT_DOCUMENT_DID_CLOSE, path)

    def narrow(root):
        # what `--project-root` leaves behind once the workspace folder is known
        lsp.STATE.root = root
        lsp.STATE.project_root_arg = str(root)

    def defer_timers():
        _Deferred.started = []
        monkeypatch.setattr(lsp, "threading", SimpleNamespace(
            Timer=_Deferred, Thread=_RightAway, Lock=threading.Lock,
        ))

    try:
        yield SimpleNamespace(
            key=key, published=published, narrow=narrow, open=open_document, change=change,
            save=save, close=close, relint=lambda: features["xbsl/relint"](None),
            defer_timers=defer_timers,
        )
    finally:
        vars(lsp.STATE).clear()
        vars(lsp.STATE).update(saved)


def _layout(tmp_path):
    """A checkout the editor opens: the project under `src`, a copy of a module under `examples`."""
    root = tmp_path / "src" / "проект"
    root.mkdir(parents=True)
    inside = root / "Склады.xbsl"
    inside.write_text(CLEAN_MODULE, encoding="utf-8")
    copies = tmp_path / "examples" / "проект"
    copies.mkdir(parents=True)
    outside = copies / "Склады.xbsl"
    outside.write_text(MODULE_WITH_FINDING, encoding="utf-8")
    return root, inside, outside


def test_a_module_outside_a_narrowed_root_keeps_its_findings_after_a_save(tmp_path, editor):
    root, inside, outside = _layout(tmp_path)
    editor.narrow(root)
    editor.open(outside)
    assert editor.published[editor.key(outside)] == [TRAILING]

    editor.save(inside)  # a save of any file starts the whole-project pass

    assert editor.published[editor.key(outside)] == [TRAILING]


def test_a_module_outside_the_workspace_folder_keeps_its_findings_after_a_save(tmp_path, editor):
    """Without `--project-root` the pass reads the workspace folder, and a module opened from
    anywhere else was wiped the same way."""
    folder = tmp_path / "папка"
    folder.mkdir()
    (folder / "Партии.xbsl").write_text(CLEAN_MODULE, encoding="utf-8")
    elsewhere = tmp_path / "Склады.xbsl"
    elsewhere.write_text(MODULE_WITH_FINDING, encoding="utf-8")
    lsp.STATE.root = folder
    editor.open(elsewhere)

    editor.relint()

    assert editor.published[editor.key(elsewhere)] == [TRAILING]


def test_the_findings_of_a_module_outside_the_root_follow_its_edits(tmp_path, editor):
    """The kept list is the live one: the pass neither brings back a fixed finding nor drops a new one."""
    root, inside, outside = _layout(tmp_path)
    editor.narrow(root)
    editor.open(outside)

    editor.change(outside, CLEAN_MODULE)
    editor.save(outside, CLEAN_MODULE)
    assert editor.published[editor.key(outside)] == []

    editor.change(outside, MODULE_WITH_FINDING)
    editor.save(outside, MODULE_WITH_FINDING)
    assert editor.published[editor.key(outside)] == [TRAILING]


def test_the_pass_still_answers_for_an_open_module_it_reads(tmp_path, editor):
    """Control on the other side: a document under the root is the pass's to answer for, open or not.

    The file is fixed on disk behind the editor's back, by a checkout say, so the per-file check
    never sees the fixed text and only the pass can clear the finding.
    """
    root, inside, _outside = _layout(tmp_path)
    inside.write_text(MODULE_WITH_FINDING, encoding="utf-8")
    editor.narrow(root)
    editor.open(inside)
    editor.relint()
    assert editor.published[editor.key(inside)] == [TRAILING]

    inside.write_text(CLEAN_MODULE, encoding="utf-8")
    editor.relint()

    assert editor.published[editor.key(inside)] == []


def test_closing_a_module_the_pass_does_not_read_clears_its_findings(tmp_path, editor):
    """Nothing refreshes the findings of a closed document the project does not own."""
    root, inside, outside = _layout(tmp_path)
    editor.narrow(root)
    editor.open(outside)
    editor.relint()
    assert editor.published[editor.key(outside)] == [TRAILING]

    editor.close(outside)

    assert editor.published[editor.key(outside)] == []
    editor.relint()
    assert editor.published[editor.key(outside)] == []


def test_a_module_closed_before_the_first_pass_is_cleared_by_that_pass(tmp_path, editor):
    """Before the first pass the server cannot tell what it will read, so the pass clears the rest."""
    root, inside, outside = _layout(tmp_path)
    editor.narrow(root)
    editor.open(outside)
    editor.close(outside)
    assert editor.published[editor.key(outside)] == [TRAILING]

    editor.relint()

    assert editor.published[editor.key(outside)] == []


def test_closing_a_module_under_the_root_keeps_the_findings_of_the_pass(tmp_path, editor):
    """The file is still part of the project: its findings stay in the Problems panel."""
    root, inside, _outside = _layout(tmp_path)
    inside.write_text(MODULE_WITH_FINDING, encoding="utf-8")
    editor.narrow(root)
    editor.open(inside)
    editor.relint()

    editor.close(inside)
    editor.relint()

    assert editor.published[editor.key(inside)] == [TRAILING]


def test_the_cli_mode_of_the_editor_finds_the_dictionary_by_the_names_the_engine_discovers():
    """Without the server the extension finds the dictionary itself, walking up from the root the
    way `dictionary.discover` does: its copy of the two names must not drift from the engine's."""
    from xbsl.translation import dictionary

    extension = Path(__file__).resolve().parent.parent / "editors" / "vscode"
    text = (extension / "src" / "workspaceCore.ts").read_text(encoding="utf-8")

    assert f'export const DICTIONARY_DIR = "{dictionary.DICTIONARY_DIR}";' in text
    assert f'export const DICTIONARY_FILE = "{dictionary.DICTIONARY_FILE}";' in text


def test_closing_a_module_cancels_its_pending_check(tmp_path, editor):
    """A check still waiting out the typing pause would publish findings for a closed document."""
    root, inside, outside = _layout(tmp_path)
    editor.narrow(root)
    editor.defer_timers()
    editor.open(outside)

    editor.close(outside)
    _Deferred.fire_all()

    assert editor.key(outside) not in editor.published or editor.published[editor.key(outside)] == []
