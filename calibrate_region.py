#!/usr/bin/env python3
"""
calibrate_region.py — where is the dialogue box on THIS layout?

    python calibrate_region.py ~/Desktop/android-screen.png
    python calibrate_region.py shot1.png shot2.png shot3.png     # better
    python calibrate_region.py shots/ --lang en                  # a whole folder
    python calibrate_region.py "shots/*.png"                     # or a wildcard

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
  4. split those into vertically separated blocks, and keep the one with the
     most text on it
  5. its extent, plus a margin, is the band

Step 3 drops the map labels, the hero cards and the tile numbers: they are not
in the corpus, so nothing anchors them. It is not enough on its own, which is
what the first version of this got wrong. **The objective bar is a narration
block** — 222 of them are — and so is every choice button, so a band drawn
around everything that matched runs from above the dialogue box to below it.
Measured on a Windows session it reported 0.07-0.57 against a default of
0.14-0.50: wider, when the whole point was to be tighter. `trigger.py` has
recorded from the beginning that the objective bar "matched in all 19
screenshots of a test session", and this tool was written as if it would not.

The bar goes by name. Each line is attributed to the one block it came from, and
495 keys carry `OBJECTIVE` — that is the game's own label, not an inference
about pixels. Separating it by geometry was tried first and is too delicate: the
gap between the bar and the box is about 1.5 line-heights, the box sets its own
lines 1.0 to 1.3 apart, and the threshold that split them on one screenshot
merged them on the next from the same session.

The buttons have no such label, so they go by shape. Blocks separated
vertically, and the box is the one that is both heavy and wide — a button is
three words in a column, the box is drawn nearly edge to edge. What gets dropped
is printed with both numbers, so the choice can be argued with rather than
trusted.

A screenshot showing only the objective bar says nothing about where a dialogue
box sits, and is reported as such rather than counted.

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


# A gap this many line-heights wide separates one block of text from the next.
# The dialogue box sets its lines about one height apart; the objective bar sits
# several heights above it and the choice buttons several below.
CLUSTER_GAP = 1.8


def _clusters(lines) -> list[tuple[tuple[float, float], int, int]]:
    """Split lines into vertically separated blocks, top to bottom.

    Matching the corpus does not identify the dialogue box, which is what the
    first version of this assumed. The objective bar is a narration block — 222
    of them are, and `trigger.py` has recorded since the beginning that it
    "matched in all 19 screenshots of a test session" — and so is every choice
    button. A band drawn around everything that matched therefore reaches from
    above the box to below it, which is the opposite of what `REGION` is for.

    Geometry separates them where the corpus cannot. Returns
    ((top, bottom), characters, lines, width) per block, width as a fraction of
    the frame.
    """
    items = sorted(lines, key=lambda ln: 1.0 - (ln.bbox[1] + ln.bbox[3]))
    if not items:
        return []
    typical = sorted(ln.bbox[3] for ln in items)[len(items) // 2] or 0.02
    out, run = [], [items[0]]
    for prev, line in zip(items, items[1:]):
        gap = (1.0 - (line.bbox[1] + line.bbox[3])) - (1.0 - prev.bbox[1])
        if gap > typical * CLUSTER_GAP:
            out.append(run)
            run = []
        run.append(line)
    out.append(run)
    return [(_band(r), sum(len(ln.text) for ln in r), len(r),
             max(ln.bbox[0] + ln.bbox[2] for ln in r)
             - min(ln.bbox[0] for ln in r)) for r in out]


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

    # Which lines are the narration? A line belongs to a matched block when the
    # block nearly contains it. The comment here used to say that nothing in
    # this project compares raw strings, above a line that did exactly that:
    # exact containment after normalising. One misread character dropped the
    # whole line, and on a Windows session that turned a dialogue box into nine
    # characters, which then lost to the objective bar.
    #
    # 88 is narrator.py's ON_SCREEN_SCORE, answering the same question about the
    # same kind of text: is this paragraph the screen is showing one of the
    # block's?
    from rapidfuzz import fuzz

    # Each line against each key separately, not against all of them joined.
    # Knowing *which* block a line came from is what lets the objective bar be
    # dropped by name, and the game names it: 495 keys carry OBJECTIVE, 222 of
    # them narration. That is the game's own label, not a guess about pixels.
    #
    # Dropping it by geometry was the first attempt and it is too delicate. The
    # gap between the bar and the box is about 1.5 line-heights and the box sets
    # its own lines 1.0 to 1.3 apart, so the threshold that separates them on
    # one screen merges them on the next — measured, on two screenshots of the
    # same session.
    texts = {k: normalize(corpus[k]["text"]) for k in keys}
    owned, bar = [], 0
    for ln in lines:
        norm = normalize(ln.text)
        if len(norm) < 4:
            continue
        key, score = None, 0.0
        for k, body in texts.items():
            s = fuzz.partial_ratio(norm, body)
            if s > score:
                key, score = k, s
        if score < 88.0:                       # not the game's prose at all
            continue
        if "OBJECTIVE" in key.upper():
            bar += 1
            continue
        owned.append(ln)
    narration = owned

    # Which block is the dialogue box? Text alone nearly answers it — the
    # objective bar is one line and a button is three words — but nearly is not
    # enough: measured on a Windows screen a 56-character bar beat a box the OCR
    # had read badly. Width is the second signal and an independent one. The box
    # is drawn nearly edge to edge; the bar is centred and narrow, and the
    # buttons sit in two columns. Neither is wide AND heavy.
    blocks = _clusters(narration)
    best = max(blocks, key=lambda b: b[1] * b[3]) if blocks else None
    return {"path": path, "keys": keys, "lines": len(lines),
            "narration": len(narration), "bar": bar,
            "band": best[0] if best else None,
            "blocks": blocks, "chars": best[1] if best else 0,
            "width": best[3] if best else 0.0,
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



    # PowerShell does not expand wildcards for external programs, so
    # `calibrate_region.py *.png` — which this file's own usage line shows —
    # arrives as the literal string "*.png" on Windows and dies as a missing
    # file. Expanding here makes the documented form true on both platforms.
    # A directory is taken as every image in it, for the same reason: it is what
    # somebody means when they point at the folder they saved the shots to.
    images: list[Path] = []
    for spec in args.images:
        if spec.is_dir():
            images += sorted(q for q in spec.iterdir()
                             if q.suffix.lower() in (".png", ".jpg", ".jpeg",
                                                     ".webp", ".bmp"))
        elif any(c in str(spec) for c in "*?["):
            images += sorted(Path().glob(str(spec)) if not spec.is_absolute()
                             else Path(spec.anchor).glob(
                                 str(spec.relative_to(spec.anchor))))
        else:
            images.append(spec)
    if not images:
        print(f"{RED}no images matched{RESET} "
              f"{', '.join(str(s) for s in args.images)}")
        return 1

    print(f"{BOLD}{len(images)} screenshot(s){RESET}, corpus {lang!r}, "
          f"{type(engine).__name__}\n")

    bands = []
    for image in images:
        try:
            r = measure(image, engine, matcher, corpus)
        except Exception as exc:  # noqa: BLE001
            print(f"  {RED}{image.name}{RESET} — {type(exc).__name__}: {exc}")
            continue
        if r["band"] is None:
            # Three different things end up here and they need different
            # answers: nothing matched (wrong language, or no game text on the
            # screen), or only the objective bar did (a screen with no dialogue
            # box open, which cannot say where the box goes).
            if r["bar"]:
                print(f"  {YELLOW}{image.name}{RESET} — only the objective bar "
                      f"{GRAY}({r['bar']} line(s)); no dialogue box on this "
                      f"screen, so it says nothing about where one sits{RESET}")
                continue
            print(f"  {YELLOW}{image.name}{RESET} — {r['lines']} lines read, "
                  f"nothing matched the corpus"
                  + (f" {GRAY}(whole-frame text spans "
                     f"{r['all'][0]:.2f}-{r['all'][1]:.2f}){RESET}"
                     if r["all"] else ""))
            continue
        top, bottom = r["band"]
        bands.append(r["band"])
        # Say what was thrown away. A block of narration text that is not the
        # dialogue box is the objective bar or a row of choice buttons, and
        # somebody reading this should see that the tool knew they were there.
        other = [b for b in r["blocks"] if b[0] != r["band"]]
        print(f"  {GREEN}{image.name}{RESET} — {top:.3f} to {bottom:.3f}  "
              f"{GRAY}{r['chars']}c x{r['width']:.2f}w over "
              f"{r['narration']}/{r['lines']} narration lines"
              + (f", bar {r['bar']} dropped" if r["bar"] else "") + f"{RESET}")
        if other:
            print(f"      {GRAY}dropped: "
                  + ", ".join(f"{b[0][0]:.2f}-{b[0][1]:.2f} ({b[1]}c "
                              f"x{b[3]:.2f}w)" for b in other) + f"{RESET}")
        print(f"      {GRAY}{', '.join(r['keys'])[:72]}{RESET}")

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
          f"--region {top:.2f},{bottom:.2f} --display")
    # Naming a window rather than a display needs the *owning application*, and
    # what that is called is not guessable from a screenshot. It also differs by
    # platform: macOS matches --app against the application name alone, Windows
    # against application and title together. The Android emulator is owned by
    # `qemu-system-aarch64`, not by anything called "Emulator" — which is what
    # this line used to suggest, and it does not work on macOS.
    print(f"{GRAY}For a window instead of a display — an emulator, a mirrored "
          f"phone — pass --app naming\nthe owning application. "
          f"`narrator.py --list-windows` prints it; for the Android emulator "
          f"it is\n`--app qemu --window \"Android Emulator\"`.{RESET}")

    if len(bands) < 3:
        print(f"\n{YELLOW}Only {len(bands)} screenshot(s).{RESET} The game draws "
              f"short blocks and long ones, and a band fitted to a short screen "
              f"clips a long one. Three or four covering both is worth the "
              f"minute it costs.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
