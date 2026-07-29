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


def _tuned_config():
    """RapidOCR's own config, with the two settings this workload cannot afford.

    Reported from a Windows laptop, and it is the whole delay: `ocr 13.48s`,
    `19.41s`, `16.20s`, `18.49s` per screen, against 0.35 s for Apple Vision on a
    Mac. Two of RapidOCR's defaults are wrong for a wide, short crop.

    **`limit_type: min`, side 736.** It scales so the *shortest* side reaches
    736. The dialogue-box crop is about 1920x389, so the short side is 389 and
    the image is **enlarged** by 1.9 to roughly 3629x736 — 2.7 megapixels of
    detection where 0.75 were handed in. Asking for the *longest* side instead
    scales down rather than up.

    **`use_angle_cls: true`.** A whole extra model pass per text box, deciding
    whether the line is upside down. A game's dialogue box is never upside down.

    Both were measured on a Mac when this was first suspected and dismissed —
    315ms to 287ms, fidelity 99.7 either way — because a fast machine has the
    headroom to hide them. The laptop does not, and the fidelity result is the
    part that carries over: nothing is being traded away here.

    Written next to the models rather than into the installed package, so a
    `pip install --upgrade` cannot silently take it away or keep it.
    """
    import json
    from pathlib import Path

    # Returns None if anything about this is not as expected — a config layout
    # that moved, a missing yaml, a read-only install. A slow OCR is a complaint;
    # an OCR that will not start is a dead narrator.
    try:
        import yaml

        import rapidocr_onnxruntime as R

        here = Path(__file__).resolve().parent / ".rapidocr.yaml"
        stock = Path(R.__file__).resolve().parent / "config.yaml"
        stamp = json.dumps({"src": stock.stat().st_mtime_ns, "v": 2})
        if here.exists() and here.read_text(
                encoding="utf-8").startswith(f"# {stamp}"):
            return here

        cfg = yaml.safe_load(stock.read_text(encoding="utf-8"))
        cfg["Global"]["use_angle_cls"] = False
        cfg["Det"]["limit_type"] = "max"
        cfg["Det"]["limit_side_len"] = 1280
        here.write_text(f"# {stamp}\n" + yaml.safe_dump(cfg, allow_unicode=True),
                        encoding="utf-8")
        return here
    except Exception:  # noqa: BLE001
        return None


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
        tuned = _tuned_config()
        self._engine = (RapidOCR(config_path=str(tuned)) if tuned
                        else RapidOCR())

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
