#!/usr/bin/env python3
"""
jime_extract.py — Phase 1 of the JiME Narrator project.

Extracts text from the Unity assets of the app "The Lord of the Rings: Journeys in
Middle-earth" (Steam desktop build, Unity + Mono). Multiplatform: macOS, Windows, Linux.

Subcommands:
  scan   <data_dir>            inventory of objects by type/file (cheap, run it first)
  dump   <data_dir> -o out/    exports TextAsset (raw + decode attempt) and MonoBehaviour
  key    <Assembly-CSharp.dll> looks for candidate (de)obfuscation constants in the IL
  deobf  <file.bin>            tries N deobfuscation heuristics and shows what became text

Dependencies: pip install UnityPy dnfile
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import zlib
from collections import Counter, defaultdict
from pathlib import Path

# --------------------------------------------------------------------------- #
# asset location
# --------------------------------------------------------------------------- #

DATA_DIR_HINTS = [
    # macOS (Steam)
    "~/Library/Application Support/Steam/steamapps/common/Journeys in Middle-earth/"
    "JiME.app/Contents/Resources/Data",
    "~/Documents/journeys/Data",
    # Windows (Steam)
    r"C:\Program Files (x86)\Steam\steamapps\common\Journeys in Middle-earth\JiME_Data",
]

ASSET_PATTERNS = (
    "resources.assets",
    "sharedassets*.assets",
    "level*",
    "globalgamemanagers*",
    "*.bundle",
    "*.unity3d",
    "data.unity3d",
)


def find_data_dir(explicit: str | None) -> Path:
    if explicit:
        p = Path(os.path.expanduser(explicit))
        if not p.is_dir():
            sys.exit(f"[error] not a directory: {p}")
        return p
    for hint in DATA_DIR_HINTS:
        p = Path(os.path.expanduser(hint))
        if p.is_dir():
            print(f"[ok] Data dir found automatically: {p}")
            return p
    sys.exit(
        "[error] could not find the game's Data directory. Pass the path explicitly.\n"
        "  macOS:   '.../Journeys in Middle-earth.app/Contents/Resources/Data'\n"
        "  Windows: '...\\Journeys in Middle-earth\\JiME_Data'"
    )


def asset_files(data_dir: Path) -> list[Path]:
    seen: dict[str, Path] = {}
    for pat in ASSET_PATTERNS:
        for f in data_dir.glob(pat):
            if f.is_file() and not f.name.endswith((".resS", ".resource", ".info")):
                seen[str(f)] = f
    # StreamingAssets is usually plain text — worth listing separately
    return sorted(seen.values(), key=lambda p: -p.stat().st_size)


# --------------------------------------------------------------------------- #
# scan
# --------------------------------------------------------------------------- #

def cmd_scan(args) -> None:
    import UnityPy

    data_dir = find_data_dir(args.data_dir)
    files = asset_files(data_dir)
    print(f"\n[scan] {len(files)} asset file(s) in {data_dir}\n")

    sa = data_dir / "StreamingAssets"
    if sa.is_dir():
        plain = [p for p in sa.rglob("*") if p.is_file()]
        print(f"[!] StreamingAssets exists with {len(plain)} file(s) — "
              f"content here is usually plain text, no ripper needed:")
        for p in plain[:25]:
            print(f"      {p.relative_to(sa)}  ({p.stat().st_size:,} B)")
        print()

    grand = Counter()
    for f in files:
        try:
            env = UnityPy.load(str(f))
        except Exception as e:  # noqa: BLE001
            print(f"  {f.name:<28} ERROR: {type(e).__name__}: {e}")
            continue
        types = Counter(o.type.name for o in env.objects)
        grand.update(types)
        interesting = {k: v for k, v in types.items()
                       if k in ("TextAsset", "MonoBehaviour", "MonoScript", "AudioClip")}
        print(f"  {f.name:<28} {f.stat().st_size/1e6:7.1f} MB  "
              f"{sum(types.values()):6d} objects  {interesting}")

    print("\n[total by type]")
    for t, n in grand.most_common(20):
        print(f"  {t:<28} {n}")
    print("\nIf there are many TextAssets, run:  jime_extract.py dump <data_dir> -o out/")


# --------------------------------------------------------------------------- #
# dump
# --------------------------------------------------------------------------- #

PT_HINTS = ("você", "não", "ção", "os vivos", "espectro", "herdeiro", "aventura")


def looks_like_text(b: bytes) -> tuple[bool, str]:
    """Heuristic: does this look like readable text in utf-8/latin-1?"""
    for enc in ("utf-8-sig", "utf-8", "utf-16", "latin-1"):
        try:
            s = b.decode(enc)
        except (UnicodeDecodeError, UnicodeError):
            continue
        printable = sum(ch.isprintable() or ch in "\r\n\t" for ch in s)
        if len(s) and printable / len(s) > 0.90:
            return True, s
    return False, ""


def cmd_dump(args) -> None:
    import UnityPy

    data_dir = find_data_dir(args.data_dir)
    out = Path(args.out)
    (out / "raw").mkdir(parents=True, exist_ok=True)
    (out / "text").mkdir(parents=True, exist_ok=True)
    (out / "mono").mkdir(parents=True, exist_ok=True)

    manifest: list[dict] = []
    stats = Counter()

    for f in asset_files(data_dir):
        try:
            env = UnityPy.load(str(f))
        except Exception as e:  # noqa: BLE001
            print(f"[skip] {f.name}: {e}")
            continue

        for obj in env.objects:
            if obj.type.name == "TextAsset":
                try:
                    d = obj.read()
                except Exception as e:  # noqa: BLE001
                    stats["textasset_erro"] += 1
                    continue
                name = getattr(d, "m_Name", None) or getattr(d, "name", None) or f"unnamed_{obj.path_id}"
                safe = re.sub(r"[^\w.\-]+", "_", str(name))[:120]
                raw = getattr(d, "m_Script", None) or getattr(d, "script", b"")
                if isinstance(raw, str):
                    raw = raw.encode("utf-8", "surrogateescape")
                (out / "raw" / f"{safe}.bin").write_bytes(raw)

                ok, s = looks_like_text(raw)
                if ok:
                    (out / "text" / f"{safe}.txt").write_text(s, encoding="utf-8")
                    stats["textasset_legivel"] += 1
                else:
                    stats["textasset_obfuscado"] += 1
                manifest.append({
                    "kind": "TextAsset", "name": str(name), "file": f.name,
                    "path_id": obj.path_id, "bytes": len(raw), "readable": ok,
                    "pt_hint": ok and any(h in s.lower() for h in PT_HINTS),
                })

            elif obj.type.name == "MonoBehaviour" and args.mono:
                try:
                    tree = obj.read_typetree()
                except Exception:  # noqa: BLE001
                    stats["mono_sem_typetree"] += 1
                    continue
                blob = json.dumps(tree, ensure_ascii=False, default=str)
                # only keep what has a long string (narration candidate)
                if re.search(r'"[^"]{80,}"', blob):
                    (out / "mono" / f"{obj.path_id}.json").write_text(blob, encoding="utf-8")
                    stats["mono_com_texto"] += 1

    (out / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

    print("\n[summary]")
    for k, v in stats.most_common():
        print(f"  {k:<24} {v}")
    legiveis = [m for m in manifest if m["readable"]]
    print(f"\n  TextAssets: {len(manifest)} | readable: {len(legiveis)} | "
          f"with pt-BR hint: {sum(m['pt_hint'] for m in manifest)}")
    print(f"  manifest: {out/'manifest.json'}")
    for m in sorted(manifest, key=lambda m: -m["bytes"])[:15]:
        flag = "TEXT" if m["readable"] else "obfs"
        print(f"   {flag}  {m['bytes']:>10,} B  {m['name']}  ({m['file']})")
    if stats["textasset_obfuscado"]:
        print("\n  → obfuscated assets found. Run 'key' on Assembly-CSharp.dll, then 'deobf'.")


# --------------------------------------------------------------------------- #
# key — looks for the obfuscation constant in the IL
# --------------------------------------------------------------------------- #

NAME_HINTS = ("obfusc", "deobfusc", "decrypt", "encrypt", "scramble", "xor",
              "localiz", "textasset", "loadtext", "unscramble")


def cmd_key(args) -> None:
    import dnfile
    from dnfile.mdtable import MethodDefRow  # noqa: F401  (imported for clarity)

    dll = Path(os.path.expanduser(args.dll))
    pe = dnfile.dnPE(str(dll))
    print(f"[key] {dll.name}: {pe.net.mdtables.MethodDef.rows if pe.net.mdtables.MethodDef else 0} methods\n")

    # 1) methods with a suspicious name
    hits = []
    md = pe.net.mdtables.MethodDef
    if md:
        for i, row in enumerate(md):
            nm = str(row.Name).lower()
            if any(h in nm for h in NAME_HINTS):
                hits.append((i, str(row.Name)))
    print(f"[1] methods with a suspicious name: {len(hits)}")
    for i, nm in hits[:40]:
        print(f"      #{i}  {nm}")

    # 2) large hardcoded integers in the code blob (ldc.i4 <imm32> heuristic)
    data = dll.read_bytes()
    cands = Counter()
    for m in re.finditer(rb"\x20(....)", data, re.S):  # 0x20 = ldc.i4 <int32>
        val = int.from_bytes(m.group(1), "little", signed=True)
        if 1_000_000 <= val <= 2_000_000_000:
            cands[val] += 1
    print(f"\n[2] candidate int32 constants (ldc.i4), most frequent:")
    for v, n in cands.most_common(25):
        note = "  <-- known key from Mansions of Madness" if v == 68264378 else ""
        print(f"      {v:>12}  0x{v & 0xFFFFFFFF:08X}  x{n}{note}")
    print("\n  Keep the first 5-10 and test them with 'deobf --keys'.")
    print("  To read the C# directly, open the DLL in ILSpy/dnSpy and look for "
          "TextAsset/Localization/Deobfuscate.")


# --------------------------------------------------------------------------- #
# deobf — heuristics
# --------------------------------------------------------------------------- #

def _score(b: bytes) -> float:
    ok, s = looks_like_text(b)
    if not ok:
        return 0.0
    low = s.lower()
    bonus = sum(2.0 for h in PT_HINTS if h in low)
    return min(len(s), 4000) / 4000 + bonus


def cmd_deobf(args) -> None:
    blob = Path(args.file).read_bytes()
    keys = [int(k) for k in (args.keys or "").split(",") if k.strip()] or [68264378]
    results: list[tuple[float, str, bytes]] = []

    def add(label: str, data: bytes) -> None:
        results.append((_score(data), label, data))

    add("raw", blob)

    # raw zlib / gzip / deflate
    for label, fn in (("zlib", lambda d: zlib.decompress(d)),
                      ("deflate", lambda d: zlib.decompress(d, -15)),
                      ("gzip", lambda d: zlib.decompress(d, 16 + zlib.MAX_WBITS))):
        try:
            add(label, fn(blob))
        except Exception:  # noqa: BLE001
            pass

    # 1-byte XOR
    for k in range(256):
        add(f"xor1:{k}", bytes(c ^ k for c in blob[:8000]))

    # XOR with the int's 4 bytes (LE and BE) + "rolling key" variation
    for key in keys:
        for order in ("little", "big"):
            kb = key.to_bytes(4, order, signed=False)
            add(f"xor4:{key}:{order}",
                bytes(c ^ kb[i % 4] for i, c in enumerate(blob[:8000])))
        # System.Random(seed)-style PRNG — same as the pattern in FFG apps
        try:
            rnd = _net_random(key)
            add(f"netrandom:{key}",
                bytes(c ^ rnd.next_byte() for c in blob[:8000]))
        except Exception:  # noqa: BLE001
            pass

    # constant addition/subtraction
    for k in (1, 2, 3, 7, 13, 42, 128):
        add(f"sub:{k}", bytes((c - k) & 0xFF for c in blob[:8000]))
        add(f"add:{k}", bytes((c + k) & 0xFF for c in blob[:8000]))

    results.sort(key=lambda t: -t[0])
    print(f"[deobf] {args.file} ({len(blob):,} B) — top 8 hypotheses:\n")
    for score, label, data in results[:8]:
        ok, s = looks_like_text(data)
        preview = (s[:220].replace("\n", " ⏎ ") if ok else data[:60].hex(" "))
        print(f"  score {score:5.2f}  {label:<22} {preview}")
    best = results[0]
    if best[0] > 0.2 and args.out:
        Path(args.out).write_bytes(best[2])
        print(f"\n  best hypothesis ({best[1]}) saved to {args.out}")
    elif best[0] <= 0.2:
        print("\n  No heuristic worked → the logic lives in Assembly-CSharp.dll.\n"
              "  Open it in ILSpy and look for the function that reads the TextAsset.")


class _net_random:
    """Reimplementation of .NET's System.Random (Knuth subtractive), used by the
    obfuscation schemes of FFG apps. Serves to generate the keystream."""

    def __init__(self, seed: int) -> None:
        MBIG, MSEED = 2147483647, 161803398
        self._seed_array = [0] * 56
        subtraction = MSEED - abs(seed) if seed != -2147483648 else MBIG
        mj = subtraction
        self._seed_array[55] = mj
        mk = 1
        for i in range(1, 55):
            ii = (21 * i) % 55
            self._seed_array[ii] = mk
            mk = mj - mk
            if mk < 0:
                mk += MBIG
            mj = self._seed_array[ii]
        for _ in range(4):
            for i in range(1, 56):
                self._seed_array[i] -= self._seed_array[1 + (i + 30) % 55]
                if self._seed_array[i] < 0:
                    self._seed_array[i] += MBIG
        self._inext, self._inextp = 0, 21

    def _sample_int(self) -> int:
        MBIG = 2147483647
        self._inext = 1 if self._inext + 1 >= 56 else self._inext + 1
        self._inextp = 1 if self._inextp + 1 >= 56 else self._inextp + 1
        ret = self._seed_array[self._inext] - self._seed_array[self._inextp]
        if ret == MBIG:
            ret -= 1
        if ret < 0:
            ret += MBIG
        self._seed_array[self._inext] = ret
        return ret

    def next_byte(self) -> int:
        return self._sample_int() % 256


# --------------------------------------------------------------------------- #

def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("scan", help="asset inventory")
    s.add_argument("data_dir", nargs="?")
    s.set_defaults(func=cmd_scan)

    d = sub.add_parser("dump", help="exports TextAsset/MonoBehaviour")
    d.add_argument("data_dir", nargs="?")
    d.add_argument("-o", "--out", default="out")
    d.add_argument("--mono", action="store_true", help="also dump MonoBehaviour with long text")
    d.set_defaults(func=cmd_dump)

    k = sub.add_parser("key", help="finds obfuscation constants in Assembly-CSharp.dll")
    k.add_argument("dll")
    k.set_defaults(func=cmd_key)

    o = sub.add_parser("deobf", help="tests deobfuscation heuristics on a .bin")
    o.add_argument("file")
    o.add_argument("--keys", help="comma-separated list of candidate integers")
    o.add_argument("--out", help="save the best hypothesis to this file")
    o.set_defaults(func=cmd_deobf)

    args = ap.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
