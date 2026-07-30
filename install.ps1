<#
.SYNOPSIS
    Installs the Journeys in Middle-earth narrator on Windows.

.DESCRIPTION
    Turns the four-command setup into one. Installs what is missing, clones or
    updates the project, builds the environment, and checks the result.

    Safe to run again: everything it does is conditional, so a second run
    updates the project and leaves the rest alone.

    Run it without downloading anything first:

        irm https://raw.githubusercontent.com/lunaruser91/journeysInMiddleEarthTextToSpeech/main/install.ps1 | iex

    That form also sidesteps the execution policy, which blocks .ps1 files by
    default and is the first thing that stops people who download the script.

.NOTES
    The PATH is refreshed in-session after each install. Without that, winget
    installs a program and the very next command cannot find it, because this
    shell's PATH was read when it opened — which is exactly what happened the
    first time this setup was walked through by hand.
#>
[CmdletBinding()]
param(
    [string] $Path = "$HOME\jime",
    [string] $Venv = "$HOME\jime-venv",
    [switch] $SkipSelfTest
)

$ErrorActionPreference = 'Stop'
$repo = 'https://github.com/lunaruser91/journeysInMiddleEarthTextToSpeech.git'

function Write-Step { param([string] $Text) Write-Host "`n== $Text" -ForegroundColor Cyan }
function Write-Ok   { param([string] $Text) Write-Host "   $Text" -ForegroundColor DarkGray }

function Update-Path {
    # Machine and user PATH, as they are now rather than when this shell opened
    $env:Path = [Environment]::GetEnvironmentVariable('Path', 'Machine') + ';' +
                [Environment]::GetEnvironmentVariable('Path', 'User')
}

function Install-IfMissing {
    param([string] $Id, [string] $Command, [string] $Label)

    if ($Command -and (Get-Command $Command -ErrorAction SilentlyContinue)) {
        Write-Ok "$Label already installed"
        return
    }
    Write-Ok "installing $Label ..."
    winget install --id $Id -e --accept-source-agreements --accept-package-agreements `
        --disable-interactivity | Out-Null
    Update-Path
    if ($Command -and -not (Get-Command $Command -ErrorAction SilentlyContinue)) {
        throw "$Label was installed but $Command is still not on the PATH. Close this window, open a new one, and run this again."
    }
}

# --------------------------------------------------------------------------- #

if ($PSVersionTable.Platform -and $PSVersionTable.Platform -ne 'Win32NT') {
    throw 'This installer is for Windows. On macOS see the README.'
}
if (-not (Get-Command winget -ErrorAction SilentlyContinue)) {
    throw 'winget was not found. It ships with Windows 11 and recent Windows 10; update App Installer from the Microsoft Store.'
}

Write-Host 'Journeys in Middle-earth — narrator' -ForegroundColor White
Write-Host 'installing to ' -NoNewline; Write-Host $Path -ForegroundColor White

Write-Step 'Tools'
Install-IfMissing -Id 'Python.Python.3.13'  -Command 'py'     -Label 'Python 3.13'
Install-IfMissing -Id 'Git.Git'             -Command 'git'    -Label 'Git'
Install-IfMissing -Id 'Gyan.FFmpeg'         -Command 'ffmpeg' -Label 'ffmpeg'

# No command to test for: it is a runtime, not a program. onnxruntime will not
# load without it, and the failure names neither itself nor what is missing.
Write-Ok 'ensuring Visual C++ Redistributable ...'
winget install --id 'Microsoft.VCRedist.2015+.x64' -e `
    --accept-source-agreements --accept-package-agreements --disable-interactivity |
    Out-Null
Update-Path

Write-Step 'Project'
if (Test-Path (Join-Path $Path '.git')) {
    Write-Ok 'already cloned, updating'
    git -C $Path pull --ff-only
} else {
    if (Test-Path $Path) {
        throw "$Path exists but is not a git clone. Move it aside or pass -Path somewhere else."
    }
    git clone $repo $Path
}

Write-Step 'Environment'
if (-not (Test-Path (Join-Path $Venv 'Scripts\python.exe'))) {
    py -3.13 -m venv $Venv
    Write-Ok "created $Venv"
} else {
    Write-Ok 'already exists'
}

$python = Join-Path $Venv 'Scripts\python.exe'
& $python -m pip install --quiet --upgrade pip
# ${Path} not $Path: inside double quotes PowerShell reads $Path[...] as an
# index into the string, so the extras would never reach pip.
& $python -m pip install --quiet -e "${Path}[tts,ocr,capture]"
if ($LASTEXITCODE -ne 0) { throw 'the install failed — the output above says why' }
Write-Ok 'dependencies installed'

# The one thing this installer cannot install.
#
# `Add-WindowsCapability` needs elevation and this does not run elevated, so the
# recogniser has to be a sentence rather than a step. It is worth the sentence:
# without it the narrator still works, reads the screen with whatever recogniser
# Windows does have — English, on most images — and drops every accent on the way
# to the voice. Nothing looks wrong; a hero's name is just said wrong.
#
# Asked through the project's own venv rather than through Get-WindowsCapability,
# which needs elevation to answer. This is the same API the narrator uses, so it
# reports what will actually happen and not what ought to.
Write-Step 'Screen reading'
$tags = & $python -c "from winrt.windows.media.ocr import OcrEngine; print(','.join(x.language_tag for x in OcrEngine.available_recognizer_languages))" 2>$null
if ($LASTEXITCODE -eq 0 -and $tags) {
    Write-Ok "Windows can read the screen in: $tags"
    Write-Host @"
    If you play the game in a language that is not in that list, Windows needs
    its recogniser too. In an elevated PowerShell, with your language in place
    of pt-BR:

        Add-WindowsCapability -Online -Name "Language.OCR~~~pt-BR~0.0.1.0"

    Without it the narrator reads the screen in another language and drops the
    accents. It still plays; names just come out wrong.

    This lists all 35 recognisers Windows can install:

        Get-WindowsCapability -Online -Name "Language.OCR*"
"@ -ForegroundColor DarkGray
} else {
    Write-Ok 'could not ask Windows which languages it can read — the check below will say'
}

if (-not $SkipSelfTest) {
    Write-Step 'Checking'
    Push-Location $Path
    try { & $python selftest.py } finally { Pop-Location }
}

Write-Host "`nReady. Start it with:" -ForegroundColor Green
Write-Host "    cd $Path"
Write-Host "    & $python jime.py"
Write-Host @"

The first time, in this order: extract the corpus, render the audio, then
narrate. The menu asks; there are no flags to remember.
"@ -ForegroundColor DarkGray
