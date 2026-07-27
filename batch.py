#!/usr/bin/env python3
"""
batch.py — runs several screens through the OCR → matcher cycle and sums up the result.

Useful for building confidence before committing hours of rendering: instead of
testing one screen at a time, throw a handful in and see the real hit rate.

    ~/jime-venv/bin/python batch.py ~/Downloads/*.webp
    ~/jime-venv/bin/python batch.py ~/Downloads/*.webp --keys keys.txt

With `--keys`, it writes out the list of identified blocks, ready to feed the
renderer:

    ~/jime-venv/bin/python phase2_render.py corpus.json -o audio/ \\
        $(sed 's/^/--key /' keys.txt | tr '\\n' ' ')
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

import demo  # noqa: E402
from matcher import Matcher, load_corpus  # noqa: E402

GREEN, YELLOW, GRAY, RESET = "\033[92m", "\033[93m", "\033[90m", "\033[0m"


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("images", nargs="+", type=Path)
    ap.add_argument("--corpus", type=Path, default=demo.CORPUS)
    ap.add_argument("--campaign")
    ap.add_argument("--crop", default="no")
    ap.add_argument("--keys", type=Path, help="write out the identified keys")
    args = ap.parse_args()

    crop = None
    if args.crop.lower() not in ("no", ""):
        crop = tuple(float(x) for x in args.crop.split(","))  # type: ignore

    campaign = args.campaign or demo.current_scope()[0]
    corpus = load_corpus(args.corpus)
    m = Matcher(corpus, campaign=campaign)
    print(f"[scope] campaign={campaign} | {len(m):,} candidate entries\n")

    found: list[str] = []
    with_block = without_block = 0
    for img in sorted(args.images):
        if not img.exists():
            continue
        try:
            text = demo.ocr(img, crop)
        except Exception as e:  # noqa: BLE001
            print(f"{YELLOW}[failed]{RESET} {img.name}: {e}")
            continue

        results = [r for r in m.match_screen(text) if r.accepted and r.key]
        # narration is what matters; the rest is HUD and buttons
        narr = [r for r in results
                if corpus.get(r.key, {}).get("narration")]
        keys = list(dict.fromkeys(r.key for r in narr))

        if keys:
            with_block += 1
            print(f"{GREEN}[ok]{RESET} {img.name}")
            for r in narr:
                if r.key in keys:
                    keys.remove(r.key)
                    if r.key not in found:
                        found.append(r.key)
                    txt = " ".join(corpus[r.key]["text"].split())[:82]
                    print(f"     {r.key:<38} score {r.score:5.1f}")
                    print(f"     {GRAY}{txt}{RESET}")
        else:
            without_block += 1
            sample = " ".join(text.split())[:70]
            print(f"{YELLOW}[no block]{RESET} {img.name}  {GRAY}{sample}{RESET}")

    n = with_block + without_block
    print(f"\n{'='*72}")
    print(f"screens with an identified narration block: {with_block}/{n} "
          f"({100*with_block/max(n,1):.0f}%)")
    print(f"distinct blocks: {len(found)}")

    if args.keys:
        args.keys.write_text("\n".join(found) + "\n", encoding="utf-8")
        print(f"\n[saved] {args.keys}")


if __name__ == "__main__":
    main()
