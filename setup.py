"""Optional native build of the hot modules.

By default the package builds pure Python - setup.py adds nothing. With the env
`XBSL_MYPYC=1` the lexer and the parser are compiled by mypyc into C extensions (a multiple
speedup of tokenization and parsing); an installed mypy and a
C compiler are required (MSVC Build Tools on Windows). The modules remain ordinary Python
code: without the flag, or on a platform without a wheel, everything works as before -
the extension merely replaces them at import time.

    XBSL_MYPYC=1 python -m build            # a wheel with the native lexer/parser
    python setup.py build_ext --inplace     # locally, .pyd/.so next to the sources
"""

import os

from setuptools import setup

kwargs = {}
if os.environ.get("XBSL_MYPYC") == "1":
    from mypyc.build import mypycify

    kwargs["ext_modules"] = mypycify(
        ["xbsl/lexer.py", "xbsl/parser.py", "--ignore-missing-imports"],
        opt_level="2",
    )

setup(**kwargs)
