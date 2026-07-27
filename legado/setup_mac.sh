#!/bin/bash
# setup_mac.sh — prepara o ambiente do Narrador JiME no macOS (Apple Silicon).
# Uso:  bash ~/Downloads/setup_mac.sh
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
  err "Homebrew não encontrado. Instale com o comando abaixo e rode este script de novo:"
  echo '  /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"'
  exit 1
fi
eval "$(brew shellenv)" 2>/dev/null || true
ok "brew em $(command -v brew)"

# --------------------------------------------------------------- 2. ffmpeg
say "2/6  ffmpeg (precisa de librubberband para a cadeia de mago)"
if ! command -v ffmpeg >/dev/null 2>&1; then
  brew install ffmpeg
fi
if ffmpeg -hide_banner -filters 2>/dev/null | grep -q rubberband; then
  ok "ffmpeg com rubberband"
else
  err "seu ffmpeg não tem o filtro rubberband — rode: brew reinstall ffmpeg"
fi

# --------------------------------------------------------------- 3. Python
say "3/6  Python compatível (3.11–3.13; o 3.14 ainda não tem wheels do PyTorch)"
PY=""
for c in /opt/homebrew/bin/python3.12 /opt/homebrew/bin/python3.13 /opt/homebrew/bin/python3.11 \
         /usr/local/bin/python3.12 python3.12 python3.13 python3.11; do
  if command -v "$c" >/dev/null 2>&1; then PY="$(command -v "$c")"; break; fi
done
if [ -z "$PY" ]; then
  echo "  instalando python@3.12 via brew ..."
  brew install python@3.12
  PY="$(brew --prefix)/bin/python3.12"
fi
ok "usando $PY ($("$PY" -V 2>&1))"

# --------------------------------------------------------------- 4. venv
say "4/6  ambiente virtual em $VENV"
if [ -d "$VENV" ]; then
  echo "  já existe — recriando para garantir a versão certa do Python"
  rm -rf "$VENV"
fi
"$PY" -m venv "$VENV" || { err "falha ao criar o venv"; exit 1; }
# shellcheck disable=SC1091
source "$VENV/bin/activate"
python -m pip install -q -U pip wheel "setuptools<81"
ok "venv pronto ($(python -V 2>&1))"

say "5/6  instalando PyTorch e Chatterbox (alguns minutos, ~2 GB)"
pip install -q torch torchaudio || { err "falha no torch"; exit 1; }
pip install -q chatterbox-tts resemble-perth || { err "falha no chatterbox"; exit 1; }
python - <<'PY'
import torch
print(f"  torch {torch.__version__} | MPS disponível: {torch.backends.mps.is_available()}")
import perth
assert perth.PerthImplicitWatermarker is not None, "perth quebrado — setuptools>=81?"
from chatterbox.mtl_tts import ChatterboxMultilingualTTS
print("  chatterbox OK")
PY

# --------------------------------------------------------------- 6. arquivos
say "6/6  arquivos do projeto em $JIME_DIR"
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
  ok "extraído de $ZIP"
else
  err "não achei fase2_narrador.zip em Downloads/Desktop — mova-o para lá e rode de novo"
fi

cd "$JIME_DIR" || exit 1
echo
ls -1
echo
if [ -f corpus/corpus_pt.json ] && [ -f render_corpus.py ] && [ -f ref/REF_paginasrecolhidas.wav ]; then
  say "Plano da campanha Bones of Arnor"
  python render_corpus.py corpus/corpus_pt.json --campaign bonesofarnor --dry-run
  cat <<'EOF'

────────────────────────────────────────────────────────────────
Tudo pronto. Daqui em diante, sempre nesta ordem:

  source ~/jime-venv/bin/activate
  cd ~/jime

  # teste de 20 blocos — mede o RTF real e deixa você ouvir
  python render_corpus.py corpus/corpus_pt.json --campaign bonesofarnor --limit 20 --device mps

  # campanha inteira
  caffeinate -i python render_corpus.py corpus/corpus_pt.json --campaign bonesofarnor --device mps

O áudio sai em ~/jime/audio/bonesofarnor/. Pode interromper com Ctrl-C:
o cache é por hash, e ao rodar de novo ele continua de onde parou.
────────────────────────────────────────────────────────────────
EOF
else
  err "faltam arquivos em $JIME_DIR — confira o conteúdo do zip"
fi
