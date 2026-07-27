#!/usr/bin/env python3
"""
fase2_render.py — Fase 2 do Narrador JiME, versão medida.

Diferenças em relação ao render_corpus.py original, cada uma justificada por
medição neste hardware (M5 Pro, MPS, chatterbox-tts 0.1.7) e não por suposição:

  1. `prepare_conditionals` UMA vez, não por frase.
     O generate() do Chatterbox refaz o condicionamento de voz sempre que recebe
     `audio_prompt_path` (mtl_tts.py:269-270). Medido: ~10,7 s por lote de 13
     frases contra ~1,1 s. Ganho real modesto (~3% do relógio), mas é de graça.

  2. NÃO agrupa frases em chunks.
     O briefing propunha juntar frases até ~220 chars para diluir o custo fixo por
     chamada. Medido em ordem contrabalanceada: chunking ficou 11% MAIS LENTO
     (RTF 3,84 contra 3,44). A razão é mecânica: o decode do T3 é autorregressivo
     com atenção eager e cache KV crescente, então dobrar o comprimento mais que
     dobra o custo. O ganho de diluir overhead não compensa. Uma frase por chamada.

  3. Higiene de hooks.
     t3.inference() reconstrói o AlignmentStreamAnalyzer a cada chamada e registra
     3 forward hooks sem remover os anteriores (alignment_stream_analyzer.py:80-84).
     Medido: 69 hooks vivos após 23 frases. Isso NÃO custa tempo mensurável — a
     correção não acelerou nada — mas retém tensores de atenção indefinidamente,
     o que numa maratona de milhares de blocos é um vazamento de memória real.
     Corrigido por higiene, sem alegar ganho de velocidade.

  4. Orçamento de tokens ADAPTATIVO por frase.
     `generate()` fixa max_new_tokens=1000 internamente (mtl_tts.py:297) — 40 s de
     fala. Quando o modelo degenera e não emite EOS, paga os 1000 inteiros: foi o
     que aconteceu com `bonesofarnor:A1_THREAT_1`, que saía com 43,2 s para 43
     palavras. Aqui cada frase recebe o dobro dos tokens que sua contagem de
     palavras prevê, com piso de 250 e teto de 1000.
     Um teto fixo baixo seria pior: medido no corpus (28.044 frases), um teto de
     400 colocaria 166 frases (0,59%) em risco de truncar, e a frase mais longa
     precisa de ~736 tokens. O orçamento adaptativo aperta onde a degeneração é
     provável e dá espaço onde é necessário.
     MEDIDO DEPOIS, em 14 seeds no bloco inteiro: o teto NUNCA é atingido
     (0/56 frases) e as saídas com teto 1000 e com teto adaptativo são idênticas.
     Ou seja, isto é apólice, não conserto — a melhora do A1_THREAT_1 (43,2 s ->
     21 s) veio da seed, não do teto. Mantido porque custa zero e limita o
     prejuízo se a degeneração ocorrer. A defesa real é o --check-ritmo.

  5. Detecção de anomalia de ritmo já durante o render (`--check-ritmo`), com
     re-tentativa automática usando outra seed.

O QUE FOI TESTADO E REJEITADO (não tente de novo sem ler isto):

  * Desligar o AlignmentStreamAnalyzer para recuperar a atenção fundida (SDPA) e
    eliminar 3 cópias GPU->CPU por token. Parecia a maior alavanca: ele força
    `_attn_implementation='eager'` nas 30 camadas do transformer. Medido em teste
    pareado: além de NÃO acelerar, o modelo passou a gerar 26,7 s de áudio onde o
    baseline gerava 14,3 s para o mesmo texto — quase o dobro. O analyzer é o
    freio que interrompe a geração degenerada; sem ele o modelo diverge em cauda
    longa. Custa caro e é load-bearing.

  * `output_hidden_states=False` isoladamente. O backend só usa
    `hidden_states[-1]`, que é `last_hidden_state` (t3_hf_backend.py:93,103), então
    parece desperdício puro — mas não foi medido isoladamente e o ganho previsto
    (dezenas de MB por chamada) é pequeno perto do decode. Fica anotado, não feito.

Cache, DSP, manifest e retomada continuam idênticos ao original — inclusive o
DSP_VERSION, para não invalidar áudio já renderizado.

Uso:
    python3 fase2_render.py corpus/corpus_pt.json -o audio/ \
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

import glifos

# --------------------------------------------------------------------------- #
# receita de voz — mude DSP_VERSION sempre que mexer na cadeia, senão o cache
# devolve áudio velho e você passa horas depurando um fantasma
# --------------------------------------------------------------------------- #

PITCH = 0.95   # 1.0 = sem mudança; menor = mais grave (formantes acompanham)
TEMPO = 0.96   # menor = mais lento

_CORPO = (
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
# Velocidade da narração. 1.0 é o ritmo cru do modelo (~118 palavras/min), que
# soa arrastado. 1.30 dá ~137 ppm — abaixo do audiobook comercial (150-160), que
# é o que se quer num narrador de fantasia: pausado, mas não sonolento.
# Escolhido de ouvido, comparando amostras a 1.12 / 1.25 / 1.40.
#
# Entra no DSP_VERSION porque muda o áudio: sem isso o cache devolveria a versão
# antiga e você passaria horas procurando um fantasma (armadilha nº 1 do briefing).
VELOCIDADE = 1.30


def dsp_version() -> str:
    base = "mago-v1" if HAS_RB else "mago-v1f"
    return f"{base}-v{VELOCIDADE:.2f}"


def wizard_chain(sr: int) -> str:
    """Cadeia de mago. Usa rubberband se existir; senão, o truque do asetrate,
    que desloca pitch e formantes juntos — sonicamente equivalente a
    'formant=shifted' — seguido de atempo para restaurar a duração."""
    if HAS_RB:
        return (f"rubberband=pitch={PITCH}:formant=shifted:tempo={TEMPO*VELOCIDADE}"
                f":pitchq=quality:transients=smooth,{_CORPO}")
    atempo = (TEMPO * VELOCIDADE) / PITCH
    return (f"asetrate={int(sr * PITCH)},aresample={sr},"
            f"atempo={atempo:.5f},{_CORPO}")


PAUSA_FRASE = 0.30      # segundos entre frases
PAUSA_PARAGRAFO = 0.45  # segundos extras entre parágrafos
SEED = 1234

SENT_SPLIT = re.compile(r"(?<=[.!?…])\s+")


def normalize_for_match(s: str) -> str:
    """Mesma normalização que a Fase 3 vai usar no OCR: sem acento, sem pontuação.

    ATENÇÃO à assimetria com a narração: o áudio DIZ "testa Agilidade", mas a tela
    MOSTRA o ícone, e o OCR não vai ler palavra nenhuma ali. Então o índice de
    casamento é construído a partir do texto com os glifos REMOVIDOS, não
    substituídos — casar contra a palavra falada nunca daria certo.
    """
    s = glifos.PUA.sub(" ", s)
    s = unicodedata.normalize("NFKD", s)
    s = "".join(c for c in s if not unicodedata.combining(c))
    s = s.casefold()
    s = re.sub(r"[^\w\s]", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def cache_key(text: str, ref: Path, params: dict) -> str:
    """Hash do texto FALADO — se o léxico de glifos mudar, o áudio é regerado."""
    h = hashlib.blake2b(digest_size=10)
    h.update(f"chatterbox-mtl|pt|{ref.name}|{dsp_version()}|{json.dumps(params, sort_keys=True)}|{text}"
             .encode("utf-8"))
    return h.hexdigest()


def split_sentences(text: str) -> list[tuple[str, bool]]:
    """Devolve (frase, é_fim_de_parágrafo). Uma chamada de TTS por frase —
    agrupar em blocos maiores foi medido e é mais lento (ver docstring)."""
    out = []
    for para in [p for p in text.split("\n") if p.strip()]:
        sents = [s.strip() for s in SENT_SPLIT.split(para) if s.strip()]
        for i, s in enumerate(sents):
            out.append((s, i == len(sents) - 1))
    return out


# --------------------------------------------------------------------------- #

# o tokenizador de fala do s3 roda a 25 Hz; 25 tokens ≈ 1 s de áudio
TOKENS_POR_SEGUNDO = 25
PALAVRAS_POR_SEGUNDO = 2.31   # medido no render de produção (127 ppm)


def orcamento_tokens(frase: str, folga: float, piso: int, teto: int) -> int:
    """Quantos tokens de fala esta frase deveria precisar, com folga.

    Um teto FIXO é a escolha errada. O `generate()` do Chatterbox fixa
    max_new_tokens=1000 (mtl_tts.py:297), que são 40 s de fala: quando o modelo
    degenera e não emite EOS, ele paga os 1000 inteiros. Mas baixar o teto para
    um valor único trunca as frases longas — medido no corpus, um teto de 400
    colocaria 166 frases (0,59%) em risco de perder palavras, e a frase mais
    longa precisa de ~736 tokens.

    A solução é orçar por frase: a mediana (11 palavras) ganha o piso, e a cauda
    longa ganha o que precisa. O efeito prático é limitar o dano da degeneração
    justamente onde ela é mais provável, sem arriscar truncar nada.
    """
    previsto = len(frase.split()) / PALAVRAS_POR_SEGUNDO * TOKENS_POR_SEGUNDO
    return int(max(piso, min(teto, previsto * folga)))


def install_t3_patches(model, orcamento) -> None:
    """Duas correções aplicadas no t3.inference, que é por onde tudo passa.

    1. Higiene de hooks. t3.inference() reconstrói o AlignmentStreamAnalyzer a
       cada chamada e registra 3 forward hooks sem remover os anteriores. Não
       acelera (medido), mas cada hook retido segura tensores de atenção; ao
       longo de milhares de blocos isso vira vazamento de memória.

    2. Teto de tokens por frase. `generate()` não expõe max_new_tokens, então o
       orçamento é imposto aqui, uma camada abaixo. `orcamento` é uma caixa de um
       elemento que o laço de síntese atualiza antes de cada frase.
    """
    attn = [l.self_attn for l in model.t3.tfmr.layers]
    inner = model.t3.inference

    def patched(*a, **k):
        for m in attn:
            m._forward_hooks.clear()
        k["max_new_tokens"] = orcamento[0]
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


def aplicar_glifos(corpus_path: Path, blocks: dict, idioma: str) -> int:
    """Anexa a cada bloco o campo `fala`: o texto com os ícones virados palavra."""
    corpus = json.loads(corpus_path.read_text(encoding="utf-8"))
    mapa = glifos.mapa_do_corpus(corpus)
    n = 0
    for v in blocks.values():
        # ordem: glifos primeiro (podem trazer números), depois os números
        fala = glifos.substituir(v["text"], mapa, idioma)
        v["fala"] = glifos.numeros_por_extenso(fala, idioma)
        if v["fala"] != v["text"]:
            n += 1
    return n


def estimate(blocks: dict, rtf: float) -> None:
    words = sum(v["words"] for v in blocks.values())
    audio_h = words / 140 / 60          # ~140 palavras/min num narrador pausado
    print(f"  blocos ................ {len(blocks):,}")
    print(f"  palavras .............. {words:,}")
    print(f"  áudio estimado ........ {audio_h:.1f} h")
    print(f"  tempo de render ....... {audio_h * rtf:.1f} h  (RTF {rtf})")
    print(f"  tamanho em opus 48k ... ~{audio_h * 3600 * 6 / 1024:.0f} MB")


def main() -> None:
    # `global` tem de vir antes de QUALQUER leitura de VELOCIDADE nesta função —
    # o argparse abaixo usa a global como valor padrão, e o Python rejeita a
    # declaração posterior com SyntaxError.
    global VELOCIDADE

    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("corpus", type=Path)
    ap.add_argument("-o", "--out", type=Path,
                    default=Path(__file__).resolve().parent / "saida" / "audio",
                    help="pasta de saída (padrão: saida/audio no repositório)")
    ap.add_argument("--ref", type=Path, default=Path(__file__).resolve().parent / "ref" / "REF_paginasrecolhidas.wav",
                    help="clipe de referência para clonagem (10-15 s, limpo)")
    ap.add_argument("--device", default="auto", choices=["auto", "mps", "cuda", "cpu"])
    ap.add_argument("--campaign", help="renderizar só uma campanha")
    ap.add_argument("--limit", type=int, help="parar depois de N blocos (teste)")
    ap.add_argument("--key", action="append", default=[],
                    help="renderizar só estas chaves (pode repetir). É o que "
                         "permite a renderização sob demanda da Fase 3.")
    ap.add_argument("--exaggeration", type=float, default=0.45,
                    help="0.3-0.7; mais baixo = leitura mais contida/narrativa")
    ap.add_argument("--cfg-weight", type=float, default=0.35,
                    help="mais baixo = ritmo mais lento e deliberado")
    ap.add_argument("--folga-tokens", type=float, default=2.0,
                    help="multiplicador sobre os tokens previstos para a frase. "
                         "2.0 dá o dobro do necessário antes de cortar")
    ap.add_argument("--tokens-piso", type=int, default=250,
                    help="orçamento mínimo por frase, em tokens (~10 s de fala)")
    ap.add_argument("--tokens-teto", type=int, default=1000,
                    help="orçamento máximo por frase; 1000 é o padrão do modelo")
    ap.add_argument("--check-ritmo", action="store_true",
                    help="mede palavras/s de cada bloco e regenera os degenerados")
    ap.add_argument("--ritmo-min", type=float, default=1.45,
                    help="palavras/s de fala abaixo do qual o bloco é suspeito")
    ap.add_argument("--retries", type=int, default=2,
                    help="tentativas extras, com outra seed, para blocos suspeitos")
    ap.add_argument("--include-dynamic", action="store_true",
                    help="renderizar também blocos com {0} (não recomendado)")
    ap.add_argument("--velocidade", type=float, default=VELOCIDADE,
                    help=f"padrão {VELOCIDADE} (~137 palavras/min). 1.0 é o ritmo "
                         "cru do modelo (~118 ppm). Entra no cache: mudar re-renderiza.")
    ap.add_argument("--lang", default="pt",
                    help="idioma do léxico de glifos (ver glifos.py)")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--rtf", type=float, default=3.4, help="RTF assumido no --dry-run")
    args = ap.parse_args()

    VELOCIDADE = args.velocidade

    blocks = load_blocks(args.corpus, args.campaign, args.include_dynamic)
    if args.key:
        blocks = {k: v for k, v in blocks.items() if k in args.key}
        faltando = [k for k in args.key if k not in blocks]
        if faltando:
            print(f"[aviso] chave(s) não encontrada(s) ou sem narração: {faltando}")
    tocados = aplicar_glifos(args.corpus, blocks, args.lang)
    print(f"[glifos] {tocados} de {len(blocks)} blocos tinham ícones do jogo no texto")
    if args.limit:
        blocks = dict(list(blocks.items())[:args.limit])

    print(f"[plano] {args.corpus}" + (f" | campanha={args.campaign}" if args.campaign else ""))
    estimate(blocks, args.rtf)
    if args.dry_run:
        return
    if not args.ref.exists():
        sys.exit(f"[erro] referência não encontrada: {args.ref}")

    import torch
    import torchaudio as ta
    from chatterbox.mtl_tts import ChatterboxMultilingualTTS

    device = args.device
    if device == "auto":
        device = ("mps" if torch.backends.mps.is_available()
                  else "cuda" if torch.cuda.is_available() else "cpu")
    print(f"[dsp] {'rubberband' if HAS_RB else 'asetrate (fallback, sem rubberband)'} "
          f"| versão {dsp_version()} | velocidade {VELOCIDADE:.2f}x")
    print(f"[modelo] carregando em {device} ...")
    t0 = time.time()
    model = ChatterboxMultilingualTTS.from_pretrained(device=device)

    orcamento = [args.tokens_teto]      # atualizado antes de cada frase
    install_t3_patches(model, orcamento)

    # condicionais UMA vez — não uma vez por frase, como fazia o original
    t_cond = time.time()
    model.prepare_conditionals(str(args.ref), exaggeration=args.exaggeration)
    print(f"[voz] condicionais preparadas em {time.time()-t_cond:.1f}s (uma vez só)")
    torch.manual_seed(SEED)
    print(f"[modelo] pronto em {time.time()-t0:.0f}s")

    params = {"exaggeration": args.exaggeration, "cfg_weight": args.cfg_weight,
              "pausa": [PAUSA_FRASE, PAUSA_PARAGRAFO], "seed": SEED}

    args.out.mkdir(parents=True, exist_ok=True)
    manifest_path = args.out / "manifest.json"
    manifest = json.loads(manifest_path.read_text()) if manifest_path.exists() else {}

    done = skipped = failed = regerados = 0
    t_start = time.time()
    total = len(blocks)

    def sintetiza(v: dict, seed: int):
        """Gera o bloco inteiro e devolve (waveform, segundos_de_fala)."""
        torch.manual_seed(seed)
        chunks, fala = [], 0.0
        for sent, fim_para in split_sentences(v["fala"]):
            orcamento[0] = orcamento_tokens(sent, args.folga_tokens,
                                            args.tokens_piso, args.tokens_teto)
            wav = model.generate(sent, language_id="pt",
                                 exaggeration=args.exaggeration,
                                 cfg_weight=args.cfg_weight)
            fala += wav.shape[-1] / model.sr
            chunks.append(wav)
            chunks.append(torch.zeros(1, int(model.sr * PAUSA_FRASE)))
            if fim_para:
                chunks.append(torch.zeros(1, int(model.sr * PAUSA_PARAGRAFO)))
        return torch.cat(chunks, dim=-1), fala

    for i, (key, v) in enumerate(blocks.items(), 1):
        ck = cache_key(v["fala"], args.ref, params)
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
            melhor, melhor_wps = None, -1.0
            for tentativa in range(args.retries + 1 if args.check_ritmo else 1):
                wav, fala = sintetiza(v, SEED + tentativa * 7919)
                wps = v["words"] / max(fala, 1e-6)
                if wps > melhor_wps:
                    melhor, melhor_wps = wav, wps
                if not args.check_ritmo or wps >= args.ritmo_min:
                    break
                regerados += 1
                print(f"    [ritmo] {key[:40]} saiu a {wps:.2f} p/s "
                      f"(limite {args.ritmo_min}); tentando outra seed", flush=True)

            tmp = args.out / f".tmp_{ck}.wav"
            ta.save(str(tmp), melhor, model.sr)
            try:
                subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(tmp),
                                "-af", wizard_chain(model.sr),
                                "-c:a", "libopus", "-b:a", "48k", str(dest)], check=True)
            finally:
                tmp.unlink(missing_ok=True)

            manifest[key] = {"file": rel, "campaign": v["campaign"], "text": v["text"],
                             "norm": normalize_for_match(v["text"]), "words": v["words"],
                             "wps": round(melhor_wps, 2)}
            done += 1
            dt = time.time() - t1
            if done % 10 == 0 or i == total:
                elapsed = time.time() - t_start
                rate = done / max(elapsed, 1)
                eta = (total - i) / max(rate, 1e-6) / 3600
                manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=1),
                                         encoding="utf-8")
                print(f"  [{i}/{total}] {key[:44]:<44} {v['words']:>4}p {dt:5.0f}s "
                      f"| feitos {done} pulados {skipped} | ETA {eta:.1f} h", flush=True)
        except KeyboardInterrupt:
            print("\n[interrompido] o cache preserva tudo — é só rodar de novo.")
            break
        except Exception as e:  # noqa: BLE001
            failed += 1
            print(f"  [falha] {key}: {type(e).__name__}: {e}", flush=True)

    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"\n[fim] renderizados {done} | em cache {skipped} | falhas {failed}"
          + (f" | regerações por ritmo {regerados}" if args.check_ritmo else ""))
    print(f"      {manifest_path}  ({len(manifest)} entradas)")


if __name__ == "__main__":
    main()
