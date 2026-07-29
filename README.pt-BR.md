# Narrador automático para *Journeys in Middle-earth*

*[English](README.md) · **Português***

Lê em voz alta, **inteiramente offline**, o texto que o aplicativo oficial de *The
Lord of the Rings: Journeys in Middle-earth* (Fantasy Flight / Asmodee) coloca na
tela durante a partida. Ele assiste à tela, descobre qual bloco do texto do jogo
está aparecendo, e fala.

O aplicativo tem narração gravada apenas para o Prólogo e os Epílogos de cada
campanha. Todo o resto é lido em voz alta por um jogador, e é isso que este
projeto substitui.

Os **treze** idiomas do jogo podem ser narrados.

> ### Aviso de licença — leia antes de qualquer `git add`
>
> Os Termos da Asmodee Digital (§5.3/§5.4) proíbem extrair o conteúdo, **mesmo
> para uso individual**. O texto é obra protegida (FFG + Middle-earth
> Enterprises) e o áudio gerado é obra derivada. FFG/Asmodee já emitiram DMCA
> contra mods de fãs.
>
> **Este repositório publica um extrator e um renderizador, nunca o conteúdo.**
> Cada pessoa roda a extração contra a própria instalação, para uso local e não
> distribuído. O `.gitignore` bloqueia corpus, manifests, áudio (em todo formato)
> e assets.

---

## Estado do projeto

| Fase | O que faz | Estado |
|---|---|---|
| 1 | assets do app → corpus, em qualquer dos 13 idiomas | **pronto** — 13.018 chaves em pt, 9.814 blocos de narração |
| 2 | corpus → áudio pré-renderizado | **pronto e medido** — RTF 0,05; uma campanha mais o texto compartilhado em ~30 min |
| 3 | tela → OCR → correspondência → fala | **funciona durante uma partida real** no macOS, confirmado de ouvido; no Windows todas as partes passam no autoteste, mas nenhuma sessão foi jogada |

---

## Instalação

Você precisa de um Mac ou um PC com Windows, **o jogo instalado no mesmo
computador** — o narrador lê os arquivos de texto dele — e cerca de 300 MB
livres por idioma. Não precisa de máquina rápida, nem placa de vídeo, nem
internet depois de configurado.

**macOS**

```bash
curl -fsSL https://raw.githubusercontent.com/lunaruser91/journeysInMiddleEarthTextToSpeech/main/install.sh | bash
```

**Windows**, no PowerShell

```powershell
irm https://raw.githubusercontent.com/lunaruser91/journeysInMiddleEarthTextToSpeech/main/install.ps1 | iex
```

Isso instala o que estiver faltando, clona o projeto, monta o ambiente e roda o
autoteste. Rodar de novo é também como você **atualiza**.

Uma coisa ele não faz por você: **o macOS exige permissão de gravação de tela.**
Ajustes do Sistema → Privacidade e Segurança → Gravação de Tela → marque o
Terminal, depois encerre o Terminal (`Cmd`+`Q`) e abra de novo — a permissão é
lida quando o programa inicia. O Windows não exige permissão.

Então inicie — ele pergunta o resto:

```bash
cd ~/jime && ~/jime-venv/bin/python jime.py            # macOS
```

```powershell
cd $HOME\jime; & $HOME\jime-venv\Scripts\python.exe jime.py   # Windows
```

**Na primeira vez, nesta ordem:** extrair o corpus, gerar o áudio, e então
narrar. A extração leva um minuto, a geração cerca de meia hora por campanha, e
depois disso só narrar importa.

Se algo der errado, ou se preferir ver cada etapa, continue lendo.

---

## Instalando à mão

Para quem já tem as ferramentas, ou quer ver exatamente o que o instalador faz.

**macOS**

```bash
brew install ffmpeg python@3.13 git
git clone https://github.com/lunaruser91/journeysInMiddleEarthTextToSpeech.git ~/jime
python3.13 -m venv ~/jime-venv
~/jime-venv/bin/pip install -e ~/jime'[tts,ocr,capture]'
```

**Windows**, no PowerShell — um pacote por comando, o `winget` aceita um único
`--id`:

```powershell
winget install --id Python.Python.3.13 -e --accept-source-agreements --accept-package-agreements
winget install --id Git.Git -e --accept-package-agreements
winget install --id Gyan.FFmpeg -e --accept-package-agreements
winget install --id Microsoft.VCRedist.2015+.x64 -e
```

Feche e reabra o PowerShell para os comandos entrarem no PATH, e então:

```powershell
git clone https://github.com/lunaruser91/journeysInMiddleEarthTextToSpeech.git $HOME\jime
cd $HOME\jime
py -3.13 -m venv $HOME\jime-venv
& $HOME\jime-venv\Scripts\pip install -e '.[tts,ocr,capture]'
```

O Visual C++ Redistributable não é opcional: sem ele o motor de fala não carrega,
com uma mensagem que não menciona nem a si mesmo nem o que falta.

`ocr` e `capture` se resolvem por plataforma — Apple Vision e ScreenCaptureKit no
macOS, RapidOCR e `windows-capture` no Windows, este último envolvendo o
Windows.Graphics.Capture, a única API que enxerga uma janela Unity, já que
BitBlt e PrintWindow devolvem quadros pretos.

A síntese é o [Piper](https://github.com/OHF-Voice/piper1-gpl): um modelo ONNX
pequeno, na CPU. Uma voz tem cerca de 60 MB, baixada na primeira vez. Sem GPU,
sem nada para assinar.

Um atalho poupa digitação:

```bash
alias jime="~/jime-venv/bin/python"
```

---

## Uso

Rode sem argumentos e ele pergunta. Cada pergunta mostra o estado por trás dela —
quais idiomas têm corpus, quanto de cada campanha já foi renderizado — para você
não precisar lembrar onde parou.

```bash
jime
```

As flags continuam existindo e são mais rápidas depois que você as conhece.
`jime <comando> --help` mostra as opções completas de cada uma.

```bash
jime status                    # o que está pronto e o que falta
jime doctor                    # esta máquina está pronta?
jime languages                 # o que cada uma das 13 localizações suporta
jime voices                    # qual voz fala cada idioma
jime extract --lang pt         # assets do jogo  ->  corpus
jime render --campaign bonesofarnor
jime play --campaign bonesofarnor --display   # jogo em tela cheia
jime check --lang pt           # audita o ritmo do que foi renderizado
```

Renderizar uma campanha inteira mais o texto compartilhado, sem supervisão e de
forma retomável:

```bash
./render_all.sh                # bonesofarnor, depois main
./render_all.sh --lang en      # o mesmo em inglês
```

O `main` guarda o texto que todas as campanhas compartilham — interface, tiles,
ativações de inimigos, tesouros. **48,8% de tudo que se fala, em 631 telas reais,
vem dele**, então uma campanha renderizada sem ele deixa metade da sessão muda.

### O que cada opção do menu faz

| Opção | O que faz | Quando você precisa |
|---|---|---|
| **Narrate a game** | Assiste à tela e lê cada bloco em voz alta | Toda sessão |
| **Render audio** | Transforma o texto extraído em arquivos de fala | Uma vez por campanha |
| **Extract the corpus** | Lê os arquivos do próprio jogo | Uma vez por idioma |
| **Status** | O que foi extraído, o que foi renderizado, quanto | Para ver onde você parou |
| **Check this machine** | Se está tudo instalado e permitido | Quando algo não funciona |
| **Voices** | Qual voz fala cada idioma | Para trocar ou calibrar uma voz |

O idioma é a primeira pergunta e vale para tudo depois dela. `b` volta uma
pergunta, `q` sai, e Enter aceita a opção destacada.

### Se algo der errado

Rode o `selftest.py`, ou **Check this machine** pelo menu — eles nomeiam o que
está faltando em vez de falhar de forma obscura.

As três respostas mais comuns:

- **Ele não encontra a janela do jogo, ou só lê quando você dá alt+tab.**
  Escolha a opção de tela cheia, que captura o monitor. As duas plataformas
  escondem um jogo em tela cheia da captura de janela, por motivos diferentes: o
  macOS lhe dá um Space próprio e não desenha Space inativo; o Windows deixa a
  tela cheia exclusiva contornar o compositor, e o Windows.Graphics.Capture só
  enxerga o que o compositor desenha. Colocar o jogo em janela sem borda resolve
  no Windows, e é a melhor saída quando o jogo oferece essa opção.
- **Ele reconhece as telas mas não fala.** Aquela campanha ainda não tem áudio —
  volte e renderize. O menu oferece isso quando percebe.
- **Windows: o motor de fala não carrega.** Falta o Visual C++ Redistributable:
  `winget install --id Microsoft.VCRedist.2015+.x64 -e`

---

### Atualizando

Rode o instalador de novo. Ele faz `git pull`, reinstala, e não mexe em mais
nada:

```bash
curl -fsSL https://raw.githubusercontent.com/lunaruser91/journeysInMiddleEarthTextToSpeech/main/install.sh | bash
```

```powershell
irm https://raw.githubusercontent.com/lunaruser91/journeysInMiddleEarthTextToSpeech/main/install.ps1 | iex
```

Ou à mão — o `git pull` sozinho costuma bastar, já que os scripts rodam do
diretório e pegam as mudanças na hora. Só dependência nova exige a segunda
linha:

```bash
cd ~/jime && git pull
~/jime-venv/bin/pip install -e ~/jime'[tts,ocr,capture]'
```

Seu corpus, o áudio gerado e as vozes baixadas ficam em `corpus/`, `output/` e
`voices/`, e o git não toca em nenhum deles. Atualizar nunca refaz áudio — a não
ser que a própria receita mude, já que voz, ritmo e efeitos entram na chave do
cache. Quando isso acontece, o commit avisa.

### Idiomas e vozes

Toda localização que o jogo traz tem uma voz no Piper, então não há nada que você
possa ler e não ouvir.

```bash
jime voices                      # a voz padrão de cada idioma
jime voices --lang de            # o que mais existe
jime render --lang de --voice de_DE-eva_k-x_low
```

Só português e inglês têm ritmo de leitura **medido**; os demais caem no ritmo
próprio da voz, que é mais rápido do que qualquer narrador fala.
`jime voices --calibrate --lang de` renderiza uma amostra, mede o ritmo e imprime
a linha para colar no `voices.py`.

`jime languages` mostra quais idiomas têm o vocabulário de ícones preenchido —
adicionar um são cerca de 21 palavras, não uma investigação nova.

### As ferramentas individuais

**Fase 1 — extrair o corpus da sua própria instalação**

```bash
jime phase1_extract.py "<.../JiME.app/.../StreamingAssets/bundles>" -o corpus/ --lang pt
```

O aplicativo é Unity 2022.3 com Mono e **nada está ofuscado**: cada bundle de
localização guarda um único `TextAsset` que é um CSV limpo.

**Fase 2 — renderizar o áudio**

```bash
jime phase2_render.py --lang pt --campaign bonesofarnor
jime phase2_render.py --lang pt --campaign bonesofarnor --dry-run   # estimar antes
jime phase2_render.py --lang pt --key "main:G22_SWORD_TRUE"         # um bloco
jime check_pace.py output/audio_pt/manifest.json                    # auditar o resultado
```

Um bloco cujo `.opus` já existe é pulado, e o manifest é reescrito a cada 50
blocos e no Ctrl+C, então parar e recomeçar não custa nada. A voz, o ritmo e a
cadeia de efeitos entram todos na chave do cache, então mudar qualquer um deles
refaz o render em vez de misturar duas receitas silenciosamente.

**Fase 3 — narrar uma partida ao vivo**

```bash
jime narrator.py --display           # jogo em tela cheia — o caso usual
jime narrator.py                     # jogo em janela, achado pelo título
jime narrator.py --list-windows      # o que o backend de captura enxerga
jime narrator.py --from-video FILE   # reproduz uma gravação, sem precisar de permissão
```

**Se o jogo roda em tela cheia, use `--display`.** Uma aplicação em tela cheia no
macOS ganha um Space próprio, e o macOS não desenha um Space que não está em
primeiro plano: enquanto você olha o terminal, a janela do jogo não está apenas
escondida, ela não está sendo desenhada, e nenhuma API de captura a alcança.
Capturar o *display* contorna isso, porque um display sempre mostra o Space ativo
— que, enquanto você joga, é o do jogo.

A captura de janela continua existindo para jogo em janela, e espera (90 s por
padrão, `--wait`) a janela aparecer, para você iniciar no terminal e depois mudar
para o jogo.

No macOS a primeira captura dispara o pedido do sistema. Se em vez disso ele
travar, é a permissão faltando: Ajustes do Sistema → Privacidade e Segurança →
Gravação de Tela → marque seu terminal, e **reinicie o terminal**. Nada precisa
ser assinado ou notarizado: a permissão se prende ao terminal e estes scripts a
herdam.

Confirme que os pixels chegam mesmo, antes de confiar numa sessão:

```bash
jime test --capture --display
```

**Testar o reconhecimento sem o jogo**

```bash
jime demo.py ~/Downloads/tela.webp --no-audio     # uma tela: OCR + correspondência
jime batch.py ~/Downloads/*.webp --keys keys.txt  # várias, com taxa de acerto
jime watch_log.py --all                           # o log de eventos do próprio jogo
jime test_matcher.py                              # 631 telas reais, com ruído
```

---

## Onde as coisas ficam

O projeto é autocontido. **Nada é escrito fora do repositório.**

```
corpus/          corpus extraído do jogo              (gerado, ignorado)
voices/          modelos de voz do Piper, ~60 MB cada (ignorado)
output/          TUDO que é gerado                    (ignorado)
  audio_<lang>/    o render, mais o manifest.json
  live_<lang>/     blocos sintetizados durante a partida
  ocr-fixtures/    telas reais com a chave certa

docs/            as notas de investigação
legacy/          o script de extração original, guardado para comparação
```

| arquivo | o que faz |
|---|---|
| `jime.py` | o único comando do qual todo o resto pende |
| `phase1_extract.py` | AssetBundles do jogo → corpus JSON/CSV |
| `phase2_render.py` | corpus → áudio, com cache retomável por hash |
| `voices.py` | qual voz fala cada idioma, e seu ritmo medido |
| `glyphs.py` | ícones do jogo → palavras faladas; números por extenso; por idioma |
| `matcher.py` | texto da tela → o bloco do corpus de onde veio |
| `trigger.py` | quando uma tela assentou e vale a pena ler |
| `live.py` | os blocos que só podem ser sintetizados durante a partida |
| `player.py` | fila, interrupção, repetição, e sobre o que ficar calado |
| `narrator.py` | o laço que junta tudo acima |
| `check_pace.py` | acha blocos cujo ritmo se afasta da mediana |
| `selftest.py` | verifica a máquina inteira, ponta a ponta |
| `test_matcher.py` | bancada: 631 telas reais + ruído sintético de OCR |

---

## O que foi medido

Tudo abaixo é medição neste hardware (MacBook Pro M5 Pro, macOS 26 Tahoe), não
estimativa. O detalhe está em
[docs/PHASE2-MEASUREMENTS.md](docs/PHASE2-MEASUREMENTS.md) e
[docs/PHASE3-STRATEGY.md](docs/PHASE3-STRATEGY.md).

### Síntese

| | |
|---|---|
| RTF (tempo de parede ÷ duração do áudio) | **0,05** |
| Bones of Arnor + texto compartilhado (3.386 blocos, 12,4 h de áudio) | **~30 min** |
| Todas as campanhas (38,1 h de áudio) | ~2 h |
| Modelo em disco | 60 MB, só CPU |
| Ritmo de leitura | 155 palavras/min, dentro da faixa de audiolivro |

Este projeto começou no Chatterbox, um modelo de clonagem de voz, e mediu **RTF
3,7** — cinquenta horas para uma campanha mais o texto compartilhado. Trocar para
o Piper transformou isso em quarenta minutos: **74× mais rápido**, nos mesmos 226
blocos, com zero falhas contra quinze. Também eliminou a exigência de GPU, baixou
o modelo de 3 GB para 60 MB, e levou os idiomas de dez para treze.

O custo foi expressividade. O Piper tem dicção clara e prosódia plana; ele lê,
não interpreta. O Chatterbox soava melhor. A medição na §6c das notas de
desempenho é a razão de ele ter perdido mesmo assim.

**Duas coisas foram tentadas sobre o Piper e removidas.** Uma cadeia de filtros
de envelhecimento (tom mais grave, realce de graves, corte de agudos, tremolo,
eco) deixou a voz mole, lenta e difícil de entender — ela cortava 2,5 dB
justamente onde vivem as consoantes. E dois processos de render em paralelo
rodam **55% mais devagar** que um, porque o decode é limitado por banda de
memória: cada processo lê seus próprios pesos por passo, então dois dobram a
demanda sem dobrar a oferta.

### Reconhecimento de tela

Medido contra **631 telas reais** reconstruídas dos logs do próprio jogo — sem
transcrever nenhuma delas à mão.

| ruído de OCR | acerto | **errado** | recusa |
|---:|---:|---:|---:|
| 0% | **99,2%** | 0,5% | 0,3% |
| 2% | 95,6% | 0,5% | 4,0% |
| 5% | 94,8% | 0,5% | 4,8% |
| 10% | 73,4% | 1,0% | 25,7% |

Recusar é o comportamento certo: silêncio é recuperável, narrar o bloco errado
não é, porque o jogador age sobre o que ouve.

Restringir pelo save (campanha, aventura) quase não muda o resultado — o trabalho
é feito pelas proteções de comprimento e margem, e pela correspondência por
parágrafo.

---

## Três descobertas que mudaram o projeto

### 1. O jogo mantém um log com as chaves exatas

`~/Library/Application Support/com.fantasyflightgames.jime/SavedGames/<slot>/LogA.txt`
registra cada bloco exibido, com seus parâmetros:

```
[3|1|PLACE_PERSON|1|8|0|A2_M1_T1_PLACE|0]
 │ │  │            │ └── tipo 8 = referência a outra chave
 │ │  │            └──── quantos parâmetros
 │ │  └─────────────── a chave, idêntica à do corpus
 │ └────────────────── rodada
 └──────────────────── aventura
```

4.827 linhas conferidas contra o corpus: **100% de correspondência, zero chaves
desconhecidas**.

Ele é escrito **uma vez por rodada** — provado no IL do `Assembly-CSharp.dll`: o
`FlushLogStream` só é chamado pelo `GameController::CoroutineEndRound` e pelo
save. Então não serve como gatilho ao vivo, mas é um oráculo exato para validar o
matcher e gera fixtures de graça.

### 2. A tela é a concatenação de várias chaves

O jogo injeta chaves como parâmetro de templates genéricos:

```
corpus  PLACE_PERSON   = "{0}\n\nColoque uma ficha de pessoa conforme indicado."
param   {0}            = A2_M1_T1_PLACE = "[a prosa narrativa do bloco]"
```

Comparar uma tela inteira com um único bloco falha exatamente nesses casos, e é
por isso que o matcher trabalha **por parágrafo** — e por isso o narrador fala
apenas os parágrafos que estão de fato na tela, não o bloco inteiro por trás
deles.

### 3. Um quarto do corpus tinha glifos que nenhum TTS conseguia ler

3.209 blocos (24,7%) contêm caracteres da **Private Use Area** — os ícones da
fonte do jogo, escritos como caracteres literais em vez de tags `<sprite=>`, de
modo que a limpeza de marcação nunca os viu. O sintetizador recebia
`"Cada herói testa ; 2"`, sem nenhum atributo nomeado.

O `glyphs.py` deriva o mapa das 24 chaves `main:GLYPH_*` que o próprio jogo
publica. Essas chaves são idênticas nos 13 idiomas, então **adicionar um idioma
são cerca de 21 palavras**, não uma investigação nova.

Uma armadilha: `GLYPH_FOCUS` é o nome interno de **Agilidade**. Nada no nome
sugere isso; a prova veio de duas chaves independentes cujo único glifo de
atributo era `FOCUS`.

E os **números** eram lidos em espanhol ("uno" em vez de "um") mesmo com o idioma
definido como português — 38,8% do corpus. Resolvido escrevendo-os por extenso
antes da síntese.

---

## Armadilhas já pagas

Não redescubra estas.

1. **O ffmpeg do Homebrew não traz o filtro `rubberband`.** Qualquer coisa que o
   nomeie falha em todo bloco. O renderizador detecta e recorre a
   `asetrate`+`atempo`, e a chave do cache registra qual foi usado.
2. **Voz, ritmo e efeitos entram na chave do cache.** Isso é deliberado — impede
   duas receitas de se misturarem numa sessão — mas significa que mudar de ideia
   refaz tudo. Com o Piper isso custa meia hora, não dois dias.
3. **No macOS 26 Tahoe**, `CGWindowListCreateImage` e `screencapture` devolvem
   apenas o papel de parede. O ScreenCaptureKit é a única API que ainda enxerga
   janelas. Ela **não** precisa de um `.app` assinado: a permissão de gravação de
   tela se prende ao processo responsável, então um script iniciado num terminal
   herda a permissão do terminal.
4. **O macOS não desenha um Space inativo.** Um jogo em tela cheia não é
   capturável a partir de um terminal em outro Space — a janela não está
   escondida, ela não está sendo desenhada. Capture o display.
5. **O pyobjc converte um argumento de callback usando os tipos que conhece
   naquele instante.** Importe o Quartz *antes* da chamada de captura, ou o
   CGImage chega como ponteiro opaco: largura, altura e stride leem
   corretamente, e os pixels vêm vazios.
6. **O Unity não expõe texto à acessibilidade.** Medido: o `UnityPlayer.dylib`
   tem 1.353 seletores Objective-C e **zero** de acessibilidade. Confirmado
   também no Gloomhaven, ou seja, é propriedade do motor. Não tente
   `AXStaticText`.
7. **Estimar RTF por it/s engana.** 18 it/s no MPS parecia ótimo e o RTF real era
   2–3. Meça tempo de parede contra duração do áudio, e **pareado**: duas
   execuções idênticas neste Mac já diferiram 30%.
8. **O `afplay` não decodifica Opus.** Ele sai com código 0 depois de 1,9 s num
   arquivo de 33 s, então parece ter funcionado. O player usa `ffplay`.
9. **O espeak-ng guarda o caminho dos dados num buffer de tamanho fixo.**
   Instale o Piper num caminho com mais de ~160 caracteres e todo render morre
   com um erro que cita um diretório da máquina que *compilou* a roda — ele cai
   silenciosamente no padrão de compilação. Medido: 156 caracteres funciona, 176
   não. O `selftest.py` verifica isso.
10. **O console do Windows não usa UTF-8.** Ele tira a codificação da code page —
   cp1252 na maioria das instalações — e um caractere que não cabe levanta
   exceção em vez de degradar. Não são só os símbolos: `ě`, `ł`, e todo o russo e
   o chinês do corpus quebram. O `console.setup()` força UTF-8 em todo ponto de
   entrada.
11. **Nunca clone um dublador famoso.** No Brasil a voz é direito de
    personalidade (CF art. 5º XXVIII-a; CC arts. 20–21) e o uso não autorizado é
    acionável mesmo sem violação de direito autoral. Isso hoje é discutível — o
    Piper sintetiza a partir de um modelo publicado, sem nenhuma gravação de
    referência — mas é a razão de o projeto ter abandonado clonagem, e o
    enquadramento sempre foi "**um** mago velho", nunca "*aquele* narrador".

---

## O que falta

1. **Uma bancada de OCR com taxa de erro real.** O ruído na bancada do matcher é
   sintético. Medir o Apple Vision contra as fixtures diria se a leitura real
   fica na faixa de 1–3%, onde o matcher está acima de 94%. Tudo que se afirma
   sobre tolerância a ruído repousa numa suposição até lá.
2. **Prosa e instrução mecânica ainda são faladas como uma coisa só.** 60,6% dos
   blocos de narração têm uma quebra de parágrafo separando história de regra,
   então dividir é quase mecânico — mas ninguém decidiu se o narrador deve ler só
   a prosa, só a regra, ou as duas.
3. **Cinco ícones são inferidos, não confirmados.** `MOUNT` (20 ocorrências),
   `WILD` (10), e `PREPARED`, `CORRUPTION`, `REVEAL_CARD_DRAW` (uma cada) foram
   deduzidos do contexto, não conferidos contra o manual impresso.
4. **Onze dos treze idiomas não têm ritmo medido.** Eles caem no ritmo próprio da
   voz, mais rápido do que um narrador deveria ler. O
   `jime voices --calibrate` resolve um em poucos minutos.
5. **O Windows passa no autoteste mas nunca narrou uma partida.** Uma VM com
   Windows 11 e o jogo instalado roda o `selftest.py` em 41/41, instalado pelo
   `install.ps1` num comando só — extração da build nativa, síntese, RapidOCR,
   correspondência e o backend de captura. O que não foi tentado lá é uma sessão:
   capturar o jogo enquanto ele roda, e ouvi-lo ler uma tela em voz alta.
6. **O nome do herói por trás de um `Id` numérico está sem resolver.** O
   parâmetro de log tipo 3 carrega um número que este projeto ainda não sabe
   mapear para um herói, o que importa apenas para gerar fixtures.

---

## Licença

O código é MIT (veja `LICENSE`). O conteúdo do jogo não é distribuído por este
repositório e não é coberto por ela.
