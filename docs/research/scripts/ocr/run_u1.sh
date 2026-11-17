#!/usr/bin/env bash
# End-to-end U1 benchmark (Git Bash). Usage:
#   bash run_u1.sh WORK_DIR RAPID_PY [WINOCR_PY] [TESS_PY]
# WORK_DIR  : scratch folder (images, downloaded models, results) - use C:/... style paths
# RAPID_PY  : python.exe of a venv with rapidocr==3.10.0 onnxruntime==1.32.0
# WINOCR_PY : optional python.exe of a venv with the pywinrt OCR packages ("" to skip)
# TESS_PY   : optional python.exe of a venv with tesserocr==2.13.0 (tessdata_fast is downloaded)
# LIMIT=N (env) runs only the first N images (smoke test); default all 240.
set -euo pipefail
W="$1"; RP="$2"; WP="${3:-}"; TP="${4:-}"
L="--limit ${LIMIT:-0}"
D="$(cd "$(dirname "$0")" && (pwd -W 2>/dev/null || pwd))"
export PYTHONIOENCODING=utf-8
"$RP" "$D/download_models.py" "$W/models_dl" > /dev/null 2>&1
M="$W/models_dl"
[ -f "$W/u1/labels.json" ] || "$RP" "$D/gen_u1_codes.py" "$W/u1"
if [ -n "$WP" ]; then "$WP" "$D/bench_u1.py" "$W/u1" "$W/res" --engine win_zh-Hant-TW $L; fi
for E in rapid_v6s rapid_v6s@max960 rapid_v6t; do
  "$RP" "$D/bench_u1.py" "$W/u1" "$W/res" --engine "$E" --models "$M" $L
done
for E in rapid_v5m rapid_v6m@max960; do
  "$RP" "$D/bench_u1.py" "$W/u1" "$W/res" --engine "$E" --pre none --models "$M" $L
done
if [ -n "$TP" ]; then
  mkdir -p "$W/tessdata"
  for T in eng chi_tra; do
    [ -f "$W/tessdata/$T.traineddata" ] || curl -sL -o "$W/tessdata/$T.traineddata" \
      "https://github.com/tesseract-ocr/tessdata_fast/raw/main/$T.traineddata"
  done
  AUTOPRESS_TESSDATA="$W/tessdata/" "$TP" "$D/bench_u1.py" "$W/u1" "$W/res" --engine "tess_eng+chi_tra" \
    --pre none,up2,up3 $L
fi
"$RP" "$D/report_u1.py" "$W/u1/labels.json" "$W/res" > "$W/res/report_u1.md"
echo "report: $W/res/report_u1.md"
