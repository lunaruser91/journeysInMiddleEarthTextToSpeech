#!/usr/bin/env python3
"""
check_ritmo.py — detector de anomalia de ritmo na narração renderizada.

Modelos autorregressivos como o Chatterbox às vezes derivam: repetem um token,
alongam uma vogal, ou entram num laço até o EOS forçado. O sintoma audível é um
bloco que demora muito mais do que o texto justifica. Foi o caso de
`bonesofarnor:A1_THREAT_1`, que saiu a 1,00 palavra/s contra uma média de 2,03.

Este script mede palavras por segundo de fala de cada bloco renderizado e sinaliza
os que fogem da mediana. Use a saída para regerar os suspeitos com outra seed.

    python3 check_ritmo.py audio/manifest.json
    python3 check_ritmo.py audio/manifest.json --mad 3.5 --json suspeitos.json

Sobre a métrica: divide-se por *segundos de fala*, não pela duração bruta do
arquivo. A duração bruta embute as pausas inseridas entre frases e parágrafos, que
não são proporcionais ao número de palavras — sem descontá-las, todo bloco curto
parece lento e todo bloco longo parece rápido, e o detector vira ruído.

Robustez: usa mediana e MAD (desvio absoluto mediano), não média e desvio padrão.
A média é puxada justamente pelos outliers que se quer achar; com poucos blocos,
um único caso ruim esconde os demais.
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

# precisam bater com o render — se você mudar lá, mude aqui
PAUSA_FRASE = 0.30
PAUSA_PARAGRAFO = 0.45
TEMPO = 0.96  # atempo/rubberband do DSP: o áudio final é 1/TEMPO mais longo

SENT_SPLIT = re.compile(r"(?<=[.!?…])\s+")


def duracao(path: Path) -> float | None:
    """Duração em segundos via ffprobe. None se o arquivo não puder ser lido."""
    try:
        out = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "default=nw=1:nk=1", str(path)],
            capture_output=True, text=True, check=True, timeout=30).stdout.strip()
        return float(out)
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired, ValueError):
        return None


def pausas_embutidas(text: str) -> float:
    """Quanto silêncio o renderizador inseriu neste bloco."""
    paras = [p for p in text.split("\n") if p.strip()]
    frases = sum(len([s for s in SENT_SPLIT.split(p) if s.strip()]) for p in paras)
    return frases * PAUSA_FRASE + len(paras) * PAUSA_PARAGRAFO


def mediana(xs: list[float]) -> float:
    s = sorted(xs)
    n = len(s)
    return s[n // 2] if n % 2 else (s[n // 2 - 1] + s[n // 2]) / 2


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("manifest", type=Path, help="manifest.json produzido pelo render")
    ap.add_argument("--root", type=Path,
                    help="pasta base dos áudios (padrão: a pasta do manifest)")
    ap.add_argument("--mad", type=float, default=3.0,
                    help="quantos desvios (MAD) para sinalizar (padrão: 3.0)")
    ap.add_argument("--json", type=Path, help="gravar os suspeitos neste arquivo")
    args = ap.parse_args()

    root = args.root or args.manifest.parent
    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    if not manifest:
        sys.exit("[erro] manifest vazio")

    linhas, ausentes = [], []
    for key, v in manifest.items():
        audio = root / v["file"]
        if not audio.exists():
            ausentes.append(key)
            continue
        dur = duracao(audio)
        if dur is None:
            ausentes.append(key)
            continue
        # desfaz o alongamento do DSP e desconta o silêncio inserido
        fala = dur * TEMPO - pausas_embutidas(v["text"])
        if fala <= 0.5:
            ausentes.append(key)
            continue
        linhas.append({"key": key, "words": v["words"], "dur": dur,
                       "fala": fala, "wps": v["words"] / fala,
                       "file": v["file"]})

    if not linhas:
        sys.exit("[erro] nenhum áudio legível encontrado a partir do manifest")

    wps = [l["wps"] for l in linhas]
    med = mediana(wps)
    mad = mediana([abs(w - med) for w in wps]) or 1e-9
    # 1,4826*MAD estima o desvio padrão de uma normal; assim o limiar em "--mad 3"
    # significa aproximadamente 3 sigmas, e não 3 MADs crus.
    sigma = 1.4826 * mad

    for l in linhas:
        l["z"] = (l["wps"] - med) / sigma

    suspeitos = sorted([l for l in linhas if abs(l["z"]) >= args.mad],
                       key=lambda l: l["z"])

    print(f"[ritmo] {len(linhas)} blocos medidos"
          + (f" | {len(ausentes)} ilegíveis/ausentes" if ausentes else ""))
    print(f"        mediana {med:.2f} palavras/s  (~{med*60:.0f} ppm) | "
          f"sigma robusto {sigma:.2f} | limiar ±{args.mad}")

    ordenado = sorted(linhas, key=lambda l: l["wps"])
    print(f"        faixa {ordenado[0]['wps']:.2f} .. {ordenado[-1]['wps']:.2f} palavras/s")

    if not suspeitos:
        print("\n[ok] nenhum bloco fora do limiar.")
    else:
        print(f"\n[suspeitos] {len(suspeitos)} bloco(s) — regerar com outra seed:\n")
        print(f"  {'bloco':<46} {'p':>4} {'dur':>7} {'p/s':>6} {'z':>7}")
        for l in suspeitos:
            marca = "lento" if l["z"] < 0 else "rápido"
            print(f"  {l['key'][:46]:<46} {l['words']:>4} {l['dur']:>6.1f}s "
                  f"{l['wps']:>6.2f} {l['z']:>+7.1f}  {marca}")

    if args.json:
        args.json.write_text(json.dumps(
            {"mediana_wps": med, "sigma": sigma, "limiar": args.mad,
             "suspeitos": suspeitos}, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"\n[salvo] {args.json}")


if __name__ == "__main__":
    main()
