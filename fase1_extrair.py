#!/usr/bin/env python3
"""
jime_corpus.py — Fase 1 do Narrador JiME (versão final, pós-descoberta).

O app guarda a localização em AssetBundles Unity, um por campanha e idioma,
mapeados em StreamingAssets/bundles/manifest.dat (JSON puro). Dentro de cada
bundle há um único TextAsset em CSV: "KEY,<Idioma>".

Este script:
  1. lê o manifest.dat
  2. seleciona os bundles do idioma escolhido (padrão: pt)
  3. extrai o CSV de cada um com UnityPy
  4. limpa a marcação do jogo ([i], [b], <sprite=...>, etc.)
  5. gera corpus.json + um .csv por campanha + estatísticas

Uso:
  python3 jime_corpus.py <dir_dos_bundles> -o corpus/ [--lang pt] [--keep-markup]

Dependência: pip install UnityPy
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

MARKUP_RE = re.compile(r"\[/?[a-zA-Z][^\]]{0,30}\]")          # [i] [/i] [b] [color=x]
RICHTEXT_RE = re.compile(r"</?[a-zA-Z][^>]{0,60}>")            # <sprite=...> <color> TMP
PLACEHOLDER_RE = re.compile(r"\{[0-9A-Za-z_]{1,30}\}")         # {0} {HERO_NAME}
WS_RE = re.compile(r"[ \t]+")

# chaves que claramente não são narrativa lida em voz alta
UI_KEY_HINTS = ("_BUTTON", "_BTN", "_TOOLTIP", "_LABEL", "_TITLE_SHORT", "_ERROR",
                "_MENU", "_SETTINGS", "_OPTION", "_HUD")


def clean(text: str, keep_markup: bool = False) -> str:
    if not keep_markup:
        text = MARKUP_RE.sub("", text)
        text = RICHTEXT_RE.sub("", text)
    text = text.replace("\\n", "\n").replace("\r\n", "\n")
    text = WS_RE.sub(" ", text)
    return text.strip()


def is_narration(key: str, text: str) -> bool:
    """Heurística: o bloco parece texto de leitura em voz alta?"""
    if any(h in key.upper() for h in UI_KEY_HINTS):
        return False
    words = len(text.split())
    return words >= 8 and any(c in text for c in ".!?…")


def extract_bundle(path: Path) -> tuple[str, str]:
    """Devolve (nome_do_textasset, conteúdo_csv)."""
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
    raise RuntimeError(f"nenhum TextAsset em {path}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("bundles_dir", help="pasta StreamingAssets/bundles")
    ap.add_argument("-o", "--out", default="corpus")
    ap.add_argument("--lang", default="pt")
    ap.add_argument("--keep-markup", action="store_true")
    args = ap.parse_args()

    bdir = Path(args.bundles_dir)
    manifest = json.loads((bdir / "manifest.dat").read_text(encoding="utf-8"))
    wanted = [b for b in manifest["bundleInfos"]
              if b["name"].startswith("localization/") and b["name"].endswith(f"/{args.lang}")]
    if not wanted:
        sys.exit(f"[erro] nenhum bundle de localização para '{args.lang}'")

    out = Path(args.out)
    (out / "csv").mkdir(parents=True, exist_ok=True)

    corpus: dict[str, dict] = {}
    stats = Counter()
    faltando: list[str] = []

    for b in sorted(wanted, key=lambda b: b["name"]):
        campaign = b["name"].split("/")[1]
        f = bdir / b["filename"]
        if not f.exists():
            faltando.append(f"{campaign} ({b['filename']})")
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
            stats["narracao"] += entry["narration"]
            stats["com_placeholder"] += bool(entry["placeholders"])
            stats["palavras"] += entry["words"]

        with (out / "csv" / f"{campaign}_{args.lang}.csv").open("w", newline="", encoding="utf-8") as fh:
            w = csv.writer(fh)
            w.writerow(["key", "narration", "placeholders", "words", "text"])
            for k, e in corpus.items():
                if e["campaign"] == campaign:
                    w.writerow([e["key"], int(e["narration"]),
                                "|".join(e.get("placeholders", [])), e["words"], e["text"]])
        print(f"  {campaign:<16} {name:<28} {n_camp:>5} chaves  (header={header})")

    (out / f"corpus_{args.lang}.json").write_text(
        json.dumps(corpus, ensure_ascii=False, indent=1), encoding="utf-8")

    print("\n[resumo]")
    print(f"  chaves totais .......... {stats['total']:,}")
    print(f"  blocos de narração ..... {stats['narracao']:,}")
    print(f"  com placeholder {{}} .... {stats['com_placeholder']:,}")
    print(f"  palavras (tudo) ........ {stats['palavras']:,}")
    if faltando:
        print(f"  ⚠ bundles ausentes: {', '.join(faltando)}")
    print(f"\n  → {out / f'corpus_{args.lang}.json'}")


if __name__ == "__main__":
    main()
