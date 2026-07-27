#!/usr/bin/env python3
"""
capture/windows.py — window capture through Windows.Graphics.Capture.

**Untested.** Written against the `windows-capture` API and the constraints the
project already knows, but nobody has run it on Windows yet. Treat every line as
a hypothesis until it has been exercised, and please report what breaks.

## Why not the obvious APIs

`BitBlt` and `PrintWindow` return **black frames for Unity windows**. The game
renders through the GPU and never draws into the window's device context, so
there is nothing for those APIs to copy. This is the same shape of problem as
macOS returning only the wallpaper, and it has the same kind of answer: ask the
compositor instead of the window.

Windows.Graphics.Capture is that answer. `windows-capture` wraps it and can
target a window by title, which is what this needs. `zbl` is an alternative with
the same underlying API.

Unlike macOS there is no permission prompt: on Windows 10 2004 and later, capture
of a named window needs no grant. Windows 11 shows a yellow border around a
captured window, which is cosmetic and cannot be turned off.

    pip install windows-capture
"""
from __future__ import annotations

import threading
from dataclasses import dataclass, field

import numpy as np

from .base import Capture, CaptureError, Window


def _require():
    try:
        import windows_capture  # noqa: F401
    except ImportError as exc:
        raise CaptureError(
            "windows-capture is not installed. It wraps Windows.Graphics.Capture, "
            "which is the only API that sees a Unity window — BitBlt and "
            "PrintWindow return black frames.\n"
            "    pip install windows-capture") from exc
    return windows_capture


def list_windows(app_hint: str = "") -> list[Window]:
    wc = _require()
    out = []
    for title in wc.Window.enumerate():
        name = title if isinstance(title, str) else getattr(title, "title", "")
        if app_hint and app_hint.lower() not in name.lower():
            continue
        out.append(Window(handle=name, title=name, app=name, width=0, height=0))
    return out


@dataclass
class WindowsCapture(Capture):
    """Bridges a push API to the pull API the trigger expects.

    `windows-capture` delivers frames through a callback on its own thread,
    whereas `grab()` has to block until a frame is available. The latest frame is
    kept in `_latest` and handed over on demand; frames that arrive while nobody
    is asking are dropped on purpose. The trigger samples at 10 Hz and the game
    renders at 60 — keeping a queue would only build latency.
    """

    title: str
    _latest: np.ndarray | None = field(default=None, init=False)
    _lock: threading.Lock = field(default_factory=threading.Lock, init=False)
    _ready: threading.Event = field(default_factory=threading.Event, init=False)
    _session: object | None = field(default=None, init=False)

    def start(self) -> None:
        wc = _require()
        session = wc.WindowsCapture(window_name=self.title,
                                    cursor_capture=False, draw_border=False)

        @session.event
        def on_frame_arrived(frame, control):        # noqa: ANN001
            rgb = frame.frame_buffer[:, :, :3].astype(np.uint16)
            gray = ((rgb[:, :, 2] * 77 + rgb[:, :, 1] * 150 + rgb[:, :, 0] * 29)
                    >> 8).astype(np.uint8)
            with self._lock:
                self._latest = gray
            self._ready.set()

        @session.event
        def on_closed():                             # noqa: ANN001
            with self._lock:
                self._latest = None
            self._ready.set()

        self._session = session
        threading.Thread(target=session.start, daemon=True).start()

    def grab(self) -> np.ndarray | None:
        if not self._ready.wait(timeout=5.0):
            raise CaptureError(
                f"no frame arrived from {self.title!r} within 5 s. Is the window "
                f"minimised? Windows.Graphics.Capture stops delivering frames for "
                f"a minimised window.")
        with self._lock:
            return self._latest

    def close(self) -> None:
        if self._session is not None:
            try:
                self._session.stop()
            except Exception:  # noqa: BLE001
                pass


def open_window(title_hint: str = "", app_hint: str = "Journeys") -> Capture:
    hint = title_hint or app_hint
    matches = [w for w in list_windows("") if hint.lower() in w.title.lower()]
    if not matches:
        seen = list_windows("")
        raise CaptureError(
            f"no window whose title contains {hint!r}. Is the game running?\n"
            f"Visible windows:\n  " + "\n  ".join(w.title for w in seen[:12]))
    cap = WindowsCapture(title=matches[0].title)
    cap.start()
    return cap
