#!/usr/bin/env python3
"""
console.py — make stdout able to carry the text this project handles.

Windows decides stdout's encoding from the system code page, which for most
installations is cp1252. That is fine until the program prints something cp1252
cannot represent, at which point it does not degrade — it raises
UnicodeEncodeError and the program dies.

This is not about the tick marks and arrows in the output. **The corpus itself
does not fit.** Measured on the game's own text: Czech `ě`, Polish `ł`, every
Russian character, every Chinese one. The narrator prints the text of each
screen it recognises, so on Windows four of the thirteen languages would take
the whole of Phase 3 down on the first block.

Python already writes UTF-16 through WriteConsoleW when stdout is a real
console, so an interactive run tends to survive. Redirect it to a file — which
is what `> log.txt` does, and what render_all.sh does — and it falls back to the
code page and breaks.

`errors="replace"` is deliberate on top of that: a console that genuinely cannot
show a glyph should print a question mark, not end the session.
"""
from __future__ import annotations

import sys
from pathlib import Path


def _enable_ansi() -> None:
    """Ask the Windows console to interpret escape sequences.

    Without this the output is worse than uncoloured — every sequence is printed
    literally, so a status line reads `←[92mpass←[0m` and the report is unusable.
    Windows Terminal turns it on itself; the classic console host, which is what
    a fresh VM opens, does not.

    ENABLE_VIRTUAL_TERMINAL_PROCESSING is 0x0004, and -11/-12 are the standard
    output and error handles.
    """
    import platform

    if platform.system() != "Windows":
        return
    try:
        import ctypes

        kernel32 = ctypes.windll.kernel32
        for handle_id in (-11, -12):
            handle = kernel32.GetStdHandle(handle_id)
            mode = ctypes.c_uint32()
            if kernel32.GetConsoleMode(handle, ctypes.byref(mode)):
                kernel32.SetConsoleMode(handle, mode.value | 0x0004)

        # Tell the console what it is being sent. `setup()` already puts Python's
        # streams in UTF-8, but that only settles which bytes leave this process
        # — the console decodes them with its own code page, which is 850 or 437
        # on a Portuguese or English install. So correct UTF-8 was drawn as
        # nonsense: "vá para o jogo" came out "v├í para o jogo", and every em
        # dash as "ÔÇö".
        #
        # 65001 is UTF-8. This is `chcp 65001` without the subprocess, and it has
        # to be both directions — output for what is printed, input for what is
        # typed at a prompt.
        kernel32.SetConsoleOutputCP(65001)
        kernel32.SetConsoleCP(65001)
    except Exception:  # noqa: BLE001
        pass          # not a console, or an old build: colour is not worth failing over


def setup() -> None:
    """Force UTF-8 and line buffering on stdout and stderr, and colour on Windows.

    Safe to call more than once.

    ## Why line buffering is not optional here

    Python line-buffers a terminal and *block*-buffers a pipe, in 8 KB chunks.
    The narrator's whole output is a slow trickle of one line per screen, so
    behind a pipe it produces nothing at all for a very long time.

    That cost a debugging session. The advice was to run it through `tee` to read
    the log afterwards; the log came back zero bytes, which read exactly like a
    narrator that had done nothing — while the process was in fact running fine,
    with everything it had said still sitting in the buffer. Anything that
    redirects, pipes or logs this program hits it.
    """
    _enable_ansi()
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is None:
            continue                    # not a TextIOWrapper; nothing to fix
        try:
            reconfigure(encoding="utf-8", errors="replace", line_buffering=True)
        except (ValueError, OSError, TypeError):
            try:                        # older wrapper: take what we can get
                reconfigure(encoding="utf-8", errors="replace")
            except (ValueError, OSError):
                pass                    # already detached, or not reconfigurable


def saves_dir() -> Path:
    """Where the game keeps SavedGames, per platform.

    Unity builds this from the company and product names, which differ by OS:
    macOS uses the bundle identifier, Windows uses AppData/LocalLow with the
    names spelled out. Taken from the game's own app.info:
    "Fantasy Flight Games" / "Journeys in Middle-earth".
    """
    import platform

    if platform.system() == "Windows":
        return (Path.home() / "AppData/LocalLow/Fantasy Flight Games"
                / "Journeys in Middle-earth" / "SavedGames")
    if platform.system() == "Darwin":
        return (Path.home() / "Library/Application Support"
                / "com.fantasyflightgames.jime" / "SavedGames")
    # Linux, where the game runs through Proton: Unity writes under the prefix
    return (Path.home() / ".steam/steam/steamapps/compatdata/1152310/pfx"
            / "drive_c/users/steamuser/AppData/LocalLow/Fantasy Flight Games"
            / "Journeys in Middle-earth" / "SavedGames")
