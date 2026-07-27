#!/usr/bin/env python3
"""
glifos.py — traduz os ícones do jogo em palavras faladas, em qualquer idioma.

## O problema

O texto do JiME usa a fonte de ícones do jogo: símbolos gravados como caracteres
literais na Private Use Area do Unicode (U+F460–U+F47A), não como tags
`<sprite=>`. A limpeza de marcação da Fase 1 remove as tags e não enxerga esses
caracteres, então eles chegam intactos ao TTS — que não sabe pronunciá-los.

Medido no corpus pt-BR: **2.363 dos 9.118 blocos a renderizar (25,9%)** contêm
3.303 desses caracteres. O efeito é audível e às vezes destrutivo:

    cru:      "Cada herói testa \\uf462; 2. Cada herói que falhar sofre 2 \\uf469"
    no TTS:   "Cada herói testa ; 2. Cada herói que falhar sofre 2 "
    corrigido:"Cada herói testa Agilidade; 2. Cada herói que falhar sofre 2 de dano"

O ícone carregava **qual atributo testar**. Sem ele a instrução fica sem sentido.

## Como o mapeamento foi obtido (não é chute)

O próprio jogo publica a tabela: existem 24 chaves `main:GLYPH_*` cujo texto é
exatamente um glifo. `GLYPH_WISDOM` contém U+F460, `GLYPH_MIGHT` contém U+F463,
e assim por diante.

Um detalhe salvou o mapeamento de estar errado: **`GLYPH_FOCUS` é o nome interno
de Agilidade**. Nada no nome sugere isso. A prova veio de duas chaves
independentes — `A39_DRUMS_TEST_AGILITY` e `A59_FALSE TRAIL_AGILITY` — cujo único
glifo de atributo é `FOCUS`.

## Por que derivar em vez de fixar os códigos

Os códigos são detalhe de implementação da fonte e podem mudar numa atualização
do jogo. As **chaves** `GLYPH_*` são estáveis e, mais importante, **idênticas em
todos os 13 idiomas** — o texto delas é só o glifo, que não se traduz.

Consequência para gerar áudio noutro idioma: o mapa código→nome sai
automaticamente do corpus daquele idioma, sem nenhum trabalho manual. A única
parte que precisa de gente são as ~24 palavras faladas do `LEXICO`. Adicionar um
idioma é preencher uma tabela, não reinvestigar o jogo.

## Uso

    from glifos import mapa_do_corpus, substituir

    mapa = mapa_do_corpus(corpus)          # {caractere: "WISDOM", ...}
    texto = substituir(v["text"], mapa, "pt")
"""
from __future__ import annotations

import re

# faixa da Private Use Area do plano básico
PUA = re.compile("[" + chr(0xE000) + "-" + chr(0xF8FF) + "]")

# artefatos que a limpeza da Fase 1 deixou passar
_BARRA_ORFA = re.compile(r"(?<![\\\w])\\(?=[A-ZÀ-Ú])")   # "\Cada herói" -> "Cada herói"
_ESPACO_ANTES_PONT = re.compile(r"\s+([;,.!?])")
_ESPACOS = re.compile(r"[ \t]{2,}")


# --------------------------------------------------------------------------- #
# léxico falado, por idioma
#
# A chave é o nome canônico do glifo (o sufixo de `GLYPH_*`), que é o mesmo em
# todos os idiomas. O valor é (singular, plural); o plural é escolhido quando o
# glifo vem precedido de um número maior que 1.
#
# Para adicionar um idioma: copie o bloco "pt", traduza as 24 entradas, pronto.
# Nada mais precisa ser investigado no jogo.
# --------------------------------------------------------------------------- #

# Cada entrada tem dois campos, e a distinção é deliberada:
#
#   "oficial" — o termo exato da legenda do manual. É a fonte de verdade
#               terminológica e serve para conferência; não é necessariamente o
#               que soa bem lido em voz alta.
#   "falado"  — (singular, plural), o que o narrador realmente diz.
#
# Eles divergem de propósito. O manual chama o ícone de "Dano", mas "sofre 2 Dano"
# lido em voz alta soa errado em português — o narrador diz "sofre 2 de dano". E
# "Ação de Interação/Componente" é preciso na legenda e intragável numa narração,
# onde "Ação:" basta. Guardar os dois deixa a decisão explícita e auditável, em
# vez de escondida numa escolha de tradução.
#
# Marcações: (manual) = confirmado na legenda oficial pt-BR;
#            (inferido) = deduzido do uso no corpus, ainda não conferido.

LEXICO: dict[str, dict[str, dict]] = {
    "pt": {
        # --- atributos de herói (todos confirmados na legenda) ---
        "FOCUS":   {"oficial": "Agilidade",  "falado": ("Agilidade", "Agilidade")},
        "SPIRIT":  {"oficial": "Espírito",   "falado": ("Espírito", "Espírito")},
        "WIT":     {"oficial": "Esperteza",  "falado": ("Esperteza", "Esperteza")},
        "MIGHT":   {"oficial": "Vigor",      "falado": ("Vigor", "Vigor")},
        "WISDOM":  {"oficial": "Sabedoria",  "falado": ("Sabedoria", "Sabedoria")},
        # --- ícones gerais (manual) ---
        "SUCCESS": {"oficial": "Sucesso",    "falado": ("sucesso", "sucessos")},
        "FATE":    {"oficial": "Destino",    "falado": ("destino", "destino")},
        "DAMAGE":  {"oficial": "Dano",       "falado": ("de dano", "de dano")},
        "FEAR":    {"oficial": "Medo",       "falado": ("de medo", "de medo")},
        "RANGED":  {"oficial": "De Alcance", "falado": ("de alcance", "de alcance")},
        "LORE":    {"oficial": "Conhecimento", "falado": ("conhecimento", "conhecimento")},
        "ACTION":  {"oficial": "Ação de Interação/Componente", "falado": ("Ação:", "Ação:")},
        # --- itens (manual) ---
        "TRINKET":     {"oficial": "Apetrecho",          "falado": ("apetrecho", "apetrechos")},
        "ARMOR":       {"oficial": "Armadura",           "falado": ("armadura", "armaduras")},
        "SINGLE_HAND": {"oficial": "Item de Uma Mão",    "falado": ("item de uma mão", "itens de uma mão")},
        "DOUBLE_HAND": {"oficial": "Item de Duas Mãos",  "falado": ("item de duas mãos", "itens de duas mãos")},
        # --- ainda não conferidos na legenda ---
        "MOUNT":      {"oficial": "Montaria",   "falado": ("montaria", "montarias"), "inferido": True},
        "PREPARED":   {"oficial": "Preparada",  "falado": ("preparada", "preparadas"), "inferido": True},
        "CORRUPTION": {"oficial": "Corrupção",  "falado": ("corrupção", "corrupção"), "inferido": True},
        "WILD":       {"oficial": "Curinga",    "falado": ("qualquer atributo", "qualquer atributo"), "inferido": True},
        "REVEAL_CARD_DRAW": {"oficial": "Compra de Carta",
                             "falado": ("compra de carta", "compras de carta"), "inferido": True},
    },
    "en": {
        "FOCUS":   {"oficial": "Agility",  "falado": ("Agility", "Agility")},
        "SPIRIT":  {"oficial": "Spirit",   "falado": ("Spirit", "Spirit")},
        "WIT":     {"oficial": "Wit",      "falado": ("Wit", "Wit")},
        "MIGHT":   {"oficial": "Might",    "falado": ("Might", "Might")},
        "WISDOM":  {"oficial": "Wisdom",   "falado": ("Wisdom", "Wisdom")},
        "SUCCESS": {"oficial": "Success",  "falado": ("success", "successes")},
        "FATE":    {"oficial": "Fate",     "falado": ("fate", "fate")},
        "DAMAGE":  {"oficial": "Damage",   "falado": ("damage", "damage")},
        "FEAR":    {"oficial": "Fear",     "falado": ("fear", "fear")},
        "RANGED":  {"oficial": "Ranged",   "falado": ("ranged", "ranged")},
        "LORE":    {"oficial": "Lore",     "falado": ("lore", "lore")},
        "ACTION":  {"oficial": "Interaction/Component Action", "falado": ("Action:", "Action:")},
        "TRINKET":     {"oficial": "Trinket",         "falado": ("trinket", "trinkets")},
        "ARMOR":       {"oficial": "Armor",           "falado": ("armor", "armor")},
        "SINGLE_HAND": {"oficial": "One-Handed Item", "falado": ("one-handed item", "one-handed items")},
        "DOUBLE_HAND": {"oficial": "Two-Handed Item", "falado": ("two-handed item", "two-handed items")},
        "MOUNT":      {"oficial": "Mount",      "falado": ("mount", "mounts"), "inferido": True},
        "PREPARED":   {"oficial": "Prepared",   "falado": ("prepared", "prepared"), "inferido": True},
        "CORRUPTION": {"oficial": "Corruption", "falado": ("corruption", "corruption"), "inferido": True},
        "WILD":       {"oficial": "Wild",       "falado": ("any attribute", "any attribute"), "inferido": True},
        "REVEAL_CARD_DRAW": {"oficial": "Card Draw",
                             "falado": ("card draw", "card draws"), "inferido": True},
    },
    # es, fr, de, it, pl, ru, uk, ko, cz... — copie um bloco acima e traduza as
    # ~21 entradas. Rode `python3 glifos.py corpus/corpus_<lang>.json --lang <lang>`
    # para conferir a cobertura antes de renderizar.
    # Deixar um idioma ausente é seguro: cai no comportamento de `desconhecido`.
}

# glifos sem significado textual conhecido; ver `auditar`
OPACOS = {"JME01", "JME05", "JME08"}


# --------------------------------------------------------------------------- #
# números por extenso
#
# O Chatterbox Multilingual lê dígitos crus na fonologia errada mesmo com
# language_id="pt": "1" sai como "uno", "2" como "dos". Escrever por extenso
# antes de sintetizar resolve na origem. Afeta 38,8% dos blocos do corpus pt-BR
# (3.541 de 9.118); só o "1" aparece 2.453 vezes.
# --------------------------------------------------------------------------- #

_IDIOMA_NUM = {"pt": "pt_BR", "en": "en", "es": "es", "fr": "fr", "de": "de",
               "it": "it", "pl": "pl", "ru": "ru"}

# "208B", "300A" são identificadores de peça de mapa: o número se lê normalmente
# e a letra fica solta ("duzentos e oito B"). Já "1º" ou "2x" não aparecem no
# corpus, então não são tratados.
_ID_PECA = re.compile(r"\b(\d{1,4})([A-Za-z])\b")
_INTEIRO = re.compile(r"(?<![\w.,])(\d{1,4})(?![\w])")
_FRACAO = re.compile(r"\b(\d{1,3})\s*/\s*(\d{1,3})\b")


def numeros_por_extenso(texto: str, idioma: str = "pt") -> str:
    """Escreve os números por extenso, para o TTS não os ler noutro idioma.

    Ordem importa: frações e identificadores de peça primeiro, senão o padrão de
    inteiro os quebraria pela metade.
    """
    try:
        from num2words import num2words
    except ImportError:  # noqa: BLE001
        return texto
    lang = _IDIOMA_NUM.get(idioma)
    if not lang:
        return texto

    def _n(v: int) -> str:
        try:
            return num2words(v, lang=lang)
        except Exception:  # noqa: BLE001
            return str(v)

    # "(0/3)" -> "zero de três"
    texto = _FRACAO.sub(lambda m: f"{_n(int(m.group(1)))} de {_n(int(m.group(2)))}",
                        texto)
    # "208B" -> "duzentos e oito B"
    texto = _ID_PECA.sub(lambda m: f"{_n(int(m.group(1)))} {m.group(2).upper()}",
                         texto)
    # inteiros soltos
    return _INTEIRO.sub(lambda m: _n(int(m.group(1))), texto)


def mapa_do_corpus(corpus: dict) -> dict[str, str]:
    """Deriva {caractere_do_glifo: NOME} a partir das chaves `GLYPH_*` do corpus.

    Funciona em qualquer idioma sem alteração: o texto dessas chaves é só o
    glifo, que é o mesmo em todas as localizações.
    """
    mapa: dict[str, str] = {}
    for chave, v in corpus.items():
        nome = chave.split(":", 1)[-1].upper()
        if not nome.startswith("GLYPH_"):
            continue
        achados = PUA.findall(v["text"])
        if len(achados) == 1:
            mapa[achados[0]] = nome[len("GLYPH_"):]
    return mapa


def substituir(texto: str, mapa: dict[str, str], idioma: str = "pt",
               desconhecido: str = "") -> str:
    """Troca cada glifo pela palavra falada e limpa os artefatos vizinhos.

    `desconhecido` é o que fazer com um glifo sem entrada no léxico. O padrão é
    removê-lo: dizer a palavra errada num jogo é pior que não dizer nada, porque
    o jogador age sobre a instrução e não tem como perceber o erro.
    """
    lex = LEXICO.get(idioma, {})

    def troca(m: re.Match) -> str:
        nome = mapa.get(m.group())
        if nome is None or nome in OPACOS:
            return desconhecido
        entrada = lex.get(nome)
        if entrada is None:
            return desconhecido
        formas = entrada["falado"]
        # plural quando vem precedido de um número > 1: "sofre 2 <DANO>"
        antes = texto[max(0, m.start() - 6):m.start()]
        num = re.search(r"(\d+)\s*$", antes)
        plural = bool(num) and int(num.group(1)) > 1
        return formas[1] if plural else formas[0]

    out = PUA.sub(troca, texto)
    out = _BARRA_ORFA.sub("", out)
    out = _ESPACO_ANTES_PONT.sub(r"\1", out)
    return _ESPACOS.sub(" ", out).strip()


def auditar(corpus: dict, idioma: str = "pt") -> dict:
    """Diz o que o léxico deste idioma ainda não cobre — rode antes de renderizar."""
    mapa = mapa_do_corpus(corpus)
    lex = LEXICO.get(idioma, {})
    from collections import Counter
    uso = Counter(ch for v in corpus.values() for ch in PUA.findall(v["text"]))
    sem_nome = {ch: n for ch, n in uso.items() if ch not in mapa}
    sem_palavra = {mapa[ch]: n for ch, n in uso.items()
                   if ch in mapa and mapa[ch] not in lex and mapa[ch] not in OPACOS}
    inferidos = {mapa[ch]: n for ch, n in uso.items()
                 if ch in mapa and lex.get(mapa[ch], {}).get("inferido")}
    return {"glifos_no_corpus": len(uso), "ocorrencias": sum(uso.values()),
            "mapeados": len(mapa), "sem_nome": sem_nome,
            "sem_palavra_no_lexico": sem_palavra, "inferidos": inferidos}


if __name__ == "__main__":
    import argparse
    import json
    from pathlib import Path

    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("corpus", type=Path)
    ap.add_argument("--lang", default="pt")
    ap.add_argument("--exemplos", type=int, default=8)
    args = ap.parse_args()

    corpus = json.loads(args.corpus.read_text(encoding="utf-8"))
    mapa = mapa_do_corpus(corpus)
    rel = auditar(corpus, args.lang)

    print(f"[glifos] {rel['mapeados']} nomes derivados das chaves GLYPH_*")
    print(f"         {rel['glifos_no_corpus']} glifos distintos em uso, "
          f"{rel['ocorrencias']:,} ocorrências")
    if rel["sem_nome"]:
        print(f"         ⚠ sem nome: {[f'U+{ord(c):04X}' for c in rel['sem_nome']]}")
    if rel["sem_palavra_no_lexico"]:
        print(f"         ⚠ sem palavra em '{args.lang}': {rel['sem_palavra_no_lexico']}")
    if rel["inferidos"]:
        print(f"         ~ ainda não conferidos no manual: {rel['inferidos']}")
    if not rel["sem_nome"] and not rel["sem_palavra_no_lexico"]:
        print("         cobertura completa")

    print("\ntabela derivada:")
    for ch, nome in sorted(mapa.items(), key=lambda x: x[1]):
        e = LEXICO.get(args.lang, {}).get(nome)
        of = e["oficial"] if e else "—"
        fa = e["falado"][0] if e else "—"
        flag = " (inferido)" if e and e.get("inferido") else ""
        print(f"  U+{ord(ch):04X}  {nome:<20} {of:<32} falado: {fa}{flag}")

    print("\nexemplos:")
    n = 0
    for k, v in corpus.items():
        if not PUA.search(v["text"]) or not v.get("narration"):
            continue
        antes = PUA.sub("", v["text"]).replace("\n", " ")
        depois = substituir(v["text"], mapa, args.lang).replace("\n", " ")
        if antes.strip() == depois.strip():
            continue
        print(f"\n  {k}")
        print(f"    antes:   {antes[:150]}")
        print(f"    depois:  {depois[:150]}")
        n += 1
        if n >= args.exemplos:
            break
