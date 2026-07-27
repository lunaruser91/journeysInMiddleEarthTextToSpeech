#!/usr/bin/env python3
"""
phase2_render.py — Phase 2 of the JiME Narrator, the measured version.

Differences from the original render_corpus.py, each one justified by a
measurement on this hardware (M5 Pro, MPS, chatterbox-tts 0.1.7) and not by a
guess:

  1. `prepare_conditionals` ONCE, not per sentence.
     Chatterbox's generate() redoes the voice conditioning every time it gets
     `audio_prompt_path` (mtl_tts.py:269-270). Measured: ~10.7 s per batch of 13
     sentences against ~1.1 s. The real gain is modest (~3% of the clock), but free.

  2. Does NOT group sentences into chunks.
     The briefing proposed joining sentences up to ~220 chars to dilute the fixed
     per-call cost. Measured in counterbalanced order: chunking came out 11% SLOWER
     (RTF 3.84 against 3.44). The reason is mechanical: the T3 decode is
     autoregressive with eager attention and a growing KV cache, so doubling the
     length more than doubles the cost. Diluting the overhead does not pay for it.
     One sentence per call.

  3. Hook hygiene.
     t3.inference() rebuilds the AlignmentStreamAnalyzer on every call and registers
     3 forward hooks without removing the previous ones
     (alignment_stream_analyzer.py:80-84). Measured: 69 live hooks after 23
     sentences. This does NOT cost measurable time — fixing it did not speed
     anything up — but it retains attention tensors indefinitely, which over a
     marathon of thousands of blocks is a real memory leak. Fixed for hygiene,
     with no claim of a speed gain.

  4. ADAPTIVE token budget per sentence.
     `generate()` hardcodes max_new_tokens=1000 internally (mtl_tts.py:297) — 40 s
     of speech. When the model degenerates and does not emit EOS, it pays the whole
     1000: that is what happened with `bonesofarnor:A1_THREAT_1`, which came out at
     43.2 s for 43 words. Here each sentence gets twice the tokens its word count
     predicts, with a floor of 250 and a ceiling of 1000.
     A low fixed ceiling would be worse: measured on the corpus (28,044 sentences),
     a ceiling of 400 would put 166 sentences (0.59%) at risk of truncation, and the
     longest sentence needs ~736 tokens. The adaptive budget tightens where
     degeneration is likely and gives room where it is needed.
     MEASURED AFTERWARDS, over 14 seeds on the whole block: the ceiling is NEVER
     reached (0/56 sentences) and the outputs with a 1000 ceiling and with the
     adaptive ceiling are identical. That is, this is insurance, not a repair — the
     A1_THREAT_1 improvement (43.2 s -> 21 s) came from the seed, not from the
     ceiling. Kept because it costs nothing and caps the damage if degeneration does
     happen. The real defense is --check-pace.

  5. Pace anomaly detection during the render itself (`--check-pace`), with an
     automatic retry using a different seed.

WHAT WAS TESTED AND REJECTED (do not try it again without reading this):

  * Turning the AlignmentStreamAnalyzer off to get fused attention (SDPA) back and
    eliminate 3 GPU->CPU copies per token. It looked like the biggest lever: it
    forces `_attn_implementation='eager'` on the transformer's 30 layers. Measured
    in a paired test: besides NOT being faster, the model started generating 26.7 s
    of audio where the baseline generated 14.3 s for the same text — almost double.
    The analyzer is the brake that stops degenerate generation; without it the model
    diverges into a long tail. It is expensive and it is load-bearing.

  * `output_hidden_states=False` on its own. The backend only uses
    `hidden_states[-1]`, which is `last_hidden_state` (t3_hf_backend.py:93,103), so
    it looks like pure waste — but it was not measured in isolation and the expected
    gain (tens of MB per call) is small next to the decode. Noted, not done.

Cache, DSP, manifest and resume remain identical to the original — including
DSP_VERSION, so as not to invalidate already rendered audio.

Usage:
    python3 phase2_render.py corpus/corpus_pt.json -o audio/ \
        --ref ref/REF_paginasrecolhidas.wav --campaign bonesofarnor
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import time
import unicodedata
from pathlib import Path

import glyphs

# --------------------------------------------------------------------------- #
# voice recipe — change DSP_VERSION whenever you touch the chain, otherwise the
# cache hands back old audio and you spend hours debugging a ghost
# --------------------------------------------------------------------------- #

PITCH = 0.95   # 1.0 = no change; lower = deeper (formants follow along)
TEMPO = 0.96   # lower = slower

_BODY = (
    "equalizer=f=110:t=q:w=0.9:g=3.5,"
    "equalizer=f=380:t=q:w=1.1:g=-2,"
    "equalizer=f=6500:t=q:w=1.2:g=-2.5,"
    "tremolo=f=5.2:d=0.05,"
    "aecho=0.8:0.85:35|75:0.28|0.16,"
    "alimiter=limit=0.95,"
    "loudnorm=I=-16:TP=-1.5:LRA=11"
)


def has_rubberband() -> bool:
    try:
        out = subprocess.run(["ffmpeg", "-hide_banner", "-filters"],
                             capture_output=True, text=True, timeout=20).stdout
        return " rubberband " in out
    except Exception:  # noqa: BLE001
        return False


HAS_RB = has_rubberband()
# Narration speed. 1.0 is the model's raw pace (~118 words/min), which sounds
# dragging. 1.30 gives ~137 wpm — below the commercial audiobook range (150-160),
# which is what you want in a fantasy narrator: unhurried, but not sleepy.
# Chosen by ear, comparing samples at 1.12 / 1.25 / 1.40.
#
# It goes into DSP_VERSION because it changes the audio: without that the cache
# would hand back the old version and you would spend hours chasing a ghost
# (pitfall no. 1 of the briefing).
SPEED = 1.30


def dsp_version() -> str:
    base = "mago-v1" if HAS_RB else "mago-v1f"
    return f"{base}-v{SPEED:.2f}"


def wizard_chain(sr: int) -> str:
    """Wizard chain. Uses rubberband if it exists; otherwise the asetrate trick,
    which shifts pitch and formants together — sonically equivalent to
    'formant=shifted' — followed by atempo to restore the duration."""
    if HAS_RB:
        return (f"rubberband=pitch={PITCH}:formant=shifted:tempo={TEMPO*SPEED}"
                f":pitchq=quality:transients=smooth,{_BODY}")
    atempo = (TEMPO * SPEED) / PITCH
    return (f"asetrate={int(sr * PITCH)},aresample={sr},"
            f"atempo={atempo:.5f},{_BODY}")


SENTENCE_PAUSE = 0.30    # seconds between sentences
PARAGRAPH_PAUSE = 0.45   # extra seconds between paragraphs
SEED = 1234

SENT_SPLIT = re.compile(r"(?<=[.!?…])\s+")


def normalize_for_match(s: str) -> str:
    """Same normalization Phase 3 will apply to the OCR: no accents, no punctuation.

    MIND the asymmetry with the narration: the audio SAYS "test Agility", but the
    screen SHOWS the icon, and the OCR will not read any word there. So the matching
    index is built from the text with the glyphs REMOVED, not substituted — matching
    against the spoken word would never work.
    """
    s = glyphs.PUA.sub(" ", s)
    s = unicodedata.normalize("NFKD", s)
    s = "".join(c for c in s if not unicodedata.combining(c))
    s = s.casefold()
    s = re.sub(r"[^\w\s]", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def cache_key(text: str, ref: Path, params: dict) -> str:
    """Hash of the SPOKEN text — if the glyph lexicon changes, the audio is redone."""
    h = hashlib.blake2b(digest_size=10)
    h.update(f"chatterbox-mtl|pt|{ref.name}|{dsp_version()}|{json.dumps(params, sort_keys=True)}|{text}"
             .encode("utf-8"))
    return h.hexdigest()


def split_sentences(text: str) -> list[tuple[str, bool]]:
    """Returns (sentence, is_end_of_paragraph). One TTS call per sentence —
    grouping into larger blocks was measured and is slower (see the docstring)."""
    out = []
    for paragraph in [p for p in text.split("\n") if p.strip()]:
        sents = [s.strip() for s in SENT_SPLIT.split(paragraph) if s.strip()]
        for i, s in enumerate(sents):
            out.append((s, i == len(sents) - 1))
    return out


# --------------------------------------------------------------------------- #

# the s3 speech tokenizer runs at 25 Hz; 25 tokens ≈ 1 s of audio
TOKENS_PER_SECOND = 25
WORDS_PER_SECOND = 2.31   # measured on the production render (127 wpm)


def token_budget(sentence: str, slack: float, floor: int, ceiling: int) -> int:
    """How many speech tokens this sentence ought to need, with slack.

    A FIXED ceiling is the wrong choice. Chatterbox's `generate()` hardcodes
    max_new_tokens=1000 (mtl_tts.py:297), which is 40 s of speech: when the model
    degenerates and does not emit EOS, it pays the whole 1000. But lowering the
    ceiling to a single value truncates the long sentences — measured on the corpus,
    a ceiling of 400 would put 166 sentences (0.59%) at risk of losing words, and
    the longest sentence needs ~736 tokens.

    The solution is to budget per sentence: the median (11 words) gets the floor,
    and the long tail gets what it needs. The practical effect is to limit the
    damage of degeneration exactly where it is most likely, without risking
    truncating anything.
    """
    predicted = len(sentence.split()) / WORDS_PER_SECOND * TOKENS_PER_SECOND
    return int(max(floor, min(ceiling, predicted * slack)))


def install_t3_patches(model, budget) -> None:
    """Two fixes applied to t3.inference, which is where everything goes through.

    1. Hook hygiene. t3.inference() rebuilds the AlignmentStreamAnalyzer on every
       call and registers 3 forward hooks without removing the previous ones. It
       does not speed anything up (measured), but every retained hook holds on to
       attention tensors; over thousands of blocks that becomes a memory leak.

    2. Token ceiling per sentence. `generate()` does not expose max_new_tokens, so
       the budget is imposed here, one layer below. `budget` is a one-element box
       that the synthesis loop updates before each sentence.
    """
    attn = [l.self_attn for l in model.t3.tfmr.layers]
    inner = model.t3.inference

    def patched(*a, **k):
        for m in attn:
            m._forward_hooks.clear()
        k["max_new_tokens"] = budget[0]
        return inner(*a, **k)

    model.t3.inference = patched


# --------------------------------------------------------------------------- #

def load_blocks(corpus_path: Path, campaign: str | None, include_dynamic: bool) -> dict:
    corpus = json.loads(corpus_path.read_text(encoding="utf-8"))
    out = {}
    for k, v in corpus.items():
        if not v.get("narration"):
            continue
        if campaign and v["campaign"] != campaign:
            continue
        if v.get("placeholders") and not include_dynamic:
            continue
        out[k] = v
    return out


def prepare_speech(corpus_path: Path, blocks: dict, lang: str) -> int:
    """Attaches to each block the `speech` field: the text with icons made words."""
    corpus = json.loads(corpus_path.read_text(encoding="utf-8"))
    glyph_map = glyphs.glyph_map_from_corpus(corpus)
    n = 0
    for v in blocks.values():
        # order: glyphs first (they may bring numbers in), then the numbers
        speech = glyphs.substitute(v["text"], glyph_map, lang)
        v["speech"] = glyphs.spell_out_numbers(speech, lang)
        if v["speech"] != v["text"]:
            n += 1
    return n


def estimate(blocks: dict, rtf: float) -> None:
    words = sum(v["words"] for v in blocks.values())
    audio_h = words / 140 / 60          # ~140 words/min for an unhurried narrator
    print(f"  blocks ................ {len(blocks):,}")
    print(f"  words ................. {words:,}")
    print(f"  estimated audio ....... {audio_h:.1f} h")
    print(f"  render time ........... {audio_h * rtf:.1f} h  (RTF {rtf})")
    print(f"  size in opus 48k ...... ~{audio_h * 3600 * 6 / 1024:.0f} MB")


def main() -> None:
    # `global` has to come before ANY read of SPEED in this function — the argparse
    # below uses the global as the default value, and Python rejects the later
    # declaration with SyntaxError.
    global SPEED

    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("corpus", type=Path)
    ap.add_argument("-o", "--out", type=Path,
                    default=Path(__file__).resolve().parent / "output" / "audio",
                    help="output folder (default: output/audio in the repository)")
    ap.add_argument("--ref", type=Path, default=Path(__file__).resolve().parent / "ref" / "REF_paginasrecolhidas.wav",
                    help="reference clip for cloning (10-15 s, clean)")
    ap.add_argument("--device", default="auto", choices=["auto", "mps", "cuda", "cpu"])
    ap.add_argument("--campaign", help="render only one campaign")
    ap.add_argument("--limit", type=int, help="stop after N blocks (testing)")
    ap.add_argument("--key", action="append", default=[],
                    help="render only these keys (may repeat). This is what "
                         "enables Phase 3's on-demand rendering.")
    ap.add_argument("--exaggeration", type=float, default=0.45,
                    help="0.3-0.7; lower = more restrained/narrative reading")
    ap.add_argument("--cfg-weight", type=float, default=0.35,
                    help="lower = slower, more deliberate pace")
    ap.add_argument("--token-slack", type=float, default=2.0,
                    help="multiplier over the tokens predicted for the sentence. "
                         "2.0 gives twice what is needed before cutting off")
    ap.add_argument("--tokens-floor", type=int, default=250,
                    help="minimum budget per sentence, in tokens (~10 s of speech)")
    ap.add_argument("--tokens-ceiling", type=int, default=1000,
                    help="maximum budget per sentence; 1000 is the model's default")
    ap.add_argument("--check-pace", action="store_true",
                    help="measure words/s of each block and redo the degenerate ones")
    ap.add_argument("--min-pace", type=float, default=1.45,
                    help="spoken words/s below which the block is suspect")
    ap.add_argument("--retries", type=int, default=2,
                    help="extra attempts, with another seed, for suspect blocks")
    ap.add_argument("--include-dynamic", action="store_true",
                    help="also render blocks with {0} (not recommended)")
    ap.add_argument("--speed", type=float, default=SPEED,
                    help=f"default {SPEED} (~137 words/min). 1.0 is the model's raw "
                         "pace (~118 wpm). Enters the cache: changing it re-renders.")
    ap.add_argument("--lang", default="pt",
                    help="language of the glyph lexicon (see glyphs.py)")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--rtf", type=float, default=3.4, help="RTF assumed in --dry-run")
    args = ap.parse_args()

    SPEED = args.speed

    blocks = load_blocks(args.corpus, args.campaign, args.include_dynamic)
    if args.key:
        blocks = {k: v for k, v in blocks.items() if k in args.key}
        missing = [k for k in args.key if k not in blocks]
        if missing:
            print(f"[warning] key(s) not found or without narration: {missing}")
    touched = prepare_speech(args.corpus, blocks, args.lang)
    print(f"[glyphs] {touched} of {len(blocks)} blocks had game icons in the text")
    if args.limit:
        blocks = dict(list(blocks.items())[:args.limit])

    print(f"[plan] {args.corpus}" + (f" | campaign={args.campaign}" if args.campaign else ""))
    estimate(blocks, args.rtf)
    if args.dry_run:
        return
    if not args.ref.exists():
        sys.exit(f"[error] reference not found: {args.ref}")

    import torch
    import torchaudio as ta
    from chatterbox.mtl_tts import ChatterboxMultilingualTTS

    device = args.device
    if device == "auto":
        device = ("mps" if torch.backends.mps.is_available()
                  else "cuda" if torch.cuda.is_available() else "cpu")
    print(f"[dsp] {'rubberband' if HAS_RB else 'asetrate (fallback, no rubberband)'} "
          f"| version {dsp_version()} | speed {SPEED:.2f}x")
    print(f"[model] loading on {device} ...")
    t0 = time.time()
    model = ChatterboxMultilingualTTS.from_pretrained(device=device)

    budget = [args.tokens_ceiling]      # updated before each sentence
    install_t3_patches(model, budget)

    # conditionals ONCE — not once per sentence, the way the original did it
    t_cond = time.time()
    model.prepare_conditionals(str(args.ref), exaggeration=args.exaggeration)
    print(f"[voice] conditionals prepared in {time.time()-t_cond:.1f}s (only once)")
    torch.manual_seed(SEED)
    print(f"[model] ready in {time.time()-t0:.0f}s")

    # the "pausa" key stays in Portuguese on purpose: it is hashed into cache_key,
    # so renaming it would invalidate every already rendered file
    params = {"exaggeration": args.exaggeration, "cfg_weight": args.cfg_weight,
              "pausa": [SENTENCE_PAUSE, PARAGRAPH_PAUSE], "seed": SEED}

    args.out.mkdir(parents=True, exist_ok=True)
    manifest_path = args.out / "manifest.json"
    manifest = json.loads(manifest_path.read_text()) if manifest_path.exists() else {}

    done = skipped = failed = regenerated = 0
    t_start = time.time()
    total = len(blocks)

    def synthesize(v: dict, seed: int):
        """Generates the whole block and returns (waveform, seconds_of_speech)."""
        torch.manual_seed(seed)
        chunks, speech = [], 0.0
        for sent, end_of_para in split_sentences(v["speech"]):
            budget[0] = token_budget(sent, args.token_slack,
                                     args.tokens_floor, args.tokens_ceiling)
            wav = model.generate(sent, language_id="pt",
                                 exaggeration=args.exaggeration,
                                 cfg_weight=args.cfg_weight)
            speech += wav.shape[-1] / model.sr
            chunks.append(wav)
            chunks.append(torch.zeros(1, int(model.sr * SENTENCE_PAUSE)))
            if end_of_para:
                chunks.append(torch.zeros(1, int(model.sr * PARAGRAPH_PAUSE)))
        return torch.cat(chunks, dim=-1), speech

    for i, (key, v) in enumerate(blocks.items(), 1):
        ck = cache_key(v["speech"], args.ref, params)
        rel = f"{v['campaign']}/{ck}.opus"
        dest = args.out / rel
        if dest.exists():
            skipped += 1
            manifest[key] = {**manifest.get(key, {}), "file": rel, "campaign": v["campaign"],
                             "text": v["text"], "norm": normalize_for_match(v["text"]),
                             "words": v["words"]}
            continue
        dest.parent.mkdir(parents=True, exist_ok=True)

        try:
            t1 = time.time()
            best, best_wps = None, -1.0
            for attempt in range(args.retries + 1 if args.check_pace else 1):
                wav, speech = synthesize(v, SEED + attempt * 7919)
                wps = v["words"] / max(speech, 1e-6)
                if wps > best_wps:
                    best, best_wps = wav, wps
                if not args.check_pace or wps >= args.min_pace:
                    break
                regenerated += 1
                print(f"    [pace] {key[:40]} came out at {wps:.2f} w/s "
                      f"(limit {args.min_pace}); trying another seed", flush=True)

            tmp = args.out / f".tmp_{ck}.wav"
            ta.save(str(tmp), best, model.sr)
            try:
                subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(tmp),
                                "-af", wizard_chain(model.sr),
                                "-c:a", "libopus", "-b:a", "48k", str(dest)], check=True)
            finally:
                tmp.unlink(missing_ok=True)

            manifest[key] = {"file": rel, "campaign": v["campaign"], "text": v["text"],
                             "norm": normalize_for_match(v["text"]), "words": v["words"],
                             "wps": round(best_wps, 2)}
            done += 1
            dt = time.time() - t1
            if done % 10 == 0 or i == total:
                elapsed = time.time() - t_start
                rate = done / max(elapsed, 1)
                eta = (total - i) / max(rate, 1e-6) / 3600
                manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=1),
                                         encoding="utf-8")
                print(f"  [{i}/{total}] {key[:44]:<44} {v['words']:>4}w {dt:5.0f}s "
                      f"| done {done} skipped {skipped} | ETA {eta:.1f} h", flush=True)
        except KeyboardInterrupt:
            print("\n[interrupted] the cache preserves everything — just run it again.")
            break
        except Exception as e:  # noqa: BLE001
            failed += 1
            print(f"  [failure] {key}: {type(e).__name__}: {e}", flush=True)

    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"\n[end] rendered {done} | cached {skipped} | failures {failed}"
          + (f" | pace regenerations {regenerated}" if args.check_pace else ""))
    print(f"      {manifest_path}  ({len(manifest)} entries)")


if __name__ == "__main__":
    main()
