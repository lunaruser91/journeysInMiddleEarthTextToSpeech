#!/usr/bin/env python3
"""
probe_capture.py — does the capture keep producing pixels while you play?

Run it, switch to the game, play for half a minute, come back and read the log.
It writes to a file rather than the terminal on purpose: looking at the terminal
changes what is being measured, which is the whole difficulty with this class of
bug — "it only reads when I alt-tab" is a report you cannot check by watching.

    python probe_capture.py --seconds 40

It samples window capture and display capture side by side, twice a second, and
records for each: whether a frame arrived, whether the pixels *changed* since
the last one, and which window the system says is in front. Those three columns
separate the causes that look identical from the outside.

## Reading the result

**No window frames, display frames fine, and the display frames change.**
Exclusive fullscreen: the game bypasses the compositor that
Windows.Graphics.Capture reads from, so window capture gets nothing, while the
display still composes. Use display capture, or set the game to borderless
windowed if it offers it.

**Frames arrive from both, but never change while you are in the game.**
The capture is handing back the same buffer — a stale frame, not a live one.
Nothing downstream can tell the difference, which is why this needs measuring:
the narrator would sit on one screen forever and look like it had gone quiet.

**Frames and changes are fine, but nothing is read during play.**
Then capture is not the problem and the guard is: compare the `front` column
against the app hint. If the game's process and title do not contain "Journeys",
`--app` needs the name that is actually there.

**Nothing at all while the game is up, everything the moment you leave.**
The compositor is not drawing the game while it is in front — the Windows
equivalent of the macOS inactive-Space case, and the one no capture API can fix
from this side.
"""
from __future__ import annotations

import argparse
import platform
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import console  # noqa: E402

console.setup()

ROOT = Path(__file__).resolve().parent


def _digest(frame) -> str:
    """Cheap fingerprint of a frame, to tell a fresh one from a repeat."""
    import hashlib

    return hashlib.blake2b(frame.tobytes(), digest_size=6).hexdigest()


def main() -> None:
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--seconds", type=float, default=40.0)
    ap.add_argument("--hz", type=float, default=2.0)
    ap.add_argument("--app", default="Journeys")
    ap.add_argument("--window", default="")
    ap.add_argument("--display", type=int, default=0)
    ap.add_argument("--out", type=Path, default=ROOT / "output" / "probe.log")
    args = ap.parse_args()

    from capture.base import (CaptureError, foreground, open_display,
                              open_window)

    args.out.parent.mkdir(parents=True, exist_ok=True)
    log = args.out.open("w", encoding="utf-8")

    def say(line: str) -> None:
        log.write(line + "\n")
        log.flush()

    say(f"probe_capture on {platform.system()} {platform.release()}")
    say(f"app hint {args.app!r}  title hint {args.window!r}  "
        f"display {args.display}")
    say("")

    sources: dict[str, object] = {}
    try:
        sources["window"] = open_window(args.window, args.app, wait=0.0)
        say(f"window capture opened: "
            f"{getattr(sources['window'], 'window', '?')}")
    except CaptureError as exc:
        say(f"window capture unavailable: {str(exc).splitlines()[0]}")
    try:
        sources["display"] = open_display(args.display)
        say(f"display capture opened: display {args.display}")
    except CaptureError as exc:
        say(f"display capture unavailable: {str(exc).splitlines()[0]}")

    if not sources:
        say("\nneither capture could be opened — nothing to measure")
        log.close()
        print("no capture available; see " + str(args.out))
        return

    say("")
    say(f"{'t':>6}  {'source':<8} {'frame':<12} {'changed':<8} front")
    say("-" * 74)

    print(f"sampling for {args.seconds:.0f}s — switch to the game now.")
    print(f"the log is written to {args.out}")

    last: dict[str, str] = {}
    changes = {name: 0 for name in sources}
    got = {name: 0 for name in sources}
    misses = {name: 0 for name in sources}

    started = time.monotonic()
    interval = 1.0 / args.hz
    while time.monotonic() - started < args.seconds:
        loop = time.monotonic()
        front = foreground()
        for name, cap in sources.items():
            try:
                frame = cap.grab()
            except Exception as exc:  # noqa: BLE001
                say(f"{loop - started:6.1f}  {name:<8} "
                    f"{'ERROR':<12} {'':<8} {type(exc).__name__}: {exc}"[:110])
                continue
            if frame is None:
                misses[name] += 1
                say(f"{loop - started:6.1f}  {name:<8} {'none':<12} "
                    f"{'':<8} {front}")
                continue
            got[name] += 1
            d = _digest(frame)
            moved = d != last.get(name)
            if moved:
                changes[name] += 1
            last[name] = d
            say(f"{loop - started:6.1f}  {name:<8} "
                f"{f'{frame.shape[1]}x{frame.shape[0]}':<12} "
                f"{'yes' if moved else 'no':<8} {front}")
        time.sleep(max(0.0, interval - (time.monotonic() - loop)))

    say("")
    say("summary")
    for name in sources:
        total = got[name] + misses[name]
        say(f"  {name:<8} {got[name]}/{total} frames arrived, "
            f"{changes[name]} of them different from the one before")
    say("")
    say("A source with frames but no changes is handing back a stale buffer.")
    say("A source with no frames while the game is up is not being composed.")

    for cap in sources.values():
        try:
            cap.close()
        except Exception:  # noqa: BLE001
            pass
    log.close()
    print(f"done — {args.out}")


if __name__ == "__main__":
    main()
