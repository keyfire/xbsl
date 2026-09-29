"""The supervisor keeps the client's MCP session while the server behind it is replaced.

A server whose engine was replaced on disk refuses its tools and asks for a restart, and only
the client can restart it - a client such as Codex never does. `xbsl-mcp-supervisor` owns the
client's stdio, runs the server as a worker process and, when the worker refuses over a replaced
engine, starts a new one, replays the handshake to it and sends it the same request: the client
gets the answer of the new code instead of the refusal (xbsl/mcp_supervisor.py).

Most tests run the supervisor as the client does - a process of its own spoken to over pipes -
in front of a fake worker: a small script that answers line by line, reads the version and the
"code files" it loaded from files at start and refuses a call when a file says otherwise, as the
engine does. The last tests run the real server behind it, on a copy of the package whose
version is bumped, or one of whose modules is replaced, under the running worker. No Element
data and no plugins are needed.
"""

from __future__ import annotations

import json
import os
import queue
import shutil
import subprocess
import sys
import threading
import time
import types
from pathlib import Path

import pytest

from xbsl import cli, i18n, mcp_supervisor, mcpjournal, selfupdate

ROOT = Path(__file__).resolve().parents[1]
#: How long a test waits for one line of the supervisor: generous, the machine may be busy.
WAIT = 60.0
PROTOCOL = "2025-06-18"
CLIENT_PARAMS = {"protocolVersion": PROTOCOL, "capabilities": {"roots": {}},
                 "clientInfo": {"name": "test-client", "version": "1.0"}}

#: The fake server. It notes every message it receives into a log, answers `initialize`, refuses
#: requests before `notifications/initialized` the way the MCP SDK does, and runs each tool call
#: in a thread of its own, so that a slow call does not hold the others.
FAKE_WORKER = r'''
import json, os, sys, threading, time

VERSION = os.environ["FAKE_VERSION"]
SOURCES = os.environ["FAKE_SOURCES"]
PROTOCOL = os.environ["FAKE_PROTOCOL"]
LOG = os.environ["FAKE_LOG"]
lock = threading.Lock()


def read(path, default=""):
    try:
        with open(path, encoding="utf-8") as handle:
            return handle.read().strip()
    except FileNotFoundError:
        return default


def disk():
    return read(VERSION)


LOADED = disk()
#: The "code files" as they were at start: a change under the same version is refused too.
STARTED = read(SOURCES)


def note(entry):
    with lock:
        with open(LOG, "a", encoding="utf-8") as handle:
            handle.write(json.dumps({"pid": os.getpid(), "loaded": LOADED, **entry}) + "\n")


def say(message):
    with lock:
        sys.stdout.write(json.dumps(message) + "\n")
        sys.stdout.flush()


def result(request_id, payload):
    say({"jsonrpc": "2.0", "id": request_id,
         "result": {"content": [{"type": "text", "text": json.dumps(payload)}], "isError": False}})


def call(request_id, name, arguments):
    on_disk, sources = disk(), read(SOURCES)
    if on_disk != LOADED:
        stale = {"reason": "version", "loaded": LOADED, "on_disk": on_disk}
    elif sources != STARTED:
        stale = {"reason": "sources", "loaded": LOADED, "on_disk": LOADED, "fingerprint": sources}
    else:
        stale = None
    if name == "exit":
        os._exit(3)
    if name == "version_info":
        payload = {"engine": LOADED, "pid": os.getpid()}
        if stale:
            payload["stale"] = stale
        return result(request_id, payload)
    if stale and name != "write":
        return result(request_id, {"error": "refused", "stale": {**stale, "ran": False}})
    note({"ran": name})
    if name == "sleep":
        time.sleep(arguments["seconds"])
    if stale:
        return result(request_id, {"error": "failed on a mix", "stale": {**stale, "ran": True}})
    result(request_id, {"pid": os.getpid(), "engine": LOADED, "name": name,
                        "arguments": arguments})


initialized = False
for raw in sys.stdin:
    message = json.loads(raw)
    method = message.get("method")
    note({"method": method, "id": message.get("id"), "params": message.get("params")})
    if method == "initialize":
        # The version asked for, unless the test says this server agrees on another one.
        say({"jsonrpc": "2.0", "id": message["id"], "result": {
            "protocolVersion": read(PROTOCOL, message["params"]["protocolVersion"]),
            "capabilities": {"tools": {"listChanged": False}},
            "serverInfo": {"name": "fake", "version": LOADED}}})
    elif method == "notifications/initialized":
        initialized = True
    elif "id" in message and not initialized:
        say({"jsonrpc": "2.0", "id": message["id"], "error": {
            "code": -32602, "message": "Received request before initialization was complete"}})
    elif method == "tools/call":
        params = message["params"]
        threading.Thread(target=call, args=(message["id"], params["name"],
                                             params.get("arguments") or {})).start()
    elif method == "resources/list":
        os._exit(4)  # a request that only reads, and yet ends every worker it reaches
    elif "id" in message:
        say({"jsonrpc": "2.0", "id": message["id"], "result": {"engine": LOADED}})
note({"end": True})
'''


class Session:
    """The supervisor in a process of its own, spoken to the way an MCP client speaks."""

    def __init__(self, command: list[str], *, env: dict, cwd: Path, stderr: Path) -> None:
        self.stderr = stderr.open("wb")
        self.process = subprocess.Popen(
            command, cwd=cwd, env=env, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=self.stderr,
        )
        self.lines: queue.Queue = queue.Queue()
        #: What came besides the answers asked for: notifications, requests of the server.
        self.other: list[dict] = []
        threading.Thread(target=self._pump, daemon=True).start()

    def _pump(self) -> None:
        for line in iter(self.process.stdout.readline, b""):
            self.lines.put(line)
        self.lines.put(None)

    def send(self, message: dict) -> None:
        self.process.stdin.write((json.dumps(message) + "\n").encode("utf-8"))
        self.process.stdin.flush()

    def receive(self, timeout: float = WAIT) -> dict | None:
        line = self.lines.get(timeout=timeout)
        return None if line is None else json.loads(line)

    def answer(self, request_id, timeout: float = WAIT) -> dict:
        """The answer with this id; everything else that comes first is kept in `other`."""
        while True:
            message = self.receive(timeout)
            assert message is not None, "the supervisor ended before the answer"
            if message.get("id") == request_id and "method" not in message:
                return message
            self.other.append(message)

    def request(self, request_id, method: str, params: dict | None = None) -> dict:
        self.send({"jsonrpc": "2.0", "id": request_id, "method": method,
                   **({"params": params} if params is not None else {})})
        return self.answer(request_id)

    def initialize(self) -> dict:
        answer = self.request(0, "initialize", CLIENT_PARAMS)
        self.send({"jsonrpc": "2.0", "method": "notifications/initialized"})
        return answer

    def call(self, request_id, name: str, arguments: dict | None = None) -> dict:
        return self.request(request_id, "tools/call", {"name": name, "arguments": arguments or {}})

    def close(self, timeout: float = WAIT) -> int:
        """Close the client's end, as a client does on shutdown; the supervisor's exit code."""
        self.process.stdin.close()
        try:
            return self.process.wait(timeout=timeout)
        finally:
            self.stderr.close()


def payload(answer: dict) -> dict:
    """The object a tool answered with: the JSON of its first text part."""
    return json.loads(answer["result"]["content"][0]["text"])


class Fake:
    """The fake worker's files: the version and the "code files" on disk, the protocol version
    a new worker agrees on (absent: the one asked for), the log of what it heard."""

    def __init__(self, tmp_path: Path) -> None:
        self.folder = tmp_path
        self.script = tmp_path / "fake_worker.py"
        self.script.write_text(FAKE_WORKER, encoding="utf-8")
        self.version = tmp_path / "version.txt"
        self.version.write_text("1.0.0", encoding="utf-8")
        self.sources = tmp_path / "sources.txt"
        self.sources.write_text("start", encoding="utf-8")
        self.protocol = tmp_path / "protocol.txt"
        self.log = tmp_path / "fake-log.jsonl"
        self.sessions: list[Session] = []

    def bump(self, version: str) -> None:
        self.version.write_text(version, encoding="utf-8")

    def pull(self, sources: str) -> None:
        """The code files change, the version stays: a pull between two releases."""
        self.sources.write_text(sources, encoding="utf-8")

    def heard(self) -> list[dict]:
        if not self.log.exists():
            return []
        return [json.loads(line) for line in self.log.read_text(encoding="utf-8").splitlines()]

    def session(self, worker: list[str] | None = None) -> Session:
        env = dict(os.environ, FAKE_VERSION=str(self.version), FAKE_SOURCES=str(self.sources),
                   FAKE_PROTOCOL=str(self.protocol), FAKE_LOG=str(self.log))
        command = [sys.executable, "-m", "xbsl.mcp_supervisor", "--",
                   *(worker or [sys.executable, str(self.script)])]
        session = Session(command, env=env, cwd=ROOT,
                          stderr=self.folder / f"stderr-{len(self.sessions)}.txt")
        self.sessions.append(session)
        return session


@pytest.fixture()
def fake(tmp_path):
    made = Fake(tmp_path)
    yield made
    for session in made.sessions:
        if session.process.poll() is None:
            session.process.kill()
            session.process.wait()
        session.stderr.close()


def _initializes(fake: Fake) -> list[dict]:
    return [entry for entry in fake.heard() if entry.get("method") == "initialize"]


# -- the answers of a worker, judged ------------------------------------------------------------


def _tool_answer(content: dict, structured: dict | None = None) -> dict:
    result = {"content": [{"type": "text", "text": json.dumps(content)}], "isError": False}
    if structured is not None:
        result["structuredContent"] = structured
    return {"jsonrpc": "2.0", "id": 5, "result": result}


def test_a_refusal_that_did_not_run_the_tool_is_replayed():
    stale = {"reason": "version", "loaded": "1.0", "on_disk": "2.0", "ran": False}
    assert mcp_supervisor.verdict(_tool_answer({"error": "x", "stale": stale}), "lint_paths") == (
        "replay", stale)


def test_a_tool_that_ran_is_not_replayed_but_its_worker_is_replaced():
    ran = {"reason": "sources", "loaded": "1.0", "on_disk": "1.0", "ran": True}
    plugins = {"reason": "plugins", "loaded": "a 1", "on_disk": "a 2"}
    assert mcp_supervisor.verdict(_tool_answer({"error": "x", "stale": ran}), "meta_add_field")[0] \
        == "replace"
    assert mcp_supervisor.verdict(_tool_answer({"stale": plugins, "files": 1}), "lint_paths")[0] \
        == "replace"


def test_version_info_is_asked_again_it_only_reads():
    stale = {"reason": "version", "loaded": "1.0", "on_disk": "2.0"}
    assert mcp_supervisor.verdict(_tool_answer({"engine": "1.0", "stale": stale}),
                                  "version_info")[0] == "replay"


def test_the_structured_content_is_read_too_and_a_fresh_answer_is_left_alone():
    stale = {"reason": "version", "loaded": "1.0", "on_disk": "2.0", "ran": False}
    wrapped = _tool_answer({"note": "text part without the record"}, {"result": {"stale": stale}})
    assert mcp_supervisor.verdict(wrapped, "docs_search")[0] == "replay"
    assert mcp_supervisor.verdict(_tool_answer({"files": 3}), "lint_paths") == (None, None)
    assert mcp_supervisor.verdict({"jsonrpc": "2.0", "id": 5, "error": {"code": 1}}, None) == (
        None, None)


def test_the_supervisor_holds_no_engine():
    """Imported, the supervisor loads the catalog of messages and the journal, and that is all.

    A supervisor holding the engine would go stale the same way the server does - which is the
    one thing it is there to outlive.
    """
    out = subprocess.run(
        [sys.executable, "-c",
         "import sys, xbsl.mcp_supervisor; "
         "print(' '.join(sorted(m for m in sys.modules if m.split('.')[0] in ('xbsl', 'mcp'))))"],
        capture_output=True, text=True, encoding="utf-8", timeout=120, cwd=ROOT,
        stdin=subprocess.DEVNULL, env=dict(os.environ, PYTHONIOENCODING="utf-8"),
    )
    assert out.returncode == 0, out.stderr
    assert out.stdout.split() == ["xbsl", "xbsl.i18n", "xbsl.mcp_supervisor", "xbsl.mcpjournal"]


def test_self_update_stops_the_worker_and_leaves_the_supervisor():
    """`self-update --stop-holders` must free the package without ending the client's session."""
    command = " ".join(mcp_supervisor.worker_command())
    assert selfupdate.is_holder("python.exe", command)
    assert not selfupdate.is_holder("xbsl-mcp-supervisor.exe", "xbsl-mcp-supervisor")
    assert not selfupdate.is_holder(
        "python.exe", r"C:\venv\Scripts\python.exe C:\venv\Scripts\xbsl-mcp-supervisor.exe")
    assert not selfupdate.is_holder("python3", "/usr/bin/python3 -m xbsl.mcp_supervisor")


def test_xbsl_mcp_is_the_supervisor_and_a_holder_only_as_the_bare_server():
    """`xbsl-mcp` starts the supervisor by default: stopping it would end the session it keeps.

    With `--no-supervisor` the same command runs the server in its own process, which holds
    the package like any server - self-update has to count it."""
    assert not selfupdate.is_holder("xbsl-mcp.exe", r"C:\venv\Scripts\xbsl-mcp.exe")
    assert not selfupdate.is_holder("python.exe", r"C:\venv\Scripts\python.exe C:\venv\Scripts\xbsl-mcp.exe")
    assert not selfupdate.is_holder("xbsllint-mcp.exe", r"C:\venv\Scripts\xbsllint-mcp.exe")
    assert not selfupdate.is_holder("python3", "/usr/bin/python3 /venv/bin/xbsl-mcp")
    assert selfupdate.is_holder("xbsl-mcp.exe", r"C:\venv\Scripts\xbsl-mcp.exe --no-supervisor")
    assert selfupdate.is_holder(
        "python.exe", r"C:\venv\Scripts\python.exe C:\venv\Scripts\xbsl-mcp.exe --no-supervisor")
    assert selfupdate.is_holder("python3", "/usr/bin/python3 -m xbsl.mcp_supervisor --no-supervisor")
    # the other commands of the package stay holders by name
    assert selfupdate.is_holder("xbsl-lsp.exe", r"C:\venv\Scripts\xbsl-lsp.exe")
    assert selfupdate.is_holder("python.exe", r"C:\venv\Scripts\python.exe C:\venv\Scripts\xbsl-lsp.exe")


def test_xbsl_mcp_names_the_supervisor_in_the_package():
    text = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    assert 'xbsl-mcp = "xbsl.mcp_supervisor:main"' in text
    assert 'xbsllint-mcp = "xbsl.mcp_supervisor:main"' in text


def test_no_supervisor_runs_the_bare_server_in_this_process(monkeypatch):
    """The flag hands the process over to the server's own entry, with no flags left for it."""
    calls = []
    fake = types.ModuleType("xbsl.mcp_server")
    fake.main = lambda: calls.append(list(sys.argv))
    monkeypatch.setitem(sys.modules, "xbsl.mcp_server", fake)
    monkeypatch.setattr("xbsl.mcp_server", fake, raising=False)
    monkeypatch.setattr(sys, "argv", ["xbsl-mcp", "--no-supervisor"])
    mcp_supervisor.main()
    assert calls == [["xbsl-mcp"]]


def test_the_mcp_journal_tells_a_replacement_in_words(capsys):
    mcpjournal.record("restart", target=101, reason="version", loaded="0.120.0", on_disk="0.121.0")
    mcpjournal.record("restart", target=102, reason="exited", code=3)
    mcpjournal.record("restart", target=103, reason="sources", loaded="0.121.0",
                      on_disk="0.121.0", fingerprint="0123456789ab")
    mcpjournal.record("protocol", target=104, client="2025-06-18", worker="2025-11-25")
    assert cli.main(["mcp-log"]) == 0
    out = capsys.readouterr().out
    assert "супервизор заменяет процесс сервера 101: движок на диске 0.120.0 -> 0.121.0" in out
    assert "процесс сервера 102: процесс завершился с кодом 3" in out
    assert "процесс сервера 103: исходники движка на диске изменились" in out
    assert "клиент продолжает говорить по 2025-06-18" in out
    i18n.set_lang("en")
    try:
        assert cli.main(["mcp-log"]) == 0
        english = capsys.readouterr().out
    finally:
        i18n.set_lang("ru")
    assert "the supervisor replaces the server process 101: the engine on disk 0.120.0" in english
    assert ("the new server process 104 agreed on protocol version 2025-11-25, while the client "
            "was answered 2025-06-18") in english


def test_a_refusal_says_that_the_tool_did_not_run(mcp_module, monkeypatch, tmp_path):
    """The mark the supervisor goes by: false on a refusal, true on a failure after running."""
    from xbsl import freshness

    package = tmp_path / "xbsl"
    package.mkdir()
    (package / "__init__.py").write_text('__version__ = "9.9.9"\n', encoding="utf-8")
    monkeypatch.setattr(freshness, "PACKAGE", package)
    refused = mcp_module._stale_guard(lambda: {"ok": True})()
    assert refused["stale"]["ran"] is False

    (package / "__init__.py").write_text(f'__version__ = "{freshness.__version__}"\n',
                                         encoding="utf-8")

    def broken():
        (package / "__init__.py").write_text('__version__ = "9.9.9"\n', encoding="utf-8")
        raise TypeError("register_row() takes 3 positional arguments but 4 were given")

    failed = mcp_module._stale_guard(broken)()
    assert failed["stale"]["ran"] is True and "TypeError" in failed["error"]


# -- the supervisor in front of a fake worker ---------------------------------------------------


def test_the_client_talks_to_the_server_through_the_supervisor(fake):
    session = fake.session()

    initialized = session.initialize()
    answer = session.call(1, "echo", {"text": "Проба"})

    # announced so that the client asks for the tools again after a replacement
    assert initialized["result"]["capabilities"]["tools"]["listChanged"] is True
    assert initialized["result"]["serverInfo"]["version"] == "1.0.0"
    assert payload(answer)["arguments"] == {"text": "Проба"}
    assert session.close() == 0
    assert fake.heard()[-1]["end"] is True  # the worker heard the end of its input and ended


def test_a_refusal_over_a_replaced_engine_is_answered_by_a_new_worker(fake):
    session = fake.session()
    session.initialize()
    first = payload(session.call(1, "echo"))

    fake.bump("2.0.0")
    answer = session.call(2, "echo", {"again": True})

    fresh = payload(answer)
    assert fresh["engine"] == "2.0.0" and fresh["pid"] != first["pid"]
    assert fresh["arguments"] == {"again": True}
    old, new = _initializes(fake)
    # the new worker heard the client's own handshake, under an id of the supervisor
    assert old["params"] == new["params"] == CLIENT_PARAMS
    assert old["id"] == 0 and str(new["id"]).startswith(mcp_supervisor.OWN_ID)
    heard = [entry for entry in fake.heard() if entry["pid"] == new["pid"]]
    assert [entry.get("method") for entry in heard[:3]] == [
        "initialize", "notifications/initialized", "tools/call"]
    # the client heard of the new tools list and got no second answer to `initialize`
    assert {"jsonrpc": "2.0", "method": "notifications/tools/list_changed"} in session.other
    assert not any("serverInfo" in json.dumps(message) for message in session.other)
    assert session.close() == 0
    ended = {entry["pid"] for entry in fake.heard() if entry.get("end")}
    assert {first["pid"], fresh["pid"]} <= ended  # the old worker ended when it was idle
    (event,) = [event for event in mcpjournal.read() if event["event"] == "restart"]
    assert event["target"] == first["pid"] and event["reason"] == "version"
    assert (event["loaded"], event["on_disk"]) == ("1.0.0", "2.0.0")
    # the new worker agreed on the protocol version the client speaks: nothing to tell
    assert not [event for event in mcpjournal.read() if event["event"] == "protocol"]


def test_each_change_of_the_sources_gets_a_new_worker(fake):
    """A pull between two releases keeps the number, and so does the next pull.

    The worker started after the first pull reports the second one with the same version on
    both sides; the fingerprint of the files tells the second change from the first, so that
    worker is replaced too instead of being taken for one started over this very change.
    """
    session = fake.session()
    session.initialize()
    first = payload(session.call(1, "echo"))

    fake.pull("after the first pull")
    second = payload(session.call(2, "echo"))
    fake.pull("after the second pull")
    third = payload(session.call(3, "echo"))

    assert "error" not in second and "error" not in third, third
    assert len({first["pid"], second["pid"], third["pid"]}) == 3
    assert first["engine"] == second["engine"] == third["engine"] == "1.0.0"
    assert session.close() == 0
    restarts = [event for event in mcpjournal.read() if event["event"] == "restart"]
    assert [(event["target"], event["reason"]) for event in restarts] == [
        (first["pid"], "sources"), (second["pid"], "sources")]


def test_another_protocol_version_of_a_new_worker_is_written_down(fake, capsys):
    """The client keeps the version it was answered at the start; the journal tells the rest."""
    session = fake.session()
    answered = session.initialize()
    fake.protocol.write_text("2024-11-05", encoding="utf-8")
    fake.bump("2.0.0")

    fresh = payload(session.call(1, "echo"))

    assert answered["result"]["protocolVersion"] == PROTOCOL
    assert fresh["engine"] == "2.0.0"  # the call is answered as ever
    assert session.close() == 0
    (event,) = [event for event in mcpjournal.read() if event["event"] == "protocol"]
    assert (event["target"], event["client"], event["worker"]) == (
        fresh["pid"], PROTOCOL, "2024-11-05")
    assert cli.main(["mcp-log"]) == 0
    assert (f"новый процесс сервера {fresh['pid']} согласовал версию протокола 2024-11-05, а "
            f"клиенту в начале сессии ответили {PROTOCOL}") in capsys.readouterr().out


def test_version_info_on_a_stale_worker_is_answered_by_a_new_one(fake):
    session = fake.session()
    session.initialize()
    fake.bump("2.0.0")

    info = payload(session.call(1, "version_info"))

    assert info["engine"] == "2.0.0" and "stale" not in info
    assert session.close() == 0


def test_a_tool_that_ran_on_a_mix_is_passed_on_and_not_repeated(fake):
    session = fake.session()
    session.initialize()
    first = payload(session.call(1, "echo"))
    fake.bump("2.0.0")

    failed = payload(session.call(2, "write"))
    after = payload(session.call(3, "echo"))

    assert failed["stale"]["ran"] is True and failed["error"] == "failed on a mix"
    assert [entry["ran"] for entry in fake.heard() if "ran" in entry].count("write") == 1
    assert after["engine"] == "2.0.0" and after["pid"] != first["pid"]
    assert session.close() == 0


def test_a_call_running_on_the_old_worker_is_finished_there(fake):
    """The old worker is not killed under a running call: it finishes, then ends."""
    session = fake.session()
    session.initialize()
    session.send({"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                  "params": {"name": "sleep", "arguments": {"seconds": 3}}})
    deadline = time.monotonic() + WAIT
    while not any(entry.get("ran") == "sleep" for entry in fake.heard()):
        assert time.monotonic() < deadline and session.process.poll() is None
        time.sleep(0.05)
    fake.bump("2.0.0")

    quick = payload(session.call(2, "echo"))
    slow = payload(session.answer(1))

    assert quick["engine"] == "2.0.0" and slow["engine"] == "1.0.0"
    assert quick["pid"] != slow["pid"]
    assert session.close() == 0


def test_a_worker_that_ended_during_a_call_is_replaced_at_the_next_one(fake):
    session = fake.session()
    session.initialize()
    first = payload(session.call(1, "echo"))

    ended = session.call(2, "exit")
    after = payload(session.call(3, "echo"))

    # whether the call wrote anything is unknown, so it is answered, not repeated
    assert ended["error"]["code"] == mcp_supervisor.INTERNAL_ERROR
    assert "3" in ended["error"]["message"]
    assert after["pid"] != first["pid"] and after["engine"] == "1.0.0"
    assert session.close() == 0
    (event,) = [event for event in mcpjournal.read() if event["event"] == "restart"]
    assert event["reason"] == "exited" and event["code"] == 3


def test_a_reading_request_goes_to_the_new_worker_but_not_round_forever(fake):
    """A request that only reads is sent on when its worker ends - a few times, not forever."""
    session = fake.session()
    session.initialize()

    listed = session.request(1, "tools/list")
    ended = session.request(2, "resources/list")
    after = payload(session.call(3, "echo"))

    assert listed["result"]["engine"] == "1.0.0"
    assert ended["error"]["code"] == mcp_supervisor.INTERNAL_ERROR and "4" in ended["error"]["message"]
    # the first worker and one more per repetition heard it, then the client got the error
    reached = [entry for entry in fake.heard() if entry.get("method") == "resources/list"]
    assert len(reached) == 1 + mcp_supervisor.MAX_REPLAYS
    assert len({entry["pid"] for entry in reached}) == len(reached)
    assert after["engine"] == "1.0.0"
    assert session.close() == 0


def test_a_server_that_cannot_start_ends_the_supervisor_with_its_code(fake):
    """Before the client's `initialize` is answered there is no session to keep: the client
    sees the server fail, as it would without a supervisor."""
    session = fake.session([sys.executable, "-c", "import sys; sys.exit(7)"])

    assert session.process.wait(timeout=WAIT) == 7
    assert session.receive() is None


def test_the_supervisor_ends_with_the_input_of_the_client(fake):
    session = fake.session()
    session.initialize()

    assert session.close(timeout=20) == 0
    assert session.receive() is None


# -- the supervisor in front of the real server -------------------------------------------------


def _copy_package(target: Path) -> Path:
    """A copy of the engine the test may bump the version of: its code, not its data."""
    shutil.copytree(ROOT / "xbsl", target / "xbsl",
                    ignore=shutil.ignore_patterns("__pycache__", "data"))
    return target / "xbsl" / "__init__.py"


def test_the_real_server_is_replaced_when_its_engine_is_updated_on_disk(fake, tmp_path):
    """The whole way: a refusal of the real server over a bumped version never reaches the client.

    The worker imports the copy of the package; the test writes another version into the
    copy's `__init__.py`, as `self-update` would, and the next call is answered by a new worker
    on the new version.
    """
    pytest.importorskip("mcp")
    init = _copy_package(tmp_path / "site")
    empty = tmp_path / "no-data"
    empty.mkdir()
    work = tmp_path / "work"
    work.mkdir()
    env = dict(os.environ, PYTHONPATH=str(tmp_path / "site"), XBSL_NO_PLUGINS="1",
               XBSL_DATA_DIR=str(empty), PYTHONIOENCODING="utf-8")
    session = Session([sys.executable, "-m", "xbsl.mcp_supervisor"], env=env, cwd=work,
                      stderr=tmp_path / "stderr-real.txt")
    fake.sessions.append(session)
    session.initialize()
    rules = {"select": ["code/brackets"]}
    before = session.call(1, "list_rules", rules)
    loaded = payload(session.call(2, "version_info"))

    source = init.read_bytes()
    init.write_bytes(source.replace(f'"{loaded["engine"]}"'.encode(), b'"9.9.9"'))
    after = session.call(3, "list_rules", rules)
    info = payload(session.call(4, "version_info"))

    assert payload(before)["id"] == "code/brackets"
    assert Path(loaded["location"]).resolve() == (tmp_path / "site").resolve()
    assert payload(after).get("id") == "code/brackets", payload(after)  # not a refusal
    assert info["engine"] == "9.9.9" and "stale" not in info
    assert {"jsonrpc": "2.0", "method": "notifications/tools/list_changed"} in session.other
    assert session.close() == 0
    events = mcpjournal.read()
    (stale,) = [event for event in events if event["event"] == "stale"]
    assert stale["tool"] == "list_rules" and stale["on_disk"] == "9.9.9"
    (restart,) = [event for event in events if event["event"] == "restart"]
    assert (restart["reason"], restart["loaded"], restart["on_disk"]) == (
        "version", loaded["engine"], "9.9.9")
    assert [event["version"] for event in events if event["event"] == "start"] == [
        loaded["engine"], "9.9.9"]


def test_the_real_server_is_replaced_when_its_sources_change_under_the_same_version(
        fake, tmp_path):
    """A pull between two releases: the code changes on disk, the number does not.

    The test replaces a module of the copy the way git does - removes it and writes it anew,
    one line longer - under the running worker. The worker refuses the next call before it runs
    it, and the client gets the answer of a new worker on the same version instead.
    """
    pytest.importorskip("mcp")
    init = _copy_package(tmp_path / "site")
    empty = tmp_path / "no-data"
    empty.mkdir()
    work = tmp_path / "work"
    work.mkdir()
    env = dict(os.environ, PYTHONPATH=str(tmp_path / "site"), XBSL_NO_PLUGINS="1",
               XBSL_DATA_DIR=str(empty), PYTHONIOENCODING="utf-8")
    session = Session([sys.executable, "-m", "xbsl.mcp_supervisor"], env=env, cwd=work,
                      stderr=tmp_path / "stderr-real.txt")
    fake.sessions.append(session)
    session.initialize()
    rules = {"select": ["code/brackets"]}
    before = session.call(1, "list_rules", rules)
    loaded = payload(session.call(2, "version_info"))

    module = init.parent / "report.py"
    source = module.read_bytes()
    module.unlink()
    module.write_bytes(source + b"\n# a line the pull brought\n")
    after = session.call(3, "list_rules", rules)
    info = payload(session.call(4, "version_info"))

    assert payload(before)["id"] == "code/brackets"
    assert Path(loaded["location"]).resolve() == (tmp_path / "site").resolve()
    assert payload(after).get("id") == "code/brackets", payload(after)  # not a refusal
    assert info["engine"] == loaded["engine"] and "stale" not in info
    assert {"jsonrpc": "2.0", "method": "notifications/tools/list_changed"} in session.other
    assert session.close() == 0
    events = mcpjournal.read()
    (stale,) = [event for event in events if event["event"] == "stale"]
    assert (stale["tool"], stale["reason"]) == ("list_rules", "sources")
    assert stale["loaded"] == stale["on_disk"] == loaded["engine"] and stale["fingerprint"]
    (restart,) = [event for event in events if event["event"] == "restart"]
    assert restart["reason"] == "sources"
    assert [event["version"] for event in events if event["event"] == "start"] == [
        loaded["engine"]] * 2
