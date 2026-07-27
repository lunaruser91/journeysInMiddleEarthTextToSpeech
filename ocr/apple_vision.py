#!/usr/bin/env python3
"""
ocr/apple_vision.py — Apple Vision, through the `ocrmac` wrapper.

Offline, native pt-BR, no model to download, 150-350 ms for a game screen. It is
the engine the briefing recommends on macOS and the one every measurement in this
project was made with.

`ocrmac` takes a file path, so frames are written to a temporary PNG. That costs
a few milliseconds and buys a lot of robustness: Vision refuses several formats
the game screenshots come in — `.webp` among them — and PIL converts everything
on the way through.
"""
from __future__ import annotations

import tempfile
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from .base import Line, Ocr, OcrError


@dataclass
class AppleVision(Ocr):
    languages: tuple[str, ...] = ("pt-BR",)
    _tmp: Path = field(default_factory=lambda: Path(tempfile.gettempdir()) /
                       "_jime_ocr_frame.png", init=False)

    def __post_init__(self) -> None:
        try:
            from ocrmac import ocrmac  # noqa: F401
        except ImportError as exc:
            raise OcrError(
                "ocrmac is not installed. It wraps Apple Vision, which is the "
                "offline pt-BR OCR this project measured against.\n"
                "    pip install ocrmac") from exc

    def read(self, image: np.ndarray) -> list[Line]:
        from ocrmac import ocrmac
        from PIL import Image

        Image.fromarray(image).convert("RGB").save(self._tmp)
        raw = ocrmac.OCR(str(self._tmp),
                         language_preference=list(self.languages)).recognize()
        # ocrmac yields (text, confidence, bbox) with bbox normalised and the
        # origin at the bottom left — already the convention base.Line expects.
        return [Line(text=t, confidence=float(c), bbox=tuple(b))
                for t, c, b in raw if t and t.strip()]
