#!/usr/bin/env python3
"""
phase2_render_piper.py — the same corpus, rendered with Piper instead of Chatterbox.

Piper is a small ONNX text-to-speech model. It runs on the CPU, needs no GPU, and
is orders of magnitude faster than an autoregressive model — which is the entire
reason it is here. Chatterbox measured RTF 3.7 on this machine, so a campaign plus
the shared `main` blocks is about 50 hours. Piper turns that into minutes.

What you give up is expressiveness. Piper has clear diction and flat prosody; it
does not act. That trade is worth making for the mechanical half of the corpus —
UI text, enemy activations, "suffer 2 fear" — where the player wants to be told
what to do, not to be told a story. Keep Chatterbox for the narrative prose.

## What was wrong with the old one

`legacy/render_piper.py` could not render a single block on this machine:

1. Its DSP chain named `rubberband` unconditionally, and rubberband is not built
   into this ffmpeg. Every block failed at the ffmpeg call, with check=True. This
   one shares `wizard_chain()` with the Chatterbox renderer, which already falls
   back to the asetrate trick.
2. It synthesized `v["text"]` — the raw screen text. That silently skipped the
   whole glyph and number layer: private-use icons went to the tokenizer as
   nothing, and digits were read in the model's default language. This one runs
   `prepare_speech` and synthesizes `v["speech"]`, exactly as Chatterbox does.
3. Its manifest entries had no `wps`, so `check_pace.py` could not audit the
   result.

## Interchangeable output

The manifest format, the cache key and the DSP chain match the Chatterbox
renderer, so `player.py` and `narrator.py` read one the same as the other. Render
`main` here and the campaigns there, point the player at both, and it will not
know the difference — beyond the voice.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
import time
import wave
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import phase2_render as P  # noqa: E402

VOICE_DIR = Path(__file__).resolve().parent / "voices"
DEFAULT_VOICE = VOICE_DIR / "pt_BR-faber-medium.onnx"

# Piper's own pacing knob: higher is slower. Kept separate from the DSP speed
# because stretching audio after the fact and speaking slower are not the same
# thing — the first smears transients, the second is free.
#
# **It is per voice, and the response is not linear.** Each of these was swept
# until its median words-per-second matched Chatterbox's 2.17 on the same 40
# blocks, because the two engines are meant to be mixed inside one session: a
# screen rendered by one and the next by the other should differ in voice, not
# in pace. Carrying one voice's number over to another is how that breaks —
# faber at cadu's 1.63 runs at 2.71 w/s, a quarter too fast.
#
#   voice                 raw    calibrated
#   pt_BR-faber-medium    2.71 ->  2.16 @ 2.16
#   pt_BR-cadu-medium     3.13 ->  2.14 @ 1.63
#
CALIBRATION = {
    "pt_BR-faber-medium": 2.16,
    "pt_BR-cadu-medium": 1.63,
}
LENGTH_SCALE = 2.16          # faber, the default voice


def dsp_version(speed: float, length_scale: float) -> str:
    base = "piper-v1" if P.HAS_RB else "piper-v1f"
    return f"{base}-s{speed:.2f}-l{length_scale:.2f}"


def main() -> None:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("corpus", type=Path, nargs="?",
                    default=Path(__file__).resolve().parent / "corpus" / "corpus_pt.json")
    ap.add_argument("-o", "--out", type=Path,
                    default=Path(__file__).resolve().parent / "output" / "audio_piper")
    ap.add_argument("--voice", type=Path, default=DEFAULT_VOICE)
    ap.add_argument("--lang", default="pt")
    ap.add_argument("--campaign")
    ap.add_argument("--key", action="append", default=[])
    ap.add_argument("--keys-from", type=Path,
                    help="file with one key per line, added to --key")
    ap.add_argument("--limit", type=int)
    ap.add_argument("--speed", type=float, default=P.SPEED,
                    help="DSP speed, matching the Chatterbox renderer")
    ap.add_argument("--length-scale", type=float, default=None,
                    help="Piper's own pacing; higher is slower. Defaults to the "
                         "calibrated value for the chosen voice.")
    ap.add_argument("--include-dynamic", action="store_true",
                    help="also render blocks carrying a {0} placeholder")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    if not args.voice.exists():
        sys.exit(f"[error] no voice at {args.voice}.\n"
                 f"Download one from huggingface.co/rhasspy/piper-voices, e.g.\n"
                 f"  pt/pt_BR/cadu/medium/pt_BR-cadu-medium.onnx  (+ .onnx.json)")

    if args.length_scale is None:
        args.length_scale = CALIBRATION.get(args.voice.stem)
        if args.length_scale is None:
            args.length_scale = LENGTH_SCALE
            print(f"[warning] {args.voice.stem} has no calibrated pace; using "
                  f"{LENGTH_SCALE} from {DEFAULT_VOICE.stem}. Sweep it and add "
                  f"it to CALIBRATION, or this voice will not match the others.")

    P.SPEED = args.speed          # wizard_chain reads this module-level value

    blocks = P.load_blocks(args.corpus, args.campaign, args.include_dynamic)
    wanted = list(args.key)
    if args.keys_from:
        wanted += [ln.strip() for ln in
                   args.keys_from.read_text(encoding="utf-8").splitlines()
                   if ln.strip() and not ln.startswith("#")]
    if wanted:
        blocks = {k: v for k, v in blocks.items() if k in wanted}
        missing = [k for k in wanted if k not in blocks]
        if missing:
            shown = ", ".join(missing[:6])
            more = f" (and {len(missing) - 6} more)" if len(missing) > 6 else ""
            print(f"[warning] {len(missing)} key(s) not found or without "
                  f"narration: {shown}{more}")

    touched = P.prepare_speech(args.corpus, blocks, args.lang)
    print(f"[glyphs] {touched} of {len(blocks)} blocks had game icons in the text")
    if args.limit:
        blocks = dict(list(blocks.items())[:args.limit])

    words = sum(v["words"] for v in blocks.values())
    print(f"[plan] {args.corpus} | voice={args.voice.stem}")
    print(f"  blocks ................ {len(blocks):,}")
    print(f"  words ................. {words:,}")
    print(f"  estimated audio ....... {words / P.WORDS_PER_SECOND / 3600:.1f} h")
    if args.dry_run:
        return

    from piper import PiperVoice, SynthesisConfig

    t_load = time.time()
    voice = PiperVoice.load(str(args.voice))
    cfg = SynthesisConfig(length_scale=args.length_scale, noise_scale=0.9,
                          noise_w_scale=1.0, volume=1.0)
    print(f"[model] {args.voice.stem} ready in {time.time() - t_load:.1f}s")

    version = dsp_version(args.speed, args.length_scale)
    print(f"[dsp] {'rubberband' if P.HAS_RB else 'asetrate (fallback)'} "
          f"| version {version} | speed {args.speed}x | length {args.length_scale}")

    args.out.mkdir(parents=True, exist_ok=True)
    mpath = args.out / "manifest.json"
    manifest = json.loads(mpath.read_text(encoding="utf-8")) if mpath.exists() else {}

    t0, done, skipped, failed = time.time(), 0, 0, 0
    total, speech_total = len(blocks), 0.0

    for i, (key, v) in enumerate(blocks.items(), 1):
        ck = hashlib.blake2b(
            f"piper|{args.voice.stem}|{version}|{v['speech']}".encode(),
            digest_size=10).hexdigest()
        rel = f"{v['campaign']}/{ck}.opus"
        dest = args.out / rel
        entry = {"file": rel, "campaign": v["campaign"], "text": v["text"],
                 "norm": P.normalize_for_match(v["text"]), "words": v["words"]}
        if dest.exists():
            skipped += 1
            manifest[key] = {**manifest.get(key, {}), **entry}
            continue

        dest.parent.mkdir(parents=True, exist_ok=True)
        tmp = args.out / f".tmp_{ck}.wav"
        try:
            with wave.open(str(tmp), "wb") as fh:
                voice.synthesize_wav(v["speech"], fh, syn_config=cfg)
            with wave.open(str(tmp), "rb") as fh:
                raw = fh.getnframes() / fh.getframerate()
                sr = fh.getframerate()
            subprocess.run(
                ["ffmpeg", "-v", "error", "-y", "-i", str(tmp),
                 "-af", P.wizard_chain(sr), "-c:a", "libopus", "-b:a", "48k",
                 str(dest)], check=True)
        except Exception as exc:  # noqa: BLE001
            failed += 1
            print(f"  [failure] {key}: {type(exc).__name__}: {exc}", flush=True)
            continue
        finally:
            tmp.unlink(missing_ok=True)

        # the DSP changes the duration, so pace is measured on the final file
        out = subprocess.run(["ffprobe", "-v", "error", "-show_entries",
                              "format=duration", "-of", "csv=p=0", str(dest)],
                             capture_output=True, text=True).stdout.strip()
        final = float(out) if out else raw
        speech_total += final
        manifest[key] = {**entry, "wps": round(v["words"] / max(final, 1e-6), 2)}
        done += 1

        if done % 50 == 0 or i == total:
            mpath.write_text(json.dumps(manifest, ensure_ascii=False, indent=1),
                             encoding="utf-8")
            el = time.time() - t0
            print(f"  [{i}/{total}] {key[:44]:<44} {v['words']:>4}w "
                  f"| done {done} skipped {skipped} "
                  f"| RTF {el / max(speech_total, 1e-6):.3f} "
                  f"| ETA {(total - i) / max(done / el, 1e-6) / 60:.1f} min",
                  flush=True)

    mpath.write_text(json.dumps(manifest, ensure_ascii=False, indent=1),
                     encoding="utf-8")
    el = time.time() - t0
    print(f"\n[end] rendered {done} | cached {skipped} | failures {failed}")
    print(f"      {el:.0f}s for {speech_total / 60:.1f} min of speech "
          f"-> RTF {el / max(speech_total, 1e-6):.3f}")
    print(f"      {mpath}  ({len(manifest)} entries)")


if __name__ == "__main__":
    main()
