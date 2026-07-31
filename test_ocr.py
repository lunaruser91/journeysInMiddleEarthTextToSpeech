#!/usr/bin/env python3
"""
test_ocr.py — how much does the OCR actually get wrong?

    python test_ocr.py                      # synthetic pages, this platform's engine
    python test_ocr.py --engines            # every engine installed, side by side
    python test_ocr.py --from-captures DIR  # real screens the narrator saved

## Why this exists

`test_matcher.py` degrades its fixtures with *synthetic* noise — a table of
confusions picked because they are the classic ones for light serif text on a
dark background — and reports 94.2% hit at 5% noise. Every claim this project
makes about noise tolerance hangs on that number, and nothing measured whether
real OCR sits at 1%, at 5%, or somewhere that makes the table irrelevant.

This measures the noise instead of assuming it.

## What a synthetic page does and does not tell you

The default mode renders each fixture's known text into an image and reads it
back. The text is real — rebuilt from the game's own logs, with its proper nouns
and its accents, which is where a recogniser actually struggles. The *rendering*
is not: this uses a system serif on a flat background, and the game uses its own
font on parchment, with antialiasing and a texture behind the words.

So this is a **lower bound**. The game's screen is strictly harder than this
page, so real CER is at least what this reports and probably more. A lower bound
still answers the question that matters — if even a clean page loses 3% of
characters, the matcher's tolerance is being spent before the game is involved.

`--from-captures` is the measurement without that caveat, and it needs somebody
to play: `jime play --save-crops DIR` writes each settled crop beside the key it
matched, and the corpus text for that key is the ground truth. It is biased the
other way — a screen that matched confidently is one the OCR read well — so the
two modes bracket the answer rather than either being it.

## CER, and why not word error

Character error rate: Levenshtein distance over the reference length. Words are
the wrong unit here for the same reason they were the wrong unit for pace — the
corpus spans thirteen languages and two of them do not delimit words with
spaces. A character is a character everywhere.
"""
from __future__ import annotations

import argparse
import json
import sys
import unicodedata
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

import console  # noqa: E402

console.setup()

GREEN, YELLOW, RED, GRAY, BOLD, RESET = (
    "\033[92m", "\033[93m", "\033[91m", "\033[90m", "\033[1m", "\033[0m")

# A serif at the size the game draws its dialogue box, on a flat dark ground.
# Not the game's font — that lives in resources.assets rather than in the
# StreamingAssets bundles this project reads — which is exactly why this mode is
# documented as a floor.
FONT_CANDIDATES = [
    "/System/Library/Fonts/Supplemental/Georgia.ttf",
    "/System/Library/Fonts/Supplemental/Baskerville.ttc",
    "/System/Library/Fonts/Supplemental/Times New Roman.ttf",
    "C:/Windows/Fonts/georgia.ttf",
    "C:/Windows/Fonts/times.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSerif.ttf",
]


def _norm(s: str) -> str:
    """Compare what a listener would notice, not what a byte comparison sees.

    Collapsed whitespace, because line breaks are the layout's business and the
    matcher normalises them away too. NFC, so a decomposed accent from one engine
    does not read as two errors against a composed one from another — that is a
    difference in Unicode form, not in what was recognised.
    """
    return unicodedata.normalize("NFC", " ".join(s.split()))


def cer(reference: str, got: str) -> tuple[int, int]:
    """(edits, reference length). Levenshtein, iterative, two rows."""
    a, b = _norm(reference), _norm(got)
    if not a:
        return (len(b), 0)
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1,
                           prev[j - 1] + (ca != cb)))
        prev = cur
    return (prev[-1], len(a))


def render(text: str, width: int = 1400, size: int = 34):
    """One dialogue box, drawn the way the game lays one out."""
    import textwrap

    import numpy as np
    from PIL import Image, ImageDraw, ImageFont

    font = None
    for path in FONT_CANDIDATES:
        if Path(path).exists():
            try:
                font = ImageFont.truetype(path, size)
                break
            except Exception:  # noqa: BLE001
                continue
    if font is None:
        raise SystemExit("no serif font found; pass --from-captures instead")

    lines = []
    for para in text.split("\n\n"):
        lines += textwrap.wrap(" ".join(para.split()), 58) + [""]
    height = max(200, 60 + len(lines) * (size + 14))
    img = Image.new("L", (width, height), 26)
    d = ImageDraw.Draw(img)
    y = 30
    for line in lines:
        d.text((60, y), line, fill=224, font=font)
        y += size + 14
    return np.array(img)


def fixtures(limit: int) -> list[tuple[str, str]]:
    """(key, text) pairs from the game's own logs, via the matcher harness.

    The game's icons are stripped, and that is a correction rather than a
    convenience. They are Private Use Area characters drawn by the game's own
    font, which is not the font this renders with, so the page shows a fallback
    box and the recogniser reads a letter out of it: `Negado por ` came back as
    `Negado por O`. The first run of this harness scored those as OCR errors when
    they were the harness failing to draw an icon.

    On a real screen the icon is drawn properly and the recogniser makes of it
    whatever it makes — which `--from-captures` measures and this cannot.
    """
    import test_matcher as H
    from glyphs import _EXTRA_SPACES, _SPACE_BEFORE_PUNCT, PUA
    from matcher import load_corpus

    import jime

    def clean(s: str) -> str:
        # And close the gap the icon leaves. Removing it bare gave "Teste ." on
        # the reference against "Teste." from the page, which counted as an OCR
        # error and was punctuation spacing — the same tidy-up `substitute` does
        # after a real swap.
        s = PUA.sub("", s)
        return _EXTRA_SPACES.sub(" ", _SPACE_BEFORE_PUNCT.sub(r"\1", s))

    lang = jime.default_language()
    corpus = load_corpus(jime.corpus_path(lang))
    out = [(f["log_key"], clean(f["screen"])) for f in H.build_fixtures(corpus)]
    return out[:limit]


def captures(folder: Path, limit: int) -> list[tuple[str, str]]:
    """(key, text) from crops the narrator saved, with the corpus as truth."""
    import numpy as np

    import jime
    from matcher import load_corpus

    index = json.loads((folder / "index.json").read_text(encoding="utf-8"))
    corpus = load_corpus(jime.corpus_path(index.get("lang", "pt")))
    out = []
    for row in index["screens"][:limit]:
        key = row["key"]
        if key not in corpus:
            continue
        out.append((key, corpus[key]["text"], np.load(folder / row["file"])))
    return out


def measure(engine, pairs, source) -> dict:
    from ocr.base import group_paragraphs

    edits = length = 0
    worst = []
    for item in pairs:
        if source == "captures":
            key, truth, image = item
        else:
            key, truth = item
            image = render(truth)
        text = "\n\n".join(group_paragraphs(engine.read(image)))
        e, n = cer(truth, text)
        edits += e
        length += n
        if n:
            worst.append((e / n, key, truth, text))
    worst.sort(reverse=True)
    return {"edits": edits, "length": length,
            "cer": edits / length if length else 0.0, "worst": worst[:3]}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--limit", type=int, default=40)
    ap.add_argument("--engines", action="store_true",
                    help="every engine installed, on the same pages")
    ap.add_argument("--from-captures", type=Path,
                    help="a folder written by `jime play --save-crops`")
    ap.add_argument("--verbose", action="store_true")
    args = ap.parse_args()

    import jime
    from ocr.base import locales_for, open_ocr

    lang = jime.default_language()
    if args.from_captures:
        pairs, source = captures(args.from_captures, args.limit), "captures"
        print(f"{BOLD}{len(pairs)} real screens{RESET} from "
              f"{args.from_captures}\n")
    else:
        pairs, source = fixtures(args.limit), "synthetic"
        print(f"{BOLD}{len(pairs)} synthetic pages{RESET}, text rebuilt from the "
              f"game's logs, language {lang!r}")
        print(f"{GRAY}A floor, not the answer: the game draws its own font on "
              f"parchment and this is a\nsystem serif on flat grey, so real "
              f"error is at least this and probably more.{RESET}\n")

    names = ["auto"]
    if args.engines:
        names = ["apple", "windows", "rapid"]

    print(f"  {'engine':16} {'CER':>7} {'edits':>8} {'chars':>9}")
    print("  " + "-" * 44)
    results = {}
    for name in names:
        try:
            engine = open_ocr(name, languages=locales_for(lang))
        except Exception as exc:  # noqa: BLE001
            print(f"  {name:16} {GRAY}unavailable — "
                  f"{type(exc).__name__}{RESET}")
            continue
        r = measure(engine, pairs, source)
        results[type(engine).__name__] = r
        colour = GREEN if r["cer"] < 0.01 else YELLOW if r["cer"] < 0.03 else RED
        print(f"  {type(engine).__name__:16} {colour}{100*r['cer']:6.2f}%{RESET} "
              f"{r['edits']:8,} {r['length']:9,}")

    if not results:
        return 1

    print(f"\n{GRAY}The matcher harness reports 99.2% hit at 0% noise, 95.6% at "
          f"2% and 94.2% at 5%.\nWhichever band the number above falls in is the "
          f"row that describes this project.{RESET}")

    if args.verbose:
        for name, r in results.items():
            print(f"\n{BOLD}{name} — worst pages{RESET}")
            for rate, key, truth, got in r["worst"]:
                print(f"  {100*rate:5.1f}%  {key}")
                print(f"    {GRAY}want{RESET} {_norm(truth)[:96]}")
                print(f"    {GRAY}got {RESET} {_norm(got)[:96]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
