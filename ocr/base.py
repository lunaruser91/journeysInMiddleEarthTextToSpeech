#!/usr/bin/env python3
"""
ocr/base.py — the contract for "turn this image into text", and the paragraph
reconstruction that every engine needs.

## Every engine returns lines, and lines are the wrong unit

This is not an implementation detail worth hiding: OCR engines return one result
per **line of text**, with a bounding box. The matcher wants **paragraphs**,
because a paragraph is what maps to a corpus block.

Joining lines with "\\n" and calling each one a paragraph looks reasonable and
fails immediately. A 60-character line matched against a 150-character block
gives a length ratio of 0.4 and the matcher's guard rejects it — a perfect score
thrown away. This was caught on the very first real screenshot, and it is why
`group_paragraphs` lives here rather than in any single engine.

The grouping uses geometry: consecutive lines separated by more than about 60% of
a typical line height belong to different paragraphs.

## Choosing an engine

Apple Vision on macOS: offline, native pt-BR, ~150-350 ms, no model to download,
and it accepts custom words — worth feeding the Tolkien proper nouns eventually.

Windows.Media.Ocr on Windows: offline, part of the operating system, 25 ms on a
dialogue box and 40 ms on a screen of dense small text — against RapidOCR's
539 ms and 1480 ms on the identical crops with the machine held equally quiet —
and more accurate on accented text besides. It needs a language recogniser
installed as a Windows optional feature, which is the one thing that can make it
unavailable.

RapidOCR anywhere: ~19 MB of ONNX weights, Apache-2.0, works on Windows and
Linux. It is the fallback now rather than the Windows engine: 22x slower on a
dialogue box, 37x on a dense screen, and the gap grows with the amount of text
because it pays per line.

**Do not reach for a local VLM.** They hallucinate plausible text, which in a
narrator is worse than an OCR error and, unlike an OCR error, undetectable — and
they are roughly ten times slower.
"""
from __future__ import annotations

import platform
from dataclasses import dataclass
from typing import Protocol

import numpy as np


class OcrError(RuntimeError):
    """Raised with a message that says how to fix it."""


@dataclass
class Line:
    """One line of recognised text.

    `bbox` is (x, y, width, height) in fractions of the image, with the origin at
    the **bottom left** — the Vision convention, which RapidOCR is converted to
    so the grouping code stays engine-agnostic.
    """

    text: str
    confidence: float
    bbox: tuple[float, float, float, float]

    @property
    def top(self) -> float:
        return self.bbox[1] + self.bbox[3]

    @property
    def height(self) -> float:
        return self.bbox[3]


class Ocr(Protocol):
    def read(self, image: np.ndarray) -> list[Line]:
        ...


def group_paragraphs(lines: list[Line], gap_factor: float = 0.6) -> list[str]:
    """Rebuild paragraphs from lines, using the vertical gaps between them.

    `gap_factor` is measured against the median line height rather than an
    absolute pixel count, so the same value works at 720p and at 1080p.

    ## Rows, then columns

    Sorting by `y` alone is not enough, and the failure is quiet. An engine
    returns one box per run of text, not one per visual line, so a line broken by
    a glyph or by extra spacing comes back as several boxes whose `y` differs by
    a pixel or two of antialiasing. Ordered by `y` those pixels decide the
    reading order, and the line is rebuilt with its words shuffled.

    It reached a session log: the narrator, capturing the display, read its own
    console and reported `esta campanha voce Qual jogando?` for a window plainly
    showing "Qual campanha você está jogando?". Every screen was passing through
    this, so the matcher was being handed scrambled text and scoring it.

    So boxes are grouped into rows first — within half a line height is the same
    row — and each row is ordered left to right before anything else looks at it.
    """
    items = [ln for ln in lines if ln.text.strip()]
    if not items:
        return []
    items.sort(key=lambda ln: -ln.bbox[1])          # top of the image downwards

    heights = sorted(ln.height for ln in items)
    typical = heights[len(heights) // 2] or 1e-6

    rows, row = [], [items[0]]
    for prev, line in zip(items, items[1:]):
        if (prev.bbox[1] - line.bbox[1]) > typical * 0.5:
            rows.append(row)
            row = [line]
        else:
            row.append(line)
    rows.append(row)
    for r in rows:
        r.sort(key=lambda ln: ln.bbox[0])
    items = [ln for r in rows for ln in r]

    paragraphs, current = [], [items[0].text]
    for prev, line in zip(items, items[1:]):
        gap = (prev.bbox[1] - line.bbox[1]) - typical
        if gap > typical * gap_factor:
            paragraphs.append(" ".join(current))
            current = [line.text]
        else:
            current.append(line.text)
    paragraphs.append(" ".join(current))
    return paragraphs


def crop(image: np.ndarray, region: tuple[float, float, float, float]) -> np.ndarray:
    """Crop by fractions: (left, top, right, bottom), origin at the top left.

    Cropping to the dialogue box is not an optimisation. The map animates on its
    own and the HUD carries counters that change every turn; both feed the OCR
    noise that then has to be filtered back out.
    """
    h, w = image.shape[:2]
    left, top, right, bottom = region
    return image[int(h * top):int(h * bottom), int(w * left):int(w * right)]


def open_ocr(prefer: str = "auto", languages: tuple[str, ...] = ("pt-BR",)) -> Ocr:
    """Pick an engine: 'auto', 'apple', 'windows', or 'rapid'.

    Each platform's native engine first, RapidOCR as the fallback everywhere.
    Naming one explicitly makes its failure fatal rather than silent, because
    "why is it slow" is a much harder question than "why did it refuse".

    That promise has to cover the platform too, and it did not. `--ocr windows`
    on a Mac matched neither branch and fell out of the bottom into RapidOCR: a
    narrator that works, reads twenty times slower, and says nothing about it.
    Naming an engine the machine cannot have is a mistake, not a preference to be
    quietly accommodated.

    The order of the two branches below is not cosmetic. `WindowsOcr` imports
    winrt, and winrt loaded before onnxruntime breaks onnxruntime — so the
    Windows engine reserves onnxruntime first, on purpose, to keep the RapidOCR
    line below reachable. See ocr/windows_ocr.py.
    """
    needs = {"apple": "Darwin", "windows": "Windows"}
    if prefer in needs and needs[prefer] != platform.system():
        raise OcrError(
            f"--ocr {prefer} needs {needs[prefer]} and this is "
            f"{platform.system()}.\n"
            f"    --ocr auto takes whatever this platform has; --ocr rapid "
            f"names the portable engine.")

    if prefer in ("auto", "apple") and platform.system() == "Darwin":
        try:
            from .apple_vision import AppleVision
            return AppleVision(languages=languages)
        except OcrError:
            if prefer == "apple":
                raise
    if prefer in ("auto", "windows") and platform.system() == "Windows":
        try:
            from .windows_ocr import WindowsOcr
            return WindowsOcr(languages=tuple(languages))
        except OcrError:
            if prefer == "windows":
                raise
    from .rapidocr_engine import RapidOcr
    return RapidOcr()


# The game's language codes are not what the OCR engines want. Apple Vision
# takes full locales and rejects a bare "de" with ValueError, so a session in any
# language but Portuguese would have died on its first screen — or worse, run the
# Portuguese recogniser over German text, which is the silent version.
#
# **There are two maps because the two engines really do differ, in both
# directions.** One Apple-shaped map served both for a while, and it was wrong
# each way: it denied Windows a Hungarian recogniser that exists, and promised it
# a Ukrainian one that does not.
#
# Measured against Vision's own supportedRecognitionLanguages on macOS 26:
# twelve of the game's thirteen are there. Hungarian is not, at all.
APPLE_OCR_LOCALE = {
    "cz": "cs-CZ", "de": "de-DE", "en": "en-US", "es": "es-ES", "fr": "fr-FR",
    "it": "it-IT", "ko": "ko-KR", "pl": "pl-PL", "pt": "pt-BR", "ru": "ru-RU",
    "uk": "uk-UA", "zh": "zh-Hans",
    # "hu" is deliberately absent: Apple Vision has no Hungarian recogniser.
}

# Measured on Windows 11 with `Get-WindowsCapability -Online -Name
# "Language.OCR*"`, which lists all 35 recognisers Windows can install:
#
#   - **Hungarian is there** as hu-HU, where Apple has none. The shared map was
#     handing a Hungarian player the English recogniser for no reason at all.
#   - **Ukrainian is not there.** Not as uk-UA, not under any tag. Apple has it;
#     Windows does not publish it, so `uk` is absent below and the engine says so
#     rather than quietly reading Cyrillic with an English model.
#   - **Chinese is zh-CN**, not Apple's script tag zh-Hans. Windows publishes
#     zh-CN, zh-HK and zh-TW; the game's Chinese is simplified, so zh-CN. Whether
#     Language("zh-Hans") would have resolved to it is unknown and not worth
#     depending on when the real tag is right here.
#
# Everything else lines up with Apple's, which is why this looked safe to share.
WINDOWS_OCR_LOCALE = {
    "cz": "cs-CZ", "de": "de-DE", "en": "en-US", "es": "es-ES", "fr": "fr-FR",
    "hu": "hu-HU", "it": "it-IT", "ko": "ko-KR", "pl": "pl-PL", "pt": "pt-BR",
    "ru": "ru-RU", "zh": "zh-CN",
    # "uk" is deliberately absent: Windows publishes no Ukrainian recogniser.
}


def locales_for(lang: str) -> tuple[str, ...]:
    """OCR locales for a game language, best first, for this platform's engine.

    ## Why English is appended on macOS and not on Windows

    Apple Vision takes the whole list and uses it *together*, so a second
    language is a hint and costs nothing — the screens carry proper nouns and
    interface words that read the same either way.

    `Windows.Media.Ocr` takes **one** language per engine, and `WindowsOcr` walks
    this list until one can be created. There, a trailing "en-US" is not a hint:
    it is a silent replacement. On a machine with only the English recogniser
    installed — an English Windows, which is most of them — asking for Portuguese
    got English, the engine reported success because its second choice worked,
    and the only trace was the word `en-US` in a grey line. The accents went with
    it, and `live.py` cuts values out of the *original* screen text, so a hero's
    name reached the voice stripped.

    So on Windows this returns the one locale that is actually wanted, and the
    engine is left to say plainly that it could not have it.
    """
    if platform.system() == "Windows":
        primary = WINDOWS_OCR_LOCALE.get(lang)
        return (primary,) if primary else ()
    primary = APPLE_OCR_LOCALE.get(lang)
    if primary is None:
        return ("en-US",)
    return (primary,) if primary == "en-US" else (primary, "en-US")


def missing_recogniser(lang: str) -> str:
    """Why this platform cannot read `lang`, or "" if it can.

    There are two different ways the screen ends up being read in the wrong
    language, and only an engine can answer the second:

      - **the platform has no recogniser for it at all.** Hungarian on macOS,
        Ukrainian on Windows. That is a property of the maps above, so it is
        knowable before anything is opened, and it is what this reports.
      - **the platform has one and this machine has not installed it.** A
        Portuguese session on an English Windows. Only the engine can see that,
        and `WindowsOcr.warning` is where it says so.

    Both were silent. The second cost two sessions on two machines; the first has
    been true for Hungarian since the map was written and nobody would have found
    out except by listening.
    """
    if platform.system() == "Windows":
        if lang not in WINDOWS_OCR_LOCALE:
            return (f"Windows publishes no OCR recogniser for {lang!r} in any "
                    f"variant, so the screen will be read as English. Accented "
                    f"words come back without their accents and the voice says "
                    f"them that way. --ocr rapid reads it with its own model "
                    f"instead, slower.")
    elif lang not in APPLE_OCR_LOCALE:
        return (f"Apple Vision has no OCR recogniser for {lang!r}, so the screen "
                f"will be read as English. Accented words come back without "
                f"their accents and the voice says them that way. --ocr rapid "
                f"reads it with its own model instead, slower.")
    return ""
