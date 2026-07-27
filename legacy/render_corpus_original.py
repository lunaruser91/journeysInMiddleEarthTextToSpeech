#!/usr/bin/env python3
"""
render_corpus.py — Phase 2 of the JiME Narrator.

Pre-renders the pt-BR corpus into narrator audio ("old wizard"), using
Chatterbox Multilingual with voice cloning + a DSP chain in ffmpeg.

Designed to run for hours unattended:
  • hash-based cache (model|voice|dsp|params|text) — resumable at any point
  • skips blocks with a {0} placeholder (those go to live TTS in Phase 3)
  • splits by sentence, with a pause between sentences and between paragraphs
  • writes an incremental manifest.json + normalized index for Phase 3 matching
  • --dry-run estimates the total time before you leave it running all night

Typical usage (on a Mac, Apple Silicon):
    python3 render_corpus.py corpus/corpus_pt.json -o audio/ \
        --ref ref/REF_paginasrecolhidas.wav --device mps

    python3 render_corpus.py corpus/corpus_pt.json --dry-run
    python3 render_corpus.py corpus/corpus_pt.json --campaign bonesofarnor

Requirements:
    pip install chatterbox-tts torch torchaudio "setuptools<81"
    ffmpeg compiled with librubberband  (brew install ffmpeg)
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import time
import unicodedata
from pathlib import Path

# --------------------------------------------------------------------------- #
# voice recipe — bump DSP_VERSION whenever you touch the chain, otherwise the
# cache hands back stale audio and you spend hours debugging a ghost
# --------------------------------------------------------------------------- #

PITCH = 0.95   # 1.0 = no change; lower = deeper (formants follow along)
TEMPO = 0.96   # lower = slower

_CORPO = (
    "equalizer=f=110:t=q:w=0.9:g=3.5,"
    "equalizer=f=380:t=q:w=1.1:g=-2,"
    "equalizer=f=6500:t=q:w=1.2:g=-2.5,"
    "tremolo=f=5.2:d=0.05,"
    "aecho=0.8:0.85:35|75:0.28|0.16,"
    "alimiter=limit=0.95,"
    "loudnorm=I=-16:TP=-1.5:LRA=11"
)


def has_rubberband() -> bool:
    try:
        out = subprocess.run(["ffmpeg", "-hide_banner", "-filters"],
                             capture_output=True, text=True, timeout=20).stdout
        return " rubberband " in out
    except Exception:  # noqa: BLE001
        return False


HAS_RB = has_rubberband()
DSP_VERSION = "mago-v1" if HAS_RB else "mago-v1f"


def wizard_chain(sr: int) -> str:
    """Wizard chain. Uses rubberband if available; otherwise the asetrate trick,
    which shifts pitch and formants together — sonically equivalent to
    'formant=shifted' — followed by atempo to restore the duration."""
    if HAS_RB:
        return (f"rubberband=pitch={PITCH}:formant=shifted:tempo={TEMPO}"
                f":pitchq=quality:transients=smooth,{_CORPO}")
    # asetrate lowers pitch+formants and STRETCHES the duration by 1/PITCH.
    # we want a final duration of 1/TEMPO, so atempo = (1/PITCH) / (1/TEMPO) = TEMPO/PITCH.
    atempo = TEMPO / PITCH
    return (f"asetrate={int(sr * PITCH)},aresample={sr},"
            f"atempo={atempo:.5f},{_CORPO}")

PAUSA_FRASE = 0.30      # seconds between sentences
PAUSA_PARAGRAFO = 0.45  # extra seconds between paragraphs
SEED = 1234

SENT_SPLIT = re.compile(r"(?<=[.!?…])\s+")


def normalize_for_match(s: str) -> str:
    """Same normalization Phase 3 will apply to the OCR: no accents, no punctuation."""
    s = unicodedata.normalize("NFKD", s)
    s = "".join(c for c in s if not unicodedata.combining(c))
    s = s.casefold()
    s = re.sub(r"[^\w\s]", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def cache_key(text: str, ref: Path, params: dict) -> str:
    h = hashlib.blake2b(digest_size=10)
    h.update(f"chatterbox-mtl|pt|{ref.name}|{DSP_VERSION}|{json.dumps(params, sort_keys=True)}|{text}"
             .encode("utf-8"))
    return h.hexdigest()


# --------------------------------------------------------------------------- #

def load_blocks(corpus_path: Path, campaign: str | None, include_dynamic: bool) -> dict:
    corpus = json.loads(corpus_path.read_text(encoding="utf-8"))
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


def estimate(blocks: dict, rtf: float) -> None:
    words = sum(v["words"] for v in blocks.values())
    audio_h = words / 140 / 60          # ~140 words/min for an unhurried narrator
    print(f"  blocks ................ {len(blocks):,}")
    print(f"  words ................. {words:,}")
    print(f"  estimated audio ....... {audio_h:.1f} h")
    print(f"  render time ........... {audio_h * rtf:.1f} h  (assumed RTF {rtf})")
    print(f"  size in opus 48k ...... ~{audio_h * 3600 * 6 / 1024:.0f} MB")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("corpus", type=Path)
    ap.add_argument("-o", "--out", type=Path, default=Path("audio"))
    ap.add_argument("--ref", type=Path, default=Path("ref/REF_paginasrecolhidas.wav"),
                    help="reference clip for cloning (10-15 s, clean)")
    ap.add_argument("--device", default="auto", choices=["auto", "mps", "cuda", "cpu"])
    ap.add_argument("--campaign", help="render only one campaign")
    ap.add_argument("--limit", type=int, help="stop after N blocks (testing)")
    ap.add_argument("--exaggeration", type=float, default=0.45,
                    help="0.3-0.7; lower = more restrained/narrative reading")
    ap.add_argument("--cfg-weight", type=float, default=0.35,
                    help="lower = slower, more deliberate pace")
    ap.add_argument("--include-dynamic", action="store_true",
                    help="also render blocks with {0} (not recommended)")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--rtf", type=float, default=0.45, help="RTF assumed by --dry-run")
    args = ap.parse_args()

    blocks = load_blocks(args.corpus, args.campaign, args.include_dynamic)
    if args.limit:
        blocks = dict(list(blocks.items())[:args.limit])

    print(f"[plan] {args.corpus}" + (f" | campaign={args.campaign}" if args.campaign else ""))
    estimate(blocks, args.rtf)
    if args.dry_run:
        return
    if not args.ref.exists():
        sys.exit(f"[error] reference not found: {args.ref}")

    import torch
    import torchaudio as ta
    from chatterbox.mtl_tts import ChatterboxMultilingualTTS

    device = args.device
    if device == "auto":
        device = ("mps" if torch.backends.mps.is_available()
                  else "cuda" if torch.cuda.is_available() else "cpu")
    print(f"[dsp] {'rubberband' if HAS_RB else 'asetrate (fallback, no rubberband)'} "
          f"| version {DSP_VERSION}")
    print(f"[model] loading on {device} ...")
    t0 = time.time()
    model = ChatterboxMultilingualTTS.from_pretrained(device=device)
    torch.manual_seed(SEED)
    print(f"[model] ready in {time.time()-t0:.0f}s")

    params = {"exaggeration": args.exaggeration, "cfg_weight": args.cfg_weight,
              "pausa": [PAUSA_FRASE, PAUSA_PARAGRAFO], "seed": SEED}

    args.out.mkdir(parents=True, exist_ok=True)
    manifest_path = args.out / "manifest.json"
    manifest = json.loads(manifest_path.read_text()) if manifest_path.exists() else {}

    done = skipped = failed = 0
    t_start = time.time()
    total = len(blocks)

    for i, (key, v) in enumerate(blocks.items(), 1):
        ck = cache_key(v["text"], args.ref, params)
        rel = f"{v['campaign']}/{ck}.opus"
        dest = args.out / rel
        if dest.exists():
            skipped += 1
            manifest[key] = {**manifest.get(key, {}), "file": rel, "campaign": v["campaign"],
                             "text": v["text"], "norm": normalize_for_match(v["text"]),
                             "words": v["words"]}
            continue
        dest.parent.mkdir(parents=True, exist_ok=True)

        try:
            t1 = time.time()
            chunks = []
            for para in [p for p in v["text"].split("\n") if p.strip()]:
                for sent in [s.strip() for s in SENT_SPLIT.split(para) if s.strip()]:
                    wav = model.generate(sent, language_id="pt",
                                         audio_prompt_path=str(args.ref),
                                         exaggeration=args.exaggeration,
                                         cfg_weight=args.cfg_weight)
                    chunks.append(wav)
                    chunks.append(torch.zeros(1, int(model.sr * PAUSA_FRASE)))
                chunks.append(torch.zeros(1, int(model.sr * PAUSA_PARAGRAFO)))

            tmp = args.out / f".tmp_{ck}.wav"
            ta.save(str(tmp), torch.cat(chunks, dim=-1), model.sr)
            try:
                subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(tmp),
                                "-af", wizard_chain(model.sr),
                                "-c:a", "libopus", "-b:a", "48k", str(dest)], check=True)
            finally:
                tmp.unlink(missing_ok=True)

            manifest[key] = {"file": rel, "campaign": v["campaign"], "text": v["text"],
                             "norm": normalize_for_match(v["text"]), "words": v["words"]}
            done += 1
            dt = time.time() - t1
            if done % 10 == 0 or i == total:
                elapsed = time.time() - t_start
                rate = done / max(elapsed, 1)
                eta = (total - i) / max(rate, 1e-6) / 3600
                manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=1),
                                         encoding="utf-8")
                print(f"  [{i}/{total}] {key[:44]:<44} {v['words']:>4}w {dt:5.0f}s "
                      f"| done {done} skipped {skipped} | ETA {eta:.1f} h", flush=True)
        except KeyboardInterrupt:
            print("\n[interrupted] the cache keeps everything — just run it again.")
            break
        except Exception as e:  # noqa: BLE001
            failed += 1
            print(f"  [failure] {key}: {type(e).__name__}: {e}", flush=True)

    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"\n[end] rendered {done} | cached {skipped} | failures {failed}")
    print(f"      {manifest_path}  ({len(manifest)} entries)")


if __name__ == "__main__":
    main()
