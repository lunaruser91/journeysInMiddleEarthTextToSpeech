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
import time
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
        import Quartz  # noqa: F401  — see _cgimage_to_gray: must precede capture
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
    """CGImage → greyscale ndarray, without a round trip through PNG on disk.

    **Quartz has to be imported before the capture call, not here.** pyobjc
    bridges a callback argument using the types it knows at the moment the
    callback fires. ScreenCaptureKit's own bindings do not describe `CGImageRef`,
    so if Quartz has not been imported by then the image arrives as an opaque
    `PyObjCPointer`. It looks healthy — width, height and stride all read back
    correctly — but `CGDataProviderCopyData` returns None on it and the failure
    surfaces here, far from its cause.

    Importing Quartz inside this function is too late: the bridging already
    happened. Hence the imports at the top of both grab() methods.
    """
    import Quartz

    width = Quartz.CGImageGetWidth(image)
    height = Quartz.CGImageGetHeight(image)
    provider = Quartz.CGImageGetDataProvider(image)
    data = Quartz.CGDataProviderCopyData(provider)
    stride = Quartz.CGImageGetBytesPerRow(image)
    if data is None:
        raise CaptureError(
            "the captured image yielded no pixel data. This is the signature of "
            "Quartz having been imported after the capture — see the note in "
            "_cgimage_to_gray.")

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
    _display: object | None = None
    _refreshed: float = 0.0

    # Enumerating shareable content costs ~35 ms, a third of the frame budget at
    # 10 Hz, and the display list barely ever changes. So it is reused, but only
    # for a bounded time: a display that has been unplugged leaves a stale
    # SCDisplay behind, and stale objects are what make SkyLight abort.
    CONTENT_TTL = 2.0

    def grab(self) -> np.ndarray | None:
        import Quartz  # noqa: F401  — see _cgimage_to_gray: must precede capture
        import ScreenCaptureKit as SCK

        now = time.monotonic()
        if self._display is None or now - self._refreshed > self.CONTENT_TTL:
            content = _shareable_content()
            displays = content.displays()
            if not displays or self.index >= len(displays):
                return None
            # keep the content alive: the SCDisplay is only meaningful while it is
            self._content, self._display = content, displays[self.index]
            self._refreshed = now
        display = self._display

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


def open_window(title_hint: str = "", app_hint: str = "Journeys",
                wait: float = 0.0) -> Capture:
    """Open a capture, optionally waiting for the window to become visible.

    Waiting is not a convenience — it is how this works at all when the game runs
    fullscreen. **macOS does not render inactive Spaces.** A fullscreen game lives
    on its own Space, and while you are looking at the terminal that Space is not
    being composited: the window is not on screen, and nothing can capture it.

    Which means the capture cannot be opened from the terminal you start it in.
    Start the narrator, switch to the game, and it picks the window up as soon as
    that Space becomes active.
    """
    deadline = time.monotonic() + wait
    announced = False
    while True:
        window = _find(title_hint, app_hint)
        if window is not None:
            return MacCapture(window=window)
        if time.monotonic() >= deadline:
            break
        if not announced:
            print("waiting for the game window — switch to it now "
                  "(fullscreen games live on their own Space, which macOS does "
                  "not render while you are looking at another one)", flush=True)
            announced = True
        time.sleep(0.5)

    seen = list_windows("")
    raise CaptureError(
        f"no usable window matching app={app_hint!r} title={title_hint!r}.\n\n"
        f"If the game IS running, it is almost certainly fullscreen on another "
        f"Space.\nmacOS does not render an inactive Space, so its window is not "
        f"capturable\nfrom here. Start with --wait and switch to the game, or run "
        f"the game windowed.\n\n"
        f"Windows visible right now:\n  "
        + "\n  ".join(str(w) for w in seen[:12]))
