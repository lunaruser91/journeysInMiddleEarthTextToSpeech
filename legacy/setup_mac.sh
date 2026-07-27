#!/bin/bash
# setup_mac.sh — prepares the JiME Narrator environment on macOS (Apple Silicon).
# Usage:  bash ~/Downloads/setup_mac.sh
set -uo pipefail

JIME_DIR="$HOME/jime"
VENV="$HOME/jime-venv"
ZIP_GUESS=("$HOME/Downloads/fase2_narrador.zip" "$HOME/Desktop/fase2_narrador.zip")

say() { printf "\n\033[1;36m▸ %s\033[0m\n" "$*"; }
err() { printf "\n\033[1;31m✗ %s\033[0m\n" "$*"; }
ok()  { printf "\033[1;32m  ✓ %s\033[0m\n" "$*"; }

# --------------------------------------------------------------- 1. Homebrew
say "1/6  Homebrew"
if ! command -v brew >/dev/null 2>&1; then
  err "Homebrew not found. Install it with the command below and run this script again:"
  echo '  /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"'
  exit 1
fi
eval "$(brew shellenv)" 2>/dev/null || true
ok "brew at $(command -v brew)"

# --------------------------------------------------------------- 2. ffmpeg
say "2/6  ffmpeg (needs librubberband for the wizard chain)"
if ! command -v ffmpeg >/dev/null 2>&1; then
  brew install ffmpeg
fi
if ffmpeg -hide_banner -filters 2>/dev/null | grep -q rubberband; then
  ok "ffmpeg with rubberband"
else
  err "your ffmpeg has no rubberband filter — run: brew reinstall ffmpeg"
fi

# --------------------------------------------------------------- 3. Python
say "3/6  compatible Python (3.11–3.13; 3.14 has no PyTorch wheels yet)"
PY=""
for c in /opt/homebrew/bin/python3.12 /opt/homebrew/bin/python3.13 /opt/homebrew/bin/python3.11 \
         /usr/local/bin/python3.12 python3.12 python3.13 python3.11; do
  if command -v "$c" >/dev/null 2>&1; then PY="$(command -v "$c")"; break; fi
done
if [ -z "$PY" ]; then
  echo "  installing python@3.12 via brew ..."
  brew install python@3.12
  PY="$(brew --prefix)/bin/python3.12"
fi
ok "using $PY ($("$PY" -V 2>&1))"

# --------------------------------------------------------------- 4. venv
say "4/6  virtual environment at $VENV"
if [ -d "$VENV" ]; then
  echo "  already exists — recreating to guarantee the right Python version"
  rm -rf "$VENV"
fi
"$PY" -m venv "$VENV" || { err "failed to create the venv"; exit 1; }
# shellcheck disable=SC1091
source "$VENV/bin/activate"
python -m pip install -q -U pip wheel "setuptools<81"
ok "venv ready ($(python -V 2>&1))"

say "5/6  installing PyTorch and Chatterbox (a few minutes, ~2 GB)"
pip install -q torch torchaudio || { err "torch failed"; exit 1; }
pip install -q chatterbox-tts resemble-perth || { err "chatterbox failed"; exit 1; }
python - <<'PY'
import torch
print(f"  torch {torch.__version__} | MPS available: {torch.backends.mps.is_available()}")
import perth
assert perth.PerthImplicitWatermarker is not None, "perth broken — setuptools>=81?"
from chatterbox.mtl_tts import ChatterboxMultilingualTTS
print("  chatterbox OK")
PY

# --------------------------------------------------------------- 6. files
say "6/6  project files at $JIME_DIR"
mkdir -p "$JIME_DIR"
ZIP=""
for z in "${ZIP_GUESS[@]}"; do [ -f "$z" ] && ZIP="$z" && break; done
if [ -z "$ZIP" ]; then
  ZIP="$(find "$HOME/Downloads" "$HOME/Desktop" -maxdepth 2 -name 'fase2_narrador*.zip' 2>/dev/null | head -1)"
fi
if [ -n "$ZIP" ]; then
  rm -rf /tmp/_f2 && mkdir -p /tmp/_f2
  unzip -qo "$ZIP" -d /tmp/_f2
  cp -R /tmp/_f2/fase2/* "$JIME_DIR"/ 2>/dev/null || cp -R /tmp/_f2/* "$JIME_DIR"/
  ok "extracted from $ZIP"
else
  err "could not find fase2_narrador.zip in Downloads/Desktop — move it there and run again"
fi

cd "$JIME_DIR" || exit 1
echo
ls -1
echo
if [ -f corpus/corpus_pt.json ] && [ -f render_corpus.py ] && [ -f ref/REF_paginasrecolhidas.wav ]; then
  say "Plan for the Bones of Arnor campaign"
  python render_corpus.py corpus/corpus_pt.json --campaign bonesofarnor --dry-run
  cat <<'EOF'

────────────────────────────────────────────────────────────────
All set. From here on, always in this order:

  source ~/jime-venv/bin/activate
  cd ~/jime

  # 20-block test — measures the real RTF and lets you listen
  python render_corpus.py corpus/corpus_pt.json --campaign bonesofarnor --limit 20 --device mps

  # the whole campaign
  caffeinate -i python render_corpus.py corpus/corpus_pt.json --campaign bonesofarnor --device mps

The audio lands in ~/jime/audio/bonesofarnor/. You can interrupt with Ctrl-C:
the cache is keyed by hash, so running again resumes where it stopped.
────────────────────────────────────────────────────────────────
EOF
else
  err "files missing in $JIME_DIR — check the zip contents"
fi
