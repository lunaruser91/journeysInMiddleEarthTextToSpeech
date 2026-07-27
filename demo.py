#!/usr/bin/env python3
"""
demo.py — o ciclo completo numa tela só: imagem → OCR → matcher → áudio.

Serve para você ver (e ouvir) o sistema funcionando ANTES de comprometer as ~19 h
de máquina que o render de uma campanha inteira custa. Pegue um screenshot do
jogo e passe para cá:

    python3 demo.py ~/Desktop/tela.png

O que acontece:

  1. **OCR** com Apple Vision (offline, pt-BR nativo, ~150 ms). É o motor que o
     briefing recomenda e o mesmo que a Fase 3 usaria.
  2. **Casamento** com `matcher.py`, escopado pela campanha do save atual.
     Mostra o score, a margem e a razão de comprimento — as travas — para você
     ver *por que* ele aceitou ou recusou.
  3. **Áudio**: procura o bloco no manifest de um render existente e toca. Se não
     achar e você passar `--render`, sintetiza aquele bloco na hora (~1 min) e
     toca. É a "renderização sob demanda" que o briefing lista como alavanca.

Opções úteis:

    --sem-audio       só OCR + casamento, sem tocar nada
    --render          sintetiza o bloco se ele ainda não existir
    --audio PASTA     onde procurar o manifest.json de um render
    --recorte         limita o OCR à caixa de texto (veja --mostrar-recorte)

Nada aqui escreve no jogo. Só lê a imagem que você entregou.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from matcher import Matcher, carregar_corpus, normalizar, paragrafos  # noqa: E402

CORPUS = Path(__file__).resolve().parent / "corpus" / "corpus_pt.json"
SAVES = Path(os.path.expanduser(
    "~/Library/Application Support/com.fantasyflightgames.jime/SavedGames"))
CAMPANHAS = {1: "bonesofarnor", 2: "shadowedpaths", 3: "spreadingwar",
             4: "hauntingofdale", 5: "poisonpromise", 6: "embercrown"}

VERDE, VERM, AMAR, CINZA, RESET = ("\033[92m", "\033[91m", "\033[93m",
                                   "\033[90m", "\033[0m")


def ocr(caminho: Path, recorte: tuple[float, float, float, float] | None) -> str:
    """Lê o texto da imagem com Apple Vision.

    `recorte` é (esq, topo, dir, base) em fração da imagem. A caixa de texto do
    JiME ocupa a faixa superior central; recortar melhora muito o OCR porque tira
    o mapa, os ícones do HUD e a barra de menus — que só geram lixo.
    """
    try:
        from ocrmac import ocrmac
        from PIL import Image
    except ImportError as e:  # noqa: BLE001
        raise SystemExit(
            f"[erro] {e.name} não está neste interpretador ({sys.executable}).\n"
            f"       Use o venv do projeto:  ~/jime-venv/bin/python demo.py ...")

    img = Image.open(caminho).convert("RGB")
    if recorte:
        w, h = img.size
        e, t, d, b = recorte
        img = img.crop((int(w * e), int(h * t), int(w * d), int(h * b)))
    # sempre grava um PNG temporário: o Vision não abre webp/heic diretamente,
    # e converter aqui evita um erro obscuro lá dentro
    tmp = Path("/tmp/_jime_entrada.png")
    img.save(tmp)
    caminho = tmp

    t0 = time.perf_counter()
    res = ocrmac.OCR(str(caminho), language_preference=["pt-BR"]).recognize()
    dt = (time.perf_counter() - t0) * 1000

    # O Apple Vision devolve UMA LINHA por resultado, não parágrafos. Juntar tudo
    # com "\n" faria cada linha virar um parágrafo no matcher — e uma linha de 60
    # chars contra um bloco de 150 reprova na trava de razão de comprimento, mesmo
    # com score 100. Foi exatamente o que aconteceu no primeiro teste real.
    #
    # A reconstrução usa a geometria: cada resultado traz (texto, confiança, bbox)
    # com bbox = (x, y, largura, altura) normalizado e origem embaixo à esquerda
    # (convenção do Vision). Linhas consecutivas cujo espaçamento vertical excede
    # ~1,6x a altura típica pertencem a parágrafos diferentes.
    itens = [(r[0], r[2]) for r in res if r[0].strip()]
    itens.sort(key=lambda it: -it[1][1])          # de cima para baixo
    if not itens:
        print(f"{CINZA}[ocr] Apple Vision, {dt:.0f} ms, nada legível{RESET}")
        return ""

    alturas = sorted(b[3] for _t, b in itens)
    h_tipica = alturas[len(alturas) // 2]
    paras, atual = [], [itens[0][0]]
    for (txt, bb), (_pt, pb) in zip(itens[1:], itens[:-1]):
        gap = (pb[1] - bb[1]) - h_tipica        # espaço em branco entre as linhas
        if gap > h_tipica * 0.6:
            paras.append(" ".join(atual))
            atual = [txt]
        else:
            atual.append(txt)
    paras.append(" ".join(atual))

    print(f"{CINZA}[ocr] Apple Vision, {dt:.0f} ms, {len(itens)} linhas "
          f"reagrupadas em {len(paras)} parágrafo(s){RESET}")
    return "\n\n".join(paras)


def achar_audio(chave: str, pastas: list[Path]) -> Path | None:
    for pasta in pastas:
        man = pasta / "manifest.json"
        if not man.exists():
            continue
        try:
            m = json.loads(man.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            continue
        if chave in m:
            p = pasta / m[chave]["file"]
            if p.exists():
                return p
    return None


def tocar(p: Path) -> None:
    print(f"{VERDE}[tocando]{RESET} {p.name}")
    subprocess.run(["afplay", str(p)], check=False)


def escopo_atual() -> tuple[str | None, int | None]:
    """Descobre campanha e aventura do save mais recente."""
    saves = sorted(SAVES.glob("*/SavedGame*"),
                   key=lambda p: p.stat().st_mtime, reverse=True)
    for s in saves:
        try:
            j = json.loads(s.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            continue
        return CAMPANHAS.get(j.get("CampaignId")), j.get("CurrentAdventureId")
    return None, None


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("imagem", type=Path, nargs="?",
                    help="caminho da imagem; se omitido, usa a captura de tela "
                         "mais recente da Área de Trabalho")
    ap.add_argument("--corpus", type=Path, default=CORPUS)
    ap.add_argument("--audio", type=Path, action="append", default=[],
                    help="pasta com manifest.json de um render (pode repetir)")
    ap.add_argument("--sem-audio", action="store_true")
    ap.add_argument("--render", action="store_true",
                    help="sintetizar o bloco na hora se ele não existir")
    ap.add_argument("--recorte", default="0.05,0.10,0.95,0.45",
                    help="esq,topo,dir,base em fração da imagem; 'nao' desliga")
    ap.add_argument("--campanha", help="forçar a campanha do escopo")
    args = ap.parse_args()

    if args.imagem is None or not args.imagem.exists():
        # conveniência: pega a captura mais recente, para não ter que digitar caminho
        cands = [p for d in (Path.home() / "Desktop", Path.home() / "Downloads")
                 if d.exists()
                 for p in d.iterdir()
                 if p.suffix.lower() in (".png", ".jpg", ".jpeg", ".webp",
                                         ".heic", ".tif", ".tiff", ".bmp")]
        if not cands:
            sys.exit(
                f"[erro] {'imagem não encontrada: ' + str(args.imagem) if args.imagem else 'nenhuma imagem indicada'}\n"
                "       e não achei captura nenhuma na Área de Trabalho.\n\n"
                "       Tire uma com  Cmd+Shift+4  (arrasta e seleciona a caixa de texto)\n"
                "       ou             Cmd+Shift+3  (tela inteira)\n"
                "       e rode de novo — sem argumento nenhum, que eu pego a mais recente.")
        args.imagem = max(cands, key=lambda p: p.stat().st_mtime)
        print(f"{CINZA}[imagem] usando a captura mais recente: "
              f"{args.imagem.name}{RESET}")

    rec = None
    if args.recorte.lower() not in ("nao", "não", "no", ""):
        rec = tuple(float(x) for x in args.recorte.split(","))  # type: ignore

    texto = ocr(args.imagem, rec)
    print(f"\n{CINZA}--- texto lido da tela ---{RESET}")
    print(texto)

    campanha, aventura = escopo_atual()
    campanha = args.campanha or campanha
    print(f"\n{CINZA}[escopo] campanha={campanha} aventura={aventura} "
          f"(do save mais recente){RESET}")

    corpus = carregar_corpus(args.corpus)
    m = Matcher(corpus, campanha=campanha)
    print(f"{CINZA}[escopo] {len(m):,} entradas candidatas{RESET}")

    print(f"\n{CINZA}--- casamento, parágrafo a parágrafo ---{RESET}")
    resultados = m.casar_tela(texto)
    escolhidos: list[str] = []
    for i, r in enumerate(resultados):
        cor = VERDE if r.aceito else AMAR
        marca = "ACEITO " if r.aceito else "recusado"
        print(f"{cor}[{marca}]{RESET} par.{i+1}  {r.chave or '—'}")
        print(f"          score {r.score:5.1f}  margem {r.margem:5.1f}  "
              f"razão {r.razao_compr:.2f}   {CINZA}{r.motivo}{RESET}")
        if r.aceito and r.chave:
            print(f"          {CINZA}corpus: "
                  f"{' '.join(corpus[r.chave]['text'].split())[:100]}{RESET}")
            if r.chave not in escolhidos:
                escolhidos.append(r.chave)

    if not escolhidos:
        print(f"\n{VERM}Nenhum bloco identificado com confiança.{RESET}")
        print("Na Fase 3 isto viraria silêncio (recuperável com TTS ao vivo),")
        print("nunca uma narração errada. Tente --recorte nao, ou ajuste a faixa.")
        return

    if args.sem_audio:
        return

    # tudo que é gerado vive em saida/, dentro do repositório
    base = Path(__file__).resolve().parent / "saida"
    pastas = args.audio or ([base / "audio"] +
                            sorted(d for d in base.glob("*") if d.is_dir()))
    print()
    for chave in escolhidos:
        p = achar_audio(chave, pastas)
        if p:
            tocar(p)
        elif args.render:
            print(f"{AMAR}[render]{RESET} {chave} ainda não existe; sintetizando "
                  f"(leva ~1 min)...")
            sintetizar_e_tocar(chave, corpus, args.corpus)
        else:
            print(f"{AMAR}[sem áudio]{RESET} {chave} — use --render para "
                  f"sintetizar na hora, ou aponte --audio para um render existente")


def sintetizar_e_tocar(chave: str, corpus: dict, corpus_path: Path) -> None:
    """Renderiza um único bloco sob demanda, reusando o renderizador de produção."""
    campanha = chave.split(":", 1)[0]
    saida = Path(__file__).resolve().parent / "saida" / "sob-demanda"
    saida.mkdir(parents=True, exist_ok=True)
    cmd = [sys.executable, "fase2_render.py", str(corpus_path), "-o", str(saida),
           "--ref", os.path.expanduser("~/jime/ref/REF_paginasrecolhidas.wav"),
           "--campaign", campanha]
    print(f"{CINZA}      {' '.join(cmd[:4])} ...{RESET}")
    # o renderizador não tem filtro por chave única; o cache faz o resto barato
    subprocess.run(cmd + ["--limit", "1"], check=False)
    p = achar_audio(chave, [saida])
    if p:
        tocar(p)


if __name__ == "__main__":
    main()
