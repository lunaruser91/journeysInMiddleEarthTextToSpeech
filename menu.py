#!/usr/bin/env python3
"""
menu.py — `jime` with no arguments: pick what to do, and see what is already done.

The flags are still there and still the fastest way in once you know them. This
exists for the other case — coming back after a fortnight and not remembering
whether Bones of Arnor was rendered, in which language, or what `main` was for.

Every question shows the state behind it. Choosing a campaign to render shows how
much of each is already done, so "resume the one at 42%" is a thing you can see
rather than remember. Choosing a language shows which ones have a corpus at all.
Nothing here does anything the flags cannot; it just stops you having to hold the
state in your head.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

BOLD, GREEN, YELLOW, RED, GRAY, RESET = (
    "\033[1m", "\033[92m", "\033[93m", "\033[91m", "\033[90m", "\033[0m")


class Abort(Exception):
    """The user asked to go back or quit."""


# --------------------------------------------------------------- questions --

def choose(title: str, rows: list[tuple[str, str]], default: int | None = None,
           allow_back: bool = True) -> int:
    """Numbered pick. Returns the index; raises Abort for back/quit.

    `rows` is (label, detail); the detail is what makes the choice informed —
    how much is rendered, whether a corpus exists — and is printed dimmed beside
    the label.
    """
    print(f"\n{BOLD}{title}{RESET}")
    width = max((len(label) for label, _ in rows), default=0)
    for i, (label, detail) in enumerate(rows, 1):
        mark = f"{GREEN}›{RESET}" if default == i - 1 else " "
        # Only dim a detail that has no colour of its own; wrapping one that
        # does nests the escapes and the reset in the middle ends the dimming
        # early, which looked like a rendering bug.
        shown = detail if "\033[" in detail else f"{GRAY}{detail}{RESET}"
        print(f"  {mark} {i:>2}. {label:<{width}}  {shown}")
    hint = "enter = " + rows[default][0] if default is not None else "1-%d" % len(rows)
    tail = ", b = back" if allow_back else ""
    while True:
        try:
            raw = input(f"{GRAY}  [{hint}{tail}, q = quit] {RESET}").strip().lower()
        except (EOFError, KeyboardInterrupt):
            raise Abort from None
        if raw in ("q", "quit"):
            raise SystemExit(0)
        if raw in ("b", "back") and allow_back:
            raise Abort
        if not raw and default is not None:
            return default
        if raw.isdigit() and 1 <= int(raw) <= len(rows):
            return int(raw) - 1
        print(f"{YELLOW}  pick a number between 1 and {len(rows)}{RESET}")


def confirm(question: str, default: bool = True) -> bool:
    suffix = "[Y/n]" if default else "[y/N]"
    try:
        raw = input(f"{GRAY}  {question} {suffix} {RESET}").strip().lower()
    except (EOFError, KeyboardInterrupt):
        raise Abort from None
    if not raw:
        return default
    return raw.startswith("y") or raw.startswith("s")   # sim, for pt speakers


# ------------------------------------------------------------------- state --

def rendered_by_campaign(lang: str) -> dict[str, int]:
    import jime

    manifest = jime.audio_dir(lang) / "manifest.json"
    if not manifest.exists():
        return {}
    out: dict[str, int] = {}
    for key in json.loads(manifest.read_text(encoding="utf-8")):
        if key.startswith("_"):
            continue
        camp = key.split(":", 1)[0]
        out[camp] = out.get(camp, 0) + 1
    return out


def language_rows() -> list[tuple[str, str, str]]:
    """(code, label, detail) for every language the game ships."""
    import jime

    rows = []
    for code in jime.GAME_LANGUAGES:
        name = jime.LANGUAGE_NAMES.get(code, code)
        corpus = jime.corpus_path(code)
        if not corpus.exists():
            detail = "no corpus yet — extract first"
        else:
            done = sum(rendered_by_campaign(code).values())
            detail = f"corpus ready, {done:,} blocks rendered" if done else "corpus ready"
        rows.append((code, f"{code}  {name}", detail))
    return rows


def campaign_rows(lang: str) -> list[tuple[str, str, str]]:
    """(campaign, label, progress) — progress is the point of this screen."""
    import jime

    done = rendered_by_campaign(lang)
    rows = []
    for camp in jime.CAMPAIGNS:
        total = jime._campaign_total(lang, camp)
        if not total:
            continue
        have = done.get(camp, 0)
        pct = have / total * 100
        if have >= total:
            detail = f"{GREEN}complete{RESET}{GRAY} — {total:,} blocks{RESET}"
        elif have:
            detail = f"{YELLOW}{pct:.0f}%{RESET}{GRAY} — {have:,} of {total:,}{RESET}"
        else:
            detail = f"{GRAY}not started — {total:,} blocks{RESET}"
        label = camp + ("   (shared by every campaign)" if camp == "main" else "")
        rows.append((camp, label, detail))
    return rows


# ------------------------------------------------------------------ flows --

def pick_language(action: str) -> str:
    """Every language the game ships, not only the ones already extracted.

    Filtering to what has a corpus made the list two items long and left no way
    to reach the other eleven: you had to know to quit, run `extract`, and come
    back. The dead end was worse than the longer list, so all thirteen are shown
    and the missing corpus is offered here.
    """
    import jime

    rows = language_rows()
    default = next((i for i, r in enumerate(rows) if r[0] == "pt"), 0)
    while True:
        i = choose(f"Which language to {action}?",
                   [(r[1], r[2]) for r in rows], default)
        lang = rows[i][0]
        if jime.corpus_path(lang).exists():
            return lang

        name = jime.LANGUAGE_NAMES.get(lang, lang)
        print(f"\n{YELLOW}  {name} has not been extracted yet.{RESET} "
              f"{GRAY}It has to come out of your own\n  copy of the game before "
              f"anything can be said in it.{RESET}")
        if not confirm(f"Extract {name} now?", True):
            continue
        if _run(["extract", "--lang", lang]) != 0:
            continue
        rows = language_rows()
        return lang


def flow_render() -> list[str] | None:
    lang = pick_language("render")
    rows = campaign_rows(lang)
    if not rows:
        print(f"\n{RED}That corpus has no campaigns with narration.{RESET}")
        raise Abort

    extra = [("everything not yet rendered", "every campaign above, in order")]
    i = choose("Which campaign?", [(r[1], r[2]) for r in rows] + extra, None)

    if i == len(rows):
        pending = [r[0] for r in rows if "complete" not in r[2]]
        if not pending:
            print(f"\n{GREEN}Everything is already rendered for {lang}.{RESET}")
            return None
        campaigns = pending
    else:
        campaigns = [rows[i][0]]

    if "main" not in campaigns and any(c != "main" for c in campaigns):
        main_row = next((r for r in rows if r[0] == "main"), None)
        if main_row and "complete" not in main_row[2]:
            print(f"\n{YELLOW}  `main` is not fully rendered.{RESET} {GRAY}It holds the "
                  f"text every campaign shares — interface, tiles,\n  enemies, treasure "
                  f"— and 48.8% of what gets spoken comes from it.{RESET}")
            if confirm("Add it to this render?", True):
                campaigns.append("main")

    print()
    for camp in campaigns:
        _run(["render", "--lang", lang, "--campaign", camp, "--dry-run"])

    print()
    if not confirm("Start rendering?", True):
        raise Abort
    return ["render", "--lang", lang, "--campaign", campaigns[0]] if len(campaigns) == 1 \
        else ["__render_many__", lang, *campaigns]


def flow_play() -> list[str]:
    import narrator

    lang = pick_language("narrate")
    # `main` is the shared text, not something anybody plays. It belongs in the
    # render list and nowhere near this question.
    rows = [r for r in campaign_rows(lang) if r[0] != "main"]
    saved = None
    try:
        saved = narrator.current_campaign()
    except Exception:  # noqa: BLE001
        pass
    default = next((i for i, r in enumerate(rows) if r[0] == saved), None)
    if default is not None:
        rows[default] = (rows[default][0],
                         rows[default][1] + "   (your most recent save)",
                         rows[default][2])
    i = choose("Which campaign are you playing?",
               [(r[1], r[2]) for r in rows], default)
    campaign = rows[i][0]

    # Missing audio used to offer only "carry on anyway?", which is a dead end:
    # the answer you want is almost always to render it, and being told to quit
    # and come back is the thing this menu exists to avoid.
    if "complete" not in rows[i][2]:
        have = "partly rendered" if "not started" not in rows[i][2] else "no audio"
        print(f"\n{YELLOW}  {campaign} has {have}.{RESET} {GRAY}Screens will be "
              f"recognised and stay\n  silent, except the blocks synthesised "
              f"during play.{RESET}")
        missing = [campaign]
        main_row = next((r for r in campaign_rows(lang) if r[0] == "main"), None)
        if main_row and "complete" not in main_row[2]:
            missing.append("main")
        what = " and ".join(missing)
        pick = choose("What now?", [
            (f"Render {what} first",
             "about half an hour per campaign, then it plays"),
            ("Play anyway", "recognises the screens, speaks what it can"),
            ("Pick another campaign", ""),
        ], 0, allow_back=False)
        if pick == 0:
            for camp in missing:
                print(f"\n{BOLD}=== {camp} ==={RESET}")
                if _run(["render", "--lang", lang, "--campaign", camp]) != 0:
                    raise Abort
        elif pick == 2:
            raise Abort

    src = choose("How is the game running?", [
        ("fullscreen", "capture the display — the usual case"),
        ("in a window", "find it by window title"),
    ], 0)
    argv = ["play", "--lang", lang, "--campaign", campaign]
    if src == 0:
        argv += ["--display", "--wait", "15"]
    return argv


def flow_extract() -> list[str]:
    import jime

    rows = language_rows()
    default = next((i for i, r in enumerate(rows) if r[0] == "pt"), 0)
    i = choose("Which language to extract?", [(r[1], r[2]) for r in rows], default)
    lang = rows[i][0]
    if jime.corpus_path(lang).exists():
        if not confirm(f"A corpus for {lang} already exists. Extract again?", False):
            raise Abort
    return ["extract", "--lang", lang]


# ------------------------------------------------------------------- entry --

def _run(argv: list[str]) -> int:
    import jime

    parser = jime.build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


def banner() -> None:
    import jime

    langs = [r for r in language_rows() if "no corpus" not in r[2]]
    print(f"\n{BOLD}Journeys in Middle-earth — narrator{RESET}")
    if not langs:
        print(f"{GRAY}nothing extracted yet{RESET}")
        return
    parts = []
    for code, label, _ in langs:
        done = sum(rendered_by_campaign(code).values())
        parts.append(f"{code} ({done:,} blocks)" if done else f"{code} (no audio)")
    print(f"{GRAY}ready: {', '.join(parts)}{RESET}")


ACTIONS = [
    ("play", "Narrate a game", "watch the screen and read it aloud", flow_play),
    ("render", "Render audio", "corpus → speech, resumable", flow_render),
    ("extract", "Extract the corpus", "read the game's own files", flow_extract),
    ("status", "Status", "what is done and what is missing", None),
    ("doctor", "Check this machine", "is everything installed?", None),
    ("voices", "Voices", "which voice speaks each language", None),
]


def main() -> int:
    if not sys.stdin.isatty():
        print("jime: run `jime --help` for the flags; the menu needs a terminal.")
        return 1

    banner()
    while True:
        try:
            i = choose("What would you like to do?",
                       [(label, detail) for _, label, detail, _ in ACTIONS],
                       0, allow_back=False)
            name, _, _, flow = ACTIONS[i]
            argv = flow() if flow else [name]
            if argv is None:
                continue
            if argv[0] == "__render_many__":
                lang, campaigns = argv[1], argv[2:]
                for camp in campaigns:
                    print(f"\n{BOLD}=== {camp} ==={RESET}")
                    rc = _run(["render", "--lang", lang, "--campaign", camp])
                    if rc != 0:
                        return rc
            else:
                _run(argv)
        except Abort:
            continue
        except KeyboardInterrupt:
            print()
            return 130


if __name__ == "__main__":
    sys.exit(main())
