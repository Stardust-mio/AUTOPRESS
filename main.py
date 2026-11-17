# OWNED BY G5
"""AutoPress launcher (also the PyInstaller entry script).

    .venv/Scripts/python.exe main.py                        normal start
    .venv/Scripts/python.exe main.py --selftest report.json packaged-build self-test (G8)
    .venv/Scripts/python.exe main.py --wait-lock            (restart_as_admin) wait for the lock

OPENBLAS_NUM_THREADS=1 is set HERE, before anything imports numpy (ui.app imports modules that
import numpy at import time, T31).
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

os.environ.setdefault("OPENBLAS_NUM_THREADS", "1")

if not getattr(sys, "frozen", False):
    _ROOT = str(Path(__file__).resolve().parent)
    if _ROOT not in sys.path:
        sys.path.insert(0, _ROOT)


def main(argv: list[str] | None = None) -> int:
    from autopress.ui.app import main as app_main

    return app_main(list(sys.argv[1:] if argv is None else argv))


if __name__ == "__main__":
    sys.exit(main())
