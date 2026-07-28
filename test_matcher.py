#!/usr/bin/env python3
"""
test_matcher.py — measures the matcher's accuracy on real screens and OCR noise.

## Where the ground truth comes from

From the game itself. `LogA.txt` records the exact key of every block that was
displayed, along with its parameters. Rebuilding `template + parameters` yields
**the text that was on the screen**, with the correct key next to it — without
transcribing anything by hand.

For composite screens the truth is a LIST of keys, in paragraph order. A real
example:

    log     [3|1|PLACE_PERSON|1|8|0|A2_M1_T1_PLACE|0]
    screen  paragraph 1 = text of A2_M1_T1_PLACE   (the prose)
            paragraph 2 = "Place a person token as indicated."
    truth   [A2_M1_T1_PLACE, PLACE_PERSON]

## The noise

OCR fails in specific ways, and uniform random noise does not represent that.
The confusions below are the classic OCR ones for light serif text on a dark
background, which is exactly the JiME case. Accents and punctuation are left out
because normalization already strips them from both sides.

    python3 test_matcher.py                 # runs the full battery
    python3 test_matcher.py --verbose       # shows each error
"""
from __future__ import annotations

import argparse
import json
import os
import collections
import random
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

import console  # noqa: E402

console.setup()
import glyphs  # noqa: E402
from matcher import Matcher, load_corpus, normalize, paragraphs  # noqa: E402

CORPUS = Path(__file__).resolve().parent / "corpus" / "corpus_pt.json"
LOGS = console.saves_dir()
LINE_RE = re.compile(r"^\[([^|]*)\|([^|]*)\|([^|\]]+)((?:\|[^\]]*)*)\]$")

# OCR confusions observed in serif text: visually close pairs
CONFUSIONS = {
    "m": "rn", "rn": "m", "l": "i", "i": "l", "c": "e", "e": "c",
    "o": "0", "0": "o", "a": "o", "s": "5", "u": "v", "v": "u",
    "d": "cl", "h": "b", "b": "h", "t": "f", "f": "t", "g": "q", "q": "g",
}


def degrade(text: str, rate: float, rnd: random.Random) -> str:
    """Applies OCR noise: visual substitutions, drops and word joins."""
    if rate <= 0:
        return text
    out = []
    for ch in text:
        r = rnd.random()
        if r < rate * 0.6 and ch.lower() in CONFUSIONS:
            out.append(CONFUSIONS[ch.lower()])
        elif r < rate * 0.85:
            continue                       # dropped character
        elif r < rate:
            out.append(ch + ch)            # duplicated character
        else:
            out.append(ch)
    s = "".join(out)
    # word join: OCR sometimes eats the space
    if rnd.random() < rate * 4:
        s = re.sub(r" ", "", s, count=1)
    return s


def parse_params(rest: str) -> list[tuple[str, str]]:
    fields = [c for c in rest.split("|") if c != ""]
    if not fields or not fields[0].isdigit():
        return []
    n = int(fields[0])
    body = fields[1:]
    if len(body) < 4 * n:
        return []
    return [(body[i * 4], body[i * 4 + 2]) for i in range(n)]


def build_fixtures(corpus: dict) -> list[dict]:
    """Rebuilds the screens from the logs: (text_on_screen, expected_keys)."""
    idx = {}
    for k, v in corpus.items():
        idx.setdefault(k.split(":", 1)[1], (k, v))

    fixtures, seen = [], set()
    for log in sorted(LOGS.glob("*/Log*.txt")):
        for line in log.read_text(encoding="utf-8", errors="replace").splitlines():
            m = LINE_RE.match(line.strip())
            if not m:
                continue
            _adv, _rd, key, rest = m.groups()
            kv = idx.get(key)
            if not kv:
                continue
            full_key, v = kv
            if not v.get("narration"):
                continue

            text = v["text"]
            expected: list[str] = []
            # resolve the parameters the way the game does
            for kind, value in parse_params(rest):
                ref = idx.get(value)
                if kind == "8" and ref:
                    text = text.replace("{0}", ref[1]["text"], 1)
                    if ref[1].get("narration"):
                        expected.append(ref[0])
                else:
                    text = re.sub(r"\{\d\}", value, text, count=1)

            if not expected:
                expected = [full_key]
            else:
                expected.append(full_key)   # the template comes after the prose

            signature = normalize(text)
            if len(signature) < 20 or signature in seen:
                continue
            seen.add(signature)
            pre = re.match(r"^([AB]\d+)_", key)
            fixtures.append({"screen": text, "expected": expected,
                             "log_key": full_key, "adventure": _adv,
                             "prefix": pre.group(1) if pre else None,
                             "composite": len(expected) > 1})
    return fixtures


def evaluate(m: Matcher, fixtures: list[dict], rate: float, seed: int,
             verbose: bool) -> dict:
    rnd = random.Random(seed)
    total = hits = accepted = wrong = refusals = 0
    errors = []
    # build every chunk at once so they can be matched in parallel
    chunks, mapping = [], []
    for fi, f in enumerate(fixtures):
        dirty = degrade(f["screen"], rate, rnd)
        for pi, para in enumerate(paragraphs(dirty)):
            chunks.append(para)
            mapping.append((fi, pi))
    all_results = m.match_batch(chunks)
    by_fixture: dict[int, list] = {}
    for (fi, _pi), res in zip(mapping, all_results):
        by_fixture.setdefault(fi, []).append(res)

    for fi, f in enumerate(fixtures):
        results = by_fixture.get(fi, [])
        # PER-SCREEN METRIC, not per paragraph. That is what matters for
        # playback: did the screen get its PROSE block identified? Counting each
        # paragraph separately punishes the matcher for matching "Place a search
        # token as indicated" with another block that carries the same
        # instruction — which is inevitable and irrelevant, because the one that
        # gets narrated is the prose block.
        primary = f["expected"][0]
        norm_ok = {normalize(m.corpus[k]["text"]) for k in f["expected"]
                   if k in m.corpus}
        accepted_keys = [r.key for r in results if r.accepted]
        total += 1
        if not accepted_keys:
            refusals += 1
            continue
        accepted += 1
        hit = primary in accepted_keys
        if not hit:
            # duplicate blocks in the corpus produce the same audio: not an error
            hit = any(k in m.corpus and normalize(m.corpus[k]["text"]) in norm_ok
                      for k in accepted_keys)
        if hit:
            hits += 1
        else:
            wrong += 1
            if verbose and len(errors) < 6:
                errors.append((primary, results[0]))

    reasons = collections.Counter()
    for res in all_results:
        if not res.accepted:
            reasons[res.reason.split(" ")[0] + " " + res.reason.split(" ")[1]
                    if len(res.reason.split(" ")) > 1 else res.reason] += 1
    return {"rate": rate, "total": total, "hits": hits, "accepted": accepted,
            "wrong": wrong, "refusals": refusals, "errors": errors,
            "reasons": reasons}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--verbose", action="store_true")
    ap.add_argument("--corpus", type=Path, default=CORPUS)
    args = ap.parse_args()

    corpus = load_corpus(args.corpus)
    fixtures = build_fixtures(corpus)
    composite = sum(1 for f in fixtures if f["composite"])
    print(f"[fixtures] {len(fixtures)} screens rebuilt from the game logs "
          f"({composite} composite of 2+ keys)\n")

    scopes = [
        ("whole corpus", Matcher(corpus)),
        ("campaign bonesofarnor+main", Matcher(corpus, campaign="bonesofarnor")),
        ("campaign + adventure A2", Matcher(corpus, campaign="bonesofarnor",
                                            adventure_prefix="A2")),
    ]
    for name, m in scopes:
        print(f"  scope {name:<30} {len(m):>6,} candidates")

    # correct scope: each fixture against the set from ITS OWN adventure
    print("\n[per-adventure scope] each screen matched against its prefix + generics")
    by_prefix = collections.defaultdict(list)
    for f in fixtures:
        by_prefix[f["prefix"]].append(f)
    for rate in (0.0, 0.05):
        tot = hi = wr = rf = 0
        for pre, fs in by_prefix.items():
            if pre is None:
                mm = scopes[1][1]           # generic ones: campaign scope
            else:
                mm = Matcher(corpus, campaign="bonesofarnor", adventure_prefix=pre)
            r = evaluate(mm, fs, rate, seed=1234, verbose=False)
            tot += r["total"]; hi += r["hits"]; wr += r["wrong"]; rf += r["refusals"]
        tot = max(tot, 1)
        print(f"  {'by adventure (correct)':<28} {rate*100:>5.0f}% "
              f"{100*hi/tot:>7.1f}% {'':>8} {100*wr/tot:>5.1f}% {100*rf/tot:>6.1f}%")

    print(f"\n{'scope':<28} {'noise':>6} {'hit':>8} {'accept':>8} "
          f"{'WRONG':>6} {'refuse':>7}")
    print("  " + "-" * 72)
    for name, m in scopes:
        for rate in (0.0, 0.02, 0.05, 0.10):
            print(f"    ... {name} @ {rate*100:.0f}%", end="\r", flush=True)
            r = evaluate(m, fixtures, rate, seed=1234, verbose=args.verbose)
            t = max(r["total"], 1)
            print(f"  {name:<28} {rate*100:>5.0f}% "
                  f"{100*r['hits']/t:>7.1f}% {100*r['accepted']/t:>7.1f}% "
                  f"{100*r['wrong']/t:>5.1f}% {100*r['refusals']/t:>6.1f}%")
            if args.verbose and r["errors"]:
                for expected_key, res in r["errors"]:
                    print(f"      EXPECTED {expected_key}")
                    print(f"      GOT      {res.key} (score {res.score:.0f}, "
                          f"margin {res.margin:.0f}, ratio {res.length_ratio:.2f})")
        print()

    r = evaluate(scopes[1][1], fixtures, 0.05, seed=1234, verbose=False)
    print("refusal reasons (campaign scope, 5% noise):")
    for reason, n in r["reasons"].most_common(6):
        print(f"  {n:>5}  {reason}")
    print()
    print("How to read it: 'WRONG' is what matters — narrating the wrong block is")
    print("worse than staying quiet, because the player acts on what they hear.")
    print("'refuse' is the safe silence, which live TTS can cover.")


if __name__ == "__main__":
    main()
