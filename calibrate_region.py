#!/usr/bin/env python3
"""
calibrate_region.py — where is the dialogue box on THIS layout?

    python calibrate_region.py ~/Desktop/android-screen.png
    python calibrate_region.py shot1.png shot2.png shot3.png     # better
    python calibrate_region.py *.png --lang en

`REGION = (0.14, 0.50)` in trigger.py is the vertical band the narrator reads,
as fractions of the frame from the top. It was measured on the desktop game at
16:9, and it is the first thing that stops being true anywhere else — a phone,
a tablet, an emulator window, an ultrawide monitor. `narrator.py --region a,b`
overrides it, which leaves the question of what a and b should be.

Guessing them costs a run of the game each time. This measures them instead.

## How

The OCR returns a bounding box per line, so a screenshot of the game already
contains the answer; nothing has to be swept. One pass over the whole frame:

  1. read every line, with its box
  2. group into paragraphs and match them against the corpus
  3. take the lines belonging to paragraphs that matched a narration block
  4. their vertical extent, plus a margin, is the band

Step 3 is what makes this a measurement rather than a heuristic. Text that
matched the corpus is the game's own prose by definition; the objective bar, the
hero cards, the buttons and the map labels are all text too, and a band drawn
around *all* text on screen would be the whole screen. The band this reports is
the band around the words the narrator exists to speak.

## Why several screenshots are better than one

One screen shows one box, and the game draws short blocks and long ones. A band
fitted to a two-line screen will clip a six-line one. Pass every screenshot you
have and the band is the union — still measured, and now covering the range the
layout actually uses.

The number this prints is deliberately rounded outward, for the same reason: a
band that is a little too generous costs some OCR time on empty parchment, and a
band that is a little too tight silences the last paragraph of a screen.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

import console  # noqa: E402

console.setup()

GREEN, YELLOW, RED, GRAY, BOLD, RESET = (
    "\033[92m", "\033[93m", "\033[91m", "\033[90m", "\033[1m", "\033[0m")

# Rounded outward to this step, and padded by this much of the frame. Both exist
# for the same reason: an over-tight band silences the tail of a long screen,
# an over-generous one costs a few milliseconds of OCR on empty parchment.
STEP = 0.01
PAD = 0.02


def _band(lines) -> tuple[float, float] | None:
    """The vertical extent of these lines, as fractions from the top.

    `Line.bbox` is (x, y, width, height) with the origin at the BOTTOM left, and
    `crop()` takes fractions from the top. Getting that flip wrong produces a
    band that is a perfect mirror of the right answer, which looks plausible and
    reads nothing, so it is done here once and named.
    """
    if not lines:
        return None
    top = min(1.0 - (ln.bbox[1] + ln.bbox[3]) for ln in lines)
    bottom = max(1.0 - ln.bbox[1] for ln in lines)
    return (top, bottom)


def measure(path: Path, engine, matcher, corpus) -> dict:
    """One screenshot: the band its narration text occupies, and what it matched."""
    import numpy as np
    from PIL import Image

    from matcher import normalize
    from ocr.base import group_paragraphs

    image = np.asarray(Image.open(path).convert("L"))
    lines = engine.read(image)                      # the WHOLE frame, uncropped
    paragraphs = group_paragraphs(lines)
    results = matcher.match_screen("\n\n".join(paragraphs))

    keys = [r.key for r in results
            if r.accepted and r.key and corpus.get(r.key, {}).get("narration")]
    keys = list(dict.fromkeys(keys))

    # Which lines are the narration? A line belongs to a matched block when its
    # text is inside that block's text. Normalised on both sides, because that
    # comparison is against OCR output and nothing else in this project compares
    # raw strings either.
    wanted = " ".join(normalize(corpus[k]["text"]) for k in keys)
    narration = [ln for ln in lines
                 if len(normalize(ln.text)) >= 4 and normalize(ln.text) in wanted]

    return {"path": path, "keys": keys, "lines": len(lines),
            "narration": len(narration), "band": _band(narration),
            "all": _band(lines)}


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("images", type=Path, nargs="+",
                    help="screenshots of the game on the layout being measured")
    ap.add_argument("--lang", help="corpus language (default: the current one)")
    ap.add_argument("--campaign", help="scope the matcher to one campaign")
    ap.add_argument("--ocr", default="auto",
                    choices=("auto", "apple", "windows", "rapid"))
    args = ap.parse_args()

    import jime
    from matcher import Matcher, load_corpus
    from ocr.base import locales_for, open_ocr

    lang = args.lang or jime.default_language()
    path = jime.corpus_path(lang)
    if not Path(path).exists():
        return int(bool(print(f"{RED}no corpus for {lang!r} — extract it first"
                              f"{RESET}")))
    corpus = load_corpus(path)
    matcher = Matcher(corpus, campaign=args.campaign)
    engine = open_ocr(args.ocr, languages=locales_for(lang))

    print(f"{BOLD}{len(args.images)} screenshot(s){RESET}, corpus {lang!r}, "
          f"{type(engine).__name__}\n")

    bands = []
    for image in args.images:
        try:
            r = measure(image, engine, matcher, corpus)
        except Exception as exc:  # noqa: BLE001
            print(f"  {RED}{image.name}{RESET} — {type(exc).__name__}: {exc}")
            continue
        if r["band"] is None:
            # Worth distinguishing: nothing matched at all is a corpus problem,
            # not a region problem, and no band can fix it.
            print(f"  {YELLOW}{image.name}{RESET} — {r['lines']} lines read, "
                  f"nothing matched the corpus"
                  + (f" {GRAY}(whole-frame text spans "
                     f"{r['all'][0]:.2f}-{r['all'][1]:.2f}){RESET}"
                     if r["all"] else ""))
            continue
        top, bottom = r["band"]
        bands.append(r["band"])
        print(f"  {GREEN}{image.name}{RESET} — {top:.3f} to {bottom:.3f}  "
              f"{GRAY}{r['narration']}/{r['lines']} lines are narration; "
              f"{', '.join(r['keys'])[:60]}{RESET}")

    if not bands:
        print(f"\n{RED}No screenshot matched anything.{RESET} Either the corpus "
              f"is a different language from the game, or the screenshots do "
              f"not show a narration block. Try one with a dialogue box open.")
        return 1

    import math

    top = max(0.0, math.floor((min(b[0] for b in bands) - PAD) / STEP) * STEP)
    bottom = min(1.0, math.ceil((max(b[1] for b in bands) + PAD) / STEP) * STEP)

    print(f"\n{BOLD}--region {top:.2f},{bottom:.2f}{RESET}")
    print(f"{GRAY}Union of {len(bands)} screenshot(s), padded by {PAD:.2f} and "
          f"rounded outward.\nThe default for the desktop game is 0.14,0.50 — a "
          f"band far from that is a different\nlayout, which is the thing this "
          f"was written to find.{RESET}\n")
    print(f"  ~/jime-venv/bin/python narrator.py --lang {lang} "
          f"--region {top:.2f},{bottom:.2f} --app \"Emulator\"")

    if len(bands) < 3:
        print(f"\n{YELLOW}Only {len(bands)} screenshot(s).{RESET} The game draws "
              f"short blocks and long ones, and a band fitted to a short screen "
              f"clips a long one. Three or four covering both is worth the "
              f"minute it costs.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
