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
| **Gerar o áudio** | Transforma o texto extraído em arquivos de fala | Uma vez por campanha |
| **Extrair o corpus** | Lê os arquivos do próprio jogo | Uma vez por idioma |
| **Situação** | O que está extraído, o que está gerado, quanto | Para ver onde você parou |
| **Verificar esta máquina** | Se está tudo instalado e permitido | Quando algo não funciona |
| **Vozes** | Qual voz fala cada idioma | Para trocar ou calibrar uma voz |
| **Trocar de idioma** | Muda o idioma de tudo que vem depois | Sem reiniciar |

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
- **Windows: o motor de fala não carrega.** Falta o Visual C++ Redistributable:
  `winget install --id Microsoft.VCRedist.2015+.x64 -e`

Se a dúvida for a captura em si, esta sonda mede para você — comece ela, vá para
o jogo, volte depois:

```bash
cd ~/jime && ~/jime-venv/bin/python probe_capture.py --seconds 40
```

Ela escreve em `output/probe.log` em vez do terminal, porque olhar o terminal
muda o que está sendo medido.

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
