#!/usr/bin/env python3
"""Back-compat shim: the extractor manager lives in the xbsl.extract package now.

Equivalent entry points: `xbsl extract ...` (installed package) or this script from a clone.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # the local xbsl wins over an installed copy

from xbsl.extract import main  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(main())
