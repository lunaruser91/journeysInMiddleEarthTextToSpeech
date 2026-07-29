#!/usr/bin/env python3
"""
i18n.py — the menu, in the language you picked.

Choosing Portuguese and then reading an English menu is a reasonable thing to
complain about, even though the question is about the game's text rather than
the interface: which corpus to extract, which voice to speak with. In practice
those coincide, so the interface follows the same choice.

English strings are the keys. A missing translation falls through to English
rather than to a placeholder, so adding a language is additive and half a
translation is still usable.

**Only the menu is translated.** The subcommands — render progress, the
narrator's per-screen lines, `status`, `doctor` — still print English. That is
about a hundred more strings and they are read while something is running, not
while deciding what to do.
"""
from __future__ import annotations

STRINGS: dict[str, dict[str, str]] = {
    "pt": {
        # --- prompts and controls ---
        "enter": "enter",
        "back": "voltar",
        "quit": "sair",
        "pick a number between 1 and {n}": "escolha um número entre 1 e {n}",
        "Which language to work in?": "Qual idioma você quer usar?",
        "What would you like to do?": "O que você quer fazer?",

        # --- the actions ---
        "Narrate a game": "Narrar uma partida",
        "watch the screen and read it aloud": "assiste à tela e lê em voz alta",
        "Render audio": "Gerar o áudio",
        "corpus → speech, resumable": "corpus → fala, retomável",
        "Extract the corpus": "Extrair o corpus",
        "read the game's own files": "lê os arquivos do próprio jogo",
        "Status": "Situação",
        "what is done and what is missing": "o que está pronto e o que falta",
        "Check this machine": "Verificar esta máquina",
        "is everything installed?": "está tudo instalado?",
        "Voices": "Vozes",
        "which voice reads, and change it": "qual voz lê, e trocar",
        "which voice speaks each language": "qual voz fala cada idioma",

        # --- picking a voice ---
        "Which voice should read?": "Qual voz deve ler?",
        "in use": "em uso",
        "pace measured": "ritmo medido",
        "downloaded": "baixada",
        "no voice for this language": "nenhuma voz para este idioma",
        "{name} has no measured pace.": "{name} não tem ritmo medido.",
        "It reads at its own speed until measured:":
            "Ela lê na velocidade dela até alguém medir:",
        "{n} blocks are rendered with the voice in use.":
            "{n} blocos já foram gerados com a voz em uso.",
        "Changing it renders every one of them again.":
            "Trocar significa gerar todos de novo.",
        "Use {name}?": "Usar {name}?",
        "{name} it is.": "{name}, então.",
        "fetching {name}, {mb} MB": "baixando {name}, {mb} MB",
        "listen...": "escute...",
        "could not play it here": "não consegui tocar aqui",
        "Use {name}": "Usar {name}",
        "Hear it again": "Ouvir de novo",
        "Try another voice": "Experimentar outra voz",
        "Change language": "Trocar de idioma",
        "currently {name}": "atualmente {name}",

        # --- state shown beside each choice ---
        "no corpus yet — extract first": "sem corpus ainda — extraia primeiro",
        "corpus ready": "corpus pronto",
        "corpus ready, {n} blocks rendered": "corpus pronto, {n} blocos gerados",
        "complete": "completo",
        "not started": "não iniciado",
        "{n} blocks": "{n} blocos",
        "{done} of {total}": "{done} de {total}",
        "(shared by every campaign)": "(compartilhado por todas as campanhas)",
        "(your most recent save)": "(seu save mais recente)",
        "every campaign above, in order": "todas as campanhas acima, em ordem",
        "everything not yet rendered": "tudo que ainda não foi gerado",

        # --- questions ---
        "Which campaign?": "Qual campanha?",
        "Which campaign are you playing?": "Qual campanha você está jogando?",
        "How is the game running?": "Como o jogo está rodando?",
        "fullscreen": "tela cheia",
        "capture the display — the usual case":
            "captura o monitor — o caso usual",
        "in a window": "em janela",
        "find it by window title": "encontra pelo título da janela",
        "Start rendering?": "Começar a gerar?",
        "What now?": "E agora?",
        "Render {what} first": "Gerar {what} primeiro",
        "about half an hour per campaign, then it plays":
            "cerca de meia hora por campanha, e então ele fala",
        "Play anyway": "Jogar assim mesmo",
        "recognises the screens, speaks what it can":
            "reconhece as telas, fala o que puder",
        "Pick another campaign": "Escolher outra campanha",
        "Add it to this render?": "Incluir na geração?",
        "Extract {name} now?": "Extrair {name} agora?",
        "A corpus for {name} already exists. Extract again?":
            "Já existe um corpus de {name}. Extrair de novo?",

        # --- messages ---
        "ready: {what}": "pronto: {what}",
        "nothing extracted yet": "nada extraído ainda",
        "no audio": "sem áudio",
        "{n} blocks": "{n} blocos",
        "Everything is already rendered for {lang}.":
            "Tudo já foi gerado para {lang}.",
        "That corpus has no campaigns with narration.":
            "Esse corpus não tem campanhas com narração.",
        "{name} has not been extracted yet. It has to come out of your own":
            "{name} ainda não foi extraído. Precisa sair da sua própria",
        "copy of the game before anything can be said in it.":
            "cópia do jogo antes que se possa dizer qualquer coisa nele.",
        "{campaign} has no audio.": "{campaign} não tem áudio.",
        "{campaign} has partly rendered.": "{campaign} está gerado em parte.",
        "Screens will be recognised and stay":
            "As telas serão reconhecidas e ficarão",
        "silent, except the blocks synthesised during play.":
            "mudas, exceto os blocos sintetizados durante a partida.",
        "`main` is not fully rendered.": "O `main` não está completo.",
        "It holds the text every campaign shares — interface, tiles,":
            "Ele guarda o texto que todas as campanhas compartilham — interface, tiles,",
        "enemies, treasure — and 48.8% of what gets spoken comes from it.":
            "inimigos, tesouros — e 48,8% do que se fala vem dele.",
        "No corpus has been extracted yet.": "Nenhum corpus foi extraído ainda.",
        "jime: run `jime --help` for the flags; the menu needs a terminal.":
            "jime: use `jime --help` para as flags; o menu precisa de um terminal.",

        # --- during a session ---
        #
        # Everything here is imperative or explains a silence. The rest of the
        # runtime output stays English — it is progress chatter, read while
        # something is running rather than acted on.
        "switch to the game now — this starts when it is in front":
            "vá para o jogo agora — começa quando ele estiver na frente",
        "switch to the game now — starting in {n}s":
            "vá para o jogo agora — começa em {n}s",
        "the game has not come forward — watching anyway, and staying quiet "
        "until it does":
            "o jogo não veio para a frente — vou observar mesmo assim, e ficar "
            "calado até que venha",
        "watching. Ctrl+C to stop.": "observando. Ctrl+C para parar.",
        "the game is not in front — nothing on this monitor is being read":
            "o jogo não está na frente — nada neste monitor está sendo lido",
        "resumed": "voltou",
        "{screens} screens settled, {queued} blocks queued":
            "{screens} telas reconhecidas, {queued} blocos enfileirados",
        "ready. I am watching the game.": "pronto. estou observando o jogo.",
        "the game is not in front. nothing is being read.":
            "o jogo não está na frente. nada está sendo lido.",
        "cannot align with the screen": "não bate com a tela",
        "none of it is on the screen": "nada dele está na tela",
        "live synthesis produced nothing": "a síntese ao vivo não produziu nada",
    },
}


def t(text: str, lang: str = "en", **fmt) -> str:
    """Translate, falling back to the English that was written in the code."""
    out = STRINGS.get(lang, {}).get(text, text)
    return out.format(**fmt) if fmt else out


# A language picker should show each language in its own language — nobody
# scanning for their own hunts for "German". These are the endonyms; the game's
# own code for each is the key.
NATIVE_NAME = {
    "cz": "Čeština", "de": "Deutsch", "en": "English", "es": "Español",
    "fr": "Français", "hu": "Magyar", "it": "Italiano", "ko": "한국어",
    "pl": "Polski", "pt": "Português (BR)", "ru": "Русский",
    "uk": "Українська", "zh": "中文",
}


def system_language(known: set[str]) -> str | None:
    """The OS language, if the game speaks it too.

    Only used for the very first screen, which has to be drawn before anyone has
    chosen anything. Guessing from the system is better than defaulting to
    English on a machine that is plainly not English.
    """
    import locale

    try:
        tag = (locale.getlocale()[0] or "") or ""
    except Exception:  # noqa: BLE001
        return None
    code = tag.replace("-", "_").split("_")[0].lower()
    alias = {"cs": "cz"}
    code = alias.get(code, code)
    return code if code in known else None
