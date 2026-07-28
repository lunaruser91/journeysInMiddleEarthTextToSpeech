#!/usr/bin/env bash
#
# render_all.sh — render whole campaigns unattended, over several sessions.
#
#   ./render_all.sh                      # bonesofarnor, then main
#   ./render_all.sh main                 # just the shared blocks
#   ./render_all.sh --lang en spreadingwar
#
# This is a long job: measured on this machine at RTF ~3.7, a full campaign plus
# the shared `main` blocks is about 50 hours. That is two days, not one night, so
# the script is built to be stopped and resumed rather than to run in one go.
#
# ## What makes it resumable
#
# The renderer skips any block whose .opus already exists, and rewrites the
# manifest every 10 blocks and again on Ctrl+C. So an interrupted run loses at
# most the block being generated, and running this again picks up where it left
# off. There is nothing to clean up first.
#
# ## Order, and why
#
# Campaign text comes before `main` by default. The 198 most common shared blocks
# are usually already rendered, so the campaign's own text is what actually turns
# more adventures from silent into narrated. Rendering `main` first would spend a
# day and a half before a single new adventure could be played.
#
# ## Sleep
#
# `caffeinate -i` blocks idle sleep, which is what would otherwise stop this an
# hour after you walk away. It does NOT stop a laptop from sleeping when the lid
# closes: leave the lid open, or run in clamshell with power and an external
# display connected.
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
        -h|--help) sed -n '2,36p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'; exit 0 ;;
        *) args+=("$1"); shift ;;
    esac
done
[[ ${#args[@]} -eq 0 ]] && args=(bonesofarnor main)

[[ -x "$PY" ]] || { echo "no interpreter at $PY — set JIME_PYTHON"; exit 1; }

STAMP="$(date +%Y%m%d-%H%M)"
LOG="$ROOT/output/render-$STAMP.log"
mkdir -p "$ROOT/output"

# Progress is measured in seconds of audio produced, not in blocks. Blocks vary
# from 8 to 150 words, so a block count says 88% done while a quarter of the
# speech is still missing — which is exactly what happened while measuring this.
progress() {
    "$PY" - "$ROOT" <<'PYEOF'
import pathlib, subprocess, sys
root = pathlib.Path(sys.argv[1])
files = list((root / "output" / "audio").rglob("*.opus"))
total = 0.0
for f in files:
    out = subprocess.run(["ffprobe", "-v", "error", "-show_entries",
                          "format=duration", "-of", "csv=p=0", str(f)],
                         capture_output=True, text=True).stdout.strip()
    total += float(out) if out else 0.0
print(f"{len(files)} blocks, {total/60:.1f} min of speech")
PYEOF
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
        --lang "$LANG_CODE" --campaign "$campaign" --check-pace 2>&1 \
        | tee -a "$LOG" \
        | grep --line-buffered -E '^\s+\[[0-9]+/|^\[end\]|^\[plan\]|failure'
    status=${PIPESTATUS[0]}
    if [[ $status -ne 0 ]]; then
        say "$campaign stopped with status $status — resume by running this again"
        say "$(progress)"
        exit "$status"
    fi
    say "$campaign done: $(progress)"
done

say ""
say "all done: $(progress)"
say "listen:  $PY player.py --manifest output/audio --all"
