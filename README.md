# Automatic narrator for *Journeys in Middle-earth*

***English** · [Português](README.pt-BR.md)*

Reads aloud, **entirely offline**, the text the official *The Lord of the Rings:
Journeys in Middle-earth* app (Fantasy Flight / Asmodee) puts on screen during
play. It watches the screen, works out which block of the game's text is
showing, and speaks it.

The app records narration only for each campaign's Prologue and Epilogues. Every
other block is read aloud by a player, and that is what this replaces.

All **thirteen** of the game's localisations can be narrated.

> ### License notice — read before any `git add`
>
> The Asmodee Digital Terms (§5.3/§5.4) prohibit extracting the content, **even for
> individual use**. The text is a protected work (FFG + Middle-earth Enterprises) and the
> generated audio is a derivative work. FFG/Asmodee have already issued DMCA against fan mods.
>
> **This repository publishes an extractor and a renderer, never the content.** Each
> person runs the extraction against their own installation, for local, non-distributed
> use. The `.gitignore` blocks corpus, manifests, audio (in every format) and assets.

---

## What using it looks like

You run one command and it asks the rest. Every question carries the state
behind it, so nothing has to be remembered between sessions.

```
Journeys in Middle-earth — narrator
ready: en (3,518 blocks)

Which language to work in?
      1. cz  Čeština          no corpus yet — extract first
   ›  3. en  English          corpus ready, 3,518 blocks rendered
     10. pt  Português (BR)   no corpus yet — extract first
     13. zh  中文             no corpus yet — extract first
  [enter = en  English, q = quit]

What would you like to do?  [English]
   ›  1. Narrate a game       watch the screen and read it aloud
      2. Check this machine   is everything installed?
      3. Voices               which voice reads, and change it
      4. Change language      currently English
  [enter = Narrate a game, q = quit]

Which campaign are you playing?
   ›  1. bonesofarnor  (your most recent save)  complete — 1,259 blocks
      2. embercrown                             not started — 1,157 blocks
      5. shadowedpaths                          not started — 976 blocks
  [enter = bonesofarnor  (your most recent save), b = back, q = quit]

How is the game running?
   ›  1. fullscreen   capture the display — the usual case
      2. in a window  find it by window title
  [enter = fullscreen, b = back, q = quit]

[scope] campaign=bonesofarnor | 7,314 candidates
[audio] 3,518 blocks rendered
[ocr] AppleVision
[source] display 0 — everything drawn on this monitor, including this window
switch to the game now — this starts when it is in front
```

Pick a campaign with nothing rendered and it says so before you waste a
session, and offers to render it:

![Choosing English, then a campaign with no audio yet. It says so, says roughly
how long rendering takes, and offers to do it before you sit down to
play](docs/images/render-windows.png)

Once the game is in front, each screen it reads is one line — the key, whether it
was spoken, and why not when it was not. (The block's own words are printed too;
they are the game's, so they are not reproduced here.)

```
watching. Ctrl+C to stop.

[speaking] main:E_306A_0_CAVE_START
[speaking] bonesofarnor:A2_M1_INTRO       (synthesised live)
[silent]   main:UI_THREAT_INCREASE — cannot align with the screen
```

---

## Install

You need a Mac or a Windows PC, **the game installed on the same computer** —
the narrator reads its text files — and about 350 MB free per campaign you
render. No graphics card and nothing fast.

It needs the internet twice: once to install, and once more the first time you
render in a new language, to fetch that voice. Never during a game.

**macOS**

```bash
curl -fsSL https://raw.githubusercontent.com/lunaruser91/journeysInMiddleEarthTextToSpeech/main/install.sh | bash
```

**Windows**, in PowerShell

![One command, and this is the whole of it: the tools it found, the clone, the
environment, which languages Windows can read the screen in, and a self-test that
tries every part on real data](docs/images/install-windows.png)

```powershell
irm https://raw.githubusercontent.com/lunaruser91/journeysInMiddleEarthTextToSpeech/main/install.ps1 | iex
```

That installs whatever is missing, clones the project, builds the environment and
checks the result. Running it again is also how you **update**.

One thing it cannot do for you: **macOS needs screen recording permission.**
System Settings → Privacy & Security → Screen Recording → tick Terminal, then
quit Terminal (`Cmd`+`Q`) and reopen it — the permission is read when a program
starts, so a running terminal keeps the old answer. Without it, capture hangs
rather than failing, which is why this is worth doing before anything else.
Windows needs no permission.

Then start it — **macOS**:

```bash
cd ~/jime && ~/jime-venv/bin/python jime.py
```

**Windows**, in PowerShell:

```powershell
cd $HOME\jime; & $HOME\jime-venv\Scripts\python.exe jime.py
```

**The first time, in this order:** extract the corpus, render the audio, then
narrate. Extraction takes a minute, rendering about twenty minutes for a
campaign plus the shared text. After that only narrating matters.

---

## Using it

Run it with no arguments and it asks. Every question shows the state behind it —
which languages have a corpus, how much of each campaign is already rendered —
so you do not have to remember where you left off.

| Option | What it does | When you need it |
|---|---|---|
| **Narrate a game** | Watches the screen and reads each block aloud | Every session |
| **Check this machine** | Whether everything is installed and permitted | When something does not work |
| **Voices** | Lists every voice for this language, and changes it | To change or calibrate a voice |
| **Change language** | Switches the language everything after it uses | Without restarting |

Extracting and rendering are not separate errands. Narrating asks: pick a
language with no corpus and it offers to extract it from your own installation;
pick a campaign with no audio and it offers to render that, and adds `main`
without being asked.

The language is the first question and applies to everything after it — the
corpus, the voice, and the menu itself. `q` quits from anywhere, Enter takes the
highlighted default, and `b` steps back a question.

**Render `main` too.** It holds the text every campaign shares — interface,
tiles, enemy activations, treasure — and about half the blocks spoken in a real
session come from it. A campaign rendered without `main` leaves half the game
silent. The menu offers it when it notices.

---

## During a game

**If the game runs fullscreen, choose the fullscreen option.** Window capture
cannot reach a fullscreen game on either platform: macOS gives it a Space of its
own and does not draw an inactive Space, and Windows lets exclusive fullscreen
bypass the compositor that screen capture reads from. Where the game offers
*borderless windowed*, that is the better answer on Windows.

The fullscreen option captures the whole monitor, so the narrator waits until
the game is the window in front, and stays quiet whenever it is not. Otherwise
it would read your desktop — in one session it read its own console back.

**The Prologue and Epilogues stay silent on purpose.** The game narrates those
itself, with recorded voice. If your first session opens on a Prologue, nothing
happening is the correct behaviour.

**A few screens are spoken as they appear.** Blocks carrying a value that only
exists at the table — a hero's name, a threat number — cannot be recorded in
advance, so they are synthesised during play from the game's own wording with
the screen's value in the gap.

**If the table reads at its own pace**, `--manual` holds each screen until you
press a key:

```bash
cd ~/jime && ~/jime-venv/bin/python jime.py play --campaign bonesofarnor --display --manual
```

When it is not sure which block is on screen, it says nothing. Silence is
recoverable; narrating the wrong block is not, because the player acts on what
they hear.

---

## When it goes wrong

Choose **Check this machine** from the menu. It names what is missing rather
than failing obscurely.

The most common answers:

- **It finds no game window, or only reads when you alt-tab.** Choose the
  fullscreen option. On Windows, set the game to borderless windowed if it
  offers it.
- **It recognises screens but says nothing.** That campaign has no audio yet —
  go back and render it. The menu offers this when it notices.
- **It reacts slowly.** Add `--profile` to `jime play`: it times each stage per
  screen, so you can see whether the delay is the game's own animation, the
  OCR, the matcher or the synthesis. On a machine without a graphics card the
  game itself can take the whole processor and leave nothing for the narrator.

  If the slow line is `settling`, some of it is yours to take back. The narrator
  waits for the screen to hold still before reading it — 11 quiet frames, which
  at the default 10 fps is 1.1 s on every screen — because a dialogue box that
  pauses mid-animation looks exactly like one that has finished, and reading it
  early means reading half-drawn text.

  `--profile` also prints `paused Nf`: the longest the game was actually seen to
  pause mid-animation, in frames. `--stable-frames` only has to clear that.
  Measured on one Windows machine over 15 screens, nothing went above 3, and
  `--stable-frames 6` took 0.5 s off every screen with no half-drawn read:

  ```bash
  cd ~/jime && ~/jime-venv/bin/python jime.py play --display --stable-frames 6
  ```

  Check your own `paused` numbers before lowering it — an older recording on
  different hardware found pauses up to 10, which is why the default is 11.
- **Windows: the speech engine will not load.** The Visual C++ Redistributable
  is missing: `winget install --id Microsoft.VCRedist.2015+.x64 -e`
- **Windows: it reads, but eats the accents.** The screen is being recognised in
  the wrong language — most often on an English Windows playing in another
  language. `selftest.py` fails the check `reads the game's own language` and says
  which one it got. In an elevated PowerShell, with your game's language in place
  of `pt-BR`:

  ```powershell
  Add-WindowsCapability -Online -Name "Language.OCR~~~pt-BR~0.0.1.0"
  ```

  `Get-WindowsCapability -Online -Name "Language.OCR*"` lists all 35. Ukrainian
  is not among them at all — there, `--ocr rapid` is the only option that reads
  the accents.
- **Windows: accented letters come out as `v├í` or `ÔÇö`.** Only when you pipe
  the output somewhere — into `Tee-Object` to keep a log, say. PowerShell decodes
  the pipe with its own code page and no program on the far end can change that,
  so tell your shell once per window:

  ```powershell
  [Console]::OutputEncoding = [Text.Encoding]::UTF8
  cd $HOME\jime; & $HOME\jime-venv\Scripts\python.exe jime.py play --display --profile | Tee-Object output\sessao.log
  ```

  On the screen alone it is already correct; this is only about the pipe.

If capture itself is in doubt, this samples it for you — start it, switch to the
game, come back:

```bash
cd ~/jime && ~/jime-venv/bin/python probe_capture.py --seconds 40
```

It writes to `output/probe.log` rather than the terminal, because looking at the
terminal changes what is being measured.

## Sending somebody a log

A normal log carries the game's own text — the block preview under every screen
that matched, and the raw screen text under every one that did not. Add `--share`
and none of it is printed: keys, scores, refusal reasons and timings all stay, and
the text becomes its own shape, "3 paragraph(s), 412 chars". That is enough to
tell a menu screen correctly refused from a real block missed by three points.

```bash
cd ~/jime && ~/jime-venv/bin/python jime.py play --display --profile --share
```

`selftest.py` output is safe to send as it stands — it contains no game text at
all, and paths are written with `~` in place of your home folder:

```bash
cd ~/jime && ~/jime-venv/bin/python selftest.py
```

---

## Updating

Re-run the installer. It pulls and reinstalls and touches nothing else. Or by
hand:

```bash
cd ~/jime && git pull
```

Your corpus, rendered audio and downloaded voices live in `corpus/`, `output/`
and `voices/`, none of which git touches. Updating never re-renders anything —
unless the recipe itself changes, since voice and pace are part of the cache
key. Commits say so when that happens.

---

## Other languages and voices

Every localisation the game ships has a voice, so there is nothing you can read
but not hear.

```bash
cd ~/jime
~/jime-venv/bin/python jime.py voices              # the default voice per language
~/jime-venv/bin/python jime.py languages           # what each localisation supports
~/jime-venv/bin/python jime.py glyphs --lang pt    # which icon words are missing
~/jime-venv/bin/python jime.py clean               # audio left over from an older voice
```

`clean` needs that language **rendered** first — it reads the manifest beside
your audio, never your corpus. `glyphs` is the one that needs an extract.

Only Portuguese has a **measured** reading pace. The other twelve read at 1.20,
the fastest `prosody.py` allows — not the voice's own speed, and slower than it.
`jime voices --calibrate --lang de` measures one, but it needs that language
extracted first, and it will tell you rather than guess when the pace you are
aiming for is outside what the voice can be asked for.

The game's icons are spoken as words in Portuguese and English. Adding a
language is about 21 words, not a fresh investigation — `jime glyphs` says
exactly which.

---

## Where things live

The installer creates two folders in your home directory: `~/jime` (the project)
and `~/jime-venv` (its Python). **Everything the narrator generates stays inside
`~/jime`** — nothing is scattered elsewhere.

```
corpus/          text extracted from your game        (generated, ignored)
voices/          voice models, ~60 MB each            (ignored)
output/          EVERYTHING that is generated         (ignored)
  audio_<lang>/    the render, plus manifest.json
  live_<lang>/     blocks synthesised during play
  selftest/        what the self-test produced
docs/            how it works, and what it cost to find out
```

---

## How it works

Capture → trigger → OCR → matcher → player. The screen is watched until it
settles, read, matched against the text extracted from your own installation,
and the matching block is spoken. Against 631 real screens rebuilt from the
game's own logs it identifies the right block **99.2%** of the time and speaks
the wrong one 0.5% of the time.

Synthesis is [Piper](https://github.com/OHF-Voice/piper1-gpl): a 60 MB ONNX
model on the CPU, no GPU, nothing to sign. It has clear diction and flat
prosody — it reads, it does not act.

The reasoning, the measurements and the mistakes are in
[docs/ENGINEERING.md](docs/ENGINEERING.md), and the individual tools each carry
their own explanation at the top of the file.

---

## License

The code is MIT (see `LICENSE`). The game content is not distributed by this repository
and is not covered by it.
