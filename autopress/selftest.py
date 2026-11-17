# OWNED BY G8 - replace this stub
"""Packaged-build self-test: ``AutoPress.exe --selftest report.json`` (also ``main.py``).

Checks without showing windows and without injecting input: bundled resources and templates
load; OCR model files exist and the engine reads a rendered test image ("兌換碼：AB12-CD34" and
"兌換" on a dialog-like image); a QApplication starts on the default platform; DPI awareness is
per-monitor-v2 after QApplication; the data folder is writable. Writes a JSON report and
returns 0 when every check passed, 1 otherwise. ui.app.main dispatches ``--selftest`` BEFORE it
creates a QApplication; run() uses ``QApplication.instance() or QApplication([...])`` (T31).
build.ps1 also runs it from a folder whose path contains Chinese characters (users' names often
do; PX-21).
"""

from __future__ import annotations

__stub__ = True


def run(report_path: str) -> int:
    raise NotImplementedError
