#!/usr/bin/env python3
"""
render_piper.py — trilha provisória / voz de fallback da Fase 3.

Mesma estrutura do render_corpus.py (mesmo cache, mesmo manifest, mesma cadeia
de DSP), mas sintetizando com Piper em vez do Chatterbox. É ~90x mais rápido e
não precisa de GPU — serve para (a) ter áudio jogável já, (b) ser a voz do TTS
ao vivo dos blocos com {0} na Fase 3.
"""
from __future__ import annotations

import argparse, hashlib, json, re, subprocess, time, unicodedata, wave
from pathlib import Path

DSP_VERSION = "mago-v1-piper"
WIZARD_CHAIN = (
    "rubberband=pitch=0.93:formant=shifted:tempo=0.94:pitchq=quality:transients=smooth,"
    "equalizer=f=110:t=q:w=0.9:g=4,equalizer=f=380:t=q:w=1.1:g=-2.5,"
    "equalizer=f=6500:t=q:w=1.2:g=-3,tremolo=f=5.2:d=0.06,"
    "aecho=0.8:0.85:35|75:0.28|0.16,alimiter=limit=0.95,loudnorm=I=-16:TP=-1.5:LRA=11"
)


def norm(s: str) -> str:
    s = unicodedata.normalize("NFKD", s)
    s = "".join(c for c in s if not unicodedata.combining(c)).casefold()
    return re.sub(r"\s+", " ", re.sub(r"[^\w\s]", " ", s)).strip()


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("corpus", type=Path)
    ap.add_argument("-o", "--out", type=Path, default=Path("audio_piper"))
    ap.add_argument("--voice", default="voices/pt_BR-cadu-medium.onnx")
    ap.add_argument("--campaign")
    ap.add_argument("--limit", type=int)
    ap.add_argument("--length-scale", type=float, default=1.16)
    args = ap.parse_args()

    from piper import PiperVoice, SynthesisConfig

    corpus = json.loads(args.corpus.read_text(encoding="utf-8"))
    blocks = {k: v for k, v in corpus.items()
              if v.get("narration") and not v.get("placeholders")
              and (not args.campaign or v["campaign"] == args.campaign)}
    if args.limit:
        blocks = dict(list(blocks.items())[:args.limit])

    voice = PiperVoice.load(args.voice)
    cfg = SynthesisConfig(length_scale=args.length_scale, noise_scale=0.9,
                          noise_w_scale=1.0, volume=1.0)
    args.out.mkdir(parents=True, exist_ok=True)
    mpath = args.out / "manifest.json"
    manifest = json.loads(mpath.read_text()) if mpath.exists() else {}

    t0, done, skipped = time.time(), 0, 0
    total = len(blocks)
    print(f"[piper] {total} blocos | voz={Path(args.voice).stem}", flush=True)

    for i, (key, v) in enumerate(blocks.items(), 1):
        ck = hashlib.blake2b(
            f"piper|{Path(args.voice).stem}|{DSP_VERSION}|{args.length_scale}|{v['text']}"
            .encode(), digest_size=10).hexdigest()
        rel = f"{v['campaign']}/{ck}.opus"
        dest = args.out / rel
        manifest[key] = {"file": rel, "campaign": v["campaign"], "text": v["text"],
                         "norm": norm(v["text"]), "words": v["words"]}
        if dest.exists():
            skipped += 1
            continue
        dest.parent.mkdir(parents=True, exist_ok=True)
        tmp = args.out / f".tmp_{ck}.wav"
        with wave.open(str(tmp), "wb") as fh:
            voice.synthesize_wav(v["text"], fh, syn_config=cfg)
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(tmp), "-af", WIZARD_CHAIN,
                        "-c:a", "libopus", "-b:a", "48k", str(dest)], check=True)
        tmp.unlink(missing_ok=True)
        done += 1
        if done % 50 == 0:
            mpath.write_text(json.dumps(manifest, ensure_ascii=False, indent=1), encoding="utf-8")
            el = time.time() - t0
            print(f"  [{i}/{total}] feitos {done} | {el/60:.1f} min | "
                  f"ETA {(total-i)/max(done/el,1e-6)/60:.1f} min", flush=True)

    mpath.write_text(json.dumps(manifest, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"[fim] {done} renderizados, {skipped} em cache, {time.time()-t0:.0f}s")


if __name__ == "__main__":
    main()
