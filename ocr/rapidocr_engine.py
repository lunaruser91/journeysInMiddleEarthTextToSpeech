#!/usr/bin/env python3
"""
ocr/rapidocr_engine.py — RapidOCR, for everywhere that is not macOS.

**Exercised on Windows 11, where it is the engine.** It read a rendered
line back with every keyword intact. Not yet run against a real game screen,
which is a harder problem than clean text on a flat background. ~19 MB of ONNX weights, Apache-2.0, runs on CPU.
It is the portable fallback; on Windows the native `Windows.Media.Ocr` is likely
faster and is not wrapped here yet.

RapidOCR returns a four-point polygon per line in **pixels**, with the origin at
the top left. `base.Line` expects a normalised box with the origin at the bottom
left, so the conversion happens here — keeping `group_paragraphs` free of any
engine's conventions.

    pip install rapidocr-onnxruntime
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from .base import Line, Ocr, OcrError


@dataclass
class RapidOcr(Ocr):
    _engine: object | None = field(default=None, init=False)

    def __post_init__(self) -> None:
        try:
            from rapidocr_onnxruntime import RapidOCR
        except ImportError as exc:
            raise OcrError(
                "rapidocr-onnxruntime is not installed. It is the portable OCR "
                "fallback for platforms without Apple Vision.\n"
                "    pip install rapidocr-onnxruntime") from exc
        self._engine = RapidOCR()

    def read(self, image: np.ndarray) -> list[Line]:
        result, _elapsed = self._engine(image)
        if not result:
            return []
        h, w = image.shape[:2]
        lines = []
        for box, text, score in result:
            xs = [p[0] for p in box]
            ys = [p[1] for p in box]
            x0, x1 = min(xs), max(xs)
            y0, y1 = min(ys), max(ys)
            # pixels, top-left origin  ->  fractions, bottom-left origin
            lines.append(Line(text=text, confidence=float(score),
                              bbox=(x0 / w, 1.0 - y1 / h,
                                    (x1 - x0) / w, (y1 - y0) / h)))
        return lines
