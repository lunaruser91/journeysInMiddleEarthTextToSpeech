#!/usr/bin/env python3
"""
capture/macos.py — window capture through ScreenCaptureKit.

Uses the official pyobjc bindings, so there is no Swift helper to build and sign.
That matters more than it looks: an ad-hoc signed helper binary is blocked from
holding screen-recording permission since Sequoia, whereas a Python script
launched from a terminal simply inherits the terminal's grant.

## The asynchronous API, made synchronous

Every ScreenCaptureKit entry point takes a completion handler and returns
immediately. The trigger wants a plain blocking `grab()`, so each call here waits
on a semaphore that the handler signals. The handlers run on Grand Central
Dispatch queues, not the calling thread, which is why the results are stashed in
a list rather than returned.

A timeout guards those waits anyway. Measured on this machine, a denied
permission does *not* hang: the handler is called with error -3801 and a clear
message. But the timeout stays, because a framework that never answers would
otherwise hang the narrator silently — the worst failure mode for a tool meant to
run unattended.
"""
from __future__ import annotations

import threading
from dataclasses import dataclass

import numpy as np

from .base import Capture, CaptureError, Window

TIMEOUT = 5.0


def _shareable_content():
    """The windows ScreenCaptureKit is willing to show us."""
    import ScreenCaptureKit as SCK

    box, done = [], threading.Event()

    def handler(content, error):
        box.append((content, error))
        done.set()

    SCK.SCShareableContent.getShareableContentWithCompletionHandler_(handler)
    if not done.wait(TIMEOUT):
        raise CaptureError(
            "ScreenCaptureKit never answered. This is what a missing permission "
            "looks like — the completion handler is simply never called.\n"
            "Grant it in System Settings → Privacy & Security → Screen Recording, "
            "tick your terminal application, then restart the terminal.")
    content, error = box[0]
    if error is not None or content is None:
        # -3801 is TCC denial. Verified on this machine: the handler IS called
        # and returns this code, so the timeout above only covers the rarer case
        # where the framework never answers at all.
        code = getattr(error, "code", lambda: None)()
        if code == -3801:
            raise CaptureError(
                "screen recording permission has not been granted.\n\n"
                "  System Settings → Privacy & Security → Screen Recording\n"
                "  Tick your terminal application, then RESTART the terminal —\n"
                "  the grant is read when the process launches, so a running\n"
                "  terminal keeps the old answer.\n\n"
                "Nothing needs to be signed or notarised: the permission attaches\n"
                "to the terminal, and this script inherits it.")
        raise CaptureError(f"ScreenCaptureKit refused: {error}")
    return content


def _usable(w) -> bool:
    """Is this window something SCContentFilter can safely be built from?

    This check is not defensive politeness — it prevents a **process abort**.
    `SCContentFilter initWithDesktopIndependentWindow:` calls down into
    SkyLight's `SLSGetDisplaysWithRect`, which fires an assertion, and therefore
    `abort()`, when handed a rect it cannot place on any display. That kills the
    interpreter outright: it is not a raised exception and cannot be caught from
    Python. Observed as a real crash on macOS 26.5.2.

    Windows that are off-screen, zero-sized, or belonging to no application all
    produce such a rect.
    """
    try:
        frame = w.frame()
        if frame.size.width < 1 or frame.size.height < 1:
            return False
        if not w.isOnScreen():
            return False
        return w.owningApplication() is not None
    except Exception:  # noqa: BLE001
        return False


def list_windows(app_hint: str = "") -> list[Window]:
    # The SCWindow objects are only meaningful while the SCShareableContent that
    # produced them is alive, so it is carried along on each Window rather than
    # left to be collected.
    content = _shareable_content()
    out = []
    for w in content.windows():
        if not _usable(w):
            continue
        app = w.owningApplication()
        app_name = app.applicationName() if app else ""
        title = w.title() or ""
        if app_hint and app_hint.lower() not in app_name.lower():
            continue
        frame = w.frame()
        out.append(Window(handle=(w, content), title=title, app=app_name,
                          width=int(frame.size.width),
                          height=int(frame.size.height)))
    return out


@dataclass
class MacCapture(Capture):
    window: Window

    def grab(self) -> np.ndarray | None:
        import ScreenCaptureKit as SCK

        # Re-resolve the window every time. A cached SCWindow goes stale when the
        # game moves between displays, is minimised, or is relaunched — and a
        # stale one is exactly what makes SkyLight abort the process.
        fresh = _find(self.window.title, self.window.app)
        if fresh is None:
            return None
        self.window = fresh
        w, _content = self.window.handle
        # desktopIndependentWindow captures the window alone: no desktop behind
        # it, nothing overlapping it, and no need to keep it frontmost.
        filt = SCK.SCContentFilter.alloc().initWithDesktopIndependentWindow_(w)
        cfg = SCK.SCStreamConfiguration.alloc().init()
        cfg.setWidth_(self.window.width)
        cfg.setHeight_(self.window.height)

        box, done = [], threading.Event()

        def handler(image, error):
            box.append((image, error))
            done.set()

        SCK.SCScreenshotManager.captureImageWithFilter_configuration_completionHandler_(
            filt, cfg, handler)
        if not done.wait(TIMEOUT):
            raise CaptureError("the capture timed out; see the permission note above")
        image, error = box[0]
        if error is not None or image is None:
            return None                      # window closed, or the game quit
        return _cgimage_to_gray(image)

    def close(self) -> None:
        pass


def _cgimage_to_gray(image) -> np.ndarray:
    """CGImage → greyscale ndarray, without a round trip through PNG on disk."""
    import Quartz

    width = Quartz.CGImageGetWidth(image)
    height = Quartz.CGImageGetHeight(image)
    provider = Quartz.CGImageGetDataProvider(image)
    data = Quartz.CGDataProviderCopyData(provider)
    stride = Quartz.CGImageGetBytesPerRow(image)

    buf = np.frombuffer(data, dtype=np.uint8)
    # rows are padded to the stride, so reshape by stride and then trim
    buf = buf[:height * stride].reshape(height, stride)
    pixels = buf[:, :width * 4].reshape(height, width, 4)

    # macOS hands these over as BGRA. Rec. 601 luma, in integer arithmetic to
    # keep a 1920x1080 frame cheap at 10 Hz.
    b = pixels[:, :, 0].astype(np.uint16)
    g = pixels[:, :, 1].astype(np.uint16)
    r = pixels[:, :, 2].astype(np.uint16)
    return ((r * 77 + g * 150 + b * 29) >> 8).astype(np.uint8)


@dataclass
class DisplayCapture(Capture):
    """Capture the whole display instead of one window.

    A safety valve. Window capture goes through
    `SCContentFilter initWithDesktopIndependentWindow:`, which aborts the process
    — via a SkyLight assertion, not a catchable exception — when it dislikes the
    window's rect. The display path never touches that code, so it works when the
    window path cannot even be attempted safely.

    The trade-off is real: the frame includes everything on screen, so the
    dialogue-box crop has to account for the game not filling the display, and
    anything overlapping the game ends up in the OCR.
    """

    index: int = 0
    _content: object | None = None

    def grab(self) -> np.ndarray | None:
        import ScreenCaptureKit as SCK

        content = _shareable_content()
        self._content = content            # keep alive while the filter exists
        displays = content.displays()
        if not displays or self.index >= len(displays):
            return None
        display = displays[self.index]

        filt = SCK.SCContentFilter.alloc().initWithDisplay_excludingWindows_(
            display, [])
        cfg = SCK.SCStreamConfiguration.alloc().init()
        cfg.setWidth_(display.width())
        cfg.setHeight_(display.height())

        box, done = [], threading.Event()

        def handler(image, error):
            box.append((image, error))
            done.set()

        SCK.SCScreenshotManager.captureImageWithFilter_configuration_completionHandler_(
            filt, cfg, handler)
        if not done.wait(TIMEOUT):
            raise CaptureError("the display capture timed out")
        image, error = box[0]
        if error is not None or image is None:
            return None
        return _cgimage_to_gray(image)

    def close(self) -> None:
        pass


def _find(title_hint: str, app_hint: str) -> Window | None:
    windows = list_windows(app_hint)
    if title_hint:
        windows = [w for w in windows if title_hint.lower() in w.title.lower()]
    windows = [w for w in windows if w.width > 200 and w.height > 200]
    return max(windows, key=lambda w: w.width * w.height) if windows else None


def open_display(index: int = 0) -> Capture:
    """Capture a whole display. See DisplayCapture for when this is the answer."""
    return DisplayCapture(index=index)


def open_window(title_hint: str = "", app_hint: str = "Journeys") -> Capture:
    window = _find(title_hint, app_hint)
    if window is None:
        seen = list_windows("")
        raise CaptureError(
            f"no usable window matching app={app_hint!r} title={title_hint!r}.\n"
            f"Is the game running and not minimised? Windows visible now:\n  "
            + "\n  ".join(str(w) for w in seen[:12]))
    return MacCapture(window=window)
