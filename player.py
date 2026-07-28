#!/usr/bin/env python3
"""
player.py — audio queue for the narrator: play, repeat, pause, skip.

This is the last stage of phase 3. `trigger.py` decides *when* a new screen
appeared, `matcher.py` decides *which* corpus blocks it holds, and this decides
*how* they are spoken.

## What a screen looks like

A screen is not one block. The game composes it from several localisation keys —
a prose block plus a generic instruction template — so the player receives a
LIST of keys and speaks them in reading order. See PHASE3-STRATEGY.md §5b.

## Two rules that are not obvious

**The game already narrates some screens.** The `narration/<campaign>/pt` bundles
hold 20 professionally recorded clips: the Prologue and the Epilogues of all six
campaigns. They correspond exactly, one to one, to the 20 corpus keys containing
`CUTSCENE`. Speaking over them would put two voices in the room, so those keys
are muted by default.

**A new screen interrupts by default.** Players advance quickly in a board game,
and audio that lags behind the table is worse than audio that stops mid-sentence.
`enqueue()` takes `interrupt=False` when you want the opposite.

## Manual mode

Some groups want to read at their own pace. In manual mode nothing plays until
`release()` is called — the queue fills up and waits.

## Usage as a library

    player = Player(manifests=[Path("output/audio")])
    player.enqueue(["main:G22_SWORD_TRUE", "main:PLACE_SEARCH"])
    player.pause(); player.resume(); player.skip(); player.repeat()

## Usage from the command line, for testing

    python3 player.py --key main:G22_SWORD_TRUE --key bonesofarnor:A2_M1_INTRO_4
    python3 player.py --manifest output/screens-130x --all
"""
from __future__ import annotations

import argparse
import json
import os
import platform
import shutil
import signal
import subprocess
import sys
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path

GREEN, YELLOW, GRAY, RESET = "\033[92m", "\033[93m", "\033[90m", "\033[0m"

# Keys the game narrates itself, with recorded voice. See the module docstring.
SELF_NARRATED = "CUTSCENE"


def _play_command(path: Path) -> list[str]:
    """The backend that actually makes sound.

    ffplay first, on every platform, and the reason matters: **macOS `afplay`
    does not play Opus**. It does not fail either — it returns exit code 0 after
    1.9 s for a 33.5 s file, having produced no sound. Silent success is the worst
    possible failure mode here, because nothing in the logs would ever show it.
    Measured on macOS 26 with a file the renderer had just produced.

    ffplay handles Opus correctly (33.8 s for that same file) and ships with
    ffmpeg, which the project already requires for the DSP chain — so this adds
    no dependency. The platform-specific players stay only as a fallback for a
    machine without ffmpeg, where the audio will have to be something else.

    Kept as a subprocess on purpose: pause and resume work by suspending the
    process, which needs a real child rather than a library playing in-thread.
    """
    if shutil.which("ffplay"):
        return ["ffplay", "-nodisp", "-autoexit", "-loglevel", "quiet", str(path)]

    system = platform.system()
    if system == "Darwin":
        return ["afplay", str(path)]        # will NOT work for .opus, see above
    if system == "Windows":
        return ["powershell", "-c",
                f"(New-Object Media.SoundPlayer '{path}').PlaySync()"]
    return ["aplay", str(path)]


@dataclass
class Track:
    key: str
    path: Path


@dataclass
class Player:
    """Plays corpus blocks in order, with transport controls.

    Thread-safe: `enqueue` and the controls are meant to be called from the
    trigger's thread while a worker thread does the playing.
    """

    manifests: list[Path]
    mute_self_narrated: bool = True
    manual: bool = False
    verbose: bool = True
    # A block is not spoken twice within this window. The game reveals a
    # dialogue box in stages — the prose first, the instruction under it a moment
    # later — and each stage settles as its own screen. The second one carries
    # both paragraphs, so without this the first is read again.
    repeat_after: float = 120.0

    _index: dict[str, Path] = field(default_factory=dict, init=False)
    _queue: deque[Track] = field(default_factory=deque, init=False)
    _lock: threading.Lock = field(default_factory=threading.Lock, init=False)
    _wake: threading.Event = field(default_factory=threading.Event, init=False)
    _released: threading.Event = field(default_factory=threading.Event, init=False)
    _proc: subprocess.Popen | None = field(default=None, init=False)
    _paused: bool = field(default=False, init=False)
    _last_screen: list[str] = field(default_factory=list, init=False)
    _spoken_at: dict[str, float] = field(default_factory=dict, init=False)
    _why_silent: dict[str, str] = field(default_factory=dict, init=False)
    _stopping: bool = field(default=False, init=False)
    _worker: threading.Thread | None = field(default=None, init=False)

    def __post_init__(self) -> None:
        for folder in self.manifests:
            manifest = Path(folder) / "manifest.json"
            if not manifest.exists():
                continue
            try:
                entries = json.loads(manifest.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                continue
            for key, entry in entries.items():
                if key.startswith("_"):
                    continue          # "_meta" and friends describe the render
                audio = Path(folder) / entry["file"]
                if audio.exists():
                    self._index.setdefault(key, audio)
        if not self.manual:
            self._released.set()
        self._worker = threading.Thread(target=self._run, daemon=True)
        self._worker.start()

    # ---------------------------------------------------------------- queue --

    def enqueue(self, keys: list[str], interrupt: bool = True,
                again: bool = False) -> list[str]:
        """Queue one screen's blocks. Returns the keys that will actually play."""
        now = time.monotonic()
        playable, skipped = [], []
        for key in keys:
            if self.mute_self_narrated and SELF_NARRATED in key.upper():
                skipped.append((key, "the game narrates this one itself"))
                continue
            last = self._spoken_at.get(key)
            if not again and last is not None and now - last < self.repeat_after:
                skipped.append((key, f"already spoken {now - last:.0f}s ago"))
                continue
            audio = self._index.get(key)
            if audio is None:
                skipped.append((key, "no audio rendered"))
                continue
            playable.append(Track(key, audio))

        # Keep the reasons where the caller can read them. The narrator builds
        # the Player with verbose=False and prints its own line, and "skipped"
        # with no reason is exactly what you cannot debug from.
        self._why_silent = dict(skipped)
        if self.verbose:
            for key, why in skipped:
                print(f"{YELLOW}[skipped]{RESET} {key} — {why}")

        with self._lock:
            # Only cut off what is playing when this screen replaces the last
            # one. When the box has merely grown — the instruction appearing
            # under the prose — the earlier blocks are still being read, and
            # interrupting would lose the rest of a sentence to say the next.
            replacing = interrupt and not (
                self._last_screen and set(self._last_screen) <= set(keys))
            if replacing:
                self._queue.clear()
                self._kill_current()
            self._queue.extend(playable)
            for track in playable:
                self._spoken_at[track.key] = now
            if playable:
                self._last_screen = [t.key for t in playable]
        self._wake.set()
        return [t.key for t in playable]

    # ------------------------------------------------------------- controls --

    def pause(self) -> None:
        with self._lock:
            if self._proc and not self._paused:
                self._signal(signal.SIGSTOP)
                self._paused = True

    def resume(self) -> None:
        with self._lock:
            if self._proc and self._paused:
                self._signal(signal.SIGCONT)
                self._paused = False

    def toggle(self) -> None:
        self.resume() if self._paused else self.pause()

    def skip(self) -> None:
        """Drop the block being spoken and move to the next in the screen."""
        with self._lock:
            self._kill_current()

    def repeat(self) -> None:
        """Play the last screen again, from its first block."""
        if self._last_screen:
            self.enqueue(list(self._last_screen), interrupt=True, again=True)

    def release(self) -> None:
        """In manual mode, let the queued screen play."""
        self._released.set()

    def hold(self) -> None:
        """Go back to waiting for `release()` before each screen."""
        self._released.clear()

    def stop(self) -> None:
        with self._lock:
            self._stopping = True
            self._queue.clear()
            self._kill_current()
        self._wake.set()
        self._released.set()

    @property
    def playing(self) -> bool:
        return self._proc is not None and self._proc.poll() is None

    @property
    def pending(self) -> int:
        with self._lock:
            return len(self._queue)

    def why_silent(self, key: str) -> str:
        """Why the last enqueue did not play this key."""
        return self._why_silent.get(key, "skipped")

    def register(self, key: str, path: Path) -> None:
        """Add audio the manifests did not have — a block synthesised mid-game.

        Blocks carrying a {0} cannot be rendered in advance, so their audio only
        exists once the screen has been read. This puts it where enqueue() looks,
        for the rest of the session.
        """
        self._index[key] = Path(path)

    def known(self, key: str) -> bool:
        return key in self._index

    def __len__(self) -> int:
        return len(self._index)

    # -------------------------------------------------------------- internal --

    def _signal(self, sig: int) -> None:
        if self._proc and self._proc.poll() is None:
            try:
                os.kill(self._proc.pid, sig)
            except ProcessLookupError:
                pass

    def _kill_current(self) -> None:
        if self._proc and self._proc.poll() is None:
            if self._paused:                 # a stopped process ignores TERM
                self._signal(signal.SIGCONT)
            self._proc.terminate()
        self._paused = False

    def _run(self) -> None:
        while not self._stopping:
            with self._lock:
                track = self._queue.popleft() if self._queue else None
            if track is None:
                self._wake.wait(timeout=0.2)
                self._wake.clear()
                continue

            self._released.wait()            # manual mode holds here
            if self._stopping:
                break
            if self.verbose:
                print(f"{GREEN}[speaking]{RESET} {track.key}")
            try:
                proc = subprocess.Popen(_play_command(track.path),
                                        stdout=subprocess.DEVNULL,
                                        stderr=subprocess.DEVNULL)
            except FileNotFoundError:
                print(f"{YELLOW}[error]{RESET} no audio backend found for this "
                      f"platform ({platform.system()})")
                return
            with self._lock:
                self._proc = proc
            proc.wait()
            with self._lock:
                self._proc = None
                self._paused = False
            if self.manual:
                self._released.clear()       # one screen per release


# --------------------------------------------------------------------- CLI --

def _single_key(timeout: float = 0.2) -> str:
    """One keypress, or "" if none arrived within `timeout`.

    Blocking here was a bug, not a shortcut. The playback loop used this as its
    only way to make progress, so a terminal that could not deliver a keypress —
    output piped somewhere, stdin not a tty — raised out of the loop, hit the
    finally, and killed ffplay mid-word. The audio was fine; the controls took it
    down with them. With a timeout the loop keeps checking whether playback is
    done, and the keyboard becomes what it should have been: optional.
    """
    if not sys.stdin.isatty():
        time.sleep(timeout)
        return ""
    try:
        import select
        import termios
        import tty
    except ImportError:
        return (sys.stdin.readline() or "q")[:1]
    fd = sys.stdin.fileno()
    try:
        old = termios.tcgetattr(fd)
    except Exception:            # noqa: BLE001 — not a real terminal after all
        time.sleep(timeout)
        return ""
    try:
        tty.setcbreak(fd)
        if select.select([sys.stdin], [], [], timeout)[0]:
            return sys.stdin.read(1)
        return ""
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    root = Path(__file__).resolve().parent
    ap.add_argument("--manifest", type=Path, action="append", default=[],
                    help="folder holding a manifest.json (repeatable)")
    ap.add_argument("--key", action="append", default=[],
                    help="corpus key to play (repeatable, in reading order)")
    ap.add_argument("--all", action="store_true",
                    help="play everything in the manifests")
    ap.add_argument("--manual", action="store_true",
                    help="wait for a keypress before each screen")
    ap.add_argument("--no-mute-cutscenes", action="store_true",
                    help="also speak the blocks the game narrates itself")
    args = ap.parse_args()

    folders = args.manifest or sorted(
        d for d in (root / "output").glob("*") if (d / "manifest.json").exists())
    if not folders:
        sys.exit("[error] no manifest.json found under output/ — render something "
                 "first with phase2_render.py")

    manual = args.manual
    if manual and not sys.stdin.isatty():
        # --manual holds each track until a keypress, and without a terminal no
        # keypress can ever arrive: it would wait forever on the first block.
        print(f"{YELLOW}[player] --manual needs a terminal; playing straight "
              f"through instead{RESET}")
        manual = False

    player = Player(manifests=folders, manual=manual,
                    mute_self_narrated=not args.no_mute_cutscenes)
    print(f"{GRAY}[player] {len(player):,} blocks available from "
          f"{len(folders)} manifest(s){RESET}")

    keys = args.key
    if args.all or not keys:
        keys = sorted(player._index)
        print(f"{GRAY}[player] playing all {len(keys)} of them{RESET}")

    player.enqueue(keys)
    print(f"\n{GRAY}  space pause/resume   n next   r repeat screen   q quit{RESET}\n")

    try:
        while player.playing or player.pending:
            ch = _single_key().lower()
            if ch == " ":
                player.toggle()
                print(f"{GRAY}  {'paused' if player._paused else 'resumed'}{RESET}")
            elif ch == "n":
                player.skip()
            elif ch == "r":
                player.repeat()
            elif ch in ("q", "\x03"):
                break
            elif ch and manual:
                player.release()
    except KeyboardInterrupt:
        pass
    finally:
        player.stop()
        print(f"\n{GRAY}[player] stopped{RESET}")


if __name__ == "__main__":
    main()
