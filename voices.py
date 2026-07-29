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
import sys
import urllib.request
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

# Chosen by ear, then measured. Piper's own pace for faber is 3.23 words per
# second — 194 a minute, faster than anyone narrates — and the response to
# length_scale is not linear, so this is swept rather than computed.
#
# The target is ~160 wpm, the bottom of the commercial audiobook range. An
# earlier pass aimed at 2.14 w/s (130 wpm) to match the engine this replaced,
# and that was wrong twice over: it was the old engine's number, and it was
# heard as dragging. 1.35 was picked by listening to 1.00, 1.15, 1.25 and 1.35
# on 125 words of prose, which is where pace is felt — a three-second
# instruction does not reveal it.
#
# It is per *voice*: carrying one speaker's number to another is how a session
# ends up with one screen rushing and the next not.
CALIBRATION = {
    "pt_BR-faber-medium": 1.35,   # 2.68 w/s, 161 wpm
}

# Reading pace to aim for, per language. Only pt is measured.
TARGET_WPS = {"pt": 2.68}
DEFAULT_TARGET_WPS = 2.68


def _fetch(url: str) -> bytes:
    """Download, as bytes, with no external command.

    This used to shell out to curl with `text=True`, which decodes using the
    locale encoding. On Windows that is cp1252, the catalogue is UTF-8, and the
    reader thread died on the first non-ASCII byte — leaving stdout as None and
    the failure surfacing three frames away as AttributeError. Bytes in, decode
    where the encoding is known, and no dependency on a command being installed.
    """
    request = urllib.request.Request(url, headers={"User-Agent": "jime-narrador"})
    with urllib.request.urlopen(request, timeout=60) as response:
        return response.read()


def voice_path(name: str) -> Path:
    return VOICE_DIR / f"{name}.onnx"


def catalogue() -> dict:
    """Every voice Piper publishes, cached next to the models."""
    cached = VOICE_DIR / "catalogue.json"
    if cached.exists():
        return json.loads(cached.read_text(encoding="utf-8"))
    VOICE_DIR.mkdir(parents=True, exist_ok=True)
    raw = _fetch(CATALOGUE)
    cached.write_bytes(raw)
    return json.loads(raw.decode("utf-8"))


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


# One sentence per language, to hear a voice before committing a render to it.
#
# Written here rather than taken from the game: the repository publishes tools
# and never the content, and a sample shipped in git would be content. These are
# also better for the job than a random block would be — each one is built to
# make the language's hard sounds happen. The Portuguese has the nasals, the tap
# R in a cluster, and lh/nh, which is exactly where the word error rate
# measurement found this engine weakest.
#
# Only the Portuguese and English have been checked by someone who speaks them.
# The rest are offered as a starting point and should be corrected by a native
# speaker rather than trusted.
SAMPLE = {
    "pt": "Olhe: a estrada sobe pela montanha, e o vento traz cheiro de chuva.",
    "en": "The road climbs through the mountains, and the wind carries the "
          "smell of rain.",
    "es": "El camino sube por la montaña, y el viento trae olor a lluvia.",
    "fr": "La route grimpe à travers la montagne, et le vent apporte une odeur "
          "de pluie.",
    "it": "La strada sale attraverso la montagna, e il vento porta odore di "
          "pioggia.",
    "de": "Der Weg steigt durch die Berge, und der Wind bringt den Geruch von "
          "Regen.",
    "pl": "Droga wspina się przez góry, a wiatr niesie zapach deszczu.",
    "cz": "Cesta stoupá přes hory a vítr přináší vůni deště.",
    "ru": "Дорога поднимается через горы, и ветер приносит запах дождя.",
    "uk": "Дорога піднімається через гори, і вітер приносить запах дощу.",
    "hu": "Az út a hegyeken át vezet, és a szél esőszagot hoz.",
    "ko": "길은 산을 넘어 이어지고, 바람이 비 냄새를 실어 옵니다.",
    "zh": "道路穿过山峦，风中带着雨的气息。",
}


def audition(name: str, lang: str, wait: bool = True) -> bool:
    """Speak the sample sentence in this voice, now.

    Reads it the way the renderer would — same pace, same prosody pass — because
    a sample that skips them is not the voice you are choosing.

    Returns False when it could not be heard, rather than raising: failing to
    audition a voice must not stop you from picking one.
    """
    import subprocess
    import tempfile
    import wave

    try:
        import prosody
        from piper import PiperVoice, SynthesisConfig
        from player import _play_command

        path = ensure(name)
        voice = PiperVoice.load(str(path))
        cfg = SynthesisConfig(length_scale=length_scale(name, lang, quiet=True),
                              noise_scale=0.9, noise_w_scale=1.0)
        text = SAMPLE.get(lang) or SAMPLE["en"]
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as fh:
            tmp = Path(fh.name)
        prosody.synthesize(voice, text, cfg.length_scale, tmp, cfg)
        run = subprocess.run(_play_command(tmp),
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        tmp.unlink(missing_ok=True)
        return run.returncode == 0
    except Exception:  # noqa: BLE001
        return False


CHOSEN = VOICE_DIR / "chosen.json"


def chosen(lang: str) -> str | None:
    """The voice this machine was told to use for a language, if any.

    Kept beside the models rather than in the repository: it is a property of an
    installation, like which languages have been downloaded, and two people
    playing in the same language may well want different readers.
    """
    if not CHOSEN.exists():
        return None
    try:
        return json.loads(CHOSEN.read_text(encoding="utf-8")).get(lang)
    except Exception:  # noqa: BLE001
        return None


def choose(lang: str, name: str | None) -> None:
    """Remember a voice for this language, or forget it when `name` is None."""
    data = {}
    if CHOSEN.exists():
        try:
            data = json.loads(CHOSEN.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            data = {}
    if name:
        data[lang] = name
    else:
        data.pop(lang, None)
    CHOSEN.parent.mkdir(parents=True, exist_ok=True)
    CHOSEN.write_text(json.dumps(data, indent=1, ensure_ascii=False),
                      encoding="utf-8")


def resolve(lang: str, override: str | None = None) -> str:
    """The voice name to use, checked against the catalogue.

    The names above are written by hand, and a locale prefix is easy to get
    wrong — `en_US-alan-medium` and `ko_KO-kss-medium` were both wrong on the
    first pass, and both would have surfaced as a download failure much later.
    Checking here turns that into a message naming the real candidates.
    """
    name = override or chosen(lang) or DEFAULT_VOICE.get(lang)
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
        try:
            dest.write_bytes(_fetch(f"{BASE}/{remote}"))
        except Exception as exc:  # noqa: BLE001
            dest.unlink(missing_ok=True)
            raise RuntimeError(f"download failed for {remote}: {exc}") from exc
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
