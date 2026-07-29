#!/usr/bin/env bash
#
# install.sh — the macOS setup in one command.
#
#   curl -fsSL https://raw.githubusercontent.com/lunaruser91/journeysInMiddleEarthTextToSpeech/main/install.sh | bash
#
# Installs what is missing, clones or updates the project, builds the
# environment and checks the result. Safe to run again: everything it does is
# conditional, so a second run updates the project and leaves the rest alone.
#
# That makes it the update command too — there is no separate one.
#
# The counterpart on Windows is install.ps1, which does the same through winget.
#
# The one thing it cannot do for you is grant screen recording. macOS gives that
# through System Settings only, per application, and it is read when a process
# starts — so the Terminal has to be restarted after granting. The script says so
# at the end rather than pretending otherwise.
#
set -euo pipefail

REPO="https://github.com/lunaruser91/journeysInMiddleEarthTextToSpeech.git"
DIR="${JIME_DIR:-$HOME/jime}"
VENV="${JIME_VENV:-$HOME/jime-venv}"

BOLD=$'\033[1m'; GREEN=$'\033[92m'; YELLOW=$'\033[93m'; GRAY=$'\033[90m'
RESET=$'\033[0m'

step() { printf '\n%s== %s%s\n' "$BOLD" "$1" "$RESET"; }
ok()   { printf '   %s%s%s\n' "$GRAY" "$1" "$RESET"; }
die()  { printf '\n%serror: %s%s\n' "$YELLOW" "$1" "$RESET" >&2; exit 1; }

[ "$(uname -s)" = "Darwin" ] || die "this installer is for macOS; on Windows use install.ps1"

printf '%sJourneys in Middle-earth — narrator%s\n' "$BOLD" "$RESET"
printf 'installing to %s%s%s\n' "$BOLD" "$DIR" "$RESET"

# ---------------------------------------------------------------------- tools

step "Tools"

if ! xcode-select -p >/dev/null 2>&1; then
    ok "installing the command line tools — accept the dialog that appears"
    xcode-select --install || true
    # The installer runs in its own window and returns immediately; there is no
    # exit code worth trusting, so wait for the thing it produces.
    until xcode-select -p >/dev/null 2>&1; do sleep 5; done
fi
ok "command line tools present"

if ! command -v brew >/dev/null 2>&1; then
    ok "installing Homebrew — it will ask for your password"
    /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
    # Apple silicon puts it somewhere not on the default PATH
    for candidate in /opt/homebrew/bin/brew /usr/local/bin/brew; do
        [ -x "$candidate" ] && eval "$("$candidate" shellenv)" && break
    done
fi
command -v brew >/dev/null 2>&1 || die "Homebrew was installed but brew is not on the PATH. Open a new terminal and run this again."
ok "homebrew present"

# Test for the command, not for what Homebrew installed. git ships with the
# command line tools, so `brew list git` says no on a machine that plainly has
# git — and installing a second one is both wasteful and confusing.
install_if_missing() {
    local pkg="$1" cmd="$2"
    if command -v "$cmd" >/dev/null 2>&1; then
        ok "$cmd already present ($(command -v "$cmd"))"
    else
        ok "installing $pkg ..."
        brew install "$pkg"
        command -v "$cmd" >/dev/null 2>&1 ||
            die "$pkg was installed but $cmd is not on the PATH"
    fi
}

install_if_missing python@3.13 python3.13
install_if_missing ffmpeg ffmpeg
install_if_missing git git

PYTHON="$(brew --prefix python@3.13)/bin/python3.13"
[ -x "$PYTHON" ] || PYTHON="$(command -v python3.13 || true)"
[ -x "$PYTHON" ] || die "python3.13 was installed but cannot be found"

# -------------------------------------------------------------------- project

step "Project"
if [ -d "$DIR/.git" ]; then
    ok "already cloned, updating"
    git -C "$DIR" pull --ff-only
elif [ -e "$DIR" ]; then
    die "$DIR exists but is not a git clone. Move it aside, or set JIME_DIR."
else
    git clone "$REPO" "$DIR"
fi

# ---------------------------------------------------------------- environment

step "Environment"
if [ ! -x "$VENV/bin/python" ]; then
    "$PYTHON" -m venv "$VENV"
    ok "created $VENV"
else
    ok "already exists"
fi

"$VENV/bin/python" -m pip install --quiet --upgrade pip
"$VENV/bin/python" -m pip install --quiet -e "$DIR[tts,ocr,capture]"
ok "dependencies installed"

# ------------------------------------------------------------------- checking

step "Checking"
(cd "$DIR" && "$VENV/bin/python" selftest.py) || true

# ---------------------------------------------------------------------- ready

printf '\n%sOne thing left, and only you can do it.%s\n' "$YELLOW" "$RESET"
cat <<EOF
The narrator reads what is on screen, and macOS grants that per application.

  System Settings -> Privacy & Security -> Screen Recording -> tick Terminal

Then quit Terminal completely (Cmd+Q) and open it again. The permission is read
when a program starts, so a running terminal keeps the old answer.
EOF

printf '\n%sReady. Start it with:%s\n' "$GREEN" "$RESET"
printf '    cd %s\n' "$DIR"
printf '    %s/bin/python jime.py\n' "$VENV"
printf '\n%sThe first time, in this order: extract the corpus, render the audio,\n' "$GRAY"
printf 'then narrate. The menu asks; there are no flags to remember.%s\n' "$RESET"
