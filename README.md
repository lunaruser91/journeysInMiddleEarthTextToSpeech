# Automatic narrator for *Journeys in Middle-earth*

Reads aloud, **entirely offline**, the text the official *The Lord of the Rings:
Journeys in Middle-earth* app (Fantasy Flight / Asmodee) puts on screen during
play. It watches the screen, works out which block of the game's text is showing,
and speaks it.

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

## Project status

| Phase | What it does | Status |
|---|---|---|
| 1 | app assets → corpus, any of 13 languages | **done** — 13,018 keys in pt, 9,814 narration blocks |
| 2 | corpus → pre-rendered audio | **done and measured** — RTF 0.05; a campaign plus the shared text in ~30 min |
| 3 | screen → OCR → matching → speech | **works during a real game** — confirmed by ear across a session |

---

## Getting started

If you are comfortable in a terminal, skip to [Installation](#installation).
Otherwise this section assumes nothing.

### What you need first

- **A Mac, or Windows.** The macOS path is the tested one; Windows is written
  and installs, but see [What is missing](#what-is-missing) for what has not
  been exercised there.
- **The game installed on this same computer.** The narrator reads the game's own
  text files, so it has to find them. Steam or the standalone app both work.
- **About 300 MB free** for the generated speech, per language.

You do **not** need a fast machine, a graphics card, or an internet connection
once it is set up.

### Step 1 — open the Terminal

Press `Cmd` + `Space`, type `Terminal`, press Enter. A window opens where you
type commands. Every block below is one command: copy it, paste it, press Enter,
wait for it to finish before the next.

### Step 2 — install the tools it needs

```bash
xcode-select --install
```

A dialog may appear asking to install developer tools — accept it. If it says
they are already installed, carry on.

```bash
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
```

That is [Homebrew](https://brew.sh), the usual way to install software on a Mac
from the terminal. It will ask for your password. If you already have it, this
says so and changes nothing.

```bash
brew install python@3.13 ffmpeg git
```

### Step 3 — download this project

```bash
git clone https://github.com/lunaruser91/journeysInMiddleEarthTextToSpeech.git ~/jime
cd ~/jime
```

That puts it in a folder called `jime` in your home directory. If you prefer not
to use `git`, the green **Code** button on the GitHub page has *Download ZIP*;
unzip it and `cd` into it instead.

### Step 4 — set it up

```bash
python3.13 -m venv ~/jime-venv
~/jime-venv/bin/pip install -e '.[tts,ocr,capture]'
```

The second one takes a few minutes and prints a lot. It is finished when your
prompt comes back.

`capture` is what lets it see the screen — leaving it out gets you a working
setup that cannot capture anything, which is a confusing way to find out. The
extras resolve per platform, so the same command is right on macOS and Windows.

### Step 5 — let it see the screen

The narrator reads what is on screen, and macOS requires permission for that.

Open **System Settings → Privacy & Security → Screen Recording**, and switch on
**Terminal**. Then **quit Terminal completely** (`Cmd` + `Q`) and open it again —
the permission is only read when the program starts.

Nothing here needs to be signed or notarised: the permission attaches to the
Terminal, and this project runs inside it.

### Step 6 — run it

```bash
cd ~/jime && ~/jime-venv/bin/python jime.py
```

That opens the menu. There are no flags to remember; it asks.

**The first time, in this order:**

1. **Extract the corpus** — reads the game's own files and writes out the text.
   Takes a minute. Nothing works before this.
2. **Render audio** — turns that text into speech. About half an hour per
   campaign. Pick your campaign, and say yes when it offers to add `main`.
3. **Narrate a game** — open the game, then choose this. It watches, recognises
   each screen and reads it aloud.

Afterwards only step 3 matters, until you start a different campaign.

### What each menu option does

| Option | What it does | When you need it |
|---|---|---|
| **Narrate a game** | Watches the screen and reads each block aloud | Every session |
| **Render audio** | Turns the extracted text into speech files | Once per campaign |
| **Extract the corpus** | Reads the game's own files | Once per language |
| **Status** | What is extracted, what is rendered, how much | To see where you left off |
| **Check this machine** | Whether everything is installed and permitted | When something does not work |
| **Voices** | Which voice speaks each language | To change or calibrate a voice |

`b` goes back a question, `q` quits, and Enter takes the highlighted default.

### If something goes wrong

Run **Check this machine** first — it names what is missing rather than failing
obscurely.

The two most common answers:

- **It finds no game window.** Use the fullscreen option. A fullscreen game on
  macOS sits on its own Space, and macOS does not draw a Space that is not in
  front, so it is invisible from the Terminal until you switch to it.
- **It recognises screens but says nothing.** That campaign has no audio yet —
  go back and render it. The menu offers this when it notices.

---

## Installation

**macOS**, for anyone who already has Python and Homebrew:

```bash
brew install ffmpeg
python3.13 -m venv ~/jime-venv
~/jime-venv/bin/pip install -e '.[tts,ocr,capture]'
```

**Windows**, in PowerShell:

```powershell
winget install --id Python.Python.3.13 -e --accept-source-agreements --accept-package-agreements
winget install --id Git.Git -e --accept-package-agreements
winget install --id Gyan.FFmpeg -e --accept-package-agreements
```

One package per command — `winget` takes a single `--id`.

`onnxruntime`, which Piper needs, will not load without the **Microsoft Visual
C++ Redistributable**. A fresh Windows image often lacks it, and the failure
names neither Piper nor the redistributable:

    DLL load failed while importing onnxruntime_pybind11_state

```powershell
winget install --id Microsoft.VCRedist.2015+.x64 -e
```

Close and reopen PowerShell so the new commands are on PATH, then:

```powershell
git clone https://github.com/lunaruser91/journeysInMiddleEarthTextToSpeech.git $HOME\jime
cd $HOME\jime
py -3.13 -m venv $HOME\jime-venv
& $HOME\jime-venv\Scripts\pip install -e '.[tts,ocr,capture]'
```

`ocr` and `capture` resolve per platform: on Windows they bring RapidOCR and
`windows-capture`, which wraps Windows.Graphics.Capture — the only API that sees
a Unity window, since BitBlt and PrintWindow return black frames for one.

Windows needs no permission prompt for capture. Windows 11 draws a yellow border
around a window being captured; that is cosmetic and cannot be switched off.

Then check the machine before trusting it:

```powershell
& $HOME\jime-venv\Scripts\python selftest.py
```

Synthesis is [Piper](https://github.com/OHF-Voice/piper1-gpl): a small ONNX model
that runs on the CPU. A voice is about 60 MB and is fetched the first time it is
needed. There is no GPU requirement and nothing to sign.

A shortcut saves typing:

```bash
alias jime="~/jime-venv/bin/python"
```

---

## Usage

Run it with no arguments and it asks. Every question shows the state behind it —
which languages have a corpus, how much of each campaign is already rendered —
so you do not have to remember where you left off.

```bash
jime
```

The flags are still there and still faster once you know them.
`jime <command> --help` shows the full options for each.

```bash
jime status                    # what is done and what is missing
jime doctor                    # is this machine ready?
jime languages                 # what each of the 13 localisations supports
jime voices                    # which voice speaks each language
jime extract --lang pt         # game assets  ->  corpus
jime render --campaign bonesofarnor
jime play --campaign bonesofarnor --display   # fullscreen game
jime check --lang pt           # audit the rendered pace
```

Render a whole campaign plus the shared text, unattended and resumable:

```bash
./render_all.sh                # bonesofarnor, then main
./render_all.sh --lang en      # the same in English
```

`main` holds the text every campaign shares — interface, tiles, enemy
activations, treasure. **48.8% of everything spoken across 631 real screens comes
from it**, so a campaign rendered without it leaves half the session silent.

### Languages and voices

Every localisation the game ships has a Piper voice, so there is nothing you can
read but not hear.

```bash
jime voices                      # the default voice for each language
jime voices --lang de            # what else is available
jime render --lang de --voice de_DE-eva_k-x_low
```

Only Portuguese and English have a **measured** reading pace; the rest fall back
to the voice's own, which is faster than anyone narrates.
`jime voices --calibrate --lang de` renders a sample, reports the pace and prints
the line to paste into `voices.py`.

`jime languages` shows which languages have the icon vocabulary filled in —
adding one is about 21 words, not a new investigation.

### The individual tools

**Phase 1 — extract the corpus from your own installation**

```bash
jime phase1_extract.py "<.../JiME.app/.../StreamingAssets/bundles>" -o corpus/ --lang pt
```

The app is Unity 2022.3 with Mono and **nothing is obfuscated**: each localisation
bundle holds a single `TextAsset` that is a clean CSV.

**Phase 2 — render the audio**

```bash
jime phase2_render.py --lang pt --campaign bonesofarnor
jime phase2_render.py --lang pt --campaign bonesofarnor --dry-run   # estimate first
jime phase2_render.py --lang pt --key "main:G22_SWORD_TRUE"         # one block
jime check_pace.py output/audio_pt/manifest.json                    # audit the result
```

A block whose `.opus` already exists is skipped and the manifest is rewritten
every 50 blocks and on Ctrl+C, so stopping and restarting costs nothing. The
voice, the pace and the effects chain all go into the cache key, so changing any
of them re-renders rather than quietly mixing two recipes.

**Phase 3 — narrate a live game**

```bash
jime narrator.py --display           # fullscreen game — the usual case
jime narrator.py                     # windowed game, found by window title
jime narrator.py --list-windows      # what the capture backend can see
jime narrator.py --from-video FILE   # replay a recording, no permission needed
```

**If the game runs fullscreen, use `--display`.** A fullscreen application on
macOS gets a Space of its own, and macOS does not draw a Space that is not in
front: while you are looking at the terminal the game's window is not merely
hidden, it is not being rendered, and no capture API can reach it. Capturing the
*display* sidesteps this, because a display always shows whichever Space is
active — which, while you are playing, is the game's.

Window capture is still there for a windowed game, and waits (90 s by default,
`--wait`) for the window to appear, so you can start in the terminal and switch
to the game.

On macOS the first capture triggers the system prompt. If it hangs instead, the
permission is missing: System Settings → Privacy & Security → Screen Recording →
tick your terminal, then **restart the terminal**. Nothing needs to be signed or
notarised: the grant attaches to the terminal and these scripts inherit it.

Check that pixels really arrive before trusting a session:

```bash
jime test --capture --display
```

**Testing the recognition without a game**

```bash
jime demo.py ~/Downloads/screen.webp --no-audio   # one screen: OCR + matching
jime batch.py ~/Downloads/*.webp --keys keys.txt  # several, with hit rate
jime watch_log.py --all                           # the game's own event log
jime test_matcher.py                              # 631 real screens, with noise
```

---

## Where things live

The project is self-contained. **Nothing is written outside the repository.**

```
corpus/          corpus extracted from the game       (generated, ignored)
voices/          Piper voice models, ~60 MB each      (ignored)
output/          EVERYTHING that is generated         (ignored)
  audio_<lang>/    the render, plus manifest.json
  live_<lang>/     blocks synthesised during play
  ocr-fixtures/    real screens with the right key

docs/            the investigation notes
legacy/          the original extraction script, kept for comparison
```

| file | what it does |
|---|---|
| `jime.py` | the one command everything else hangs off |
| `phase1_extract.py` | the game's AssetBundles → JSON/CSV corpus |
| `phase2_render.py` | corpus → audio, with a resumable hash-based cache |
| `voices.py` | which voice speaks each language, and its measured pace |
| `glyphs.py` | game icons → spoken words; numbers spelled out; per language |
| `matcher.py` | screen text → the corpus block it came from |
| `trigger.py` | when a screen has settled and is worth reading |
| `live.py` | the blocks that can only be synthesised during play |
| `player.py` | queue, interrupt, repeat, and what to stay silent about |
| `narrator.py` | the loop that joins all of the above |
| `check_pace.py` | finds blocks whose pace strays from the median |
| `test_matcher.py` | harness: 631 real screens + synthetic OCR noise |

---

## What was measured

Everything below is measurement on this hardware (MacBook Pro M5 Pro, macOS 26
Tahoe), not estimate. Detail in [docs/PHASE2-MEASUREMENTS.md](docs/PHASE2-MEASUREMENTS.md)
and [docs/PHASE3-STRATEGY.md](docs/PHASE3-STRATEGY.md).

### Synthesis

| | |
|---|---|
| RTF (wall clock ÷ audio duration) | **0.05** |
| Bones of Arnor + shared text (3,386 blocks, 12.4 h of audio) | **~30 min** |
| Every campaign (38.1 h of audio) | ~2 h |
| Model on disk | 60 MB, CPU only |
| Reading pace | 155 wpm, inside the audiobook range |

This project started on Chatterbox, a voice-cloning model, and measured **RTF
3.7** — fifty hours for one campaign plus the shared text. Swapping to Piper made
it forty minutes: **74× faster**, on the same 226 blocks, with zero failures
against fifteen. It also removed the GPU requirement, dropped the model from 3 GB
to 60 MB, and took the languages from ten to thirteen.

What it cost is expressiveness. Piper has clear diction and flat prosody; it
reads, it does not act. Chatterbox sounded better. The measurement in §6c of the
performance notes is why it lost anyway.

**Two things were tried on top of Piper and removed.** An aged-voice filter chain
(pitch down, low lift, high rolloff, tremolo, echo) made it soft, slow and hard
to make out — it cut 2.5 dB where the consonants live. And two render processes
in parallel run **55% slower** than one, because the decode is bound by memory
bandwidth: each process reads its own weights per step, so two double the demand
without doubling the supply.

### Screen recognition

Measured against **631 real screens** rebuilt from the game's own logs — without
transcribing any of them by hand.

| OCR noise | hit rate | **wrong** | refusal |
|---:|---:|---:|---:|
| 0% | **99.2%** | 0.5% | 0.3% |
| 2% | 95.6% | 0.5% | 4.0% |
| 5% | 94.8% | 0.5% | 4.8% |
| 10% | 73.4% | 1.0% | 25.7% |

Refusing is the right behaviour: silence is recoverable, narrating the wrong
block is not, because the player acts on what they hear.

Scoping by the save (campaign, adventure) barely changes the result — the work is
done by the length and margin guards, and by matching per paragraph.

---

## Three discoveries that changed the project

### 1. The game keeps a log with the exact keys

`~/Library/Application Support/com.fantasyflightgames.jime/SavedGames/<slot>/LogA.txt`
records each block displayed, with its parameters:

```
[3|1|PLACE_PERSON|1|8|0|A2_M1_T1_PLACE|0]
 │ │  │            │ └── type 8 = reference to another key
 │ │  │            └──── how many parameters
 │ │  └─────────────── the key, identical to the corpus one
 │ └────────────────── round
 └──────────────────── adventure
```

4,827 lines checked against the corpus: **100% match, zero unknown keys**.

It is written **once per round** — proven in the IL of `Assembly-CSharp.dll`:
`FlushLogStream` is called only by `GameController::CoroutineEndRound` and by the
save. So it cannot be a live trigger, but it is an exact oracle for validating the
matcher and it generates fixtures for free.

### 2. The screen is the concatenation of several keys

The game injects keys as parameters of generic templates:

```
corpus  PLACE_PERSON   = "{0}\n\nPlace a person token as indicated."
param   {0}            = A2_M1_T1_PLACE = "[the block's narrative prose]"
```

Matching a whole screen against a single block fails in exactly these cases,
which is why the matcher works **per paragraph** — and why the narrator speaks
only the paragraphs actually on screen, rather than the whole block behind them.

### 3. A quarter of the corpus had glyphs no TTS could read

3,209 blocks (24.7%) contain **Private Use Area** characters — the icons of the
game's font, written as literal characters rather than `<sprite=>` tags, so the
markup cleanup never saw them. The synthesiser received `"Each hero tests ; 2"`,
with no attribute named.

`glyphs.py` derives the map from the 24 `main:GLYPH_*` keys the game itself
publishes. Those keys are identical across all 13 languages, so **adding a
language is about 21 words**, not a fresh investigation.

A pitfall: `GLYPH_FOCUS` is the internal name for **Agility**. Nothing in the name
suggests it; the proof came from two independent keys whose only attribute glyph
is `FOCUS`.

And the **numbers** were read in Spanish ("uno" for "um") even with the language
set to Portuguese — 38.8% of the corpus. Fixed by spelling them out before
synthesis.

---

## Pitfalls already paid for

Do not rediscover them.

1. **Homebrew's ffmpeg has no `rubberband` filter.** Anything that names it fails
   on every block. The renderer detects it and falls back to `asetrate`+`atempo`,
   and the cache key records which was used.
2. **Voice, pace and effects go into the cache key.** That is deliberate — it
   stops two recipes mixing in one session — but it means changing your mind
   re-renders everything. With Piper that costs half an hour, not two days.
3. **On macOS 26 Tahoe**, `CGWindowListCreateImage` and `screencapture` return
   only the wallpaper. ScreenCaptureKit is the only API that still sees windows.
   It does **not** need a signed `.app`: screen-recording permission attaches to
   the responsible process, so a script launched from a terminal inherits the
   terminal's grant.
4. **macOS does not draw an inactive Space.** A fullscreen game is not capturable
   from a terminal in another Space — the window is not hidden, it is not being
   rendered. Capture the display instead.
5. **pyobjc bridges a callback argument using the types it knows at that moment.**
   Import Quartz *before* the capture call or the CGImage arrives as an opaque
   pointer: width, height and stride all read back correctly, and the pixels come
   out empty.
6. **Unity does not expose text to accessibility.** Measured: `UnityPlayer.dylib`
   has 1,353 Objective-C selectors and **zero** accessibility ones. Confirmed in
   Gloomhaven too, so it is a property of the engine. Do not try `AXStaticText`.
7. **Estimating RTF from it/s misleads.** 18 it/s on MPS looked excellent and the
   real RTF was 2–3. Measure wall clock against audio duration, and **paired**:
   two identical runs on this Mac have differed by 30%.
8. **`afplay` does not decode Opus.** It exits 0 after 1.9 s on a 33 s file, so it
   looks like it worked. The player uses `ffplay`.
9. **Never clone a famous voice actor.** In Brazil the voice is a personality right
   (CF art. 5 XXVIII-a; CC arts. 20–21) and unauthorised use is actionable even
   without copyright infringement. This is now moot — Piper synthesises from a
   published model with no reference recording at all — but it is why the project
   left cloning behind, and the framing was always "**an** old wizard", never
   "*that* narrator".

---

## What is missing

1. **An OCR harness with real character error rate.** The noise in the matcher
   harness is synthetic. Measuring Apple Vision against the fixtures would say
   whether real reading sits in the 1–3% band, where the matcher is above 94%.
   Everything claimed about noise tolerance rests on an assumption until then.
2. **Prose and mechanical instruction are still spoken as one.** 60.6% of
   narration blocks contain a paragraph break separating story from rule, so
   splitting them is mostly mechanical — but nobody has decided whether the
   narrator should read only the prose, only the rule, or both.
3. **Five icons are inferred, not confirmed.** `MOUNT` (20 occurrences), `WILD`
   (10), and `PREPARED`, `CORRUPTION`, `REVEAL_CARD_DRAW` (one each) were derived
   from context rather than checked against the printed manual.
4. **Eleven of the thirteen languages have no measured pace.** They fall back to
   the voice's own, which is faster than a narrator should read.
   `jime voices --calibrate` fixes one in a few minutes.
5. **Windows capture and the portable OCR have never been executed.**
   `capture/windows.py` (Windows.Graphics.Capture) and `ocr/rapidocr_engine.py`
   are written against their APIs and the constraints this project already knows,
   and both say so at the top of the file. Treat every line as a hypothesis.
6. **The hero name behind a numeric `Id` is unresolved.** Log parameter type 3
   carries a number this project cannot yet map to a hero, which matters only for
   fixture generation.

---

## License

The code is MIT (see `LICENSE`). The game content is not distributed by this repository
and is not covered by it.
