#!/usr/bin/env bash
#
# render_all.sh — render whole campaigns, unattended.
#
#   ./render_all.sh                      # bonesofarnor, then main
#   ./render_all.sh main                 # just the shared blocks
#   ./render_all.sh --lang en spreadingwar
#
# `main` holds the text every campaign shares: interface, tile descriptions,
# enemy activations, treasure. Roughly half of what gets spoken in a session
# comes from there — measured at 48.8% across 627 screens rebuilt from real game
# logs — so a campaign rendered without it leaves half the game silent.
#
# The whole job is well under an hour at the measured RTF of ~0.05. It used to be
# fifty hours, which is why this script exists; it is still built to be stopped
# and resumed, because that costs nothing to keep.
#
# ## Resuming
#
# A block whose .opus already exists is skipped, and the manifest is rewritten
# every 50 blocks and again on Ctrl+C. An interrupted run loses at most the block
# being generated. Run the same command again and it continues; there is nothing
# to clean up first.
#
# ## Sleep
#
# `caffeinate -i` blocks idle sleep. It matters far less than when a run took two
# days, but an interrupted render still has to be restarted and the flag is free.
# It does NOT stop a laptop sleeping when the lid closes.
#
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PY="${JIME_PYTHON:-$HOME/jime-venv/bin/python}"
LANG_CODE="pt"

args=()
while [[ $# -gt 0 ]]; do
    case "$1" in
        --lang) LANG_CODE="$2"; shift 2 ;;
        --lang=*) LANG_CODE="${1#*=}"; shift ;;
        -h|--help) sed -n '2,29p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'; exit 0 ;;
        *) args+=("$1"); shift ;;
    esac
done
[[ ${#args[@]} -eq 0 ]] && args=(bonesofarnor main)

[[ -x "$PY" ]] || { echo "no interpreter at $PY — set JIME_PYTHON"; exit 1; }

mkdir -p "$ROOT/output"
LOG="$ROOT/output/render-$(date +%Y%m%d-%H%M).log"

# Progress is seconds of speech, not blocks. Blocks run from 8 to 150 words, so a
# block count reads 88% done while a quarter of the speech is still missing —
# which is exactly what happened while measuring this.
#
# The numbers come from the manifest, not from ffprobe: duration is words/wps and
# both are already recorded, whereas probing a few thousand files one subprocess
# at a time took longer than the progress line was worth.
progress() {
    "$PY" - "$ROOT" "$LANG_CODE" <<'PY_PROGRESS'
import json, pathlib, sys
root, lang = pathlib.Path(sys.argv[1]), sys.argv[2]
man = root / "output" / f"audio_{lang}" / "manifest.json"
if not man.exists():
    print("nothing rendered yet")
    raise SystemExit
entries = {k: v for k, v in json.loads(man.read_text(encoding="utf-8")).items()
           if not k.startswith("_")}
secs = sum(v["words"] / v["wps"] for v in entries.values() if v.get("wps"))
print(f"{len(entries)} blocks, {secs / 60:.1f} min of speech")
PY_PROGRESS
}

say() { printf '%s | %s\n' "$(date '+%H:%M:%S')" "$*" | tee -a "$LOG"; }

interrupted() {
    say "interrupted — nothing is lost, run this script again to resume"
    say "$(progress)"
    exit 130
}
trap interrupted INT TERM

say "rendering: ${args[*]}  (lang=$LANG_CODE)"
say "log: $LOG"
say "starting from: $(progress)"
say ""

for campaign in "${args[@]}"; do
    say "=== $campaign ==="
    caffeinate -i "$PY" "$ROOT/jime.py" render \
        --lang "$LANG_CODE" --campaign "$campaign" 2>&1 \
        | tee -a "$LOG" \
        | grep --line-buffered -E '^\s+\[[0-9]+/|^\[end\]|^\[voice\]|failure'
    status=${PIPESTATUS[0]}
    if [[ $status -ne 0 ]]; then
        say "$campaign stopped with status $status — run this again to resume"
        say "$(progress)"
        exit "$status"
    fi
    say "$campaign done: $(progress)"
done

say ""
say "all done: $(progress)"
say "listen:   $PY player.py --manifest output/audio_$LANG_CODE --all"
say "audit:    $PY jime.py check --lang $LANG_CODE"
