"""The parallel run: what is allowed to cross a process boundary.

`run_parallel` shards the file rules over a ProcessPoolExecutor. Everything a worker
returns is pickled in the child and unpickled in the parent, and a failure on either
side reaches the user as a bare `BrokenProcessPool`: the real exception dies with the
child process, so such a defect is expensive to diagnose and easy to misread as a
problem with the pool itself.

The `--jobs` path had no test at all, which is why it could ship broken. The trap it
walked into is worth stating, because it is invisible to a normal checkout: in the
native build (mypyc, `XBSL_MYPYC=1`) the lexer and the parser become C extensions, and
their classes pickle without complaint but cannot be rebuilt - unpickling calls
`cls.__new__(cls)` with no arguments while the generated constructor demands its
parameters. A source file carrying such an object in its cache therefore travelled fine
in a pure-Python run and killed the pool in the released wheel.
"""

import pickle
from pathlib import Path

import pytest

from xbsl.engine import make_source, run, run_parallel


class _RebuiltOnlyWithArgs:
    """Stand-in for a native class such as `lexer._LineMap`.

    A pure-Python build cannot exhibit the real failure - there `_LineMap` round-trips
    happily - so the guard needs an object with the same shape: picklable, but not
    reconstructible without constructor arguments.
    """

    def __new__(cls, text):
        obj = super().__new__(cls)
        obj.text = text
        return obj


def _source(text: str = "// пример\nметод Ф() кон\n"):
    return make_source(Path("Пример.xbsl"), text.encode("utf-8"))


def test_the_stand_in_really_breaks_unpickling():
    """Negative control: without this the guards below would prove nothing."""
    blob = pickle.dumps(_RebuiltOnlyWithArgs("текст"))
    with pytest.raises(TypeError):
        pickle.loads(blob)


def test_source_pickle_drops_the_cache():
    src = _source()
    src.cache["tokens"] = [1, 2, 3]
    restored = pickle.loads(pickle.dumps(src))
    assert restored.cache == {}
    # everything that is not derived data survives
    assert restored.path == src.path
    assert restored.kind == src.kind
    assert restored.data == src.data
    assert restored.text == src.text
    assert restored.newline == src.newline


def test_source_pickle_survives_a_cache_that_cannot_travel():
    """The invariant that keeps the pool alive.

    Both directions are covered: an entry that refuses to be pickled at all, and one
    that pickles but cannot be rebuilt - the shape of the native lexer classes.
    """
    src = _source()
    src.cache["linemap"] = _RebuiltOnlyWithArgs("текст")
    src.cache["callback"] = lambda: None
    restored = pickle.loads(pickle.dumps(src))
    assert restored.cache == {}
    assert restored.text == src.text


@pytest.mark.needs_data
def test_parallel_run_matches_the_sequential_one(request):
    """A real two-worker run over the demo project.

    This is what the pickling tests above cannot reach: spawning the workers, the
    re-import of the package and its entry points in a fresh interpreter, and the
    pickling of both the payload and the result. The report must be identical to the
    sequential one - `run_parallel` promises the same output, only sooner.
    """
    root = request.config.rootpath / "demo"
    paths = sorted(p for p in root.rglob("*") if p.suffix in (".xbsl", ".yaml"))
    assert paths, "the demo project is empty - the test would assert nothing"

    sequential = sorted(run(paths), key=lambda d: (d.path, d.line, d.col, d.rule_id))
    parallel = run_parallel(paths, jobs=2)

    assert parallel == sequential
