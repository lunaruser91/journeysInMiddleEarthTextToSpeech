# Narrador automático para *Jornadas na Terra Média*

Narração em voz alta, **100% offline** e em **pt-BR**, dos textos que o app oficial de
*The Lord of the Rings: Journeys in Middle-earth* (Fantasy Flight / Asmodee) mostra
durante a partida. Voz de mago velho.

O app não tem narração em português para o jogo em si — só o Prólogo e os Epílogos de
cada campanha têm áudio gravado. Todo o resto os jogadores leem em voz alta, e é isso
que este projeto substitui.

> ### Aviso de licença — leia antes de qualquer `git add`
>
> Os Termos da Asmodee Digital (§5.3/§5.4) proíbem extrair o conteúdo, **mesmo para uso
> individual**. O texto é obra protegida (FFG + Middle-earth Enterprises) e o áudio
> gerado é obra derivada. FFG/Asmodee já emitiram DMCA contra mods de fãs.
>
> **Este repositório publica um extrator e um renderizador, nunca o conteúdo.** Cada
> pessoa roda a extração sobre a própria instalação, para uso local e não distribuído.
> O `.gitignore` bloqueia corpus, manifests, áudio (em todos os formatos) e assets.

---

## Estado do projeto

| Fase | O que faz | Situação |
|---|---|---|
| 1 | assets do app → corpus pt-BR | **pronta** — 13.018 chaves, 9.740 blocos de narração |
| 2 | corpus → áudio pré-renderizado | **funciona e está medida** — RTF 3,17; uma campanha em ~19 h |
| 3 | tela → OCR → casamento → toca o áudio | **matcher pronto e medido (97,8%)**; falta captura, gatilho e tocador |

---

## Instalação

O Python 3.14 **não tem wheels do PyTorch** — use 3.12 ou 3.13.

```bash
python3.13 -m venv ~/jime-venv
~/jime-venv/bin/pip install -e .
~/jime-venv/bin/pip install -e '.[tts]'
~/jime-venv/bin/pip install -e '.[ocr]'
brew install ffmpeg
```

Um atalho poupa digitação:

```bash
alias jime="~/jime-venv/bin/python"
```

---

## Uso

### Fase 1 — extrair o corpus da sua instalação

```bash
jime fase1_extrair.py "<.../JiME.app/Contents/Resources/Data/StreamingAssets/bundles>" -o corpus/ --lang pt
```

O app é Unity 2022.3 com Mono e **nada é obfuscado**: cada bundle de localização contém
um único `TextAsset` que é um CSV limpo. São 13 idiomas disponíveis.

### Fase 2 — renderizar o áudio

```bash
jime fase2_render.py corpus/corpus_pt.json --campaign bonesofarnor --check-ritmo
```

Estimar antes de deixar a noite rodando:

```bash
jime fase2_render.py corpus/corpus_pt.json --campaign bonesofarnor --dry-run
```

Renderizar blocos avulsos — é a renderização sob demanda que a Fase 3 usa:

```bash
jime fase2_render.py corpus/corpus_pt.json --key "main:G22_SWORD_TRUE"
```

Auditar o resultado, procurando blocos degenerados:

```bash
jime check_ritmo.py saida/audio/manifest.json --mad 2.0
```

### Fase 3 — testar o reconhecimento

Uma tela:

```bash
jime demo.py ~/Downloads/tela.webp --sem-audio     # só OCR + casamento
jime demo.py ~/Downloads/tela.webp                 # toca o áudio, se existir
jime demo.py ~/Downloads/tela.webp --render        # sintetiza na hora se faltar
```

Sem argumento nenhum ele pega a captura mais recente da Área de Trabalho.

Várias telas de uma vez, com taxa de acerto:

```bash
jime lote.py ~/Downloads/*.webp --chaves /tmp/chaves.txt
```

Ver o log de eventos do jogo, útil para gerar fixtures:

```bash
jime ver_log.py --tudo
```

---

## Onde as coisas ficam

O projeto é autocontido. **Nada é escrito fora do repositório.**

```
corpus/          corpus extraído do jogo              (gerado, ignorado)
ref/             voz de referência para clonagem      (ignorado)
saida/           TUDO que é gerado                    (ignorado)
  audio/           render por campanha + manifest.json
  sob-demanda/     blocos sintetizados na hora
  ocr-fixtures/    telas reais com a chave certa
  legado-audio/    renders antigos, preservados

docs/            as notas de investigação
legado/          scripts originais, mantidos para comparação
```

| arquivo | o que faz |
|---|---|
| `fase1_extrair.py` | AssetBundles do jogo → corpus JSON/CSV |
| `fase2_render.py` | corpus → áudio, com cache retomável por hash |
| `glifos.py` | ícones do jogo → palavras faladas; números por extenso; multi-idioma |
| `check_ritmo.py` | detecta blocos cujo ritmo foge da mediana, para regeração |
| `matcher.py` | casa o texto lido da tela com o bloco do corpus |
| `test_matcher.py` | harness: 626 telas reais + ruído de OCR sintético |
| `demo.py` | ciclo completo numa tela: imagem → OCR → matcher → áudio |
| `lote.py` | o mesmo em várias telas, com taxa de acerto |
| `ver_log.py` | lê o log de eventos do jogo |

---

## O que foi medido

Tudo abaixo é medição neste hardware (MacBook Pro M5 Pro, macOS 26 Tahoe), não
estimativa. O detalhe está em [docs/FASE2-MEDICOES.md](docs/FASE2-MEDICOES.md) e
[docs/FASE3-ESTRATEGIA.md](docs/FASE3-ESTRATEGIA.md).

### Desempenho da síntese

| | |
|---|---|
| RTF (relógio ÷ duração do áudio) | **3,17** |
| Bones of Arnor (6,0 h de áudio) | **~19 h de máquina** |
| Corpus completo (44,8 h) | ~142 h — inviável de uma vez, viável por campanha |
| Gargalo | decode autorregressivo do T3: **80–85% do relógio** |

**Cinco hipóteses plausíveis foram testadas e quatro caíram.** Vale ler antes de tentar
otimizar:

- **agrupar frases em chunks de 220 chars** → 11% **mais lento**. O decode cresce
  superlinearmente com o comprimento; o custo fixo por chamada que se queria diluir é
  pequeno demais para compensar.
- **desligar o `AlignmentStreamAnalyzer`** para recuperar a atenção fundida → o modelo
  passou a gerar **quase o dobro** de áudio para o mesmo texto. Ele é o freio que contém
  a geração degenerada, não overhead decorativo.
- **corrigir o vazamento de forward hooks** → o vazamento é real (69 hooks vivos após 23
  frases) mas **não custa tempo**. Vale corrigir por memória, não por velocidade.
- **teto de tokens por frase** → nunca é atingido (0 de 56 frases). É apólice, não
  conserto.
- **`prepare_conditionals` uma vez só** → a única que sobreviveu, e vale ~3%.

Uma armadilha de método: a variação entre duas execuções idênticas neste Mac chega a
**30%**. Diferenças menores que isso só podem ser afirmadas com teste **pareado**.

### Reconhecimento de tela

Medido contra **626 telas reais** reconstruídas dos logs do jogo — sem transcrever
nenhuma à mão.

| ruído de OCR | acerto | **erra** | recusa |
|---:|---:|---:|---:|
| 0% | **97,8%** | 0,6% | 1,6% |
| 2% | 95,5% | 1,4% | 3,0% |
| 5% | 94,4% | 1,9% | 3,7% |
| 10% | 67% | 5% | 27% |

Recusar é o comportamento certo: silêncio é recuperável com TTS ao vivo; narrar o bloco
errado não é, porque o jogador age sobre o que ouve.

O escopo pelo save (campanha, aventura) quase não muda o resultado — quem faz o trabalho
são as travas de comprimento e margem, e o casamento por parágrafo.

---

## Três descobertas que mudaram o projeto

### 1. O jogo mantém um log com as chaves exatas

`~/Library/Application Support/com.fantasyflightgames.jime/SavedGames/<slot>/LogA.txt`
registra cada bloco exibido, com os parâmetros:

```
[3|1|PLACE_PERSON|1|8|0|A2_M1_T1_PLACE|0]
 │ │  │            │ └── tipo 8 = referência a outra chave
 │ │  │            └──── quantos parâmetros
 │ │  └─────────────── a chave, idêntica à do corpus
 │ └────────────────── rodada
 └──────────────────── aventura
```

4.827 linhas conferidas contra o corpus: **100% casam, zero chaves desconhecidas**.

Ele é gravado **a cada rodada** do jogo — provado no IL do `Assembly-CSharp.dll`:
`FlushLogStream` só é chamado por `GameController::CoroutineEndRound` e pelo save. Então
**não serve de gatilho ao vivo**, mas é oráculo exato para validar o matcher e gera
fixtures de graça.

### 2. A tela é a concatenação de várias chaves

O jogo injeta chaves como parâmetro de templates genéricos:

```
corpus  PLACE_PERSON   = "{0}\n\nColoque uma ficha de pessoa conforme indicado."
param   {0}            = A2_M1_T1_PLACE = "[prosa narrativa do bloco]"
```

Casar a tela inteira contra um bloco isolado falha exatamente nesses casos. Por isso o
matcher trabalha **por parágrafo**.

### 3. Um quarto do corpus tinha lixo que o TTS não sabia ler

2.363 blocos (25,9%) contêm caracteres da **Private Use Area** — os ícones da fonte do
jogo, gravados como caracteres literais e não como tags `<sprite=>`, então a limpeza de
marcação não os enxergava. O TTS recebia `"Cada herói testa ; 2"`, sem dizer qual
atributo testar.

`glifos.py` resolve derivando o mapa das 24 chaves `main:GLYPH_*` que o próprio jogo
publica. Como essas chaves são idênticas nos 13 idiomas, **adicionar um idioma é
preencher ~21 palavras**, não reinvestigar o jogo.

Uma armadilha: `GLYPH_FOCUS` é o nome interno de **Agilidade**. Nada no nome sugere isso;
a prova veio de duas chaves independentes cujo único glifo de atributo é `FOCUS`.

E os **números** eram lidos em espanhol ("uno" em vez de "um") mesmo com
`language_id="pt"` — afetava 38,8% do corpus. Corrigido escrevendo por extenso antes de
sintetizar.

---

## Armadilhas já pagas

Não as redescubra.

1. **`setuptools>=81` quebra o `perth`** (marca d'água do Chatterbox) e o modelo **nem
   carrega**. Pinar `setuptools<81`.
2. **Python 3.14 não tem wheels do PyTorch.** Use 3.12 ou 3.13.
3. **O ffmpeg do Homebrew não traz o filtro `rubberband`.** O renderizador detecta e cai
   num equivalente com `asetrate`+`atempo`; o `DSP_VERSION` muda para não misturar cache.
4. **A velocidade entra no `DSP_VERSION`.** Mudar de ideia depois joga fora o render
   inteiro — decida antes de gastar as horas.
5. **No macOS 26 Tahoe**, `CGWindowListCreateImage` e `screencapture` devolvem só o
   wallpaper. Captura exige **ScreenCaptureKit** num `.app` assinado com Team ID real.
6. **O Unity não expõe texto à acessibilidade.** Medido: o `UnityPlayer.dylib` tem 1.353
   seletores Objective-C e **zero** de acessibilidade. Confirmado também no Gloomhaven,
   ou seja, é propriedade da engine. Não perca tempo com `AXStaticText`.
7. **Estimar RTF por it/s engana.** 18 it/s no MPS parecia ótimo e o RTF real deu 2-3.
   Meça relógio contra duração de áudio, e **pareado**.
8. **Nunca clonar dublador famoso.** No Brasil a voz é direito da personalidade (CF art.
   5º XXVIII-a; CC arts. 20–21) e o uso não autorizado é acionável mesmo sem violação de
   direito autoral. O enquadramento é "**um** mago velho", não "*aquele* narrador". A
   referência usada é do LibriVox, domínio público.

---

## O que falta

1. **`trigger.py`** — absdiff → dhash → estabilidade → dedupe com TTL. Desenvolvível com
   imagens salvas, sem captura real.
2. **Harness de OCR com CER real** — hoje o ruído é sintético. Medir Apple Vision contra
   as fixtures diz se estamos na faixa de 1-3%, onde o matcher acerta 97%.
3. **`player.py`** — fila de áudio, repetir/pausar/pular, hotkeys.
4. **Captura no macOS** — ScreenCaptureKit num `.app` assinado. É o item caro (meio dia
   mais a conta de desenvolvedor) e o último a fazer, porque tudo acima roda sem ele.
5. **Piper para os blocos com `{0}`** — 622 blocos só se completam em tempo de jogo.
   Atenção: o Piper **não está instalado** e o `legado/render_piper.py` quebra neste
   ffmpeg (usa `rubberband` incondicionalmente).
6. **Revisar a heurística `narration`** — a dica `_OPTION` descarta 74 blocos de narração
   real (867 palavras); as outras nove dicas de UI juntas descartam 29 palavras.
7. **Decidir sobre prosa × instrução mecânica** — 38,2% dos blocos misturam narrativa e
   regra (prosa, quebra de parágrafo, e então a regra). Separáveis
   por quebra de parágrafo; outros 8% têm a instrução embutida no meio.

---

## Licença

O código é MIT (veja `LICENSE`). O conteúdo do jogo não é distribuído por este
repositório e não é coberto por ela.
