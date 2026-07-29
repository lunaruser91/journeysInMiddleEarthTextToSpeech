#!/usr/bin/env python3
"""
capture/windows.py — window capture through Windows.Graphics.Capture.

## Why not the obvious APIs

`BitBlt` and `PrintWindow` return **black frames for Unity windows**. The game
renders through the GPU and never draws into the window's device context, so
there is nothing for those APIs to copy. Windows.Graphics.Capture asks the
compositor instead, which is the only thing holding the pixels.

`windows-capture` wraps it. No permission prompt is involved: on Windows 10 2004
and later, capturing a named window needs no grant. Windows 11 draws a yellow
border around a captured window; that is cosmetic and cannot be turned off.

    pip install -e '.[capture]'

## Exclusive fullscreen is invisible

Windows.Graphics.Capture sees what the compositor composes. A game in *exclusive*
fullscreen bypasses the compositor, so no frames arrive — reported from play as
"it only reads when I alt-tab", alt-tab being the moment the game drops back into
composition.

Two ways around it: set the game to borderless windowed, which is the better fix
where the game offers it, or capture the display rather than the window.

## Enumeration is ours, not the library's

The first version of this file called `windows_capture.Window.enumerate()`. That
method does not exist — the API had been written from memory and never run, and
the first real Windows session said so in one line:

    module 'windows_capture' has no attribute 'Window'

The library captures; it does not list. Listing therefore goes through `user32`
by ctypes, which adds no dependency and yields the owning process name as well —
which is what the application hint needs to match against.
"""
from __future__ import annotations

import ctypes
import threading
import time
from ctypes import wintypes
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
            "    pip install -e '.[capture]'") from exc
    return windows_capture


# -------------------------------------------------------------- enumeration --

def _process_name(hwnd: int) -> str:
    """The executable behind a window, or "" — what the app hint matches on."""
    user32, kernel32 = ctypes.windll.user32, ctypes.windll.kernel32
    pid = wintypes.DWORD()
    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    if not pid.value:
        return ""
    # PROCESS_QUERY_LIMITED_INFORMATION: enough for the image name, and granted
    # between processes at the same integrity level without elevation
    handle = kernel32.OpenProcess(0x1000, False, pid.value)
    if not handle:
        return ""
    try:
        size = wintypes.DWORD(260)
        buf = ctypes.create_unicode_buffer(size.value)
        if kernel32.QueryFullProcessImageNameW(handle, 0, buf, ctypes.byref(size)):
            return buf.value.rsplit("\\", 1)[-1]
        return ""
    finally:
        kernel32.CloseHandle(handle)


def list_windows(app_hint: str = "") -> list[Window]:
    user32 = ctypes.windll.user32
    found: list[Window] = []

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def each(hwnd, _lparam):
        if not user32.IsWindowVisible(hwnd):
            return True
        length = user32.GetWindowTextLengthW(hwnd)
        if length <= 0:
            return True                 # untitled: toolbars and hidden helpers
        buf = ctypes.create_unicode_buffer(length + 1)
        user32.GetWindowTextW(hwnd, buf, length + 1)
        title = buf.value

        rect = wintypes.RECT()
        user32.GetWindowRect(hwnd, ctypes.byref(rect))
        width, height = rect.right - rect.left, rect.bottom - rect.top
        if width < 1 or height < 1:
            return True

        app = _process_name(hwnd)
        if app_hint and app_hint.lower() not in f"{app} {title}".lower():
            return True
        found.append(Window(handle=int(hwnd), title=title, app=app,
                            width=width, height=height))
        return True

    user32.EnumWindows(each, 0)
    return found


# ------------------------------------------------------------------ capture --

@dataclass
class WindowsCapture(Capture):
    """Bridges a push API to the pull API the trigger expects.

    `windows-capture` delivers frames through a callback on its own thread,
    whereas `grab()` must return one on demand. The latest frame is kept and
    handed over; frames arriving while nobody is asking are dropped deliberately.
    The trigger samples at 10 Hz and the compositor runs at 60, so queueing them
    would only build latency.
    """

    title: str = ""
    hwnd: int | None = None
    monitor: int | None = None
    _latest: np.ndarray | None = field(default=None, init=False)
    _lock: threading.Lock = field(default_factory=threading.Lock, init=False)
    _ready: threading.Event = field(default_factory=threading.Event, init=False)
    _control: object | None = field(default=None, init=False)

    def start(self) -> None:
        wc = _require()
        kwargs: dict = {"cursor_capture": False, "draw_border": False}
        if self.monitor is not None:
            # windows-capture counts monitors from 1; this project's API counts
            # from 0, like ScreenCaptureKit. Passing 0 through fails with "the
            # monitor index must be greater than zero", which says what is wrong
            # without saying whose convention is being violated.
            kwargs["monitor_index"] = self.monitor + 1
        elif self.hwnd is not None:
            kwargs["window_hwnd"] = self.hwnd
        else:
            kwargs["window_name"] = self.title
        session = wc.WindowsCapture(**kwargs)

        @session.event
        def on_frame_arrived(frame, capture_control):     # noqa: ANN001
            # frame_buffer is BGRA. Rec. 601 luma in integer arithmetic, which
            # keeps a 1920x1080 frame cheap at 10 Hz.
            px = frame.frame_buffer
            b = px[:, :, 0].astype(np.uint16)
            g = px[:, :, 1].astype(np.uint16)
            r = px[:, :, 2].astype(np.uint16)
            with self._lock:
                self._latest = ((r * 77 + g * 150 + b * 29) >> 8).astype(np.uint8)
            self._ready.set()

        @session.event
        def on_closed():                                  # noqa: ANN001
            with self._lock:
                self._latest = None
            self._ready.set()

        # free-threaded: plain start() blocks until the capture ends, which here
        # would mean never returning
        self._control = session.start_free_threaded()

    def grab(self) -> np.ndarray | None:
        who = self.title or self.hwnd or f"monitor {self.monitor}"
        if not self._ready.wait(timeout=5.0):
            raise CaptureError(
                f"no frame arrived from {who} within 5 s. Is the window "
                f"minimised? Windows.Graphics.Capture stops delivering frames "
                f"for a minimised window.")
        with self._lock:
            return self._latest

    def close(self) -> None:
        if self._control is not None:
            try:
                self._control.stop()
            except Exception:  # noqa: BLE001
                pass


def open_window(title_hint: str = "", app_hint: str = "Journeys",
                wait: float = 0.0) -> Capture:
    deadline = time.monotonic() + wait
    announced = False
    while True:
        matches = [
            w for w in list_windows("")
            if (not title_hint or title_hint.lower() in w.title.lower())
            and (not app_hint or app_hint.lower() in f"{w.app} {w.title}".lower())
            and w.width > 200 and w.height > 200
        ]
        if matches:
            best = max(matches, key=lambda w: w.width * w.height)
            cap = WindowsCapture(title=best.title, hwnd=best.handle)
            cap.start()
            cap.window = best             # type: ignore[attr-defined]
            return cap
        if time.monotonic() >= deadline:
            break
        if not announced:
            print("waiting for the game window — start it now", flush=True)
            announced = True
        time.sleep(0.5)

    seen = list_windows("")
    raise CaptureError(
        f"no window matching app={app_hint!r} title={title_hint!r}.\n\n"
        f"If the game IS running, it may be in exclusive fullscreen, which\n"
        f"bypasses the compositor — and Windows.Graphics.Capture only sees what\n"
        f"the compositor draws. Set the game to borderless windowed, or capture\n"
        f"the display instead with --display.\n\n"
        f"Visible windows:\n  "
        + "\n  ".join(str(w) for w in seen[:12]))


def open_display(index: int = 0) -> Capture:
    """Capture a whole monitor rather than one window.

    `index` is 0-based, as everywhere else in this project. The translation to
    the library's 1-based numbering happens in start().
    """
    cap = WindowsCapture(monitor=index)
    cap.start()
    return cap
