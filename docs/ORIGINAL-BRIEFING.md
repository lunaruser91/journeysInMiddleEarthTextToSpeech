# Automatic narrator for *Journeys in Middle-earth* — briefing for Claude Code

> **The brief this project started from, kept unedited.** It describes what was
> known before anything was built, including guesses that measurement later
> overturned. Nothing here should be followed as instruction; it is here so the
> reasoning behind the shape of the project can be traced. The current state is
> the [README](../README.md) and [ENGINEERING](ENGINEERING.md).

> Paste this whole file as the first prompt in the new repository.
> It contains everything already discovered, what already works, what is missing,
> and above all the pitfalls that have already cost time — do not rediscover them.

---

## 1. Objective

Automatically narrate aloud, **100% offline**, the texts that the official app of the
board game *The Lord of the Rings: Journeys in Middle-earth* (Fantasy Flight / Asmodee)
shows during play. Voice of an **old man, fantasy wizard**, in **pt-BR**.

The app has no Portuguese narration at all — only English has audio, and only for the
introduction and the epilogue. Players read everything aloud. The project replaces that.

Strictly personal use, no distribution (see §8).

## 2. The user's actual environment

| | |
|---|---|
| Machine | MacBook Pro 14", **Apple M5 Pro**, 24 GB |
| OS | **macOS Tahoe 26.5.2** |
| Game | Steam for macOS, `~/Library/Application Support/Steam/steamapps/common/Journeys in Middle-earth/JiME.app` |
| Project Python | **3.13 via Homebrew** in `~/jime-venv` (the system's 3.14 does **not** have PyTorch wheels) |
| Current code | `~/jime` |
| Audio output | `~/Documents/journeys/entrega/` |
| Windows | must remain a possible target: pure-Python core, isolated capture layer |

## 3. Three-phase architecture

```
PHASE 1 (DONE)        app assets → pt-BR corpus in JSON/CSV
PHASE 2 (IN PROGRESS) corpus → pre-rendered audio, one folder per campaign
PHASE 3 (TO DO)       screen capture → OCR → matching against the corpus → plays the audio
```

---

## 4. PHASE 1 — COMPLETED

### What was discovered (do not repeat the investigation)

The app is **Unity 2022.3.62f2 with Mono**. The content lives in `JiME.app/Contents/Resources/Data`.
**Nothing is obfuscated.** The path is trivial and already solved:

1. `Data/StreamingAssets/bundles/manifest.dat` is **pure JSON**, mapping 137 AssetBundles.
2. 92 of them are localization bundles, named `localization/<campaign>/<language>` — 13 languages,
   including `pt`. The `filename` field gives the real name (hash) of the file in the same folder.
3. Each bundle contains **a single `TextAsset`** which is a **clean CSV**: header
   `KEY,Portuguese`, one row per text block.
4. Extraction with **UnityPy** (`pip install UnityPy`). No AssetRipper, no ILSpy,
   no deobfuscation key.

> This invalidates the initial assumption (based on FFG's sibling apps, such as Mansions of
> Madness, whose TextAssets are obfuscated with an integer constant). JiME is not like that.

### Campaigns

`bonesofarnor`, `embercrown`, `shadowedpaths`, `spreadingwar`, `hauntingofdale`,
`poisonpromise` and `main` (common and interface texts).

### pt-BR corpus numbers

| | |
|---|---|
| Total keys | 13,021 |
| Narration blocks | 9,740 (9,549 unique texts) |
| Narration words | 366,965 |
| Blocks with `{0}` placeholder | 622 (6.4% of the narration) |
| To render (narration without placeholder) | **9,118 blocks / 341,646 words** |

Validation done: the exact sentence from a game screenshot was located in
`bonesofarnor:A10_THREAT_3`, intact, with correct accents and proper names.

### Ready script: `jime_corpus.py`

```bash
python3 jime_corpus.py <Data/StreamingAssets/bundles> -o corpus/ --lang pt
```

Produces `corpus/corpus_pt.json` (key `campaign:KEY`) and one CSV per campaign. Each entry:

```json
{
  "key": "A10_THREAT_3", "campaign": "bonesofarnor",
  "text": "[block text]",
  "placeholders": [], "narration": true, "words": 87, "chars": 512
}
```

`narration` is a heuristic: it discards keys with `_BUTTON`, `_TOOLTIP`, `_LABEL` etc.,
requires ≥8 words and final punctuation. The script also strips the game's markup
(`[i]`, `[b]`, `<sprite=...>`).

**To do in Phase 1 (minor):** review the `narration` heuristic against the CSVs
(nobody has audited the false positives/negatives so far), and decide what to do with
the 622 blocks with `{0}` — today they are only flagged.

---

## 5. PHASE 2 — IN PROGRESS, WITH AN OPEN PERFORMANCE PROBLEM

### Chosen voice (decided by blind comparison of samples)

- **Model:** `chatterbox-tts` (Chatterbox Multilingual, `language_id="pt"`), **MIT license**,
  running on **MPS**.
- **Cloning reference:** 12 clean seconds from the narrator of *Páginas Recolhidas*
  (Machado de Assis) on **LibriVox — public domain**. File `ref/REF_paginasrecolhidas.wav`,
  24 kHz mono, already filtered (`highpass=70`, `afftdn`, `loudnorm I=-19`).
- **Why this one:** of 13 Portuguese readers measured in the collection, 9 were female voices.
  Two low-pitched ones were left; this one has a median F0 of **123.2 Hz**.
- **"mago-v1" DSP chain** applied after synthesis, via ffmpeg.

> ⚠️ Never clone a famous voice actor. In Brazil the voice is a personality right
> (CF art. 5º XXVIII-a; CC arts. 20–21) and unauthorized use is actionable even without
> copyright infringement. The framing is "**an** old wizard", not "*that* narrator".

### Ready scripts

- `render_corpus.py` — renders the corpus with Chatterbox + DSP. Hash-based cache
  (`model|voice|DSP_VERSION|params|text`), resumable, incremental manifest,
  `--dry-run`, `--campaign`, `--limit`, `--device`.
- `render_piper.py` — same thing with **Piper** (`pt_BR-cadu-medium`). ~90× faster,
  no cloning. It is the **live fallback voice for Phase 3** and the provisional track.
- `setup_mac.sh` — installs everything from scratch (brew, ffmpeg, Python 3.12/3.13, venv, deps).

### What has already been rendered

- **Bones of Arnor complete in Piper**: 1,193 blocks → 1,174 files (19 repeated texts
  share audio through the hash), **5.8 h of narration, 125 MB**, zero truncated.
- **20 blocks in Chatterbox on the user's Mac** + 10 validation blocks on CPU.

### Measured consistency (the clone does not drift)

| Batch | Mean F0 | Deviation | Range |
|---|---|---|---|
| LibriVox human reference | 123.2 Hz | — | — |
| 10 validation blocks (CPU) | 122.3 Hz | 8.0 Hz | 109–139 |
| 20 blocks on the M5 Pro (MPS) | 120.7 Hz | 6.2 Hz | 108–133 |

Average pace: **2.03 words per second (~122 wpm)**, deviation 0.36 — adequate for narration.

### 🔴 OPEN PROBLEM: the render is ~4× slower than estimated

Real measurement on the M5 Pro: **20 blocks = 748 s of wall clock for 356 s of audio → RTF ≈ 2.1**.
The project estimate assumed RTF 0.45. Extrapolating:

| | estimated | **actual** |
|---|---|---|
| Bones of Arnor (5.8 h of audio) | 2.4 h | **~12 h** |
| Full corpus (40.7 h of audio) | 18 h | **~85 h** |

85 hours of machine time is not viable. **This is the repository's first task.**

**Two optimization hypotheses, still NOT validated** (the benchmark was interrupted):

1. **Conditionals recomputed on every call.** `render_corpus.py` calls
   `model.generate(..., audio_prompt_path=REF)` **once per sentence**. From the signatures
   `generate(self, text, language_id, audio_prompt_path=None, ...)` and
   `prepare_conditionals(self, wav_fpath, exaggeration=0.5)`, passing `audio_prompt_path`
   redoes the voice conditioning (voice encoder + tokenizer over 12 s of audio) on
   **all** of the ~5,000 calls. Fix: call `prepare_conditionals(REF, exaggeration=...)`
   **once** and then generate **without** `audio_prompt_path`.
2. **Calls that are too short.** Today it is one call per sentence. Grouping sentences into
   blocks of ~220 characters reduces the number of calls and the fixed overhead, and tends to
   improve prosody. Keep a ceiling (~300 chars) because autoregressive models drift on
   long texts.

Benchmark to run (A = as it is today, B = with cached conditionals,
C = cache + 220-char chunks), measuring the same block in all three modes.

**Other levers, if A+B are not enough:**

- Check whether the bottleneck is T3 (sampling, ~18 it/s on MPS) or s3gen/vocoder — profile before optimizing.
- `torch.float16` on MPS.
- Process several sentences in a batch in one call, if the model supports it.
- Accept Piper (`RTF 0.03`) for the lower-value campaigns and reserve the clone for the ones the user is going to play.
- On-demand rendering: generate the first time the block appears in game and cache it.

### Anomaly to investigate

The block `bonesofarnor:A1_THREAT_1` came out at **1.00 word per second** (43 words in 43 s),
against the average of 2.03. The generation log shows
`🚨 Detected 2x repetition of token 6405 → forcing EOS`. Suspicion: repetition/stretching
by the model. An automatic detector is worth it — flag blocks whose `words/duration` deviates
more than 2 deviations from the median and regenerate them with a different seed.

---

## 6. PHASE 3 — DESIGNED, NOT STARTED

### The constraint that defines the architecture

The app **exposes no text at all to macOS**: Unity rasterizes the whole UI onto a single
GPU surface, so there is no `AXStaticText` and no UI Automation. (Unity 6.3 gained native
screen-reader support, but it is a manual opt-in per screen and this app is from 2019 in maintenance.)
Confirm this in 10 minutes with the Accessibility Inspector and close that door.

Therefore: **the screen is the trigger; the corpus is the source of truth for the text.**

### Capture — the thorniest point on Tahoe

- On **macOS 26 Tahoe**, `CGWindowListCreateImage`, `CGDisplayCreateImage` and the
  `screencapture` CLI return **only the wallpaper** — app windows are invisible. That
  **rules out `mss`, `pyautogui` and `PIL.ImageGrab`**. Do not waste time with them.
- Valid path: **ScreenCaptureKit**, `SCContentFilter(desktopIndependentWindow:)` to
  capture only the game window and `SCScreenshotManager.captureImage` for on-demand frames.
  10 fps is enough (a human needs ≥300 ms to register new text).
- **TCC will cost time**: the permission binds to the responsible process (running from the
  Terminal grants it to the Terminal), and ad-hoc signed binaries have been blocked since Sequoia.
  The reliable path is a **packaged `.app` signed with a real Team ID** (a free developer
  account is enough), with `NSScreenCaptureUsageDescription` and hardened runtime.
- Windows (portability): `zbl` or `windows-capture` (capture by window name on top of
  Windows.Graphics.Capture). **Avoid BitBlt/PrintWindow** — they return black on Unity windows.

### OCR

- **macOS: Apple Vision** (`VNRecognizeTextRequest`), offline, native `pt-BR`, 130–210 ms,
  accepts `customWords` (feed it the Tolkien proper names). In Python via
  [`ocrmac`](https://github.com/straussmaximilian/ocrmac); a Swift binary is cleaner.
- Portable: **RapidOCR** (PP-OCRv5 latin, ~19 MB, Apache-2.0). Windows: `Windows.Media.Ocr`.
- **Do not use a local VLM** (Qwen3-VL etc.): it hallucinates plausible text, which in a narrator
  is worse than an OCR error and undetectable; and it is ~10× slower.
- **Preprocessing matters 10–20×; the engine, ~2×.** Recipe: fixed crop → grayscale (test
  isolated R/G/B channels) → background flattening (`bg = medianBlur(gray,31)`; `subtract`;
  normalize) → Otsu → invert if light-on-dark → Lanczos upscale up to **~35 px of
  character height and stop** (4× makes it worse). **Never adaptive threshold before flattening
  the background** — it hallucinates text out of the parchment grain.

### Trigger and deduplication

```
capture 5–10 Hz
 → absdiff (>0.5% of pixels with delta >25)      [every tick, cheap]
 → dhash(hash_size=16), Hamming ≤ 2              [only when absdiff fires]
 → stability: 3 identical frames                 [waits for the text animation]
 → if the new text starts with the old one → replace, do not narrate again
 → OCR
 → significance: ≥8 chars, ≥2 words, ≥35% alphanumeric   [discards HUD/timer]
 → dedupe: normalized hash in deque(maxlen=30) with TTL 90–120 s
 → matching against the corpus
```

`hash_size=16`, not the default 8 (64 bits are coarse for a 1000×200 box).
**Do not use phash** — the DCT erases precisely the glyph edges. **TTL is essential**:
without it, "Sim"/"Não" and recurring sentences go silent forever.

### Matching against the corpus

**`rapidfuzz`** — 1 query against a few thousand options costs 1–3 ms. No embeddings
(they are invariant to surface form, the opposite of what is needed against OCR errors).

- Scorer: `fuzz.partial_ratio`. **Avoid `token_set_ratio`** — it returns 100 whenever one
  token set is a subset of the other.
- Normalize both sides the same way: NFKD, **strip accents**, `casefold()`, punctuation → space.
  The `norm` field already comes ready in the Phase 2 `manifest.json`, with exactly this normalization.
- Thresholds: **≥92** plays; **82–92** only with the guards; **<82** falls back to live TTS.
- **The two guards are worth more than the threshold:** (a) length ratio ≥0.75 — without it a
  10-char fragment matches 100 against a 200-char paragraph and narrates the wrong block;
  (b) margin ≥5 points over the runner-up.
- **Scoping by the save**: the saves are **plain unencrypted JSON** in
  `Contents/Resources/Data/SavedGames`, with fields such as `CurrentAdventureId` and
  `CampaignDifficulty`. A file watcher reduces the candidate corpus from thousands of blocks
  to dozens and makes the matching practically infallible. It does not work as a trigger
  (mid-mission blocks probably do not write a save), but it works as context.
- Note: **since RapidFuzz 3.0 nothing is preprocessed by default** (unlike fuzzywuzzy).

### Live fallback

The 622 blocks with `{0}` are only completed at game time. For them and for OCR with no match:
**Piper `pt_BR-cadu-medium`** (RTF 0.03, ~40 ms, 300 MB of RAM). Same DSP chain.

### Requested interface

**Small status window**: shows the captured region, the last sentences read and
repeat / pause / skip buttons. Also plan for global hotkeys and an "only narrate when I
press" mode — players sometimes want to read at their own pace.

### References to draw on

| Project | What to take |
|---|---|
| [LOTR-Lector](https://github.com/rpiotrow96/LOTR-Lector) | Same game. Heuristic for detecting the text border. Ignore BitBlt and gTTS (it is online) |
| [UGTLive](https://github.com/SethRobinson/UGTLive) | Best architectural match: detect change → act "when things settle" |
| [Game2Text](https://github.com/mathewthe2/Game2Text) | Direct precedent for matching OCR × known script |
| [oneocr SmartDedup](https://huggingface.co/MattyMroz/oneocr/blob/main/_archive/dedup.py) | The stabilization/dedupe algorithm with real constants |
| [Translumo](https://github.com/ramjke/Translumo) | Ensemble of OCR engines with a scorer — accuracy lever for v2 |

---

## 7. Pitfalls already paid for (do not repeat)

1. **Homebrew's `ffmpeg` does not ship the `rubberband` filter.** `render_corpus.py` already
   detects this and falls back to an equivalent with `asetrate`+`aresample`+`atempo` — which shifts
   pitch and formants together, exactly what `formant=shifted` did. Identical duration (38.01 s in both).
   `DSP_VERSION` changes to `mago-v1f` in the fallback, so caches do not get mixed.
2. **`setuptools>=81` breaks `perth`** (Chatterbox's watermarking) with
   `No module named 'pkg_resources'`, and then the model **does not even load**. Pin `setuptools<81`.
3. **Python 3.14 has no PyTorch wheels.** Use 3.12 or 3.13.
4. **`antlr4-python3-runtime` does not build** with Debian's setuptools (`AttributeError:
   install_layout`) — install inside a clean venv, not in the system Python.
5. **Opus always decodes at 48 kHz.** When testing DSP chains with `asetrate`, make sure that
   the input is at the rate you think it is, or the duration comes out wrong by 2×.
6. **Kyutai Pocket TTS**: cloning requires the *gated* `kyutai/pocket-tts` repository on
   Hugging Face, with the terms accepted. The built-in voices work without that.
7. **XTTS-v2 is out**: weights under the Coqui Public Model License (non-commercial) and Coqui
   shut down in January 2024, so nobody can license it anymore. Besides, `aten::_fft_r2c`
   does not exist on MPS — it runs on CPU on the Mac.
8. **Native voices are not usable**: on macOS pt-BR only has Luciana and Joana, both female;
   the male Felipe is a Siri voice and is not exposed to `say`/`AVSpeechSynthesizer`.
9. **Estimating RTF from it/s is misleading.** 18 it/s on MPS looked great and the actual RTF came out at 2.1.
   Always measure wall clock against audio duration.

---

## 8. License, and what must NOT go into git

The Asmodee Digital Terms (§5.3 and §5.4) prohibit decompiling and **"extracting… even for
individual use"**. The text is a protected work (FFG + Middle-earth Enterprises) and the generated
audio is a derivative work. FFG/Asmodee have already issued DMCA notices against fan mods.

Local, non-distributed use: practical risk nil. **Publishing the corpus, the JSON or the audio:
do not do it.** Direct consequence for the repository:

```gitignore
# game content and derivatives — NEVER commit
corpus/
audio/
audio_piper/
entrega/
*.opus
*.csv
Data/
ref/*.wav      # unless you recorded the reference yourself
```

The repository publishes **an extractor and a renderer**, never the content. Each user runs
the extraction against their own installation.

---

## 9. Suggested repository structure

```
jime-narrador/
├── README.md
├── pyproject.toml            # deps: UnityPy, chatterbox-tts, piper-tts, rapidfuzz, ocrmac
├── .gitignore                # see §8
├── src/jime/
│   ├── fase1_extract.py      # ← jime_corpus.py (ready)
│   ├── fase2_render.py       # ← render_corpus.py (ready, needs optimizing)
│   ├── fase2_render_piper.py # ← render_piper.py (ready)
│   ├── dsp.py                # wizard chain + rubberband detection
│   ├── capture/
│   │   ├── base.py           # interface: grab() -> ndarray
│   │   ├── macos_sck.py      # ScreenCaptureKit (via Swift helper or pyobjc)
│   │   └── windows_wgc.py
│   ├── ocr/
│   │   ├── base.py
│   │   ├── apple_vision.py   # ocrmac
│   │   └── rapidocr_engine.py
│   ├── trigger.py            # absdiff → dhash → stability → significance → dedupe
│   ├── matcher.py            # rapidfuzz + guards + scoping by the save
│   ├── player.py             # audio queue, repeat/pause/skip
│   └── ui/status_window.py
├── helper-swift/             # signed capture+OCR binary (macOS)
├── scripts/setup_mac.sh      # ready
└── tests/
    ├── test_matcher.py       # synthetic OCR with errors → check the guards
    └── fixtures/screenshots/ # 30-50 real screenshots + transcription (CER harness)
```

## 10. Suggested order of work

1. **Optimize Phase 2** (§5): run the A/B/C benchmark, apply `prepare_conditionals` +
   chunks, re-measure the RTF. **Goal: bring it down from ~85 h to something that fits in 1-2 nights.**
   Without that, nothing else matters.
2. Pace anomaly detector + automatic regeneration with a different seed.
3. Render the 7 campaigns, one at a time, measuring.
4. **OCR harness**: 30–50 real screenshots transcribed + CER script. Choose the engine
   with data, not with faith — there is no public OCR benchmark on game UI text.
5. Capture layer on macOS (the signed `.app` is half a day of work, plan for it).
6. `trigger.py` + `matcher.py` with synthetic tests before plugging into the real screen.
7. Integration, status window, hotkeys.
8. Only then port the capture to Windows.

## 11. Numeric facts, so they are not recomputed

- Corpus: 13,021 keys, 9,740 narration blocks, 366,965 words, 622 with `{0}`.
- To render: 9,118 blocks / 341,646 words / ~40.7 h of audio / ~850 MB in Opus 48k.
- Per campaign (blocks): main 2,178, poisonpromise 1,405, hauntingofdale 1,212,
  bonesofarnor 1,193, spreadingwar 1,150, embercrown 1,056, shadowedpaths 924.
- Measured RTF: Chatterbox MPS on the M5 Pro **2.1**; Chatterbox CPU (2 cores) 8.3; Piper CPU 0.09.
- Phase 3 latency budget: capture 20–40 ms + preproc 5–10 ms + OCR 130–350 ms +
  match 1–3 ms ≈ **<0.5 s**, plus 300–600 ms of deliberate wait for stability.
