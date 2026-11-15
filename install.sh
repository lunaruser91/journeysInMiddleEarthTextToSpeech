#!/usr/bin/env bash
#
# install.sh — the macOS and Linux setup in one command.
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
# On macOS the one thing it cannot do for you is grant screen recording. macOS
# gives that through System Settings only, per application, and it is read when a
# process starts — so the Terminal has to be restarted after granting. The script
# says so at the end rather than pretending otherwise.
#
# On Linux the one thing it cannot do for you is choose the session type. Capture
# needs X11, and that is picked on the login screen. The script checks and says.
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

OS="$(uname -s)"
case "$OS" in
    Darwin|Linux) ;;
    *) die "this installer is for macOS and Linux; on Windows use install.ps1" ;;
esac

printf '%sJourneys in Middle-earth — narrator%s\n' "$BOLD" "$RESET"
printf 'installing to %s%s%s\n' "$BOLD" "$DIR" "$RESET"

# ---------------------------------------------------------------------- tools

step "Tools"

if [ "$OS" = "Linux" ]; then

# A Python this project can run on: 3.12 or 3.13. Named versions first, because
# on a rolling distribution `python3` is already 3.14, which onnxruntime has no
# wheels for — and the venv module has to be there too, which Debian and Ubuntu
# package separately from the interpreter.
find_python() {
    local candidate
    for candidate in python3.13 python3.12 python3; do
        command -v "$candidate" >/dev/null 2>&1 || continue
        "$candidate" -c 'import sys, venv, ensurepip; sys.exit(not (3, 12) <= sys.version_info[:2] <= (3, 13))' \
            >/dev/null 2>&1 || continue
        command -v "$candidate"
        return 0
    done
    return 1
}

# What is missing, and one line per package manager for getting it: a suitable
# Python with venv, git, and ffmpeg — which brings ffplay, the only player here
# that decodes Opus. Nothing is installed that is already present.
PYTHON="$(find_python || true)"
missing=""
[ -n "$PYTHON" ] || missing="$missing python"
command -v git    >/dev/null 2>&1 || missing="$missing git"
command -v ffmpeg >/dev/null 2>&1 || missing="$missing ffmpeg"
command -v ffplay >/dev/null 2>&1 || missing="$missing ffplay"

# As root where that is needed, and never reading this script's own input: run
# as `curl ... | bash`, the script IS standard input, and a package manager that
# stops to ask something would swallow the rest of it as the answer.
as_root() {
    if [ "$(id -u)" -eq 0 ]; then "$@" </dev/null; else sudo "$@" </dev/null; fi
}

if [ -n "$missing" ]; then
    ok "missing:$missing"
    [ "$(id -u)" -eq 0 ] || ok "installing them needs sudo — it will ask for your password"
    if   command -v apt-get >/dev/null 2>&1; then
        # update first: on a machine that has not installed anything lately the
        # package lists name files the mirrors no longer have
        as_root apt-get update
        as_root apt-get install -y python3 python3-venv git ffmpeg
    elif command -v dnf     >/dev/null 2>&1; then
        # Fedora's own ffmpeg-free is enough; RPM Fusion's ffmpeg satisfies it too
        as_root dnf install -y python3.13 git ffmpeg-free
    elif command -v pacman  >/dev/null 2>&1; then
        as_root pacman -S --needed --noconfirm python git ffmpeg
    elif command -v zypper  >/dev/null 2>&1; then
        as_root zypper --non-interactive install python313 git ffmpeg
    else
        die "no package manager this script knows. Install Python 3.12 or 3.13 (with venv), git and ffmpeg yourself, then run this again."
    fi
    PYTHON="$(find_python || true)"
fi

[ -n "$PYTHON" ] || die "no Python 3.12 or 3.13 with the venv module was found, and this distribution's own python3 is another version.
Install one beside it — for example with uv:

    curl -LsSf https://astral.sh/uv/install.sh | sh
    uv python install 3.13

then run this again with it on the PATH as python3.13."
command -v git    >/dev/null 2>&1 || die "git is still missing"
command -v ffmpeg >/dev/null 2>&1 || die "ffmpeg is still missing"
command -v ffplay >/dev/null 2>&1 ||
    die "ffmpeg is installed but ffplay is not. Some distributions package it separately; without it nothing plays, because nothing else decodes Opus."
ok "python  $PYTHON ($("$PYTHON" -c 'import platform; print(platform.python_version())'))"
ok "git     $(command -v git)"
ok "ffmpeg  $(command -v ffmpeg)"

else   # ---------------------------------------------------------------- macOS

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

fi

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
"$VENV/bin/python" -m pip install --quiet -e "$DIR[tts,ocr,capture]" || {
    # Every dependency ships a ready-made wheel for 64-bit Intel/AMD Linux and
    # for macOS. Anywhere else — ARM Linux, an old glibc — pip compiles UnityPy
    # from source, and the error it prints for a missing compiler is two hundred
    # lines long and ends in a file name.
    [ "$OS" = "Linux" ] && printf '\n%sIf the error above ends in "gcc", pip had to compile a dependency and found\nno compiler. Install one with the Python headers (Debian/Ubuntu:\nbuild-essential python3-dev; Fedora: gcc python3-devel) and run this again.%s\n' "$YELLOW" "$RESET" >&2
    die "the dependencies did not install"
}
ok "dependencies installed"

# ------------------------------------------------------------------- checking

step "Checking"
(cd "$DIR" && "$VENV/bin/python" selftest.py) || true

# ---------------------------------------------------------------------- ready

if [ "$OS" = "Darwin" ]; then
printf '\n%sOne thing left, and only you can do it.%s\n' "$YELLOW" "$RESET"
cat <<EOF
The narrator reads what is on screen, and macOS grants that per application.

  System Settings -> Privacy & Security -> Screen Recording -> tick Terminal

Then quit Terminal completely (Cmd+Q) and open it again. The permission is read
when a program starts, so a running terminal keeps the old answer.
EOF
elif [ "${XDG_SESSION_TYPE:-}" = "wayland" ] || [ -n "${WAYLAND_DISPLAY:-}" ]; then
printf '\n%sOne thing left, and only you can do it.%s\n' "$YELLOW" "$RESET"
cat <<EOF
This is a Wayland session, and the narrator can only read the screen on X11:
Wayland does not let one program see another's window unattended.

  Log out, pick an X11 session on the login screen — on KDE, "Plasma (X11)" —
  and log in again.

Extracting and rendering work as they are. Only narrating needs X11.
EOF
fi

printf '\n%sReady. Start it with:%s\n' "$GREEN" "$RESET"
printf '    cd %s\n' "$DIR"
printf '    %s/bin/python jime.py\n' "$VENV"
printf '\n%sThe first time, in this order: extract the corpus, render the audio,\n' "$GRAY"
printf 'then narrate. The menu asks; there are no flags to remember.%s\n' "$RESET"
