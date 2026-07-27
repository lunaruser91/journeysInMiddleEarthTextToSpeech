#!/usr/bin/env python3
"""
render_corpus.py — Fase 2 do Narrador JiME.

Pré-renderiza o corpus pt-BR em áudio de narrador ("mago velho"), usando
Chatterbox Multilingual com clonagem de voz + cadeia de DSP no ffmpeg.

Projetado para rodar horas sem supervisão:
  • cache por hash (modelo|voz|dsp|params|texto) — retomável a qualquer momento
  • pula blocos com placeholder {0} (esses vão para TTS ao vivo na Fase 3)
  • quebra por frase, com pausa entre frases e entre parágrafos
  • grava manifest.json incremental + índice normalizado para o matching da Fase 3
  • --dry-run estima o tempo total antes de você deixar a noite inteira rodando

Uso típico (no Mac, Apple Silicon):
    python3 render_corpus.py corpus/corpus_pt.json -o audio/ \
        --ref ref/REF_paginasrecolhidas.wav --device mps

    python3 render_corpus.py corpus/corpus_pt.json --dry-run
    python3 render_corpus.py corpus/corpus_pt.json --campaign bonesofarnor

Requisitos:
    pip install chatterbox-tts torch torchaudio "setuptools<81"
    ffmpeg compilado com librubberband  (brew install ffmpeg)
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
# receita de voz — mude DSP_VERSION sempre que mexer na cadeia, senão o cache
# devolve áudio velho e você passa horas depurando um fantasma
# --------------------------------------------------------------------------- #

PITCH = 0.95   # 1.0 = sem mudança; menor = mais grave (formantes acompanham)
TEMPO = 0.96   # menor = mais lento

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
    """Cadeia de mago. Usa rubberband se existir; senão, o truque do asetrate,
    que desloca pitch e formantes juntos — sonicamente equivalente a
    'formant=shifted' — seguido de atempo para restaurar a duração."""
    if HAS_RB:
        return (f"rubberband=pitch={PITCH}:formant=shifted:tempo={TEMPO}"
                f":pitchq=quality:transients=smooth,{_CORPO}")
    # asetrate baixa pitch+formantes e ALONGA a duração em 1/PITCH.
    # queremos duração final de 1/TEMPO, logo atempo = (1/PITCH) / (1/TEMPO) = TEMPO/PITCH.
    atempo = TEMPO / PITCH
    return (f"asetrate={int(sr * PITCH)},aresample={sr},"
            f"atempo={atempo:.5f},{_CORPO}")

PAUSA_FRASE = 0.30      # segundos entre frases
PAUSA_PARAGRAFO = 0.45  # segundos extras entre parágrafos
SEED = 1234

SENT_SPLIT = re.compile(r"(?<=[.!?…])\s+")


def normalize_for_match(s: str) -> str:
    """Mesma normalização que a Fase 3 vai usar no OCR: sem acento, sem pontuação."""
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
    audio_h = words / 140 / 60          # ~140 palavras/min num narrador pausado
    print(f"  blocos ................ {len(blocks):,}")
    print(f"  palavras .............. {words:,}")
    print(f"  áudio estimado ........ {audio_h:.1f} h")
    print(f"  tempo de render ....... {audio_h * rtf:.1f} h  (RTF assumido {rtf})")
    print(f"  tamanho em opus 48k ... ~{audio_h * 3600 * 6 / 1024:.0f} MB")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("corpus", type=Path)
    ap.add_argument("-o", "--out", type=Path, default=Path("audio"))
    ap.add_argument("--ref", type=Path, default=Path("ref/REF_paginasrecolhidas.wav"),
                    help="clipe de referência para clonagem (10-15 s, limpo)")
    ap.add_argument("--device", default="auto", choices=["auto", "mps", "cuda", "cpu"])
    ap.add_argument("--campaign", help="renderizar só uma campanha")
    ap.add_argument("--limit", type=int, help="parar depois de N blocos (teste)")
    ap.add_argument("--exaggeration", type=float, default=0.45,
                    help="0.3-0.7; mais baixo = leitura mais contida/narrativa")
    ap.add_argument("--cfg-weight", type=float, default=0.35,
                    help="mais baixo = ritmo mais lento e deliberado")
    ap.add_argument("--include-dynamic", action="store_true",
                    help="renderizar também blocos com {0} (não recomendado)")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--rtf", type=float, default=0.45, help="RTF assumido no --dry-run")
    args = ap.parse_args()

    blocks = load_blocks(args.corpus, args.campaign, args.include_dynamic)
    if args.limit:
        blocks = dict(list(blocks.items())[:args.limit])

    print(f"[plano] {args.corpus}" + (f" | campanha={args.campaign}" if args.campaign else ""))
    estimate(blocks, args.rtf)
    if args.dry_run:
        return
    if not args.ref.exists():
        sys.exit(f"[erro] referência não encontrada: {args.ref}")

    import torch
    import torchaudio as ta
    from chatterbox.mtl_tts import ChatterboxMultilingualTTS

    device = args.device
    if device == "auto":
        device = ("mps" if torch.backends.mps.is_available()
                  else "cuda" if torch.cuda.is_available() else "cpu")
    print(f"[dsp] {'rubberband' if HAS_RB else 'asetrate (fallback, sem rubberband)'} "
          f"| versão {DSP_VERSION}")
    print(f"[modelo] carregando em {device} ...")
    t0 = time.time()
    model = ChatterboxMultilingualTTS.from_pretrained(device=device)
    torch.manual_seed(SEED)
    print(f"[modelo] pronto em {time.time()-t0:.0f}s")

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
                print(f"  [{i}/{total}] {key[:44]:<44} {v['words']:>4}p {dt:5.0f}s "
                      f"| feitos {done} pulados {skipped} | ETA {eta:.1f} h", flush=True)
        except KeyboardInterrupt:
            print("\n[interrompido] o cache preserva tudo — é só rodar de novo.")
            break
        except Exception as e:  # noqa: BLE001
            failed += 1
            print(f"  [falha] {key}: {type(e).__name__}: {e}", flush=True)

    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"\n[fim] renderizados {done} | em cache {skipped} | falhas {failed}")
    print(f"      {manifest_path}  ({len(manifest)} entradas)")


if __name__ == "__main__":
    main()
