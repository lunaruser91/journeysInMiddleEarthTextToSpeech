#!/usr/bin/env python3
"""
phase2_render.py — corpus in, narrated audio out.

    python3 phase2_render.py --lang pt --campaign bonesofarnor
    python3 phase2_render.py --lang de --dry-run
    python3 phase2_render.py --key "main:G22_SWORD_TRUE"

Synthesis is Piper: a small ONNX model that runs on the CPU. The whole voice is
60 MB and renders about twenty times faster than it plays, so a campaign is
minutes rather than a weekend. The previous engine here was Chatterbox, which
sounded better and measured RTF 3.7 — fifty hours for a campaign plus the shared
blocks, against forty-odd minutes. The recording in docs/PHASE2-MEASUREMENTS.md
§6c is why this one won.

It also removed a constraint nobody wanted: Chatterbox cloned a reference
recording, which meant thinking about whose voice it was. Piper synthesises from
a published model with no reference at all, and covers all thirteen of the
game's languages instead of ten.

## The voice, and the wizard chain

Piper alone sounds like a competent announcer. The character comes from the
ffmpeg chain: pitch down a little, low end lifted, high end rolled off, and a
slow tremolo that reads as an unsteady old voice.

Pace is Piper's own `length_scale`, never the DSP. Stretching audio after the
fact smears transients; speaking slower costs nothing. The value is per voice
and measured — see voices.py.

## Resuming

A block whose .opus already exists is skipped, and the manifest is rewritten
every 50 blocks and again at the end. Stopping and restarting is free, and
nothing needs cleaning up first. Changing the voice, the pace or the chain
changes the cache key, so old audio is neither reused nor silently mixed in.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
import time
import unicodedata
import wave
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import glyphs  # noqa: E402
import voices  # noqa: E402

ROOT = Path(__file__).resolve().parent

# --------------------------------------------------------------------------- #
# voice recipe — DSP_VERSION goes into the cache key, so touching any of this
# invalidates old audio instead of quietly mixing two recipes in one session
# --------------------------------------------------------------------------- #

PITCH = 0.95   # 1.0 = unchanged; lower is deeper, formants follow
TEMPO = 0.96   # a shade under 1.0, for weight rather than speed

_BODY = (
    "equalizer=f=110:t=q:w=0.9:g=3.5,"
    "equalizer=f=380:t=q:w=1.1:g=-2,"
    "equalizer=f=6500:t=q:w=1.2:g=-2.5,"
    "tremolo=f=5.2:d=0.05,"
    "aecho=0.8:0.85:35|75:0.28|0.16,"
    "alimiter=limit=0.95,"
    "loudnorm=I=-16:TP=-1.5:LRA=11"
)

WORDS_PER_SECOND = 2.31    # only used to estimate durations before rendering


def has_rubberband() -> bool:
    try:
        out = subprocess.run(["ffmpeg", "-hide_banner", "-filters"],
                             capture_output=True, text=True, timeout=20).stdout
        return " rubberband " in out
    except Exception:  # noqa: BLE001
        return False


HAS_RB = has_rubberband()


def dsp_version(voice: str, length_scale: float) -> str:
    base = "wizard-v2" if HAS_RB else "wizard-v2f"
    return f"{base}-{voice}-l{length_scale:.2f}"


def wizard_chain(sr: int) -> str:
    """Timbre only. Pace belongs to Piper, and mixing the two fights itself.

    The chain this replaced sped the audio up 1.31x with atempo, because the old
    engine spoke too slowly. Piper has the opposite problem, so that speed-up had
    to be cancelled by slowing Piper down — two filters undoing each other, with
    atempo smearing transients for nothing. Now atempo lands at 1.01, which is
    what you want: inert.

    With rubberband the pitch shift keeps formants moving with it. Without it,
    resampling does the same thing by construction — that is what `formant=shifted`
    means — and atempo puts the duration back.
    """
    if HAS_RB:
        return (f"rubberband=pitch={PITCH}:formant=shifted:tempo={TEMPO}"
                f":pitchq=quality:transients=smooth,{_BODY}")
    return (f"asetrate={int(sr * PITCH)},aresample={sr},"
            f"atempo={TEMPO / PITCH:.5f},{_BODY}")


# --------------------------------------------------------------------------- #
# corpus
# --------------------------------------------------------------------------- #

def corpus_path(lang: str) -> Path:
    return ROOT / "corpus" / f"corpus_{lang}.json"


def load_blocks(path: Path, campaign: str | None, include_dynamic: bool) -> dict:
    corpus = json.loads(path.read_text(encoding="utf-8"))
    out = {}
    for k, v in corpus.items():
        if not v.get("narration"):
            continue
        if campaign and v["campaign"] != campaign:
            continue
        if v.get("placeholders") and not include_dynamic:
            continue
        out[k] = v
    return out


def prepare_speech(path: Path, blocks: dict, lang: str) -> int:
    """Attach to each block a `speech` field: the text with icons made words."""
    corpus = json.loads(path.read_text(encoding="utf-8"))
    glyph_map = glyphs.glyph_map_from_corpus(corpus)
    n = 0
    for v in blocks.values():
        # order matters: glyphs first, since they can bring numbers with them
        speech = glyphs.substitute(v["text"], glyph_map, lang)
        v["speech"] = glyphs.spell_out_numbers(speech, lang)
        if v["speech"] != v["text"]:
            n += 1
    return n


def normalize_for_match(s: str) -> str:
    """The normalisation Phase 3 applies to OCR: no accents, no punctuation.

    MIND the asymmetry with the narration: the audio SAYS "test Agility", but the
    screen SHOWS an icon and the OCR reads no word there. So the matching index is
    built from text with the glyphs REMOVED, not substituted — indexing the spoken
    word would never match what is on screen.
    """
    s = glyphs.PUA.sub(" ", s)
    s = unicodedata.normalize("NFKD", s)
    s = "".join(c for c in s if not unicodedata.combining(c))
    s = s.casefold()
    s = re.sub(r"[^\w\s]", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def duration(path: Path) -> float:
    out = subprocess.run(["ffprobe", "-v", "error", "-show_entries",
                          "format=duration", "-of", "csv=p=0", str(path)],
                         capture_output=True, text=True).stdout.strip()
    return float(out) if out else 0.0


# --------------------------------------------------------------------------- #

def main() -> None:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("corpus", type=Path, nargs="?",
                    help="defaults to corpus/corpus_<lang>.json")
    ap.add_argument("--lang", default="pt")
    ap.add_argument("-o", "--out", type=Path,
                    help="defaults to output/audio_<lang>")
    ap.add_argument("--voice", help="Piper voice name; defaults to the one "
                                    "chosen for this language in voices.py")
    ap.add_argument("--campaign")
    ap.add_argument("--key", action="append", default=[])
    ap.add_argument("--keys-from", type=Path,
                    help="file with one key per line, added to --key")
    ap.add_argument("--limit", type=int)
    ap.add_argument("--length-scale", type=float,
                    help="Piper's pacing; higher is slower. Defaults to the "
                         "measured value for the voice.")
    ap.add_argument("--include-dynamic", action="store_true",
                    help="also render blocks carrying a {0} placeholder")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    path = args.corpus or corpus_path(args.lang)
    if not path.exists():
        sys.exit(f"[error] no corpus at {path}. Run: jime extract --lang {args.lang}")
    out_dir = args.out or ROOT / "output" / f"audio_{args.lang}"

    voice_name = voices.resolve(args.lang, args.voice)
    scale = args.length_scale
    if scale is None:
        scale = voices.length_scale(voice_name, args.lang)

    blocks = load_blocks(path, args.campaign, args.include_dynamic)
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

    touched = prepare_speech(path, blocks, args.lang)
    print(f"[glyphs] {touched} of {len(blocks)} blocks had game icons in the text")
    if args.limit:
        blocks = dict(list(blocks.items())[:args.limit])

    words = sum(v["words"] for v in blocks.values())
    print(f"[plan] {path.name} | lang={args.lang} | voice={voice_name}")
    print(f"  blocks ................ {len(blocks):,}")
    print(f"  words ................. {words:,}")
    print(f"  estimated audio ....... {words / WORDS_PER_SECOND / 3600:.1f} h")
    print(f"  estimated render ...... {words / WORDS_PER_SECOND * 0.05 / 60:.0f} min")
    if args.dry_run:
        return
    if not blocks:
        print("[end] nothing to render")
        return

    model = voices.ensure(voice_name)
    from piper import PiperVoice, SynthesisConfig

    t_load = time.time()
    voice = PiperVoice.load(str(model))
    cfg = SynthesisConfig(length_scale=scale, noise_scale=0.9,
                          noise_w_scale=1.0, volume=1.0)
    print(f"[model] {voice_name} ready in {time.time() - t_load:.1f}s")

    version = dsp_version(voice_name, scale)
    print(f"[dsp] {'rubberband' if HAS_RB else 'asetrate (fallback)'} "
          f"| version {version} | length_scale {scale}")

    out_dir.mkdir(parents=True, exist_ok=True)
    mpath = out_dir / "manifest.json"
    manifest = json.loads(mpath.read_text(encoding="utf-8")) if mpath.exists() else {}

    # Stamp what produced this. Without it, a folder of audio is a folder of
    # audio: nothing on disk says which language it speaks, and filling a gap in
    # a Portuguese session with an English block is worse than silence. Keys
    # starting with "_" are metadata, and readers skip them.
    manifest["_meta"] = {"lang": args.lang, "voice": voice_name,
                         "length_scale": scale, "version": version}

    t0, done, skipped, failed, speech = time.time(), 0, 0, 0, 0.0
    total = len(blocks)

    for i, (key, v) in enumerate(blocks.items(), 1):
        ck = hashlib.blake2b(f"{version}|{v['speech']}".encode(),
                             digest_size=10).hexdigest()
        rel = f"{v['campaign']}/{ck}.opus"
        dest = out_dir / rel
        entry = {"file": rel, "campaign": v["campaign"], "text": v["text"],
                 "norm": normalize_for_match(v["text"]), "words": v["words"]}
        if dest.exists():
            skipped += 1
            manifest[key] = {**manifest.get(key, {}), **entry}
            continue

        dest.parent.mkdir(parents=True, exist_ok=True)
        tmp = out_dir / f".tmp_{ck}.wav"
        try:
            with wave.open(str(tmp), "wb") as fh:
                voice.synthesize_wav(v["speech"], fh, syn_config=cfg)
            with wave.open(str(tmp), "rb") as fh:
                sr = fh.getframerate()
            subprocess.run(
                ["ffmpeg", "-v", "error", "-y", "-i", str(tmp),
                 "-af", wizard_chain(sr), "-c:a", "libopus", "-b:a", "48k",
                 str(dest)], check=True)
        except KeyboardInterrupt:
            # KeyboardInterrupt is not an Exception, so the clause below never
            # sees it. Letting it escape skips the manifest write after the loop
            # and loses up to 49 entries — the .opus files survive, but nothing
            # points at them until the next run re-adds them through the skip
            # path. Breaking here keeps the two in step.
            tmp.unlink(missing_ok=True)
            print("\n[interrupted] run the same command again to resume",
                  flush=True)
            break
        except Exception as exc:  # noqa: BLE001
            failed += 1
            print(f"  [failure] {key}: {type(exc).__name__}: {exc}", flush=True)
            continue
        finally:
            tmp.unlink(missing_ok=True)

        # the chain changes the length, so pace is measured on the final file
        final = duration(dest)
        speech += final
        manifest[key] = {**entry, "wps": round(v["words"] / max(final, 1e-6), 2)}
        done += 1

        if done % 50 == 0 or i == total:
            mpath.write_text(json.dumps(manifest, ensure_ascii=False, indent=1),
                             encoding="utf-8")
            el = time.time() - t0
            print(f"  [{i}/{total}] {key[:44]:<44} {v['words']:>4}w "
                  f"| done {done} skipped {skipped} "
                  f"| RTF {el / max(speech, 1e-6):.3f} "
                  f"| ETA {(total - i) / max(done / el, 1e-6) / 60:.1f} min",
                  flush=True)

    mpath.write_text(json.dumps(manifest, ensure_ascii=False, indent=1),
                     encoding="utf-8")
    el = time.time() - t0
    print(f"\n[end] rendered {done} | cached {skipped} | failures {failed}")
    if done:
        print(f"      {el:.0f}s for {speech / 60:.1f} min of speech "
              f"-> RTF {el / max(speech, 1e-6):.3f}")
    print(f"      {mpath}  ({sum(1 for k in manifest if not k.startswith('_'))} entries)")


if __name__ == "__main__":
    main()
