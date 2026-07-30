#!/usr/bin/env python3
"""
selftest.py — does this whole thing work on this machine?

    python selftest.py                 # everything it can check unattended
    python selftest.py --lang en       # extract and render in another language
    python selftest.py --skip-render   # faster: no synthesis

Written to be the first thing run on a machine nobody has tried before. It walks
the same path a user does — install, find the game, extract, render, read a
screen, match it — and reports each step separately, so a failure names its own
cause instead of surfacing three steps later as silence.

Every check is a real operation on real data. Nothing here is mocked: it renders
actual audio and decodes it, and puts real text through OCR. That is the point —
the failures this project has hit on macOS were all things that looked fine
until something was actually run.

It is safe to run repeatedly. It writes only under `output/selftest/`, which it
clears first, and never touches the corpus or renders you already have.
"""
from __future__ import annotations

import argparse
import io
import platform
import shutil
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

import console  # noqa: E402

console.setup()

OUT = ROOT / "output" / "selftest"
GREEN, YELLOW, RED, GRAY, BOLD, RESET = (
    "\033[92m", "\033[93m", "\033[91m", "\033[90m", "\033[1m", "\033[0m")

results: list[tuple[str, bool, str]] = []


def check(name: str, ok: bool, detail: str = "", fatal: bool = False) -> bool:
    mark = f"{GREEN}pass{RESET}" if ok else f"{RED}FAIL{RESET}"
    print(f"  {mark}  {name:<38} {GRAY}{detail}{RESET}", flush=True)
    results.append((name, ok, detail))
    if fatal and not ok:
        report()
        raise SystemExit(1)
    return ok


def short(path) -> str:
    """A path with the user's home folder written as `~`.

    This output is the one artefact of this project somebody is asked to send to
    a stranger — it carries no game text at all, only counts, keys and timings.
    It did carry their account name, four times over, inside paths like
    `C:\\Users\\<name>\\AppData\\Local\\Microsoft\\WinGet\\Links\\ffmpeg.EXE`.
    Nobody debugging an OCR engine needs to know that, and it is one
    substitution to remove.
    """
    text, home = str(path), str(Path.home())
    return "~" + text[len(home):] if text.startswith(home) else text


def skip(name: str, why: str) -> None:
    print(f"  {YELLOW}skip{RESET}  {name:<38} {GRAY}{why}{RESET}", flush=True)


def section(title: str) -> None:
    print(f"\n{BOLD}{title}{RESET}")


# --------------------------------------------------------------------------- #

def test_environment() -> None:
    section(f"environment — {platform.system()} {platform.machine()}")
    v = sys.version_info
    # 3.12, matching requires-python in pyproject.toml and the check in
    # jime.py:doctor. This said 3.11 and would have passed a machine the
    # installer refuses.
    check("python >= 3.12", v >= (3, 12), f"{v.major}.{v.minor}.{v.micro}",
          fatal=True)
    for tool in ("ffmpeg", "ffprobe"):
        check(f"{tool} on PATH", shutil.which(tool) is not None,
              short(shutil.which(tool)) if shutil.which(tool) else "not found",
              fatal=True)
    check("ffplay on PATH", shutil.which("ffplay") is not None,
          short(shutil.which("ffplay")) if shutil.which("ffplay")
          else "playback will not work — install ffmpeg")


def test_imports() -> None:
    section("imports")
    for mod, why in [("rapidfuzz", "matching"), ("numpy", "trigger"),
                     ("PIL", "images"), ("num2words", "spoken numbers"),
                     ("piper", "synthesis"), ("UnityPy", "extraction")]:
        try:
            __import__(mod)
            check(mod, True, why)
        except ImportError as exc:
            hint = str(exc)[:48]
            if "DLL load failed" in str(exc) and mod == "piper":
                # The message names neither Piper nor the missing piece.
                hint = "install Microsoft.VCRedist.2015+.x64 — onnxruntime needs it"
            check(mod, False, hint)

    for mod in ("jime", "matcher", "glyphs", "voices", "trigger",
                "player", "live", "menu", "phase2_render"):
        try:
            __import__(mod)
            check(f"{mod}.py", True, "")
        except Exception as exc:  # noqa: BLE001
            check(f"{mod}.py", False, f"{type(exc).__name__}: {exc}"[:48])


def test_console_encoding() -> None:
    """The failure that would take Phase 3 down on Windows for four languages."""
    section("console encoding")
    hard = "Několik ł Несколько 这个 ✓ →"
    buf = io.TextIOWrapper(io.BytesIO(), encoding="cp1252", errors="strict")
    try:
        print(hard, file=buf)
        raw_ok = True
    except UnicodeEncodeError:
        raw_ok = False
    check("cp1252 cannot hold the corpus", not raw_ok,
          "as expected — this is why console.setup() exists")

    buf2 = io.TextIOWrapper(io.BytesIO(), encoding="cp1252", errors="strict")
    buf2.reconfigure(encoding="utf-8", errors="replace")
    try:
        print(hard, file=buf2)
        check("console.setup() survives it", True, "utf-8 with errors=replace")
    except UnicodeEncodeError as exc:
        check("console.setup() survives it", False, str(exc)[:48])

    check("stdout is utf-8 now", (sys.stdout.encoding or "").lower().startswith("utf"),
          sys.stdout.encoding or "?")


def test_assets(lang: str) -> Path | None:
    section("the game's files")
    import jime

    found = jime.find_assets()
    check("game data located", found is not None,
          short(found) if found else f"tried {len(jime.ASSET_GUESSES)} places")
    if found is None:
        print(f"{GRAY}        install the game, or pass --bundles to extract{RESET}")
    saves = console.saves_dir()
    check("saves folder path", True, short(saves))
    if saves.exists():
        check("saves folder found", True, "campaign can be auto-detected")
    else:
        # Absent is not a failure: it appears the first time the game saves, and
        # everything except picking the campaign for you works without it.
        skip("saves folder found", "no save yet — pick the campaign manually")
    return found


def test_extract(lang: str, bundles: Path | None) -> Path | None:
    section(f"extraction — {lang}")
    if bundles is None:
        skip("extract", "the game was not found")
        return None
    import jime

    corpus = jime.corpus_path(lang)
    if corpus.exists():
        skip("extract", f"{corpus.name} already exists; reusing it")
    else:
        rc = subprocess.call([sys.executable, str(ROOT / "phase1_extract.py"),
                              str(bundles), "-o", str(ROOT / "corpus"),
                              "--lang", lang],
                             stdout=subprocess.DEVNULL)
        if not check("extract ran", rc == 0, f"exit {rc}"):
            return None

    import json
    data = json.loads(corpus.read_text(encoding="utf-8"))
    narration = [v for v in data.values() if v.get("narration")]
    check("corpus has keys", len(data) > 1000, f"{len(data):,}")
    check("corpus has narration", len(narration) > 500, f"{len(narration):,} blocks")
    glyphs_seen = sum(1 for v in data.values()
                      if any(0xE000 <= ord(c) <= 0xF8FF for c in v["text"]))
    check("icons survived extraction", glyphs_seen > 0,
          f"{glyphs_seen:,} blocks carry game icons")
    return corpus


def test_render(lang: str, corpus: Path | None) -> Path | None:
    section(f"synthesis — {lang}")
    if corpus is None:
        skip("render", "no corpus")
        return None
    import json

    import voices as V

    # espeak-ng, inside Piper, keeps its data path in a fixed-size buffer. Past
    # roughly 160 characters initialize() silently falls back to the path the
    # wheel was BUILT at — a directory on the CI machine — and every render dies
    # with an error naming neither Piper nor your installation. Measured here:
    # 156 works, 176 does not.
    try:
        from piper.phonemize_espeak import ESPEAK_DATA_DIR
        n = len(str(ESPEAK_DATA_DIR))
        check("speech data path is short enough", n < 160,
              f"{n} chars"
              + ("" if n < 160 else " — reinstall somewhere shorter, e.g. ~/jime-venv"))
    except ImportError:
        pass

    name = V.resolve(lang)
    check("voice chosen", True, name)
    try:
        model = V.ensure(name)
        check("voice model present", model.exists(), f"{model.stat().st_size/1e6:.0f} MB")
    except Exception as exc:  # noqa: BLE001
        check("voice model present", False, str(exc)[:60])
        return None

    t0 = time.time()
    rc = subprocess.call([sys.executable, str(ROOT / "phase2_render.py"),
                          "--lang", lang, "-o", str(OUT / "audio"), "--limit", "3"],
                         stdout=subprocess.DEVNULL)
    if not check("render ran", rc == 0, f"exit {rc}, {time.time()-t0:.0f}s"):
        return None

    manifest = OUT / "audio" / "manifest.json"
    entries = {k: v for k, v in json.loads(manifest.read_text(encoding="utf-8")).items()
               if not k.startswith("_")}
    check("manifest written", len(entries) == 3, f"{len(entries)} blocks")

    ok = True
    for key, v in entries.items():
        f = OUT / "audio" / v["file"]
        out = subprocess.run(["ffprobe", "-v", "error", "-show_entries",
                              "format=duration", "-of", "csv=p=0", str(f)],
                             capture_output=True, text=True,
                             encoding="utf-8", errors="replace").stdout.strip()
        if not out or float(out) < 0.3:
            ok = False
    check("audio decodes", ok, f"{len(entries)} files, opus")
    wps = [v["wps"] for v in entries.values() if v.get("wps")]
    if wps:
        med = sorted(wps)[len(wps)//2]
        check("pace is sane", 1.5 < med < 4.0, f"{med:.2f} words/s ({med*60:.0f} wpm)")
    return manifest


def test_ocr(lang: str, corpus: Path | None) -> None:
    section("OCR")
    try:
        from ocr.base import locales_for, missing_recogniser, open_ocr
        engine = open_ocr(languages=locales_for(lang))
        detail = getattr(engine, "settings", "")
        check("engine loaded", True,
              f"{type(engine).__name__}{' — ' + detail if detail else ''}"[:70])
        # A wrong-language recogniser is a pass everywhere else and a defect
        # here. This check exists because `WindowsOcr — language en-US` on a
        # Portuguese session printed as a pass twice, on two machines, and read
        # as a detail both times.
        warning = missing_recogniser(lang) or getattr(engine, "warning", "")
        if warning:
            check("reads the game's own language", False,
                  warning.splitlines()[0][:56])
            # The 56 characters above identify the problem and cannot carry the
            # fix. This one names an install command, so it is printed whole —
            # a failure whose remedy is a line of PowerShell should not make
            # anybody go and look for it.
            for line in warning.splitlines()[1:]:
                print(f"        {GRAY}{line.strip()}{RESET}")
        else:
            check("reads the game's own language", True, f"{lang} — as asked")
    except Exception as exc:  # noqa: BLE001
        check("engine loaded", False, f"{type(exc).__name__}: {exc}"[:56])
        return

    # A real image with real text, drawn here so no fixture is needed.
    from PIL import Image, ImageDraw
    phrase = "The shadows deepen, though hope remains."
    img = Image.new("L", (900, 200), 20)
    d = ImageDraw.Draw(img)
    try:
        from PIL import ImageFont
        font = ImageFont.load_default(size=34)
    except Exception:  # noqa: BLE001
        font = None
    d.text((30, 70), phrase, fill=230, font=font)
    path = OUT / "ocr.png"
    path.parent.mkdir(parents=True, exist_ok=True)
    img.save(path)

    import numpy as np
    try:
        lines = engine.read(np.array(img))
    except Exception as exc:  # noqa: BLE001
        check("read an image", False, f"{type(exc).__name__}: {exc}"[:56])
        return
    text = " ".join(l.text for l in lines)
    check("read an image", bool(text.strip()), f"{len(lines)} line(s)")
    hits = sum(1 for w in ("shadows", "deepen", "hope") if w.lower() in text.lower())
    check("read it correctly", hits >= 2, f"{hits}/3 keywords — got {text[:40]!r}")


def test_matcher(lang: str, corpus: Path | None) -> None:
    section("matching")
    if corpus is None:
        skip("matcher", "no corpus")
        return
    from matcher import Matcher, load_corpus

    c = load_corpus(corpus)
    m = Matcher(c)
    check("index built", len(m) > 1000, f"{len(m):,} candidates")

    key = next((k for k, v in c.items()
                if v.get("narration") and 30 < len(v["text"].split()) < 60
                and not v.get("placeholders")), None)
    if key is None:
        skip("match a screen", "no suitable block")
        return
    r = m.match_text(c[key]["text"])
    check("exact text matches", r.key == key and r.accepted,
          f"{r.key} score {r.score:.0f}")

    noisy = c[key]["text"].replace("m", "rn", 1).replace("a", "e", 2)
    r2 = m.match_text(noisy)
    check("survives OCR noise", r2.key == key and r2.accepted,
          f"score {r2.score:.0f}")


def test_capture() -> None:
    section("screen capture")
    try:
        from capture.base import list_windows
    except Exception as exc:  # noqa: BLE001
        check("backend imports", False, f"{type(exc).__name__}: {exc}"[:56])
        return
    try:
        windows = list_windows("")
        check("backend lists windows", True, f"{len(windows)} visible")
    except Exception as exc:  # noqa: BLE001
        check("backend lists windows", False, str(exc).split("\n")[0][:56])
        return
    # Display capture is what the menu picks for a fullscreen game — which is
    # how most people run it — and nothing here used to exercise it. It needs no
    # game: a monitor with anything on it is enough to prove frames arrive.
    from capture.base import foreground, open_display
    try:
        cap = open_display(0)
        frame = cap.grab()
        cap.close()
        ok = frame is not None and float(frame.std()) > 1.0
        check("capture a display", ok,
              f"{frame.shape[1]}x{frame.shape[0]}" if frame is not None
              else "no frame returned")
    except Exception as exc:  # noqa: BLE001
        check("capture a display", False, str(exc).split("\n")[0][:56])

    # The guard that keeps display capture from reading the desktop, and the
    # terminal it is printing into.
    front = foreground()
    check("know which window is in front", front is not None,
          (front or "backend cannot tell")[:56])

    game = [w for w in windows if "journey" in (w.app or "").lower()
            or "journey" in (w.title or "").lower()]
    if not game:
        # On macOS this cannot distinguish the two: a fullscreen game owns a
        # Space that is not drawn while you are here, and an undrawn window is
        # not listed. On Windows it is listed either way, so absence is absence.
        skip("capture the game",
             "the game is not running — start it and rerun"
             if platform.system() == "Windows" else
             "no game window visible — not running, or fullscreen on its own "
             "Space")
        return
    from capture.base import open_window
    try:
        cap = open_window("", "Journeys")
        frame = cap.grab()
        cap.close()
    except Exception as exc:  # noqa: BLE001
        check("capture the game", False, str(exc).split("\n")[0][:56])
        return
    if frame is None:
        check("capture the game", False, "no frame returned")
        return
    import numpy as np
    spread = float(frame.std())
    check("capture the game", spread > 3,
          f"{frame.shape[1]}x{frame.shape[0]}, std {spread:.1f}"
          + ("" if spread > 3 else " — uniform, which means blocked"))


# --------------------------------------------------------------------------- #

def report() -> None:
    passed = sum(1 for _, ok, _ in results if ok)
    total = len(results)
    print(f"\n{BOLD}{passed}/{total} checks passed{RESET}")
    failed = [n for n, ok, _ in results if not ok]
    if failed:
        print(f"{RED}failed:{RESET} " + ", ".join(failed))
    else:
        print(f"{GREEN}everything this machine can check, works.{RESET}")
    print(f"{GRAY}artefacts in {short(OUT)}{RESET}")


def main() -> int:
    import jime          # imported here, as everywhere else in this file: the
                         # import checks above have to be able to report jime.py
                         # failing to import, which they cannot if this module
                         # already died on the same import at startup.

    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--lang", default=jime.default_language(),
                    help="which language to check. Defaults to what this "
                         "machine is already set up for, then to the "
                         "system language, then to English")
    ap.add_argument("--skip-render", action="store_true")
    args = ap.parse_args()

    if OUT.exists():
        shutil.rmtree(OUT)
    OUT.mkdir(parents=True, exist_ok=True)

    print(f"{BOLD}selftest — {platform.system()} {platform.release()} "
          f"{platform.machine()}{RESET}")

    test_environment()
    test_imports()
    test_console_encoding()
    bundles = test_assets(args.lang)
    corpus = test_extract(args.lang, bundles)
    if args.skip_render:
        skip("render", "--skip-render")
    else:
        test_render(args.lang, corpus)
    test_ocr(args.lang, corpus)
    test_matcher(args.lang, corpus)
    test_capture()

    report()
    return 0 if all(ok for _, ok, _ in results) else 1


if __name__ == "__main__":
    sys.exit(main())
