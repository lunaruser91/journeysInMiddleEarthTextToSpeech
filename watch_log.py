#!/usr/bin/env python3
"""
watch_log.py — watches the game's logs and prints the text of every block shown.

It exists to answer the question that decides the Phase 3 architecture:
**does the game write the log in real time, or only dump it when saving?**

How to use:

  1. run this script
  2. open the game and load any session
  3. advance two or three narration screens

If the lines show up here the moment they appear on screen, Phase 3 can be a
plain file reader — no screen capture, no OCR, none of the macOS TCC
permissions, and the same code on Windows.
If they only show up when the game saves, the log still works as context, but
the trigger will have to be the screen.

    python3 watch_log.py                    # watches every slot
    python3 watch_log.py --slot 2           # only one
    python3 watch_log.py --all              # includes non-narration blocks

Writes nothing, never touches the game: it only reads files.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import time
from collections import deque
from pathlib import Path

SAVES = Path(os.path.expanduser(
    "~/Library/Application Support/com.fantasyflightgames.jime/SavedGames"))
DEFAULT_CORPUS = Path(__file__).resolve().parent / "corpus" / "corpus_pt.json"

LINE_RE = re.compile(r"^\[([^|]*)\|([^|]*)\|([^|\]]+)((?:\|[^\]]*)*)\]$")

# parameter types observed in the logs
TYPE_KEY_REF = "8"   # the value is another localization key
TYPE_LITERAL = "10"  # the value is a literal (number, tile id...)

GRAY, GREEN, YELLOW, RESET = "\033[90m", "\033[92m", "\033[93m", "\033[0m"


def load_corpus(path: Path) -> dict:
    if not path.exists():
        return {}
    corpus = json.loads(path.read_text(encoding="utf-8"))
    idx = {}
    for k, v in corpus.items():
        idx.setdefault(k.split(":", 1)[1], v)   # key -> entry (1st campaign wins)
    return idx


def parse_params(rest: str) -> list[str]:
    """Extracts the parameter values. Each takes up 4 fields: type|?|value|?"""
    fields = [c for c in rest.split("|") if c != ""]
    if not fields or not fields[0].isdigit():
        return []
    n = int(fields[0])
    body = fields[1:]
    if len(body) < 4 * n:
        return []
    return [body[i * 4 + 2] for i in range(n)]


def resolve(text: str, values: list[str], idx: dict) -> str:
    """Replaces {0}, {1}... with the values, resolving references to other keys."""
    for i, val in enumerate(values):
        target = idx.get(val)
        readable = target["text"] if target else val
        text = text.replace("{%d}" % i, readable)
    return text


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--slot", help="watch only this slot (default: all of them)")
    ap.add_argument("--corpus", type=Path, default=DEFAULT_CORPUS)
    ap.add_argument("--all", action="store_true",
                    help="also show blocks that are not narration")
    ap.add_argument("--interval", type=float, default=0.25)
    args = ap.parse_args()

    if not SAVES.exists():
        raise SystemExit(f"[error] saves folder not found: {SAVES}")

    idx = load_corpus(args.corpus)
    print(f"[corpus] {len(idx):,} keys loaded from {args.corpus}"
          if idx else f"[corpus] not found at {args.corpus} — showing keys only")

    pattern = f"{args.slot}/Log*.txt" if args.slot else "*/Log*.txt"
    files = sorted(SAVES.glob(pattern))
    if not files:
        raise SystemExit(f"[error] no log in {SAVES}/{pattern}")

    # start at the end: only what happens from now on matters
    pos = {f: f.stat().st_size for f in files}
    for f in files:
        print(f"[watching] {f.relative_to(SAVES)}  ({pos[f]:,} bytes)")

    print(f"\n{GREEN}Ready. Open the game, load a session and advance one narration "
          f"screen.{RESET}")
    print(f"{GRAY}If the lines show up right away, Phase 3 gets much simpler."
          f"  Ctrl+C to quit.{RESET}\n")

    recent: deque[str] = deque(maxlen=4000)  # LogA and LogB repeat the same content
    last_ping = time.time()
    try:
        while True:
            if time.time() - last_ping > 30:
                print(f"{GRAY}[alive] {time.strftime('%H:%M:%S')} — no write "
                      f"detected yet{RESET}")
                last_ping = time.time()
            # the game may create a new slot in the middle of a session
            for new in sorted(SAVES.glob(pattern)):
                if new not in pos:
                    pos[new] = 0
                    files.append(new)
                    print(f"{YELLOW}[new file]{RESET} {new.relative_to(SAVES)}")

            for f in list(files):
                try:
                    size = f.stat().st_size
                except FileNotFoundError:
                    continue
                if size == pos[f]:
                    continue
                # ALWAYS announce the write — this is what answers "live or on save?"
                print(f"{YELLOW}[write]{RESET} {time.strftime('%H:%M:%S')} "
                      f"{f.relative_to(SAVES)}  {pos[f]:,} -> {size:,} bytes")
                if size < pos[f]:         # the game truncated/rewrote the file
                    pos[f] = 0
                with f.open("r", encoding="utf-8", errors="replace") as fh:
                    fh.seek(pos[f])
                    fresh = fh.read()
                    pos[f] = fh.tell()

                for line in fresh.splitlines():
                    line = line.strip()
                    if not line or line in recent:
                        continue
                    recent.append(line)
                    m = LINE_RE.match(line)
                    if not m:
                        print(f"{YELLOW}[unknown format]{RESET} {line}")
                        continue
                    adventure, round_, key, rest = m.groups()
                    v = idx.get(key)
                    narration = bool(v and v.get("narration"))
                    if not args.all and idx and not narration:
                        continue
                    when = time.strftime("%H:%M:%S")
                    mark = f"{GREEN}NARR {RESET}" if narration else f"{GRAY} ui  {RESET}"
                    print(f"{GRAY}{when}{RESET} {mark} "
                          f"{GRAY}adv{adventure} rnd{round_}{RESET} {key}")
                    if v:
                        text = resolve(v["text"], parse_params(rest), idx)
                        text = " ".join(text.split())
                        print(f"        {text[:150]}")
            time.sleep(args.interval)
    except KeyboardInterrupt:
        print("\n[done]")


if __name__ == "__main__":
    main()
