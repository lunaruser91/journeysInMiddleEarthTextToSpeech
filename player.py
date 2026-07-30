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

sys.path.insert(0, str(Path(__file__).resolve().parent))
import console  # noqa: E402

console.setup()

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

    # Every fallback below is WAV-only, and this project renders Opus. They are
    # kept because a wrong file type is a clearer failure than a missing command,
    # but none of them will actually play what is rendered here — which is why
    # ffplay is checked first and why its absence is worth saying out loud.
    #
    # macOS taught this the hard way: afplay exits 0 after 1.9 s on a 33 s Opus
    # file, so it looks like it worked. Windows' Media.SoundPlayer is the same
    # kind of API and the same trap.
    system = platform.system()
    if system == "Darwin":
        return ["afplay", str(path)]
    if system == "Windows":
        return ["powershell", "-c",
                f"(New-Object Media.SoundPlayer '{path}').PlaySync()"]
    return ["aplay", str(path)]


def require_ffplay() -> str | None:
    """Warn once if playback is about to be attempted without ffplay."""
    if shutil.which("ffplay"):
        return None
    system = platform.system()
    how = {"Windows": "winget install ffmpeg   (or: choco install ffmpeg)",
           "Darwin": "brew install ffmpeg"}.get(system, "apt install ffmpeg")
    return (f"ffplay was not found, and nothing else on {system} decodes Opus — "
            f"the audio this renders.\n  Install ffmpeg and it will play:\n    {how}")


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
    # How long a screen can still be growing. See enqueue(): the two conditions
    # are both needed, and neither works alone.
    grow_window: float = 10.0

    _index: dict[str, Path] = field(default_factory=dict, init=False)
    # {recipe version: {campaigns rendered under it}}, only when there is more
    # than one. See `recipe_warning`.
    _mixed_recipes: dict[str, set[str]] = field(default_factory=dict, init=False)
    _queue: deque[Track] = field(default_factory=deque, init=False)
    _lock: threading.Lock = field(default_factory=threading.Lock, init=False)
    _wake: threading.Event = field(default_factory=threading.Event, init=False)
    _released: threading.Event = field(default_factory=threading.Event, init=False)
    _proc: subprocess.Popen | None = field(default=None, init=False)
    _paused: bool = field(default=False, init=False)
    _last_screen: list[str] = field(default_factory=list, init=False)
    _last_screen_at: float = field(default=0.0, init=False)
    _why_silent: dict[str, str] = field(default_factory=dict, init=False)
    _stopping: bool = field(default=False, init=False)
    _worker: threading.Thread | None = field(default=None, init=False)

    def __post_init__(self) -> None:
        recipes: dict[str, set[str]] = {}
        for folder in self.manifests:
            manifest = Path(folder) / "manifest.json"
            if not manifest.exists():
                continue
            try:
                entries = json.loads(manifest.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                continue
            meta = entries.get("_meta") or {}
            for camp, ver in (meta.get("versions") or {}).items():
                recipes.setdefault(ver, set()).add(camp)
            for key, entry in entries.items():
                if key.startswith("_"):
                    continue          # "_meta" and friends describe the render
                audio = Path(folder) / entry["file"]
                if audio.exists():
                    self._index.setdefault(key, audio)
        self._mixed_recipes = recipes if len(recipes) > 1 else {}
        warning = require_ffplay()
        if warning and self._index:
            print(f"{YELLOW}[player] {warning}{RESET}", file=sys.stderr)

        if not self.manual:
            self._released.set()
        self._worker = threading.Thread(target=self._run, daemon=True)
        self._worker.start()

    # ---------------------------------------------------------------- queue --

    def enqueue(self, keys: list[str], interrupt: bool = True,
                again: bool = False,
                audio: dict[str, Path] | None = None) -> list[str]:
        """Queue one screen's blocks. Returns the keys that will actually play.

        `audio` supplies a path for this screen only. Audio synthesised while
        playing belongs to the screen that produced it, not to the key: a {0}
        block says "raise the threat by 4" on one screen and "by 2" on the next,
        and a block shown in part must not become the block's voice for the rest
        of the session. Registering it permanently would do both.
        """
        audio = audio or {}
        # The game reveals a dialogue box in stages: prose first, the
        # instruction under it a moment later. Each stage settles as its own
        # screen, and the second carries both paragraphs — so the first block
        # would be read twice.
        #
        # Recognising that needs both a structural and a temporal test, and
        # neither works alone. A plain time window was the first attempt: it
        # silenced "place a search token", which recurs legitimately every few
        # tiles, with "already spoken 52s ago". Structure alone was the second:
        # a new screen that happens to reuse the same instruction also contains
        # the previous screen, so it looked like growth.
        #
        # A box grows within seconds. A tile is revisited much later. So this is
        # a continuation only when the screen strictly contains the last one AND
        # that was moments ago. Equality is not growth — the same screen reached
        # again is a new screen — and identical re-settles are already stopped
        # upstream by the trigger.
        now = time.monotonic()
        growing = (not again and self._last_screen
                   and set(self._last_screen) < set(keys)
                   and now - self._last_screen_at < self.grow_window)

        playable, skipped = [], []
        for key in keys:
            if self.mute_self_narrated and SELF_NARRATED in key.upper():
                skipped.append((key, "the game narrates this one itself"))
                continue
            if growing and key in self._last_screen:
                skipped.append((key, "already spoken — the box just grew"))
                continue
            path = audio.get(key) or self._index.get(key)
            if path is None:
                skipped.append((key, "no audio rendered"))
                continue
            playable.append(Track(key, path))

        # Keep the reasons where the caller can read them. The narrator builds
        # the Player with verbose=False and prints its own line, and "skipped"
        # with no reason is exactly what you cannot debug from.
        self._why_silent = dict(skipped)
        if self.verbose:
            for key, why in skipped:
                print(f"{YELLOW}[skipped]{RESET} {key} — {why}")

        with self._lock:
            # Only cut off what is playing when this screen replaces the last.
            # A box that merely grew is still being read, and interrupting would
            # lose the end of one sentence to start the next.
            if interrupt and not growing:
                self._queue.clear()
                self._kill_current()
            self._queue.extend(playable)
            if playable:
                self._last_screen = [t.key for t in playable]
                self._last_screen_at = now
        self._wake.set()
        return [t.key for t in playable]

    # ------------------------------------------------------------- controls --

    # Suspending the child is a Unix trick: SIGSTOP and SIGCONT do not exist on
    # Windows, and reaching for the names there raises AttributeError out of the
    # key handler mid-block. Windows gets the honest substitute — stop the block
    # and let the next screen carry on. Pausing speech you cannot resume is the
    # same as skipping it, and saying so is better than crashing.
    CAN_SUSPEND = hasattr(signal, "SIGSTOP")

    def pause(self) -> None:
        with self._lock:
            if not self._proc or self._paused:
                return
            if self.CAN_SUSPEND:
                self._signal(signal.SIGSTOP)
                self._paused = True
            else:
                self._kill_current()

    def resume(self) -> None:
        with self._lock:
            if self._proc and self._paused and self.CAN_SUSPEND:
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

    def recipe_warning(self, campaigns: set[str]) -> str:
        """"" unless the campaigns about to be played were rendered differently.

        The voice recipe goes into every cache key so that two of them can never
        end up in one session — but the check only ever existed at render time,
        and `render --campaign X` renders one campaign. Reported from a real
        machine: a recipe change, a scoped re-render, and a session that then
        played `bonesofarnor:A2_M1_S1_SEARCH` and `main:PLACE_SEARCH` one after
        the other at two different paces, with the manifest asserting a single
        recipe over both.

        Scoped on purpose. A session plays its campaign and `main`; a third
        campaign left on an older recipe is not this session's problem, and
        warning about it would train people to ignore the line.
        """
        here = {ver: sorted(c for c in camps if c in campaigns)
                for ver, camps in self._mixed_recipes.items()}
        here = {v: c for v, c in here.items() if c}
        if len(here) < 2:
            return ""
        return ("this session mixes two voice recipes, so the pace changes "
                "between blocks: "
                + "; ".join(f"{', '.join(c)} at {v}" for v, c in sorted(here.items()))
                + ". Re-render without --campaign to settle it.")

    def why_silent(self, key: str) -> str:
        """Why the last enqueue did not play this key."""
        return self._why_silent.get(key, "skipped")



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
            if self._paused and self.CAN_SUSPEND:  # a stopped process ignores TERM
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
            # Publish the handle before anything can ask to kill it, and check
            # the flag again while holding the same lock. Between the Popen above
            # and this assignment there used to be a window where `self._proc`
            # still named the *previous*, already-dead process: a stop() or an
            # interrupting screen landing in that window terminated a corpse and
            # let this one talk to the end.
            with self._lock:
                self._proc = proc
                orphan = self._stopping
            if orphan:
                proc.terminate()
                break
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
