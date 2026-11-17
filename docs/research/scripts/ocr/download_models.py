"""Pre-download extra RapidOCR ONNX models (SHA256-verified) into a local folder.

The rapidocr wheel already bundles PP-OCRv6 det/rec "small" + the v2.0 cls model.
This script fetches the alternatives used by the benchmark (from ModelScope, the
URLs listed in rapidocr/default_models.yaml) so that everything afterwards runs
offline from explicit model paths.

Usage:
    python download_models.py OUT_DIR
Prints one line per file: name, size in bytes.
"""
import sys
from pathlib import Path

from rapidocr.inference_engine.base import FileInfo, InferSession
from rapidocr.utils.download_file import DownloadFile, DownloadFileInput
from rapidocr.utils.log import logger
from rapidocr.utils.typings import EngineType, LangRec, ModelType, OCRVersion, TaskType

COMBOS = [
    (TaskType.DET, OCRVersion.PPOCRV6, ModelType.TINY, "ch"),
    (TaskType.DET, OCRVersion.PPOCRV6, ModelType.MEDIUM, "ch"),
    (TaskType.REC, OCRVersion.PPOCRV6, ModelType.TINY, "ch"),
    (TaskType.REC, OCRVersion.PPOCRV6, ModelType.MEDIUM, "ch"),
    (TaskType.DET, OCRVersion.PPOCRV5, ModelType.MOBILE, "ch"),
    (TaskType.REC, OCRVersion.PPOCRV5, ModelType.MOBILE, "ch"),
    (TaskType.REC, OCRVersion.PPOCRV5, ModelType.MOBILE, "korean"),
]


def main():
    out = Path(sys.argv[1])
    out.mkdir(parents=True, exist_ok=True)
    for task, ver, mtype, lang in COMBOS:
        info = InferSession.get_model_url(FileInfo(EngineType.ONNXRUNTIME, ver, task, lang, mtype))
        url = info["model_dir"]
        dst = out / Path(url).name
        DownloadFile.run(DownloadFileInput(file_url=url, save_path=dst, logger=logger, sha256=info.get("SHA256")))
        print("%-45s %d" % (dst.name, dst.stat().st_size))


if __name__ == "__main__":
    main()
