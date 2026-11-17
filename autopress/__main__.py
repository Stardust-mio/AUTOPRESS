# OWNED BY G5 - replace this stub
"""``python -m autopress`` -> ui.app.main() (OPENBLAS_NUM_THREADS=1 set before numpy loads)."""

from __future__ import annotations

import os
import sys

os.environ.setdefault("OPENBLAS_NUM_THREADS", "1")

__stub__ = True


def _run() -> int:
    from autopress.ui.app import main

    return main(sys.argv[1:])


if __name__ == "__main__":
    sys.exit(_run())
