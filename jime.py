#!/usr/bin/env python3
"""
jime — one front door for the whole narrator.

    jime status                     what is done and what is missing
    jime doctor                     is this machine ready?
    jime extract --lang pt          game assets  ->  corpus
    jime render  --campaign X       corpus       ->  audio
    jime play    --campaign X       narrate a live game
    jime test    --video FILE       exercise recognition without capturing
    jime check                      audit rendered audio for bad pace
    jime glyphs  --lang pt          icon coverage for a language

Every subcommand delegates to the module that does the work; nothing is
reimplemented here. `jime <command> --help` shows that module's full options.

## Languages

The game ships 13 localisations. Ten of them can be narrated, because that is
where the game's languages and the speech model's languages overlap. Czech,
Hungarian and Ukrainian have game text but no voice — the corpus extracts fine
and everything up to synthesis works, so they are still useful for reading.

Icon vocabularies (`glyphs.py`) are filled for Portuguese and English. Any other
language extracts and renders, but the game's icons will be dropped rather than
spoken until someone fills in ~21 words. `jime glyphs --lang <code>` says exactly
what is missing.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

GREEN, YELLOW, RED, GRAY, BOLD, RESET = ("\033[92m", "\033[93m", "\033[91m",
                                         "\033[90m", "\033[1m", "\033[0m")

# The game's localisations, and whether the speech model can voice them.
GAME_LANGUAGES = ["cz", "de", "en", "es", "fr", "hu", "it", "ko", "pl",
                  "pt", "ru", "uk", "zh"]
VOICEABLE = {"de", "en", "es", "fr", "it", "ko", "pl", "pt", "ru", "zh"}
LANGUAGE_NAMES = {
    "cz": "Czech", "de": "German", "en": "English", "es": "Spanish",
    "fr": "French", "hu": "Hungarian", "it": "Italian", "ko": "Korean",
    "pl": "Polish", "pt": "Portuguese (BR)", "ru": "Russian",
    "uk": "Ukrainian", "zh": "Chinese",
}
CAMPAIGNS = ["bonesofarnor", "embercrown", "hauntingofdale", "main",
             "poisonpromise", "shadowedpaths", "spreadingwar"]

# Where the game keeps its assets, per platform. Used to guess so the user does
# not have to type a path that is always in the same place.
ASSET_GUESSES = [
    Path.home() / "Library/Application Support/Steam/steamapps/common/"
                  "Journeys in Middle-earth/JiME.app/Contents/Resources/Data/"
                  "StreamingAssets/bundles",
    Path("C:/Program Files (x86)/Steam/steamapps/common/"
         "Journeys in Middle-earth/JiME_Data/StreamingAssets/bundles"),
]


def corpus_path(lang: str) -> Path:
    return ROOT / "corpus" / f"corpus_{lang}.json"


def audio_dir(lang: str) -> Path:
    return ROOT / "output" / ("audio" if lang == "pt" else f"audio_{lang}")


def _run(module: str, argv: list[str]) -> int:
    """Delegate to a module's own CLI, so options never diverge from the docs."""
    return subprocess.call([sys.executable, str(ROOT / module), *argv])


def find_assets() -> Path | None:
    for guess in ASSET_GUESSES:
        if (guess / "manifest.dat").exists():
            return guess
    return None


# ------------------------------------------------------------------ status --

def cmd_status(args: argparse.Namespace) -> int:
    print(f"{BOLD}corpus{RESET}")
    found = False
    for lang in GAME_LANGUAGES:
        path = corpus_path(lang)
        if not path.exists():
            continue
        found = True
        data = json.loads(path.read_text(encoding="utf-8"))
        narration = [v for v in data.values()
                     if v.get("narration") and not v.get("placeholders")]
        voice = "" if lang in VOICEABLE else f"  {YELLOW}(no voice available){RESET}"
        print(f"  {GREEN}✓{RESET} {lang}  {LANGUAGE_NAMES.get(lang, lang):<18} "
              f"{len(data):>6,} keys, {len(narration):>6,} to narrate{voice}")
    if not found:
        print(f"  {YELLOW}none extracted yet — run: jime extract --lang pt{RESET}")

    print(f"\n{BOLD}audio{RESET}")
    any_audio = False
    for lang in GAME_LANGUAGES:
        folder = audio_dir(lang)
        manifest = folder / "manifest.json"
        if not manifest.exists():
            continue
        any_audio = True
        entries = json.loads(manifest.read_text(encoding="utf-8"))
        by_campaign: dict[str, int] = {}
        for key in entries:
            by_campaign[key.split(":", 1)[0]] = by_campaign.get(
                key.split(":", 1)[0], 0) + 1
        size = sum(f.stat().st_size for f in folder.rglob("*.opus")) / 1e6
        print(f"  {GREEN}✓{RESET} {lang}  {len(entries):>6,} blocks, {size:>6.0f} MB")
        for campaign, count in sorted(by_campaign.items()):
            total = _campaign_total(lang, campaign)
            pct = f"{100 * count / total:.0f}%" if total else "?"
            print(f"       {campaign:<18} {count:>5,} / {total or '?':<6} {pct}")
    if not any_audio:
        print(f"  {YELLOW}none rendered yet — run: jime render --campaign "
              f"bonesofarnor{RESET}")

    # Ad-hoc renders: everything else under output/ that carries a manifest.
    # They are not part of any language's canonical set, but the player and the
    # narrator will happily use them, so hiding them would be misleading.
    canonical = {audio_dir(lang).resolve() for lang in GAME_LANGUAGES}
    others = [d for d in sorted((ROOT / "output").glob("*"))
              if (d / "manifest.json").exists() and d.resolve() not in canonical]
    if others:
        print(f"\n{BOLD}other renders{RESET} {GRAY}(tests and one-offs; the "
              f"player uses these too){RESET}")
        for folder in others:
            entries = json.loads((folder / "manifest.json").read_text(
                encoding="utf-8"))
            print(f"  {GRAY}·{RESET} {folder.name:<22} {len(entries):>4} blocks")

    print(f"\n{BOLD}game assets{RESET}")
    assets = find_assets()
    print(f"  {GREEN}✓{RESET} {assets}" if assets else
          f"  {YELLOW}not found automatically — pass --bundles to extract{RESET}")
    return 0


def _campaign_total(lang: str, campaign: str) -> int:
    path = corpus_path(lang)
    if not path.exists():
        return 0
    data = json.loads(path.read_text(encoding="utf-8"))
    return sum(1 for k, v in data.items()
               if k.startswith(f"{campaign}:") and v.get("narration")
               and not v.get("placeholders"))


# ------------------------------------------------------------------ doctor --

def cmd_doctor(args: argparse.Namespace) -> int:
    ok = True

    def check(label: str, good: bool, detail: str = "") -> None:
        nonlocal ok
        mark = f"{GREEN}✓{RESET}" if good else f"{RED}✗{RESET}"
        print(f"  {mark} {label:<34} {GRAY}{detail}{RESET}")
        ok = ok and good

    print(f"{BOLD}core{RESET}")
    check("python", sys.version_info[:2] >= (3, 12),
          f"{sys.version_info.major}.{sys.version_info.minor} "
          f"(3.14 has no PyTorch wheels)")
    for module, why in (("rapidfuzz", "matching"), ("numpy", "trigger"),
                        ("PIL", "images"), ("num2words", "spoken numbers")):
        try:
            __import__(module)
            check(module, True, why)
        except ImportError:
            check(module, False, f"{why} — pip install -e .")

    print(f"\n{BOLD}audio{RESET}")
    check("ffmpeg", bool(shutil.which("ffmpeg")), "DSP chain")
    check("ffplay", bool(shutil.which("ffplay")),
          "playback — afplay cannot decode Opus")

    print(f"\n{BOLD}recognition{RESET}")
    try:
        from ocr.base import open_ocr
        engine = open_ocr()
        check("OCR", True, type(engine).__name__)
    except Exception as exc:  # noqa: BLE001
        check("OCR", False, str(exc).split("\n")[0])
    try:
        from capture.base import list_windows
        windows = list_windows("")
        check("screen capture", True, f"{len(windows)} windows visible")
        game = [w for w in windows if "journey" in w.app.lower()]
        print(f"  {GREEN if game else YELLOW}{'✓' if game else '!'}{RESET} "
              f"{'game window':<34} {GRAY}"
              f"{game[0] if game else 'game not running'}{RESET}")
    except Exception as exc:  # noqa: BLE001
        first = str(exc).split("\n")[0]
        check("screen capture", False, first)
        print(f"    {GRAY}This is usually the permission. System Settings → "
              f"Privacy & Security →\n    Screen Recording → tick your terminal, "
              f"then restart the terminal.{RESET}")

    print(f"\n{BOLD}synthesis{RESET} {GRAY}(only needed to render){RESET}")
    try:
        import torch
        device = ("mps" if torch.backends.mps.is_available()
                  else "cuda" if torch.cuda.is_available() else "cpu")
        check("torch", True, f"device: {device}"
              + ("  — CPU rendering is ~8x slower" if device == "cpu" else ""))
    except ImportError:
        check("torch", False, "pip install -e '.[tts]'")
    check("voice reference", (ROOT / "ref" / "REF_paginasrecolhidas.wav").exists(),
          "ref/REF_paginasrecolhidas.wav")

    print(f"\n{GREEN}ready{RESET}" if ok else
          f"\n{YELLOW}some pieces are missing — see above{RESET}")
    return 0 if ok else 1


# ----------------------------------------------------------------- extract --

def cmd_extract(args: argparse.Namespace) -> int:
    bundles = args.bundles or find_assets()
    if bundles is None:
        return _fail("could not find the game assets automatically.\n"
                     "Pass the folder holding manifest.dat:\n"
                     "  jime extract --lang pt --bundles '<...>/StreamingAssets/bundles'")
    if args.lang not in GAME_LANGUAGES:
        return _fail(f"unknown language {args.lang!r}. The game ships: "
                     f"{', '.join(GAME_LANGUAGES)}")
    if args.lang not in VOICEABLE:
        print(f"{YELLOW}note: {LANGUAGE_NAMES[args.lang]} has game text but the "
              f"speech model cannot voice it. Extraction works; rendering will "
              f"not.{RESET}")

    print(f"{GRAY}[extract] {LANGUAGE_NAMES.get(args.lang)} from {bundles}{RESET}")
    return _run("phase1_extract.py",
                [str(bundles), "-o", str(ROOT / "corpus"), "--lang", args.lang])


# ------------------------------------------------------------------ render --

def cmd_render(args: argparse.Namespace) -> int:
    corpus = corpus_path(args.lang)
    if not corpus.exists():
        return _fail(f"no corpus for {args.lang!r}. Run first:\n"
                     f"  jime extract --lang {args.lang}")
    if args.lang not in VOICEABLE:
        return _fail(f"the speech model cannot voice {LANGUAGE_NAMES[args.lang]}. "
                     f"It can do: {', '.join(sorted(VOICEABLE))}")

    from glyphs import LEXICON
    if args.lang not in LEXICON:
        print(f"{YELLOW}note: no icon vocabulary for {args.lang!r}. The game's "
              f"icons will be dropped instead of spoken — see 'jime glyphs "
              f"--lang {args.lang}'.{RESET}")

    argv = [str(corpus), "-o", str(audio_dir(args.lang)),
            "--lang", args.lang, "--speed", str(args.speed)]
    if args.campaign:
        argv += ["--campaign", args.campaign]
    if args.check_pace:
        argv += ["--check-pace"]
    if args.device:
        argv += ["--device", args.device]
    if args.dry_run:
        argv += ["--dry-run"]
    if args.limit:
        argv += ["--limit", str(args.limit)]
    for key in args.key or []:
        argv += ["--key", key]
    return _run("phase2_render.py", argv)


# -------------------------------------------------------------------- play --

def cmd_play(args: argparse.Namespace) -> int:
    corpus = corpus_path(args.lang)
    if not corpus.exists():
        return _fail(f"no corpus for {args.lang!r}. Run: jime extract --lang {args.lang}")

    folder = audio_dir(args.lang)
    if not (folder / "manifest.json").exists():
        print(f"{YELLOW}no audio rendered for {args.lang!r} yet — the narrator "
              f"will recognise screens but stay silent.{RESET}")

    argv = ["--corpus", str(corpus), "--audio", str(folder)]
    if args.campaign:
        argv += ["--campaign", args.campaign]
    if args.manual:
        argv += ["--manual"]
    if args.silent:
        argv += ["--no-audio"]
    if args.fps:
        argv += ["--fps", str(args.fps)]
    return _run("narrator.py", argv)


def cmd_test(args: argparse.Namespace) -> int:
    if args.capture:
        return _probe_capture(args)
    if args.video:
        return _run("narrator.py", ["--from-video", str(args.video), "--no-audio",
                                    "--corpus", str(corpus_path(args.lang))])
    if args.images:
        return _run("batch.py", [str(i) for i in args.images])
    return _run("narrator.py", ["--list-windows"])


def _probe_capture(args: argparse.Namespace) -> int:
    """Grab one frame and prove the window really was captured.

    Seeing a window in the list is not the same as getting its pixels. Unity
    renders through the GPU, and the classic macOS capture APIs return the
    wallpaper for exactly this kind of window — which is the whole reason this
    project uses ScreenCaptureKit. A uniform frame is what that failure looks
    like, so the check is whether the pixels actually vary.
    """
    import numpy as np

    from capture.base import CaptureError, open_display, open_window

    try:
        cap = open_display() if args.display else open_window("", "Journeys")
    except CaptureError as exc:
        return _fail(str(exc))

    frame = cap.grab()
    cap.close()
    if frame is None:
        return _fail("the capture returned nothing — did the window close?")

    spread = float(frame.std())
    distinct = int(np.unique(frame[::7, ::7]).size)
    print(f"  frame          {frame.shape[1]}x{frame.shape[0]}")
    print(f"  brightness     mean {frame.mean():.0f}, std {spread:.1f}")
    print(f"  distinct tones {distinct}")

    out = ROOT / "output" / "capture-probe.png"
    out.parent.mkdir(parents=True, exist_ok=True)
    from PIL import Image
    Image.fromarray(frame).save(out)

    if spread < 3 or distinct < 8:
        return _fail(
            "the frame is essentially uniform — this is what a blocked capture "
            "looks like.\n"
            f"Saved anyway to {out} so you can look at it.")
    print(f"\n{GREEN}the window really was captured{RESET} — {out}")
    return 0


def cmd_check(args: argparse.Namespace) -> int:
    manifest = audio_dir(args.lang) / "manifest.json"
    if not manifest.exists():
        return _fail(f"nothing rendered for {args.lang!r} yet")
    return _run("check_pace.py", [str(manifest), "--mad", str(args.mad)])


def cmd_glyphs(args: argparse.Namespace) -> int:
    corpus = corpus_path(args.lang)
    if not corpus.exists():
        return _fail(f"no corpus for {args.lang!r}")
    return _run("glyphs.py", [str(corpus), "--lang", args.lang])


def cmd_languages(args: argparse.Namespace) -> int:
    from glyphs import LEXICON
    print(f"{'code':<6} {'language':<20} {'text':<6} {'voice':<7} icons")
    for lang in GAME_LANGUAGES:
        voice = f"{GREEN}yes{RESET}" if lang in VOICEABLE else f"{YELLOW}no {RESET}"
        icons = (f"{GREEN}yes{RESET}" if lang in LEXICON
                 else f"{YELLOW}missing{RESET}")
        have = f"{GREEN}✓{RESET}" if corpus_path(lang).exists() else " "
        print(f"{lang:<6} {LANGUAGE_NAMES[lang]:<20} {have:<6} {voice:<7} {icons}")
    print(f"\n{GRAY}text  = the game ships this localisation\n"
          f"voice = the speech model can synthesise it\n"
          f"icons = glyphs.py has the spoken words for the game's symbols{RESET}")
    return 0


def _fail(message: str) -> int:
    print(f"{RED}[error]{RESET} {message}")
    return 1


def main() -> None:
    ap = argparse.ArgumentParser(
        prog="jime", description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="command", required=True)

    sub.add_parser("status", help="what is done and what is missing"
                   ).set_defaults(func=cmd_status)
    sub.add_parser("doctor", help="is this machine ready?"
                   ).set_defaults(func=cmd_doctor)
    sub.add_parser("languages", help="what each language supports"
                   ).set_defaults(func=cmd_languages)

    p = sub.add_parser("extract", help="game assets -> corpus")
    p.add_argument("--lang", default="pt", choices=GAME_LANGUAGES)
    p.add_argument("--bundles", type=Path, help="folder holding manifest.dat")
    p.set_defaults(func=cmd_extract)

    p = sub.add_parser("render", help="corpus -> audio")
    p.add_argument("--lang", default="pt", choices=sorted(VOICEABLE))
    p.add_argument("--campaign", choices=CAMPAIGNS)
    p.add_argument("--speed", type=float, default=1.30,
                   help="1.30 is ~137 words per minute; 1.0 is the model's own "
                        "pace, which drags. Changing it re-renders everything.")
    p.add_argument("--device", choices=["auto", "mps", "cuda", "cpu"])
    p.add_argument("--check-pace", action="store_true",
                   help="detect degenerate blocks and retry with another seed")
    p.add_argument("--limit", type=int)
    p.add_argument("--key", action="append", help="render only these blocks")
    p.add_argument("--dry-run", action="store_true", help="estimate, do not render")
    p.set_defaults(func=cmd_render)

    p = sub.add_parser("play", help="narrate a live game")
    p.add_argument("--lang", default="pt")
    p.add_argument("--campaign", choices=CAMPAIGNS,
                   help="defaults to the campaign in the most recent save")
    p.add_argument("--manual", action="store_true",
                   help="hold each screen until a key is pressed")
    p.add_argument("--silent", action="store_true", help="recognise, do not speak")
    p.add_argument("--fps", type=float)
    p.set_defaults(func=cmd_play)

    p = sub.add_parser("test", help="exercise recognition without capturing")
    p.add_argument("--lang", default="pt")
    p.add_argument("--video", type=Path, help="replay a recording")
    p.add_argument("--images", type=Path, nargs="+", help="screenshots")
    p.add_argument("--capture", action="store_true",
                   help="grab one frame from the game and prove it has pixels")
    p.add_argument("--display", action="store_true",
                   help="capture the whole display instead of the game window")
    p.set_defaults(func=cmd_test)

    p = sub.add_parser("check", help="audit rendered audio for bad pace")
    p.add_argument("--lang", default="pt")
    p.add_argument("--mad", type=float, default=2.5)
    p.set_defaults(func=cmd_check)

    p = sub.add_parser("glyphs", help="icon coverage for a language")
    p.add_argument("--lang", default="pt")
    p.set_defaults(func=cmd_glyphs)

    args = ap.parse_args()
    sys.exit(args.func(args))


if __name__ == "__main__":
    main()
