#!/usr/bin/env python3
"""
matcher.py — casa o texto lido da tela (OCR) com o bloco correto do corpus.

## O problema, como ele realmente é

A tela do JiME **não** mostra um bloco do corpus. Mostra a composição de vários:
o jogo pega um template e injeta outras chaves de localização como parâmetros.
Exemplo real, capturado do log do jogo:

    corpus  PLACE_PERSON     = "{0}\\n\\nColoque uma ficha de pessoa conforme indicado."
    corpus  A2_M1_T1_PLACE   = "Você vê a centelha de uma pequena fogueira e uma mulher
                                vestida nos trajes dos Guardiões do Norte. (...)"
    tela    = A2_M1_T1_PLACE + "\\n\\n" + "Coloque uma ficha de pessoa conforme indicado."

Casar a tela inteira contra um bloco isolado falha exatamente nesses casos — e
eles não são raros. Por isso o matcher trabalha em dois níveis:

  1. **por parágrafo** — cada parágrafo da tela é casado separadamente. É o modo
     que respeita a composição, e é o que alimenta a reprodução: toca-se o áudio
     do parágrafo de prosa, e opcionalmente o da instrução.
  2. **tela inteira** — como verificação e para telas de um parágrafo só.

## Escopo

O save (`SavedGame*`, JSON puro) diz `CampaignId` e `CurrentAdventureId`. Isso
reduz os candidatos, mas menos do que parece: medido no corpus, a aventura 3 de
Bones of Arnor tem 44 chaves de história (`A2_*`) e ~2.358 chaves genéricas
(`UI_*`, `PLACE_*`, `ENEMY_*`, `TERRAIN_*`...) que podem aparecer em qualquer
aventura. De 9.740 para ~2.402 — uma redução de 4x, não de 100x.

O escopo ajuda, mas quem desambigua de verdade é o casamento por parágrafo somado
às travas.

## Travas (valem mais que o limiar)

- **razão de comprimento** — sem ela, um fragmento de 10 chars casa 100 com um
  parágrafo de 200 via `partial_ratio`, e narra o bloco errado.
- **margem sobre o segundo colocado** — se os dois primeiros empatam, é melhor
  não narrar do que narrar o errado.

## Normalização

Os dois lados passam pela mesma função: sem acento, sem pontuação, minúsculas, e
**sem os glifos da fonte do jogo** (U+E000–U+F8FF). Isso é essencial: 25,9% dos
blocos contêm ícones que o OCR não lê como texto nenhum. Ver `glifos.py`.
"""
from __future__ import annotations

import json
import re
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path

try:
    from rapidfuzz import fuzz, process
except ImportError:  # noqa: BLE001
    import sys as _sys
    raise SystemExit(
        f"[erro] rapidfuzz não está neste interpretador ({_sys.executable}).\n"
        f"       As dependências do projeto vivem no venv. Rode assim:\n\n"
        f"         ~/jime-venv/bin/python {' '.join(_sys.argv) or 'demo.py ...'}\n\n"
        f"       (ou instale aqui:  {_sys.executable} -m pip install rapidfuzz)")

import glifos

# Atenção: desde o RapidFuzz 3.0 nada é pré-processado por padrão (diferente do
# fuzzywuzzy). A normalização abaixo é obrigatória nos dois lados.

PREFIXO_HISTORIA = re.compile(r"^([AB]\d+)_")
_DIGITOS = re.compile(r"\d+")
PARAGRAFO = re.compile(r"\n\s*\n|\n")


def normalizar(s: str) -> str:
    """Mesma normalização dos dois lados: corpus e OCR."""
    s = glifos.PUA.sub(" ", s)
    s = re.sub(r"\{\d+\}", " ", s)          # placeholders não aparecem na tela
    s = unicodedata.normalize("NFKD", s)
    s = "".join(c for c in s if not unicodedata.combining(c))
    s = s.casefold()
    s = re.sub(r"[^\w\s]", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def paragrafos(texto: str) -> list[str]:
    """Divide a tela em parágrafos. Cada um tende a ser uma chave do corpus."""
    return [p.strip() for p in PARAGRAFO.split(texto) if p.strip()]


@dataclass
class Resultado:
    chave: str | None
    score: float
    margem: float
    razao_compr: float
    aceito: bool
    motivo: str
    texto: str = ""
    segundo: str | None = None


@dataclass
class Matcher:
    """Índice de casamento, opcionalmente escopado por campanha e aventura."""

    corpus: dict
    campanha: str | None = None
    aventura_prefixo: str | None = None
    limiar: float = 82.0
    limiar_seguro: float = 92.0
    razao_min: float = 0.75
    margem_min: float = 5.0
    _chaves: list[str] = field(default_factory=list, init=False)
    _normas: list[str] = field(default_factory=list, init=False)
    _fragmento: list[bool] = field(default_factory=list, init=False)

    def __post_init__(self) -> None:
        for k, v in self.corpus.items():
            if not v.get("narration"):
                continue
            camp, chave = k.split(":", 1)
            if self.campanha and camp not in (self.campanha, "main"):
                continue
            if self.aventura_prefixo:
                m = PREFIXO_HISTORIA.match(chave)
                # aceita as chaves da aventura atual + todas as genéricas
                if m and m.group(1) != self.aventura_prefixo:
                    continue
            # Indexa o bloco inteiro E cada parágrafo dele.
            #
            # Sem isso, a trava de razão de comprimento rejeita o casamento
            # correto sempre que a tela mostra UM parágrafo de um bloco que tem
            # vários: 150 chars contra 300 dá razão 0,50 e cai na trava. Medido:
            # 471 das 536 recusas vinham daí. Cada parágrafo aponta de volta para
            # a chave do bloco, então o áudio tocado continua sendo o do bloco.
            partes = [v["text"]]
            ps = paragrafos(v["text"])
            if len(ps) > 1:
                partes += ps
            for i, parte in enumerate(partes):
                n = normalizar(parte)
                if len(n) < 8:      # curto demais para casar com segurança
                    continue
                self._chaves.append(k)
                self._normas.append(n)
                self._fragmento.append(i > 0)   # 0 = bloco inteiro

    def __len__(self) -> int:
        return len(self._chaves)

    def casar(self, texto_ocr: str) -> Resultado:
        """Casa um trecho já lido da tela contra o escopo."""
        alvo = normalizar(texto_ocr)
        if len(alvo) < 8:
            return Resultado(None, 0, 0, 0, False, "trecho curto demais")

        # score_cutoff poda candidatos ruins e acelera muito; um segundo colocado
        # abaixo do corte significa margem larga, que é o caso favorável mesmo.
        achados = process.extract(alvo, self._normas, scorer=fuzz.partial_ratio,
                                  limit=20, score_cutoff=self.limiar - 12)
        if not achados:
            return Resultado(None, 0, 0, 0, False, "nenhum candidato acima do corte")
        return self._escolher(alvo, [(sc, i) for _t, sc, i in achados])

        # --- as travas ---
        if razao < self.razao_min:
            return Resultado(chave, melhor_score, margem, razao, False,
                             f"razão de comprimento {razao:.2f} < {self.razao_min}",
                             melhor_txt, segundo)
        if melhor_score >= self.limiar_seguro:
            return Resultado(chave, melhor_score, margem, razao, True,
                             "acima do limiar seguro", melhor_txt, segundo)
        if melhor_score >= self.limiar and margem >= self.margem_min:
            return Resultado(chave, melhor_score, margem, razao, True,
                             "acima do limiar, com margem", melhor_txt, segundo)
        if melhor_score < self.limiar:
            return Resultado(chave, melhor_score, margem, razao, False,
                             f"score {melhor_score:.0f} < {self.limiar}",
                             melhor_txt, segundo)
        return Resultado(chave, melhor_score, margem, razao, False,
                         f"margem {margem:.0f} < {self.margem_min}", melhor_txt, segundo)

    def casar_lote(self, trechos: list[str]) -> list[Resultado]:
        """Casa muitos trechos de uma vez, usando todos os núcleos.

        `process.extract` é serial e fica caro quando se avalia um harness
        inteiro (centenas de telas x milhares de candidatos). `cdist` calcula a
        matriz completa em paralelo; os scores cabem em uint8 porque vão de 0 a
        100. O resultado é idêntico ao de chamar `casar` num laço.
        """
        import numpy as np
        from rapidfuzz.process import cdist

        alvos = [normalizar(t) for t in trechos]
        validos = [i for i, a in enumerate(alvos) if len(a) >= 8]
        saida: list[Resultado] = [
            Resultado(None, 0, 0, 0, False, "trecho curto demais") for _ in alvos]
        if not validos:
            return saida

        m = cdist([alvos[i] for i in validos], self._normas,
                  scorer=fuzz.partial_ratio, dtype=np.uint8, workers=-1)
        k = min(20, len(self._normas))
        for linha, i in enumerate(validos):
            row = m[linha]
            top = np.argpartition(row, -k)[-k:]
            top = top[np.argsort(row[top])][::-1]
            saida[i] = self._escolher(alvos[i], [(float(row[j]), int(j)) for j in top])
        return saida

    def _escolher(self, alvo: str, cands: list[tuple[float, int]]) -> Resultado:
        """Escolhe entre os candidatos do topo e calcula a margem por CHAVE.

        Duas sutilezas que só apareceram no primeiro teste com OCR real:

        1. **Desempate pela razão de comprimento.** Um bloco e um parágrafo dele
           dão os dois score 100 no `partial_ratio`; se o desempate for arbitrário
           e cair no bloco inteiro, a razão fica em 0,64 e a trava recusa um
           acerto perfeito. Entre scores iguais, vence quem tem a razão melhor.
        2. **A margem é entre CHAVES distintas, não entre entradas.** O bloco e
           seus parágrafos são a mesma chave; medir margem entre eles daria 0 e
           reprovaria todo casamento bom.
        """
        def razao_de(j: int) -> float:
            t = self._normas[j]
            return min(len(alvo), len(t)) / max(len(alvo), len(t))

        # descarta cedo quem tem número conflitante: senão um candidato errado
        # com score alto rouba a vaga de um certo com score um pouco menor
        limpos = [(sc, j) for sc, j in cands
                  if not self._numeros_conflitam(alvo, self._normas[j])]
        cands = limpos or cands

        melhor_score = max(sc for sc, _ in cands)
        empatados = [j for sc, j in cands if sc == melhor_score]
        j1 = max(empatados, key=razao_de)
        chave = self._chaves[j1]

        # melhor score entre candidatos de OUTRA chave
        outros = [(sc, j) for sc, j in cands if self._chaves[j] != chave]
        s2, j2 = max(outros, default=(0.0, j1))
        return self._decidir(alvo, melhor_score, s2, j1, j2)

    @staticmethod
    def _numeros_conflitam(alvo: str, cand: str) -> bool:
        """Os números do candidato contradizem os da tela?

        Trava descoberta com telas reais: o bloco `A11_SECTION_0` contém
        "Coloque a peça 205B conforme indicado", e a tela mostrava 208B. Um
        caractere de diferença dá partial_ratio 97,3 e razão 1,00 — passa em
        todas as outras travas e narra o bloco errado.

        Números são semanticamente decisivos aqui: identificam a peça do mapa, a
        quantidade de dano, a dificuldade do teste. Errar o número é pior que
        calar, porque o jogador age sobre ele.

        A regra é assimétrica de propósito: só bloqueia quando o CANDIDATO tem
        dígitos literais. Os templates do jogo trazem `{0}`, que a normalização
        remove, e eles precisam continuar casando com a tela que mostra o valor.
        """
        n_cand = set(_DIGITOS.findall(cand))
        if not n_cand:
            return False
        n_alvo = set(_DIGITOS.findall(alvo))
        if not n_alvo:
            return False
        return n_cand != n_alvo

    def _decidir(self, alvo: str, s1: float, s2: float, j1: int, j2: int) -> Resultado:
        """Aplica limiar e travas. Compartilhado por `casar` e `casar_lote`."""
        margem = s1 - s2
        melhor_txt = self._normas[j1]
        razao = min(len(alvo), len(melhor_txt)) / max(len(alvo), len(melhor_txt))
        chave, segundo = self._chaves[j1], self._chaves[j2]
        if self._numeros_conflitam(alvo, melhor_txt):
            return Resultado(chave, s1, margem, razao, False,
                             "números não batem com os da tela", melhor_txt, segundo)
        # Um fragmento (parágrafo solto de um bloco) casa mais fácil e erra mais:
        # indexá-los subiu o acerto de 80% para 86%, mas dobrou o erro de 0,4%
        # para 1,0%. Exigir deles o limiar seguro recupera a precisão sem perder
        # o ganho de cobertura.
        if self._fragmento[j1] and s1 < self.limiar_seguro:
            return Resultado(chave, s1, margem, razao, False,
                             f"fragmento com score {s1:.0f} < {self.limiar_seguro}",
                             melhor_txt, segundo)
        if razao < self.razao_min:
            return Resultado(chave, s1, margem, razao, False,
                             f"razão de comprimento {razao:.2f} < {self.razao_min}",
                             melhor_txt, segundo)
        if s1 >= self.limiar_seguro:
            return Resultado(chave, s1, margem, razao, True,
                             "acima do limiar seguro", melhor_txt, segundo)
        if s1 >= self.limiar and margem >= self.margem_min:
            return Resultado(chave, s1, margem, razao, True,
                             "acima do limiar, com margem", melhor_txt, segundo)
        if s1 < self.limiar:
            return Resultado(chave, s1, margem, razao, False,
                             f"score {s1:.0f} < {self.limiar}", melhor_txt, segundo)
        return Resultado(chave, s1, margem, razao, False,
                         f"margem {margem:.0f} < {self.margem_min}", melhor_txt, segundo)

    def casar_tela(self, texto_ocr: str) -> list[Resultado]:
        """Casa uma tela inteira, parágrafo a parágrafo.

        É este o modo que respeita a composição do jogo: a prosa costuma vir de
        uma chave e a instrução de outra. Devolve um resultado por parágrafo, na
        ordem — que é também a ordem em que o áudio deve tocar.
        """
        return [self.casar(p) for p in paragrafos(texto_ocr)]


def escopo_do_save(save_path: Path) -> tuple[str | None, int | None]:
    """Lê campanha e aventura atuais do save do jogo (JSON puro)."""
    j = json.loads(Path(save_path).read_text(encoding="utf-8"))
    return j.get("CampaignId"), j.get("CurrentAdventureId")


def carregar_corpus(caminho: Path) -> dict:
    return json.loads(Path(caminho).read_text(encoding="utf-8"))
