# Phase 3 — syncing the audio with the game

> **This is the plan as it stood before Phase 3 was built, kept for its
> reasoning.** Several of its constraints turned out to be false and the
> shipped narrator does not have them — notably that macOS capture would need a
> signed `.app` and a developer account (it does not: the screen-recording
> grant attaches to the terminal), and that Piper was not installed (it is the
> only synthesiser the project has). For what was actually built and measured,
> read [ENGINEERING](ENGINEERING.md).

> **Conclusion, after testing:** the trigger is still the screen, as §6 of the
> briefing predicted — but the problem became **much** easier.
>
> The game keeps a log with the exact localization keys (4,827 lines checked
> against the corpus: 100% match). It is written **every round** of the game,
> with no need to save — tested on 2026-07-27, see §5. As a per-screen trigger,
> it arrives far too late; as live context, it is perfect.
>
> What it delivers instead is **free ground truth** for the OCR harness — 626
> labelled screens without transcribing any by hand — and it decodes how the game
> assembles the text on screen (§5b). It also narrows the candidate set through the
> save file, though measurement later showed that narrowing matters far less than
> it seemed at first (§5c, §5f).

## 1. The discovery

```
~/Library/Application Support/com.fantasyflightgames.jime/SavedGames/<slot>/
    SavedGameA, SavedGameB    plain JSON, not encrypted
    LogA.txt,   LogB.txt      event log, append-only
```

`LogA.txt` is plain text, one line per block displayed, in chronological order:

```
[1|1|A1_M1_E1_CHOICE|0]
[1|1|A1_M1_E1_INTIMIDATE|0]
[1|1|A1_M1_E1_ENEMIES|1|8|0|UI_ZERO_WIDTH_SPACE|0]
[1|1|UI_THREAT_INCREASE|1|10|0|4|0]
```

Format: `[adventure | round | KEY | n_params | (type|?|value|?) * n_params]`

- **field 1** — adventure number, 1..8 in a full campaign
- **field 2** — round within the mission
- **field 3** — the localization key, identical to the corpus one
- **field 4** — how many parameters follow; each takes up 4 fields
- **observed types** — `8` = reference to another localization key,
  `10` = literal value, `4` and `11` = not yet identified

The log accumulates the entire campaign: the measured slot runs from
`A1_M1_E1_CHOICE` (adventure 1) to `B2_GOOD_ENDING` (adventure 8) in 1,009 lines.

## 2. The numbers on the matching problem

The OCR path has problems that **I measured in this corpus**, not ones I assume:

| problem | measured |
|---|---|
| blocks with normalized text identical to another | 153 groups, **346 blocks** |
| blocks sharing the first 40 characters | **1,194 (13.1%)** |
| short blocks (< 60 chars), the ones that confuse the most | 627 (6.9%) |
| blocks with icons the OCR does not read as text | **2,396 (26.1%)** |

Add to that what the briefing already listed: on macOS 26 Tahoe the classic
capture APIs return only the wallpaper, the valid path requires ScreenCaptureKit
in a `.app` signed with a real Team ID because of TCC, and OCR costs 130–350 ms
per frame.

**But note: these numbers apply to the ENTIRE corpus.** That is the difference
§5c makes — scoping by adventure, the ambiguity practically disappears.

## 3. The 622 blocks with `{0}`: resolved after the fact, not live

They were the hole in the original plan: they are only completed at game time.
The log carries the values — but only after the save, so this is good for
checking and for understanding the structure, not for narrating on the spot:

```
text   : "Aumente a ameaça em {0}."
log    : [1|1|UI_THREAT_INCREASE|1|10|0|4|0]      -> {0} = 4
```
```
text   : "Coloque a peça {0} conforme indicado."
log    : [1|2|UI_SECTION_REVEAL_PLACE_TILE_FORMATTED|1|10|0|300A|0]   -> {0} = "300A"
```
```
text   : "{0} <DANO> {1} <MEDO>"
log    : [1|1|UI_DAMAGE_LOG_FORMATTED|2|10|0|2|0|10|0|2|0]   -> {0}=2, {1}=2
```

Live, the value will have to come from the OCR of the screen itself — which is
exactly where it appears. The log serves to validate whether the OCR read it
right.

## 4. Revised architecture (after the §5 test)

```
watcher on SavedGame*        -> reads CurrentAdventureId  [SCOPE: ~80 candidates]
game window capture          -> ScreenCaptureKit, 5-10 Hz
 -> absdiff -> dhash -> stability (3 frames)         [trigger]
 -> OCR (Apple Vision, pt-BR)
 -> matching with rapidfuzz AGAINST THE ~80 BLOCKS OF THE ADVENTURE, not against 9,814
 -> plays the .opus from the manifest
 -> at the end of the session: checks what was narrated against LogA.txt and measures the real hit rate
```

Scoping by the save is what makes this viable. And the log, even if late, closes
the loop: you can measure the hit rate without transcribing anything by hand.

`SavedGame*` (plain JSON) remains useful as context: `CampaignId`,
`CurrentAdventureId`, `CampaignDifficulty`, `PartyName`, the heroes. It serves
the status window and the choice of the audio folder for the right campaign.

## 5. ANSWERED: the log is written EVERY ROUND

Two tests, on 2026-07-27.

**Test 1 — play 9 screens and quit with a save.** The watcher showed nothing. The
disk showed a single write, at 08:29:37, in the same second as `SavedGameA`.
Hasty conclusion: "the log is only written on save". **Wrong.**

**Test 2 — play without saving, watching only the file size.**

```
08:29:37  11,056 bytes   (end of test 1, save and quit)
08:41:28  11,239 bytes   DURING the game, without saving
```

The file grew in the middle of the game. The 6 lines added were:

```
adv3 rd1 UI_PHASE_SHADOW               "Fase da Sombra"
adv3 rd1 ENEMY_ORC_MARAUDER_ALT_ACTIV  "Bradando um grito de guerra feroz..."
adv3 rd1 UI_THREAT_INCREASE            "Aumente a ameaça em 4."
adv3 rd1 UI_RALLY_PHASE                "Fase de Reagrupamento"
adv3 rd1 UI_RALLY_PHASE_INSTRUCTIONS   "...restaura seu baralho e examina 2."
adv3 rd2 UI_PHASE_HERO                 "Fase de Ação"
```

The write landed exactly on the turn from `rd1` to `rd2`, and the following
screens (round 2, still in progress) were not in the file.

**Cadence: one write per game ROUND, with all of the round's events at once.** In
the measured batch, ~6 events per write.

### What this means

| question | answer |
|---|---|
| does it work as a trigger to narrate each screen? | **no** — it arrives one round late |
| does the log stay fresh during the game? | **yes** — no need to save or quit |
| does it work as scope in real time? | **yes** — current adventure and round, with at most one round of lag |
| does it work as ground truth? | **yes**, and it accumulates on its own every game |

The trigger is still the screen. But the log stops being a post-game artifact and
becomes **live context**: at any moment of the game it says which adventure and
round the party is in, which is exactly what the scoping in §5c needs.

## 5b. The parameter system, decoded

Before knowing the log was late, the decoding of the parameters was already done,
and it holds independently — because it describes how the game **assembles** the
text that appears on screen:

| type | meaning | example |
|---|---|---|
| `3` | hero of the party, by index in the party | `A2_M1_INTRO` + `3\|0` → "**Legolas** se curva sobre o chão…" |
| `8` | reference to another localization key | `PLACE_PERSON` + `8\|A2_M1_T1_PLACE` |
| `10` | literal value | `UI_THREAT_INCREASE` + `10\|4` → "Aumente a ameaça em **4**." |

Type 8 is the most important one and it was a surprise: **narrative prose is
usually passed as a parameter to a generic template.** The text of `PLACE_PERSON`
in the corpus is only `"{0}\n\nColoque uma ficha de pessoa conforme indicado."`
(English: "Place a person token as indicated.") —
the whole story lives in `A2_M1_T1_PLACE`, a separate key.

This changes how OCR matching has to work: **what appears on screen is the
concatenation of several corpus keys, not a single key.** Matching the whole
screen against an isolated block would fail in exactly those cases.

(Open link: the hero index comes from the save's `HeroInfo`, but the numeric `Id`
— 4, in the party tested — has not yet been mapped to `HERO_LEGOLAS_NAME`. That
table still has to be found in the assets.)

## 5c. What saves the OCR path: scoping by adventure

The save says which adventure the party is in (`CurrentAdventureId`). Measuring
the existing logs, how many distinct narration blocks appear in each adventure:

| adventure | distinct blocks |
|---|---|
| 1 | 115 |
| 2 | 54 |
| 3 | 62 |
| 4 | 86 |
| 5–6 | 84 each |
| 7–10 | 18 to 57 |

**Careful with what this table means.** These are the blocks *observed in the
logs* for each adventure, not the candidate set a matcher has to choose from. The
real scope is larger: adventure 3 of Bones of Arnor has 44 story keys (`A2_*`) plus
~2,358 generic ones (`UI_*`, `PLACE_*`, `ENEMY_*`, `TERRAIN_*`) that can show up in
any adventure. From 9,814 down to ~2,402 — a 4× reduction, not 100×.

And measurement went further, in §5f: scoping barely changes the outcome at all.
The whole corpus scores 97.6%, the campaign 98.2%, the adventure 98.7%. What
actually does the work are the guards and the paragraph-level matching. The scope
is still worth keeping — it is free, since the save file is already there, and it
cuts CPU cost — but it is not the lever it first appeared to be.

## 5d. And the log gains three new roles

Even when late, it is valuable:

1. **Ground truth for the OCR harness.** The test session produced 9 real screens
   with the exact key for each one, saved in
   `output/ocr-fixtures/sessao-2026-07-27.json`. It is exactly what §10 item 4
   of the briefing asks for, and it came for free. Every game played generates more.
2. **After-the-fact correction.** At the end of a session, you can check what was
   narrated against what the game recorded, and measure the real hit rate of the
   matching — without transcribing anything by hand.
3. **Scope.** Together with `SavedGame`, it defines the candidate set.

## 5e. There is no live signal — four avenues investigated and closed

Before accepting OCR, four alternatives were investigated. **All dead ends**, and
the evidence comes from code, not from watching mtime.

**Flush mechanism, proven in the IL of `Assembly-CSharp.dll`:**

`FFG.JIME.MasterMessageCache` accumulates every displayed block in
`_pendingMessages`, an in-memory list. `AddMessage` — called by
`Adventure::LogMessage`, `DisplayMessageBase::LogMessage`,
`SpawnEnemyGroup::OnProgress`, `CoroutineExploreTile` and others — **never
touches the disk**. The only point that calls `Stream::Flush` is
`FlushLogStream`, and it has exactly two callers: `CloseLogStream` and
`GameData::CoroutineSave`. The latter, in turn, is called from six places, of
which **the only periodic one is `GameController::CoroutineEndRound`** — the end
of the round. The others are the explicit save, the adventure setup and three
scene transitions.

Independent confirmation: with the game running, `lsof` does not list `LogA.txt`
among the open descriptors. The file is not even kept open during the game.

> This corrects the *argument* I used before, even though the conclusion was
> right: I deduced the cadence from a single mtime, and mtime only records the
> LAST write, never the count. It is the call graph that supports the claim.

**Accessibility — the door the briefing closed by assumption, now closed by
measurement.** `UnityEngine.AccessibilityModule.dll` is in the build, but it is
only the color-blindness palette. `UnityPlayer.dylib` exposes 1,353 Objective-C
selectors and **zero** accessibility ones. Independent control: Gloomhaven (Unity
2021.3.5f1) gives the same result — it is a property of the engine, not of this
game. All the text is TextMeshPro SDF mesh on the Metal layer; there is never an
`NSView` with a string.

**Analytics, audio, network and IPC — all dead.** The game never emits a custom
Analytics event (only the `appRunning` heartbeat and `appStop`, written at
shutdown). macOS exposes audio per process, but only as a boolean, and Unity
keeps it pinned. The AssetBundles are per adventure, not per screen, and they
stay open. There is no listening socket, pipe, distributed notification or XPC.

**The only useful side finding:** `Player.log` is the game's unbuffered stdout,
written live (<100 ms). But it records only **scene** changes (~6-7 per session),
never a localization key. It is good for knowing when the game enters or leaves a
mission — not for narrating.

**Conclusion: the screen is the only possible trigger.** What changes relative to
the briefing is not the path, it is the difficulty: with the scoping by adventure
(§5c) the matching picks among ~62 candidates, and the log provides the exact
oracle to measure the hit rate.

## 5f. The matcher: built and measured

`matcher.py` + `test_matcher.py`, measured against **627 real screens
reconstructed from the game logs** (107 of them composed of 2+ keys). The
briefing asked for "30-50 real transcribed screenshots"; these 627 came out
without transcribing any.

Synthetic OCR noise with the classic confusions of serif text
(m↔rn, l↔i, c↔e, d↔cl, o↔0), character drops and duplications, word joining.

**Metric: per screen.** The question that matters for playback is "did the screen
have its prose block identified?", not "did every paragraph match?". Counting per
paragraph punishes the matcher for matching *"Coloque uma ficha de busca conforme
indicado"* with another block that has the same instruction — inevitable and
irrelevant, because what gets narrated is the prose.

| scope | noise | hit rate | **wrong** | refusal |
|---|---:|---:|---:|---:|
| campaign + main (7,314 cand.) | 0% | **98.2%** | 1.0% | 0.8% |
| campaign + main | 2% | 95.5% | 1.3% | 3.2% |
| campaign + main | 5% | 93.0% | 2.1% | 4.9% |
| campaign + main | 10% | 73.0% | 4.6% | 22.3% |
| entire corpus (21,559 cand.) | 0% | 97.6% | 1.0% | 1.4% |
| by adventure | 0% | 98.7% | 0.6% | 0.6% |

### Three conclusions, one of them against what I assumed

1. **Scope barely matters.** The entire corpus gives 97.6%; the campaign gives
   98.2%; the adventure gives 98.7%. I had bet on scope as the big lever — it is
   not. What does the work are the guards and the per-paragraph matching. Scope
   is still worth it for being free (the save is already there) and for cutting
   the CPU cost.

2. **Robust up to ~5% CER, collapses at 10%.** Between 0% and 5% the hit rate
   drops about 5 points. At 10% it drops 20 points. Since Apple Vision usually
   gives 1-3% on clean text, the margin is comfortable — but it is the image
   pre-processing (§6 of the briefing) that keeps the CER in that range, and it
   is not optional.

3. **The ~2.4% wrong are less serious than they look.** Opening up the 7 wrong
   results of one run: 2 were blocks with identical normalized text (same audio),
   2 were the same key in a different paragraph, 1 differed by one letter — `"ha
   boatos **sobra** a existencia"` against `"**sobre**"`, a typo in the game
   itself. That left ~2 real errors in ~940 matches.

### What is left in the ~10% refusals

The length-ratio guard accounts for most of them. It was the one that led to the
most useful fix in the matcher: **also indexing every paragraph of every block**,
not just the whole block. Without that, a screen showing one paragraph of a
three-paragraph block fell into the guard (150 chars against 450 gives a ratio of
0.33). That alone was worth +6 points of hit rate.

Refusing is the right behavior: silence is recoverable with live TTS, narrating
the wrong block is not — the player acts on what they hear.

## 6. Remaining risks and uncertainties

- **Coverage.** 592 distinct keys in the analyzed logs, 1,863 occurrences of
  narration blocks. It remains to be confirmed that *every* screen the players
  read aloud generates a line — there may be displayed text that is not recorded.
- **Order ≠ display.** The log says the block was triggered, not how long it
  stayed on screen. For narration that is enough, but there is no way to know
  whether the player has already read it.
- **A/B buffers.** Read both and deduplicate; do not assume A is always the current one.
- **Prologue and epilogue.** The game **already narrates** these in pt-BR (see
  `narration/<campanha>/pt`, 20 clips, 18.4 min of professional voice). The
  narrator must stay silent on these blocks, or there will be two voices at once.
- **The log belongs to the game, not to you.** An update can change the format.
  The parser must fail visibly, not silently.

## 7. Order of work

1. **OCR harness.** Real, labeled fixtures already exist in
   `output/ocr-fixtures/`, generated without transcribing anything — the log
   gives the key of each screen. Accumulate more by playing, and measure the CER
   of Apple Vision vs RapidOCR with data, not with faith.
2. **`matcher.py`** — rapidfuzz against the set of the current adventure (~62 blocks),
   not against the corpus. Test with degraded synthetic OCR before plugging it into the screen.
   Remember that the screen is a concatenation of several keys (§5b).
3. **Save reader** — `CurrentAdventureId` for the scope; cheap and requires no permission.
4. **Capture on macOS** — ScreenCaptureKit in a signed `.app`. It is the expensive
   item (half a day, plus the developer account), and the last one to do, because
   everything above can be developed and tested with saved screenshots.
5. **`trigger.py`** — absdiff → dhash → stability → dedupe, per §6 of the
   briefing, which remains valid.
6. Integration, status window, hotkeys.
7. Piper for the blocks with `{0}` — remembering that it is **not installed** and
   that `render_piper.py` breaks on this ffmpeg (it uses `rubberband`, absent).
8. Only then port to Windows — where the capture layer changes, but the matcher,
   the scope and the corpus are identical.
