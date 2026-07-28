# Phase 2 — what was measured about Chatterbox's performance

This document closes the "🔴 OPEN PROBLEM" from §5 of the briefing. Everything
here is measurement on this hardware, not estimate. Where the measurement
contradicts the briefing, the measurement wins — and the briefing is annotated as
corrected.

**Hardware:** MacBook Pro 14" M5 Pro, 24 GB, macOS Tahoe 26.5.2
**Stack:** Python 3.13.13, torch 2.6.0, transformers 5.2.0, chatterbox-tts 0.1.7, MPS
**Parameters:** `exaggeration=0.45`, `cfg_weight=0.35`, seed 1234, 12 s reference

---

## 1. The methodological pitfall that nearly invalidated everything

The first round measured the four modes in sequence, in the same process. The
result was clean, coherent and **false**: each mode was slower than the previous
one, in perfect order (117 → 143 → 202 → 218 ms/token). Two causes added up —
there was concurrent load on the machine, and the order effect was not
controlled.

Redoing it with **one process per mode** and **counterbalanced order**
(`A B C D D C B A`), the drift became explicit:

| mode | 1st pass | 2nd pass | drift |
|---|---|---|---|
| A | RTF 3.64 | RTF 3.23 | −11.3% |
| B | RTF 3.10 | RTF 3.57 | +15.0% |
| C | RTF 3.35 | RTF 4.34 | **+29.5%** |
| D | RTF 4.21 | RTF 4.43 | +5.3% |

**The drift between two runs of the same mode reaches 30%.** That is larger than
almost every effect one wants to measure. Practical consequence, and the most
important lesson in this document:

> No difference below ~30% can be asserted by comparing separate runs on this
> Mac. Smaller differences require a **paired design** — the same sentence, in
> both configurations, one right after the other, alternating the order.

This adds to pitfall no. 9 of the briefing ("estimating RTF from it/s is
misleading"): measuring wall clock against audio is not enough, it must be
measured **paired**.

## 2. Where the time actually goes

Per-stage profiling, average of the two passes:

| stage | share of wall clock |
|---|---|
| `t3.inference` (autoregressive decode) | **80–85%** |
| `s3gen.inference` (flow matching + vocoder) | 11–16% |
| `prepare_conditionals` | ~1% (after the fix) |
| watermark (perth) | <0.5% |

**The T3 decode is the entire problem.** Any optimization that does not attack it
is statistical noise. That rules out the watermark and the DSP chain as targets
from the start.

## 3. The briefing's two hypotheses

### §5.1 — conditionals recomputed on every call: **confirmed, but small**

The code confirms it: `mtl_tts.py:269-270` calls `prepare_conditionals()`
whenever it receives `audio_prompt_path`, that is, once per sentence. Measured,
the stage drops from **10.7 s to 1.1 s** in a batch of 13 sentences.

Except that this was ~4% of the wall clock, not the bottleneck. **Net gain in
RTF: ~3%.** Worth applying because it is free, not because it solves anything.

### §5.2 — joining sentences into chunks of ~220 chars: **refuted**

| | mean RTF | calls |
|---|---|---|
| one sentence per call (B) | 3.34 | 13 |
| chunks of 220 chars (C) | **3.84** | 7 |

Grouping sentences **made it 11% worse**, despite almost halving the calls.
Profiling shows why: `s3gen` improved (44 s → 30 s), but `t3` got worse by more
(188 s → 212 s). The decode is autoregressive with *eager* attention and a
growing KV cache — doubling the length **more than doubles** the cost. The fixed
per-call cost one wanted to dilute is too small to compensate.

> Correction to briefing §5.2: chunking is not a lever, it is a step backwards.
> Keep one call per sentence.

## 4. A third hypothesis, found in the code and also refuted

`t3.py` sets `self.compiled = False` at the start of **every** `inference()`,
rebuilding the `AlignmentStreamAnalyzer`; its `__init__` registers 3
`register_forward_hook` (`alignment_stream_analyzer.py:80-84`) and **never
removes the previous ones**.

The leak is real and was measured: **69 live hooks after 23 sentences**, against
3 with the fix. Since each hook does `output[1].cpu()` per token, it looked like
the bottleneck.

It is not. Two pieces of evidence:

- Within a single run of mode A, ms/token **does not grow**: 138.9 on the first
  call, 128.2 in the last third — despite the hooks going from 3 to 69.
- The mode with the fix (D) came out **slower**, not faster.

**Verdict:** it is a hygiene defect, not a performance one. It is still worth
fixing, because each retained hook holds attention tensors and in a marathon of
thousands of blocks that is a memory leak — but without claiming any time gain.

## 5. The lever that looked big — and is a pitfall

The `AlignmentStreamAnalyzer` forces `_attn_implementation='eager'` on the
**entire** transformer, turning off fused attention (SDPA) across the 30 layers,
and does 3 GPU→CPU synchronizations per token. Turning it off looked like the
largest gain available.

Paired test (same sentence, same seed, the two configurations in sequence):

| | wall clock | audio generated | RTF |
|---|---|---|---|
| baseline | 34.5 s | 14.3 s | 2.41 |
| without the analyzer | 136.0 s | **26.7 s** | 5.10 |

Note the audio: **the model generated almost twice as much sound for the same
text.** The analyzer is not decorative overhead — it is the brake that stops
degenerate generation. Without it the model goes into a long tail and
hallucinates. Turning it off makes speed *and* quality worse.

> This also reinterprets the briefing's "anomaly to investigate" (§5, the
> `A1_THREAT_1` block at 1.00 words/s with `🚨 Detected 2x repetition → forcing
> EOS`): the analyzer did not cause the problem, it **contained** it. Without the
> brake, that block would have come out much worse.

## 6. Situation and options

Measurement of the production renderer on 15 real Bones of Arnor blocks:
**733 s of synthesis for 231 s of audio → RTF 3.17**, pace of 127 words per
minute, zero failures.

| campaign | blocks | words | audio | render |
|---|---:|---:|---:|---:|
| main | 2,178 | 71,002 | 9.3 h | 29.6 h |
| poisonpromise | 1,405 | 51,505 | 6.8 h | 21.5 h |
| spreadingwar | 1,150 | 49,715 | 6.5 h | 20.7 h |
| bonesofarnor | 1,193 | 45,556 | 6.0 h | **19.0 h** |
| hauntingofdale | 1,212 | 45,415 | 6.0 h | 18.9 h |
| embercrown | 1,056 | 43,575 | 5.7 h | 18.2 h |
| shadowedpaths | 924 | 34,878 | 4.6 h | 14.5 h |
| **total** | **9,192** | **342,513** | **44.8 h** | **142.3 h** |

The whole corpus remains unfeasible in one go. **One campaign is not.**

There is, on the measured path, no order-of-magnitude gain. The real options, in
order of cost:

1. **Render per campaign, on demand.** Bones of Arnor: 6.0 h of audio in ~19 h of
   machine time. Two nights, for the campaign one is going to play. This makes
   the project feasible today, without writing anything more.
2. **Piper for the lower-value campaigns** (RTF 0.03). But see §7: Piper is not
   installed on this machine and `render_piper.py` has a defect.
3. **Batching in T3.** It is the only lever with order-of-magnitude potential.
   The decode is strongly *memory-bound* (536 M parameters in fp32 = 2.14 GB read
   per step, regardless of the batch), so there is headroom for 8–16 rows before
   it becomes *compute-bound*. Cost: ~40 lines to unlock the loop, plus an
   attention mask that today does not exist anywhere in the T3 path, plus
   rewriting or turning off the `AlignmentStreamAnalyzer` — which reads only row
   0 of the batch. I estimate 150 delicate lines. **Not measured; it is a
   project, not a tweak.**

## 6a. Two render processes at once are 55% SLOWER than one

The obvious way to go faster is to run several renders side by side. Measured, it
is not merely useless — it costs more than half the throughput again.

| arm | wall clock | decode only | spread |
|---|---|---|---|
| one process, 8 blocks | 115.2 / 121.1 s | 108.2 s | 5% |
| two processes, 4 blocks each | 181.0 / 184.9 s | 172.5 s | 2% |

**0.63x.** Both arms rendered the same 8 blocks and the same 96 words; the halves
were interleaved by length so each process carried 48 words. Order was ABBA
(seq, par, par, seq) because two identical runs on this machine have differed by
30% before, and each run wrote to its own output directory — the renderer skips a
block whose file already exists, so a repeated run would have measured nothing.
Model load, ~10 s, is reported separately: the parallel arm pays it twice, which
is a real cost of the approach but not evidence about decode.

The effect is far larger than the spread within either arm, so it is not drift.

This is what §6's memory-bound claim predicts, and then some. Each process reads
its own 2.14 GB of weights per step, so two of them double the demand on a single
memory system without doubling the bandwidth. Going *below* 1.0x on top of that
is what unified memory adds: two full copies of the weights compete for the same
pool the CPU uses, and MPS has to switch contexts between them.

The conclusion is not "parallelism does not help here". It is that the sharing
has to happen **inside** one process, where those same 2.14 GB serve 8-16 rows at
once instead of being read once per row. That is item 3 below, and this
measurement is the argument for it.

## 6c. Piper measured: RTF 0.049, and the old renderer never worked

§7 said Piper was not installed and `render_piper.py` had a defect. Both are now
fixed, and the numbers are measured on this machine rather than inherited.

Rendering the **same 226 blocks** the Chatterbox run had just produced:

| | Chatterbox | Piper |
|---|---|---|
| wall clock | ~2.5 h | **103 s** |
| RTF | 3.7 | **0.049** |
| failures | 15 | 0 |
| size | 14 MB | 12 MB |

**74x.** What remains of `main` + `bonesofarnor` — 111,131 words, 14.4 h of
speech — is 53 h with Chatterbox and **43 minutes** with Piper.

The briefing's figure was RTF 0.03. The measured 0.049 is worse than that but
the order of magnitude holds, and it is the one to quote from now on.

### The old renderer had two defects, not one

`legacy/render_piper.py` was known to name `rubberband` unconditionally, which
this ffmpeg does not have — every block would have failed at the ffmpeg call.
The second defect was not recorded anywhere: it synthesized `v["text"]`, the raw
screen text, so the entire glyph and number layer was bypassed. Icons would have
reached the tokenizer as nothing and digits would have been read in whatever
language the model defaulted to — the exact bug that produced "uno" for "1".

`phase2_render_piper.py` shares `wizard_chain()` and `prepare_speech()` with the
Chatterbox renderer rather than restating them, which is why it cannot drift
again.

### Pace had to be calibrated, and it is not linear

Piper at `length_scale=1.0` speaks at 3.13 words/s against Chatterbox's 2.17 on
the same 40 blocks — 182 words per minute, above the audiobook range. The
response to the knob is not linear:

| length_scale | words/s |
|---|---|
| 1.00 | 3.13 |
| 1.42 | 2.43 |
| 1.50 | 2.32 |
| **1.63** | **2.14** |

1.63 is the default. It matters because the two engines are meant to be mixed
inside one session: a screen rendered by one and the next by the other should
differ in voice, not in pace.

## 6b. The degenerate block: the cause was the seed, not the token ceiling

`bonesofarnor:A1_THREAT_1` came out at 43.2 s for 43 words in the old renderer
and comes out at ~21 s in the new one. Between the two, two things changed at the
same time — the token ceiling per sentence (fixed 1000 -> budgeted by length) and
the seed handling (seeded once before the loop -> reset per block). I attributed
the improvement to the ceiling. **I was wrong, and the experiment shows why.**

The design did not need to be a 2x2: "global seed" is not a treatment, it is an
unknown draw — the RNG state at the start of a block is only a consequence of
what the previous blocks consumed. Varying the seed already covers that factor,
and the entire generation budget goes to repetitions, which is where the power
is.

Whole block, sentence by sentence, 14 seeds, ceiling 1000 against adaptive
ceiling:

| | ceiling 1000 | adaptive |
|---|---|---|
| degenerate blocks (ratio > 1.4) | **0/14** | **0/14** |
| median ratio | 1.05 | 1.05 |
| worst case | 1.12 | 1.12 |
| sentences that blew the budget | — | **0/56** |

The two columns came out **identical across all 14 seeds** (20.4/20.4,
18.0/18.0…). With the same seed and the ceiling never being reached, generation
is deterministic and produces the same audio. That is: **the adaptive ceiling is
inert in normal operation.**

Conclusions, in this order of confidence:

1. **The token ceiling fixed nothing** — it never gets to act. The improvement
   from 43.2 s to 21 s came from the other factor: a different sampling
   trajectory. The 43.2 s were a **rare draw**, not a systematic defect.
2. **The adaptive budget is safe and worth keeping**, but as an insurance policy,
   not as a fix: zero cost in normal operation (0/56 sentences reach it, none
   truncated) and it limits the damage if degeneration does occur.
3. **Degeneration is rarer than 1/14 for this block.** Adding up the three
   experiments — 12 seeds on the sentence with an icon, 20 pairs in the broad
   test, 14 seeds on the whole block — there were only 2 events in ~60 attempts,
   and none reproduced the original case.
4. Therefore, **the only real defense is after-the-fact detection**:
   `--check-ritmo` measures words/s and re-renders with another seed. It is the
   right mechanism for a rare, stochastic event — it cannot be prevented, it can
   be caught.

## 6c. Game icons in the text — fixed in `glifos.py`

**2,396 of the 9,192 blocks (26.1%)** contain 3,303 Private Use Area characters
(U+F460–U+F47A): the symbols of the game's font. The Phase 1 cleanup removes
`<sprite=>` tags but does not see literal characters, so they were reaching the
TTS.

The mapping came from the game's own 24 `main:GLYPH_*` keys, validated against
the legend in the pt-BR manual. Two entries I had inferred were wrong and the
manual corrected them: `RANGED` is "De Alcance" (not "à distância") and `TRINKET`
is "Apetrecho" (not "bugiganga").

A subtlety that would break Phase 3: the audio SAYS "testa Agilidade", but the
screen SHOWS the icon. The matching index (`norm` in the manifest) is built with
the glyphs REMOVED, not substituted — otherwise the OCR would never match.

## 7. Defects found in passing

- **`render_piper.py` breaks on this Mac.** `WIZARD_CHAIN` (line 17) uses
  `rubberband=` unconditionally, and Homebrew's ffmpeg does not ship that filter
  — `render_corpus.py` already detected this and fell back to an equivalent, but
  the Piper one was left behind. Every block would fail.
- **Piper is not installed** in this venv, and there are no `.onnx` voices
  downloaded. Phase 3's "live fallback" does not yet exist in practice.
- **The Piper render of Bones of Arnor described in the briefing** (1,174 files,
  125 MB, 5.8 h) **is not on this machine.** Only the 20 Chatterbox test blocks
  exist.
- **`manifest.json` was not in the briefing's `.gitignore`**, and it contains the
  full text of every block — it is the corpus under another name. Fixed.

## 8. Reproducing

The measurement scripts live outside the repository (they are disposable), but
the method is:

```bash
# per-stage profile, one mode per process, counterbalanced order
for m in A B C D D C B A; do python3 bench2.py $m 4; done

# paired test — the only design that resolves differences <30%
python3 bench3.py 12
```

The pace detector, that one is permanent:

```bash
python3 check_ritmo.py audio/manifest.json --mad 2.0
```
