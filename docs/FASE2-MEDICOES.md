# Fase 2 — o que foi medido sobre o desempenho do Chatterbox

Este documento fecha o "🔴 PROBLEMA ABERTO" do §5 do briefing. Tudo aqui é
medição neste hardware, não estimativa. Onde a medição contraria o briefing, a
medição vence — e o briefing está anotado como corrigido.

**Hardware:** MacBook Pro 14" M5 Pro, 24 GB, macOS Tahoe 26.5.2
**Pilha:** Python 3.13.13, torch 2.6.0, transformers 5.2.0, chatterbox-tts 0.1.7, MPS
**Parâmetros:** `exaggeration=0.45`, `cfg_weight=0.35`, seed 1234, ref de 12 s

---

## 1. A armadilha metodológica que quase invalidou tudo

A primeira rodada mediu os quatro modos em sequência, no mesmo processo. O
resultado foi limpo, coerente e **falso**: cada modo era mais lento que o
anterior, em ordem perfeita (117 → 143 → 202 → 218 ms/token). Duas causas se
somaram — havia carga concorrente na máquina, e o efeito da ordem não estava
controlado.

Refazendo com **um processo por modo** e **ordem contrabalanceada**
(`A B C D D C B A`), a deriva ficou explícita:

| modo | 1ª passagem | 2ª passagem | deriva |
|---|---|---|---|
| A | RTF 3,64 | RTF 3,23 | −11,3% |
| B | RTF 3,10 | RTF 3,57 | +15,0% |
| C | RTF 3,35 | RTF 4,34 | **+29,5%** |
| D | RTF 4,21 | RTF 4,43 | +5,3% |

**A deriva entre duas execuções do mesmo modo chega a 30%.** Isso é maior do que
quase todos os efeitos que se quer medir. Consequência prática, e a lição mais
importante deste documento:

> Nenhuma diferença abaixo de ~30% pode ser afirmada comparando execuções
> separadas neste Mac. Diferenças menores exigem **desenho pareado** — a mesma
> frase, nas duas configurações, uma logo após a outra, alternando a ordem.

Isto se soma à armadilha nº 9 do briefing ("estimar RTF por it/s engana"): não
basta medir relógio contra áudio, é preciso medir **pareado**.

## 2. Onde o tempo realmente vai

Perfilamento por estágio, média das duas passagens:

| estágio | fatia do relógio |
|---|---|
| `t3.inference` (decode autorregressivo) | **80–85%** |
| `s3gen.inference` (flow matching + vocoder) | 11–16% |
| `prepare_conditionals` | ~1% (depois da correção) |
| watermark (perth) | <0,5% |

**O decode do T3 é o problema inteiro.** Qualquer otimização que não o ataque é
ruído estatístico. Isso descarta de saída o watermark e a cadeia de DSP como
alvos.

## 3. As duas hipóteses do briefing

### §5.1 — condicionais recalculadas a cada chamada: **confirmada, mas pequena**

O código confirma: `mtl_tts.py:269-270` chama `prepare_conditionals()` sempre que
recebe `audio_prompt_path`, ou seja, uma vez por frase. Medido, o estágio cai de
**10,7 s para 1,1 s** num lote de 13 frases.

Só que isso era ~4% do relógio, não o gargalo. **Ganho líquido em RTF: ~3%.**
Vale aplicar porque é grátis, não porque resolve.

### §5.2 — juntar frases em chunks de ~220 chars: **refutada**

| | RTF médio | chamadas |
|---|---|---|
| uma frase por chamada (B) | 3,34 | 13 |
| chunks de 220 chars (C) | **3,84** | 7 |

Agrupar frases **piorou 11%**, apesar de quase metade das chamadas. O
perfilamento mostra por quê: `s3gen` melhorou (44 s → 30 s), mas o `t3` piorou
mais (188 s → 212 s). O decode é autorregressivo com atenção *eager* e cache KV
crescente — dobrar o comprimento **mais que dobra** o custo. O custo fixo por
chamada que se queria diluir é pequeno demais para compensar.

> Correção ao briefing §5.2: chunking não é uma alavanca, é um retrocesso.
> Manter uma chamada por frase.

## 4. Uma terceira hipótese, encontrada no código e também refutada

`t3.py` seta `self.compiled = False` no início de **cada** `inference()`,
reconstruindo o `AlignmentStreamAnalyzer`; o `__init__` dele registra 3
`register_forward_hook` (`alignment_stream_analyzer.py:80-84`) e **nunca remove
os anteriores**.

O vazamento é real e foi medido: **69 hooks vivos após 23 frases**, contra 3 com
a correção. Como cada hook faz `output[1].cpu()` por token, parecia o gargalo.

Não é. Duas evidências:

- Dentro de uma execução do modo A, o ms/token **não cresce**: 138,9 na primeira
  chamada, 128,2 no último terço — apesar de os hooks irem de 3 a 69.
- O modo com a correção (D) ficou **mais lento**, não mais rápido.

**Veredito:** é um defeito de higiene, não de desempenho. Continua valendo a pena
corrigir, porque cada hook retido segura tensores de atenção e numa maratona de
milhares de blocos isso é vazamento de memória — mas sem alegar ganho de tempo.

## 5. A alavanca que parecia grande — e é uma armadilha

O `AlignmentStreamAnalyzer` força `_attn_implementation='eager'` no transformer
**inteiro**, desligando a atenção fundida (SDPA) nas 30 camadas, e faz 3
sincronizações GPU→CPU por token. Desligá-lo parecia o maior ganho disponível.

Teste pareado (mesma frase, mesma seed, as duas configurações em sequência):

| | relógio | áudio gerado | RTF |
|---|---|---|---|
| baseline | 34,5 s | 14,3 s | 2,41 |
| sem o analyzer | 136,0 s | **26,7 s** | 5,10 |

Repare no áudio: **o modelo gerou quase o dobro de som para o mesmo texto.** O
analyzer não é overhead decorativo — é o freio que interrompe a geração
degenerada. Sem ele o modelo entra em cauda longa e alucina. Desligá-lo piora a
velocidade *e* a qualidade.

> Isto também reinterpreta a "anomalia a investigar" do briefing (§5, o bloco
> `A1_THREAT_1` a 1,00 palavra/s com `🚨 Detected 2x repetition → forcing EOS`):
> o analyzer não causou o problema, ele o **conteve**. Sem o freio, aquele bloco
> teria saído muito pior.

## 6. Situação e opções

Medição do renderizador de produção em 15 blocos reais de Bones of Arnor:
**733 s de síntese para 231 s de áudio → RTF 3,17**, ritmo de 127 palavras/min,
zero falhas.

| campanha | blocos | palavras | áudio | render |
|---|---:|---:|---:|---:|
| main | 2.178 | 71.002 | 9,3 h | 29,6 h |
| poisonpromise | 1.405 | 51.505 | 6,8 h | 21,5 h |
| spreadingwar | 1.150 | 49.715 | 6,5 h | 20,7 h |
| bonesofarnor | 1.193 | 45.556 | 6,0 h | **19,0 h** |
| hauntingofdale | 1.212 | 45.415 | 6,0 h | 18,9 h |
| embercrown | 1.056 | 43.575 | 5,7 h | 18,2 h |
| shadowedpaths | 924 | 34.878 | 4,6 h | 14,5 h |
| **total** | **9.118** | **341.646** | **44,8 h** | **142,3 h** |

O corpus inteiro continua inviável de uma vez. **Uma campanha, não.**

Não existe, no caminho medido, nenhum ganho de ordem de grandeza. As opções
reais, em ordem de custo:

1. **Renderizar por campanha, sob demanda.** Bones of Arnor: 6,0 h de áudio em
   ~19 h de máquina. Duas noites, para a campanha que se vai jogar. Isto torna o
   projeto viável hoje, sem escrever mais nada.
2. **Piper para as campanhas de menor valor** (RTF 0,03). Mas veja §7: o Piper
   não está instalado nesta máquina e o `render_piper.py` tem um defeito.
3. **Batching no T3.** É a única alavanca com potencial de ordem de grandeza. O
   decode é fortemente *memory-bound* (536 M parâmetros em fp32 = 2,14 GB lidos
   por passo, independentemente do lote), então há folga para 8–16 linhas antes
   de virar *compute-bound*. Custo: ~40 linhas para destravar o laço, mais uma
   máscara de atenção que hoje não existe em lugar nenhum do caminho T3, mais
   reescrever ou desligar o `AlignmentStreamAnalyzer` — que lê só a linha 0 do
   lote. Estimo 150 linhas delicadas. **Não medido; é um projeto, não um ajuste.**

## 6b. O bloco degenerado: a causa era a seed, não o teto de tokens

`bonesofarnor:A1_THREAT_1` saía a 43,2 s para 43 palavras no renderizador antigo
e sai a ~21 s no novo. Entre os dois mudaram duas coisas ao mesmo tempo — o teto
de tokens por frase (1000 fixo -> orçado pelo tamanho) e o tratamento da seed
(semeada uma vez antes do laço -> resetada por bloco). Atribuí a melhora ao teto.
**Estava errado, e o experimento mostra por quê.**

O desenho não precisou ser um 2x2: "seed global" não é um tratamento, é um
sorteio desconhecido — o estado do RNG no início de um bloco é só consequência do
que os blocos anteriores consumiram. Variar a seed já cobre esse fator, e todo o
orçamento de gerações vai para repetições, que é onde está o poder.

Bloco inteiro, frase a frase, 14 seeds, teto 1000 contra teto adaptativo:

| | teto 1000 | adaptativo |
|---|---|---|
| blocos degenerados (razão > 1,4) | **0/14** | **0/14** |
| razão mediana | 1,05 | 1,05 |
| pior caso | 1,12 | 1,12 |
| frases que estouraram o orçamento | — | **0/56** |

As duas colunas saíram **idênticas em todas as 14 seeds** (20,4/20,4, 18,0/18,0…).
Com a mesma seed e o teto nunca sendo atingido, a geração é determinística e
produz o mesmo áudio. Ou seja: **o teto adaptativo é inerte na operação normal.**

Conclusões, nesta ordem de confiança:

1. **O teto de tokens não consertou nada** — ele nunca chega a agir. A melhora de
   43,2 s para 21 s veio do outro fator: uma trajetória de amostragem diferente.
   Os 43,2 s foram um **sorteio raro**, não um defeito sistemático.
2. **O orçamento adaptativo é seguro e vale manter**, mas como apólice, não como
   conserto: custo zero na operação normal (0/56 frases o atingem, nenhuma
   truncada) e limita o prejuízo se a degeneração ocorrer.
3. **A degeneração é mais rara que 1/14 para este bloco.** Somando os três
   experimentos — 12 seeds na frase com ícone, 20 pares no teste amplo, 14 seeds
   no bloco inteiro — só houve 2 eventos em ~60 tentativas, e nenhum reproduziu o
   caso original.
4. Logo, **a única defesa real é a detecção a posteriori**: `--check-ritmo` mede
   palavras/s e regera com outra seed. É o mecanismo certo para um evento raro e
   estocástico — não dá para preveni-lo, dá para pegá-lo.

## 6c. Ícones do jogo no texto — corrigido em `glifos.py`

**2.363 dos 9.118 blocos (25,9%)** contêm 3.303 caracteres da Private Use Area
(U+F460–U+F47A): os símbolos da fonte do jogo. A limpeza da Fase 1 remove tags
`<sprite=>` mas não enxerga caracteres literais, então eles chegavam ao TTS.

O mapeamento veio das 24 chaves `main:GLYPH_*` do próprio jogo, validado contra a
legenda do manual pt-BR. Duas entradas que eu havia inferido estavam erradas e o
manual corrigiu: `RANGED` é "De Alcance" (não "à distância") e `TRINKET` é
"Apetrecho" (não "bugiganga").

Sutileza que quebraria a Fase 3: o áudio DIZ "testa Agilidade", mas a tela MOSTRA
o ícone. O índice de casamento (`norm` no manifest) é construído com os glifos
REMOVIDOS, não substituídos — senão o OCR nunca casaria.

## 7. Defeitos encontrados de passagem

- **`render_piper.py` quebra neste Mac.** A `WIZARD_CHAIN` (linha 17) usa
  `rubberband=` de forma incondicional, e o ffmpeg do Homebrew não traz esse
  filtro — o `render_corpus.py` já detectava e caía num equivalente, mas o do
  Piper ficou para trás. Todo bloco falharia.
- **Piper não está instalado** neste venv, e não há vozes `.onnx` baixadas. O
  "fallback ao vivo" da Fase 3 ainda não existe na prática.
- **O render em Piper de Bones of Arnor descrito no briefing** (1.174 arquivos,
  125 MB, 5,8 h) **não está nesta máquina.** Só existem os 20 blocos de teste do
  Chatterbox.
- **`manifest.json` não estava no `.gitignore`** do briefing, e ele contém o
  texto integral de cada bloco — é o corpus com outro nome. Corrigido.

## 8. Reproduzir

Os scripts de medição ficam fora do repositório (são descartáveis), mas o método é:

```bash
# perfil por estágio, um modo por processo, ordem contrabalanceada
for m in A B C D D C B A; do python3 bench2.py $m 4; done

# teste pareado — o único desenho que resolve diferenças <30%
python3 bench3.py 12
```

O detector de ritmo, esse é permanente:

```bash
python3 check_ritmo.py audio/manifest.json --mad 2.0
```
