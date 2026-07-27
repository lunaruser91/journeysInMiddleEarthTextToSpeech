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

A timeout is mandatory on those waits. Without permission the handler is never
called at all, and a bare `semaphore.wait()` would hang the whole narrator with
no message — the single worst failure mode for a tool that runs unattended.
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
        raise CaptureError(f"ScreenCaptureKit refused: {error}")
    return content


def list_windows(app_hint: str = "") -> list[Window]:
    content = _shareable_content()
    out = []
    for w in content.windows():
        app = w.owningApplication()
        app_name = app.applicationName() if app else ""
        title = w.title() or ""
        if app_hint and app_hint.lower() not in app_name.lower():
            continue
        frame = w.frame()
        out.append(Window(handle=w, title=title, app=app_name,
                          width=int(frame.size.width),
                          height=int(frame.size.height)))
    return out


@dataclass
class MacCapture(Capture):
    window: Window

    def grab(self) -> np.ndarray | None:
        import ScreenCaptureKit as SCK

        w = self.window.handle
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


def open_window(title_hint: str = "", app_hint: str = "Journeys") -> Capture:
    windows = list_windows(app_hint)
    if title_hint:
        windows = [w for w in windows if title_hint.lower() in w.title.lower()]
    windows = [w for w in windows if w.width > 200 and w.height > 200]
    if not windows:
        seen = list_windows("")
        raise CaptureError(
            f"no window matching app={app_hint!r} title={title_hint!r}.\n"
            f"Is the game running? Visible windows right now:\n  "
            + "\n  ".join(str(w) for w in seen[:12]))
    return MacCapture(window=max(windows, key=lambda w: w.width * w.height))
