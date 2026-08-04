#!/usr/bin/env python3
"""
test_voice_ab.py — two engines, the same blocks, and something to listen to.

    ~/jime-tts-lab/bin/python test_voice_ab.py --lang pt
    ~/jime-tts-lab/bin/python test_voice_ab.py --lang pt --ref voz.wav
    ~/jime-tts-lab/bin/python test_voice_ab.py --engines piper --blocks 10

## What this is for

A second rendering mode — "with action", an expressive engine on a GPU beside
the plain one — is worth building only if the difference is worth its cost. This
renders the same blocks through both and reports the cost, so the listening is
the only thing left to decide.

The cost is already known to be large. Chatterbox measured **RTF 3.7** on this
Mac's MPS against Piper's 0.029: 53 hours for `main` plus one campaign, against
22 minutes. It also wanted 3 GB of model against 60 MB, a reference recording,
and covered ten of the game's thirteen languages instead of all of them. That is
the measurement that removed it from the project in July, recorded in
[PHASE2-MEASUREMENTS](docs/PHASE2-MEASUREMENTS.md) §6c.

None of that says it sounds worse. It sounded better — the note kept at the top
of that document says so plainly: "Piper has clear diction and flat prosody; it
reads, it does not act." This harness exists because "sounds better" was never
weighed against "53 hours" by anybody actually listening to both.

## Install it beside the project, not into it

The project's venv is 60 MB of model and no GPU, and that is a promise its
README makes. Chatterbox brings torch. So:

    python3 -m venv ~/jime-tts-lab
    ~/jime-tts-lab/bin/pip install piper-tts chatterbox-tts
    ~/jime-tts-lab/bin/python test_voice_ab.py --lang pt

Both engines in one interpreter, none of it in `~/jime-venv`.

## The trap this is written around

`legacy/render_piper.py` had two defects and only one was known. The second:
it synthesized `v["text"]`, the raw block, so the whole glyph and number layer
was bypassed — icons reached the tokenizer as nothing and digits were read in
whatever language the model felt like, which is where "uno" for "1" came from.

This calls `prepare_speech()` from the real renderer and speaks `v["speech"]`,
the same string `phase2_render.py` speaks. An A/B where one side is fed
different text is not an A/B.

## What it does not do

It does not judge. It reports seconds, real-time factor and failures, and leaves
two files per block side by side. Whether the acting is worth the wait is not a
number, and pretending otherwise would be the third time this project mistook a
statistic for the thing it stood for.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
import wave
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

import console  # noqa: E402

console.setup()

GREEN, YELLOW, RED, GRAY, BOLD, RESET = (
    "\033[92m", "\033[93m", "\033[91m", "\033[90m", "\033[1m", "\033[0m")

# The parameters the July measurement used, kept so a comparison against it is a
# comparison and not a new experiment.
CHATTERBOX = {"exaggeration": 0.45, "cfg_weight": 0.35}
SEED = 1234


def duration(path: Path) -> float:
    """Seconds of audio in a wav, or 0 if it is not readable as one."""
    try:
        with wave.open(str(path), "rb") as w:
            return w.getnframes() / float(w.getframerate())
    except Exception:  # noqa: BLE001
        return 0.0


def blocks_for(lang: str, count: int) -> list[tuple[str, dict]]:
    """The first N narration blocks, with `speech` attached the renderer's way."""
    import phase2_render as P

    import jime

    path = jime.corpus_path(lang)
    if not Path(path).exists():
        raise SystemExit(f"{RED}no corpus for {lang!r}{RESET} — extract it first")
    corpus = json.loads(Path(path).read_text(encoding="utf-8"))
    # The same call the renderer makes, for the same reason: icons become words
    # and digits become words, in this language, before anything is spoken.
    P.prepare_speech(Path(path), corpus, lang)
    out = [(k, v) for k, v in corpus.items()
           if v.get("narration") and v.get("speech")
           and not v.get("placeholders")]
    return out[:count]


def render_piper(items, out: Path, lang: str) -> dict:
    """The engine the project ships, through the pass the project ships."""
    import prosody
    import voices as V
    from piper import PiperVoice, SynthesisConfig

    out.mkdir(parents=True, exist_ok=True)
    name = V.resolve(lang)
    voice = PiperVoice.load(str(V.ensure(name)))
    scale = V.length_scale(name, lang, quiet=True)
    cfg = SynthesisConfig(length_scale=scale, noise_scale=0.9, noise_w_scale=1.0)
    print(f"{GRAY}  piper: {name}, length_scale {scale}{RESET}")

    t0, spoke, failed = time.monotonic(), 0.0, 0
    for i, (key, v) in enumerate(items):
        dest = out / f"{i:02d}.wav"
        try:
            prosody.synthesize(voice, v["speech"], scale, dest, cfg)
            spoke += duration(dest)
        except Exception as exc:  # noqa: BLE001
            failed += 1
            print(f"    {RED}{key}{RESET} {type(exc).__name__}")
    return {"wall": time.monotonic() - t0, "audio": spoke, "failed": failed}


def render_chatterbox(items, out: Path, ref: Path | None) -> dict:
    """The expressive one, at the parameters July measured it with."""
    try:
        import torch
        from chatterbox.tts import ChatterboxTTS
    except ImportError as exc:
        raise SystemExit(
            f"{RED}{exc.name} is not in this interpreter{RESET} "
            f"({sys.executable}).\n"
            f"{GRAY}This harness wants both engines in one venv, beside the "
            f"project rather than inside it:{RESET}\n\n"
            f"  python3 -m venv ~/jime-tts-lab\n"
            f"  ~/jime-tts-lab/bin/pip install piper-tts chatterbox-tts\n")

    out.mkdir(parents=True, exist_ok=True)
    device = ("mps" if torch.backends.mps.is_available()
              else "cuda" if torch.cuda.is_available() else "cpu")
    # Worth saying out loud rather than discovering from the clock: on CPU this
    # is not slow, it is unusable, and the number at the end will say so.
    print(f"{GRAY}  chatterbox: device {device}"
          + (f", reference {ref.name}" if ref else ", no reference — default voice")
          + f"{RESET}")
    if device == "cpu":
        print(f"  {YELLOW}no GPU here. The July measurement was RTF 3.7 on MPS; "
              f"CPU will be worse.{RESET}")

    torch.manual_seed(SEED)
    model = ChatterboxTTS.from_pretrained(device=device)

    t0, spoke, failed = time.monotonic(), 0.0, 0
    for i, (key, v) in enumerate(items):
        dest = out / f"{i:02d}.wav"
        try:
            kw = dict(CHATTERBOX)
            if ref:
                kw["audio_prompt_path"] = str(ref)
            wav = model.generate(v["speech"], **kw)
            import torchaudio
            torchaudio.save(str(dest), wav, model.sr)
            spoke += duration(dest)
        except Exception as exc:  # noqa: BLE001
            failed += 1
            print(f"    {RED}{key}{RESET} {type(exc).__name__}: "
                  f"{str(exc).splitlines()[0][:70]}")
    return {"wall": time.monotonic() - t0, "audio": spoke, "failed": failed}


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--lang", default="pt")
    ap.add_argument("--blocks", type=int, default=25)
    ap.add_argument("--engines", default="both",
                    choices=("both", "piper", "chatterbox"))
    ap.add_argument("--ref", type=Path,
                    help="a few seconds of speech for Chatterbox to imitate. "
                         "Without one it uses its default voice, which is a "
                         "different comparison — say which you ran")
    ap.add_argument("--out", type=Path, default=ROOT / "output" / "ab",
                    help="where the two folders of wavs go")
    args = ap.parse_args()

    if args.ref and not args.ref.exists():
        return int(bool(print(f"{RED}no such file{RESET} {args.ref}")))

    items = blocks_for(args.lang, args.blocks)
    words = sum(v.get("words", len(v["speech"].split())) for _, v in items)
    print(f"{BOLD}{len(items)} blocks{RESET}, {words:,} words, language "
          f"{args.lang!r}\n")

    want = (["piper", "chatterbox"] if args.engines == "both"
            else [args.engines])
    results = {}
    for name in want:
        print(f"{BOLD}{name}{RESET}")
        try:
            if name == "piper":
                results[name] = render_piper(items, args.out / "piper", args.lang)
            else:
                results[name] = render_chatterbox(items, args.out / "chatterbox",
                                                  args.ref)
        except SystemExit as exc:
            print(exc)
            continue

    if not results:
        return 1

    print(f"\n  {'engine':12} {'wall':>9} {'audio':>9} {'RTF':>8} {'failed':>7}")
    print("  " + "-" * 48)
    for name, r in results.items():
        rtf = r["wall"] / r["audio"] if r["audio"] else float("inf")
        colour = GREEN if rtf < 0.2 else YELLOW if rtf < 1 else RED
        print(f"  {name:12} {r['wall']:8.1f}s {r['audio']:8.1f}s "
              f"{colour}{rtf:8.3f}{RESET} {r['failed']:7}")

    if len(results) == 2:
        a, b = results["piper"], results["chatterbox"]
        if a["wall"]:
            times = b["wall"] / a["wall"]
            # The number that matters is not this ratio, it is what the ratio
            # costs over the whole corpus. 9,814 narration blocks.
            whole = b["wall"] / len(items) * 9814 / 3600
            print(f"\n{GRAY}Chatterbox is {times:.0f}x the wall clock here. "
                  f"Over all 9,814 narration blocks that is\n{whole:.0f} hours "
                  f"against Piper's {a['wall'] / len(items) * 9814 / 3600:.1f}. "
                  f"July measured 53 h against 43 min on the same\ncomparison, "
                  f"so a number far from that is worth explaining before it is "
                  f"trusted.{RESET}")

    print(f"\n{BOLD}Now listen.{RESET} Same block, both engines, side by side:\n")
    print(f"  for i in 00 05 10; do")
    print(f"    ffplay -nodisp -autoexit {args.out}/piper/$i.wav")
    print(f"    ffplay -nodisp -autoexit {args.out}/chatterbox/$i.wav")
    print(f"  done")
    print(f"\n{GRAY}The question the numbers cannot answer: is the difference "
          f"worth the hours above,\nfor a voice that reads a board game aloud "
          f"between turns.{RESET}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
