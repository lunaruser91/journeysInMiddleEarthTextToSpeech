#!/usr/bin/env python3
"""
demo.py — the whole cycle on a single screen: image → OCR → matcher → audio.

This is here so you can see (and hear) the system working BEFORE committing the
~19 h of machine time that rendering a whole campaign costs. Grab a screenshot
of the game and hand it over:

    python3 demo.py ~/Desktop/screen.png

What happens:

  1. **OCR** with Apple Vision (offline, native pt-BR, ~150 ms). It is the
     engine the briefing recommends and the same one Phase 3 would use.
  2. **Matching** with `matcher.py`, scoped by the campaign of the current save.
     It shows the score, the margin and the length ratio — the locks — so you
     can see *why* it accepted or refused.
  3. **Audio**: it looks the block up in the manifest of an existing render and
     plays it. If it is not there and you pass `--render`, it synthesizes that
     block on the spot (~1 min) and plays it. This is the "render on demand"
     that the briefing lists as a lever.

Useful options:

    --no-audio        OCR + matching only, plays nothing
    --render          synthesizes the block if it does not exist yet
    --audio FOLDER    where to look for the manifest.json of a render
    --crop            limits the OCR to the text box (see --show-crop)

Nothing here writes to the game. It only reads the image you handed it.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

import console  # noqa: E402

console.setup()

from matcher import Matcher, load_corpus, normalize, paragraphs  # noqa: E402

CORPUS = Path(__file__).resolve().parent / "corpus" / "corpus_pt.json"
SAVES = console.saves_dir()
CAMPAIGNS = {1: "bonesofarnor", 2: "shadowedpaths", 3: "spreadingwar",
             4: "hauntingofdale", 5: "poisonpromise", 6: "embercrown"}

GREEN, RED, YELLOW, GRAY, RESET = ("\033[92m", "\033[91m", "\033[93m",
                                   "\033[90m", "\033[0m")


def ocr(path: Path, region: tuple[float, float, float, float] | None) -> str:
    """Read the image, via the shared OCR layer.

    The engine choice and the line-to-paragraph reconstruction both live in
    ocr/base.py, so this tool, batch.py and narrator.py cannot drift apart on
    the part that turned out to matter most — see that module on why grouping
    lines into paragraphs is not optional.
    """
    import numpy as np
    from PIL import Image

    from ocr.base import crop as crop_region
    from ocr.base import group_paragraphs, open_ocr

    image = np.asarray(Image.open(path).convert("L"))
    if region:
        image = crop_region(image, region)

    t0 = time.perf_counter()
    engine = open_ocr()
    lines = engine.read(image)
    dt = (time.perf_counter() - t0) * 1000
    paragraphs = group_paragraphs(lines)
    print(f"{GRAY}[ocr] {type(engine).__name__}, {dt:.0f} ms, {len(lines)} lines "
          f"regrouped into {len(paragraphs)} paragraph(s){RESET}")
    return "\n\n".join(paragraphs)


def find_audio(key: str, folders: list[Path]) -> Path | None:
    for folder in folders:
        man = folder / "manifest.json"
        if not man.exists():
            continue
        try:
            m = json.loads(man.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            continue
        if key in m:
            p = folder / m[key]["file"]
            if p.exists():
                return p
    return None


def play(p: Path) -> None:
    print(f"{GREEN}[playing]{RESET} {p.name}")
    subprocess.run(["afplay", str(p)], check=False)


def current_scope() -> tuple[str | None, int | None]:
    """Finds the campaign and adventure of the most recent save."""
    saves = sorted(SAVES.glob("*/SavedGame*"),
                   key=lambda p: p.stat().st_mtime, reverse=True)
    for s in saves:
        try:
            j = json.loads(s.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            continue
        return CAMPAIGNS.get(j.get("CampaignId")), j.get("CurrentAdventureId")
    return None, None


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("image", type=Path, nargs="?",
                    help="path of the image; if omitted, uses the most recent "
                         "screenshot on the Desktop")
    ap.add_argument("--corpus", type=Path, default=CORPUS)
    ap.add_argument("--audio", type=Path, action="append", default=[],
                    help="folder with the manifest.json of a render (repeatable)")
    ap.add_argument("--no-audio", action="store_true")
    ap.add_argument("--render", action="store_true",
                    help="synthesize the block on the spot if it does not exist")
    ap.add_argument("--crop", default="0.05,0.10,0.95,0.45",
                    help="left,top,right,bottom as a fraction of the image; "
                         "'no' turns it off")
    ap.add_argument("--campaign", help="force the campaign of the scope")
    args = ap.parse_args()

    if args.image is None or not args.image.exists():
        # convenience: take the latest screenshot, so you need not type a path
        cands = [p for d in (Path.home() / "Desktop", Path.home() / "Downloads")
                 if d.exists()
                 for p in d.iterdir()
                 if p.suffix.lower() in (".png", ".jpg", ".jpeg", ".webp",
                                         ".heic", ".tif", ".tiff", ".bmp")]
        if not cands:
            sys.exit(
                f"[error] {'image not found: ' + str(args.image) if args.image else 'no image given'}\n"
                "        and I found no screenshot at all on the Desktop.\n\n"
                "        Take one with  Cmd+Shift+4  (drag and select the text box)\n"
                "        or             Cmd+Shift+3  (whole screen)\n"
                "        and run again — with no argument at all, so I take the most recent one.")
        args.image = max(cands, key=lambda p: p.stat().st_mtime)
        print(f"{GRAY}[image] using the most recent screenshot: "
              f"{args.image.name}{RESET}")

    crop = None
    if args.crop.lower() not in ("no", ""):
        crop = tuple(float(x) for x in args.crop.split(","))  # type: ignore

    text = ocr(args.image, crop)
    print(f"\n{GRAY}--- text read from the screen ---{RESET}")
    print(text)

    campaign, adventure = current_scope()
    campaign = args.campaign or campaign
    print(f"\n{GRAY}[scope] campaign={campaign} adventure={adventure} "
          f"(from the most recent save){RESET}")

    corpus = load_corpus(args.corpus)
    m = Matcher(corpus, campaign=campaign)
    print(f"{GRAY}[scope] {len(m):,} candidate entries{RESET}")

    print(f"\n{GRAY}--- matching, paragraph by paragraph ---{RESET}")
    results = m.match_screen(text)
    chosen: list[str] = []
    for i, r in enumerate(results):
        color = GREEN if r.accepted else YELLOW
        mark = "ACCEPTED" if r.accepted else "refused "
        print(f"{color}[{mark}]{RESET} par.{i+1}  {r.key or '—'}")
        print(f"          score {r.score:5.1f}  margin {r.margin:5.1f}  "
              f"ratio {r.length_ratio:.2f}   {GRAY}{r.reason}{RESET}")
        if r.accepted and r.key:
            print(f"          {GRAY}corpus: "
                  f"{' '.join(corpus[r.key]['text'].split())[:100]}{RESET}")
            if r.key not in chosen:
                chosen.append(r.key)

    if not chosen:
        print(f"\n{RED}No block identified with confidence.{RESET}")
        print("In Phase 3 this would turn into silence (recoverable with live TTS),")
        print("never a wrong narration. Try --crop no, or adjust the band.")
        return

    if args.no_audio:
        return

    # everything that gets generated lives in output/, inside the repository
    base = Path(__file__).resolve().parent / "output"
    folders = args.audio or ([base / "audio"] +
                             sorted(d for d in base.glob("*") if d.is_dir()))
    print()
    for key in chosen:
        p = find_audio(key, folders)
        if p:
            play(p)
        elif args.render:
            print(f"{YELLOW}[render]{RESET} {key} does not exist yet; "
                  f"synthesizing (takes ~1 min)...")
            synthesize_and_play(key, corpus, args.corpus)
        else:
            print(f"{YELLOW}[no audio]{RESET} {key} — use --render to "
                  f"synthesize on the spot, or point --audio at an existing render")


def synthesize_and_play(key: str, corpus: dict, corpus_path: Path) -> None:
    """Renders a single block on demand, reusing the production renderer.

    Uses the renderer's `--key`, which renders exactly the requested block. An
    earlier version passed `--limit 1` instead, which silently rendered the first
    block of the campaign — the wrong audio, played with no warning. That was
    written before `--key` existed and never revisited.
    """
    # Blocks with a {0} placeholder only resolve at play time, so the renderer
    # skips them by design. Saying so beats reporting a generic failure.
    if corpus.get(key, {}).get("placeholders"):
        print(f"{YELLOW}[dynamic]{RESET} {key} carries "
              f"{corpus[key]['placeholders']} — the value only exists during play, "
              f"so it cannot be pre-rendered. This is one of the blocks that needs "
              f"live TTS in phase 3.")
        return

    root = Path(__file__).resolve().parent
    out = root / "output" / "on-demand"
    out.mkdir(parents=True, exist_ok=True)
    cmd = [sys.executable, str(root / "phase2_render.py"), str(corpus_path),
           "-o", str(out), "--key", key]
    subprocess.run(cmd, check=False, cwd=root)
    p = find_audio(key, [out])
    if p:
        play(p)
    else:
        print(f"{YELLOW}[failed]{RESET} {key} was not rendered — run "
              f"phase2_render.py --key '{key}' by hand to see the error")


if __name__ == "__main__":
    main()
