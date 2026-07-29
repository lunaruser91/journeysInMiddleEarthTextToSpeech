#!/usr/bin/env python3
"""
glyphs.py — turns the game's icons into spoken words, in any language.

## The problem

JiME's text uses the game's icon font: symbols stored as literal characters in
the Unicode Private Use Area (U+F460–U+F47A), not as `<sprite=>` tags. The
Phase 1 markup cleanup strips the tags and never sees these characters, so they
reach the TTS intact — and it has no idea how to pronounce them.

Measured on the pt-BR corpus: **2,363 of the 9,118 blocks to render (25.9%)**
contain 3,303 of these characters. The effect is audible and sometimes
destructive:

    raw:      "Cada herói testa \\uf462; 2. Cada herói que falhar sofre 2 \\uf469"
    at TTS:   "Cada herói testa ; 2. Cada herói que falhar sofre 2 "
    fixed:    "Cada herói testa Agilidade; 2. Cada herói que falhar sofre 2 de dano"

    (in English: "Each hero tests <AGILITY>; 2. Each hero who fails suffers 2
    <DAMAGE>". The glyph carried WHICH ATTRIBUTE to test — without it the
    instruction is meaningless, and the TTS reads a silent gap.)

The icon carried **which attribute to test**. Without it the instruction makes
no sense.

## How the mapping was obtained (it is not guesswork)

The game itself publishes the table: there are 24 `main:GLYPH_*` keys whose
text is exactly one glyph. `GLYPH_WISDOM` contains U+F460, `GLYPH_MIGHT`
contains U+F463, and so on.

One detail saved the mapping from being wrong: **`GLYPH_FOCUS` is the internal
name of Agility**. Nothing in the name suggests it. The proof came from two
independent keys — `A39_DRUMS_TEST_AGILITY` and `A59_FALSE TRAIL_AGILITY` —
whose only attribute glyph is `FOCUS`, and the four official rulebooks settle
it: "Agility" appears 26 times across them and "Focus" not once. It is a code
name that never reaches a player.

## Why derive instead of hard-coding the codepoints

The codepoints are an implementation detail of the font and may change in a
game update. The `GLYPH_*` **keys** are stable and, more importantly,
**identical across all 13 languages** — their text is just the glyph, which
does not translate.

Consequence for generating audio in another language: the codepoint→name map
comes out of that language's corpus automatically, with no manual work. The
only part that needs a human is the ~24 spoken words in `LEXICON`. Adding a
language means filling in a table, not re-investigating the game.

## Usage

    from glyphs import glyph_map_from_corpus, substitute

    glyph_map = glyph_map_from_corpus(corpus)   # {character: "WISDOM", ...}
    text = substitute(v["text"], glyph_map, "pt")
"""
from __future__ import annotations

import re

# Private Use Area range of the basic plane
PUA = re.compile("[" + chr(0xE000) + "-" + chr(0xF8FF) + "]")

# artifacts that the Phase 1 cleanup let through
# "\Cada herói" -> "Cada herói"
_ORPHAN_BACKSLASH = re.compile(r"(?<![\\\w])\\(?=[A-ZÀ-Ú])")
_SPACE_BEFORE_PUNCT = re.compile(r"\s+([;,.!?])")
_EXTRA_SPACES = re.compile(r"[ \t]{2,}")


# --------------------------------------------------------------------------- #
# spoken lexicon, per language
#
# The key is the canonical name of the glyph (the suffix of `GLYPH_*`), which is
# the same in every language. The value is (singular, plural); the plural is
# picked when the glyph is preceded by a number greater than 1.
#
# To add a language: copy the "pt" block, translate the 24 entries, done.
# Nothing else has to be investigated in the game.
# --------------------------------------------------------------------------- #

# Each entry has two fields, and the distinction is deliberate:
#
#   "official" — the exact term from the manual's legend. It is the
#                terminological source of truth and exists for cross-checking;
#                it is not necessarily what sounds good read aloud.
#   "spoken"   — (singular, plural), what the narrator actually says.
#
# They diverge on purpose. The manual calls the icon "Dano", but "sofre 2 Dano"
# read aloud sounds wrong in Portuguese — the narrator says "sofre 2 de dano".
# And "Ação de Interação/Componente" is precise in a legend and unbearable in a
# narration, where "Ação:" is enough. Keeping both makes the decision explicit
# and auditable, instead of hiding it inside a translation choice.
#
# Tags: (manual) = confirmed in the official pt-BR legend;
#       (inferred) = deduced from corpus usage, not cross-checked yet.

LEXICON: dict[str, dict[str, dict]] = {
    "pt": {
        # --- hero attributes (all confirmed in the legend) ---
        "FOCUS":   {"official": "Agilidade",  "spoken": ("Agilidade", "Agilidade")},
        "SPIRIT":  {"official": "Espírito",   "spoken": ("Espírito", "Espírito")},
        "WIT":     {"official": "Esperteza",  "spoken": ("Esperteza", "Esperteza")},
        "MIGHT":   {"official": "Vigor",      "spoken": ("Vigor", "Vigor")},
        "WISDOM":  {"official": "Sabedoria",  "spoken": ("Sabedoria", "Sabedoria")},
        # --- general icons (manual) ---
        "SUCCESS": {"official": "Sucesso",    "spoken": ("sucesso", "sucessos")},
        "FATE":    {"official": "Destino",    "spoken": ("destino", "destino")},
        "DAMAGE":  {"official": "Dano",       "spoken": ("de dano", "de dano")},
        "FEAR":    {"official": "Medo",       "spoken": ("de medo", "de medo")},
        "RANGED":  {"official": "De Alcance", "spoken": ("de alcance", "de alcance")},
        "LORE":    {"official": "Conhecimento", "spoken": ("conhecimento", "conhecimento")},
        "ACTION":  {"official": "Ação de Interação/Componente", "spoken": ("Ação:", "Ação:")},
        # --- items (manual) ---
        "TRINKET":     {"official": "Apetrecho",          "spoken": ("apetrecho", "apetrechos")},
        "ARMOR":       {"official": "Armadura",           "spoken": ("armadura", "armaduras")},
        "SINGLE_HAND": {"official": "Item de Uma Mão",    "spoken": ("item de uma mão", "itens de uma mão")},
        "DOUBLE_HAND": {"official": "Item de Duas Mãos",  "spoken": ("item de duas mãos", "itens de duas mãos")},
        # --- meaning settled against the manual, Portuguese wording is not ---
        #
        # The icon glossary in the Spreading War rulebook (p8) lists Mount among
        # the item types beside Trinket, Armor, One- and Two-Handed, and Wild at
        # the end of the hero stats after Wit. Corruption has its own section
        # and the manual names the symbol outright; Prepared is a card state.
        # So what each icon *means* is no longer inferred.
        #
        # These manuals are in English, though, and what the Portuguese edition
        # prints for each is still unchecked — hence `inferred` stays here and
        # is dropped in the English lexicon below.
        "MOUNT":      {"official": "Montaria",   "spoken": ("montaria", "montarias"), "inferred": True},
        "PREPARED":   {"official": "Preparada",  "spoken": ("preparada", "preparadas"), "inferred": True},
        "CORRUPTION": {"official": "Corrupção",  "spoken": ("corrupção", "corrupção"), "inferred": True},
        "WILD":       {"official": "Curinga",    "spoken": ("qualquer atributo", "qualquer atributo"), "inferred": True},
        # Not in any of the four rulebooks, and it appears in no narration block
        # either — only in its own GLYPH_ definition. Nothing the narrator says
        # depends on it.
        "REVEAL_CARD_DRAW": {"official": "Compra de Carta",
                             "spoken": ("compra de carta", "compras de carta"), "inferred": True},
    },
    "en": {
        "FOCUS":   {"official": "Agility",  "spoken": ("Agility", "Agility")},
        "SPIRIT":  {"official": "Spirit",   "spoken": ("Spirit", "Spirit")},
        "WIT":     {"official": "Wit",      "spoken": ("Wit", "Wit")},
        "MIGHT":   {"official": "Might",    "spoken": ("Might", "Might")},
        "WISDOM":  {"official": "Wisdom",   "spoken": ("Wisdom", "Wisdom")},
        "SUCCESS": {"official": "Success",  "spoken": ("success", "successes")},
        "FATE":    {"official": "Fate",     "spoken": ("fate", "fate")},
        "DAMAGE":  {"official": "Damage",   "spoken": ("damage", "damage")},
        "FEAR":    {"official": "Fear",     "spoken": ("fear", "fear")},
        "RANGED":  {"official": "Ranged",   "spoken": ("ranged", "ranged")},
        "LORE":    {"official": "Lore",     "spoken": ("lore", "lore")},
        "ACTION":  {"official": "Interaction/Component Action", "spoken": ("Action:", "Action:")},
        "TRINKET":     {"official": "Trinket",         "spoken": ("trinket", "trinkets")},
        "ARMOR":       {"official": "Armor",           "spoken": ("armor", "armor")},
        "SINGLE_HAND": {"official": "One-Handed Item", "spoken": ("one-handed item", "one-handed items")},
        "DOUBLE_HAND": {"official": "Two-Handed Item", "spoken": ("two-handed item", "two-handed items")},
        # Checked against the rulebooks. The Spreading War icon glossary (p8)
        # prints Mount among the item types and Wild at the end of the hero
        # stats; Corruption has a named section of its own; Prepared is the
        # card state described under deck rules.
        #
        # Wild is worth stating plainly because the glossary's layout allows the
        # opposite reading — "Wild items" as a category. The corpus settles it:
        # all nine uses, in both languages, put it where an attribute goes.
        # "Test <WILD>; 3", "a hero may test <WILD> instead", "<WILD> negates".
        # Never once as something a hero carries. Hence "any attribute".
        "MOUNT":      {"official": "Mount",      "spoken": ("mount", "mounts")},
        "PREPARED":   {"official": "Prepared",   "spoken": ("prepared", "prepared")},
        "CORRUPTION": {"official": "Corruption", "spoken": ("corruption", "corruption")},
        "WILD":       {"official": "Wild",       "spoken": ("any attribute", "any attribute")},
        # Absent from all four rulebooks, and from every narration block — it
        # exists only as its own GLYPH_ definition, so nothing spoken uses it.
        "REVEAL_CARD_DRAW": {"official": "Card Draw",
                             "spoken": ("card draw", "card draws"), "inferred": True},
    },
    # es, fr, de, it, pl, ru, uk, ko, cz... — copy a block above and translate
    # the ~21 entries. Run `python3 glyphs.py corpus/corpus_<lang>.json --lang <lang>`
    # to check the coverage before rendering.
    # Leaving a language out is safe: it falls back to the `unknown` behavior.
}

# glyphs with no known textual meaning; see `audit`
OPAQUE = {"JME01", "JME05", "JME08"}


# --------------------------------------------------------------------------- #
# numbers spelled out
#
# Speech models read bare digits with the wrong phonology even with
# language_id="pt": "1" comes out as "uno", "2" as "dos". Spelling them out
# before synthesis fixes it at the source. Affects 38.8% of the pt-BR corpus
# blocks (3,541 of 9,118); "1" alone appears 2,453 times.
# --------------------------------------------------------------------------- #

_NUM_LANG = {"pt": "pt_BR", "en": "en", "es": "es", "fr": "fr", "de": "de",
             "it": "it", "pl": "pl", "ru": "ru"}

# "208B", "300A" are map tile identifiers: the number is read normally and the
# letter stands on its own ("duzentos e oito B"). "1º" or "2x", on the other
# hand, do not appear in the corpus, so they are not handled.
_TILE_ID = re.compile(r"\b(\d{1,4})([A-Za-z])\b")
_INTEGER = re.compile(r"(?<![\w.,])(\d{1,4})(?![\w])")
_FRACTION = re.compile(r"\b(\d{1,3})\s*/\s*(\d{1,3})\b")


def spell_out_numbers(text: str, lang: str = "pt") -> str:
    """Spells the numbers out, so the TTS does not read them in another language.

    Order matters: fractions and tile identifiers first, otherwise the integer
    pattern would break them in half.
    """
    try:
        from num2words import num2words
    except ImportError:  # noqa: BLE001
        return text
    code = _NUM_LANG.get(lang)
    if not code:
        return text

    def _n(v: int) -> str:
        try:
            return num2words(v, lang=code)
        except Exception:  # noqa: BLE001
            return str(v)

    # "(0/3)" -> "zero de três"
    text = _FRACTION.sub(lambda m: f"{_n(int(m.group(1)))} de {_n(int(m.group(2)))}",
                         text)
    # "208B" -> "duzentos e oito B"
    text = _TILE_ID.sub(lambda m: f"{_n(int(m.group(1)))} {m.group(2).upper()}",
                        text)
    # bare integers
    return _INTEGER.sub(lambda m: _n(int(m.group(1))), text)


def glyph_map_from_corpus(corpus: dict) -> dict[str, str]:
    """Derives {glyph_character: NAME} from the corpus's `GLYPH_*` keys.

    Works in any language without changes: the text of those keys is just the
    glyph, which is the same in every localization.
    """
    glyph_map: dict[str, str] = {}
    for key, v in corpus.items():
        name = key.split(":", 1)[-1].upper()
        if not name.startswith("GLYPH_"):
            continue
        found = PUA.findall(v["text"])
        if len(found) == 1:
            glyph_map[found[0]] = name[len("GLYPH_"):]
    return glyph_map


def substitute(text: str, glyph_map: dict[str, str], lang: str = "pt",
               unknown: str = "") -> str:
    """Swaps each glyph for its spoken word and cleans up the nearby artifacts.

    `unknown` is what to do with a glyph that has no lexicon entry. The default
    is to drop it: saying the wrong word in a game is worse than saying nothing,
    because the player acts on the instruction and has no way to notice the
    mistake.
    """
    lex = LEXICON.get(lang, {})

    def swap(m: re.Match) -> str:
        name = glyph_map.get(m.group())
        if name is None or name in OPAQUE:
            return unknown
        entry = lex.get(name)
        if entry is None:
            return unknown
        forms = entry["spoken"]
        # plural when preceded by a number > 1: "sofre 2 <DAMAGE>"
        before = text[max(0, m.start() - 6):m.start()]
        num = re.search(r"(\d+)\s*$", before)
        plural = bool(num) and int(num.group(1)) > 1
        return forms[1] if plural else forms[0]

    out = PUA.sub(swap, text)
    out = _ORPHAN_BACKSLASH.sub("", out)
    out = _SPACE_BEFORE_PUNCT.sub(r"\1", out)
    return _EXTRA_SPACES.sub(" ", out).strip()


def audit(corpus: dict, lang: str = "pt") -> dict:
    """Says what this language's lexicon does not cover yet — run before rendering."""
    glyph_map = glyph_map_from_corpus(corpus)
    lex = LEXICON.get(lang, {})
    from collections import Counter
    usage = Counter(ch for v in corpus.values() for ch in PUA.findall(v["text"]))
    unnamed = {ch: n for ch, n in usage.items() if ch not in glyph_map}
    missing_word = {glyph_map[ch]: n for ch, n in usage.items()
                    if ch in glyph_map and glyph_map[ch] not in lex
                    and glyph_map[ch] not in OPAQUE}
    inferred = {glyph_map[ch]: n for ch, n in usage.items()
                if ch in glyph_map and lex.get(glyph_map[ch], {}).get("inferred")}
    return {"glyphs_in_corpus": len(usage), "occurrences": sum(usage.values()),
            "mapped": len(glyph_map), "unnamed": unnamed,
            "missing_from_lexicon": missing_word, "inferred": inferred}


if __name__ == "__main__":
    import argparse
    import json
    from pathlib import Path

    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("corpus", type=Path)
    ap.add_argument("--lang", default="pt")
    ap.add_argument("--examples", type=int, default=8)
    args = ap.parse_args()

    corpus = json.loads(args.corpus.read_text(encoding="utf-8"))
    glyph_map = glyph_map_from_corpus(corpus)
    report = audit(corpus, args.lang)

    print(f"[glyphs] {report['mapped']} names derived from the GLYPH_* keys")
    print(f"         {report['glyphs_in_corpus']} distinct glyphs in use, "
          f"{report['occurrences']:,} occurrences")
    if report["unnamed"]:
        print(f"         ⚠ no name: {[f'U+{ord(c):04X}' for c in report['unnamed']]}")
    if report["missing_from_lexicon"]:
        print(f"         ⚠ no word in '{args.lang}': {report['missing_from_lexicon']}")
    if report["inferred"]:
        print(f"         ~ not checked against the manual yet: {report['inferred']}")
    if not report["unnamed"] and not report["missing_from_lexicon"]:
        print("         full coverage")

    print("\nderived table:")
    for ch, name in sorted(glyph_map.items(), key=lambda x: x[1]):
        e = LEXICON.get(args.lang, {}).get(name)
        official = e["official"] if e else "—"
        spoken = e["spoken"][0] if e else "—"
        flag = " (inferred)" if e and e.get("inferred") else ""
        print(f"  U+{ord(ch):04X}  {name:<20} {official:<32} spoken: {spoken}{flag}")

    print("\nexamples:")
    n = 0
    for k, v in corpus.items():
        if not PUA.search(v["text"]) or not v.get("narration"):
            continue
        before = PUA.sub("", v["text"]).replace("\n", " ")
        after = substitute(v["text"], glyph_map, args.lang).replace("\n", " ")
        if before.strip() == after.strip():
            continue
        print(f"\n  {k}")
        print(f"    before:  {before[:150]}")
        print(f"    after:   {after[:150]}")
        n += 1
        if n >= args.examples:
            break
