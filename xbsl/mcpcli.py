"""The command line that makes the same call as an MCP tool.

A server whose engine was replaced on disk refuses its tools (xbsl/freshness.py), and the cure
it names - a restart - belongs to the client that owns the process; an agent calling the tools
cannot restart it. Caught on 27.09.2026: the engine under a running session moved from 0.119.1
to 0.120.0, every call answered "restart the xbsl MCP server", and the lint and the dictionary
were finished through the CLI, the commands pieced together by hand. A NEW process of the same
interpreter imports the engine from the same place, and that place holds the new code now -
which is all the CLI needs to answer. So the refusal of a tool the CLI can run carries the
command line of the same call, built here from the arguments the call came with.

The line is for a POSIX shell (Git Bash on Windows): every word goes through `shlex.quote`, so a
path with spaces or Cyrillic reaches the process as it was written. It opens with the settings
the server's answers depend on - their language, the Element data, the plugins switched off, the
rule parameters moved off their defaults - as variable assignments, since the agent's shell does
not share the environment the client gave the server. The rest of that environment stays out:
`XBSL_TRANSLATE_*_KEY` hold the keys of a paid translation service.

A call whose input is data rather than a path - the text of `lint_source`, the inline edits of
`translate_set` - has that data written into a temporary folder of this process, and the command
reads it from there: `--stdin` without a redirection checks an empty text and calls it clean.
The folder outlives its server, since the command may run after the restart; a folder older
than a day is taken out by the next server that stages anything (`sweep_old_folders`).

A tool that runs with the plugins loaded at start while others are on disk answers anyway, and
its `stale` record carries the same command: the answer by the plugins on disk.

A call the CLI cannot make the same way - several filters where the CLI takes one, a batch that
is half a file and half inline - gets no command rather than a different one, and so does a tool
without a CLI counterpart; their refusal stays as it was.

The server imports this module at its start, never at the moment of a refusal: by then the
modules on disk are another version, and one imported then would be the new code talking to the
old. For the same reason nothing here imports anything lazily.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shlex
import shutil
import site
import sys
import sysconfig
import tempfile
import time
from collections.abc import Callable
from dataclasses import dataclass

from xbsl import engine, freshness, i18n, plugins

MESSAGES = {
    "mcpcli.same-call": {
        "ru": "Тот же вызов без перезапуска – команда из поля cli: новый процесс того же "
              "интерпретатора загрузит код движка, который сейчас на диске",
        "en": "The same call without a restart is the command in `cli`: a new process of the "
              "same interpreter loads the engine code that is on disk now",
    },
    "mcpcli.same-call-plugins": {
        "ru": "Ответ по надстройкам с диска без перезапуска – команда из поля cli",
        "en": "The answer by the plugins on disk, without a restart, is the command in `cli`",
    },
    "mcpcli.stdin-staged": {
        "ru": "Команда читает текст со stdin (--stdin): текст этого вызова записан в {path}, и "
              "команда подает его перенаправлением <. Другой текст подается так же; --filename "
              "задает только вид файла и путь в находках, сам файл не нужен",
        "en": "The command reads the text from stdin (--stdin): the text of this call is saved "
              "to {path}, and the command feeds it in with <. Another text goes in the same "
              "way; --filename only sets the kind of the file and the path in the findings, the "
              "file itself is not needed",
    },
    "mcpcli.stdin-unstaged": {
        "ru": "Команда читает текст со stdin (--stdin): запишите текст вызова в файл и допишите "
              "к команде < ФАЙЛ. Без перенаправления stdin пуст, и проверка пустого текста "
              "ничего не найдет",
        "en": "The command reads the text from stdin (--stdin): save the text of the call to a "
              "file and append < FILE to the command. Without the redirection stdin is empty, "
              "and a check of an empty text finds nothing",
    },
    "mcpcli.edits-staged": {
        "ru": "Правки этого вызова (edits) записаны в {path}, команда передает их ключом --set",
        "en": "The edits of this call are saved to {path}, and the command passes them with --set",
    },
}
i18n.register(MESSAGES)


@dataclass(frozen=True)
class Run:
    """One run of the CLI: the words after `-m xbsl`, and the file its stdin is read from."""

    argv: tuple[str, ...]
    stdin: str = ""


#: What a builder answers: the runs of the command and a note on data saved for it ("" for
#: none), or None when the CLI cannot make this call the same way.
Built = tuple[list[Run], str] | None

#: The variables the answers of the server depend on besides the language, carried over when
#: set - the data root made absolute, since the shell stands elsewhere. Named one by one: the
#: whole environment would carry the keys of the translation service as well.
_CARRIED = (
    "XBSL_DATA_DIR", "XBSLLINT_DATA_DIR", "XBSL_ELEMENT_VERSION", "XBSLLINT_ELEMENT_VERSION",
    plugins.ENV_DISABLE, "XBSLLINT_NO_PLUGINS",
)

#: The folder holding the data of refused calls (see _stage); made on first use.
_staged_in: str | None = None
#: The file name extensions a staged file keeps, so a person can tell its kind.
_SUFFIX = re.compile(r"\.[A-Za-z0-9]{1,16}")


def same_call(tool: str, arguments: dict) -> dict | None:
    """{"cli": the command line of this call, "cli_note" when data was saved for it}.

    None when the tool has no CLI counterpart or the call cannot be made the same way.
    `arguments` are the call's own, the defaults included. Nothing raised while the line is
    built reaches the caller: the refusal answers either way, with the command or without it.
    """
    build = BUILDERS.get(tool)
    if build is None:
        return None
    try:
        built = build(arguments)
        if built is None:
            return None
        runs, note = built
        assignments = " ".join(
            f"{name}={shlex.quote(value)}" for name, value in _environment().items()
        )
        answer = {"cli": "; ".join(_line(run, assignments) for run in runs)}
    except Exception:  # noqa: BLE001 - see the docstring
        return None
    if note:
        answer["cli_note"] = note
    return answer


def _line(run: Run, assignments: str) -> str:
    words = shlex.join([*_interpreter(), *run.argv])
    line = f"{assignments} {words}" if assignments else words
    if run.stdin:
        line += f" < {shlex.quote(run.stdin)}"
    return line


def _interpreter() -> list[str]:
    """The server's own interpreter, running the engine package as a program.

    `-m` puts the working folder first on sys.path, so a shell standing in a checkout of the
    engine would run that checkout instead of the installation the server came from; `-P`
    (Python 3.11+) leaves the folder out. An older interpreter has no such flag, and there a
    folder named `xbsl` where the shell stands still takes the engine's place.
    """
    words = [sys.executable or "python"]
    if sys.version_info >= (3, 11):
        words.append("-P")
    return [*words, "-m", "xbsl"]


def _environment() -> dict[str, str]:
    """The variable assignments the command opens with."""
    carried: dict[str, str] = {}
    home = str(freshness.PACKAGE.parent)
    if _key(home) not in _site_folders():
        # A source checkout: an editable install, a worktree, the folder the server was
        # started in. Named outright, it is the copy the command imports wherever the shell
        # stands - an installed copy is found by the interpreter itself.
        carried["PYTHONPATH"] = home
    carried[i18n.ENV_LANG] = i18n.current_lang()
    for name in _CARRIED:
        value = os.environ.get(name)
        if value:
            carried[name] = os.path.abspath(value) if name.endswith("_DATA_DIR") else value
    for param in engine.PARAMS:
        value = os.environ.get(param.env) if param.env else None
        if value is not None and value.strip():
            carried[param.env] = value
    return carried


def _site_folders() -> set[str]:
    """The folders installed distributions live in, spelled by `_key`."""
    paths = sysconfig.get_paths()
    found = [paths.get("purelib"), paths.get("platlib")]
    try:
        found += site.getsitepackages()
    except AttributeError:  # the site module of an old virtualenv has no such function
        pass
    try:
        found.append(site.getusersitepackages())
    except AttributeError:
        pass
    return {_key(folder) for folder in found if folder}


def _key(folder: str) -> str:
    return os.path.normcase(os.path.realpath(folder))


def _stage(data: bytes, suffix: str) -> str:
    """The path of a file holding `data` for the command to read; "" when it cannot be written.

    Bytes, not text: the text of lint_source has to reach --stdin exactly as the tool would
    have encoded it, its line endings included. The folder is this process's own (`mkdtemp`:
    private, its name unpredictable), and a file is named by the digest of its data, so a call
    refused twice writes one file.
    """
    global _staged_in
    try:
        if _staged_in is None or not os.path.isdir(_staged_in):
            sweep_old_folders()
            _staged_in = tempfile.mkdtemp(prefix=_FOLDER_PREFIX)
        name = hashlib.sha256(data).hexdigest()[:16]
        path = os.path.join(_staged_in, name + (suffix if _SUFFIX.fullmatch(suffix) else ""))
        with open(path, "wb") as target:
            target.write(data)
    except OSError:
        return ""
    return path


#: The folder prefix of the staged data; a folder of it older than _OLD_FOLDER_SECONDS was left by
#: a server process long gone, and its commands were answered or dropped long ago.
_FOLDER_PREFIX = "xbsl-mcp-"
_OLD_FOLDER_SECONDS = 24 * 3600


def sweep_old_folders(root: str | None = None, now: float | None = None) -> int:
    """Take out the staged folders earlier servers left; the count of the folders taken out.

    A folder is not cleaned when its server exits: the agent may run the command only after
    the client restarted the server, and the data would be gone by then. So the next server
    that stages anything clears what is older than a day. Only this module's own folders go:
    the prefix, a real folder (not a link, not a junction), past the age.
    """
    base = root or tempfile.gettempdir()
    moment = time.time() if now is None else now
    is_junction = getattr(os.path, "isjunction", lambda _path: False)
    removed = 0
    try:
        names = os.listdir(base)
    except OSError:
        return 0
    for name in names:
        if not name.startswith(_FOLDER_PREFIX):
            continue
        path = os.path.join(base, name)
        try:
            if (os.path.islink(path) or is_junction(path) or not os.path.isdir(path)
                    or moment - os.path.getmtime(path) < _OLD_FOLDER_SECONDS):
                continue
        except OSError:
            continue
        shutil.rmtree(path, ignore_errors=True)
        removed += not os.path.exists(path)
    return removed


# --- the arguments ------------------------------------------------------------------------------


def _base(root: str | None) -> str:
    """The folder the relative paths of a call resolve against: `mcp_server._base`, as text."""
    return os.path.abspath(root) if root else os.getcwd()


def _under(base: str, path: str) -> str:
    """`path` against the base, an absolute one standing as it is: `mcp_server._under`."""
    return os.path.normpath(os.path.join(base, path))


def _paths(arguments: dict, base: str) -> list[str] | None:
    """The paths of the call as the tool resolves them; None for none, or for an empty one."""
    paths = arguments.get("paths") or []
    if not paths or not all(isinstance(path, str) and path for path in paths):
        return None
    return [_under(base, path) for path in paths]


def _option(flag: str, value: object) -> list[str]:
    """A flag and its value. A value that starts with a dash is joined to the flag by `=`:
    apart, argparse would take it for a flag of its own."""
    text = str(value)
    return [f"{flag}={text}"] if text.startswith("-") else [flag, text]


def _each(flag: str, values) -> list[str]:
    return [word for value in values or () for word in _option(flag, value)]


def _rules(arguments: dict, *names: str) -> list[str]:
    """--select, --ignore and --enable as the call gave them."""
    return [word for name in names for word in _each(f"--{name}", arguments.get(name))]


# --- the linter ---------------------------------------------------------------------------------


def _list_rules(arguments: dict) -> Built:
    argv = ["--list-rules", *_rules(arguments, "select", "ignore")]
    if arguments.get("filter"):
        argv += _option("--rules-filter", arguments["filter"])
    return [Run((*argv, "--format", "json"))], ""


def _lint_paths(arguments: dict) -> Built:
    base = _base(arguments.get("root"))
    paths = _paths(arguments, base)
    if paths is None:
        return None
    argv = [*paths, *_rules(arguments, "select", "ignore", "enable")]
    if arguments.get("baseline"):
        argv += _option("--baseline", _under(base, arguments["baseline"]))
    if arguments.get("no_baseline"):
        argv.append("--no-baseline")
    if arguments.get("as_ci_job"):
        argv += _option("--as-ci-job", arguments["as_ci_job"])  # implies --as-ci, as here
    elif arguments.get("as_ci"):
        argv.append("--as-ci")
    if arguments.get("fix"):
        argv.append("--fix")
    if arguments.get("compare"):
        # A report of its own, in text: the CLI refuses a second format beside it.
        argv += _option("--compare", _under(base, arguments["compare"]))
    elif not arguments.get("compact"):
        # Without `compact` the whole report; with it the text of the CLI - every finding one
        # line and the summary under them, which is what the short answer holds.
        argv += ["--format", "json"]
    return [Run(tuple(argv))], ""


def _baseline_prune(arguments: dict) -> Built:
    base = _base(arguments.get("root"))
    paths = _paths(arguments, base)
    if paths is None:
        return None
    argv = [*paths, *_rules(arguments, "select", "ignore", "enable")]
    if arguments.get("baseline"):
        argv += _option("--baseline", _under(base, arguments["baseline"]))
    # --summary: the stale entries are named (on stderr) and the findings only counted - the
    # answer of the tool names the entries and not the findings either.
    mode = "--stale-baseline" if arguments.get("dry_run") else "--prune-baseline"
    return [Run((*argv, mode, "--summary"))], ""


def _lint_source(arguments: dict) -> Built:
    filename, content = arguments.get("filename"), arguments.get("content")
    if not filename or not isinstance(content, str):
        return None
    # --no-baseline: the tool applies none, and the CLI would look for one above the name.
    argv = ("--stdin", *_option("--filename", filename), "--no-baseline",
            *_rules(arguments, "select", "ignore"), "--format", "json")
    staged = _stage(content.encode("utf-8"), os.path.splitext(filename)[1])
    if staged:
        return [Run(argv, staged)], i18n.t("mcpcli.stdin-staged", path=staged)
    return [Run(argv)], i18n.t("mcpcli.stdin-unstaged")


def _fold_comments(arguments: dict) -> Built:
    base = _base(arguments.get("root"))
    paths = _paths(arguments, base)
    if paths is None:
        return None
    argv = ["fold-comments", *paths]
    if not arguments.get("dry_run", True):
        argv.append("--write")
    if arguments.get("take_proposed"):
        argv.append("--all")
    if arguments.get("compact"):
        argv.append("--compact")
    return [Run((*argv, "--format", "json"))], ""


# --- the translation dictionary -----------------------------------------------------------------


def _project(arguments: dict) -> list[str]:
    """`translate <root>`, the root made absolute the way the tools read it (load_for_tools)."""
    return ["translate", os.path.abspath(arguments.get("root") or "")]


def _narrowed(arguments: dict, *, kind: bool = True) -> list[str]:
    words = []
    if kind and arguments.get("kind", "any") != "any":
        words += _option("--kind", arguments["kind"])
    if arguments.get("filter"):
        words += _option("--filter", arguments["filter"])
    return words


def _page(arguments: dict) -> list[str]:
    """The page of the call. The CLI lists everything unless told otherwise and the tools a
    page, so the limit goes along whenever it is not "all" (0)."""
    words = []
    if arguments.get("limit"):
        words += _option("--limit", arguments["limit"])
    if arguments.get("offset"):
        words += _option("--offset", arguments["offset"])
    return words


def _as_json(arguments: dict) -> list[str]:
    """JSON, unless the call asked for the short rows - which is what the text of the CLI is."""
    return [] if arguments.get("compact") else ["--format", "json"]


def _translate_status(arguments: dict) -> Built:
    # The report in text: its JSON lists every name the dictionary misses, the tool only counts.
    runs = [Run(tuple(_project(arguments)))]
    if arguments.get("against"):
        # The collisions with a ref are a mode of their own in the CLI: a second run.
        runs.append(Run((*_project(arguments), "--check-duplicates",
                         *_option("--against", arguments["against"]))))
    return runs, ""


def _translate_gaps(arguments: dict) -> Built:
    argv = (*_project(arguments), "--gaps", *_narrowed(arguments), *_page(arguments))
    return [Run((*argv, *_as_json(arguments)))], ""


def _translate_entries(arguments: dict) -> Built:
    argv = (*_project(arguments), "--entries", *_narrowed(arguments), *_page(arguments))
    return [Run((*argv, *_as_json(arguments)))], ""


def _translate_unused(arguments: dict) -> Built:
    wanted = arguments.get("filter") or ""
    if isinstance(wanted, list):
        texts = [text for text in wanted if text]
        if len(texts) > 1:
            # The CLI takes one substring: several would be several walks over the sources,
            # and a pruning run could not be told apart from the tool's single one.
            return None
        wanted = texts[0] if texts else ""
    arguments = {**arguments, "filter": wanted}
    argv = [*_project(arguments), "--unused", *_narrowed(arguments)]
    if arguments.get("since"):
        argv += _option("--since", arguments["since"])
    # The tool removes the whole filtered set whatever its page, the CLI the page it lists:
    # a pruning run lists everything.
    argv += ["--prune"] if arguments.get("prune") else _page(arguments)
    return [Run((*argv, *_as_json(arguments)))], ""


def _translate_redundant(arguments: dict) -> Built:
    argv = [*_project(arguments), "--redundant", *_narrowed(arguments, kind=False)]
    argv += ["--prune"] if arguments.get("prune") else _page(arguments)  # as in _translate_unused
    return [Run((*argv, "--format", "json"))], ""


def _translate_drift(arguments: dict) -> Built:
    argv = (*_project(arguments), "--drift", *_narrowed(arguments, kind=False), *_page(arguments))
    return [Run((*argv, "--format", "json"))], ""


def _translate_set(arguments: dict) -> Built:
    edits, source = arguments.get("edits"), arguments.get("edits_file") or ""
    if edits and source:
        return None  # the CLI takes one file, the tool the file and then the list after it
    note = ""
    if source:
        source = os.path.abspath(source)  # the tool reads it against its own working folder
    elif edits:
        # The JSON list the tool takes inline is one of the two shapes of a --set file.
        text = json.dumps(edits, ensure_ascii=False, indent=1)
        source = _stage(text.encode("utf-8"), ".json")
        if not source:
            return None
        note = i18n.t("mcpcli.edits-staged", path=source)
    else:
        return None
    argv = [*_project(arguments), *_option("--set", source)]
    if arguments.get("target"):
        argv += _option("--target", arguments["target"])
    if arguments.get("comment"):
        argv += _option("--comment", arguments["comment"])
    return [Run((*argv, "--format", "json"))], note


#: The tools the CLI can run, each with the builder of its command. A tool missing here has no
#: counterpart that answers the same way, and its refusal stays as it was: the documentation and
#: the schemas have no command at all, and the meta_* scaffolding has subcommands whose
#: arguments are not the tools' one to one (properties as nested objects, batches of names, the
#: JSON of a report) - a write the command would not repeat exactly is worse than none.
BUILDERS: dict[str, Callable[[dict], Built]] = {
    "list_rules": _list_rules,
    "lint_paths": _lint_paths,
    "lint_source": _lint_source,
    "baseline_prune": _baseline_prune,
    "meta_fold_comments": _fold_comments,
    "translate_status": _translate_status,
    "translate_gaps": _translate_gaps,
    "translate_entries": _translate_entries,
    "translate_unused": _translate_unused,
    "translate_redundant": _translate_redundant,
    "translate_drift": _translate_drift,
    "translate_set": _translate_set,
}
