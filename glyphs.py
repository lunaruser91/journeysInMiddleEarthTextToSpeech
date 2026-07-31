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
    # Read off the icon glossary on page 16 of the Spanish rulebook, sent by a
    # player. Sixteen of the twenty-one are printed there and they cover 99.3%
    # of the icon occurrences in Spanish narration; MOUNT (18x) and WILD (9x) are
    # not on that page and have no entry, so they are dropped rather than
    # guessed.
    #
    # `official` is what the page prints. `spoken` is derived from it here — the
    # preposition and the plural are this project's, not the book's, the same way
    # the Portuguese "de dano" is.
    #
    # Worth recording: Spanish calls the Agility icon *Agilidad* and the Might
    # icon *Vigor*, which is what Portuguese does too — and both are the ones a
    # translation from English gets wrong.
    "es": {
        "FOCUS":   {"official": "Agilidad",  "spoken": ("Agilidad", "Agilidad")},
        "SPIRIT":  {"official": "Brío",      "spoken": ("Brío", "Brío")},
        "WIT":     {"official": "Astucia",   "spoken": ("Astucia", "Astucia")},
        "MIGHT":   {"official": "Vigor",     "spoken": ("Vigor", "Vigor")},
        "WISDOM":  {"official": "Sabiduría", "spoken": ("Sabiduría", "Sabiduría")},
        "SUCCESS": {"official": "Éxito",     "spoken": ("éxito", "éxitos")},
        "FATE":    {"official": "Destino",   "spoken": ("destino", "destino")},
        "DAMAGE":  {"official": "Daño",      "spoken": ("de daño", "de daño")},
        "FEAR":    {"official": "Miedo",     "spoken": ("de miedo", "de miedo")},
        "RANGED":  {"official": "Ataque a distancia",
                    "spoken": ("a distancia", "a distancia")},
        "LORE":    {"official": "Erudición", "spoken": ("erudición", "erudición")},
        "ACTION":  {"official": "Acción de interacción",
                    "spoken": ("Acción:", "Acción:")},
        "TRINKET":     {"official": "Pertrecho",  "spoken": ("pertrecho", "pertrechos")},
        "ARMOR":       {"official": "Armadura",   "spoken": ("armadura", "armaduras")},
        "SINGLE_HAND": {"official": "Objeto de una mano",
                        "spoken": ("objeto de una mano", "objetos de una mano")},
        "DOUBLE_HAND": {"official": "Objeto de dos manos",
                        "spoken": ("objeto de dos manos", "objetos de dos manos")},
    },
    # Read off the icon glossary on page 8 of the German rulebook, sent by a
    # player. Eighteen of the twenty-one are printed there — two more than the
    # Spanish page carries: it lists *Universal* among the hero attributes and
    # *Reittier* among the items, which are WILD and MOUNT. Coverage of German
    # narration is 100.0%: every icon that occurs has a word.
    #
    # PREPARED, CORRUPTION and REVEAL_CARD_DRAW are on neither page and occur
    # once each in German narration.
    #
    # `official` is what the page prints. `spoken` is derived here: German takes
    # no preposition where Portuguese does — "2 Schaden" against "2 de dano" — so
    # the bare noun is right. WILD is the one to look at: the page calls it
    # *Universal*, which is a label rather than something to say inside "Probe
    # auf ... 2", and Portuguese solved the same problem by speaking it as
    # "qualquer atributo" rather than "Curinga".
    "de": {
        "FOCUS":   {"official": "Beweglichkeit", "spoken": ("Beweglichkeit", "Beweglichkeit")},
        "SPIRIT":  {"official": "Wille",         "spoken": ("Wille", "Wille")},
        "WIT":     {"official": "Scharfsinn",    "spoken": ("Scharfsinn", "Scharfsinn")},
        "MIGHT":   {"official": "Körperkraft",   "spoken": ("Körperkraft", "Körperkraft")},
        "WISDOM":  {"official": "Weisheit",      "spoken": ("Weisheit", "Weisheit")},
        "SUCCESS": {"official": "Erfolg",        "spoken": ("Erfolg", "Erfolge")},
        "FATE":    {"official": "Schicksal",     "spoken": ("Schicksal", "Schicksal")},
        "DAMAGE":  {"official": "Schaden",       "spoken": ("Schaden", "Schaden")},
        "FEAR":    {"official": "Furcht",        "spoken": ("Furcht", "Furcht")},
        "RANGED":  {"official": "Fernkampf",     "spoken": ("Fernkampf", "Fernkampf")},
        "LORE":    {"official": "Wissen",        "spoken": ("Wissen", "Wissen")},
        "ACTION":  {"official": 'Aktion "Interagieren"', "spoken": ("Aktion:", "Aktion:")},
        "TRINKET":     {"official": "Schmuckstück", "spoken": ("Schmuckstück", "Schmuckstücke")},
        "ARMOR":       {"official": "Rüstung",      "spoken": ("Rüstung", "Rüstungen")},
        "SINGLE_HAND": {"official": "Einhand-Gegenstand",
                        "spoken": ("Einhand-Gegenstand", "Einhand-Gegenstände")},
        "DOUBLE_HAND": {"official": "Zweihand-Gegenstand",
                        "spoken": ("Zweihand-Gegenstand", "Zweihand-Gegenstände")},
        "MOUNT":   {"official": "Reittier",   "spoken": ("Reittier", "Reittiere")},
        "WILD":    {"official": "Universal",  "spoken": ("Universal", "Universal")},
    },
    # Read off the icon glossary of the French rulebook, sent by a player.
    # Sixteen entries, the same set the Spanish page carries — no Mount, no
    # wildcard — covering 99.3% of the icons in French narration.
    #
    # This one is the evidence that guessing does not transfer. French calls the
    # Might icon *Force*, which is exactly what I guessed for Portuguese and got
    # wrong: Portuguese and Spanish both say *Vigor*, German says
    # *Körperkraft*. Four editions, three different words, and the English
    # "Might" predicts none of them.
    "fr": {
        "FOCUS":   {"official": "Agilité",      "spoken": ("Agilité", "Agilité")},
        "SPIRIT":  {"official": "Esprit",       "spoken": ("Esprit", "Esprit")},
        "WIT":     {"official": "Ingéniosité",  "spoken": ("Ingéniosité", "Ingéniosité")},
        "MIGHT":   {"official": "Force",        "spoken": ("Force", "Force")},
        "WISDOM":  {"official": "Sagesse",      "spoken": ("Sagesse", "Sagesse")},
        "SUCCESS": {"official": "Succès",       "spoken": ("succès", "succès")},
        "FATE":    {"official": "Destin",       "spoken": ("destin", "destin")},
        "DAMAGE":  {"official": "Dégât",        "spoken": ("dégât", "dégâts")},
        "FEAR":    {"official": "Peur",         "spoken": ("peur", "peur")},
        "RANGED":  {"official": "À Distance",   "spoken": ("à distance", "à distance")},
        "LORE":    {"official": "Connaissance", "spoken": ("connaissance", "connaissance")},
        "ACTION":  {"official": "Action Interagir", "spoken": ("Action :", "Action :")},
        "TRINKET":     {"official": "Trouvaille", "spoken": ("trouvaille", "trouvailles")},
        "ARMOR":       {"official": "Armure",     "spoken": ("armure", "armures")},
        "SINGLE_HAND": {"official": "Objet à une main",
                        "spoken": ("objet à une main", "objets à une main")},
        "DOUBLE_HAND": {"official": "Objet à deux mains",
                        "spoken": ("objet à deux mains", "objets à deux mains")},
    },
    # Read off the icon glossary of the Italian rulebook, sent by a player.
    # Sixteen entries, the Spanish and French set, 99.3% of Italian narration.
    #
    # This page also shows why the printed glossary beats the string the game
    # exports. `main:UI_PHYSICAL` is "Danni" in the Italian corpus and
    # `main:UI_FEAR` is "Paure" — both plural, because those strings label a
    # counter in the interface. The glossary names the icon: *Danno*, *Paura*.
    # The template pre-fills the corpus version, and Italian is the case where
    # somebody reading the page should overwrite it.
    "it": {
        "FOCUS":   {"official": "Agilità",  "spoken": ("Agilità", "Agilità")},
        "SPIRIT":  {"official": "Spirito",  "spoken": ("Spirito", "Spirito")},
        "WIT":     {"official": "Ingegno",  "spoken": ("Ingegno", "Ingegno")},
        "MIGHT":   {"official": "Forza",    "spoken": ("Forza", "Forza")},
        "WISDOM":  {"official": "Saggezza", "spoken": ("Saggezza", "Saggezza")},
        "SUCCESS": {"official": "Successo", "spoken": ("successo", "successi")},
        "FATE":    {"official": "Fato",     "spoken": ("fato", "fato")},
        "DAMAGE":  {"official": "Danno",    "spoken": ("danno", "danni")},
        "FEAR":    {"official": "Paura",    "spoken": ("paura", "paura")},
        "RANGED":  {"official": "Distanza", "spoken": ("a distanza", "a distanza")},
        "LORE":    {"official": "Sapienza", "spoken": ("sapienza", "sapienza")},
        "ACTION":  {"official": "Azione di Interazione", "spoken": ("Azione:", "Azione:")},
        "TRINKET":     {"official": "Accessorio", "spoken": ("accessorio", "accessori")},
        "ARMOR":       {"official": "Armatura",   "spoken": ("armatura", "armature")},
        "SINGLE_HAND": {"official": "Oggetto a Una Mano",
                        "spoken": ("oggetto a una mano", "oggetti a una mano")},
        "DOUBLE_HAND": {"official": "Oggetto a Due Mani",
                        "spoken": ("oggetto a due mani", "oggetti a due mani")},
    },
    # Read off the icon glossary of the Russian rulebook, sent by a player.
    # Sixteen entries. Russian is the first language here where `official` and
    # `spoken` have to differ for grammar rather than for style, and both
    # differences are measured rather than assumed.
    #
    # **Attributes are spoken in the genitive.** The glossary prints the
    # nominative — Ловкость — and the game never uses it that way. Counted over
    # the 1,524 attribute glyphs in Russian narration, the word before is
    # `проверку` 62% of the time, `с помощью` 31%, then `или`, `показатель`,
    # `значением`. Every one of those governs the genitive, so the icon is said
    # as Ловкости.
    #
    # **The plural form is the genitive singular, not the plural.** Russian
    # numerals take 1 → nominative, 2-4 → genitive singular, 5+ → genitive
    # plural, and this table has room for two forms. Counted over the numbers
    # that actually precede a countable icon: 1 appears 586 times, 2-4 appears
    # 412, 5 appears once and 0 once. So ("урон", "урона") is right for 1,233 of
    # 1,236 numbered cases, and the two it misses are one occurrence each.
    "ru": {
        "FOCUS":   {"official": "Ловкость",  "spoken": ("Ловкости", "Ловкости")},
        "SPIRIT":  {"official": "Храбрость", "spoken": ("Храбрости", "Храбрости")},
        "WIT":     {"official": "Смекалка",  "spoken": ("Смекалки", "Смекалки")},
        "MIGHT":   {"official": "Сила",      "spoken": ("Силы", "Силы")},
        "WISDOM":  {"official": "Мудрость",  "spoken": ("Мудрости", "Мудрости")},
        "SUCCESS": {"official": "Успех",     "spoken": ("успех", "успеха")},
        "FATE":    {"official": "Судьба",    "spoken": ("судьбы", "судьбы")},
        "DAMAGE":  {"official": "Урон",      "spoken": ("урон", "урона")},
        "FEAR":    {"official": "Страх",     "spoken": ("страх", "страха")},
        "RANGED":  {"official": "Дальняя атака",
                    "spoken": ("дальняя атака", "дальняя атака")},
        "LORE":    {"official": "Сведения",  "spoken": ("сведения", "сведения")},
        "ACTION":  {"official": "Взаимодействие",
                    "spoken": ("Взаимодействие:", "Взаимодействие:")},
        "TRINKET":     {"official": "Вещь",  "spoken": ("вещь", "вещи")},
        "ARMOR":       {"official": "Броня", "spoken": ("броня", "брони")},
        "SINGLE_HAND": {"official": "Снаряжение в одну руку",
                        "spoken": ("снаряжение в одну руку", "снаряжение в одну руку")},
        "DOUBLE_HAND": {"official": "Снаряжение в две руки",
                        "spoken": ("снаряжение в две руки", "снаряжение в две руки")},
    },
    # Read off the icon glossary of the Polish rulebook, sent by a player.
    # Sixteen entries. Polish declines like Russian, and the same two questions
    # were counted rather than guessed.
    #
    # Attributes: `test` precedes 1,169 of them, then `karty`, `albo`, `kartę` —
    # all governing the genitive, so `zręczność` is spoken `zręczności`.
    #
    # Number agreement matters far less here than in Russian: of the countable
    # icons, **1,373 carry no number at all** against 207 that do, and of those
    # 170 are a bare 1. So the singular form is what is nearly always heard, and
    # the plural slot holds the 2-4 nominative plural, which covers the 37 that
    # remain.
    #
    # The items are printed as bare adjectives — `pomocniczy`, `jednoręczny` —
    # because the section heading supplies the noun. They are left as printed;
    # whether they should be spoken as `przedmiot pomocniczy` is a question for
    # somebody who speaks Polish, not for the page.
    "pl": {
        "FOCUS":   {"official": "zręczność", "spoken": ("zręczności", "zręczności")},
        "SPIRIT":  {"official": "duch",      "spoken": ("ducha", "ducha")},
        "WIT":     {"official": "spryt",     "spoken": ("sprytu", "sprytu")},
        "MIGHT":   {"official": "siła",      "spoken": ("siły", "siły")},
        "WISDOM":  {"official": "mądrość",   "spoken": ("mądrości", "mądrości")},
        "SUCCESS": {"official": "sukces",    "spoken": ("sukces", "sukcesy")},
        "FATE":    {"official": "przeznaczenie",
                    "spoken": ("przeznaczenie", "przeznaczenia")},
        # Genitive, and measured: the damage glyph follows a form of `karta`
        # 91% of the time — `kartę obrażeń`, `karty obrażeń` — and fear does at
        # 81%. Both are "a card OF damage", which wants the genitive whatever
        # the number is. `sukces` keeps ordinary agreement because 78% of its
        # occurrences follow a bare numeral instead.
        "DAMAGE":  {"official": "obrażenie", "spoken": ("obrażeń", "obrażeń")},
        "FEAR":    {"official": "strach",    "spoken": ("strachu", "strachu")},
        "RANGED":  {"official": "atak dystansowy",
                    "spoken": ("atak dystansowy", "atak dystansowy")},
        "LORE":    {"official": "wiedza tajemna",
                    "spoken": ("wiedza tajemna", "wiedza tajemna")},
        "ACTION":  {"official": "akcja oddziaływania",
                    "spoken": ("akcja oddziaływania:", "akcja oddziaływania:")},
        "TRINKET":     {"official": "pomocniczy", "spoken": ("pomocniczy", "pomocnicze")},
        "ARMOR":       {"official": "pancerz",    "spoken": ("pancerz", "pancerze")},
        "SINGLE_HAND": {"official": "jednoręczny",
                        "spoken": ("jednoręczny", "jednoręczne")},
        "DOUBLE_HAND": {"official": "dwuręczny", "spoken": ("dwuręczny", "dwuręczne")},
    },
    # Read off the icon glossary of the Korean rulebook, sent by a player.
    # Sixteen entries. Korean marks no plural on these nouns, so both forms are
    # the same word — the one language here where the two-slot structure is not
    # a compromise but simply unused.
    #
    # The two the game exports agree with the page exactly: `main:UI_PHYSICAL`
    # is 피해 and `main:UI_FEAR` is 공포.
    "ko": {
        "FOCUS":   {"official": "민첩", "spoken": ("민첩", "민첩")},
        "SPIRIT":  {"official": "기백", "spoken": ("기백", "기백")},
        "WIT":     {"official": "재치", "spoken": ("재치", "재치")},
        "MIGHT":   {"official": "힘",   "spoken": ("힘", "힘")},
        "WISDOM":  {"official": "지혜", "spoken": ("지혜", "지혜")},
        "SUCCESS": {"official": "성공", "spoken": ("성공", "성공")},
        "FATE":    {"official": "숙명", "spoken": ("숙명", "숙명")},
        "DAMAGE":  {"official": "피해", "spoken": ("피해", "피해")},
        "FEAR":    {"official": "공포", "spoken": ("공포", "공포")},
        "RANGED":  {"official": "원거리", "spoken": ("원거리", "원거리")},
        "LORE":    {"official": "지식", "spoken": ("지식", "지식")},
        "ACTION":  {"official": "상호작용 행동", "spoken": ("상호작용 행동:", "상호작용 행동:")},
        "TRINKET":     {"official": "소모품", "spoken": ("소모품", "소모품")},
        "ARMOR":       {"official": "방어구", "spoken": ("방어구", "방어구")},
        "SINGLE_HAND": {"official": "한손 물품", "spoken": ("한손 물품", "한손 물품")},
        "DOUBLE_HAND": {"official": "양손 물품", "spoken": ("양손 물품", "양손 물품")},
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

# `num2words` covers twelve of the game's thirteen; this mapped eight of them,
# so Czech, Hungarian, Korean and Ukrainian read their digits in whatever the
# voice does with a bare numeral. Chinese is the one num2words has no converter
# for at all — 56 languages and none of them — and it is also the one that needs
# it least: 43% of its narration carries an Arabic digit and a Chinese voice
# reads those natively.
_NUM_LANG = {"pt": "pt_BR", "en": "en", "es": "es", "fr": "fr", "de": "de",
             "it": "it", "pl": "pl", "ru": "ru", "cz": "cs", "hu": "hu",
             "ko": "ko", "uk": "uk"}

# "(0/3)" is a counter — nought of three search tokens found — and the word
# between the two numbers was hardcoded to the Portuguese "de" for every
# language. An English session read "(zero de three)"; German "(null de drei)";
# Russian "(ноль de три)". It shipped that way in a language that has been
# rendered.
#
# Only the Portuguese and English are checked by someone who speaks them. The
# rest are the ordinary counter phrasing and should be corrected by a native
# speaker rather than trusted — same standing as the audition sentences in
# voices.py.
#
# A language with no entry reads the two numbers with a pause between them. That
# is terse and it is not wrong, which a preposition borrowed from another
# language is.
_FRACTION_WORD = {
    "pt": "de", "es": "de", "en": "of", "it": "di", "fr": "sur",
    "de": "von", "pl": "z", "ru": "из", "cz": "ze", "uk": "з",
}

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

    # "(0/3)" -> "zero de três", "zero of three", "null von drei"
    joiner = _FRACTION_WORD.get(lang)
    sep = f" {joiner} " if joiner else ", "
    text = _FRACTION.sub(
        lambda m: f"{_n(int(m.group(1)))}{sep}{_n(int(m.group(2)))}", text)
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
    ap.add_argument("--template", action="store_true",
                    help="print a fillable LEXICON block for this language, "
                         "commonest icon first, with the English beside each")
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

    if args.template:
        # A speaker of the language should have to translate 21 words, not read
        # this file and work out a dict-of-dicts. The counts order it so that
        # stopping halfway still covers the icons that actually occur: FEAR
        # appears 705 times in German narration and LORE once.
        counts = {}
        for v in corpus.values():
            if not v.get("narration"):
                continue
            for ch in PUA.findall(v["text"]):
                name = glyph_map.get(ch)
                if name:
                    counts[name] = counts.get(name, 0) + 1
        en = LEXICON.get("en", {})
        # Two of the twenty-one the game does publish as plain strings, and they
        # are the two most spoken: FEAR and DAMAGE are 1,364 of German's 4,272
        # icon occurrences between them. Filled in from the corpus rather than
        # asked for — and seeing two already correct is what tells whoever fills
        # the rest what "official" is supposed to mean.
        FROM_GAME = {"DAMAGE": "main:UI_PHYSICAL", "FEAR": "main:UI_FEAR"}
        known = {}
        for icon, key in FROM_GAME.items():
            got = (corpus.get(key) or {}).get("text", "").strip()
            if got:
                known[icon] = got
        # Every glyph the corpus defines, not only the ones that occur: a name
        # with no count is one this language never speaks today, and saying so
        # is better than a list that is quietly five short of the table it is
        # meant to fill.
        for name in set(glyph_map.values()):
            counts.setdefault(name, 0)
        print(f'\n    "{args.lang}": {{')
        for name in sorted(counts, key=lambda n: (-counts[n], n)):
            ref = en.get(name)
            hint = (f'{ref["official"]} / {ref["spoken"][0]}, {ref["spoken"][1]}'
                    if ref else "not in the English lexicon either")
            n = counts[name]
            quanto = f"{n:>4}x" if n else "   -"
            chave = f'"{name}":'
            got = known.get(name)
            if got:
                corpo = (f'{{"official": {got!r}, '
                         f'"spoken": ({got.lower()!r}, {got.lower()!r})}},')
                nota = f'   # {quanto}  from the game itself'
            else:
                corpo = '{"official": "", "spoken": ("", "")},'
                nota = f'   # {quanto}  en: {hint}'
            print(f'        {chave:<22} {corpo}{nota}')
        print("    },")
        print(f"\nPaste that into LEXICON in glyphs.py and fill the two strings "
              f"per line:\n  official — what the printed {args.lang!r} edition "
              f"calls the icon\n  spoken   — how it is said, singular and plural, "
              f"in the middle of a sentence")
        raise SystemExit(0)

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
