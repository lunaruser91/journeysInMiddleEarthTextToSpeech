#!/usr/bin/env python3
"""
ocr/rapidocr_engine.py — RapidOCR, for everywhere that is not macOS.

Measured on Windows 11 against real game screens, not only against clean text on
a flat background: a dialogue box in 3.9 s tuned and 12.3 s as it ships. ~19 MB
of ONNX weights, Apache-2.0, runs on CPU.

It is the portable fallback, and on Windows that is now all it is: the native
`Windows.Media.Ocr` reads the same crop in 25 ms against this engine's 539 ms,
and reads it better. See ocr/windows_ocr.py. This is what runs where no native
recogniser is available — Linux, or a Windows without the language feature
installed — and the tuning below is what makes that bearable rather than fast.

Its defaults are tuned for photographs of Chinese signage and are wrong for a
wide, short crop of a dialogue box — badly enough to be the whole of this
project's Windows latency. See `TUNING`, which must be passed as keyword
arguments: RapidOCR accepts no config file, whatever it looks like it accepts.

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


# The two settings this workload cannot afford, and one that its shape makes
# expensive.
#
# **`det_limit_type`, `det_limit_side_len`.** RapidOCR ships `min` at side 736:
# it scales until the *shortest* side reaches 736. A dialogue-box crop is wide
# and short — 1366x277 on the laptop this was measured on — so the short side is
# 277 and the image is **enlarged** 2.7x, to 736x3616. That is 2.7 megapixels of
# detection where 0.38 were handed in. Asking for the longest side scales down
# instead, and the detector goes from 5230 ms to 1004 ms.
#
# Bounding the *longest* side also makes the text a fixed size in pixels
# whatever the display is: a line is a constant fraction of the screen's width,
# so normalising by width hands the recogniser the same glyph height at 1366 as
# at 1920. Bounding the shortest side would not — the crop's height depends on
# REGION, and the same setting would mean two different things.
#
# 1280 rather than 960: on the game's dialogue box the two are within noise of
# each other (3.79 s against 3.71 s, fidelity 99.0 either way), but on a screen
# of small dense text 960 read less of it. Time that is inside the noise is not
# worth paying for in text.
#
# **`use_angle_cls`.** A whole extra model pass per text box, deciding whether
# the line is upside down. A game's dialogue box is never upside down.
#
# **`rec_batch_num`.** The recogniser pads every crop in a batch out to the
# widest aspect ratio in that batch, so one full-width line makes every short
# line cost full width too. Measured on a real dialogue box, whose four lines
# were 177, 207, 1270 and 1426 wide: 4495 ms as one padded batch of four,
# 2534 ms one at a time. A dialogue box always has this shape — long prose lines
# beside short buttons — so the padding is not an unlucky case here, it is the
# normal one.
#
# Names, not a config file: `RapidOCR.__init__` takes `**kwargs` and hardcodes
# its own config path (rapid_ocr_api.py:22). There is no `config_path`
# parameter — passing one lands it in kwargs, where `UpdateParameters` files it
# under Global as a key nothing reads. That is how this project spent a day
# measuring a tuning that never arrived.
#
# `det_model_path` and `rec_model_path` are not optional here. `update_det_params`
# reads `det_dict['model_path']` unconditionally (utils.py:251), so passing any
# `det_*` without it raises KeyError; None means "keep the packaged model".
TUNING = dict(
    use_angle_cls=False,
    det_model_path=None,
    det_limit_type="max",
    det_limit_side_len=1280,
    rec_model_path=None,
    rec_batch_num=1,
)


def _took_effect(engine) -> str:
    """What the engine is actually configured to do, read back off the engine.

    A setting that is claimed rather than shown is exactly what went wrong here,
    so the caller can print this and see the real numbers. Returns "" if the
    library's internals have moved, which is a reason to look rather than to
    fail.
    """
    try:
        resize = next(op for op in engine.text_detector.preprocess_op
                      if hasattr(op, "limit_type"))
        return (f"det {resize.limit_type} {int(resize.limit_side_len)}, "
                f"angle_cls {engine.use_angle_cls}, "
                f"rec_batch {engine.text_recognizer.rec_batch_num}")
    except Exception:  # noqa: BLE001
        return ""


@dataclass
class RapidOcr(Ocr):
    _engine: object | None = field(default=None, init=False)
    settings: str = field(default="", init=False)

    def __post_init__(self) -> None:
        try:
            from rapidocr_onnxruntime import RapidOCR
        except ImportError as exc:
            raise OcrError(
                "rapidocr-onnxruntime is not installed. It is the portable OCR "
                "fallback for platforms without Apple Vision.\n"
                "    pip install rapidocr-onnxruntime") from exc
        # A slow OCR is a complaint; an OCR that will not start is a dead
        # narrator. If a future version renames these keywords, take the stock
        # engine rather than nothing — but say so, because the stock engine is
        # 4.6x slower and a silent fallback here is the whole bug again.
        try:
            self._engine = RapidOCR(**TUNING)
            self.settings = _took_effect(self._engine)
        except Exception as exc:  # noqa: BLE001
            self._engine = RapidOCR()
            self.settings = (f"stock settings — {type(exc).__name__}: {exc}. "
                             f"Expect several seconds per screen.")

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
