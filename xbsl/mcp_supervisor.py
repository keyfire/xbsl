"""The supervisor of the MCP server: the client's session outlives the process that serves it.

`xbsl-mcp` lives as long as the client session, and the engine on disk can be replaced under
it: `self-update`, a pull of an editable checkout, a plugin upgrade. The server then refuses
its tools and asks for a restart (xbsl/freshness.py), which only the client can do - and a
client such as Codex never starts a stopped server again. Restarting from inside does not work
either: `os.execv` on Windows starts a new process that the client does not know, and on POSIX
the new image waits for `initialize` the client sent long ago (see the comment on the stale
engine in xbsl/mcp_server.py).

`xbsl-mcp-supervisor` stands between the client and the server. It owns the stdio the client
speaks over, runs the server as a worker process behind it and passes the JSON-RPC lines both
ways. It keeps the client's `initialize` request and its `notifications/initialized`, and when
a worker has to go it starts a new one and replays that handshake to it. The answer to the
replayed `initialize` stays here, so the client never learns that another process answers now.

When to replace the worker is the engine's own verdict, read from its answers. The supervisor
has no check of its own: it imports nothing of the engine (the catalog of messages and the
journal are leaves), so it never goes stale itself - and the worker sees what the supervisor
could not: the plugins, the sources behind an unchanged version.

- A refusal over a replaced engine - another version on disk, or the engine's code files changed
  under the same one - carries `stale` with `ran: false`: the tool did not run. The supervisor
  starts a new worker and sends it the same request, and the client gets the answer of the new
  code instead of the refusal. `version_info` is asked again as well: it only reads. A request
  goes to a new worker twice at most, then the refusal is passed on.
- Any other answer with `stale` - a tool that failed on a mix of the old and the new code, a
  warning about the plugins changed on disk - is passed on as it is: the tool ran and may have
  written files, so it is not repeated. The next request goes to a new worker.
- A worker that ended on its own or was stopped (`self-update --stop-holders` stops it, while the
  supervisor is not a holder: it keeps no file of the package open) is replaced at the next
  request rather than at once, since a start in the middle of an update would load the package
  being moved aside. A `tools/call` it was running is answered with an error - whether the tool
  wrote anything is unknown - and any other request it was running goes to the new worker.

A worker being replaced gets no new requests, finishes the ones it runs and ends when its stdin
is closed; a refusal it sends meanwhile goes to the new worker the same way. After a new worker
takes over, the client gets `notifications/tools/list_changed`: a new version may bring tools
and parameters, and the client asks for the list again. For that the answer to the client's
`initialize` announces `tools.listChanged`.

The replayed `initialize` asks for the protocol version the client asked for, and a new worker
may agree on another one: an update of the `mcp` package can drop the version the client
speaks. Nothing changes then - the client keeps the version it was answered, and the new
worker goes on - but the journal gets a `protocol` event with both versions, and `xbsl mcp-log`
shows it next to the replacement.

The supervisor ends when the client closes its stdin: the workers get the end of their input
too, and the supervisor waits for them (SHUTDOWN_GRACE at most). It also ends when the first
worker ends before the client's `initialize` was answered, with the worker's exit code: the
server could not start at all, and the client should see it as it would without a supervisor.

The transport, as the traps on Windows dictate:

- lines are bytes: nothing is decoded or re-encoded on the way, apart from the messages the
  supervisor writes itself and the answer to `initialize` it amends;
- the worker's stdin is a pipe of the supervisor, never the client's handle: a child that
  inherits the stdin the client speaks over does not end on Windows;
- the worker's stderr is the supervisor's, so the client's log shows what the server says there;
- the supervisor leaves by `os._exit`: a daemon thread blocked in a read of stdin holds the lock
  of that stream, and the normal shutdown of the interpreter stops on it.
"""

from __future__ import annotations

import argparse
import json
import os
import queue
import subprocess
import sys
import threading
import time
from collections import deque
from pathlib import Path

from xbsl import i18n, mcpjournal

#: The module the worker runs: the MCP server itself.
WORKER_MODULE = "xbsl.mcp_server"
#: How many times one request is sent to a new worker after a refusal over a replaced engine.
MAX_REPLAYS = 2
#: The pauses before the attempts to start a new worker, in seconds. An update still unpacking
#: the package makes a start fail, and a later one succeeds; after the last one the waiting
#: requests are answered with an error, and the next request starts the attempts anew.
START_DELAYS = (0.0, 0.5, 1.0, 2.0, 4.0, 8.0)
#: How long a new worker may take to answer the replayed `initialize`: the engine is imported
#: before it answers, and on a cold disk that is seconds.
HANDSHAKE_TIMEOUT = 120.0
#: How long a replaced worker may take to end after its stdin is closed before it is killed.
EXIT_GRACE = 10
#: How long the supervisor waits for its workers after the client closed its stdin.
SHUTDOWN_GRACE = 30.0
#: The id prefix of the requests the supervisor sends itself (the replayed `initialize`).
OWN_ID = "xbsl-supervisor-"
#: The JSON-RPC error code of an answer the supervisor gives itself.
INTERNAL_ERROR = -32603
#: The request that only reads is sent to a new worker when its worker ended; this one is not.
UNSAFE_METHODS = frozenset({"tools/call"})
#: The tools answered again by a new worker when the old one answered them stale.
READ_ONLY_TOOLS = frozenset({"version_info"})


def worker_command() -> list[str]:
    """The command of the worker: the MCP server on this interpreter, found as `xbsl-mcp` finds it.

    The console scripts do not put the working directory on `sys.path`, and `python -m` does -
    so a project folder with its own `xbsl` package would give the worker another engine than
    the supervisor's. `-P` (Python 3.11) leaves it out, unless the supervisor itself was
    imported from the working directory (`python -m` in a checkout): then the worker imports
    the same checkout. The command keeps `-m xbsl.mcp_server`, which is how `self-update` tells
    the worker for a holder of the package.
    """
    command = [sys.executable]
    if sys.version_info >= (3, 11) and not _imported_from_working_directory():
        command.append("-P")
    return [*command, "-m", WORKER_MODULE]


def _imported_from_working_directory() -> bool:
    try:
        return Path(__file__).resolve().parent.parent == Path.cwd().resolve()
    except OSError:
        return False


def _parse(line: bytes):
    try:
        return json.loads(line)
    except ValueError:
        return None


def _key(value) -> str:
    """A request id as a dictionary key: 1 and "1" are two different ids."""
    return json.dumps(value)


def _line(message: dict) -> bytes:
    return (json.dumps(message, ensure_ascii=False, separators=(",", ":")) + "\n").encode("utf-8")


def _error(request_id, message: str) -> bytes:
    return _line({"jsonrpc": "2.0", "id": request_id,
                  "error": {"code": INTERNAL_ERROR, "message": message}})


def _protocol(message: dict) -> str | None:
    """The protocol version an answer to `initialize` agreed on; None when it names none."""
    result = message.get("result")
    version = result.get("protocolVersion") if isinstance(result, dict) else None
    return version if isinstance(version, str) else None


def _answers(result: dict) -> list[dict]:
    """The objects a tool answered with: the structured content and the JSON of its text parts."""
    found = []
    structured = result.get("structuredContent")
    if isinstance(structured, dict):
        found.append(structured)
        if isinstance(structured.get("result"), dict):  # a union return type is wrapped
            found.append(structured["result"])
    for item in result.get("content") or ():
        if isinstance(item, dict) and item.get("type") == "text":
            parsed = _parse(item.get("text") or "")
            if isinstance(parsed, dict):
                found.append(parsed)
    return found


def verdict(message: dict, tool: str | None) -> tuple[str | None, dict | None]:
    """What an answer of a worker says about the worker: ("replay" | "replace" | None, stale).

    "replay": the tool did not run (a refusal with `stale.ran` false) or only reads, so a new
    worker answers the same request. "replace": the answer goes to the client as it is, and the
    worker is replaced for the next request. None: a fresh worker, nothing to do.
    """
    result = message.get("result")
    if not isinstance(result, dict):
        return None, None
    for answer in _answers(result):
        stale = answer.get("stale")
        if isinstance(stale, dict) and stale.get("reason"):
            if stale.get("ran") is False or tool in READ_ONLY_TOOLS:
                return "replay", stale
            return "replace", stale
    return None, None


class _Request:
    """A request of the client that is not answered yet."""

    __slots__ = ("id", "line", "method", "tool", "worker", "replays", "cancelled")

    def __init__(self, request_id, line: bytes, method: str, tool: str | None) -> None:
        self.id = request_id
        self.line = line
        self.method = method
        self.tool = tool
        self.worker: _Worker | None = None
        self.replays = 0
        self.cancelled = False


class _Worker:
    """One process of the server and what it runs now."""

    def __init__(self, process: subprocess.Popen) -> None:
        self.process = process
        #: starting (the replayed handshake is not answered yet), ready, retiring, dead.
        self.state = "starting"
        #: The keys of the client's requests this worker runs, in the order they came.
        self.inflight: dict[str, None] = {}
        #: The keys of the requests this worker sent to the client.
        self.asked: set[str] = set()
        #: The id of the replayed `initialize`; None for a worker the client initializes itself.
        self.handshake: str | None = None
        #: When the worker is killed: no answer to the handshake, or no end after the stdin closed.
        self.deadline: float | None = None
        self.closed = False
        #: Why a start of this worker failed, in words for the answer to a waiting request.
        self.error = ""
        #: The change on disk this worker was started for: (reason, on disk and the fingerprint
        #: of the sources). A worker that reports the same change again is not replaced over
        #: it - a new one would see it too.
        self.cause: tuple[str, str] | None = None


class Supervisor:
    """The loop: one thread per stream reads lines into a queue, and this one acts on them."""

    def __init__(self, command: list[str], client_in, client_out, *, env=None) -> None:
        self.command = list(command)
        self.client_in = client_in
        self.client_out = client_out
        self.env = env
        self.events: queue.Queue = queue.Queue()
        self.worker: _Worker | None = None
        self.retiring: list[_Worker] = []
        self.requests: dict[str, _Request] = {}
        #: The client's lines waiting for a worker that is ready: (line, key of a request or None).
        self.backlog: deque[tuple[bytes, str | None]] = deque()
        self.initialize: dict | None = None
        self.initialize_key: str | None = None
        self.initialized: bytes | None = None
        #: Whether the client's own `initialize` was answered: the session exists.
        self.session = False
        #: The protocol version that answer agreed on: the one the client speaks.
        self.protocol: str | None = None
        #: Whether the client was told `tools.listChanged`, and so hears of every new worker.
        self.announce = False
        self.started = 0
        self.failures = 0
        self.retry_at: float | None = None
        self.last_error = ""
        self.closing = False
        self.closing_deadline: float | None = None
        self.client_gone = False
        self.finished = False
        self.exit_code = 0

    # -- the loop -------------------------------------------------------------------------------

    def run(self) -> int:
        """Serve until the client closes its stdin; the exit code of the supervisor."""
        self._start()
        if self.worker is None:
            sys.stderr.write(f"xbsl-mcp-supervisor: {self.last_error}\n")
            return 1
        threading.Thread(target=self._read_client, name="client", daemon=True).start()
        while not self.finished:
            try:
                kind, payload = self.events.get(timeout=self._timeout())
            except queue.Empty:
                pass
            else:
                if kind == "client":
                    self._from_client(payload)
                elif kind == "client-end":
                    self._client_end()
                elif kind == "worker":
                    self._from_worker(*payload)
                else:
                    self._worker_end(payload)
            self._timers()
        return self.exit_code

    def _read_client(self) -> None:
        try:
            for line in iter(self.client_in.readline, b""):
                self.events.put(("client", line))
        except (OSError, ValueError):
            pass
        self.events.put(("client-end", None))

    def _read_worker(self, worker: _Worker) -> None:
        try:
            for line in iter(worker.process.stdout.readline, b""):
                self.events.put(("worker", (worker, line)))
        except (OSError, ValueError):
            pass
        self.events.put(("worker-end", worker))

    def _live(self) -> list[_Worker]:
        return [worker for worker in (self.worker, *self.retiring)
                if worker is not None and worker.state != "dead"]

    def _timeout(self) -> float | None:
        moments = [moment for moment in (self.retry_at, self.closing_deadline,
                                         *(worker.deadline for worker in self._live()))
                   if moment is not None]
        return max(0.0, min(moments) - time.monotonic()) if moments else None

    def _timers(self) -> None:
        now = time.monotonic()
        if self.retry_at is not None and now >= self.retry_at:
            self.retry_at = None
            self._start()
        for worker in self._live():
            if worker.deadline is not None and now >= worker.deadline:
                worker.deadline = None
                if worker.state == "starting":
                    worker.error = f"no answer to initialize in {HANDSHAKE_TIMEOUT:g} s"
                self._kill(worker)  # its end arrives as an event
        if self.closing_deadline is not None and now >= self.closing_deadline:
            for worker in self._live():
                self._kill(worker)
            self.finished = True

    # -- workers --------------------------------------------------------------------------------

    def _start(self) -> None:
        """Start a worker; with a session, replay the handshake to it first."""
        if self.worker is not None or self.closing:
            return
        self.started += 1
        try:
            process = subprocess.Popen(
                self.command, stdin=subprocess.PIPE, stdout=subprocess.PIPE, env=self.env,
                # No console window of its own when the client started the supervisor without one.
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
        except OSError as error:
            self.last_error = f"{type(error).__name__}: {error}"
            self._start_failed()
            return
        worker = _Worker(process)
        self.worker = worker
        threading.Thread(target=self._read_worker, args=(worker,), name=f"worker-{process.pid}",
                         daemon=True).start()
        if self.initialize is None:
            worker.state = "ready"  # the client's own `initialize` comes to it
            self._flush()
            return
        worker.handshake = f"{OWN_ID}{self.started}"
        worker.deadline = time.monotonic() + HANDSHAKE_TIMEOUT
        self._send(worker, _line({**self.initialize, "id": worker.handshake}))

    def _start_failed(self) -> None:
        """A start that did not come to a ready worker: try again later, or give up for now."""
        self.failures += 1
        if self.failures < len(START_DELAYS):
            self.retry_at = time.monotonic() + START_DELAYS[self.failures]
            return
        self.failures = 0
        message = i18n.t("supervisor.start-failed", error=self.last_error or "?")
        while self.backlog:
            _waiting, key = self.backlog.popleft()
            request = self.requests.pop(key, None) if key is not None else None
            if request is not None and not request.cancelled:
                self._write_client(_error(request.id, message))

    def _handshake(self, worker: _Worker, message: dict) -> None:
        worker.deadline = None
        if not isinstance(message.get("result"), dict):
            worker.error = json.dumps(message.get("error"), ensure_ascii=False)[:300]
            self._kill(worker)  # its end counts as a failed start
            return
        worker.state = "ready"
        self.failures = 0
        agreed = _protocol(message)
        if self.protocol is not None and agreed != self.protocol:
            # The client goes on speaking the version it was answered: the difference is only
            # told, for whoever looks into a session that misbehaves after a replacement.
            mcpjournal.record("protocol", target=worker.process.pid, client=self.protocol,
                              worker=agreed or "?")
        if self.initialized is not None:
            self._send(worker, self.initialized)
        self._flush()
        if self.announce:
            self._write_client(_line({"jsonrpc": "2.0",
                                      "method": "notifications/tools/list_changed"}))

    def _replace(self, worker: _Worker, stale: dict) -> None:
        """Retire the current worker and start a new one; the old one ends when it is idle."""
        # A change of the sources keeps the number on disk: its fingerprint names the change.
        cause = (str(stale.get("reason")), json.dumps(
            [stale.get("on_disk"), stale.get("fingerprint")], sort_keys=True))
        if worker is not self.worker or worker.cause == cause:
            return  # replaced already, or started for this very change
        self._journal(worker, stale)
        worker.state = "retiring"
        self.retiring.append(worker)
        self.worker = None
        self._settle(worker)
        self._start()
        if self.worker is not None:
            self.worker.cause = cause

    def _settle(self, worker: _Worker) -> None:
        if worker.state == "retiring" and not worker.inflight and not worker.closed:
            self._close(worker)
            worker.deadline = time.monotonic() + EXIT_GRACE

    def _close(self, worker: _Worker) -> None:
        worker.closed = True
        try:
            worker.process.stdin.close()
        except (OSError, ValueError):
            pass

    def _kill(self, worker: _Worker) -> None:
        try:
            worker.process.kill()
        except OSError:
            pass

    def _reap(self, worker: _Worker):
        try:
            return worker.process.wait(timeout=EXIT_GRACE)
        except subprocess.TimeoutExpired:
            self._kill(worker)
            return worker.process.wait()

    def _journal(self, worker: _Worker, stale: dict) -> None:
        fields = {name: stale[name] for name in ("loaded", "on_disk", "code") if name in stale}
        mcpjournal.record("restart", target=worker.process.pid, reason=stale.get("reason", "?"),
                          **fields)

    def _worker_end(self, worker: _Worker) -> None:
        if worker.state == "dead":
            return
        state, worker.state, worker.deadline = worker.state, "dead", None
        code = self._reap(worker)
        self._close(worker)
        if worker in self.retiring:
            self.retiring.remove(worker)
        current = worker is self.worker
        if current:
            self.worker = None
        if self.closing:
            if not self._live():
                self.finished = True
            return
        if state == "starting":
            self.last_error = worker.error or f"exit code {code}"
            self._start_failed()
            return
        if current and not self.session:
            # The server could not start at all: the client sees it end, as without a supervisor.
            self.exit_code = code if isinstance(code, int) and code > 0 else 1
            self.finished = True
            return
        if current:
            self._journal(worker, {"reason": "exited", "code": code})
        message = i18n.t("supervisor.worker-ended", code=code)
        for key in list(worker.inflight):
            request = self.requests.get(key)
            if request is None:
                continue
            request.worker = None
            # A request that ends every worker it reaches is answered, not sent round forever.
            if (request.method in UNSAFE_METHODS or request.cancelled
                    or request.replays >= MAX_REPLAYS):
                del self.requests[key]
                if not request.cancelled:
                    self._write_client(_error(request.id, message))
            else:
                request.replays += 1
                self._forward(request.line, key)
        worker.inflight.clear()

    # -- the client's lines ---------------------------------------------------------------------

    def _from_client(self, line: bytes) -> None:
        message = _parse(line)
        if not isinstance(message, dict):
            self._forward(line, None)  # a batch or not JSON at all: the server answers it
            return
        method = message.get("method")
        if isinstance(method, str) and "id" in message:
            key = _key(message["id"])
            if method == "initialize" and self.initialize is None:
                self.initialize, self.initialize_key = message, key
            params = message.get("params") if isinstance(message.get("params"), dict) else {}
            tool = params.get("name") if method == "tools/call" else None
            self.requests[key] = _Request(message["id"], line, method, tool)
            self._forward(line, key)
        elif isinstance(method, str):
            if method == "notifications/initialized" and self.initialized is None:
                self.initialized = line
            elif method == "notifications/cancelled":
                params = message.get("params") if isinstance(message.get("params"), dict) else {}
                request = self.requests.get(_key(params.get("requestId")))
                if request is not None:
                    request.cancelled = True
            self._forward(line, None, notification=True)
        elif "id" in message:
            self._to_asker(line, _key(message["id"]))
        else:
            self._forward(line, None)

    def _forward(self, line: bytes, key: str | None, *, notification: bool = False) -> None:
        """To the current worker when it is ready, else into the backlog (a start is due)."""
        worker = self.worker
        if worker is not None and worker.state == "ready":
            self._deliver(worker, line, key)
            return
        if worker is None and notification:
            return  # nobody to tell: a new worker starts without it
        self.backlog.append((line, key))
        if worker is None and self.retry_at is None:
            self._start()

    def _deliver(self, worker: _Worker, line: bytes, key: str | None) -> None:
        if key is not None:
            request = self.requests.get(key)
            if request is None:
                return
            if request.cancelled:  # cancelled while it waited for a worker: nobody wants it
                del self.requests[key]
                return
            request.worker = worker
            worker.inflight[key] = None
        self._send(worker, line)

    def _flush(self) -> None:
        worker = self.worker
        while self.backlog and worker is not None and worker.state == "ready":
            line, key = self.backlog.popleft()
            self._deliver(worker, line, key)

    def _to_asker(self, line: bytes, key: str) -> None:
        """The client's answer to a request of a worker goes to the worker that asked."""
        for worker in self._live():
            if key in worker.asked:
                worker.asked.discard(key)
                self._send(worker, line)
                return

    def _client_end(self) -> None:
        if self.closing:
            return
        self.closing = True
        self.closing_deadline = time.monotonic() + SHUTDOWN_GRACE
        self.backlog.clear()
        self.retry_at = None
        live = self._live()
        for worker in live:
            worker.deadline = None
            self._close(worker)
        if not live:
            self.finished = True

    # -- the workers' lines ---------------------------------------------------------------------

    def _from_worker(self, worker: _Worker, line: bytes) -> None:
        message = _parse(line)
        if isinstance(message, dict) and "method" not in message and "id" in message:
            key = _key(message["id"])
            if worker.state == "starting" and key == _key(worker.handshake):
                self._handshake(worker, message)
                return
            request = self.requests.get(key)
            if request is not None:
                if request.worker is worker:
                    self._answered(worker, key, request, line, message)
                return  # the request is another worker's now: a second answer would confuse
        elif isinstance(message, dict) and isinstance(message.get("method"), str) and "id" in message:
            worker.asked.add(_key(message["id"]))
        self._write_client(line)

    def _answered(self, worker: _Worker, key: str, request: _Request, line: bytes,
                  message: dict) -> None:
        worker.inflight.pop(key, None)
        found, stale = verdict(message, request.tool) if b"stale" in line else (None, None)
        if (found == "replay" and request.replays < MAX_REPLAYS and not request.cancelled
                and not self.closing):
            request.replays += 1
            request.worker = None
            self._replace(worker, stale)
            self._forward(request.line, key)
            self._settle(worker)
            return
        del self.requests[key]
        if key == self.initialize_key and not self.session:
            self.session = True
            self.protocol = _protocol(message)
            line = self._announced(message) or line
        self._write_client(line)
        if found is not None:
            self._replace(worker, stale)
        self._settle(worker)

    def _announced(self, message: dict) -> bytes | None:
        """The answer to the client's `initialize` with `tools.listChanged` set, or None as it is."""
        result = message.get("result")
        capabilities = result.get("capabilities") if isinstance(result, dict) else None
        tools = capabilities.get("tools") if isinstance(capabilities, dict) else None
        if not isinstance(tools, dict):
            return None
        self.announce = True
        if tools.get("listChanged") is True:
            return None
        tools["listChanged"] = True
        return _line(message)

    # -- writing --------------------------------------------------------------------------------

    def _send(self, worker: _Worker, data: bytes) -> None:
        if worker.closed:
            return
        try:
            worker.process.stdin.write(data if data.endswith(b"\n") else data + b"\n")
            worker.process.stdin.flush()
        except (OSError, ValueError):
            pass  # the worker is gone: its end arrives as an event

    def _write_client(self, data: bytes) -> None:
        if self.client_gone:
            return
        try:
            self.client_out.write(data if data.endswith(b"\n") else data + b"\n")
            self.client_out.flush()
        except (OSError, ValueError):
            self.client_gone = True
            self._client_end()


def _parser() -> argparse.ArgumentParser:
    return i18n.ArgumentParser(
        prog="xbsl-mcp-supervisor",
        description=i18n.t("cli.help.mcp-supervisor.description"),
        epilog=i18n.t("cli.help.mcp-supervisor.epilog"),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )


def main(argv: list[str] | None = None) -> None:
    arguments = sys.argv[1:] if argv is None else list(argv)
    command: list[str] = []
    if "--" in arguments:
        at = arguments.index("--")
        arguments, command = arguments[:at], arguments[at + 1:]
    _parser().parse_args(arguments)
    supervisor = Supervisor(command or worker_command(), sys.stdin.buffer, sys.stdout.buffer)
    try:
        code = supervisor.run()
    except KeyboardInterrupt:
        code = 130
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.flush()
        except (OSError, ValueError):
            pass
    os._exit(code)


if __name__ == "__main__":
    main()
