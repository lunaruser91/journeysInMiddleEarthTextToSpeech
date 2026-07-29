#!/usr/bin/env python3
"""
live.py — the blocks that cannot be rendered in advance, spoken during play.

161 blocks of Bones of Arnor and the shared text carry a `{0}`: a hero's name,
an objective, a threat value. The number only exists at the table, so there is
nothing to pre-render — "Reduce the threat by ___" is worse than silence,
because the player acts on what they hear.

Two things make this workable now. Piper renders at RTF 0.05, so a screen's
worth of speech takes well under a second on the CPU: what was out of the
question with a model at RTF 3.7 is unremarkable here. And **the screen already
shows the value** — the game substituted it before drawing. The OCR read it. So
there is nothing to guess.

## Why not just speak the OCR

Because OCR is wrong sometimes, and this text is instructions. Speaking raw OCR
means speaking its mistakes with the same confidence as the rest.

Instead the corpus template is the skeleton and only the gap is taken from the
screen. `Reduce the threat by {0}.` fixes every word except one; the OCR only
has to supply what goes in the hole. A misread elsewhere in the line cannot
change what is spoken, and if the fixed parts cannot be found at all, nothing is
spoken — the caller is told, rather than being handed a guess.
"""
from __future__ import annotations

import hashlib
import re
import subprocess
import unicodedata
import wave
from pathlib import Path

import prosody

PLACEHOLDER = re.compile(r"\{\d*\}")
ROOT = Path(__file__).resolve().parent


def _flat(s: str) -> tuple[str, list[int]]:
    """Accent-free, punctuation-free, single-spaced — plus a map back.

    The flattened form is for *locating* only. Values must be cut from the
    original, or a recovered hero name would be spoken stripped of its accents
    and capitals. So every character kept carries the index it came from.
    """
    out, index = [], []
    prev_space = True
    for i, ch in enumerate(s):
        d = unicodedata.normalize("NFKD", ch)
        d = "".join(c for c in d if not unicodedata.combining(c)).casefold()
        if not d:
            continue
        c = d[0]
        if c.isalnum() or c == "_":
            out.append(c)
            index.append(i)
            prev_space = False
        elif not prev_space:
            out.append(" ")
            index.append(i)
            prev_space = True
    while out and out[-1] == " ":
        out.pop()
        index.pop()
    return "".join(out), index


def _find_words(haystack: str, needle: str, start: int) -> int:
    """Substring search that prefers not to land inside a word.

    Both halves of this matter, and they pull against each other. The fixed text
    between two placeholders is sometimes a single short word — "and", "or", "e"
    — and a plain find() lets it match inside the value: looking for "or" in
    "Aragorn or 2" hits the one in the name, and everything after is
    misattributed. But a placeholder can also sit flush against the fixed text
    with no separator at all, as in "{0}Find clues", where "aragornfind clues"
    has no boundary to respect.

    So a boundary-aligned match wins if one exists, and an unaligned one is
    accepted when it is all there is. Requiring alignment outright traded four
    failures for seventeen.
    """
    at = haystack.find(needle, start)
    first = at
    while at >= 0:
        end = at + len(needle)
        if ((at == 0 or not haystack[at - 1].isalnum())
                and (end >= len(haystack) or not haystack[end].isalnum())):
            return at
        at = haystack.find(needle, at + 1)
    return first


EDGE = 30            # flattened chars at each end of a fixed part
PRESENT_SCORE = 82.0  # the matcher's own floor, so both stages agree


def _anchor(flat: str, flat_part: str, cursor: int) -> tuple[int, int] | None:
    """Where a fixed part of the template sits in the screen, or None.

    ## Why the whole part cannot be required

    The matcher accepts a block at 82% similarity, so by the time a template
    reaches here the screen is *known* to differ from it. Demanding the fixed
    parts back verbatim asked the OCR to be perfect exactly where it had already
    been forgiven: one 'm' read as 'rn' anywhere in a 44-word run silenced the
    paragraph, and two thirds of the placeholder blocks carry a run of 20 words
    or more. The trailing test line — "Teste ⌘ 2." — is worse still, because it
    is often below the band this crops to and is not on the screen at all.

    ## Why similarity cannot place it either

    Matching the whole part by similarity finds it, but not its edges. A part
    that follows a placeholder scores about as well starting at the value as
    starting after it, so the best window swallowed the value and the sentence
    came back with a hole: "o(a) desapareceu", "toma conta da estrada., que
    está de vigia".

    ## Only the ends decide

    A value is bounded by the text immediately beside it, and nothing else. So
    the ends of a part are located exactly and its middle is only checked for
    presence. Thirty characters is long enough not to land somewhere else by
    accident and short enough that an OCR usually gets it whole.
    """
    at = _find_words(flat, flat_part, cursor)
    if at >= 0:
        return at, at + len(flat_part)
    if len(flat_part) <= EDGE * 2:
        return None                  # short enough that the ends are the middle
    from rapidfuzz import fuzz

    if fuzz.partial_ratio(flat_part, flat[cursor:]) < PRESENT_SCORE:
        return None                  # not on this screen at all

    head = _find_words(flat, flat_part[:EDGE], cursor)
    after = head + EDGE if head >= 0 else cursor
    tail = _find_words(flat, flat_part[-EDGE:], after)
    if head < 0 and tail < 0:
        return None
    if head < 0:                     # only the far edge was legible
        return max(cursor, tail + EDGE - len(flat_part)), tail + EDGE
    if tail < 0:                     # the part runs to where the screen stops
        return head, min(len(flat), head + len(flat_part))
    return head, tail + EDGE


def fill_template(template: str, screen: str) -> str | None:
    """Put the screen's values into the corpus template.

    Returns the template with each placeholder replaced by what the screen has
    in that position, or None when the fixed parts cannot be located — the
    honest answer when the OCR disagrees with the corpus badly enough that the
    alignment would be guesswork.
    """
    parts = PLACEHOLDER.split(template)
    if len(parts) == 1:
        return template

    flat, index = _flat(screen)
    if not flat:
        return None

    # Anchor only on parts that survive flattening. A part that is pure
    # punctuation — "." after a trailing placeholder, which is the commonest
    # shape here — carries no signal, and treating it as a zero-width anchor
    # collapses the gap the value was supposed to fill.
    #
    # A part that cannot be found is dropped rather than failing the template.
    # The commonest absentee is the trailing test line — "Teste ⌘ 2." — which
    # sits below the band this crops to and is simply not on the screen the
    # player is being read. Losing it should cost that line, not the paragraph.
    #
    # What must not happen is dropping *everything* and handing the screen back
    # as one enormous value: that is speaking raw OCR, which this module exists
    # to avoid. So the located anchors have to account for most of the fixed
    # text before the alignment is trusted at all.
    anchors: dict[int, tuple[int, int]] = {}
    cursor = 0
    fixed = located = 0
    for i, part in enumerate(parts):
        flat_part, _ = _flat(part)
        if not flat_part:
            continue
        fixed += len(flat_part)
        span = _anchor(flat, flat_part, cursor)
        if span is None:
            continue
        anchors[i] = span
        located += len(flat_part)
        cursor = max(cursor, span[1])
    if not anchors or located < fixed * 0.6:
        return None                  # this template does not describe this screen

    def cut(lo: int, hi: int) -> str:
        """Original-text slice for a flattened span, accents and case intact.

        Punctuation at the edges belongs to the template, not to the value: the
        flattened anchors stop at the last letter of "Objective updated", so the
        span starts on the colon the template already supplies. Leaving it in
        produced "Objective updated:: ...".
        """
        if hi <= lo or lo >= len(index):
            return ""
        raw = screen[index[lo]:index[min(hi, len(index)) - 1] + 1]
        return raw.strip(" \t\n.,;:!?\"'()[]-–—")

    # Placeholders with no fixed text between them — "{0}{1}", "{0} {1} {2}" —
    # share one gap, and there is nothing in the screen that says where one value
    # ends and the next begins. Splitting it would be invention, so the first
    # takes the whole gap and the rest take nothing. The sentence still reads
    # back exactly as it appears on screen, which is the only property that
    # matters here; without this the value was simply repeated.
    values, claimed = [], set()
    for i in range(len(parts) - 1):
        # Walk back to the nearest anchor, not to the start of the string. With
        # "{0}{1}" the second placeholder has no anchored part before it, and
        # defaulting to 0 handed it the whole screen — it spoke the entire block
        # again before reaching the words that follow.
        before = next((anchors[j] for j in range(i, -1, -1) if j in anchors), None)
        lo = before[1] if before else 0
        after = next((anchors[j] for j in range(i + 1, len(parts))
                      if j in anchors), None)
        hi = after[0] if after else len(flat)
        if (lo, hi) in claimed:
            values.append("")
            continue
        claimed.add((lo, hi))
        values.append(cut(lo, hi))

    filled = "".join(part + (values[i] if i < len(values) else "")
                     for i, part in enumerate(parts))
    # A placeholder that recovered nothing leaves a hole; close the spacing so it
    # reads as an ordinary sentence rather than a gap.
    filled = re.sub(r"\s+([.,;:!?])", r"\1", re.sub(r"\s{2,}", " ", filled))
    return filled.strip()


class LiveVoice:
    """Piper, loaded once, synthesising to a cache on demand.

    Loading costs about half a second, so it is deferred until something
    actually needs speaking — most sessions never do. Results are cached by the
    exact text, because the same screen tends to come back.
    """

    def __init__(self, voice: str | None = None, lang: str = "pt",
                 length_scale: float | None = None,
                 cache: Path | None = None) -> None:
        import voices as V

        self.lang = lang
        self.name = V.resolve(lang, voice)
        self.length_scale = (length_scale if length_scale is not None
                             else V.length_scale(self.name, lang, quiet=True))
        self.cache = cache or ROOT / "output" / f"live_{lang}"
        self.cache.mkdir(parents=True, exist_ok=True)
        self._voice = None
        self._cfg = None

    def _load(self):
        if self._voice is None:
            import voices as V
            from piper import PiperVoice, SynthesisConfig

            self._voice = PiperVoice.load(str(V.ensure(self.name, quiet=True)))
            self._cfg = SynthesisConfig(length_scale=self.length_scale,
                                        noise_scale=0.9, noise_w_scale=1.0,
                                        volume=1.0)
        return self._voice, self._cfg

    def say(self, text: str) -> Path | None:
        """Audio for this exact text, synthesising it if it is new."""
        if not text.strip():
            return None
        # "p2" is the prosody pass, the same marker the renderer puts in its
        # cache key. A live block and a pre-rendered one have to be read the same
        # way or the join between them is audible, and a cache from before the
        # change must not be served after it.
        key = hashlib.blake2b(
            f"{self.name}|{self.length_scale}|p2|{text}".encode(),
            digest_size=10).hexdigest()
        dest = self.cache / f"{key}.opus"
        if dest.exists():
            return dest

        voice, cfg = self._load()
        tmp = self.cache / f".tmp_{key}.wav"
        try:
            prosody.synthesize(voice, text, self.length_scale, tmp, cfg)
            subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(tmp),
                            "-c:a", "libopus", "-b:a", "48k", str(dest)],
                           check=True)
        except Exception:  # noqa: BLE001
            dest.unlink(missing_ok=True)
            return None
        finally:
            tmp.unlink(missing_ok=True)
        return dest


if __name__ == "__main__":
    import argparse
    import json
    import sys
    import time

    sys.path.insert(0, str(ROOT))
    import console
    import glyphs as G

    console.setup()

    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("key", help="a corpus key carrying a placeholder")
    ap.add_argument("--screen", help="the text as it appears on screen")
    ap.add_argument("--lang", default="pt")
    ap.add_argument("--no-audio", action="store_true")
    args = ap.parse_args()

    corpus = json.loads((ROOT / "corpus" / f"corpus_{args.lang}.json")
                        .read_text(encoding="utf-8"))
    template = corpus[args.key]["text"]
    screen = args.screen or PLACEHOLDER.sub("2", template)
    filled = fill_template(template, screen)
    print(f"template: {' '.join(template.split())}")
    print(f"screen  : {' '.join(screen.split())}")
    print(f"filled  : {filled}")
    if filled is None or args.no_audio:
        raise SystemExit(0 if filled else 1)

    speech = G.spell_out_numbers(
        G.substitute(filled, G.glyph_map_from_corpus(corpus), args.lang), args.lang)
    print(f"spoken  : {speech}")
    t0 = time.time()
    path = LiveVoice(lang=args.lang).say(speech)
    print(f"rendered in {time.time() - t0:.2f}s -> {path}")
