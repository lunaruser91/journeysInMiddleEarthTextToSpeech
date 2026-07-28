#!/usr/bin/env python3
"""
narrator.py — the whole thing: watch the screen, read it, speak it.

    capture → trigger → OCR → matcher → player

Runs from a terminal on macOS and Windows. There is deliberately no bundled
`.app` or `.exe`: on macOS, screen-recording permission attaches to the
*responsible process*, so a script launched from a terminal inherits the
terminal's grant. Signing and notarisation exist to ship a standalone binary,
not to capture, and skipping them removes the most expensive item in the project.

## Running it

    python3 narrator.py --display            # fullscreen game (recommended)
    python3 narrator.py                      # windowed game, by window title
    python3 narrator.py --from-video FILE    # replay a recording, no permission
    python3 narrator.py --list-windows       # what the capture backend can see

The `--from-video` mode exists so the entire chain can be exercised without
granting anything, and so a regression can be reproduced from a file rather than
from a live game.

## Fullscreen games, and why it waits

macOS does not render an inactive Space. A game running fullscreen sits on its
own Space, so while you are looking at the terminal there are no pixels of it to
capture — the window does not even report itself as on screen. So this starts by
waiting: run it, switch to the game, and it attaches as soon as that Space comes
forward. `--wait 0` restores the old fail-immediately behaviour.

## First run on macOS

The first capture triggers the system prompt. If nothing happens and it hangs,
that is the permission being absent: grant it in System Settings → Privacy &
Security → Screen Recording, tick the terminal application, and **restart the
terminal** — the grant is read at launch.

## What gets spoken, and what does not

Blocks whose key contains `CUTSCENE` stay silent: the game narrates those itself,
with recorded voice, in all six campaigns. Blocks carrying a `{0}` placeholder
cannot be pre-rendered because the value only exists during play; they are
reported and skipped until live synthesis exists.
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))

import glyphs  # noqa: E402
from live import LiveVoice, fill_template  # noqa: E402
from matcher import Matcher, load_corpus, normalize  # noqa: E402
from ocr.base import crop, group_paragraphs, open_ocr  # noqa: E402
from player import Player  # noqa: E402
from trigger import REGION, Trigger  # noqa: E402

GREEN, YELLOW, RED, GRAY, RESET = ("\033[92m", "\033[93m", "\033[91m",
                                   "\033[90m", "\033[0m")

ROOT = Path(__file__).resolve().parent
CAMPAIGNS = {1: "bonesofarnor", 2: "shadowedpaths", 3: "spreadingwar",
             4: "hauntingofdale", 5: "poisonpromise", 6: "embercrown"}
SAVES = Path.home() / ("Library/Application Support/"
                       "com.fantasyflightgames.jime/SavedGames")


def current_campaign() -> str | None:
    """Read the campaign from the most recent save, to scope the matcher."""
    import json

    saves = sorted(SAVES.glob("*/SavedGame*"),
                   key=lambda p: p.stat().st_mtime, reverse=True) \
        if SAVES.exists() else []
    for save in saves:
        try:
            return CAMPAIGNS.get(json.loads(save.read_text(encoding="utf-8"))
                                 .get("CampaignId"))
        except Exception:  # noqa: BLE001
            continue
    return None


def frames_from_video(path: Path, fps: float):
    """Yield greyscale frames from a recording, for --from-video."""
    import subprocess

    import PIL.Image

    probe = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0",
         "-show_entries", "stream=width,height", "-of", "csv=p=0", str(path)],
        capture_output=True, text=True, check=True).stdout.strip()
    width, height = (int(x) for x in probe.split(",")[:2])

    proc = subprocess.Popen(
        ["ffmpeg", "-v", "error", "-i", str(path), "-vf", f"fps={fps}",
         "-f", "rawvideo", "-pix_fmt", "gray", "-"],
        stdout=subprocess.PIPE)
    size = width * height
    while True:
        raw = proc.stdout.read(size)
        if len(raw) < size:
            break
        yield np.frombuffer(raw, dtype=np.uint8).reshape(height, width)
    proc.stdout.close()
    proc.wait()


def frames_live(cap, fps: float, grace: float = 300.0):
    """Yield frames from the live capture at roughly `fps`.

    A missing frame is not the end. Switching away from the game's Space, or to
    another application in fullscreen, makes the window stop being rendered and
    `grab()` returns None — but the game has not quit and the session is not
    over. Treating that as the end would stop the narrator every time you checked
    something on another screen.

    So absence is tolerated for `grace` seconds, and only a window that stays
    gone that long ends the run.
    """
    interval = 1.0 / fps
    gone_since: float | None = None
    while True:
        started = time.monotonic()
        frame = cap.grab()
        if frame is None:
            if gone_since is None:
                gone_since = started
                print(f"{GRAY}[waiting] the game window is not being rendered — "
                      f"switch back to it{RESET}", flush=True)
            elif started - gone_since > grace:
                print(f"{GRAY}[done] the window stayed gone for "
                      f"{grace:.0f}s{RESET}")
                return
            time.sleep(0.5)
            continue
        if gone_since is not None:
            print(f"{GRAY}[resumed]{RESET}", flush=True)
            gone_since = None
        yield frame
        time.sleep(max(0.0, interval - (time.monotonic() - started)))


def main() -> None:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--from-video", type=Path,
                    help="replay a recording instead of capturing the screen")
    ap.add_argument("--list-windows", action="store_true")
    ap.add_argument("--lang", default="pt")
    ap.add_argument("--corpus", type=Path, default=ROOT / "corpus" / "corpus_pt.json")
    ap.add_argument("--audio", type=Path, action="append", default=[],
                    help="folder with a manifest.json (repeatable)")
    ap.add_argument("--campaign", help="override the campaign used for scoping")
    ap.add_argument("--fps", type=float, default=10.0)
    ap.add_argument("--region", default=f"{REGION[0]},{REGION[1]}",
                    help="vertical band of the dialogue box, as fractions")
    ap.add_argument("--window", default="", help="window title hint")
    ap.add_argument("--app", default="Journeys", help="application name hint")
    ap.add_argument("--display", type=int, nargs="?", const=0, default=None,
                    metavar="N",
                    help="capture a whole display instead of the game window. "
                         "This is the right choice for a fullscreen game: a "
                         "display shows whichever Space is active, so it keeps "
                         "working when the game has a Space of its own, where "
                         "window capture cannot reach.")
    ap.add_argument("--wait", type=float, default=90.0,
                    help="seconds to wait for the game window to appear. A "
                         "fullscreen game lives on its own Space, which macOS "
                         "does not render while you are looking at another one, "
                         "so the window only becomes capturable once you switch "
                         "to it. Waiting is how you start here and play there.")
    ap.add_argument("--no-audio", action="store_true",
                    help="recognise and report, but stay silent")
    ap.add_argument("--manual", action="store_true",
                    help="hold each screen until a key is pressed")
    args = ap.parse_args()

    from capture.base import (CaptureError, list_windows, open_display,
                              open_window)

    if args.list_windows:
        try:
            for w in list_windows(""):
                print(f"  {w}")
        except CaptureError as exc:
            sys.exit(f"{RED}{exc}{RESET}")
        return

    top, bottom = (float(x) for x in args.region.split(","))

    campaign = args.campaign or current_campaign()
    corpus = load_corpus(args.corpus)
    matcher = Matcher(corpus, campaign=campaign)
    print(f"{GRAY}[scope] campaign={campaign} | {len(matcher):,} candidates{RESET}")

    folders = args.audio or sorted(
        d for d in (ROOT / "output").glob("*") if (d / "manifest.json").exists())
    player = Player(manifests=folders, manual=args.manual, verbose=False)
    print(f"{GRAY}[audio] {len(player):,} blocks rendered{RESET}")

    glyph_map = glyphs.glyph_map_from_corpus(corpus)
    live: LiveVoice | None = None

    engine = open_ocr()
    trigger = Trigger(region=(top, bottom))
    print(f"{GRAY}[ocr] {type(engine).__name__}{RESET}")

    if args.from_video:
        source = frames_from_video(args.from_video, args.fps)
        print(f"{GRAY}[source] replaying {args.from_video.name} at "
              f"{args.fps:g} Hz{RESET}")
        cap = None
    else:
        try:
            if args.display is not None:
                cap = open_display(args.display)
                print(f"{GRAY}[source] display {args.display} — whichever Space "
                      f"is in front{RESET}")
                if args.wait:
                    print(f"{YELLOW}switch to the game now — starting in "
                          f"{args.wait:.0f}s{RESET}")
                    time.sleep(args.wait)
            else:
                cap = open_window(args.window, args.app, wait=args.wait)
                print(f"{GRAY}[source] {cap.window}{RESET}")  # type: ignore[attr-defined]
        except CaptureError as exc:
            sys.exit(f"{RED}{exc}{RESET}")
        source = frames_live(cap, args.fps)

    print(f"\n{GREEN}watching. Ctrl+C to stop.{RESET}\n")
    screens = spoken = 0
    try:
        for frame in source:
            settled = trigger.feed(frame)
            if settled is None:
                continue
            screens += 1

            box = crop(settled, (0.0, top, 1.0, bottom))
            paragraphs = group_paragraphs(engine.read(box))
            text = "\n\n".join(paragraphs)
            if not trigger.accept_text(text, normalize):
                continue

            fresh: set[str] = set()
            results = matcher.match_screen(text)
            keys = [r.key for r in results
                    if r.accepted and r.key and corpus.get(r.key, {}).get("narration")]
            keys = list(dict.fromkeys(keys))
            if not keys:
                snippet = " ".join(text.split())[:70]
                print(f"{YELLOW}[no match]{RESET} {GRAY}{snippet}{RESET}")
                continue

            # Live synthesis first, so the report below can tell the truth
            # about what will be heard. Blocks with a {0} have no pre-rendered
            # audio — the value only exists at the table — but the screen was
            # drawn with it filled in and the OCR just read it, so the template
            # supplies every word but one and the gap comes from the screen.
            for key in keys:
                if player.known(key) or "CUTSCENE" in key:
                    continue
                if not corpus.get(key, {}).get("placeholders"):
                    continue
                if live is None:
                    live = LiveVoice(lang=args.lang)
                filled = fill_template(corpus[key]["text"], text)
                if filled is None:
                    continue
                # not `spoken`: that name is the counter this loop runs inside
                say = glyphs.spell_out_numbers(
                    glyphs.substitute(filled, glyph_map, args.lang), args.lang)
                path = live.say(say)
                if path:
                    player.register(key, path)
                    fresh.add(key)

            played = [] if args.no_audio else player.enqueue(keys)
            spoken += len(played)

            # One line per block, and it says what happens to it. Printing
            # "[screen] KEY" for every match regardless of whether it plays made
            # a de-duplicated repeat look exactly like a repeat.
            for key in keys:
                if key in played:
                    mark = f"{GREEN}[speaking]{RESET}"
                    why = f" {GRAY}(synthesised live){RESET}" if key in fresh else ""
                elif args.no_audio:
                    mark = f"{GRAY}[matched]{RESET}"
                    why = ""
                else:
                    mark = f"{YELLOW}[silent]{RESET}"
                    why = f" {YELLOW}— {player.why_silent(key)}{RESET}"
                print(f"{mark} {key}{why}")
                print(f"          {GRAY}"
                      f"{' '.join(corpus[key]['text'].split())[:84]}{RESET}")
    except KeyboardInterrupt:
        pass
    finally:
        player.stop()
        if cap is not None:
            cap.close()
        print(f"\n{GRAY}[done] {screens} screens settled, {spoken} blocks "
              f"spoken{RESET}")


if __name__ == "__main__":
    main()
