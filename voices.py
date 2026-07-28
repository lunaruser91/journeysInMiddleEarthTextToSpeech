#!/usr/bin/env python3
"""
voices.py — which voice speaks each language, and how to get it.

The game ships thirteen localisations. All thirteen have a Piper voice, so the
narrator has no text-only languages: whatever you can extract, you can hear.
That was not true before — the previous engine covered ten, leaving Czech,
Hungarian and Ukrainian readable but silent.

## Choosing a default

The defaults below lean male where the speaker is identifiable, because the
project's framing is an old wizard reading aloud. That is a guess for every
language except Portuguese, which was picked by listening to all four
candidates. Treat the rest as a starting point and override with `--voice`;
`jime voices --lang de` lists the alternatives.

## Pace, and why it is stored per voice

Piper speaks faster than a narrator should. Left alone, `pt_BR-faber-medium`
runs at 3.4 words per second, well above the audiobook range this project aims
at. `length_scale` slows it down, and the response is **not
linear**, so the value is swept per voice rather than computed.

It is also per *voice*, not per language or per engine: carrying one speaker's
number to another is how a session ends up with one screen rushing and the next
not. A voice with no measured entry says so rather than borrowing a number from
a different speaker.

Words per second is a poor target across languages — German compounds and
Chinese characters do not count the same way — so `TARGET_WPS` is per language
too, and only Portuguese is measured. Calibrate with:

    jime voices --calibrate --lang de
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
VOICE_DIR = ROOT / "voices"
CATALOGUE = "https://huggingface.co/rhasspy/piper-voices/resolve/main/voices.json"
BASE = "https://huggingface.co/rhasspy/piper-voices/resolve/main"

# The game's language codes are not always Piper's. Only Czech differs.
PIPER_CODE = {"cz": "cs"}

# One default per language. `jime voices --lang X` shows what else exists.
DEFAULT_VOICE = {
    "cz": "cs_CZ-jirka-medium",
    "de": "de_DE-thorsten-medium",
    "en": "en_GB-alan-medium",
    "es": "es_ES-davefx-medium",
    "fr": "fr_FR-tom-medium",
    "hu": "hu_HU-imre-medium",
    "it": "it_IT-paola-medium",
    "ko": "ko_KR-kss-medium",
    "pl": "pl_PL-darkman-medium",
    "pt": "pt_BR-faber-medium",
    "ru": "ru_RU-ruslan-medium",
    "uk": "uk_UA-ukrainian_tts-medium",
    "zh": "zh_CN-huayan-medium",
}

# Measured, not guessed. See the module docstring: swept until the median
# matched, per voice, because the response to length_scale is not linear.
CALIBRATION = {
    "pt_BR-faber-medium": 1.61,   # measured 2.17 w/s on 40 blocks
    "pt_BR-cadu-medium": 1.25,    # measured 2.10 w/s on the same 40
    "en_GB-alan-medium": 1.32,    # measured 2.08 w/s on 25 blocks
}

# Reading pace to aim for, per language. Only pt is measured; the rest inherit
# it, which is a guess that the calibrate command exists to replace.
TARGET_WPS = {"pt": 2.14}
DEFAULT_TARGET_WPS = 2.14


def voice_path(name: str) -> Path:
    return VOICE_DIR / f"{name}.onnx"


def catalogue() -> dict:
    """Every voice Piper publishes, cached next to the models."""
    cached = VOICE_DIR / "catalogue.json"
    if cached.exists():
        return json.loads(cached.read_text(encoding="utf-8"))
    VOICE_DIR.mkdir(parents=True, exist_ok=True)
    out = subprocess.run(["curl", "-sL", CATALOGUE], capture_output=True, text=True)
    if out.returncode != 0 or not out.stdout.strip():
        raise RuntimeError("could not fetch the Piper voice catalogue; are you online?")
    cached.write_text(out.stdout, encoding="utf-8")
    return json.loads(out.stdout)


def for_language(lang: str) -> list[dict]:
    """Voices available for a game language, best quality first."""
    code = PIPER_CODE.get(lang, lang)
    rank = {"high": 0, "medium": 1, "low": 2, "x_low": 3}
    found = [
        {"name": name,
         "quality": meta["quality"],
         "speaker": name.split("-")[1],
         "mb": round(sum(f["size_bytes"] for f in meta["files"].values()) / 1e6),
         "installed": voice_path(name).exists()}
        for name, meta in catalogue().items()
        if meta["language"]["family"] == code
    ]
    found.sort(key=lambda v: (rank.get(v["quality"], 9), v["name"]))
    return found


def resolve(lang: str, override: str | None = None) -> str:
    """The voice name to use, checked against the catalogue.

    The names above are written by hand, and a locale prefix is easy to get
    wrong — `en_US-alan-medium` and `ko_KO-kss-medium` were both wrong on the
    first pass, and both would have surfaced as a download failure much later.
    Checking here turns that into a message naming the real candidates.
    """
    name = override or DEFAULT_VOICE.get(lang)
    if name is None:
        raise RuntimeError(
            f"no default voice for {lang!r}. Pick one with --voice; "
            f"`jime voices --lang {lang}` lists them.")
    if name.endswith(".onnx"):
        name = Path(name).stem
    if voice_path(name).exists():
        return name                      # already downloaded, catalogue not needed
    known = catalogue()
    if name not in known:
        speaker = name.split("-")[1] if "-" in name else name
        near = [n for n in known if speaker in n][:4]
        raise RuntimeError(
            f"no Piper voice called {name!r}."
            + (f" Did you mean: {', '.join(near)}?" if near else "")
            + f"\n`jime voices --lang {lang}` lists what exists.")
    return name


def ensure(name: str, quiet: bool = False) -> Path:
    """The model file, downloading it the first time.

    ~60 MB per voice, from huggingface.co/rhasspy/piper-voices — the same place
    Piper's own tooling fetches them.
    """
    onnx = voice_path(name)
    if onnx.exists() and onnx.with_suffix(".onnx.json").exists():
        return onnx

    meta = catalogue().get(name)
    if meta is None:
        raise RuntimeError(f"unknown voice {name!r}. `jime voices` lists what exists.")
    VOICE_DIR.mkdir(parents=True, exist_ok=True)
    total = round(sum(f["size_bytes"] for f in meta["files"].values()) / 1e6)
    if not quiet:
        print(f"[voice] fetching {name} ({total} MB) from "
              f"huggingface.co/rhasspy/piper-voices", flush=True)

    for remote in meta["files"]:
        if not remote.endswith((".onnx", ".onnx.json")):
            continue
        dest = VOICE_DIR / Path(remote).name
        rc = subprocess.run(["curl", "-sL", "--fail", "-o", str(dest),
                             f"{BASE}/{remote}"]).returncode
        if rc != 0:
            dest.unlink(missing_ok=True)
            raise RuntimeError(f"download failed for {remote}")
    if not onnx.exists():
        raise RuntimeError(f"{name} downloaded but {onnx.name} is missing")
    return onnx


def length_scale(name: str, lang: str = "pt", quiet: bool = False) -> float:
    """Pace for this voice, or a warned-about fallback."""
    if name in CALIBRATION:
        return CALIBRATION[name]
    if not quiet:
        print(f"[warning] {name} has no measured pace, using 1.0. It will not "
              f"match the calibrated voices.\n"
              f"          Measure it with: jime voices --calibrate --lang {lang}",
              file=sys.stderr)
    return 1.0
