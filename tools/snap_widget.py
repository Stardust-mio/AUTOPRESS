"""Render any widget/page to a PNG on the REAL windows platform, never shown on screen
(WA_DontShowOnScreen). OWNED BY A1. Use it to look at your UI (offscreen has no real fonts).

    .venv/Scripts/python.exe tools/snap_widget.py autopress.ui.codes_page:CodesPage --out C:/.../codes.png
        [--theme dark|light] [--scale 1.25] [--size 1280x800] [--lang zh-TW|en] [--empty]

``module:factory`` - a class or function; it receives the demo AppContext when it has a
required first parameter (pages: ``Page(ctx)``), otherwise it is called without arguments.
The context comes from tests/fakes.py demo_context() (``--empty``: without demo data); its
theme setting is the rendered theme. Window lookups, the privilege probe and the monitor list
see the demo desktop of tools/guide_capture.py, never the real one (real window titles can
hold e-mail addresses or account names).
While G5's theme/widgets are stubs, tests/ui_fallback.py stand-ins are used (plain look).
Prints the PNG path and any QLabel whose text is clipped. Writes nothing else.
For the user-guide pictures (every screen, one coherent demo state) use tools/guide_capture.py.
"""

from __future__ import annotations

import argparse
import atexit
import importlib
import inspect
import os
import shutil
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def clipped_labels(root: object, include_elided: bool = False) -> list[str]:
    """Visible single-line QLabels whose text is wider than the label ("clipped: ..."). Labels
    that elide on purpose (widgets.ElidedLabel, drawn with "…") are left out, or reported as
    "elided: ..." with ``include_elided``. Rich-text labels are measured without their tags."""
    from PyQt6.QtCore import Qt
    from PyQt6.QtGui import QFontMetrics, QTextDocument
    from PyQt6.QtWidgets import QLabel

    out = []
    for lb in root.findChildren(QLabel):  # type: ignore[attr-defined]
        if not lb.isVisible() or lb.wordWrap() or not lb.text() or lb.pixmap() is not None and not lb.pixmap().isNull():
            continue
        text = lb.text()
        if lb.textFormat() == Qt.TextFormat.RichText or (lb.textFormat() == Qt.TextFormat.AutoText
                                                         and Qt.mightBeRichText(text)):
            doc = QTextDocument()
            doc.setHtml(text)
            text = doc.toPlainText()
        need = QFontMetrics(lb.font()).horizontalAdvance(text.split("\n")[0])
        if need > lb.contentsRect().width() + 1:
            elided = any(c.__name__ == "ElidedLabel" for c in type(lb).__mro__)
            if elided and not include_elided:
                continue
            kind = "elided" if elided else "clipped"
            out.append(f"{kind}: {text[:40]!r} needs {need}px, has {lb.contentsRect().width()}px")
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("target", help="module:factory, e.g. autopress.ui.codes_page:CodesPage")
    ap.add_argument("--out", required=True)
    ap.add_argument("--theme", default="dark", choices=["dark", "light"])
    ap.add_argument("--scale", type=float, default=0.0, help="emulate 125/150 %% with QT_SCALE_FACTOR")
    ap.add_argument("--size", default="1280x800")
    ap.add_argument("--lang", default="zh-TW")
    ap.add_argument("--empty", action="store_true")
    a = ap.parse_args(argv)

    if os.environ.get("QT_QPA_PLATFORM", "windows") != "windows":
        os.environ.pop("QT_QPA_PLATFORM")  # never offscreen: no real fonts there
    if a.scale:
        os.environ["QT_SCALE_FACTOR"] = str(a.scale)
    os.environ.setdefault("OPENBLAS_NUM_THREADS", "1")
    home = tempfile.mkdtemp(prefix="autopress-snap-")
    os.environ["AUTOPRESS_HOME"] = home
    atexit.register(shutil.rmtree, home, ignore_errors=True)

    from PyQt6.QtCore import Qt
    from PyQt6.QtWidgets import QApplication, QWidget

    app = QApplication.instance() or QApplication([sys.argv[0]])
    from tests import ui_fallback

    ui_fallback.install()
    from autopress import i18n
    from autopress.ui import theme

    i18n.set_language(a.lang)
    theme.apply_theme(app, a.theme)
    from autopress.models import ThemeName
    from tests.fakes import demo_context
    from tools.guide_capture import DemoWorld, install_demo_environment

    install_demo_environment(DemoWorld())  # never the real desktop's windows or monitors
    ctx = demo_context(Path(os.environ["AUTOPRESS_HOME"]), with_data=not a.empty)
    ctx.settings.theme = ThemeName(a.theme)  # the Appearance controls match the rendered theme
    modname, _, attr = a.target.partition(":")
    factory = getattr(importlib.import_module(modname), attr)
    try:
        params = [p for p in inspect.signature(factory).parameters.values()
                  if p.default is inspect.Parameter.empty and p.kind in (p.POSITIONAL_ONLY, p.POSITIONAL_OR_KEYWORD)
                  and p.name != "self"]
    except (TypeError, ValueError):
        params = []
    widget = factory(ctx) if params else factory()
    if not isinstance(widget, QWidget):
        print(f"{a.target} did not return a QWidget", file=sys.stderr)
        return 2
    w, h = (int(v) for v in a.size.lower().split("x"))
    widget.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen, True)
    widget.resize(w, h)
    widget.show()
    end = time.monotonic() + 0.4
    while time.monotonic() < end:
        app.processEvents()
        time.sleep(0.02)
    out = Path(a.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    if not widget.grab().save(str(out), "PNG"):
        print(f"could not write {out}", file=sys.stderr)
        return 1
    print(out)
    for line in clipped_labels(widget):
        print(line)
    widget.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
