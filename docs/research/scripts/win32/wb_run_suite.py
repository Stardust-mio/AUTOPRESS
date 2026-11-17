"""wb_run_suite.py - runs wb_qt_probe.py in child processes under several environments and
prints a compact summary. Results (JSON) go to OUT_DIR (default: %TEMP%/wb_out).

usage: python wb_run_suite.py [OUT_DIR] [variant ...]
variants: base import before after sf125 sf150 mixed (visible) + sf125h sf150h mixedh sf175h (hidden only)
Visible variants (base, sf125, sf150, mixed) briefly show a 400x150 no-focus,
input-transparent window per screen; nothing is activated and no input is injected.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
PY = sys.executable
VARIANTS = {
    "base": ({}, ["--visible", "--timing"]),
    "import": ({}, ["--mss", "import"]),
    "before": ({}, ["--mss", "before"]),
    "after": ({}, ["--mss", "after"]),
    "sf125": ({"QT_SCALE_FACTOR": "1.25"}, ["--visible"]),
    "sf150": ({"QT_SCALE_FACTOR": "1.5"}, ["--visible"]),
    "mixed": ({"QT_SCREEN_SCALE_FACTORS": "1.5;1.25"}, ["--visible"]),
    "sf125h": ({"QT_SCALE_FACTOR": "1.25"}, []),
    "sf150h": ({"QT_SCALE_FACTOR": "1.5"}, []),
    "mixedh": ({"QT_SCREEN_SCALE_FACTORS": "1.5;1.25"}, []),
    "sf175h": ({"QT_SCALE_FACTOR": "1.75"}, []),
}


def main() -> None:
    out_dir = sys.argv[1] if len(sys.argv) > 1 else os.path.join(tempfile.gettempdir(), "wb_out")
    names = sys.argv[2:] or list(VARIANTS)
    os.makedirs(out_dir, exist_ok=True)
    for name in names:
        extra_env, extra_args = VARIANTS[name]
        env = {k: v for k, v in os.environ.items() if not k.startswith("QT_")}
        env.update(extra_env, PYTHONIOENCODING="utf-8")
        out = os.path.join(out_dir, f"wb_{name}.json")
        if os.path.exists(out):
            os.remove(out)
        p = subprocess.run([PY, os.path.join(HERE, "wb_qt_probe.py"), out, *extra_args], env=env,
                           capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=180)
        print(f"=== {name} rc={p.returncode} env={extra_env}")
        if p.stderr.strip():
            print("  stderr:", p.stderr.strip()[-600:])
        if not os.path.exists(out):
            print("  NO JSON")
            continue
        r = json.load(open(out, encoding="utf-8"))
        print("  completed:", r.get("completed", False), "| qt", r.get("qt_version"), r.get("rounding_policy"))
        for k in ("pre_qt", "after_import_mss", "post_qt", "after_mss_ctor"):
            if k in r:
                print(f"  {k}: {r[k]}")
        for s in r.get("screens", []):
            print(f"  screen {s['name']} geo={s['geometry']} dpr={s['dpr']} win32={s['win32_rect']} "
                  f"origin_equal={s['origin_equal']} size*dpr={s['size_times_dpr']}")
        for m in r.get("mapping", []):
            print(f"  map {m['screen']} (win screen {m['window_screen']}) dpr={m['dpr']} top L={m['logical_top']} "
                  f"meas={m['measured_top_client'][:2]} pred={m['predicted_top']} naive={m['naive_global_scale_top']} | child L="
                  f"{m['logical_child']} meas={m['measured_child_client'][:2]} pred={m['predicted_child']} | size meas="
                  f"{m['measured_top_client'][2:]} ok={m['ok_top']},{m['ok_child']},{m['ok_size']} dpi={m['window_dpi']} "
                  f"aw={m['window_awareness']} vis={m['visible_flag']} IsWindow_after_delete={m['IsWindow_after_delete']}")
        for o in r.get("overlay", []):
            bad = [c for c in o["cases"] if not c["ok"]]
            print(f"  overlay {o['screen']} dpr={o['dpr']} logical={o['overlay_logical']} phys={o['overlay_physical']} "
                  f"mon={o['monitor_physical']} cases_ok={len(o['cases']) - len(bad)}/{len(o['cases'])} bad={bad}")
        for c in r.get("cursor", [])[:3]:
            print(f"  cursor {c}")
        for c in r.get("capture", []):
            print(f"  capture {json.dumps(c)[:900]}")
        if "timing" in r:
            t = dict(r["timing"])
            t.pop("mss_monitors", None)
            print(f"  timing {t}")
            print(f"  mss_monitors {r['timing']['mss_monitors']}")
        if r.get("qt_messages"):
            print("  qt_messages:", r["qt_messages"][:6])


if __name__ == "__main__":
    main()
