# How it works, and what it cost to find out

Everything here is measurement on the machine that made it (MacBook Pro M5 Pro,
macOS 26 Tahoe), not estimate. The [README](../README.md) is for playing; this is
for the next person who has to change something.

Most of the reasoning lives in the modules themselves — `matcher.py`,
`trigger.py`, `live.py` and `capture/*.py` each open with why they are the shape
they are. This file holds what does not belong to any one module.

---

## What was measured

### Synthesis

| | |
|---|---|
| RTF, M-series Mac | **0.029** |
| RTF, GPU-less Windows VM | **0.042–0.043** |
| Bones of Arnor + shared text (3,386 blocks, 12.4 h of audio), Mac | **22 min** |
| The same on that VM (3,330 blocks, 12.0 h) | **31 min** |
| Every campaign (~37 h of audio), Mac | ~1 h |
| Model on disk | 60 MB, CPU only |
| Reading pace | 153 wpm, inside the audiobook range |

The Mac figures come from `output/render-20260727-2325.log`: 744.1 minutes of
speech produced in 21.9 minutes of wall clock. The Windows ones are from a
GPU-less Azure VM rendering English: 710 s for 280.3 min of speech, then 1125 s
for 438.6 min. A machine with no graphics card and a weak CPU costs about 1.45×,
which is much less than the gap in the machines suggests — synthesis here is
CPU-only either way.

The 153 wpm is the measured output of the shipped recipe, and it is also the
target a new voice is swept against. That number has now been wrong twice, the
same way both times: it named a statistic nobody had measured.

First it was 2.68 w/s, 161 wpm, which nothing produced. Then 2.58, 155 wpm —
which the reference voice does not reach by any reading. At its ear-tuned 1.35 it
does 2.480 w/s over 25 blocks, 2.485 over 100, 2.530 over the whole 3,340-block
render, all medians, and **2.556 weighted by words** over that render. The only
figure equal to 2.58 is the median of blocks with 60 words or more.

Two things were wrong at once. The target was a long-block statistic, and
`_calibrate` compared it against the median of *all* blocks — where short ones
outnumber long ones three to one and run slower, because a clause pause and two
edges weigh more when there are fewer words to spread them over. 2.48 w/s under
20 words against 2.58 over 60.

So the sweep read the reference as slower than it is and sped every calibrated
voice up by about 5% to compensate. It is fixed by making both sides agree:
words-weighted measurement, and 2.556 as the target. The proof is that
Portuguese now calibrates back to the 1.35 somebody chose by ear — exactly, over
400 blocks. Over 100 it returns 1.32, which is why `--blocks` defaults to 400: a
fast wrong answer is the worst kind.

A second voice aimed at the old number would have come out 6 wpm faster than the
first, which is the mismatch the target exists to
prevent, so the target is what the ear-tuned voice actually does.

### Screen recognition

Measured against **653 real screens** rebuilt from the game's own logs — without
transcribing any of them by hand, 112 of them composite of two or more keys.
Campaign scope (`bonesofarnor` + `main`), which is what the narrator uses.

| OCR noise | hit rate | **wrong** | refusal |
|---:|---:|---:|---:|
| 0% | **99.2%** | 0.5% | 0.3% |
| 2% | 95.6% | 0.6% | 3.8% |
| 5% | 94.2% | 0.8% | 5.1% |
| 10% | 73.4% | 0.9% | 25.7% |

Refusing is the right behaviour: silence is recoverable, narrating the wrong
block is not, because the player acts on what they hear.

Scoping by the save (campaign, adventure) barely changes the result — the work is
done by the length and margin guards, and by matching per paragraph.

The screen count is per-machine: it depends on how much you have played, which
is why this table moves without the matcher changing. It said 631 until the log
grew to 653, and `render_all.sh` and `docs/PHASE3-STRATEGY.md` still quote 627
from a run before that. Re-measure rather than trust any of them:
`python test_matcher.py`.

### Why Piper

This project started on Chatterbox, a voice-cloning model, and measured **RTF
3.7** — fifty hours for one campaign plus the shared text. Swapping to Piper made
it twenty-two minutes, on the same blocks, with zero failures against fifteen. It
also removed the GPU requirement, dropped the model from 3 GB to 60 MB, and took
the languages from ten to thirteen.

What it cost is expressiveness. Piper has clear diction and flat prosody; it
reads, it does not act. Chatterbox sounded better. The measurement in §6c of
[PHASE2-MEASUREMENTS](PHASE2-MEASUREMENTS.md) is why it lost anyway.

That decision was between engines, and a second rendering mode — an expressive
one beside the plain one — is a different question nobody has answered.
`test_voice_ab.py` runs the same blocks through both and reports what each
costs, because "sounded better" was never weighed against "53 hours" by anybody
listening to the two. Four things would decide it, and only the first is a
matter of taste:

1. Is the difference worth the wait, listening to both on the same blocks
2. **Thirteen languages.** Piper covers all of them; Chatterbox covered ten. An
   expressive mode for six is defensible and has to be said on the screen where
   somebody picks it, not discovered afterwards
3. **Neither machine this runs on has a usable GPU.** RTF 3.7 was measured on
   this Mac's MPS, and the Windows VM has no card at all
4. **The 622 placeholder blocks cannot use it.** Their value only exists at the
   table, and a model at RTF 3.7 needs about 30 s for a ten-second block. They
   would come out in Piper whichever mode was chosen — a mixed session, which is
   the one thing `dsp_version` exists to prevent

There is a cheaper thing that attacks the same complaint. Flat prosody is not
only an engine property: `prosody.py` already reads a block clause by clause
with its own pauses, and going further there — scene-break pauses, pace per
sentence type, emphasis on short test lines — costs nothing in RTF, keeps all
thirteen languages, and does not break the Android path.

The same engine is what makes an Android port plausible: 60 MB of model replaces
264 MB of pre-rendered audio, and 6.3% of the narration cannot be rendered ahead at
all. [ANDROID](ANDROID.md) has the plan and what has been measured for it.

An aged-voice filter chain (pitch down, low lift, high rolloff, tremolo, echo)
was tried on top and turned off by default: it made the voice soft, slow and
hard to make out, cutting 2.5 dB where the consonants live. It is still there
behind `--effects`.

**On the old GPU engine**, two render processes in parallel ran **55% slower**
than one, because the decode was bound by memory bandwidth: each process read
its own weights per step, so two doubled the demand without doubling the supply.
That measurement is Chatterbox-era and has not been repeated on Piper.

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

Every logged key checked against the corpus matched, with zero unknowns, across
about 4,900 lines of this machine's play. The count grows as you play; the
property is what matters.

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

The game does not always break where the corpus does, though. When it renders one
block's prose as two paragraphs, each half is judged against the whole block's
length and refused as an excerpt; the narrator falls back to matching the screen
as one target, which only runs when nothing else matched.

### 3. A quarter of the corpus had glyphs no TTS could read

3,209 blocks (24.7%) contain **Private Use Area** characters — the icons of the
game's font, written as literal characters rather than `<sprite=>` tags, so the
markup cleanup never saw them. The synthesiser received `"Each hero tests ; 2"`,
with no attribute named.

`glyphs.py` derives the map from the 24 `main:GLYPH_*` keys the game itself
publishes. Those keys hold the *character*, identically in all 13 languages,
which is what makes the map work — and they carry no words at all. Read this
sentence as promising the words and you will go looking for them: only two of
the twenty-one exist as a standalone string anywhere in the corpus,
`main:UI_PHYSICAL` and `main:UI_FEAR`.

So **adding a language is about 21 words** and still not an investigation, but
the words come from the icon glossary in that edition's rulebook. They cannot be
translated from the English: four editions use four different words for the
Might icon — Vigor, Vigor, Körperkraft, Force — and the English predicts none of
them. `jime glyphs --lang <code> --template` prints the block to fill.

A pitfall: `GLYPH_FOCUS` is the internal name for **Agility**. Nothing in the name
suggests it; the proof came from two independent keys whose only attribute glyph
is `FOCUS`.

And the **numbers** were read in Spanish ("uno" for "um") even with the language
set to Portuguese — about 42% of the narration blocks. Fixed by spelling them out
before synthesis.

---

## Pitfalls already paid for

Do not rediscover them.

1. **Homebrew's ffmpeg has no `rubberband` filter.** Anything that names it fails
   on every block. The renderer detects it and falls back to `asetrate`+`atempo`,
   and the cache key records which was used.
2. **Voice, pace and effects go into the cache key.** That is deliberate — it
   stops two recipes mixing in one session — but it means changing your mind
   re-renders everything. With Piper that costs twenty minutes, not two days.
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
9. **espeak-ng keeps its data path in a fixed-size buffer.** Install under a path
   longer than about 160 characters and every render dies with an error naming a
   directory on the machine that *built* the wheel — it silently falls back to the
   compile-time default. Measured: 156 characters works, 176 does not.
   `selftest.py` checks it.
10. **The Windows console is not UTF-8.** It takes its encoding from the code page
   — cp1252 on most installs — and a character that does not fit raises rather
   than degrading. It is not only the symbols: `ě`, `ł`, and every Russian and
   Chinese character in the corpus break. `console.setup()` forces UTF-8 at every
   entry point.
11. **OCR boxes must be ordered into rows before reading.** Sorting by `y` alone
   lets a pixel or two of antialiasing decide the reading order inside a line, and
   the text comes back with its words shuffled. It reached a session log before
   anyone noticed, because scrambled text still scores badly rather than
   obviously wrong.
12. **Display capture reads whatever is in front, including your own terminal.**
   The narrator asks the window manager whether the game is foreground — and has
   to tolerate a gap, because a fullscreen game does not hold the foreground
   steadily and a single sample made it flap several times a second.
13. **The two OCR engines do not cover the same languages, and one map served
   both.** Measured against `Get-WindowsCapability -Online -Name "Language.OCR*"`
   on Windows 11 and Vision's `supportedRecognitionLanguages` on macOS 26, the
   gaps point opposite ways: **Apple has no Hungarian; Windows has no Ukrainian**
   — not under any tag — and Windows wants `zh-CN` where Apple wants `zh-Hans`.
   An Apple-shaped map with `en-US` appended was being handed to both, which on
   Windows is worse than wrong: `try_create_from_language` takes **one** language,
   so the trailing English was not a hint but a silent replacement. A Portuguese
   session on an English Windows got the English recogniser, reported success,
   and dropped every accent — audible, because `live.py` cuts values out of the
   original screen text. There are two maps now, and both the missing-recogniser
   case and the not-installed case say so out loud.
14. **Never clone a famous voice actor.** In Brazil the voice is a personality right
   (CF art. 5 XXVIII-a; CC arts. 20–21) and unauthorised use is actionable even
   without copyright infringement. This is now moot — Piper synthesises from a
   published model with no reference recording at all — but it is why the project
   left cloning behind, and the framing was always "**an** old wizard", never
   "*that* narrator".

---

## The individual tools

Every script runs from the project directory with the virtual environment's
Python. There is no `jime` command on the PATH.

```bash
cd ~/jime
alias jime="~/jime-venv/bin/python"     # then: jime jime.py status, jime demo.py ...
```

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
jime player.py --manifest output/audio_pt --all                     # listen to it
```

A block whose `.opus` already exists is skipped and the manifest is rewritten
every 50 blocks and on Ctrl+C, so stopping and restarting costs nothing.

`render_all.sh` renders a campaign plus the shared text unattended — macOS and
Linux only. On Windows, `jime render --lang <code>` with no `--campaign` does
the same thing, and the menu offers a campaign plus `main` when it notices one
is missing.

**Phase 3 — narrate a live game**

```bash
jime narrator.py --display           # fullscreen game — the usual case
jime narrator.py                     # windowed game, found by window title
jime narrator.py --list-windows      # what the capture backend can see
jime narrator.py --from-video FILE   # replay a recording, no permission needed
jime narrator.py --display --profile # time each stage, per screen
jime narrator.py --display --no-guard  # read the monitor even when the game is behind
```

`--wait` (90 s by default) is how long it waits for the game to come forward;
`--wait 0` starts immediately.

**Testing the recognition without a game**

```bash
jime demo.py ~/Downloads/screen.webp --no-audio   # one screen: OCR + matching
jime batch.py ~/Downloads/*.webp --keys keys.txt  # several, with hit rate
jime watch_log.py --all                           # the game's own event log
jime test_matcher.py --verbose                    # 631 real screens, with noise
jime test_ocr.py                                  # character error rate, rendered pages
jime test_ocr.py --from-captures crops/           # ... on screens `--save-crops` kept
jime calibrate_region.py shot1.png shot2.png      # where the dialogue box is on this layout
jime probe_capture.py --seconds 40                # does capture keep producing pixels
```

---

## Installing by hand

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

The Visual C++ Redistributable is **not optional**: without it the speech engine
fails to load, with a message naming neither itself nor what is missing.

Close and reopen PowerShell so the new commands are on the PATH, then:

```powershell
git clone https://github.com/lunaruser91/journeysInMiddleEarthTextToSpeech.git $HOME\jime
cd $HOME\jime
py -3.13 -m venv $HOME\jime-venv
& $HOME\jime-venv\Scripts\pip install -e '.[tts,ocr,capture]'
```

Both installers accept overrides: `JIME_DIR` and `JIME_VENV` on macOS, `-Path`
and `-Venv` on Windows.

`ocr` and `capture` resolve per platform — Apple Vision and ScreenCaptureKit on
macOS, Windows.Media.Ocr and `windows-capture` on Windows, the latter wrapping
Windows.Graphics.Capture, the only API that sees a Unity window since BitBlt and
PrintWindow return black frames.

RapidOCR is the fallback, and that is all it is — and it is not installed on
macOS at all: `pyproject.toml` pins it to `sys_platform != 'darwin'`, so a Mac
gets ocrmac and nothing else. Measured on Windows, same crops, machine equally
quiet in every row: it reads a dialogue box in 539 ms against
Windows.Media.Ocr's 25 ms, and a dense screen in 1480 ms against 40 ms. It is
what runs on Linux, or on a Windows with no OCR language feature installed. `--ocr windows|apple|rapid` names one and makes its failure fatal
rather than silent — worth doing when a session is slow, since a fallback that
works is indistinguishable from the engine you meant to use except by the clock.

---

## The files

| file | what it does |
|---|---|
| `jime.py` | the one command everything else hangs off |
| `menu.py` | what you get when you run it with no arguments |
| `i18n.py` | the menu and the session messages, per language |
| `console.py` | UTF-8 and ANSI on a Windows console; where saves live |
| `phase1_extract.py` | the game's AssetBundles → JSON/CSV corpus |
| `phase2_render.py` | corpus → audio, with a resumable hash-based cache |
| `voices.py` | which voice speaks each language, and its measured pace |
| `prosody.py` | one block read clause by clause; the pace band every clause is clamped into |
| `glyphs.py` | game icons → spoken words; numbers spelled out; per language |
| `capture/` | one screen-capture backend per platform |
| `ocr/` | one OCR engine per platform, plus paragraph rebuilding |
| `matcher.py` | screen text → the corpus block it came from |
| `trigger.py` | when a screen has settled and is worth reading |
| `live.py` | the blocks that can only be synthesised during play |
| `player.py` | queue, interrupt, repeat, and what to stay silent about |
| `narrator.py` | the loop that joins all of the above |
| `check_pace.py` | finds blocks whose pace strays from the median |
| `probe_capture.py` | whether capture keeps producing pixels while you play |
| `selftest.py` | checks the whole machine, end to end |
| `test_matcher.py` | harness: 631 real screens + synthetic OCR noise |
| `test_ocr.py` | harness: how much the recogniser actually gets wrong |
| `calibrate_region.py` | measures `--region` for a layout that is not the desktop one |
| `test_voice_ab.py` | the same blocks through two engines, with the cost of each |

---

## What is missing

1. **The OCR harness has one half of its measurement.** `test_ocr.py` renders
   every fixture's known text onto a page and reads it back: **0.09% CER, 18
   edits over 19,928 characters** on Apple Vision, 120 pages of the game's own
   prose with its proper nouns and its accents. That is twenty times below the
   2% row of the table above, and it answers one question completely — the
   corpus vocabulary is not what a recogniser struggles with.

   It is a floor and it says so. The page is a system serif on flat grey; the
   game draws its own font on parchment, with a texture behind the words. So the
   real number is at least 0.09% and the gap between them is entirely the
   game's pixels, which is where the remaining half lives: `jime play
   --save-crops DIR` keeps every screen that matched cleanly — one key, won with
   a margin, no placeholder, so the corpus block is exactly what the pixels say
   — and `test_ocr.py --from-captures DIR` scores those. That half is biased the
   other way, since a screen that matched is one the OCR read well enough to
   match. The two bracket the answer; neither is it.

   Two of the harness's first three findings were the harness. It scored the
   game's icons as OCR errors when they are Private Use Area characters no
   system font can draw — `Negado por ⬜.` read back as `Negado por O.` — and
   then scored the space the stripped icon left behind. 0.28%, 0.11%, 0.09%.
2. **Prose and mechanical instruction are still spoken as one.** Most narration
   blocks contain a paragraph break separating story from rule, so splitting them
   is mostly mechanical — but nobody has decided whether the narrator should read
   only the prose, only the rule, or both.
3. **One icon is still inferred.** `REVEAL_CARD_DRAW` appears in none of the
   four official rulebooks, and in no narration block either — only in its own
   `GLYPH_` definition — so nothing spoken depends on it. `MOUNT`, `WILD`,
   `PREPARED` and `CORRUPTION` were checked against the rulebooks and hold; the
   English lexicon no longer flags them. What remains open for Portuguese is the
   printed wording, since all four manuals are in English.
4. **Seven of the thirteen languages have no measured pace, and six of them
   cannot get one this way.** Six do: Portuguese, English, German, Spanish,
   Italian and French, swept over 400 blocks each against 2.556 w/s.

   | | length_scale | w/s |
   |---|---|---|
   | `pt_BR-faber-medium` | 1.35 | 2.556 |
   | `en_GB-alan-medium` | 1.07 | 2.56 |
   | `de_DE-thorsten-medium` | 1.23 | 2.58 |
   | `es_ES-davefx-medium` | 1.35 | 2.55 |
   | `it_IT-paola-medium` | 1.40 | 2.55 |
   | `fr_FR-tom-medium` | 1.15 | 2.46 |

   English moved from 1.02 to 1.07 in the process, and that is the same finding
   from the other side. Its old number came out of the broken sweep, not out of
   anybody's ear, so it carried the bias: 1.28 → 1.35 for Portuguese is +5.5%,
   1.01 → 1.07 for English is +5.9%. The same correction twice is what a
   systematic error looks like. Portuguese escaped only because 1.35 was settled
   by listening and never came from this procedure at all.

   English audio rendered at 1.02 therefore reads about 6% fast. It re-renders
   on its own — `length_scale` is in the version string, so
   `plain-p2-en_GB-alan-medium-l1.02` stops matching and those blocks stop being
   cached.

   French lands 3.8% under, and the sweep reports it rather than hiding it: its
   response to `length_scale` is the steepest measured — 3.01 to 1.94 w/s across
   0.9 to 1.5, against German's 2.98 to 2.20 — so a single linear interpolation
   between the ends overshoots. A second pass through the verify point would
   close it. Nothing does that yet.

   **The other seven do not fail, they show that the unit does.** Czech, Polish,
   Russian, Ukrainian, Hungarian and Korean top out between 1.83 and 2.36 w/s at
   `length_scale` 0.9, so 2.556 is not reachable at any speed the sweep allows.
   Those are not slow voices: they are languages whose words are longer, read at
   a normal speed. Every language that *does* converge is Romance or Germanic,
   with Portuguese-like word lengths, and that is not a coincidence.

   Chinese breaks the ruler outright — 0.16 w/s, 10 wpm — because it does not
   delimit words with spaces and `text.split()` returns roughly one "word" per
   paragraph. The number is not bad, it is meaningless.

   So `TARGET_WPS` per language exists for a real reason and is still empty: the
   seven need either their own target or a different unit, and choosing either
   needs somebody who speaks the language to listen. Which was already this
   entry's conclusion, now with thirteen measurements behind it rather than two.

   Getting the second one there meant fixing two things that only look like one.
   `prosody.synthesize` clamped every clause into an absolute `[1.20, 1.50]`,
   written when there was one voice calibrated to 1.35 — at that base an absolute
   band and a band relative to the base are the same thing, so nothing
   distinguished them. A second voice separates them: English reaches audiobook
   pace at about 1.05, which the absolute floor forbade, so it read at 137 wpm
   and could not be asked to do otherwise. The band is `[1.20/1.35, 1.50/1.35]`
   of the base now — identical output for the calibrated voice, verified across
   all eight multiplier combinations and 92 clauses of real blocks, so nothing
   already rendered changed.

   And `TARGET_WPS` was 2.68 w/s, 161 wpm, which nothing produced: 1.35 was
   chosen by ear and delivers 155. Aiming a second voice at 161 would have made
   it 6 wpm faster than the first — the mismatch the target exists to prevent. It
   is 2.58 now, which is what the ear-tuned voice actually does.

   Words per second looked like the wrong unit for this and was measured rather
   than assumed. On the same 14 blocks, Portuguese and English differ by 21% in
   words per second at equal `length_scale`, 26% in characters, and **55% in
   syllables** — the unit that was supposed to be the stable one is the worst of
   the three. No unit converges, which is why pace is per voice and `TARGET_WPS`
   per language starts empty.

   The remaining eleven are mechanical now: extract, fetch the voice, sweep.
   What no measurement settles is whether the number sounds right — 1.35 was
   picked by listening to four values on 125 words of prose, and that step needs
   somebody who speaks the language.

   Separately, four languages have no icon vocabulary: Czech, Hungarian,
   Ukrainian and Chinese. Nine are filled, each covering 99% or more of the
   icons in its own narration, and every one of them was read off a player's
   rulebook rather than translated — four editions use four different words for
   the Might icon and the English predicts none of them. `jime glyphs --lang
   <code> --template` prints the block to fill and paste back.
5. **Latency has never been measured on a machine with a graphics card.** The
   Windows testing was done on a GPU-less VM, where the game software-renders and
   takes about 88% of the processor; the narrator needs roughly 0.7 s of CPU per
   screen and was getting a few percent of a core. `--profile` exists to settle
   this on real hardware.

   This now blocks a specific decision rather than being a general wish.
   `STABLE_FRAMES` is a 1.1 s floor on every screen — about half of what a player
   waits, now that the rest of the pipeline runs in under two seconds. Two
   measurements of the pause it guards against disagree: a recording found
   mid-animation pauses up to 10 frames, and 15 screens on the GPU-less VM found
   nothing above 3. A machine that drops frames animates as continuous motion, so
   the VM is plausibly the optimistic one and the wrong one to generalise from.
   `--stable-frames 6` is measured-safe there and takes 0.5 s off every screen;
   the default stays at 11 until the same figure comes from a machine that draws
   the game properly. Run `--profile` and read `paused Nf`.
6. **The hero name behind a numeric `Id` is unresolved.** Log parameter type 3
   carries a number this project cannot yet map to a hero, which matters only for
   fixture generation.
