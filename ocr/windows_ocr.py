#!/usr/bin/env python3
"""
ocr/windows_ocr.py — Windows.Media.Ocr, the recogniser already in the operating system.

Measured on the reported laptop, both engines in one process, on identical saved
crops, with the machine quiet in every row. Both found the same lines:

    a dialogue box, 1366x277, 4 lines      24.6 ms  against   538.8 ms   22x
    a screen of small dense text, 15 lines 39.9 ms  against  1479.6 ms   37x

The gap widens with the amount of text because RapidOCR pays per line and this
barely does. It is not a tuning difference but a different class of thing: the
model is part of Windows, already resident, and built for screen text rather
than for photographs of signage.

**A first, wrong version of this comparison said 163x.** It timed RapidOCR while
the game was rendering and the machine was at 99%, and the native engine after
the game had been closed — two conditions, one ratio, and the ratio was
meaningless. Contention is worth roughly an order of magnitude here on its own,
so it has to be held still. Under six spinning threads, which is a harsher load
than the game and only a stand-in for it, the same pair reads 2338 ms against
10487 ms: the native engine degrades *more* in relative terms, and stays far
ahead in absolute ones.

It is also **more accurate here**, which is the part that decides it. RapidOCR
reads Portuguese through a Chinese model whose dictionary has no room for the
accents, so it returns "chao", "lamina", "inutilizavel"; this returns "chão",
"lâmina", "inutilizável". The matcher normalises accents away and so never
minded, but `live.py` cuts values out of the *original* screen text, and a hero's
name spoken without its accents is audible.

No model to download either — the 19 MB of ONNX weights stop being needed on
Windows, and there is nothing to keep in step with a pip upgrade.

    pip install -e '.[ocr]'

## The recogniser is a Windows feature, not a package

`OcrEngine` can only read languages Windows has a recogniser installed for, and
without one `try_create_from_language` returns None rather than raising — which
is why the error below has to be written by hand.

The capability has its own name, and it is worth using rather than the graphical
path. Read off a Windows 11 machine:

    Get-WindowsCapability -Online -Name "Language*pt*"

    Language.Handwriting~~~pt-PT~0.0.1.0   NotPresent
    Language.OCR~~~pt-BR~0.0.1.0           NotPresent      <- the only one wanted
    Language.OCR~~~pt-PT~0.0.1.0           NotPresent
    Language.Speech~~~pt-BR~0.0.1.0        NotPresent
    Language.TextToSpeech~~~pt-BR~0.0.1.0  NotPresent

So `Language.OCR~~~<tag>~0.0.1.0`, in an elevated PowerShell, and none of the
other five do anything for this project:

    Add-WindowsCapability -Online -Name "Language.OCR~~~pt-BR~0.0.1.0"

`Settings -> Time & language -> Language & region -> (a language) -> Language
options -> Optional features -> Basic typing` is the same thing through the
interface, and it is what to say to somebody who is not at a prompt.

## Importing this before onnxruntime breaks onnxruntime

Measured, three processes, one question each:

    onnxruntime alone                    ok
    onnxruntime, then winrt              ok
    winrt, then onnxruntime              ImportError: DLL load failed while
                                         importing onnxruntime_pybind11_state

So the order is load-bearing, and it matters precisely when things are going
wrong: `open_ocr` tries this engine first and falls back to RapidOCR, and a
fallback that cannot be imported is worse than no fallback at all — it turns a
missing language pack into a dead narrator.

`_reserve_onnxruntime` therefore imports onnxruntime *before* any winrt module
is touched, whenever it is installed. It costs about a second, once, and it buys
a fallback that still works.

The likely mechanism is the static-TLS budget Windows reserves for dynamically
loaded DLLs: winrt arrives as a crowd of small extension modules, and
onnxruntime's pybind module wants static thread-local storage that is no longer
there. ERROR_DLL_INIT_FAILED is what that looks like from Python. That part is a
reading of the symptom and not a measurement — but the ordering above is
measured, and the ordering is what the code depends on.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from .base import Line, Ocr, OcrError


def _reserve_onnxruntime() -> None:
    """Get onnxruntime's DLLs in before winrt's, so the fallback survives.

    Silent on purpose: if onnxruntime is not installed there is nothing to
    reserve and nothing to say, and if it fails to import for its own reasons
    then RapidOCR was never going to be a fallback anyway. Neither is a reason
    to stop the engine that is about to work.
    """
    try:
        import onnxruntime  # noqa: F401
    except Exception:  # noqa: BLE001
        pass


@dataclass
class WindowsOcr(Ocr):
    languages: tuple[str, ...] = ("pt-BR",)
    _engine: object | None = field(default=None, init=False)
    settings: str = field(default="", init=False)
    # Not a failure, so not an exception; not a detail, so not `settings`. The
    # narrator prints this in its own right, because the whole cost of the case
    # it reports is that nothing looks wrong.
    warning: str = field(default="", init=False)

    def __post_init__(self) -> None:
        _reserve_onnxruntime()          # must precede every winrt import below
        try:
            from winrt.windows.globalization import Language
            from winrt.windows.media.ocr import OcrEngine
        except ImportError as exc:
            raise OcrError(
                "the WinRT bindings are not installed. They are how Python "
                "reaches Windows.Media.Ocr, which is the fast OCR on this "
                "platform.\n"
                "    pip install -e '.[ocr]'") from exc

        installed = [x.language_tag
                     for x in OcrEngine.available_recognizer_languages]
        # Best first, as `locales_for` orders them. A tag Windows has no
        # recogniser for returns None rather than raising, so this cannot be a
        # try/except.
        #
        # `wanted` is the first entry and the only one that is not a compromise.
        # Settling for anything else used to be silent, because from here it
        # looked like success — the loop's second choice worked. `locales_for` no
        # longer offers a second choice on Windows, and this records the
        # difference so the caller can say it out loud rather than print a tag
        # nobody reads.
        wanted = self.languages[0] if self.languages else None
        engine = None
        for tag in self.languages:
            engine = OcrEngine.try_create_from_language(Language(tag))
            if engine is not None:
                break
        if engine is None:
            # Whatever the user's own language settings offer, before giving up:
            # reading the screen in the wrong language still beats silence, as
            # long as nobody is left thinking it read the right one.
            engine = OcrEngine.try_create_from_user_profile_languages()

        if engine is None:
            raise OcrError(
                f"Windows has no OCR recogniser installed"
                + (f" for {', '.join(self.languages)}" if self.languages else "")
                + f". It has: {', '.join(installed) or 'none at all'}.\n"
                + (f"    In an elevated PowerShell:\n"
                   f"    Add-WindowsCapability -Online -Name "
                   f"\"Language.OCR~~~{self.languages[0]}~0.0.1.0\"\n"
                   if self.languages else "")
                + f"    Or: Settings -> Time & language -> Language & region\n"
                f"    -> the language -> Language options -> Optional features\n"
                f"    -> add 'Basic typing'\n"
                f"Or run the narrator with --ocr rapid to use the portable "
                f"engine, which is slower but needs nothing installed.")

        self._engine = engine
        self._max = int(OcrEngine.max_image_dimension)
        got = engine.recognizer_language.language_tag
        self.settings = f"language {got}"

        # The one case worth interrupting somebody over. It is not a slow path or
        # a broken one — it reads, and it reads the wrong language, and the only
        # visible symptom is accents quietly going missing from names the voice
        # then says wrong.
        if wanted is None:
            self.warning = (
                f"this language has no Windows OCR recogniser at all, so the "
                f"screen is being read as {got}. Accented words will come back "
                f"without their accents, and the voice will say them that way. "
                f"--ocr rapid reads it in a Latin-script model instead.")
        elif got.lower() != wanted.lower():
            self.warning = (
                f"asked Windows for {wanted} and got {got}: the {wanted} "
                f"recogniser is not installed. It reads, but accented words come "
                f"back without their accents, and the voice says them that way.\n"
                f"    In an elevated PowerShell:\n"
                f"    Add-WindowsCapability -Online -Name "
                f"\"Language.OCR~~~{wanted}~0.0.1.0\"\n"
                f"    Installed now: {', '.join(installed) or 'none'}")

    def read(self, image: np.ndarray) -> list[Line]:
        from winrt.windows.graphics.imaging import (BitmapPixelFormat,
                                                    SoftwareBitmap)
        from winrt.windows.storage.streams import DataWriter

        h, w = image.shape[:2]
        if max(h, w) > self._max:
            raise OcrError(
                f"the crop is {w}x{h} and Windows.Media.Ocr reads at most "
                f"{self._max} on a side. Narrow --region, or use --ocr rapid.")

        # Bgra8 rather than Gray8: every OcrEngine build accepts it, and the
        # conversion is a broadcast into a preallocated array, which does not
        # show up beside a 24 ms recognition.
        bgra = np.empty((h, w, 4), dtype=np.uint8)
        bgra[..., 0] = bgra[..., 1] = bgra[..., 2] = image
        bgra[..., 3] = 255
        writer = DataWriter()
        writer.write_bytes(bgra.tobytes())
        # `create_copy_from_buffer` copies, so the bitmap does not hold a
        # reference into a numpy array the caller is free to drop. This project
        # has already lost a day to a native object outliving what it pointed at.
        bitmap = SoftwareBitmap.create_copy_from_buffer(
            writer.detach_buffer(), BitmapPixelFormat.BGRA8, w, h)

        # `.get()` blocks. The narrator is a plain synchronous frame loop, and
        # an event loop built and torn down per screen would be both the wrong
        # shape and a lifetime problem, for a call that takes 24 ms.
        result = self._engine.recognize_async(bitmap).get()

        lines = []
        for ocr_line in result.lines:
            # An OcrLine carries no rectangle of its own — only its words do —
            # so the line's box is their union.
            rects = [word.bounding_rect for word in ocr_line.words]
            if not rects:
                continue
            x0 = min(r.x for r in rects)
            x1 = max(r.x + r.width for r in rects)
            y0 = min(r.y for r in rects)
            y1 = max(r.y + r.height for r in rects)
            # Windows OCR scores nothing, and nothing in this project reads a
            # confidence — both other engines' scores are written and never
            # looked at. 1.0 keeps the dataclass honest about what is known.
            lines.append(Line(text=ocr_line.text, confidence=1.0,
                              bbox=(x0 / w, 1.0 - y1 / h,
                                    (x1 - x0) / w, (y1 - y0) / h)))
        return lines
