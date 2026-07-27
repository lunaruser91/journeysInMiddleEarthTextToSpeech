# Fase 3 — sincronizar o áudio com o jogo

> **Conclusão, depois de testar:** o gatilho continua sendo a tela, como o §6 do
> briefing previa — mas o problema ficou **muito** mais fácil.
>
> O jogo mantém um log com as chaves de localização exatas (4.827 linhas
> conferidas contra o corpus: 100% casam). Ele é gravado **a cada rodada** do
> jogo, sem precisar salvar — testado em 27/07/2026, ver §5. Como gatilho por
> tela, chega tarde demais; como contexto vivo, é perfeito.
>
> O que ele entrega é melhor que um gatilho: **escopo**. Sabendo a aventura atual,
> o casamento por OCR escolhe entre ~80 blocos em vez de 9.740 — uma redução de
> 156× que desarma a ambiguidade que o briefing temia. Mais: o log é verdade
> fundamental grátis para o harness de OCR, e decodifica como o jogo monta o texto
> na tela (§5b).

## 1. A descoberta

```
~/Library/Application Support/com.fantasyflightgames.jime/SavedGames/<slot>/
    SavedGameA, SavedGameB    JSON puro, não criptografado
    LogA.txt,   LogB.txt      log de eventos, append-only
```

O `LogA.txt` é texto puro, uma linha por bloco exibido, em ordem cronológica:

```
[1|1|A1_M1_E1_CHOICE|0]
[1|1|A1_M1_E1_INTIMIDATE|0]
[1|1|A1_M1_E1_ENEMIES|1|8|0|UI_ZERO_WIDTH_SPACE|0]
[1|1|UI_THREAT_INCREASE|1|10|0|4|0]
```

Formato: `[aventura | rodada | CHAVE | n_params | (tipo|?|valor|?) * n_params]`

- **campo 1** — número da aventura, 1..8 numa campanha completa
- **campo 2** — rodada dentro da missão
- **campo 3** — a chave de localização, idêntica à do corpus
- **campo 4** — quantos parâmetros seguem; cada um ocupa 4 campos
- **tipos observados** — `8` = referência a outra chave de localização,
  `10` = valor literal, `4` e `11` = ainda não identificados

O log acumula a campanha inteira: o slot medido vai de `A1_M1_E1_CHOICE`
(aventura 1) a `B2_GOOD_ENDING` (aventura 8) em 1.009 linhas.

## 2. Os números do problema de casamento

O caminho por OCR tem problemas que **medi neste corpus**, não que suponho:

| problema | medido |
|---|---|
| blocos com texto normalizado idêntico a outro | 153 grupos, **346 blocos** |
| blocos que compartilham os 40 primeiros caracteres | **1.194 (13,1%)** |
| blocos curtos (< 60 chars), os que mais confundem | 627 (6,9%) |
| blocos com ícones que o OCR não lê como texto | **2.363 (25,9%)** |

Some-se a isso o que o briefing já listou: no macOS 26 Tahoe as APIs clássicas de
captura devolvem só o wallpaper, o caminho válido exige ScreenCaptureKit num
`.app` assinado com Team ID real por causa do TCC, e o OCR custa 130–350 ms por
quadro.

**Mas atenção: esses números valem para o corpus INTEIRO.** É essa a diferença
que o §5c faz — escopando pela aventura, a ambiguidade praticamente desaparece.

## 3. Os 622 blocos com `{0}`: resolvidos a posteriori, não ao vivo

Eles eram o buraco do plano original: só se completam em tempo de jogo. O log
traz os valores — mas só depois do save, então isto serve para conferência e para
entender a estrutura, não para narrar na hora:

```
texto  : "Aumente a ameaça em {0}."
log    : [1|1|UI_THREAT_INCREASE|1|10|0|4|0]      -> {0} = 4
```
```
texto  : "Coloque a peça {0} conforme indicado."
log    : [1|2|UI_SECTION_REVEAL_PLACE_TILE_FORMATTED|1|10|0|300A|0]   -> {0} = "300A"
```
```
texto  : "{0} <DANO> {1} <MEDO>"
log    : [1|1|UI_DAMAGE_LOG_FORMATTED|2|10|0|2|0|10|0|2|0]   -> {0}=2, {1}=2
```

Ao vivo, o valor terá de vir do OCR da própria tela — que é justamente onde ele
aparece. O log serve para validar se o OCR leu certo.

## 4. Arquitetura revista (depois do teste do §5)

```
watcher em SavedGame*        -> lê CurrentAdventureId  [ESCOPO: ~80 candidatos]
captura da janela do jogo    -> ScreenCaptureKit, 5-10 Hz
 -> absdiff -> dhash -> estabilidade (3 quadros)     [gatilho]
 -> OCR (Apple Vision, pt-BR)
 -> casamento com rapidfuzz CONTRA OS ~80 BLOCOS DA AVENTURA, não contra 9.740
 -> toca o .opus do manifest
 -> ao fim da sessão: confere o narrado contra o LogA.txt e mede o acerto real
```

O escopo pelo save é o que torna isto viável. E o log, mesmo tardio, fecha o
ciclo: dá para medir a taxa de acerto sem transcrever nada à mão.

O `SavedGame*` (JSON puro) continua útil como contexto: `CampaignId`,
`CurrentAdventureId`, `CampaignDifficulty`, `PartyName`, os heróis. Serve para a
janela de status e para escolher a pasta de áudio da campanha certa.

## 5. RESPONDIDO: o log é gravado A CADA RODADA

Dois testes, em 27/07/2026.

**Teste 1 — jogar 9 telas e sair salvando.** O vigia não mostrou nada. O disco
mostrou uma única escrita, às 08:29:37, no mesmo segundo do `SavedGameA`.
Conclusão apressada: "o log só é escrito ao salvar". **Errada.**

**Teste 2 — jogar sem salvar, olhando só o tamanho do arquivo.**

```
08:29:37  11.056 bytes   (fim do teste 1, salvar e sair)
08:41:28  11.239 bytes   DURANTE a partida, sem salvar
```

O arquivo cresceu no meio do jogo. As 6 linhas acrescentadas foram:

```
av3 rd1  UI_PHASE_SHADOW               "Fase da Sombra"
av3 rd1  ENEMY_ORC_MARAUDER_ALT_ACTIV  "Bradando um grito de guerra feroz..."
av3 rd1  UI_THREAT_INCREASE            "Aumente a ameaça em 4."
av3 rd1  UI_RALLY_PHASE                "Fase de Reagrupamento"
av3 rd1  UI_RALLY_PHASE_INSTRUCTIONS   "...restaura seu baralho e examina 2."
av3 rd2  UI_PHASE_HERO                 "Fase de Ação"
```

A escrita caiu exatamente na virada de `rd1` para `rd2`, e as telas seguintes
(rodada 2, ainda em curso) não estavam no arquivo.

**Cadência: uma escrita por RODADA do jogo, com todos os eventos da rodada de uma
vez.** No lote medido, ~6 eventos por escrita.

### O que isso significa

| pergunta | resposta |
|---|---|
| serve de gatilho para narrar cada tela? | **não** — chega uma rodada atrasado |
| o log fica fresco durante a partida? | **sim** — não precisa salvar nem sair |
| serve de escopo em tempo real? | **sim** — aventura e rodada atuais, com no máximo uma rodada de defasagem |
| serve de verdade fundamental? | **sim**, e acumula sozinho a cada partida |

O gatilho continua sendo a tela. Mas o log deixa de ser um artefato pós-jogo e
vira um **contexto vivo**: a qualquer momento da partida ele diz em que aventura
e rodada o grupo está, o que é exatamente o que o escopo do §5c precisa.

## 5b. O sistema de parâmetros, decodificado

Antes de saber que o log era tardio, a decodificação dos parâmetros já estava
feita, e ela vale independentemente — porque descreve como o jogo **monta** o
texto que aparece na tela:

| tipo | significado | exemplo |
|---|---|---|
| `3` | herói do grupo, por índice na party | `A2_M1_INTRO` + `3\|0` → "**Legolas** se curva sobre o chão…" |
| `8` | referência a outra chave de localização | `PLACE_PERSON` + `8\|A2_M1_T1_PLACE` |
| `10` | valor literal | `UI_THREAT_INCREASE` + `10\|4` → "Aumente a ameaça em **4**." |

O tipo 8 é o mais importante e foi uma surpresa: **a prosa narrativa costuma ser
passada como parâmetro de um template genérico.** O texto de `PLACE_PERSON` no
corpus é só `"{0}\n\nColoque uma ficha de pessoa conforme indicado."` — a
história inteira mora em `A2_M1_T1_PLACE`, uma chave separada.

Isso muda como o casamento por OCR deve funcionar: **o que aparece na tela é a
concatenação de várias chaves do corpus, não uma chave só.** Casar a tela inteira
contra um bloco isolado falharia justamente nesses casos.

(Elo em aberto: o índice do herói vem do `HeroInfo` do save, mas o `Id` numérico
— 4, no grupo testado — ainda não foi mapeado para `HERO_LEGOLAS_NAME`. Falta
achar essa tabela nos assets.)

## 5c. O que salva o caminho por OCR: escopo pela aventura

O save diz em que aventura o grupo está (`CurrentAdventureId`). Medindo os logs
existentes, quantos blocos de narração distintos aparecem em cada aventura:

| aventura | blocos distintos |
|---|---|
| 1 | 115 |
| 2 | 54 |
| 3 | 62 |
| 4 | 86 |
| 5–6 | 84 cada |
| 7–10 | 18 a 57 |

**Entre 18 e 115 candidatos, contra 9.740 do corpus inteiro — uma redução de
~156×.** O briefing temia a ambiguidade do casamento difuso, e com razão: medi
13,1% de blocos compartilhando os 40 primeiros caracteres. Mas essa ambiguidade
foi medida no corpus TODO. Dentro de uma aventura, com ~80 candidatos, o
casamento fica praticamente infalível — e as travas de comprimento e margem do
§6 do briefing passam a ser folga, não necessidade.

## 5d. E o log ganha três papéis novos

Mesmo tardio, ele é valioso:

1. **Verdade fundamental para o harness de OCR.** A sessão de teste produziu 9
   telas reais com a chave exata de cada uma, salvas em
   `entrega/ocr-fixtures/sessao-2026-07-27.json`. É exatamente o que o §10 item 4
   do briefing pede, e saiu de graça. Cada partida jogada gera mais.
2. **Correção a posteriori.** Ao fim de uma sessão, dá para conferir o que foi
   narrado contra o que o jogo registrou, e medir a taxa de acerto real do
   casamento — sem transcrever nada à mão.
3. **Escopo.** Junto com o `SavedGame`, define o conjunto de candidatos.

## 5e. Não existe sinal ao vivo — quatro frentes investigadas e fechadas

Antes de aceitar o OCR, foram investigadas quatro alternativas. **Todas
sem-saída**, e as provas são de código, não de observação de mtime.

**Mecanismo do flush, provado no IL do `Assembly-CSharp.dll`:**

`FFG.JIME.MasterMessageCache` acumula cada bloco exibido em `_pendingMessages`,
uma lista em memória. `AddMessage` — chamado por `Adventure::LogMessage`,
`DisplayMessageBase::LogMessage`, `SpawnEnemyGroup::OnProgress`,
`CoroutineExploreTile` e outros — **nunca toca o disco**. O único ponto que chama
`Stream::Flush` é `FlushLogStream`, e ele tem exatamente dois chamadores:
`CloseLogStream` e `GameData::CoroutineSave`. Este, por sua vez, é chamado por seis
lugares, dos quais **o único periódico é `GameController::CoroutineEndRound`** —
o fim da rodada. Os outros são o save explícito, o setup da aventura e três
transições de cena.

Confirmação independente: com o jogo rodando, `lsof` não lista o `LogA.txt` entre
os descritores abertos. O arquivo nem fica aberto durante a partida.

> Isto corrige o *argumento* que usei antes, embora a conclusão estivesse certa:
> eu deduzi a cadência de um único mtime, e mtime só registra a ÚLTIMA escrita,
> nunca a contagem. O grafo de chamadas é que sustenta a afirmação.

**Acessibilidade — a porta que o briefing fechou por suposição, agora fechada por
medição.** `UnityEngine.AccessibilityModule.dll` está no build, mas é só a paleta
para daltonismo. O `UnityPlayer.dylib` expõe 1.353 seletores Objective-C e
**zero** de acessibilidade. Controle independente: o Gloomhaven (Unity 2021.3.5f1)
dá o mesmo resultado — é propriedade da engine, não deste jogo. Todo o texto é
malha SDF do TextMeshPro na camada Metal; nunca existe uma `NSView` com string.

**Analytics, áudio, rede e IPC — todos mortos.** O jogo nunca emite evento
customizado de Analytics (só `appRunning` de heartbeat e `appStop`, gravados no
encerramento). O macOS expõe áudio por processo, mas só como booleano, e o Unity o
mantém cravado. Os AssetBundles são por aventura, não por tela, e ficam abertos.
Não há socket em escuta, pipe, distributed notification nem XPC.

**Único achado colateral útil:** o `Player.log` é o stdout sem buffer do jogo,
escrito ao vivo (<100 ms). Mas registra apenas trocas de **cena** (~6-7 por
sessão), nunca uma chave de localização. Serve para saber quando o jogo entra ou
sai de uma missão — não para narrar.

**Conclusão: a tela é o único gatilho possível.** O que muda em relação ao
briefing não é o caminho, é a dificuldade: com o escopo por aventura (§5c) o
casamento escolhe entre ~62 candidatos, e o log fornece o oráculo exato para medir
o acerto.

## 5f. O matcher: construído e medido

`matcher.py` + `test_matcher.py`, medidos contra **626 telas reais reconstruídas
dos logs do jogo** (107 delas compostas de 2+ chaves). O briefing pedia "30-50
screenshots reais transcritos"; estas 626 saíram sem transcrever nenhuma.

Ruído de OCR sintético com as confusões clássicas de texto serifado
(m↔rn, l↔i, c↔e, d↔cl, o↔0), quedas e duplicações de caractere, junção de palavras.

**Métrica: por tela.** A pergunta que importa para a reprodução é "a tela teve seu
bloco de prosa identificado?", não "cada parágrafo casou?". Contar por parágrafo
pune o matcher por casar *"Coloque uma ficha de busca conforme indicado"* com
outro bloco que tem a mesma instrução — inevitável e irrelevante, porque quem se
narra é a prosa.

| escopo | ruído | acerto | **erra** | recusa |
|---|---:|---:|---:|---:|
| campanha + main (7.299 cand.) | 0% | **88,2%** | 2,4% | 9,4% |
| campanha + main | 2% | 87,5% | 2,2% | 10,2% |
| campanha + main | 5% | 86,7% | 2,9% | 10,4% |
| campanha + main | 10% | 67,3% | 5,4% | 27,3% |
| corpus inteiro (21.476 cand.) | 0% | 87,5% | 2,4% | 10,1% |
| por aventura | 0% | 87,9% | 2,1% | 10,1% |

### Três conclusões, uma delas contra o que eu supunha

1. **O escopo quase não importa.** Corpus inteiro dá 87,5%; campanha dá 88,2%;
   aventura dá 87,9%. Eu tinha apostado no escopo como a grande alavanca — não é.
   O que faz o trabalho são as travas e o casamento por parágrafo. O escopo segue
   valendo por ser grátis (o save já está lá) e por cortar o custo de CPU.

2. **Robusto até ~5% de CER, despenca em 10%.** Entre 0% e 5% o acerto cai só 1,5
   ponto. Em 10% cai 20 pontos. Como o Apple Vision costuma dar 1-3% em texto
   limpo, a margem é confortável — mas o pré-processamento da imagem (§6 do
   briefing) é que mantém o CER nessa faixa, e não é opcional.

3. **Os ~2,4% de erro são menos graves do que parecem.** Abrindo os 7 erros de uma
   execução: 2 eram blocos de texto normalizado idêntico (mesmo áudio), 2 eram a
   mesma chave em parágrafo diferente, 1 diferia por uma letra — `"ha boatos
   **sobra** a existencia"` contra `"**sobre**"`, erro de digitação do próprio
   jogo. Sobraram ~2 erros reais em ~940 casamentos.

### O que ficou nos ~10% de recusa

A trava de razão de comprimento responde pela maioria. Foi ela que levou à
correção mais útil do matcher: **indexar também cada parágrafo de cada bloco**,
não só o bloco inteiro. Sem isso, uma tela que mostra um parágrafo de um bloco de
três caía na trava (150 chars contra 450 dá razão 0,33). Isso sozinho valeu +6
pontos de acerto.

Recusar é o comportamento certo: silêncio é recuperável com TTS ao vivo, narrar
o bloco errado não é — o jogador age sobre o que ouve.

## 6. Riscos e incertezas que restam

- **Cobertura.** 592 chaves distintas nos logs analisados, 1.863 ocorrências de
  blocos de narração. Falta confirmar que *toda* tela que os jogadores leem em voz
  alta gera uma linha — pode haver texto exibido que não é registrado.
- **Ordem ≠ exibição.** O log diz que o bloco foi acionado, não quanto tempo ficou
  na tela. Para narração isso basta, mas não dá para saber se o jogador já leu.
- **Buffers A/B.** Ler os dois e deduplicar; não assumir que A é sempre o atual.
- **Prólogo e epílogo.** O jogo **já narra** esses em pt-BR (ver
  `narration/<campanha>/pt`, 20 clipes, 18,4 min de voz profissional). O narrador
  deve ficar em silêncio nesses blocos, ou haverá duas vozes ao mesmo tempo.
- **O log é do jogo, não seu.** Uma atualização pode mudar o formato. O parser
  deve falhar de forma visível, não silenciosa.

## 7. Ordem de trabalho

1. **Harness de OCR.** Já existem fixtures reais e rotuladas em
   `entrega/ocr-fixtures/`, geradas sem transcrever nada — o log dá a chave de
   cada tela. Acumular mais jogando, e medir CER de Apple Vision vs RapidOCR com
   dado, não com fé.
2. **`matcher.py`** — rapidfuzz contra o conjunto da aventura atual (~62 blocos),
   não contra o corpus. Testar com OCR sintético degradado antes de plugar na tela.
   Lembrar que a tela é concatenação de várias chaves (§5b).
3. **Leitor do save** — `CurrentAdventureId` para o escopo; barato e sem permissão.
4. **Captura no macOS** — ScreenCaptureKit num `.app` assinado. É o item caro
   (meio dia, mais a conta de desenvolvedor), e o último a fazer, porque tudo
   acima pode ser desenvolvido e testado com screenshots salvos.
5. **`trigger.py`** — absdiff → dhash → estabilidade → dedupe, conforme o §6 do
   briefing, que segue válido.
6. Integração, janela de status, hotkeys.
7. Piper para os blocos com `{0}` — lembrando que **não está instalado** e que o
   `render_piper.py` quebra neste ffmpeg (usa `rubberband`, ausente).
8. Só então portar para Windows — onde a camada de captura muda, mas o matcher,
   o escopo e o corpus são idênticos.
