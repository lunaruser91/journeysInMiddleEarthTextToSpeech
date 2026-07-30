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

## Como é na prática

Você roda um comando e ele pergunta o resto. Cada pergunta traz o estado por
trás dela, então não é preciso lembrar de nada entre uma sessão e outra.

```
Journeys in Middle-earth — narrator
pronto: pt (3,386 blocos)

Qual idioma você quer usar?
      1. cz  Čeština          sem corpus ainda — extraia primeiro
      3. en  English          corpus pronto
   › 10. pt  Português (BR)   corpus pronto, 3,386 blocos gerados
     13. zh  中文             sem corpus ainda — extraia primeiro
  [enter = pt  Português (BR), q = sair]

O que você quer fazer?  [Português (BR)]
   ›  1. Narrar uma partida      assiste à tela e lê em voz alta
      2. Verificar esta máquina  está tudo instalado?
      3. Vozes                   qual voz lê, e trocar
      4. Trocar de idioma        atualmente Português (BR)
  [enter = Narrar uma partida, q = sair]

Qual campanha você está jogando?
   ›  1. bonesofarnor  (seu save mais recente)  completo — 1,200 blocos
      2. embercrown                             não iniciado — 1,105 blocos
      5. shadowedpaths                          não iniciado — 927 blocos
  [enter = bonesofarnor  (seu save mais recente), b = voltar, q = sair]

Como o jogo está rodando?
   ›  1. tela cheia  captura o monitor — o caso usual
      2. em janela   encontra pelo título da janela
  [enter = tela cheia, b = voltar, q = sair]

[scope] campaign=bonesofarnor | 7,314 candidates
[audio] 3,386 blocks rendered
[ocr] AppleVision
[source] display 0 — everything drawn on this monitor, including this window
vá para o jogo agora — começa quando ele estiver na frente
```

Se você escolher uma campanha sem áudio gerado, ele avisa antes de você perder
a sessão, e oferece gerar:

![Escolhendo inglês, depois uma campanha que ainda não tem áudio. Ele avisa, diz
mais ou menos quanto tempo leva para gerar, e oferece fazer isso antes de você
sentar para jogar](docs/images/render-windows.png)

Com o jogo na frente, cada tela lida vira uma linha — a chave, se foi falada, e
por que não quando não foi. (O texto do bloco também é impresso; ele é do jogo,
então não está reproduzido aqui.)

```
observando. Ctrl+C para parar.

[speaking] main:E_306A_0_CAVE_START
[speaking] bonesofarnor:A2_M1_INTRO       (synthesised live)
[silent]   main:UI_THREAT_INCREASE — não bate com a tela
```

---

## Instalação

Você precisa de um Mac ou um PC com Windows, **o jogo instalado no mesmo
computador** — o narrador lê os arquivos de texto dele — e cerca de 350 MB
livres por campanha que você gerar. Nada de placa de vídeo, nada de máquina
rápida.

Precisa de internet duas vezes: uma para instalar, e outra na primeira vez que
você gerar áudio num idioma novo, para baixar aquela voz. Nunca durante a
partida.

**macOS**

```bash
curl -fsSL https://raw.githubusercontent.com/lunaruser91/journeysInMiddleEarthTextToSpeech/main/install.sh | bash
```

**Windows**, no PowerShell

![Um comando, e isto é tudo: as ferramentas que ele encontrou, o clone, o
ambiente, em que idiomas o Windows sabe ler a tela, e um autoteste que
experimenta cada peça com dados reais](docs/images/install-windows.png)

```powershell
irm https://raw.githubusercontent.com/lunaruser91/journeysInMiddleEarthTextToSpeech/main/install.ps1 | iex
```

Isso instala o que faltar, clona o projeto, monta o ambiente e confere o
resultado. Rodar de novo é também como você **atualiza**.

Uma coisa ele não faz por você: **o macOS exige permissão de gravação de tela.**
Ajustes do Sistema → Privacidade e Segurança → Gravação de Tela → marque o
Terminal, depois feche o Terminal (`Cmd`+`Q`) e abra de novo — a permissão é
lida quando o programa inicia, então um terminal já aberto mantém a resposta
antiga. Sem ela a captura trava em vez de dar erro, e é por isso que vale
resolver antes de qualquer outra coisa. O Windows não pede permissão.

Depois é só iniciar:

```bash
cd ~/jime && ~/jime-venv/bin/python jime.py
```

```powershell
cd $HOME\jime; & $HOME\jime-venv\Scripts\python.exe jime.py
```

**Na primeira vez, nesta ordem:** extrair o corpus, gerar o áudio, e então
narrar. A extração leva um minuto, a geração cerca de vinte minutos para uma
campanha mais o texto compartilhado. Depois disso, só narrar importa.

---

## Usando

Rode sem argumentos e ele pergunta. Cada pergunta mostra o estado por trás dela
— quais idiomas têm corpus, quanto de cada campanha já foi gerado — para você
não precisar lembrar onde parou.

| Opção | O que faz | Quando você precisa |
|---|---|---|
| **Narrar uma partida** | Assiste à tela e lê cada bloco em voz alta | Toda sessão |
| **Verificar esta máquina** | Se está tudo instalado e permitido | Quando algo não funciona |
| **Vozes** | Lista as vozes deste idioma, e troca | Para trocar ou calibrar uma voz |
| **Trocar de idioma** | Muda o idioma de tudo que vem depois | Sem reiniciar |

Extrair e gerar não são tarefas separadas. Narrar pergunta: escolha um idioma sem
corpus e ele oferece extrair da sua própria instalação; escolha uma campanha sem
áudio e ele oferece gerar, incluindo o `main` sem você pedir.

O idioma é a primeira pergunta e vale para tudo depois dela — o corpus, a voz e o
próprio menu. `q` sai de qualquer lugar, Enter aceita o destacado, e `b` volta
uma pergunta.

**Gere o `main` também.** Ele guarda o texto que todas as campanhas compartilham
— interface, tiles, ativações de inimigos, tesouros — e cerca de metade dos
blocos falados numa sessão real vêm dele. Uma campanha gerada sem o `main` deixa
metade do jogo em silêncio. O menu oferece isso quando percebe.

---

## Durante a partida

**Se o jogo roda em tela cheia, escolha a opção de tela cheia.** A captura de
janela não alcança um jogo em tela cheia em nenhum dos dois sistemas: o macOS lhe
dá um Space próprio e não desenha Space inativo, e o Windows deixa a tela cheia
*exclusiva* passar por cima do compositor de onde a captura lê. Onde o jogo
oferecer *borderless windowed*, essa é a melhor resposta no Windows.

A opção de tela cheia captura o monitor inteiro, então o narrador espera o jogo
ser a janela da frente e fica calado sempre que não for. Senão ele leria a sua
área de trabalho — numa sessão chegou a ler o próprio console de volta.

**O Prólogo e os Epílogos ficam mudos de propósito.** O jogo narra esses com voz
gravada. Se a sua primeira sessão abrir num Prólogo, não acontecer nada é o
comportamento certo.

**Algumas telas são faladas na hora.** Blocos que carregam um valor que só existe
na mesa — o nome de um herói, um número de ameaça — não podem ser gravados antes,
então são sintetizados durante a partida a partir do texto do próprio jogo, com o
valor da tela no lugar.

**Se a mesa lê no próprio ritmo**, o `--manual` segura cada tela até você apertar
uma tecla:

```bash
cd ~/jime && ~/jime-venv/bin/python jime.py play --campaign bonesofarnor --display --manual
```

Quando ele não tem certeza de qual bloco está na tela, não fala nada. Silêncio se
recupera; narrar o bloco errado não, porque o jogador age pelo que ouve.

---

## Quando dá errado

Escolha **Verificar esta máquina** no menu. Ele diz o que está faltando, em vez
de falhar de forma obscura.

As quatro respostas mais comuns:

- **Não encontra a janela do jogo, ou só lê quando você dá alt+tab.** Escolha a
  opção de tela cheia. No Windows, configure o jogo como borderless windowed se
  ele oferecer.
- **Reconhece as telas mas não fala nada.** Aquela campanha ainda não tem áudio —
  volte e gere. O menu oferece isso quando percebe.
- **Demora para reagir.** Acrescente `--profile` ao `jime play`: ele cronometra
  cada etapa por tela, e aí dá para ver se a demora é a animação do próprio jogo,
  o OCR, o reconhecimento ou a síntese. Numa máquina sem placa de vídeo o jogo
  sozinho pode tomar o processador inteiro e não sobrar nada para o narrador.

  Se a linha lenta for a `settling`, parte dela é sua para recuperar. O narrador
  espera a tela ficar parada antes de ler — 11 quadros parados, que aos 10 fps
  padrão são 1,1 s em toda tela — porque uma caixa de diálogo que pausa no meio
  da animação é idêntica a uma que terminou, e ler cedo é ler texto meio
  desenhado.

  O `--profile` também imprime `paused Nf`: a maior pausa que o jogo realmente
  deu no meio da animação, em quadros. O `--stable-frames` só precisa ser maior
  que isso. Medido numa máquina Windows ao longo de 15 telas, nada passou de 3, e
  o `--stable-frames 6` tirou 0,5 s de cada tela sem nenhuma leitura parcial:

  ```bash
  ~/jime-venv/bin/python jime.py play --display --stable-frames 6
  ```

  Confira os seus próprios números de `paused` antes de baixar — uma gravação
  antiga, em outro hardware, achou pausas de até 10, e é por isso que o padrão
  é 11.
- **Windows: o motor de fala não carrega.** Falta o Visual C++ Redistributable:
  `winget install --id Microsoft.VCRedist.2015+.x64 -e`
- **Windows: ele lê, mas come os acentos.** A tela está sendo reconhecida no
  idioma errado — o caso mais comum é um Windows em inglês jogando em outro
  idioma. O `selftest.py` reprova a verificação `reads the game's own language` e
  diz qual reconhecedor ele conseguiu. Num PowerShell **como administrador**, com
  o idioma do seu jogo no lugar de `pt-BR`:

  ```powershell
  Add-WindowsCapability -Online -Name "Language.OCR~~~pt-BR~0.0.1.0"
  ```

  O `Get-WindowsCapability -Online -Name "Language.OCR*"` lista todos os 35. O
  ucraniano não está entre eles de jeito nenhum — nesse caso o `--ocr rapid` é a
  única opção que lê os acentos.
- **Windows: os acentos saem como `v├í` ou `ÔÇö`.** Só quando você manda a saída
  para algum lugar — para o `Tee-Object`, para guardar um log. O PowerShell
  decodifica o cano com a code page dele, e nenhum programa do outro lado
  consegue mudar isso; então avise o seu shell uma vez por janela:

  ```powershell
  [Console]::OutputEncoding = [Text.Encoding]::UTF8
  cd $HOME\jime; & $HOME\jime-venv\Scripts\python.exe jime.py play --display --profile | Tee-Object output\sessao.log
  ```

  Direto na tela já sai certo; isso é só sobre o cano.

Se a dúvida for a captura em si, esta sonda mede para você — comece ela, vá para
o jogo, volte depois:

```bash
cd ~/jime && ~/jime-venv/bin/python probe_capture.py --seconds 40
```

Ela escreve em `output/probe.log` em vez do terminal, porque olhar o terminal
muda o que está sendo medido.

## Mandar um log para alguém

Um log normal carrega o texto do próprio jogo — a prévia do bloco embaixo de cada
tela que casou, e o texto cru da tela embaixo de cada uma que não casou.
Acrescente `--share` e nada disso é impresso: chaves, pontuações, motivos de
recusa e tempos continuam, e o texto vira a forma dele, "3 paragraph(s), 412
chars". Isso basta para distinguir uma tela de menu recusada corretamente de um
bloco real perdido por três pontos.

```bash
~/jime-venv/bin/python jime.py play --display --profile --share
```

A saída do `selftest.py` já pode ser enviada como está — ela não tem texto nenhum
do jogo, e os caminhos são escritos com `~` no lugar da sua pasta pessoal.

---

## Atualizando

Rode o instalador de novo. Ele puxa e reinstala, e não mexe em mais nada. Ou na
mão:

```bash
cd ~/jime && git pull
```

Seu corpus, o áudio gerado e as vozes baixadas ficam em `corpus/`, `output/` e
`voices/`, e o git não toca em nenhum deles. Atualizar nunca regera nada — a
menos que a receita mude, já que voz e ritmo fazem parte da chave de cache. Os
commits avisam quando isso acontece.

---

## Outros idiomas e vozes

Toda localização que o jogo traz tem uma voz, então não existe nada que você
consiga ler e não consiga ouvir.

```bash
cd ~/jime
~/jime-venv/bin/python jime.py voices              # a voz padrão de cada idioma
~/jime-venv/bin/python jime.py languages           # o que cada localização suporta
~/jime-venv/bin/python jime.py glyphs --lang pt    # quais palavras de ícone faltam
~/jime-venv/bin/python jime.py clean               # áudio sobrando de uma voz antiga
```

O último precisa que aquele idioma já tenha sido extraído — ele lê o seu corpus.

Só o português tem ritmo de leitura **medido**; os outros doze usam o ritmo da
própria voz, que é mais rápido do que qualquer um narra. `jime voices --calibrate
--lang de` gera uma amostra, informa o ritmo e imprime a linha para colar no
`voices.py`.

Os ícones do jogo são falados como palavras em português e inglês. Acrescentar um
idioma são cerca de 21 palavras, não uma investigação nova — o `jime glyphs` diz
exatamente quais.

---

## Onde as coisas ficam

O instalador cria duas pastas na sua pasta pessoal: `~/jime` (o projeto) e
`~/jime-venv` (o Python dele). **Tudo que o narrador gera fica dentro de
`~/jime`** — nada se espalha por aí.

```
corpus/          texto extraído do seu jogo           (gerado, ignorado)
voices/          modelos de voz, ~60 MB cada          (ignorado)
output/          TUDO que é gerado                    (ignorado)
  audio_<lang>/    a geração, mais o manifest.json
  live_<lang>/     blocos sintetizados durante a partida
  selftest/        o que o autoteste produziu
docs/            como funciona, e o que custou descobrir
```

---

## Como funciona

Captura → gatilho → OCR → reconhecimento → player. A tela é observada até
estabilizar, lida, comparada com o texto extraído da sua própria instalação, e o
bloco correspondente é falado. Contra 631 telas reais reconstruídas a partir dos
logs do próprio jogo, ele identifica o bloco certo **99,2%** das vezes e fala o
errado 0,5% das vezes.

A síntese é o [Piper](https://github.com/OHF-Voice/piper1-gpl): um modelo ONNX de
60 MB na CPU, sem GPU, nada para assinar. Tem dicção clara e prosódia plana — ele
lê, não interpreta.

O raciocínio, as medições e os erros estão em
[docs/ENGINEERING.md](docs/ENGINEERING.md) (em inglês), e cada ferramenta carrega
a própria explicação no topo do arquivo.

---

## Licença

O código é MIT (veja `LICENSE`). O conteúdo do jogo não é distribuído por este
repositório e não é coberto por ela.
