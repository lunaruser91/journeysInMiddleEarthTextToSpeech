#!/usr/bin/env python3
"""
lote.py — passa várias telas pelo ciclo OCR → matcher e resume o resultado.

Serve para ganhar confiança antes de comprometer horas de render: em vez de
testar uma tela por vez, joga um punhado e vê a taxa de acerto de verdade.

    ~/jime-venv/bin/python lote.py ~/Downloads/*.webp
    ~/jime-venv/bin/python lote.py ~/Downloads/*.webp --chaves chaves.txt

Com `--chaves`, grava a lista de blocos identificados, pronta para alimentar o
renderizador:

    ~/jime-venv/bin/python fase2_render.py corpus.json -o audio/ \\
        $(sed 's/^/--key /' chaves.txt | tr '\\n' ' ')
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

import demo  # noqa: E402
from matcher import Matcher, carregar_corpus  # noqa: E402

VERDE, AMAR, CINZA, RESET = "\033[92m", "\033[93m", "\033[90m", "\033[0m"


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("imagens", nargs="+", type=Path)
    ap.add_argument("--corpus", type=Path, default=demo.CORPUS)
    ap.add_argument("--campanha")
    ap.add_argument("--recorte", default="nao")
    ap.add_argument("--chaves", type=Path, help="gravar as chaves identificadas")
    args = ap.parse_args()

    rec = None
    if args.recorte.lower() not in ("nao", "não", "no", ""):
        rec = tuple(float(x) for x in args.recorte.split(","))  # type: ignore

    campanha = args.campanha or demo.escopo_atual()[0]
    corpus = carregar_corpus(args.corpus)
    m = Matcher(corpus, campanha=campanha)
    print(f"[escopo] campanha={campanha} | {len(m):,} entradas candidatas\n")

    achadas: list[str] = []
    com_bloco = sem_bloco = 0
    for img in sorted(args.imagens):
        if not img.exists():
            continue
        try:
            texto = demo.ocr(img, rec)
        except Exception as e:  # noqa: BLE001
            print(f"{AMAR}[falha]{RESET} {img.name}: {e}")
            continue

        resultados = [r for r in m.casar_tela(texto) if r.aceito and r.chave]
        # narração é o que interessa; o resto é HUD e botão
        narr = [r for r in resultados
                if corpus.get(r.chave, {}).get("narration")]
        chaves = list(dict.fromkeys(r.chave for r in narr))

        if chaves:
            com_bloco += 1
            print(f"{VERDE}[ok]{RESET} {img.name}")
            for r in narr:
                if r.chave in chaves:
                    chaves.remove(r.chave)
                    if r.chave not in achadas:
                        achadas.append(r.chave)
                    txt = " ".join(corpus[r.chave]["text"].split())[:82]
                    print(f"     {r.chave:<38} score {r.score:5.1f}")
                    print(f"     {CINZA}{txt}{RESET}")
        else:
            sem_bloco += 1
            amostra = " ".join(texto.split())[:70]
            print(f"{AMAR}[sem bloco]{RESET} {img.name}  {CINZA}{amostra}{RESET}")

    n = com_bloco + sem_bloco
    print(f"\n{'='*72}")
    print(f"telas com bloco de narração identificado: {com_bloco}/{n} "
          f"({100*com_bloco/max(n,1):.0f}%)")
    print(f"blocos distintos: {len(achadas)}")

    if args.chaves:
        args.chaves.write_text("\n".join(achadas) + "\n", encoding="utf-8")
        print(f"\n[salvo] {args.chaves}")


if __name__ == "__main__":
    main()
