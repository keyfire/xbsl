"""Опциональная нативная сборка горячих модулей.

По умолчанию пакет собирается чисто питоньим - setup.py ничего не добавляет. С env
`XBSL_MYPYC=1` лексер и парсер компилируются mypyc'ом в C-расширения (замер на корпусе -
кратное ускорение токенизации и разбора); нужен установленный mypy и C-компилятор
(на Windows - MSVC Build Tools). Модули остаются обычным Python-кодом: без флага или на
платформе без колеса всё работает как раньше - расширение лишь замещает их при импорте.

    XBSL_MYPYC=1 python -m build            # колесо с нативными lexer/parser
    python setup.py build_ext --inplace     # локально, .pyd/.so рядом с исходниками
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
