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

A fullscreen game is unreachable by window capture on both platforms, for
different reasons: macOS gives it a Space of its own and does not draw an
inactive Space, and Windows lets exclusive fullscreen bypass the compositor that
Windows.Graphics.Capture reads from. `--display` gets around both.

What a display gives back is the whole monitor, and the game is only part of
what is on it. So the run waits until the game is the window in front — and once
watching, reads nothing while it is not. Without that guard a Windows session
OCR-ed its own console and reported "no match" against the menu it had just
printed. `--wait 0` starts immediately.

## First run on macOS

The first capture triggers the system prompt. If nothing happens and it hangs,
that is the permission being absent: grant it in System Settings → Privacy &
Security → Screen Recording, tick the terminal application, and **restart the
terminal** — the grant is read at launch.

## What gets spoken, and what does not

Blocks whose key contains `CUTSCENE` stay silent: the game narrates those itself,
with recorded voice, in all six campaigns.

Blocks carrying a `{0}` placeholder cannot be pre-rendered, because the value
only exists at the table — so they are synthesised during play, from the corpus
template with the screen's own value in the gap (see live.py).

A block is also cut down to what the screen is actually showing. The game
composes a box from pieces of several blocks, so playing a whole recording
narrates paragraphs that are not there. And when two blocks tie, only the
paragraph they share is spoken: that is the part the tie agrees on.
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))

import console  # noqa: E402

console.setup()

import glyphs  # noqa: E402
from i18n import t  # noqa: E402
from live import LiveVoice, fill_template  # noqa: E402
from matcher import Matcher, load_corpus, normalize  # noqa: E402
from matcher import paragraphs as mparagraphs  # noqa: E402
from ocr.base import crop, group_paragraphs, locales_for, open_ocr  # noqa: E402
from player import Player  # noqa: E402
from trigger import REGION, Trigger  # noqa: E402

GREEN, YELLOW, RED, GRAY, RESET = ("\033[92m", "\033[93m", "\033[91m",
                                   "\033[90m", "\033[0m")

ROOT = Path(__file__).resolve().parent
CAMPAIGNS = {1: "bonesofarnor", 2: "shadowedpaths", 3: "spreadingwar",
             4: "hauntingofdale", 5: "poisonpromise", 6: "embercrown"}
SAVES = console.saves_dir()


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


# A paragraph counts as present when the screen nearly contains it. Exact
# containment was the first attempt and it is too strict for OCR: Apple Vision
# reads the game's icons as stray characters rather than as nothing, and a
# single "m" read as "rn" is enough. Measured on the screen that exposed this,
# a paragraph the OCR had plainly read scored 94-97 and was judged absent, so
# only the first half of the block was spoken.
#
# 88 sits above the matcher's own 82 and below its safe 92: high enough that a
# different paragraph does not pass, low enough to survive a misread icon.
ON_SCREEN_SCORE = 88.0
MIN_PARAGRAPH = 12


def _visible(parts: list[str], norm_screen: str) -> list[bool]:
    """Which of a block's paragraphs this screen is showing.

    A long paragraph answers for itself, by similarity. A short one cannot:
    "Teste ⚔ 2" or "Sofra 1 dano" is a handful of characters, and a fuzzy score
    over a handful of characters finds them somewhere in almost any screen.

    They used to be assumed present, on the reasoning that carving a block up on
    weak evidence was worse than reading a line twice. But in this corpus the
    short paragraphs are precisely the actionable ones — the tests, the damage,
    the tokens to place — and 990 of them were being read out whether or not the
    game was showing them. Telling a table to suffer a wound it was never dealt
    is a different kind of wrong from saying a sentence twice.

    So a short paragraph is present when the screen literally contains it, or
    when a paragraph beside it was found — the game draws these attached to the
    prose they belong to, and a neighbour is evidence where the text is not.
    """
    from rapidfuzz import fuzz

    scored: list[bool | None] = []
    for p in parts:
        norm = normalize(p)
        scored.append(None if len(norm) < MIN_PARAGRAPH
                      else fuzz.partial_ratio(norm, norm_screen) >= ON_SCREEN_SCORE)

    out: list[bool] = []
    for i, hit in enumerate(scored):
        if hit is not None:
            out.append(hit)
            continue
        norm = normalize(parts[i])
        near = [scored[j] for j in (i - 1, i + 1) if 0 <= j < len(scored)]
        out.append(bool(norm and norm in norm_screen) or any(n is True for n in near))
    return out


def matched_paragraph(block_text: str, norm_matched: str) -> str | None:
    """The block's own wording for the paragraph the matcher scored.

    Used when two blocks tie. A tie means the text scored identically against
    both, which means it is present in both — so speaking exactly that paragraph
    is right whichever key won, and everything *else* in the block is precisely
    what the guess would have got wrong. Refusing ties instead costs 7% of all
    screens; guessing costs 0.5% of them spoken wrong. Saying only what tied
    costs neither.

    The matcher hands back its normalised form — lowercased, unaccented — which
    is for locating and not for speaking. The words come from the block.
    """
    for para in mparagraphs(block_text):
        if normalize(para) == norm_matched:
            return para
    return None


def await_game(app_hint: str, title_hint: str, wait: float,
               lang: str = "en") -> None:
    """Hold until the game is the window in front, or until `wait` runs out.

    A fixed countdown was the old answer, and it is a guess about how fast
    someone can alt-tab. When it guessed wrong the narrator started reading the
    desktop — in one session, its own console, reporting "no match" against the
    menu it had just printed. Asking the window manager costs nothing and is
    never wrong.
    """
    from capture.base import is_foreground

    if is_foreground(app_hint, title_hint) is None:
        print(YELLOW + t("switch to the game now — starting in {n}s", lang,
                         n=f"{wait:.0f}") + RESET)
        time.sleep(wait)
        return

    print(YELLOW + t("switch to the game now — this starts when it is in front",
                     lang) + RESET)
    deadline = time.monotonic() + wait
    while time.monotonic() < deadline:
        if is_foreground(app_hint, title_hint):
            return
        time.sleep(0.3)
    print(GRAY + "[waiting] " + t("the game has not come forward — watching "
                                  "anyway, and staying quiet until it does",
                                  lang) + RESET)


def frames_from_video(path: Path, fps: float):
    """Yield greyscale frames from a recording, for --from-video."""
    import subprocess

    import PIL.Image

    probe = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0",
         "-show_entries", "stream=width,height", "-of", "csv=p=0", str(path)],
        capture_output=True, text=True, check=True,
        encoding="utf-8", errors="replace").stdout.strip()
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
                         "This is the right choice for a fullscreen game, which "
                         "window capture cannot reach — on macOS because the "
                         "game owns a Space that is not drawn while you are "
                         "elsewhere, on Windows because exclusive fullscreen "
                         "bypasses the compositor. It captures the whole "
                         "monitor, so nothing is read while the game is not the "
                         "window in front.")
    ap.add_argument("--wait", type=float, default=90.0,
                    help="seconds to wait for the game to come forward before "
                         "starting anyway. With --display the wait ends as soon "
                         "as the game is the window in front; with window "
                         "capture it ends when the window becomes capturable. "
                         "Either way it is how you start here and play there.")
    ap.add_argument("--profile", action="store_true",
                    help="time each stage and print it per screen. Use this "
                         "when the narrator reacts slowly: the delay between a "
                         "line appearing and being read is made of the game's "
                         "own animation, the OCR, the matcher and the "
                         "synthesis, and only one of those is worth tuning at "
                         "a time.")
    ap.add_argument("--no-guard", action="store_true",
                    help="with --display, read the monitor even while the game "
                         "is not the window in front. The guard is what stops "
                         "the narrator reading the desktop, so this is for when "
                         "the guard itself is wrong about which window is the "
                         "game.")
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

    engine = open_ocr(languages=locales_for(args.lang))
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
                print(f"{GRAY}[source] display {args.display} — everything drawn "
                      f"on this monitor, including this window{RESET}")
                if args.wait:
                    await_game(args.app, args.window, args.wait,
                               args.lang)
            else:
                cap = open_window(args.window, args.app, wait=args.wait)
                print(f"{GRAY}[source] {cap.window}{RESET}")  # type: ignore[attr-defined]
        except CaptureError as exc:
            sys.exit(f"{RED}{exc}{RESET}")
        source = frames_live(cap, args.fps)

    # Display capture takes the monitor, not the game. Anything else in front is
    # captured too and read as if it were a game screen, so the loop holds its
    # tongue whenever the game is not the window in front. Window capture needs
    # no guard: it can only ever see the game.
    from capture.base import is_foreground

    # It has to tolerate a gap. Reported from a real session, the guard flapped
    # between quiet and watching several times a second: a fullscreen game does
    # not hold the foreground steadily — overlays, the compositor, and whatever
    # the window manager is doing between frames all show up as a sample where
    # something else is in front. One sample is not evidence. A second of them
    # is.
    #
    # The direction is deliberately asymmetric: it goes quiet slowly and comes
    # back at once, because the cost of the two mistakes is not the same. Reading
    # the desktop for a second is noise; missing the first line of a screen is
    # the thing the narrator exists to prevent.
    AWAY_AFTER = 1.5
    guard = (args.display is not None and not args.from_video
             and not args.no_guard
             and is_foreground(args.app, args.window) is not None)
    away = False
    not_since: float | None = None

    print("\n" + GREEN + t("watching. Ctrl+C to stop.", args.lang) + RESET + "\n")
    # Counted where it is known. A block reaching the queue is not a block
    # heard: the next screen interrupts what is playing, so the honest label
    # for this number is the one it measures.
    screens = queued = 0
    try:
        for frame in source:
            if guard and not is_foreground(args.app, args.window):
                now = time.monotonic()
                if not_since is None:
                    not_since = now
                if now - not_since >= AWAY_AFTER:
                    if not away:
                        away = True
                        # Name what is in front. When this fires while the game
                        # plainly is in front, that string is the whole answer:
                        # the hint does not match what the system calls the game.
                        from capture.base import foreground
                        print(GRAY + "[waiting] "
                              + t("the game is not in front — nothing on this "
                                  "monitor is being read", args.lang)
                              + f" ({foreground()})" + RESET, flush=True)
                    continue
            else:
                not_since = None
                if away:
                    away = False
                    print(f"{GRAY}[{t('resumed', args.lang)}]{RESET}", flush=True)

            settled = trigger.feed(frame)
            if settled is None:
                continue
            screens += 1
            settling = trigger.settling
            t0 = time.monotonic()

            box = crop(settled, (0.0, top, 1.0, bottom))
            paragraphs = group_paragraphs(engine.read(box))
            text = "\n\n".join(paragraphs)
            t_ocr = time.monotonic()
            if not trigger.accept_text(text, normalize):
                continue

            fresh: set[str] = set()
            results = matcher.match_screen(text)
            keys = [r.key for r in results
                    if r.accepted and r.key and corpus.get(r.key, {}).get("narration")]
            keys = list(dict.fromkeys(keys))

            # The game does not always break where the corpus does. Matching
            # paragraph by paragraph respects how the game *composes* a box out
            # of several blocks, which is usually right — but when the box
            # renders one block's prose as two paragraphs, each half is judged
            # against the whole block's length and fails for being an excerpt.
            # Measured on a real screen: two halves at length ratio 0.41 and
            # 0.39 against a floor of 0.75, both refused, and a block plainly on
            # the screen went unread while the log said "no match".
            #
            # Putting the screen back together as one target scores 0.99. This
            # only runs when nothing matched, so it cannot override the
            # composition case, and it passes every guard the others did.
            if not keys:
                whole = matcher.match_text(text)
                if (whole.accepted and whole.key
                        and corpus.get(whole.key, {}).get("narration")):
                    keys, results = [whole.key], [whole]

            # Blocks that scored level with another. The matcher lets a long
            # paragraph through on a tie, because refusing every tie silences 7%
            # of all screens to prevent 0.5% being spoken wrong — but the key it
            # then picks is the first in corpus order, which is a guess. What is
            # not a guess is the paragraph that tied: it scored the same against
            # both, so it is in both. Speaking only that is right either way.
            tied = {r.key: r.text for r in results
                    if r.accepted and r.key and r.text
                    and r.margin < matcher.min_tie_margin}

            # Which paragraph did each block match? A template whose placeholder
            # sits at the start — "{0}\n\nPlace a search token" — has no anchor
            # before the gap, so given the whole screen it takes everything up to
            # the first anchored word as the value. On a two-block screen that is
            # the other block's prose, and the player hears it twice: once from
            # its own audio, once inside this one. Aligning against the paragraph
            # that actually matched keeps each block to its own text.
            source = {}
            for r in results:
                if not (r.accepted and r.key and r.text):
                    continue
                for para in paragraphs:
                    if r.text in normalize(para):
                        source.setdefault(r.key, para)
                        break
            if not keys:
                # Say why. "[no match]" plus 70 characters of screen was not
                # enough to tell a screen that is genuinely not in the corpus
                # from one the matcher refused for a reason — and the refusal
                # reasons are the only thing that distinguishes a bad crop from
                # bad OCR from a real gap in the corpus.
                print(f"{YELLOW}[no match]{RESET} "
                      f"{GRAY}{' '.join(text.split())[:70]}{RESET}")
                for r in results[:3]:
                    if r.key:
                        print(f"           {GRAY}closest {r.key} "
                              f"({r.score:.0f}) — {r.reason}{RESET}")
                continue

            t_match = time.monotonic()

            # Speak what is on the screen, and only that.
            #
            # Pre-rendered audio covers a whole block, but the matcher indexes
            # each paragraph separately and a screen often shows only one of
            # them — the game composes a box from pieces of different blocks.
            # Playing the block then narrates paragraphs that are not there,
            # which is what a session turned up: a screen showing "a hero with a
            # rosehip token may apply the antidote" also heard the paragraph
            # before it, from a box shown minutes earlier.
            #
            # A {0} block needs synthesis for the other reason — the value only
            # exists at the table — and both paths land here because both need
            # audio that no manifest can hold.
            # Why a block will not be spoken, when that is decided here. It
            # matters that this removes the key from what gets enqueued: every
            # escape below used to `continue` out of the *synthesis* only, and
            # the key stayed in the list handed to the player, which then found
            # the block's own recording and played it whole. The screen showing
            # one paragraph heard all four, and the log said "no audio rendered"
            # for a block that had just been declared unalignable.
            norm_screen = normalize(text)
            live_audio: dict[str, Path] = {}
            mute: dict[str, str] = {}
            for key in keys:
                if "CUTSCENE" in key:
                    continue
                block = corpus.get(key, {})
                if not block:
                    continue

                # A one-paragraph block that ties needs nothing: its recording is
                # that paragraph, so whichever key won says the same words.
                if key in tied and len(mparagraphs(block["text"])) > 1:
                    say_text = matched_paragraph(block["text"], tied[key])
                    if say_text is None:
                        mute[key] = t("cannot align with the screen", args.lang)
                        continue
                    if block.get("placeholders") and "{" in say_text:
                        say_text = fill_template(say_text,
                                                 source.get(key) or text)
                        if say_text is None:
                            mute[key] = t("cannot align with the screen",
                                          args.lang)
                            continue
                elif block.get("placeholders"):
                    say_text = None
                    for context in (source.get(key), text):
                        if context is None:
                            continue
                        say_text = fill_template(block["text"], context)
                        if say_text is not None:
                            break
                    if say_text is None:
                        mute[key] = t("cannot align with the screen", args.lang)
                        continue
                else:
                    parts = mparagraphs(block["text"])
                    on = _visible(parts, norm_screen)
                    showing = [p for p, ok in zip(parts, on) if ok]
                    if len(showing) == len(parts):
                        continue          # the block's own audio is right
                    if not showing:
                        mute[key] = t("none of it is on the screen", args.lang)
                        continue
                    say_text = "\n\n".join(showing)

                if live is None:
                    live = LiveVoice(lang=args.lang)
                say = glyphs.spell_out_numbers(
                    glyphs.substitute(say_text, glyph_map, args.lang), args.lang)
                path = live.say(say)
                if path:
                    live_audio[key] = path
                    fresh.add(key)
                else:
                    mute[key] = t("live synthesis produced nothing", args.lang)

            t_synth = time.monotonic()
            speak = [k for k in keys if k not in mute]
            played = ([] if args.no_audio
                      else player.enqueue(speak, audio=live_audio))
            if args.profile:
                print(f"{GRAY}  [profile] settling {settling:5.2f}s  "
                      f"ocr {t_ocr - t0:5.2f}s  match {t_match - t_ocr:5.2f}s  "
                      f"synth {t_synth - t_match:5.2f}s  "
                      f"queued {player.pending}, "
                      f"{'playing' if player.playing else 'idle'}{RESET}",
                      flush=True)
            queued += len(played)

            # One line per block, and it says what happens to it. Printing
            # "[screen] KEY" for every match regardless of whether it plays made
            # a de-duplicated repeat look exactly like a repeat.
            for key in keys:
                if key in played:
                    mark = f"{GREEN}[speaking]{RESET}"
                    why = f" {GRAY}(synthesised live){RESET}" if key in fresh else ""
                elif key in mute:
                    mark = f"{YELLOW}[silent]{RESET}"
                    why = f" {YELLOW}— {mute[key]}{RESET}"
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
        # A second Ctrl+C is not news — it is the same person pressing the same
        # key harder, usually because the first one did not seem to do anything.
        # Unprotected, it unwinds straight out of player.stop() before the child
        # process has been killed: the narrator prints a traceback and keeps
        # talking. Shutdown absorbs interrupts and is idempotent, so pressing it
        # again just runs it again.
        while True:
            try:
                player.stop()
                if cap is not None:
                    cap.close()
                print("\n" + GRAY + "[done] "
                      + t("{screens} screens settled, {queued} blocks queued",
                          args.lang, screens=screens, queued=queued) + RESET)
                break
            except KeyboardInterrupt:
                continue


if __name__ == "__main__":
    main()
