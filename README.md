# Automatic narrator for *Journeys in Middle-earth*

***English** · [Português](README.pt-BR.md)*

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
| 3 | screen → OCR → matching → speech | **works during a real game** on macOS, confirmed by ear; on Windows every part passes its self-test but no session has been played |

---

## Install

You need a Mac or a Windows PC, **the game installed on the same computer** —
the narrator reads its text files — and about 300 MB free per language. Not a
fast machine, not a graphics card, and no internet once it is set up.

**macOS**

```bash
curl -fsSL https://raw.githubusercontent.com/lunaruser91/journeysInMiddleEarthTextToSpeech/main/install.sh | bash
```

**Windows**, in PowerShell

```powershell
irm https://raw.githubusercontent.com/lunaruser91/journeysInMiddleEarthTextToSpeech/main/install.ps1 | iex
```

That installs whatever is missing, clones the project, builds the environment and
runs the self-test. Running it again is also how you **update**.

One thing it cannot do for you: **macOS needs screen recording permission.**
System Settings → Privacy & Security → Screen Recording → tick Terminal, then
quit Terminal (`Cmd`+`Q`) and reopen it — the permission is read when a program
starts. Windows needs no permission.

Then start it — it asks the rest:

```bash
cd ~/jime && ~/jime-venv/bin/python jime.py            # macOS
```

```powershell
cd $HOME\jime; & $HOME\jime-venv\Scripts\python.exe jime.py   # Windows
```

**The first time, in this order:** extract the corpus, render the audio, then
narrate. Extraction takes a minute, rendering about half an hour per campaign,
and after that only narrating matters.

If any of that went wrong, or you would rather see each step, read on.

---

## Installing by hand

For anyone who already has the tools, or who wants to see exactly what the
installer does.

**macOS**

```bash
brew install ffmpeg python@3.13 git
git clone https://github.com/lunaruser91/journeysInMiddleEarthTextToSpeech.git ~/jime
python3.13 -m venv ~/jime-venv
~/jime-venv/bin/pip install -e ~/jime'[tts,ocr,capture]'
```

**Windows**, in PowerShell — one package per `winget` command, it takes a single
`--id`:

```powershell
winget install --id Python.Python.3.13 -e --accept-source-agreements --accept-package-agreements
winget install --id Git.Git -e --accept-package-agreements
winget install --id Gyan.FFmpeg -e --accept-package-agreements
winget install --id Microsoft.VCRedist.2015+.x64 -e
```

Close and reopen PowerShell so the new commands are on the PATH, then:

```powershell
git clone https://github.com/lunaruser91/journeysInMiddleEarthTextToSpeech.git $HOME\jime
cd $HOME\jime
py -3.13 -m venv $HOME\jime-venv
& $HOME\jime-venv\Scripts\pip install -e '.[tts,ocr,capture]'
```

The Visual C++ Redistributable is not optional: without it the speech engine
fails to load, with a message naming neither itself nor what is missing.

`ocr` and `capture` resolve per platform — Apple Vision and ScreenCaptureKit on
macOS, RapidOCR and `windows-capture` on Windows, the latter wrapping
Windows.Graphics.Capture, the only API that sees a Unity window since BitBlt and
PrintWindow return black frames.

Synthesis is [Piper](https://github.com/OHF-Voice/piper1-gpl): a small ONNX model
on the CPU. A voice is about 60 MB, fetched the first time it is needed. No GPU,
nothing to sign.

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

### What each menu option does

| Option | What it does | When you need it |
|---|---|---|
| **Narrate a game** | Watches the screen and reads each block aloud | Every session |
| **Render audio** | Turns the extracted text into speech files | Once per campaign |
| **Extract the corpus** | Reads the game's own files | Once per language |
| **Status** | What is extracted, what is rendered, how much | To see where you left off |
| **Check this machine** | Whether everything is installed and permitted | When something does not work |
| **Voices** | Which voice speaks each language | To change or calibrate a voice |

The language is the first question and applies to everything after it. `b` goes
back a question, `q` quits, and Enter takes the highlighted default.

### If something goes wrong

Run `selftest.py`, or **Check this machine** from the menu — they name what is
missing rather than failing obscurely.

The three most common answers:

- **It finds no game window.** On macOS use the fullscreen option: a fullscreen
  game sits on its own Space, and macOS does not draw a Space that is not in
  front, so it is invisible from the Terminal until you switch to it. On Windows
  either works.
- **It recognises screens but says nothing.** That campaign has no audio yet — go
  back and render it. The menu offers this when it notices.
- **Windows: the speech engine will not load.** The Visual C++ Redistributable
  is missing: `winget install --id Microsoft.VCRedist.2015+.x64 -e`

---

### Updating

Re-run the installer. It pulls and reinstalls, and touches nothing else:

```bash
curl -fsSL https://raw.githubusercontent.com/lunaruser91/journeysInMiddleEarthTextToSpeech/main/install.sh | bash
```

```powershell
irm https://raw.githubusercontent.com/lunaruser91/journeysInMiddleEarthTextToSpeech/main/install.ps1 | iex
```

Or by hand — `git pull` alone is usually enough, since the scripts run from the
directory and pick up changes immediately. Only a new dependency needs the
second line:

```bash
cd ~/jime && git pull
~/jime-venv/bin/pip install -e ~/jime'[tts,ocr,capture]'
```

Your corpus, rendered audio and downloaded voices live in `corpus/`, `output/`
and `voices/`, none of which git touches. Updating never re-renders anything —
unless the recipe itself changes, since voice, pace and effects are part of the
cache key. Commits say so when that happens.

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
| `selftest.py` | checks the whole machine, end to end |
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
9. **espeak-ng keeps its data path in a fixed-size buffer.** Install Piper
   under a path longer than about 160 characters and every render dies with an
   error naming a directory on the machine that *built* the wheel — it silently
   falls back to the compile-time default. Measured: 156 characters works, 176
   does not. `selftest.py` checks it.
10. **The Windows console is not UTF-8.** It takes its encoding from the code page
   — cp1252 on most installs — and a character that does not fit raises rather
   than degrading. It is not only the symbols: `ě`, `ł`, and every Russian and
   Chinese character in the corpus break. `console.setup()` forces UTF-8 at every
   entry point.
11. **Never clone a famous voice actor.** In Brazil the voice is a personality right
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
5. **Windows passes its self-test but has never narrated a game.** A Windows 11
   VM with the game installed runs `selftest.py` at 41/41, installed by
   `install.ps1` in one command — extraction from the native build, synthesis,
   RapidOCR, matching, and the capture backend. What is untried there is a
   session: capturing the game while it runs, and hearing it read a screen
   aloud.
6. **The hero name behind a numeric `Id` is unresolved.** Log parameter type 3
   carries a number this project cannot yet map to a hero, which matters only for
   fixture generation.

---

## License

The code is MIT (see `LICENSE`). The game content is not distributed by this repository
and is not covered by it.
