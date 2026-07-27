#!/usr/bin/env python3
"""
check_pace.py — pace anomaly detector for the rendered narration.

Autoregressive models like Chatterbox sometimes drift: they repeat a token,
stretch a vowel, or fall into a loop until the forced EOS. The audible symptom is
a block that takes much longer than the text justifies. That was the case of
`bonesofarnor:A1_THREAT_1`, which came out at 1.00 word/s against an average of 2.03.

This script measures words per second of speech for each rendered block and flags
the ones that stray from the median. Use the output to regenerate the suspects with
another seed.

    python3 check_pace.py audio/manifest.json
    python3 check_pace.py audio/manifest.json --mad 3.5 --json suspects.json

About the metric: it divides by *seconds of speech*, not by the raw duration of the
file. The raw duration embeds the pauses inserted between sentences and paragraphs,
which are not proportional to the word count — without discounting them, every short
block looks slow and every long block looks fast, and the detector becomes noise.

Robustness: it uses median and MAD (median absolute deviation), not mean and standard
deviation. The mean is pulled by exactly the outliers you want to find; with few
blocks, a single bad case hides the rest.
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

# these must match the render — if you change them there, change them here
SENTENCE_PAUSE = 0.30
PARAGRAPH_PAUSE = 0.45
TEMPO = 0.96  # DSP atempo/rubberband: the final audio is 1/TEMPO longer

SENT_SPLIT = re.compile(r"(?<=[.!?…])\s+")


def duration(path: Path) -> float | None:
    """Duration in seconds via ffprobe. None if the file cannot be read."""
    try:
        out = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "default=nw=1:nk=1", str(path)],
            capture_output=True, text=True, check=True, timeout=30).stdout.strip()
        return float(out)
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired, ValueError):
        return None


def embedded_pauses(text: str) -> float:
    """How much silence the renderer inserted into this block."""
    paragraphs = [p for p in text.split("\n") if p.strip()]
    sentences = sum(len([s for s in SENT_SPLIT.split(p) if s.strip()])
                    for p in paragraphs)
    return sentences * SENTENCE_PAUSE + len(paragraphs) * PARAGRAPH_PAUSE


def median(xs: list[float]) -> float:
    s = sorted(xs)
    n = len(s)
    return s[n // 2] if n % 2 else (s[n // 2 - 1] + s[n // 2]) / 2


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("manifest", type=Path, help="manifest.json produced by the render")
    ap.add_argument("--root", type=Path,
                    help="base folder of the audio (default: the manifest's folder)")
    ap.add_argument("--mad", type=float, default=3.0,
                    help="how many deviations (MAD) to flag at (default: 3.0)")
    ap.add_argument("--json", type=Path, help="write the suspects to this file")
    args = ap.parse_args()

    root = args.root or args.manifest.parent
    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    if not manifest:
        sys.exit("[error] empty manifest")

    rows, unreadable = [], []
    for key, v in manifest.items():
        audio = root / v["file"]
        if not audio.exists():
            unreadable.append(key)
            continue
        dur = duration(audio)
        if dur is None:
            unreadable.append(key)
            continue
        # undo the DSP stretching and discount the inserted silence
        speech = dur * TEMPO - embedded_pauses(v["text"])
        if speech <= 0.5:
            unreadable.append(key)
            continue
        rows.append({"key": key, "words": v["words"], "dur": dur,
                     "speech": speech, "wps": v["words"] / speech,
                     "file": v["file"]})

    if not rows:
        sys.exit("[error] no readable audio found from the manifest")

    wps = [l["wps"] for l in rows]
    med = median(wps)
    mad = median([abs(w - med) for w in wps]) or 1e-9
    # 1.4826*MAD estimates the standard deviation of a normal; that way the threshold
    # in "--mad 3" means approximately 3 sigmas, and not 3 raw MADs.
    sigma = 1.4826 * mad

    for l in rows:
        l["z"] = (l["wps"] - med) / sigma

    suspects = sorted([l for l in rows if abs(l["z"]) >= args.mad],
                      key=lambda l: l["z"])

    print(f"[pace] {len(rows)} blocks measured"
          + (f" | {len(unreadable)} unreadable/missing" if unreadable else ""))
    print(f"        median {med:.2f} words/s  (~{med*60:.0f} wpm) | "
          f"robust sigma {sigma:.2f} | threshold ±{args.mad}")

    ordered = sorted(rows, key=lambda l: l["wps"])
    print(f"        range {ordered[0]['wps']:.2f} .. {ordered[-1]['wps']:.2f} words/s")

    if not suspects:
        print("\n[ok] no block outside the threshold.")
    else:
        print(f"\n[suspects] {len(suspects)} block(s) — "
              "regenerate with another seed:\n")
        print(f"  {'block':<46} {'w':>4} {'dur':>7} {'w/s':>6} {'z':>7}")
        for l in suspects:
            mark = "slow" if l["z"] < 0 else "fast"
            print(f"  {l['key'][:46]:<46} {l['words']:>4} {l['dur']:>6.1f}s "
                  f"{l['wps']:>6.2f} {l['z']:>+7.1f}  {mark}")

    if args.json:
        args.json.write_text(json.dumps(
            {"median_wps": med, "sigma": sigma, "threshold": args.mad,
             "suspects": suspects}, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"\n[saved] {args.json}")


if __name__ == "__main__":
    main()
