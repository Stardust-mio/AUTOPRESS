"""Print the character coverage of PP-OCR recognizer ONNX models (dictionary embedded in the metadata).

Usage:
    python model_vocab.py MODEL.onnx [MODEL.onnx ...]
"""
import sys
from pathlib import Path

import onnxruntime as ort

PROBE = "兌換確認領取獎勵"


def main():
    for p in sys.argv[1:]:
        s = ort.InferenceSession(p, providers=["CPUExecutionProvider"])
        ch = s.get_modelmeta().custom_metadata_map["character"].splitlines()
        S = {c for c in ch if len(c) == 1}

        def count(lo, hi):
            return sum(1 for c in S if lo <= ord(c) <= hi)
        missing = [c for c in PROBE if c not in S]
        print("%s: %d entries, CJK %d, hiragana %d, katakana %d, hangul %d, missing from %s: %s" % (
            Path(p).name, len(ch), count(0x4E00, 0x9FFF), count(0x3040, 0x309F), count(0x30A0, 0x30FF),
            count(0xAC00, 0xD7A3), PROBE, "".join(missing) or "none"))


if __name__ == "__main__":
    main()
