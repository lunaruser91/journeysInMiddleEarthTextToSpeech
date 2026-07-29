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

import console  # noqa: E402
from i18n import NATIVE_NAME, system_language, t  # noqa: E402

console.setup()

# The language chosen at startup, so every helper can translate without it
# being threaded through every call. Set once by main().
UI = "en"

BOLD, GREEN, YELLOW, RED, GRAY, RESET = (
    "\033[1m", "\033[92m", "\033[93m", "\033[91m", "\033[90m", "\033[0m")


class Abort(Exception):
    """The user asked to go back or quit."""


# --------------------------------------------------------------- questions --

def _width(text: str) -> int:
    """How many terminal columns this takes, not how many characters it has.

    한국어 and 中文 occupy two columns each, so padding by len() leaves those rows
    short and the detail column ragged. Only noticeable once the language list
    started showing endonyms, which is when it started mattering.
    """
    import unicodedata

    return sum(2 if unicodedata.east_asian_width(c) in ("W", "F") else 1
               for c in text)


def choose(title: str, rows: list[tuple[str, str]], default: int | None = None,
           allow_back: bool = True) -> int:
    """Numbered pick. Returns the index; raises Abort for back/quit.

    `rows` is (label, detail); the detail is what makes the choice informed —
    how much is rendered, whether a corpus exists — and is printed dimmed beside
    the label.
    """
    print(f"\n{BOLD}{title}{RESET}")
    width = max((_width(label) for label, _ in rows), default=0)
    for i, (label, detail) in enumerate(rows, 1):
        mark = f"{GREEN}›{RESET}" if default == i - 1 else " "
        # Only dim a detail that has no colour of its own; wrapping one that
        # does nests the escapes and the reset in the middle ends the dimming
        # early, which looked like a rendering bug.
        shown = detail if "\033[" in detail else f"{GRAY}{detail}{RESET}"
        pad = " " * (width - _width(label))
        print(f"  {mark} {i:>2}. {label}{pad}  {shown}")
    hint = (f"{t('enter', UI)} = " + rows[default][0] if default is not None
            else "1-%d" % len(rows))
    tail = f", b = {t('back', UI)}" if allow_back else ""
    while True:
        try:
            raw = input(f"{GRAY}  [{hint}{tail}, q = {t('quit', UI)}] "
                        f"{RESET}").strip().lower()
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
        print(f"{YELLOW}  "
              f"{t('pick a number between 1 and {n}', UI, n=len(rows))}{RESET}")


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


def language_rows() -> list[tuple[str, str, str, bool]]:
    """(code, label, detail, has_corpus) for every language the game ships.

    `has_corpus` for the same reason campaign_rows carries a state: reading it
    back out of `detail` breaks the moment `detail` is translated.
    """
    import jime

    rows = []
    for code in jime.GAME_LANGUAGES:
        name = jime.LANGUAGE_NAMES.get(code, code)
        corpus = jime.corpus_path(code)
        has = corpus.exists()
        if not has:
            detail = t("no corpus yet — extract first", UI)
        else:
            done = sum(rendered_by_campaign(code).values())
            detail = (t("corpus ready, {n} blocks rendered", UI, n=f"{done:,}")
                      if done else t("corpus ready", UI))
        rows.append((code, f"{code}  {NATIVE_NAME.get(code, name)}", detail, has))
    return rows


def campaign_rows(lang: str) -> list[tuple[str, str, str, str]]:
    """(campaign, label, progress, state).

    `state` is "complete", "partial" or "none" — a value, not something to be
    read back out of `progress`. The first version had callers testing whether
    the word "complete" appeared in the progress text, which worked until the
    interface was translated and that text started saying "completo": a fully
    rendered campaign was then announced as partly rendered. Display strings are
    for display.
    """
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
            state = "complete"
            detail = (f"{GREEN}{t('complete', UI)}{RESET}{GRAY} — "
                      f"{t('{n} blocks', UI, n=f'{total:,}')}{RESET}")
        elif have:
            state = "partial"
            detail = (f"{YELLOW}{pct:.0f}%{RESET}{GRAY} — "
                      f"{t('{done} of {total}', UI, done=f'{have:,}', total=f'{total:,}')}{RESET}")
        else:
            state = "none"
            detail = (f"{GRAY}{t('not started', UI)} — "
                      f"{t('{n} blocks', UI, n=f'{total:,}')}{RESET}")
        label = camp + (f"   {t('(shared by every campaign)', UI)}"
                        if camp == "main" else "")
        rows.append((camp, label, detail, state))
    return rows


# ------------------------------------------------------------------ flows --

def pick_language(action: str = "use", current: str | None = None,
                  first: bool = False) -> str:
    """Every language the game ships, not only the ones already extracted.

    `first` marks the very first question of the session, where there is nothing
    to go back to. Offering `b` there advertised a key that raised Abort straight
    through main() and out: the program answered a request to go back with a
    traceback.

    Filtering to what has a corpus made the list two items long and left no way
    to reach the other eleven: you had to know to quit, run `extract`, and come
    back. The dead end was worse than the longer list, so all thirteen are shown
    and the missing corpus is offered here.
    """
    import jime

    rows = language_rows()
    default = next((i for i, r in enumerate(rows) if r[0] == (current or "pt")), 0)
    while True:
        i = choose(t("Which language to work in?", UI),
                   [(r[1], r[2]) for r in rows], default,
                   allow_back=not first)
        lang = rows[i][0]
        if jime.corpus_path(lang).exists():
            return lang

        name = jime.LANGUAGE_NAMES.get(lang, lang)
        print(f"\n{YELLOW}  "
              f"{t('{name} has not been extracted yet. It has to come out of your own', UI, name=name)}"
              f"{RESET}\n{GRAY}  "
              f"{t('copy of the game before anything can be said in it.', UI)}{RESET}")
        if not confirm(t("Extract {name} now?", UI, name=name), True):
            continue
        if _run(["extract", "--lang", lang]) != 0:
            continue
        rows = language_rows()
        return lang


def flow_play(lang: str) -> list[str]:
    import narrator

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
                         rows[default][1] + f"   {t('(your most recent save)', UI)}",
                         rows[default][2], rows[default][3])
    i = choose(t("Which campaign are you playing?", UI),
               [(r[1], r[2]) for r in rows], default)
    campaign = rows[i][0]

    # Missing audio used to offer only "carry on anyway?", which is a dead end:
    # the answer you want is almost always to render it, and being told to quit
    # and come back is the thing this menu exists to avoid.
    if rows[i][3] != "complete":
        partial = rows[i][3] == "partial"
        head = (t("{campaign} has partly rendered.", UI, campaign=campaign) if partial
                else t("{campaign} has no audio.", UI, campaign=campaign))
        print(f"\n{YELLOW}  {head}{RESET} "
              f"{GRAY}{t('Screens will be recognised and stay', UI)}\n  "
              f"{t('silent, except the blocks synthesised during play.', UI)}{RESET}")
        missing = [campaign]
        main_row = next((r for r in campaign_rows(lang) if r[0] == "main"), None)
        if main_row and main_row[3] != "complete":
            missing.append("main")
        what = " and ".join(missing)
        pick = choose(t("What now?", UI), [
            (t("Render {what} first", UI, what=what),
             t("about half an hour per campaign, then it plays", UI)),
            (t("Play anyway", UI),
             t("recognises the screens, speaks what it can", UI)),
            (t("Pick another campaign", UI), ""),
        ], 0, allow_back=False)
        if pick == 0:
            for camp in missing:
                print(f"\n{BOLD}=== {camp} ==={RESET}")
                if _run(["render", "--lang", lang, "--campaign", camp]) != 0:
                    raise Abort
        elif pick == 2:
            raise Abort

    # Both platforms need this question, for different reasons, and assuming
    # otherwise cost a session.
    #
    # macOS: a fullscreen game gets a Space of its own and macOS does not draw an
    # inactive Space, so its window is unreachable from the terminal — the
    # display is the only way in.
    #
    # Windows: a game in *exclusive* fullscreen bypasses the compositor
    # altogether, and Windows.Graphics.Capture only sees what the compositor
    # draws. Reported from play: frames arrived only on alt-tab, which is the
    # moment the game drops back into composition. Capturing the display gets
    # around it; so does setting the game to borderless windowed, which is the
    # better fix when the game offers it.
    argv = ["play", "--lang", lang, "--campaign", campaign]
    src = choose(t("How is the game running?", UI), [
        (t("fullscreen", UI), t("capture the display — the usual case", UI)),
        (t("in a window", UI), t("find it by window title", UI)),
    ], 0)
    # 15 seconds used to be a countdown, and a guess about how fast someone can
    # alt-tab: when it guessed short, watching began on the desktop. The wait now
    # ends the moment the game is the window in front, so this is only the
    # timeout, and a generous one costs nothing.
    return argv + (["--display", "--wait", "60"] if src == 0 else ["--wait", "60"])


# ------------------------------------------------------------------- entry --

def _run(argv: list[str]) -> int:
    import jime

    parser = jime.build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


def banner() -> None:
    import jime

    langs = [r for r in language_rows() if r[3]]
    print(f"\n{BOLD}Journeys in Middle-earth — narrator{RESET}")
    if not langs:
        print(f"{GRAY}{t('nothing extracted yet', UI)}{RESET}")
        return
    parts = []
    for code, label, _, _ in langs:
        done = sum(rendered_by_campaign(code).values())
        parts.append(f"{code} ({t('{n} blocks', UI, n=f'{done:,}')})" if done
                     else f"{code} ({t('no audio', UI)})")
    print(f"{GRAY}{t('ready: {what}', UI, what=', '.join(parts))}{RESET}")


# (subcommand, label, detail, flow, takes_lang). `status` and `doctor` describe
# the whole installation and have no --lang; passing one is an argparse error.
def flow_voices(lang: str) -> list[str] | None:
    """Pick the voice for this language, and say what picking one costs.

    Listing was all this option did, which made it a dead end: a catalogue of
    forty readers and no way to act on it. Choosing is the point of looking.

    The cost belongs at the moment of choosing, because it is large and not
    obvious. Voice is part of the render's cache key — it has to be, or two
    recipes end up mixed inside one session — so a swap re-renders every block
    already done. And pace is per voice: the response to `length_scale` is not
    linear, so a reader whose pace nobody has measured speaks at whatever speed
    it was trained at.
    """
    import voices as V

    try:
        found = V.for_language(lang)
    except Exception as exc:  # noqa: BLE001
        print(f"\n{YELLOW}  {exc}{RESET}")
        raise Abort from None
    if not found:
        print(f"\n{YELLOW}  {t('no voice for this language', UI)}{RESET}")
        raise Abort

    now = V.resolve(lang)
    rows, names = [], []
    for v in found:
        marks = [v["quality"], f"{v['mb']} MB"]
        if v["name"] == now:
            marks.append(f"{GREEN}{t('in use', UI)}{RESET}")
        if v["name"] in V.CALIBRATION:
            marks.append(t("pace measured", UI))
        elif v["installed"]:
            marks.append(t("downloaded", UI))
        names.append(v["name"])
        rows.append((v["name"], "  ".join(marks)))

    default = names.index(now) if now in names else 0
    pick = names[choose(t("Which voice should read?", UI), rows, default)]
    if pick == now:
        return None

    if pick not in V.CALIBRATION:
        print(f"\n{YELLOW}  {t('{name} has no measured pace.', UI, name=pick)}{RESET}")
        print(f"{GRAY}  {t('It reads at its own speed until measured:', UI)}{RESET}")
        print(f"{GRAY}    jime voices --calibrate --lang {lang}{RESET}")

    done = sum(rendered_by_campaign(lang).values())
    if done:
        print(f"\n{YELLOW}  "
              f"{t('{n} blocks are rendered with the voice in use.', UI, n=f'{done:,}')}"
              f"{RESET}")
        print(f"{GRAY}  {t('Changing it renders every one of them again.', UI)}{RESET}")

    if not confirm(t("Use {name}?", UI, name=pick), False):
        return None
    V.choose(lang, pick)
    print(f"{GREEN}  {t('{name} it is.', UI, name=pick)}{RESET}")
    return None


# Extracting and rendering are not offered here, because narrating already asks.
# `pick_language` runs before every action and offers to extract a language that
# has no corpus; `flow_play` notices a campaign with no audio, offers to render
# it, and adds `main` to the job without being asked. Listing them again as
# separate errands made the first screen look like a four-step procedure when it
# is one.
#
# Status went with them. Every question already carries the state behind it —
# which languages have a corpus, how far each campaign is rendered — so the
# figures are in front of whoever is about to decide something with them, which
# is the only place they are worth reading. `jime status` is still there for a
# terminal.
ACTIONS = [
    ("play", "Narrate a game", "watch the screen and read it aloud", flow_play, True),
    ("doctor", "Check this machine", "is everything installed?", None, False),
    ("voices", "Voices", "which voice reads, and change it", flow_voices, True),
]


def main() -> int:
    # The interface follows the same choice. Someone who picks Portuguese and
    # then reads an English menu has a fair complaint, even though the question
    # is about the game's text rather than the interface — in practice they are
    # the same person's language.
    global UI

    import jime

    if not sys.stdin.isatty():
        print(t("jime: run `jime --help` for the flags; the menu needs a terminal.",
                UI))
        return 1

    # The first screen has to be drawn before anyone has chosen, so it guesses
    # from the operating system. Wrong is harmless — it is a list of languages,
    # and picking one sets everything after it.
    UI = system_language(set(jime.GAME_LANGUAGES)) or "en"

    banner()
    # Language is asked once, first, and then carried. Asking it inside every
    # action meant answering the same question before each one, and it is the
    # rarest thing to change: most people extract one language and stay there.
    lang = pick_language("work in", first=True)
    UI = lang

    while True:
        name = NATIVE_NAME.get(lang, jime.LANGUAGE_NAMES.get(lang, lang))
        options = [(t(label, UI), t(detail, UI))
                   for _, label, detail, _, _ in ACTIONS]
        options.append((t("Change language", UI),
                        t("currently {name}", UI, name=name)))
        try:
            i = choose(f"{t('What would you like to do?', UI)}  "
                       f"{GRAY}[{name}]{RESET}",
                       options, 0, allow_back=False)
            if i == len(ACTIONS):
                lang = pick_language("work in", lang)
                UI = lang
                continue

            key, _, _, flow, takes_lang = ACTIONS[i]
            argv = flow(lang) if flow else ([key, "--lang", lang] if takes_lang
                                            else [key])
            if argv is None:
                continue
            if argv[0] == "__render_many__":
                for camp in argv[2:]:
                    print(f"\n{BOLD}=== {camp} ==={RESET}")
                    if _run(["render", "--lang", argv[1], "--campaign", camp]) != 0:
                        break
            else:
                _run(argv)
        except Abort:
            continue
        except KeyboardInterrupt:
            print()
            return 130


if __name__ == "__main__":
    sys.exit(main())
