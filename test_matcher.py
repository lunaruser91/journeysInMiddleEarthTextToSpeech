#!/usr/bin/env python3
"""
test_matcher.py — mede a precisão do matcher com telas reais e ruído de OCR.

## De onde vem a verdade fundamental

Do próprio jogo. O `LogA.txt` registra a chave exata de cada bloco exibido, com
os parâmetros. Reconstruindo `template + parâmetros` obtém-se **o texto que
esteve na tela**, com a chave correta ao lado — sem transcrever nada à mão.

Para as telas compostas, a verdade é uma LISTA de chaves, na ordem dos
parágrafos. Exemplo real:

    log     [3|1|PLACE_PERSON|1|8|0|A2_M1_T1_PLACE|0]
    tela    parágrafo 1 = texto de A2_M1_T1_PLACE   (a prosa)
            parágrafo 2 = "Coloque uma ficha de pessoa conforme indicado."
    verdade [A2_M1_T1_PLACE, PLACE_PERSON]

## O ruído

O OCR erra de formas específicas, e ruído aleatório uniforme não representa isso.
As confusões abaixo são as clássicas de OCR em texto serifado claro sobre fundo
escuro, que é exatamente o caso do JiME. Acentos e pontuação não entram porque a
normalização já os remove dos dois lados.

    python3 test_matcher.py                 # roda a bateria completa
    python3 test_matcher.py --verboso       # mostra cada erro
"""
from __future__ import annotations

import argparse
import json
import os
import collections
import random
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import glifos  # noqa: E402
from matcher import Matcher, carregar_corpus, normalizar, paragrafos  # noqa: E402

CORPUS = Path(__file__).resolve().parent / "corpus" / "corpus_pt.json"
LOGS = Path(os.path.expanduser(
    "~/Library/Application Support/com.fantasyflightgames.jime/SavedGames"))
LINHA = re.compile(r"^\[([^|]*)\|([^|]*)\|([^|\]]+)((?:\|[^\]]*)*)\]$")

# confusões de OCR observadas em texto serifado: pares visualmente próximos
CONFUSOES = {
    "m": "rn", "rn": "m", "l": "i", "i": "l", "c": "e", "e": "c",
    "o": "0", "0": "o", "a": "o", "s": "5", "u": "v", "v": "u",
    "d": "cl", "h": "b", "b": "h", "t": "f", "f": "t", "g": "q", "q": "g",
}


def degradar(texto: str, taxa: float, rnd: random.Random) -> str:
    """Aplica ruído de OCR: substituições visuais, quedas e junções de palavra."""
    if taxa <= 0:
        return texto
    saida = []
    for ch in texto:
        r = rnd.random()
        if r < taxa * 0.6 and ch.lower() in CONFUSOES:
            saida.append(CONFUSOES[ch.lower()])
        elif r < taxa * 0.85:
            continue                       # caractere perdido
        elif r < taxa:
            saida.append(ch + ch)          # caractere duplicado
        else:
            saida.append(ch)
    s = "".join(saida)
    # junção de palavras: o OCR às vezes come o espaço
    if rnd.random() < taxa * 4:
        s = re.sub(r" ", "", s, count=1)
    return s


def parse_params(resto: str) -> list[tuple[str, str]]:
    campos = [c for c in resto.split("|") if c != ""]
    if not campos or not campos[0].isdigit():
        return []
    n = int(campos[0])
    corpo = campos[1:]
    if len(corpo) < 4 * n:
        return []
    return [(corpo[i * 4], corpo[i * 4 + 2]) for i in range(n)]


def montar_fixtures(corpus: dict) -> list[dict]:
    """Reconstrói as telas a partir dos logs: (texto_na_tela, chaves_esperadas)."""
    idx = {}
    for k, v in corpus.items():
        idx.setdefault(k.split(":", 1)[1], (k, v))

    fixtures, vistos = [], set()
    for log in sorted(LOGS.glob("*/Log*.txt")):
        for linha in log.read_text(encoding="utf-8", errors="replace").splitlines():
            m = LINHA.match(linha.strip())
            if not m:
                continue
            _av, _rd, chave, resto = m.groups()
            kv = idx.get(chave)
            if not kv:
                continue
            chave_full, v = kv
            if not v.get("narration"):
                continue

            texto = v["text"]
            esperadas: list[str] = []
            # resolve os parâmetros como o jogo faz
            for tipo, valor in parse_params(resto):
                ref = idx.get(valor)
                if tipo == "8" and ref:
                    texto = texto.replace("{0}", ref[1]["text"], 1)
                    if ref[1].get("narration"):
                        esperadas.append(ref[0])
                else:
                    texto = re.sub(r"\{\d\}", valor, texto, count=1)

            if not esperadas:
                esperadas = [chave_full]
            else:
                esperadas.append(chave_full)   # o template vem depois da prosa

            assinatura = normalizar(texto)
            if len(assinatura) < 20 or assinatura in vistos:
                continue
            vistos.add(assinatura)
            pre = re.match(r"^([AB]\d+)_", chave)
            fixtures.append({"tela": texto, "esperadas": esperadas,
                             "chave_log": chave_full, "aventura": _av,
                             "prefixo": pre.group(1) if pre else None,
                             "composta": len(esperadas) > 1})
    return fixtures


def avaliar(m: Matcher, fixtures: list[dict], taxa: float, seed: int,
            verboso: bool) -> dict:
    rnd = random.Random(seed)
    total = acertos = aceitos = falsos = recusas = 0
    erros = []
    # monta todos os trechos de uma vez para casar em paralelo
    trechos, mapa = [], []
    for fi, f in enumerate(fixtures):
        sujo = degradar(f["tela"], taxa, rnd)
        for pi, para in enumerate(paragrafos(sujo)):
            trechos.append(para)
            mapa.append((fi, pi))
    todos = m.casar_lote(trechos)
    por_fixture: dict[int, list] = {}
    for (fi, _pi), res in zip(mapa, todos):
        por_fixture.setdefault(fi, []).append(res)

    for fi, f in enumerate(fixtures):
        resultados = por_fixture.get(fi, [])
        # MÉTRICA POR TELA, não por parágrafo. É o que importa para a reprodução:
        # a tela teve seu bloco de PROSA identificado? Contar cada parágrafo
        # separadamente pune o matcher por casar "Coloque uma ficha de busca
        # conforme indicado" com outro bloco que tem a mesma instrução — o que é
        # inevitável e irrelevante, porque quem se narra é o bloco de prosa.
        principal = f["esperadas"][0]
        norm_ok = {normalizar(m.corpus[k]["text"]) for k in f["esperadas"]
                   if k in m.corpus}
        aceitas = [r.chave for r in resultados if r.aceito]
        total += 1
        if not aceitas:
            recusas += 1
            continue
        aceitos += 1
        acertou = principal in aceitas
        if not acertou:
            # blocos duplicados no corpus produzem o mesmo áudio: não é erro
            acertou = any(k in m.corpus and normalizar(m.corpus[k]["text"]) in norm_ok
                          for k in aceitas)
        if acertou:
            acertos += 1
        else:
            falsos += 1
            if verboso and len(erros) < 6:
                erros.append((principal, resultados[0]))

    motivos = collections.Counter()
    for res in todos:
        if not res.aceito:
            motivos[res.motivo.split(" ")[0] + " " + res.motivo.split(" ")[1]
                    if len(res.motivo.split(" ")) > 1 else res.motivo] += 1
    return {"taxa": taxa, "total": total, "acertos": acertos, "aceitos": aceitos,
            "falsos": falsos, "recusas": recusas, "erros": erros,
            "motivos": motivos}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--verboso", action="store_true")
    ap.add_argument("--corpus", type=Path, default=CORPUS)
    args = ap.parse_args()

    corpus = carregar_corpus(args.corpus)
    fixtures = montar_fixtures(corpus)
    compostas = sum(1 for f in fixtures if f["composta"])
    print(f"[fixtures] {len(fixtures)} telas reconstruídas dos logs do jogo "
          f"({compostas} compostas de 2+ chaves)\n")

    escopos = [
        ("corpus inteiro", Matcher(corpus)),
        ("campanha bonesofarnor+main", Matcher(corpus, campanha="bonesofarnor")),
        ("campanha + aventura A2", Matcher(corpus, campanha="bonesofarnor",
                                           aventura_prefixo="A2")),
    ]
    for nome, m in escopos:
        print(f"  escopo {nome:<30} {len(m):>6,} candidatos")

    # escopo correto: cada fixture contra o conjunto da SUA aventura
    print("\n[escopo por aventura] cada tela casada contra o prefixo dela + genéricos")
    porpre = collections.defaultdict(list)
    for f in fixtures:
        porpre[f["prefixo"]].append(f)
    for taxa in (0.0, 0.05):
        tot = ac = fa = re_ = 0
        for pre, fs in porpre.items():
            if pre is None:
                mm = escopos[1][1]          # genéricas: escopo de campanha
            else:
                mm = Matcher(corpus, campanha="bonesofarnor", aventura_prefixo=pre)
            r = avaliar(mm, fs, taxa, seed=1234, verboso=False)
            tot += r["total"]; ac += r["acertos"]; fa += r["falsos"]; re_ += r["recusas"]
        tot = max(tot, 1)
        print(f"  {'por aventura (correto)':<28} {taxa*100:>5.0f}% "
              f"{100*ac/tot:>7.1f}% {'':>8} {100*fa/tot:>5.1f}% {100*re_/tot:>6.1f}%")

    print(f"\n{'escopo':<28} {'ruído':>6} {'acerto':>8} {'aceita':>8} "
          f"{'ERRA':>6} {'recusa':>7}")
    print("  " + "-" * 72)
    for nome, m in escopos:
        for taxa in (0.0, 0.02, 0.05, 0.10):
            print(f"    ... {nome} @ {taxa*100:.0f}%", end="\r", flush=True)
            r = avaliar(m, fixtures, taxa, seed=1234, verboso=args.verboso)
            t = max(r["total"], 1)
            print(f"  {nome:<28} {taxa*100:>5.0f}% "
                  f"{100*r['acertos']/t:>7.1f}% {100*r['aceitos']/t:>7.1f}% "
                  f"{100*r['falsos']/t:>5.1f}% {100*r['recusas']/t:>6.1f}%")
            if args.verboso and r["erros"]:
                for esperada, res in r["erros"]:
                    print(f"      ESPERADO {esperada}")
                    print(f"      OBTIDO   {res.chave} (score {res.score:.0f}, "
                          f"margem {res.margem:.0f}, razão {res.razao_compr:.2f})")
        print()

    r = avaliar(escopos[1][1], fixtures, 0.05, seed=1234, verboso=False)
    print("motivos de recusa (escopo de campanha, 5% de ruído):")
    for mot, n in r["motivos"].most_common(6):
        print(f"  {n:>5}  {mot}")
    print()
    print("Leitura: 'ERRA' é o que importa — narrar o bloco errado é pior que")
    print("ficar calado, porque o jogador age sobre o que ouve. 'recusa' é o")
    print("silêncio seguro, que o TTS ao vivo pode cobrir.")


if __name__ == "__main__":
    main()
