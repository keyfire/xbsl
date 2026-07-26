#!/usr/bin/env python3
"""Back-compat shim: the extractor lives in xbsl/extract/stdlib.py now."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # the local xbsl wins over an installed copy

from xbsl.extract.stdlib import main  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(main())
