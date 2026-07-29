#!/usr/bin/env python3
"""
matcher.py — matches the text read off the screen (OCR) with the right corpus block.

## The problem, as it really is

The JiME screen does **not** show one corpus block. It shows several composed
together: the game takes a template and injects other localization keys into it as
parameters. A real example, captured from the game log:

    corpus  PLACE_PERSON     = "{0}\\n\\nPlace a person token as indicated."
    corpus  A2_M1_T1_PLACE   = "You see the spark of a small campfire and a woman
                                dressed in the garb of the Wardens of the North. (...)"
    screen  = A2_M1_T1_PLACE + "\\n\\n" + "Place a person token as indicated."

Matching the whole screen against an isolated block fails in exactly these cases —
and they are not rare. That is why the matcher works at two levels:

  1. **per paragraph** — each paragraph of the screen is matched separately. This
     is the mode that respects composition, and it is the one that feeds playback:
     the prose paragraph's audio is played, and optionally the instruction's.
  2. **whole screen** — as a check, and for single-paragraph screens.

## Scope

The save (`SavedGame*`, plain JSON) tells us `CampaignId` and `CurrentAdventureId`.
That narrows the candidates down, but less than it looks: measured on the corpus,
adventure 3 of Bones of Arnor has 44 story keys (`A2_*`) and ~2,358 generic keys
(`UI_*`, `PLACE_*`, `ENEMY_*`, `TERRAIN_*`...) that can show up in any adventure.
From 9,740 to ~2,402 — a 4x reduction, not a 100x one.

Scope helps, but what really disambiguates is per-paragraph matching plus the
guards.

## Guards (worth more than the threshold)

- **length ratio** — without it, a 10-char fragment scores 100 against a 200-char
  paragraph via `partial_ratio`, and narrates the wrong block.
- **margin over the runner-up** — if the top two tie, it is better not to narrate
  than to narrate the wrong thing.

## Normalization

Both sides go through the same function: no accents, no punctuation, lowercase, and
**without the game font's glyphs** (U+E000–U+F8FF). This is essential: 25.9% of the
blocks contain icons that OCR does not read as text at all. See `glyphs.py`.
"""
from __future__ import annotations

import json
import re
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path

try:
    import numpy as np
    from rapidfuzz import fuzz
    from rapidfuzz.process import cdist
except ImportError:  # noqa: BLE001
    import sys as _sys
    raise SystemExit(
        f"[error] rapidfuzz is not in this interpreter ({_sys.executable}).\n"
        f"        The project's dependencies live in the venv. Run it like this:\n\n"
        f"          ~/jime-venv/bin/python {' '.join(_sys.argv) or 'demo.py ...'}\n\n"
        f"        (or install it here:  {_sys.executable} -m pip install rapidfuzz)")

import glyphs

# Careful: since RapidFuzz 3.0 nothing is pre-processed by default (unlike
# fuzzywuzzy). The normalization below is mandatory on both sides.

STORY_PREFIX = re.compile(r"^([AB]\d+)_")
_DIGITS = re.compile(r"\d+")
PARAGRAPH = re.compile(r"\n\s*\n|\n")


def normalize(s: str) -> str:
    """Same normalization on both sides: corpus and OCR."""
    s = glyphs.PUA.sub(" ", s)
    s = re.sub(r"\{\d+\}", " ", s)          # placeholders do not show on screen
    s = unicodedata.normalize("NFKD", s)
    s = "".join(c for c in s if not unicodedata.combining(c))
    s = s.casefold()
    s = re.sub(r"[^\w\s]", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def paragraphs(text: str) -> list[str]:
    """Splits the screen into paragraphs. Each tends to be one corpus key."""
    return [p.strip() for p in PARAGRAPH.split(text) if p.strip()]


@dataclass
class Result:
    key: str | None
    score: float
    margin: float
    length_ratio: float
    accepted: bool
    reason: str
    text: str = ""
    runner_up: str | None = None


@dataclass
class Matcher:
    """Matching index, optionally scoped by campaign and adventure."""

    corpus: dict
    campaign: str | None = None
    adventure_prefix: str | None = None
    threshold: float = 82.0
    safe_threshold: float = 92.0
    min_length_ratio: float = 0.75
    min_margin: float = 5.0
    # Minimum gap over the runner-up key, applied even above `safe_threshold`.
    # Guards against generic phrases that score 100 against many blocks at once.
    min_tie_margin: float = 1.0
    # The tie guard only applies below this length. Measured by sweeping it: at 40
    # the harness is unchanged (98.2% hit, 1.0% wrong) while the real-world false
    # positive disappears; at 60 the hit rate already drops to 96.8%. A short
    # paragraph that ties is a generic instruction that identifies nothing.
    #
    # A long one that ties is a different case, and applying the guard to it
    # costs more than it saves: measured, hit falls 99.2% -> 92.1% to take wrong
    # from 0.5% to zero — 45 screens silenced for every 3 spoken wrong. So a long
    # tie is still accepted here, and `narrator.matched_paragraph` speaks only
    # the paragraph that tied, which is the part both candidates agree on. The
    # guess is confined to a key; it never reaches what the player hears.
    tie_guard_chars: int = 40
    _keys: list[str] = field(default_factory=list, init=False)
    _norms: list[str] = field(default_factory=list, init=False)
    _is_fragment: list[bool] = field(default_factory=list, init=False)
    _longest: int = field(default=0, init=False)

    def __post_init__(self) -> None:
        for k, v in self.corpus.items():
            if not v.get("narration"):
                continue
            camp, key = k.split(":", 1)
            if self.campaign and camp not in (self.campaign, "main"):
                continue
            if self.adventure_prefix:
                m = STORY_PREFIX.match(key)
                # accepts the current adventure's keys + all the generic ones
                if m and m.group(1) != self.adventure_prefix:
                    continue
            # Index the whole block AND each of its paragraphs.
            #
            # Without this, the length-ratio guard rejects the correct match
            # whenever the screen shows ONE paragraph of a block that has
            # several: 150 chars against 300 gives a ratio of 0.50 and trips the
            # guard. Measured: 471 of the 536 refusals came from that. Each
            # paragraph points back to the block's key, so the audio played is
            # still the block's.
            parts = [v["text"]]
            ps = paragraphs(v["text"])
            if len(ps) > 1:
                parts += ps
            for i, part in enumerate(parts):
                n = normalize(part)
                if len(n) < 8:      # too short to match safely
                    continue
                self._keys.append(k)
                self._norms.append(n)
                self._is_fragment.append(i > 0)   # 0 = whole block

        self._longest = max((len(n) for n in self._norms), default=0)

    def __len__(self) -> int:
        return len(self._keys)

    def _too_long(self, target: str) -> bool:
        """Is this target so long that the length guard must refuse it anyway?

        `min_length_ratio` compares the shorter against the longer, so against a
        target longer than every candidate the best achievable ratio is
        `longest / len(target)`. Once that falls under the floor, no candidate
        can pass and the whole comparison is a foregone conclusion.

        Worth checking because the comparison is not cheap. `partial_ratio` costs
        the product of the two lengths, so a screenful of prose that is not the
        game — a browser, a chat window, this project's own terminal — is both
        the most expensive thing to score and the most certainly refused.
        Measured: 2,512 ms for a 5,148-character target against 7,314
        candidates, to arrive at "length ratio 0.18 < 0.75".
        """
        return (bool(self._longest)
                and len(target) * self.min_length_ratio > self._longest)

    def match_text(self, ocr_text: str) -> Result:
        """Matches an excerpt already read off the screen against the scope."""
        target = normalize(ocr_text)
        if len(target) < 8:
            return Result(None, 0, 0, 0, False, "excerpt too short")
        if self._too_long(target):
            return Result(None, 0, 0, 0, False, "longer than any block")

        # Every candidate is scored, not the top 20.
        #
        # `partial_ratio` gives 100 to any block that merely CONTAINS the screen
        # text, so a short instruction ties with every long block quoting it —
        # measured at 42 for "discard the exploration token". Taking 20 of those
        # 42 is an arbitrary cut, and the tie-break that exists precisely to
        # prefer the exact-length block never saw it: the correct key was absent
        # from the list, and the block that won was refused for a length ratio
        # of 0.37. The screen stayed silent.
        #
        # Scoring the whole index costs 21 ms against 12.7 for the truncated
        # search, on a per-screen budget where the OCR alone spends 150.
        #
        # The index goes FIRST and the target second. See `match_batch`: rapidfuzz
        # splits its workers across the rows, so a single target is a single row
        # and fifteen cores have nothing to divide. Transposed, the 7,314
        # candidates are the rows.
        row = cdist(self._norms, [target], scorer=fuzz.partial_ratio,
                    dtype=np.uint8, workers=-1)[:, 0]
        cands = self._candidates(row)
        if not cands:
            return Result(None, 0, 0, 0, False, "no candidate above the cutoff")
        return self._choose(target, cands)

    def _candidates(self, row) -> list[tuple[float, int]]:
        """Everything tied at the best score, plus enough below it for a margin.

        The tie-break needs all of the joint winners or it cannot pick among
        them. The margin only needs the best scorer from another key, so a
        handful of runners-up is enough.
        """
        best = int(row.max())
        if best < self.threshold - 12:
            return []
        top = [(float(best), int(j)) for j in np.flatnonzero(row == best)]
        rest = row.copy()
        rest[row == best] = 0
        k = min(20, len(rest))
        if k:
            near = np.argpartition(rest, -k)[-k:]
            top += [(float(rest[j]), int(j)) for j in near if rest[j] > 0]
        return top

    def match_batch(self, excerpts: list[str]) -> list[Result]:
        """Matches many excerpts at once, using every core.

        `process.extract` is serial and gets expensive when evaluating a whole
        harness (hundreds of screens x thousands of candidates). `cdist` computes
        the full matrix in parallel; the scores fit in uint8 because they range
        from 0 to 100. The result is identical to calling `match_text` in a loop.

        ## The index is the first argument, and that is the whole optimisation

        rapidfuzz divides `workers` across the **rows** of the matrix it is
        building. Written the obvious way — targets first, index second — a live
        screen is one to three rows, so fifteen cores have one to three pieces of
        work to share and the call is effectively serial. Measured on this
        machine, 15 workers took 11.92 s where 2 took 11.84 and 1 took 12.99:
        no parallelism at all, and the comment here used to claim "every core".
        It was true of the harness, which passes ~1,300 paragraphs at once, and
        false of the narrator, which passes one screen.

        Transposed, the 7,314 candidates are the rows. Same comparisons, same
        numbers, arranged so the workers have something to divide. Measured over
        the 653 real screens, one call each, as the narrator does it:

            median    67.9 ms  ->   8.5 ms
            p99      573.5 ms  ->  78.2 ms
            maximum  817.9 ms  ->  91.4 ms

        This is safe only because `partial_ratio` is symmetric — it decides which
        string is the window and which is the haystack by length, not by
        position. Verified rather than assumed: 658,260 real pairs scored both
        ways, zero differences. If a future rapidfuzz breaks that symmetry, the
        scores move and every guard downstream moves with them.
        """
        targets = [normalize(t) for t in excerpts]
        out: list[Result] = [
            Result(None, 0, 0, 0, False, "excerpt too short")
            if len(a) < 8 else
            Result(None, 0, 0, 0, False, "longer than any block")
            for a in targets]
        valid = [i for i, a in enumerate(targets)
                 if len(a) >= 8 and not self._too_long(a)]
        if not valid:
            return out

        # `.copy()` after the transpose: `_candidates` slices a row and hands it
        # to `argpartition`, and a strided view of a column is the slow way to do
        # that. The copy is 7,314 bytes per target.
        m = cdist(self._norms, [targets[i] for i in valid],
                  scorer=fuzz.partial_ratio, dtype=np.uint8, workers=-1).T.copy()
        for row_idx, i in enumerate(valid):
            cands = self._candidates(m[row_idx])
            out[i] = (self._choose(targets[i], cands) if cands else
                      Result(None, 0, 0, 0, False, "no candidate above the cutoff"))
        return out

    def _choose(self, target: str, cands: list[tuple[float, int]]) -> Result:
        """Picks among the top candidates and computes the margin per KEY.

        Two subtleties that only showed up in the first test with real OCR:

        1. **Tie-break by length ratio.** A block and one of its paragraphs both
           score 100 on `partial_ratio`; if the tie-break is arbitrary and lands
           on the whole block, the ratio comes out at 0.64 and the guard refuses
           a perfect hit. Between equal scores, the better ratio wins.
        2. **The margin is between distinct KEYS, not between entries.** The
           block and its paragraphs are the same key; measuring the margin
           between them would give 0 and fail every good match.
        """
        def ratio_of(j: int) -> float:
            t = self._norms[j]
            return min(len(target), len(t)) / max(len(target), len(t))

        # discard early anything with a conflicting number: otherwise a wrong
        # candidate with a high score steals the slot from a right one scoring
        # slightly lower
        clean = [(sc, j) for sc, j in cands
                 if not self._numbers_conflict(target, self._norms[j])]
        cands = clean or cands

        best_score = max(sc for sc, _ in cands)
        tied = [j for sc, j in cands if sc == best_score]
        j1 = max(tied, key=ratio_of)
        key = self._keys[j1]

        # best score among candidates from ANOTHER key
        others = [(sc, j) for sc, j in cands if self._keys[j] != key]
        s2, j2 = max(others, default=(0.0, j1))
        return self._decide(target, best_score, s2, j1, j2)

    @staticmethod
    def _numbers_conflict(target: str, cand: str) -> bool:
        """Do the candidate's numbers contradict the ones on screen?

        Guard discovered with real screens: the block `A11_SECTION_0` contains
        "Place tile 205B as indicated", and the screen was showing 208B. One
        character of difference gives partial_ratio 97.3 and ratio 1.00 — it
        passes every other guard and narrates the wrong block.

        Numbers are semantically decisive here: they identify the map tile, the
        amount of damage, the difficulty of the test. Getting the number wrong is
        worse than staying silent, because the player acts on it.

        The rule is asymmetric on purpose: it only blocks when the CANDIDATE has
        literal digits. The game's templates carry `{0}`, which normalization
        strips, and they need to keep matching the screen that shows the value.
        """
        n_cand = set(_DIGITS.findall(cand))
        if not n_cand:
            return False
        n_target = set(_DIGITS.findall(target))
        if not n_target:
            return False
        return n_cand != n_target

    def _decide(self, target: str, s1: float, s2: float, j1: int, j2: int) -> Result:
        """Applies threshold and guards. Shared by `match_text` and `match_batch`."""
        margin = s1 - s2
        best_txt = self._norms[j1]
        ratio = min(len(target), len(best_txt)) / max(len(target), len(best_txt))
        key, runner_up = self._keys[j1], self._keys[j2]
        if self._numbers_conflict(target, best_txt):
            return Result(key, s1, margin, ratio, False,
                          "numbers do not match those on screen", best_txt, runner_up)
        # A fragment (a loose paragraph of a block) matches more easily and gets it
        # wrong more often: indexing them raised the hit rate from 80% to 86%, but
        # doubled the error rate from 0.4% to 1.0%. Requiring the safe threshold of
        # them recovers the precision without losing the coverage gain.
        if self._is_fragment[j1] and s1 < self.safe_threshold:
            return Result(key, s1, margin, ratio, False,
                          f"fragment with score {s1:.0f} < {self.safe_threshold}",
                          best_txt, runner_up)
        if ratio < self.min_length_ratio:
            return Result(key, s1, margin, ratio, False,
                          f"length ratio {ratio:.2f} < {self.min_length_ratio}",
                          best_txt, runner_up)
        # A tie is a tie, however high the score. `partial_ratio` gives 100 to a
        # short generic phrase against every block that contains it — "Ganhe 1
        # inspiração." appears in dozens — so a perfect score with zero margin
        # means the text does not identify a block at all. Caught on a real frame
        # where that phrase was accepted as A1_M1_E3_PASS with score 100 and
        # margin 0, which would have narrated an unrelated scene out loud.
        if margin < self.min_tie_margin and len(target) < self.tie_guard_chars:
            return Result(key, s1, margin, ratio, False,
                          f"short text tying with another key (margin {margin:.0f})",
                          best_txt, runner_up)
        if s1 >= self.safe_threshold:
            return Result(key, s1, margin, ratio, True,
                          "above the safe threshold", best_txt, runner_up)
        if s1 >= self.threshold and margin >= self.min_margin:
            return Result(key, s1, margin, ratio, True,
                          "above the threshold, with margin", best_txt, runner_up)
        if s1 < self.threshold:
            return Result(key, s1, margin, ratio, False,
                          f"score {s1:.0f} < {self.threshold}", best_txt, runner_up)
        return Result(key, s1, margin, ratio, False,
                      f"margin {margin:.0f} < {self.min_margin}", best_txt, runner_up)

    def match_screen(self, ocr_text: str) -> list[Result]:
        """Matches a whole screen, paragraph by paragraph.

        This is the mode that respects the game's composition: the prose usually
        comes from one key and the instruction from another. Returns one result
        per paragraph, in order — which is also the order in which the audio
        should play.

        Through `match_batch`, which scores every paragraph against the index in
        one pass instead of one pass each. The results are identical; the saving
        is only the per-call overhead, about 7% on a four-paragraph screen here,
        and it is worth having on a machine where the matcher is not the thing
        with spare cycles.
        """
        return self.match_batch(paragraphs(ocr_text))


def scope_from_save(save_path: Path) -> tuple[str | None, int | None]:
    """Reads the current campaign and adventure from the game save (plain JSON)."""
    j = json.loads(Path(save_path).read_text(encoding="utf-8"))
    return j.get("CampaignId"), j.get("CurrentAdventureId")


def load_corpus(path: Path) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))
