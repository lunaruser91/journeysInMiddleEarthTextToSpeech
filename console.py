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


def setup() -> None:
    """Force UTF-8 on stdout and stderr. Safe to call more than once."""
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is None:
            continue                    # not a TextIOWrapper; nothing to fix
        try:
            reconfigure(encoding="utf-8", errors="replace")
        except (ValueError, OSError):
            pass                        # already detached, or not reconfigurable


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
