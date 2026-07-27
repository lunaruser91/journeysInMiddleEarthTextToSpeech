#!/usr/bin/env python3
"""
trigger.py — decides WHEN a new screen appeared and is worth narrating.

The middle stage of phase 3: capture feeds it frames, it decides which ones
deserve an OCR pass, `matcher.py` turns that text into corpus keys, and
`player.py` speaks them.

## Why this stage exists at all

OCR costs 150-350 ms and the matcher is not free either. Running them on every
frame would be wasteful and, worse, would narrate the same screen many times as
its text animates in. This stage exists to answer two questions cheaply: *did
anything change?* and *has it settled?*

## The numbers here were measured, not guessed

From an 83-second screen recording of real play, sampled at 10 Hz (828 frames),
looking only at the dialogue box region:

* **The screen is static almost all the time.** Median frame-to-frame delta is
  0.00%; the 75th percentile is 0.01%. Any movement at all is a real event, so
  the 0.5% threshold from the briefing is comfortable rather than tight.

* **15 change events in 83 s** — one every 5.5 s, which matches the pace of a
  real game.

* **Transitions are not continuous.** The text animates in with pauses inside
  it. Measuring runs of quiet frames gives two clean populations: runs of up to
  10 frames (1.0 s) happen *inside* a transition, and runs of 16 frames (1.6 s)
  or more happen *between* screens. Nothing landed in between.

  This is why `STABLE_FRAMES` defaults to 11 and not to the 3 the briefing
  suggested. Three quiet frames — 0.3 s — fire in the middle of the animation
  and read half-drawn text. The cost is 1.1 s of latency before speaking, which
  is nothing at a table where players read for ten seconds or more.

  Honest caveat: that clean separation comes from 15 events in one recording. A
  larger sample could blur it, so the parameter is exposed.

## Cropping the dialogue box is not an optimisation

The map animates on its own — tiles being placed, fog moving — so a full-screen
diff fires on things that are not text. `REGION` limits everything to the
horizontal band where the dialogue box lives.

## Dedupe needs a TTL, and this is not optional

The objective bar at the top of the screen matched in **all 19** screenshots of
a test session. Without expiry, either it gets narrated nineteen times, or it is
suppressed forever and never spoken again when it genuinely changes. The TTL
resolves both: a screen is suppressed only while it is recent.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Callable

import numpy as np

# Region of the dialogue box, as fractions of the frame: (top, bottom).
# Measured against 1920x1080 and 1280x720 captures of the game.
REGION = (0.14, 0.50)

CHANGE_THRESHOLD = 0.5      # % of pixels differing by more than PIXEL_DELTA
PIXEL_DELTA = 25
STABLE_FRAMES = 11          # quiet frames before declaring the screen settled
HASH_SIZE = 16              # dhash side; 8 is too coarse for a 1000x200 box
HAMMING_MAX = 2             # near-identical screens
TTL_SECONDS = 100.0         # how long a screen stays suppressed
MEMORY = 30                 # how many recent screens to remember

MIN_CHARS = 8               # significance: shorter than this is HUD noise
MIN_WORDS = 2
MIN_ALNUM_RATIO = 0.35


def dhash(gray: np.ndarray, size: int = HASH_SIZE) -> int:
    """Difference hash: compares each pixel with its right-hand neighbour.

    Deliberately not a pHash. The DCT in a pHash discards high frequencies,
    which is exactly where glyph edges live — two different paragraphs of the
    same length would collide.
    """
    from PIL import Image

    small = np.asarray(
        Image.fromarray(gray.astype(np.uint8)).resize((size + 1, size)),
        dtype=np.int16)
    bits = small[:, 1:] > small[:, :-1]
    out = 0
    for bit in bits.flatten():
        out = (out << 1) | int(bit)
    return out


def hamming(a: int, b: int) -> int:
    return bin(a ^ b).count("1")


def significant(text: str) -> bool:
    """Is this worth narrating, or is it HUD noise?"""
    stripped = text.strip()
    if len(stripped) < MIN_CHARS or len(stripped.split()) < MIN_WORDS:
        return False
    alnum = sum(c.isalnum() for c in stripped)
    return alnum / max(len(stripped), 1) >= MIN_ALNUM_RATIO


@dataclass
class Seen:
    norm: str
    at: float


@dataclass
class Trigger:
    """Turns a stream of frames into a stream of "this screen is new" events.

    Feed it frames with `feed()`. It returns the settled frame when one is worth
    reading, and None otherwise. The OCR call belongs to the caller, because
    only the caller knows how to run it.
    """

    region: tuple[float, float] = REGION
    change_threshold: float = CHANGE_THRESHOLD
    stable_frames: int = STABLE_FRAMES
    ttl: float = TTL_SECONDS
    now: Callable[[], float] = time.monotonic

    _prev: np.ndarray | None = field(default=None, init=False)
    _quiet: int = field(default=0, init=False)
    _dirty: bool = field(default=False, init=False)
    _settled_hash: int | None = field(default=None, init=False)
    _recent: list[Seen] = field(default_factory=list, init=False)
    _last_norm: str = field(default="", init=False)

    # ------------------------------------------------------------- frames --

    def _crop(self, gray: np.ndarray) -> np.ndarray:
        h = gray.shape[0]
        return gray[int(h * self.region[0]):int(h * self.region[1])]

    def feed(self, gray: np.ndarray) -> np.ndarray | None:
        """Give it one greyscale frame. Returns the frame when it has settled.

        The contract is deliberately narrow: it fires **once** per settled
        screen, on the frame where the screen stopped moving.
        """
        box = self._crop(gray)
        if self._prev is None:
            self._prev = box
            return None

        delta = (np.abs(box.astype(np.int16) - self._prev.astype(np.int16))
                 > PIXEL_DELTA).mean() * 100
        self._prev = box

        if delta > self.change_threshold:
            self._dirty = True
            self._quiet = 0
            return None

        if not self._dirty:
            return None

        self._quiet += 1
        if self._quiet < self.stable_frames:
            return None

        # settled: fire once, then wait for the next change
        self._dirty = False
        h = dhash(box)
        if self._settled_hash is not None and hamming(h, self._settled_hash) <= HAMMING_MAX:
            return None                      # same screen as before, visually
        self._settled_hash = h
        return gray

    # -------------------------------------------------------------- text --

    def accept_text(self, text: str, normalize: Callable[[str], str]) -> bool:
        """Second gate, after OCR: is this text new and worth speaking?

        Kept separate from `feed` on purpose. A screen can be visually different
        while carrying the same words — a tile sliding in behind the dialogue
        box, for instance — and only the text can settle that.
        """
        if not significant(text):
            return False
        norm = normalize(text)
        if not norm:
            return False

        now = self.now()
        self._recent = [s for s in self._recent if now - s.at < self.ttl]

        # progressive reveal: the game grows the text, it is not a new screen
        if self._last_norm and norm.startswith(self._last_norm):
            self._last_norm = norm
            for s in self._recent:
                if s.norm == norm:
                    s.at = now
                    return False
            self._recent.append(Seen(norm, now))
            return True

        for s in self._recent:
            if s.norm == norm:
                s.at = now                   # refresh: it is still on screen
                return False

        self._recent.append(Seen(norm, now))
        del self._recent[:-MEMORY]
        self._last_norm = norm
        return True

    def reset(self) -> None:
        self._prev = None
        self._quiet = 0
        self._dirty = False
        self._settled_hash = None
        self._recent.clear()
        self._last_norm = ""
