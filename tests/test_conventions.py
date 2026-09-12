"""Conventions of the sources that no single test of a feature would ever notice.

A convention nobody wrote down is a convention every new file gets to rediscover, and both
conventions here hide their failures.

The first is the encoding of a started PROCESS: read as text without a named encoding, it is
decoded with the console code page, so the Russian half of the output turns into replacement
characters - and the exit code goes on saying that everything went well. The other half of the
same failure sits on the child's side: a Python process writes its stdout in the code page too
unless PYTHONIOENCODING says otherwise, so a parent that decodes perfectly still gets mojibake.
This repository generates a whole Russian documentation page out of `--help` that way.

The second is the line ending of a file this repository WRITES. `write_text` and `open` in text
mode turn a line feed into whatever the platform uses, so a generator run on Windows hands back
a file with every line changed. `core.autocrlf=input` hides that in a checkout that has it, and
that is the whole trouble: on a machine without the setting, a page nobody edited goes to a
public repository as one line-ending change. The generators of the documentation were already
passing `newline=""` and so was the baseline writer, which is the only reason the convention was
recognizable as one; twenty-two other writes were not, from the template export of the CLI to
the language data of an extraction.

The third is the stdin of a started process, and it is the quietest of the three. The engine
ships two servers that speak over stdin - MCP and LSP - and a child started without a word
about stdin inherits that handle. On Windows the child then cannot finish: git did the work
of `rev-parse` in four milliseconds and sat holding the pipe, so the parent waited out the
whole timeout with nothing printed, and the orphans-of-one-change mode read as a tool that
had stopped answering. Nothing here ever writes to a child, so `stdin=subprocess.DEVNULL`
costs nothing and closes the class.

The MECHANICS are not this repository's business: the engine, the bridge and the console all
start processes and write their files the same way and have the same silent failures waiting,
so reading the sources with `ast` and judging a call lives in the shared `docsguard` package
(`conventions.py`). What stays here is the list of FOLDERS - which of them hold code that starts
a process, and which of them write files that outlive the run, are facts about this repository -
and the half of the first convention the shared package has no word for: a PYTHON child needs
`PYTHONIOENCODING=utf-8` in its environment, which is meaningless for `git` or `taskkill`.

Two details of the reading are ours as well. The files are read with `utf-8-sig`, because
`xbsl/__init__.py` carries a BOM and `ast.parse` refuses the mark as a non-printable
character - the folder-wide `process_encoding_problems` and `text_write_newline_problems`,
which open the files themselves as plain `utf-8`, would die on the first one instead of judging
the repository, so both conventions are read here file by file. And `ast` rather than a regular
expression is the whole point of the shared readers: a process start is written
`(run or subprocess.run)(...)` wherever the tests need a seam, and a check reading the text
before the parenthesis would pass over exactly those.
"""

from __future__ import annotations

import ast
from pathlib import Path

from docsguard import (
    Layout,
    asks_for_text,
    encoding_problems,
    newline_problems,
    process_starts,
    python_sources,
    text_write_newline_problems,
    text_writes,
)

ROOT = Path(__file__).resolve().parents[1]
LAYOUT = Layout(root=ROOT)

#: Everything written in Python here: the engine, the generators of the pages, the guards and
#: the tests themselves - a convention that stops at the test folder is half a convention.
FOLDERS = ("xbsl", "scripts", "tests", "tools")

#: The folders of the stdin convention: the SHIPPED package alone. A server speaking over
#: stdin is what makes an inherited handle fatal, and that is the engine - a generator or a
#: test runs from a console, where stdin is a console and a child may have it.
SERVER_FOLDERS = ("xbsl",)

#: The folders of the newline convention, and deliberately a shorter list: a test writes into a
#: temporary directory that is gone when the run ends - nothing it writes is committed, shipped
#: or compared between machines, and a fixture carrying the other line ending on purpose is a
#: test in its own right. What belongs here is the code whose writes OUTLIVE the run.
WRITING_FOLDERS = ("xbsl", "scripts", "tools")

#: How a command line names a Python interpreter when it is not `sys.executable`.
PYTHON_NAMES = frozenset({"python", "python3", "py", "python.exe", "pythonw.exe"})
#: What the child's own streams are set by.
CHILD_ENCODING = "PYTHONIOENCODING"


def read(path: Path) -> str:
    """The text of a source file - with the BOM taken off, which some of them carry.

    `utf-8` would leave the mark in the string and `ast.parse` refuses it as a non-printable
    character: the guard would then die on the first file instead of judging the repository.
    """
    return path.read_text(encoding="utf-8-sig")


def sources() -> list[Path]:
    """Every Python file of the repository, in a stable order."""
    return python_sources(LAYOUT, FOLDERS)


def starts_python(call: ast.Call) -> bool:
    """Whether the command line is a PYTHON interpreter - `sys.executable`, or named outright.

    Only a literal list is judged: a command built elsewhere says nothing here, and guessing
    would make the check fire on lines nobody can fix.
    """
    if not call.args or not isinstance(call.args[0], (ast.List, ast.Tuple)):
        return False
    elements = call.args[0].elts
    if not elements:
        return False
    head = elements[0]
    if isinstance(head, ast.Attribute) and head.attr == "executable":
        return isinstance(head.value, ast.Name) and head.value.id == "sys"
    return isinstance(head, ast.Constant) and str(head.value).lower() in PYTHON_NAMES


def names_child_encoding(tree: ast.AST) -> bool:
    """Whether the file hands its Python children an environment that sets PYTHONIOENCODING.

    The environment reaches a call in three shapes - `dict(os.environ, ...)`, `{**os.environ,
    ...}` and a name built a few lines above - so what is looked for is the NAME anywhere in
    the file, not a keyword of the call. In `dict(...)` it is an argument name and in a dict
    literal a string, hence the two halves. A file that names the variable has thought about
    the child's encoding; a file that never mentions it has not, and that is the distinction
    worth guarding.
    """
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            if CHILD_ENCODING in node.value:
                return True
        elif isinstance(node, ast.keyword) and node.arg == CHILD_ENCODING:
            return True
    return False


def problems_in(source: str, where: str) -> list[str]:
    """The process starts of one file that decode without saying how.

    The first half is the shared one - a process read as text without an encoding. The second
    is this repository's own: a Python child started from here writes in the console code page
    unless its environment says otherwise, and the parent's own `encoding="utf-8"` does not
    reach it.
    """
    problems = list(encoding_problems(source, where))
    tree = ast.parse(source)
    if names_child_encoding(tree):
        return problems
    for call in process_starts(tree):
        if asks_for_text(call) and starts_python(call):
            problems.append(f"{where}:{call.lineno}: a Python child is read as text without "
                            f'{CHILD_ENCODING}="utf-8" in its environment')
    return sorted(problems)


def test_every_process_read_as_text_names_its_encoding():
    """The convention: nothing decodes with whatever code page the machine happens to have."""
    problems = []
    for path in sources():
        problems += problems_in(read(path), path.relative_to(ROOT).as_posix())

    assert problems == []


def test_the_reader_finds_the_calls_it_is_meant_to_judge():
    """A detector that finds nothing passes every repository, this one included."""
    found = [
        path.relative_to(ROOT).as_posix()
        for path in sources()
        if process_starts(ast.parse(read(path)))
    ]

    assert len(found) > 4
    assert "scripts/gen-cli-docs.py" in found  # the page generator, the costliest of them


def test_a_call_that_asks_for_text_without_an_encoding_is_caught():
    """The provocation, in both shapes a process start is written in."""
    plain = "import subprocess\nsubprocess.run(command, capture_output=True, text=True)\n"
    seam = "import subprocess\n(run or subprocess.run)(command, text=True)\n"

    assert len(problems_in(plain, "plain.py")) == 1
    # the shape the failure comes in: the callable is chosen at the call site, and a check
    # reading the head of the call would look straight past it
    assert len(problems_in(seam, "seam.py")) == 1


def test_a_call_that_decodes_nothing_is_left_alone():
    """Bytes in, bytes out: there is no encoding to name, and demanding one would be noise."""
    bytes_only = "import subprocess\nsubprocess.run(command, capture_output=True, check=True)\n"
    spelled = ('import subprocess\nsubprocess.run(command, capture_output=True, text=True, '
               'encoding="utf-8")\n')

    assert problems_in(bytes_only, "bytes.py") == []
    assert problems_in(spelled, "spelled.py") == []


def test_a_python_child_without_an_encoding_of_its_own_is_caught():
    """The other half: the parent decodes utf-8 while the child writes the console code page."""
    silent = ('import subprocess, sys\n'
              'subprocess.run([sys.executable, "-m", "xbsl", "--help"],'
              ' capture_output=True, text=True, encoding="utf-8")\n')
    named = ('import subprocess, sys, os\n'
             'env = dict(os.environ, PYTHONIOENCODING="utf-8")\n'
             'subprocess.run([sys.executable, "-c", code], env=env,'
             ' capture_output=True, text=True, encoding="utf-8")\n')
    by_name = ('import subprocess\nsubprocess.run(["python3", "-c", code],'
               ' capture_output=True, text=True, encoding="utf-8")\n')

    assert len(problems_in(silent, "silent.py")) == 1
    assert problems_in(named, "named.py") == []
    assert len(problems_in(by_name, "byname.py")) == 1


def test_a_child_that_is_not_python_is_not_asked_for_a_python_variable():
    """`git` and `taskkill` have no PYTHONIOENCODING - demanding it would be cargo cult."""
    git = ('import subprocess\nsubprocess.run(["git", "log"], capture_output=True,'
           ' text=True, encoding="utf-8")\n')

    assert problems_in(git, "git.py") == []


def test_the_source_with_a_bom_is_read_rather_than_refused():
    """`xbsl/__init__.py` carries one, and `ast.parse` refuses the mark outright.

    The shared `process_encoding_problems` opens the files itself as plain `utf-8`, so this
    repository reads them with `utf-8-sig` and hands the text over - otherwise the guard dies
    on the first file instead of judging the repository.
    """
    marked = ROOT / "xbsl" / "__init__.py"

    assert marked.read_bytes().startswith(b"\xef\xbb\xbf")
    assert problems_in(read(marked), "init.py") == []


def stdin_problems_in(source: str, where: str) -> list[str]:
    """The process starts of one file that let the child inherit this process's stdin.

    A call that hands the child something to read - `input=` or an `stdin=` of its own - has
    answered the question and is left alone; what is caught is the call that never asks.
    """
    problems = []
    for call in process_starts(ast.parse(source)):
        if any(keyword.arg in ("stdin", "input") for keyword in call.keywords):
            continue
        problems.append(f"{where}:{call.lineno}: a process is started without saying what its "
                        "stdin is, so it inherits the one the server speaks over")
    return problems


def test_no_process_of_the_engine_inherits_the_stdin_of_its_parent():
    """The convention itself: a child of the MCP or LSP server can always reach its own exit."""
    problems = []
    for path in python_sources(LAYOUT, SERVER_FOLDERS):
        problems += stdin_problems_in(read(path), path.relative_to(ROOT).as_posix())

    assert problems == []


def test_a_process_started_without_a_word_about_stdin_is_caught():
    """The provocation - and the two shapes that have thought about it."""
    silent = 'import subprocess\nsubprocess.run(["git", "log"], capture_output=True)\n'
    closed = ('import subprocess\nsubprocess.run(["git", "log"], capture_output=True,'
              ' stdin=subprocess.DEVNULL)\n')
    fed = ('import subprocess\nsubprocess.run(["git", "hash-object", "--stdin"], input=blob)\n')

    assert len(stdin_problems_in(silent, "silent.py")) == 1
    assert stdin_problems_in(closed, "closed.py") == []
    assert stdin_problems_in(fed, "fed.py") == []


def writing_sources() -> list[Path]:
    """Every Python file whose writes outlive the run, in a stable order."""
    return python_sources(LAYOUT, WRITING_FOLDERS)


def test_every_text_file_written_here_names_its_newline():
    """The convention itself: no generator hands back a file with every line changed."""
    problems: list[str] = []
    for path in writing_sources():
        problems += newline_problems(read(path), path.relative_to(ROOT).as_posix())

    assert problems == []


def test_the_writes_reader_finds_the_calls_it_is_meant_to_judge():
    """A detector that finds nothing passes every repository, this one included."""
    found = [
        path.relative_to(ROOT).as_posix()
        for path in writing_sources()
        if text_writes(ast.parse(read(path)))
    ]

    assert len(found) > 3
    # The writer the convention was found broken in: `xbsl templates` rewrites the file of
    # custom templates on every import and export.
    assert "xbsl/cli.py" in found


def test_the_shared_newline_check_still_bites(tmp_path):
    """The guard comes from a pinned package, and a pin is raised by hand.

    A version that had stopped judging would look from here exactly like a repository in order,
    which is the whole failure this file exists to prevent - so the provocation is made against
    the installed package, on sources of its own. No BOM in a temporary file, so the folder-wide
    reader can do the reading here.
    """
    (tmp_path / "scripts").mkdir()
    (tmp_path / "scripts" / "offender.py").write_text(
        'from pathlib import Path\nPath("page.md").write_text(text, encoding="utf-8")\n',
        encoding="utf-8", newline="")

    problems = text_write_newline_problems(Layout(root=tmp_path), ("scripts",))

    assert len(problems) == 1
    assert "scripts/offender.py:2" in problems[0]


def test_a_write_that_names_its_newline_is_left_alone():
    """Either spelling passes - `""` and `"\\n"` both write the text through untouched."""
    empty = 'from pathlib import Path\nPath("a").write_text(t, encoding="utf-8", newline="")\n'
    feed = 'from pathlib import Path\nPath("a").write_text(t, encoding="utf-8", newline="\\n")\n'
    read_only = 'from pathlib import Path\ntext = open("a", encoding="utf-8").read()\n'

    assert newline_problems(empty, "empty.py") == []
    assert newline_problems(feed, "feed.py") == []
    assert newline_problems(read_only, "read.py") == []
