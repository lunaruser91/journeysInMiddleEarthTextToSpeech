#!/usr/bin/env python3
"""
test_capture_linux.py — the X11 backend against a real X server.

Nothing here is mocked, because the bug this file exists for could not have been
caught by a mock: the backend asked the X server where the game's window was and
got the right numbers with the wrong sign. A mock would have returned whatever
the test's author believed the answer to be. A fullscreen game sits at (0, 0),
where the sign does not show, so it also survived being played.

So the test puts a window of its own on the screen, at a position that is not
the origin and in a colour the desktop is not, and checks that the pixels the
backend returns are that window's.

It needs an X server and no game. Any will do, including a virtual one:

    xvfb-run -s "-screen 0 1280x800x24" python test_capture_linux.py

A window manager is optional. Without one the "which window is in front" check is
skipped, since nothing is there to answer it.
"""
from __future__ import annotations

import os
import platform
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

import console  # noqa: E402

console.setup()

GREEN, YELLOW, RED, GRAY, RESET = ("\033[92m", "\033[93m", "\033[91m",
                                   "\033[90m", "\033[0m")

# Not the origin, and not symmetric: a swapped or negated coordinate lands
# somewhere else.
X, Y, W, H = 301, 220, 640, 360
# A title of its own, so the test finds its window and not a game that happens
# to be running beside it.
TITLE = "Journeys in Middle-earth (capture test)"
WM_CLASS = "steam_app_1003400"          # what Proton sets for this game

failures = 0


def check(label: str, good: bool, detail: str = "") -> None:
    global failures
    failures += not good
    mark = f"{GREEN}✓{RESET}" if good else f"{RED}✗{RESET}"
    print(f"  {mark} {label:<46} {GRAY}{detail}{RESET}")


def skip(label: str, why: str) -> None:
    print(f"  {YELLOW}-{RESET} {label:<46} {GRAY}{why}{RESET}")


def main() -> int:
    if platform.system() != "Linux":
        print(f"{GRAY}skipped: this tests the Linux backend and this is "
              f"{platform.system()}{RESET}")
        return 0
    if not os.environ.get("DISPLAY"):
        print(f"{GRAY}skipped: no X server. Run it under xvfb-run.{RESET}")
        return 0
    # A virtual X server started from inside a Wayland session is exactly the
    # nested server the override exists for.
    os.environ["JIME_FORCE_X11"] = "1"

    from Xlib import X as xconst
    from Xlib import Xatom, display

    from capture import linux
    from capture.base import GAME_APP, CaptureError, is_foreground

    d = display.Display()
    screen = d.screen()
    root = screen.root
    # A black desktop and a white window: every check below is a brightness.
    root.change_attributes(background_pixel=screen.black_pixel)
    root.clear_area(width=screen.width_in_pixels, height=screen.height_in_pixels)
    win = root.create_window(X, Y, W, H, 0, screen.root_depth,
                             background_pixel=screen.white_pixel,
                             event_mask=xconst.ExposureMask)
    win.set_wm_name(TITLE)
    win.set_wm_class(WM_CLASS, WM_CLASS)
    win.change_property(d.intern_atom("_NET_WM_NAME"),
                        d.intern_atom("UTF8_STRING"), 8, TITLE.encode())
    # Ask to be put exactly here; a window manager is otherwise free to choose.
    win.set_wm_normal_hints(flags=0x1 | 0x4, min_width=W, min_height=H)  # USPosition | PPosition
    win.map()
    d.sync()
    time.sleep(1.0)                      # let a window manager reparent and draw
    win.clear_area(width=W, height=H)
    d.sync()

    managed = root.get_full_property(
        d.intern_atom("_NET_SUPPORTING_WM_CHECK"), Xatom.WINDOW) is not None
    actual = root.translate_coords(win, 0, 0)
    print(f"{GRAY}X server {os.environ['DISPLAY']}, "
          f"{screen.width_in_pixels}x{screen.height_in_pixels}, "
          f"{'with' if managed else 'without'} a window manager; test window at "
          f"({actual.x}, {actual.y}){RESET}\n")

    # ---------------------------------------------------------------- listing
    listed = [w for w in linux.list_windows("") if w.title == TITLE]
    check("the window is listed", len(listed) == 1,
          str(listed[0]) if listed else "not found")
    check("a Proton window answers to the default hint",
          any(w.title == TITLE for w in linux.list_windows(GAME_APP)),
          f"{WM_CLASS} + title, against {GAME_APP!r}")
    check("and not to somebody else's",
          not [w for w in linux.list_windows("Firefox") if w.title == TITLE])

    # ----------------------------------------------------------------- window
    cap = linux.open_window(TITLE, GAME_APP)
    frame = cap.grab()
    check("window capture returns a frame", frame is not None)
    if frame is not None:
        check("of the window's size", frame.shape == (H, W),
              f"{frame.shape[1]}x{frame.shape[0]}, expected {W}x{H}")
        # The whole point. Negated coordinates return a frame too — of the
        # black desktop off to one side.
        check("showing the window, not the desktop beside it",
              float(frame.mean()) > 250, f"mean brightness {frame.mean():.0f}")

    # ---------------------------------------------------------------- display
    full = linux.open_display(0).grab()
    check("display capture returns the monitor", full is not None,
          f"{full.shape[1]}x{full.shape[0]}" if full is not None else "")
    if full is not None:
        inside = float(full[actual.y + 10:actual.y + H - 10,
                            actual.x + 10:actual.x + W - 10].mean())
        outside = float(full[:actual.y - 40, :].mean()) if actual.y > 60 else 0.0
        check("with the window where the X server says it is",
              inside > 250 and outside < 60,
              f"inside {inside:.0f}, above it {outside:.0f}")
    try:
        linux.open_display(7)
        check("a display that does not exist is refused", False, "it opened")
    except CaptureError as exc:
        check("a display that does not exist is refused", True,
              str(exc).split(":")[0])

    # ------------------------------------------------------------- foreground
    if managed:
        win.set_input_focus(xconst.RevertToParent, xconst.CurrentTime)
        root.send_event(
            _client_message(d, win, "_NET_ACTIVE_WINDOW"),
            event_mask=(xconst.SubstructureRedirectMask
                        | xconst.SubstructureNotifyMask))
        d.sync()
        time.sleep(0.5)
        front = linux.foreground()
        check("the window in front is known", WM_CLASS in front, repr(front))
        check("and recognised as the game", is_foreground(GAME_APP) is True)
    else:
        skip("the window in front is known", "no window manager to ask")

    # --------------------------------------------------------------- following
    win.configure(x=40, y=60)
    d.sync()
    time.sleep(0.5)
    moved = cap.grab()
    check("a moved window is followed",
          moved is not None and moved.shape == (H, W)
          and float(moved.mean()) > 250,
          f"mean brightness {moved.mean():.0f}" if moved is not None else "no frame")

    win.unmap()
    d.sync()
    time.sleep(0.5)
    check("a hidden window yields no frame", cap.grab() is None,
          "rather than whatever is now behind it")
    win.destroy()
    d.sync()
    check("a closed window yields no frame", cap.grab() is None)

    # ----------------------------------------------------------------- wayland
    del os.environ["JIME_FORCE_X11"]
    os.environ["XDG_SESSION_TYPE"] = "wayland"
    try:
        linux.open_display(0)
        check("a Wayland session is refused by name", False, "it opened")
    except CaptureError as exc:
        check("a Wayland session is refused by name", "X11" in str(exc),
              str(exc).split("\n")[0])

    d.close()
    print(f"\n{RED}{failures} failed{RESET}" if failures
          else f"\n{GREEN}the X11 backend sees what is on the screen.{RESET}")
    return 1 if failures else 0


def _client_message(d, win, name: str):
    from Xlib.protocol import event

    return event.ClientMessage(window=win, client_type=d.intern_atom(name),
                               data=(32, [1, 0, 0, 0, 0]))


if __name__ == "__main__":
    sys.exit(main())
