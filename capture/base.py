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


def open_window(title_hint: str = "", app_hint: str = "Journeys") -> Capture:
    """Open a capture on the first window matching the hints.

    The default hint targets the game. Raises `CaptureError` with something the
    user can act on when nothing matches — a silent empty capture would look
    exactly like a game that is simply not showing text.
    """
    return _backend().open_window(title_hint, app_hint)


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
