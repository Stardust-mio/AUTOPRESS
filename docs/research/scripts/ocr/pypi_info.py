"""Query PyPI JSON API for OCR candidate packages and write a summary.

Usage (any Python 3.10+, no third-party deps):
    python pypi_info.py OUT.json [pkg ...]

Writes OUT.json (full summary) and prints a compact table (ASCII only).
For each package: latest version, upload time, license fields, requires_python,
requires_dist, and the wheel files relevant to Windows x64 / CPython 3.12
(win_amd64 cp312 or py3-none-any) with their sizes.
"""
import json
import sys
import urllib.request

DEFAULT_PKGS = [
    "rapidocr", "rapidocr_onnxruntime", "onnxruntime", "opencv-python",
    "opencv-python-headless", "paddleocr", "paddlepaddle", "easyocr",
    "cnocr", "cnstd", "onnxocr", "pytesseract", "tesserocr", "python-doctr",
    "surya-ocr", "winocr", "winrt-runtime", "winrt-Windows.Media.Ocr",
    "torch", "shapely", "pyclipper", "omegaconf", "PyYAML", "six", "tqdm",
    "requests", "colorlog", "Pillow", "numpy", "flatbuffers", "protobuf",
    "sympy", "coloredlogs", "packaging",
]


def fetch(name):
    url = "https://pypi.org/pypi/%s/json" % name
    req = urllib.request.Request(url, headers={"User-Agent": "pypi-info-script"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read().decode("utf-8"))


def relevant_files(files):
    out = []
    for f in files:
        fn = f["filename"]
        if f.get("packagetype") == "bdist_wheel":
            if ("win_amd64" in fn and ("cp312" in fn or "abi3" in fn or "py3" in fn)) or fn.endswith("none-any.whl"):
                out.append({"filename": fn, "size": f["size"], "upload_time": f.get("upload_time_iso_8601")})
        elif f.get("packagetype") == "sdist":
            out.append({"filename": fn, "size": f["size"], "upload_time": f.get("upload_time_iso_8601")})
    return out


def main():
    out_path = sys.argv[1]
    pkgs = sys.argv[2:] or DEFAULT_PKGS
    summary = {}
    for p in pkgs:
        try:
            d = fetch(p)
        except Exception as e:  # noqa: BLE001
            summary[p] = {"error": repr(e)}
            print("%-26s ERROR %r" % (p, e))
            continue
        info = d["info"]
        files = relevant_files(d.get("urls", []))
        classifiers = [c for c in info.get("classifiers") or [] if c.startswith("License")]
        lic = info.get("license_expression") or info.get("license") or ""
        if lic and len(lic) > 80:
            lic = lic[:80] + "..."
        summary[p] = {
            "version": info["version"],
            "license": lic,
            "license_classifiers": classifiers,
            "requires_python": info.get("requires_python"),
            "requires_dist": info.get("requires_dist"),
            "home_page": info.get("home_page") or (info.get("project_urls") or {}),
            "files": files,
            "summary": info.get("summary"),
        }
        upl = files[0]["upload_time"][:10] if files and files[0].get("upload_time") else "?"
        win = [f for f in files if f["filename"].endswith(".whl")]
        size = ",".join("%.1fMB" % (f["size"] / 1e6) for f in win[:2]) or "no-wheel"
        print("%-26s %-12s %-10s %-14s lic=%s" % (p, info["version"], upl, size,
                                                  (lic or ";".join(classifiers))[:40].encode("ascii", "replace").decode()))
    with open(out_path, "w", encoding="utf-8") as fh:
        json.dump(summary, fh, ensure_ascii=False, indent=1)


if __name__ == "__main__":
    main()
