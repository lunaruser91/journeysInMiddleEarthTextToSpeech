# Narrating the Android game

The game is on the Play Store as well as on desktop, and the same question
applies there: the app records narration only for the Prologue and Epilogues, and
somebody at the table reads the rest aloud. This is the plan for doing on Android
what [the narrator](../README.md) does on macOS and Windows, and the measurements
that shaped it.

Nothing here is built yet except the two tools named as done. The plan is ordered
so that each phase ends with something **known**, not with something written —
you can stop after any of them without having wasted the one before.

---

## What was measured, and what it settled

### The corpus can be extracted from an Android device, without root

This was the largest unknown in the whole plan, and it decides whether somebody
who owns the game **only** on Android can use any of this. It is answered, and
answered well.

The localisation bundles are **not** in the APK. `assets/` holds seventeen
entries and they are all Unity's own — `data.unity3d`, `sharedassets*.resource`,
`global-metadata.dat`. The game downloads its bundles at first run, into Unity's
asset cache:

    /sdcard/Android/data/com.fantasyflightgames.jime/files/UnityCache/Shared/
        <filename>/<version-hash>/__data

The outer directory name is exactly the `filename` field of the manifest — 137
of 137 matched, no exceptions — so reassembling a desktop-shaped `bundles/`
folder is a copy loop and not a reverse-engineering exercise.

And `adb` reads all of it **without root**: the `shell` user belongs to group
`ext_data_rw` (1078), which is what grants it `Android/data`. Measured by
unrooting the emulator and listing inside an installed package's directory.

The manifest itself is byte-comparable with the desktop one:

| | macOS (Steam) | Android |
|---|---|---|
| `version` | 1.6.6 | 1.6.6 |
| `bundleInfos` | 137 | 137 |
| bundle names | — | identical |
| fields per entry | — | identical |

So `phase1_extract.py` runs against the reassembled folder **with no change at
all**, and the corpus it produces is the same corpus:

| | |
|---|---|
| macOS | 13,018 keys |
| Android | 13,018 keys |
| only on one side | 0 |
| differing text | **0** |

Measured on an emulator (Pixel Tablet, android-34, `google_apis_playstore`,
arm64), not on physical hardware. `Android/data` access through `adb shell` is
the same mechanism on both, but that step has not been run on a real phone.

### A speech engine has to be on the device regardless

622 narration blocks — 6.3% of them — carry a `{0}` whose value only exists at
the table. No amount of rendering ahead covers those. So the choice is not
"synthesize on the device or don't"; it is "synthesize on the device, or leave
6% of the narration silent".

Once the engine is there, batch rendering is the same engine in a loop. That
turns a question of engineering into a question of scheduling, and the numbers
answer it:

| | |
|---|---|
| Per block, on an M-series Mac | 0.39 s (RTF 0.029) |
| The same on an ARM tablet, estimated | 1–3 s |
| All 9,814 narration blocks, therefore | 3–8 h |
| Voice model on disk | **60 MB** |
| Pre-rendered audio, pt, `main` + one campaign | **264 MB** |

Two things fall out. Rendering on the device **saves** space rather than costing
it — the model is a quarter the size of the audio it replaces. And rendering the
whole corpus as a batch is an overnight job, which is the wrong shape for a
phone.

So: synthesize **on demand during play, and cache**. Each screen needs one block;
1–3 s while the screen settles fits inside a budget the project already accepts
(`STABLE_FRAMES` alone is a 1.1 s floor, and desktop live synthesis targets about
2.4 s after warm-up). After a few sessions the cache holds exactly the blocks
that campaign uses, and nothing was ever spent on the majority a given
playthrough never shows.

This inverts the desktop design deliberately. On a PC, rendering ahead costs 22
minutes and disk is free. On a phone, CPU is expensive, battery is real, and 264
MB is money.

### What none of that fixes

The corpus still needs one pass through a computer. The game's bundles live in
its own `Android/data` directory, and on Android 11 and later **no other app can
read that** — not through the Storage Access Framework either, which blocks
`Android/data` and `Android/obb` from the picker explicitly. `adb` works because
the `shell` user is privileged; an ordinary app is not.

One USB cable, once. After that the device is self-contained.

---

## The plan

### Phase 0 — can an Android owner extract? — **done**

Answered above: yes, over USB, without root, with the extractor unchanged.

### Phase 1 — does the corpus match the Android layout?

**The phase that can end the project, and the cheapest one.** It needs no Android
code at all: the emulator's window is an ordinary desktop window, and the
narrator already captures windows by title.

The Android build draws its dialogue box somewhere else, at another size, with
other line breaks. If the corpus does not match what the OCR reads there, no APK
fixes it.

```bash
~/jime-venv/bin/python calibrate_region.py shot1.png shot2.png shot3.png
```

That reports the vertical band the narration occupies — see
[`calibrate_region.py`](../calibrate_region.py), which measures it from the OCR's
own bounding boxes rather than sweeping. Then:

```bash
~/jime-venv/bin/python narrator.py --app qemu --window "Android Emulator" \
    --lang pt --region <a>,<b> --profile --save-crops crops-android/
```

**Measured, on six screens harvested from the emulator: six matched.**

| screen | key |
|---|---|
| 1–3 | `bonesofarnor:A1_M1_E1_CHOICE` |
| 4 | `A1_M1_E1_SNEAK_FAIL` + `A1_M1_E1_GREETED` — one box composed of two blocks |
| 5 | `bonesofarnor:A1_M1_E1_ENEMIES` |
| 6 | `main:E_TREASURE_CHEST_SUPER_PASS` |

The band is **`--region 0.15,0.40`** against the desktop's `0.14,0.50` — a
different layout, which is what the tool exists to find. The top is anchored
(0.179–0.181 across all six; the box grows downward) and the bottom ranges
0.257–0.380 with the length of the block.

Screen 4 is the one worth noticing: the game composed a box from two blocks and
the matcher found both, which is the same composition behaviour it has on the
desktop. Nothing about the matching had to change for Android.

**Still open:** the narrator has not been run live against the emulator window
end to end. It finds the window and starts watching — `[source]
qemu-system-aarch64 — Android Emulator` — and then CoreGraphics refuses a
process launched detached from a background shell (`CGS_REQUIRE_INIT`). That is
the harness, not the narrator; run from a terminal it is the ordinary path.
Someone should confirm it interactively.

Two things this turned up about `--app`, which are the project's own, not
Android's. macOS matches the hint against the **application name alone**;
Windows matches it against **application and title together**. So the Android
emulator needs `--app qemu` on macOS — it is owned by `qemu-system-aarch64` and
nothing there is called "Emulator". And the Windows form will match any window
whose *title* contains the hint, which for a default of `Journeys` includes a
terminal sitting in this project's own directory.

Do not read the `paused Nf` figure from an emulator. A machine that drops frames
animates as continuous motion — the same trap that made a GPU-less VM report no
pause above 3 frames when a real recording found 10.

### Phase 2 — pull the bundles, one cable, one time

A tool that reads the bundles off a connected device and reassembles them in the
shape `phase1_extract.py` expects. The measurement above is the whole design:
walk `UnityCache/Shared/*/*/__data` and name each copy after its parent
directory, which is the manifest's `filename`.

**Ends when** somebody with only an Android copy of the game can produce their
own corpus.

### Phase 3 — port the matcher, with the net underneath

The intellectual core, and the one part with an objective finish line.
`rapidfuzz` is C++ with no Android build, so `partial_ratio` gets written by hand
either way.

What has to be reproduced, all of it from `matcher.py`:

- `normalize` identical on both sides — PUA, case, accents
- `partial_ratio`: sliding-window Levenshtein, best score
- threshold 82, safe threshold 92
- minimum length ratio 0.75
- minimum margin 5.0 over the runner-up
- tie margin 1.0, applied only below 40 characters
- a fragment requires the safe threshold
- conflicting numbers refuse

**Ends when** the Kotlin matcher reproduces `test_matcher.py`'s table against the
same 631 real screens: 99.2% hit at 0% noise, 95.6% at 2%, 94.2% at 5%. That is a
proof, not an estimate.

### Phase 4 — capture and trigger

`MediaProjection` with a foreground service, and `ImageReader`. The trigger is
mechanical: dhash 16×16, 0.5% of pixels changed, dedupe with a 100 s TTL.

One thing does not copy across: `STABLE_FRAMES = 11`. It is a 1.1 s floor
calibrated on the desktop, and the frame rate and animation of the Android build
are not the desktop's. Measure it on the device.

**Ends when** the app marks "settled" at the right moments, speaking nothing.

### Phase 5 — OCR

ML Kit on-device, offline, free. It covers Latin, Chinese, Japanese and Korean —
and **not Cyrillic**, so Russian and Ukrainian need Tesseract or wait. Those two
have no icon vocabulary yet either, so leaving them for later is consistent.

**Ends when** `test_ocr.py --from-captures` on the Phase 1 crops reports a
character error rate in the same band as Apple Vision's 0.09%.

### Phase 6 — synthesis on the device, with a cache

onnxruntime's Android AAR, the same 60 MB voice model, and espeak-ng for
phonemization — `pt_BR-faber-medium.onnx.json` declares `phoneme_type: espeak`,
so the text-to-IPA step is not optional.

Worth evaluating before porting espeak-ng by hand: **sherpa-onnx** packages
VITS/Piper models together with espeak-ng data and publishes an Android AAR. If
it covers Piper voices, this becomes a binding rather than a port. Unverified.

Synthesize on demand, cache by block key, and let the cache fill with what is
actually played. Nothing is rendered ahead and nothing is copied from a PC.

**Ends when** a block is spoken within the budget the settling floor already
imposes, and the second time it appears comes from the cache.

### Phase 7 — playback

A queue over ExoPlayer, interrupted when the next screen arrives, with the
silence reasons `player.py` already knows how to give. The small one.

---

## What changed from the first draft of this plan

Two phases died and one was promoted.

**The export package is gone.** The first plan had the PC rendering audio and a
264 MB folder being copied to the device. On-device synthesis removes it
entirely, and costs less disk than it saves.

**"Decide what to leave out" is gone.** It existed to decide what to do about the
622 placeholder blocks without a speech engine. There is no version of this that
does not have a speech engine, so there is nothing to leave out.

**Synthesis moved from optional to required**, for the same reason.
