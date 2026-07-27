#!/usr/bin/env python3
"""
ver_log.py — vigia os logs do jogo e mostra o texto de cada bloco exibido.

Serve para responder a pergunta que decide a arquitetura da Fase 3:
**o jogo escreve o log em tempo real, ou só descarrega ao salvar?**

Como usar:

  1. rode este script
  2. abra o jogo e carregue qualquer partida
  3. avance duas ou três telas de narração

Se as linhas aparecerem aqui no mesmo instante em que surgem na tela, a Fase 3
pode ser um simples leitor de arquivo — sem captura de tela, sem OCR, sem as
permissões de TCC do macOS, e com o mesmo código no Windows.
Se só aparecerem quando o jogo salvar, o log ainda serve como contexto, mas o
gatilho terá de ser a tela.

    python3 ver_log.py                      # vigia todos os slots
    python3 ver_log.py --slot 2             # só um
    python3 ver_log.py --tudo               # inclui blocos que não são narração

Não escreve nada, não toca no jogo: só lê arquivos.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import time
from collections import deque
from pathlib import Path

SAVES = Path(os.path.expanduser(
    "~/Library/Application Support/com.fantasyflightgames.jime/SavedGames"))
CORPUS_PADRAO = Path(__file__).resolve().parent / "corpus" / "corpus_pt.json"

LINHA = re.compile(r"^\[([^|]*)\|([^|]*)\|([^|\]]+)((?:\|[^\]]*)*)\]$")

# tipos de parâmetro observados nos logs
TIPO_CHAVE = "8"     # o valor é outra chave de localização
TIPO_LITERAL = "10"  # o valor é literal (número, id de peça...)

CINZA, VERDE, AMARELO, RESET = "\033[90m", "\033[92m", "\033[93m", "\033[0m"


def carregar_corpus(caminho: Path) -> dict:
    if not caminho.exists():
        return {}
    corpus = json.loads(caminho.read_text(encoding="utf-8"))
    idx = {}
    for k, v in corpus.items():
        idx.setdefault(k.split(":", 1)[1], v)   # chave -> entrada (1a campanha vence)
    return idx


def parse_params(resto: str) -> list[str]:
    """Extrai os valores dos parâmetros. Cada um ocupa 4 campos: tipo|?|valor|?"""
    campos = [c for c in resto.split("|") if c != ""]
    if not campos or not campos[0].isdigit():
        return []
    n = int(campos[0])
    corpo = campos[1:]
    if len(corpo) < 4 * n:
        return []
    return [corpo[i * 4 + 2] for i in range(n)]


def resolver(texto: str, valores: list[str], idx: dict) -> str:
    """Substitui {0}, {1}... pelos valores, resolvendo referências a outras chaves."""
    for i, val in enumerate(valores):
        alvo = idx.get(val)
        legivel = alvo["text"] if alvo else val
        texto = texto.replace("{%d}" % i, legivel)
    return texto


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--slot", help="vigiar só este slot (padrão: todos)")
    ap.add_argument("--corpus", type=Path, default=CORPUS_PADRAO)
    ap.add_argument("--tudo", action="store_true",
                    help="mostrar também blocos que não são narração")
    ap.add_argument("--intervalo", type=float, default=0.25)
    args = ap.parse_args()

    if not SAVES.exists():
        raise SystemExit(f"[erro] pasta de saves não encontrada: {SAVES}")

    idx = carregar_corpus(args.corpus)
    print(f"[corpus] {len(idx):,} chaves carregadas de {args.corpus}"
          if idx else f"[corpus] não encontrado em {args.corpus} — mostro só as chaves")

    padrao = f"{args.slot}/Log*.txt" if args.slot else "*/Log*.txt"
    arquivos = sorted(SAVES.glob(padrao))
    if not arquivos:
        raise SystemExit(f"[erro] nenhum log em {SAVES}/{padrao}")

    # começa do fim: só interessa o que acontecer a partir de agora
    pos = {f: f.stat().st_size for f in arquivos}
    for f in arquivos:
        print(f"[vigiando] {f.relative_to(SAVES)}  ({pos[f]:,} bytes)")

    print(f"\n{VERDE}Pronto. Abra o jogo, carregue uma partida e avance uma tela de "
          f"narração.{RESET}")
    print(f"{CINZA}Se as linhas aparecerem na hora, a Fase 3 fica muito mais simples."
          f"  Ctrl+C para sair.{RESET}\n")

    recentes: deque[str] = deque(maxlen=4000)  # LogA e LogB repetem o mesmo conteúdo
    ultimo_sinal = time.time()
    try:
        while True:
            if time.time() - ultimo_sinal > 30:
                print(f"{CINZA}[vivo] {time.strftime('%H:%M:%S')} — nenhuma escrita "
                      f"detectada ainda{RESET}")
                ultimo_sinal = time.time()
            # o jogo pode criar um slot novo no meio da partida
            for novo in sorted(SAVES.glob(padrao)):
                if novo not in pos:
                    pos[novo] = 0
                    arquivos.append(novo)
                    print(f"{AMARELO}[novo arquivo]{RESET} {novo.relative_to(SAVES)}")

            for f in list(arquivos):
                try:
                    tam = f.stat().st_size
                except FileNotFoundError:
                    continue
                if tam == pos[f]:
                    continue
                # anuncia a escrita SEMPRE — é isto que responde "ao vivo ou ao salvar?"
                print(f"{AMARELO}[escrita]{RESET} {time.strftime('%H:%M:%S')} "
                      f"{f.relative_to(SAVES)}  {pos[f]:,} -> {tam:,} bytes")
                if tam < pos[f]:          # o jogo truncou/reescreveu o arquivo
                    pos[f] = 0
                with f.open("r", encoding="utf-8", errors="replace") as fh:
                    fh.seek(pos[f])
                    novas = fh.read()
                    pos[f] = fh.tell()

                for linha in novas.splitlines():
                    linha = linha.strip()
                    if not linha or linha in recentes:
                        continue
                    recentes.append(linha)
                    m = LINHA.match(linha)
                    if not m:
                        print(f"{AMARELO}[formato desconhecido]{RESET} {linha}")
                        continue
                    aventura, rodada, chave, resto = m.groups()
                    v = idx.get(chave)
                    narracao = bool(v and v.get("narration"))
                    if not args.tudo and idx and not narracao:
                        continue
                    quando = time.strftime("%H:%M:%S")
                    marca = f"{VERDE}NARRA{RESET}" if narracao else f"{CINZA} ui  {RESET}"
                    print(f"{CINZA}{quando}{RESET} {marca} "
                          f"{CINZA}av{aventura} rd{rodada}{RESET} {chave}")
                    if v:
                        texto = resolver(v["text"], parse_params(resto), idx)
                        texto = " ".join(texto.split())
                        print(f"        {texto[:150]}")
            time.sleep(args.intervalo)
    except KeyboardInterrupt:
        print("\n[fim]")


if __name__ == "__main__":
    main()
