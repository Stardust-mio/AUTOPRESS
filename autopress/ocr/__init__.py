# OWNED BY G2
"""OCR (G2): RapidOCR engine wrapper, the single-worker OCR service, text finding, image I/O.

Never import rapidocr / onnxruntime at module import time of anything else: engine.py imports
them lazily inside OcrEngine.__init__ so the app starts fast and tests without OCR stay fast.
"""
