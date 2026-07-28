#!/usr/bin/env python3
"""
jime_corpus.py — Phase 1 of the JiME Narrator (final version, post-discovery).

The app keeps the localization in Unity AssetBundles, one per campaign and
language, mapped in StreamingAssets/bundles/manifest.dat (plain JSON). Inside
each bundle there is a single TextAsset in CSV form: "KEY,<Language>".

This script:
  1. reads manifest.dat
  2. selects the bundles of the chosen language (default: pt)
  3. extracts the CSV from each one with UnityPy
  4. cleans the game markup ([i], [b], <sprite=...>, etc.)
  5. generates corpus.json + one .csv per campaign + statistics

Usage:
  python3 jime_corpus.py <bundles_dir> -o corpus/ [--lang pt] [--keep-markup]

Dependency: pip install UnityPy
"""
from __future__ import annotations

import argparse
import csv
import io
import json
import re
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import console  # noqa: E402

console.setup()

MARKUP_RE = re.compile(r"\[/?[a-zA-Z][^\]]{0,30}\]")          # [i] [/i] [b] [color=x]
RICHTEXT_RE = re.compile(r"</?[a-zA-Z][^>]{0,60}>")            # <sprite=...> <color> TMP
PLACEHOLDER_RE = re.compile(r"\{[0-9A-Za-z_]{1,30}\}")         # {0} {HERO_NAME}
WS_RE = re.compile(r"[ \t]+")

# keys that are clearly not narration read out loud
# Key fragments that mark a block as interface rather than narration.
#
# `_OPTION` used to be on this list and was removed after measurement: it vetoed
# 320 blocks, of which 74 (867 words) were real narration — dialogue choices such
# as `A46_FARMER_TALK_2_OPTION_2_RESPONSE`, which are read out loud. With the hint
# gone those 320 fall through to the text test below, which correctly keeps the 74
# and rejects the other 246 (too short, or no sentence punctuation).
#
# Measured on the pt-BR corpus, the remaining hints veto almost nothing: `_MENU`
# catches 5 blocks and `_BUTTON`/`_SETTINGS` one each; the other six catch zero.
# They are kept because they cost nothing and may earn their place in the other
# twelve localisations.
#
# `_MENU` is knowingly imperfect: it vetoes one genuine scene description
# (`A54_KING_BAIN_ASK_MENU`) along with one true interface string. Carving out an
# exception for a single block would be overfitting, so it stays.
UI_KEY_HINTS = ("_BUTTON", "_BTN", "_TOOLTIP", "_LABEL", "_TITLE_SHORT", "_ERROR",
                "_MENU", "_SETTINGS", "_HUD")


def clean(text: str, keep_markup: bool = False) -> str:
    if not keep_markup:
        text = MARKUP_RE.sub("", text)
        text = RICHTEXT_RE.sub("", text)
    text = text.replace("\\n", "\n").replace("\r\n", "\n")
    text = WS_RE.sub(" ", text)
    return text.strip()


def is_narration(key: str, text: str) -> bool:
    """Heuristic: does the block look like text to be read out loud?"""
    if any(h in key.upper() for h in UI_KEY_HINTS):
        return False
    words = len(text.split())
    return words >= 8 and any(c in text for c in ".!?…")


def extract_bundle(path: Path) -> tuple[str, str]:
    """Returns (textasset_name, csv_content)."""
    import UnityPy

    env = UnityPy.load(str(path))
    for obj in env.objects:
        if obj.type.name != "TextAsset":
            continue
        d = obj.read()
        name = str(getattr(d, "m_Name", "") or getattr(d, "name", ""))
        raw = getattr(d, "m_Script", None) or getattr(d, "script", b"")
        if isinstance(raw, str):
            raw = raw.encode("utf-8", "surrogateescape")
        return name, raw.decode("utf-8-sig", errors="replace")
    raise RuntimeError(f"no TextAsset in {path}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("bundles_dir", help="StreamingAssets/bundles folder")
    ap.add_argument("-o", "--out", default="corpus")
    ap.add_argument("--lang", default="pt")
    ap.add_argument("--keep-markup", action="store_true")
    args = ap.parse_args()

    bdir = Path(args.bundles_dir)
    manifest = json.loads((bdir / "manifest.dat").read_text(encoding="utf-8"))
    wanted = [b for b in manifest["bundleInfos"]
              if b["name"].startswith("localization/") and b["name"].endswith(f"/{args.lang}")]
    if not wanted:
        sys.exit(f"[error] no localization bundle for '{args.lang}'")

    out = Path(args.out)
    (out / "csv").mkdir(parents=True, exist_ok=True)

    corpus: dict[str, dict] = {}
    stats = Counter()
    missing: list[str] = []

    for b in sorted(wanted, key=lambda b: b["name"]):
        campaign = b["name"].split("/")[1]
        f = bdir / b["filename"]
        if not f.exists():
            missing.append(f"{campaign} ({b['filename']})")
            continue
        name, csv_text = extract_bundle(f)

        rows = list(csv.reader(io.StringIO(csv_text)))
        header = rows[0] if rows else []
        n_camp = 0
        for row in rows[1:]:
            if len(row) < 2 or not row[0].strip():
                continue
            key, value = row[0].strip(), row[1]
            text = clean(value, args.keep_markup)
            if not text:
                continue
            entry = {
                "key": key,
                "campaign": campaign,
                "text": text,
                "raw": value if args.keep_markup else None,
                "placeholders": PLACEHOLDER_RE.findall(value),
                "narration": is_narration(key, text),
                "words": len(text.split()),
                "chars": len(text),
            }
            corpus[f"{campaign}:{key}"] = {k: v for k, v in entry.items() if v is not None}
            n_camp += 1
            stats["total"] += 1
            stats["narration"] += entry["narration"]
            stats["with_placeholder"] += bool(entry["placeholders"])
            stats["words"] += entry["words"]

        with (out / "csv" / f"{campaign}_{args.lang}.csv").open("w", newline="", encoding="utf-8") as fh:
            w = csv.writer(fh)
            w.writerow(["key", "narration", "placeholders", "words", "text"])
            for k, e in corpus.items():
                if e["campaign"] == campaign:
                    w.writerow([e["key"], int(e["narration"]),
                                "|".join(e.get("placeholders", [])), e["words"], e["text"]])
        print(f"  {campaign:<16} {name:<28} {n_camp:>5} keys  (header={header})")

    (out / f"corpus_{args.lang}.json").write_text(
        json.dumps(corpus, ensure_ascii=False, indent=1), encoding="utf-8")

    print("\n[summary]")
    print(f"  total keys ............. {stats['total']:,}")
    print(f"  narration blocks ....... {stats['narration']:,}")
    print(f"  with placeholder {{}} ... {stats['with_placeholder']:,}")
    print(f"  words (all) ............ {stats['words']:,}")
    if missing:
        print(f"  ⚠ missing bundles: {', '.join(missing)}")
    print(f"\n  → {out / f'corpus_{args.lang}.json'}")


if __name__ == "__main__":
    main()
