#!/usr/bin/env python3
"""
prosody.py — reading a block as speech rather than as a paragraph.

Piper has no prosody. Its ONNX graph takes three inputs — phoneme ids, their
lengths, and a vector of three scales — and none of them is pitch. There is no
style vector and no per-phoneme duration. Read against the model, that is the
end of the matter.

But a block does not have to be one call. Split it where a reader would breathe,
give each piece its own pace and its own trailing silence, and join them. That is
this file. It buys the two things a flat read most lacks: somewhere to slow down,
and somewhere to stop.

## What is deliberately not here

Pitch. It was tried, measured and rejected by ear in the same session that built
this. The only way to move pitch with the ffmpeg this project can require is to
resample — `asetrate` then `aresample` — which moves the formants along with the
frequency. Formants are how an ear estimates the size of a vocal tract, so a
clause dropped 1.6 semitones this way is not the same person speaking lower; it
is a larger person. Across a clause boundary it reads as somebody else taking
over, which is exactly how it was reported: "parece outra pessoa falando".

`rubberband` moves pitch and leaves formants alone, and would fix it. This
project already records that Homebrew's ffmpeg does not have it, and the Gyan
build `install.ps1` fetches on Windows does not either. It is not a dependency
this can require, so pitch stays out. Pace and silence never touch the spectrum,
so they cannot change who is speaking.

## The rule, and how much it is worth

Prose leans slower where the words are dark and a little quicker where they are
not; a sentence closes slower than it opens; the mechanical instruction at the
end of a block is read a touch quicker and flatter, because it is information
rather than story.

Measured over eight real blocks against the single-call read: silence 15.8% ->
16.8%, median pause 200 ms -> 240 ms, total length 132.8 s -> 133.8 s. That is a
small change and it is presented as one. It was kept because it was preferred by
ear over both the flat read and the pitched version, which is the only test that
has ever settled anything about this voice.
"""
from __future__ import annotations

import re
import wave

# Where a clause is long enough to deserve its own breath.
LONG = 90

# The pace the owner settled on by ear, and the band around it. Anything outside
# this is a different decision, not a shade of this one.
MIN_SCALE, MAX_SCALE = 1.20, 1.50

DARK = re.compile(r"\b(escurid|sombra|medo|terror|morte|morto|sangue|gritos?|"
                  r"uivo|fedor|podre|ru[ií]na|amea|inimig|orc|goblin|troll|"
                  r"perigo|ferid|dor|frio|silenci|vazio|dark|shadow|fear|death|"
                  r"blood|scream|rot|ruin|threat|enemy|danger|wound|cold|empty)",
                  re.I)
LIGHT = re.compile(r"\b(luz|sol|esperan|al[íi]vio|aliviad|calor|amig|salv|"
                   r"vit[óo]ria|descans|seguro|canta|riso|belo|bela|light|sun|"
                   r"hope|relief|warm|friend|save|victory|rest|safe|song)", re.I)


def clauses(text: str) -> list[str]:
    """Break a paragraph where a reader would breathe.

    Sentences first, then long sentences at their own punctuation. Never below a
    clause: splitting inside a phrase puts a pause where speech has none, and
    every seam costs one.
    """
    out: list[str] = []
    for sentence in re.split(r"(?<=[.!?…])\s+", text.strip()):
        if not sentence.strip():
            continue
        if len(sentence) <= LONG:
            out.append(sentence.strip())
            continue
        buf = ""
        for bit in re.split(r"(?<=[,;:])\s+", sentence):
            if buf and len(buf) + len(bit) > LONG:
                out.append(buf.strip())
                buf = bit
            else:
                buf = f"{buf} {bit}".strip()
        if buf.strip():
            out.append(buf.strip())

    # Never hand back a fragment with nothing to say. Splitting after sentence
    # punctuation cuts `"... um ladrão roubou seu rolo de massa!"` into `"...`
    # and the rest, and the first piece has no letters in it — Piper synthesises
    # silence, an empty buffer reaches `wave`, and the whole block fails with
    # "# channels not specified". Three blocks in the corpus start this way, and
    # all three failed on the first Windows render.
    #
    # The ellipsis belongs to the sentence it opens, so it is glued to the front
    # of the next piece rather than dropped.
    merged: list[str] = []
    for part in out:
        if any(c.isalnum() for c in part):
            merged.append(part)
        elif merged:
            merged[-1] = f"{merged[-1]} {part}"
        else:
            merged.append(part)          # nothing to attach it to yet
    while len(merged) > 1 and not any(c.isalnum() for c in merged[0]):
        merged[1] = f"{merged[0]} {merged[1]}"
        merged.pop(0)
    return merged


def plan(text: str, base: float) -> list[tuple[str, float, float]]:
    """(clause, length_scale, trailing pause) for a whole block.

    The last paragraph of a multi-paragraph block is read as the instruction it
    almost always is — this game separates story from rule with a blank line, and
    most narration blocks have exactly that shape.
    """
    paras = [p.strip() for p in text.split("\n\n") if p.strip()]
    if not paras:
        return []
    out: list[tuple[str, float, float]] = []
    for pi, para in enumerate(paras):
        rule = len(paras) > 1 and pi == len(paras) - 1
        cl = clauses(para)
        for i, c in enumerate(cl):
            last = i == len(cl) - 1
            if rule:
                scale, pause = base * 0.96, 0.22
            else:
                if DARK.search(c):
                    scale = base * 1.08
                elif LIGHT.search(c):
                    scale = base * 0.97
                else:
                    scale = base
                if last:
                    scale *= 1.05           # the close is not a stop
                pause = 0.40 if c[-1:] in ".!?…" else 0.22
            if last and pi == len(paras) - 1:
                pause = 0.0                 # the block ends; the player decides
            elif last:
                pause = 0.55                # between story and rule, a beat
            out.append((c, min(MAX_SCALE, max(MIN_SCALE, scale)), pause))
    return out


def _trim(frames: bytes, width: int, rate: int, thresh: int = 260) -> bytes:
    """Cut Piper's padding so the seams are the pauses chosen here.

    Every call pads roughly 120 ms of silence at each end. Left in, each seam
    becomes silence against silence and the pauses above are additions to a gap
    that is already there.
    """
    import numpy as np

    a = np.frombuffer(frames, dtype=np.int16)
    loud = np.flatnonzero(np.abs(a) > thresh)
    if loud.size:
        a = a[max(0, loud[0] - rate // 200):loud[-1] + rate // 200]
    return a.tobytes()


def synthesize(voice, text: str, base: float, path, config) -> None:
    """Write the block to `path` as a wav, read clause by clause.

    `config` is the SynthesisConfig the renderer already built: everything but
    the pace is taken from it, so the noise settings stay wherever they were set.
    """
    import copy
    import io

    import numpy as np

    pieces = plan(text, base)
    if not pieces:
        pieces = [(text, base, 0.0)]

    chunks: list[np.ndarray] = []
    params = None
    for clause, scale, pause in pieces:
        cfg = copy.copy(config)
        cfg.length_scale = scale
        # A clause that produced nothing costs itself, not the block. The
        # splitter no longer makes silent fragments, but a voice can decline any
        # particular string and losing a whole page of prose to one of them is
        # not a trade worth making.
        #
        # The guard has to be around the *write*. When Piper emits no audio it
        # never sets the wav parameters, and it is closing the file that raises
        # — "# channels not specified", from the context manager's exit, not from
        # anything this file reads.
        buf = io.BytesIO()
        try:
            with wave.open(buf, "wb") as fh:
                voice.synthesize_wav(clause, fh, syn_config=cfg)
        except (wave.Error, EOFError):
            continue
        buf.seek(0)
        try:
            with wave.open(buf, "rb") as fh:
                params = fh.getparams()
                raw = _trim(fh.readframes(fh.getnframes()),
                            fh.getsampwidth(), fh.getframerate())
        except (wave.Error, EOFError):
            continue
        chunks.append(np.frombuffer(raw, dtype=np.int16))
        if pause:
            chunks.append(np.zeros(int(params.framerate * pause), dtype=np.int16))

    if params is None:
        # Not one clause spoke. Try the whole string in one go, in case the
        # splitting was what confused the voice; if that is silent too there is
        # genuinely nothing to say, and it is worth saying which block rather
        # than letting `wave` report "# channels not specified" from three frames
        # down. No block in either corpus is like this — the check is for the
        # next corpus, not this one.
        buf = io.BytesIO()
        try:
            with wave.open(buf, "wb") as fh:
                voice.synthesize_wav(text, fh, syn_config=config)
            buf.seek(0)
            with wave.open(buf, "rb") as fh:
                params, frames = fh.getparams(), fh.readframes(fh.getnframes())
        except (wave.Error, EOFError):
            raise ValueError(
                f"nothing to speak in {text[:60]!r}: the voice produced no "
                f"audio for it, clause by clause or whole") from None
        with wave.open(str(path), "wb") as fh:
            fh.setparams(params)
            fh.writeframes(frames)
        return

    with wave.open(str(path), "wb") as fh:
        fh.setparams(params)
        fh.writeframes(np.concatenate(chunks).tobytes())
