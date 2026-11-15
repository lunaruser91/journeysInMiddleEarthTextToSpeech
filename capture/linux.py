#!/usr/bin/env python3
"""
capture/linux.py — screen and window capture on an X11 desktop.

The game has no Linux build. It runs through Steam's Proton, and once Proton has
drawn it the pixels are ordinary X11 desktop pixels. Pillow copies them with
`XGetImage` through XCB; python-xlib is used only to ask the window manager
questions — which windows exist, where the game's is, which one is in front.

    pip install -e '.[capture]'

No permission is involved: any X11 client may read the screen.

## X11 only, and it says so

Wayland does not let one application read another's pixels without going through
the desktop portal and a chooser the user has to click each time, which is not a
thing a narrator can do while you are playing. Under a Wayland session the X
server this would talk to is XWayland, whose root window is not the screen:
`XGetImage` on it succeeds and returns black. That is the failure this project
keeps meeting in other clothes — a capture that works and shows nothing — so a
Wayland session is refused by name rather than captured into silence. Log in to
an X11 session instead; KDE's login screen offers "Plasma (X11)".

`JIME_FORCE_X11=1` skips the refusal, for a nested X server that really does own
its pixels (Xephyr, a gamescope session, a VNC desktop).

## What the game is called here

macOS reports the bundle name and Windows the executable. On X11 the equivalent
is `WM_CLASS`, and Proton sets it to the Steam application id —
`steam_app_1003400` — which names nothing a hint could match. So for a
`steam_app_*` window the title is appended to the application name, and
"Journeys" finds it. Only for those: a terminal's title is its command line, this
project's directory is named after the game, and matching titles in general
would mistake the terminal you launched from for the game. Wine outside Steam
reports the executable, `jime.exe`, which the default hint already covers.

## A window capture here is a rectangle of the screen

`grab()` looks the window's rectangle up again on every frame, so moving or
resizing the game is followed. But what it copies is the screen under that
rectangle, not the window's own surface: another window lying on top of the game
is captured too. It matches nothing and is not read aloud, but it is the one way
this backend differs from the other two, where a window capture can only ever
see the game. A minimised window returns no frame at all, so the narrator waits
rather than reading whatever is now where the game used to be.

## Coordinates: which window is asked matters

`translate_coords` is a method of the *destination* window. The first version of
this file called it on the game's window with the root as source, which answers
"where is the root, as seen from the game" — the right numbers, negated. A game
at the screen's origin is at (0, 0) either way, so a fullscreen or maximised game
hid it completely; a window at (301, 220) was looked for at (-301, -220). Found
by running it against a virtual X server and comparing with `xwininfo`.

The Linux/X11 backend was contributed by tharak, implemented with OpenAI Codex.
"""
from __future__ import annotations

import os
import time
from dataclasses import dataclass

import numpy as np

from .base import GAME_APP, Capture, CaptureError, Window, app_matches

IS_VIEWABLE = 2            # X11's map_state for "mapped, and so are its parents"


def _display():
    """A connection to the X server, or a CaptureError that says what to do."""
    wayland = (os.environ.get("XDG_SESSION_TYPE", "").lower() == "wayland"
               or bool(os.environ.get("WAYLAND_DISPLAY")))
    if wayland and not os.environ.get("JIME_FORCE_X11"):
        raise CaptureError(
            "this is a Wayland session, and capture on Linux needs X11.\n\n"
            "Wayland does not let one program read another's pixels unattended;\n"
            "the X server visible from here is XWayland, which answers a screen\n"
            "capture with a black frame instead of an error.\n\n"
            "  Log out, choose an X11 session on the login screen — on KDE,\n"
            "  \"Plasma (X11)\" — and log in again.\n\n"
            "On a nested X server that owns its own pixels, set JIME_FORCE_X11=1.")
    if not os.environ.get("DISPLAY"):
        raise CaptureError(
            "DISPLAY is not set, so there is no X11 desktop to capture. Run "
            "this from a terminal inside your desktop session, not over SSH or "
            "from a text console.")
    try:
        from Xlib import display
    except ImportError as exc:
        raise CaptureError(
            "python-xlib is not installed. It is how the narrator finds the "
            "game's window on X11.\n"
            "    pip install -e '.[capture]'") from exc
    try:
        return display.Display()
    except Exception as exc:  # noqa: BLE001
        raise CaptureError(
            f"cannot connect to the X11 display "
            f"{os.environ['DISPLAY']!r}: {exc}") from exc


# -------------------------------------------------------------- enumeration --

def _title(win) -> str:
    try:
        prop = win.get_full_property(win.display.intern_atom("_NET_WM_NAME"), 0)
        if prop is not None and prop.value is not None:
            value = prop.value
            if isinstance(value, bytes):
                return value.decode("utf-8", errors="replace").rstrip("\0")
            return str(value)
    except Exception:  # noqa: BLE001
        pass
    try:
        name = win.get_wm_name() or ""
        return name.decode("latin-1") if isinstance(name, bytes) else str(name)
    except Exception:  # noqa: BLE001
        return ""


def _app(win) -> str:
    """What the application hint is matched against. See the module docstring."""
    try:
        cls = win.get_wm_class() or ()
        app = cls[-1] if cls else ""
        if app.lower().startswith("steam_app_"):
            title = _title(win)
            return f"{app} {title}" if title else app
        return app
    except Exception:  # noqa: BLE001
        return ""


def _client_windows(d) -> list:
    root = d.screen().root
    prop = root.get_full_property(d.intern_atom("_NET_CLIENT_LIST"), 0)
    if prop is not None:
        return [d.create_resource_object("window", int(w)) for w in prop.value]
    # No EWMH window manager: the root's children are frames or bare clients.
    return list(root.query_tree().children)


def _rect(d, win) -> tuple[int, int, int, int] | None:
    """The window's rectangle in screen coordinates, or None if it is not drawn."""
    if win.get_attributes().map_state != IS_VIEWABLE:
        return None
    geom = win.get_geometry()
    if geom.width < 1 or geom.height < 1:
        return None
    # Asked of the root: "where is the window's own (0, 0), as you see it".
    pos = d.screen().root.translate_coords(win, 0, 0)
    return pos.x, pos.y, geom.width, geom.height


def list_windows(app_hint: str = "") -> list[Window]:
    d = _display()
    try:
        out: list[Window] = []
        for win in _client_windows(d):
            try:
                rect = _rect(d, win)
                if rect is None:
                    continue
                title, app = _title(win), _app(win)
                if not title or not app_matches(app, app_hint):
                    continue
                out.append(Window(handle=int(win.id), title=title, app=app,
                                  width=rect[2], height=rect[3]))
            except Exception:  # noqa: BLE001 — a window closing mid-listing
                continue
        return out
    finally:
        d.close()


def foreground() -> str:
    """Application owning the active window, for the display-capture guard."""
    d = _display()
    try:
        root = d.screen().root
        prop = root.get_full_property(d.intern_atom("_NET_ACTIVE_WINDOW"), 0)
        if prop is None or not len(prop.value) or not int(prop.value[0]):
            return ""
        return _app(d.create_resource_object("window", int(prop.value[0])))
    finally:
        d.close()


def _monitors(d) -> list[tuple[int, int, int, int]]:
    """Each monitor as (x, y, width, height), the primary first.

    X11 presents every monitor as one wide screen, and a capture of that is not
    a capture of "a display": the trigger looks for the dialogue box in a fixed
    band of the frame, and two monitors side by side put the game's band in one
    half of a frame twice as wide. RandR knows where the seams are.
    """
    screen = d.screen()
    whole = [(0, 0, screen.width_in_pixels, screen.height_in_pixels)]
    try:
        from Xlib.ext import randr  # noqa: F401 — registers the methods below
        found = screen.root.xrandr_get_monitors().monitors
    except Exception:  # noqa: BLE001 — no RandR 1.5: one screen is all there is
        return whole
    found = sorted(found, key=lambda m: (not m.primary, m.x, m.y))
    return [(m.x, m.y, m.width_in_pixels, m.height_in_pixels)
            for m in found if m.width_in_pixels and m.height_in_pixels] or whole


# ------------------------------------------------------------------ capture --

@dataclass
class X11Capture(Capture):
    """One rectangle of the screen: a monitor, or wherever a window is now."""

    bbox: tuple[int, int, int, int] | None = None      # left, top, right, bottom
    window_id: int | None = None

    def grab(self) -> np.ndarray | None:
        bbox = self.bbox
        if self.window_id is not None:
            d = _display()
            try:
                rect = _rect(d, d.create_resource_object("window", self.window_id))
                screen = d.screen()
                limit = (screen.width_in_pixels, screen.height_in_pixels)
            except Exception:  # noqa: BLE001 — BadWindow: it has been closed
                return None
            finally:
                d.close()
            if rect is None:
                return None                    # minimised, or on another desktop
            x, y, w, h = rect
            # A window dragged partly off the screen has no pixels out there.
            bbox = (max(x, 0), max(y, 0),
                    min(x + w, limit[0]), min(y + h, limit[1]))
            if bbox[2] - bbox[0] < 1 or bbox[3] - bbox[1] < 1:
                return None
        return _grab(bbox)

    def close(self) -> None:
        pass


def _grab(bbox: tuple[int, int, int, int] | None) -> np.ndarray:
    from PIL import ImageGrab

    try:
        # Naming the display keeps Pillow on XCB. Left to guess, a failure sends
        # it looking for gnome-screenshot, which takes a second and plays a
        # shutter sound ten times a second.
        image = ImageGrab.grab(bbox=bbox, xdisplay=os.environ.get("DISPLAY"))
    except Exception as exc:  # noqa: BLE001
        hint = ""
        if "XCB" in str(exc):
            hint = ("\nThis Pillow was built without XCB. The wheels on PyPI "
                    "have it:\n    pip install --force-reinstall pillow")
        raise CaptureError(f"X11 screen capture failed: {exc}{hint}") from exc
    return np.asarray(image.convert("L"))


def open_display(index: int = 0) -> Capture:
    d = _display()                 # also: configuration errors surface here,
    try:                           # before the play loop rather than inside it
        monitors = _monitors(d)
    finally:
        d.close()
    if not 0 <= index < len(monitors):
        raise CaptureError(
            f"there is no display {index}: this desktop has {len(monitors)}, "
            f"numbered from 0 with the primary first.")
    x, y, w, h = monitors[index]
    return X11Capture(bbox=(x, y, x + w, y + h))


def open_window(title_hint: str = "", app_hint: str = GAME_APP,
                wait: float = 0.0) -> Capture:
    deadline = time.monotonic() + wait
    announced = False
    while True:
        matches = [w for w in list_windows(app_hint)
                   if (not title_hint or title_hint.lower() in w.title.lower())
                   and w.width > 200 and w.height > 200]
        if matches:
            best = max(matches, key=lambda w: w.width * w.height)
            cap = X11Capture(window_id=best.handle)
            cap.window = best  # type: ignore[attr-defined]
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
        f"If the game IS running, look at what it is called below: the hint is\n"
        f"matched against the application name, and --app takes alternatives\n"
        f"separated by `|`. Or capture the display instead with --display.\n\n"
        f"Visible windows:\n  "
        + "\n  ".join(str(w) for w in seen[:12]))
