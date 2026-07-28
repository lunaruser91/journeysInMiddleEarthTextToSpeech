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

RapidOCR anywhere: ~19 MB of ONNX weights, Apache-2.0, works on Windows and
Linux. Windows also has `Windows.Media.Ocr` natively, which is not wrapped here.

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
    """
    items = [ln for ln in lines if ln.text.strip()]
    if not items:
        return []
    items.sort(key=lambda ln: -ln.bbox[1])          # top of the image downwards

    heights = sorted(ln.height for ln in items)
    typical = heights[len(heights) // 2] or 1e-6

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
    """Pick an engine: 'auto', 'apple', or 'rapid'."""
    if prefer in ("auto", "apple") and platform.system() == "Darwin":
        try:
            from .apple_vision import AppleVision
            return AppleVision(languages=languages)
        except OcrError:
            if prefer == "apple":
                raise
    from .rapidocr_engine import RapidOcr
    return RapidOcr()


# The game's language codes are not what the OCR engines want. Apple Vision
# takes full locales and rejects a bare "de" with ValueError, so a session in any
# language but Portuguese would have died on its first screen — or worse, run the
# Portuguese recogniser over German text, which is the silent version.
#
# Measured against Vision's own supportedRecognitionLanguages on macOS 26:
# twelve of the game's thirteen are there. Hungarian is not, at all.
OCR_LOCALE = {
    "cz": "cs-CZ", "de": "de-DE", "en": "en-US", "es": "es-ES", "fr": "fr-FR",
    "it": "it-IT", "ko": "ko-KR", "pl": "pl-PL", "pt": "pt-BR", "ru": "ru-RU",
    "uk": "uk-UA", "zh": "zh-Hans",
    # "hu" is deliberately absent: Apple Vision has no Hungarian recogniser.
}


def locales_for(lang: str) -> tuple[str, ...]:
    """OCR locales for a game language, best first.

    English is appended as a second choice everywhere: the game's screens carry
    proper nouns and interface words that read the same either way, and giving
    the recogniser a fallback costs nothing.
    """
    primary = OCR_LOCALE.get(lang)
    if primary is None:
        return ("en-US",)
    return (primary,) if primary == "en-US" else (primary, "en-US")
