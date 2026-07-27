# Narrador automático para *Jornadas na Terra Média* — briefing para o Claude Code

> Cole este arquivo inteiro como primeiro prompt no repositório novo.
> Ele contém tudo que já foi descoberto, o que já funciona, o que falta,
> e principalmente as armadilhas que já custaram tempo — não as redescubra.

---

## 1. Objetivo

Narrar automaticamente, em voz alta e **100% offline**, os textos que o app oficial do
board game *The Lord of the Rings: Journeys in Middle-earth* (Fantasy Flight / Asmodee)
mostra durante a partida. Voz de **homem velho, mago de fantasia**, em **pt-BR**.

O app não tem narração em português nenhuma — só o inglês tem áudio, e apenas na
introdução e no epílogo. Os jogadores leem tudo em voz alta. O projeto substitui isso.

Uso estritamente pessoal, sem distribuição (ver §8).

## 2. Ambiente real do usuário

| | |
|---|---|
| Máquina | MacBook Pro 14", **Apple M5 Pro**, 24 GB |
| SO | **macOS Tahoe 26.5.2** |
| Jogo | Steam para macOS, `~/Library/Application Support/Steam/steamapps/common/Journeys in Middle-earth/JiME.app` |
| Python do projeto | **3.13 via Homebrew** em `~/jime-venv` (o 3.14 do sistema **não** tem wheels do PyTorch) |
| Código atual | `~/jime` |
| Saída de áudio | `~/Documents/journeys/entrega/` |
| Windows | precisa continuar sendo alvo possível: núcleo em Python puro, camada de captura isolada |

## 3. Arquitetura em três fases

```
FASE 1 (PRONTA)   assets do app → corpus pt-BR em JSON/CSV
FASE 2 (EM CURSO) corpus → áudio pré-renderizado, uma pasta por campanha
FASE 3 (A FAZER)  captura de tela → OCR → casamento com o corpus → toca o áudio
```

---

## 4. FASE 1 — CONCLUÍDA

### O que se descobriu (não repita a investigação)

O app é **Unity 2022.3.62f2 com Mono**. O conteúdo fica em `JiME.app/Contents/Resources/Data`.
**Nada é obfuscado.** O caminho é trivial e já está resolvido:

1. `Data/StreamingAssets/bundles/manifest.dat` é **JSON puro**, mapeando 137 AssetBundles.
2. 92 deles são de localização, nomeados `localization/<campanha>/<idioma>` — 13 idiomas,
   incluindo `pt`. O campo `filename` dá o nome real (hash) do arquivo na mesma pasta.
3. Cada bundle contém **um único `TextAsset`** que é um **CSV limpo**: cabeçalho
   `KEY,Portuguese`, uma linha por bloco de texto.
4. Extração com **UnityPy** (`pip install UnityPy`). Sem AssetRipper, sem ILSpy,
   sem chave de desobfuscação.

> Isso invalida a suposição inicial (baseada nos apps irmãos da FFG, como o Mansions of
> Madness, cujos TextAssets são obfuscados com uma constante inteira). O JiME não é assim.

### Campanhas

`bonesofarnor`, `embercrown`, `shadowedpaths`, `spreadingwar`, `hauntingofdale`,
`poisonpromise` e `main` (textos comuns e de interface).

### Números do corpus pt-BR

| | |
|---|---|
| Chaves totais | 13.021 |
| Blocos de narração | 9.740 (9.549 textos únicos) |
| Palavras de narração | 366.965 |
| Blocos com placeholder `{0}` | 622 (6,4% da narração) |
| A renderizar (narração sem placeholder) | **9.118 blocos / 341.646 palavras** |

Validação feita: a frase exata de um screenshot do jogo foi localizada em
`bonesofarnor:A10_THREAT_3`, íntegra, com acentuação e nomes próprios corretos.

### Script pronto: `jime_corpus.py`

```bash
python3 jime_corpus.py <Data/StreamingAssets/bundles> -o corpus/ --lang pt
```

Produz `corpus/corpus_pt.json` (chave `campanha:KEY`) e um CSV por campanha. Cada entrada:

```json
{
  "key": "A10_THREAT_3", "campaign": "bonesofarnor",
  "text": "[texto do bloco]",
  "placeholders": [], "narration": true, "words": 87, "chars": 512
}
```

`narration` é heurística: descarta chaves com `_BUTTON`, `_TOOLTIP`, `_LABEL` etc.,
exige ≥8 palavras e pontuação final. O script também limpa a marcação do jogo
(`[i]`, `[b]`, `<sprite=...>`).

**A fazer na Fase 1 (menor):** revisar a heurística `narration` contra os CSVs
(hoje ninguém auditou os falsos positivos/negativos), e decidir o que fazer com
os 622 blocos com `{0}` — hoje eles só são marcados.

---

## 5. FASE 2 — EM CURSO, COM UM PROBLEMA DE DESEMPENHO ABERTO

### Voz escolhida (decidida por comparação cega de amostras)

- **Modelo:** `chatterbox-tts` (Chatterbox Multilingual, `language_id="pt"`), **licença MIT**,
  rodando em **MPS**.
- **Referência de clonagem:** 12 s limpos do narrador de *Páginas Recolhidas*
  (Machado de Assis) no **LibriVox — domínio público**. Arquivo `ref/REF_paginasrecolhidas.wav`,
  24 kHz mono, já filtrado (`highpass=70`, `afftdn`, `loudnorm I=-19`).
- **Por que esse:** de 13 leitores em português medidos no acervo, 9 eram vozes femininas.
  Sobraram dois graves; este tem F0 mediano de **123,2 Hz**.
- **Cadeia de DSP "mago-v1"** aplicada depois da síntese, via ffmpeg.

> ⚠️ Nunca clonar dublador famoso. No Brasil a voz é direito da personalidade
> (CF art. 5º XXVIII-a; CC arts. 20–21) e o uso não autorizado é acionável mesmo sem
> violação de direito autoral. O enquadramento é "**um** mago velho", não "*aquele* narrador".

### Scripts prontos

- `render_corpus.py` — renderiza o corpus com Chatterbox + DSP. Cache por hash
  (`modelo|voz|DSP_VERSION|params|texto`), retomável, manifest incremental,
  `--dry-run`, `--campaign`, `--limit`, `--device`.
- `render_piper.py` — mesma coisa com **Piper** (`pt_BR-cadu-medium`). ~90× mais rápido,
  sem clonagem. É a **voz de fallback ao vivo da Fase 3** e a trilha provisória.
- `setup_mac.sh` — instala tudo do zero (brew, ffmpeg, Python 3.12/3.13, venv, deps).

### O que já foi renderizado

- **Bones of Arnor completa em Piper**: 1.193 blocos → 1.174 arquivos (19 textos
  repetidos compartilham áudio pelo hash), **5,8 h de narração, 125 MB**, zero truncados.
- **20 blocos em Chatterbox no Mac do usuário** + 10 blocos de validação em CPU.

### Consistência medida (o clone não deriva)

| Lote | F0 médio | Desvio | Faixa |
|---|---|---|---|
| Referência humana LibriVox | 123,2 Hz | — | — |
| 10 blocos de validação (CPU) | 122,3 Hz | 8,0 Hz | 109–139 |
| 20 blocos no M5 Pro (MPS) | 120,7 Hz | 6,2 Hz | 108–133 |

Ritmo médio: **2,03 palavras/s (~122 ppm)**, desvio 0,36 — adequado para narração.

### 🔴 PROBLEMA ABERTO: o render é ~4× mais lento que o estimado

Medição real no M5 Pro: **20 blocos = 748 s de relógio para 356 s de áudio → RTF ≈ 2,1**.
A estimativa de projeto assumia RTF 0,45. Extrapolando:

| | estimado | **real** |
|---|---|---|
| Bones of Arnor (5,8 h de áudio) | 2,4 h | **~12 h** |
| Corpus completo (40,7 h de áudio) | 18 h | **~85 h** |

85 horas de máquina é inviável. **Esta é a primeira tarefa do repositório.**

**Duas hipóteses de otimização, ainda NÃO validadas** (o benchmark foi interrompido):

1. **Condicionais recalculadas a cada chamada.** `render_corpus.py` chama
   `model.generate(..., audio_prompt_path=REF)` **uma vez por frase**. Pela assinatura
   `generate(self, text, language_id, audio_prompt_path=None, ...)` e
   `prepare_conditionals(self, wav_fpath, exaggeration=0.5)`, passar o `audio_prompt_path`
   refaz o condicionamento de voz (voice encoder + tokenizer sobre 12 s de áudio) em
   **todas** as ~5.000 chamadas. Correção: chamar `prepare_conditionals(REF, exaggeration=...)`
   **uma vez** e depois gerar **sem** `audio_prompt_path`.
2. **Chamadas curtas demais.** Hoje é uma chamada por frase. Juntar frases em blocos de
   ~220 caracteres reduz o número de chamadas e o overhead fixo, e tende a melhorar a
   prosódia. Manter um teto (~300 chars) porque modelos autorregressivos derivam em
   textos longos.

Benchmark a executar (A = como está hoje, B = com cache de condicionais,
C = cache + chunks de 220 chars), medindo o mesmo bloco nos três modos.

**Outras alavancas, se A+B não bastarem:**

- Verificar se o gargalo é o T3 (amostragem, ~18 it/s no MPS) ou o s3gen/vocoder — perfilar antes de otimizar.
- `torch.float16` no MPS.
- Processar em lote (batch) várias frases numa chamada, se o modelo suportar.
- Aceitar o Piper (`RTF 0,03`) para as campanhas de menor valor e reservar o clone para as que o usuário for jogar.
- Renderização sob demanda: gerar na primeira vez que o bloco aparece em jogo e cachear.

### Anomalia a investigar

O bloco `bonesofarnor:A1_THREAT_1` saiu com **1,00 palavra/s** (43 palavras em 43 s),
contra a média de 2,03. No log da geração aparece
`🚨 Detected 2x repetition of token 6405 → forcing EOS`. Suspeita: repetição/alongamento
do modelo. Vale um detector automático — sinalizar blocos cujo `palavras/duração` fuja
mais de 2 desvios da mediana e regerá-los com outra seed.

---

## 6. FASE 3 — PROJETADA, NÃO INICIADA

### Restrição que define a arquitetura

O app **não expõe texto nenhum ao macOS**: Unity rasteriza toda a UI numa única superfície
de GPU, então não há `AXStaticText` nem UI Automation. (A Unity 6.3 ganhou suporte nativo a
leitor de tela, mas é opt-in manual por tela e este app é de 2019 em manutenção.)
Confirmar em 10 minutos com o Accessibility Inspector e fechar essa porta.

Logo: **a tela é o gatilho; o corpus é a fonte da verdade do texto.**

### Captura — o ponto mais espinhoso no Tahoe

- No **macOS 26 Tahoe**, `CGWindowListCreateImage`, `CGDisplayCreateImage` e o CLI
  `screencapture` devolvem **só o wallpaper** — janelas de app ficam invisíveis. Isso
  **inviabiliza `mss`, `pyautogui` e `PIL.ImageGrab`**. Não perca tempo com eles.
- Caminho válido: **ScreenCaptureKit**, `SCContentFilter(desktopIndependentWindow:)` para
  capturar só a janela do jogo e `SCScreenshotManager.captureImage` para frames sob demanda.
  10 fps basta (humano precisa de ≥300 ms para registrar texto novo).
- **TCC vai custar tempo**: a permissão se liga ao processo responsável (rodar pelo Terminal
  concede ao Terminal), e binários com assinatura ad-hoc estão bloqueados desde o Sequoia.
  O caminho confiável é um **`.app` empacotado e assinado com Team ID real** (conta de
  desenvolvedor gratuita basta), com `NSScreenCaptureUsageDescription` e hardened runtime.
- Windows (portabilidade): `zbl` ou `windows-capture` (captura por nome de janela sobre
  Windows.Graphics.Capture). **Evitar BitBlt/PrintWindow** — devolvem preto em janelas Unity.

### OCR

- **macOS: Apple Vision** (`VNRecognizeTextRequest`), offline, `pt-BR` nativo, 130–210 ms,
  aceita `customWords` (alimentar com os nomes próprios tolkienianos). Em Python via
  [`ocrmac`](https://github.com/straussmaximilian/ocrmac); um binário Swift é mais limpo.
- Portátil: **RapidOCR** (PP-OCRv5 latin, ~19 MB, Apache-2.0). Windows: `Windows.Media.Ocr`.
- **Não usar VLM local** (Qwen3-VL etc.): alucina texto plausível, o que num narrador é pior
  que erro de OCR e indetectável; e é ~10× mais lento.
- **Pré-processamento importa 10–20×; o motor, ~2×.** Receita: crop fixo → cinza (testar
  canais R/G/B isolados) → achatamento de fundo (`bg = medianBlur(gray,31)`; `subtract`;
  normalizar) → Otsu → inverter se claro-sobre-escuro → upscale Lanczos até **~35 px de
  altura de caractere e parar** (4× piora). **Nunca threshold adaptativo antes de achatar
  o fundo** — ele alucina texto a partir do grão do pergaminho.

### Gatilho e deduplicação

```
captura 5–10 Hz
 → absdiff (>0,5% dos pixels com delta >25)      [a cada tick, barato]
 → dhash(hash_size=16), Hamming ≤ 2              [só quando absdiff dispara]
 → estabilidade: 3 frames idênticos              [espera a animação do texto]
 → se o novo texto começa com o antigo → substitui, não narra de novo
 → OCR
 → significância: ≥8 chars, ≥2 palavras, ≥35% alfanumérico   [descarta HUD/timer]
 → dedupe: hash normalizado em deque(maxlen=30) com TTL 90–120 s
 → matching no corpus
```

`hash_size=16`, não o padrão 8 (64 bits são grosseiros para uma caixa de 1000×200).
**Não usar phash** — a DCT apaga justamente as bordas de glifo. **TTL é essencial**:
sem ele, "Sim"/"Não" e frases recorrentes ficam mudas para sempre.

### Casamento com o corpus

**`rapidfuzz`** — 1 query contra alguns milhares de opções custa 1–3 ms. Nada de embeddings
(eles são invariantes à forma superficial, o oposto do que se precisa contra erros de OCR).

- Scorer: `fuzz.partial_ratio`. **Evitar `token_set_ratio`** — devolve 100 sempre que um
  conjunto de tokens é subconjunto do outro.
- Normalizar os dois lados igual: NFKD, **remover acentos**, `casefold()`, pontuação → espaço.
  O campo `norm` já vem pronto no `manifest.json` da Fase 2, com exatamente essa normalização.
- Limiares: **≥92** toca; **82–92** só com as travas; **<82** cai no TTS ao vivo.
- **As duas travas valem mais que o limiar:** (a) razão de comprimento ≥0,75 — sem ela um
  fragmento de 10 chars casa 100 com um parágrafo de 200 e narra o bloco errado;
  (b) margem ≥5 pontos sobre o segundo colocado.
- **Escopo pelo save**: os saves são **JSON puro não criptografado** em
  `Contents/Resources/Data/SavedGames`, com campos como `CurrentAdventureId` e
  `CampaignDifficulty`. Um watcher de arquivo reduz o corpus candidato de milhares de blocos
  para dezenas e torna o matching praticamente infalível. Não serve como gatilho (blocos de
  meio de missão provavelmente não gravam save), mas serve como contexto.
- Atenção: **desde o RapidFuzz 3.0 nada é pré-processado por padrão** (diferente do fuzzywuzzy).

### Fallback ao vivo

Os 622 blocos com `{0}` só se completam em tempo de jogo. Para eles e para OCR sem match:
**Piper `pt_BR-cadu-medium`** (RTF 0,03, ~40 ms, 300 MB de RAM). Mesma cadeia de DSP.

### Interface pedida

**Janelinha de status**: mostra a região capturada, as últimas frases lidas e botões
repetir / pausar / pular. Prever também hotkeys globais e um modo "só narra quando eu
apertar" — os jogadores às vezes querem ler no próprio ritmo.

### Referências para aproveitar

| Projeto | O que tirar |
|---|---|
| [LOTR-Lector](https://github.com/rpiotrow96/LOTR-Lector) | Mesmo jogo. Heurística de detecção da borda do texto. Ignorar BitBlt e gTTS (é online) |
| [UGTLive](https://github.com/SethRobinson/UGTLive) | Melhor par arquitetural: detectar mudança → agir "quando as coisas assentam" |
| [Game2Text](https://github.com/mathewthe2/Game2Text) | Precedente direto de casamento OCR × script conhecido |
| [oneocr SmartDedup](https://huggingface.co/MattyMroz/oneocr/blob/main/_archive/dedup.py) | O algoritmo de estabilização/dedupe com constantes reais |
| [Translumo](https://github.com/ramjke/Translumo) | Ensemble de motores de OCR com scorer — alavanca de precisão para v2 |

---

## 7. Armadilhas já pagas (não repita)

1. **`ffmpeg` do Homebrew não traz o filtro `rubberband`.** O `render_corpus.py` já detecta
   e cai num equivalente com `asetrate`+`aresample`+`atempo` — que desloca altura e formantes
   juntos, exatamente o que `formant=shifted` fazia. Duração idêntica (38,01 s nos dois).
   `DSP_VERSION` muda para `mago-v1f` no fallback, para não misturar cache.
2. **`setuptools>=81` quebra o `perth`** (a marca d'água do Chatterbox) com
   `No module named 'pkg_resources'`, e aí o modelo **nem carrega**. Pinar `setuptools<81`.
3. **Python 3.14 não tem wheels do PyTorch.** Usar 3.12 ou 3.13.
4. **`antlr4-python3-runtime` não compila** com o setuptools do Debian (`AttributeError:
   install_layout`) — instalar dentro de um venv limpo, não no Python do sistema.
5. **Opus decodifica sempre a 48 kHz.** Ao testar cadeias de DSP com `asetrate`, garanta que
   a entrada está na taxa que você acha que está, ou a duração sai errada por 2×.
6. **Kyutai Pocket TTS**: a clonagem exige o repositório *gated* `kyutai/pocket-tts` no
   Hugging Face, com termos aceitos. As vozes internas funcionam sem isso.
7. **XTTS-v2 está fora**: pesos sob Coqui Public Model License (não comercial) e a Coqui
   fechou em janeiro de 2024, então ninguém mais pode licenciar. Além disso `aten::_fft_r2c`
   não existe no MPS — roda em CPU no Mac.
8. **Vozes nativas não servem**: no macOS o pt-BR só tem Luciana e Joana, ambas femininas;
   a masculina Felipe é voz Siri e não é exposta a `say`/`AVSpeechSynthesizer`.
9. **Estimar RTF por it/s engana.** 18 it/s no MPS parecia ótimo e o RTF real deu 2,1.
   Meça sempre relógio contra duração de áudio.

---

## 8. Licença, e o que NÃO pode ir para o git

Os Termos da Asmodee Digital (§5.3 e §5.4) proíbem descompilar e **"extrair… mesmo para uso
individual"**. O texto é obra protegida (FFG + Middle-earth Enterprises) e o áudio gerado é
obra derivada. FFG/Asmodee já emitiram DMCA contra mods de fãs.

Uso local e não distribuído: risco prático nulo. **Publicar o corpus, o JSON ou os áudios:
não faça.** Consequência direta para o repositório:

```gitignore
# conteúdo do jogo e derivados — NUNCA versionar
corpus/
audio/
audio_piper/
entrega/
*.opus
*.csv
Data/
ref/*.wav      # exceto se você mesmo gravou a referência
```

O repositório publica **um extrator e um renderizador**, nunca o conteúdo. Cada usuário roda
a extração sobre a própria instalação.

---

## 9. Estrutura sugerida do repositório

```
jime-narrador/
├── README.md
├── pyproject.toml            # deps: UnityPy, chatterbox-tts, piper-tts, rapidfuzz, ocrmac
├── .gitignore                # ver §8
├── src/jime/
│   ├── fase1_extract.py      # ← jime_corpus.py (pronto)
│   ├── fase2_render.py       # ← render_corpus.py (pronto, precisa otimizar)
│   ├── fase2_render_piper.py # ← render_piper.py (pronto)
│   ├── dsp.py                # cadeia de mago + detecção do rubberband
│   ├── capture/
│   │   ├── base.py           # interface: grab() -> ndarray
│   │   ├── macos_sck.py      # ScreenCaptureKit (via helper Swift ou pyobjc)
│   │   └── windows_wgc.py
│   ├── ocr/
│   │   ├── base.py
│   │   ├── apple_vision.py   # ocrmac
│   │   └── rapidocr_engine.py
│   ├── trigger.py            # absdiff → dhash → estabilidade → significância → dedupe
│   ├── matcher.py            # rapidfuzz + travas + escopo pelo save
│   ├── player.py             # fila de áudio, repetir/pausar/pular
│   └── ui/status_window.py
├── helper-swift/             # binário assinado de captura+OCR (macOS)
├── scripts/setup_mac.sh      # pronto
└── tests/
    ├── test_matcher.py       # OCR sintético com erros → checar as travas
    └── fixtures/screenshots/ # 30-50 screenshots reais + transcrição (harness de CER)
```

## 10. Ordem de trabalho sugerida

1. **Otimizar a Fase 2** (§5): rodar o benchmark A/B/C, aplicar `prepare_conditionals` +
   chunks, remedir o RTF. **Meta: derrubar de ~85 h para algo que caiba em 1-2 noites.**
   Sem isso, nada mais importa.
2. Detector de anomalia de ritmo + regeração automática com outra seed.
3. Renderizar as 7 campanhas, uma por vez, medindo.
4. **Harness de OCR**: 30–50 screenshots reais transcritos + script de CER. Escolher o motor
   com dado, não com fé — não existe benchmark público de OCR em texto de UI de jogo.
5. Camada de captura no macOS (o `.app` assinado é meio dia de trabalho, planeje).
6. `trigger.py` + `matcher.py` com testes sintéticos antes de plugar na tela real.
7. Integração, janelinha de status, hotkeys.
8. Só então portar a captura para Windows.

## 11. Fatos numéricos para não recalcular

- Corpus: 13.021 chaves, 9.740 blocos de narração, 366.965 palavras, 622 com `{0}`.
- A renderizar: 9.118 blocos / 341.646 palavras / ~40,7 h de áudio / ~850 MB em Opus 48k.
- Por campanha (blocos): main 2.178, poisonpromise 1.405, hauntingofdale 1.212,
  bonesofarnor 1.193, spreadingwar 1.150, embercrown 1.056, shadowedpaths 924.
- RTF medido: Chatterbox MPS no M5 Pro **2,1**; Chatterbox CPU (2 núcleos) 8,3; Piper CPU 0,09.
- Orçamento de latência da Fase 3: captura 20–40 ms + pré-proc 5–10 ms + OCR 130–350 ms +
  match 1–3 ms ≈ **<0,5 s**, mais 300–600 ms de espera deliberada por estabilidade.
