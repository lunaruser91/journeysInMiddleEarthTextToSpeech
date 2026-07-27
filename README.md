# Automatic narrator for *Journeys in Middle-earth*

Read-aloud narration, **100% offline** and in **pt-BR**, of the texts that the official
*The Lord of the Rings: Journeys in Middle-earth* (Fantasy Flight / Asmodee) app shows
during play. Old-wizard voice.

The app has no Portuguese narration for the game itself — only the Prologue and the
Epilogues of each campaign have recorded audio. Everything else the players read aloud,
and that is what this project replaces.

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
| 1 | app assets → pt-BR corpus | **done** — 13,018 keys, 9,740 narration blocks |
| 2 | corpus → pre-rendered audio | **works and is measured** — RTF 3.17; one campaign in ~19 h |
| 3 | screen → OCR → matching → plays the audio | **matcher done and measured (97.8%)**; capture, trigger and player still missing |

---

## Installation

Python 3.14 **has no PyTorch wheels** — use 3.12 or 3.13.

```bash
python3.13 -m venv ~/jime-venv
~/jime-venv/bin/pip install -e .
~/jime-venv/bin/pip install -e '.[tts]'
~/jime-venv/bin/pip install -e '.[ocr]'
brew install ffmpeg
```

A shortcut saves typing:

```bash
alias jime="~/jime-venv/bin/python"
```

---

## Usage

### Phase 1 — extract the corpus from your installation

```bash
jime phase1_extract.py "<.../JiME.app/Contents/Resources/Data/StreamingAssets/bundles>" -o corpus/ --lang pt
```

The app is Unity 2022.3 with Mono and **nothing is obfuscated**: each localization bundle
contains a single `TextAsset` that is a clean CSV. There are 13 languages available.

### Phase 2 — render the audio

```bash
jime phase2_render.py corpus/corpus_pt.json --campaign bonesofarnor --check-pace
```

Estimate before leaving it running overnight:

```bash
jime phase2_render.py corpus/corpus_pt.json --campaign bonesofarnor --dry-run
```

Render individual blocks — this is the on-demand rendering that Phase 3 uses:

```bash
jime phase2_render.py corpus/corpus_pt.json --key "main:G22_SWORD_TRUE"
```

Audit the result, looking for degenerate blocks:

```bash
jime check_pace.py output/audio/manifest.json --mad 2.0
```

### Phase 3 — test the recognition

One screen:

```bash
jime demo.py ~/Downloads/screen.webp --no-audio     # only OCR + matching
jime demo.py ~/Downloads/screen.webp                 # plays the audio, if it exists
jime demo.py ~/Downloads/screen.webp --render        # synthesizes on the spot if missing
```

With no argument at all it picks up the most recent screenshot from the Desktop.

Several screens at once, with hit rate:

```bash
jime batch.py ~/Downloads/*.webp --keys /tmp/keys.txt
```

View the game's event log, useful for generating fixtures:

```bash
jime watch_log.py --all
```

---

## Where things live

The project is self-contained. **Nothing is written outside the repository.**

```
corpus/          corpus extracted from the game       (generated, ignored)
ref/             reference voice for cloning          (ignored)
output/           EVERYTHING that is generated         (ignored)
  audio/           render per campaign + manifest.json
  sob-demanda/     blocks synthesized on the spot
  ocr-fixtures/    real screens with the right key
  legacy-audio/    old renders, preserved

docs/            the investigation notes
legacy/          original scripts, kept for comparison
```

| file | what it does |
|---|---|
| `phase1_extract.py` | the game's AssetBundles → JSON/CSV corpus |
| `phase2_render.py` | corpus → audio, with a resumable hash-based cache |
| `glyphs.py` | game icons → spoken words; numbers spelled out; multi-language |
| `check_pace.py` | detects blocks whose pace strays from the median, for regeneration |
| `matcher.py` | matches the text read from the screen against the corpus block |
| `test_matcher.py` | harness: 626 real screens + synthetic OCR noise |
| `demo.py` | full cycle on one screen: image → OCR → matcher → audio |
| `batch.py` | the same across several screens, with hit rate |
| `watch_log.py` | reads the game's event log |

---

## What was measured

Everything below is measurement on this hardware (MacBook Pro M5 Pro, macOS 26 Tahoe), not
estimate. The detail is in [docs/PHASE2-MEASUREMENTS.md](docs/PHASE2-MEASUREMENTS.md) and
[docs/PHASE3-STRATEGY.md](docs/PHASE3-STRATEGY.md).

### Synthesis performance

| | |
|---|---|
| RTF (wall clock ÷ audio duration) | **3.17** |
| Bones of Arnor (6.0 h of audio) | **~19 h of machine time** |
| Full corpus (44.8 h) | ~142 h — not viable in one go, viable per campaign |
| Bottleneck | T3 autoregressive decode: **80–85% of the wall clock** |

**Five plausible hypotheses were tested and four fell.** Worth reading before trying to
optimize:

- **grouping sentences into 220-char chunks** → 11% **slower**. Decode grows
  superlinearly with length; the fixed per-call cost one wanted to amortize is too small
  to compensate.
- **turning off the `AlignmentStreamAnalyzer`** to recover the fused attention → the model
  started generating **almost twice** the audio for the same text. It is the brake that
  holds back degenerate generation, not decorative overhead.
- **fixing the forward-hook leak** → the leak is real (69 live hooks after 23 sentences)
  but **costs no time**. Worth fixing for memory, not for speed.
- **token ceiling per sentence** → never reached (0 out of 56 sentences). It is insurance,
  not a fix.
- **`prepare_conditionals` only once** → the only one that survived, and it is worth ~3%.

A methodological pitfall: the variation between two identical runs on this Mac reaches
**30%**. Differences smaller than that can only be asserted with a **paired** test.

### Screen recognition

Measured against **626 real screens** reconstructed from the game's logs — without
transcribing any of them by hand.

| OCR noise | hit rate | **wrong** | refusal |
|---:|---:|---:|---:|
| 0% | **97.8%** | 0.6% | 1.6% |
| 2% | 95.5% | 1.4% | 3.0% |
| 5% | 94.4% | 1.9% | 3.7% |
| 10% | 67% | 5% | 27% |

Refusing is the right behavior: silence is recoverable with live TTS; narrating the wrong
block is not, because the player acts on what they hear.

Scoping by the save (campaign, adventure) barely changes the result — the work is done by
the length and margin guards, and by paragraph matching.

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

It is written **every round** of the game — proven in the IL of `Assembly-CSharp.dll`:
`FlushLogStream` is only called by `GameController::CoroutineEndRound` and by the save. So
it **does not serve as a live trigger**, but it is an exact oracle for validating the
matcher and it generates fixtures for free.

### 2. The screen is the concatenation of several keys

The game injects keys as a parameter of generic templates:

```
corpus  PLACE_PERSON   = "{0}\n\nColoque uma ficha de pessoa conforme indicado."
                               (English: "{0}\n\nPlace a person token as indicated.")
param   {0}            = A2_M1_T1_PLACE = "[narrative prose of the block]"
```

Matching the whole screen against a single block fails in exactly these cases. That is why
the matcher works **per paragraph**.

### 3. A quarter of the corpus had garbage the TTS could not read

2,363 blocks (25.9%) contain **Private Use Area** characters — the icons of the game's
font, written as literal characters and not as `<sprite=>` tags, so the markup cleanup did
not see them. The TTS received `"Cada herói testa ; 2"`, without saying which attribute
to test.

`glyphs.py` solves this by deriving the map from the 24 `main:GLYPH_*` keys the game
itself publishes. Since these keys are identical across the 13 languages, **adding a
language means filling in ~21 words**, not re-investigating the game.

A pitfall: `GLYPH_FOCUS` is the internal name for **Agility**. Nothing in the name suggests
it; the proof came from two independent keys whose only attribute glyph is `FOCUS`.

And the **numbers** were read in Spanish ("uno" instead of "um") even with
`language_id="pt"` — it affected 38.8% of the corpus. Fixed by spelling them out before
synthesizing.

---

## Pitfalls already paid for

Do not rediscover them.

1. **`setuptools>=81` breaks `perth`** (Chatterbox's watermark) and the model **does not
   even load**. Pin `setuptools<81`.
2. **Python 3.14 has no PyTorch wheels.** Use 3.12 or 3.13.
3. **Homebrew's ffmpeg does not ship the `rubberband` filter.** The renderer detects it and
   falls back to an equivalent with `asetrate`+`atempo`; `DSP_VERSION` changes so caches do not mix.
4. **The speed goes into the `DSP_VERSION`.** Changing your mind later throws away the
   whole render — decide before spending the hours.
5. **On macOS 26 Tahoe**, `CGWindowListCreateImage` and `screencapture` return only the
   wallpaper. Capture requires **ScreenCaptureKit** in a `.app` signed with a real Team ID.
6. **Unity does not expose text to accessibility.** Measured: `UnityPlayer.dylib` has 1,353
   Objective-C selectors and **zero** accessibility ones. Confirmed in Gloomhaven too, i.e.
   it is a property of the engine. Do not waste time with `AXStaticText`.
7. **Estimating RTF from it/s misleads.** 18 it/s on MPS looked great and the real RTF came
   out at 2-3. Measure wall clock against audio duration, and **paired**.
8. **Never clone a famous voice actor.** In Brazil the voice is a personality right (CF art.
   5 XXVIII-a; CC arts. 20–21) and unauthorized use is actionable even without copyright
   infringement. The framing is "**an** old wizard", not "*that* narrator". The reference
   used is from LibriVox, public domain.

---

## What is missing

1. **`trigger.py`** — absdiff → dhash → stability → dedupe with TTL. Developable with
   saved images, without real capture.
2. **OCR harness with real CER** — today the noise is synthetic. Measuring Apple Vision
   against the fixtures tells whether we are in the 1-3% range, where the matcher is 97% correct.
3. **`player.py`** — audio queue, repeat/pause/skip, hotkeys.
4. **Capture on macOS** — ScreenCaptureKit in a signed `.app`. It is the expensive item (half
   a day plus the developer account) and the last to do, because everything above runs without it.
5. **Piper for the blocks with `{0}`** — 622 blocks are only completed at game time.
   Note: Piper **is not installed** and `legacy/render_piper.py` breaks on this ffmpeg
   (it uses `rubberband` unconditionally).
6. **Review the `narration` heuristic** — the `_OPTION` hint discards 74 blocks of real
   narration (867 words); the other nine UI hints together discard 29 words.
7. **Decide on prose vs. mechanical instruction** — 38.2% of the blocks mix narrative and
   rule (prose, paragraph break, and then the rule). Separable
   by paragraph break; another 8% have the instruction embedded in the middle.

---

## License

The code is MIT (see `LICENSE`). The game content is not distributed by this repository
and is not covered by it.
