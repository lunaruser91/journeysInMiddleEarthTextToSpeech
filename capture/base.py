#!/usr/bin/env python3
"""
capture/base.py — the contract between "get me a frame" and the OS that provides it.

Everything above this line — trigger, OCR, matcher, player — is plain Python and
runs anywhere. Everything below it is platform-specific, and there is no way
around that: grabbing the pixels of another application's window is exactly the
kind of thing operating systems disagree about.

## Why not just take a screenshot

On **macOS 26 Tahoe**, `CGWindowListCreateImage`, `CGDisplayCreateImage` and the
`screencapture` command return only the wallpaper — application windows come back
invisible. That rules out `mss`, `pyautogui` and `PIL.ImageGrab` in one stroke.
ScreenCaptureKit is the only path that still sees windows.

On **Windows**, `BitBlt` and `PrintWindow` return black frames for Unity windows,
because the game renders through the GPU rather than into the window's device
context. Windows.Graphics.Capture is the equivalent answer there.

## Permission, and why running from a terminal matters

macOS attaches screen-recording permission to the *responsible process*. Launched
from a terminal, the grant lands on the terminal application, which is why this
project can stay a set of scripts instead of a signed, notarised `.app`: the
signing requirement exists to distribute a standalone binary, not to capture.

The user grants it once, in System Settings → Privacy & Security → Screen
Recording, and restarts the terminal. There is no way to request it from inside
Python — the first capture attempt is what makes the prompt appear.
"""
from __future__ import annotations

import platform
from dataclasses import dataclass
from typing import Protocol

import numpy as np


class CaptureError(RuntimeError):
    """Raised with an actionable message — never a bare failure."""


@dataclass
class Window:
    """A window the capture backend can see."""

    handle: object          # opaque, meaningful only to the backend
    title: str
    app: str
    width: int
    height: int

    def __str__(self) -> str:
        return f"{self.app} — {self.title} ({self.width}x{self.height})"


class Capture(Protocol):
    """Grabs frames from one window.

    Implementations must return a greyscale `ndarray`, because that is what the
    trigger compares and what the OCR engines want. Colour is never needed
    downstream and doubles the bytes moved per frame.
    """

    def grab(self) -> np.ndarray | None:
        """One frame, or None if the window went away."""

    def close(self) -> None:
        ...


def list_windows(app_hint: str = "") -> list[Window]:
    """Windows currently on screen, optionally filtered by application name."""
    return _backend().list_windows(app_hint)


def open_window(title_hint: str = "", app_hint: str = "Journeys",
                wait: float = 0.0) -> Capture:
    """Open a capture on the first window matching the hints.

    The default hint targets the game. Raises `CaptureError` with something the
    user can act on when nothing matches — a silent empty capture would look
    exactly like a game that is simply not showing text.
    """
    return _backend().open_window(title_hint, app_hint, wait)


def open_display(index: int = 0) -> Capture:
    """Capture an entire display instead of one window.

    Slower to process and noisier for OCR, but it avoids the window-filter code
    path in ScreenCaptureKit that can abort the process on macOS. Use it when
    window capture will not cooperate.
    """
    backend = _backend()
    if not hasattr(backend, "open_display"):
        raise CaptureError("this backend cannot capture a whole display")
    return backend.open_display(index)


def foreground() -> str | None:
    """"app title" of whatever the user is looking at, or None if unknowable.

    Display capture takes the monitor, not the game, so it also takes the
    narrator's own terminal, the Start menu, and anything else in front. That is
    not a hypothetical: a Windows session read its own console back and reported
    "no match" against the menu it had just printed.

    Knowing what is in front is what lets the loop hold its tongue until the game
    is. Returns None on a backend that cannot answer, and the caller then does
    what it did before rather than refusing to run.
    """
    backend = _backend()
    if not hasattr(backend, "foreground"):
        return None
    try:
        return backend.foreground()
    except Exception:  # noqa: BLE001
        return None


def app_names(app_hint: str) -> list[str]:
    """The alternatives in a hint like "Journeys|JiME", lowercased.

    The same game is not called the same thing on the two platforms: macOS
    reports the bundle's display name, "Journeys in Middle-earth", and Windows
    reports the executable, `JiME.exe`. So the default hint names it both ways
    and any of them counts.

    This lived inline in `is_foreground` and nowhere else, which meant the
    foreground guard understood `|` and the two window matchers did not — they
    compared the literal string "journeys|jime", which matches neither name.
    Window capture could not find the game on either platform with the default
    hint. It went unnoticed because `--display` is the documented path and does
    not go through here.
    """
    return [h.strip().lower() for h in app_hint.split("|") if h.strip()]


def app_matches(app: str, app_hint: str) -> bool:
    """Does this application name satisfy the hint?

    The application name, never the window title. Matching the title would cover
    both platforms with one name and is worse for a reason this project can name
    precisely: a terminal's title is its command line, and this project's own
    directory is called `journeysInMiddleEarthTextToSpeech`, so the terminal the
    narrator was launched from passes a `Journeys` hint. The Windows backend was
    matching `f"{app} {title}"` and had exactly that hole.
    """
    names = app_names(app_hint)
    return not names or any(n in (app or "").lower() for n in names)


def is_foreground(app_hint: str, title_hint: str = "") -> bool | None:
    """Whether the game is the window in front. None when it cannot be told.

    The hint may name the application more than one way, separated by `|`, and
    any of them counts. The same game is not called the same thing on the two
    platforms: macOS reports the bundle's display name, "Journeys in
    Middle-earth", while Windows reports the executable, `JiME.exe`. Matching
    only the first left the guard permanently shut on Windows — the game was in
    front and the narrator, comparing "journeys" against "jime.exe", could not
    see it.

    Matching the window *title* instead would cover both and is worse: a
    terminal's title is its command line, and this project's own directory is
    named after the game, so the terminal you launched from would pass.
    """
    front = foreground()
    if front is None:
        return None
    front = front.lower()
    names = app_names(app_hint)
    return ((not names or any(h in front for h in names))
            and (not title_hint or title_hint.lower() in front))


def _backend():
    system = platform.system()
    if system == "Darwin":
        from . import macos
        return macos
    if system == "Windows":
        from . import windows
        return windows
    raise CaptureError(
        f"no capture backend for {system}. The trigger, matcher and player are "
        f"portable, but grabbing another window's pixels is not — see "
        f"capture/base.py for what each platform needs.")
