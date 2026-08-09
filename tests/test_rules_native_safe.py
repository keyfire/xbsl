"""Rules must stay correct in the NATIVE build, not only in a pure-Python run.

The released wheel compiles the lexer and the parser with mypyc, and a compiled class has no
`__dict__`: `vars(node)` raises TypeError there. A rule that walks an AST that way passes every
local test and then crashes on every module of a real project - which is exactly what happened
twice, to two different rules. The walk has to read `dataclasses.fields`, which lives on the
class and survives compilation.

Local tests cannot exercise mypyc (building the native extension takes minutes), so the guard
is a source check: no rule may reach into the instance dictionary of a node.
"""

import re
from pathlib import Path

RULES_DIR = Path(__file__).resolve().parent.parent / "xbsl" / "rules"

#: `vars(` outside comments and docstrings - the mention in a docstring explains the ban.
_CALL = re.compile(r"(?<![\w.])vars\s*\(")


def _code_lines(path: Path):
    """Lines with the docstrings and comments stripped crudely - enough for one call name."""
    inside = False
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        stripped = line.strip()
        if stripped.startswith(('"""', "'''")) or stripped.endswith(('"""', "'''")):
            # a one-line docstring opens and closes on the same line
            if not (len(stripped) > 6 and stripped.startswith(('"""', "'''"))
                    and stripped.endswith(('"""', "'''"))):
                inside = not inside
            continue
        if inside or stripped.startswith("#"):
            continue
        yield number, line


def test_no_rule_walks_a_node_through_vars():
    offenders = []
    for path in sorted(RULES_DIR.glob("*.py")):
        for number, line in _code_lines(path):
            if _CALL.search(line):
                offenders.append(f"{path.name}:{number}")
    assert not offenders, (
        "правило читает узел через vars() - в нативной сборке у скомпилированного класса нет "
        "__dict__, и правило упадёт на каждом модуле; обходить поля через "
        "dataclasses.fields: " + ", ".join(offenders)
    )
